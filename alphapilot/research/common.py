"""Small, dependency-free persistence and wire helpers."""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import math
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "lost"})
ACTIVE = frozenset({"queued", "starting", "running", "cancelling"})
SCOPES = frozenset({"research:read", "research:write", "jobs:submit", "jobs:cancel",
                    "data:write", "signals:write", "schedules:write"})


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def root_path(root: str | Path | None = None) -> Path:
    return Path(root or os.getenv("ALPHAPILOT_PORTAL_JOB_ROOT") or
                Path.cwd() / "git_ignore_folder" / "portal_jobs").expanduser().resolve()


def opaque(value: str) -> str:
    if not value or value in {".", ".."} or any(c in value for c in "/\\\x00"):
        raise ResearchError("INVALID_ID", "Expected an opaque resource ID", 422)
    return value


def json_value(value: Any) -> Any:
    """JSON values only: never publish repr() of an internal object."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value):
        return {f.name: json_value(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_value(v) for v in value]
    if hasattr(value, "model_dump"):
        return json_value(value.model_dump(mode="json"))
    if hasattr(value, "to_dict"):
        try:
            return json_value(value.reset_index().to_dict(orient="records"))
        except (AttributeError, TypeError, ValueError):
            return json_value(value.to_dict())
    if hasattr(value, "item"):
        return json_value(value.item())
    raise TypeError(f"No public serializer for {type(value).__name__}")


def encode(value: Any) -> str:
    return json.dumps(json_value(value), ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


@contextlib.contextmanager
def atomic_text(path: Path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            yield stream
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        if os.name == "posix":
            descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()


def atomic_json(path: Path, value: Any) -> None:
    with atomic_text(path) as stream:
        stream.write(encode(value))


class ResearchError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, *,
                 retryable: bool = False, details: Any = None):
        super().__init__(message)
        self.code, self.status, self.retryable, self.details = code, status, retryable, details

    def payload(self, request_id: str | None = None) -> dict:
        return {"code": self.code, "message": str(self), "details": self.details,
                "retryable": self.retryable, "request_id": request_id or uuid.uuid4().hex}
