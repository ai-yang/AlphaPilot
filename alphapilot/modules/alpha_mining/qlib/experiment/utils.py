"""Compatibility re-exports; implementation lives in ``components.coder.factor_coder.data``."""

from alphapilot.components.coder.factor_coder.data import (
    ensure_factor_data,
    generate_data_folder_from_qlib,
    get_data_folder_intro,
    get_file_desc,
)

__all__ = [
    "ensure_factor_data",
    "generate_data_folder_from_qlib",
    "get_data_folder_intro",
    "get_file_desc",
]
