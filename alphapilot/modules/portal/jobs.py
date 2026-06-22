"""Persistent background jobs for long-running portal actions."""

from __future__ import annotations

import contextlib
import csv
import dataclasses
import json
import multiprocessing
import os
import re
import shutil
import signal
import sys
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

JobKind = str
JobStatus = str

# AlphaForge formulaic miners run as background jobs (heavy torch training).
# Each kind maps to (module name, command) dispatched in ``_run_target``.
ALPHAFORGE_JOBS: dict[str, tuple[str, str]] = {
    "mine_aff": ("alphaforge_aff", "mine_aff"),
    "mine_gp": ("alphaforge_search", "mine_gp"),
    "mine_rl": ("alphaforge_search", "mine_rl"),
    "mine_dso": ("alphaforge_search", "mine_dso"),
}

VALID_KINDS = {"mine", "factor_backtest", "strategy_backtest", "daily_signals", "data", *ALPHAFORGE_JOBS}

# Data-system actions runnable as a ``data`` job; ``kwargs["action"]`` selects one.
DATA_ACTIONS = ("pipeline", "download", "apply_adjust", "convert", "build_h5")
TERMINAL_STATUSES = {"succeeded", "failed", "cancelled", "lost"}


def default_job_root() -> Path:
    """Return the persistent portal job directory."""
    configured = os.getenv("ALPHAPILOT_PORTAL_JOB_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / "git_ignore_folder" / "portal_jobs"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _job_path(job_dir: Path) -> Path:
    return job_dir / "job.json"


def _result_path(job_dir: Path) -> Path:
    return job_dir / "result.json"


def _log_path(job_dir: Path) -> Path:
    return job_dir / "run.log"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _patch_job(job_dir: Path, changes: dict[str, Any]) -> dict[str, Any]:
    path = _job_path(job_dir)
    payload = _read_json(path)
    payload.update(changes)
    _atomic_write_json(path, payload)
    return payload


def _progress(
    percent: int | float,
    stage: str,
    message: str | None = None,
    *,
    updated_at: str | None = None,
) -> dict[str, Any]:
    value = max(0, min(100, int(percent)))
    return {"percent": value, "stage": stage, "message": message or stage, "updated_at": updated_at or utc_now()}


def update_current_job_progress(
    percent: int | float,
    stage: str,
    message: str | None = None,
    **extra: Any,
) -> None:
    """Best-effort progress update for code running inside a portal worker."""
    job_dir_raw = os.getenv("ALPHAPILOT_PORTAL_JOB_DIR")
    if not job_dir_raw:
        return
    try:
        payload = _progress(percent, stage, message)
        payload.update(_jsonable(extra))
        _patch_job(Path(job_dir_raw), {"progress": payload})
    except Exception:
        return


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def _result_summary(result: Any) -> str:
    if result is None:
        return "completed"
    if isinstance(result, list):
        return f"list[{len(result)}]"
    if isinstance(result, dict):
        # AlphaForge mining summary: surface the accept/mine counts directly.
        if "n_accepted" in result and "mined" in result:
            parts = [f"accepted={result.get('n_accepted')}/{result.get('mined')} mined"]
            if result.get("n_rejected"):
                parts.append(f"rejected={result.get('n_rejected')}")
            if result.get("untranslatable"):
                parts.append(f"untranslatable={result.get('untranslatable')}")
            return ", ".join(parts)
        keys = ", ".join(list(result.keys())[:8])
        return f"dict({keys})"
    text = repr(result)
    return text if len(text) <= 500 else text[:497] + "..."


def _pid_exists(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _new_job_id(kind: JobKind) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_{kind}_{uuid.uuid4().hex[:8]}"


def _run_target(kind: JobKind, kwargs: dict[str, Any]) -> Any:
    from alphapilot.kernel import build_engine

    engine = build_engine(discover=True)
    if kind == "mine":
        return engine.get_module("alpha_mining").run_mining(**kwargs)
    if kind == "factor_backtest":
        return engine.get_module("alpha_mining").run_backtest(**kwargs)
    if kind == "strategy_backtest":
        return engine.get_module("strategy_backtest").strategy_backtest(**kwargs)
    if kind == "daily_signals":
        return engine.get_module("daily_trade").daily_signals(**kwargs)
    if kind == "data":
        call_kwargs = dict(kwargs)
        action = call_kwargs.pop("action", "pipeline")
        if action not in DATA_ACTIONS:
            raise ValueError(f"Unsupported data action: {action!r} (expected one of {DATA_ACTIONS})")
        return getattr(engine.get_system("data"), action)(**call_kwargs)
    if kind in ALPHAFORGE_JOBS:
        module_name, command = ALPHAFORGE_JOBS[kind]
        return getattr(engine.get_module(module_name), command)(**kwargs)
    raise ValueError(f"Unsupported portal job kind: {kind!r}")


def _csv_last_date(path: Path) -> str | None:
    """Return the first comma-separated field from the last data row of a CSV."""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return None
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            end = handle.tell()
            size = min(end, 4096)
            handle.seek(end - size)
            text = handle.read(size).decode("utf-8", errors="ignore")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) <= 1:
            return None
        last = lines[-1]
        first = next(csv.reader([last]))[0]
        return first[:10] if first else None
    except Exception:
        return None


def _data_job_disk_progress(job: dict[str, Any]) -> dict[str, Any] | None:
    """Estimate data download progress from raw CSV files on disk.

    This avoids relying on the worker periodically writing ``job.json``. A stock
    is counted complete once its raw CSV last date reaches the requested end date.
    """
    if job.get("kind") != "data":
        return None
    params = job.get("params") if isinstance(job.get("params"), dict) else {}
    if params.get("action") not in {"download", "pipeline"}:
        return None

    try:
        from alphapilot.systems.data.prepare_cn import resolve_raw_dir
        from alphapilot.systems.data.prepare_tushare import resolve_tushare_raw_dir
        from alphapilot.systems.data.stock_list import load_stocks_from_file, normalize_to_baostock
    except Exception:
        return None

    source = str(params.get("source") or "baostock_cn")
    adjust_mode = str(params.get("adjust_mode") or "backward")
    if source == "tushare_cn":
        # Tushare raw download is always unadjusted; pipeline may adjust later.
        mode_for_raw = "none" if params.get("action") == "pipeline" else adjust_mode
        raw_dir = resolve_tushare_raw_dir(params.get("data_dir"), mode_for_raw)
    else:
        raw_dir = resolve_raw_dir(params.get("data_dir"), adjust_mode)

    end_date = str(params.get("end_date") or "")
    if not end_date:
        return None
    try:
        # Normalize dates like 2026-6-18 to lexical YYYY-MM-DD comparison.
        import pandas as pd

        end_date = pd.to_datetime(end_date, errors="raise").strftime("%Y-%m-%d")
    except Exception:
        return None

    symbols = params.get("symbols")
    if isinstance(symbols, list) and symbols:
        codes = [c for c in (normalize_to_baostock(str(item)) for item in symbols) if c]
    elif params.get("stock_csv"):
        try:
            codes = load_stocks_from_file(str(params["stock_csv"]), code_column=params.get("code_column"))
        except Exception:
            return None
    else:
        return None

    if not codes:
        return None

    completed = 0
    latest_seen: str | None = None
    current_symbol: str | None = None
    for code in codes:
        csv_path = raw_dir / f"{code.replace('.', '')}.csv"
        last_date = _csv_last_date(csv_path)
        if last_date:
            if latest_seen is None or last_date > latest_seen:
                latest_seen = last_date
                current_symbol = code
            if last_date >= end_date:
                completed += 1

    total = len(codes)
    percent = 8 + (completed / max(total, 1)) * 70
    return {
        "percent": min(99, int(percent)),
        "stage": f"download:{source}",
        "message": f"按已落盘 CSV 计算: {completed}/{total} 已达到 {end_date}",
        "total": total,
        "completed": completed,
        "pending": max(0, total - completed),
        "current_symbol": current_symbol,
        "latest_data_date": latest_seen,
        "progress_source": "disk",
        "raw_dir": str(raw_dir),
    }


def _infer_progress(job: dict[str, Any], log_text: str = "") -> dict[str, Any]:
    """Infer user-facing progress from job metadata and tqdm-style logs."""
    status = str(job.get("status") or "")
    saved = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    out = dict(saved)
    if status in {"succeeded"}:
        out.update(_progress(100, "done", "completed"))
        return out
    if status in {"failed", "cancelled", "lost"}:
        out.update(_progress(saved.get("percent", 0), status, str(job.get("error") or status)))
        return out

    percent = int(saved.get("percent", 1) or 1)
    stage = str(saved.get("stage") or "running")
    message = str(saved.get("message") or stage)

    matches = list(re.finditer(r"(?P<pct>\d{1,3})%\|", log_text))
    if matches:
        latest = matches[-1]
        percent = max(percent, min(99, int(latest.group("pct"))))
        line_start = log_text.rfind("\n", 0, latest.start()) + 1
        line_end = log_text.find("\n", latest.end())
        if line_end == -1:
            line_end = len(log_text)
        message = log_text[line_start:line_end].replace("\r", " ").strip() or message

    if status == "running":
        percent = min(percent, 99)
    out.update(_progress(percent, stage, message, updated_at=saved.get("updated_at")))
    return out


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


def _job_worker(job_dir_raw: str, kind: JobKind, kwargs: dict[str, Any]) -> None:
    from alphapilot.modules.portal.env_config import apply_portal_env

    apply_portal_env()
    job_dir = Path(job_dir_raw)
    job_id = job_dir.name
    log_file = _log_path(job_dir)
    os.environ["ALPHAPILOT_PORTAL_JOB_ID"] = job_id
    os.environ.setdefault("ALPHAPILOT_PORTAL_JOB_DIR", str(job_dir))

    kwargs = dict(kwargs)
    notify_flag = kwargs.pop("notify", None)  # control key, not a task argument
    if kind == "strategy_backtest" and not kwargs.get("run_tag"):
        kwargs["run_tag"] = f"portal_{job_id}"

    with log_file.open("a", encoding="utf-8", buffering=1) as stream:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            print(f"[portal-job] job_id={job_id} kind={kind} pid={os.getpid()}")
            print(f"[portal-job] kwargs={json.dumps(_jsonable(kwargs), ensure_ascii=False)}")
            _patch_job(
                job_dir,
                {
                    "pid": os.getpid(),
                    "status": "running",
                    "started_at": utc_now(),
                    "params": _jsonable(kwargs),
                    "progress": _progress(2, "starting", "worker started"),
                },
            )
            try:
                if kind == "data":
                    action = kwargs.get("action", "pipeline")
                    _patch_job(job_dir, {"progress": _progress(5, f"data:{action}", f"running data action: {action}")})
                result = _run_target(kind, kwargs)
                result_payload = _jsonable(result)
                _atomic_write_json(_result_path(job_dir), {"result": result_payload})
                _patch_job(
                    job_dir,
                    {
                        "status": "succeeded",
                        "finished_at": utc_now(),
                        "returncode": 0,
                        "error": None,
                        "result_summary": _result_summary(result),
                        "progress": _progress(100, "done", "completed"),
                    },
                )
                print("[portal-job] succeeded")
                _maybe_notify(job_dir, kind, kwargs, notify_flag, "succeeded", result, None)
            except BaseException as exc:  # noqa: BLE001
                traceback.print_exc()
                _patch_job(
                    job_dir,
                    {
                        "status": "failed",
                        "finished_at": utc_now(),
                        "returncode": 1,
                        "error": f"{type(exc).__name__}: {exc}",
                        "progress": _progress(100, "failed", f"{type(exc).__name__}: {exc}"),
                    },
                )
                _maybe_notify(job_dir, kind, kwargs, notify_flag, "failed", None, exc)
                raise


ProcessFactory = Callable[[Callable[..., None], tuple[Any, ...]], Any]


def start_job(
    kind: JobKind,
    kwargs: dict[str, Any],
    *,
    job_root: Path | str | None = None,
    process_factory: ProcessFactory | None = None,
) -> dict[str, Any]:
    """Create a persistent job and start its worker process."""
    if kind not in VALID_KINDS:
        raise ValueError(f"Unsupported portal job kind: {kind!r}")

    root = Path(job_root) if job_root is not None else default_job_root()
    root.mkdir(parents=True, exist_ok=True)
    job_id = _new_job_id(kind)
    job_dir = root / job_id
    job_dir.mkdir(parents=False, exist_ok=False)

    payload = {
        "job_id": job_id,
        "kind": kind,
        "status": "running",
        "pid": None,
        "params": _jsonable(kwargs),
        "job_dir": str(job_dir),
        "log_path": str(_log_path(job_dir)),
        "result_path": str(_result_path(job_dir)),
        "created_at": utc_now(),
        "started_at": None,
        "finished_at": None,
        "returncode": None,
        "error": None,
        "result_summary": None,
        "progress": _progress(0, "queued", "queued"),
    }
    _atomic_write_json(_job_path(job_dir), payload)
    _log_path(job_dir).touch()

    args = (str(job_dir), kind, dict(kwargs))
    if process_factory is None:
        ctx = multiprocessing.get_context("spawn")
        process = ctx.Process(target=_job_worker, args=args, daemon=False)
    else:
        process = process_factory(_job_worker, args)
    try:
        process.start()
    except Exception as exc:
        _patch_job(
            job_dir,
            {
                "status": "failed",
                "finished_at": utc_now(),
                "returncode": None,
                "error": f"Failed to start worker: {type(exc).__name__}: {exc}",
            },
        )
        raise
    return _patch_job(job_dir, {"pid": getattr(process, "pid", None)})


def _refresh_job(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("status") != "running":
        return job
    pid = job.get("pid")
    try:
        pid_int = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        pid_int = None
    if not pid_int:
        return job
    if _pid_exists(pid_int):
        return job

    job_dir = Path(job["job_dir"])
    latest = _read_json(_job_path(job_dir))
    if latest.get("status") in TERMINAL_STATUSES:
        return latest
    latest.update(
        {
            "status": "lost",
            "finished_at": utc_now(),
            "returncode": None,
            "error": "Worker process is no longer running and did not write a terminal status.",
        }
    )
    _atomic_write_json(_job_path(job_dir), latest)
    return latest


def list_jobs(*, job_root: Path | str | None = None, refresh: bool = True) -> list[dict[str, Any]]:
    root = Path(job_root) if job_root is not None else default_job_root()
    if not root.is_dir():
        return []
    jobs: list[dict[str, Any]] = []
    for path in root.glob("*/job.json"):
        try:
            job = _read_json(path)
            if refresh:
                job = _refresh_job(job)
            jobs.append(job)
        except Exception:  # noqa: BLE001
            continue
    return sorted(jobs, key=lambda item: item.get("created_at") or "", reverse=True)


def get_job(job_id: str, *, job_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(job_root) if job_root is not None else default_job_root()
    job = _read_json(root / job_id / "job.json")
    return _refresh_job(job)


def read_log_tail(job_id: str, *, job_root: Path | str | None = None, max_chars: int = 12000) -> str:
    job = get_job(job_id, job_root=job_root)
    path = Path(job["log_path"])
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[-max_chars:]


def read_progress(job_id: str, *, job_root: Path | str | None = None, max_chars: int = 50000) -> dict[str, Any]:
    job = get_job(job_id, job_root=job_root)
    log = read_log_tail(job_id, job_root=job_root, max_chars=max_chars)
    progress = _infer_progress(job, log)
    disk_progress = _data_job_disk_progress(job)
    if disk_progress and job.get("status") == "running":
        if int(disk_progress.get("completed", 0)) >= int(progress.get("completed", 0) or 0):
            progress.update(disk_progress)
            progress["updated_at"] = utc_now()
    return {"job_id": job_id, "status": job.get("status"), **progress}


def read_result(job_id: str, *, job_root: Path | str | None = None) -> dict[str, Any] | None:
    job = get_job(job_id, job_root=job_root)
    path = Path(job["result_path"])
    if not path.exists():
        return None
    return _read_json(path)


def cancel_job(job_id: str, *, job_root: Path | str | None = None) -> dict[str, Any]:
    job = get_job(job_id, job_root=job_root)
    if job.get("status") in TERMINAL_STATUSES:
        return job

    pid = job.get("pid")
    pid_int = int(pid) if pid is not None else None
    if pid_int and _pid_exists(pid_int):
        os.kill(pid_int, signal.SIGTERM)
        time.sleep(0.2)

    job_dir = Path(job["job_dir"])
    return _patch_job(
        job_dir,
        {
            "status": "cancelled",
            "finished_at": utc_now(),
            "returncode": -signal.SIGTERM,
            "error": "Cancelled from portal.",
            "progress": _progress(100, "cancelled", "cancelled"),
        },
    )


def delete_job(
    job_id: str,
    *,
    job_root: Path | str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Delete a job's directory (metadata, log, result).

    A still-running job is refused unless *force* is set, in which case its worker
    is sent SIGTERM first. Returns ``{"job_id", "status", "deleted"}``.
    """
    root = Path(job_root) if job_root is not None else default_job_root()
    job_dir = root / job_id
    if not job_dir.is_dir():
        raise FileNotFoundError(f"Job not found: {job_id}")

    job = _refresh_job(_read_json(_job_path(job_dir)))
    status = job.get("status")
    if status == "running":
        if not force:
            raise RuntimeError(
                f"Job {job_id} is still running; cancel it before deleting (or pass force=True)."
            )
        pid = job.get("pid")
        try:
            pid_int = int(pid) if pid is not None else None
        except (TypeError, ValueError):
            pid_int = None
        if pid_int and _pid_exists(pid_int):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid_int, signal.SIGTERM)
                time.sleep(0.2)

    shutil.rmtree(job_dir, ignore_errors=True)
    return {"job_id": job_id, "status": status, "deleted": not job_dir.exists()}


def clear_finished_jobs(*, job_root: Path | str | None = None) -> int:
    """Delete every job in a terminal status. Returns the number removed."""
    removed = 0
    for job in list_jobs(job_root=job_root, refresh=True):
        if job.get("status") not in TERMINAL_STATUSES:
            continue
        job_id = job.get("job_id")
        if not job_id:
            continue
        try:
            if delete_job(job_id, job_root=job_root).get("deleted"):
                removed += 1
        except Exception:  # noqa: BLE001
            continue
    return removed


if __name__ == "__main__":
    # Useful for ad-hoc worker debugging without importing Streamlit.
    _, job_dir_arg, kind_arg, kwargs_arg = sys.argv
    _job_worker(job_dir_arg, kind_arg, json.loads(kwargs_arg))
