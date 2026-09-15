"""One workspace daemon dispatches persistent jobs into isolated worker processes."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import signal
import subprocess
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from .common import TERMINAL, ResearchError, atomic_json, encode, now
from .execution import ExecutionHandle, ResourceLockService, alive, identity
from .store import Store


def status(store: Store) -> dict:
    lock = FileLock(str(store.root / "runtime.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        running = True
    else:
        running = False
        lock.release()
    heartbeat = store.setting("runtime", {})
    return {"running": running, "heartbeat_at": heartbeat.get("heartbeat_at"),
            "draining": store.setting("drain", False), "start_error": store.setting("runtime_start_error")}


def ensure_running(store: Store) -> dict:
    store.require_migrated()
    if status(store)["running"]:
        return status(store)
    if store.setting("drain", False):
        return status(store)
    # Concurrent launchers are harmless: only the child holding runtime.lock
    # may dispatch. Do not trust stale PID files or heartbeat ages for ownership.
    with (store.root / "runtime.log").open("ab") as log:
        subprocess.Popen([sys.executable, "-m", "alphapilot.research.runtime", "--root", str(store.root)],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
                         cwd=str(Path.cwd()), close_fds=True)
    return status(store)


class TaskRuntime:
    def __init__(self, store: Store, *, launcher=None):
        self.store = store
        self.launcher = launcher or self._launch
        self.children: list = []
        self._schedules = None

    def _launch(self, job_id: str, attempt: str):
        with (self.store.root / job_id / "run.log").open("ab") as log:
            process = subprocess.Popen([sys.executable, "-m", "alphapilot.research.runtime",
                                        "--root", str(self.store.root), "--worker", job_id, "--attempt", attempt],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True, close_fds=True)
        self.children.append(process)
        return process

    def claim(self) -> tuple[str, str] | None:
        with self.store.connect(write=True) as db:
            capacity = max(1, int(os.getenv("ALPHAPILOT_RESEARCH_MAX_RUNNING", "1")))
            active = db.execute("SELECT count(*) FROM jobs WHERE status IN ('starting','running','cancelling')").fetchone()[0]
            if active >= capacity:
                return None
            row = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created,id LIMIT 1").fetchone()
            if not row:
                return None
            execution = json.loads(row["execution"])
            attempt = uuid.uuid4().hex
            if not ResourceLockService.acquire_in(db, attempt, execution["resources"]):
                return None
            payload = json.loads(row["payload"])
            payload.update(status="starting", progress={"percent": None, "stage": "starting"})
            db.execute("INSERT INTO executions(id,job_id,attempt,created,resources) VALUES (?,?,?,?,?)",
                       (attempt, row["id"], attempt, now(), encode(execution["resources"])))
            db.execute("UPDATE jobs SET status='starting',attempt=?,payload=? WHERE id=? AND status='queued'",
                       (attempt, encode(payload), row["id"]))
            return row["id"], attempt

    def tick(self) -> None:
        self.children = [p for p in self.children if p.poll() is None]
        self.reconcile()
        if self.store.setting("drain", False):
            return
        with self.store.connect() as db:
            has_schedules = db.execute("SELECT 1 FROM schedules LIMIT 1").fetchone()
        if has_schedules:
            if self._schedules is None:
                from .schedules import ScheduleService
                from .tasks import TaskService
                self._schedules = ScheduleService(TaskService(self.store, autostart=False))
            self._schedules.run_due()
        while claim := self.claim():
            job_id, attempt = claim
            try:
                process = self.launcher(job_id, attempt)
                saved = identity(process.pid)
                with self.store.connect(write=True) as db:
                    # The worker may have registered first. Never overwrite its identity.
                    db.execute("UPDATE executions SET identity=? WHERE id=? AND identity IS NULL", (encode(saved), attempt))
            except Exception as exc:
                self._request_stop(job_id, attempt, "failed", ResearchError("WORKER_START_FAILED", str(exc), 503, retryable=True))

    def _request_stop(self, job_id: str, attempt: str, final: str, error: ResearchError) -> None:
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["attempt"] != attempt or row["status"] in TERMINAL:
                return
            payload, execution = json.loads(row["payload"]), json.loads(row["execution"])
            if row["status"] != "cancelling":
                execution["stop_final"] = final
            payload.update(status="cancelling", error=error.payload(),
                           progress={"percent": None, "stage": "cancelling", "message": str(error)})
            db.execute("UPDATE jobs SET status='cancelling',payload=?,execution=? WHERE id=?",
                       (encode(payload), encode(execution), job_id))

    def reconcile(self) -> None:
        with self.store.connect() as db:
            rows = db.execute("SELECT j.*,e.identity,e.created AS attempt_created FROM jobs j JOIN executions e ON e.id=j.attempt "
                              "WHERE j.status IN ('starting','running','cancelling')").fetchall()
        for row in rows:
            saved = json.loads(row["identity"]) if row["identity"] else None
            payload, execution = json.loads(row["payload"]), json.loads(row["execution"])
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(row["attempt_created"])).total_seconds()
            if row["status"] == "starting":
                if age < 30:
                    continue
                # Invalidate before cleanup; a late worker's CAS must fail. A
                # registered worker would already have changed status to running.
                with self.store.connect(write=True) as db:
                    current = db.execute("SELECT status,attempt FROM jobs WHERE id=?", (row["id"],)).fetchone()
                    if current["status"] != "starting" or current["attempt"] != row["attempt"]:
                        continue
                    payload.update(status="cancelling", progress={"percent": None, "stage": "cancelling"})
                    execution["stop_final"] = "queued"
                    db.execute("UPDATE jobs SET status='cancelling',payload=?,execution=? WHERE id=?",
                               (encode(payload), encode(execution), row["id"]))
                continue
            if row["status"] == "running" and alive(saved):
                started = datetime.fromisoformat(payload["started_at"])
                if (datetime.now(timezone.utc) - started).total_seconds() > payload["budget"]["timeout_seconds"]:
                    self._request_stop(row["id"], row["attempt"], "failed", ResearchError("TIMEOUT", "Task execution budget exceeded", 408))
                continue
            handle = ExecutionHandle(self.store, row["attempt"])
            if not handle.stop():
                self._request_stop(row["id"], row["attempt"], "lost", ResearchError(
                    "EXECUTION_UNCONFIRMED", "Waiting for process/container cleanup before releasing resources", 503, retryable=True))
                continue
            if row["status"] == "cancelling":
                final = execution.get("stop_final", "cancelled")
                completion = None
            else:
                completion = execution.get("completion")
                final = completion["status"] if completion else "lost"
            self.finalize(row["id"], row["attempt"], final, completion)
        # Foreground CLI executions use the same registry and may leave locks on
        # process death. Never unlock on heartbeat expiry alone.
        with self.store.connect() as db:
            standalone = db.execute("SELECT * FROM executions WHERE job_id IS NULL AND finished=0").fetchall()
        for row in standalone:
            saved = json.loads(row["identity"]) if row["identity"] else None
            pending = self.store.setting("cleanup:" + row["id"], False)
            if (pending or not alive(saved)) and ExecutionHandle(self.store, row["id"]).stop(stop_process=not pending):
                ResourceLockService(self.store).release(row["id"])

    def finalize(self, job_id: str, attempt: str, final: str, completion: dict | None) -> bool:
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row or row["attempt"] != attempt or row["status"] in TERMINAL:
                return False
            payload, execution = json.loads(row["payload"]), json.loads(row["execution"])
            if row["status"] == "cancelling" and final not in {"cancelled", "queued", "lost", "failed"}:
                return False
            if row["status"] == "cancelling":
                final = execution.get("stop_final", "cancelled")
                completion = None
            if completion:
                staged = self.store.root / job_id / f"result.{attempt}.json"
                if completion["status"] == "succeeded" and not staged.is_file():
                    final = "failed"
                    completion = {"error": ResearchError("RESULT_MISSING", "Worker completion has no immutable result", 500).payload(), "summary": None}
                elif staged.is_file():
                    # File contents are immutable; publish the reference and terminal
                    # state in one SQLite transaction. A crash/cancel cannot expose a
                    # renamed result whose database transaction never committed.
                    execution["published_result"] = staged.name
                payload["error"] = completion.get("error")
                payload["result_summary"] = completion.get("summary")
            elif final == "lost":
                payload["error"] = ResearchError("WORKER_LOST", "Worker exited without a committed completion", 500).payload()
            payload.update(status=final, finished_at=now() if final != "queued" else None,
                           progress={"percent": 100 if final == "succeeded" else None, "stage": final})
            execution.pop("completion", None)
            execution.pop("stop_final", None)
            db.execute("UPDATE jobs SET status=?,payload=?,execution=?,attempt=? WHERE id=?",
                       (final, encode(payload), encode(execution), None if final == "queued" else attempt, job_id))
            db.execute("DELETE FROM locks WHERE owner=?", (attempt,))
            db.execute("DELETE FROM lock_scopes WHERE owner=?", (attempt,))
            db.execute("UPDATE executions SET finished=1 WHERE id=?", (attempt,))
            if final != "queued":
                db.execute("INSERT OR IGNORE INTO notifications VALUES (?,?,0)", (job_id, final))
                runs = db.execute("SELECT id,path,payload FROM runs WHERE job_id=? AND attempt=?", (job_id, attempt)).fetchall()
                for run in runs:
                    manifest = json.loads(run["payload"])
                    manifest["job_status"] = final
                    if manifest.get("status") == "completed":
                        manifest["status"] = "succeeded"
                    elif manifest.get("status") not in TERMINAL:
                        manifest.update(status=final, finished_at=payload["finished_at"])
                    atomic_json(Path(run["path"]) / "manifest.json", manifest)
                    db.execute("UPDATE runs SET payload=? WHERE id=?", (encode(manifest), run["id"]))
        atomic_json(self.store.root / job_id / "job.json", payload)
        return True

    def deliver_notifications(self) -> None:
        with self.store.connect(write=True) as db:
            rows = db.execute("SELECT n.*,j.execution,j.payload FROM notifications n JOIN jobs j ON j.id=n.job_id WHERE n.sent=0").fetchall()
            # Best-effort at-most-once delivery, matching the existing notifier.
            db.executemany("UPDATE notifications SET sent=1 WHERE job_id=?", [(r["job_id"],) for r in rows])
        from alphapilot.modules.portal.jobs import _maybe_notify
        for row in rows:
            execution, payload = json.loads(row["execution"]), json.loads(row["payload"])
            _maybe_notify(self.store.root / row["job_id"], payload["kind"], execution["input"],
                          execution.get("notify"), row["status"], payload.get("result_summary"),
                          RuntimeError(payload["error"]["message"]) if payload.get("error") else None)


def worker(store: Store, job_id: str, attempt: str) -> bool:
    os.environ.update(ALPHAPILOT_PORTAL_JOB_ROOT=str(store.root), ALPHAPILOT_PORTAL_JOB_ID=job_id,
                      ALPHAPILOT_PORTAL_JOB_DIR=str(store.root / job_id), ALPHAPILOT_JOB_ATTEMPT=attempt,
                      ALPHAPILOT_EXECUTION_ID=attempt)
    with store.connect(write=True) as db:
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["attempt"] != attempt or row["status"] != "starting":
            return False
        payload = json.loads(row["payload"])
        payload.update(status="running", started_at=now(), progress={"percent": None, "stage": "running"})
        db.execute("UPDATE executions SET identity=? WHERE id=?", (encode(identity()), attempt))
        db.execute("UPDATE jobs SET status='running',payload=? WHERE id=?", (encode(payload), job_id))
        execution = json.loads(row["execution"])
    try:
        from alphapilot.modules.portal.env_config import apply_portal_env
        apply_portal_env()
        from .executor import execute
        result = execute(execution)
        atomic_json(store.root / job_id / f"result.{attempt}.json", result)
        completion = {"status": "succeeded", "error": None, "summary": "Completed"}
    except BaseException as exc:
        traceback.print_exc()
        error = exc if isinstance(exc, ResearchError) else ResearchError("EXECUTION_FAILED", f"{type(exc).__name__}: {exc}", 500)
        completion = {"status": "failed", "error": error.payload(), "summary": None}
    with store.connect(write=True) as db:
        current = db.execute("SELECT status,attempt,execution FROM jobs WHERE id=?", (job_id,)).fetchone()
        if current["status"] != "running" or current["attempt"] != attempt:
            return False
        execution = json.loads(current["execution"])
        execution["completion"] = completion
        db.execute("UPDATE jobs SET execution=? WHERE id=?", (encode(execution), job_id))
    # The daemon publishes completion only after this worker and its executions exit.
    return True


def progress(percent=None, stage="running", message=None, **extra) -> None:
    job_id, attempt = os.getenv("ALPHAPILOT_PORTAL_JOB_ID"), os.getenv("ALPHAPILOT_JOB_ATTEMPT")
    if not job_id or not attempt:
        return
    store = Store()
    with store.connect(write=True) as db:
        row = db.execute("SELECT status,attempt,payload FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "running" or row["attempt"] != attempt:
            return
        payload = json.loads(row["payload"])
        payload["progress"] = {"percent": max(0, min(99, float(percent))) if percent is not None else None,
                               "stage": str(stage), "message": message, "updated_at": now(),
                               **{k: int(v) for k, v in extra.items() if k in {"total", "completed"} and v is not None}}
        db.execute("UPDATE jobs SET payload=? WHERE id=?", (encode(payload), job_id))


def main(argv=None) -> None:
    from .common import root_path
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(root_path()))
    parser.add_argument("--worker")
    parser.add_argument("--attempt")
    args = parser.parse_args(argv)
    os.environ["ALPHAPILOT_PORTAL_JOB_ROOT"] = args.root
    store = Store(args.root)
    if args.worker:
        worker(store, args.worker, args.attempt)
        return
    store.require_migrated()
    lock = FileLock(str(store.root / "runtime.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        return
    runtime = TaskRuntime(store)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while not stopping:
            store.set_setting("runtime", {"identity": identity(), "heartbeat_at": now()})
            store.set_setting("runtime_start_error", None)
            try:
                runtime.tick()
                runtime.deliver_notifications()
            except Exception:
                traceback.print_exc()
            if store.setting("drain", False):
                with store.connect() as db:
                    active = db.execute("SELECT 1 FROM jobs WHERE status IN ('starting','running','cancelling') LIMIT 1").fetchone()
                if not active:
                    break
            time.sleep(1)
    finally:
        lock.release()


if __name__ == "__main__":
    main()
