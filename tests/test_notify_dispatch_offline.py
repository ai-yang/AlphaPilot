"""Tier 1 (offline): inbound command dispatch logic.

Drives ``dispatch_text`` through the isolated notify command store so the
parse → authorize → execute pipeline can be asserted without any external
channel. Complements ``test_notify_inbound_features.py`` (pairing/fsbrowse/
planner) by covering the everyday read-only commands and the auth gate.
"""

from __future__ import annotations

import pytest

from alphapilot.systems.notify.commands import dispatch_text


pytestmark = pytest.mark.usefixtures("isolated_env")


def test_help_command_returns_command_list() -> None:
    result = dispatch_text("/help")
    assert result["ok"] is True
    assert "commands" in result["reply"] or "命令" in result["reply"]


def test_jobs_command_lists_no_jobs_initially() -> None:
    result = dispatch_text("/jobs")
    assert result["ok"] is True
    assert isinstance(result["reply"], str) and result["reply"].strip()


def test_unknown_command_fails_gracefully() -> None:
    result = dispatch_text("/definitely_not_a_command")
    assert result["ok"] is False
    assert result["reply"]


def test_portal_channel_bypasses_auth_by_default() -> None:
    # The portal UI dispatches with enforce_auth=False (trusted local caller).
    result = dispatch_text("/help", channel="portal")
    assert result["ok"] is True


def test_enforce_auth_blocks_unconfigured_channel() -> None:
    # With auth enforced and no telegram allowlist configured, the receiver is
    # disabled, so even /jobs is rejected before parsing.
    result = dispatch_text(
        "/jobs", channel="telegram", user_id="999", chat_id="999", enforce_auth=True
    )
    assert result["ok"] is False
    assert "未授权" in result["reply"]


def test_dispatch_writes_event_log(isolated_env) -> None:
    dispatch_text("/help")
    events = isolated_env.notify_command_root / "events.jsonl"
    assert events.exists()
    assert events.read_text(encoding="utf-8").strip()
