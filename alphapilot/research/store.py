"""Authoritative SQLite store, shared by HTTP, channels, CLI and workers."""
from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Iterator

from .common import root_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, status TEXT NOT NULL, created TEXT NOT NULL,
 client_id TEXT NOT NULL, idem_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 payload TEXT NOT NULL, execution TEXT NOT NULL, attempt TEXT,
 UNIQUE(client_id, idem_key));
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(status, created, id);
CREATE TABLE IF NOT EXISTS executions (
 id TEXT PRIMARY KEY, job_id TEXT, attempt TEXT, identity TEXT,
 containers TEXT NOT NULL DEFAULT '[]', resources TEXT NOT NULL DEFAULT '[]',
 created TEXT NOT NULL, finished INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS locks (
 resource TEXT NOT NULL, owner TEXT NOT NULL, mode TEXT NOT NULL,
 PRIMARY KEY(resource, owner));
CREATE TABLE IF NOT EXISTS lock_scopes (
 owner TEXT NOT NULL, scope TEXT NOT NULL, resources TEXT NOT NULL,
 PRIMARY KEY(owner, scope));
CREATE TABLE IF NOT EXISTS child_processes (
 execution_id TEXT NOT NULL, identity TEXT NOT NULL,
 PRIMARY KEY(execution_id, identity));
CREATE TABLE IF NOT EXISTS credentials (
 id TEXT PRIMARY KEY, client_id TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
 scopes TEXT NOT NULL, created TEXT NOT NULL, expires TEXT, revoked TEXT);
CREATE TABLE IF NOT EXISTS audit (
 id INTEGER PRIMARY KEY AUTOINCREMENT, created TEXT NOT NULL,
 actor TEXT NOT NULL, action TEXT NOT NULL, request_id TEXT NOT NULL, details TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assets (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, revision INTEGER NOT NULL,
 fingerprint TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
 UNIQUE(kind, name));
CREATE TABLE IF NOT EXISTS runs (
 id TEXT PRIMARY KEY, job_id TEXT, attempt TEXT, path TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifacts (
 id TEXT PRIMARY KEY, job_id TEXT, run_id TEXT, attempt TEXT,
 path TEXT NOT NULL, payload TEXT NOT NULL, published INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS uploads (
 id TEXT PRIMARY KEY, path TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schedules (
 id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS notifications (
 job_id TEXT PRIMARY KEY, status TEXT NOT NULL, sent INTEGER NOT NULL DEFAULT 0);
"""


class Store:
    def __init__(self, root: Path | str | None = None):
        self.root = root_path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "tasks.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version', '1')")
        self.path.chmod(0o600)

    @contextlib.contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if db.in_transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def setting(self, name: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (name,)).fetchone()
        return json.loads(row[0]) if row else default

    def require_migrated(self) -> None:
        """Never admit a new worker beside untracked workers from an old release."""
        from .common import ResearchError
        from .migration import require_legacy_scheduler_stopped
        if self.setting("migration_pending", False):
            raise ResearchError("MIGRATION_REQUIRED", "Resume the interrupted research_migrate before research writes", 409)
        require_legacy_scheduler_stopped()
        with self.connect() as db:
            known = {r[0] for r in db.execute("SELECT id FROM jobs")}
            schedules = {r[0] for r in db.execute("SELECT id FROM schedules")}
        from alphapilot.modules.portal.schedules import default_schedule_root
        old_schedules = [p for p in default_schedule_root().glob("*.json") if p.name != "scheduler.pid.json"]
        if (any(p.parent.name not in known for p in self.root.glob("*/job.json"))
                or any(json.loads(p.read_text()).get("schedule_id", p.stem) not in schedules for p in old_schedules)):
            raise ResearchError("MIGRATION_REQUIRED", "Stop old processes and run alphapilot research_migrate --execute before research writes", 409)

    def set_setting(self, name: str, value) -> None:
        with self.connect(write=True) as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES (?,?)", (name, json.dumps(value)))
