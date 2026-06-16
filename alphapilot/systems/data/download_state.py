"""CSV-backed download state tracking for market data refreshes."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

STATE_COLUMNS = [
    "source",
    "adjust_mode",
    "code",
    "raw_dir",
    "data_end_date",
    "checked_until",
    "last_success_at",
    "last_status",
    "last_error",
]


@dataclass(frozen=True)
class DownloadStateRecord:
    source: str
    adjust_mode: str
    code: str
    raw_dir: str
    data_end_date: str | None = None
    checked_until: str | None = None
    last_success_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None


def default_download_state_path(raw_dir: str | Path) -> Path:
    """Resolve the shared state table beside the raw-data mode directories."""
    return Path(raw_dir).expanduser().parent / "download_state.csv"


def resolve_download_state_path(
    download_state_path: str | Path | None,
    raw_dir: str | Path,
) -> Path:
    if download_state_path is not None:
        return Path(download_state_path).expanduser()
    return default_download_state_path(raw_dir)


def normalize_date_str(value: object) -> str | None:
    """Normalize a date-like value to ``YYYY-MM-DD`` or ``None``."""
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


class DownloadStateStore:
    """Small thread-safe CSV state store keyed by source/mode/code/raw_dir."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()
        self._df = self._load()

    def _load(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=STATE_COLUMNS)

        df = pd.read_csv(self.path, dtype=str).fillna("")
        for column in STATE_COLUMNS:
            if column not in df.columns:
                df[column] = ""
        return df[STATE_COLUMNS].copy()

    @staticmethod
    def _raw_dir_key(raw_dir: str | Path) -> str:
        return str(Path(raw_dir).expanduser())

    def get(
        self,
        *,
        source: str,
        adjust_mode: str,
        code: str,
        raw_dir: str | Path,
    ) -> DownloadStateRecord | None:
        raw_dir_key = self._raw_dir_key(raw_dir)
        with self._lock:
            mask = (
                (self._df["source"] == source)
                & (self._df["adjust_mode"] == adjust_mode)
                & (self._df["code"] == code)
                & (self._df["raw_dir"] == raw_dir_key)
            )
            if not mask.any():
                return None
            row = self._df.loc[mask].iloc[-1]

        return DownloadStateRecord(
            source=source,
            adjust_mode=adjust_mode,
            code=code,
            raw_dir=raw_dir_key,
            data_end_date=normalize_date_str(row.get("data_end_date")),
            checked_until=normalize_date_str(row.get("checked_until")),
            last_success_at=row.get("last_success_at") or None,
            last_status=row.get("last_status") or None,
            last_error=row.get("last_error") or None,
        )

    def upsert(
        self,
        *,
        source: str,
        adjust_mode: str,
        code: str,
        raw_dir: str | Path,
        data_end_date: str | None = None,
        checked_until: str | None = None,
        last_status: str | None = None,
        last_error: str | None = None,
        mark_success: bool = False,
    ) -> DownloadStateRecord:
        raw_dir_key = self._raw_dir_key(raw_dir)
        updates = {
            "source": source,
            "adjust_mode": adjust_mode,
            "code": code,
            "raw_dir": raw_dir_key,
            "data_end_date": normalize_date_str(data_end_date),
            "checked_until": normalize_date_str(checked_until),
            "last_status": last_status or "",
            "last_error": last_error or "",
        }
        if mark_success:
            updates["last_success_at"] = datetime.now().isoformat(timespec="seconds")

        with self._lock:
            mask = (
                (self._df["source"] == source)
                & (self._df["adjust_mode"] == adjust_mode)
                & (self._df["code"] == code)
                & (self._df["raw_dir"] == raw_dir_key)
            )
            if mask.any():
                index = self._df.index[mask][-1]
                for column, value in updates.items():
                    if value is not None:
                        self._df.at[index, column] = value
                if mark_success:
                    self._df.at[index, "last_success_at"] = updates["last_success_at"]
            else:
                row = {column: "" for column in STATE_COLUMNS}
                for column, value in updates.items():
                    row[column] = value or ""
                if mark_success:
                    row["last_success_at"] = updates["last_success_at"]
                self._df = pd.concat([self._df, pd.DataFrame([row])], ignore_index=True)

        record = self.get(source=source, adjust_mode=adjust_mode, code=code, raw_dir=raw_dir_key)
        if record is None:
            raise RuntimeError("failed to upsert download state")
        return record

    def save(self) -> None:
        with self._lock:
            df = self._df.copy()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.path, index=False, encoding="utf-8")
