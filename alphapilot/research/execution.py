"""Persistent execution identity and shared reader/writer resource locks."""
from __future__ import annotations

import contextlib
import json
import os
import signal
import time
import uuid
from contextvars import ContextVar
from pathlib import Path

import psutil

from .common import ResearchError, encode, now
from .store import Store

_context: ContextVar[tuple[str, str] | None] = ContextVar("research_execution", default=None)


def identity(pid: int | None = None) -> dict:
    process = psutil.Process(pid or os.getpid())
    return {"pid": process.pid, "created": process.create_time(), "boot": psutil.boot_time(),
            "group_owned": os.name == "posix" and os.getpgid(process.pid) == process.pid}


def alive(saved: dict | None) -> bool:
    if not saved or saved.get("boot") != psutil.boot_time():
        return False
    try:
        process = psutil.Process(saved["pid"])
        return process.create_time() == saved["created"] and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        # Fail closed: an inaccessible process must not free its resource locks.
        return True


def resource_path(path: str | Path) -> str:
    resolved = Path(path).expanduser().resolve()
    marker = resolved / ".research-source.json"
    if marker.is_file():
        resolved = Path(json.loads(marker.read_text())["source"]).resolve()
    return "path:" + os.path.normcase(str(resolved))


class ResourceLockService:
    def __init__(self, store: Store):
        self.store = store

    @staticmethod
    def acquire_in(db, owner: str, resources: list[dict]) -> bool:
        merged = {}
        for item in resources:
            key, mode = item["resource"], item["mode"]
            merged[key] = "write" if mode == "write" or merged.get(key) == "write" else "read"
        for key, mode in sorted(merged.items()):
            rows = db.execute("SELECT owner,mode FROM locks WHERE resource=? AND owner<>?", (key, owner)).fetchall()
            if rows and (mode == "write" or any(row["mode"] == "write" for row in rows)):
                return False
        for key, mode in sorted(merged.items()):
            row = db.execute("SELECT mode FROM locks WHERE resource=? AND owner=?", (key, owner)).fetchone()
            if row and row[0] == "write":
                mode = "write"
            db.execute("INSERT OR REPLACE INTO locks VALUES (?,?,?)", (key, owner, mode))
        return True

    def acquire(self, owner: str, resources: list[dict]) -> bool:
        with self.store.connect(write=True) as db:
            return self.acquire_in(db, owner, resources)

    def release(self, owner: str) -> None:
        with self.store.connect(write=True) as db:
            db.execute("DELETE FROM locks WHERE owner=?", (owner,))
            db.execute("DELETE FROM lock_scopes WHERE owner=?", (owner,))
            db.execute("UPDATE executions SET finished=1 WHERE id=?", (owner,))

    @contextlib.contextmanager
    def hold(self, resources: list[dict]):
        current = _context.get()
        existing = current[1] if current else os.getenv("ALPHAPILOT_EXECUTION_ID")
        owner = existing or uuid.uuid4().hex
        scope = uuid.uuid4().hex
        with self.store.connect(write=True) as db:
            db.execute("INSERT OR IGNORE INTO executions(id,identity,created,resources) VALUES (?,?,?,?)",
                       (owner, encode(identity()), now(), "[]"))
            row = db.execute("SELECT finished FROM executions WHERE id=?", (owner,)).fetchone()
            if row["finished"]:
                raise ResearchError("EXECUTION_ENDED", "Execution is no longer active", 409)
            if not self.acquire_in(db, owner, resources):
                if not existing:
                    db.execute("UPDATE executions SET finished=1 WHERE id=?", (owner,))
                raise ResearchError("RESOURCE_BUSY", "Research resource is in use", 409, retryable=True)
            db.execute("INSERT INTO lock_scopes VALUES (?,?,?)", (owner, scope, encode(resources)))
        token = _context.set((str(self.store.root), owner))
        try:
            yield owner
        finally:
            confirmed = existing or ExecutionHandle(self.store, owner).stop(stop_process=False)
            _context.reset(token)
            if not confirmed:
                # Retain locks until the daemon can confirm all managed children
                # and containers stopped. Never terminate the foreground owner.
                self.store.set_setting("cleanup:" + owner, True)
                raise ResearchError("EXECUTION_UNCONFIRMED", "Local execution cleanup is pending; resource locks are retained", 503)
            with self.store.connect(write=True) as db:
                db.execute("DELETE FROM lock_scopes WHERE owner=? AND scope=?", (owner, scope))
                remaining = json.loads(db.execute("SELECT resources FROM executions WHERE id=?", (owner,)).fetchone()[0]) if existing else []
                for row in db.execute("SELECT resources FROM lock_scopes WHERE owner=?", (owner,)):
                    remaining.extend(json.loads(row[0]))
                db.execute("DELETE FROM locks WHERE owner=?", (owner,))
                self.acquire_in(db, owner, remaining)
                if not existing:
                    db.execute("UPDATE executions SET finished=1 WHERE id=?", (owner,))


class ExecutionHandle:
    def __init__(self, store: Store, execution_id: str):
        self.store, self.id = store, execution_id

    @classmethod
    def current(cls):
        current = _context.get()
        if current:
            return cls(Store(current[0]), current[1])
        key = os.getenv("ALPHAPILOT_EXECUTION_ID")
        return cls(Store(), key) if key else None

    @property
    def labels(self) -> dict:
        from .common import digest
        with self.store.connect() as db:
            row = db.execute("SELECT job_id,attempt FROM executions WHERE id=?", (self.id,)).fetchone()
        return {"alphapilot.workspace": digest(str(self.store.root)), "alphapilot.execution": self.id,
                "alphapilot.job": row["job_id"] or "cli", "alphapilot.attempt": row["attempt"] or "cli"}

    def register_container(self, container_id: str) -> None:
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT containers FROM executions WHERE id=? AND finished=0", (self.id,)).fetchone()
            if not row:
                raise ResearchError("EXECUTION_ENDED", "Execution is no longer active", 409)
            containers = json.loads(row[0])
            if container_id not in containers:
                containers.append(container_id)
            db.execute("UPDATE executions SET containers=? WHERE id=?", (encode(containers), self.id))

    def stop(self, grace: float = 2.0, *, stop_process: bool = True) -> bool:
        """Stop only this recorded identity, its process group and labelled containers."""
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM executions WHERE id=?", (self.id,)).fetchone()
        if not row:
            return True
        saved = json.loads(row["identity"]) if row["identity"] else None
        stopped = _stop_identity(saved, grace) if stop_process else True
        with self.store.connect() as db:
            children = db.execute("SELECT identity FROM child_processes WHERE execution_id=?", (self.id,)).fetchall()
        for child in children:
            stopped = _stop_identity(json.loads(child[0]), grace) and stopped
        # A label search also discovers a crash between Docker create and DB registration.
        # Once a Docker execution is possible, daemon unavailability must block cleanup.
        if json.loads(row["containers"]) or self._docker_intent():
            try:
                import docker
                client = docker.from_env(timeout=5)
                containers = client.containers.list(all=True, filters={"label": [
                    f"alphapilot.execution={self.id}",
                    f"alphapilot.workspace={self.labels['alphapilot.workspace']}"]})
                for container in containers:
                    container.reload()
                    if container.status in {"running", "restarting", "paused"}:
                        container.stop(timeout=max(1, int(grace)))
                        container.reload()
                    if container.status in {"running", "restarting", "paused"}:
                        stopped = False
                    else:
                        container.remove()
            except Exception:
                stopped = False
        return stopped and (not stop_process or not alive(saved))

    def docker_intent(self) -> None:
        self.store.set_setting("docker:" + self.id, True)

    def _docker_intent(self) -> bool:
        return bool(self.store.setting("docker:" + self.id, False))


def managed_local_command(command: list[str], environment: dict) -> tuple[list[str], dict, bool]:
    """Fence local subprocesses before business code, including foreground CLI."""
    import sys
    handle = ExecutionHandle.current()
    if handle is None:
        return command, environment, False
    root = str(Path(__file__).resolve().parents[2])
    environment = {**environment, "ALPHAPILOT_EXECUTION_ID": handle.id,
                   "ALPHAPILOT_PORTAL_JOB_ROOT": str(handle.store.root),
                   "PYTHONPATH": root + os.pathsep + environment.get("PYTHONPATH", "")}
    return ([sys.executable, "-m", "alphapilot.research.process", "--root", str(handle.store.root),
             "--owner", handle.id, "--", *command], environment, True)


def _stop_identity(saved: dict | None, grace: float) -> bool:
    stopped = True
    # The original leader can exit before its children. POSIX reserves the
    # process-group ID while members remain; avoid touching a reused leader.
    if saved and saved.get("group_owned", True) and os.name == "posix" and saved.get("boot") == psutil.boot_time() and not alive(saved):
        try:
            reused = psutil.pid_exists(saved["pid"]) and psutil.Process(saved["pid"]).create_time() != saved["created"]
            if not reused:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(saved["pid"], signal.SIGKILL)
                for process in psutil.process_iter(["pid", "status"]):
                    try:
                        if os.getpgid(process.pid) == saved["pid"] and process.status() != psutil.STATUS_ZOMBIE:
                            stopped = False
                    except (ProcessLookupError, psutil.NoSuchProcess):
                        pass
        except (PermissionError, psutil.AccessDenied):
            stopped = False
    if saved and alive(saved):
        try:
            process = psutil.Process(saved["pid"])
            children = process.children(recursive=True)
            if os.name == "posix" and os.getpgid(process.pid) == process.pid:
                os.killpg(process.pid, signal.SIGTERM)
            else:
                for child in children:
                    with contextlib.suppress(psutil.NoSuchProcess):
                        child.terminate()
                process.terminate()
            _, remaining = psutil.wait_procs([process, *children], timeout=grace)
            for child in remaining:
                with contextlib.suppress(psutil.NoSuchProcess):
                    child.kill()
            _, remaining = psutil.wait_procs(remaining, timeout=grace)
            stopped = not remaining
        except (psutil.AccessDenied, PermissionError):
            stopped = False
        except (psutil.NoSuchProcess, ProcessLookupError):
            pass
    return stopped and not alive(saved)
