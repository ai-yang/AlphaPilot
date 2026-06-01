"""Scenario registry for CLI workflow selection.

This module introduces a lightweight registration mechanism so workflow
entrypoints (e.g. ``alphapilot mine`` / ``alphapilot backtest``) no
longer hardcode a single scenario preset.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScenarioSpec:
    """A scenario preset wired to a loop class + prop setting."""

    name: str
    description: str
    loop_class_path: str
    prop_setting_path: str
    commands: tuple[str, ...] = field(default_factory=tuple)


class ScenarioRegistry:
    """In-memory registry for scenario presets."""

    def __init__(self) -> None:
        self._specs: dict[str, ScenarioSpec] = {}

    def register(self, spec: ScenarioSpec) -> ScenarioSpec:
        if spec.name in self._specs:
            raise ValueError(f"Scenario {spec.name!r} is already registered.")
        self._specs[spec.name] = spec
        return spec

    def get(self, name: str, command: str | None = None) -> ScenarioSpec:
        if name not in self._specs:
            available = ", ".join(sorted(self._specs))
            raise KeyError(f"Scenario {name!r} not found. Available: [{available}]")
        spec = self._specs[name]
        if command and command not in spec.commands:
            allowed = ", ".join(spec.commands)
            raise ValueError(
                f"Scenario {name!r} does not support command {command!r}. "
                f"Allowed: [{allowed}]"
            )
        return spec

    def list(self, command: str | None = None) -> list[ScenarioSpec]:
        specs = sorted(self._specs.values(), key=lambda s: s.name)
        if command is None:
            return specs
        return [s for s in specs if command in s.commands]


SCENARIO_REGISTRY = ScenarioRegistry()


def register_scenario(spec: ScenarioSpec) -> ScenarioSpec:
    return SCENARIO_REGISTRY.register(spec)


def get_scenario(name: str, command: str | None = None) -> ScenarioSpec:
    return SCENARIO_REGISTRY.get(name, command=command)


def list_scenarios(command: str | None = None) -> list[ScenarioSpec]:
    return SCENARIO_REGISTRY.list(command=command)


def _register_builtins() -> None:
    register_scenario(
        ScenarioSpec(
            name="alpha_factor_mining",
            description="AlphaPilot factor mining loop (default).",
            loop_class_path="alphapilot.modules.alpha_mining.loops.alphapilot_loop.AlphaPilotLoop",
            prop_setting_path="alphapilot.modules.alpha_mining.conf.ALPHAPILOT_FACTOR_PROP_SETTING",
            commands=("mine",),
        )
    )
    register_scenario(
        ScenarioSpec(
            name="factor_backtest",
            description="Single-round factor backtest loop.",
            loop_class_path="alphapilot.modules.alpha_mining.loops.alphapilot_loop.BacktestLoop",
            prop_setting_path="alphapilot.modules.alpha_mining.conf.FACTOR_BACK_TEST_PROP_SETTING",
            commands=("backtest",),
        )
    )


_register_builtins()
