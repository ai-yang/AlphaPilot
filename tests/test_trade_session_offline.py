"""Tier 1 (offline): the trade-session store.

A trade session snapshots an existing strategy (model + factors + params) into its own folder
and accumulates the rolling state + per-day history there. These tests exercise the store on a
real strategy asset (registered through the ``engine`` fixture) without any market data: create /
snapshot, default-name + duplicate guard, history append, and list / show / delete. The session
root is isolated under ``tmp_path`` via ``ALPHAPILOT_TRADE_SESSIONS_DIR`` (set by ``isolated_env``).
"""

from __future__ import annotations

import pickle

import pytest

from alphapilot.systems.backtest.live import session as live_session
from alphapilot.systems.strategy import StrategyMetrics, StrategyModelSpec, StrategyRecord


def _register_strategy(engine, name: str = "live_src", *, with_model: bool = True, artifact=None):
    model = None
    if with_model:
        model = StrategyModelSpec(model_name="lightgbm", trained_artifact_uri=str(artifact))
    record = StrategyRecord(
        strategy_name=name,
        factor_formulas=["Mean($close,5)/$close-1", "$close/$open-1"],
        model=model,
        metrics=StrategyMetrics(ic=0.03),
        metadata={"market": "test_pool", "yaml_params": {"template_type": "combined"}},
    )
    engine.get_system("strategy").register_strategy(record)
    return record


@pytest.fixture()
def trained_artifact(tmp_path):
    pkl = tmp_path / "fitted_model.pkl"
    pkl.write_bytes(pickle.dumps({"fake_model": True}))
    return pkl


@pytest.fixture()
def daily(engine):
    return engine.get_module("daily_trade")


def test_create_session_snapshots_strategy(engine, daily, isolated_env, trained_artifact) -> None:
    _register_strategy(engine, artifact=trained_artifact)

    manifest = daily.trade_session_create(name="live_demo", strategy_name="live_src", init_cash=50000)
    assert manifest["name"] == "live_demo"
    assert manifest["source_strategy"] == "live_src"
    assert manifest["init_cash"] == 50000.0
    assert manifest["current_date"] is None
    assert manifest["n_factors"] == 2

    sdir = live_session.session_dir("live_demo")
    # The strategy snapshot (record + copied model artifact) lives inside the session.
    assert list(sdir.glob("strategy/**/strategy_record.json")), "strategy record not snapshotted"
    assert list(sdir.glob("strategy/**/artifacts/*.pkl")), "model artifact not copied into session"
    # No trading has happened yet.
    assert not live_session.state_path_for("live_demo").exists()
    assert live_session.read_log("live_demo") == []


def test_default_name_and_duplicate_guard(engine, daily, isolated_env, trained_artifact) -> None:
    _register_strategy(engine, artifact=trained_artifact)

    # Default name == strategy name.
    manifest = daily.trade_session_create(strategy_name="live_src")
    assert manifest["name"] == "live_src"

    # Re-creating the same name is rejected (the "duplicate" prompt) ...
    with pytest.raises(ValueError, match="already exists"):
        daily.trade_session_create(strategy_name="live_src")

    # ... unless overwrite is requested.
    again = daily.trade_session_create(strategy_name="live_src", overwrite=True)
    assert again["name"] == "live_src"


def test_create_requires_trained_model(engine, daily, isolated_env) -> None:
    _register_strategy(engine, name="no_model", with_model=False)
    with pytest.raises(ValueError, match="trained model"):
        daily.trade_session_create(name="bad", strategy_name="no_model")


def test_append_history_advances_and_logs(engine, daily, isolated_env, trained_artifact) -> None:
    _register_strategy(engine, artifact=trained_artifact)
    daily.trade_session_create(name="live_demo", strategy_name="live_src")

    summary = {
        "date": "2026-06-10",
        "new_cash": 48230.5,
        "n_positions": 2,
        "trades": [
            {"instrument": "SH600000", "status_label": "买入"},
            {"instrument": "SZ000001", "status_label": "卖出"},
            {"instrument": "SH600519", "status_label": "买入"},
        ],
        "holdings": [],
        "info": {"strategy": "live_demo"},
    }
    live_session.append_history("live_demo", summary)

    sdir = live_session.session_dir("live_demo")
    assert (sdir / "history" / "2026-06-10.json").exists()

    log = live_session.read_log("live_demo")
    assert len(log) == 1
    assert log[0]["date"] == "2026-06-10"
    assert log[0]["n_buy"] == 2
    assert log[0]["n_sell"] == 1

    # The manifest now stands at the executed date — the replay guard reads this.
    assert live_session.current_date("live_demo") == "2026-06-10"

    shown = daily.trade_session_show("live_demo")
    assert shown["manifest"]["current_date"] == "2026-06-10"
    assert len(shown["history"]) == 1


def test_append_history_persists_chart_metrics(engine, daily, isolated_env, trained_artifact) -> None:
    _register_strategy(engine, artifact=trained_artifact)
    daily.trade_session_create(name="live_demo", strategy_name="live_src")

    # A summary carrying qlib's per-day metrics (nav / return / cost / turnover) should land in the
    # compact daily-log row that powers the P&L chart.
    summary = {
        "date": "2026-06-11",
        "new_cash": 47000.0,
        "n_positions": 3,
        "trades": [{"instrument": "SH600000", "status_label": "买入"}],
        "metrics": {"nav": 1_020_000.0, "ret": 0.012, "cost": 0.0006, "turnover": 0.25},
        "info": {"strategy": "live_demo"},
    }
    live_session.append_history("live_demo", summary)

    log = live_session.read_log("live_demo")
    assert len(log) == 1
    row = log[0]
    assert row["nav"] == 1_020_000.0
    assert row["ret"] == 0.012
    assert row["cost"] == 0.0006
    assert row["turnover"] == 0.25


def test_append_history_metrics_optional_backward_compat(engine, daily, isolated_env, trained_artifact) -> None:
    _register_strategy(engine, artifact=trained_artifact)
    daily.trade_session_create(name="legacy", strategy_name="live_src")

    # An older summary without a "metrics" block must still log fine (metrics fields just None).
    live_session.append_history(
        "legacy",
        {"date": "2026-06-12", "new_cash": 50000.0, "n_positions": 0, "trades": [], "info": {}},
    )
    row = live_session.read_log("legacy")[0]
    assert row["nav"] is None and row["ret"] is None


def test_report_metrics_extracts_execution_day_row() -> None:
    import pandas as pd

    from alphapilot.modules.daily_trade.module import _report_metrics

    idx = pd.to_datetime(["2026-06-09", "2026-06-10"])
    report = pd.DataFrame(
        {"account": [1_000_000.0, 1_015_000.0], "return": [0.0, 0.015], "cost": [0.0, 0.0007], "turnover": [0.0, 0.3]},
        index=idx,
    )
    m = _report_metrics(report, "2026-06-10")
    assert m == {"nav": 1_015_000.0, "ret": 0.015, "cost": 0.0007, "turnover": 0.3}

    # No report (failed/degenerate run) yields an empty dict, never an error.
    assert _report_metrics(None, "2026-06-10") == {}


def test_adjust_cash_deposit_withdraw_and_ledger(engine, daily, isolated_env, trained_artifact) -> None:
    _register_strategy(engine, artifact=trained_artifact)
    daily.trade_session_create(name="live_demo", strategy_name="live_src", init_cash=1_000_000)

    # First deposit seeds the rolling state from the manifest's init_cash, then adds the delta.
    res = daily.trade_session_cash("live_demo", 500_000, note="转入")
    assert res["previous_cash"] == 1_000_000.0
    assert res["new_cash"] == 1_500_000.0

    # Withdrawal reduces the balance.
    res2 = daily.trade_session_cash("live_demo", -200_000)
    assert res2["new_cash"] == 1_300_000.0

    # The rolling state file now reflects the adjusted cash (so the next run seeds from it).
    state = live_session.load_session("live_demo")["state"]
    assert state is not None and state["cash"] == 1_300_000.0

    # Cash-flow ledger accumulates one line per adjustment.
    flows = live_session.read_cashflows("live_demo")
    assert [f["delta"] for f in flows] == [500_000.0, -200_000.0]
    assert flows[0]["balance_after"] == 1_500_000.0
    assert flows[0]["note"] == "转入"
    assert live_session.load_session("live_demo")["cashflows"] == flows


def test_adjust_cash_blocks_overdraw_and_zero(engine, daily, isolated_env, trained_artifact) -> None:
    _register_strategy(engine, artifact=trained_artifact)
    daily.trade_session_create(name="live_demo", strategy_name="live_src", init_cash=100_000)

    with pytest.raises(ValueError, match="现金不足|insufficient"):
        daily.trade_session_cash("live_demo", -500_000)
    with pytest.raises(ValueError, match="non-zero|Invalid"):
        daily.trade_session_cash("live_demo", 0)

    with pytest.raises(ValueError, match="not found"):
        daily.trade_session_cash("__nope__", 1000)


def test_list_and_delete(engine, daily, isolated_env, trained_artifact) -> None:
    _register_strategy(engine, artifact=trained_artifact)
    daily.trade_session_create(name="s1", strategy_name="live_src")
    daily.trade_session_create(name="s2", strategy_name="live_src")

    names = {s["name"] for s in daily.trade_session_list()}
    assert {"s1", "s2"} <= names

    assert daily.trade_session_delete("s1")["deleted"] is True
    names = {s["name"] for s in daily.trade_session_list()}
    assert "s1" not in names and "s2" in names

    # Deleting a missing session is a safe no-op (not an error).
    assert daily.trade_session_delete("nope")["deleted"] is False
