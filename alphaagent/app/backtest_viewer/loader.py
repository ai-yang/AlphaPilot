"""Load Qlib backtest artifacts from AlphaAgent workspace directories."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

DEFAULT_WORKSPACE_ROOT = Path(
    os.environ.get("ALPHAAGENT_BACKTEST_ROOT", Path.cwd() / "git_ignore_folder" / "RD-Agent_workspace")
)


@dataclass
class BacktestArtifacts:
    workspace: Path
    report: pd.DataFrame
    positions: dict
    indicators: Optional[pd.DataFrame]
    metrics: Optional[pd.Series]
    trades: pd.DataFrame
    holdings: pd.DataFrame


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
