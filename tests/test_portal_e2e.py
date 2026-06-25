"""Tier 5: portal API end-to-end against the *real* engine (no fakes).

``test_portal_api.py`` wires fake systems to assert request/response plumbing.
Here we let ``create_app`` lazily build the real ``build_engine()`` on an
isolated environment and drive real systems/modules through HTTP — status,
module discovery + invocation, schedule persistence, the background job
lifecycle, and job-completion notifications.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from alphapilot.modules.portal.api import create_app

TERMINAL = {"succeeded", "failed", "cancelled", "lost"}


@pytest.fixture()
def client(isolated_env) -> TestClient:
    return TestClient(create_app())


def test_status_reports_real_systems(client: TestClient) -> None:
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    systems = set(body.get("systems") or {}) if isinstance(body.get("systems"), dict) else set(body.get("systems") or [])
    # Be tolerant of list-vs-dict shape; just assert the core systems surface.
    text = str(body)
    for name in ("data", "factor", "strategy", "backtest", "notify"):
        assert name in text


def test_modules_list_and_run_factor_list(client: TestClient) -> None:
    resp = client.get("/api/modules")
    assert resp.status_code == 200
    modules = resp.json()
    assert {"alpha_mining", "portal", "factor"} <= set(modules)

    # Seed a factor, then list it back through a real module command.
    client.post("/api/factors", json={"factor_name": "e2e_f", "factor_expression": "Mean($close,5)/$close-1"})
    resp = client.post("/api/modules/run", json={"module": "factor", "command": "factor_list", "kwargs": {}})
    assert resp.status_code == 200
    assert "e2e_f" in str(resp.json())


def test_factor_duplicates_and_bulk_delete(client: TestClient) -> None:
    # Two commutatively-equivalent factors (string-distinct, so add_factor lets
    # both through) must be reported as one duplicate group.
    client.post("/api/factors", json={"factor_name": "dup_keep", "factor_expression": "Mean($high,5)+Mean($low,5)"})
    client.post("/api/factors", json={"factor_name": "dup_drop", "factor_expression": "Mean($low,5)+Mean($high,5)"})

    dupes = client.get("/api/factors/duplicates").json()
    assert dupes["n_duplicate_groups"] == 1
    members = {m["factor_name"] for m in dupes["groups"][0]["members"]}
    assert members == {"dup_keep", "dup_drop"}

    keep = dupes["groups"][0]["suggested_keep"]
    to_delete = dupes["groups"][0]["suggested_delete"]
    deleted = client.post("/api/factors/bulk-delete", json={"factor_names": to_delete}).json()
    assert deleted["deleted"] == to_delete

    remaining = {f["factor_name"] for f in client.get("/api/factors").json()["factors"]}
    assert set(to_delete).isdisjoint(remaining)
    assert keep in remaining


def test_schedule_crud(client: TestClient) -> None:
    created = client.post(
        "/api/schedules",
        json={"name": "nightly_h5", "kind": "data", "time": "09:00",
              "kwargs": {"action": "build_h5"}, "enabled": True},
    )
    assert created.status_code == 200
    sid = created.json()["schedule_id"]

    listing = client.get("/api/schedules").json()
    assert any(s["schedule_id"] == sid for s in listing)

    daemon = client.get("/api/schedules/daemon")
    assert daemon.status_code == 200
    assert daemon.json().get("running") in (False, True)

    patched = client.patch(f"/api/schedules/{sid}", json={"enabled": False})
    assert patched.status_code == 200

    deleted = client.delete(f"/api/schedules/{sid}")
    assert deleted.status_code == 200
    assert all(s["schedule_id"] != sid for s in client.get("/api/schedules").json())


def test_job_completion_notification(captured_notify) -> None:
    # The job worker composes a Message and fans it out on completion; assert the
    # composition + send wiring without spawning a worker or sending externally.
    from alphapilot.systems.notify.service import build_job_message, send

    message = build_job_message(
        kind="factor_backtest", job_id="job-123", status="succeeded",
        result={"IC": 0.03}, kwargs={"mode": "single_ic"},
    )
    send(message)
    assert len(captured_notify) == 1
    assert "factor" in captured_notify[0].title.lower() or "因子" in captured_notify[0].title


@pytest.mark.slow
def test_job_lifecycle(client: TestClient, tmp_path) -> None:
    # A real background worker: factor_backtest with no market data terminates
    # quickly (failure is fine) — we assert the lifecycle, not the outcome.
    factor_csv = tmp_path / "f.csv"
    factor_csv.write_text('factor_name,factor_expression\nf,"Mean($close,5)/$close-1"\n')

    started = client.post(
        "/api/jobs",
        json={"kind": "factor_backtest", "kwargs": {"factor_path": str(factor_csv), "mode": "single_ic"}},
    )
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    assert started.json()["status"] == "running"

    # Poll to a terminal state; cancel if it lingers so the test stays bounded.
    deadline = time.time() + 120
    status = "running"
    cancelled = False
    while time.time() < deadline:
        prog = client.get(f"/api/jobs/{job_id}/progress")
        assert prog.status_code == 200
        status = prog.json().get("status", "running")
        if status in TERMINAL:
            break
        if not cancelled and time.time() > deadline - 90:
            client.post(f"/api/jobs/{job_id}/cancel")
            cancelled = True
        time.sleep(2)

    assert status in TERMINAL, f"job never reached a terminal state (last={status})"

    # Result + log endpoints must respond for a finished job.
    assert client.get(f"/api/jobs/{job_id}/result").status_code == 200
    assert client.get(f"/api/jobs/{job_id}/log").status_code == 200

    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert all(j["job_id"] != job_id for j in client.get("/api/jobs").json())
