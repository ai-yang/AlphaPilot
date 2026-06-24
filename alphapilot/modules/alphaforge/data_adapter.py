"""Build AlphaForge ``StockData`` from alphapilot's qlib data + resolved device.

AlphaForge's own loader (``gan/utils/data.py``) hardcodes a placeholder qlib
path and ``cuda:0``. Here we instead source the qlib provider directory from
``context.config.data.qlib_data_dir`` (the same data the rest of alphapilot
uses) and inject the device chosen by :func:`alphapilot.modules.alphaforge.device.resolve_device`.

``StockData`` accepts a qlib market name (e.g. ``"csi300"``) directly, so no
manual instrument enumeration is needed.

Note on ``raw``: AlphaForge sets ``raw=True``, which rewrites features as
``$close*$factor`` etc. and therefore requires a ``$factor`` field in the qlib
dump. alphapilot's baostock dump may not provide it, so ``raw`` defaults to
False here (prices used as stored). Flip it on only if your qlib data carries
adjustment factors. ``build_stock_data`` now probes the dump for ``$factor`` and
auto-downgrades ``raw=True -> False`` (with a warning) when it is absent, so a
missing-field load no longer crashes with an empty-reshape error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def resolve_qlib_dir(context: "Context", override: str | None = None) -> str:
    """Qlib provider dir: explicit *override* else ``config.data.qlib_data_dir``."""
    if override:
        return str(override)
    return str(context.config.data.qlib_data_dir)


def _qlib_dump_has_factor(qlib_dir: str, freq: str) -> bool:
    """Whether the qlib dump carries a ``$factor`` field (adjustment factor).

    ``raw=True`` rewrites every feature to reference ``$factor``; on a dump without
    it (e.g. alphapilot's baostock day dump) qlib returns an empty frame and
    ``StockData`` crashes on reshape. ``any(glob)`` short-circuits on the first hit.
    """
    from pathlib import Path

    feat_root = Path(qlib_dir).expanduser() / "features"
    return feat_root.exists() and any(feat_root.glob(f"*/factor.{freq}.bin"))


def build_stock_data(
    *,
    qlib_dir: str,
    instruments: str,
    start_time: str,
    end_time: str,
    device: Any,
    freq: str = "day",
    raw: bool = False,
    max_backtrack_days: int = 100,
    max_future_days: int = 30,
) -> Any:
    """Construct one :class:`StockData` slice on *device* from the qlib dir."""
    from alphagen_qlib.stock_data import StockData

    if raw and not _qlib_dump_has_factor(qlib_dir, freq):
        from alphapilot.log import logger

        logger.warning(
            f"[alphaforge] raw=True requested but qlib dump at {qlib_dir} has no '$factor' "
            f"field ({freq}); falling back to raw=False (prices used as stored). Otherwise the "
            "factor-rewritten features load empty and StockData crashes on reshape."
        )
        raw = False

    return StockData(
        instrument=instruments,
        start_time=start_time,
        end_time=end_time,
        max_backtrack_days=max_backtrack_days,
        max_future_days=max_future_days,
        device=device,
        raw=raw,
        qlib_path=qlib_dir,
        freq=freq,
    )


@dataclass
class DataSplits:
    """Train / valid / test ``StockData`` slices (AlphaForge convention).

    ``*_withhead`` slices prepend two extra years so rolling operators have
    lookback at the start of the eval window.
    """

    data_all: Any
    train: Any
    valid: Any
    valid_withhead: Any
    test: Any
    test_withhead: Any


def get_data_splits(
    context: "Context",
    *,
    instruments: str = "csi300",
    train_start: int = 2010,
    train_end_year: int = 2020,
    freq: str = "day",
    device: Any = None,
    raw: bool = False,
    qlib_dir: str | None = None,
) -> DataSplits:
    """Load the year-based splits used by the AlphaForge miners.

    train = [train_start, train_end_year]; valid = train_end_year+1;
    test = train_end_year+2 (mirrors ``gan/utils/data.get_data_by_year``).
    """
    from alphapilot.modules.alphaforge.device import resolve_device

    dev = device if device is not None and not isinstance(device, str) else resolve_device(device)
    qdir = resolve_qlib_dir(context, qlib_dir)
    valid_year = train_end_year + 1
    test_year = train_end_year + 2

    def slice_(start: str, end: str) -> Any:
        return build_stock_data(
            qlib_dir=qdir, instruments=instruments, start_time=start, end_time=end,
            device=dev, freq=freq, raw=raw,
        )

    return DataSplits(
        data_all=slice_(f"{train_start}-01-01", f"{test_year}-12-31"),
        train=slice_(f"{train_start}-01-01", f"{train_end_year}-12-31"),
        valid=slice_(f"{valid_year}-01-01", f"{valid_year}-12-31"),
        valid_withhead=slice_(f"{valid_year - 2}-01-01", f"{valid_year}-12-31"),
        test=slice_(f"{test_year}-01-01", f"{test_year}-12-31"),
        test_withhead=slice_(f"{test_year - 2}-01-01", f"{test_year}-12-31"),
    )


def default_target() -> Any:
    """The default forward-return label used by AlphaForge."""
    from alphagen_generic.features import target

    return target
