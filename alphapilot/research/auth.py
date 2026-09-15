"""Independent, scoped research credentials and authenticated actors."""
from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from .common import ResearchError, SCOPES, encode, now
from .store import Store


@dataclass(frozen=True)
class Actor:
    client_id: str
    scopes: frozenset[str]
    source: str = "http"
    credential_id: str | None = None
    request_id: str = ""

    def require(self, *scopes: str) -> None:
        missing = set(scopes) - self.scopes
        if missing:
            raise ResearchError("INSUFFICIENT_SCOPE", "Missing required research permissions", 403,
                                details={"required": sorted(missing)})

    def to_dict(self) -> dict:
        return {"client_id": self.client_id, "scopes": sorted(self.scopes), "source": self.source,
                "credential_id": self.credential_id, "request_id": self.request_id}

    @classmethod
    def local(cls, source: str = "cli") -> "Actor":
        return cls("local-owner", SCOPES, source, request_id=uuid.uuid4().hex)


class AuthService:
    def __init__(self, store: Store):
        self.store = store

    def create(self, client_id: str, scopes: list[str], expires: str | None = None) -> dict:
        if not client_id.strip() or not scopes or set(scopes) - SCOPES:
            raise ResearchError("INVALID_CREDENTIAL", "A client ID and valid scopes are required", 422)
        if expires:
            expires = datetime.fromisoformat(expires.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
            if expires <= now():
                raise ResearchError("INVALID_EXPIRY", "Expiry must be in the future", 422)
        token = "apr_" + secrets.token_urlsafe(36)
        key, created = uuid.uuid4().hex, now()
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO credentials VALUES (?,?,?,?,?,?,NULL)",
                       (key, client_id.strip(), hashlib.sha256(token.encode()).hexdigest(),
                        encode(sorted(set(scopes))), created, expires))
        return {"credential_id": key, "client_id": client_id, "scopes": sorted(set(scopes)),
                "token": token, "created_at": created, "expires_at": expires}

    def list(self) -> list[dict]:
        with self.store.connect() as db:
            rows = db.execute("SELECT id,client_id,scopes,created,expires,revoked FROM credentials ORDER BY created").fetchall()
        return [{**dict(row), "scopes": json.loads(row["scopes"])} for row in rows]

    def revoke(self, credential_id: str) -> None:
        with self.store.connect(write=True) as db:
            if not db.execute("UPDATE credentials SET revoked=? WHERE id=?", (now(), credential_id)).rowcount:
                raise ResearchError("NOT_FOUND", "Credential not found", 404)

    def authenticate(self, authorization: str | None, request_id: str = "") -> Actor:
        if not authorization or not authorization.startswith("Bearer "):
            raise ResearchError("UNAUTHENTICATED", "Research Bearer credential required", 401)
        hashed = hashlib.sha256(authorization[7:].encode()).hexdigest()
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM credentials WHERE token_hash=?", (hashed,)).fetchone()
        return self._actor(row, request_id)

    def restore(self, saved: dict) -> Actor:
        if saved.get("credential_id"):
            with self.store.connect() as db:
                row = db.execute("SELECT * FROM credentials WHERE id=?", (saved["credential_id"],)).fetchone()
            return self._actor(row, uuid.uuid4().hex)
        # Only server-side schedule/channel adapters can create these actors.
        return Actor(saved["client_id"], frozenset(saved["scopes"]) & SCOPES,
                     saved.get("source", "scheduler"), request_id=uuid.uuid4().hex)

    @staticmethod
    def _actor(row, request_id: str) -> Actor:
        if not row or row["revoked"] or (row["expires"] and row["expires"] <= now()):
            raise ResearchError("UNAUTHENTICATED", "Research credential is invalid, expired or revoked", 401)
        return Actor(row["client_id"], frozenset(json.loads(row["scopes"])), "http", row["id"],
                     request_id or uuid.uuid4().hex)

    def audit(self, actor: Actor, action: str, details: dict) -> None:
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO audit(created,actor,action,request_id,details) VALUES (?,?,?,?,?)",
                       (now(), encode(actor.to_dict()), action, actor.request_id, encode(details)))
