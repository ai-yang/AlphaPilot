"""Version 1 request/response schemas. No executable paths or free-form kwargs."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

ID = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^/\\\x00]+$")]
Name = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[\w-]+$")]
Expression = Annotated[str, Field(min_length=1, max_length=20000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class BacktestOptions(StrictModel):
    benchmark: str | None = None
    start_time: date | None = None
    end_time: date | None = None
    train_start: date | None = None
    train_end: date | None = None
    valid_start: date | None = None
    valid_end: date | None = None
    test_start: date | None = None
    test_end: date | None = None
    backtest_start: date | None = None
    backtest_end: date | None = None
    topk: int | None = Field(None, ge=1, le=10000)
    n_drop: int | None = Field(None, ge=0, le=10000)
    hold_thresh: int | None = Field(None, ge=0)
    risk_degree: float | None = Field(None, ge=0, le=1)
    account: float | None = Field(None, gt=0)
    open_cost: float | None = Field(None, ge=0, le=1)
    close_cost: float | None = Field(None, ge=0, le=1)
    min_cost: float | None = Field(None, ge=0)
    trade_unit: int | None = Field(None, ge=0)
    limit_threshold: float | None = Field(None, ge=0, le=1)
    learning_rate: float | None = Field(None, gt=0, le=1)
    max_depth: int | None = Field(None, ge=-1, le=100)
    num_leaves: int | None = Field(None, ge=2, le=10000)
    num_threads: int | None = Field(None, ge=1, le=256)
    colsample_bytree: float | None = Field(None, gt=0, le=1)
    subsample: float | None = Field(None, gt=0, le=1)
    lambda_l1: float | None = Field(None, ge=0)
    lambda_l2: float | None = Field(None, ge=0)
    ann_scaler: int | None = Field(None, ge=1)
    ana_long_short: bool | None = None
    enable_signal_record: bool | None = None
    enable_sig_ana_record: bool | None = None
    enable_port_ana_record: bool | None = None

    @model_validator(mode="after")
    def date_ranges(self):
        for start, end in (("start_time", "end_time"), ("train_start", "train_end"),
                           ("valid_start", "valid_end"), ("test_start", "test_end"),
                           ("backtest_start", "backtest_end")):
            if getattr(self, start) and getattr(self, end) and getattr(self, start) > getattr(self, end):
                raise ValueError(f"{start} must not exceed {end}")
        return self


class DatasetInput(StrictModel):
    dataset_id: ID
    stock_pool_id: ID | None = None
    template_id: ID = "combined"
    model_id: ID = "lgbm"
    parameters: BacktestOptions = Field(default_factory=BacktestOptions)


class FactorExpression(StrictModel):
    name: Name
    expression: str = Field(min_length=1, max_length=20000)


class LibraryFactors(StrictModel):
    type: Literal["library"]
    factor_ids: list[ID] = Field(min_length=1, max_length=1000)


class InlineFactors(StrictModel):
    type: Literal["inline"]
    factors: list[FactorExpression] = Field(min_length=1, max_length=1000)


FactorSource = Annotated[Union[LibraryFactors, InlineFactors], Field(discriminator="type")]


class FactorBacktestInput(DatasetInput):
    factor_source: FactorSource
    mode: Literal["single_ic", "multi_combined", "multi_sequential"] = "single_ic"


class MiningInput(DatasetInput):
    max_steps: int = Field(ge=1, le=100000)
    direction: str | None = Field(None, max_length=20000)
    save_factors_to_library: bool = False
    random_seed: int | None = None
    campaign_id: str | None = Field(None, max_length=200)
    resume_run_id: ID | None = None


class FormulaMiningInput(DatasetInput):
    train_end_year: int = Field(2020, ge=1990, le=2200)
    train_start_date: date | None = None
    train_end_date: date | None = None
    seed: int = 0
    target_horizon: int = Field(20, ge=1, le=10000)
    target_price: Literal["close", "vwap"] = "vwap"
    vwap_mode: Literal["amount_volume", "factor_adjusted_amount_volume"] = "amount_volume"
    device: Literal["cpu", "cuda"] | None = None
    backtest: bool = False
    save: bool = False
    raw: bool = False


class AFFInput(FormulaMiningInput):
    max_loops: int = Field(ge=1, le=100000)
    zoo_size: int = Field(100, ge=1, le=10000)
    corr_thresh: float = Field(.7, ge=0, le=1)
    ic_thresh: float = Field(.03, ge=0, le=1)
    icir_thresh: float = Field(.1, ge=0)
    max_len: int = Field(20, ge=1, le=200)
    batch_size: int = Field(256, ge=1, le=65536)
    num_epochs_g: int = Field(200, ge=1, le=100000)
    num_epochs_p: int = Field(100, ge=1, le=100000)


class GPInput(FormulaMiningInput):
    population_size: int = Field(100, ge=2, le=100000)
    generations: int = Field(20, ge=1, le=100000)
    tournament_size: int = Field(20, ge=2, le=100000)
    top_n: int = Field(50, ge=1, le=10000)


class RLInput(FormulaMiningInput):
    steps: int = Field(200000, ge=1, le=10000000)
    pool_capacity: int = Field(10, ge=1, le=10000)


class StrategyBacktestInput(DatasetInput):
    strategy_id: ID
    mode: Literal["retrain", "reuse_model"] = "retrain"
    save_as: Name | None = None


class DataBase(StrictModel):
    dataset_id: ID


class DataDownload(DataBase):
    action: Literal["download", "update", "pipeline"]
    start_date: date = date(2005, 1, 1)
    end_date: date | None = None
    symbols: list[str] | None = Field(None, max_length=20000)
    stock_pool_id: ID | None = None
    workers: int = Field(1, ge=1, le=64)
    include_daily_basic: bool = True
    include_delisted: bool = False

    @model_validator(mode="after")
    def dates(self):
        if self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not exceed end_date")
        if self.symbols is not None and self.stock_pool_id is not None:
            raise ValueError("symbols and stock_pool_id are mutually exclusive")
        return self


class DataConvert(DataBase):
    action: Literal["convert"]
    stock_pool_id: ID | None = None


class DataAdjust(DataBase):
    action: Literal["apply_adjust"]


class DataDelete(DataBase):
    action: Literal["delete_symbol"]
    symbol: str = Field(min_length=1, max_length=32)
    dry_run: bool = False


class DataRefresh(DataBase):
    action: Literal["refresh_symbol"]
    symbol: str = Field(min_length=1, max_length=32)
    start_date: date = date(2005, 1, 1)
    end_date: date | None = None

    @model_validator(mode="after")
    def dates(self):
        if self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not exceed end_date")
        return self


class DataTrim(DataBase):
    action: Literal["trim_symbol"]
    symbol: str = Field(min_length=1, max_length=32)
    start_date: date | None = None
    end_date: date | None = None
    drop_dates: list[date] = Field(default_factory=list, max_length=10000)
    dry_run: bool = False

    @model_validator(mode="after")
    def dates(self):
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not exceed end_date")
        if not (self.start_date or self.end_date or self.drop_dates):
            raise ValueError("A date boundary or drop_dates is required")
        return self


class DataAdjustSymbol(DataBase):
    action: Literal["apply_adjust_symbol"]
    symbol: str = Field(min_length=1, max_length=32)
    dry_run: bool = False


DataInput = Annotated[Union[DataDownload, DataConvert, DataAdjust, DataDelete, DataRefresh, DataTrim, DataAdjustSymbol], Field(discriminator="action")]


class DailyInput(DatasetInput):
    mode: Literal["preview", "advance"]
    session_id: ID | None = None
    strategy_id: ID | None = None
    date: date
    init_cash: float | None = Field(None, gt=0)
    refresh_data: bool = False

    @model_validator(mode="after")
    def source(self):
        if bool(self.session_id) == bool(self.strategy_id):
            raise ValueError("Exactly one session_id or strategy_id is required")
        if self.mode == "advance" and not self.session_id:
            raise ValueError("advance requires a session_id")
        if self.session_id and self.init_cash is not None:
            raise ValueError("A session already owns its cash state; use the cash adjustment endpoint")
        return self


class ReportInput(StrictModel):
    upload_id: ID
    ocr_provider: str | None = Field(None, max_length=100)
    market: str = Field("China A-share", max_length=100)
    frequency: str = Field("daily", max_length=30)
    available_data: list[str] | None = Field(None, max_length=100)


class Budget(StrictModel):
    timeout_seconds: int = Field(3600, ge=1, le=86400)


class JobBase(StrictModel):
    budget: Budget = Field(default_factory=Budget)
    notify: bool | None = None


class MiningJob(JobBase):
    kind: Literal["mine"]
    input: MiningInput


class AFFJob(JobBase):
    kind: Literal["mine_aff"]
    input: AFFInput


class GPJob(JobBase):
    kind: Literal["mine_gp"]
    input: GPInput


class RLJob(JobBase):
    kind: Literal["mine_rl"]
    input: RLInput


class FactorBacktestJob(JobBase):
    kind: Literal["factor_backtest"]
    input: FactorBacktestInput


class StrategyBacktestJob(JobBase):
    kind: Literal["strategy_backtest"]
    input: StrategyBacktestInput


class DataJob(JobBase):
    kind: Literal["data"]
    input: DataInput


class DailyJob(JobBase):
    kind: Literal["daily_signals"]
    input: DailyInput


class ReportJob(JobBase):
    kind: Literal["report_factor_extract"]
    input: ReportInput


JobSpec = Annotated[Union[MiningJob, AFFJob, GPJob, RLJob, FactorBacktestJob,
                         StrategyBacktestJob, DataJob, DailyJob, ReportJob], Field(discriminator="kind")]
JOB_ADAPTER = TypeAdapter(JobSpec)


class ErrorBody(StrictModel):
    code: str
    message: str
    details: JsonValue = None
    retryable: bool = False
    request_id: str


class Progress(StrictModel):
    percent: float | None = None
    stage: str
    message: str | None = None
    updated_at: str | None = None
    completed: int | None = None
    total: int | None = None


class Job(StrictModel):
    job_id: str
    kind: str
    status: Literal["queued", "starting", "running", "cancelling", "succeeded", "failed", "cancelled", "lost"]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    normalized_input: JsonValue
    budget: Budget
    progress: Progress
    run_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    result_summary: str | None = None
    error: ErrorBody | None = None
    source: str
    client_id: str


class Result(StrictModel):
    job_id: str
    availability: Literal["pending", "partial", "complete", "unavailable"]
    summary: JsonValue = None
    run_ids: list[str]
    artifact_ids: list[str]
    error: ErrorBody | None = None


class FactorCreate(FactorExpression):
    categories: list[str] = Field(default_factory=list, max_length=100)


class FactorUpdate(StrictModel):
    name: Name | None = None
    categories: list[str] | None = Field(None, max_length=100)


class FactorValidation(StrictModel):
    expressions: list[Expression] = Field(min_length=1, max_length=1000)


class StrategyCreate(DatasetInput):
    name: Name
    factor_ids: list[ID] = Field(min_length=1, max_length=1000)


class StockPoolCreate(StrictModel):
    name: Name
    dataset_id: ID
    symbols: list[str] = Field(min_length=1, max_length=20000)
    description: str = Field("", max_length=5000)


class StockPoolUpdate(StrictModel):
    dataset_id: ID
    name: Name | None = None
    symbols: list[str] | None = Field(None, min_length=1, max_length=20000)
    description: str | None = Field(None, max_length=5000)


class SessionCreate(StrictModel):
    name: Name
    strategy_id: ID
    init_cash: float = Field(200000, gt=0)


class CashChange(StrictModel):
    delta: float
    note: str = Field("", max_length=1000)


class AssetRef(StrictModel):
    id: ID
    revision: int = Field(ge=1)


class Asset(AssetRef):
    name: str
    kind: Literal["factor", "strategy", "stock_pool", "signal_session", "factor_category"]
    metadata: dict[str, JsonValue]


class Dataset(StrictModel):
    dataset_id: str
    label: str
    source: str
    freq: str
    adjust_mode: str
    ready: bool
    unavailable_reason: str | None
    revision: str


class Template(StrictModel):
    template_id: str
    label: str
    template_type: str
    parameters: BacktestOptions
    ready: bool


class RegisteredModel(StrictModel):
    model_id: str
    label: str
    parameters_schema: str


class Artifact(StrictModel):
    artifact_id: str
    job_id: str | None
    run_id: str | None
    kind: str
    schema_version: str
    media_type: str
    size: int
    sha256: str
    name: str
    created_at: str
    content_url: str


class Run(StrictModel):
    run_id: str
    job_id: str | None
    metadata: dict[str, JsonValue]
    artifacts: list[Artifact]


class ImportRequest(StrictModel):
    upload_id: ID


class ExportRequest(StrictModel):
    ids: list[ID] = Field(min_length=1, max_length=1000)


class PortableStrategy(StrictModel):
    name: Name
    factor_expressions: list[Expression] = Field(min_length=1, max_length=1000)
    dataset_id: ID | None = None
    stock_pool_name: Name | None = None
    template_id: ID = "combined"
    model_id: Literal["lgbm"] = "lgbm"
    parameters: BacktestOptions = Field(default_factory=BacktestOptions)


class PortablePool(StrictModel):
    name: Name
    symbols: list[str] = Field(min_length=1, max_length=20000)
    description: str = ""


class FactorBundle(StrictModel):
    schema_version: Literal["1"] = "1"
    kind: Literal["factor"] = "factor"
    items: list[FactorCreate] = Field(min_length=1, max_length=1000)


class StrategyBundle(StrictModel):
    schema_version: Literal["1"] = "1"
    kind: Literal["strategy"] = "strategy"
    items: list[PortableStrategy] = Field(min_length=1, max_length=1000)


class StockPoolBundle(StrictModel):
    schema_version: Literal["1"] = "1"
    kind: Literal["stock_pool"] = "stock_pool"
    items: list[PortablePool] = Field(min_length=1, max_length=1000)


ASSET_BUNDLE_ADAPTER = TypeAdapter(Annotated[Union[FactorBundle, StrategyBundle, StockPoolBundle], Field(discriminator="kind")])


class ScheduleCreate(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    timezone: str = "Asia/Shanghai"
    enabled: bool = True
    job: JobSpec


class CommandRequest(StrictModel):
    text: str = Field(min_length=1, max_length=20000)


class RuntimeStatus(StrictModel):
    running: bool
    heartbeat_at: str | None
    draining: bool
    start_error: str | None


class Algorithm(StrictModel):
    kind: str
    available: bool
    may_use_llm: bool
    required_dependencies: list[str]


class Limits(StrictModel):
    page_default: int = 50
    page_max: int = 200
    log_bytes: int = 65536
    upload_bytes: int = 50 * 1024 * 1024
    max_queued: int
    max_running: int
    max_timeout_seconds: int


class Capabilities(StrictModel):
    api_version: str
    scopes: list[str]
    algorithms: list[Algorithm]
    runtime: RuntimeStatus
    limits: Limits
    budgets: dict[str, JsonValue]
    job_schema: str
    dataset_policy: Literal["latest_at_start"]
    workspace_mode: Literal["single_owner"]


class JobLogs(StrictModel):
    text: str
    next_cursor: int
    complete: bool


class ValidationIssue(StrictModel):
    code: str
    message: str


class ExpressionValidation(StrictModel):
    expression: str
    normalized_expression: str
    normalization: Literal["whitespace_trim"]
    valid: bool
    syntax_valid: bool
    temporal_valid: bool
    analysis: JsonValue
    issues: list[ValidationIssue]
    library_admission: JsonValue


class ValidationResults(StrictModel):
    results: list[ExpressionValidation]


class CategoryList(StrictModel):
    categories: list[str]
    supports_categories: bool
    items: list[Asset]


class Series(StrictModel):
    rows: list[dict[str, JsonValue]]
    total_points: int
    returned_points: int
    downsampled: bool
    sampling: Literal["evenly_spaced"]


class Upload(StrictModel):
    upload_id: str
    name: str
    size: int
    media_type: str
    created_at: str


class Schedule(StrictModel):
    schedule_id: str
    revision: int
    name: str
    time: str
    timezone: str
    enabled: bool
    job: JobSpec | None
    created_at: str | None = None
    last_run_date: str | None = None
    last_job_id: str | None = None
    last_error: str | None = None
    retry_at: float | None = None
    migration_error: str | None = None
