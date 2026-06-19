"""AlphaPilot notification system (email / Feishu / Telegram).

Phase 1 = outbound only. Public surface:

* :class:`Message`, :class:`MessageAction`, :class:`NotifyLevel` -- portable model.
* :func:`send`, :func:`test_send`, :func:`build_job_message`, :func:`configured_channel_names`.
* config helpers: :data:`CHANNEL_FIELDS`, :func:`load_file_config`, :func:`save_notify_config`,
  :func:`credentials_path`, :func:`notify_on_all_jobs`.
* :class:`NotificationSystem` -- engine-registered capability (``engine.get_system("notify")``).
"""

from alphapilot.systems.notify.config import (
    CHANNEL_FIELDS,
    credentials_path,
    load_file_config,
    load_notify_config,
    notify_on_all_jobs,
    save_notify_config,
)
from alphapilot.systems.notify.models import Message, MessageAction, NotifyLevel
from alphapilot.systems.notify.service import (
    NotificationSystem,
    build_job_message,
    configured_channel_names,
    send,
    test_send,
)

__all__ = [
    "Message",
    "MessageAction",
    "NotifyLevel",
    "send",
    "test_send",
    "build_job_message",
    "configured_channel_names",
    "NotificationSystem",
    "CHANNEL_FIELDS",
    "credentials_path",
    "load_file_config",
    "load_notify_config",
    "save_notify_config",
    "notify_on_all_jobs",
]
