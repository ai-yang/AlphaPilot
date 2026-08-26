"""Fail-closed statistical and economic gates for the five-day campaign."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from alphapilot.components.coder.factor_coder.factor_ast import (
    BinaryOpNode,
    ConditionalNode,
    FunctionNode,
    Node,
    NumberNode,
    VarNode,
    find_largest_common_subtree,
    parse_expression,
)
from alphapilot.systems.backtest.report_metrics import average_daily_turnover


@dataclass(frozen=True)
class FactorGateConfig:
    min_finite_coverage: float = 0.95
    min_nonconstant_day_ratio: float = 0.95
    min_abs_mean_rank_ic: float = 0.015
    min_abs_rank_icir: float = 0.30
    min_month_direction_ratio: float = 0.55
    max_lookback: int = 120
    max_abs_spearman: float = 0.75


@dataclass(frozen=True)
class EconomicGateConfig:
    annualization: int = 252
    min_annualized_excess: float = 0.03
    min_information_ratio: float = 0.50
    max_drawdown: float = 0.15
    min_positive_six_month_ratio: float = 0.60
    max_average_daily_turnover: float = 0.20
    six_month_trading_days: int = 126


_WINDOW_FUNCTIONS = {
    "mean",
    "std",
    "sum",
    "max",
    "min",
    "median",
    "quantile",
    "rank",
    "ts_mean",
    "ts_std",
    "ts_sum",
    "ts_max",
    "ts_min",
    "ts_median",
    "ts_rank",
    "ts_quantile",
    "delay",
    "delta",
    "ref",
    "slope",
    "rsquare",
    "resi",
    "wma",
    "ema",
    "corr",
    "cov",
}


def _walk(node: Node) -> Iterable[Node]:
    yield node
    if isinstance(node, FunctionNode):
        for arg in node.args:
            yield from _walk(arg)
    elif isinstance(node, BinaryOpNode):
        yield from _walk(node.left)
        yield from _walk(node.right)
    elif isinstance(node, ConditionalNode):
        yield from _walk(node.condition)
        yield from _walk(node.true_expr)
        yield from _walk(node.false_expr)


def _node_size(node: Node) -> int:
    if isinstance(node, (NumberNode, VarNode)):
        return 1
    if isinstance(node, FunctionNode):
        return 1 + sum(_node_size(arg) for arg in node.args)
    if isinstance(node, BinaryOpNode):
        return 1 + _node_size(node.left) + _node_size(node.right)
    if isinstance(node, ConditionalNode):
        return (
            1
            + _node_size(node.condition)
            + _node_size(node.true_expr)
            + _node_size(node.false_expr)
        )
    return 0


def validate_factor_expression(
    expression: str,
    *,
    max_lookback: int = 120,
) -> dict[str, Any]:
    """Parse an expression and reject future references or overlong windows."""

    errors: list[str] = []
    try:
        tree = parse_expression(expression)
    except Exception as exc:  # noqa: BLE001
        return {
            "passed": False,
            "factor_ast": "",
            "max_lookback": 0,
            "errors": [f"parse_error: {exc}"],
        }

    observed_lookback = 0
    for node in _walk(tree):
        if not isinstance(node, FunctionNode):
            continue
        function = str(node.name).strip().lower()
        if function not in _WINDOW_FUNCTIONS or len(node.args) < 2:
            continue
        numeric_args = [arg.value for arg in node.args[1:] if isinstance(arg, NumberNode)]
        if not numeric_args:
            continue
        # Ref/Delay/Delta use their second argument as a lag. In this factor DSL,
        # positive values mean historical observations and negative values are future data.
        if function in {"ref", "delay", "delta"}:
            lag = numeric_args[0]
            if lag < 0:
                errors.append(f"future reference is forbidden: {node}")
                continue
            observed_lookback = max(observed_lookback, int(math.ceil(lag)))
        else:
            positive_windows = [value for value in numeric_args if value > 0]
            if positive_windows:
                observed_lookback = max(
                    observed_lookback,
                    int(math.ceil(max(positive_windows))),
                )
        if observed_lookback > max_lookback:
            errors.append(
                f"lookback {observed_lookback} exceeds maximum {max_lookback}"
            )
            break

    return {
        "passed": not errors,
        "factor_ast": str(tree),
        "max_lookback": observed_lookback,
        "errors": errors,
    }


def _index_levels(index: pd.Index) -> tuple[str | int, str | int]:
    if not isinstance(index, pd.MultiIndex) or index.nlevels < 2:
        raise ValueError("factor and label must use a (datetime, instrument) MultiIndex")
    names = list(index.names)
    date_level: str | int = "datetime" if "datetime" in names else 0
    other = [name for name in names if name != date_level]
    instrument_level: str | int = other[0] if other else 1
    return date_level, instrument_level


def _daily_rank_ic(factor: pd.Series, label: pd.Series) -> pd.Series:
    pair = pd.concat(
        [pd.to_numeric(factor, errors="coerce").rename("factor"),
         pd.to_numeric(label, errors="coerce").rename("label")],
        axis=1,
        join="inner",
    ).replace([np.inf, -np.inf], np.nan)
    date_level, _ = _index_levels(pair.index)
    rows: dict[pd.Timestamp, float] = {}
    for date, group in pair.groupby(level=date_level, sort=True):
        valid = group.dropna()
        if (
            len(valid) < 2
            or valid["factor"].nunique(dropna=True) < 2
            or valid["label"].nunique(dropna=True) < 2
        ):
            rows[pd.Timestamp(date)] = float("nan")
            continue
        rows[pd.Timestamp(date)] = float(
            valid["factor"].corr(valid["label"], method="spearman")
        )
    return pd.Series(rows, name="rank_ic", dtype=float).sort_index()


def calibrate_factor_direction(factor: pd.Series, label: pd.Series) -> int:
    """Freeze direction from the calibration (train + validation) period."""

    mean_ic = float(_daily_rank_ic(factor, label).mean())
    if not math.isfinite(mean_ic) or mean_ic == 0:
        raise ValueError("factor direction cannot be calibrated from a zero/non-finite RankIC")
    return 1 if mean_ic > 0 else -1


def evaluate_factor_gate(
    factor: pd.Series,
    label: pd.Series,
    *,
    direction: int,
    expression: str | None = None,
    config: FactorGateConfig | None = None,
) -> dict[str, Any]:
    """Evaluate one factor on the development period with a frozen direction."""

    cfg = config or FactorGateConfig()
    if direction not in {-1, 1}:
        raise ValueError("direction must be +1 or -1 and frozen before development")
    values = pd.to_numeric(factor, errors="coerce").replace([np.inf, -np.inf], np.nan)
    date_level, _ = _index_levels(values.index)
    coverage = float(values.notna().mean()) if len(values) else 0.0
    by_day = values.groupby(level=date_level)
    nonconstant_ratio = float(
        by_day.apply(lambda series: series.dropna().nunique() >= 2).mean()
    ) if len(values) else 0.0
    raw_daily_ic = _daily_rank_ic(values, label).dropna()
    adjusted_ic = raw_daily_ic * direction
    mean_rank_ic = float(adjusted_ic.mean()) if len(adjusted_ic) else float("nan")
    std_rank_ic = float(adjusted_ic.std(ddof=1)) if len(adjusted_ic) > 1 else float("nan")
    rank_icir = (
        mean_rank_ic / std_rank_ic
        if math.isfinite(std_rank_ic) and std_rank_ic > 0
        else float("nan")
    )
    monthly = adjusted_ic.groupby(adjusted_ic.index.to_period("M")).mean()
    month_direction_ratio = float((monthly > 0).mean()) if len(monthly) else 0.0
    static = (
        validate_factor_expression(expression, max_lookback=cfg.max_lookback)
        if expression is not None
        else {"passed": True, "factor_ast": "", "max_lookback": 0, "errors": []}
    )
    failures: list[str] = list(static["errors"])
    checks = {
        "finite_coverage": coverage >= cfg.min_finite_coverage,
        "nonconstant_day_ratio": nonconstant_ratio >= cfg.min_nonconstant_day_ratio,
        "mean_rank_ic": math.isfinite(mean_rank_ic)
        and abs(mean_rank_ic) >= cfg.min_abs_mean_rank_ic,
        "rank_icir": math.isfinite(rank_icir)
        and abs(rank_icir) >= cfg.min_abs_rank_icir,
        "month_direction_ratio": month_direction_ratio
        >= cfg.min_month_direction_ratio,
        "expression": bool(static["passed"]),
    }
    failures.extend(name for name, passed in checks.items() if not passed and name != "expression")
    return {
        "passed": all(checks.values()),
        "direction": direction,
        "finite_coverage": coverage,
        "nonconstant_day_ratio": nonconstant_ratio,
        "mean_rank_ic": mean_rank_ic,
        "rank_icir": rank_icir,
        "month_direction_ratio": month_direction_ratio,
        "rank_ic_days": int(len(adjusted_ic)),
        "rank_ic_months": int(len(monthly)),
        "expression_validation": static,
        "thresholds": asdict(cfg),
        "checks": checks,
        "failures": failures,
    }


def _expressions_equivalent(left: str, right: str) -> bool:
    left_tree = parse_expression(left)
    right_tree = parse_expression(right)
    if _node_size(left_tree) != _node_size(right_tree):
        return False
    match = find_largest_common_subtree(left_tree, right_tree)
    return match is not None and match.size == _node_size(left_tree)


def _mean_daily_spearman(left: pd.Series, right: pd.Series) -> float:
    pair = pd.concat([left.rename("left"), right.rename("right")], axis=1).dropna()
    if pair.empty:
        return float("nan")
    date_level, _ = _index_levels(pair.index)
    correlations: list[float] = []
    for _, group in pair.groupby(level=date_level):
        if len(group) < 2 or group["left"].nunique() < 2 or group["right"].nunique() < 2:
            continue
        value = float(group["left"].corr(group["right"], method="spearman"))
        if math.isfinite(value):
            correlations.append(value)
    return float(np.mean(correlations)) if correlations else float("nan")


def select_diverse_factors(
    candidates: Iterable[dict[str, Any]],
    *,
    max_factors: int,
    max_abs_spearman: float = 0.75,
    source_limits: dict[str, int] | None = None,
    hypothesis_limit: int | None = None,
) -> dict[str, Any]:
    """Greedily select qualified factors while enforcing AST/correlation limits.

    Each candidate must carry ``name``, ``expression``, ``values`` (Series) and
    optionally ``score``, ``source`` and ``hypothesis``. Higher scores win.
    """

    if max_factors <= 0:
        raise ValueError("max_factors must be positive")
    ranked = sorted(
        list(candidates),
        key=lambda item: (-float(item.get("score", 0.0)), str(item.get("name", ""))),
    )
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    hypothesis_counts: dict[str, int] = {}
    correlations: dict[str, float] = {}
    for candidate in ranked:
        if len(selected) >= max_factors:
            rejected.append({"name": candidate.get("name"), "reason": "capacity"})
            continue
        source = str(candidate.get("source") or "")
        hypothesis = str(candidate.get("hypothesis") or "")
        if source_limits and source in source_limits and source_counts.get(source, 0) >= source_limits[source]:
            rejected.append({"name": candidate.get("name"), "reason": "source_limit"})
            continue
        if hypothesis_limit is not None and hypothesis and hypothesis_counts.get(hypothesis, 0) >= hypothesis_limit:
            rejected.append({"name": candidate.get("name"), "reason": "hypothesis_limit"})
            continue
        static = validate_factor_expression(str(candidate["expression"]))
        if not static["passed"]:
            rejected.append({"name": candidate.get("name"), "reason": "expression", "details": static["errors"]})
            continue
        duplicate = next(
            (
                item
                for item in selected
                if _expressions_equivalent(
                    str(candidate["expression"]), str(item["expression"])
                )
            ),
            None,
        )
        if duplicate is not None:
            rejected.append({"name": candidate.get("name"), "reason": "duplicate_ast", "with": duplicate["name"]})
            continue
        violation: tuple[str, float] | None = None
        for item in selected:
            correlation = _mean_daily_spearman(candidate["values"], item["values"])
            correlations[f"{candidate['name']}::{item['name']}"] = correlation
            if not math.isfinite(correlation) or abs(correlation) >= max_abs_spearman:
                violation = (str(item["name"]), correlation)
                break
        if violation is not None:
            rejected.append(
                {
                    "name": candidate.get("name"),
                    "reason": "correlation",
                    "with": violation[0],
                    "spearman": violation[1],
                }
            )
            continue
        selected.append(candidate)
        source_counts[source] = source_counts.get(source, 0) + 1
        if hypothesis:
            hypothesis_counts[hypothesis] = hypothesis_counts.get(hypothesis, 0) + 1
    return {
        "selected": selected,
        "selected_names": [item["name"] for item in selected],
        "rejected": rejected,
        "correlations": correlations,
    }


def _compound(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty or (clean <= -1).any():
        return float("nan")
    return float((1.0 + clean).prod() - 1.0)


def _annualize(total_return: float, observations: int, annualization: int) -> float:
    if observations <= 0 or not math.isfinite(total_return) or total_return <= -1:
        return float("nan")
    return float((1.0 + total_return) ** (annualization / observations) - 1.0)


def evaluate_economic_gate(
    report: pd.DataFrame,
    *,
    baseline_metrics: dict[str, float],
    config: EconomicGateConfig | None = None,
) -> dict[str, Any]:
    """Evaluate the single sealed champion against the pre-registered blind gates."""

    cfg = config or EconomicGateConfig()
    required = {"benchmark_return", "cost", "turnover"}
    missing = sorted(required - set(report.columns))
    return_column = "net_return" if "net_return" in report.columns else "strategy_return"
    if return_column not in report.columns:
        missing.append("net_return|strategy_return")
    if missing:
        raise ValueError(f"economic gate report is missing columns: {', '.join(missing)}")
    frame = report.sort_index().copy()
    for column in (return_column, "benchmark_return", "cost", "turnover"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    # Turnover is an execution-intensity metric.  Do not drop a bad bar and
    # silently aggregate a partial trading day.
    average_turnover = average_daily_turnover(frame[["turnover"]])
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(
        subset=[return_column, "benchmark_return", "cost", "turnover"]
    )
    if frame.empty:
        raise ValueError("economic gate report has no finite observations")
    net = frame[return_column]
    benchmark = frame["benchmark_return"]
    excess = (1.0 + net) / (1.0 + benchmark) - 1.0
    total_excess = _compound(excess)
    annualized_excess = _annualize(total_excess, len(excess), cfg.annualization)
    excess_std = float(excess.std(ddof=1))
    information_ratio = (
        float(excess.mean() / excess_std * math.sqrt(cfg.annualization))
        if math.isfinite(excess_std) and excess_std > 0
        else float("nan")
    )
    equity = (1.0 + net).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = abs(float(drawdown.min()))
    gross = (
        pd.to_numeric(frame["gross_return"], errors="coerce")
        if "gross_return" in frame.columns
        else net + frame["cost"]
    )
    doubled_net = gross - 2.0 * frame["cost"]
    doubled_excess = (1.0 + doubled_net) / (1.0 + benchmark) - 1.0
    doubled_total_return = _compound(doubled_net)
    doubled_total_excess = _compound(doubled_excess)
    window = cfg.six_month_trading_days
    rolling_values: list[float] = []
    for end in range(window, len(excess) + 1):
        rolling_values.append(_compound(excess.iloc[end - window : end]))
    positive_rolling_ratio = (
        float(np.mean([value > 0 for value in rolling_values if math.isfinite(value)]))
        if rolling_values and any(math.isfinite(value) for value in rolling_values)
        else 0.0
    )
    baseline_excess = float(baseline_metrics.get("annualized_excess", float("nan")))
    baseline_ir = float(baseline_metrics.get("information_ratio", float("nan")))
    checks = {
        "annualized_excess": annualized_excess >= cfg.min_annualized_excess,
        "information_ratio": information_ratio >= cfg.min_information_ratio,
        "max_drawdown": max_drawdown <= cfg.max_drawdown,
        "double_cost_net_positive": doubled_total_return > 0,
        "double_cost_excess_positive": doubled_total_excess > 0,
        "positive_six_month_ratio": positive_rolling_ratio
        >= cfg.min_positive_six_month_ratio,
        "average_daily_turnover": average_turnover
        <= cfg.max_average_daily_turnover,
        "not_below_baseline_excess": math.isfinite(baseline_excess)
        and annualized_excess >= baseline_excess,
        "not_below_baseline_ir": math.isfinite(baseline_ir)
        and information_ratio >= baseline_ir,
    }
    metrics = {
        "annualized_excess": annualized_excess,
        "information_ratio": information_ratio,
        "max_drawdown": max_drawdown,
        "double_cost_total_return": doubled_total_return,
        "double_cost_total_excess": doubled_total_excess,
        "positive_six_month_ratio": positive_rolling_ratio,
        "average_daily_turnover": average_turnover,
        "observations": len(frame),
    }
    return {
        "passed": all(checks.values()),
        "metrics": metrics,
        "checks": checks,
        "failures": [name for name, passed in checks.items() if not passed],
        "thresholds": asdict(cfg),
        "baseline_metrics": dict(baseline_metrics),
    }


def choose_development_champion(candidates: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Pick one eligible development champion using the pre-registered tie-breaks."""

    eligible = [item for item in candidates if item.get("passed", True)]
    if not eligible:
        raise ValueError("no development candidate passed its gates")
    return min(
        eligible,
        key=lambda item: (
            -float(item["net_information_ratio"]),
            int(item["factor_count"]),
            float(item["average_daily_turnover"]),
            str(item.get("name", "")),
        ),
    )
