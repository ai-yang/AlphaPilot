"""PDF factor loader bridge for factor system.

The default implementation path is configurable so system layer does not
hardcode module-internal class imports.
"""

from __future__ import annotations

import os
from importlib import import_module
from typing import Any

from alphapilot.components.loader.experiment_loader import FactorExperimentLoader

DEFAULT_FACTOR_PDF_LOADER_CLASS = (
    "alphapilot.modules.alpha_mining.qlib.factor_experiment_loader.pdf_loader.FactorExperimentLoaderFromPDFfiles"
)


def _resolve_pdf_loader_class() -> type:
    class_path = os.getenv("ALPHAPILOT_FACTOR_PDF_LOADER_CLASS", DEFAULT_FACTOR_PDF_LOADER_CLASS)
    module_path, class_name = class_path.rsplit(".", 1)
    return getattr(import_module(module_path), class_name)


class FactorExperimentLoaderFromPDFfiles(FactorExperimentLoader):
    """Delegating PDF loader with configurable concrete implementation."""

    def load(self, file_or_folder_path: str) -> Any:
        loader_cls = _resolve_pdf_loader_class()
        return loader_cls().load(file_or_folder_path)
