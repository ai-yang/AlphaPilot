"""Notification transport channels."""

from alphapilot.systems.notify.channels.base import BaseChannel, ChannelCapabilities
from alphapilot.systems.notify.channels.email import EmailChannel
from alphapilot.systems.notify.channels.feishu import FeishuChannel
from alphapilot.systems.notify.channels.telegram import TelegramChannel

# Registry: channel name -> implementation. Adding a channel = add a class here.
CHANNEL_CLASSES: dict[str, type[BaseChannel]] = {
    "telegram": TelegramChannel,
    "feishu": FeishuChannel,
    "email": EmailChannel,
}

__all__ = [
    "BaseChannel",
    "ChannelCapabilities",
    "EmailChannel",
    "FeishuChannel",
    "TelegramChannel",
    "CHANNEL_CLASSES",
]
