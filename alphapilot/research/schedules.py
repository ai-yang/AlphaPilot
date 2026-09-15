"""Typed schedules submit into the same durable queue with occurrence idempotency."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .assets import AssetService
from .auth import Actor, AuthService
from .common import ResearchError, encode, now, opaque
from .models import ScheduleCreate
from .store import Store
from .tasks import TaskService, required_scopes, page


class ScheduleService:
    def __init__(self, tasks: TaskService):
        self.tasks, self.store = tasks, tasks.store

    def all(self, actor: Actor) -> list[dict]:
        actor.require("research:read")
        with self.store.connect() as db:
            rows = db.execute("SELECT payload,revision FROM schedules ORDER BY id").fetchall()
        return [{k: v for k, v in {**json.loads(r[0]), "revision": r[1]}.items() if k != "actor"} for r in rows]

    def save(self, request: ScheduleCreate, actor: Actor, *, key: str | None = None, expected=None,
             require_existing: bool = False) -> dict:
        actor.require("schedules:write", *required_scopes(request.job))
        try:
            ZoneInfo(request.timezone)
        except (KeyError, ValueError):
            raise ResearchError("INVALID_TIMEZONE", "Unknown IANA timezone", 422) from None
        key = opaque(key) if key else uuid.uuid4().hex
        payload = {**request.model_dump(mode="json"), "schedule_id": key, "actor": actor.to_dict(),
                   "created_at": now(), "last_run_date": None, "last_job_id": None,
                   "last_error": None, "retry_at": None}
        with self.store.connect(write=True) as db:
            old = db.execute("SELECT * FROM schedules WHERE id=?", (key,)).fetchone()
            if require_existing and not old:
                raise ResearchError("NOT_FOUND", "Schedule not found", 404)
            if old:
                AssetService.check_version({"revision": old["revision"]}, expected)
                previous = json.loads(old["payload"])
                for field in ("created_at", "last_run_date", "last_job_id"):
                    payload[field] = previous.get(field)
            revision = old["revision"] + 1 if old else 1
            db.execute("INSERT OR REPLACE INTO schedules VALUES (?,?,?)", (key, encode(payload), revision))
        AuthService(self.store).audit(actor, "schedule.save", {"schedule_id": key, "revision": revision})
        return {k: v for k, v in {**payload, "revision": revision}.items() if k != "actor"}

    def delete(self, key: str, actor: Actor, expected) -> dict:
        actor.require("research:read", "schedules:write")
        with self.store.connect(write=True) as db:
            row = db.execute("SELECT revision FROM schedules WHERE id=?", (opaque(key),)).fetchone()
            if not row:
                raise ResearchError("NOT_FOUND", "Schedule not found", 404)
            AssetService.check_version({"revision": row[0]}, expected)
            db.execute("DELETE FROM schedules WHERE id=?", (key,))
        return {"schedule_id": key, "deleted": True}

    def run(self, key: str, actor: Actor, idem: str) -> dict:
        actor.require("schedules:write")
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM schedules WHERE id=?", (opaque(key),)).fetchone()
        if not row:
            raise ResearchError("NOT_FOUND", "Schedule not found", 404)
        return self.tasks.submit(json.loads(row[0])["job"], actor, idem)

    def run_due(self, instant: datetime | None = None) -> list[dict]:
        if self.store.setting("schedules_paused", False):
            return []
        instant = instant or datetime.now(timezone.utc)
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM schedules").fetchall()
        outcomes = []
        for row in rows:
            data = json.loads(row["payload"])
            local = instant.astimezone(ZoneInfo(data["timezone"]))
            day = local.date().isoformat()
            if not data["enabled"] or data.get("last_run_date") == day or local.strftime("%H:%M") < data["time"]:
                continue
            if data.get("retry_at") and instant.timestamp() < data["retry_at"]:
                continue
            try:
                actor = AuthService(self.store).restore(data["actor"])
                actor.require("schedules:write")
                request = data["job"]
                if request["kind"] == "daily_signals":
                    request = json.loads(encode(request))
                    request["input"]["date"] = day
                job = self.tasks.submit(request, actor, f"schedule:{row['id']}:{day}:{data['time']}")
                data.update(last_run_date=day, last_job_id=job["job_id"], last_error=None, retry_at=None)
                outcomes.append({"schedule_id": row["id"], "job_id": job["job_id"]})
            except Exception as exc:
                data.update(last_error=str(exc), retry_at=instant.timestamp() + 60)
                outcomes.append({"schedule_id": row["id"], "error": str(exc)})
            with self.store.connect(write=True) as db:
                # Do not overwrite a concurrent GUI edit with stale scheduler data.
                db.execute("UPDATE schedules SET payload=? WHERE id=? AND revision=?", (encode(data), row["id"], row["revision"]))
        return outcomes
