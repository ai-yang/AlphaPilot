"""One trading-day forward step via qlib's backtest, seeded with the current account.

Mirrors ``PortAnaRecord``'s strategy/executor/exchange config (qlib ``record_temp.py``) but:
- runs a single day (``start==end``),
- seeds the initial account with the current cash + holdings
  (``create_account_instance`` accepts ``{"cash": x, <stock>: shares, ...}``),
- injects today's model scores as a *static* strategy signal (no model training).

Returns today's trades (computed as the yesterday->today position diff) and holdings plus the
resulting :class:`PortfolioState`.
"""

from __future__ import annotations

import math
from typing import Any

from alphapilot.log import logger
from alphapilot.systems.backtest.live.types import PortfolioState

_EXECUTOR_CONFIG = {
    "class": "SimulatorExecutor",
    "module_path": "qlib.backtest.executor",
    "kwargs": {
        "time_per_step": "day",
        "generate_portfolio_metrics": True,
        "verbose": False,
    },
}


def _coerce_params(yaml_params: Any):
    from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams

    if yaml_params is None:
        return QlibYamlParams.defaults_for("combined")
    if isinstance(yaml_params, QlibYamlParams):
        return yaml_params
    return QlibYamlParams.model_validate(yaml_params)


def build_strategy_config(params: Any, scores: Any) -> dict:
    """qlib strategy config with today's scores injected as a static signal."""
    strat_kwargs = dict(params.effective_strategy_kwargs)
    strat_kwargs["signal"] = scores  # replace the "<PRED>" placeholder with real scores
    return {
        "class": params.strategy_class,
        "module_path": params.strategy_module,
        "kwargs": strat_kwargs,
    }


def _lot_size(params: Any) -> int:
    """Board-lot size from params (A-shares = 100); ``0`` disables lot constraints."""
    try:
        return max(0, int(getattr(params, "trade_unit", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _round_to_lot(amount: float, unit: int) -> float:
    """Floor ``amount`` down to a whole multiple of ``unit``; ``unit<=0`` passes through."""
    if unit and unit > 0:
        return math.floor(float(amount) / unit) * unit
    return float(amount)


def build_exchange_kwargs(params: Any) -> dict:
    kwargs: dict[str, Any] = {
        "limit_threshold": params.limit_threshold,
        "deal_price": ["$open", "$close"],
        "open_cost": params.open_cost,
        "close_cost": params.close_cost,
        "min_cost": params.min_cost,
    }
    unit = _lot_size(params)
    if unit > 0:
        # Constrain qlib's simulated fills to whole board lots. qlib only honours ``trade_unit``
        # when the data carries a valid ``$factor`` (non-adjusted-price mode); otherwise it warns
        # and ignores it. We also round the *reported* plan to lots in ``run_one_day`` so the
        # buy/sell amounts are clean regardless of qlib's internal price mode.
        kwargs["trade_unit"] = unit
    return kwargs


def _min_score_date(scores: Any) -> str | None:
    try:
        import pandas as pd

        dts = scores.index.get_level_values(0)
        return pd.Timestamp(min(dts)).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return None


def _fetch_close(stocks: Any, date: str) -> dict:
    """Latest available ``$close`` at/just before ``date`` for ``stocks`` (qlib must be inited)."""
    stocks = [s for s in stocks if s != "cash"]
    if not stocks:
        return {}
    import pandas as pd
    from qlib.data import D

    d = pd.Timestamp(date)
    df = D.features(
        list(stocks), ["$close"], d - pd.Timedelta(days=15), d, freq="day", disk_cache=True
    ).dropna()
    if df.empty:
        return {}
    # keep the latest row per instrument, then collapse the (instrument, datetime) index to the
    # instrument code so callers can look up by plain code.
    tail = df.groupby("instrument", group_keys=False).tail(1)["$close"]
    tail.index = tail.index.get_level_values("instrument")
    return {str(code): float(px) for code, px in tail.items()}


def _seed_with_prices(account_seed: dict, start_date: str) -> tuple[dict, list[str]]:
    """Attach explicit seed prices so qlib's ``fill_stock_value`` is skipped.

    Drops any held stock with no resolvable close at ``start_date`` (e.g. suspended) so the
    backtest never raises; returns ``(seed_with_prices, dropped_codes)``.
    """
    import pandas as pd

    out: dict[str, object] = {"cash": float(account_seed.get("cash", 0.0))}
    stocks = [k for k in account_seed if k != "cash"]
    if not stocks:
        return out, []
    px = _fetch_close(stocks, start_date)
    dropped: list[str] = []
    for s in stocks:
        raw = account_seed[s]
        amt = raw["amount"] if isinstance(raw, dict) else raw
        if s in px and pd.notna(px[s]):
            out[s] = {"amount": float(amt), "price": float(px[s])}
        else:
            dropped.append(s)
    return out, dropped


def _compute_trades(seed_amounts: dict, final_positions: dict, prices: dict) -> Any:
    """Trades = today's positions minus yesterday's (share delta), with buy/sell direction."""
    import pandas as pd

    rows = []
    for code in sorted(set(seed_amounts) | set(final_positions)):
        before = float(seed_amounts.get(code, 0.0))
        after = float(final_positions.get(code, 0.0))
        delta = after - before
        if abs(delta) < 1e-6:
            continue
        status = 1 if delta > 0 else -1
        rows.append({
            "instrument": code, "amount": abs(delta), "price": prices.get(code, float("nan")),
            "status": status, "status_label": "买入" if status == 1 else "卖出",
        })
    return pd.DataFrame(rows, columns=["instrument", "amount", "price", "status", "status_label"])


def _holdings_frame(final_positions: dict, prices: dict) -> Any:
    import pandas as pd

    rows = []
    for code, amount in sorted(final_positions.items()):
        px = prices.get(code)
        rows.append({
            "instrument": code, "amount": float(amount), "price": px,
            "value": float(amount) * px if px is not None else float("nan"),
        })
    return pd.DataFrame(rows, columns=["instrument", "amount", "price", "value"])


def run_one_day(
    date: str,
    scores: Any,
    account_seed: dict,
    *,
    start_date: str | None = None,
    yaml_params: Any = None,
    benchmark: str | None = None,
) -> dict:
    """Run the rebalance over ``[start_date, date]`` seeded with ``account_seed``.

    qlib executes a decision made on day T at the *next* session, so a single ``[T,T]`` window
    trades nothing. We seed yesterday's portfolio at ``start_date`` (the prior trading day) and
    read out the trades/holdings that execute on ``date`` (driven by ``start_date``'s signal).
    Trades are computed as the yesterday→today position diff (robust to ``parse_position``'s
    baseline-day labelling on a 2-day window).
    """
    from qlib.backtest import backtest as normal_backtest

    params = _coerce_params(yaml_params)
    start = start_date or _min_score_date(scores) or date
    seeded, dropped = _seed_with_prices(account_seed, start)
    if dropped:
        logger.warning(
            f"[daily_trade] {len(dropped)} seeded stock(s) unpriceable at {start}, excluded: {dropped[:5]}"
        )
    seed_amounts = {
        k: (v["amount"] if isinstance(v, dict) else v) for k, v in seeded.items() if k != "cash"
    }
    strategy_config = build_strategy_config(params, scores)
    exchange_kwargs = build_exchange_kwargs(params)
    bench = benchmark or params.benchmark

    logger.info(
        f"[daily_trade] rebalance window [{start} -> {date}] "
        f"(strategy={params.strategy_class}, seed_cash={seeded.get('cash')}, "
        f"seed_positions={len(seed_amounts)})"
    )
    portfolio_dict, indicator_dict = normal_backtest(
        start_time=start,
        end_time=date,
        strategy=strategy_config,
        executor=_EXECUTOR_CONFIG,
        benchmark=bench,
        account=dict(seeded),  # copy: create_account_instance pops "cash"
        exchange_kwargs=exchange_kwargs,
    )

    if "1day" in portfolio_dict:
        report_normal, positions_normal = portfolio_dict["1day"]
    else:
        _freq, (report_normal, positions_normal) = next(iter(portfolio_dict.items()))

    # ``new_state`` / trades / holdings must mirror qlib's actual end-of-day book (full positions +
    # cash) so the account value rolls forward intact — the next day re-seeds from this state. Do
    # NOT lot-round or drop positions here. Board lots are enforced *inside* qlib's exchange via
    # ``trade_unit`` (see build_exchange_kwargs), which qlib honours in real shares whenever every
    # instrument carries a valid ``$factor`` (non-adjusted-price mode). When any instrument lacks a
    # ``$factor`` qlib falls back to adjusted prices, ignores ``trade_unit`` and holds *fractional*
    # adjusted-share amounts; post-flooring those to whole lots (and dropping the many sub-lot
    # holdings) silently deletes most of the portfolio every day, compounding the account to ~zero
    # in a few sessions. So lots are qlib's job, not a destructive post-process on the rolled state.
    new_state = _state_from_positions(date, positions_normal)

    prices_today = _fetch_close(set(seed_amounts) | set(new_state.positions), date)
    trades = _compute_trades(seed_amounts, new_state.positions, prices_today)
    holdings = _holdings_frame(new_state.positions, prices_today)
    return {
        "trades": trades,
        "holdings": holdings,
        "report": report_normal,
        "new_state": new_state,
        "indicator": indicator_dict,
    }


def _state_from_positions(date: str, positions_normal: dict) -> PortfolioState:
    if not positions_normal:
        return PortfolioState(date=str(date), cash=0.0, positions={})
    import pandas as pd

    pos = positions_normal.get(pd.Timestamp(date))
    if pos is None:
        pos = positions_normal[sorted(positions_normal)[-1]]
    try:
        cash = float(pos.get_cash())
    except Exception:  # noqa: BLE001 — degenerate position without settled cash
        cash = 0.0
    try:
        positions = {str(k): float(v) for k, v in pos.get_stock_amount_dict().items() if v}
    except Exception:  # noqa: BLE001
        positions = {}
    return PortfolioState(date=str(date), cash=cash, positions=positions)
