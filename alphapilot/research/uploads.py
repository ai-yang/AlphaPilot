"""Bounded uploads with server-owned locations; no path based import API."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from .auth import Actor
from .common import ResearchError, encode, now, opaque
from .store import Store


class UploadService:
    def __init__(self, store: Store):
        self.store = store

    async def save(self, upload, actor: Actor) -> dict:
        actor.require("research:read", "research:write")
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in {".csv", ".json", ".pdf"}:
            raise ResearchError("UNSUPPORTED_UPLOAD", "Supported uploads: CSV, JSON, PDF", 422)
        key = uuid.uuid4().hex
        path = self.store.root / "uploads" / f"{key}{suffix}"
        path.parent.mkdir(exist_ok=True)
        size, first = 0, b""
        try:
            with path.open("wb") as stream:
                while chunk := await upload.read(1024 * 1024):
                    if not first:
                        first = chunk[:1024]
                    size += len(chunk)
                    if size > 50 * 1024 * 1024:
                        raise ResearchError("UPLOAD_TOO_LARGE", "Upload limit is 50 MiB", 413)
                    stream.write(chunk)
            if not size or (suffix == ".pdf" and b"%PDF-" not in first):
                raise ResearchError("INVALID_UPLOAD", "Upload is empty or has an invalid PDF header", 422)
            payload = {"upload_id": key, "name": Path(upload.filename).name, "size": size,
                       "media_type": {".pdf": "application/pdf", ".json": "application/json", ".csv": "text/csv"}[suffix],
                       "created_at": now()}
            with self.store.connect(write=True) as db:
                db.execute("INSERT INTO uploads VALUES (?,?,?)", (key, str(path), encode(payload)))
            return payload
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def get(self, key: str, actor: Actor, *, content=False):
        actor.require("research:read")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM uploads WHERE id=?", (opaque(key),)).fetchone()
        if not row:
            raise ResearchError("NOT_FOUND", "Upload not found", 404)
        path = Path(row["path"]).resolve()
        if self.store.root / "uploads" not in path.parents or not path.is_file():
            raise ResearchError("UPLOAD_UNAVAILABLE", "Upload content is unavailable", 404)
        return path if content else json.loads(row["payload"])

    def delete(self, key: str, actor: Actor) -> dict:
        actor.require("research:write")
        path = self.get(key, actor, content=True)
        with self.store.connect(write=True) as db:
            db.execute("DELETE FROM uploads WHERE id=?", (key,))
        path.unlink(missing_ok=True)
        return {"upload_id": key, "deleted": True}
