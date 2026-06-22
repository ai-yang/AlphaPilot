"""Inbound notification command models and runtime helpers."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class InboundMessage:
    channel: str
    text: str
    user_id: str
    chat_id: str
    message_id: str | None = None
    user_name: str | None = None
    chat_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class InboundReply:
    text: str
    channel: str | None = None
    chat_id: str | None = None
    parse_mode: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandContext:
    message: InboundMessage
    notify_config: dict[str, Any]
    authorized: bool = False
    reason: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def command_root() -> Path:
    override = os.getenv("ALPHAPILOT_NOTIFY_COMMAND_ROOT")
    if override:
        return Path(override).expanduser()
    return Path("~/.alphapilot/portal/notify_commands").expanduser()


def pid_path(root: Path | None = None) -> Path:
    return (root or command_root()) / "notify_commands.pid.json"


def log_path(root: Path | None = None) -> Path:
    return (root or command_root()) / "notify_commands.log"


def events_path(root: Path | None = None) -> Path:
    return (root or command_root()) / "events.jsonl"


def pending_path(root: Path | None = None) -> Path:
    return (root or command_root()) / "pending.json"


def pairing_path(root: Path | None = None) -> Path:
    return (root or command_root()) / "pairing.json"


def telegram_offset_path(root: Path | None = None) -> Path:
    return (root or command_root()) / "telegram_offset.json"


def chats_root(root: Path | None = None) -> Path:
    return (root or command_root()) / "chats"


def _safe_id(value: str) -> str:
    """Filesystem-safe slug for a channel/chat id (keeps digits, '-' and '_')."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(value)).strip("_")
    return safe or "unknown"


def chat_dir(channel: str, chat_id: str, *, root: Path | None = None) -> Path:
    return chats_root(root) / f"{_safe_id(channel)}__{_safe_id(chat_id)}"


def transcript_path(channel: str, chat_id: str, *, root: Path | None = None) -> Path:
    return chat_dir(channel, chat_id, root=root) / "transcript.jsonl"


def _jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)

def append_event(event: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    root = root or command_root()
    root.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": utc_now(), **_jsonable(event)}
    with events_path(root).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return payload


def recent_events(*, root: Path | None = None, limit: int = 100) -> list[dict[str, Any]]:
    path = events_path(root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


# --------------------------------------------------------------------------- #
# Per-chat conversation transcripts (one file per channel+chat)
# --------------------------------------------------------------------------- #
_MAX_TRANSCRIPT_LINES = 1000


def _trim_transcript(path: Path, *, max_lines: int = _MAX_TRANSCRIPT_LINES) -> None:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    if len(lines) <= max_lines:
        return
    path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


def append_turn(
    channel: str, chat_id: str, record: dict[str, Any], *, root: Path | None = None
) -> dict[str, Any]:
    """Append one conversation turn to that chat's transcript.jsonl (capped)."""
    path = transcript_path(channel, chat_id, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"created_at": utc_now(), **_jsonable(record)}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    _trim_transcript(path)
    return payload


def recent_turns(
    channel: str, chat_id: str, *, limit: int = 6, root: Path | None = None
) -> list[dict[str, Any]]:
    """Most recent turns for a chat, oldest first (for multi-turn planner context)."""
    path = transcript_path(channel, chat_id, root=root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


# --------------------------------------------------------------------------- #
# Telegram poll offset (persisted so a restart never replays queued commands)
# --------------------------------------------------------------------------- #
def load_telegram_offset(*, root: Path | None = None) -> int | None:
    path = telegram_offset_path(root)
    if not path.exists():
        return None
    try:
        return int(json.loads(path.read_text(encoding="utf-8")).get("offset"))
    except Exception:
        return None


def save_telegram_offset(offset: int, *, root: Path | None = None) -> None:
    path = telegram_offset_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"offset": int(offset), "updated_at": utc_now()}), encoding="utf-8"
    )


# --------------------------------------------------------------------------- #
# Pairing codes: portal mints a single-use, short-TTL code; /start <code> redeems
# --------------------------------------------------------------------------- #
PAIR_CODE_TTL_MINUTES = 10
_PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous 0/O/1/I


def _load_pairing(root: Path | None = None) -> dict[str, Any]:
    path = pairing_path(root)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _save_pairing(payload: dict[str, Any], root: Path | None = None) -> None:
    path = pairing_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _purge_expired_codes(payload: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    out: dict[str, Any] = {}
    for code, item in payload.items():
        try:
            if datetime.fromisoformat(str(item.get("expires_at"))) >= now:
                out[code] = item
        except Exception:
            continue
    return out


def create_pair_code(
    channel: str = "telegram", *, ttl_minutes: int = PAIR_CODE_TTL_MINUTES, root: Path | None = None
) -> dict[str, Any]:
    """Mint a single-use pairing code for *channel* and persist it."""
    payload = _purge_expired_codes(_load_pairing(root))
    code = "".join(secrets.choice(_PAIR_ALPHABET) for _ in range(6))
    now = datetime.now(timezone.utc)
    item = {
        "code": code,
        "channel": channel,
        "created_at": now.isoformat(timespec="seconds"),
        "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds"),
    }
    payload[code] = item
    _save_pairing(payload, root)
    return item


def redeem_pair_code(code: str, channel: str, *, root: Path | None = None) -> dict[str, Any]:
    """Validate + consume a pairing code. Raises ValueError on any problem."""
    code = str(code).strip().upper()
    payload = _load_pairing(root)
    item = payload.get(code)
    if not isinstance(item, dict):
        raise ValueError("配对码无效 / invalid pairing code")
    if str(item.get("channel")) != str(channel):
        raise ValueError("配对码渠道不匹配 / pairing code channel mismatch")
    try:
        expired = datetime.fromisoformat(str(item.get("expires_at"))) < datetime.now(timezone.utc)
    except Exception:
        expired = True
    payload.pop(code, None)  # single-use: consume whether valid or expired
    _save_pairing(payload, root)
    if expired:
        raise ValueError("配对码已过期 / pairing code expired")
    return item


def _pid_exists(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def daemon_status(*, root: Path | None = None) -> dict[str, Any]:
    root = root or command_root()
    path = pid_path(root)
    payload: dict[str, Any] = {
        "running": False,
        "pid": None,
        "channel": None,
        "root": str(root),
        "pid_path": str(path),
        "log_path": str(log_path(root)),
    }
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            payload.update(saved)
            payload["running"] = _pid_exists(int(saved.get("pid") or 0))
        except Exception:
            payload["running"] = False
    return payload


def start_daemon(channel: str = "telegram", *, root: Path | None = None) -> dict[str, Any]:
    root = root or command_root()
    root.mkdir(parents=True, exist_ok=True)
    status = daemon_status(root=root)
    if status.get("running"):
        return status

    from alphapilot.modules.portal.env_config import apply_portal_env

    env = os.environ.copy()
    apply_portal_env(env)
    env["ALPHAPILOT_NOTIFY_COMMAND_ROOT"] = str(root)
    log = log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(f"\n[notify-commands] launching at {utc_now()} channel={channel}\n")
        process = subprocess.Popen(
            [sys.executable, "-m", "alphapilot.systems.notify.inbound", "--channel", channel],
            stdout=stream,
            stderr=stream,
            env=env,
            start_new_session=True,
        )
    payload = {
        "pid": process.pid,
        "channel": channel,
        "started_at": utc_now(),
        "root": str(root),
        "log_path": str(log),
    }
    pid_path(root).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return daemon_status(root=root)


def stop_daemon(*, root: Path | None = None) -> dict[str, Any]:
    root = root or command_root()
    status = daemon_status(root=root)
    pid = status.get("pid")
    try:
        pid_int = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        pid_int = None
    if pid_int and status.get("running"):
        os.kill(pid_int, signal.SIGTERM)
        time.sleep(0.2)
    path = pid_path(root)
    if path.exists():
        path.unlink()
    status["running"] = False
    return status


def run_daemon(channel: str = "telegram", poll_interval: float | None = None) -> None:
    from alphapilot.systems.notify.receivers import run_feishu_placeholder, run_telegram_polling

    root = command_root()
    root.mkdir(parents=True, exist_ok=True)
    print(f"[notify-commands] started pid={os.getpid()} channel={channel} root={root}", flush=True)
    if channel in {"telegram", "all"}:
        run_telegram_polling(poll_interval=poll_interval)
    elif channel == "feishu":
        run_feishu_placeholder()
    else:
        raise ValueError(f"Unsupported notify command channel: {channel}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AlphaPilot notify command receiver.")
    parser.add_argument("--channel", default="telegram", choices=["telegram", "feishu", "all"])
    parser.add_argument("--poll-interval", type=float, default=None)
    args = parser.parse_args()
    run_daemon(channel=args.channel, poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()
