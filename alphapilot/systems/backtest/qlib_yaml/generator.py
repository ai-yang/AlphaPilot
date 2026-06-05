"""Render qlib qrun YAML from structured params and optional LLM patches."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from alphapilot.core.prompts import Prompts
from alphapilot.kernel.paths import factor_qlib_templates_dir
from alphapilot.log import logger
from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams
from alphapilot.systems.backtest.qlib_yaml.types import GenerateRequest, GenerateResult, ValidateRequest
from alphapilot.systems.backtest.qlib_yaml.validator import validate_qlib_yaml

_PACKAGE_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _PACKAGE_DIR / "templates"
_PROMPTS = Prompts(file_path=_PACKAGE_DIR / "prompts.yaml")

_TEMPLATE_FILES = {
    "baseline": "conf.yaml.j2",
    "combined": "conf_cn_combined_kdd_ver.yaml.j2",
}


def _jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=False,
    )
    env.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)
    return env


def render_yaml_text(params: QlibYamlParams) -> str:
    template_name = _TEMPLATE_FILES[params.template_type]
    text = _jinja_env().get_template(template_name).render(p=params)
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("Rendered YAML did not produce a mapping")
    return text


def _apply_llm_patch(params: QlibYamlParams, prompt: str) -> QlibYamlParams:
    from jinja2 import Environment as JinjaEnvironment

    from alphapilot.adapters import get_llm
    from alphapilot.oai.llm_utils import extract_and_validate_llm_json

    jinja = JinjaEnvironment(undefined=StrictUndefined)
    system_prompt = jinja.from_string(_PROMPTS["qlib_yaml_patch"]["system"]).render()
    user_prompt = jinja.from_string(_PROMPTS["qlib_yaml_patch"]["user"]).render(
        current_params=json.dumps(params.model_dump(), ensure_ascii=False, indent=2),
        allowed_fields=json.dumps(params.llm_schema_hint(), ensure_ascii=False, indent=2),
        user_request=prompt.strip(),
    )

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            resp = get_llm().chat_completion(user_prompt, system_prompt, json_mode=True)
            patch = json.loads(extract_and_validate_llm_json(resp))
            if not isinstance(patch, dict):
                raise ValueError("LLM patch must be a JSON object")
            return QlibYamlParams.merge_patch(params, patch)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning(f"LLM patch attempt {attempt + 1} failed: {exc}")
    raise RuntimeError(f"Failed to apply LLM patch after retries: {last_error}")


def _maybe_copy_helpers(output_path: Path) -> None:
    helper_src = factor_qlib_templates_dir() / "read_exp_res.py"
    if not helper_src.is_file():
        logger.warning(f"Helper script not found at {helper_src}; skip copy")
        return
    dst = output_path.parent / "read_exp_res.py"
    if dst.exists():
        logger.info(f"Helper already exists: {dst}")
        return
    shutil.copy2(helper_src, dst)
    logger.info(f"Copied read_exp_res.py to {dst}")


def generate_qlib_yaml(request: GenerateRequest) -> GenerateResult:
    params = QlibYamlParams.defaults_for(request.template_type)
    if request.params_patch:
        params = QlibYamlParams.merge_patch(params, request.params_patch)
    if request.prompt:
        params = _apply_llm_patch(params, request.prompt)

    yaml_text = render_yaml_text(params)

    if request.output is None:
        default_name = (
            "conf.yaml" if params.template_type == "baseline" else "conf_cn_combined_kdd_ver.yaml"
        )
        output_path = Path.cwd() / default_name
    else:
        output_path = Path(request.output).expanduser().resolve()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml_text, encoding="utf-8")
    logger.info(f"Wrote qlib config to {output_path}")

    if request.copy_helpers:
        _maybe_copy_helpers(output_path)

    validation = validate_qlib_yaml(
        ValidateRequest(
            config=output_path,
            workspace=request.workspace,
            skip_smoke=request.skip_smoke,
            smoke_timeout=request.smoke_timeout,
        )
    )

    return GenerateResult(
        output_path=output_path,
        yaml_text=yaml_text,
        params=params.model_dump(),
        validation=validation,
    )
