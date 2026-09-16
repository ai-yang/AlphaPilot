"""Durable task admission and queries; no HTTP or MCP dependency."""
from __future__ import annotations

import base64
import codecs
import json
import os
import shutil
import uuid
from pathlib import Path

from .auth import Actor, AuthService
from .common import ACTIVE, TERMINAL, ResearchError, atomic_json, digest, encode, now, opaque
from .models import JOB_ADAPTER
from .store import Store


def page(items: list, cursor: str | None = None, limit: int = 50) -> dict:
    if not 1 <= limit <= 200:
        raise ResearchError("INVALID_PAGE", "limit must be between 1 and 200", 422)
    try:
        offset = int(base64.urlsafe_b64decode(cursor).decode()) if cursor else 0
        if offset < 0:
            raise ValueError()
    except (ValueError, UnicodeError):
        raise ResearchError("INVALID_CURSOR", "Invalid pagination cursor", 422) from None
    selected = items[offset:offset + limit]
    next_offset = offset + len(selected)
    return {"items": selected, "next_cursor": base64.urlsafe_b64encode(str(next_offset).encode()).decode()
            if next_offset < len(items) else None, "total": len(items)}


def required_scopes(spec) -> set[str]:
    scopes = {"research:read", "jobs:submit"}
    kind, data = spec.kind, spec.input
    if kind == "data" or getattr(data, "refresh_data", False):
        scopes.add("data:write")
    if kind == "daily_signals" and data.mode == "advance":
        scopes.add("signals:write")
    if getattr(data, "save", False) or getattr(data, "save_factors_to_library", False) or getattr(data, "save_as", None):
        scopes.add("research:write")
    # Retests append a durable evaluation to the source strategy asset.
    if kind in {"strategy_backtest", "mine"}:
        scopes.add("research:write")
    return scopes


class TaskService:
    def __init__(self, store: Store | None = None, engine=None, *, autostart: bool | None = None):
        self.store = store or Store()
        self._engine = engine
        self.autostart = autostart if autostart is not None else os.getenv("ALPHAPILOT_RESEARCH_AUTOSTART", "1") == "1"

    @property
    def engine(self):
        if self._engine is None:
            from alphapilot.kernel import build_engine
            self._engine = build_engine(discover=True)
        return self._engine

    def submit(self, request, actor: Actor, idempotency_key: str) -> dict:
        self.store.require_migrated()
        spec = JOB_ADAPTER.validate_python(request)
        actor.require(*required_scopes(spec))
        if not idempotency_key or len(idempotency_key) > 200:
            raise ResearchError("IDEMPOTENCY_REQUIRED", "Idempotency-Key (1–200 characters) is required", 422)
        request_hash = digest(spec.model_dump(mode="json"))
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE client_id=? AND idem_key=?", (actor.client_id, idempotency_key)).fetchone()
        if row:
            return self._replay(row, request_hash)
        if spec.budget.timeout_seconds > int(os.getenv("ALPHAPILOT_RESEARCH_MAX_TIMEOUT", "86400")):
            raise ResearchError("BUDGET_EXCEEDED", "Task timeout exceeds the configured maximum", 422)
        if self.store.setting("drain", False):
            raise ResearchError("RUNTIME_DRAINING", "Task runtime is draining; start it before submitting new work", 503, retryable=True)
        job_id = uuid.uuid4().hex
        folder = self.store.root / job_id
        folder.mkdir(mode=0o700)
        try:
            from .executor import prepare
            execution, normalized = prepare(self.engine, self.store, spec, folder, actor)
            payload = {"job_id": job_id, "kind": spec.kind, "status": "queued", "created_at": now(),
                       "started_at": None, "finished_at": None, "normalized_input": normalized,
                       "budget": spec.budget.model_dump(), "progress": {"percent": None, "stage": "queued"},
                       "run_ids": [], "artifact_ids": [], "result_summary": None, "error": None,
                       "source": actor.source, "client_id": actor.client_id}
            execution["actor"] = actor.to_dict()
            execution["notify"] = spec.notify
            with self.store.connect(write=True) as db:
                row = db.execute("SELECT * FROM jobs WHERE client_id=? AND idem_key=?", (actor.client_id, idempotency_key)).fetchone()
                if row:
                    shutil.rmtree(folder)
                    return self._replay(row, request_hash)
                count = db.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0]
                if count >= max(1, int(os.getenv("ALPHAPILOT_RESEARCH_MAX_QUEUED", "100"))):
                    raise ResearchError("QUEUE_FULL", "Research task queue is full", 429, retryable=True)
                db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,NULL)",
                           (job_id, "queued", payload["created_at"], actor.client_id, idempotency_key,
                            request_hash, encode(payload), encode(execution)))
                db.execute("INSERT INTO audit(created,actor,action,request_id,details) VALUES (?,?,?,?,?)",
                           (now(), encode(actor.to_dict()), "jobs.submit", actor.request_id, encode({"job_id": job_id})))
            atomic_json(folder / "job.json", payload)
            (folder / "run.log").touch()
        except BaseException:
            with self.store.connect() as db:
                persisted = db.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not persisted:
                shutil.rmtree(folder, ignore_errors=True)
            raise
        if self.autostart:
            from .runtime import ensure_running
            # Admission has committed. A runtime startup failure must never turn a
            # durable accepted job into a failed HTTP submission/retry duplicate.
            try:
                ensure_running(self.store)
            except Exception as exc:
                self.store.set_setting("runtime_start_error", type(exc).__name__)
        return self.get(job_id, actor)

    def _replay(self, row, request_hash: str) -> dict:
        if row["request_hash"] != request_hash:
            raise ResearchError("IDEMPOTENCY_CONFLICT", "This key was used with different input", 409)
        payload = json.loads(row["payload"])
        if payload.get("_deleted"):
            raise ResearchError("GONE", "The original task has been deleted; this key cannot be reused", 410)
        return self.get(row["id"], Actor.local("idempotency"))

    def get(self, job_id: str, actor: Actor) -> dict:
        actor.require("research:read")
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (opaque(job_id),)).fetchone()
            runs = db.execute("SELECT id FROM runs WHERE job_id=? ORDER BY id", (job_id,)).fetchall()
            artifacts = db.execute("SELECT id FROM artifacts WHERE job_id=? AND published=1 ORDER BY id", (job_id,)).fetchall()
        if not row:
            raise ResearchError("NOT_FOUND", "Task not found", 404)
        payload = json.loads(row[0])
        if payload.get("_deleted"):
            raise ResearchError("GONE", "Task has been deleted", 410)
        payload["run_ids"] = [r[0] for r in runs]
        payload["artifact_ids"] = [r[0] for r in artifacts]
        return payload

    def list(self, actor: Actor, *, cursor: str | None = None, limit: int = 50, status: str | None = None) -> dict:
        actor.require("research:read")
        if not 1 <= limit <= 200 or (status and status not in ACTIVE | TERMINAL):
            raise ResearchError("INVALID_FILTER", "Invalid limit or status", 422)
        values = []
        clauses = ["json_extract(payload, '$._deleted') IS NULL"]
        if status:
            clauses.append("status=?")
            values.append(status)
        if cursor:
            try:
                stamp, key = json.loads(base64.urlsafe_b64decode(cursor))
            except Exception:
                raise ResearchError("INVALID_CURSOR", "Invalid task cursor", 422) from None
            clauses.append("(created,id)<(?,?)")
            values.extend([stamp, key])
        with self.store.connect() as db:
            rows = db.execute("SELECT id,created,payload FROM jobs WHERE " + " AND ".join(clauses) +
                              " ORDER BY created DESC,id DESC LIMIT ?", (*values, limit + 1)).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        items = [self.get(row["id"], actor) for row in rows]
        next_cursor = base64.urlsafe_b64encode(encode([rows[-1]["created"], rows[-1]["id"]]).encode()).decode() if more else None
        return {"items": items, "next_cursor": next_cursor}

    def cancel(self, job_id: str, actor: Actor) -> dict:
        actor.require("research:read", "jobs:cancel")
        self.get(job_id, actor)
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            payload = json.loads(row["payload"])
            if row["status"] in TERMINAL:
                return self.get(job_id, actor)
            status = "cancelled" if row["status"] == "queued" else "cancelling"
            payload.update(status=status, progress={"percent": None, "stage": status})
            if status == "cancelled":
                payload["finished_at"] = now()
                db.execute("INSERT OR IGNORE INTO notifications VALUES (?,?,0)", (job_id, status))
            db.execute("UPDATE jobs SET status=?,payload=? WHERE id=?", (status, encode(payload), job_id))
        AuthService(self.store).audit(actor, "jobs.cancel", {"job_id": job_id})
        return self.get(job_id, actor)

    def read_result(self, job_id: str, actor: Actor) -> dict:
        job = self.get(job_id, actor)
        with self.store.connect() as db:
            execution = json.loads(db.execute("SELECT execution FROM jobs WHERE id=?", (job_id,)).fetchone()[0])
        filename = execution.get("published_result") or ("result.json" if execution.get("legacy") else None)
        path = self.store.root / job_id / opaque(filename) if filename else None
        has_result = bool(path and path.is_file())
        result = json.loads(path.read_text()) if has_result else None
        availability = ("complete" if has_result or job["artifact_ids"] else "unavailable") if job["status"] == "succeeded" else (
            "partial" if result is not None or job["artifact_ids"] else
            "pending" if job["status"] in ACTIVE else "unavailable")
        return {"job_id": job_id, "availability": availability, "summary": result,
                "run_ids": job["run_ids"], "artifact_ids": job["artifact_ids"], "error": job["error"]}

    def logs(self, job_id: str, actor: Actor, *, cursor: int = 0, limit: int = 65536) -> dict:
        job = self.get(job_id, actor)
        if cursor < 0 or not 1 <= limit <= 65536:
            raise ResearchError("INVALID_LOG_RANGE", "Invalid log cursor or byte limit", 422)
        path = self.store.root / job_id / "run.log"
        if not path.exists():
            return {"text": "", "next_cursor": 0, "complete": job["status"] in TERMINAL}
        with path.open("rb") as stream:
            stream.seek(min(cursor, path.stat().st_size))
            # Never consume half a UTF-8 character across polling cursors. A
            # limit smaller than one character may read up to four bytes.
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            text = decoder.decode(stream.read(limit), final=False)
            if not text and decoder.getstate()[0]:
                for _ in range(3):
                    byte = stream.read(1)
                    if not byte:
                        break
                    text += decoder.decode(byte, final=False)
                    if text:
                        break
            if job["status"] in TERMINAL and stream.tell() >= path.stat().st_size:
                text += decoder.decode(b"", final=True)
            next_cursor = stream.tell() - len(decoder.getstate()[0])
        return {"text": text, "next_cursor": next_cursor,
                "complete": job["status"] in TERMINAL and next_cursor >= path.stat().st_size}

    def delete(self, job_id: str, actor: Actor) -> dict:
        actor.require("research:read", "research:write")
        self.get(job_id, actor)
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            live = db.execute("SELECT 1 FROM executions WHERE job_id=? AND finished=0", (job_id,)).fetchone()
            if row["status"] not in TERMINAL or live:
                raise ResearchError("TASK_ACTIVE", "Cancel and wait for task execution to stop before deletion", 409)
            payload = json.loads(row["payload"])
            payload["_deleted"] = now()
            db.execute("UPDATE jobs SET payload=? WHERE id=?", (encode(payload), job_id))
        # Keep the tombstone and idempotency key. Runs have their own retention.
        # Inputs can be referenced by saved strategy/factor provenance. Keep
        # immutable snapshots after hiding the job; artifact retention is separate.
        for name in ("job.json", "run.log", "result.json"):
            (self.store.root / job_id / name).unlink(missing_ok=True)
        return {"job_id": job_id, "deleted": True}
