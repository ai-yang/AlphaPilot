"""Append-only audit ledger for the live-trading subsystem.

Every intent, submission, cancel, fill, halt and reconciliation is appended as
one JSON line. This is the durable audit trail — distinct from the OMS's
in-memory projection and from any paper/rolling state — so that after the fact you
can reconstruct exactly what the system decided and did, and when.

Append-only + line-oriented is deliberate: it is crash-safe (a torn last line is
recoverable), human-greppable, and never mutates history.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class Ledger:
    """A per-day JSONL audit log under ``root``."""

    def __init__(self, root: str | Path, *, now_fn=datetime.now) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._now_fn = now_fn

    def _path_for(self, when: datetime) -> Path:
        return self.root / f"ledger-{when:%Y%m%d}.jsonl"

    def record(self, kind: str, payload: Any = None) -> dict[str, Any]:
        """Append one event. ``payload`` may be a dict or a dataclass."""
        when = self._now_fn()
        if is_dataclass(payload) and not isinstance(payload, type):
            payload = asdict(payload)
        event = {"ts": when.isoformat(timespec="seconds"), "kind": kind, "payload": payload}
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._path_for(when).open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        return event

    def events(self) -> list[dict[str, Any]]:
        """Read every recorded event across all days (chronological by filename)."""
        out: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("ledger-*.jsonl")):
            for raw in path.read_text(encoding="utf-8").splitlines():
                raw = raw.strip()
                if raw:
                    try:
                        out.append(json.loads(raw))
                    except json.JSONDecodeError:  # tolerate a torn final line
                        continue
        return out
