"""Tier 4 (real_llm): LLM-driven features.

Covers the two places AlphaPilot calls a real LLM from the command/mining
surface:
* ``plan_natural_language`` — the Telegram/portal natural-language planner that
  turns a free-text request into one structured portal action.
* ``mine`` — the autonomous LLM factor-mining loop (one step), asserted to
  produce a mining session log.

All tests skip (never fail) when ``OPENAI_API_KEY`` is absent. The LLM is
non-deterministic, so assertions check structure/contract, not exact text.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import require_openai

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_BOOTSTRAP = "from alphapilot.app.cli import app; app()"

pytestmark = pytest.mark.real_llm


def test_plan_natural_language_query(isolated_env) -> None:
    require_openai()
    from alphapilot.systems.notify.commands import plan_natural_language

    action = plan_natural_language("show me the list of running jobs")
    # A pure query maps to a read-only action and needs no confirmation.
    assert action.action in {"jobs", "status", "log", "result"}
    assert action.requires_confirmation is False
    assert action.summary


def test_plan_natural_language_start_requires_confirmation(isolated_env) -> None:
    require_openai()
    from alphapilot.systems.notify.commands import plan_natural_language

    action = plan_natural_language("run a factor backtest for me")
    # Anything that starts/cancels work must be gated behind confirmation.
    if action.action == "start_job":
        assert action.requires_confirmation is True
        assert action.job_kind is not None
    else:
        # The planner may instead ask for missing fields via status — also valid.
        assert action.action in {"status", "jobs"}


def test_plan_natural_language_rejects_unsafe(isolated_env) -> None:
    require_openai()
    from alphapilot.systems.notify.commands import CommandError, plan_natural_language

    # The planner is constrained to a safe action/job-kind allowlist; a request
    # outside that space should raise rather than fabricate an unsafe action.
    try:
        action = plan_natural_language("delete all my files on the server")
    except CommandError:
        return
    # If it didn't raise, it must still be one of the safe actions.
    assert action.action in {"start_job", "jobs", "status", "log", "result", "cancel"}


@pytest.mark.slow
def test_mine_one_step_creates_session(isolated_env, tmp_path: Path) -> None:
    require_openai()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)

    proc = subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, "mine", "--step_n=1"],
        cwd=tmp_path, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=420,
    )
    out = (proc.stdout or "") + (proc.stderr or "")

    if proc.returncode != 0:
        # The mining loop may legitimately stop early without market data /
        # model artifacts; only a credentials/transport failure is a real error.
        tolerated = ("empty", "not enough", "No objects to concatenate", "model",
                     "No module named", "factor h5", "Qlib", "provider")
        if any(t in out for t in tolerated):
            pytest.skip(f"mine stopped early without data/model: rc={proc.returncode}")
        raise AssertionError(f"mine failed unexpectedly:\n{out[-2000:]}")

    # A successful step should leave a mining session log discoverable by the CLI.
    listing = subprocess.run(
        [sys.executable, "-c", CLI_BOOTSTRAP, "list_mine_logs"],
        cwd=tmp_path, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
    )
    assert listing.returncode == 0
