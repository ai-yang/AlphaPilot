"""Shared output pipeline for the AlphaForge-derived miners.

Takes the mined alphagen ``Expression`` objects (+ optional scores), translates
each into alphapilot DSL, validates / adds them to the factor zoo, and
optionally backtests the accepted set through the backtest system. Everything
downstream of here speaks alphapilot's native factor language only.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Sequence

from alphapilot.modules.alphaforge.translate import try_translate

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def _ranked(exprs: Sequence[Any], scores: Sequence[float] | None) -> list[tuple[Any, float | None]]:
    """Pair exprs with scores, best (|score|) first when scores are present."""
    if scores is None or len(scores) != len(exprs):
        return [(e, None) for e in exprs]
    paired = list(zip(exprs, scores))
    paired.sort(key=lambda es: abs(es[1]) if es[1] is not None else 0.0, reverse=True)
    return paired


def emit_factors(
    context: "Context",
    exprs: Sequence[Any],
    scores: Sequence[float] | None = None,
    *,
    source: str,
    backtest: bool = False,
    save: bool = True,
    qlib_config_name: str | None = None,
) -> dict[str, Any]:
    """Translate -> validate/add -> (optional) backtest a batch of mined factors.

    Returns a summary dict: counts, accepted factor (name, dsl, score) tuples,
    rejected/untranslatable details, and backtest metrics when requested.
    """
    factor_sys = context.factor()
    run_id = time.strftime("%m%d%H%M%S")

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    untranslatable = 0

    for i, (expr, score) in enumerate(_ranked(exprs, scores)):
        dsl = try_translate(expr)
        if dsl is None:
            untranslatable += 1
            continue

        name = f"{source}_{run_id}_{i:03d}"
        if save:
            try:
                # Auto-tag every mined factor with its source method (e.g.
                # ``alphaforge_gp``). Defer the CSV mirror to one save after the loop.
                result = factor_sys.add_factor(name, dsl, categories=[source], save=False)
            except Exception as exc:  # noqa: BLE001 - never let one factor abort the batch
                rejected.append({"name": name, "dsl": dsl, "reason": f"add_factor error: {exc}"})
                continue
            if getattr(result, "acceptable", False):
                accepted.append({"name": name, "dsl": dsl, "score": score})
            else:
                rejected.append({
                    "name": name, "dsl": dsl,
                    "code": getattr(result, "code", None),
                    "reason": getattr(result, "message", "rejected"),
                })
        else:
            if factor_sys.is_acceptable(dsl):
                accepted.append({"name": name, "dsl": dsl, "score": score})
            else:
                rejected.append({"name": name, "dsl": dsl, "reason": "not acceptable"})

    if save and accepted:
        factor_sys.database.save()  # single CSV re-materialization for the batch

    summary: dict[str, Any] = {
        "source": source,
        "mined": len(exprs),
        "untranslatable": untranslatable,
        "accepted": accepted,
        "rejected": rejected,
        "n_accepted": len(accepted),
        "n_rejected": len(rejected),
    }

    if backtest and accepted:
        summary["backtest"] = _run_backtest(context, accepted, source, qlib_config_name)

    return summary


def _run_backtest(
    context: "Context",
    accepted: list[dict[str, Any]],
    source: str,
    qlib_config_name: str | None,
) -> dict[str, Any]:
    """Backtest the accepted factor set via the backtest system."""
    from alphapilot.systems.backtest.types import FactorBacktestRequest, FactorDefinition

    request = FactorBacktestRequest(
        factors=[FactorDefinition(factor_name=a["name"], factor_expression=a["dsl"]) for a in accepted],
        scenario="factor_backtest",
        qlib_config_name=qlib_config_name,
        use_local=context.config.backtest.use_local,
    )
    try:
        result = context.backtest().run_factor_evaluation(request)
        return {"ok": True, "metrics": getattr(result, "metrics", None)}
    except Exception as exc:  # noqa: BLE001 - surface but don't lose mining results
        return {"ok": False, "error": str(exc)}
