"""Run one real MCP mining round (3 steps + checkpoint resume for 2 steps).

Uses configured data/model credentials and saves research assets in this workspace.
Requires an idle runtime and no schedules. Never sends channel notifications.
The sibling alphapilot-mcp repository must already be built with npm run build.
"""
from __future__ import annotations

import json
import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("mining", "unary-backtest"), default="mining")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    os.chdir(repo)
    from dotenv import load_dotenv
    load_dotenv(repo / ".env", override=False)
    from alphapilot.modules.portal.env_config import apply_portal_env
    apply_portal_env()
    os.environ["ALPHAPILOT_RESEARCH_AUTOSTART"] = "0"
    os.environ["ALPHAPILOT_NOTIFY_ON_ALL_JOBS"] = "false"
    for channel in ("TELEGRAM", "FEISHU", "EMAIL"):
        os.environ[f"ALPHAPILOT_NOTIFY_{channel}_ENABLED"] = "false"
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    from alphapilot.research.store import Store
    from alphapilot.research.auth import AuthService
    from alphapilot.research.runtime import status
    from alphapilot.modules.portal.api import create_app
    import uvicorn

    mcp = Path(os.environ.get("MCP_REPOSITORY", repo.parent / "alphapilot-mcp")).resolve()
    if not (mcp / "dist/cli.js").is_file():
        raise SystemExit("Build the sibling alphapilot-mcp repository first")
    store = Store()
    store.require_migrated()
    with store.connect() as db:
        active = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','starting','running','cancelling')").fetchone()[0]
        scheduled = db.execute("SELECT count(*) FROM schedules").fetchone()[0]
    if active or scheduled or status(store)["running"]:
        raise SystemExit("Requires an idle workspace with no schedules; existing work was not changed")

    key = f"mcp-{args.scenario}-" + time.strftime("%Y%m%d-%H%M%S")
    folder = repo / "git_ignore_folder/qa/mcp" / key
    folder.mkdir(parents=True)
    auth = AuthService(store)
    scopes = ["research:read", "research:write", "jobs:submit", "jobs:cancel"]
    credentials = []
    runtime = server = thread = None
    sock = socket.socket()
    try:
        credentials.append(auth.create(key + "-stdio", scopes))
        credentials.append(auth.create(key + "-http", scopes))
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(), log_level="warning", access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("Temporary Portal did not start")
            time.sleep(.1)
        with (folder / "runtime.log").open("ab") as log:
            runtime = subprocess.Popen(
                [sys.executable, "-m", "alphapilot.research.runtime", "--root", str(store.root)],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                env=os.environ.copy(), cwd=repo, start_new_session=True,
            )
        deadline = time.monotonic() + 30
        while not status(store)["running"]:
            if runtime.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Temporary TaskRuntime did not start")
            time.sleep(.2)
        env = {
            **os.environ,
            "ALPHAPILOT_BASE_URL": f"http://127.0.0.1:{port}",
            "ALPHAPILOT_RESEARCH_TOKEN": credentials[0]["token"],
            "MCP_SMOKE_OBSERVER_TOKEN": credentials[1]["token"],
            "MCP_SMOKE_ID": os.environ.get("MCP_SMOKE_ID", key),
            "MCP_SMOKE_REPORT": str(folder / "report.json"),
        }
        print(json.dumps({"event": "started", "report": str(folder / "report.json")}), flush=True)
        script = "real-smoke.mjs" if args.scenario == "mining" else "real-unary-smoke.mjs"
        result = subprocess.run(["node", str(mcp / "scripts" / script)], env=env)
        print(json.dumps({"returncode": result.returncode, "report": str(folder / "report.json")}), flush=True)
        return result.returncode
    finally:
        with store.connect() as db:
            active = db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','starting','running','cancelling')").fetchone()[0]
        if runtime is not None and not active:
            runtime.terminate()
            try:
                runtime.wait(timeout=20)
            except subprocess.TimeoutExpired:
                print("Runtime shutdown not yet confirmed; inspect locally", file=sys.stderr)
        elif runtime is not None:
            print("Active tasks retained; runtime remains running. Inspect/cancel explicitly.", file=sys.stderr)
        for credential in credentials:
            auth.revoke(credential["credential_id"])
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=10)
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
