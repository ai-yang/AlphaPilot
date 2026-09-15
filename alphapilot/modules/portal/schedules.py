"""Trusted local scheduler facade; the durable TaskRuntime owns all dispatch."""
from __future__ import annotations
import os
from pathlib import Path
from alphapilot.research.auth import Actor
from alphapilot.research.models import ScheduleCreate
from alphapilot.research.schedules import ScheduleService
from alphapilot.research.tasks import TaskService
from alphapilot.research.store import Store

SCHEDULE_KINDS = ("data", "mine", "mine_aff", "mine_gp", "mine_rl", "factor_backtest", "strategy_backtest", "daily_signals", "report_factor_extract")

def default_schedule_root():
    return Path(os.getenv("ALPHAPILOT_PORTAL_SCHEDULE_ROOT", str(Path.cwd() / "git_ignore_folder" / "portal_schedules"))).expanduser()

def _service():
    return ScheduleService(TaskService())

def list_schedules(**_):
    return _service().all(Actor.local())

def get_schedule(schedule_id, **_):
    from alphapilot.research.common import ResearchError
    row = next((r for r in list_schedules() if r["schedule_id"] == schedule_id), None)
    if row is None:
        raise ResearchError("NOT_FOUND", "Schedule not found", 404)
    return row

def create_schedule(name, kind, time, kwargs=None, enabled=True, **_):
    from alphapilot.research.channels import command_spec
    service, actor = _service(), Actor.local()
    job = command_spec(kind, kwargs or {}, service.tasks, actor)
    return service.save(ScheduleCreate(name=name, time=time, enabled=enabled, job=job), actor)

def update_schedule(schedule_id, **changes):
    row = get_schedule(schedule_id)
    value = {k: row[k] for k in ("name", "time", "timezone", "enabled", "job")}
    value.update({k: v for k, v in changes.items() if k in value})
    return _service().save(ScheduleCreate.model_validate(value), Actor.local(), key=schedule_id, expected=row["revision"])

def set_enabled(schedule_id, enabled, **_):
    return update_schedule(schedule_id, enabled=enabled)

def delete_schedule(schedule_id, **_):
    return _service().delete(schedule_id, Actor.local(), get_schedule(schedule_id)["revision"])

def run_now(schedule_id, **_):
    import uuid
    return _service().run(schedule_id, Actor.local(), uuid.uuid4().hex)

trigger_schedule = run_now

def run_due(*, now=None, **_):
    return _service().run_due(now)

def daemon_status(**_):
    from alphapilot.research.runtime import status
    store = Store()
    return {**status(store), "paused": store.setting("schedules_paused", False)}

def start_daemon(**_):
    from alphapilot.research.runtime import ensure_running
    store = Store()
    store.set_setting("schedules_paused", False)
    return ensure_running(store)

def stop_daemon(**_):
    Store().set_setting("schedules_paused", True)
    return daemon_status()

def run_scheduler_loop(**_):
    from alphapilot.research.runtime import main
    main([])

if __name__ == "__main__":
    run_scheduler_loop()
