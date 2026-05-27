"""
CLI entrance for all alphaagent application.

This will 
- make alphaagent a nice entry and
- autoamtically load dotenv
"""

from dotenv import load_dotenv

load_dotenv(".env")
# 1) Make sure it is at the beginning of the script so that it will load dotenv before initializing BaseSettings.
# 2) The ".env" argument is necessary to make sure it loads `.env` from the current directory.

import subprocess
from importlib.resources import path as rpath

import fire
from alphaagent.app.data.prepare_data import PrepareDataCLI
from alphaagent.app.qlib_rd_loop.factor_mining import main as mine
from alphaagent.app.qlib_rd_loop.factor_backtest import main as backtest
from alphaagent.app.utils.health_check import health_check
from alphaagent.app.utils.info import collect_info


def ui(port=19899, log_dir="./log", debug=False):
    """
    start web app to show the log traces.
    """
    with rpath("alphaagent.log.ui", "app.py") as app_path:
        cmds = ["streamlit", "run", app_path, f"--server.port={port}"]
        if log_dir or debug:
            cmds.append("--")
        if log_dir:
            cmds.append(f"--log_dir={log_dir}")
        if debug:
            cmds.append("--debug")
        subprocess.run(cmds)


def backtest_ui(port=19900, workspace_root=None, log_dir="./log"):
    """
    Visualize daily trades, holdings, and return curves from backtest workspaces.
    """
    with rpath("alphaagent.app.backtest_viewer", "app.py") as app_path:
        cmds = ["streamlit", "run", str(app_path), f"--server.port={port}"]
        import os

        if workspace_root:
            os.environ["ALPHAAGENT_BACKTEST_ROOT"] = workspace_root
        if log_dir:
            os.environ["ALPHAAGENT_LOG_DIR"] = log_dir
        subprocess.run(cmds)


def prepare_data():
    """Prepare A-share data: download CSV, convert to Qlib, calendar, and h5."""
    import sys

    argv = sys.argv[1:]
    if argv[:1] == ["prepare_data"]:
        argv = argv[1:]
    fire.Fire(PrepareDataCLI, command=argv)
    # Inner Fire handled all subcommand args; stop outer Fire from re-parsing them.
    raise SystemExit(0)


def app():
    fire.Fire(
        {
            "mine": mine,
            "backtest": backtest,
            "prepare_data": prepare_data,
            "ui": ui,
            "backtest_ui": backtest_ui,
            "health_check": health_check,
            "collect_info": collect_info,
        }
    )
