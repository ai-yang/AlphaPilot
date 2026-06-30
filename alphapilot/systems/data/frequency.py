"""Frequency abstraction: single source of truth for freq-dependent mappings.

Bar frequency was historically implicit ``"day"`` across the data download,
qlib conversion, and backtest config layers (magic values ``"d"`` / ``252`` /
``"1day"`` / ``time_per_step: day`` scattered around). ``FrequencySpec``
centralizes those mappings so the rest of the codebase only needs to thread a
single ``freq`` string and look the rest up here.

Supported keys: ``day`` plus baostock intraday bars ``5min/15min/30min/60min``
(baostock has no 1-minute bars; 1min would need a different source).
"""

from __future__ import annotations

from dataclasses import dataclass

#: A-share continuous trading session length in minutes (09:30-11:30 + 13:00-15:00).
_SESSION_MINUTES = 240
#: Trading days per year, the daily annualization scaler used by qlib's SigAnaRecord.
_TRADING_DAYS_PER_YEAR = 252

#: Daily baostock query fields (price + fundamentals), matching the existing CSV schema.
DAILY_CSV_FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,turn,"
    "tradestatus,pctChg,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
)
#: Minute baostock query fields. Intraday bars expose far fewer columns than daily
#: (no preclose/turn/pctChg/peTTM/...) and add an intraday ``time`` column.
MINUTE_CSV_FIELDS = "date,time,code,open,high,low,close,volume,amount,adjustflag"


@dataclass(frozen=True)
class FrequencySpec:
    """All frequency-dependent knobs for one bar frequency."""

    key: str  # canonical label: "day" | "5min" | "15min" | "30min" | "60min"
    baostock_code: str  # baostock ``frequency``: "d" | "5" | "15" | "30" | "60"
    qlib_freq: str  # qlib calendar/bin/loader freq name (== key)
    is_intraday: bool
    bars_per_day: int  # day=1; A-share 4h session: 5min=48, 15min=16, 30min=8, 60min=4
    qlib_dir_suffix: str  # "" for day; "_5min" ... for the per-freq qlib subdir layout
    time_per_step: str  # qlib executor ``time_per_step``: day="day", minute=key
    rebalance_tag: str  # qlib PortAnaRecord suffix: day="1day", minute=key (e.g. "5min")
    csv_fields: str  # baostock query field list for this frequency

    @property
    def ann_scaler(self) -> int:
        """Annualization scaler: daily 252; intraday 252 * bars_per_day."""
        return _TRADING_DAYS_PER_YEAR * self.bars_per_day


def _minute_spec(key: str, baostock_code: str, bars_per_day: int) -> FrequencySpec:
    return FrequencySpec(
        key=key,
        baostock_code=baostock_code,
        qlib_freq=key,
        is_intraday=True,
        bars_per_day=bars_per_day,
        qlib_dir_suffix=f"_{key}",
        time_per_step=key,
        rebalance_tag=key,
        csv_fields=MINUTE_CSV_FIELDS,
    )


FREQUENCIES: dict[str, FrequencySpec] = {
    "day": FrequencySpec(
        key="day",
        baostock_code="d",
        qlib_freq="day",
        is_intraday=False,
        bars_per_day=1,
        qlib_dir_suffix="",
        time_per_step="day",
        rebalance_tag="1day",
        csv_fields=DAILY_CSV_FIELDS,
    ),
    "5min": _minute_spec("5min", "5", _SESSION_MINUTES // 5),
    "15min": _minute_spec("15min", "15", _SESSION_MINUTES // 15),
    "30min": _minute_spec("30min", "30", _SESSION_MINUTES // 30),
    "60min": _minute_spec("60min", "60", _SESSION_MINUTES // 60),
}

#: Lenient aliases accepted from CLI / yaml so users need not memorize the canonical key.
_ALIASES: dict[str, str] = {
    "d": "day",
    "1d": "day",
    "daily": "day",
    "1day": "day",
    "5": "5min",
    "5m": "5min",
    "15": "15min",
    "15m": "15min",
    "30": "30min",
    "30m": "30min",
    "60": "60min",
    "60m": "60min",
    "1h": "60min",
    "hour": "60min",
}


def get_frequency(freq: "str | FrequencySpec | None" = None) -> FrequencySpec:
    """Resolve *freq* to a :class:`FrequencySpec`. ``None`` -> daily (current default)."""
    if isinstance(freq, FrequencySpec):
        return freq
    if freq is None:
        return FREQUENCIES["day"]
    key = str(freq).strip().lower()
    key = _ALIASES.get(key, key)
    if key not in FREQUENCIES:
        raise ValueError(
            f"Unsupported frequency {freq!r}. Supported: {sorted(FREQUENCIES)} "
            f"(aliases: {sorted(_ALIASES)})."
        )
    return FREQUENCIES[key]


def portfolio_artifact_names(freq: "str | FrequencySpec | None" = None) -> dict[str, str]:
    """Qlib ``PortAnaRecord`` artifact filenames for the given rebalance frequency.

    qlib normalizes the executor ``time_per_step`` into the file suffix: ``day`` ->
    ``report_normal_1day.pkl``; ``5min`` -> ``report_normal_5min.pkl``.
    """
    tag = get_frequency(freq).rebalance_tag
    return {
        "report": f"report_normal_{tag}.pkl",
        "positions": f"positions_normal_{tag}.pkl",
        "indicators": f"indicators_normal_{tag}.pkl",
    }
