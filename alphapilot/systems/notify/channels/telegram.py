"""Telegram bot channel (Bot API ``sendMessage``, HTML parse mode)."""

from __future__ import annotations

import requests

from alphapilot.systems.notify.channels.base import BaseChannel, ChannelCapabilities, render_telegram_html
from alphapilot.systems.notify.models import Message

_TIMEOUT = 15


class TelegramChannel(BaseChannel):
    name = "telegram"
    capabilities = ChannelCapabilities(supports_actions=True)

    def is_configured(self) -> bool:
        return bool(self.conf.get("enabled") and self.conf.get("bot_token") and self.conf.get("chat_id"))

    def send(self, message: Message) -> None:
        token = self.conf["bot_token"]
        payload: dict = {
            "chat_id": str(self.conf["chat_id"]),
            "text": render_telegram_html(message),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        links = [a for a in message.actions if a.kind == "link" and a.value]
        if links:
            payload["reply_markup"] = {
                "inline_keyboard": [[{"text": a.label, "url": a.value}] for a in links]
            }
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=_TIMEOUT
        )
        # Don't raise_for_status() first: Telegram returns the actionable reason
        # (e.g. "can't parse entities", "chat not found") in the JSON body on 4xx.
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if not resp.ok or not data.get("ok"):
            detail = data.get("description") or resp.text[:300]
            raise RuntimeError(f"Telegram API {resp.status_code}: {detail}")
