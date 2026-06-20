"""Daily live-trade signal CLI module.

``alphapilot daily_signals`` — generate today's trades/holdings for a strategy given
yesterday's portfolio state (auto-rolled JSON). Reuses the backtest stack (model inference +
qlib one-day rebalance) via ``systems/backtest/live``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context
    from alphapilot.systems.backtest.live.types import DailyTradeResult


def _parse_yaml_params(raw: str | dict | None) -> dict | None:
    """Parse ``yaml_params`` (JSON string, ``.json``/``.yaml`` file path, or dict)."""
    if raw is None or isinstance(raw, dict):
        return raw
    import json

    text = str(raw).strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.exists():
        content = candidate.read_text(encoding="utf-8")
        if candidate.suffix.lower() in (".yaml", ".yml"):
            import yaml

            return yaml.safe_load(content)
        return json.loads(content)
    return json.loads(text)


def _records(df: Any, columns: list[str]) -> list[dict]:
    if df is None or getattr(df, "empty", True):
        return []
    cols = [c for c in columns if c in df.columns]
    return df[cols].to_dict("records") if cols else df.to_dict("records")


def summarize(result: "DailyTradeResult") -> dict[str, Any]:
    """CLI-friendly summary of a daily trade result."""
    scores = result.scores
    top_scores: list[dict] = []
    if scores is not None and len(scores) > 0:
        # ``scores`` spans [signal_day, execution_day]; show only the execution day's so each
        # instrument appears once (the holdings reflect this day).
        display = scores
        try:
            level0 = scores.index.get_level_values(0)
            display = scores[level0 == level0.max()]
        except Exception:  # noqa: BLE001 — single-level index, show as-is
            pass
        top = display.sort_values(ascending=False).head(10)
        top_scores = [
            {"instrument": idx[-1] if isinstance(idx, tuple) else idx, "score": float(val)}
            for idx, val in top.items()
        ]
    trade_cols = ["instrument", "amount", "price", "weight", "status_label"]
    return {
        "date": result.date,
        "new_cash": result.new_state.cash,
        "n_positions": len(result.new_state.positions),
        "trades": _records(result.trades, trade_cols),
        "holdings": _records(result.holdings, trade_cols),
        "top_scores": top_scores,
        "info": result.info,
    }


class DailyTradeModule(BaseModule):
    """CLI module for daily live-trade signal generation."""

    name = "daily_trade"

    def setup(self, context: "Context") -> None:
        self.context = context

    def daily_signals(
        self,
        strategy_name: str | None = None,
        factor_path: str | None = None,
        model_pickle_path: str | None = None,
        yaml_params: str | None = None,
        date: str | None = None,
        state_path: str | None = None,
        init_cash: float | None = None,
        refresh_data: bool = False,
        qlib_template_dir: str | None = None,
        market: str | None = None,
        factor_data_dir: str | None = None,
    ) -> dict[str, Any]:
        """Generate today's trade plan.

        Strategy source: ``--strategy_name`` (saved asset) and/or manual
        ``--factor_path`` + ``--model_pickle_path`` + ``--yaml_params``.
        ``--date`` defaults to the latest trading day. State auto-rolls in ``--state_path``.
        ``--market`` / ``--factor_data_dir`` override the factor h5 universe (default: the
        strategy asset's recorded market).
        """
        from alphapilot.systems.backtest.live import DailySignalRequest, generate_daily_signal

        request = DailySignalRequest(
            strategy_name=strategy_name,
            factor_path=factor_path,
            model_pickle_path=model_pickle_path,
            yaml_params=_parse_yaml_params(yaml_params),
            date=date,
            state_path=state_path,
            init_cash=init_cash,
            refresh_data=refresh_data,
            qlib_template_dir=qlib_template_dir,
            market=market,
            factor_data_dir=factor_data_dir,
            use_local=self.context.config.backtest.use_local,
        )
        return summarize(generate_daily_signal(self.context, request))

    def daily_state(
        self,
        strategy_name: str | None = None,
        state_path: str | None = None,
    ) -> dict[str, Any]:
        """Show the current saved portfolio state for a strategy."""
        from alphapilot.systems.backtest.live.portfolio_state import load_state
        from alphapilot.systems.backtest.live.service import _default_state_path, _safe_name

        path = (
            Path(state_path)
            if state_path
            else _default_state_path(strategy_name or "manual")
        )
        state = load_state(path)
        if state is None:
            return {"state_path": str(path), "exists": False}
        return {
            "state_path": str(path),
            "exists": True,
            "date": state.date,
            "cash": state.cash,
            "n_positions": len(state.positions),
            "positions": state.positions,
        }

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "daily_signals": self.daily_signals,
            "daily_state": self.daily_state,
        }
