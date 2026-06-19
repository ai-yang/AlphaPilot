"""Feishu (Lark) custom-bot webhook channel (interactive card + optional sign)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

import requests

from alphapilot.systems.notify.channels.base import BaseChannel, ChannelCapabilities
from alphapilot.systems.notify.models import Message, NotifyLevel

_TIMEOUT = 15
_TEMPLATE = {
    NotifyLevel.INFO: "blue",
    NotifyLevel.SUCCESS: "green",
    NotifyLevel.WARNING: "orange",
    NotifyLevel.ERROR: "red",
}


def _sign(secret: str, timestamp: int) -> str:
    # Feishu custom-bot signature: HMAC-SHA256 keyed by "<ts>\n<secret>", empty msg.
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


class FeishuChannel(BaseChannel):
    name = "feishu"
    capabilities = ChannelCapabilities(supports_actions=True)

    def is_configured(self) -> bool:
        return bool(self.conf.get("enabled") and self.conf.get("webhook"))

    def _card(self, message: Message) -> dict:
        md = message.body or ""
        if message.fields:
            field_lines = "\n".join(f"**{k}**: {v}" for k, v in message.fields.items())
            md = f"{md}\n{field_lines}" if md else field_lines
        elements: list[dict] = [{"tag": "div", "text": {"tag": "lark_md", "content": md or " "}}]
        links = [a for a in message.actions if a.kind == "link" and a.value]
        if links:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": a.label},
                            "url": a.value,
                            "type": "default",
                        }
                        for a in links
                    ],
                }
            )
        return {
            "header": {
                "title": {"tag": "plain_text", "content": f"{message.emoji()} {message.title}".strip()},
                "template": _TEMPLATE.get(message.level, "blue"),
            },
            "elements": elements,
        }

    def send(self, message: Message) -> None:
        payload: dict = {"msg_type": "interactive", "card": self._card(message)}
        secret = self.conf.get("secret")
        if secret:
            ts = int(time.time())
            payload["timestamp"] = str(ts)
            payload["sign"] = _sign(secret, ts)
        resp = requests.post(self.conf["webhook"], json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        code = data.get("code", data.get("StatusCode", 0))
        if code not in (0, None):
            raise RuntimeError(f"Feishu API error: {data}")
