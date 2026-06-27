"""Trade sessions: self-contained, resumable daily-trade accounts.

A *trade session* snapshots an existing strategy (model + factors + params) into its own
folder and accumulates the rolling portfolio state plus a per-day rebalance history there, so
daily signals can be resumed with a single ``--session`` and the whole track — strategy
snapshot + state + history — lives together. Sessions are local artifacts under
``git_ignore_folder/trade_sessions`` (overridable via ``ALPHAPILOT_TRADE_SESSIONS_DIR`` or an
explicit ``root``).

Layout::

    <root>/<sanitized_name>/
        session.json          # manifest: name, source_strategy, init_cash, current_date, ...
        strategy/             # strategy snapshot (FileStrategyParamDatabase.save_record output)
            <source>/strategy_record.json, factors.json, model.json, artifacts/<model>.pkl, ...
        state.json            # rolling PortfolioState (current; same format as portfolio_state)
        history/<date>.json   # full daily result (summarize() output)
        daily_log.jsonl       # one compact line per day
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alphapilot.core.path_safety import ensure_child_path
from alphapilot.log import logger
from alphapilot.systems.strategy.database import FileStrategyParamDatabase

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
def default_sessions_root() -> Path:
    configured = os.getenv("ALPHAPILOT_TRADE_SESSIONS_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / "git_ignore_folder" / "trade_sessions"


def _root(root: Path | str | None) -> Path:
    return Path(root) if root is not None else default_sessions_root()


def sanitize_name(name: str) -> str:
    """Reuse the strategy zoo's name sanitizer so session/strategy names stay consistent."""
    return FileStrategyParamDatabase._sanitize_name(name)


def session_dir(name: str, *, root: Path | str | None = None) -> Path:
    return _root(root) / sanitize_name(name)


def _manifest_path(sdir: Path) -> Path:
    return sdir / "session.json"


def _strategy_snapshot_dir(sdir: Path) -> Path:
    return sdir / "strategy"


def state_path_for(name: str, *, root: Path | str | None = None) -> Path:
    return session_dir(name, root=root) / "state.json"


def session_exists(name: str, *, root: Path | str | None = None) -> bool:
    return _manifest_path(session_dir(name, root=root)).exists()


# --------------------------------------------------------------------------- #
# Manifest IO
# --------------------------------------------------------------------------- #
def _read_manifest(sdir: Path) -> dict[str, Any]:
    return json.loads(_manifest_path(sdir).read_text(encoding="utf-8"))


def _write_manifest(sdir: Path, manifest: dict[str, Any]) -> None:
    sdir.mkdir(parents=True, exist_ok=True)
    _manifest_path(sdir).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Create / resolve
# --------------------------------------------------------------------------- #
def create_session(
    context: "Context",
    *,
    name: str | None = None,
    strategy_name: str,
    init_cash: float | None = None,
    overwrite: bool = False,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Snapshot ``strategy_name`` into a new trade session.

    ``name`` defaults to ``strategy_name``. A pre-existing session with the same name is
    rejected (the duplicate "prompt") unless ``overwrite=True``. The strategy's model + factors
    + params are *copied* (via the strategy database's record/artifact machinery), so the session
    is self-contained and immune to later changes of the source strategy.
    """
    strategy_name = (strategy_name or "").strip()
    if not strategy_name:
        raise ValueError("strategy_name is required to create a trade session")
    name = (name or strategy_name).strip()

    base = _root(root)
    sdir = session_dir(name, root=root)
    if _manifest_path(sdir).exists() and not overwrite:
        raise ValueError(
            f"Trade session {name!r} already exists at {sdir}. "
            f"Choose a different name, or pass overwrite=True to replace it."
        )

    record = context.strategy().get_strategy(strategy_name)
    if record is None:
        raise ValueError(f"Strategy asset not found: {strategy_name}")
    if record.model is None or not getattr(record.model, "trained_artifact_uri", None):
        raise ValueError(
            f"Strategy {strategy_name!r} has no trained model (model.trained_artifact_uri); a "
            f"daily-trade session needs a trained model. Backtest/train the strategy first."
        )

    # Clear leftovers on overwrite so the snapshot is clean.
    if sdir.exists() and overwrite:
        ensure_child_path(base, sdir)
        shutil.rmtree(sdir)

    snap_dir = _strategy_snapshot_dir(sdir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    # Reuse the strategy database's record + artifact copy machinery: it copies the model pkl
    # into ``<snap>/<source>/artifacts`` and rewrites trained_artifact_uri to the copy.
    FileStrategyParamDatabase(snap_dir).save_record(record)

    market = (record.metadata or {}).get("market")
    manifest = {
        "name": name,
        "source_strategy": strategy_name,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "init_cash": float(init_cash) if init_cash is not None else None,
        "market": market,
        "current_date": None,
        "status": "created",
        "n_factors": len(record.factor_formulas or []),
    }
    _write_manifest(sdir, manifest)
    logger.info(f"[trade_session] created {name!r} from strategy {strategy_name!r} at {sdir}")
    return manifest


@dataclass
class ResolvedSessionStrategy:
    factor_csv: Path | None
    is_temp_csv: bool
    model_pickle_path: str
    yaml_params: Any
    market: str | None


def resolve_session_strategy(name: str, *, root: Path | str | None = None) -> ResolvedSessionStrategy:
    """Load the session's strategy snapshot into the inputs ``generate_daily_signal`` needs."""
    from alphapilot.systems.backtest.live.service import _write_factor_csv_from_formulas

    sdir = session_dir(name, root=root)
    if not _manifest_path(sdir).exists():
        raise ValueError(f"Trade session not found: {name}")
    manifest = _read_manifest(sdir)
    source = manifest.get("source_strategy") or name

    record = FileStrategyParamDatabase(_strategy_snapshot_dir(sdir)).load_record(source)
    if record is None:
        raise ValueError(f"Trade session {name!r} has no strategy snapshot")
    model_pkl = record.model.trained_artifact_uri if record.model else None
    if not model_pkl:
        raise ValueError(f"Trade session {name!r} snapshot has no trained model artifact")

    yaml_params = (record.metadata or {}).get("yaml_params")
    market = manifest.get("market") or (record.metadata or {}).get("market")
    factor_csv: Path | None = None
    is_temp = False
    if record.factor_formulas:
        factor_csv = _write_factor_csv_from_formulas(record.factor_formulas)
        is_temp = True
    return ResolvedSessionStrategy(
        factor_csv=factor_csv,
        is_temp_csv=is_temp,
        model_pickle_path=str(model_pkl),
        yaml_params=yaml_params,
        market=market,
    )


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
def current_date(name: str, *, root: Path | str | None = None) -> str | None:
    sdir = session_dir(name, root=root)
    if not _manifest_path(sdir).exists():
        return None
    return _read_manifest(sdir).get("current_date")


def append_history(name: str, summary: dict[str, Any], *, root: Path | str | None = None) -> Path:
    """Persist a day's full result + a compact log line; advance the manifest's ``current_date``."""
    sdir = session_dir(name, root=root)
    if not _manifest_path(sdir).exists():
        raise ValueError(f"Trade session not found: {name}")

    date = str(summary.get("date") or datetime.now().strftime("%Y-%m-%d"))
    history_dir = sdir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    day_path = history_dir / f"{date}.json"
    day_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    trades = summary.get("trades") or []
    info = summary.get("info") or {}
    log_line = {
        "date": date,
        "n_trades": len(trades),
        "n_buy": sum(1 for t in trades if str(t.get("status_label")) == "买入"),
        "n_sell": sum(1 for t in trades if str(t.get("status_label")) == "卖出"),
        "cash": summary.get("new_cash"),
        "n_positions": summary.get("n_positions"),
        "strategy": info.get("strategy"),
    }
    with (sdir / "daily_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(log_line, ensure_ascii=False, default=str) + "\n")

    manifest = _read_manifest(sdir)
    manifest["current_date"] = date
    manifest["status"] = "running"
    manifest["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    _write_manifest(sdir, manifest)
    return day_path


def read_log(name: str, *, root: Path | str | None = None) -> list[dict[str, Any]]:
    path = session_dir(name, root=root) / "daily_log.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001 — skip a corrupt line, keep the rest
            continue
    return out


def read_history_day(name: str, date: str, *, root: Path | str | None = None) -> dict[str, Any] | None:
    path = session_dir(name, root=root) / "history" / f"{date}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# List / load / delete
# --------------------------------------------------------------------------- #
def list_sessions(*, root: Path | str | None = None) -> list[dict[str, Any]]:
    base = _root(root)
    if not base.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(base.iterdir()):
        mpath = child / "session.json"
        if not mpath.exists():
            continue
        try:
            out.append(json.loads(mpath.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue
    return out


def load_session(name: str, *, root: Path | str | None = None, history_limit: int = 60) -> dict[str, Any]:
    """Manifest + current portfolio state + recent compact history for a session."""
    sdir = session_dir(name, root=root)
    if not _manifest_path(sdir).exists():
        raise ValueError(f"Trade session not found: {name}")
    manifest = _read_manifest(sdir)

    state: dict[str, Any] | None = None
    spath = state_path_for(name, root=root)
    if spath.exists():
        state = json.loads(spath.read_text(encoding="utf-8"))

    log = read_log(name, root=root)
    if history_limit and len(log) > history_limit:
        log = log[-history_limit:]
    return {"manifest": manifest, "state": state, "history": log}


def delete_session(name: str, *, root: Path | str | None = None) -> bool:
    base = _root(root)
    sdir = session_dir(name, root=root)
    if not sdir.exists():
        return False
    ensure_child_path(base, sdir)
    shutil.rmtree(sdir)
    return not sdir.exists()
