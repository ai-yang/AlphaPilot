"""Daily scheduler for portal background jobs.

A lightweight, dependency-free scheduler that stores per-task definitions on disk
and, via a long-running daemon, fires them once per day at a configured local time
by delegating to :mod:`alphapilot.modules.portal.jobs` (so each run becomes a
tracked background job with its own log / status / cancel / delete).

Pieces:
* **Store** -- one JSON file per schedule under ``<root>/<schedule_id>.json``.
* **Daemon** -- :func:`run_scheduler_loop` checks due schedules every *interval*
  seconds, triggers them and records ``last_run_date`` to avoid double-firing.
* **Control** -- :func:`start_daemon` / :func:`stop_daemon` / :func:`daemon_status`
  let the portal manage the daemon process via a heartbeat pid file.

Run the daemon directly with ``alphapilot scheduler`` or
``python -m alphapilot.modules.portal.schedules``.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from alphapilot.modules.portal import jobs as portal_jobs

# Task kinds a schedule may run. ``data`` additionally expects ``kwargs["action"]``.
# Kept in sync with the portal job kinds (and the scheduler UI's dropdown) so that
# every offered kind — including ``daily_signals`` and the AlphaForge miners —
# actually dispatches instead of being rejected at create time.
SCHEDULE_KINDS = (
    "data",
    "mine",
    "mine_aff",
    "mine_gp",
    "mine_rl",
    "factor_backtest",
    "strategy_backtest",
    "daily_signals",
)

# A heartbeat older than this (seconds) means the daemon is considered dead even
# if a stale pid file remains.
HEARTBEAT_STALE_SECONDS = 180

TriggerFn = Callable[..., dict[str, Any]]


# --------------------------------------------------------------------------- #
# Paths & small IO helpers (mirrors jobs.py conventions)
# --------------------------------------------------------------------------- #
def default_schedule_root() -> Path:
    configured = os.getenv("ALPHAPILOT_PORTAL_SCHEDULE_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / "git_ignore_folder" / "portal_schedules"


def _root(schedule_root: Path | str | None) -> Path:
    return Path(schedule_root) if schedule_root is not None else default_schedule_root()


def _schedule_path(root: Path, schedule_id: str) -> Path:
    return root / f"{schedule_id}.json"


def _pidfile_path(root: Path) -> Path:
    return root / "scheduler.pid.json"


def _daemon_log_path(root: Path) -> Path:
    return root / "scheduler.log"


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
def parse_hhmm(value: str) -> tuple[int, int]:
    """Validate/normalize a ``HH:MM`` string, returning ``(hour, minute)``."""
    parts = str(value).strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time {value!r}; expected HH:MM (24h).")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"Invalid time {value!r}; hour 0-23, minute 0-59.")
    return hour, minute


def next_run_at(schedule: dict[str, Any], now: datetime | None = None) -> datetime:
    """Next datetime this schedule will fire (today if still pending, else tomorrow)."""
    now = now or datetime.now()
    hour, minute = parse_hhmm(schedule["time"])
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    ran_today = schedule.get("last_run_date") == now.date().isoformat()
    if candidate <= now or ran_today:
        candidate += timedelta(days=1)
    return candidate


def _is_due(schedule: dict[str, Any], now: datetime) -> bool:
    if not schedule.get("enabled", True):
        return False
    if schedule.get("last_run_date") == now.date().isoformat():
        return False
    try:
        hour, minute = parse_hhmm(schedule["time"])
    except (ValueError, KeyError):
        return False
    scheduled = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return now >= scheduled


# --------------------------------------------------------------------------- #
# Store CRUD
# --------------------------------------------------------------------------- #
def _new_schedule_id(kind: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{kind}_{uuid.uuid4().hex[:6]}"


def create_schedule(
    *,
    name: str,
    kind: str,
    time: str,
    kwargs: dict[str, Any] | None = None,
    enabled: bool = True,
    schedule_root: Path | str | None = None,
) -> dict[str, Any]:
    if kind not in SCHEDULE_KINDS:
        raise ValueError(f"Unsupported schedule kind: {kind!r} (expected one of {SCHEDULE_KINDS})")
    parse_hhmm(time)  # validate
    root = _root(schedule_root)
    schedule_id = _new_schedule_id(kind)
    record = {
        "schedule_id": schedule_id,
        "name": name or schedule_id,
        "kind": kind,
        "time": time,
        "kwargs": dict(kwargs or {}),
        "enabled": bool(enabled),
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "last_run_date": None,
        "last_run_at": None,
        "last_job_id": None,
    }
    _atomic_write_json(_schedule_path(root, schedule_id), record)
    return record


def get_schedule(schedule_id: str, *, schedule_root: Path | str | None = None) -> dict[str, Any]:
    return _read_json(_schedule_path(_root(schedule_root), schedule_id))


def list_schedules(*, schedule_root: Path | str | None = None) -> list[dict[str, Any]]:
    root = _root(schedule_root)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in root.glob("*.json"):
        if path.name == _pidfile_path(root).name:
            continue
        try:
            out.append(_read_json(path))
        except Exception:  # noqa: BLE001
            continue
    return sorted(out, key=lambda s: (s.get("time", ""), s.get("name", "")))


def update_schedule(
    schedule_id: str,
    changes: dict[str, Any],
    *,
    schedule_root: Path | str | None = None,
) -> dict[str, Any]:
    root = _root(schedule_root)
    path = _schedule_path(root, schedule_id)
    record = _read_json(path)
    if "time" in changes:
        parse_hhmm(changes["time"])
    if "kind" in changes and changes["kind"] not in SCHEDULE_KINDS:
        raise ValueError(f"Unsupported schedule kind: {changes['kind']!r}")
    record.update(changes)
    record["updated_at"] = utc_now()
    _atomic_write_json(path, record)
    return record


def set_enabled(schedule_id: str, enabled: bool, *, schedule_root: Path | str | None = None) -> dict[str, Any]:
    return update_schedule(schedule_id, {"enabled": bool(enabled)}, schedule_root=schedule_root)


def delete_schedule(schedule_id: str, *, schedule_root: Path | str | None = None) -> bool:
    path = _schedule_path(_root(schedule_root), schedule_id)
    if not path.exists():
        raise FileNotFoundError(f"Schedule not found: {schedule_id}")
    path.unlink()
    return not path.exists()


def _mark_ran(
    schedule_id: str,
    job_id: str | None,
    when: datetime,
    *,
    schedule_root: Path | str | None = None,
) -> None:
    update_schedule(
        schedule_id,
        {
            "last_run_date": when.date().isoformat(),
            "last_run_at": when.astimezone().isoformat(timespec="seconds"),
            "last_job_id": job_id,
        },
        schedule_root=schedule_root,
    )


# --------------------------------------------------------------------------- #
# Triggering
# --------------------------------------------------------------------------- #
def trigger_schedule(
    schedule: dict[str, Any],
    *,
    job_root: Path | str | None = None,
    trigger_fn: TriggerFn | None = None,
) -> dict[str, Any]:
    """Start a background job for *schedule* and return the job record."""
    trigger_fn = trigger_fn or portal_jobs.start_job
    return trigger_fn(schedule["kind"], dict(schedule.get("kwargs") or {}), job_root=job_root)


def run_now(
    schedule_id: str,
    *,
    schedule_root: Path | str | None = None,
    job_root: Path | str | None = None,
    trigger_fn: TriggerFn | None = None,
) -> dict[str, Any]:
    """Manually fire a schedule immediately (also records it as today's run)."""
    schedule = get_schedule(schedule_id, schedule_root=schedule_root)
    job = trigger_schedule(schedule, job_root=job_root, trigger_fn=trigger_fn)
    _mark_ran(schedule_id, job.get("job_id"), datetime.now(), schedule_root=schedule_root)
    return job


def run_due(
    now: datetime | None = None,
    *,
    schedule_root: Path | str | None = None,
    job_root: Path | str | None = None,
    trigger_fn: TriggerFn | None = None,
) -> list[dict[str, Any]]:
    """Fire every schedule due at *now*. Returns ``[{schedule_id, job_id, error?}]``."""
    now = now or datetime.now()
    fired: list[dict[str, Any]] = []
    for schedule in list_schedules(schedule_root=schedule_root):
        if not _is_due(schedule, now):
            continue
        sid = schedule["schedule_id"]
        try:
            job = trigger_schedule(schedule, job_root=job_root, trigger_fn=trigger_fn)
            _mark_ran(sid, job.get("job_id"), now, schedule_root=schedule_root)
            fired.append({"schedule_id": sid, "job_id": job.get("job_id")})
        except Exception as exc:  # noqa: BLE001
            # Still mark the date so a broken schedule doesn't retry in a hot loop.
            _mark_ran(sid, None, now, schedule_root=schedule_root)
            fired.append({"schedule_id": sid, "job_id": None, "error": f"{type(exc).__name__}: {exc}"})
    return fired


# --------------------------------------------------------------------------- #
# Daemon
# --------------------------------------------------------------------------- #
def _write_heartbeat(root: Path, started_at: str) -> None:
    _atomic_write_json(
        _pidfile_path(root),
        {"pid": os.getpid(), "started_at": started_at, "heartbeat_at": utc_now()},
    )


def daemon_status(*, schedule_root: Path | str | None = None) -> dict[str, Any]:
    """Return ``{running, pid, started_at, heartbeat_at, stale}`` for the daemon."""
    root = _root(schedule_root)
    pidfile = _pidfile_path(root)
    if not pidfile.exists():
        return {"running": False, "pid": None, "started_at": None, "heartbeat_at": None, "stale": False}
    try:
        info = _read_json(pidfile)
    except Exception:  # noqa: BLE001
        return {"running": False, "pid": None, "started_at": None, "heartbeat_at": None, "stale": True}
    pid = info.get("pid")
    alive = _pid_alive(pid)
    stale = False
    hb = info.get("heartbeat_at")
    if alive and hb:
        try:
            age = (datetime.now().astimezone() - datetime.fromisoformat(hb)).total_seconds()
            stale = age > HEARTBEAT_STALE_SECONDS
        except ValueError:
            stale = False
    return {
        "running": bool(alive),
        "pid": pid,
        "started_at": info.get("started_at"),
        "heartbeat_at": hb,
        "stale": stale,
    }


def run_scheduler_loop(
    interval: int = 30,
    *,
    schedule_root: Path | str | None = None,
    job_root: Path | str | None = None,
    once: bool = False,
) -> None:
    """Daemon entry: poll for due schedules every *interval* seconds.

    Set *once* to make a single pass and return (used by tests). Responds to
    SIGTERM/SIGINT for a clean shutdown that removes the pid file.
    """
    root = _root(schedule_root)
    root.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()

    stopping = {"flag": False}

    def _handle_stop(signum, _frame):  # noqa: ANN001
        stopping["flag"] = True

    if not once:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _handle_stop)
            except (ValueError, OSError):
                pass  # not in main thread

    print(f"[scheduler] started pid={os.getpid()} root={root} interval={interval}s", flush=True)
    try:
        while True:
            _write_heartbeat(root, started_at)
            fired = run_due(schedule_root=schedule_root, job_root=job_root)
            for item in fired:
                if item.get("error"):
                    print(f"[scheduler] {item['schedule_id']} trigger failed: {item['error']}", flush=True)
                else:
                    print(f"[scheduler] fired {item['schedule_id']} -> job {item['job_id']}", flush=True)
            if once or stopping["flag"]:
                break
            for _ in range(max(1, int(interval))):
                if stopping["flag"]:
                    break
                time.sleep(1)
    finally:
        if not once:
            _pidfile_path(root).unlink(missing_ok=True)
            print("[scheduler] stopped", flush=True)


def start_daemon(*, schedule_root: Path | str | None = None, interval: int = 30) -> dict[str, Any]:
    """Spawn a detached scheduler daemon if one is not already running."""
    root = _root(schedule_root)
    root.mkdir(parents=True, exist_ok=True)
    status = daemon_status(schedule_root=schedule_root)
    if status["running"] and not status["stale"]:
        return status
    # Clear a stale pid file before relaunching.
    _pidfile_path(root).unlink(missing_ok=True)

    from alphapilot.modules.portal.env_config import apply_portal_env

    env = dict(os.environ)
    apply_portal_env(env)
    env["ALPHAPILOT_PORTAL_SCHEDULE_ROOT"] = str(root)
    log = _daemon_log_path(root).open("a", encoding="utf-8")
    log.write(f"\n[scheduler] launching at {utc_now()}\n")
    log.flush()
    subprocess.Popen(  # noqa: S603 - trusted, fixed argv
        [sys.executable, "-m", "alphapilot.modules.portal.schedules", "--interval", str(interval)],
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,  # detach from the portal process group
        env=env,
        cwd=str(Path.cwd()),
    )
    # Give the child a moment to write its pid file.
    for _ in range(20):
        time.sleep(0.1)
        if daemon_status(schedule_root=schedule_root)["running"]:
            break
    return daemon_status(schedule_root=schedule_root)


def stop_daemon(*, schedule_root: Path | str | None = None) -> dict[str, Any]:
    """Terminate a running scheduler daemon."""
    root = _root(schedule_root)
    status = daemon_status(schedule_root=schedule_root)
    pid = status.get("pid")
    if status["running"] and pid:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, ValueError):
            pass
        for _ in range(20):
            time.sleep(0.1)
            if not _pid_alive(pid):
                break
    _pidfile_path(root).unlink(missing_ok=True)
    return daemon_status(schedule_root=schedule_root)


def _main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    interval = 30
    if "--interval" in argv:
        idx = argv.index("--interval")
        try:
            interval = int(argv[idx + 1])
        except (IndexError, ValueError):
            interval = 30
    run_scheduler_loop(interval=interval)


if __name__ == "__main__":
    _main()
