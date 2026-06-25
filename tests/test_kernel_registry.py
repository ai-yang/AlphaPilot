"""Tier 1 (offline): kernel registry, engine wiring, and CLI command surface.

These are pure structural assertions — no network, no credentials. They guard
against a module/system silently dropping out of the registry or a CLI command
being renamed/removed without anyone noticing.
"""

from __future__ import annotations

from conftest import (
    EXPECTED_CLI_COMMANDS,
    EXPECTED_MODULES,
    EXPECTED_SYSTEMS,
)


def test_engine_loads_all_builtin_systems(engine) -> None:
    assert set(engine.systems.keys()) == set(EXPECTED_SYSTEMS)
    # Every system must answer get_system without raising.
    for name in EXPECTED_SYSTEMS:
        assert engine.get_system(name) is not None


def test_engine_loads_all_builtin_modules(engine) -> None:
    loaded = set(engine.modules.keys())
    missing = set(EXPECTED_MODULES) - loaded
    assert not missing, f"modules dropped from registry: {sorted(missing)}"
    # A new module appearing is also worth flagging so the snapshot stays honest.
    extra = loaded - set(EXPECTED_MODULES)
    assert not extra, f"unexpected new modules (update EXPECTED_MODULES): {sorted(extra)}"


def test_cli_command_surface_matches_snapshot(engine) -> None:
    commands = set(engine.collect_commands().keys())
    assert commands == set(EXPECTED_CLI_COMMANDS), (
        "CLI command surface changed.\n"
        f"  missing: {sorted(set(EXPECTED_CLI_COMMANDS) - commands)}\n"
        f"  added:   {sorted(commands - set(EXPECTED_CLI_COMMANDS))}"
    )


def test_all_commands_are_callable(engine) -> None:
    for name, fn in engine.collect_commands().items():
        assert callable(fn), f"command {name!r} is not callable"


def test_unknown_system_raises(engine) -> None:
    import pytest

    with pytest.raises(KeyError):
        engine.get_system("does_not_exist")


def test_context_exposes_systems(engine) -> None:
    # Modules reach systems through the shared Context; confirm the wiring.
    ctx = engine.context
    assert ctx.config is not None
    assert ctx.engine is engine
