from __future__ import annotations

import json
import subprocess
from unittest.mock import Mock


def _workspace_for_hash(factor_module):
    workspace = factor_module.FactorFBWorkspace.__new__(
        factor_module.FactorFBWorkspace
    )
    workspace.code_dict = {"factor.py": "expr = '$close'\n"}
    workspace.raise_exception = False
    return workspace


def test_factor_subprocess_environment_is_an_explicit_allowlist() -> None:
    from alphapilot.components.coder.factor_coder.factor import (
        _factor_subprocess_env,
    )

    child_env = _factor_subprocess_env(
        {
            "PATH": "/runtime/bin",
            "PYTHONPATH": "/project",
            "OMP_NUM_THREADS": "2",
            "ALPHAPILOT_FACTOR_DATA_DIR": "/safe/data",
            "OPENAI_API_KEY": "secret",
            "AWS_SESSION_TOKEN": "secret",
            "DATABASE_URL": "secret",
            "HTTP_COOKIE": "secret",
        }
    )

    assert child_env == {
        "PATH": "/runtime/bin",
        "PYTHONPATH": "/project",
        "OMP_NUM_THREADS": "2",
        "ALPHAPILOT_FACTOR_DATA_DIR": "/safe/data",
    }


def test_runtime_fingerprint_probes_the_execution_interpreter(monkeypatch) -> None:
    from alphapilot.components.coder.factor_coder import factor as factor_module

    payload = {
        "executable": "/opt/factor/bin/python",
        "python": "3.12.1",
        "sources": {"function_lib": {"sha256": "abc"}},
    }
    check_output = Mock(
        return_value=(
            "startup noise\n"
            f"{factor_module._RUNTIME_PROBE_PREFIX}{json.dumps(payload)}\n"
        )
    )
    monkeypatch.setattr(factor_module.subprocess, "check_output", check_output)

    first = factor_module._factor_runtime_fingerprint("/opt/factor/bin/python")

    args, kwargs = check_output.call_args
    assert args[0][0:2] == ["/opt/factor/bin/python", "-c"]
    assert args[0][2] == factor_module._RUNTIME_PROBE
    assert kwargs.get("shell", False) is False
    assert kwargs["text"] is True
    assert len(first) == 64

    check_output.return_value = (
        f"{factor_module._RUNTIME_PROBE_PREFIX}"
        f"{json.dumps(payload | {'python': '3.12.2'})}\n"
    )
    second = factor_module._factor_runtime_fingerprint("/opt/factor/bin/python")
    assert first != second


def test_runtime_probe_failure_disables_factor_cache(monkeypatch) -> None:
    from alphapilot.components.coder.factor_coder import factor as factor_module

    monkeypatch.setattr(
        factor_module.subprocess,
        "check_output",
        Mock(side_effect=subprocess.CalledProcessError(1, ["python"])),
    )
    warning = Mock()
    monkeypatch.setattr(factor_module.logger, "warning", warning)

    assert factor_module._factor_runtime_fingerprint("/missing/python") is None
    assert "pickle cache disabled" in warning.call_args.args[0]


def test_factor_cache_key_binds_data_source_python_and_runtime(monkeypatch) -> None:
    from alphapilot.components.coder.factor_coder import factor as factor_module

    workspace = _workspace_for_hash(factor_module)
    monkeypatch.setattr(factor_module, "resolve_factor_python_bin", lambda: "/python-a")
    monkeypatch.setattr(
        factor_module,
        "resolve_factor_data_fingerprint",
        lambda _workspace: "data-a",
    )
    monkeypatch.setattr(
        factor_module,
        "_factor_runtime_fingerprint",
        lambda _python_bin: "runtime-a",
    )

    baseline = workspace.hash_func()
    workspace.code_dict["factor.py"] = "expr = '$open'\n"
    assert workspace.hash_func() != baseline

    workspace.code_dict["factor.py"] = "expr = '$close'\n"
    monkeypatch.setattr(
        factor_module,
        "_factor_runtime_fingerprint",
        lambda _python_bin: "runtime-b",
    )
    assert workspace.hash_func() != baseline

    monkeypatch.setattr(
        factor_module,
        "_factor_runtime_fingerprint",
        lambda _python_bin: None,
    )
    assert workspace.hash_func() is None
