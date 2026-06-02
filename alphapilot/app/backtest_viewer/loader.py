"""Load Qlib backtest artifacts from AlphaPilot workspace directories."""

from __future__ import annotations

import json
import os
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_WORKSPACE_ROOT = Path(
    os.environ.get("ALPHAPILOT_BACKTEST_ROOT", Path.cwd() / "git_ignore_folder" / "RD-Agent_workspace")
)
DEFAULT_LOG_ROOT = Path(os.environ.get("ALPHAPILOT_LOG_DIR", Path.cwd() / "log"))
LABELS_FILENAME = "backtest_workspace_labels.json"


@dataclass
class BacktestArtifacts:
    workspace: Path
    report: pd.DataFrame
    positions: dict
    indicators: Optional[pd.DataFrame]
    metrics: Optional[pd.Series]
    trades: pd.DataFrame
    holdings: pd.DataFrame


def _workspace_id_from_experiment(exp: object) -> str | None:
    workspace_path = getattr(getattr(exp, "experiment_workspace", None), "workspace_path", None)
    if workspace_path is None:
        return None
    return Path(workspace_path).name


def _workspace_id_from_runner_pkl(pkl_path: Path) -> str | None:
    try:
        with pkl_path.open("rb") as f:
            exp = pickle.load(f)
    except Exception:
        return None
    return _workspace_id_from_experiment(exp)


def _log_dir_reference_mtime(log_dir: Path) -> float:
    """Use latest session snapshot time when present, else log folder mtime."""
    for session_name in ("session_snapshots", "__session__"):
        session_root = log_dir / session_name
        if session_root.is_dir():
            mtimes = [p.stat().st_mtime for p in session_root.rglob("*") if p.is_file()]
            if mtimes:
                return max(mtimes)
    return log_dir.stat().st_mtime


def _list_ret_workspaces(workspace_root: Path) -> list[Path]:
    if not workspace_root.exists():
        return []
    return sorted(
        [p for p in workspace_root.iterdir() if p.is_dir() and (p / "ret.pkl").exists()],
        key=lambda p: p.stat().st_mtime,
    )


def _list_log_session_dirs(log_root: Path) -> list[Path]:
    if not log_root.exists():
        return []
    dirs = [
        p
        for p in log_root.iterdir()
        if p.is_dir()
        and ((p / "session_snapshots").is_dir() or (p / "__session__").is_dir())
    ]
    return sorted(dirs, key=_log_dir_reference_mtime)


def _load_manual_labels(log_root: Path, workspace_root: Path) -> dict[str, str]:
    path = log_root / LABELS_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    mapping: dict[str, str] = {}
    for ws_id, title in data.items():
        if not isinstance(ws_id, str) or not isinstance(title, str):
            continue
        if (workspace_root / ws_id / "ret.pkl").exists():
            mapping[ws_id] = title
    return mapping


def _workspace_id_from_session_dump(dump_path: Path) -> str | None:
    try:
        with dump_path.open("rb") as f:
            state = pickle.load(f)
    except Exception:
        return None
    loop_prev_out = getattr(state, "loop_prev_out", None)
    if not isinstance(loop_prev_out, dict):
        return None
    exp = loop_prev_out.get("factor_backtest")
    return _workspace_id_from_experiment(exp)


def _is_factor_backtest_dump(path: Path) -> bool:
    if path.is_file() and path.name == "workflow.snapshot.pkl":
        return "04_backtest" in path.as_posix() or "factor_backtest" in path.as_posix()
    return path.is_file() and path.name.endswith("factor_backtest")


def _map_from_session_dumps(log_root: Path, workspace_root: Path) -> dict[str, str]:
    """Each __session__/*/3_factor_backtest snapshot -> log folder name for that backtest workspace."""
    mapping: dict[str, str] = {}
    for log_dir in _list_log_session_dirs(log_root):
        for dump_path in log_dir.rglob("*"):
            if not _is_factor_backtest_dump(dump_path):
                continue
            ws_id = _workspace_id_from_session_dump(dump_path)
            if ws_id is None or not (workspace_root / ws_id / "ret.pkl").exists():
                continue
            mapping[ws_id] = log_dir.name
    return mapping


def _map_chronological(log_root: Path, workspace_root: Path) -> dict[str, str]:
    """1:1 map ret.pkl workspaces to log sessions by creation time (run01, run02_best, …)."""
    ws_dirs = _list_ret_workspaces(workspace_root)
    log_dirs = _list_log_session_dirs(log_root)
    if not ws_dirs or not log_dirs:
        return {}
    n = min(len(ws_dirs), len(log_dirs))
    return {ws_dirs[i].name: log_dirs[i].name for i in range(n)}


def _map_from_runner_pkls(log_root: Path, workspace_root: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not log_root.exists():
        return mapping
    for log_dir in log_root.iterdir():
        if not log_dir.is_dir():
            continue
        for pkl_path in log_dir.rglob("ef/runner result/**/*.pkl"):
            ws_id = _workspace_id_from_runner_pkl(pkl_path)
            if ws_id is None or not (workspace_root / ws_id / "ret.pkl").exists():
                continue
            mapping[ws_id] = log_dir.name
    return mapping


def build_workspace_log_titles(
    log_root: Path | str = DEFAULT_LOG_ROOT,
    workspace_root: Path | str = DEFAULT_WORKSPACE_ROOT,
) -> dict[str, str]:
    """
    Map workspace id (must have ret.pkl) -> log folder name (e.g. run02_best).

    Priority: manual labels > chronological 1:1 (by mtime) > __session__ dumps >
    ef/runner result pkl (only fills gaps). Chronological order matches renamed log
    folders (run01, run02_best, run03_…, run04_…) when each run produced one ret.pkl.
    """
    log_root = Path(log_root)
    workspace_root = Path(workspace_root)
    mapping = _load_manual_labels(log_root, workspace_root)

    for ws_id, title in _map_chronological(log_root, workspace_root).items():
        mapping.setdefault(ws_id, title)

    for ws_id, title in _map_from_session_dumps(log_root, workspace_root).items():
        mapping.setdefault(ws_id, title)

    for ws_id, title in _map_from_runner_pkls(log_root, workspace_root).items():
        mapping.setdefault(ws_id, title)

    return mapping


def format_workspace_label(
    workspace: Path,
    log_titles: dict[str, str] | None = None,
    all_workspaces: list[Path] | None = None,
) -> str:
    """Display label for selectbox; prefer matching log folder name."""
    log_titles = log_titles or {}
    title = log_titles.get(workspace.name)
    if title:
        if all_workspaces:
            same_title = sum(1 for w in all_workspaces if log_titles.get(w.name) == title)
            if same_title > 1:
                stamp = pd.Timestamp(workspace.stat().st_mtime, unit="s").strftime("%m-%d %H:%M")
                return f"{title}  ({stamp})"
        return title
    mtime = pd.Timestamp(workspace.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M")
    short_id = f"{workspace.name[:8]}…" if len(workspace.name) > 8 else workspace.name
    return f"{short_id}  ({mtime}，未匹配日志)"


def list_workspaces(root: Path | str = DEFAULT_WORKSPACE_ROOT) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    workspaces = [p for p in root.iterdir() if p.is_dir() and (p / "ret.pkl").exists()]
    return sorted(workspaces, key=lambda p: p.stat().st_mtime, reverse=True)


def _find_artifact(workspace: Path, filename: str) -> Optional[Path]:
    direct = workspace / filename
    if direct.exists():
        return direct
    matches = list(workspace.rglob(filename))
    return matches[0] if matches else None


def _load_positions(workspace: Path) -> dict:
    path = _find_artifact(workspace, "positions_normal_1day.pkl")
    if path is None:
        return {}
    return pd.read_pickle(path)


def _parse_trades_and_holdings(positions: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    if not positions:
        return pd.DataFrame(), pd.DataFrame()

    from qlib.contrib.report.analysis_position.parse_position import parse_position

    parsed = parse_position(positions)
    if parsed.empty:
        return pd.DataFrame(), pd.DataFrame()

    parsed = parsed.reset_index()
    parsed["datetime"] = pd.to_datetime(parsed["datetime"])
    parsed["status_label"] = parsed["status"].map({1: "买入", -1: "卖出", 0: "持有"})

    trades = parsed[parsed["status"] != 0].copy()
    holdings = parsed[parsed["status"] != -1].copy()
    return trades, holdings


def load_backtest(workspace: Path | str) -> BacktestArtifacts:
    workspace = Path(workspace)
    ret_path = workspace / "ret.pkl"
    if not ret_path.exists():
        raise FileNotFoundError(f"未找到 ret.pkl: {ret_path}")

    report = pd.read_pickle(ret_path)
    if not isinstance(report.index, pd.DatetimeIndex):
        report.index = pd.to_datetime(report.index)

    positions = _load_positions(workspace)
    trades, holdings = _parse_trades_and_holdings(positions)

    indicators_path = _find_artifact(workspace, "indicators_normal_1day.pkl")
    indicators = pd.read_pickle(indicators_path) if indicators_path else None
    if indicators is not None and not isinstance(indicators.index, pd.DatetimeIndex):
        indicators.index = pd.to_datetime(indicators.index)

    metrics_path = workspace / "qlib_res.csv"
    metrics = None
    if metrics_path.exists():
        metrics = pd.read_csv(metrics_path, index_col=0).squeeze()

    return BacktestArtifacts(
        workspace=workspace,
        report=report.sort_index(),
        positions=positions,
        indicators=indicators,
        metrics=metrics,
        trades=trades,
        holdings=holdings,
    )


def build_summary(report: pd.DataFrame) -> dict[str, float]:
    cum_return = report["return"].cumsum()
    cum_bench = report["bench"].cumsum()
    cum_excess = (report["return"] - report["bench"]).cumsum()
    cum_return_w_cost = (report["return"] - report["cost"]).cumsum()

    dd = cum_return - cum_return.cummax()
    max_dd = float(dd.min()) if len(dd) else 0.0

    return {
        "累计收益(不含成本)": float(cum_return.iloc[-1]) if len(cum_return) else 0.0,
        "累计收益(含成本)": float(cum_return_w_cost.iloc[-1]) if len(cum_return_w_cost) else 0.0,
        "基准累计收益": float(cum_bench.iloc[-1]) if len(cum_bench) else 0.0,
        "累计超额(不含成本)": float(cum_excess.iloc[-1]) if len(cum_excess) else 0.0,
        "最大回撤(不含成本)": max_dd,
        "平均日换手": float(report["turnover"].mean()) if "turnover" in report else 0.0,
        "累计手续费": float(report["cost"].sum()) if "cost" in report else 0.0,
        "期末总资产": float(report["account"].iloc[-1]) if "account" in report and len(report) else 0.0,
    }
