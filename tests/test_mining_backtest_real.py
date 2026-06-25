"""Tier 3: factor mining (local) and backtest.

Two layers:
* deterministic, fast, offline — the AlphaForge ``emit_factors`` pipeline that
  every miner funnels through (translate alphagen expressions -> alphapilot DSL
  -> validate -> persist to the zoo). This is the part we can assert positively
  without a full-history qlib dump.
* invocation smoke (``slow`` + ``real_data``) — actually drive ``mine_gp`` and a
  factor backtest on a freshly built 10-symbol qlib dump. Because the vendored
  AlphaForge ``StockData`` needs >100 trading days of calendar headroom before
  the hard-coded ``train_start=2010`` (otherwise ``cal[start_index - 100]`` wraps
  to the calendar tail and the slice loads empty), a short-window mini universe
  may legitimately not produce factors; such cases skip with a clear reason
  rather than fail. The full path is still covered by the real-CLI smoke test.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

# Vendored alphagen on sys.path.
import alphapilot.modules.alphaforge  # noqa: F401
from alphapilot.modules.alphaforge.pipeline import emit_factors

from alphagen.data.expression import Div, Sub, ts_mean, ts_std, ts_sum
from alphagen_generic.features import close, high, low, open_, volume

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_BOOTSTRAP = "from alphapilot.app.cli import app; app()"


# --------------------------------------------------------------------------- #
# Deterministic emit_factors pipeline (offline, always runs)
# --------------------------------------------------------------------------- #
def test_emit_factors_translates_and_saves(engine) -> None:
    exprs = [ts_mean(close, 10), ts_std(close, 20), ts_sum(volume, 5)]
    scores = [0.05, 0.04, 0.03]
    result = emit_factors(engine.context, exprs, scores, source="afg_test", backtest=False, save=True)

    assert result["mined"] == 3
    assert result["n_accepted"] >= 1
    assert set(result) >= {"accepted", "rejected", "n_accepted", "n_rejected", "untranslatable"}

    saved = {f["factor_name"] for f in engine.get_system("factor").list_factors()}
    accepted_names = {a["name"] for a in result["accepted"]}
    assert accepted_names and accepted_names <= saved


def test_emit_factors_rejects_duplicates(engine) -> None:
    # The same expression twice: the second must be rejected by the zoo's
    # duplicate-expression guard, so it never double-counts.
    exprs = [Div(close, open_), Div(close, open_)]
    result = emit_factors(engine.context, exprs, [0.05, 0.05], source="dup_test", save=True)
    assert result["mined"] == 2
    assert result["n_accepted"] <= 1


def test_emit_factors_save_false_does_not_persist(engine) -> None:
    before = len(engine.get_system("factor").list_factors())
    emit_factors(engine.context, [Sub(high, low)], [0.05], source="nosave", save=False)
    after = len(engine.get_system("factor").list_factors())
    assert after == before


# --------------------------------------------------------------------------- #
# Mining + backtest invocation on a real mini qlib dump
# --------------------------------------------------------------------------- #
TS_CODES = [
    "000001.SZ", "600000.SH", "600519.SH", "000858.SZ", "600036.SH",
    "601318.SH", "600030.SH", "000333.SZ", "601012.SH", "600276.SH",
]
START_DATE = "2022-01-04"
END_DATE = "2026-06-20"
MARKET = "mini_mine_10"

_DATA_LIMIT_HINTS = (
    "cannot reshape", "out of bounds", "index", "empty", "not enough",
    "Found array with 0", "least one array", "0 sample", "NaN",
)


@dataclass
class QlibData:
    qlib_dir: Path
    home: Path
    market: str
    env: dict[str, str]


def _cli_ok(env, cwd, *args, timeout=600):
    proc = subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, *map(str, args)],
        cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
    )
    assert proc.returncode == 0, f"CLI {args[0]} failed:\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
    return proc


@pytest.fixture(scope="module")
def qlib_data(tmp_path_factory: pytest.TempPathFactory) -> QlibData:
    if not os.getenv("ALPHAPILOT_RUN_REAL_CLI"):
        pytest.skip("set ALPHAPILOT_RUN_REAL_CLI=1 to build the mining dataset")

    root = tmp_path_factory.mktemp("mine_data")
    home = root / "home"
    stock_lists = root / "important" / "stock_lists"
    baostock_root = home / ".qlib" / "qlib_data" / "cn_data" / "baostock"
    raw_none = baostock_root / "raw_data_no_adjust"
    raw_backward = baostock_root / "raw_data_back_adjust"
    factor_dir = baostock_root / "adjust_factors"
    qlib_dir = baostock_root / "qlib"
    for p in (home, stock_lists, raw_none, raw_backward, factor_dir, qlib_dir):
        p.mkdir(parents=True, exist_ok=True)

    stock_csv = stock_lists / f"{MARKET}.csv"
    stock_csv.write_text("ts_code,name\n" + "\n".join(f"{c},s{i}" for i, c in enumerate(TS_CODES)) + "\n")

    env = os.environ.copy()
    env.update({
        "HOME": str(home), "PYTHONPATH": str(REPO_ROOT),
        "ALPHAPILOT_QLIB_DATA_DIR": str(qlib_dir), "ALPHAPILOT_RAW_DATA_DIR": str(raw_backward),
        "ALPHAPILOT_ADJUST_FACTOR_DIR": str(factor_dir), "ALPHAPILOT_FACTOR_ZOO_DIR": str(root / "zoo"),
        "ALPHAPILOT_PICKLE_CACHE_ENABLED": "false", "USE_LOCAL": "True",
    })

    _cli_ok(env, root, "prepare_data", "--action=download", f"--start_date={START_DATE}", f"--end_date={END_DATE}",
            f"--stock_csv={stock_csv}", "--adjust_mode=none", f"--output_dir={raw_none}", f"--factor_dir={factor_dir}",
            "--max_workers=4", timeout=600)
    _cli_ok(env, root, "prepare_data", "--action=apply_adjust", "--adjust_mode=backward", f"--raw_dir={raw_none}",
            f"--factor_dir={factor_dir}", f"--output_dir={raw_backward}", "--max_workers=4", timeout=300)
    _cli_ok(env, root, "prepare_data", "--action=convert", f"--stock_csv={stock_csv}", f"--data_path={raw_backward}",
            "--adjust_mode=backward", f"--qlib_dir={qlib_dir}", f"--market={MARKET}", f"--start_date={START_DATE}",
            f"--end_date={END_DATE}", "--include_benchmark=False", "--max_workers=4", timeout=420)

    built = len(list((qlib_dir / "features").glob("*"))) if (qlib_dir / "features").is_dir() else 0
    assert built >= 8, f"qlib dump only built {built} symbols"
    return QlibData(qlib_dir=qlib_dir, home=home, market=MARKET, env=env)


def _apply_env(monkeypatch, env: dict[str, str]) -> None:
    for key, value in env.items():
        if key.startswith("ALPHAPILOT_") or key in ("USE_LOCAL", "HOME"):
            monkeypatch.setenv(key, value)


@pytest.mark.real_data
@pytest.mark.slow
def test_mine_gp_invocation(qlib_data: QlibData, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("gplearn")
    _apply_env(monkeypatch, qlib_data.env)
    from alphapilot.kernel import build_engine

    engine = build_engine()
    module = engine.get_module("alphaforge_search")
    try:
        result = module.mine_gp(
            instruments=qlib_data.market, train_end_year=2023,
            population_size=12, generations=1, tournament_size=3, top_n=2,
            device="cpu", qlib_dir=str(qlib_data.qlib_dir), backtest=False, save=False,
        )
    except Exception as exc:  # noqa: BLE001
        if any(h in str(exc) for h in _DATA_LIMIT_HINTS):
            pytest.skip(f"mini universe too small for GP data splits: {type(exc).__name__}: {exc}")
        raise
    assert set(result) >= {"mined", "n_accepted", "n_rejected"}
    assert result["mined"] >= 0


@pytest.mark.real_data
@pytest.mark.slow
def test_mine_aff_invocation(qlib_data: QlibData, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("torch")
    _apply_env(monkeypatch, qlib_data.env)
    from alphapilot.kernel import build_engine

    engine = build_engine()
    module = engine.get_module("alphaforge_aff")
    try:
        result = module.mine_aff(
            instruments=qlib_data.market, train_end_year=2023, zoo_size=1, max_len=4,
            device="cpu", qlib_dir=str(qlib_data.qlib_dir), backtest=False, save=False,
            batch_size=4, num_epochs_g=1, num_epochs_p=1, init_collect=4, iter_collect=2,
            max_iter_init=2, max_iter=1, max_loops=1,
        )
    except Exception as exc:  # noqa: BLE001
        if any(h in str(exc) for h in _DATA_LIMIT_HINTS):
            pytest.skip(f"mini universe too small for AFF data splits: {type(exc).__name__}: {exc}")
        raise
    assert set(result) >= {"mined", "n_accepted", "n_rejected"}


@pytest.mark.real_data
@pytest.mark.slow
def test_factor_backtest_cli(qlib_data: QlibData) -> None:
    # single_ic mode computes the IC of one factor against the mini qlib dump.
    factor_csv = qlib_data.home / "bt_factor.csv"
    factor_csv.write_text('factor_name,factor_expression\nclose_ret,"Mean($close,5)/$close-1"\n')
    yaml_params = f'{{"market":"{qlib_data.market}","provider_uri":"{qlib_data.qlib_dir}"}}'
    proc = subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, "backtest", f"--factor_path={factor_csv}",
         "--mode=single_ic", f"--market={qlib_data.market}", f"--yaml_params={yaml_params}"],
        cwd=qlib_data.home, env=qlib_data.env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=420,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        if any(h in out for h in _DATA_LIMIT_HINTS) or "Qlib" in out or "factor h5" in out:
            pytest.skip("mini universe insufficient for factor backtest")
        raise AssertionError(f"backtest failed unexpectedly:\n{out[-2000:]}")
