"""Shared base for the AlphaForge-derived mining modules.

This package is NOT a registered kernel module. It hosts:

* ``vendor/`` -- a near-verbatim copy of the AlphaForge / AlphaGen source
  subset that the two feature modules (``alphaforge_aff`` and
  ``alphaforge_search``) depend on. The vendored trees keep their original
  top-level package names (``alphagen``, ``alphagen_qlib``, ``alphagen_generic``,
  ``gan``, ``gplearn``, ``dso``) so their internal imports work unchanged --
  we put the single ``vendor/`` directory on ``sys.path`` instead of rewriting
  every import (keeps re-syncing from upstream cheap).
* the integration glue that maps AlphaForge's torch/Expression world onto
  alphapilot: :mod:`~alphapilot.modules.alphaforge.device`,
  :mod:`~alphapilot.modules.alphaforge.translate`,
  :mod:`~alphapilot.modules.alphaforge.data_adapter`,
  :mod:`~alphapilot.modules.alphaforge.pipeline`.

Importing this package is enough to make the vendored packages importable.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Absolute path to the directory that directly contains the vendored
# top-level packages (alphagen/, gan/, ...). Adding it to sys.path makes
# ``import alphagen`` resolve to the vendored copy.
VENDOR_ROOT = Path(__file__).resolve().parent / "vendor"


def _ensure_vendor_on_path() -> None:
    vendor = str(VENDOR_ROOT)
    if vendor not in sys.path:
        # insert at front so the vendored copy wins over any same-named
        # package that might be installed elsewhere.
        sys.path.insert(0, vendor)


_ensure_vendor_on_path()

__all__ = ["VENDOR_ROOT"]
