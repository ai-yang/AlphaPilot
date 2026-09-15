"""Frontend interaction-to-OpenAPI consistency checks."""

from __future__ import annotations

import json
import re
from pathlib import Path

from alphapilot.modules.portal.api import create_app


ROOT = Path(__file__).parents[1]
WEB_SRC = ROOT / "alphapilot" / "modules" / "portal" / "web" / "src"
MANIFEST = Path(__file__).with_name("portal_interaction_contracts.json")
CALL_RE = re.compile(
    r"api\.(get|post|patch|delete)(?:<[^;\n()]*>)?\(\s*([`\"])(/api/.*?)(?<!\\)\2",
    re.DOTALL,
)
RESEARCH_CALL_RE = re.compile(
    r'research\.(get|post|delete|all)(?:<[^;\n()]*>)?\(\s*([`"])(/.*?)(?<!\\)\2', re.DOTALL,
)


def _segments(path: str) -> list[str]:
    return [segment for segment in path.split("?", 1)[0].split("/") if segment]


def _matches(frontend_path: str, openapi_path: str) -> bool:
    front = _segments(frontend_path)
    back = _segments(openapi_path)
    if len(front) != len(back):
        return False
    return all("${" in left or (right.startswith("{") and right.endswith("}")) or left == right for left, right in zip(front, back))


def _operations() -> set[tuple[str, str]]:
    spec = create_app().openapi()
    return {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in {"get", "post", "patch", "delete", "put"}
    }


def test_declared_interaction_contracts_are_unique_and_exist_in_openapi() -> None:
    contracts = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert len({item["id"] for item in contracts}) == len(contracts)
    operations = _operations()
    missing = [
        (item["method"], item["path"])
        for item in contracts
        if (item["method"], item["path"]) not in operations
    ]
    assert missing == []
    for item in contracts:
        assert item["page"] and item["action"] and item["states"]
        assert len(item["states"]) >= 2


def test_every_literal_frontend_api_call_resolves_to_an_openapi_operation() -> None:
    operations = _operations()
    calls: set[tuple[str, str]] = set()
    for source in WEB_SRC.rglob("*.ts*"):
        if ".test." in source.name:
            continue
        text = source.read_text(encoding="utf-8")
        calls.update((match.group(1).upper(), match.group(3)) for match in CALL_RE.finditer(text))
        calls.update(("GET" if match.group(1) == "all" else match.group(1).upper(), "/api/v1" + match.group(3))
                     for match in RESEARCH_CALL_RE.finditer(text))
    assert len(calls) >= 65, "API extraction unexpectedly missed a large part of the Portal surface"
    missing = [
        (method, path)
        for method, path in sorted(calls)
        if not any(method == spec_method and _matches(path, spec_path) for spec_method, spec_path in operations)
    ]
    assert missing == []
