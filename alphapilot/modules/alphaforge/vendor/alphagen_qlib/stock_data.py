from typing import List, Union, Optional, Tuple, Dict
from collections.abc import Mapping
from enum import IntEnum
import json
from pathlib import Path
import threading
import numpy as np
import pandas as pd
import torch


def _resolve_padded_calendar_range(
    cal: np.ndarray,
    start_time: str,
    end_time: str,
    max_backtrack_days: int,
    max_future_days: int,
) -> tuple[int, int]:
    """Return inclusive usable indices with full history/future padding."""
    for name, value in (
        ("max_backtrack_days", max_backtrack_days),
        ("max_future_days", max_future_days),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, np.integer))
            or value < 0
        ):
            raise ValueError(f"{name} must be a non-negative integer")
    if len(cal) == 0:
        raise ValueError("Qlib calendar is empty")
    calendar = pd.DatetimeIndex(cal)
    requested_start = int(calendar.searchsorted(pd.Timestamp(start_time), side="left"))
    requested_end = int(calendar.searchsorted(pd.Timestamp(end_time), side="right")) - 1
    start_index = max(requested_start, max_backtrack_days)
    end_index = min(requested_end, len(cal) - max_future_days - 1)
    if start_index > end_index:
        raise ValueError(
            "No usable Qlib dates remain after applying AlphaForge padding: "
            f"requested=[{start_time}, {end_time}], "
            f"calendar=[{cal[0]}, {cal[-1]}], "
            f"backtrack={max_backtrack_days}, future={max_future_days}"
        )
    return start_index, end_index

class FeatureType(IntEnum):
    OPEN = 0
    CLOSE = 1
    HIGH = 2
    LOW = 3
    VOLUME = 4
    VWAP = 5

def change_to_raw_min(features):
    """Apply legacy minute scaling to non-VWAP fields only."""
    result = []
    for feature in features:
        if feature in ['$vwap']:
            raise ValueError("VWAP must be supplied by the explicit vwap expression")
        elif feature in ['$volume']:
            result.append(f"{feature}/100000")
            # result.append('$close')
        else:
            result.append(feature)
    return result

def change_to_raw(features):
    """Apply legacy daily factor adjustment to non-VWAP OHLCV fields."""
    result = []
    for feature in features:
        if feature in ['$open','$close','$high','$low']:
            result.append(f"{feature}*$factor")
        elif feature in ['$vwap']:
            raise ValueError("VWAP must be supplied by the explicit vwap expression")
        elif feature in ['$volume']:
            result.append(f"{feature}/$factor/1000000")
            # result.append('$close')
        else:
            raise ValueError(f"feature {feature} not supported")
    return result

class StockData:
    _qlib_provider_identity: str | None = None
    _qlib_init_lock = threading.RLock()

    def __init__(self,
                 instrument: Union[str, List[str]],
                 start_time: str,
                 end_time: str,
                 max_backtrack_days: int = 100,
                 max_future_days: int = 30,
                 features: Optional[List[FeatureType]] = None,
                 device: torch.device = torch.device('cuda:0'),
                 raw:bool = False,
                 vwap_expression:str = '($amount/$volume)',
                 qlib_path:Union[str,Dict] = "",
                 freq:str = 'day',
                 ) -> None:
        if raw and freq != 'day':
            raise ValueError("raw=True AlphaForge data is supported only for day frequency")
        if not isinstance(vwap_expression, str) or not vwap_expression.strip():
            raise ValueError("vwap_expression must be a non-empty Qlib expression")
        self._init_qlib(qlib_path)
        self.df_bak = None
        self.raw = raw
        self.vwap_expression = vwap_expression.strip()
        self._instrument = instrument
        self.max_backtrack_days = max_backtrack_days
        self.max_future_days = max_future_days
        self._start_time = start_time
        self._end_time = end_time
        self._effective_start_time: Optional[str] = None
        self._effective_end_time: Optional[str] = None
        self._features = features if features is not None else list(FeatureType)
        self.device = device
        self.freq = freq
        self.data, self._dates, self._stock_ids = self._get_data()


    @classmethod
    def _provider_identity(cls, qlib_path) -> str:
        if isinstance(qlib_path, (str, Path)):
            return f"path:{Path(qlib_path).expanduser().resolve()}"
        if isinstance(qlib_path, Mapping):
            payload = json.dumps(
                dict(qlib_path),
                sort_keys=True,
                separators=(',', ':'),
                default=str,
            )
            return f"mapping:{payload}"
        return f"{type(qlib_path).__module__}.{type(qlib_path).__qualname__}:{qlib_path!r}"

    @classmethod
    def _init_qlib(cls,qlib_path) -> None:
        identity = cls._provider_identity(qlib_path)
        with cls._qlib_init_lock:
            if cls._qlib_provider_identity == identity:
                return
            import qlib
            from qlib.config import REG_CN
            qlib.init(provider_uri=qlib_path, region=REG_CN)
            cls._qlib_provider_identity = identity

    def _load_exprs(self, exprs: Union[str, List[str]]) -> pd.DataFrame:
        # This evaluates an expression on the data and returns the dataframe
        # It might throw on illegal expressions like "Ref(constant, dtime)"
        from qlib.data.dataset.loader import QlibDataLoader
        from qlib.data import D
        if not isinstance(exprs, list):
            exprs = [exprs]
        cal: np.ndarray = D.calendar(freq=self.freq)
        # AlphaForge evaluates expressions with fixed history/future padding.  The
        # original implementation indexed the calendar directly and therefore
        # wrapped a request before the first date (``cal[-100]``) or overflowed a
        # request near the final date.  Clamp the *usable* research interval to
        # dates for which the full padding exists instead.  This also lets a
        # generic request such as 2010..2023 run on a provider that starts in 2017.
        start_index, end_index = _resolve_padded_calendar_range(
            cal,
            self._start_time,
            self._end_time,
            self.max_backtrack_days,
            self.max_future_days,
        )
        effective_start = pd.Timestamp(cal[start_index])
        effective_end = pd.Timestamp(cal[end_index])
        # AlphaForge's public training contract is date-based even when the
        # provider calendar is intraday.  Preserve that contract in metadata;
        # the tensor itself still retains the full timestamp index in ``_dates``.
        self._effective_start_time = effective_start.date().isoformat()
        self._effective_end_time = effective_end.date().isoformat()

        real_start_time = cal[start_index - self.max_backtrack_days]
        real_end_time = cal[end_index + self.max_future_days]
        result =  (QlibDataLoader(config=exprs,freq=self.freq)  # type: ignore
                .load(self._instrument, real_start_time, real_end_time))
        return result

    def _get_data(self) -> Tuple[torch.Tensor, pd.Index, pd.Index]:
        # VWAP is already resolved and validated by the public data adapter.
        # ``raw`` remains solely responsible for transforming other OHLCV
        # fields, so factor-adjusted VWAP can never be multiplied twice here.
        features = []
        for feature_type in self._features:
            feature = '$' + feature_type.name.lower()
            if feature_type == FeatureType.VWAP:
                features.append(self.vwap_expression)
            elif self.raw:
                features.extend(change_to_raw([feature]))
            else:
                features.append(feature)
        df = self._load_exprs(features)
        self.df_bak = df
        # print(df)
        df = df.stack().unstack(level=1)
        dates = df.index.levels[0]                                      # type: ignore
        stock_ids = df.columns
        values = df.values
        values = values.reshape((-1, len(features), values.shape[-1]))  # type: ignore
        return torch.tensor(values, dtype=torch.float, device=self.device), dates, stock_ids

    @property
    def n_features(self) -> int:
        return len(self._features)

    @property
    def n_stocks(self) -> int:
        return self.data.shape[-1]

    @property
    def n_days(self) -> int:
        return self.data.shape[0] - self.max_backtrack_days - self.max_future_days

    @property
    def effective_start_time(self) -> str:
        if self._effective_start_time is None:
            raise RuntimeError("StockData has not resolved its effective calendar range")
        return self._effective_start_time

    @property
    def effective_end_time(self) -> str:
        if self._effective_end_time is None:
            raise RuntimeError("StockData has not resolved its effective calendar range")
        return self._effective_end_time

    def add_data(self,data:torch.Tensor,dates:pd.Index):
        data = data.to(self.device)
        self.data = torch.cat([self.data,data],dim=0)
        self._dates = pd.Index(self._dates.append(dates))


    def make_dataframe(
        self,
        data: Union[torch.Tensor, List[torch.Tensor]],
        columns: Optional[List[str]] = None
    ) -> pd.DataFrame:
        """
            Parameters:
            - `data`: a tensor of size `(n_days, n_stocks[, n_columns])`, or
            a list of tensors of size `(n_days, n_stocks)`
            - `columns`: an optional list of column names
            """
        if isinstance(data, list):
            data = torch.stack(data, dim=2)
        if len(data.shape) == 2:
            data = data.unsqueeze(2)
        if columns is None:
            columns = [str(i) for i in range(data.shape[2])]
        n_days, n_stocks, n_columns = data.shape
        if self.n_days != n_days:
            raise ValueError(f"number of days in the provided tensor ({n_days}) doesn't "
                             f"match that of the current StockData ({self.n_days})")
        if self.n_stocks != n_stocks:
            raise ValueError(f"number of stocks in the provided tensor ({n_stocks}) doesn't "
                             f"match that of the current StockData ({self.n_stocks})")
        if len(columns) != n_columns:
            raise ValueError(f"size of columns ({len(columns)}) doesn't match with "
                             f"tensor feature count ({data.shape[2]})")
        if self.max_future_days == 0:
            date_index = self._dates[self.max_backtrack_days:]
        else:
            date_index = self._dates[self.max_backtrack_days:-self.max_future_days]
        index = pd.MultiIndex.from_product([date_index, self._stock_ids])
        data = data.reshape(-1, n_columns)
        return pd.DataFrame(data.detach().cpu().numpy(), index=index, columns=columns)
