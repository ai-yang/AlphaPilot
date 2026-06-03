"""Resolve qlib workspace template directories (yaml/read_exp_res.py copies)."""

from __future__ import annotations

from pathlib import Path

_EXPERIMENT_DIR = Path(__file__).resolve().parent

DEFAULT_QLIB_FACTOR_TEMPLATE_DIR = _EXPERIMENT_DIR / "factor_template"
DEFAULT_QLIB_MODEL_TEMPLATE_DIR = _EXPERIMENT_DIR / "model_template"


def resolve_qlib_template_dir(path: str | Path | None, *, default: Path | None = None) -> Path:
    """
    Resolve template folder for ``QlibFBWorkspace.inject_code_from_folder``.

    - ``None`` → ``default`` or built-in factor_template
    - relative path → resolved against current working directory
    - absolute path → used as-is
    """
    if path is None or (isinstance(path, str) and not str(path).strip()):
        return (default or DEFAULT_QLIB_FACTOR_TEMPLATE_DIR).resolve()
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()
