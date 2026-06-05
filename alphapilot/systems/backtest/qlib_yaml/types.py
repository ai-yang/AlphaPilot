"""DTOs for qlib YAML generation and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass
class ValidationCheck:
    name: str
    level: Literal["error", "warning", "info"]
    ok: bool
    message: str


@dataclass
class ValidationReport:
    config_path: Path | None = None
    checks: list[ValidationCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok or c.level != "error" for c in self.checks)

    @property
    def errors(self) -> list[ValidationCheck]:
        return [c for c in self.checks if not c.ok and c.level == "error"]

    @property
    def warnings(self) -> list[ValidationCheck]:
        return [c for c in self.checks if not c.ok and c.level == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "config_path": str(self.config_path) if self.config_path else None,
            "checks": [
                {"name": c.name, "level": c.level, "ok": c.ok, "message": c.message}
                for c in self.checks
            ],
        }


@dataclass
class GenerateRequest:
    template_type: Literal["baseline", "combined"] = "baseline"
    output: Path | None = None
    params_patch: dict[str, Any] | None = None
    prompt: str | None = None
    skip_smoke: bool = False
    smoke_timeout: int = 120
    workspace: Path | None = None
    copy_helpers: bool = False


@dataclass
class GenerateResult:
    output_path: Path
    yaml_text: str
    params: dict[str, Any]
    validation: ValidationReport


@dataclass
class ValidateRequest:
    config: Path
    workspace: Path | None = None
    skip_smoke: bool = False
    smoke_timeout: int = 120
