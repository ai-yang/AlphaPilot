"""Pydantic schema for qlib qrun YAML parameters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from alphapilot.systems.data.frequency import get_frequency

BASELINE_FEATURES = [
    "($close-$open)/$open",
    "$volume/Mean($volume, 20)",
    "($high-$low)/Ref($close, 1)",
    "$close/Ref($close, 1)-1",
]

COMBINED_FEATURES = [
    "($close - $open) / $open",
    "$close / Ref($close, 1) - 1",
    "$volume / Mean($volume, 20)",
    "($high - $low) / Ref($close, 1)",
]


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d")


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class QlibYamlParams(BaseModel):
    """Structured parameters rendered into qlib qrun YAML templates."""

    template_type: Literal["baseline", "combined"] = "baseline"
    # Bar frequency: "day" (default, unchanged behavior) or intraday 5/15/30/60min.
    freq: str = "day"
    provider_uri: str = "~/.qlib/qlib_data/cn_data"
    region: str = "cn"
    market: str = "main_stock_2026_4_27"
    benchmark: str = "SH000905"
    start_time: str = "2017-01-01"
    end_time: str = "2026-05-22"
    feature_expressions: list[str] = Field(default_factory=lambda: list(BASELINE_FEATURES))
    label_expression: str = "Ref($close, -2)/Ref($close, -1) - 1"
    static_pkl_name: str = "combined_factors_df.pkl"
    include_static_factors: bool = True
    include_executor: bool = True

    train_start: str = "2017-01-01"
    train_end: str = "2022-12-31"
    valid_start: str = "2023-01-01"
    valid_end: str = "2023-12-31"
    test_start: str = "2024-01-01"
    test_end: str = "2026-05-22"

    loss: str = "mse"
    colsample_bytree: float = 0.8879
    learning_rate: float = 0.1
    subsample: float = 0.8789
    lambda_l1: float = 205.6999
    lambda_l2: float = 580.9768
    max_depth: int = 4
    num_leaves: int = 210
    num_threads: int = 20

    # Model class is configurable; ``model_kwargs`` (when non-empty) overrides the
    # LGBM scalar fields above so non-LGBM / custom models can be plugged in.
    model_class: str = "LGBModel"
    model_module: str = "qlib.contrib.model.gbdt"
    model_kwargs: dict[str, Any] = Field(default_factory=dict)

    topk: int = 15
    n_drop: int = 5
    hold_thresh: int = 1
    risk_degree: float = 0.90

    # Trading/rebalancing strategy is configurable; ``strategy_kwargs`` (when
    # non-empty) overrides the topk/n_drop scalars so custom strategies can be used.
    strategy_class: str = "TopkDropoutStrategy"
    strategy_module: str = "qlib.contrib.strategy"
    strategy_kwargs: dict[str, Any] = Field(default_factory=dict)

    backtest_start: str = "2024-01-01"
    backtest_end: str = "2026-05-22"
    account: float = 50000
    limit_threshold: float = 0.095
    open_cost: float = 0.0002
    close_cost: float = 0.0008
    min_cost: float = 5
    # Board-lot size for trading. A-shares trade in lots of 100. Consumed by the daily-trade
    # rebalance (``live/rebalance.py``) to constrain buy/sell to whole lots; ``0`` disables it.
    # NOTE: the qrun backtest/mining templates (conf*.yaml.j2) do NOT reference this field, so it
    # is inert for factor mining / factor backtest — only the daily-trade path reads it.
    trade_unit: int = 100

    ann_scaler: int = 252
    ana_long_short: bool = False

    # Record toggles. ``single_ic`` style runs can disable the (expensive) portfolio
    # simulation by setting ``enable_port_ana_record=False``.
    enable_signal_record: bool = True
    enable_sig_ana_record: bool = True
    enable_port_ana_record: bool = True

    @field_validator(
        "start_time",
        "end_time",
        "train_start",
        "train_end",
        "valid_start",
        "valid_end",
        "test_start",
        "test_end",
        "backtest_start",
        "backtest_end",
    )
    @classmethod
    def validate_date_format(cls, value: str) -> str:
        _parse_date(value)
        return value

    @field_validator("freq")
    @classmethod
    def validate_freq(cls, value: str) -> str:
        # Normalize aliases ("5" -> "5min") and reject unsupported frequencies early.
        return get_frequency(value).key

    @model_validator(mode="after")
    def apply_freq_defaults(self) -> "QlibYamlParams":
        """Derive the intraday annualization scaler unless explicitly overridden.

        ``ann_scaler`` keeps its daily default (252) for ``freq="day"`` so rendered
        daily YAML is byte-identical to before. For an intraday freq, when the value
        is still the daily default we replace it with ``252 * bars_per_day``; an
        explicit non-252 value (e.g. from an LLM patch) is always respected.
        """
        spec = get_frequency(self.freq)
        if spec.is_intraday and self.ann_scaler == 252:
            self.ann_scaler = spec.ann_scaler
        return self

    @property
    def time_per_step(self) -> str:
        """Qlib executor ``time_per_step`` for this frequency (day -> "day")."""
        return get_frequency(self.freq).time_per_step

    @model_validator(mode="after")
    def validate_segment_order(self) -> "QlibYamlParams":
        if _parse_date(self.train_end) >= _parse_date(self.valid_start):
            raise ValueError("train_end must be before valid_start")
        if _parse_date(self.valid_end) >= _parse_date(self.test_start):
            raise ValueError("valid_end must be before test_start")
        if _parse_date(self.backtest_start) < _parse_date(self.test_start):
            raise ValueError("backtest_start must be within or after test_start")
        if _parse_date(self.backtest_end) > _parse_date(self.test_end):
            raise ValueError("backtest_end must not exceed test_end")
        if not self.feature_expressions:
            raise ValueError("feature_expressions must not be empty")
        return self

    @classmethod
    def defaults_for(cls, template_type: Literal["baseline", "combined"]) -> "QlibYamlParams":
        if template_type == "combined":
            return cls(
                template_type="combined",
                include_executor=False,
                feature_expressions=list(COMBINED_FEATURES),
            )
        return cls(template_type="baseline", include_executor=True, feature_expressions=list(BASELINE_FEATURES))

    @classmethod
    def merge_patch(cls, base: "QlibYamlParams", patch: dict[str, Any]) -> "QlibYamlParams":
        merged = _deep_merge(base.model_dump(), patch)
        return cls.model_validate(merged)

    @property
    def effective_model_kwargs(self) -> dict[str, Any]:
        """Model kwargs rendered into the template.

        When ``model_kwargs`` is provided it is used verbatim (custom / non-LGBM
        models); otherwise the LGBM scalar fields reproduce today's behavior.
        """
        if self.model_kwargs:
            return dict(self.model_kwargs)
        return {
            "loss": self.loss,
            "colsample_bytree": self.colsample_bytree,
            "learning_rate": self.learning_rate,
            "subsample": self.subsample,
            "lambda_l1": self.lambda_l1,
            "lambda_l2": self.lambda_l2,
            "max_depth": self.max_depth,
            "num_leaves": self.num_leaves,
            "num_threads": self.num_threads,
        }

    @property
    def effective_strategy_kwargs(self) -> dict[str, Any]:
        """Strategy kwargs rendered into the template.

        When ``strategy_kwargs`` is provided it is used verbatim (custom strategy);
        otherwise the TopkDropout scalar fields reproduce today's behavior. ``<PRED>``
        is the qlib placeholder for the model prediction signal.
        """
        if self.strategy_kwargs:
            return dict(self.strategy_kwargs)
        return {
            "signal": "<PRED>",
            "topk": self.topk,
            "n_drop": self.n_drop,
            "hold_thresh": self.hold_thresh,
            "risk_degree": self.risk_degree,
        }

    def llm_schema_hint(self) -> dict[str, Any]:
        """JSON-schema-like hint for LLM patch generation."""
        return {
            "template_type": "baseline | combined",
            "freq": "string, bar frequency: day | 5min | 15min | 30min | 60min",
            "provider_uri": "string, qlib data root",
            "region": "string, e.g. cn",
            "market": "string, instruments pool name",
            "benchmark": "string, e.g. SH000905",
            "start_time": "YYYY-MM-DD",
            "end_time": "YYYY-MM-DD",
            "feature_expressions": ["list of qlib expression strings"],
            "label_expression": "qlib label expression string",
            "static_pkl_name": "filename for combined StaticDataLoader",
            "model_class": "string, qlib model class name (e.g. LGBModel)",
            "model_module": "string, python module path of the model class",
            "model_kwargs": "object, overrides scalar model hyperparams when set",
            "strategy_class": "string, qlib strategy class name (e.g. TopkDropoutStrategy)",
            "strategy_module": "string, python module path of the strategy class",
            "strategy_kwargs": "object, overrides scalar strategy params when set",
            "train_start": "YYYY-MM-DD",
            "train_end": "YYYY-MM-DD",
            "valid_start": "YYYY-MM-DD",
            "valid_end": "YYYY-MM-DD",
            "test_start": "YYYY-MM-DD",
            "test_end": "YYYY-MM-DD",
            "learning_rate": "float",
            "max_depth": "int",
            "num_leaves": "int",
            "topk": "int",
            "n_drop": "int",
            "hold_thresh": "int",
            "risk_degree": "float 0-1",
            "backtest_start": "YYYY-MM-DD",
            "backtest_end": "YYYY-MM-DD",
            "account": "float",
            "open_cost": "float",
            "close_cost": "float",
            "limit_threshold": "float",
            "trade_unit": "int (board-lot size, e.g. 100; 0 disables; daily-trade only)",
        }
