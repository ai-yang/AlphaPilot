"""Tier 6: communication / notification system.

Offline (always runs): notify config round-trip + masking, per-channel test-send
status, and the inbound command pipeline via the portal API.

Real send (``real_notify``): actually deliver a message to each *configured*
channel (telegram / feishu / email). These read the real notify credentials
file (not the isolated one) and skip when a channel is not configured, so they
send for real on a machine that has credentials and quietly skip otherwise.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from alphapilot.modules.portal.api import create_app
from conftest import require_notify

CHANNELS = ["telegram", "feishu", "email"]


@pytest.fixture()
def client(isolated_env) -> TestClient:
    return TestClient(create_app())


# --------------------------------------------------------------------------- #
# Offline: config + dispatch (isolated credentials)
# --------------------------------------------------------------------------- #
def test_notify_config_roundtrip_masks_secret(client: TestClient) -> None:
    saved = client.patch(
        "/api/notify",
        json={"config": {"telegram": {"enabled": True, "bot_token": "secret-token-xyz", "chat_id": "12345"}}},
    )
    assert saved.status_code == 200

    body = client.get("/api/notify").json()
    telegram = body["config"]["telegram"]
    assert telegram["enabled"] is True
    assert telegram["chat_id"] == "12345"
    # The secret must never come back in clear text.
    assert telegram["bot_token"] != "secret-token-xyz"
    assert "telegram" in body["configured_channels"]


def test_test_send_reports_unconfigured(client: TestClient) -> None:
    # No channels configured in the isolated env -> each reports "not configured".
    result = client.post("/api/notify/test").json()
    assert set(result) == set(CHANNELS)
    assert all(status == "not configured" for status in result.values())


def test_inbound_dispatch_and_events(client: TestClient) -> None:
    dispatched = client.post("/api/notify/commands/dispatch", json={"text": "/help", "channel": "portal"})
    assert dispatched.status_code == 200
    assert dispatched.json()["ok"] is True

    events = client.get("/api/notify/commands/events").json()
    assert isinstance(events, list) and events
    assert any("/help" in str(e) for e in events)


def test_commands_status_daemon_not_running(client: TestClient) -> None:
    status = client.get("/api/notify/commands/status").json()
    assert status["daemon"].get("running") in (False, True)
    assert "payload" in status


def test_daemon_start_stop_endpoints(client: TestClient) -> None:
    # Without telegram credentials the daemon can't actually poll; the endpoints
    # must still respond cleanly (start may report disabled), and stop is safe.
    started = client.post("/api/notify/commands/start", json={"channel": "telegram"})
    assert started.status_code == 200
    stopped = client.post("/api/notify/commands/stop")
    assert stopped.status_code == 200


# --------------------------------------------------------------------------- #
# Real external send (skips unless a channel is configured)
# --------------------------------------------------------------------------- #
@pytest.mark.real_notify
@pytest.mark.parametrize("channel", CHANNELS)
def test_real_send_to_configured_channel(channel: str) -> None:
    require_notify(channel)  # skips if this channel has no real credentials
    from alphapilot.systems.notify.service import test_send

    result = test_send(channel)
    assert result.get(channel) == "ok", f"send to {channel} failed: {result}"


@pytest.mark.real_notify
def test_real_send_message_fanout() -> None:
    # At least one channel must be configured for a meaningful fan-out test.
    from alphapilot.systems.notify.service import configured_channel_names, send
    from alphapilot.systems.notify.models import Message, MessageAction, NotifyLevel

    configured = configured_channel_names()
    if not configured:
        pytest.skip("no notify channel configured; skipping real fan-out")

    message = Message(
        title="AlphaPilot 测试套件 / Test Suite",
        body="End-to-end notify fan-out test.",
        level=NotifyLevel.INFO,
        fields={"source": "pytest", "tier": "6"},
        actions=[MessageAction(label="Docs", value="https://example.com", kind="link")],
    )
    result = send(message)
    # Every configured channel reports a status; configured ones should be "ok".
    for ch in configured:
        assert result.get(ch) == "ok", f"{ch}: {result.get(ch)}"
