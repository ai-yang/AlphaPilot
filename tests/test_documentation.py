"""Documentation coverage, generated-reference and safety contracts."""

from __future__ import annotations

import json
import inspect
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import sys
import tomllib
from urllib.parse import unquote

from alphapilot.kernel import build_engine
from alphapilot.modules.portal.api import create_app


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CATALOG = json.loads((DOCS / "catalog.json").read_text(encoding="utf-8"))
REMOVED_STAGE_COMMANDS = {
    "trading_stage_start",
    "trading_stage_finish",
    "trading_stage_evaluate",
}


def _markdown_files() -> list[Path]:
    return [ROOT / "README.md", ROOT / "README_en.md", *sorted(DOCS.rglob("*.md"))]


def _github_heading_anchors(document: Path) -> set[str]:
    anchors: set[str] = set()
    occurrences: dict[str, int] = {}
    for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*$", document.read_text(encoding="utf-8")):
        value = re.sub(r"<[^>]+>", "", heading).lower()
        value = re.sub(r"[^\w\-\s]", "", value, flags=re.UNICODE)
        value = re.sub(r"\s", "-", value)
        suffix = occurrences.get(value, 0)
        occurrences[value] = suffix + 1
        anchors.add(value if suffix == 0 else f"{value}-{suffix}")
    return anchors


def test_first_party_component_and_cli_documentation_surface(isolated_env) -> None:  # noqa: ANN001
    engine = build_engine(discover=False)
    try:
        assert set(engine.systems) == set(CATALOG["systems"])
        assert set(engine.modules) == set(CATALOG["modules"])
        assert len(engine.systems) == 7
        assert len(engine.modules) == 15
        assert len(engine.collect_commands()) == 120
        assert REMOVED_STAGE_COMMANDS.isdisjoint(engine.collect_commands())
        trading = engine.get_system("trading")
        assert not hasattr(trading, "start_stage_run")
        assert not hasattr(trading, "finish_stage_run")
        assert not hasattr(trading, "evaluate_stage")
        assert not hasattr(trading.store, "start_stage_run")
        assert hasattr(trading.store, "configure_deployment")
        assert hasattr(trading.store, "runtime_diagnostics")
        assert hasattr(trading.store, "create_decision_comparison")
    finally:
        engine.shutdown()


def test_composition_root_and_packaging_entry_points_are_consistent() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    points = project["project"]["entry-points"]
    assert set(points["alphapilot.systems"]) == set(CATALOG["systems"])
    assert set(points["alphapilot.modules"]) == set(CATALOG["modules"])


def test_generated_documentation_is_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_docs_reference.py", "--check"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    cli_reference = (DOCS / "reference/cli.md").read_text(encoding="utf-8")
    main_reference, appendix = cli_reference.split("## 已弃用命令附录", 1)
    for command in CATALOG["cli_status"]["deprecated"]:
        assert f"`{command}`" not in main_reference
        assert f"`{command}`" in appendix


def test_documentation_generator_imports_its_own_checkout(tmp_path: Path) -> None:
    shadow_root = tmp_path / "shadow"
    shadow_package = shadow_root / "alphapilot"
    shadow_package.mkdir(parents=True)
    (shadow_package / "__init__.py").write_text(
        'raise RuntimeError("imported shadow AlphaPilot checkout")\n',
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(shadow_root)

    result = subprocess.run(
        [sys.executable, "scripts/generate_docs_reference.py", "--check"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_mermaid_diagrams_parse() -> None:
    web = ROOT / "alphapilot/modules/portal/web"
    result = subprocess.run(
        ["npm", "run", "docs:mermaid"],
        cwd=web,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_catalog_covers_portal_routes_and_openapi(isolated_env) -> None:  # noqa: ANN001
    source = (ROOT / "alphapilot/modules/portal/web/src/main.tsx").read_text(encoding="utf-8")
    routes = {"/", *("/" + value.strip("/") for value in re.findall(r'\{ path: "([^"]+)"', source))}
    assert routes == {page["route"] for page in CATALOG["portal_pages"]}
    assert len(routes) == 11

    engine = build_engine(discover=False)
    try:
        spec = create_app(engine=engine).openapi()
    finally:
        engine.shutdown()
    methods = {"get", "post", "put", "patch", "delete"}
    operations = {
        (method.upper(), path)
        for path, item in spec["paths"].items()
        for method in item
        if method in methods
    }
    assert len(spec["paths"]) == 138
    assert len(operations) == 155
    assert not any(path.startswith("/api/timing/") for path in spec["paths"])
    assert not any(path.startswith("/api/live/daemon/strategy/") for path in spec["paths"])
    removed_fragments = {
        "stage-runs", "parity-runs", "qualification", "authorize-live",
        "execution-binding", "/promote",
    }
    assert not any(
        any(fragment in path for fragment in removed_fragments)
        for _method, path in operations
    )
    reference = (DOCS / "reference/http-api.md").read_text(encoding="utf-8")
    for method, path in operations:
        assert f"`{method}`" in reference
        assert f"`{path}`" in reference


def test_component_documents_and_portal_images_exist() -> None:
    for group in ("systems", "modules"):
        for item in CATALOG[group].values():
            for key in ("user_doc", "developer_doc"):
                path = DOCS / item[key]
                assert path.is_file(), path
                assert path.stat().st_size > 200, path
    expected_images = {Path(page["screenshot"]).name for page in CATALOG["portal_pages"]}
    assert {path.name for path in (DOCS / "assets/portal").glob("*.png")} == expected_images
    screenshot_source = (
        ROOT / "alphapilot/modules/portal/web/e2e/docs-screenshots.spec.ts"
    ).read_text(encoding="utf-8")
    for page in CATALOG["portal_pages"]:
        image = DOCS / page["screenshot"]
        assert image.is_file(), image
        assert f'"{page["route"]}"' in screenshot_source
        assert f'"{image.name}"' in screenshot_source
        data = image.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n"), image
        width, height = struct.unpack(">II", data[16:24])
        assert width >= 1200 and height >= 700, (image, width, height)


def test_guides_and_component_pages_have_the_required_visual_structure() -> None:
    for guide in sorted((DOCS / "user").glob("*.md")):
        text = guide.read_text(encoding="utf-8")
        assert "```mermaid" in text, guide
        assert "![" in text, guide
        assert "前置条件" in text, guide
        assert any(value in text for value in ("常见错误", "常见问题", "排错")), guide

    for page in sorted((DOCS / "developer/systems").glob("*.md")):
        text = page.read_text(encoding="utf-8")
        assert "```mermaid" in text, page
        assert "职责与非职责" in text, page
        assert "测试" in text, page
    for page in sorted((DOCS / "developer/modules").glob("*.md")):
        if page.name == "README.md":
            continue
        text = page.read_text(encoding="utf-8")
        assert "```mermaid" in text, page
        assert "用户能力" in text, page
        assert "测试" in text, page


def test_portal_reference_records_cli_api_and_equivalence() -> None:
    reference = (DOCS / "reference/portal-capabilities.md").read_text(encoding="utf-8")
    for page in CATALOG["portal_pages"]:
        for key in ("cli", "api", "equivalence"):
            assert page[key], (page["route"], key)
            assert page[key] in reference, (page["route"], key)
    assert "Portal/API-only" in reference


def test_markdown_relative_links_and_fences_are_valid() -> None:
    link_pattern = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
    image_pattern = re.compile(r'<img[^>]+src="([^"]+)"')
    for document in _markdown_files():
        text = document.read_text(encoding="utf-8")
        assert text.count("```") % 2 == 0, f"unbalanced code fences: {document}"
        targets = [*link_pattern.findall(text), *image_pattern.findall(text)]
        for raw in targets:
            clean = raw.strip().strip("<>")
            target_raw, separator, fragment_raw = clean.partition("#")
            target = unquote(target_raw)
            if target.startswith(("http://", "https://", "mailto:", "/")):
                continue
            resolved = document if not target else (document.parent / target).resolve()
            assert resolved.exists(), f"broken link in {document.relative_to(ROOT)}: {raw}"
            if separator and resolved.suffix.lower() == ".md":
                fragment = unquote(fragment_raw).lower()
                assert fragment in _github_heading_anchors(resolved), (
                    f"broken heading anchor in {document.relative_to(ROOT)}: {raw}"
                )


def test_user_cli_examples_only_use_registered_commands(isolated_env) -> None:  # noqa: ANN001
    engine = build_engine(discover=False)
    try:
        command_map = engine.collect_commands()
        commands = set(command_map)
    finally:
        engine.shutdown()
    current_guides = [DOCS / "alphapilot-cli.md", *sorted((DOCS / "user").glob("*.md"))]
    for document in current_guides:
        text = document.read_text(encoding="utf-8")
        for name in re.findall(
            r"(?m)^\s*alphapilot\s+([A-Za-z][A-Za-z0-9_-]*)", text
        ):
            assert name in commands, f"unknown CLI example {name} in {document.relative_to(ROOT)}"

        for block in re.findall(r"```bash\s*\n(.*?)```", text, flags=re.DOTALL):
            logical_lines: list[str] = []
            pending = ""
            for raw_line in block.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                pending += (" " if pending else "") + line.removesuffix("\\").strip()
                if line.endswith("\\"):
                    continue
                logical_lines.append(pending)
                pending = ""
            if pending:
                logical_lines.append(pending)
            for line in logical_lines:
                if not line.startswith("alphapilot "):
                    continue
                arguments = shlex.split(line)
                name = arguments[1]
                if name not in command_map or arguments[2:4] == ["--", "--help"]:
                    continue
                signature = inspect.signature(command_map[name])
                accepts_extra = any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in signature.parameters.values()
                )
                for argument in arguments[2:]:
                    if not argument.startswith("--") or argument == "--":
                        continue
                    parameter_name = argument[2:].split("=", 1)[0].replace("-", "_")
                    assert accepts_extra or parameter_name in signature.parameters, (
                        f"unknown parameter --{parameter_name} for {name} in "
                        f"{document.relative_to(ROOT)}"
                    )


def test_current_guides_do_not_restore_removed_interfaces() -> None:
    current = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [DOCS / "index.md", DOCS / "alphapilot-cli.md", *sorted((DOCS / "user").glob("*.md"))]
    )
    forbidden = (
        "/api/timing/",
        "/api/live/daemon/strategy/",
        "trading_stage_start --",
        "trading_stage_finish --",
        "trading_stage_evaluate --",
    )
    for value in forbidden:
        assert value not in current


def test_documentation_text_and_images_do_not_contain_credentials() -> None:
    text = "\n".join(path.read_text(encoding="utf-8") for path in _markdown_files())
    assert re.search(r"/home/[^/\s]+/", text) is None
    assert re.search(r"/Users/(?!\.\.\.)[^/\s]+/", text) is None
    assert re.search(r"[A-Za-z]:\\Users\\[^\\\s]+\\", text) is None
    assert "-----BEGIN PRIVATE KEY-----" not in text
    assert re.search(r"\bsk-[A-Za-z0-9_-]{20,}\b", text) is None

    secret_values = {
        value.encode()
        for key, value in os.environ.items()
        if len(value) >= 8 and any(token in key.upper() for token in ("TOKEN", "PASSWORD", "SECRET", "API_KEY"))
    }
    for image in (DOCS / "assets/portal").glob("*.png"):
        payload = image.read_bytes()
        for secret in secret_values:
            assert secret not in payload, image
