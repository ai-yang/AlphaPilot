"""Pydantic schema for qlib qrun YAML parameters."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

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

    topk: int = 15
    n_drop: int = 5
    hold_thresh: int = 1
    risk_degree: float = 0.90

    backtest_start: str = "2024-01-01"
    backtest_end: str = "2026-05-22"
    account: float = 50000
    limit_threshold: float = 0.095
    open_cost: float = 0.0002
    close_cost: float = 0.0008
    min_cost: float = 5

    ann_scaler: int = 252
    ana_long_short: bool = False

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

    def llm_schema_hint(self) -> dict[str, Any]:
        """JSON-schema-like hint for LLM patch generation."""
        return {
            "template_type": "baseline | combined",
            "provider_uri": "string, qlib data root",
            "region": "string, e.g. cn",
            "market": "string, instruments pool name",
            "benchmark": "string, e.g. SH000905",
            "start_time": "YYYY-MM-DD",
            "end_time": "YYYY-MM-DD",
            "feature_expressions": ["list of qlib expression strings"],
            "label_expression": "qlib label expression string",
            "static_pkl_name": "filename for combined StaticDataLoader",
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
        }
