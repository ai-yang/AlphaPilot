"""Validate qlib qrun YAML configs (static + qlib smoke)."""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from alphapilot.systems.backtest.qlib_yaml.types import ValidateRequest, ValidationCheck, ValidationReport

_QLIB_FIELD_PATTERN = re.compile(r"\$[a-zA-Z_][a-zA-Z0-9_]*")
_COMBINED_MARKERS = ("NestedDataLoader", "StaticDataLoader", "combined_factors_df.pkl")


def _parse_date(value: str) -> datetime:
    return datetime.strptime(str(value).strip(), "%Y-%m-%d")


def _add(checks: list[ValidationCheck], name: str, ok: bool, message: str, *, level: str = "error") -> None:
    checks.append(ValidationCheck(name=name, level=level, ok=ok, message=message))


def _load_conf(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        conf = yaml.safe_load(handle)
    if not isinstance(conf, dict):
        raise ValueError("YAML root must be a mapping")
    return conf


def _find_segments(conf: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return conf["task"]["dataset"]["kwargs"]["segments"]
    except (KeyError, TypeError):
        return None


def _find_backtest(conf: dict[str, Any]) -> dict[str, Any] | None:
    port = conf.get("port_analysis_config")
    if isinstance(port, dict):
        backtest = port.get("backtest")
        if isinstance(backtest, dict):
            return backtest
    try:
        records = conf["task"]["record"]
        for record in records:
            if not isinstance(record, dict):
                continue
            cfg = record.get("kwargs", {}).get("config")
            if isinstance(cfg, dict) and "backtest" in cfg:
                return cfg["backtest"]
    except (KeyError, TypeError):
        pass
    return None


def _extract_feature_expressions(conf: dict[str, Any]) -> list[str]:
    expressions: list[str] = []
    handler = conf.get("data_handler_config")
    if not isinstance(handler, dict):
        try:
            handler = conf["task"]["dataset"]["kwargs"]["handler"]["kwargs"]
        except (KeyError, TypeError):
            handler = None
    if not isinstance(handler, dict):
        return expressions

    loader = handler.get("data_loader", {})
    if not isinstance(loader, dict):
        return expressions

    if loader.get("class") == "qlib.contrib.data.loader.QlibDataLoader":
        config = loader.get("kwargs", {}).get("config", {})
        features = config.get("feature", []) if isinstance(config, dict) else []
        if isinstance(features, list):
            expressions.extend(str(x) for x in features)
    elif loader.get("class") == "NestedDataLoader":
        for item in loader.get("kwargs", {}).get("dataloader_l", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("class") != "qlib.contrib.data.loader.QlibDataLoader":
                continue
            config = item.get("kwargs", {}).get("config", {})
            features = config.get("feature", []) if isinstance(config, dict) else []
            if isinstance(features, list):
                expressions.extend(str(x) for x in features)
    return expressions


def _is_combined_config(conf: dict[str, Any], raw_text: str) -> bool:
    blob = yaml.safe_dump(conf, allow_unicode=True)
    return any(marker in blob or marker in raw_text for marker in _COMBINED_MARKERS)


def _validate_expression(expr: str, checks: list[ValidationCheck], prefix: str) -> None:
    if not expr.strip():
        _add(checks, f"{prefix}_non_empty", False, "Expression must not be empty")
        return
    if not _QLIB_FIELD_PATTERN.search(expr):
        _add(
            checks,
            f"{prefix}_qlib_fields",
            False,
            f"Expression lacks qlib field prefix ($close, etc.): {expr!r}",
            level="warning",
        )


def run_static_validation(config_path: Path, workspace: Path | None = None) -> ValidationReport:
    checks: list[ValidationCheck] = []
    report = ValidationReport(config_path=config_path, checks=checks)

    if not config_path.is_file():
        _add(checks, "file_exists", False, f"Config not found: {config_path}")
        return report

    raw_text = config_path.read_text(encoding="utf-8")
    try:
        conf = _load_conf(config_path)
        _add(checks, "yaml_parse", True, "YAML parsed successfully")
    except Exception as exc:  # noqa: BLE001
        _add(checks, "yaml_parse", False, f"YAML parse error: {exc}")
        return report

    for key in ("qlib_init", "task", "data_handler_config"):
        ok = key in conf
        _add(checks, f"required_key_{key}", ok, f"Missing top-level key: {key}" if not ok else f"Found {key}")

    qlib_init = conf.get("qlib_init", {})
    provider_uri = qlib_init.get("provider_uri") if isinstance(qlib_init, dict) else None
    if provider_uri:
        provider_path = Path(str(provider_uri)).expanduser()
        ok = provider_path.exists()
        _add(
            checks,
            "provider_uri_exists",
            ok,
            f"provider_uri exists: {provider_path}" if ok else f"provider_uri missing: {provider_path}",
        )
    else:
        _add(checks, "provider_uri_exists", False, "qlib_init.provider_uri is missing")

    market = conf.get("market")
    if market and provider_uri:
        instruments = Path(str(provider_uri)).expanduser() / "instruments" / f"{market}.txt"
        ok = instruments.is_file()
        _add(
            checks,
            "market_instruments",
            ok,
            f"instruments file found: {instruments}" if ok else f"instruments file missing: {instruments}",
        )

    segments = _find_segments(conf)
    if segments:
        try:
            train = segments.get("train", [])
            valid = segments.get("valid", [])
            test = segments.get("test", [])
            if len(train) == 2 and len(valid) == 2 and len(test) == 2:
                ok = (
                    _parse_date(train[1]) < _parse_date(valid[0])
                    and _parse_date(valid[1]) < _parse_date(test[0])
                )
                _add(
                    checks,
                    "segment_order",
                    ok,
                    "train/valid/test segments are ordered correctly"
                    if ok
                    else "Segment dates must satisfy train_end < valid_start and valid_end < test_start",
                )
            else:
                _add(checks, "segment_order", False, "segments.train/valid/test must each have [start, end]")
        except ValueError as exc:
            _add(checks, "segment_order", False, f"Invalid segment dates: {exc}")
    else:
        _add(checks, "segment_order", False, "Could not locate task.dataset.kwargs.segments")

    backtest = _find_backtest(conf)
    if backtest and segments and len(segments.get("test", [])) == 2:
        try:
            bt_ok = _parse_date(backtest["start_time"]) >= _parse_date(segments["test"][0])
            bt_ok = bt_ok and _parse_date(backtest["end_time"]) <= _parse_date(segments["test"][1])
            _add(
                checks,
                "backtest_within_test",
                bt_ok,
                "Backtest window is within test segment"
                if bt_ok
                else "Backtest start/end must fall within test segment",
            )
        except (KeyError, ValueError) as exc:
            _add(checks, "backtest_within_test", False, f"Backtest date check failed: {exc}")
    else:
        _add(checks, "backtest_within_test", False, "Could not validate backtest window", level="warning")

    features = _extract_feature_expressions(conf)
    if features:
        _add(checks, "feature_non_empty", True, f"Found {len(features)} feature expression(s)")
        for idx, expr in enumerate(features):
            _validate_expression(expr, checks, f"feature_{idx}")
    else:
        _add(checks, "feature_non_empty", False, "No feature expressions found in data_loader")

    if _is_combined_config(conf, raw_text):
        _add(checks, "combined_template_detected", True, "Combined-factor template detected", level="info")
        if workspace is not None:
            pkl_path = workspace / "combined_factors_df.pkl"
            ok = pkl_path.is_file()
            _add(
                checks,
                "combined_pkl_exists",
                ok,
                f"Found {pkl_path}" if ok else f"Missing combined_factors_df.pkl in workspace: {pkl_path}",
                level="warning" if not ok else "info",
            )
        else:
            _add(
                checks,
                "combined_pkl_exists",
                True,
                "Workspace not provided; skipping combined_factors_df.pkl check",
                level="warning",
            )

    return report


def run_smoke_validation(config_path: Path, timeout: int = 120) -> ValidationReport:
    checks: list[ValidationCheck] = []
    report = ValidationReport(config_path=config_path, checks=checks)

    script = textwrap.dedent(
        f"""
        import sys
        import yaml
        import qlib
        from qlib.utils import init_instance_by_config

        conf_path = {str(config_path)!r}
        with open(conf_path, encoding="utf-8") as f:
            conf = yaml.safe_load(f)
        qlib.init(**conf["qlib_init"])
        handler_cfg = conf["task"]["dataset"]["kwargs"]["handler"]
        handler = init_instance_by_config(handler_cfg)
        handler.setup_data(init_type="infer")
        print("SMOKE_OK")
        """
    ).strip()

    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(config_path.parent),
        )
        ok = proc.returncode == 0 and "SMOKE_OK" in proc.stdout
        detail = proc.stderr.strip() or proc.stdout.strip() or "no output"
        _add(
            checks,
            "qlib_smoke",
            ok,
            "Qlib handler infer setup succeeded" if ok else f"Smoke test failed: {detail[:500]}",
        )
    except subprocess.TimeoutExpired:
        _add(checks, "qlib_smoke", False, f"Smoke test timed out after {timeout}s")
    except Exception as exc:  # noqa: BLE001
        _add(checks, "qlib_smoke", False, f"Smoke test error: {exc}")

    return report


def validate_qlib_yaml(request: ValidateRequest) -> ValidationReport:
    config_path = Path(request.config).expanduser().resolve()
    static_report = run_static_validation(config_path, workspace=request.workspace)
    if request.skip_smoke:
        static_report.checks.append(
            ValidationCheck(
                name="qlib_smoke",
                level="info",
                ok=True,
                message="Smoke test skipped (--skip_smoke)",
            )
        )
        return static_report

    if not static_report.ok:
        static_report.checks.append(
            ValidationCheck(
                name="qlib_smoke",
                level="info",
                ok=True,
                message="Smoke test skipped due to static validation errors",
            )
        )
        return static_report

    smoke_report = run_smoke_validation(config_path, timeout=request.smoke_timeout)
    static_report.checks.extend(smoke_report.checks)
    return static_report


def print_validation_report(report: ValidationReport) -> None:
    path = report.config_path or "(unknown)"
    print(f"Validation report for {path}")
    for check in report.checks:
        status = "OK" if check.ok else check.level.upper()
        print(f"  [{status}] {check.name}: {check.message}")
    print(f"Overall: {'PASS' if report.ok else 'FAIL'}")
