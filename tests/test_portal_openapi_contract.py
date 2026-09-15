"""Stable contract snapshot for the complete Portal HTTP surface."""

from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient

from alphapilot.modules.portal.api import create_app


EXPECTED_OPERATION_COUNT = 154
EXPECTED_PATH_COUNT = 130
EXPECTED_CONTRACT_SHA256 = "c27b28f9153b68e055e6e48efdf7b0d287287a6666f8acb7383df41b0da8fb58"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
LEGACY_HTTP_OPERATIONS = {
    ("get", "/api/timing/strategies"),
    ("post", "/api/timing/signal"),
    ("post", "/api/timing/backtest"),
    ("get", "/api/timing/jobs/{job_id}/detail"),
    ("post", "/api/trading/strategy-instances/{instance_id}/backtest"),
    ("post", "/api/trading/deployments/{instance_id}/{action}"),
    ("post", "/api/trading/stage-runs/{instance_id}/{stage}/start"),
    ("post", "/api/trading/stage-runs/{run_id}/finish"),
    ("post", "/api/trading/stage-runs/{instance_id}/{stage}/evaluate"),
    ("post", "/api/trading/deployments/{instance_id}/promote"),
    ("post", "/api/trading/deployments/{instance_id}/authorize-live"),
    ("get", "/api/trading/deployments/{instance_id}/qualification"),
    ("post", "/api/trading/deployments/{instance_id}/parity-runs"),
    ("get", "/api/trading/parity-runs/{run_id}"),
    ("get", "/api/trading/deployments/{instance_id}/execution-binding"),
    ("put", "/api/trading/deployments/{instance_id}/execution-binding"),
    ("post", "/api/live/daemon/strategy/status"),
    ("post", "/api/live/daemon/strategy/start"),
    ("post", "/api/live/daemon/strategy/pause"),
    ("post", "/api/live/daemon/strategy/resume"),
    ("post", "/api/live/daemon/strategy/stop"),
}


def _operation_contract(spec: dict) -> list[dict]:
    operations = []
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operations.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "operation_id": operation.get("operationId"),
                    "request_body_required": bool(
                        operation.get("requestBody", {}).get("required")
                    ),
                    "responses": sorted(operation.get("responses", {})),
                }
            )
    return sorted(operations, key=lambda item: (item["path"], item["method"]))


def test_openapi_operation_snapshot_is_exact() -> None:
    spec = create_app().openapi()
    contract = _operation_contract(spec)
    encoded = json.dumps(
        contract,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert len(spec["paths"]) == EXPECTED_PATH_COUNT
    assert len(contract) == EXPECTED_OPERATION_COUNT
    assert len({item["operation_id"] for item in contract}) == EXPECTED_OPERATION_COUNT
    assert hashlib.sha256(encoded).hexdigest() == EXPECTED_CONTRACT_SHA256

    by_path = {(item["method"], item["path"]): item for item in contract}
    for action in ("start", "pause", "reconcile", "resume", "stop"):
        item = by_path[("POST", f"/api/trading/deployments/{{instance_id}}/{action}")]
        assert item["operation_id"] == f"trading_deployment_{action}"


def test_all_typed_operations_declare_validation_errors() -> None:
    spec = create_app().openapi()
    for item in _operation_contract(spec):
        operation = spec["paths"][item["path"]][item["method"].lower()]
        has_typed_input = bool(
            operation.get("parameters") or operation.get("requestBody")
        )
        if has_typed_input:
            assert "422" in operation["responses"], item
        assert any(code.startswith("2") for code in operation["responses"]), item


def test_removed_http_operations_are_absent_and_none_remain_deprecated() -> None:
    spec = create_app().openapi()
    operations = {
        (method, path)
        for path, path_item in spec["paths"].items()
        for method in path_item
        if method in HTTP_METHODS
    }
    deprecated = {
        (method, path)
        for path, path_item in spec["paths"].items()
        for method, operation in path_item.items()
        if method in HTTP_METHODS and operation.get("deprecated") is True
    }

    assert LEGACY_HTTP_OPERATIONS.isdisjoint(operations)
    assert deprecated == set()


def test_representative_resource_and_validation_failures_never_return_500(isolated_env) -> None:
    client = TestClient(create_app())
    probes = [
        ("GET", "/api/jobs/missing/log", None),
        ("GET", "/api/jobs/missing/result", None),
        ("GET", "/api/backtests/missing", None),
        ("GET", "/api/trade-sessions/missing", None),
        ("POST", "/api/factors", {}),
        ("POST", "/api/jobs", {}),
        ("PATCH", "/api/factors/missing", {}),
    ]
    for method, path, body in probes:
        response = client.request(method, path, json=body)
        assert response.status_code == 410, (method, path, response.text)
        assert response.json()["code"] == "API_REMOVED"
