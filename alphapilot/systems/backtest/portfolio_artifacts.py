"""Export Qlib portfolio backtest artifacts (daily report, trades, holdings)."""

from __future__ import annotations

import json
import pickle
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from alphapilot.log import logger


def _find_artifact(workspace: Path, filename: str) -> Path | None:
    direct = workspace / filename
    if direct.exists():
        return direct
    matches = list(workspace.rglob(filename))
    return matches[0] if matches else None


def _resolve_daily_report(workspace: Path) -> tuple[pd.DataFrame, Path | None]:
    """Load daily portfolio report from ret.pkl or qlib mlruns artifact."""
    ret_path = workspace / "ret.pkl"
    if ret_path.exists():
        report = pd.read_pickle(ret_path)
        return report, ret_path

    report_path = _find_artifact(workspace, "report_normal_1day.pkl")
    if report_path is not None:
        report = pd.read_pickle(report_path)
        return report, report_path

    raise FileNotFoundError(
        f"ret.pkl / report_normal_1day.pkl not found under workspace: {workspace}"
    )


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


def build_portfolio_summary(report: pd.DataFrame) -> dict[str, float]:
    if report.empty or "return" not in report.columns:
        return {}

    cum_return = report["return"].cumsum()
    cum_bench = report["bench"].cumsum() if "bench" in report.columns else pd.Series(dtype=float)
    cum_excess = (report["return"] - report["bench"]).cumsum() if "bench" in report.columns else cum_return
    cum_return_w_cost = (
        (report["return"] - report["cost"]).cumsum() if "cost" in report.columns else cum_return
    )

    dd = cum_return - cum_return.cummax()
    max_dd = float(dd.min()) if len(dd) else 0.0

    return {
        "累计收益(不含成本)": float(cum_return.iloc[-1]) if len(cum_return) else 0.0,
        "累计收益(含成本)": float(cum_return_w_cost.iloc[-1]) if len(cum_return_w_cost) else 0.0,
        "基准累计收益": float(cum_bench.iloc[-1]) if len(cum_bench) else 0.0,
        "累计超额(不含成本)": float(cum_excess.iloc[-1]) if len(cum_excess) else 0.0,
        "最大回撤(不含成本)": max_dd,
        "平均日换手": float(report["turnover"].mean()) if "turnover" in report.columns else 0.0,
        "累计手续费": float(report["cost"].sum()) if "cost" in report.columns else 0.0,
        "期末总资产": float(report["account"].iloc[-1]) if "account" in report.columns and len(report) else 0.0,
    }


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

    positions_path = _find_artifact(workspace, "positions_normal_1day.pkl")
    if positions_path is not None:
        positions_dst = dest_dir / "positions_normal_1day.pkl"
        shutil.copy2(positions_path, positions_dst)
        exported["positions_raw"] = positions_dst.name

        with positions_dst.open("rb") as f:
            positions = pickle.load(f)
        trades, holdings = _parse_trades_and_holdings(positions)

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

    indicators_path = _find_artifact(workspace, "indicators_normal_1day.pkl")
    if indicators_path is not None:
        indicators_dst = dest_dir / "indicators_normal_1day.pkl"
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
