"""Tier 1 (offline): board-lot (trade_unit) handling for the daily-trade rebalance.

Pure-function coverage for the lot constraint added to ``live/rebalance.py`` + the
``QlibYamlParams.trade_unit`` schema field — no market data, no qlib backtest.
"""

from __future__ import annotations

import sys
import types

import pandas as pd

from alphapilot.systems.backtest.live import rebalance
from alphapilot.systems.backtest.live.rebalance import (
    _lot_size,
    _round_to_lot,
    build_exchange_kwargs,
)
from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams


def test_trade_unit_defaults_to_one_lot() -> None:
    params = QlibYamlParams.defaults_for("combined")
    assert params.trade_unit == 100
    assert _lot_size(params) == 100


def test_round_to_lot_floors_to_whole_lots() -> None:
    assert _round_to_lot(3810.67, 100) == 3800
    assert _round_to_lot(150, 100) == 100
    assert _round_to_lot(99, 100) == 0  # sub-lot drops to zero
    assert _round_to_lot(2000, 100) == 2000


def test_round_to_lot_passthrough_when_disabled() -> None:
    assert _round_to_lot(3810.67, 0) == 3810.67
    assert _lot_size(QlibYamlParams.defaults_for("combined").model_copy(update={"trade_unit": 0})) == 0


def test_build_exchange_kwargs_includes_trade_unit_only_when_positive() -> None:
    params = QlibYamlParams.defaults_for("combined")
    assert build_exchange_kwargs(params)["trade_unit"] == 100

    disabled = params.model_copy(update={"trade_unit": 0})
    assert "trade_unit" not in build_exchange_kwargs(disabled)

    custom = params.model_copy(update={"trade_unit": 200})
    assert build_exchange_kwargs(custom)["trade_unit"] == 200


def test_run_one_day_preserves_qlib_book_without_lot_flooring(monkeypatch) -> None:
    """Regression: the rolled state must mirror qlib's actual end-of-day book exactly.

    qlib falls back to adjusted-price mode whenever any instrument lacks a ``$factor``; there it
    ignores ``trade_unit`` and holds *fractional* adjusted-share amounts (incl. sub-lot positions).
    The daily-trade code used to floor those to whole lots and drop sub-lot holdings, which silently
    deleted most of the account every day and compounded it toward zero. ``run_one_day`` must now
    return ``new_state`` with qlib's exact cash + fractional positions (lots are qlib's job, inside
    the exchange) so the account value rolls forward intact.
    """
    date = "2026-06-01"
    # qlib's real book: fractional amounts, including two sub-lot holdings (17.9 and 2.0 shares).
    qlib_amounts = {"SH600759": 111.20, "SH601633": 17.90, "SZ000895": 2.0, "SH600918": 213.83}

    class _FakePos:
        def get_cash(self):
            return 1925.0

        def get_stock_amount_dict(self):
            return dict(qlib_amounts)

    report = pd.DataFrame(
        {"account": [20000.0, 20169.0], "return": [0.0, 0.012]},
        index=pd.to_datetime(["2026-05-29", date]),
    )
    positions_normal = {pd.Timestamp(date): _FakePos()}

    # Stub qlib entirely (the backtest + the two price lookups) so the test stays offline.
    fake_backtest_mod = types.ModuleType("qlib.backtest")
    fake_backtest_mod.backtest = lambda **kw: ({"1day": (report, positions_normal)}, {})
    monkeypatch.setitem(sys.modules, "qlib", types.ModuleType("qlib"))
    monkeypatch.setitem(sys.modules, "qlib.backtest", fake_backtest_mod)
    monkeypatch.setattr(rebalance, "_seed_with_prices", lambda seed, start: (dict(seed), []))
    monkeypatch.setattr(rebalance, "_fetch_close", lambda stocks, d: {s: 10.0 for s in stocks})

    params = QlibYamlParams.defaults_for("combined")  # trade_unit=100 (lot mode on)
    out = rebalance.run_one_day(
        date, scores=object(), account_seed={"cash": 20000.0},
        start_date="2026-05-29", yaml_params=params,
    )

    st = out["new_state"]
    assert st.cash == 1925.0
    # Exact fractional book preserved — nothing floored to 100, nothing dropped.
    assert st.positions == qlib_amounts
    assert "SZ000895" in st.positions and st.positions["SZ000895"] == 2.0
    # Holdings reflect the same full book (so displayed value matches the rolled NAV).
    assert set(out["holdings"]["instrument"]) == set(qlib_amounts)


def test_trade_unit_is_inert_for_qrun_templates() -> None:
    # Guard the isolation promise: the qrun (mining / backtest) templates must NOT reference
    # trade_unit, so adding the schema field cannot change factor mining / backtest configs.
    from pathlib import Path

    import alphapilot.systems.backtest.qlib_yaml as qy

    tpl_dir = Path(qy.__file__).parent / "templates"
    for tpl in tpl_dir.glob("*.j2"):
        assert "trade_unit" not in tpl.read_text(encoding="utf-8"), f"{tpl.name} references trade_unit"
