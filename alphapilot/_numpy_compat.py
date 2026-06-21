"""NumPy 2.x compatibility shim.

This environment runs NumPy 2.x, but some pinned dependencies (notably the old
``dask`` that ``lightgbm`` pulls in) still reference attributes that were
*removed* in the NumPy 2.0 release. The references live at module import time
(e.g. ``@implements(np.round, np.round_)`` in ``dask/array/routines.py``), so a
plain ``import dask.array`` — triggered transitively by ``import lightgbm`` /
``model.predict`` during a qlib backtest — raises::

    AttributeError: `np.round_` was removed in the NumPy 2.0 release.
                    Use `np.round` instead.

``lightgbm`` guards its optional dask import with ``except ImportError`` only, so
this ``AttributeError`` is not swallowed and aborts the daily-signal / backtest
run.

We restore the removed aliases (only when missing, so NumPy 1.x is untouched)
*before* any of those libraries get imported. Importing this module is a no-op
on NumPy 1.x and idempotent on repeated imports.
"""

from __future__ import annotations


def apply() -> None:
    import numpy as np

    # Removed-in-2.0 name -> NumPy 2.x replacement object.
    removed_aliases: dict[str, str] = {
        "round_": "round",
        "product": "prod",
        "cumproduct": "cumprod",
        "sometrue": "any",
        "alltrue": "all",
        "float_": "float64",
        "complex_": "complex128",
        "unicode_": "str_",
        "string_": "bytes_",
        "in1d": "isin",
        "row_stack": "vstack",
        "NaN": "nan",
        "NAN": "nan",
        "infty": "inf",
        "Inf": "inf",
        "PINF": "inf",
    }

    for old, new in removed_aliases.items():
        if not hasattr(np, old) and hasattr(np, new):
            setattr(np, old, getattr(np, new))

    # ``np.NINF`` was the negative-infinity float constant (not a function alias).
    if not hasattr(np, "NINF"):
        np.NINF = -np.inf


apply()
