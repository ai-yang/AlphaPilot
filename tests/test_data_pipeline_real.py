"""Tier 2 (real_data): full market-data pipeline for ~10 symbols.

Downloads a small basket of real A-share stocks (baostock, no token needed),
adjusts, converts to Qlib binary, and exercises the data/market portal API
against the freshly built Qlib directory.

Marked ``real_data``: needs network. Kept to 10 symbols over a short window so
it stays a smoke test, not a bulk download. Run with::

    ALPHAPILOT_RUN_REAL_CLI=1 pytest -m real_data tests/test_data_pipeline_real.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_BOOTSTRAP = "from alphapilot.app.cli import app; app()"

# 10 large-cap, liquid names that reliably have history.
TS_CODES = [
    "000001.SZ",
    "600000.SH",
    "600519.SH",
    "000858.SZ",
    "600036.SH",
    "601318.SH",
    "600030.SH",
    "000333.SZ",
    "601012.SH",
    "600276.SH",
]
START_DATE = "2026-05-06"
END_DATE = "2026-06-20"
MARKET = "mini_pipeline_10"


def _stem(ts_code: str) -> str:
    code, exch = ts_code.split(".")
    return f"{exch.lower()}{code}"


STEMS = [_stem(c) for c in TS_CODES]

# Skip the whole module up front unless real network runs are explicitly enabled.
pytestmark = pytest.mark.real_data

if not os.getenv("ALPHAPILOT_RUN_REAL_CLI"):
    pytest.skip(
        "real data pipeline disabled; set ALPHAPILOT_RUN_REAL_CLI=1 to run",
        allow_module_level=True,
    )


@dataclass
class Pipeline:
    root: Path
    raw_none: Path
    raw_backward: Path
    factor_dir: Path
    qlib_dir: Path
    stock_csv: Path
    env: dict[str, str]
    downloaded: list[str]


def _cli(env: dict[str, str], cwd: Path, *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-c", CLI_BOOTSTRAP, *map(str, args)]
    return subprocess.run(
        cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
    )


def _cli_ok(env, cwd, *args, timeout=300) -> subprocess.CompletedProcess[str]:
    proc = _cli(env, cwd, *args, timeout=timeout)
    assert proc.returncode == 0, (
        f"CLI {args[0]} failed ({proc.returncode})\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    return proc


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory: pytest.TempPathFactory) -> Pipeline:
    root = tmp_path_factory.mktemp("data_pipeline")
    home = root / "home"
    important = root / "important_data"
    stock_lists = important / "stock_lists"
    # baostock data must live at its canonical ~/.qlib layout so the data system
    # (manage.list_symbols) resolves the same directories the CLI wrote to.
    baostock_root = home / ".qlib" / "qlib_data" / "cn_data" / "baostock"
    raw_none = baostock_root / "raw_data_no_adjust"
    raw_backward = baostock_root / "raw_data_back_adjust"
    factor_dir = baostock_root / "adjust_factors"
    qlib_dir = baostock_root / "qlib"
    for p in (home, stock_lists, raw_none, raw_backward, factor_dir, qlib_dir):
        p.mkdir(parents=True, exist_ok=True)

    stock_csv = stock_lists / f"{MARKET}.csv"
    stock_csv.write_text(
        "ts_code,name\n" + "\n".join(f"{c},stock{i}" for i, c in enumerate(TS_CODES)) + "\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PYTHONPATH": str(REPO_ROOT),
            "ALPHAPILOT_IMPORTANT_DATA_DIR": str(important),
            "ALPHAPILOT_RAW_DATA_DIR": str(raw_backward),
            "ALPHAPILOT_QLIB_DATA_DIR": str(qlib_dir),
            "ALPHAPILOT_ADJUST_FACTOR_DIR": str(factor_dir),
            "ALPHAPILOT_LOG_DIR": str(root / "log"),
            "ALPHAPILOT_PICKLE_CACHE_ENABLED": "false",
            "USE_LOCAL": "True",
        }
    )

    # 1) download unadjusted bars + adjust factors
    _cli_ok(
        env, root,
        "prepare_data", "--action=download",
        f"--start_date={START_DATE}", f"--end_date={END_DATE}",
        f"--stock_csv={stock_csv}", "--adjust_mode=none",
        f"--output_dir={raw_none}", f"--factor_dir={factor_dir}",
        f"--download_state_path={home / 'download_state.csv'}", "--max_workers=2",
        timeout=420,
    )
    downloaded = [s for s in STEMS if (raw_none / f"{s}.csv").is_file()]

    # 2) backward-adjust
    _cli_ok(
        env, root,
        "prepare_data", "--action=apply_adjust", "--adjust_mode=backward",
        f"--raw_dir={raw_none}", f"--factor_dir={factor_dir}",
        f"--output_dir={raw_backward}", "--max_workers=2",
        timeout=240,
    )

    # 3) convert to qlib binary
    _cli_ok(
        env, root,
        "prepare_data", "--action=convert",
        f"--stock_csv={stock_csv}", f"--data_path={raw_backward}",
        "--adjust_mode=backward", f"--qlib_dir={qlib_dir}", f"--market={MARKET}",
        f"--start_date={START_DATE}", f"--end_date={END_DATE}",
        "--include_benchmark=False", "--max_workers=2",
        timeout=300,
    )

    return Pipeline(
        root=root, raw_none=raw_none, raw_backward=raw_backward, factor_dir=factor_dir,
        qlib_dir=qlib_dir, stock_csv=stock_csv, env=env, downloaded=downloaded,
    )


def test_download_produced_most_symbols(pipeline: Pipeline) -> None:
    # Tolerate the odd symbol with no bars in a narrow window, but expect the bulk.
    assert len(pipeline.downloaded) >= 8, f"only got {pipeline.downloaded}"
    for stem in pipeline.downloaded:
        price = pipeline.raw_none / f"{stem}.csv"
        df = pd.read_csv(price)
        assert not df.empty
        assert df["date"].min() >= START_DATE
        assert df["date"].max() <= END_DATE
        assert (pipeline.factor_dir / f"{stem}.csv").is_file()


def test_backward_adjust_written(pipeline: Pipeline) -> None:
    for stem in pipeline.downloaded:
        assert (pipeline.raw_backward / f"{stem}.csv").is_file()


def test_convert_built_qlib_layout(pipeline: Pipeline) -> None:
    assert (pipeline.qlib_dir / "instruments" / f"{MARKET}.txt").is_file()
    assert (pipeline.qlib_dir / "calendars" / "day.txt").is_file()
    built = [s for s in pipeline.downloaded if (pipeline.qlib_dir / "features" / s).is_dir()]
    assert len(built) >= 8, f"qlib features only built for {built}"


def test_factor_h5_cache_generated_on_demand(pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch) -> None:
    from alphapilot.systems.data.factor_h5 import prepare_factor_data_context

    monkeypatch.chdir(pipeline.root)
    ctx = prepare_factor_data_context(
        market=MARKET,
        qlib_dir=pipeline.qlib_dir,
        start_date=START_DATE,
        use_local=True,
    )
    assert (ctx.data_dir / "daily_pv.h5").is_file()
    assert (ctx.debug_dir / "daily_pv.h5").is_file()
    store = pd.read_hdf(ctx.data_dir / "daily_pv.h5")
    assert not store.empty


def test_data_api_reads_pipeline(pipeline: Pipeline, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from alphapilot.modules.portal.api import create_app

    # Point the in-process engine at the freshly built directories. HOME matters
    # because baostock dirs resolve under ~/.qlib via expanduser().
    for key, value in pipeline.env.items():
        if key.startswith("ALPHAPILOT_") or key in ("USE_LOCAL", "HOME"):
            monkeypatch.setenv(key, value)

    client = TestClient(create_app())

    # Symbols known to the data system (keyed by adjust mode).
    resp = client.get("/api/data/symbols", params={"source": "baostock_cn"})
    assert resp.status_code == 200
    symbol_map = resp.json()
    all_listed = {s for group in symbol_map.values() for s in group}
    assert len(all_listed & set(pipeline.downloaded)) >= 8

    # Market source browser should see the raw CSV directory.
    resp = client.get("/api/market/sources")
    assert resp.status_code == 200

    # K-line for one symbol straight from the raw CSV dir.
    stem = pipeline.downloaded[0]
    resp = client.get(
        "/api/market/kline",
        params={"data_dir": str(pipeline.raw_none), "symbol": stem},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["symbol"] == stem
    assert payload["rows"]
