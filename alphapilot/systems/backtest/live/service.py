"""Daily live-trade signal orchestration.

Resolves the strategy (saved asset, with optional manual overrides), scores today's
universe, runs one qlib trading day seeded with yesterday's portfolio state, persists the
new state, and returns the trade plan.
"""

from __future__ import annotations

import csv
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alphapilot.log import logger
from alphapilot.systems.backtest.live.portfolio_state import (
    init_state,
    load_state,
    save_state,
    state_to_account,
)
from alphapilot.systems.backtest.live.predict import (
    _coerce_params,
    latest_factor_date,
    predict_scores,
)
from alphapilot.systems.backtest.live.rebalance import run_one_day
from alphapilot.systems.backtest.live.types import DailySignalRequest, DailyTradeResult

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context

_DEFAULT_STATE_DIR = Path("git_ignore_folder") / "portfolio_state"


@dataclass
class _ResolvedStrategy:
    factor_csv: Path | None
    is_temp_csv: bool
    model_pickle_path: str
    yaml_params: Any
    benchmark: str | None
    key: str
    market: str | None = None


def _safe_name(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", name).strip("_") or "strategy"


def _write_factor_csv_from_formulas(formulas: list[str]) -> Path:
    fd, temp_path = tempfile.mkstemp(prefix="alphapilot_daily_factors_", suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["factor_name", "factor_expression"])
        writer.writeheader()
        # Names are arbitrary; qlib aligns LGBModel features by column *order*, so preserving
        # ``factor_formulas`` order is what matters for matching training-time features.
        for i, formula in enumerate(formulas):
            writer.writerow({"factor_name": f"f{i}", "factor_expression": formula})
    return Path(temp_path)


def _resolve_strategy(context: "Context", request: DailySignalRequest) -> _ResolvedStrategy:
    factor_csv: Path | None = None
    is_temp = False
    model_pkl = str(request.model_pickle_path) if request.model_pickle_path else None
    yaml_params = request.yaml_params
    benchmark = request.benchmark
    key = "manual"
    market = request.market

    if request.strategy_name:
        record = context.strategy().get_strategy(request.strategy_name)
        if record is None:
            raise ValueError(f"Strategy asset not found: {request.strategy_name}")
        key = request.strategy_name
        if model_pkl is None and record.model is not None:
            model_pkl = record.model.trained_artifact_uri
        if yaml_params is None:
            yaml_params = (record.metadata or {}).get("yaml_params")
        if market is None:
            # Bind daily signals to the same instrument universe the strategy was trained on.
            market = (record.metadata or {}).get("market")
        if request.factor_path is None and record.factor_formulas:
            factor_csv = _write_factor_csv_from_formulas(record.factor_formulas)
            is_temp = True

    if request.factor_path is not None:
        factor_csv = Path(request.factor_path).expanduser()
        is_temp = False

    if not model_pkl:
        raise ValueError(
            "A trained model is required: set model_pickle_path, or use a strategy asset "
            "whose model.trained_artifact_uri is populated."
        )
    return _ResolvedStrategy(
        factor_csv, is_temp, str(model_pkl), yaml_params, benchmark, key, market
    )


def _default_state_path(key: str) -> Path:
    return _DEFAULT_STATE_DIR / f"{_safe_name(key)}.json"


def _latest_trading_day(
    params: Any, provider_uri: str | None = None, factor_day: str | None = None
) -> str:
    """Latest tradable execution day.

    The execution day must carry model scores (qlib only trades on a day that has a signal),
    and combined-template scores cannot extend past the factor source. So when ``factor_day``
    is given we cap the calendar at it; otherwise we fall back to the latest price-calendar day.
    """
    from alphapilot.systems.backtest.live.predict import _init_qlib

    _init_qlib(params, provider_uri)
    import pandas as pd
    from qlib.data import D

    cal = [pd.Timestamp(c) for c in D.calendar()]
    if factor_day is not None:
        cap = pd.Timestamp(factor_day)
        eligible = [c for c in cal if c <= cap]
        if eligible:
            return eligible[-1].strftime("%Y-%m-%d")
    return cal[-1].strftime("%Y-%m-%d")


def _prev_trading_day(date: str, params: Any, provider_uri: str | None = None) -> str:
    from alphapilot.systems.backtest.live.predict import _init_qlib

    _init_qlib(params, provider_uri)
    import pandas as pd
    from qlib.data import D

    target = pd.Timestamp(date)
    prior = [pd.Timestamp(c) for c in D.calendar() if pd.Timestamp(c) < target]
    if not prior:
        raise ValueError(f"No trading day before {date} in the qlib calendar")
    return prior[-1].strftime("%Y-%m-%d")


def _maybe_refresh_data(context: "Context") -> None:
    try:
        data_system = context.engine.get_system("data")
        download = getattr(data_system, "download", None)
        if callable(download):
            download()  # best-effort incremental update to today
            logger.info("[daily_trade] data refreshed to latest")
    except Exception as exc:  # noqa: BLE001 — refresh is best-effort, non-fatal
        logger.warning(f"[daily_trade] data refresh skipped ({exc}); please update data manually")


def generate_daily_signal(context: "Context", request: DailySignalRequest) -> DailyTradeResult:
    use_local = (
        request.use_local if request.use_local is not None else context.config.backtest.use_local
    )
    # A trade session draws its strategy (model + factors + params) from a self-contained
    # snapshot and rolls its own state/history; otherwise resolve from the strategy zoo / manual
    # overrides as before.
    session_name = getattr(request, "session", None)
    live_session = None
    session_state: dict[str, Any] | None = None
    if session_name:
        from alphapilot.systems.backtest.live import session as live_session

        session_state = live_session.load_session(session_name)
        rs = live_session.resolve_session_strategy(session_name)
        resolved = _ResolvedStrategy(
            factor_csv=rs.factor_csv,
            is_temp_csv=rs.is_temp_csv,
            model_pickle_path=rs.model_pickle_path,
            yaml_params=request.yaml_params if request.yaml_params is not None else rs.yaml_params,
            benchmark=request.benchmark,
            key=session_name,
            market=request.market or rs.market,
        )
    else:
        resolved = _resolve_strategy(context, request)
    params = _coerce_params(resolved.yaml_params)

    # Optional per-run board-lot override (A-shares = 100; 0 disables). Defaults to the
    # strategy/template ``trade_unit`` when not given.
    if request.trade_unit is not None:
        try:
            params = params.model_copy(update={"trade_unit": int(request.trade_unit)})
        except Exception:  # noqa: BLE001 — bad override should not break the run
            logger.warning(f"[daily_trade] ignoring invalid trade_unit={request.trade_unit!r}")

    # Effective first-run seed cash: explicit request wins, else the session's recorded init_cash.
    init_cash = request.init_cash
    if init_cash is None and session_state is not None:
        init_cash = (session_state.get("manifest") or {}).get("init_cash")

    # The real qlib binary store lives at the kernel-config data dir (e.g. the baostock
    # store), not QlibYamlParams.provider_uri's default. Resolve it once and thread it
    # through prediction so model.predict reads the right data.
    provider_uri = str(context.config.data.qlib_data_dir)

    if request.refresh_data:
        _maybe_refresh_data(context)

    # Combined-template scores are computed from the factor source (daily_pv.h5), which can lag
    # the qlib price store. qlib only trades on a day that carries a signal, so the execution
    # ``date`` must be within factor coverage — otherwise the backtest silently does nothing.
    factor_cache_dir: Path | None = None
    factor_data_spec: str | None = None
    if params.template_type == "combined":
        # Bind to the strategy's data context (rebuild from spec when the cache is missing) and
        # publish it via env so predict_scores/compute_combined_factors use the same h5 snapshot.
        from alphapilot.systems.data.factor_h5 import apply_context_env, prepare_or_reuse_context

        factor_ctx = prepare_or_reuse_context(
            market=resolved.market,
            qlib_dir=provider_uri,
            yaml_params=resolved.yaml_params,
            factor_data_dir=request.factor_data_dir,
            use_local=use_local,
        )
        apply_context_env(factor_ctx)
        factor_cache_dir = factor_ctx.cache_dir
        factor_data_spec = factor_ctx.fingerprint
        logger.info(
            f"[daily_trade] factor data spec={factor_ctx.fingerprint} "
            f"market={factor_ctx.spec.market} dir={factor_ctx.data_dir}"
        )
    factor_day = (
        latest_factor_date(factor_data_dir=factor_cache_dir, use_local=use_local)
        if params.template_type == "combined"
        else None
    )

    date = request.date or _latest_trading_day(params, provider_uri, factor_day)
    if request.date and factor_day is not None:
        import pandas as pd

        if pd.Timestamp(request.date) > pd.Timestamp(factor_day):
            tradable = _latest_trading_day(params, provider_uri, factor_day)
            raise ValueError(
                f"Execution date {request.date} has no factor scores: the factor source "
                f"(daily_pv.h5) only covers up to {factor_day} while the qlib price store is "
                f"fresher. Refresh the factor data to >= {request.date}, or use "
                f"--date <= {tradable}."
            )
    # A session rolls forward; refuse to re-run a date at/before where it already stands so the
    # same day is never traded twice on top of itself (state would be corrupted).
    if session_state is not None:
        cur = (session_state.get("manifest") or {}).get("current_date")
        if cur:
            import pandas as pd

            if pd.Timestamp(date) <= pd.Timestamp(cur):
                raise ValueError(
                    f"Trade session {session_name!r} has already advanced to {cur}; execution date "
                    f"{date} is not after it. Use a later --date (the next trading day), or create a "
                    f"new/overwritten session to restart from scratch."
                )

    # The decision that executes on ``date`` is driven by the prior trading day's signal and
    # seeded with the portfolio held as of that day, so score+seed over [prev_day, date].
    prev_day = _prev_trading_day(date, params, provider_uri)

    if session_name:
        state_path = live_session.state_path_for(session_name)
    else:
        state_path = Path(request.state_path) if request.state_path else _default_state_path(resolved.key)
    prev_state = load_state(state_path)
    if prev_state is None:
        seed_cash = init_cash if init_cash is not None else float(params.account)
        prev_state = init_state(seed_cash, date="", metadata={"seeded": True})
        logger.info(f"[daily_trade] no prior state at {state_path}; seeded cash={seed_cash}")

    scores = predict_scores(
        date,
        resolved.model_pickle_path,
        resolved.factor_csv,
        yaml_params=resolved.yaml_params,
        qlib_template_dir=request.qlib_template_dir,
        use_local=use_local,
        provider_uri=provider_uri,
        start_date=prev_day,
    )

    try:
        out = run_one_day(
            date,
            scores,
            state_to_account(prev_state),
            start_date=prev_day,
            yaml_params=resolved.yaml_params,
            benchmark=resolved.benchmark,
        )
    finally:
        if resolved.is_temp_csv and resolved.factor_csv is not None:
            try:
                resolved.factor_csv.unlink(missing_ok=True)
            except OSError:
                pass

    new_state = out["new_state"]
    new_state.metadata = {"strategy": resolved.key, "prev_date": prev_state.date, "signal_day": prev_day}
    save_state(new_state, state_path)

    return DailyTradeResult(
        date=date,
        trades=out["trades"],
        holdings=out["holdings"],
        scores=scores,
        new_state=new_state,
        report=out["report"],
        info={
            "strategy": resolved.key,
            "state_path": str(state_path),
            "signal_day": prev_day,
            "factor_data_through": factor_day,
            "factor_data_spec": factor_data_spec,
            "prev_cash": prev_state.cash,
            "new_cash": new_state.cash,
            "n_scored": int(len(scores)),
        },
    )
