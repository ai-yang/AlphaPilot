"""Per-task run workspace: one named directory per `alphapilot mine` / `alphapilot backtest`.

Groups a single task's outputs under `git_ignore_folder/runs/<ts>__<cmd>__<market>__<id>/`:

    runs/<run_id>/
      workspaces/     # every FBWorkspace (factor + experiment) of this run
      factor_data ->  # symlink to the shared factor_h5_cache/<spec_hash> (NOT copied)
      logs ->         # best-effort symlink to this run's log session
      manifest.json   # run metadata (command, market, spec_hash, status, timestamps, ...)

Large/shared content caches (the h5 data and the content-addressed pickle reuse cache) stay
global and are only *referenced* here, so deleting a run dir never touches shared caches.

The workspace root is relocated for the duration of the run via a contextvar
(`alphapilot.core.workspace`) plus the `ALPHAPILOT_WORKSPACE_ROOT` env (for artifact/leaderboard
mapping in `systems/backtest/artifacts.py`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from alphapilot.core.path_safety import ensure_child_path
from alphapilot.core.workspace import reset_workspace_root_override, set_workspace_root_override
from alphapilot.log import logger

WORKSPACE_ROOT_ENV = "ALPHAPILOT_WORKSPACE_ROOT"
RUNS_DIR_ENV = "ALPHAPILOT_RUNS_DIR"

_current_run: ContextVar["RunWorkspace | None"] = ContextVar("current_run_workspace", default=None)


def runs_root() -> Path:
    """Root holding all per-task run directories (under repo ``git_ignore_folder``)."""
    env = os.environ.get(RUNS_DIR_ENV)
    if env:
        return Path(env)
    return Path("git_ignore_folder") / "runs"


def current_run() -> "RunWorkspace | None":
    """The run workspace active in this context, if any."""
    return _current_run.get()


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _sanitize(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", str(name)).strip("_") or "na"


def _make_run_id(command: str, market: str | None) -> str:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{ts}__{_sanitize(command)}__{_sanitize(market) if market else 'na'}__{uuid.uuid4().hex[:6]}"


def _safe_symlink(target: Path, link: Path, *, is_dir: bool) -> bool:
    """Best-effort symlink ``link`` -> ``target``; never raise (Windows/perm fall back to manifest)."""
    try:
        if link.is_symlink() or link.exists():
            return True
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link, target_is_directory=is_dir)
        return True
    except OSError as exc:  # noqa: BLE001 — symlink is a convenience; manifest still records the path
        logger.warning(f"[run_workspace] could not symlink {link} -> {target}: {exc}")
        return False


@dataclass
class RunWorkspace:
    """A single task's run directory + manifest."""

    run_id: str
    root: Path
    workspaces_dir: Path
    manifest_path: Path
    _manifest: dict[str, Any] = field(default_factory=dict, repr=False)

    def _flush(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self._manifest, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )

    def record(self, **kv: Any) -> None:
        self._manifest.update(kv)
        self._flush()

    def attach_factor_data(self, ctx: Any) -> None:
        """Symlink the shared factor h5 cache and record its fingerprint (idempotent)."""
        target = Path(ctx.cache_dir)
        _safe_symlink(target, self.root / "factor_data", is_dir=True)
        self.record(
            spec_hash=getattr(ctx, "fingerprint", None),
            market=getattr(getattr(ctx, "spec", None), "market", None) or self._manifest.get("market"),
            factor_data_dir=str(target),
        )

    def set_primary_experiment(self, path: str | Path | None) -> None:
        if path:
            self.record(primary_experiment_workspace=str(path))


@contextmanager
def run_workspace(
    *,
    command: str,
    market: str | None = None,
    scenario: str | None = None,
    qlib_config_name: str | None = None,
    qlib_template_dir: str | None = None,
    factor_data_ctx: Any = None,
) -> Iterator[RunWorkspace]:
    """Create + activate a per-task run directory; relocate the workspace root for its duration."""
    run_id = _make_run_id(command, market)
    root = (runs_root() / run_id).resolve()
    workspaces_dir = root / "workspaces"
    workspaces_dir.mkdir(parents=True, exist_ok=True)

    rw = RunWorkspace(
        run_id=run_id, root=root, workspaces_dir=workspaces_dir, manifest_path=root / "manifest.json"
    )
    rw._manifest = {
        "run_id": run_id,
        "command": command,
        "market": market,
        "scenario": scenario,
        "qlib_config_name": qlib_config_name,
        "qlib_template_dir": qlib_template_dir,
        "workspaces_dir": str(workspaces_dir),
        "created_at": _now_iso(),
        "status": "running",
    }
    rw._flush()
    if factor_data_ctx is not None:
        rw.attach_factor_data(factor_data_ctx)

    ws_token = set_workspace_root_override(workspaces_dir)
    old_env = os.environ.get(WORKSPACE_ROOT_ENV)
    os.environ[WORKSPACE_ROOT_ENV] = str(workspaces_dir)
    run_token = _current_run.set(rw)
    logger.info(f"[run_workspace] {run_id} -> {root}")

    status = "completed"
    try:
        yield rw
    except BaseException:
        status = "failed"
        raise
    finally:
        reset_workspace_root_override(ws_token)
        if old_env is None:
            os.environ.pop(WORKSPACE_ROOT_ENV, None)
        else:
            os.environ[WORKSPACE_ROOT_ENV] = old_env
        _current_run.reset(run_token)
        # Best-effort: link this run's log session into the run dir for one-stop browsing.
        trace_path = getattr(logger, "log_trace_path", None)
        if trace_path and Path(trace_path).exists():
            _safe_symlink(Path(trace_path), root / "logs", is_dir=True)
            rw._manifest["log_trace_path"] = str(trace_path)
        rw._manifest["status"] = status
        rw._manifest["finished_at"] = _now_iso()
        rw._flush()


def list_runs() -> list[dict[str, Any]]:
    """Run directories (newest first) with their manifest fields merged in."""
    root = runs_root().resolve()
    if not root.exists():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for d in dirs:
        info: dict[str, Any] = {"run_id": d.name, "path": str(d)}
        manifest = d / "manifest.json"
        if manifest.exists():
            try:
                info.update(json.loads(manifest.read_text()))
            except (OSError, json.JSONDecodeError):
                pass
        out.append(info)
    return out


def delete_run(run_id: str) -> bool:
    """Delete one run directory (symlinks are unlinked; shared cache targets are preserved)."""
    root = runs_root().resolve()
    candidate = Path(run_id).expanduser()
    target = candidate.resolve() if candidate.is_absolute() else (root / run_id).resolve()
    ensure_child_path(root, target)
    if target == root:
        raise ValueError(f"Refusing to delete runs root: {root}")
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


# --------------------------------------------------------------------------- #
# Backtest-result discovery from saved runs (durable record, not the transient
# global workspace cache). Each run dir holds its own ``workspaces/<id>/`` and a
# ``logs`` symlink, so the portal can browse results by run instead of scanning a
# flat workspace root.
# --------------------------------------------------------------------------- #
def _run_label(manifest: dict[str, Any], ws_name: str, *, dup: bool = False) -> str:
    """Readable label for a run's backtest result (``command · market · time``)."""
    cmd = manifest.get("command") or "run"
    market = manifest.get("market") or ""
    stamp = ""
    raw_ts = manifest.get("created_at") or ""
    if raw_ts:
        try:
            stamp = datetime.fromisoformat(str(raw_ts)).strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            stamp = str(raw_ts)[:16]
    label = " · ".join(p for p in (cmd, market, stamp) if p) or ws_name
    return f"{label}  ({ws_name[:8]}…)" if dup else label


def list_run_backtests() -> list[dict[str, Any]]:
    """Backtest-result workspaces (those with ``ret.pkl``) across all saved runs.

    Newest run first; entries carry manifest-derived ``label`` / ``command`` /
    ``market`` / ``status`` plus the workspace ``mtime``. This replaces scanning a
    flat workspace root in the portal.
    """
    root = runs_root().resolve()
    if not root.exists():
        return []
    out: list[dict[str, Any]] = []
    for run in list_runs():
        run_id = run.get("run_id")
        if not run_id:
            continue
        ws_dir = root / run_id / "workspaces"
        if not ws_dir.is_dir():
            continue
        ret_workspaces = sorted(
            (w for w in ws_dir.iterdir() if w.is_dir() and (w / "ret.pkl").exists()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        dup = len(ret_workspaces) > 1
        for ws in ret_workspaces:
            out.append(
                {
                    "workspace_id": ws.name,
                    "path": str(ws),
                    "run_id": run_id,
                    "label": _run_label(run, ws.name, dup=dup),
                    "command": run.get("command"),
                    "market": run.get("market"),
                    "status": run.get("status"),
                    "log_trace_path": run.get("log_trace_path"),
                    "mtime": datetime.fromtimestamp(ws.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                }
            )
    return out


def resolve_run_workspace(workspace_id: str) -> Path | None:
    """Find a backtest-result workspace (``ret.pkl``) by its dir name across runs."""
    root = runs_root().resolve()
    if not root.exists():
        return None
    for run_dir in root.iterdir():
        if not run_dir.is_dir():
            continue
        ws = run_dir / "workspaces" / workspace_id
        if ws.is_dir() and (ws / "ret.pkl").exists():
            return ws
    return None


def delete_run_workspace(workspace_id: str) -> bool:
    """Delete a single backtest-result workspace dir (kept within ``runs_root``)."""
    ws = resolve_run_workspace(workspace_id)
    if ws is None:
        return False
    root = runs_root().resolve()
    ensure_child_path(root, ws.resolve())
    shutil.rmtree(ws)
    return True
