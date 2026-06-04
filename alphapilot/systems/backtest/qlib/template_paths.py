"""Resolve qlib workspace template directories (yaml, read_exp_res.py)."""

from __future__ import annotations

from pathlib import Path

from alphapilot.kernel.paths import factor_qlib_templates_dir, remap_legacy_relative_path

_QLIB_DIR = Path(__file__).resolve().parent

DEFAULT_QLIB_FACTOR_TEMPLATE_DIR = _QLIB_DIR / "templates" / "factor_template"
DEFAULT_QLIB_MODEL_TEMPLATE_DIR = _QLIB_DIR / "templates" / "model_template"
DEFAULT_USER_QLIB_FACTOR_TEMPLATE_DIR = factor_qlib_templates_dir()


def resolve_qlib_template_dir(path: str | Path | None, *, default: Path | None = None) -> Path:
    """
    Resolve template folder for ``QlibFBWorkspace.inject_code_from_folder``.

    - ``None`` → ``default`` or built-in factor_template under this package
    - relative path → resolved against current working directory
    - absolute path → used as-is
    """
    if path is None or (isinstance(path, str) and not str(path).strip()):
        if default is not None:
            return default.resolve()
        if DEFAULT_USER_QLIB_FACTOR_TEMPLATE_DIR.is_dir():
            return DEFAULT_USER_QLIB_FACTOR_TEMPLATE_DIR
        return DEFAULT_QLIB_FACTOR_TEMPLATE_DIR.resolve()
    remapped = remap_legacy_relative_path(path)
    p = Path(remapped if remapped is not None else path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()
