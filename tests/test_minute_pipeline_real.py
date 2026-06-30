"""Tier (real_data): baostock 5-minute pipeline smoke test.

Downloads 3 A-share stocks over a short window at 5-minute frequency (baostock,
no token), converts to a per-frequency Qlib dir, and runs a ``single_ic`` factor
evaluation on the intraday data. Kept tiny (3 symbols x ~4 days) so it stays a
smoke test, not a bulk download.

Run with::

    ALPHAPILOT_RUN_REAL_CLI=1 pytest -m real_data tests/test_minute_pipeline_real.py
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

TS_CODES = ["000001.SZ", "600000.SH", "600519.SH"]
START_DATE = "2026-06-23"
END_DATE = "2026-06-26"  # ~4 trading days -> ~48 5min bars/day each
MARKET = "mini3_5min"
FREQ = "5min"

pytestmark = pytest.mark.real_data

if not os.getenv("ALPHAPILOT_RUN_REAL_CLI"):
    pytest.skip(
        "real minute pipeline disabled; set ALPHAPILOT_RUN_REAL_CLI=1 to run",
        allow_module_level=True,
    )


def _stem(ts_code: str) -> str:
    code, exch = ts_code.split(".")
    return f"{exch.lower()}{code}"


STEMS = [_stem(c) for c in TS_CODES]


@dataclass
class MinutePipeline:
    root: Path
    raw_dir: Path
    qlib_dir: Path
    stock_csv: Path
    factor_csv: Path
    env: dict
    downloaded: list[str]


def _cli_ok(env, cwd, *args, timeout=420) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-c", CLI_BOOTSTRAP, *map(str, args)]
    proc = subprocess.run(
        cmd, cwd=cwd, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout,
    )
    assert proc.returncode == 0, f"CLI {args[:2]} failed:\n{proc.stdout}"
    return proc


@pytest.fixture(scope="module")
def pipeline(tmp_path_factory: pytest.TempPathFactory) -> MinutePipeline:
    root = tmp_path_factory.mktemp("minute_pipeline")
    home = root / "home"
    lists = root / "lists"
    for p in (home, lists):
        p.mkdir(parents=True, exist_ok=True)

    # Minute data resolves under ~/.qlib/.../baostock/{raw_min_5min,qlib_5min}.
    baostock_root = home / ".qlib" / "qlib_data" / "cn_data" / "baostock"
    raw_dir = baostock_root / f"raw_min_{FREQ}"
    qlib_dir = baostock_root / f"qlib_{FREQ}"

    stock_csv = lists / f"{MARKET}.csv"
    stock_csv.write_text(
        "ts_code,name\n" + "\n".join(f"{c},stk{i}" for i, c in enumerate(TS_CODES)) + "\n",
        encoding="utf-8",
    )
    factor_csv = root / "factors.csv"
    factor_csv.write_text(
        "factor_name,factor_expression\n"
        'mom1,"TS_PCTCHANGE($close,1)"\n'
        'volr,"DIVIDE($volume,TS_MEAN($volume,5))"\n',
        encoding="utf-8",
    )

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PYTHONPATH": str(REPO_ROOT),  # factor subprocess (cwd=workspace) imports alphapilot
            "ALPHAPILOT_LOG_DIR": str(root / "log"),
            "ALPHAPILOT_RUNS_DIR": str(root / "runs"),
            "ALPHAPILOT_WORKSPACE_ROOT": str(root / "workspaces"),
            "ALPHAPILOT_PICKLE_CACHE_ENABLED": "false",
            "USE_LOCAL": "True",
        }
    )

    # One-shot minute pipeline: download adjusted 5min bars -> convert to Qlib.
    _cli_ok(
        env, root,
        "prepare_data", "--action=pipeline", f"--freq={FREQ}",
        f"--stock_csv={stock_csv}", f"--start_date={START_DATE}", f"--end_date={END_DATE}",
        f"--market={MARKET}", "--max_workers=1", "--dump_workers=2",
    )
    downloaded = [s for s in STEMS if (raw_dir / f"{s}.csv").is_file()]
    return MinutePipeline(
        root=root, raw_dir=raw_dir, qlib_dir=qlib_dir,
        stock_csv=stock_csv, factor_csv=factor_csv, env=env, downloaded=downloaded,
    )


def test_minute_csv_has_intraday_bars(pipeline: MinutePipeline) -> None:
    assert len(pipeline.downloaded) == len(STEMS), pipeline.downloaded
    for stem in pipeline.downloaded:
        df = pd.read_csv(pipeline.raw_dir / f"{stem}.csv")
        assert {"date", "time", "close"} <= set(df.columns)
        # Intraday timestamps carry an HH:MM:SS part; far more rows than daily bars.
        assert " " in str(df["date"].iloc[0])
        assert len(df) > 4 * 10  # ~48 bars/day x ~4 days, generous lower bound


def test_qlib_5min_layout_built(pipeline: MinutePipeline) -> None:
    assert (pipeline.qlib_dir / "calendars" / f"{FREQ}.txt").is_file()
    assert (pipeline.qlib_dir / "instruments" / f"{MARKET}.txt").is_file()
    for stem in pipeline.downloaded:
        assert (pipeline.qlib_dir / "features" / stem / f"close.{FREQ}.bin").is_file()
    # Daily-only artifacts must be skipped for intraday.
    assert not (pipeline.qlib_dir / "calendars" / "day.txt").exists()


def test_qlib_reads_5min_features(pipeline: MinutePipeline) -> None:
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=str(pipeline.qlib_dir))
    df = D.features(D.instruments(market=MARKET), ["$close"], freq=FREQ)
    assert not df.empty
    # Intraday timestamps within a single day (more than one bar per date).
    dts = df.index.get_level_values("datetime")
    assert dts.normalize().nunique() < dts.nunique()


def test_single_ic_on_minute_data(pipeline: MinutePipeline) -> None:
    _cli_ok(
        pipeline.env, pipeline.root,
        "backtest", f"--factor_path={pipeline.factor_csv}",
        "--mode=single_ic", f"--freq={FREQ}", f"--market={MARKET}",
    )
    boards = list((pipeline.root / "runs").rglob("factor_ic_leaderboard.csv"))
    assert boards, "single_ic produced no IC leaderboard"
    table = pd.read_csv(sorted(boards, key=lambda p: p.stat().st_mtime)[-1])
    assert {"factor_name", "IC", "RankIC", "ICIR"} <= set(table.columns)
    assert set(table["factor_name"]) >= {"mom1", "volr"}
