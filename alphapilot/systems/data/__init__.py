"""Data system: stock data download, conversion, and storage.

The package intentionally avoids eager imports. ``kernel.config`` imports
``systems.data.data_paths`` during startup; importing service/storage here would
pull ``kernel.config`` back in before ``DataConfig`` is defined.
"""

from __future__ import annotations

from typing import Any


_EXPORTS = {
    "BaseDataSystem": "alphapilot.systems.data.base",
    "DataActionCommand": "alphapilot.systems.data.types",
    "DataConvertCommand": "alphapilot.systems.data.types",
    "DataDownloadCommand": "alphapilot.systems.data.types",
    "DataPipelineCommand": "alphapilot.systems.data.types",
    "DataStorage": "alphapilot.systems.data.storage",
    "PrepareDataCLI": "alphapilot.systems.data.prepare_data",
    "QlibDataSystem": "alphapilot.systems.data.service",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    from importlib import import_module

    module = import_module(_EXPORTS[name])
    value = getattr(module, name)
    globals()[name] = value
    return value

__all__ = [
    "BaseDataSystem",
    "DataActionCommand",
    "DataConvertCommand",
    "DataDownloadCommand",
    "DataPipelineCommand",
    "DataStorage",
    "PrepareDataCLI",
    "QlibDataSystem",
]
