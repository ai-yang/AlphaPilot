"""Portal live-trading endpoints: the in-process PAPER sandbox flow."""

from __future__ import annotations

from fastapi.testclient import TestClient

from alphapilot.modules.portal.api import create_app


def _client(engine):
    return TestClient(create_app(engine=engine))


def test_live_status_before_connect(engine) -> None:
    client = _client(engine)
    data = client.get("/api/live/status").json()
    assert data["config"]["broker"] == "paper"
    assert data["config"]["mode"] in set(data["modes"])
    assert data["running"] is False
    assert "state" not in data


def test_live_paper_full_flow(engine) -> None:
    client = _client(engine)

    # connect a paper account
    st = client.post("/api/live/paper/connect", json={"cash": 100000}).json()
    assert st["account"]["buying_power"] == 100000
    assert st["snapshot"]["mode"] == "paper"

    # manual buy fills immediately in the paper broker
    st = client.post(
        "/api/live/paper/order",
        json={"code": "SH600000", "side": "buy", "volume": 1000, "price": 10.0},
    ).json()
    positions = {p["code"]: p for p in st["positions"]}
    assert positions["600000"]["volume"] == 1000
    assert positions["600000"]["available"] == 0          # bought today -> T+1
    assert st["account"]["buying_power"] < 100000          # cash spent (+ fee)

    # submit a target -> reconcile against real positions -> buy the delta up to 2000
    st = client.post(
        "/api/live/paper/submit-target",
        json={"holdings": {"SH600000": 2000}, "prices": {"SH600000": 10.0}},
    ).json()
    assert st["planned"] >= 1
    positions = {p["code"]: p for p in st["positions"]}
    assert positions["600000"]["volume"] == 2000

    # kill-switch: halts and blocks further routing
    st = client.post("/api/live/paper/halt", json={}).json()
    assert st["snapshot"]["halted"] is True
    st = client.post(
        "/api/live/paper/order",
        json={"code": "SZ000001", "side": "buy", "volume": 100, "price": 5.0},
    ).json()
    assert all(p["code"] != "000001" for p in st["positions"])   # not routed while halted

    # resume, then reset the sandbox
    assert client.post("/api/live/paper/resume", json={}).json()["snapshot"]["halted"] is False
    assert client.post("/api/live/paper/reset", json={}).json()["running"] is False
    assert client.get("/api/live/status").json()["running"] is False


def test_live_paper_requires_connect(engine) -> None:
    client = _client(engine)
    # order without a session -> 400 from _api_error
    resp = client.post("/api/live/paper/order", json={"code": "SH600000", "side": "buy", "volume": 100})
    assert resp.status_code >= 400
