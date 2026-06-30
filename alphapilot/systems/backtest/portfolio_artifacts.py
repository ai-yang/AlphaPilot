"""Export Qlib portfolio backtest artifacts (daily report, trades, holdings)."""

from __future__ import annotations

import json
import pickle
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from alphapilot.log import logger
from alphapilot.systems.backtest.artifacts import (
    build_summary,
    find_artifact,
    parse_trades_and_holdings,
)
from alphapilot.systems.data.frequency import FREQUENCIES, portfolio_artifact_names


def _find_portfolio_artifact(workspace: Path, kind: str) -> Path | None:
    """Find a PortAnaRecord artifact (``report``/``positions``/``indicators``),
    tolerating the rebalance-freq filename tag: tries daily (``1day``) first for
    back-compat, then intraday variants (``5min`` ...)."""
    for freq in FREQUENCIES:
        name = portfolio_artifact_names(freq)[kind]
        path = find_artifact(workspace, name)
        if path is not None:
            return path
    return None


def _resolve_daily_report(workspace: Path) -> tuple[pd.DataFrame, Path | None]:
    """Load portfolio report from ret.pkl or qlib mlruns artifact (any freq tag)."""
    ret_path = workspace / "ret.pkl"
    if ret_path.exists():
        report = pd.read_pickle(ret_path)
        return report, ret_path

    report_path = _find_portfolio_artifact(workspace, "report")
    if report_path is not None:
        report = pd.read_pickle(report_path)
        return report, report_path

    raise FileNotFoundError(
        f"ret.pkl / report_normal_*.pkl not found under workspace: {workspace}"
    )


def build_portfolio_summary(report: pd.DataFrame) -> dict[str, float]:
    """Portfolio summary for export; ``{}`` when there is nothing to summarize."""
    if report.empty or "return" not in report.columns:
        return {}
    return build_summary(report)


def export_portfolio_to_dir(workspace: Path | str, dest_dir: Path | str) -> dict[str, str]:
    """
    Persist daily backtest artifacts under *dest_dir*.

    Returns a map of logical name -> relative filename (under dest_dir).
    """
    workspace = Path(workspace).resolve()
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    exported: dict[str, str] = {}

    report, ret_source = _resolve_daily_report(workspace)
    if not isinstance(report.index, pd.DatetimeIndex):
        report.index = pd.to_datetime(report.index)
    report = report.sort_index()

    daily_report_path = dest_dir / "daily_report.csv"
    report.to_csv(daily_report_path, encoding="utf-8-sig")
    exported["daily_report"] = daily_report_path.name

    summary_path = dest_dir / "portfolio_summary.json"
    summary_path.write_text(
        json.dumps(build_portfolio_summary(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    exported["portfolio_summary"] = summary_path.name

    metrics_src = workspace / "qlib_res.csv"
    if metrics_src.exists():
        metrics_dst = dest_dir / "qlib_metrics.csv"
        shutil.copy2(metrics_src, metrics_dst)
        exported["qlib_metrics"] = metrics_dst.name

    positions_path = _find_portfolio_artifact(workspace, "positions")
    if positions_path is not None:
        positions_dst = dest_dir / positions_path.name
        shutil.copy2(positions_path, positions_dst)
        exported["positions_raw"] = positions_dst.name

        with positions_dst.open("rb") as f:
            positions = pickle.load(f)
        trades, holdings = parse_trades_and_holdings(positions)

        if not trades.empty:
            trades_path = dest_dir / "daily_trades.csv"
            trades.to_csv(trades_path, index=False, encoding="utf-8-sig")
            exported["daily_trades"] = trades_path.name

        if not holdings.empty:
            holdings_path = dest_dir / "daily_holdings.csv"
            holdings.to_csv(holdings_path, index=False, encoding="utf-8-sig")
            exported["daily_holdings"] = holdings_path.name

            pivot_cols = [c for c in ("weight", "amount", "price") if c in holdings.columns]
            if pivot_cols and "instrument" in holdings.columns and "datetime" in holdings.columns:
                for col in pivot_cols:
                    try:
                        wide = holdings.pivot_table(
                            index="datetime",
                            columns="instrument",
                            values=col,
                            aggfunc="last",
                        )
                        wide_path = dest_dir / f"position_{col}_wide.csv"
                        wide.to_csv(wide_path, encoding="utf-8-sig")
                        exported[f"position_{col}_wide"] = wide_path.name
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(f"Skip position pivot {col}: {exc}")

    indicators_path = _find_portfolio_artifact(workspace, "indicators")
    if indicators_path is not None:
        indicators_dst = dest_dir / indicators_path.name
        shutil.copy2(indicators_path, indicators_dst)
        exported["indicators_raw"] = indicators_dst.name

        indicators = pd.read_pickle(indicators_dst)
        if isinstance(indicators, pd.DataFrame) and not indicators.empty:
            if not isinstance(indicators.index, pd.DatetimeIndex):
                indicators.index = pd.to_datetime(indicators.index)
            ind_csv = dest_dir / "daily_indicators.csv"
            indicators.to_csv(ind_csv, encoding="utf-8-sig")
            exported["daily_indicators"] = ind_csv.name

    manifest = {
        "workspace_path": str(workspace),
        "files": exported,
    }
    manifest_path = dest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    exported["manifest"] = manifest_path.name

    logger.info(f"[portfolio_export] saved {len(exported)} files to {dest_dir}")
    return exported
