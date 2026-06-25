"""Tests for the enhanced inbound chat-command features:

pairing codes + /start flow, sandboxed file browsing, per-chat transcripts,
multi-turn planner context, the COMMAND_SPECS/menu single source of truth, and
the Telegram setMyCommands / sendDocument payloads.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from alphapilot.modules.portal import jobs
from alphapilot.systems.notify import config as notify_config
from alphapilot.systems.notify import fsbrowse, inbound
from alphapilot.systems.notify import receivers
from alphapilot.systems.notify.commands import (
    COMMAND_SPECS,
    dispatch_text,
    parse_command,
)


def _setup(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("ALPHAPILOT_NOTIFY_CREDENTIALS_PATH", str(tmp_path / "notify.json"))
    monkeypatch.setenv("ALPHAPILOT_NOTIFY_COMMAND_ROOT", str(tmp_path / "cmd"))


def _save(telegram: dict[str, Any] | None = None, options: dict[str, Any] | None = None) -> None:
    notify_config.save_notify_config(
        {
            "telegram": telegram or {},
            "feishu": {},
            "email": {},
            "options": options or {},
        }
    )


# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #
def test_pair_code_create_redeem_single_use(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _setup(tmp_path, monkeypatch)
    item = inbound.create_pair_code("telegram", ttl_minutes=5)
    assert re.fullmatch(r"[A-Z0-9]{6}", item["code"])

    redeemed = inbound.redeem_pair_code(item["code"].lower(), "telegram")  # case-insensitive
    assert redeemed["channel"] == "telegram"

    with pytest.raises(ValueError):  # single use
        inbound.redeem_pair_code(item["code"], "telegram")


def test_pair_code_expiry_and_channel_mismatch(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _setup(tmp_path, monkeypatch)
    expired = inbound.create_pair_code("telegram", ttl_minutes=-1)
    with pytest.raises(ValueError):
        inbound.redeem_pair_code(expired["code"], "telegram")

    other = inbound.create_pair_code("telegram", ttl_minutes=5)
    with pytest.raises(ValueError):
        inbound.redeem_pair_code(other["code"], "feishu")


def test_start_pairing_bypasses_allowlist_and_enrolls(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _setup(tmp_path, monkeypatch)
    # Receiver enabled but no users yet -> a normal command is rejected.
    _save(telegram={"receive_enabled": True, "allowed_user_ids": []})
    rejected = dispatch_text("/jobs", channel="telegram", user_id="42", chat_id="100", enforce_auth=True)
    assert rejected["ok"] is False
    assert "未授权" in rejected["reply"]

    code = inbound.create_pair_code("telegram")["code"]
    paired = dispatch_text(
        f"/start {code}", channel="telegram", user_id="42", chat_id="100", enforce_auth=True
    )
    assert paired["ok"] is True
    assert "配对成功" in paired["reply"]

    cfg = notify_config.load_file_config()
    assert "42" in cfg["telegram"]["allowed_user_ids"]
    assert cfg["telegram"]["receive_enabled"] is True

    # Now the same user is authorized for a normal command.
    monkeypatch.setattr(jobs, "list_jobs", lambda **_o: [])
    follow = dispatch_text("/jobs", channel="telegram", user_id="42", chat_id="100", enforce_auth=True)
    assert follow["ok"] is True


def test_bad_pair_code_is_rejected_via_dispatch(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _setup(tmp_path, monkeypatch)
    _save(telegram={"receive_enabled": True, "allowed_user_ids": []})
    res = dispatch_text("/start ZZZZZZ", channel="telegram", user_id="9", chat_id="9", enforce_auth=True)
    assert res["ok"] is False
    cfg = notify_config.load_file_config()
    assert "9" not in cfg["telegram"]["allowed_user_ids"]  # not enrolled on a bad code


# --------------------------------------------------------------------------- #
# Sandboxed file browser
# --------------------------------------------------------------------------- #
def test_fsbrowse_sandbox_and_denylist(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _setup(tmp_path, monkeypatch)
    sandbox = tmp_path / "box"
    (sandbox / "sub").mkdir(parents=True)
    (sandbox / "sub" / "a.txt").write_text("hello")
    (sandbox / "data.csv").write_text("x,y\n1,2\n")
    (sandbox / ".env").write_text("SECRET=1")
    (sandbox / "api_token.txt").write_text("tok")
    (sandbox / "big.bin").write_bytes(b"0" * (300 * 1024))
    _save(options={"file_browse_enabled": True, "file_browse_root": str(sandbox), "file_browse_max_kb": 256})

    assert "data.csv" in fsbrowse.ls("")
    assert ".env" not in fsbrowse.ls("")  # denied files hidden from listings
    assert "hello" in fsbrowse.read_text("sub/a.txt")

    for bad in ["../etc/passwd", "..", "sub/../../x", ".env", "api_token.txt"]:
        with pytest.raises(fsbrowse.FileBrowseError):
            fsbrowse.read_text(bad)

    with pytest.raises(fsbrowse.FileBrowseError):  # oversized
        fsbrowse.file_for_download("big.bin")
    assert fsbrowse.file_for_download("data.csv").name == "data.csv"


def test_fsbrowse_disabled_and_download_gate(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _setup(tmp_path, monkeypatch)
    sandbox = tmp_path / "box"
    sandbox.mkdir()
    (sandbox / "f.txt").write_text("hi")

    _save(options={"file_browse_enabled": False, "file_browse_root": str(sandbox)})
    with pytest.raises(fsbrowse.FileBrowseError):
        fsbrowse.ls("")

    _save(options={"file_browse_enabled": True, "file_browse_root": str(sandbox), "file_browse_allow_download": False})
    with pytest.raises(fsbrowse.FileBrowseError):
        fsbrowse.file_for_download("f.txt")


def test_get_command_returns_document_path(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _setup(tmp_path, monkeypatch)
    sandbox = tmp_path / "box"
    sandbox.mkdir()
    (sandbox / "r.json").write_text('{"ok": true}')
    _save(
        telegram={"receive_enabled": True, "allowed_user_ids": ["7"]},
        options={"file_browse_enabled": True, "file_browse_root": str(sandbox)},
    )
    res = dispatch_text("/get r.json", channel="telegram", user_id="7", chat_id="7", enforce_auth=True)
    assert res["ok"] is True
    assert res["data"]["document_path"].endswith("r.json")


# --------------------------------------------------------------------------- #
# Transcripts + multi-turn context
# --------------------------------------------------------------------------- #
def test_transcript_roundtrip_and_dispatch_writes_turn(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _setup(tmp_path, monkeypatch)
    inbound.append_turn("telegram", "-1009", {"text": "one", "reply": "r1", "ok": True})
    inbound.append_turn("telegram", "-1009", {"text": "two", "reply": "r2", "ok": True})
    turns = inbound.recent_turns("telegram", "-1009", limit=6)
    assert [t["text"] for t in turns] == ["one", "two"]  # ordered oldest-first

    _save(telegram={"receive_enabled": True, "allowed_user_ids": ["7"]})
    monkeypatch.setattr(jobs, "list_jobs", lambda **_o: [])
    dispatch_text("/jobs", channel="telegram", user_id="7", chat_id="555", enforce_auth=True)
    assert inbound.recent_turns("telegram", "555")[-1]["text"] == "/jobs"


def test_natural_language_planner_receives_history(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    _setup(tmp_path, monkeypatch)
    _save(telegram={"receive_enabled": True, "allowed_user_ids": ["u1"]})
    inbound.append_turn("telegram", "c1", {"text": "mine momentum factors", "reply": "started job X", "ok": True})
    monkeypatch.setattr(jobs, "list_jobs", lambda **_o: [])

    captured: dict[str, str] = {}

    class FakeLLM:
        def chat_completion(self, prompt: str, **_kw: Any) -> str:
            captured["prompt"] = prompt
            return '{"action":"status","summary":"ok"}'

    dispatch_text(
        "what about it",
        channel="telegram",
        user_id="u1",
        chat_id="c1",
        enforce_auth=True,
        llm_factory=lambda: FakeLLM(),
    )
    assert "mine momentum factors" in captured["prompt"]
    assert "Current request: what about it" in captured["prompt"]


# --------------------------------------------------------------------------- #
# Command specs / parser / Telegram payloads
# --------------------------------------------------------------------------- #
def test_command_specs_are_telegram_legal() -> None:
    names = [s["command"] for s in COMMAND_SPECS]
    assert len(names) == len(set(names))  # unique
    for spec in COMMAND_SPECS:
        assert re.fullmatch(r"[a-z0-9_]{1,32}", spec["command"])
        assert 1 <= len(spec["desc"]) <= 256


def test_parse_command_routes_new_commands() -> None:
    assert parse_command("/start ABC123").action == "pair"
    assert parse_command("/start ABC123").kwargs == {"code": "ABC123"}
    assert parse_command("/start").action == "help"
    assert parse_command("/ls runs/2026").kwargs == {"path": "runs/2026"}
    assert parse_command("/tree").action == "fs_tree"
    assert parse_command("/cat a/b.txt").action == "fs_cat"
    assert parse_command("/get x.csv").action == "fs_get"
    with pytest.raises(ValueError):
        parse_command("/cat")
    with pytest.raises(ValueError):
        parse_command("/get")


def test_telegram_set_my_commands_payload(monkeypatch) -> None:  # noqa: ANN001
    calls: dict[str, Any] = {}

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url: str, json: Any = None, **_kw: Any) -> FakeResp:
        calls["url"] = url
        calls["json"] = json
        return FakeResp()

    monkeypatch.setattr(receivers.requests, "post", fake_post)
    receivers.telegram_set_my_commands("TOKEN")
    assert calls["url"].endswith("/setMyCommands")
    sent = {c["command"] for c in calls["json"]["commands"]}
    assert {"start", "ls", "get", "jobs"} <= sent


def test_telegram_send_document_payload(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    doc = tmp_path / "doc.txt"
    doc.write_text("hi")
    sent: dict[str, Any] = {}

    class FakeResp:
        def raise_for_status(self) -> None:
            return None

    def fake_post(url: str, data: Any = None, files: Any = None, **_kw: Any) -> FakeResp:
        sent["url"] = url
        sent["data"] = data
        sent["has_file"] = files is not None
        return FakeResp()

    monkeypatch.setattr(receivers.requests, "post", fake_post)
    receivers.telegram_send_document("TOKEN", "100", str(doc), caption="cap")
    assert sent["url"].endswith("/sendDocument")
    assert sent["data"]["chat_id"] == "100"
    assert sent["has_file"] is True
