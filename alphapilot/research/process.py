"""Register a local execution before replacing this process with its command.

The parent launches this wrapper in a new process group. If the parent crashes
before registration, no business command runs. If it crashes afterwards, the
runtime knows the exact birth identity and group needed for cleanup.
"""
from __future__ import annotations

import argparse
import json
import os

from .common import encode
from .execution import alive, identity
from .store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise SystemExit(2)
    store = Store(args.root)
    with store.connect(write=True) as db:
        pending = db.execute("SELECT value FROM metadata WHERE key=?", ("cleanup:" + args.owner,)).fetchone()
        if pending and json.loads(pending[0]):
            raise SystemExit("Execution cleanup has started")
        row = db.execute("SELECT identity,finished,job_id FROM executions WHERE id=?", (args.owner,)).fetchone()
        if not row or row["finished"] or not row["identity"] or not alive(json.loads(row["identity"])):
            raise SystemExit("Execution owner is no longer active")
        if row["job_id"]:
            job = db.execute("SELECT status,attempt FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
            if not job or job["status"] != "running" or job["attempt"] != args.owner:
                raise SystemExit("Job execution has ended")
        db.execute("INSERT OR IGNORE INTO child_processes VALUES (?,?)", (args.owner, encode(identity())))
    os.execvpe(command[0], command, os.environ)


if __name__ == "__main__":
    main()
