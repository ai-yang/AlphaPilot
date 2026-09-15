"""FastAPI backend for the JavaScript AlphaPilot portal."""

from __future__ import annotations

import inspect
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from fastapi import FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from alphapilot.modules.portal import jobs, schedules
from alphapilot.modules.portal.env_config import apply_portal_env, portal_env_payload, save_env_values
from alphapilot.modules.portal.runtime import load_runtime, pid_running, runtime_path, schedule_current_process_restart
from alphapilot.modules.portal.settings import (
    COMMON_TIMEZONES,
    apply_timezone,
    load_file_portal_settings,
    resolve_operator_auth,
    resolve_timezone,
    save_portal_settings,
    settings_path,
)
from alphapilot.systems.trading.account_identity import public_account_state

def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, pd.Series):
        return _jsonable(value.to_dict())
    if isinstance(value, pd.DataFrame):
        return _jsonable(value.to_dict(orient="records"))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)


def _safe_call(label: str, fn, default: Any = None) -> Any:  # noqa: ANN001
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return default if default is not None else {"error": f"{label}: {type(exc).__name__}: {exc}"}


def _api_error(exc: Exception) -> HTTPException:
    status = (
        401 if isinstance(exc, PermissionError)
        else 404 if isinstance(exc, (FileNotFoundError, KeyError))
        else 400
    )
    return HTTPException(status_code=status, detail=f"{type(exc).__name__}: {exc}")


def _truthy_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _trading_operator(
    app: FastAPI,
    request: Request,
    authorization: str | None,
    *,
    reason: str = "",
) -> Any:
    from alphapilot.systems.trading.contracts import OperatorContext

    cached = getattr(request.state, "trading_operator", None)
    if cached is not None:
        return OperatorContext(
            operator_id=cached.operator_id,
            request_id=cached.request_id,
            reason=str(reason or cached.reason),
            auth_source=cached.auth_source,
        )

    trading = _engine(app).get_system("trading")
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    raw_authorization = str(authorization or "").strip()
    if bool(getattr(app.state, "operator_auth_required", True)) or raw_authorization:
        return trading.operator_auth.authenticate(
            raw_authorization,
            request_id=request_id,
            reason=reason,
        )

    return OperatorContext(
        operator_id="portal-unauthenticated",
        request_id=request_id,
        reason=reason,
        auth_source="portal-config:operator-auth-optional",
    )


def _trading_mutation(path: str, method: str) -> bool:
    """Identify Portal trading writes governed by operator-auth mode."""

    if method.upper() not in {"POST", "PATCH", "PUT", "DELETE"}:
        return False
    if not (path.startswith("/api/live/") or path.startswith("/api/trading/")):
        return False
    # This POST endpoint is a read-only probe.
    return path != "/api/live/runtime/preflight"


def _request_audit_details(request: Request, **extra: Any) -> dict[str, Any]:
    client = request.client.host if request.client is not None else ""
    return {
        "path": request.url.path,
        "method": request.method,
        "client_address": str(client)[:255],
        "origin": str(request.headers.get("origin") or "")[:512],
        "user_agent": str(request.headers.get("user-agent") or "")[:512],
        **extra,
    }


def _removed_strategy_route(path: str) -> bool:
    """Reject removed strategy APIs before the SPA fallback can claim them."""

    parts = path.strip("/").split("/")
    if parts[:2] == ["api", "timing"]:
        return True
    if parts[:4] == ["api", "live", "daemon", "strategy"]:
        return True
    if parts[:3] == ["api", "trading", "stage-runs"]:
        return True
    if parts[:3] == ["api", "trading", "parity-runs"]:
        return True
    return (
        parts[:3] == ["api", "trading", "deployments"]
        and len(parts) >= 5
        and parts[4] in {
            "promote",
            "authorize-live",
            "qualification",
            "parity-runs",
            "execution-binding",
            "stage-runs",
        }
    )


def _count_unique_symbols(symbols_by_mode: Any) -> int:
    """Count distinct stock symbols across data-source/adjust-mode buckets."""
    if isinstance(symbols_by_mode, dict):
        return len(
            {
                str(symbol).strip()
                for values in symbols_by_mode.values()
                if isinstance(values, (list, tuple, set))
                for symbol in values
                if str(symbol).strip()
            }
        )
    if isinstance(symbols_by_mode, (list, tuple, set)):
        return len({str(symbol).strip() for symbol in symbols_by_mode if str(symbol).strip()})
    return 0


def _load_engine() -> Any:
    from alphapilot.kernel import build_engine

    return build_engine(discover=True)


def _engine(app: FastAPI) -> Any:
    if not hasattr(app.state, "engine"):
        app.state.engine = _load_engine()
    return app.state.engine


def _mining_session_root(app: FastAPI, session_name: str) -> Path:
    """Resolve a mining session as one direct child of the configured log root."""
    from alphapilot.core.path_safety import ensure_child_path

    root = Path(
        getattr(_engine(app).config, "log_dir", Path.cwd() / "log")
    ).expanduser().resolve()
    name = Path(session_name).expanduser()
    # Percent-encoded ``..`` is decoded by Starlette before route dispatch.
    if name.is_absolute() or len(name.parts) != 1 or name.name in {"", ".", ".."}:
        raise ValueError("Invalid mining session name")
    target = ensure_child_path(root, root / name)
    if target == root:
        raise ValueError("Invalid mining session name")
    return target


def _portal_asset_path(raw_path: str, *, must_exist: bool = False) -> Path:
    """Resolve Portal import/export files strictly below ``important_data``."""
    from alphapilot.core.path_safety import ensure_child_path
    from alphapilot.kernel.paths import important_data_dir

    root = important_data_dir().resolve()
    supplied = Path(raw_path).expanduser()
    if supplied.is_absolute():
        target = supplied.resolve()
    else:
        cwd_target = (Path.cwd() / supplied).resolve()
        try:
            target = ensure_child_path(root, cwd_target)
        except ValueError:
            # Portal defaults use repository-style ``important_data/...`` paths.
            # When tests/deployments relocate that root via the environment, strip
            # the conventional prefix instead of creating important_data twice.
            parts = (
                supplied.parts[1:]
                if supplied.parts and supplied.parts[0] == "important_data"
                else supplied.parts
            )
            target = root.joinpath(*parts).resolve()
    target = ensure_child_path(root, target)
    if target == root:
        raise ValueError("Asset path must name a file below important_data")
    if must_exist and not target.is_file():
        raise FileNotFoundError(f"Asset file not found: {target}")
    return target


def _configured_log_root(app: FastAPI, requested: str | None = None) -> Path:
    """Accept log maintenance only for the engine's configured log root."""
    configured = Path(getattr(_engine(app).config, "log_dir", Path.cwd() / "log")).expanduser().resolve()
    target = Path(requested).expanduser().resolve() if requested else configured
    if target != configured:
        raise ValueError(f"Log directory is outside the configured root: {target}")
    return target


def _market_data_root(app: FastAPI, requested: str) -> Path:
    """Resolve one of the data roots advertised by the market-data API."""
    from alphapilot.modules.data_viz.loader import list_data_sources

    target = Path(requested).expanduser().resolve()
    allowed = {Path(source.path).expanduser().resolve() for source in list_data_sources()}
    configured = getattr(getattr(_engine(app).config, "data", None), "raw_data_dir", None)
    if configured:
        allowed.add(Path(configured).expanduser().resolve())
    if target not in allowed:
        raise ValueError(f"Market data directory is not a configured data source: {target}")
    return target


def _backtest_root(app: FastAPI, requested: str | None = None, *, include_runs: bool = False) -> Path:
    """Resolve an approved legacy backtest or durable-runs root."""
    from alphapilot.systems.run_workspace import runs_root

    configured = Path(_engine(app).config.backtest.workspace_root).expanduser().resolve()
    allowed = {configured}
    if include_runs:
        allowed.add(runs_root().expanduser().resolve())
    target = (
        Path(requested).expanduser().resolve()
        if requested
        else (runs_root().resolve() if include_runs else configured)
    )
    if target not in allowed:
        raise ValueError(f"Backtest workspace root is not configured: {target}")
    return target


class JobCreate(BaseModel):
    kind: str
    kwargs: dict[str, Any] = Field(default_factory=dict)


class ScheduleCreate(BaseModel):
    name: str
    kind: str
    time: str
    kwargs: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    time: str | None = None
    kwargs: dict[str, Any] | None = None
    enabled: bool | None = None

    def changes(self) -> dict[str, Any]:
        data = self.model_dump() if hasattr(self, "model_dump") else self.dict()
        return {k: v for k, v in data.items() if v is not None}


def _model_data(model: BaseModel) -> dict[str, Any]:
    return model.model_dump() if hasattr(model, "model_dump") else model.dict()


class PortalSettingsUpdate(BaseModel):
    host: str
    port: int
    timezone: str | None = None


class PortalEnvUpdate(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class LogCleanupRequest(BaseModel):
    log_dir: str | None = None
    execute: bool = False


class FactorCreate(BaseModel):
    factor_name: str
    factor_expression: str
    categories: list[str] = Field(default_factory=list)


class FactorValidate(BaseModel):
    expression: str


class FactorRename(BaseModel):
    new_name: str


class FactorCategoryEdit(BaseModel):
    name: str | None = None
    new_name: str | None = None
    factor_names: list[str] = Field(default_factory=list)
    category: str | None = None
    categories: list[str] = Field(default_factory=list)
    output_path: str | None = None


class FactorImport(BaseModel):
    kind: Literal["csv", "json"] = "csv"
    source: str


class FactorExport(BaseModel):
    output_path: str


class FactorBulkDelete(BaseModel):
    factor_names: list[str] = Field(default_factory=list)


class FactorBacktestCreate(BaseModel):
    factor_names: list[str] = Field(default_factory=list)
    category: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class ReportFactorExtractRequest(BaseModel):
    source: str
    market: str = "China A-share"
    frequency: str = "daily"
    available_data: list[str] = Field(default_factory=list)
    ocr_mode: str = Field(default="auto", min_length=1, max_length=64)


class ReportFactorCommitItem(BaseModel):
    draft_id: str
    factor_name: str
    factor_expression: str
    categories: list[str] = Field(default_factory=list)


class ReportFactorCommitRequest(BaseModel):
    job_id: str
    factors: list[ReportFactorCommitItem] = Field(default_factory=list)


class StrategySave(BaseModel):
    strategy_name: str
    params: dict[str, Any] = Field(default_factory=dict)


class StrategyFromFactors(BaseModel):
    strategy_name: str
    factor_names: list[str] = Field(default_factory=list)
    model_name: str | None = None
    market: str | None = None
    yaml_params: dict[str, Any] = Field(default_factory=dict)


class StrategyExport(BaseModel):
    strategy_name: str
    output_path: str


class StrategyImport(BaseModel):
    kind: str = "pdf"
    source: str


class DataAction(BaseModel):
    action: str
    options: dict[str, Any] = Field(default_factory=dict)


class SymbolAction(BaseModel):
    symbol: str
    options: dict[str, Any] = Field(default_factory=dict)


class NotifyUpdate(BaseModel):
    config: dict[str, Any]


class NotifyCommandDispatch(BaseModel):
    text: str
    channel: str = "portal"
    user_id: str = "portal"
    chat_id: str = "portal"
    user_name: str | None = None
    enforce_auth: bool = False


class NotifyCommandDaemonStart(BaseModel):
    channel: str = "telegram"


class NotifyPairCodeRequest(BaseModel):
    channel: str = "telegram"


class ModuleRun(BaseModel):
    module: str
    command: str
    kwargs: dict[str, Any] = Field(default_factory=dict)


class TradingDeploymentUpdate(BaseModel):
    run_mode: Literal["paper", "simulation", "shadow", "live"]
    trade_provider: str = ""
    quote_provider: str = ""
    account_profile: str = ""
    account_id: str = ""
    reason: str | None = None


class TradingDecisionComparisonCreate(BaseModel):
    left_mode: Literal["replay", "paper", "simulation", "shadow", "live"]
    left_run_id: str
    right_mode: Literal["replay", "paper", "simulation", "shadow", "live"]
    right_run_id: str


class ObserverSubscriptionCreate(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    wait: bool = True
    timeout: float = Field(default=5.0, ge=0.1, le=60.0)
    mode: str | None = None
    broker: str | None = None
    trade_broker: str | None = None
    quote_provider: str | None = None
    state_dir: str | None = None


# The generic Advanced-page dispatcher must never bypass the dedicated job,
# filesystem, or live-trading API guards. CLI commands remain unchanged.
PORTAL_MODULE_RUN_ALLOWLIST: dict[str, set[str]] = {
    "factor": {
        "factor_validate", "factor_add", "factor_rename", "factor_list",
        "factor_duplicates", "factor_categorize", "factor_category_add",
        "factor_category_remove", "category_list", "category_create",
        "category_rename", "category_delete",
    },
    "stock_pool": {
        "pool_create", "pool_save", "pool_list", "pool_show", "pool_add",
        "pool_remove", "pool_rename", "pool_set_description", "pool_delete",
        "pool_export",
    },
    "platform": {"list_stocks", "modules"},
    "live": {
        "live_status", "live_modes", "live_brokers", "live_quote_providers",
        "live_plugins", "live_risk_status", "live_ledger_events", "live_state",
        "live_preflight",
    },
    "strategy_backtest": {"strategy_backtest_list"},
    "daily_trade": {
        "daily_state", "trade_session_list", "trade_session_show",
        "trade_session_history",
    },
}


def _safe_module_run_kwargs(payload: ModuleRun) -> dict[str, Any]:
    allowed = PORTAL_MODULE_RUN_ALLOWLIST.get(payload.module, set())
    if payload.command not in allowed:
        raise ValueError(
            f"Command {payload.module}.{payload.command} is not allowed through /api/modules/run; "
            "use its dedicated Portal endpoint or background job"
        )
    kwargs = dict(payload.kwargs)
    if payload.module == "stock_pool":
        if kwargs.get("stock_csv"):
            kwargs["stock_csv"] = str(_portal_asset_path(str(kwargs["stock_csv"]), must_exist=True))
        if payload.command == "pool_export":
            kwargs["output"] = str(_portal_asset_path(str(kwargs.get("output") or "")))
    if payload.module == "live":
        if kwargs.get("network"):
            raise ValueError("Network preflight is not allowed through /api/modules/run")
        for key in ("state_dir", "ledger_dir"):
            if kwargs.get(key):
                raise ValueError(f"Custom live {key} is not allowed through /api/modules/run")
    return kwargs


def _write_factor_csv(rows: list[dict[str, Any]], prefix: str = "alphapilot_factors") -> Path:
    path = Path(tempfile.gettempdir()) / f"{prefix}_{int(time.time())}.csv"
    pd.DataFrame(
        [
            {
                "factor_name": row.get("factor_name"),
                "factor_expression": row.get("factor_expression"),
            }
            for row in rows
        ]
    ).to_csv(path, index=False)
    return path


def create_app(
    *,
    static_dir: str | Path | None = None,
    engine: Any | None = None,
    portal_host: str | None = None,
    portal_port: int | None = None,
) -> FastAPI:
    apply_portal_env()
    apply_timezone()
    app = FastAPI(title="AlphaPilot Portal API")
    if engine is not None:
        app.state.engine = engine
    operator_auth = resolve_operator_auth()
    app.state.operator_auth_required = bool(operator_auth["required"])
    app.state.operator_auth_source = str(operator_auth["source"])
    saved_portal_settings = load_file_portal_settings()
    configured_host = (
        portal_host
        or os.getenv("ALPHAPILOT_PORTAL_BIND_HOST")
        or saved_portal_settings["host"]
    )
    configured_port = (
        int(portal_port)
        if portal_port is not None
        else int(saved_portal_settings["port"])
    )
    app.state.portal_host = configured_host
    app.state.portal_port = configured_port

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def reject_removed_strategy_entrypoints(request: Request, call_next):  # noqa: ANN001
        path = request.url.path
        if _removed_strategy_route(path):
            return JSONResponse(
                status_code=404,
                content={"detail": "This compatibility entrypoint was removed in 0.2.0"},
            )
        return await call_next(request)

    @app.middleware("http")
    async def authenticate_trading_writes(request: Request, call_next):  # noqa: ANN001
        """Apply one operator-auth policy and transport audit to trading writes."""

        if not _trading_mutation(request.url.path, request.method):
            return await call_next(request)
        trading = _engine(app).get_system("trading")
        try:
            operator = _trading_operator(
                app,
                request,
                request.headers.get("authorization"),
                reason=(
                    request.headers.get("x-operator-reason")
                    or f"Portal trading API {request.url.path}"
                ),
            )
            request.state.trading_operator = operator
            trading.operator_auth.audit(
                operator,
                action=f"portal_write:{request.url.path}",
                result="requested",
                details=_request_audit_details(request),
            )
        except Exception as exc:  # noqa: BLE001 - fail closed at the API boundary
            try:
                from alphapilot.systems.trading.contracts import OperatorContext

                trading.operator_auth.audit(
                    OperatorContext(
                        operator_id="portal-auth-rejected",
                        request_id=request.headers.get("x-request-id") or uuid.uuid4().hex,
                        reason=f"Portal trading API {request.url.path}",
                        auth_source="portal-auth-rejected",
                    ),
                    action=f"portal_write:{request.url.path}",
                    result="rejected",
                    details=_request_audit_details(
                        request,
                        status_code=401,
                        error=f"{type(exc).__name__}: {exc}",
                    ),
                )
            except Exception:  # noqa: BLE001 - return the original auth failure
                pass
            error = _api_error(exc)
            return JSONResponse(
                status_code=error.status_code,
                content={"detail": error.detail},
            )

        try:
            response = await call_next(request)
        except Exception as exc:
            try:
                trading.operator_auth.audit(
                    operator,
                    action=f"portal_write:{request.url.path}",
                    result="failed",
                    details=_request_audit_details(
                        request,
                        status_code=500,
                        error_type=type(exc).__name__,
                    ),
                )
            except Exception:  # noqa: BLE001 - preserve the request failure
                pass
            raise
        try:
            trading.operator_auth.audit(
                operator,
                action=f"portal_write:{request.url.path}",
                result="ok" if response.status_code < 400 else "failed",
                details=_request_audit_details(
                    request,
                    status_code=response.status_code,
                ),
            )
        except Exception:  # noqa: BLE001 - the pre-action audit is already durable
            pass
        return response

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        eng = _engine(app)
        data_system = _safe_call("data", lambda: eng.get_system("data"))
        factor_system = _safe_call("factor", lambda: eng.get_system("factor"))
        strategy_system = _safe_call("strategy", lambda: eng.get_system("strategy"))
        backtest_system = _safe_call("backtest", lambda: eng.get_system("backtest"))
        return _jsonable(
            {
                "systems": sorted(getattr(eng, "systems", {}).keys()),
                "modules": {
                    name: sorted(module.commands().keys()) if hasattr(module, "commands") else []
                    for name, module in getattr(eng, "modules", {}).items()
                },
                "config": {
                    "summary": _safe_call("config", lambda: eng.config.summary(), ""),
                    "qlib_data_dir": getattr(getattr(eng.config, "data", None), "qlib_data_dir", None),
                    "raw_data_dir": getattr(getattr(eng.config, "data", None), "raw_data_dir", None),
                    "factor_zoo_dir": getattr(getattr(eng.config, "factor", None), "zoo_dir", None),
                    "strategy_param_dir": getattr(getattr(eng.config, "strategy", None), "param_dir", None),
                    "backtest_workspace_root": getattr(getattr(eng.config, "backtest", None), "workspace_root", None),
                },
                "metrics": {
                    "symbols": _safe_call("symbols", lambda: _count_unique_symbols(data_system.list_symbols()), "—"),
                    "factors": _safe_call("factors", lambda: len(factor_system.list_factors()), "—"),
                    "strategies": _safe_call("strategies", lambda: len(strategy_system.param_database.list_strategies()), "—"),
                    "backtests": _safe_call("backtests", lambda: len(list(backtest_system.results.list_runs())), "—"),
                },
                "recent_jobs": jobs.list_jobs()[:5],
                "recent_mining": _safe_call(
                    "mining",
                    lambda: eng.get_module("alpha_mining").list_mining_sessions()[:5],
                    [],
                ),
            }
        )

    @app.get("/api/portal/settings")
    def get_portal_settings(request: Request) -> dict[str, Any]:
        saved = load_file_portal_settings()
        runtime = load_runtime()
        current = {
            "host": getattr(app.state, "portal_host", None) or request.url.hostname,
            "port": getattr(app.state, "portal_port", None) or request.url.port,
            "timezone": resolve_timezone(),
        }
        restart_required = saved.get("host") != current.get("host") or int(saved.get("port", 0)) != int(current.get("port") or 0)
        return _jsonable(
            {
                "settings": saved,
                "current": current,
                "config_path": settings_path(),
                "host_options": [
                    {"value": "127.0.0.1", "label": "127.0.0.1 (local only)"},
                    {"value": "0.0.0.0", "label": "0.0.0.0 (LAN / all interfaces)"},
                ],
                "timezone_options": list(COMMON_TIMEZONES),
                "restart_required": restart_required,
                "runtime": {
                    "pid": runtime.get("pid"),
                    "running": pid_running(runtime.get("pid")),
                    "path": runtime_path(),
                    "argv": runtime.get("argv", []),
                },
            }
        )

    @app.get("/api/portal/security")
    def get_portal_security(request: Request) -> dict[str, Any]:
        pending = resolve_operator_auth()
        current_required = bool(app.state.operator_auth_required)
        bind_host = str(
            getattr(app.state, "portal_host", None)
            or "127.0.0.1"
        )
        bind_port = int(
            getattr(app.state, "portal_port", None)
            or request.url.port
            or 19901
        )
        network_exposed = bind_host.strip().lower() not in {
            "127.0.0.1", "localhost", "::1",
        }
        return _jsonable({
            "operator_auth_required": current_required,
            "operator_auth_mode": "required" if current_required else "optional",
            "source": str(app.state.operator_auth_source),
            "pending_required": bool(pending["required"]),
            "pending_mode": str(pending["mode"]),
            "pending_source": str(pending["source"]),
            "restart_required": current_required != bool(pending["required"]),
            "bind_host": bind_host,
            "bind_port": bind_port,
            "bind_address": f"{bind_host}:{bind_port}",
            "network_exposed": network_exposed,
            "automated_live_enabled": _truthy_env("ALPHAPILOT_AUTOMATED_LIVE_ENABLED"),
            "cors_policy": "wildcard",
            "warning": (
                "Operator authentication is optional. Unauthenticated trading "
                "writes are accepted from every reachable client and wildcard "
                "CORS is enabled."
                if not current_required else ""
            ),
        })

    @app.patch("/api/portal/settings")
    def update_portal_settings(payload: PortalSettingsUpdate, request: Request) -> dict[str, Any]:
        try:
            save_portal_settings(_model_data(payload))
            apply_timezone()  # timezone takes effect immediately in this process
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc
        return get_portal_settings(request)

    @app.post("/api/portal/restart")
    def restart_portal() -> dict[str, Any]:
        try:
            restart = schedule_current_process_restart()
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc
        return _jsonable({"accepted": True, "restart": restart})

    @app.get("/api/portal/env")
    def get_portal_env() -> dict[str, Any]:
        return _jsonable(portal_env_payload())

    @app.patch("/api/portal/env")
    def update_portal_env(payload: PortalEnvUpdate) -> dict[str, Any]:
        try:
            save_env_values(payload.values)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc
        return _jsonable(portal_env_payload())

    @app.post("/api/logs/cleanup")
    def cleanup_logs(payload: LogCleanupRequest) -> dict[str, Any]:
        from alphapilot.log.cleanup import clean_log_dirs

        try:
            log_root = _configured_log_root(app, payload.log_dir)
            return _jsonable(clean_log_dirs(log_root, execute=payload.execute).as_dict())
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return _jsonable(jobs.list_jobs())

    @app.post("/api/jobs")
    def start_job(payload: JobCreate) -> dict[str, Any]:
        try:
            return _jsonable(jobs.start_job(payload.kind, payload.kwargs))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/jobs/clear")
    def clear_jobs() -> dict[str, Any]:
        try:
            return {"deleted": jobs.clear_finished_jobs()}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str, max_chars: int = 12000) -> dict[str, str]:
        try:
            return {"log": jobs.read_log_tail(job_id, max_chars=max_chars)}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/jobs/{job_id}/progress")
    def job_progress(job_id: str, max_chars: int = 50000) -> dict[str, Any]:
        try:
            return _jsonable(jobs.read_progress(job_id, max_chars=max_chars))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/jobs/{job_id}/result")
    def job_result(job_id: str) -> dict[str, Any] | None:
        try:
            return _jsonable(jobs.read_result(job_id))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        try:
            return _jsonable(jobs.cancel_job(job_id))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str, force: bool = False) -> dict[str, Any]:
        try:
            return _jsonable(jobs.delete_job(job_id, force=force))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/schedules")
    def list_schedules() -> list[dict[str, Any]]:
        records = schedules.list_schedules()
        for record in records:
            # Enrich each record with the next firing time so the UI can show it;
            # the stored record only carries the last_run_* fields.
            try:
                record["next_run_at"] = schedules.next_run_at(record).isoformat(timespec="seconds")
            except Exception:  # noqa: BLE001 - a malformed time should not break the list
                record["next_run_at"] = None
        return _jsonable(records)

    @app.post("/api/schedules")
    def create_schedule(payload: ScheduleCreate) -> dict[str, Any]:
        try:
            return _jsonable(schedules.create_schedule(**_model_data(payload)))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/schedules/daemon")
    def scheduler_status() -> dict[str, Any]:
        return _jsonable(schedules.daemon_status())

    @app.post("/api/schedules/daemon/start")
    def scheduler_start(interval: int = 30) -> dict[str, Any]:
        return _jsonable(schedules.start_daemon(interval=interval))

    @app.post("/api/schedules/daemon/stop")
    def scheduler_stop() -> dict[str, Any]:
        return _jsonable(schedules.stop_daemon())

    @app.post("/api/schedules/{schedule_id}/run")
    def run_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            return _jsonable(schedules.run_now(schedule_id))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.patch("/api/schedules/{schedule_id}")
    def update_schedule(schedule_id: str, payload: ScheduleUpdate) -> dict[str, Any]:
        try:
            return _jsonable(schedules.update_schedule(schedule_id, payload.changes()))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.delete("/api/schedules/{schedule_id}")
    def delete_schedule(schedule_id: str) -> dict[str, Any]:
        try:
            return {"schedule_id": schedule_id, "deleted": schedules.delete_schedule(schedule_id)}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/report-factors/ocr-providers")
    def report_factor_ocr_providers() -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_module("report_factor").ocr_providers())
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/report-factors/upload")
    async def upload_report_factor(file: UploadFile = File(...)) -> dict[str, Any]:
        from alphapilot.modules.report_factor.settings import ReportFactorSettings
        from alphapilot.modules.report_factor.uploads import save_uploaded_pdf

        try:
            return _jsonable(
                await save_uploaded_pdf(file, ReportFactorSettings.load())
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.delete("/api/report-factors/uploads/{upload_id}")
    def delete_report_factor_upload(upload_id: str) -> dict[str, Any]:
        from alphapilot.modules.report_factor.settings import ReportFactorSettings
        from alphapilot.modules.report_factor.uploads import delete_uploaded_pdf

        try:
            deleted = delete_uploaded_pdf(upload_id, ReportFactorSettings.load())
            return {"upload_id": upload_id, "deleted": deleted}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/report-factors/extract")
    def extract_report_factors(payload: ReportFactorExtractRequest) -> dict[str, Any]:
        try:
            source_path = _portal_asset_path(payload.source, must_exist=True)
            if source_path.suffix.lower() != ".pdf":
                raise ValueError("Report source must be a single .pdf file")
            with source_path.open("rb") as handle:
                header = handle.read(1024)
            if b"%PDF-" not in header:
                raise ValueError("Report source does not contain a valid PDF header")
            kwargs = _model_data(payload)
            kwargs["source"] = str(source_path)
            kwargs["ocr_mode"] = _engine(app).get_module(
                "report_factor"
            ).validate_ocr_mode(payload.ocr_mode)
            if not kwargs.get("available_data"):
                kwargs["available_data"] = None
            return _jsonable(jobs.start_job("report_factor_extract", kwargs))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/report-factors/commit")
    def commit_report_factors(payload: ReportFactorCommitRequest) -> dict[str, Any]:
        try:
            if not payload.factors:
                raise ValueError("At least one factor draft must be selected")
            job = jobs.get_job(payload.job_id)
            if job.get("kind") != "report_factor_extract":
                raise ValueError("job_id does not refer to a report-factor extraction")
            if job.get("status") != "succeeded":
                raise ValueError("Report-factor extraction has not succeeded")
            result_payload = jobs.read_result(payload.job_id) or {}
            extraction = result_payload.get("result")
            if not isinstance(extraction, dict):
                raise ValueError("Report-factor extraction result is unavailable")
            drafts = extraction.get("factors")
            if not isinstance(drafts, list):
                raise ValueError("Report-factor extraction result has no factor drafts")
            allowed_ids = {
                str(item.get("draft_id"))
                for item in drafts
                if isinstance(item, dict) and item.get("draft_id")
            }
            submitted = [_model_data(item) for item in payload.factors]
            unknown = sorted(
                {
                    str(item.get("draft_id") or "")
                    for item in submitted
                    if str(item.get("draft_id") or "") not in allowed_ids
                }
            )
            if unknown:
                raise ValueError(f"Unknown factor draft id(s): {', '.join(unknown)}")
            module = _engine(app).get_module("report_factor")
            return _jsonable(module.commit_factors(payload.job_id, submitted))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/factors")
    def list_factors() -> dict[str, Any]:
        factor_system = _engine(app).get_system("factor")
        db = factor_system.database
        return _jsonable(
            {
                "factors": factor_system.list_factors(),
                "categories": db.list_categories(),
                "supports_categories": bool(getattr(db, "supports_categories", False)),
            }
        )

    @app.post("/api/factors/import")
    def import_factors(payload: FactorImport) -> Any:
        try:
            source_path = _portal_asset_path(payload.source, must_exist=True)
            source: Any = str(source_path)
            if payload.kind == "json":
                source = json.loads(source_path.read_text(encoding="utf-8"))
            return _jsonable(_engine(app).get_system("factor").import_factors(source, kind=payload.kind))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/factors/export")
    def export_factors(payload: FactorExport) -> dict[str, Any]:
        try:
            output_path = _portal_asset_path(payload.output_path)
            _engine(app).get_system("factor").database.save(str(output_path))
            return {"output_path": str(output_path), "saved": True}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/factors")
    def add_factor(payload: FactorCreate) -> dict[str, Any]:
        try:
            result = _engine(app).get_system("factor").add_factor(
                payload.factor_name,
                payload.factor_expression,
                categories=payload.categories,
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/factors/validate")
    def validate_factor(payload: FactorValidate) -> dict[str, Any]:
        return _jsonable(_engine(app).get_system("factor").validate_expression(payload.expression))

    @app.get("/api/factors/duplicates")
    def factor_duplicates(similarity_threshold: float = 0.8) -> dict[str, Any]:
        try:
            return _jsonable(
                _engine(app).get_system("factor").find_duplicate_factors(
                    similarity_threshold=similarity_threshold
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/factors/bulk-delete")
    def bulk_delete_factors(payload: FactorBulkDelete) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("factor").delete_factors(payload.factor_names))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.delete("/api/factors/{factor_name}")
    def delete_factor(factor_name: str) -> dict[str, Any]:
        try:
            return {"factor_name": factor_name, "deleted": _engine(app).get_system("factor").delete_factor(factor_name)}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.patch("/api/factors/{factor_name}")
    def rename_factor(factor_name: str, payload: FactorRename) -> dict[str, Any]:
        try:
            result = _engine(app).get_system("factor").rename_factor(factor_name, payload.new_name)
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/factors/categories")
    def create_category(payload: FactorCategoryEdit) -> dict[str, Any]:
        try:
            name = payload.name or payload.category or ""
            return {"name": name, "created": _engine(app).get_system("factor").create_category(name)}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.patch("/api/factors/categories/{name}")
    def rename_category(name: str, payload: FactorCategoryEdit) -> dict[str, Any]:
        try:
            return {
                "old_name": name,
                "new_name": payload.new_name,
                "renamed": _engine(app).get_system("factor").rename_category(name, payload.new_name or ""),
            }
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.delete("/api/factors/categories/{name}")
    def delete_category(name: str) -> dict[str, Any]:
        try:
            return {"name": name, "deleted": _engine(app).get_system("factor").delete_category(name)}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/factors/categories/bulk")
    def bulk_factor_category(payload: FactorCategoryEdit, op: str = Query("add")) -> dict[str, Any]:
        try:
            if op not in {"add", "remove", "set", "export"}:
                raise ValueError("op must be one of: add, remove, set, export")
            factor_system = _engine(app).get_system("factor")
            if op == "add":
                return _jsonable(factor_system.add_factors_to_category(payload.factor_names, payload.category or ""))
            if op == "remove":
                return _jsonable(factor_system.remove_factors_from_category(payload.factor_names, payload.category or ""))
            if op == "set":
                ok = factor_system.set_factor_categories(payload.name or "", payload.categories)
                return {"factor_name": payload.name, "updated": ok}
            output_path = _portal_asset_path(payload.output_path or "")
            count = factor_system.export_category_csv(
                payload.category or payload.name or "", str(output_path)
            )
            return {
                "category": payload.category or payload.name,
                "output_path": str(output_path),
                "count": count,
            }
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/factors/backtest")
    def backtest_factors(payload: FactorBacktestCreate) -> dict[str, Any]:
        try:
            factor_system = _engine(app).get_system("factor")
            if payload.category:
                rows = factor_system.factors_in_category(payload.category)
                prefix = f"alphapilot_category_{payload.category}"
            else:
                wanted = set(payload.factor_names)
                rows = [row for row in factor_system.list_factors() if row.get("factor_name") in wanted]
                prefix = "alphapilot_selected"
            if not rows:
                raise ValueError("No factors selected for backtest.")
            factor_path = _write_factor_csv(rows, prefix=prefix)
            kwargs = {**payload.options, "factor_path": str(factor_path)}
            return _jsonable(jobs.start_job("factor_backtest", kwargs))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/strategies")
    def list_strategies() -> dict[str, Any]:
        strategy_system = _engine(app).get_system("strategy")
        names = strategy_system.param_database.list_strategies()
        records = [strategy_system.get_strategy(name) for name in names]
        return _jsonable({"strategies": [r for r in records if r is not None], "names": names})

    @app.post("/api/strategies")
    def save_strategy(payload: StrategySave) -> dict[str, Any]:
        try:
            _engine(app).get_system("strategy").param_database.save(payload.strategy_name, payload.params)
            return {"strategy_name": payload.strategy_name, "saved": True}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/strategies/from-factors")
    def create_strategy_from_factors(payload: StrategyFromFactors) -> dict[str, Any]:
        try:
            record = _engine(app).get_system("strategy").create_strategy_from_factors(
                strategy_name=payload.strategy_name,
                factor_names=payload.factor_names,
                model_name=payload.model_name,
                market=payload.market,
                yaml_params=payload.yaml_params,
            )
            return _jsonable(record)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/strategies/import")
    def import_strategy(payload: StrategyImport) -> Any:
        try:
            source = str(_portal_asset_path(payload.source, must_exist=True))
            return _jsonable(_engine(app).get_system("strategy").import_strategy(source, kind=payload.kind))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/strategies/export")
    def export_strategy_file(payload: StrategyExport) -> dict[str, Any]:
        try:
            strategy_system = _engine(app).get_system("strategy")
            data = strategy_system.param_database.load(payload.strategy_name)
            if data is None:
                raise FileNotFoundError(f"Strategy not found: {payload.strategy_name}")
            out = _portal_asset_path(payload.output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(_jsonable(data), ensure_ascii=False, indent=2), encoding="utf-8")
            return {"strategy_name": payload.strategy_name, "output_path": str(out), "saved": True}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/strategies/{strategy_name}/export")
    def export_strategy(strategy_name: str) -> dict[str, Any]:
        strategy_system = _engine(app).get_system("strategy")
        data = strategy_system.param_database.load(strategy_name)
        if data is None:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return _jsonable(data)

    @app.delete("/api/strategies/{strategy_name}")
    def delete_strategy(strategy_name: str) -> dict[str, Any]:
        try:
            return {"strategy_name": strategy_name, "deleted": _engine(app).get_system("strategy").delete_strategy(strategy_name)}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/strategy-definitions")
    def trading_strategy_definitions() -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("trading").list_definitions())
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/compatibility")
    def trading_compatibility() -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("trading").compatibility_status())
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/broker-uat-runs")
    def trading_broker_uat_runs(broker: str | None = None) -> dict[str, Any]:
        try:
            return _jsonable({
                "runs": _engine(app).get_system("trading").list_broker_uat_runs(broker)
            })
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/broker-uat-runs/{run_id}")
    def trading_broker_uat_run(run_id: str) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("trading").get_broker_uat_run(run_id))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/portfolio-policy-definitions")
    def trading_portfolio_policy_definitions() -> dict[str, Any]:
        try:
            return _jsonable(
                _engine(app).get_system("trading").list_portfolio_policy_definitions()
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/strategy-instances")
    def trading_strategy_instances() -> dict[str, Any]:
        try:
            return _jsonable({"instances": _engine(app).get_system("trading").list_instances()})
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trading/strategy-instances")
    def trading_strategy_instance_create(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            operator = _trading_operator(app, request, authorization, reason=str(payload.get("reason") or ""))
            trading = _engine(app).get_system("trading")
            result = trading.create_instance(payload)
            trading.operator_auth.audit(
                operator, action="create_instance", result="ok",
                instance_id=result["instance_id"], config_hash=result["config_hash"],
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trading/strategy-instances/from-research-asset")
    def trading_strategy_instance_from_research(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            operator = _trading_operator(app, request, authorization, reason=str(payload.get("reason") or ""))
            trading = _engine(app).get_system("trading")
            result = trading.create_instance_from_research_asset(payload)
            trading.operator_auth.audit(
                operator, action="create_instance_from_research_asset", result="ok",
                instance_id=result["instance_id"], config_hash=result["config_hash"],
                details={"research_asset": payload.get("strategy_name") or payload.get("research_asset")},
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.patch("/api/trading/strategy-instances/{instance_id}")
    def trading_strategy_instance_update(
        instance_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            operator = _trading_operator(app, request, authorization, reason=str(payload.get("reason") or ""))
            trading = _engine(app).get_system("trading")
            result = trading.update_instance(instance_id, payload)
            trading.operator_auth.audit(
                operator, action="update_instance", result="ok",
                instance_id=instance_id, config_hash=result["config_hash"],
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trading/strategy-instances/{instance_id}/validate")
    def trading_strategy_instance_validate(
        instance_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            operator = _trading_operator(app, request, authorization)
            trading = _engine(app).get_system("trading")
            result = trading.validate_instance(instance_id)
            current = trading.store.get_instance(instance_id)
            trading.operator_auth.audit(
                operator, action="validate_instance", result="ok" if result["ok"] else "rejected",
                instance_id=instance_id, config_hash=current["config_hash"], details=result.get("errors"),
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trading/strategy-instances/{instance_id}/preview")
    def trading_strategy_instance_preview(
        instance_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            operator = _trading_operator(app, request, authorization, reason=str(payload.get("reason") or ""))
            trading = _engine(app).get_system("trading")
            result = trading.preview_instance(instance_id, payload)
            trading.operator_auth.audit(
                operator, action="preview_signal", result="ok",
                instance_id=instance_id, config_hash=result["config_hash"],
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trading/strategy-instances/{instance_id}/backtest-runs")
    def trading_backtest_run_create(
        instance_id: str,
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            operator = _trading_operator(app, request, authorization, reason=str(payload.get("reason") or ""))
            trading = _engine(app).get_system("trading")
            result = trading.start_backtest_run(instance_id, payload)
            trading.operator_auth.audit(
                operator, action="start_backtest", result="queued",
                instance_id=instance_id, config_hash=result["config_hash"],
                details={"run_id": result["run_id"]},
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/backtest-runs/{run_id}")
    def trading_backtest_run_get(run_id: str) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("trading").get_backtest_run(run_id))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/backtest-runs/{run_id}/detail")
    def trading_backtest_run_detail(run_id: str) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("trading").get_backtest_run(run_id, detail=True))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trading/backtest-runs/{run_id}/cancel")
    def trading_backtest_run_cancel(
        run_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            operator = _trading_operator(app, request, authorization, reason="cancel backtest")
            trading = _engine(app).get_system("trading")
            result = trading.cancel_backtest_run(run_id)
            trading.operator_auth.audit(
                operator, action="cancel_backtest", result="requested",
                instance_id=result["instance_id"], config_hash=result["config_hash"],
                details={"run_id": run_id},
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/deployments/{instance_id}")
    def trading_deployment(instance_id: str, request: Request) -> dict[str, Any]:
        try:
            return _jsonable(public_account_state(
                _engine(app).get_system("trading").deployment(instance_id)
            ))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/deployments")
    def trading_deployments(request: Request) -> dict[str, Any]:
        try:
            return _jsonable(public_account_state({
                "deployments": _engine(app).get_system("trading").list_deployments()
            }))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.put("/api/trading/deployments/{instance_id}")
    def trading_deployment_update(
        instance_id: str,
        payload: TradingDeploymentUpdate,
        request: Request,
    ) -> dict[str, Any]:
        try:
            data = _model_data(payload)
            operator = _trading_operator(
                app,
                request,
                request.headers.get("authorization"),
                reason=str(data.get("reason") or "configure deployment"),
            )
            trading = _engine(app).get_system("trading")
            result = trading.configure_deployment(instance_id, data)
            configuration = result.get("configuration") or {}
            instance = result.get("instance") or {}
            trading.operator_auth.audit(
                operator,
                action="configure_deployment",
                result="ok",
                instance_id=instance_id,
                config_hash=str(
                    instance.get("config_hash")
                    or configuration.get("config_hash")
                    or ""
                ),
                broker=str(configuration.get("trade_provider") or ""),
                details={
                    "run_mode": configuration.get("run_mode"),
                    "quote_provider": configuration.get("quote_provider"),
                    "binding_hash": configuration.get("binding_hash"),
                },
            )
            return _jsonable(public_account_state(result))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/deployments/{instance_id}/diagnostics")
    def trading_deployment_diagnostics(instance_id: str, request: Request) -> dict[str, Any]:
        try:
            return _jsonable(
                _engine(app).get_system("trading").deployment_diagnostics(instance_id)
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trading/deployments/{instance_id}/observer-subscriptions")
    def trading_deployment_observer_subscriptions(
        instance_id: str,
        payload: ObserverSubscriptionCreate,
        request: Request,
    ) -> dict[str, Any]:
        try:
            trading = _engine(app).get_system("trading")
            result = trading.deployment_subscribe_observer(
                instance_id,
                payload.symbols,
            )
            current = trading.store.get_instance(instance_id)
            operator = _trading_operator(
                app,
                request,
                request.headers.get("authorization"),
                reason="add deployment observer subscriptions",
            )
            trading.operator_auth.audit(
                operator,
                action="deployment_observer_subscribe",
                result="ok" if result.get("ok") else "failed",
                instance_id=instance_id,
                config_hash=str(current.get("config_hash") or ""),
                details={
                    "command_id": result.get("command_id"),
                    "requested": result.get("requested") or [],
                    "added": result.get("added") or [],
                    "already_subscribed": result.get("already_subscribed") or [],
                    "failed": result.get("failed") or [],
                },
            )
            return _jsonable(public_account_state(result))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/deployments/{instance_id}/market/snapshot")
    def trading_deployment_market_snapshot(
        instance_id: str,
        symbols: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            selected = [
                item.strip()
                for item in str(symbols or "").replace("，", ",").split(",")
                if item.strip()
            ]
            return _jsonable(
                _engine(app).get_system("trading").deployment_market_snapshot(
                    instance_id,
                    selected,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/deployments/{instance_id}/market/bars")
    def trading_deployment_market_bars(
        instance_id: str,
        symbol: str,
        interval: int = Query(default=60),
        limit: int = Query(default=300, ge=1, le=2000),
    ) -> dict[str, Any]:
        try:
            return _jsonable(
                _engine(app).get_system("trading").deployment_market_bars(
                    instance_id,
                    symbol,
                    interval,
                    limit=limit,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trading/deployments/{instance_id}/decision-comparisons")
    def trading_decision_comparison_create(
        instance_id: str,
        payload: TradingDecisionComparisonCreate,
        request: Request,
    ) -> dict[str, Any]:
        try:
            operator = _trading_operator(
                app,
                request,
                request.headers.get("authorization"),
                reason="create decision comparison",
            )
            trading = _engine(app).get_system("trading")
            result = trading.compare_decisions(instance_id, _model_data(payload))
            current = trading.store.get_instance(instance_id)
            trading.operator_auth.audit(
                operator,
                action="create_decision_comparison",
                result="ok",
                instance_id=instance_id,
                config_hash=str(current["config_hash"]),
                details={
                    "comparison_id": result.get("comparison_id"),
                    "left_mode": result.get("left_mode"),
                    "right_mode": result.get("right_mode"),
                },
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/deployments/{instance_id}/decision-comparisons")
    def trading_decision_comparisons(instance_id: str, request: Request) -> dict[str, Any]:
        try:
            return _jsonable({
                "comparisons": _engine(app).get_system(
                    "trading"
                ).list_decision_comparisons(instance_id)
            })
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/decision-comparisons/{comparison_id}")
    def trading_decision_comparison(comparison_id: str, request: Request) -> dict[str, Any]:
        try:
            return _jsonable(
                _engine(app).get_system("trading").get_decision_comparison(comparison_id)
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    def _deployment_command(
        instance_id: str,
        action: str,
        operator: Any,
    ) -> dict[str, Any]:
        trading = _engine(app).get_system("trading")
        result = trading.lifecycle_action(instance_id, action)
        instance = result.get("instance") or {}
        runtime = result.get("runtime") or {}
        configuration = result.get("configuration") or {}
        trading.operator_auth.audit(
            operator,
            action=f"deployment_{action}",
            result="ok" if result.get("ok", True) else "failed",
            instance_id=instance_id,
            config_hash=str(
                instance.get("config_hash")
                or configuration.get("config_hash")
                or ""
            ),
            broker=str(
                runtime.get("trade_provider")
                or configuration.get("trade_provider")
                or ""
            ),
            details={
                "desired_state": runtime.get("desired_state"),
                "observed_state": runtime.get("observed_state"),
                "runtime_id": runtime.get("runtime_id"),
            },
        )
        return _jsonable(public_account_state(result))

    for _action in ("start", "pause", "reconcile", "resume", "stop"):
        def _make_action(action_name: str):
            def endpoint(
                instance_id: str,
                request: Request,
                payload: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                try:
                    operator = _trading_operator(
                        app,
                        request,
                        request.headers.get("authorization"),
                        reason=str((payload or {}).get("reason") or f"deployment {action_name}"),
                    )
                    return _deployment_command(instance_id, action_name, operator)
                except Exception as exc:  # noqa: BLE001
                    raise _api_error(exc) from exc
            return endpoint
        app.post(
            f"/api/trading/deployments/{{instance_id}}/{_action}",
            summary=f"Trading Deployment {_action.title()}",
            operation_id=f"trading_deployment_{_action}",
        )(
            _make_action(_action)
        )

    @app.get("/api/trading/deployments/{instance_id}/status")
    def trading_deployment_status(instance_id: str, request: Request) -> dict[str, Any]:
        try:
            return _jsonable(public_account_state(
                _engine(app).get_system("trading").lifecycle_action(instance_id, "status")
            ))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/kill-switches")
    def trading_kill_switches() -> dict[str, Any]:
        try:
            return _jsonable({
                "kill_switches": _engine(app).get_system("trading").list_kill_switches()
            })
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trading/audit-events")
    def trading_audit_events(limit: int = 200) -> dict[str, Any]:
        try:
            return _jsonable({
                "events": public_account_state(
                    _engine(app).get_system("trading").audit_events(limit=limit)
                )
            })
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trading/kill-switches/{scope_type}/{scope_id}/{action}")
    def trading_kill_switch(
        scope_type: str,
        scope_id: str,
        action: str,
        request: Request,
        payload: dict[str, Any] | None = None,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        try:
            if action not in {"engage", "release"}:
                raise ValueError("kill-switch action must be engage or release")
            reason = str((payload or {}).get("reason") or "").strip()
            if not reason:
                raise ValueError("kill-switch changes require an operator reason")
            operator = _trading_operator(
                app, request, authorization, reason=reason,
            )
            trading = _engine(app).get_system("trading")
            result = trading.set_kill_switch(
                    scope_type,
                    scope_id,
                    active=action == "engage",
                    reason=reason,
                )
            trading.operator_auth.audit(
                operator, action=f"kill_switch_{action}", result="ok", details=result,
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/data/actions")
    def run_data_action(payload: DataAction) -> Any:
        try:
            return _jsonable(_engine(app).get_system("data").run_action(payload.action, **payload.options))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/data/universe")
    def data_universe(stock_csv: str | None = None, code_column: str | None = None) -> dict[str, Any]:
        try:
            options = {k: v for k, v in {"stock_csv": stock_csv, "code_column": code_column}.items() if v}
            universe = _engine(app).get_system("data").get_universe(**options)
            return {"count": len(universe), "symbols": universe}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/data/instrument-sets")
    def data_instrument_sets() -> dict[str, Any]:
        """List Qlib instrument-set names (stock pools) available for selection."""
        try:
            inst_dir = Path(_engine(app).config.data.qlib_data_dir) / "instruments"
            sets = sorted(p.stem for p in inst_dir.glob("*.txt")) if inst_dir.exists() else []
            return {"sets": sets}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/data/symbols")
    def data_symbols(source: str | None = None, adjust_mode: str | None = None) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("data").list_symbols(adjust_mode, source=source))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/data/symbols/delete")
    def delete_symbol(payload: SymbolAction) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("data").delete_symbol(payload.symbol, **payload.options))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/data/symbols/refresh")
    def refresh_symbol(payload: SymbolAction) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("data").refresh_symbol(payload.symbol, **payload.options))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/data/symbols/trim")
    def trim_symbol(payload: SymbolAction) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("data").trim_symbol(payload.symbol, **payload.options))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/data/symbols/apply-adjust")
    def apply_adjust_symbol(payload: SymbolAction) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_system("data").apply_adjust_symbol(payload.symbol, **payload.options))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/market/sources")
    def market_sources() -> list[dict[str, Any]]:
        from alphapilot.modules.data_viz.loader import list_data_sources

        return _jsonable(list_data_sources())

    @app.get("/api/market/symbols")
    def market_symbols(data_dir: str) -> list[str]:
        from alphapilot.modules.data_viz.loader import list_symbols

        try:
            return list_symbols(_market_data_root(app, data_dir))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/market/kline")
    def market_kline(data_dir: str, symbol: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        from alphapilot.modules.data_viz.loader import available_date_range, format_symbol_label, load_bars

        try:
            df = load_bars(
                symbol,
                _market_data_root(app, data_dir),
                start=date.fromisoformat(start) if start else None,
                end=date.fromisoformat(end) if end else None,
            )
            dmin, dmax = available_date_range(df)
            return _jsonable(
                {
                    "symbol": symbol,
                    "label": format_symbol_label(symbol),
                    "date_range": [dmin, dmax],
                    "rows": df,
                }
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/backtests")
    def backtests(workspace_root: str | None = None, log_root: str | None = None) -> list[dict[str, Any]]:
        # Prefer the durable per-run records under git_ignore_folder/runs/<id>/; each
        # run keeps its own workspaces + a logs symlink. Only fall back to a flat
        # workspace root (legacy layout) when there are no saved runs.
        from alphapilot.systems.run_workspace import list_run_backtests

        from alphapilot.systems.backtest.artifacts import (
            build_workspace_log_titles,
            format_workspace_label,
            list_workspaces,
        )

        try:
            root = _backtest_root(app, workspace_root)
            configured_log_root = _configured_log_root(app, log_root)
            entries = list_run_backtests()
            if entries:
                return _jsonable(entries)
            titles = build_workspace_log_titles(configured_log_root, root)
            workspaces = list_workspaces(root)
            return _jsonable(
                [
                    {
                        "workspace_id": ws.name,
                        "path": ws,
                        "label": format_workspace_label(ws, titles, workspaces),
                        "mtime": datetime.fromtimestamp(ws.stat().st_mtime),
                    }
                    for ws in workspaces
                ]
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    # Static paths must be declared before "/api/backtests/{workspace_id}" so they
    # aren't swallowed by the parametric route (workspace_id="leaderboards").
    @app.get("/api/backtests/leaderboards")
    def backtest_leaderboards(workspace_root: str | None = None) -> list[dict[str, Any]]:
        from alphapilot.systems.backtest.artifacts import find_leaderboards

        try:
            root = _backtest_root(app, workspace_root, include_runs=True)
            return _jsonable(
                [
                    {
                        "file": str(p.relative_to(root)),
                        "label": f"{p.parent.name}/{p.name}",
                        "mtime": datetime.fromtimestamp(p.stat().st_mtime),
                    }
                    for p in find_leaderboards(root)
                ]
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/backtests/leaderboard")
    def backtest_leaderboard(file: str, workspace_root: str | None = None) -> dict[str, Any]:
        import pandas as pd

        from alphapilot.systems.backtest.artifacts import read_leaderboard

        try:
            root = _backtest_root(app, workspace_root, include_runs=True)
            target = (root / file).resolve()
            if root not in target.parents or not target.name.endswith("_leaderboard.csv"):
                raise ValueError(f"invalid leaderboard file: {file}")
            df = read_leaderboard(target)
            numeric = [c for c in df.columns if c != "factor_name" and pd.api.types.is_numeric_dtype(df[c])]
            return _jsonable({"columns": list(df.columns), "numeric_columns": numeric, "rows": df})
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/backtests/{workspace_id}")
    def backtest_detail(workspace_id: str, workspace_root: str | None = None) -> dict[str, Any]:
        from alphapilot.modules.backtest_viz import charts
        from alphapilot.systems.backtest.artifacts import build_summary, load_backtest
        from alphapilot.systems.run_workspace import resolve_run_workspace

        try:
            ws = resolve_run_workspace(workspace_id)
            if ws is None:
                root = _backtest_root(app, workspace_root)
                name = Path(workspace_id).expanduser()
                if name.is_absolute() or len(name.parts) != 1 or name.name in {"", ".", ".."}:
                    raise ValueError("Invalid backtest workspace id")
                from alphapilot.core.path_safety import ensure_child_path

                ws = ensure_child_path(root, root / name)
            data = load_backtest(ws)
            # The report's DatetimeIndex is named "datetime", so renaming the
            # "index" column is a no-op — force the date column name explicitly so
            # the payload always carries a `date` field (charts key off it).
            rep = data.report.copy()
            rep.index.name = "date"
            report = rep.reset_index()
            nav_returns_df = charts.nav_return_series(data.report)
            nav_returns_df.index.name = "date"
            nav_returns = nav_returns_df.reset_index()
            return _jsonable(
                {
                    "workspace_id": workspace_id,
                    "summary": build_summary(data.report),
                    "report": report,
                    # Keep the response field for compatibility; its values are
                    # compounded NAV returns rather than arithmetic cumulative sums.
                    "cumulative": nav_returns,
                    "trades": data.trades,
                    "holdings": data.holdings,
                    "metrics": data.metrics,
                }
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.delete("/api/backtests/{workspace_id}")
    def delete_backtest(workspace_id: str) -> dict[str, Any]:
        from alphapilot.systems.run_workspace import delete_run_workspace

        try:
            deleted = delete_run_workspace(workspace_id)
            if not deleted:  # legacy flat workspace root
                deleted = _engine(app).get_system("backtest").delete_workspace(workspace_id)
            return {"workspace_id": workspace_id, "deleted": deleted}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/mining/sessions")
    def mining_sessions() -> list[dict[str, Any]]:
        try:
            eng = _engine(app)
            root = Path(getattr(eng.config, "log_dir", Path.cwd() / "log"))
            module = eng.get_module("alpha_mining")
            sessions = module.list_mining_sessions()
            out = []
            for name in sessions:
                path = root / name
                out.append(
                    {
                        "name": name,
                        "path": str(path),
                        "mtime": datetime.fromtimestamp(path.stat().st_mtime).isoformat() if path.exists() else None,
                    }
                )
            return out
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/mining/sessions/{session_name}")
    def mining_session_detail(session_name: str) -> dict[str, Any]:
        try:
            path = _mining_session_root(app, session_name)
            if not path.exists():
                raise FileNotFoundError(session_name)
            files = [
                {
                    "path": str(p.relative_to(path)),
                    "size": p.stat().st_size,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(),
                }
                for p in path.rglob("*")
                if p.is_file()
            ]
            files.sort(key=lambda item: item["mtime"], reverse=True)
            return {"name": session_name, "path": str(path), "files": files[:300]}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/mining/sessions/{session_name}/files/{file_path:path}")
    def mining_session_file(session_name: str, file_path: str, max_chars: int = 20000) -> dict[str, Any]:
        try:
            session_root = _mining_session_root(app, session_name)
            target = (session_root / file_path).resolve()
            if session_root not in target.parents and target != session_root:
                raise ValueError("Invalid file path")
            if not target.is_file():
                raise FileNotFoundError(file_path)
            text = target.read_text(encoding="utf-8", errors="replace")
            if max_chars > 0 and len(text) > max_chars:
                text = text[-max_chars:]
            return {"session": session_name, "path": file_path, "content": text, "truncated": max_chars > 0 and target.stat().st_size > max_chars}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.delete("/api/mining/sessions/{session_name}")
    def delete_mining_session(session_name: str) -> dict[str, Any]:
        try:
            deleted = _engine(app).get_module("alpha_mining").delete_mining_session(session_name)
            return {"name": session_name, "deleted": deleted}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/daily-trade")
    def daily_trade(payload: dict[str, Any]) -> dict[str, Any]:
        # Run as a background job (kind "daily_signals") so the portal shows live
        # run status / progress and the task lands in the jobs panel. The worker pops the
        # ``notify`` control key itself and pushes on success/failure via ``_maybe_notify``.
        try:
            return _jsonable(jobs.start_job("daily_signals", dict(payload)))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    # --- trade sessions (self-contained, resumable daily-trade accounts) ----------
    @app.get("/api/trade-sessions")
    def list_trade_sessions() -> list[dict[str, Any]]:
        try:
            return _jsonable(_engine(app).get_module("daily_trade").trade_session_list())
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trade-sessions")
    def create_trade_session(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _engine(app).get_module("daily_trade").trade_session_create(
                    name=payload.get("name"),
                    strategy_name=payload.get("strategy_name"),
                    init_cash=payload.get("init_cash"),
                    overwrite=bool(payload.get("overwrite", False)),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trade-sessions/{name}")
    def get_trade_session(name: str) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_module("daily_trade").trade_session_show(name))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/trade-sessions/{name}/history")
    def get_trade_session_history(name: str) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_module("daily_trade").trade_session_history(name))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.delete("/api/trade-sessions/{name}")
    def delete_trade_session(name: str) -> dict[str, Any]:
        try:
            return _jsonable(_engine(app).get_module("daily_trade").trade_session_delete(name))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/trade-sessions/{name}/cash")
    def adjust_trade_session_cash(name: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Simulate a deposit (delta>0) / withdrawal (delta<0) on the session's rolling cash.
        try:
            return _jsonable(
                _engine(app).get_module("daily_trade").trade_session_cash(
                    name, payload.get("delta"), payload.get("note"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/notify")
    def notify_config() -> dict[str, Any]:
        from alphapilot.systems.notify import config as notify_config
        from alphapilot.systems.notify import service as notify_service

        return _jsonable(
            {
                "config": notify_config.public_notify_config(),
                "fields": notify_config.CHANNEL_FIELDS,
                "configured_channels": notify_service.configured_channel_names(),
                "credentials_path": notify_config.credentials_path(),
                "masked_secret": notify_config.MASKED_SECRET,
            }
        )

    @app.patch("/api/notify")
    def update_notify(payload: NotifyUpdate) -> dict[str, Any]:
        from alphapilot.systems.notify import config as notify_config

        path = notify_config.save_notify_config(payload.config)
        return {"saved": True, "path": str(path)}

    @app.post("/api/notify/test")
    def test_notify(channel: str | None = None) -> dict[str, Any]:
        from alphapilot.systems.notify import service as notify_service

        return _jsonable(notify_service.test_send(channel))

    @app.get("/api/notify/commands/status")
    def notify_commands_status() -> dict[str, Any]:
        from alphapilot.systems.notify import commands as notify_commands
        from alphapilot.systems.notify import inbound

        return _jsonable(
            {
                "daemon": inbound.daemon_status(),
                "payload": notify_commands.command_payload_status(),
                "events": inbound.recent_events(limit=20),
            }
        )

    @app.post("/api/notify/commands/start")
    def notify_commands_start(payload: NotifyCommandDaemonStart) -> dict[str, Any]:
        try:
            from alphapilot.systems.notify import inbound

            return _jsonable(inbound.start_daemon(channel=payload.channel))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/notify/commands/stop")
    def notify_commands_stop() -> dict[str, Any]:
        try:
            from alphapilot.systems.notify import inbound

            return _jsonable(inbound.stop_daemon())
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/notify/commands/events")
    def notify_commands_events(limit: int = 100) -> list[dict[str, Any]]:
        from alphapilot.systems.notify import inbound

        return _jsonable(inbound.recent_events(limit=limit))

    @app.post("/api/notify/commands/dispatch")
    def notify_commands_dispatch(payload: NotifyCommandDispatch) -> dict[str, Any]:
        from alphapilot.systems.notify.commands import dispatch_text

        try:
            return _jsonable(
                dispatch_text(
                    payload.text,
                    channel=payload.channel,
                    user_id=payload.user_id,
                    chat_id=payload.chat_id,
                    user_name=payload.user_name,
                    enforce_auth=payload.enforce_auth,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/notify/commands/plan")
    def notify_commands_plan(payload: NotifyCommandDispatch) -> dict[str, Any]:
        from alphapilot.systems.notify.commands import plan_natural_language

        try:
            action = plan_natural_language(payload.text)
            return _jsonable({"ok": True, "action": action.to_dict()})
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/notify/commands/pair-code")
    def notify_commands_pair_code(payload: NotifyPairCodeRequest) -> dict[str, Any]:
        from alphapilot.systems.notify import inbound

        try:
            item = inbound.create_pair_code(channel=payload.channel)
            return _jsonable({"ok": True, **item})
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/notify/commands/register-menu")
    def notify_commands_register_menu() -> dict[str, Any]:
        from alphapilot.systems.notify.config import load_notify_config
        from alphapilot.systems.notify.receivers import telegram_set_my_commands

        try:
            token = str(load_notify_config().get("telegram", {}).get("bot_token") or "")
            if not token:
                raise ValueError("telegram bot_token is required to register the menu")
            telegram_set_my_commands(token)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/notify/feishu/events")
    async def notify_feishu_events(
        request: Request,
        x_lark_request_timestamp: str | None = Header(default=None),
        x_lark_request_nonce: str | None = Header(default=None),
        x_lark_signature: str | None = Header(default=None),
    ) -> dict[str, Any]:
        from alphapilot.systems.notify.config import load_notify_config
        from alphapilot.systems.notify.receivers import handle_feishu_event, verify_feishu_signature

        body = await request.body()
        cfg = load_notify_config()
        feishu_cfg = cfg.get("feishu", {}) if isinstance(cfg.get("feishu"), dict) else {}
        if not verify_feishu_signature(
            body=body,
            timestamp=x_lark_request_timestamp,
            nonce=x_lark_request_nonce,
            signature=x_lark_signature,
            encrypt_key=feishu_cfg.get("encrypt_key"),
        ):
            raise HTTPException(status_code=401, detail="Invalid Feishu signature")
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
            token = feishu_cfg.get("verification_token")
            if token and payload.get("token") and payload.get("token") != token:
                raise HTTPException(status_code=401, detail="Invalid Feishu verification token")
            return _jsonable(handle_feishu_event(payload))
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/modules")
    def modules() -> dict[str, Any]:
        eng = _engine(app)
        out: dict[str, Any] = {}
        for module_name, module in getattr(eng, "modules", {}).items():
            commands = module.commands() if hasattr(module, "commands") else {}
            out[module_name] = {
                "commands": [
                    {
                        "name": name,
                        "signature": str(inspect.signature(fn)),
                        "doc": (inspect.getdoc(fn) or "").splitlines()[0] if inspect.getdoc(fn) else "",
                        "deprecated": False,
                        "replacement": "",
                    }
                    for name, fn in commands.items()
                ]
            }
        return out

    @app.post("/api/modules/run")
    def run_module(payload: ModuleRun) -> Any:
        try:
            module = _engine(app).get_module(payload.module)
            commands = module.commands()
            if payload.command not in commands:
                raise ValueError(f"Unknown command: {payload.module}.{payload.command}")
            kwargs = _safe_module_run_kwargs(payload)
            return _jsonable(commands[payload.command](**kwargs))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    # ---- Live trading --------------------------------------------------------
    # Portal controls the same LiveRuntime used by the CLI. PAPER remains the
    # safe in-process sandbox; LIVE endpoints below are deliberately read-only /
    # connect-only so real order routing still needs explicit CLI/runtime
    # confirmation.
    def _live_system() -> Any:
        return _engine(app).get_system("live")

    def _live_module() -> Any:
        return _engine(app).get_module("live")

    def _active_runtime() -> Any:
        return getattr(app.state, "live_runtime", None)

    def _replace_runtime(runtime: Any | None) -> None:
        old = _active_runtime()
        if old is not None and old is not runtime:
            try:
                old.close()
            except Exception:
                pass
        app.state.live_runtime = runtime

    def _require_paper() -> Any:
        runtime = _active_runtime()
        if runtime is None:
            raise ValueError("Paper session not started; connect first.")
        if runtime.config.mode != "paper":
            raise ValueError("Active live runtime is not a paper session.")
        return runtime

    def _live_state(runtime: Any) -> dict[str, Any]:
        state = runtime.snapshot()
        engine_state = state.get("engine") or {}
        account = state.get("account") or {}
        return {
            "snapshot": engine_state,
            "account": {
                "buying_power": engine_state.get("buying_power", 0.0),
                "balance": account.get("balance", 0.0),
                "available": account.get("available", 0.0),
            },
            "positions": state.get("positions") or [],
            "orders": state.get("orders") or [],
            "trades": state.get("trades") or [],
            "ledger": state.get("ledger_tail") or [],
            "runtime": state.get("config") or {},
        }

    @app.get("/api/live/status")
    def live_status() -> dict[str, Any]:
        try:
            live = _live_system()
            runtime = _active_runtime()
            data: dict[str, Any] = {
                "config": live.snapshot(),
                "modes": live.modes(),
                "running": runtime is not None,
            }
            if runtime is not None:
                data["state"] = _live_state(runtime)
            return _jsonable(data)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/brokers")
    def live_brokers(account_kind: str | None = None) -> list[dict[str, Any]]:
        try:
            return _jsonable(_live_module().live_brokers(account_kind=account_kind))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/quote-providers")
    def live_quote_providers(data_kind: str | None = None) -> list[dict[str, Any]]:
        try:
            return _jsonable(_live_module().live_quote_providers(data_kind=data_kind))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/plugins")
    def live_plugins() -> dict[str, Any]:
        try:
            return _jsonable(_live_module().live_plugins())
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/runtime/state")
    def live_runtime_state(
        mode: str | None = Query(default=None),
        broker: str | None = Query(default=None),
        trade_broker: str | None = Query(default=None),
        quote_provider: str | None = Query(default=None),
        state_dir: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_state(
                    mode=mode,
                    broker=broker,
                    trade_broker=trade_broker,
                    quote_provider=quote_provider,
                    state_dir=state_dir,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/runtime/preflight")
    def live_runtime_preflight(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_preflight(
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    network=bool(payload.get("network", False)),
                    timeout=float(payload.get("timeout") or 3.0),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/runtime/connect")
    def live_runtime_connect(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_connect(
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    cash=payload.get("cash"),
                    timeout=float(payload.get("timeout") or 20.0),
                    ledger_dir=payload.get("ledger_dir"),
                    state_dir=payload.get("state_dir"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/risk/status")
    def live_risk_status(
        mode: str | None = Query(default=None),
        broker: str | None = Query(default=None),
        trade_broker: str | None = Query(default=None),
        quote_provider: str | None = Query(default=None),
        state_dir: str | None = Query(default=None),
        ledger_dir: str | None = Query(default=None),
        tail: int = Query(default=20),
    ) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_risk_status(
                    mode=mode,
                    broker=broker,
                    trade_broker=trade_broker,
                    quote_provider=quote_provider,
                    state_dir=state_dir,
                    ledger_dir=ledger_dir,
                    tail=tail,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/ledger/events")
    def live_ledger_events(
        kind: str | None = Query(default=None),
        command_id: str | None = Query(default=None),
        order_id: str | None = Query(default=None),
        reference: str | None = Query(default=None),
        day: str | None = Query(default=None),
        limit: int = Query(default=50),
        mode: str | None = Query(default=None),
        broker: str | None = Query(default=None),
        trade_broker: str | None = Query(default=None),
        quote_provider: str | None = Query(default=None),
        ledger_dir: str | None = Query(default=None),
        state_dir: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_ledger_events(
                    kind=kind,
                    command_id=command_id,
                    order_id=order_id,
                    reference=reference,
                    day=day,
                    limit=limit,
                    mode=mode,
                    broker=broker,
                    trade_broker=trade_broker,
                    quote_provider=quote_provider,
                    ledger_dir=ledger_dir,
                    state_dir=state_dir,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/daemon/status")
    def live_daemon_status(
        mode: str | None = Query(default=None),
        broker: str | None = Query(default=None),
        trade_broker: str | None = Query(default=None),
        quote_provider: str | None = Query(default=None),
        state_dir: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_status(
                    mode=mode,
                    broker=broker,
                    trade_broker=trade_broker,
                    quote_provider=quote_provider,
                    state_dir=state_dir,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/market/snapshot")
    def live_market_snapshot(
        mode: str | None = Query(default=None),
        broker: str | None = Query(default=None),
        trade_broker: str | None = Query(default=None),
        quote_provider: str | None = Query(default=None),
        state_dir: str | None = Query(default=None),
        symbols: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_market_snapshot(
                    mode=mode,
                    broker=broker,
                    trade_broker=trade_broker,
                    quote_provider=quote_provider,
                    state_dir=state_dir,
                    symbols=symbols,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/market/bars")
    def live_market_bars(
        symbol: str,
        interval: int = Query(default=60),
        limit: int = Query(default=300, ge=1, le=2000),
        mode: str | None = Query(default=None),
        broker: str | None = Query(default=None),
        trade_broker: str | None = Query(default=None),
        quote_provider: str | None = Query(default=None),
        state_dir: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_market_bars(
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    mode=mode,
                    broker=broker,
                    trade_broker=trade_broker,
                    quote_provider=quote_provider,
                    state_dir=state_dir,
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/start")
    def live_daemon_start(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_start(
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    symbols=payload.get("symbols"),
                    cash=payload.get("cash"),
                    interval=float(payload.get("interval") or 1.0),
                    timeout=float(payload.get("timeout") or 20.0),
                    ledger_dir=payload.get("ledger_dir"),
                    state_dir=payload.get("state_dir"),
                    duration=payload.get("duration"),
                    record_market_data=payload.get("record_market_data"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/subscribe")
    def live_daemon_subscribe(
        payload: ObserverSubscriptionCreate,
        request: Request,
    ) -> dict[str, Any]:
        try:
            result = _live_module().live_daemon_subscribe(
                symbols=payload.symbols,
                mode=payload.mode,
                broker=payload.broker,
                trade_broker=payload.trade_broker,
                quote_provider=payload.quote_provider,
                state_dir=payload.state_dir,
                wait=payload.wait,
                timeout=payload.timeout,
            )
            trading = _engine(app).get_system("trading")
            operator = _trading_operator(
                app,
                request,
                request.headers.get("authorization"),
                reason="add standalone observer subscriptions",
            )
            trading.operator_auth.audit(
                operator,
                action="live_daemon_observer_subscribe",
                result=(
                    "ok"
                    if result.get("accepted") and result.get("ok", True)
                    else "failed"
                ),
                details={
                    "command_id": (result.get("command") or {}).get("id"),
                    "requested": result.get("requested") or payload.symbols,
                    "added": result.get("added") or [],
                    "already_subscribed": result.get("already_subscribed") or [],
                    "failed": result.get("failed") or [],
                },
            )
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/stop")
    def live_daemon_stop(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_stop(
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    state_dir=payload.get("state_dir"),
                    timeout=float(payload.get("timeout") or 5.0),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/halt")
    def live_daemon_halt(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_halt(
                    reason=str(payload.get("reason") or "portal"),
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    state_dir=payload.get("state_dir"),
                    wait=bool(payload.get("wait", False)),
                    timeout=float(payload.get("timeout") or 5.0),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/resume")
    def live_daemon_resume(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_resume(
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    state_dir=payload.get("state_dir"),
                    wait=bool(payload.get("wait", False)),
                    timeout=float(payload.get("timeout") or 5.0),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/refresh")
    def live_daemon_refresh(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_refresh(
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    state_dir=payload.get("state_dir"),
                    wait=bool(payload.get("wait", False)),
                    timeout=float(payload.get("timeout") or 5.0),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/reconnect")
    def live_daemon_reconnect(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_reconnect(
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    state_dir=payload.get("state_dir"),
                    wait=bool(payload.get("wait", False)),
                    timeout=float(payload.get("timeout") or 20.0),
                    auto_resume=bool(payload.get("auto_resume", False)),
                    confirm_live=bool(payload.get("confirm_live", False)),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/cancel")
    def live_daemon_cancel(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_cancel(
                    order_id=str(payload.get("order_id") or ""),
                    symbol=payload.get("symbol") or payload.get("code"),
                    force=bool(payload.get("force", False)),
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    state_dir=payload.get("state_dir"),
                    wait=bool(payload.get("wait", False)),
                    timeout=float(payload.get("timeout") or 5.0),
                    event_timeout=float(payload.get("event_timeout") or 3.0),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/order")
    def live_daemon_order(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_order(
                    symbol=str(payload.get("symbol") or payload.get("code") or ""),
                    side=str(payload.get("side") or "buy"),
                    volume=float(payload["volume"]),
                    price=float(payload.get("price") or 0.0),
                    order_type=str(payload.get("order_type") or "limit"),
                    exchange=payload.get("exchange"),
                    offset=str(payload.get("offset") or "none"),
                    product=str(payload.get("product") or "equity"),
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    state_dir=payload.get("state_dir"),
                    wait=bool(payload.get("wait", False)),
                    timeout=float(payload.get("timeout") or 5.0),
                    event_timeout=float(payload.get("event_timeout") or 3.0),
                    confirm_live=bool(payload.get("confirm_live", False)),
                    reference=str(payload.get("reference") or "portal_daemon"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/daemon/submit-target")
    def live_daemon_submit_target(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return _jsonable(
                _live_module().live_daemon_submit_target(
                    target_path=payload.get("target_path"),
                    holdings=payload.get("holdings"),
                    prices=payload.get("prices"),
                    positions=payload.get("positions"),
                    date=payload.get("date"),
                    source=payload.get("source") or "portal_daemon",
                    session=payload.get("session"),
                    strategy_name=payload.get("strategy_name"),
                    factor_path=payload.get("factor_path"),
                    model_pickle_path=payload.get("model_pickle_path"),
                    yaml_params=payload.get("yaml_params"),
                    refresh_data=bool(payload.get("refresh_data", False)),
                    route=bool(payload.get("route", False)),
                    mode=payload.get("mode"),
                    broker=payload.get("broker"),
                    trade_broker=payload.get("trade_broker"),
                    quote_provider=payload.get("quote_provider"),
                    state_dir=payload.get("state_dir"),
                    wait=bool(payload.get("wait", False)),
                    timeout=float(payload.get("timeout") or 5.0),
                    confirm_live=bool(payload.get("confirm_live", False)),
                )
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/paper/connect")
    def live_paper_connect(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            cash = float(payload.get("cash") or 1_000_000.0)
            runtime = _live_system().create_runtime(mode="paper", broker="paper")
            runtime.connect(paper_cash=cash)
            runtime.wait_ready(timeout=1.0, require_contracts=False)
            _replace_runtime(runtime)
            return _jsonable(_live_state(runtime))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/live/paper/state")
    def live_paper_state() -> dict[str, Any]:
        try:
            runtime = _active_runtime()
            if runtime is None:
                return _jsonable({"running": False})
            return _jsonable({"running": True, **_live_state(runtime)})
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/paper/order")
    def live_paper_order(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            runtime = _require_paper()
            code = str(payload["code"]).strip()
            side = str(payload.get("side", "buy")).lower()
            volume = float(payload["volume"])
            price = float(payload.get("price") or 0.0)
            if price > 0:
                runtime.engine.gateway.set_prices({code: price})
            order = runtime.submit_order(code, side=side, volume=volume, price=price, reference="portal")
            return _jsonable({"order_id": order["order_id"], **_live_state(runtime)})
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/paper/submit-target")
    def live_paper_submit_target(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            from alphapilot.systems.live.targets import TargetPortfolio

            runtime = _require_paper()
            holdings = {str(k): float(v) for k, v in (payload.get("holdings") or {}).items()}
            prices = {str(k): float(v) for k, v in (payload.get("prices") or {}).items()}
            if prices:
                runtime.engine.gateway.set_prices(prices)
            target = TargetPortfolio(date=str(payload.get("date") or "portal"), holdings=holdings, prices=prices)
            result = runtime.submit_target(target, route=True)
            return _jsonable({"planned": result["planned"], "routed": len(result["routed"]), **_live_state(runtime)})
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/paper/halt")
    def live_paper_halt(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            runtime = _require_paper()
            runtime.engine.halt(str(payload.get("reason") or "portal kill-switch"))
            runtime.write_state()
            return _jsonable(_live_state(runtime))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/paper/resume")
    def live_paper_resume() -> dict[str, Any]:
        try:
            runtime = _require_paper()
            runtime.engine.resume()
            runtime.write_state()
            return _jsonable(_live_state(runtime))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/live/paper/reset")
    def live_paper_reset() -> dict[str, Any]:
        _replace_runtime(None)
        return _jsonable({"running": False})

    @app.get("/branding/logo.svg")
    def portal_logo() -> FileResponse:
        logo_path = Path(__file__).resolve().parents[3] / "docs" / "logo.svg"
        if not logo_path.exists():
            raise HTTPException(status_code=404, detail="Logo file not found")
        return FileResponse(logo_path, media_type="image/svg+xml")

    from alphapilot.research.api import install as install_research_api
    install_research_api(app, lambda: _engine(app))

    static_path = Path(static_dir) if static_dir else Path(__file__).parent / "web" / "dist"
    if static_path.exists():
        assets_path = static_path / "assets"
        if assets_path.exists():
            app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

        # The SPA fallback is an implementation detail, not a public API. Keep
        # OpenAPI stable whether the optional frontend build output is present.
        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="API endpoint not found")
            index_path = static_path / "index.html"
            if not index_path.exists():
                raise HTTPException(status_code=404, detail="Portal frontend build not found")
            return FileResponse(index_path)

    return app


app = create_app()
