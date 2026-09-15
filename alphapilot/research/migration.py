"""Explicit, offline migration of historical jobs/runs/schedules."""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import uuid
from pathlib import Path

import psutil

from .auth import Actor
from .common import TERMINAL, ResearchError, atomic_json, digest, encode, now
from .store import Store


def require_legacy_scheduler_stopped() -> None:
    from alphapilot.modules.portal.schedules import default_schedule_root
    path = default_schedule_root() / "scheduler.pid.json"
    if path.is_file():
        record = json.loads(path.read_text())
        if record.get("pid") and psutil.pid_exists(int(record["pid"])):
            raise ResearchError("LEGACY_SCHEDULER_ACTIVE", "Stop the old scheduler before starting the research runtime or migrating", 409)


def migrate(store: Store, engine, *, execute: bool = False) -> dict:
    from filelock import FileLock, Timeout
    lock = FileLock(str(store.root / "runtime.lock"))
    try:
        lock.acquire(timeout=0)
    except Timeout:
        raise ResearchError("RUNTIME_ACTIVE", "Drain and stop TaskRuntime before migration", 409) from None
    try:
        return _migrate(store, engine, execute=execute)
    finally:
        lock.release()


def _migrate(store: Store, engine, *, execute: bool) -> dict:
    from alphapilot.systems.run_workspace import runs_root
    from alphapilot.modules.portal.schedules import default_schedule_root
    require_legacy_scheduler_stopped()
    jobs = sorted(store.root.glob("*/job.json"))
    with store.connect() as db:
        known = {r[0] for r in db.execute("SELECT id FROM jobs")}
    jobs = [p for p in jobs if p.parent.name not in known]
    for path in jobs:
        job = json.loads(path.read_text())
        if job.get("status") not in TERMINAL and job.get("pid") and psutil.pid_exists(int(job["pid"])):
            raise ResearchError("LEGACY_WORKER_ACTIVE", "Wait for or stop old workers before migrating", 409,
                                details={"job_id": path.parent.name})
    run_manifests = sorted(runs_root().glob("*/manifest.json"))
    from alphapilot.core.workspace import resolve_workspace_root
    flat_root = Path(os.getenv("ALPHAPILOT_WORKSPACE_ROOT") or resolve_workspace_root())
    flat_workspaces = sorted(flat_root.glob("*/ret.pkl"))
    from alphapilot.log.ui.session import filter_log_folders
    log_root = getattr(getattr(engine, "config", None), "log_dir", None)
    log_sessions = filter_log_folders(Path(log_root)) if log_root else []
    schedules = sorted(default_schedule_root().glob("*.json"))
    schedules = [p for p in schedules if p.name != "scheduler.pid.json"]
    report = {"jobs": len(jobs), "runs": len(run_manifests), "flat_backtests": len(flat_workspaces),
              "mining_sessions": len(log_sessions), "schedules": len(schedules),
              "executed": execute, "manual_schedules": []}
    if not execute:
        return report
    backup = store.root / "migration_backups" / uuid.uuid4().hex
    backup.mkdir(parents=True)
    with store.connect() as source:
        import sqlite3
        with sqlite3.connect(backup / "tasks.sqlite3") as target:
            source.backup(target)
    from .artifacts import public_value, ArtifactService
    store.set_setting("migration_pending", True)
    for path in jobs:
        old = json.loads(path.read_text())
        key = path.parent.name
        shutil.copytree(path.parent, backup / "jobs" / key)
        state = old.get("status") if old.get("status") in TERMINAL else "lost"
        error = old.get("error")
        if state == "lost":
            error = "Historical worker could not be recovered; task was not restarted"
        payload = {"job_id": key, "kind": old.get("kind", "legacy"), "status": state,
                   "created_at": old.get("created_at") or now(), "started_at": old.get("started_at"),
                   "finished_at": old.get("finished_at") or now(), "normalized_input": public_value(old.get("params", {})),
                   "budget": {"timeout_seconds": 3600}, "progress": {"percent": 100 if state == "succeeded" else None, "stage": state},
                   "run_ids": [], "artifact_ids": [], "result_summary": old.get("result_summary"),
                   "error": ResearchError("LEGACY_EXECUTION", str(error)).payload() if error else None,
                   "source": "migration", "client_id": "local-owner"}
        execution = {"kind": payload["kind"], "input": payload["normalized_input"], "resources": [], "legacy": True,
                     "actor": Actor.local("migration").to_dict(), "notify": False}
        result = path.parent / "result.json"
        if result.exists():
            content = json.loads(result.read_text())
            atomic_json(path.parent / "result.migration.json", public_value(content.get("result", content)))
            execution["published_result"] = "result.migration.json"
        with store.connect(write=True) as db:
            db.execute("INSERT OR IGNORE INTO jobs VALUES (?,?,?,?,?,?,?,?,NULL)",
                       (key, state, payload["created_at"], "local-owner", "legacy:" + key,
                        digest(payload), encode(payload), encode(execution)))
    service = ArtifactService(store)

    def emit_for(run_id, job_id=None):
        def emit(value, kind, path=None):
            if path:
                with Path(path).open("rb") as stream:
                    hasher = hashlib.sha256()
                    while chunk := stream.read(1024 * 1024):
                        hasher.update(chunk)
                    checksum = hasher.hexdigest()
            else:
                checksum = hashlib.sha256(encode(value).encode()).hexdigest()
            # A crash after the artifact commit is safe to retry. Reuse the
            # immutable publication rather than appending duplicate artifacts.
            with store.connect() as db:
                for row in db.execute("SELECT payload FROM artifacts WHERE run_id=? AND published=1", (run_id,)):
                    artifact = json.loads(row[0])
                    if artifact["kind"] == kind and artifact["sha256"] == checksum:
                        return artifact
            kwargs = {"kind": kind, "run_id": run_id, "job_id": job_id}
            return service.register(Path(path), **kwargs) if path else service.register_json(value, **kwargs)
        return emit

    def complete(run_id):
        with store.connect(write=True) as db:
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
            value = json.loads(row[0])
            value["migration_artifacts"] = "complete"
            db.execute("UPDATE runs SET payload=? WHERE id=?", (encode(value), run_id))

    for path in run_manifests:
        payload = json.loads(path.read_text())
        key = path.parent.name
        shutil.copytree(path.parent, backup / "runs" / key, symlinks=True)
        with store.connect(write=True) as db:
            existing = db.execute("SELECT payload FROM runs WHERE id=?", (key,)).fetchone()
            if existing and json.loads(existing[0]).get("migration_artifacts") != "pending":
                continue
            job_id = payload.get("job_id")
            if not job_id or not db.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
                job_id = None
            payload.update(job_id=job_id, association="known" if job_id else "unknown", migration_artifacts="pending")
            if payload.get("status") == "running":
                payload["status"] = "lost"
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)", (key, job_id, None, str(path.parent.resolve()), encode(payload)))
        emit = emit_for(key, job_id)
        for artifact in sorted(path.parent.glob("workspaces/*/*")):
            if artifact.is_file() and not artifact.name.startswith("research_") and artifact.suffix in {".csv", ".json", ".html", ".png", ".txt"}:
                emit(None, "legacy_" + artifact.suffix.lstrip("."), path=artifact)
        from .artifacts import publish_backtest
        for result_file in sorted(path.parent.glob("workspaces/*/ret.pkl")):
            evaluation_id = key + "--" + result_file.parent.name
            with store.connect(write=True) as db:
                db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?,?)", (evaluation_id, job_id, None, str(result_file.parent),
                           encode({"command": "factor_evaluation", "status": "completed", "parent_run_id": key,
                                   "association": "known" if job_id else "unknown", "source": "migration"})))
            emit = emit_for(evaluation_id, job_id)
            try:
                publish_backtest(result_file.parent, emit)
            except Exception as exc:
                # Keep the historical run queryable even if an old pickle can
                # no longer be read by today's Qlib/pandas installation.
                emit({"code": "LEGACY_ARTIFACT_UNAVAILABLE", "message": str(exc)}, "migration_error")
        complete(key)
    # Old flat workspaces and independent log sessions have no trustworthy job
    # relation. Stable source IDs preserve them without guessing by timestamps.
    from .artifacts import publish_backtest, publish_logs
    for source, command in ([(p.parent, "legacy_backtest") for p in flat_workspaces]
                            + [(p, "legacy_mine") for p in log_sessions]):
        key = command + "-" + digest(str(source.resolve()))[:24]
        with store.connect() as db:
            existing = db.execute("SELECT payload FROM runs WHERE id=?", (key,)).fetchone()
            if existing and json.loads(existing[0]).get("migration_artifacts") != "pending":
                continue
        shutil.copytree(source, backup / command / key, symlinks=True)
        payload = {"command": command, "status": "completed", "association": "unknown", "source_name": source.name,
                   "migration_artifacts": "pending"}
        if command == "legacy_mine":
            payload["session_path"] = str(source.resolve())
        with store.connect(write=True) as db:
            db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?)", (key, None, None, str(source.resolve()), encode(payload)))
        emit = emit_for(key)
        try:
            publish_backtest(source, emit) if command == "legacy_backtest" else publish_logs(source, emit)
        except Exception as exc:
            emit({"code": "LEGACY_ARTIFACT_UNAVAILABLE", "message": str(exc)}, "migration_error")
        complete(key)
    from .channels import command_spec
    from .models import ScheduleCreate
    from .schedules import ScheduleService
    from .tasks import TaskService
    tasks = TaskService(store, engine, autostart=False)
    for path in schedules:
        shutil.copy2(path, backup / ("schedule-" + path.name))
        old = json.loads(path.read_text())
        key = old.get("schedule_id", path.stem)
        with store.connect() as db:
            if db.execute("SELECT 1 FROM schedules WHERE id=?", (key,)).fetchone():
                path.unlink()
                continue
        try:
            request = command_spec(old["kind"], old.get("kwargs", {}), tasks, Actor.local("migration"))
            schedule = ScheduleCreate(name=old["name"], time=old["time"], enabled=old.get("enabled", True), job=request)
            ScheduleService(tasks).save(schedule, Actor.local("migration"), key=key)
        except Exception as exc:
            # Preserve a visible disabled record and the exact original in backup.
            report["manual_schedules"].append({"schedule_id": key, "reason": str(exc)})
            disabled = {"schedule_id": key, "name": old.get("name", key), "enabled": False,
                        "time": old.get("time", "00:00"), "timezone": "Asia/Shanghai", "job": None,
                        "migration_error": str(exc), "actor": Actor.local("migration").to_dict()}
            with store.connect(write=True) as db:
                db.execute("INSERT INTO schedules VALUES (?,?,1)", (key, encode(disabled)))
        path.unlink()
    report["backup"] = str(backup)
    store.set_setting("migration_pending", False)
    return report
