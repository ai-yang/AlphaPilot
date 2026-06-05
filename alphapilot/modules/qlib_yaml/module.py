"""CLI module for qlib qrun YAML generation and validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule
from alphapilot.systems.backtest.qlib_yaml.generator import generate_qlib_yaml
from alphapilot.systems.backtest.qlib_yaml.types import GenerateRequest, ValidateRequest
from alphapilot.systems.backtest.qlib_yaml.validator import print_validation_report, validate_qlib_yaml

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def _load_params_file(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    params_path = Path(path).expanduser()
    with params_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("params_file must contain a JSON object")
    return data


def _build_params_patch(
    params_file: str | None = None,
    *,
    market: str | None = None,
    benchmark: str | None = None,
    topk: int | None = None,
    backtest_start: str | None = None,
    backtest_end: str | None = None,
    test_start: str | None = None,
    test_end: str | None = None,
    learning_rate: float | None = None,
    provider_uri: str | None = None,
) -> dict[str, Any] | None:
    patch = _load_params_file(params_file) or {}
    optional = {
        "market": market,
        "benchmark": benchmark,
        "topk": topk,
        "backtest_start": backtest_start,
        "backtest_end": backtest_end,
        "test_start": test_start,
        "test_end": test_end,
        "learning_rate": learning_rate,
        "provider_uri": provider_uri,
    }
    for key, value in optional.items():
        if value is not None:
            patch[key] = value
    return patch or None


class QlibYamlModule(BaseModule):
    """Generate and validate qlib qrun YAML configs."""

    name = "qlib_yaml"

    def setup(self, context: "Context") -> None:
        self.context = context

    def qlib_yaml_generate(
        self,
        output: str,
        template: str = "baseline",
        prompt: str | None = None,
        params_file: str | None = None,
        market: str | None = None,
        benchmark: str | None = None,
        topk: int | None = None,
        backtest_start: str | None = None,
        backtest_end: str | None = None,
        test_start: str | None = None,
        test_end: str | None = None,
        learning_rate: float | None = None,
        provider_uri: str | None = None,
        workspace: str | None = None,
        skip_smoke: bool = False,
        smoke_timeout: int = 120,
        copy_helpers: bool = False,
    ) -> dict[str, Any]:
        """Generate a qlib qrun YAML from structured params and optional LLM prompt."""
        if template not in ("baseline", "combined"):
            raise ValueError("template must be 'baseline' or 'combined'")

        params_patch = _build_params_patch(
            params_file,
            market=market,
            benchmark=benchmark,
            topk=topk,
            backtest_start=backtest_start,
            backtest_end=backtest_end,
            test_start=test_start,
            test_end=test_end,
            learning_rate=learning_rate,
            provider_uri=provider_uri,
        )

        result = generate_qlib_yaml(
            GenerateRequest(
                template_type=template,  # type: ignore[arg-type]
                output=Path(output),
                params_patch=params_patch,
                prompt=prompt,
                skip_smoke=skip_smoke,
                smoke_timeout=smoke_timeout,
                workspace=Path(workspace).expanduser() if workspace else None,
                copy_helpers=copy_helpers,
            )
        )

        print_validation_report(result.validation)
        payload = {
            "output": str(result.output_path),
            "template": template,
            "validation_ok": result.validation.ok,
            "params": result.params,
        }
        if not result.validation.ok:
            sys.exit(1)
        return payload

    def qlib_yaml_validate(
        self,
        config: str,
        workspace: str | None = None,
        skip_smoke: bool = False,
        smoke_timeout: int = 120,
    ) -> dict[str, Any]:
        """Validate an existing qlib qrun YAML."""
        report = validate_qlib_yaml(
            ValidateRequest(
                config=Path(config),
                workspace=Path(workspace).expanduser() if workspace else None,
                skip_smoke=skip_smoke,
                smoke_timeout=smoke_timeout,
            )
        )
        print_validation_report(report)
        payload = report.to_dict()
        if not report.ok:
            sys.exit(1)
        return payload

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "qlib_yaml_generate": self.qlib_yaml_generate,
            "qlib_yaml_validate": self.qlib_yaml_validate,
        }
