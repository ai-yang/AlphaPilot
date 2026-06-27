from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_BOOTSTRAP = "from alphapilot.app.cli import app; app()"
MARKET = "mini_real_cli"
SYMBOL = "sz.000001"
STEM = "sz000001"
START_DATE = "2026-06-10"
END_DATE = "2026-06-12"
SMOKE_FACTOR_EXPR = "Mean($close,5)/$close-1"

EXPECTED_COMMANDS = {
    "backtest",
    "backtest_ui",
    "backtest_viz",
    "category_create",
    "category_delete",
    "category_list",
    "category_rename",
    "clean_logs",
    "daily_signals",
    "daily_state",
    "data_viz",
    "delete_mine_log",
    "delete_run",
    "delete_stock",
    "factor_add",
    "factor_categorize",
    "factor_category_add",
    "factor_category_remove",
    "factor_duplicates",
    "factor_list",
    "factor_rename",
    "factor_validate",
    "list_mine_logs",
    "list_runs",
    "list_stocks",
    "mine",
    "mine_aff",
    "mine_gp",
    "mine_rl",
    "modules",
    "notify_commands",
    "portal",
    "portal_legacy",
    "portal_restart",
    "prepare_data",
    "qlib_yaml_generate",
    "qlib_yaml_validate",
    "refresh_stock",
    "scheduler",
    "strategy_backtest",
    "strategy_backtest_list",
    "strategy_create",
    "timezone",
    "trade_session_cash",
    "trade_session_create",
    "trade_session_delete",
    "trade_session_history",
    "trade_session_list",
    "trade_session_show",
    "trim_stock",
    "ui",
}


@dataclass
class CliContext:
    cwd: Path
    home: Path
    important: Path
    stock_csv: Path
    raw_none: Path
    raw_backward: Path
    factor_dir: Path
    qlib_dir: Path
    h5_out: Path
    runs_dir: Path
    log_dir: Path
    env: dict[str, str]
    coverage: dict[str, str]


@pytest.fixture()
def cli_ctx(tmp_path: Path) -> CliContext:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    important = tmp_path / "important_data"
    stock_lists = important / "stock_lists"
    stock_csv = stock_lists / "mini_real_cli.csv"
    baostock_root = home / ".qlib" / "qlib_data" / "cn_data" / "baostock"
    raw_none = baostock_root / "raw_data_no_adjust"
    raw_backward = baostock_root / "raw_data_back_adjust"
    factor_dir = baostock_root / "adjust_factors"
    qlib_dir = baostock_root / "qlib"
    h5_out = tmp_path / "daily_pv_direct"
    runs_dir = tmp_path / "runs"
    log_dir = tmp_path / "log"

    for path in (
        cwd,
        home,
        important / "factor_zoo",
        important / "strategy_zoo",
        stock_lists,
        raw_none,
        raw_backward,
        factor_dir,
        qlib_dir,
        h5_out,
        runs_dir,
        log_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    stock_csv.write_text("ts_code,name\n000001.SZ,PingAn\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PYTHONPATH": str(REPO_ROOT),
            "ALPHAPILOT_IMPORTANT_DATA_DIR": str(important),
            "ALPHAPILOT_FACTOR_ZOO_DIR": str(important / "factor_zoo"),
            "ALPHAPILOT_STRATEGY_PARAM_DIR": str(important / "strategy_zoo"),
            "ALPHAPILOT_RAW_DATA_DIR": str(raw_backward),
            "ALPHAPILOT_QLIB_DATA_DIR": str(qlib_dir),
            "ALPHAPILOT_ADJUST_FACTOR_DIR": str(factor_dir),
            "ALPHAPILOT_LOG_DIR": str(log_dir),
            "ALPHAPILOT_WORKSPACE_ROOT": str(tmp_path / "workspaces"),
            "ALPHAPILOT_RUNS_DIR": str(runs_dir),
            "ALPHAPILOT_PICKLE_CACHE_ENABLED": "false",
            "ALPHAPILOT_PORTAL_JOB_ROOT": str(tmp_path / "portal_jobs"),
            "ALPHAPILOT_PORTAL_SCHEDULE_ROOT": str(tmp_path / "portal_schedules"),
            "ALPHAPILOT_PORTAL_ENV_PATH": str(tmp_path / "portal_env.json"),
            "ALPHAPILOT_PORTAL_RUNTIME_PATH": str(tmp_path / "portal_runtime.json"),
            "ALPHAPILOT_PORTAL_SETTINGS_PATH": str(tmp_path / "portal_settings.json"),
            "ALPHAPILOT_NOTIFY_CREDENTIALS_PATH": str(tmp_path / "notify.json"),
            "ALPHAPILOT_NOTIFY_COMMAND_ROOT": str(tmp_path / "notify_commands"),
            "ALPHAPILOT_TIMEZONE": "Asia/Shanghai",
            "MPLCONFIGDIR": str(tmp_path / "mplconfig"),
            "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
            "STREAMLIT_SERVER_HEADLESS": "true",
            "USE_LOCAL": "True",
        }
    )
    env.pop("PYTEST_CURRENT_TEST", None)

    return CliContext(
        cwd=cwd,
        home=home,
        important=important,
        stock_csv=stock_csv,
        raw_none=raw_none,
        raw_backward=raw_backward,
        factor_dir=factor_dir,
        qlib_dir=qlib_dir,
        h5_out=h5_out,
        runs_dir=runs_dir,
        log_dir=log_dir,
        env=env,
        coverage={},
    )


def _run_raw(
    ctx: CliContext,
    args: Iterable[str],
    *,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-c", CLI_BOOTSTRAP, *map(str, args)]
    return subprocess.run(
        cmd,
        cwd=ctx.cwd,
        env=ctx.env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _combined(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def _pass(ctx: CliContext, command: str, detail: str = "passed") -> None:
    ctx.coverage[command] = detail


def _skip(ctx: CliContext, command: str, reason: str) -> None:
    ctx.coverage[command] = f"skipped: {reason}"


def _run_ok(
    ctx: CliContext,
    command: str,
    *args: str,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    proc = _run_raw(ctx, (command, *args), timeout=timeout)
    assert proc.returncode == 0, (
        f"alphapilot {command} failed with {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    _pass(ctx, command)
    return proc


def _run_expected_failure(
    ctx: CliContext,
    command: str,
    *args: str,
    patterns: tuple[str, ...],
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    proc = _run_raw(ctx, (command, *args), timeout=timeout)
    out = _combined(proc)
    assert proc.returncode != 0, f"alphapilot {command} unexpectedly passed:\n{out}"
    assert any(p in out for p in patterns), (
        f"alphapilot {command} failed for an unexpected reason.\n"
        f"expected one of: {patterns}\n{out}"
    )
    ctx.coverage[command] = "expected_failure"
    return proc


def _run_optional(
    ctx: CliContext,
    command: str,
    *args: str,
    allowed_patterns: tuple[str, ...],
    timeout: int = 90,
) -> subprocess.CompletedProcess[str]:
    proc = _run_raw(ctx, (command, *args), timeout=timeout)
    out = _combined(proc)
    if proc.returncode == 0:
        _pass(ctx, command)
        return proc
    if any(p in out for p in allowed_patterns):
        ctx.coverage[command] = "expected_failure"
        return proc
    raise AssertionError(
        f"alphapilot {command} failed for an unexpected reason.\n"
        f"expected one of: {allowed_patterns}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _terminate(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _run_service(
    ctx: CliContext,
    command: str,
    *args: str,
    port: int | None = None,
    health_path: str | None = None,
    timeout: int = 20,
) -> None:
    cmd = [sys.executable, "-c", CLI_BOOTSTRAP, command, *map(str, args)]
    proc = subprocess.Popen(
        cmd,
        cwd=ctx.cwd,
        env=ctx.env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=2)
                out = stdout + "\n" + stderr
                allowed = (
                    "No such file or directory",
                    "streamlit",
                    "credentials",
                    "token",
                    "TUSHARE_TOKEN",
                    "No module named",
                    "missing",
                    "disabled",
                )
                if any(item in out for item in allowed):
                    ctx.coverage[command] = "expected_failure"
                    return
                raise AssertionError(f"alphapilot {command} exited early:\n{out}")
            if port is not None:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        if health_path:
                            with urllib.request.urlopen(
                                f"http://127.0.0.1:{port}{health_path}", timeout=3
                            ) as resp:
                                assert resp.status < 500
                        _pass(ctx, command, "started")
                        return
                except (OSError, urllib.error.URLError):
                    pass
            else:
                time.sleep(2)
                if proc.poll() is None:
                    _pass(ctx, command, "started")
                    return
            time.sleep(0.25)
        raise AssertionError(f"alphapilot {command} did not start within {timeout}s")
    finally:
        _terminate(proc)


def _has_llm_credentials(env: dict[str, str]) -> bool:
    return any(
        env.get(name)
        for name in (
            "OPENAI_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "ALPHAPILOT_OPENAI_API_KEY",
        )
    )


def _write_fake_run(ctx: CliContext, run_id: str) -> None:
    run_dir = ctx.runs_dir / run_id
    (run_dir / "workspaces").mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "command": "smoke", "status": "completed"}),
        encoding="utf-8",
    )


def _assert_all_commands_covered(ctx: CliContext) -> None:
    missing = sorted(EXPECTED_COMMANDS - set(ctx.coverage))
    assert not missing, f"CLI commands without smoke coverage: {missing}\n{ctx.coverage}"


@pytest.mark.real_cli
def test_real_cli_command_smoke(cli_ctx: CliContext) -> None:
    if os.getenv("ALPHAPILOT_RUN_REAL_CLI") != "1":
        pytest.skip("set ALPHAPILOT_RUN_REAL_CLI=1 to run real CLI/network smoke tests")

    ctx = cli_ctx

    discovered = _run_ok(ctx, "modules")
    for command in EXPECTED_COMMANDS:
        assert command in _combined(discovered), f"{command} missing from alphapilot modules"

    _write_fake_run(ctx, "smoke-run")
    (ctx.log_dir / "smoke-session").mkdir(parents=True)
    _run_ok(ctx, "list_runs")
    _run_ok(ctx, "delete_run", "--run_id=smoke-run")
    _run_ok(ctx, "list_mine_logs")
    _run_ok(ctx, "delete_mine_log", "--session=smoke-session")
    _run_ok(ctx, "clean_logs")

    _run_ok(ctx, "timezone")
    _run_expected_failure(
        ctx,
        "portal_restart",
        patterns=("No running portal process found",),
        timeout=30,
    )

    _run_ok(ctx, "category_list")
    _run_ok(ctx, "category_create", "--name=cli_smoke")
    _run_ok(ctx, "category_rename", "--old_name=cli_smoke", "--new_name=cli_smoke_renamed")
    _run_ok(ctx, "factor_validate", f"--expression={SMOKE_FACTOR_EXPR}")
    _run_ok(
        ctx,
        "factor_add",
        "--factor_name=cli_factor",
        f"--expression={SMOKE_FACTOR_EXPR}",
        "--categories=cli_smoke_renamed",
    )
    _run_ok(ctx, "factor_rename", "--factor_name=cli_factor", "--new_name=cli_factor_renamed")
    _run_ok(ctx, "factor_categorize", "--factor_name=cli_factor_renamed", "--categories=momentum,smoke")
    _run_ok(ctx, "factor_category_add", "--factor_names=cli_factor_renamed", "--category=bulk_smoke")
    _run_ok(ctx, "factor_category_remove", "--factor_names=cli_factor_renamed", "--category=bulk_smoke")
    _run_ok(ctx, "factor_list")
    _run_ok(ctx, "category_delete", "--name=cli_smoke_renamed")

    _run_ok(
        ctx,
        "prepare_data",
        "--action=download",
        f"--start_date={START_DATE}",
        f"--end_date={END_DATE}",
        f"--stock_csv={ctx.stock_csv}",
        "--adjust_mode=none",
        f"--output_dir={ctx.raw_none}",
        f"--factor_dir={ctx.factor_dir}",
        f"--download_state_path={ctx.home / 'download_state.csv'}",
        "--max_workers=1",
        timeout=180,
    )
    price_csv = ctx.raw_none / f"{STEM}.csv"
    factor_csv = ctx.factor_dir / f"{STEM}.csv"
    assert price_csv.is_file(), f"download did not create {price_csv}"
    assert factor_csv.is_file(), f"download did not create {factor_csv}"
    price_df = pd.read_csv(price_csv)
    assert 1 <= len(price_df) <= 10
    assert price_df["date"].min() >= START_DATE
    assert price_df["date"].max() <= END_DATE

    _run_ok(
        ctx,
        "prepare_data",
        "--action=apply_adjust",
        "--adjust_mode=backward",
        f"--raw_dir={ctx.raw_none}",
        f"--factor_dir={ctx.factor_dir}",
        f"--output_dir={ctx.raw_backward}",
        "--max_workers=1",
        timeout=120,
    )
    assert (ctx.raw_backward / f"{STEM}.csv").is_file()

    hdf_allowed = (
        "numpy.dtype size changed",
        "tables",
        "PyTables",
        "HDFStore",
        "No module named 'tables'",
        "No module named: tables",
    )

    _run_optional(
        ctx,
        "prepare_data",
        "--action=convert",
        f"--stock_csv={ctx.stock_csv}",
        f"--data_path={ctx.raw_backward}",
        "--adjust_mode=backward",
        f"--qlib_dir={ctx.qlib_dir}",
        f"--market={MARKET}",
        f"--start_date={START_DATE}",
        f"--end_date={END_DATE}",
        "--include_benchmark=False",
        "--max_workers=1",
        allowed_patterns=hdf_allowed,
        timeout=180,
    )
    assert (ctx.qlib_dir / "instruments" / f"{MARKET}.txt").is_file()
    assert (ctx.qlib_dir / "calendars" / "day.txt").is_file()
    assert (ctx.qlib_dir / "features" / STEM).is_dir()

    _run_ok(ctx, "list_stocks")
    _run_ok(
        ctx,
        "delete_stock",
        f"--symbol={SYMBOL}",
        "--adjust_mode=backward",
        "--dry_run=True",
    )
    _run_ok(
        ctx,
        "trim_stock",
        f"--symbol={SYMBOL}",
        "--adjust_mode=backward",
        f"--end_date={START_DATE}",
        "--resync_qlib=False",
        "--dry_run=True",
    )
    _run_ok(
        ctx,
        "refresh_stock",
        f"--symbol={SYMBOL}",
        "--adjust_mode=backward",
        f"--start_date={START_DATE}",
        f"--end_date={END_DATE}",
        "--resync_qlib=True",
        "--rebuild_h5=False",
        timeout=180,
    )
    refreshed_df = pd.read_csv(ctx.raw_backward / f"{STEM}.csv")
    assert 1 <= len(refreshed_df) <= 10

    _run_ok(
        ctx,
        "prepare_data",
        "--action=calendar",
        f"--qlib_dir={ctx.qlib_dir}",
        f"--start_date={START_DATE}",
        f"--end_date={END_DATE}",
        timeout=120,
    )
    _run_optional(
        ctx,
        "prepare_data",
        "--action=build_h5",
        f"--qlib_dir={ctx.qlib_dir}",
        f"--output_dir={ctx.h5_out}",
        f"--market={MARKET}",
        f"--start_date={START_DATE}",
        allowed_patterns=hdf_allowed,
        timeout=120,
    )
    if (ctx.h5_out / "daily_pv_all.h5").exists():
        assert (ctx.h5_out / "daily_pv_debug.h5").is_file()
    _run_optional(
        ctx,
        "prepare_data",
        "--action=h5",
        f"--qlib_dir={ctx.qlib_dir}",
        f"--market={MARKET}",
        f"--start_date={START_DATE}",
        allowed_patterns=hdf_allowed,
        timeout=120,
    )

    yaml_path = ctx.cwd / "generated_qlib.yaml"
    _run_ok(
        ctx,
        "qlib_yaml_generate",
        f"--output={yaml_path}",
        "--template=baseline",
        f"--market={MARKET}",
        f"--provider_uri={ctx.qlib_dir}",
        "--skip_smoke=True",
    )
    assert yaml_path.is_file()
    _run_ok(ctx, "qlib_yaml_validate", f"--config={yaml_path}", "--skip_smoke=True")

    _run_ok(
        ctx,
        "strategy_create",
        "--strategy_name=cli_strategy",
        "--factor_names=cli_factor_renamed",
        "--model_name=none",
        f"--market={MARKET}",
    )
    _run_ok(ctx, "strategy_backtest_list")
    _run_optional(
        ctx,
        "strategy_backtest",
        "--strategy_name=cli_strategy",
        f"--qlib_data_dir={ctx.qlib_dir}",
        "--mode=retrain",
        f"--market={MARKET}",
        allowed_patterns=(
            "No module named",
            "not enough",
            "empty",
            "No objects to concatenate",
            "cannot reshape",
            "unsupported",
            "model",
        ),
        timeout=180,
    )

    factor_csv_path = ctx.cwd / "factor_smoke.csv"
    factor_csv_path.write_text(
        f'factor_name,factor_expression\nclose_factor,"{SMOKE_FACTOR_EXPR}"\n',
        encoding="utf-8",
    )
    _run_optional(
        ctx,
        "backtest",
        f"--factor_path={factor_csv_path}",
        "--mode=single_ic",
        f"--market={MARKET}",
        f"--yaml_params={{\"market\":\"{MARKET}\",\"provider_uri\":\"{ctx.qlib_dir}\"}}",
        allowed_patterns=(
            "No module named",
            "not enough",
            "empty",
            "No objects to concatenate",
            "cannot reshape",
            "factor h5",
            "Qlib",
        ),
        timeout=180,
    )

    _run_ok(ctx, "daily_state", "--strategy_name=cli_strategy")
    _run_optional(
        ctx,
        "daily_signals",
        "--strategy_name=cli_strategy",
        f"--market={MARKET}",
        allowed_patterns=(
            "No module named",
            "No model artifact",
            "model",
            "empty",
            "not enough",
            "No objects to concatenate",
        ),
        timeout=120,
    )

    # Trade sessions: list/history/delete are safe no-ops on an unknown name; show raises; create
    # needs a trained model (cli_strategy may lack one), so it is optional.
    _run_ok(ctx, "trade_session_list")
    _run_ok(ctx, "trade_session_history", "--name=__nope__")
    _run_ok(ctx, "trade_session_delete", "--name=__nope__")
    _run_expected_failure(
        ctx,
        "trade_session_show",
        "--name=__nope__",
        patterns=("not found", "Trade session"),
    )
    _run_expected_failure(
        ctx,
        "trade_session_cash",
        "--name=__nope__",
        "--amount=1000",
        patterns=("not found", "Trade session"),
    )
    _run_optional(
        ctx,
        "trade_session_create",
        "--name=cli_session",
        "--strategy_name=cli_strategy",
        allowed_patterns=("trained model", "not found", "No module named", "model"),
        timeout=60,
    )

    if _has_llm_credentials(ctx.env):
        _run_optional(
            ctx,
            "mine",
            "--step_n=1",
            f"--market={MARKET}",
            allowed_patterns=(
                "No module named",
                "empty",
                "not enough",
                "OPENAI",
                "API",
                "model",
            ),
            timeout=180,
        )
    else:
        _skip(ctx, "mine", "missing LLM credentials")

    alphaforge_allowed = (
        "No module named",
        "ModuleNotFoundError",
        "ImportError",
        "empty",
        "not enough",
        "cannot reshape",
        "index",
        "least one array",
        "Found array with 0",
    )
    _run_optional(
        ctx,
        "mine_gp",
        f"--instruments={MARKET}",
        "--train_end_year=2026",
        "--population_size=4",
        "--generations=1",
        "--tournament_size=2",
        "--top_n=1",
        "--device=cpu",
        f"--qlib_dir={ctx.qlib_dir}",
        "--backtest=False",
        "--save=False",
        allowed_patterns=alphaforge_allowed,
        timeout=120,
    )
    _run_optional(
        ctx,
        "mine_aff",
        f"--instruments={MARKET}",
        "--train_end_year=2026",
        "--zoo_size=1",
        "--max_len=4",
        "--device=cpu",
        f"--qlib_dir={ctx.qlib_dir}",
        "--backtest=False",
        "--save=False",
        "--batch_size=4",
        "--num_epochs_g=1",
        "--num_epochs_p=1",
        "--init_collect=4",
        "--iter_collect=2",
        "--max_iter_init=2",
        "--max_iter=1",
        "--max_loops=1",
        allowed_patterns=alphaforge_allowed,
        timeout=120,
    )
    _run_optional(
        ctx,
        "mine_rl",
        f"--instruments={MARKET}",
        "--train_end_year=2026",
        "--steps=1",
        "--pool_capacity=1",
        "--device=cpu",
        f"--qlib_dir={ctx.qlib_dir}",
        "--backtest=False",
        "--save=False",
        allowed_patterns=alphaforge_allowed
        + (
            "gym",
            "shimmy",
            "stable_baselines3",
            "sb3_contrib",
        ),
        timeout=120,
    )

    if ctx.env.get("TUSHARE_TOKEN"):
        tushare_raw = ctx.home / ".qlib" / "qlib_data" / "cn_data" / "tushare" / "raw_data_no_adjust"
        _run_optional(
            ctx,
            "prepare_data",
            "--action=download",
            f"--start_date={START_DATE}",
            f"--end_date={END_DATE}",
            f"--stock_csv={ctx.stock_csv}",
            "--adjust_mode=none",
            "--source=tushare_cn",
            f"--output_dir={tushare_raw}",
            "--max_workers=1",
            allowed_patterns=("TUSHARE_TOKEN", "token", "积分", "rate", "permission"),
            timeout=180,
        )
        if (tushare_raw / f"{STEM}.csv").exists():
            assert len(pd.read_csv(tushare_raw / f"{STEM}.csv")) <= 10

    _run_service(ctx, "scheduler", "--interval=1", timeout=8)
    _run_service(ctx, "notify_commands", "--channel=telegram", "--poll_interval=0.1", timeout=8)
    _run_ok(ctx, "ui")
    _run_ok(ctx, "backtest_ui")

    portal_port = _free_port()
    _run_service(
        ctx,
        "portal",
        f"--port={portal_port}",
        "--host=127.0.0.1",
        port=portal_port,
        health_path="/api/status",
        timeout=30,
    )
    _run_service(ctx, "portal_legacy", f"--port={_free_port()}", "--host=127.0.0.1", timeout=12)
    _run_service(ctx, "data_viz", f"--port={_free_port()}", "--host=127.0.0.1", timeout=12)
    _run_service(ctx, "backtest_viz", f"--port={_free_port()}", "--host=127.0.0.1", timeout=12)

    _assert_all_commands_covered(ctx)
