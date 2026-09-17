"""Static Docker/Compose contract checks for hosts where Docker is unavailable."""

from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]


def test_docker_build_inputs_and_runtime_command_are_consistent() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:20-slim AS web-builder" in dockerfile
    assert "FROM python:3.11-slim-bookworm AS runtime" in dockerfile
    assert "COPY alphapilot/modules/portal/web/package.json" in dockerfile
    assert "COPY --from=web-builder /web/dist ./alphapilot/modules/portal/web/dist" in dockerfile
    assert 'CMD ["alphapilot", "portal", "--host", "0.0.0.0", "--port", "19901"]' in dockerfile
    for path in ("requirements.txt", "pyproject.toml", "README.md", "docs/logo.svg"):
        assert (ROOT / path).exists(), f"Docker build input is missing: {path}"


def test_compose_services_mounts_commands_and_profiles_are_consistent() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert set(services) == {"portal", "notify", "live"}
    assert services["portal"]["command"] == [
        "alphapilot", "portal", "--host", "0.0.0.0", "--port", "19901"
    ]
    assert services["portal"]["ports"] == [
        "${ALPHAPILOT_PORTAL_BIND_ADDRESS:-127.0.0.1}:${ALPHAPILOT_PORTAL_PUBLISHED_PORT:-19901}:19901"
    ]
    assert services["portal"]["environment"]["ALPHAPILOT_RESEARCH_AUTOSTART"] == "1"
    assert services["notify"]["environment"]["ALPHAPILOT_RESEARCH_AUTOSTART"] == "0"
    assert services["notify"]["pid"] == "service:portal"
    assert services["notify"]["depends_on"]["portal"]["condition"] == "service_healthy"
    for name in ("portal", "notify"):
        service = services[name]
        assert service["environment"]["USE_LOCAL"] == "True"
        targets = {v.split(":", 1)[1] for v in service["volumes"]}
        for directory in ("factor_zoo", "strategy_zoo", "stock_pools"):
            assert f"/app/important_data/{directory}" in targets
    assert services["notify"]["profiles"] == ["notify"]
    assert services["live"]["profiles"] == ["live"]
    assert services["live"]["build"]["dockerfile"] == "Dockerfile.live"
    for service in services.values():
        build = service.get("build")
        if isinstance(build, dict):
            assert (ROOT / build["dockerfile"]).is_file()
        for volume in service.get("volumes", []):
            host, container = volume.split(":", 1)
            assert host.startswith("./docker-data/")
            assert container.startswith("/")


def test_docker_context_excludes_secrets_state_and_local_build_outputs() -> None:
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    required = {
        ".env",
        "git_ignore_folder/",
        "docker-data/",
        "important_data/factor_zoo/",
        "important_data/strategy_zoo/",
        "important_data/stock_pools/",
        "pickle_cache/",
        "log/",
        ".git/",
        "alphapilot/modules/portal/web/node_modules/",
        "alphapilot/modules/portal/web/dist/",
    }
    assert required <= set(ignored)
    assert "!.env.docker.example" in ignored


def test_live_image_installs_standalone_tts_binding_and_plugin() -> None:
    dockerfile = (ROOT / "Dockerfile.live").read_text(encoding="utf-8")
    assert "FROM live-base AS live-tts" in dockerfile
    assert "COPY alphapilot_tts/ ./alphapilot_tts/" in dockerfile
    assert "pip install --no-deps --no-build-isolation ./alphapilot_tts" in dockerfile
    assert "plugins/alphapilot_broker_tts" not in dockerfile
    assert "LIVE_SMOKE_REQUIRE=xtp,emt,tts" in dockerfile
