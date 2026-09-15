"""Trusted Python job facade; TaskService and TaskRuntime own all execution.

Public clients use /api/v1. These helpers preserve local callers without
maintaining a second queue, state machine or research dispatcher in Portal.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

JobKind = str
JobStatus = str


def default_job_root() -> Path:
    from alphapilot.research.common import root_path
    return root_path()


def update_current_job_progress(
    percent: int | float,
    stage: str,
    message: str | None = None,
    **extra: Any,
) -> None:
    """Publish only through the current durable execution attempt."""
    from alphapilot.research.runtime import progress
    progress(percent, stage, message, **extra)


def _maybe_notify(
    job_dir: Path,
    kind: JobKind,
    kwargs: dict[str, Any],
    notify_flag: Any,
    status: str,
    result: Any,
    error: BaseException | None,
) -> None:
    """Best-effort completion notification.

    ``notify_flag`` comes from the per-job ``notify`` control key; when it is
    unset, fall back to the global ``notify_on_all_jobs`` option. Never raises --
    a notification must not break (or fail) the job that triggered it.
    """
    try:
        from alphapilot.systems import notify as notify_pkg

        enabled = bool(notify_flag) if notify_flag is not None else notify_pkg.notify_on_all_jobs()
        if not enabled:
            return
        message = notify_pkg.build_job_message(
            kind=kind,
            job_id=job_dir.name,
            status=status,
            result=result,
            error=f"{type(error).__name__}: {error}" if error else None,
            kwargs=kwargs,
            job_dir=job_dir,
        )
        print(f"[portal-job] notify -> {notify_pkg.send(message)}")
    except Exception as exc:  # noqa: BLE001 - notification is best-effort
        print(f"[portal-job] notify skipped: {exc}")


def _service(job_root=None):
    from alphapilot.research.store import Store
    from alphapilot.research.tasks import TaskService
    return TaskService(Store(job_root))


def start_job(kind, kwargs, *, job_root=None, process_factory=None, actor=None, idempotency_key=None):
    from alphapilot.research.auth import Actor
    from alphapilot.research.channels import command_spec
    import uuid
    if process_factory is not None:
        raise ValueError("Worker factories belong to TaskRuntime")
    service = _service(job_root)
    actor = actor or Actor.local()
    return service.submit(command_spec(kind, kwargs, service, actor), actor, idempotency_key or uuid.uuid4().hex)


def list_jobs(*, job_root=None, refresh=True):
    from alphapilot.research.auth import Actor
    service, cursor, rows = _service(job_root), None, []
    while True:
        page = service.list(Actor.local(), cursor=cursor, limit=200)
        rows.extend(page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            return rows


def get_job(job_id, *, job_root=None):
    from alphapilot.research.auth import Actor
    return _service(job_root).get(job_id, Actor.local())


def read_log_tail(job_id, *, job_root=None, max_chars=12000):
    from alphapilot.research.auth import Actor
    service = _service(job_root)
    service.get(job_id, Actor.local())
    path = service.store.root / job_id / "run.log"
    cursor = max(0, path.stat().st_size - min(max_chars, 65536)) if path.exists() else 0
    return service.logs(job_id, Actor.local(), cursor=cursor, limit=min(max_chars, 65536))["text"]


def read_progress(job_id, *, job_root=None, max_chars=50000):
    job = get_job(job_id, job_root=job_root)
    return {"job_id": job_id, "status": job["status"], **job["progress"]}


def read_result(job_id, *, job_root=None):
    from alphapilot.research.auth import Actor
    return _service(job_root).read_result(job_id, Actor.local())


def cancel_job(job_id, *, job_root=None):
    from alphapilot.research.auth import Actor
    return _service(job_root).cancel(job_id, Actor.local())


def delete_job(job_id, *, job_root=None, **_):
    from alphapilot.research.auth import Actor
    return _service(job_root).delete(job_id, Actor.local())


def clear_finished_jobs(*, job_root=None):
    rows = [j for j in list_jobs(job_root=job_root) if j["status"] in {"succeeded", "failed", "cancelled", "lost"}]
    for job in rows:
        delete_job(job["job_id"], job_root=job_root)
    return len(rows)
