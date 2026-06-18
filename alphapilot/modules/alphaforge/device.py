"""Device resolution for the vendored torch code.

AlphaForge hardcodes ``cuda:0`` throughout (``StockData`` default device,
``train_AFF`` config, ``torch.cuda.empty_cache()`` calls). This dev machine is
macOS with no CUDA, so we centralise device selection here and thread the
resolved device through the miners/data adapter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    import torch


def use_fork_start_method() -> None:
    """Force the multiprocessing 'fork' start method.

    AlphaForge was written for Linux, where ``fork`` is the default. macOS (and
    Windows) default to ``spawn``, which re-imports the ``__main__`` module in
    every worker -- and qlib/joblib spawn worker pools during data loading, so
    under spawn each worker re-executes the caller and you get a fork-bomb /
    hang. Forcing ``fork`` (matching Linux) avoids that. Safe to call repeatedly.
    """
    import multiprocessing as mp
    import os

    # Avoid the macOS "fork after Objective-C init" abort in forked workers.
    os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
    try:
        if mp.get_start_method(allow_none=True) != "fork":
            mp.set_start_method("fork", force=True)
    except (RuntimeError, ValueError):  # not available on this platform
        pass


def resolve_device(pref: Union[str, "torch.device", None] = None) -> "torch.device":
    """Return a usable ``torch.device``.

    Resolution order: explicit *pref* > CUDA > Apple MPS > CPU. Importing
    torch is deferred so merely importing this module stays cheap.
    """
    import torch

    if pref is not None:
        return torch.device(pref)
    if torch.cuda.is_available():
        return torch.device("cuda:0")
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def empty_cache(device: "torch.device") -> None:
    """Free cached memory only when it makes sense for *device*.

    Replaces bare ``torch.cuda.empty_cache()`` calls so the code does not blow
    up on non-CUDA backends.
    """
    import torch

    if device.type == "cuda":
        torch.cuda.empty_cache()
    elif device.type == "mps" and hasattr(torch, "mps"):
        try:
            torch.mps.empty_cache()
        except Exception:  # noqa: BLE001 - best effort
            pass
