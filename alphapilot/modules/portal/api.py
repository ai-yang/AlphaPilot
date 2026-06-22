"""FastAPI backend for the JavaScript AlphaPilot portal."""

from __future__ import annotations

import inspect
import json
import tempfile
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from alphapilot.modules.portal import jobs, schedules
from alphapilot.modules.portal.runtime import load_runtime, pid_running, runtime_path, schedule_current_process_restart
from alphapilot.modules.portal.settings import load_file_portal_settings, save_portal_settings, settings_path


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
    status = 404 if isinstance(exc, FileNotFoundError) else 400
    return HTTPException(status_code=status, detail=f"{type(exc).__name__}: {exc}")


def _load_engine() -> Any:
    from alphapilot.kernel import build_engine

    return build_engine(discover=True)


def _engine(app: FastAPI) -> Any:
    if not hasattr(app.state, "engine"):
        app.state.engine = _load_engine()
    return app.state.engine


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


class FactorCreate(BaseModel):
    factor_name: str
    factor_expression: str
    categories: list[str] = Field(default_factory=list)


class FactorValidate(BaseModel):
    expression: str


class FactorCategoryEdit(BaseModel):
    name: str | None = None
    new_name: str | None = None
    factor_names: list[str] = Field(default_factory=list)
    category: str | None = None
    categories: list[str] = Field(default_factory=list)
    output_path: str | None = None


class FactorImport(BaseModel):
    kind: str = "csv"
    source: str


class FactorExport(BaseModel):
    output_path: str


class FactorBacktestCreate(BaseModel):
    factor_names: list[str] = Field(default_factory=list)
    category: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class StrategySave(BaseModel):
    strategy_name: str
    params: dict[str, Any] = Field(default_factory=dict)


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


class ModuleRun(BaseModel):
    module: str
    command: str
    kwargs: dict[str, Any] = Field(default_factory=dict)


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
    app = FastAPI(title="AlphaPilot Portal API")
    if engine is not None:
        app.state.engine = engine
    app.state.portal_host = portal_host
    app.state.portal_port = portal_port

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
                    "symbols": _safe_call("symbols", lambda: sum(len(v) for v in data_system.list_symbols().values()), "—"),
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
                "restart_required": restart_required,
                "runtime": {
                    "pid": runtime.get("pid"),
                    "running": pid_running(runtime.get("pid")),
                    "path": runtime_path(),
                    "argv": runtime.get("argv", []),
                },
            }
        )

    @app.patch("/api/portal/settings")
    def update_portal_settings(payload: PortalSettingsUpdate, request: Request) -> dict[str, Any]:
        try:
            save_portal_settings(_model_data(payload))
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
        return _jsonable(schedules.list_schedules())

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
            source: Any = payload.source
            if payload.kind == "json":
                source_path = Path(payload.source).expanduser()
                source = json.loads(source_path.read_text(encoding="utf-8"))
            return _jsonable(_engine(app).get_system("factor").import_factors(source, kind=payload.kind))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/factors/export")
    def export_factors(payload: FactorExport) -> dict[str, Any]:
        try:
            _engine(app).get_system("factor").database.save(payload.output_path)
            return {"output_path": payload.output_path, "saved": True}
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

    @app.delete("/api/factors/{factor_name}")
    def delete_factor(factor_name: str) -> dict[str, Any]:
        try:
            return {"factor_name": factor_name, "deleted": _engine(app).get_system("factor").delete_factor(factor_name)}
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
            count = factor_system.export_category_csv(payload.category or payload.name or "", payload.output_path or "")
            return {"category": payload.category or payload.name, "output_path": payload.output_path, "count": count}
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

    @app.post("/api/strategies/import")
    def import_strategy(payload: StrategyImport) -> Any:
        try:
            return _jsonable(_engine(app).get_system("strategy").import_strategy(payload.source, kind=payload.kind))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.post("/api/strategies/export")
    def export_strategy_file(payload: StrategyExport) -> dict[str, Any]:
        try:
            strategy_system = _engine(app).get_system("strategy")
            data = strategy_system.param_database.load(payload.strategy_name)
            if data is None:
                raise FileNotFoundError(f"Strategy not found: {payload.strategy_name}")
            out = Path(payload.output_path).expanduser()
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

    @app.post("/api/data/h5/rebuild")
    def rebuild_h5(options: dict[str, Any] | None = None) -> Any:
        try:
            return _jsonable(_engine(app).get_system("data").rebuild_h5(**(options or {})))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/market/sources")
    def market_sources() -> list[dict[str, Any]]:
        from alphapilot.modules.data_viz.loader import list_data_sources

        return _jsonable(list_data_sources())

    @app.get("/api/market/symbols")
    def market_symbols(data_dir: str) -> list[str]:
        from alphapilot.modules.data_viz.loader import list_symbols

        return list_symbols(Path(data_dir))

    @app.get("/api/market/kline")
    def market_kline(data_dir: str, symbol: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        from alphapilot.modules.data_viz.loader import available_date_range, format_symbol_label, load_bars

        try:
            df = load_bars(
                symbol,
                Path(data_dir),
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
        from alphapilot.systems.backtest.artifacts import (
            DEFAULT_LOG_ROOT,
            build_workspace_log_titles,
            format_workspace_label,
            list_workspaces,
        )

        root = Path(workspace_root or _engine(app).config.backtest.workspace_root)
        titles = build_workspace_log_titles(Path(log_root) if log_root else DEFAULT_LOG_ROOT, root)
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

    @app.get("/api/backtests/{workspace_id}")
    def backtest_detail(workspace_id: str, workspace_root: str | None = None) -> dict[str, Any]:
        from alphapilot.modules.backtest_viz import charts
        from alphapilot.systems.backtest.artifacts import build_summary, load_backtest

        root = Path(workspace_root or _engine(app).config.backtest.workspace_root)
        try:
            data = load_backtest(root / workspace_id)
            report = data.report.reset_index().rename(columns={"index": "date"})
            cum = charts.cum_series(data.report).reset_index().rename(columns={"index": "date"})
            return _jsonable(
                {
                    "workspace_id": workspace_id,
                    "summary": build_summary(data.report),
                    "report": report,
                    "cumulative": cum,
                    "trades": data.trades,
                    "holdings": data.holdings,
                    "metrics": data.metrics,
                }
            )
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.delete("/api/backtests/{workspace_id}")
    def delete_backtest(workspace_id: str) -> dict[str, Any]:
        try:
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
            eng = _engine(app)
            root = Path(getattr(eng.config, "log_dir", Path.cwd() / "log"))
            path = root / session_name
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
            eng = _engine(app)
            root = Path(getattr(eng.config, "log_dir", Path.cwd() / "log"))
            session_root = (root / session_name).resolve()
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
        try:
            kwargs = dict(payload)
            notify_flag = bool(kwargs.pop("notify", False))  # control key, not a task arg
            result = _engine(app).get_module("daily_trade").daily_signals(**kwargs)
            if notify_flag and isinstance(result, dict):
                # Best-effort push of today's positions/trades; never fail the request on it.
                try:
                    from alphapilot.log import logger
                    from alphapilot.systems import notify as notify_pkg

                    message = notify_pkg.build_job_message(
                        kind="daily_signals", job_id="manual", status="succeeded",
                        result=result, kwargs=kwargs,
                    )
                    result.setdefault("info", {})["notify"] = notify_pkg.send(message)
                except Exception as notify_exc:  # noqa: BLE001 - notify is best-effort
                    logger.warning(f"[daily-trade] notify skipped: {notify_exc}")
            return _jsonable(result)
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/api/notify")
    def notify_config() -> dict[str, Any]:
        from alphapilot.systems.notify import config as notify_config
        from alphapilot.systems.notify import service as notify_service

        return _jsonable(
            {
                "config": notify_config.load_file_config(),
                "fields": notify_config.CHANNEL_FIELDS,
                "configured_channels": notify_service.configured_channel_names(),
                "credentials_path": notify_config.credentials_path(),
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
            return _jsonable(commands[payload.command](**payload.kwargs))
        except Exception as exc:  # noqa: BLE001
            raise _api_error(exc) from exc

    @app.get("/branding/logo.svg")
    def portal_logo() -> FileResponse:
        logo_path = Path(__file__).resolve().parents[3] / "docs" / "logo.svg"
        if not logo_path.exists():
            raise HTTPException(status_code=404, detail="Logo file not found")
        return FileResponse(logo_path, media_type="image/svg+xml")

    static_path = Path(static_dir) if static_dir else Path(__file__).parent / "web" / "dist"
    if static_path.exists():
        assets_path = static_path / "assets"
        if assets_path.exists():
            app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str) -> FileResponse:  # noqa: ARG001
            index_path = static_path / "index.html"
            if not index_path.exists():
                raise HTTPException(status_code=404, detail="Portal frontend build not found")
            return FileResponse(index_path)

    return app


app = create_app()
