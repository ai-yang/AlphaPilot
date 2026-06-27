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
