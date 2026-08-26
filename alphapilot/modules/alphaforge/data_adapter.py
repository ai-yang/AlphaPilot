"""Build AlphaForge ``StockData`` from alphapilot's qlib data + resolved device.

AlphaForge's own loader (``gan/utils/data.py``) hardcodes a placeholder qlib
path and ``cuda:0``. Here we instead source the qlib provider directory from
``context.config.data.qlib_data_dir`` (the same data the rest of alphapilot
uses) and inject the device chosen by :func:`alphapilot.modules.alphaforge.device.resolve_device`.

``StockData`` accepts a qlib market name (e.g. ``"csi300"``) directly, so no
manual instrument enumeration is needed.

``raw`` controls AlphaForge's legacy OHLCV transformation only: daily OHLC is
multiplied by ``$factor`` and volume is divided by it. VWAP construction is a
separate, explicit :class:`VwapSpec`. The compatibility default is
``$amount/$volume``; callers that require factor-adjusted VWAP must opt in.
Any factor-dependent mode validates full market coverage before Qlib is
initialized and never silently downgrades to different price semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, List

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


def resolve_qlib_dir(context: "Context", override: Any = None) -> Any:
    """Qlib provider dir: explicit *override* else ``config.data.qlib_data_dir``."""
    if override is not None:
        return override
    return context.config.data.qlib_data_dir


@dataclass(frozen=True)
class VwapSpec:
    """Explicit Qlib expression used for AlphaForge's VWAP feature.

    ``amount_volume`` preserves the historical ``raw=False`` behavior.
    ``factor_adjusted_amount_volume`` opts into one, and only one, multiplication
    by the provider's daily ``$factor`` feature.
    """

    mode: str = "amount_volume"

    def __post_init__(self) -> None:
        if not isinstance(self.mode, str) or not self.mode.strip():
            raise ValueError(
                "vwap_mode must be amount_volume or factor_adjusted_amount_volume"
            )
        normalized = self.mode.strip().lower()
        if normalized not in {
            "amount_volume",
            "factor_adjusted_amount_volume",
        }:
            raise ValueError(
                "vwap_mode must be amount_volume or factor_adjusted_amount_volume"
            )
        object.__setattr__(self, "mode", normalized)

    @classmethod
    def resolve(cls, value: "VwapSpec | str | None" = None) -> "VwapSpec":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(value)
        raise ValueError(
            "vwap_mode must be amount_volume or factor_adjusted_amount_volume"
        )

    @property
    def requires_factor(self) -> bool:
        return self.mode == "factor_adjusted_amount_volume"

    @property
    def qlib_expression(self) -> str:
        base = "($amount/$volume)"
        return f"({base}*$factor)" if self.requires_factor else base


def _local_provider_root(qlib_dir: Any) -> Path:
    if not isinstance(qlib_dir, (str, Path)):
        raise ValueError(
            "factor-dependent AlphaForge data requires a local filesystem Qlib provider"
        )
    root = Path(qlib_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(
            "factor-dependent AlphaForge data requires an existing local Qlib provider: "
            f"{root}"
        )
    return root


def _provider_instruments(root: Path, instruments: str | List[str]) -> list[str]:
    if isinstance(instruments, str):
        normalized = instruments.strip()
        if not normalized:
            raise ValueError("instruments must not be empty")
        market_file = root / "instruments" / f"{normalized}.txt"
        if not market_file.is_file() and normalized.lower() != normalized:
            market_file = root / "instruments" / f"{normalized.lower()}.txt"
        if market_file.is_file():
            symbols = [
                line.split("\t", 1)[0].strip().lower()
                for line in market_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        elif (root / "features" / normalized.lower()).is_dir():
            # Qlib also accepts a single instrument instead of a market name.
            symbols = [normalized.lower()]
        else:
            raise ValueError(
                "cannot prove full $factor coverage: missing market instrument file "
                f"{market_file}"
            )
    elif isinstance(instruments, list):
        symbols = [
            symbol.strip().lower()
            for symbol in instruments
            if isinstance(symbol, str) and symbol.strip()
        ]
        if len(symbols) != len(instruments):
            raise ValueError("instruments must contain only non-empty strings")
    else:
        raise ValueError("instruments must be a market name or a list of symbols")
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        raise ValueError("cannot prove full $factor coverage for an empty universe")
    return symbols


def _require_full_factor_coverage(
    *,
    qlib_dir: Any,
    instruments: str | List[str],
    freq: str,
) -> None:
    normalized_freq = str(freq).strip().lower()
    if normalized_freq != "day":
        raise ValueError(
            "factor-dependent AlphaForge data is supported only for day frequency"
        )
    root = _local_provider_root(qlib_dir)
    symbols = _provider_instruments(root, instruments)
    feature_root = root / "features"
    directories = (
        {
            path.name.lower(): path
            for path in feature_root.iterdir()
            if path.is_dir()
        }
        if feature_root.is_dir()
        else {}
    )
    missing = [
        symbol
        for symbol in symbols
        if symbol not in directories
        or not (directories[symbol] / "factor.day.bin").is_file()
        or (directories[symbol] / "factor.day.bin").stat().st_size == 0
    ]
    if missing:
        preview = ", ".join(missing[:5])
        suffix = "" if len(missing) <= 5 else f" (+{len(missing) - 5} more)"
        raise ValueError(
            "Qlib provider does not have full $factor coverage; missing "
            f"{preview}{suffix}"
        )


def build_stock_data(
    *,
    qlib_dir: Any,
    instruments: str | List[str],
    start_time: str,
    end_time: str,
    device: Any,
    freq: str = "day",
    raw: bool = False,
    vwap_spec: VwapSpec | str | None = None,
    max_backtrack_days: int = 100,
    max_future_days: int = 30,
) -> Any:
    """Construct one validated :class:`StockData` slice.

    ``raw`` transforms non-VWAP OHLCV fields. ``vwap_spec`` independently
    resolves the VWAP expression. If either contract needs ``$factor``, complete
    daily factor coverage is proven before importing or initializing Qlib.
    """
    if not isinstance(raw, bool):
        raise ValueError("raw must be a boolean")
    normalized_freq = str(freq).strip().lower()
    resolved_vwap = VwapSpec.resolve(vwap_spec)
    if raw or resolved_vwap.requires_factor:
        _require_full_factor_coverage(
            qlib_dir=qlib_dir,
            instruments=instruments,
            freq=normalized_freq,
        )

    from alphagen_qlib.stock_data import StockData

    return StockData(
        instrument=instruments,
        start_time=start_time,
        end_time=end_time,
        max_backtrack_days=max_backtrack_days,
        max_future_days=max_future_days,
        device=device,
        raw=raw,
        vwap_expression=resolved_vwap.qlib_expression,
        qlib_path=qlib_dir,
        freq=normalized_freq,
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
    # Keep this field last and defaulted so legacy positional construction of
    # the five original fields remains source compatible.
    vwap_spec: VwapSpec = field(default_factory=VwapSpec)

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
    instruments: str | List[str] = "csi300",
    freq: str = "day",
    device: Any = None,
    raw: bool = False,
    vwap_spec: VwapSpec | str | None = None,
    qlib_dir: Any = None,
) -> LoadedTrainingData:
    """Load only the training slice used by all current AlphaForge miners.

    GP, RL, and AFF do not evaluate their ``valid``/``test`` ``StockData``
    objects during search.  Loading all six legacy slices for every independent
    seed multiplied Qlib I/O and GPU memory without changing the optimizer.
    """
    from alphapilot.modules.alphaforge.device import resolve_device

    dev = device if device is not None and not isinstance(device, str) else resolve_device(device)
    qdir = resolve_qlib_dir(context, qlib_dir)
    resolved_vwap = VwapSpec.resolve(vwap_spec)
    data = build_stock_data(
        qlib_dir=qdir,
        instruments=instruments,
        start_time=training_spec.requested_start_date,
        end_time=training_spec.requested_end_date,
        device=dev,
        freq=freq,
        raw=raw,
        vwap_spec=resolved_vwap,
        max_future_days=target_spec.required_future_days,
    )
    return LoadedTrainingData(
        data=data,
        training_spec=training_spec,
        target_spec=target_spec,
        vwap_spec=resolved_vwap,
        effective_start_date=data.effective_start_time,
        effective_end_date=data.effective_end_time,
    )


def get_data_splits(
    context: "Context",
    *,
    instruments: str | List[str] = "csi300",
    train_start: int = 2010,
    train_end_year: int = 2020,
    freq: str = "day",
    device: Any = None,
    raw: bool = False,
    vwap_mode: str = "amount_volume",
    qlib_dir: Any = None,
) -> DataSplits:
    """Load the year-based splits used by the AlphaForge miners.

    train = [train_start, train_end_year]; valid = train_end_year+1;
    test = train_end_year+2 (mirrors ``gan/utils/data.get_data_by_year``).
    """
    from alphapilot.modules.alphaforge.device import resolve_device

    dev = device if device is not None and not isinstance(device, str) else resolve_device(device)
    qdir = resolve_qlib_dir(context, qlib_dir)
    vwap_spec = VwapSpec(vwap_mode)
    valid_year = train_end_year + 1
    test_year = train_end_year + 2

    def slice_(start: str, end: str) -> Any:
        return build_stock_data(
            qlib_dir=qdir, instruments=instruments, start_time=start, end_time=end,
            device=dev, freq=freq, raw=raw, vwap_spec=vwap_spec,
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
