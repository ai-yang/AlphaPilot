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
from datetime import date
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


def _parse_iso_date(value: Any, name: str) -> str:
    """Validate and normalize one user-facing ISO calendar date."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty ISO date")
    normalized = value.strip()
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO date in YYYY-MM-DD form") from exc
    return parsed.isoformat()


def _validate_year(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer year")
    try:
        date(value, 1, 1)
    except ValueError as exc:
        raise ValueError(f"{name} must be a valid calendar year") from exc
    return value


@dataclass(frozen=True)
class TrainingSpec:
    """Normalized requested training interval.

    Exact dates are an all-or-nothing override of the legacy year-based API.
    Keeping the source explicit prevents ignored legacy values from leaking into
    run fingerprints or research metadata.
    """

    requested_start_date: str
    requested_end_date: str
    source: str

    def __post_init__(self) -> None:
        start = _parse_iso_date(self.requested_start_date, "requested_start_date")
        end = _parse_iso_date(self.requested_end_date, "requested_end_date")
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("training start date cannot exceed training end date")
        if self.source not in {"explicit_dates", "legacy_years"}:
            raise ValueError("training source must be explicit_dates or legacy_years")
        object.__setattr__(self, "requested_start_date", start)
        object.__setattr__(self, "requested_end_date", end)

    @classmethod
    def resolve(
        cls,
        *,
        train_start: int = 2010,
        train_end_year: int = 2020,
        train_start_date: str | None = None,
        train_end_date: str | None = None,
    ) -> "TrainingSpec":
        exact_dates_requested = train_start_date is not None or train_end_date is not None
        if exact_dates_requested:
            if train_start_date is None or train_end_date is None:
                raise ValueError(
                    "train_start_date and train_end_date must be provided together"
                )
            return cls(train_start_date, train_end_date, "explicit_dates")

        start_year = _validate_year(train_start, "train_start")
        end_year = _validate_year(train_end_year, "train_end_year")
        return cls(
            f"{start_year:04d}-01-01",
            f"{end_year:04d}-12-31",
            "legacy_years",
        )

    @property
    def requested_range(self) -> tuple[str, str]:
        return self.requested_start_date, self.requested_end_date


@dataclass(frozen=True)
class TargetSpec:
    """Normalized AlphaForge forward-return target contract."""

    horizon: int = 20
    price: str = "vwap"

    def __post_init__(self) -> None:
        if isinstance(self.horizon, bool) or not isinstance(self.horizon, int):
            raise ValueError("target_horizon must be an integer")
        if self.horizon < 1:
            raise ValueError("target_horizon must be a positive integer")
        if not isinstance(self.price, str) or not self.price.strip():
            raise ValueError("target_price must be one of: close, vwap")
        normalized_price = self.price.strip().lower()
        if normalized_price not in {"close", "vwap"}:
            raise ValueError("target_price must be one of: close, vwap")
        object.__setattr__(self, "price", normalized_price)

    @property
    def required_future_days(self) -> int:
        """Maximum positive offset read by the target expression."""

        return self.horizon + 1

    @property
    def qlib_expression(self) -> str:
        return (
            f"Ref(${self.price},-{self.required_future_days})/"
            f"Ref(${self.price},-1)-1"
        )

    def build_expression(self) -> Any:
        from alphagen.data.expression import Feature, Ref
        from alphagen_qlib.stock_data import FeatureType

        feature_type = FeatureType.CLOSE if self.price == "close" else FeatureType.VWAP
        price = Feature(feature_type)
        return Ref(price, -self.required_future_days) / Ref(price, -1) - 1


@dataclass(frozen=True)
class LoadedTrainingData:
    """StockData plus the requested and actually usable training contract."""

    data: Any
    training_spec: TrainingSpec
    target_spec: TargetSpec
    effective_start_date: str
    effective_end_date: str

    def __post_init__(self) -> None:
        start = _parse_iso_date(self.effective_start_date, "effective_start_date")
        end = _parse_iso_date(self.effective_end_date, "effective_end_date")
        if date.fromisoformat(start) > date.fromisoformat(end):
            raise ValueError("effective training start cannot exceed effective training end")
        object.__setattr__(self, "effective_start_date", start)
        object.__setattr__(self, "effective_end_date", end)

    def data_split_metadata(self) -> dict[str, Any]:
        """Describe only the split that AlphaForge actually loaded and used."""

        return {
            "train": {
                "requested": list(self.training_spec.requested_range),
                "effective": [self.effective_start_date, self.effective_end_date],
            }
        }


def get_train_data(
    context: "Context",
    *,
    training_spec: TrainingSpec,
    target_spec: TargetSpec,
    instruments: str = "csi300",
    freq: str = "day",
    device: Any = None,
    raw: bool = False,
    qlib_dir: str | None = None,
) -> LoadedTrainingData:
    """Load only the training slice used by all current AlphaForge miners.

    GP, RL, and AFF do not evaluate their ``valid``/``test`` ``StockData``
    objects during search.  Loading all six legacy slices for every independent
    seed multiplied Qlib I/O and GPU memory without changing the optimizer.
    """
    from alphapilot.modules.alphaforge.device import resolve_device

    dev = device if device is not None and not isinstance(device, str) else resolve_device(device)
    qdir = resolve_qlib_dir(context, qlib_dir)
    data = build_stock_data(
        qlib_dir=qdir,
        instruments=instruments,
        start_time=training_spec.requested_start_date,
        end_time=training_spec.requested_end_date,
        device=dev,
        freq=freq,
        raw=raw,
        max_future_days=target_spec.required_future_days,
    )
    return LoadedTrainingData(
        data=data,
        training_spec=training_spec,
        target_spec=target_spec,
        effective_start_date=data.effective_start_time,
        effective_end_date=data.effective_end_time,
    )


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


def default_target(
    target_horizon: int = 20,
    target_price: str = "vwap",
) -> Any:
    """Build an AlphaForge forward-return label without changing legacy defaults.

    AlphaForge aligns a decision at D with prices from D+1 through D+horizon;
    consequently the expression is ``Ref(price, -(horizon+1)) / Ref(price, -1) - 1``.
    """

    return TargetSpec(target_horizon, target_price).build_expression()
