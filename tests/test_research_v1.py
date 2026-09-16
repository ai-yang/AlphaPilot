"""Offline public-contract and durable runtime integration tests."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from alphapilot.research.auth import Actor, AuthService
from alphapilot.research.common import SCOPES, ResearchError, encode, now
from alphapilot.research.store import Store
from alphapilot.research.tasks import TaskService


@pytest.fixture(autouse=True)
def installed_live_test_plugins():
    """Research contracts deliberately run without optional broker wheels."""
    yield


@pytest.fixture
def research(tmp_path, monkeypatch, isolated_env):
    monkeypatch.setenv("ALPHAPILOT_PORTAL_JOB_ROOT", str(tmp_path / "jobs"))
    monkeypatch.setenv("ALPHAPILOT_RESEARCH_AUTOSTART", "0")
    from alphapilot.modules.portal.api import create_app
    store = Store()
    auth = AuthService(store)
    credential = auth.create("integration-test", sorted(SCOPES))
    client = TestClient(create_app())
    client.headers["Authorization"] = "Bearer " + credential["token"]
    return client, store, auth


def test_research_auth_and_retired_routes(research):
    client, store, auth = research
    assert client.get("/api/jobs").status_code == 410
    assert client.get("/api/data/symbols").status_code == 410
    assert client.post("/api/modules/run", json={"module": "factor", "command": "factor_list"}).status_code == 410
    assert client.get("/api/v1/capabilities").status_code == 200
    client.headers.pop("Authorization")
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    token = auth.create("reader", ["research:read"])
    client.headers["Authorization"] = "Bearer " + token["token"]
    assert client.post("/api/v1/factors", json={"name": "x", "expression": "TS_MEAN($close, 10)/($close+1e-8)-1"}).status_code == 403
    auth.revoke(token["credential_id"])
    assert client.get("/api/v1/capabilities").status_code == 401


def test_openapi_is_standalone_and_strict(research):
    client, *_ = research
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 200, response.text
    schema = response.json()
    assert all(p.startswith("/api/v1/") for p in schema["paths"])
    assert "202" in schema["paths"]["/api/v1/jobs"]["post"]["responses"]
    spec = schema["components"]["schemas"]["MiningInput"]
    assert spec["additionalProperties"] is False
    assert "max_steps" in spec["required"]
    assert "path" not in spec["properties"]
    body = {"kind": "mine", "input": {"dataset_id": "x", "max_steps": 5, "path": "/tmp/escape"}}
    response = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "bad"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_catalog_and_factor_versions(research):
    client, *_ = research
    for path in ("datasets", "templates", "models", "factor-dsl"):
        response = client.get("/api/v1/" + path)
        assert response.status_code == 200, response.text
    created = client.post("/api/v1/factors", json={"name": "research_close", "expression": "TS_MEAN($close, 10)/($close+1e-8)-1"})
    assert created.status_code == 201, created.text
    row = created.json()
    response = client.patch("/api/v1/factors/" + row["id"], json={"name": "research_close_renamed"}, headers={"If-Match": str(row["revision"])})
    assert response.status_code == 200, response.text
    assert response.json()["id"] == row["id"]
    assert client.delete("/api/v1/factors/" + row["id"], headers={"If-Match": str(row["revision"])}).status_code == 412


def test_durable_admission_idempotency_cancel_and_restart(research, monkeypatch):
    client, store, _ = research
    # Admission uses real typed input/persistence while the domain snapshot is a
    # controlled fixture; no downloads, LLM calls or worker processes are launched.
    from alphapilot.research import executor
    def prepare(engine, store, spec, folder, actor):
        return {"kind": spec.kind, "input": spec.input.model_dump(mode="json"), "resources": [], "folder": str(folder)}, spec.input.model_dump(mode="json")
    monkeypatch.setattr(executor, "prepare", prepare)
    body = {"kind": "mine", "input": {"dataset_id": "fixture", "max_steps": 5}}
    first = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "once"})
    assert first.status_code == 202, first.text
    job = first.json()
    assert job["status"] == "queued"
    repeated = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "once"})
    assert repeated.json()["job_id"] == job["job_id"]
    body["input"]["max_steps"] = 6
    assert client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "once"}).status_code == 409
    assert TaskService(Store(store.root), autostart=False).get(job["job_id"], Actor.local())["status"] == "queued"
    assert client.get(f"/api/v1/jobs/{job['job_id']}/result").json()["availability"] == "pending"
    response = client.post(f"/api/v1/jobs/{job['job_id']}/cancel")
    assert response.json()["status"] == "cancelled"
    assert client.get(f"/api/v1/jobs/{job['job_id']}/result").json()["availability"] == "unavailable"


def prepare_dataset(client):
    from alphapilot.research.catalog import Catalog
    from alphapilot.research.common import atomic_json
    client.get("/api/v1/datasets")
    catalog = Catalog(client.app.state.engine)
    row = catalog.dataset("baostock_cn:day:backward")
    root = Path(row["qlib_dir"])
    (root / "features").mkdir(parents=True, exist_ok=True)
    (root / "calendars").mkdir(exist_ok=True)
    (root / "instruments").mkdir(exist_ok=True)
    (root / "calendars/day.txt").write_text("2026-01-05\n2026-01-06\n")
    (root / "instruments/all.txt").write_text("SH600000\t2026-01-05\t2026-01-06\n")
    atomic_json(root / ".research-revision.json", {"source": row["source"], "adjust_mode": row["adjust_mode"]})
    return catalog.dataset(row["dataset_id"])


@pytest.mark.parametrize("mode", ["single_ic", "multi_combined", "multi_sequential"])
def test_inline_backtest_freezes_parameters_and_does_not_add_to_library(research, mode):
    client, store, _ = research
    dataset = prepare_dataset(client)
    before = client.get("/api/v1/factors").json()["items"]
    body = {"kind": "factor_backtest", "input": {"dataset_id": dataset["dataset_id"], "mode": mode,
            "factor_source": {"type": "inline", "factors": [{"name": "price", "expression": " $close "}]},
            "parameters": {"topk": 7}}}
    response = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "inline-" + mode})
    assert response.status_code == 202, response.text
    job = response.json()
    assert job["normalized_input"]["parameters"]["topk"] == 7
    assert job["normalized_input"]["factors_snapshot"][0]["expression"] == "$close"
    assert client.get("/api/v1/factors").json()["items"] == before
    assert (store.root / job["job_id"] / "inputs/factors.csv").is_file()


def test_library_backtest_does_not_apply_novelty_admission_gate(research):
    client, store, _ = research
    dataset = prepare_dataset(client)
    row = client.post("/api/v1/factors", json={"name": "existing", "expression": "TS_MEAN($close, 10)/($close+1e-8)-1"}).json()
    payload = {"kind": "factor_backtest", "input": {"dataset_id": dataset["dataset_id"], "factor_source": {"type": "library", "factor_ids": [row["id"]]}}}
    response = client.post("/api/v1/jobs", json=payload, headers={"Idempotency-Key": "library"})
    assert response.status_code == 202, response.text
    frozen = response.json()["normalized_input"]["factors_snapshot"]
    client.patch("/api/v1/factors/" + row["id"], json={"name": "changed"}, headers={"If-Match": str(row["revision"])})
    assert client.get("/api/v1/jobs/" + response.json()["job_id"]).json()["normalized_input"]["factors_snapshot"] == frozen


def test_validation_and_asset_category_preconditions(research):
    client, *_ = research
    response = client.post("/api/v1/factors/validate", json={"expressions": [" $close ", "TS_MEAN($close, -1)", "__import__('os')"]})
    assert response.status_code == 200, response.text
    rows = response.json()["results"]
    assert rows[0]["valid"] and rows[0]["normalized_expression"] == "$close"
    assert not rows[1]["valid"] and not rows[2]["valid"]
    row = client.post("/api/v1/factors/categories", json={"name": "a"}).json()
    assert client.patch("/api/v1/factors/categories/" + row["id"], json={"name": "b"}).status_code == 428
    updated = client.patch("/api/v1/factors/categories/" + row["id"], json={"name": "b"}, headers={"If-Match": str(row["revision"])})
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] == row["id"]
    assert client.delete("/api/v1/factors/categories/" + row["id"], headers={"If-Match": str(row["revision"])}).status_code == 412


def test_upload_import_export_download_is_http_only(research):
    import hashlib
    client, *_ = research
    upload = client.post("/api/v1/uploads", files={"file": ("factors.csv", b'name,expression\nmomentum,"TS_MEAN($close,10)/($close+1e-8)-1"\n', "text/csv")})
    assert upload.status_code == 201, upload.text
    result = client.post("/api/v1/factors/import", json={"upload_id": upload.json()["upload_id"]})
    assert result.status_code == 200, result.text
    assert result.json()["imported"] == 1
    artifact = client.post("/api/v1/factors/export", json={"ids": [result.json()["items"][0]["id"]]}).json()
    content = client.get(artifact["content_url"])
    assert content.status_code == 200
    assert hashlib.sha256(content.content).hexdigest() == artifact["sha256"]
    assert content.json()["items"][0]["name"] == "momentum"
    assert client.post("/api/v1/uploads", files={"file": ("model.pkl", b"pickle", "application/octet-stream")}).status_code == 422


def test_data_aliases_do_not_claim_different_adjustment_modes(research):
    from alphapilot.research.catalog import Catalog
    from alphapilot.research.common import atomic_json
    client, *_ = research
    dataset = prepare_dataset(client)
    catalog = Catalog(client.app.state.engine)
    assert catalog.dataset(dataset["dataset_id"])["ready"]
    assert not catalog.dataset("baostock_cn:day:forward")["ready"]
    atomic_json(Path(dataset["qlib_dir"]) / ".research-dirty.json", {"interrupted": True})
    assert not catalog.dataset(dataset["dataset_id"])["ready"]


def test_all_research_aliases_are_retired_before_spa(research):
    client, *_ = research
    for path in ("/api/factors/anything", "/api/backtests/x", "/api/mining/sessions", "/api/status", "/api/schedules/daemon", "/api/notify/commands/dispatch", "/api/trade-sessions"):
        response = client.get(path)
        assert response.status_code == 410 and response.json()["code"] == "API_REMOVED"
    for command in ("research_token", "research_migrate", "task_runtime", "scheduler", "prepare_data"):
        assert client.post("/api/modules/run", json={"module": "portal", "command": command, "kwargs": {}}).status_code == 410
    assert client.get("/api/v1/unknown").json()["code"] == "NOT_FOUND"


def test_http_command_cannot_spoof_identity_or_access_files(research):
    client, *_ = research
    assert client.post("/api/v1/commands/dispatch", headers={"Idempotency-Key": "spoof"}, json={"text": "/jobs", "enforce_auth": False}).status_code == 422
    response = client.post("/api/v1/commands/dispatch", headers={"Idempotency-Key": "files"}, json={"text": "/ls"})
    assert response.status_code in {200, 422}
    assert not response.json().get("ok", False)


def test_execution_rechecks_dataset_mode_and_dirty_state(research):
    from alphapilot.research.executor import bind_dataset
    from alphapilot.research.common import atomic_json
    client, store, _ = research
    dataset = prepare_dataset(client)
    folder = store.root / "execution"
    (folder / "inputs").mkdir(parents=True)
    execution = {"dataset": dataset, "folder": str(folder)}
    atomic_json(Path(dataset["qlib_dir"]) / ".research-revision.json", {"source": dataset["source"], "adjust_mode": "forward"})
    with pytest.raises(ResearchError, match="execution time"):
        bind_dataset(execution)
    atomic_json(Path(dataset["qlib_dir"]) / ".research-revision.json", {"source": dataset["source"], "adjust_mode": "backward"})
    atomic_json(Path(dataset["qlib_dir"]) / ".research-dirty.json", {"action": "failed-write"})
    with pytest.raises(ResearchError, match="execution time"):
        bind_dataset(execution)


def test_template_then_explicit_parameter_precedence(research, tmp_path, monkeypatch):
    from alphapilot.research.catalog import Catalog
    from alphapilot.research.common import atomic_json
    import shutil
    client, _, _ = research
    dataset = prepare_dataset(client)
    original = Catalog(client.app.state.engine).template("combined")
    template = tmp_path / "custom-template"
    shutil.copytree(original["directory"], template)
    config = template / original["config_name"]
    config.write_text(config.read_text().replace("topk: 20", "topk: 13"))
    catalog_file = tmp_path / "catalog.json"
    atomic_json(catalog_file, {"templates": [{"template_id": "custom", "label": "Custom", "template_type": "combined", "directory": str(template), "config_name": original["config_name"]}]})
    monkeypatch.setenv("ALPHAPILOT_RESEARCH_CATALOG", str(catalog_file))
    body = {"kind": "factor_backtest", "input": {"dataset_id": dataset["dataset_id"], "template_id": "custom", "factor_source": {"type": "inline", "factors": [{"name": "close", "expression": "$close"}]}}}
    first = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "preset"})
    assert first.status_code == 202, first.text
    assert first.json()["normalized_input"]["parameters"]["topk"] == 13
    body["input"]["parameters"] = {"topk": 9}
    second = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "explicit"})
    assert second.json()["normalized_input"]["parameters"]["topk"] == 9


def test_independent_http_client_and_gui_share_job_and_artifact(research, tmp_path, monkeypatch):
    """Exercise the standalone stdlib client against a real ephemeral HTTP port."""
    import importlib.util
    import socket
    import threading
    import time
    import uvicorn
    from alphapilot.research import executor, runtime
    from alphapilot.research.artifacts import ArtifactService
    client, store, auth = research
    dataset = prepare_dataset(client)
    spec = importlib.util.spec_from_file_location("independent_client", Path(__file__).parents[1] / "examples/research/http_client.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token = auth.create("mcp-client", sorted(SCOPES))["token"]
    socket_ = socket.socket()
    socket_.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(client.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[socket_]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        external = module.ResearchClient(f"http://127.0.0.1:{socket_.getsockname()[1]}", token)
        assert external.request("/capabilities")["api_version"] == "1.0.0"
        request = {"kind": "factor_backtest", "input": {"dataset_id": dataset["dataset_id"], "factor_source": {"type": "inline", "factors": [{"name": "close", "expression": "$close"}]}}}
        job = external.request("/jobs", request, key="http-intent")
        assert external.request("/jobs", request, key="http-intent")["job_id"] == job["job_id"]
        assert client.get("/api/v1/jobs/" + job["job_id"]).json()["client_id"] == "mcp-client"
        client.post("/api/v1/jobs/" + job["job_id"] + "/cancel")
        assert external.request("/jobs/" + job["job_id"])["status"] == "cancelled"
        artifact = ArtifactService(store).register_json({"metrics": {"IC": .1}}, kind="evaluation")
        downloaded = external.download(external.request("/artifacts/" + artifact["artifact_id"]), tmp_path / "client-downloads")
        assert json.loads(downloaded.read_text()) == {"metrics": {"IC": .1}}
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        socket_.close()
    assert not thread.is_alive()


def test_schedule_update_requires_existing_id_and_observed_revision(research):
    client, *_ = research
    payload = {"name": "daily", "time": "16:30", "job": {"kind": "mine", "input": {"dataset_id": "fixture", "max_steps": 2}}}
    assert client.put("/api/v1/schedules/missing", json=payload, headers={"If-Match": "1"}).status_code == 404
    created = client.post("/api/v1/schedules", json=payload)
    assert created.status_code == 201, created.text
    row = created.json()
    url = "/api/v1/schedules/" + row["schedule_id"]
    assert client.put(url, json=payload).status_code == 428
    payload["name"] = "renamed"
    updated = client.put(url, json=payload, headers={"If-Match": str(row["revision"])})
    assert updated.status_code == 200, updated.text
    assert client.put(url, json=payload, headers={"If-Match": str(row["revision"])}).status_code == 412


def test_portable_strategy_round_trip_keeps_expressions_without_executable_state(research):
    client, *_ = research
    dataset = prepare_dataset(client)
    from alphapilot.systems.strategy.base import StrategyModelSpec, StrategyRecord
    client.app.state.engine.get_system("strategy").register_strategy(StrategyRecord(
        strategy_name="historical", factor_formulas=["$close"], model=StrategyModelSpec(model_name="LGBModel"),
        metadata={"market": "all", "yaml_params": {"provider_uri": "/private/data", "topk": 9}, "secret": "private-token"}))
    strategies = client.get("/api/v1/strategies").json()["items"]
    original = next(s for s in strategies if s["name"] == "historical")
    exported = client.post("/api/v1/strategies/export", json={"ids": [original["id"]]})
    assert exported.status_code == 200, exported.text
    content = client.get(exported.json()["content_url"])
    assert "/private/data" not in content.text and "private-token" not in content.text
    bundle = content.json()
    assert bundle["items"][0]["factor_expressions"] == ["$close"]
    assert bundle["items"][0]["dataset_id"] is None
    bundle["items"][0]["name"] = "imported"
    upload = client.post("/api/v1/uploads", files={"file": ("recipe.json", json.dumps(bundle).encode(), "application/json")})
    payload = {"upload_id": upload.json()["upload_id"]}
    before = client.get("/api/v1/factors").json()["items"]
    missing = client.post("/api/v1/strategies/import", json=payload)
    assert missing.json()["items"][0]["error"]["code"] == "DATASET_REQUIRED"
    imported = client.post("/api/v1/strategies/import", params={"dataset_id": dataset["dataset_id"]}, json=payload)
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 1, imported.text
    row = client.get("/api/v1/strategies/" + imported.json()["items"][0]["id"]).json()
    assert row["metadata"]["factor_formulas"] == ["$close"]
    assert row["metadata"]["metadata"]["requires_retrain"] is True
    assert client.get("/api/v1/factors").json()["items"] == before


def test_deleted_asset_id_never_resolves_to_recreated_name(research):
    client, *_ = research
    body = {"name": "same", "expression": "TS_MEAN($close,10)/($close+1e-8)-1"}
    first = client.post("/api/v1/factors", json=body).json()
    assert client.delete("/api/v1/factors/" + first["id"], headers={"If-Match": str(first["revision"])}).status_code == 200
    recreated = client.post("/api/v1/factors", json=body)
    assert recreated.status_code == 201, recreated.text
    assert recreated.json()["id"] != first["id"]
    assert client.get("/api/v1/factors/" + first["id"]).status_code == 404


def test_separate_runtime_and_worker_processes_publish_http_results_once(research):
    import os
    import subprocess
    import sys
    import time
    from alphapilot.research.runtime import status
    from alphapilot.research.execution import ExecutionHandle
    client, store, _ = research
    body = {"kind": "data", "input": {"action": "delete_symbol", "dataset_id": "baostock_cn:day:backward", "symbol": "SH600000", "dry_run": True}, "notify": False}
    accepted = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "real-offline-worker"})
    assert accepted.status_code == 202, accepted.text
    key = accepted.json()["job_id"]
    def wait_for(predicate):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(.1)
        pytest.fail("Timed out waiting for isolated task runtime")
    processes = []
    with (store.root / "integration-runtime.log").open("wb") as output:
        def start():
            process = subprocess.Popen([sys.executable, "-m", "alphapilot.research.runtime", "--root", str(store.root)],
                                       env=dict(os.environ), stdout=output, stderr=output)
            processes.append(process)
            return process
        try:
            first = start()
            wait_for(lambda: client.get(f"/api/v1/jobs/{key}").json()["status"] in {"succeeded", "failed", "lost"})
            job = client.get(f"/api/v1/jobs/{key}").json()
            assert job["status"] == "succeeded", job
            result = client.get(f"/api/v1/jobs/{key}/result").json()
            assert result["availability"] == "complete"
            assert result["run_ids"] and result["artifact_ids"]
            artifact = client.get("/api/v1/artifacts/" + result["artifact_ids"][0]).json()
            assert client.get(artifact["content_url"]).status_code == 200
            first.terminate()
            first.wait(timeout=10)
            start()
            wait_for(lambda: status(store)["running"])
            repeated = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "real-offline-worker"})
            assert repeated.json()["job_id"] == key
            with store.connect() as db:
                assert db.execute("SELECT count(*) FROM executions WHERE job_id=?", (key,)).fetchone()[0] == 1
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
            with store.connect() as db:
                executions = [row[0] for row in db.execute("SELECT id FROM executions WHERE job_id=?", (key,))]
            for execution in executions:
                ExecutionHandle(store, execution).stop()


def test_invalid_asset_bundle_returns_structured_field_errors(research):
    client, *_ = research
    bundle = {"schema_version": "1", "kind": "factor", "items": ["not-an-asset"]}
    upload = client.post("/api/v1/uploads", files={"file": ("bundle.json", json.dumps(bundle).encode(), "application/json")})
    result = client.post("/api/v1/factors/import", json={"upload_id": upload.json()["upload_id"]})
    assert result.status_code == 422, result.text
    assert result.json()["code"] == "VALIDATION_ERROR"
    assert result.json()["details"][0]["loc"][-2:] == ["items", 0]


def test_mcp_run_and_artifact_pagination(research):
    client, store, _ = research
    with store.connect(write=True) as db:
        for run_id, job_id in [('run-a', 'job-a'), ('run-b', 'job-a'), ('run-c', 'job-b')]:
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (run_id, job_id, None, '/private', encode({'command': 'mine'})))
            for index in range(3):
                artifact_id = f'{run_id}-{index}'
                payload = {'artifact_id': artifact_id, 'run_id': run_id, 'job_id': job_id, 'kind': 'test',
                           'schema_version': '1', 'media_type': 'text/plain', 'size': 0, 'sha256': '0' * 64,
                           'name': 'test.txt', 'created_at': now(), 'content_url': f'/api/v1/artifacts/{artifact_id}/content'}
                db.execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?)', (artifact_id, job_id, run_id, None, '/private', encode(payload), 1))
    first = client.get('/api/v1/runs', params={'job_id': 'job-a', 'limit': 1, 'include_artifacts': False}).json()
    assert first['total'] == 2 and first['items'][0]['artifacts'] == []
    second = client.get('/api/v1/runs', params={'job_id': 'job-a', 'limit': 1, 'cursor': first['next_cursor']}).json()
    assert second['items'][0]['run_id'] != first['items'][0]['run_id']
    assert len(second['items'][0]['artifacts']) == 3
    assert client.get('/api/v1/runs', params={'job_id': 'job-b', 'cursor': first['next_cursor']}).status_code == 422
    items = []
    cursor = None
    while True:
        response = client.get('/api/v1/artifacts', params={k: v for k, v in {'job_id': 'job-a', 'run_id': 'run-a', 'limit': 2, 'cursor': cursor}.items() if v is not None})
        assert response.status_code == 200, response.text
        page = response.json()
        items.extend(page['items'])
        cursor = page['next_cursor']
        if cursor is None:
            break
    assert len({row['artifact_id'] for row in items}) == 3
    assert client.get('/api/v1/artifacts', params={'limit': 201}).status_code == 422
    assert client.get('/api/v1/capabilities').json()['features']['mining_checkpoint_resume']


def test_incremental_chinese_log_cursor_preserves_characters(research, monkeypatch):
    from alphapilot.research.tasks import TaskService
    client, store, _ = research
    key = 'unicode-log'
    folder = store.root / key
    folder.mkdir()
    original = '开始挖掘🚀\n第一轮完成\n'
    (folder / 'run.log').write_text(original)
    monkeypatch.setattr(TaskService, 'get', lambda *args, **kwargs: {'status': 'succeeded'})
    for limit in (1, 4, 8, 13):
        cursor, output = 0, ''
        for _ in range(100):
            response = client.get(f'/api/v1/jobs/{key}/logs', params={'cursor': cursor, 'limit': limit})
            assert response.status_code == 200, response.text
            row = response.json()
            output += row['text']
            assert row['next_cursor'] > cursor or row['complete']
            cursor = row['next_cursor']
            if row['complete']:
                break
        assert output == original
        assert cursor == len(original.encode())
