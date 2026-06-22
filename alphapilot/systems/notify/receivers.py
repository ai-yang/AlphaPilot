"""Inbound receivers for Telegram and Feishu command messages."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

import requests

from alphapilot.systems.notify.commands import COMMAND_SPECS, dispatch_text
from alphapilot.systems.notify.config import load_notify_config
from alphapilot.systems.notify.inbound import (
    InboundMessage,
    append_event,
    load_telegram_offset,
    save_telegram_offset,
)

_TIMEOUT = 20


def _telegram_api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


def telegram_reply(token: str, chat_id: str, text: str) -> None:
    requests.post(
        _telegram_api(token, "sendMessage"),
        json={"chat_id": str(chat_id), "text": text[:4000], "disable_web_page_preview": True},
        timeout=15,
    ).raise_for_status()


def telegram_send_document(token: str, chat_id: str, path: str, *, caption: str | None = None) -> None:
    """Upload a local file to the chat via ``sendDocument`` (multipart)."""
    file_path = Path(path)
    data: dict[str, Any] = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption[:1000]
    with file_path.open("rb") as handle:
        requests.post(
            _telegram_api(token, "sendDocument"),
            data=data,
            files={"document": (file_path.name, handle)},
            timeout=60,
        ).raise_for_status()


def telegram_set_my_commands(token: str) -> None:
    """Register the command palette so Telegram shows commands + descriptions."""
    commands = [
        {"command": spec["command"], "description": spec["desc"][:256]} for spec in COMMAND_SPECS
    ]
    resp = requests.post(
        _telegram_api(token, "setMyCommands"), json={"commands": commands}, timeout=15
    )
    resp.raise_for_status()


def telegram_message_from_update(update: dict[str, Any]) -> InboundMessage | None:
    msg = update.get("message") or update.get("edited_message")
    if not isinstance(msg, dict):
        return None
    text = msg.get("text") or msg.get("caption") or ""
    if not str(text).strip():
        return None
    user = msg.get("from") if isinstance(msg.get("from"), dict) else {}
    chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
    return InboundMessage(
        channel="telegram",
        text=str(text),
        user_id=str(user.get("id") or ""),
        user_name=str(user.get("username") or user.get("first_name") or ""),
        chat_id=str(chat.get("id") or ""),
        chat_type=str(chat.get("type") or ""),
        message_id=str(msg.get("message_id") or update.get("update_id") or ""),
        raw=update,
    )


def handle_telegram_update(update: dict[str, Any], *, token: str | None = None) -> dict[str, Any] | None:
    cfg = load_notify_config()
    token = token or str(cfg.get("telegram", {}).get("bot_token") or "")
    msg = telegram_message_from_update(update)
    if msg is None:
        return None
    result = dispatch_text(
        msg.text,
        channel="telegram",
        user_id=msg.user_id,
        chat_id=msg.chat_id,
        user_name=msg.user_name,
        raw=update,
        enforce_auth=True,
    )
    if token and msg.chat_id:
        document = (result.get("data") or {}).get("document_path") if isinstance(result, dict) else None
        try:
            if document:
                telegram_send_document(token, msg.chat_id, document, caption=result.get("reply"))
            else:
                telegram_reply(token, msg.chat_id, result.get("reply") or "")
        except Exception as exc:  # noqa: BLE001
            append_event(
                {
                    "channel": "telegram",
                    "text": msg.text,
                    "ok": False,
                    "error": f"Telegram reply failed: {type(exc).__name__}: {exc}",
                }
            )
            # If the document upload failed, still tell the user in plain text.
            if document:
                try:
                    telegram_reply(
                        token, msg.chat_id, f"{result.get('reply') or ''}\n(文件发送失败 / file send failed: {exc})"
                    )
                except Exception:  # noqa: BLE001
                    pass
    return result


def run_telegram_polling(poll_interval: float | None = None) -> None:
    cfg = load_notify_config()
    telegram = cfg.get("telegram", {}) if isinstance(cfg.get("telegram"), dict) else {}
    token = str(telegram.get("bot_token") or "")
    if not telegram.get("receive_enabled"):
        raise RuntimeError("Telegram command receiver is disabled")
    if not token:
        raise RuntimeError("Telegram bot_token is required for command receiver")
    interval = float(poll_interval or telegram.get("poll_interval") or 2)
    # Register the command palette once at startup (best-effort).
    try:
        telegram_set_my_commands(token)
    except Exception as exc:  # noqa: BLE001
        print(f"[notify-commands] setMyCommands failed: {type(exc).__name__}: {exc}", flush=True)
    # Restore the saved offset so a restart never replays already-handled commands.
    offset: int | None = load_telegram_offset()
    while True:
        params: dict[str, Any] = {"timeout": 20, "allowed_updates": json.dumps(["message", "edited_message"])}
        if offset is not None:
            params["offset"] = offset
        try:
            resp = requests.get(_telegram_api(token, "getUpdates"), params=params, timeout=_TIMEOUT + 5)
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("ok"):
                raise RuntimeError(payload)
            for update in payload.get("result", []):
                update_id = int(update.get("update_id", 0))
                offset = max(offset or 0, update_id + 1)
                handle_telegram_update(update, token=token)
                save_telegram_offset(offset)  # persist per-update: no replay on crash/restart
        except Exception as exc:  # noqa: BLE001
            append_event({"channel": "telegram", "ok": False, "error": f"polling failed: {type(exc).__name__}: {exc}"})
            print(f"[notify-commands] telegram polling failed: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(max(interval, 5))
        else:
            time.sleep(interval)


def run_feishu_placeholder() -> None:
    print(
        "[notify-commands] Feishu receive mode is served by the portal FastAPI callback "
        "POST /api/notify/feishu/events. Keep `alphapilot portal` running.",
        flush=True,
    )
    while True:
        time.sleep(3600)


def verify_feishu_signature(
    *,
    body: bytes,
    timestamp: str | None,
    nonce: str | None,
    signature: str | None,
    encrypt_key: str | None,
) -> bool:
    if not encrypt_key:
        return True
    if not timestamp or not nonce or not signature:
        return False
    base = (timestamp + nonce + encrypt_key).encode("utf-8") + body
    expected = hashlib.sha256(base).hexdigest()
    return hmac.compare_digest(expected, signature)


def feishu_message_from_event(payload: dict[str, Any]) -> InboundMessage | None:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else payload
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_id = sender.get("sender_id") if isinstance(sender.get("sender_id"), dict) else {}
    chat_id = message.get("chat_id") or message.get("open_chat_id") or sender_id.get("open_id") or ""
    user_id = sender_id.get("user_id") or sender_id.get("open_id") or sender_id.get("union_id") or ""
    text = ""
    content = message.get("content")
    if isinstance(content, str):
        try:
            content_payload = json.loads(content)
            text = str(content_payload.get("text") or content_payload.get("content") or "")
        except json.JSONDecodeError:
            text = content
    if not text.strip():
        return None
    return InboundMessage(
        channel="feishu",
        text=text,
        user_id=str(user_id),
        chat_id=str(chat_id),
        chat_type=str(message.get("chat_type") or ""),
        message_id=str(message.get("message_id") or payload.get("uuid") or ""),
        raw=payload,
    )


def handle_feishu_event(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}
    msg = feishu_message_from_event(payload)
    if msg is None:
        return {"ok": True, "ignored": True}
    return dispatch_text(
        msg.text,
        channel="feishu",
        user_id=msg.user_id,
        chat_id=msg.chat_id,
        raw=payload,
        enforce_auth=True,
    )
