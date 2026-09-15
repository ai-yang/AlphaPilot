"""Versioned research HTTP boundary. No MCP implementation dependency."""
from __future__ import annotations

import csv
import json
import os
import uuid
from pathlib import Path
from typing import Annotated, Generic, Literal, TypeVar

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer
from pydantic import Field, JsonValue, ValidationError

from .artifacts import ArtifactService, public_value
from .assets import AssetService
from .auth import Actor, AuthService
from .catalog import Catalog
from .common import ResearchError, SCOPES, encode, json_value, now, opaque
from .models import (BacktestOptions, Budget, CashChange, CommandRequest, ErrorBody, ExportRequest,
                     FactorCreate, FactorUpdate, FactorValidation, ImportRequest, Job, JobSpec, Result,
                     ScheduleCreate, SessionCreate, StockPoolCreate, StockPoolUpdate, StrategyCreate, StrictModel)
from .models import (Asset, AssetRef, Artifact, Dataset, Template, RegisteredModel, Run,
                     Capabilities, JobLogs, ValidationResults, CategoryList, Series, Upload, Schedule)
from .schedules import ScheduleService
from .store import Store
from .tasks import TaskService, page
from .uploads import UploadService

T = TypeVar("T")


class Page(StrictModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    total: int | None = None


class CategoryEdit(StrictModel):
    name: str = Field(min_length=1, max_length=100)


class CategoryMembers(StrictModel):
    op: Literal["add", "remove", "set"]
    category: str = Field(min_length=1, max_length=100)
    factors: list[AssetRef] = Field(min_length=1, max_length=1000)


class ReviewedFactor(StrictModel):
    draft_id: str
    factor_name: str
    factor_expression: str
    categories: list[str] = Field(default_factory=list)


class ReportCommit(StrictModel):
    job_id: str
    factors: list[ReviewedFactor] = Field(min_length=1, max_length=1000)


LEGACY_PREFIXES = ("/api/jobs", "/api/factors", "/api/strategies", "/api/data", "/api/market",
                   "/api/backtests", "/api/mining", "/api/daily-trade", "/api/trade-sessions",
                   "/api/schedules", "/api/report-factors")
LEGACY_EXACT = {"/api/status", "/api/notify/commands/dispatch", "/api/notify/commands/plan"}
RESEARCH_MODULES = {"alpha_mining", "factor", "stock_pool", "strategy_backtest", "daily_trade",
                    "report_factor", "alphaforge_aff", "alphaforge_search", "qlib_yaml", "data_viz", "backtest_viz"}


def removed(path: str) -> bool:
    return path in LEGACY_EXACT or any(path == p or path.startswith(p + "/") for p in LEGACY_PREFIXES)


def install(app, engine_factory) -> None:
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(HTTPBearer(auto_error=False))],
                       responses={code: {"model": ErrorBody} for code in (401, 403, 404, 409, 410, 412, 422, 428, 429, 500, 503)})

    def tasks() -> TaskService:
        if not hasattr(app.state, "research_tasks"):
            app.state.research_tasks = TaskService(Store(), engine_factory())
        return app.state.research_tasks

    def store() -> Store:
        # Auth/catalog queries do not instantiate a heavy engine just to reject a credential.
        if not hasattr(app.state, "research_store"):
            app.state.research_store = Store()
        return app.state.research_store

    def assets() -> AssetService:
        return AssetService(engine_factory(), store())

    def asset_view(row: dict) -> dict:
        base = {k: row[k] for k in ("id", "name", "kind", "revision")}
        return {**base, "metadata": {k: v for k, v in row.items() if k not in base}}

    def run_view(row: dict) -> dict:
        base = {k: row[k] for k in ("run_id", "job_id", "artifacts")}
        return {**base, "metadata": {k: v for k, v in row.items() if k not in base}}

    def artifacts() -> ArtifactService:
        return ArtifactService(store())

    def actor(request: Request) -> Actor:
        return request.state.research_actor

    @app.middleware("http")
    async def research_boundary(request: Request, call_next):
        path = request.url.path
        request_id = uuid.uuid4().hex
        request.state.research_request_id = request_id
        if removed(path):
            return JSONResponse(ResearchError("API_REMOVED", "Research API moved to /api/v1; upgrade this client", 410).payload(request_id), status_code=410)
        if path == "/api/modules/run" and request.method == "POST":
            try:
                body = await request.json()
                if body.get("module") in RESEARCH_MODULES or body.get("command") in {"research_token", "research_migrate", "task_runtime", "scheduler", "prepare_data"}:
                    return JSONResponse(ResearchError("API_REMOVED", "Use typed /api/v1 research operations", 410).payload(request_id), status_code=410)
            except (ValueError, AttributeError):
                pass
        if not (path == "/api/v1" or path.startswith("/api/v1/")):
            return await call_next(request)
        try:
            origin = request.headers.get("origin")
            allowed = {str(request.base_url).rstrip("/"), *filter(None, os.getenv("ALPHAPILOT_RESEARCH_CORS_ORIGINS", "").split(","))}
            if origin and origin not in allowed:
                raise ResearchError("ORIGIN_REJECTED", "Origin is not permitted for the research API", 403)
            if request.method == "OPTIONS":
                return await call_next(request)
            authenticated = AuthService(store()).authenticate(request.headers.get("authorization"), request_id)
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                store().require_migrated()
            request.state.research_actor = authenticated
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            if response.status_code == 429:
                response.headers["Retry-After"] = "5"
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                AuthService(store()).audit(authenticated, f"http:{request.method}:{path}", {"status": response.status_code})
            return response
        except ResearchError as exc:
            headers = {"X-Request-ID": request_id}
            if exc.status == 401:
                headers["WWW-Authenticate"] = "Bearer"
            return JSONResponse(exc.payload(request_id), status_code=exc.status, headers=headers)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Research request %s failed", request_id)
            return JSONResponse(ResearchError("INTERNAL_ERROR", "Research request failed", 500).payload(request_id), status_code=500)

    async def research_error(request: Request, exc: ResearchError):
        return JSONResponse(exc.payload(getattr(request.state, "research_request_id", None)), status_code=exc.status)

    async def validation_error(request: Request, exc: RequestValidationError):
        if not request.url.path.startswith("/api/v1/"):
            return await request_validation_exception_handler(request, exc)
        details = [{"loc": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
        return await research_error(request, ResearchError("VALIDATION_ERROR", "Request validation failed", 422, details=details))

    async def domain_error(request: Request, exc: Exception):
        if not request.url.path.startswith("/api/v1/"):
            raise exc
        if isinstance(exc, ValidationError):
            details = [{"loc": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]
            return await research_error(request, ResearchError("VALIDATION_ERROR", "Research input validation failed", 422, details=details))
        return await research_error(request, ResearchError("NOT_FOUND" if isinstance(exc, FileNotFoundError) else "INVALID_REQUEST",
                                                            str(exc), 404 if isinstance(exc, FileNotFoundError) else 422))

    app.add_exception_handler(ResearchError, research_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(ValueError, domain_error)
    app.add_exception_handler(FileNotFoundError, domain_error)

    @router.get("/openapi.json", operation_id="research_openapi")
    def openapi(a: Actor = Depends(actor)) -> dict:
        a.require("research:read")
        return get_openapi(title="AlphaPilot Research API", version="1.0.0", routes=router.routes)

    @router.get("/capabilities", operation_id="research_capabilities", response_model=Capabilities)
    def capabilities(a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        from .runtime import status
        return {"api_version": "1.0.0", "scopes": sorted(a.scopes), "algorithms": Catalog.algorithms(),
                "runtime": status(store()), "limits": {"page_default": 50, "page_max": 200, "log_bytes": 65536,
                "upload_bytes": 50 * 1024 * 1024, "max_queued": int(os.getenv("ALPHAPILOT_RESEARCH_MAX_QUEUED", "100")),
                "max_running": int(os.getenv("ALPHAPILOT_RESEARCH_MAX_RUNNING", "1")),
                "max_timeout_seconds": int(os.getenv("ALPHAPILOT_RESEARCH_MAX_TIMEOUT", "86400"))},
                "budgets": Budget.model_json_schema(), "job_schema": "/api/v1/openapi.json",
                "dataset_policy": "latest_at_start", "workspace_mode": "single_owner"}

    @router.get("/status", operation_id="research_status")
    def research_status(a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        from .runtime import status
        factors = len(assets().all("factor", a))
        strategies = len(assets().all("strategy", a))
        runs = artifacts().runs(a, limit=50)
        return {"runtime": status(store()), "api_version": "1.0.0", "factor_count": factors, "strategy_count": strategies,
                "metrics": {"factors": factors, "strategies": strategies, "backtests": runs["total"]},
                "recent_mining": [r["run_id"] for r in runs["items"] if "min" in str(r.get("command", ""))][:5]}

    @router.get("/datasets", operation_id="research_datasets", response_model=Page[Dataset])
    def datasets(cursor: str | None = None, limit: int = Query(50, ge=1, le=200), a: Actor = Depends(actor)):
        a.require("research:read")
        return page(Catalog(engine_factory()).datasets(), cursor, limit)

    @router.get("/templates", operation_id="research_templates", response_model=Page[Template])
    def templates(cursor: str | None = None, limit: int = Query(50, ge=1, le=200), a: Actor = Depends(actor)):
        a.require("research:read")
        return page(Catalog(engine_factory()).templates(), cursor, limit)

    @router.get("/models", operation_id="research_models", response_model=Page[RegisteredModel])
    def models(a: Actor = Depends(actor)):
        a.require("research:read")
        return page(Catalog(engine_factory()).models())

    @router.get("/factor-dsl", operation_id="research_factor_dsl")
    def factor_dsl(a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        return Catalog.dsl()

    @router.post("/jobs", status_code=202, response_model=Job, operation_id="research_submit_job")
    def submit_job(payload: JobSpec, idempotency_key: str = Header(...), a: Actor = Depends(actor)):
        return tasks().submit(payload, a, idempotency_key)

    @router.get("/jobs", response_model=Page[Job], operation_id="research_list_jobs")
    def list_jobs(cursor: str | None = None, limit: int = Query(50, ge=1, le=200), status: str | None = None, a: Actor = Depends(actor)):
        return tasks().list(a, cursor=cursor, limit=limit, status=status)

    @router.get("/jobs/{job_id}", response_model=Job, operation_id="research_get_job")
    def get_job(job_id: str, a: Actor = Depends(actor)):
        return tasks().get(job_id, a)

    @router.post("/jobs/{job_id}/cancel", response_model=Job, operation_id="research_cancel_job")
    def cancel_job(job_id: str, a: Actor = Depends(actor)):
        return tasks().cancel(job_id, a)

    @router.delete("/jobs/{job_id}", operation_id="research_delete_job")
    def delete_job(job_id: str, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return tasks().delete(job_id, a)

    @router.get("/jobs/{job_id}/result", response_model=Result, operation_id="research_job_result")
    def job_result(job_id: str, a: Actor = Depends(actor)):
        return tasks().read_result(job_id, a)

    @router.get("/jobs/{job_id}/logs", operation_id="research_job_logs", response_model=JobLogs)
    def job_logs(job_id: str, cursor: int = Query(0, ge=0), limit: int = Query(65536, ge=1, le=65536), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return tasks().logs(job_id, a, cursor=cursor, limit=limit)

    @router.post("/factors/validate", operation_id="research_validate_factors", response_model=ValidationResults)
    def validate_factors(payload: FactorValidation, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        with assets().lock("factor"):
            system = engine_factory().get_system("factor")
            system.database.reload()
            from .validation import validate_expression
            return {"results": [validate_expression(system, e) for e in payload.expressions]}

    @router.get("/factors/categories", operation_id="research_factor_categories", response_model=CategoryList)
    def categories(a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        with assets().lock("factor"):
            system = engine_factory().get_system("factor")
            return {"categories": system.list_categories(), "supports_categories": system.supports_categories,
                    "items": [asset_view(r) for r in assets().all("factor_category", a)]}

    @router.post("/factors/categories", operation_id="research_create_category", response_model=Asset, status_code=201)
    def category_create(payload: CategoryEdit, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read", "research:write")
        with assets().lock("factor", "write"):
            engine_factory().get_system("factor").create_category(payload.name)
            return asset_view(next(r for r in assets().all("factor_category", a) if r["name"] == payload.name))

    @router.patch("/factors/categories/{name}", operation_id="research_rename_category", response_model=Asset)
    def category_rename(name: str, payload: CategoryEdit, if_match: str | None = Header(None), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read", "research:write")
        with assets().lock("factor", "write"):
            row = assets().get("factor_category", name, a)
            AssetService.check_version(row, if_match)
            engine_factory().get_system("factor").rename_category(row["name"], payload.name)
            assets()._rename("factor_category", row["id"], payload.name)
            return asset_view(assets().get("factor_category", name, a))

    @router.delete("/factors/categories/{name}", operation_id="research_delete_category")
    def category_delete(name: str, if_match: str | None = Header(None), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read", "research:write")
        with assets().lock("factor", "write"):
            row = assets().get("factor_category", name, a)
            AssetService.check_version(row, if_match)
            deleted = engine_factory().get_system("factor").delete_category(row["name"])
            with store().connect(write=True) as db:
                db.execute("UPDATE assets SET deleted=1,revision=revision+1 WHERE id=?", (row["id"],))
            return {"deleted": deleted}

    @router.post("/factors/categories/members", operation_id="research_category_members")
    def category_members(payload: CategoryMembers, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read", "research:write")
        with assets().lock("factor", "write"):
            rows = [assets().get("factor", item.id, a) for item in payload.factors]
            for row, item in zip(rows, payload.factors):
                AssetService.check_version(row, item.revision)
            system = engine_factory().get_system("factor")
            for row in rows:
                old = set(row.get("categories", []))
                new = old | {payload.category} if payload.op == "add" else old - {payload.category} if payload.op == "remove" else {payload.category}
                system.set_factor_categories(row["name"], sorted(new))
            return {"updated": [r["id"] for r in rows]}

    @router.get("/factors/duplicates", operation_id="research_factor_duplicates")
    def duplicates(a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        with assets().lock("factor"):
            return public_value(engine_factory().get_system("factor").find_duplicate_factors())

    @router.post("/factors", status_code=201, response_model=Asset, operation_id="research_create_factor")
    def create_factor(payload: FactorCreate, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return asset_view(assets().factor_create(payload, a))

    @router.patch("/factors/{key}", response_model=Asset, operation_id="research_update_factor")
    def update_factor(key: str, payload: FactorUpdate, if_match: str | None = Header(None), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return asset_view(assets().factor_update(key, payload, if_match, a))

    @router.post("/strategies", status_code=201, response_model=Asset, operation_id="research_create_strategy")
    def create_strategy(payload: StrategyCreate, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return asset_view(assets().strategy_create(payload, a))

    @router.put("/strategies/{key}", response_model=Asset, operation_id="research_update_strategy")
    def update_strategy(key: str, payload: StrategyCreate, if_match: str | None = Header(None), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return asset_view(assets().strategy_create(payload, a, replace_id=key, expected=if_match))

    @router.post("/stock-pools", status_code=201, response_model=Asset, operation_id="research_create_stock_pool")
    def create_pool(payload: StockPoolCreate, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return asset_view(assets().pool_save(payload, a))

    @router.patch("/stock-pools/{key}", response_model=Asset, operation_id="research_update_stock_pool")
    def update_pool(key: str, payload: StockPoolUpdate, if_match: str | None = Header(None), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return asset_view(assets().pool_save(payload, a, key=key, expected=if_match))

    def exchange_routes(plural: str, kind: str):
        @router.post("/" + plural + "/export", response_model=Artifact, operation_id="research_export_" + kind)
        def export_rows(payload: ExportRequest, a: Actor = Depends(actor)):
            from .exchange import export_assets
            return export_assets(assets(), kind, payload.ids, a)

        @router.post("/" + plural + "/import", operation_id="research_import_" + kind)
        def import_rows(payload: ImportRequest, dataset_id: str | None = None, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
            from .exchange import import_assets
            return import_assets(assets(), kind, payload.upload_id, a, dataset_id)

    for plural, kind in (("factors", "factor"), ("strategies", "strategy"), ("stock-pools", "stock_pool")):
        exchange_routes(plural, kind)

    # Register collection/member reads after static factor routes.
    def asset_routes(plural: str, kind: str):
        @router.get("/" + plural, operation_id="research_list_" + plural.replace("-", "_"), response_model=Page[Asset])
        def asset_list(cursor: str | None = None, limit: int = Query(50, ge=1, le=200), a: Actor = Depends(actor)):
            result = assets().list(kind, a, cursor=cursor, limit=limit)
            return {**result, "items": [asset_view(r) for r in result["items"]]}

        @router.get("/" + plural + "/{key}", response_model=Asset, operation_id="research_get_" + kind)
        def asset_get(key: str, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
            return asset_view(assets().get(kind, key, a))

        @router.delete("/" + plural + "/{key}", operation_id="research_delete_" + kind)
        def asset_delete(key: str, if_match: str | None = Header(None), dataset_id: str | None = None, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
            return assets().delete(kind, key, if_match, a, dataset_id=dataset_id)

    for plural, kind in (("factors", "factor"), ("strategies", "strategy"), ("stock-pools", "stock_pool"), ("signal-sessions", "signal_session")):
        asset_routes(plural, kind)

    @router.post("/signal-sessions", status_code=201, response_model=Asset, operation_id="research_create_signal_session")
    def create_session(payload: SessionCreate, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read", "signals:write")
        service = assets()
        with service.lock("signal_session", "write", [{"resource": service.resource("strategy"), "mode": "read"}]):
            strategy = service.get("strategy", payload.strategy_id, a)
            engine_factory().get_module("daily_trade").trade_session_create(name=payload.name, strategy_name=strategy["name"], init_cash=payload.init_cash)
            return asset_view(next(r for r in service.all("signal_session", a) if r["name"] == payload.name))

    @router.post("/signal-sessions/{key}/cash", operation_id="research_signal_cash")
    def cash_change(key: str, payload: CashChange, if_match: str | None = Header(None), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read", "signals:write")
        with assets().lock("signal_session", "write"):
            row = assets().get("signal_session", key, a)
            AssetService.check_version(row, if_match)
            from alphapilot.systems.backtest.live.session import adjust_cash
            return adjust_cash(row["name"], payload.delta, note=payload.note)

    @router.get("/signal-sessions/{key}/history", operation_id="research_signal_history")
    def session_history(key: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=200), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        from alphapilot.systems.backtest.live import session
        row = assets().get("signal_session", key, a)
        return page(session.read_log(row["name"]), cursor, limit)

    @router.get("/signal-sessions/{key}/cashflows", response_model=Page[dict[str, JsonValue]], operation_id="research_signal_cashflows")
    def session_cashflows(key: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=200), a: Actor = Depends(actor)):
        from alphapilot.systems.backtest.live import session
        row = assets().get("signal_session", key, a)
        return page(session.read_cashflows(row["name"]), cursor, limit)

    @router.get("/runs", response_model=Page[Run], operation_id="research_list_runs")
    def runs(cursor: str | None = None, limit: int = Query(50, ge=1, le=200), a: Actor = Depends(actor)):
        result = artifacts().runs(a, cursor=cursor, limit=limit)
        return {**result, "items": [run_view(r) for r in result["items"]]}

    @router.delete("/runs/{run_id}", operation_id="research_delete_run")
    def delete_run(run_id: str, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:write")
        row = artifacts().run(run_id, a)
        with store().connect(write=True) as db:
            job = db.execute("SELECT status FROM jobs WHERE id=?", (row["job_id"],)).fetchone() if row["job_id"] else None
            if job and job["status"] not in {"succeeded", "failed", "cancelled", "lost"}:
                raise ResearchError("RUN_ACTIVE", "Cancel the owning job and wait for termination before deleting its run", 409)
            db.execute("DELETE FROM runs WHERE id=?", (run_id,))
            db.execute("UPDATE artifacts SET published=0 WHERE run_id=?", (run_id,))
        return {"run_id": run_id, "deleted": True}

    @router.get("/runs/{run_id}", response_model=Run, operation_id="research_get_run")
    def get_run(run_id: str, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return run_view(artifacts().run(run_id, a))

    @router.get("/artifacts/{artifact_id}", response_model=Artifact, operation_id="research_get_artifact")
    def get_artifact(artifact_id: str, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return artifacts().get(artifact_id, a)

    @router.get("/artifacts/{artifact_id}/content", operation_id="research_artifact_content", response_class=FileResponse)
    def artifact_content(artifact_id: str, a: Actor = Depends(actor)):
        metadata = artifacts().get(artifact_id, a)
        return FileResponse(artifacts().get(artifact_id, a, content=True), media_type=metadata["media_type"], filename=metadata["name"])

    @router.get("/artifacts/{artifact_id}/table", operation_id="research_artifact_table")
    def artifact_table(artifact_id: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=200), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return artifacts().table(artifact_id, a, cursor=cursor, limit=limit)

    @router.get("/artifacts/{artifact_id}/series", operation_id="research_artifact_series", response_model=Series)
    def artifact_series(artifact_id: str, max_points: int = Query(1000, ge=2, le=5000), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        import pandas as pd
        path = artifacts().get(artifact_id, a, content=True)
        if path.suffix != ".csv":
            raise ResearchError("NOT_A_SERIES", "Expected a CSV series artifact", 422)
        frame = pd.read_csv(path)
        total = len(frame)
        if total > max_points:
            indices = sorted({round(i * (total - 1) / (max_points - 1)) for i in range(max_points)})
            frame = frame.iloc[indices]
        return {"rows": json_value(frame.to_dict("records")), "total_points": total, "returned_points": len(frame),
                "downsampled": len(frame) < total, "sampling": "evenly_spaced"}

    @router.post("/uploads", status_code=201, operation_id="research_upload", response_model=Upload)
    async def upload(file: UploadFile = File(...), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return await UploadService(store()).save(file, a)

    @router.delete("/uploads/{key}", operation_id="research_delete_upload")
    def delete_upload(key: str, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return UploadService(store()).delete(key, a)

    @router.get("/report-factors/ocr-providers", operation_id="research_ocr_providers")
    def ocr_providers(a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        return public_value(engine_factory().get_module("report_factor").ocr_providers())

    @router.post("/report-factors/commit", operation_id="research_commit_report_factors")
    def report_commit(payload: ReportCommit, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read", "research:write")
        job = tasks().get(payload.job_id, a)
        if job["kind"] != "report_factor_extract" or job["status"] != "succeeded":
            raise ResearchError("RESULT_NOT_READY", "A completed report extraction is required", 409)
        result = tasks().read_result(payload.job_id, a)["summary"]
        allowed = {r["draft_id"] for r in (result or {}).get("factors", [])}
        if any(f.draft_id not in allowed for f in payload.factors):
            raise ResearchError("UNKNOWN_DRAFT", "Draft does not belong to this extraction", 422)
        with assets().lock("factor", "write"):
            return public_value(engine_factory().get_module("report_factor").commit_factors(payload.job_id, [f.model_dump() for f in payload.factors]))

    @router.get("/schedules", response_model=Page[Schedule], operation_id="research_list_schedules")
    def schedules(cursor: str | None = None, limit: int = Query(50, ge=1, le=200), a: Actor = Depends(actor)):
        return page(ScheduleService(tasks()).all(a), cursor, limit)

    @router.post("/schedules", status_code=201, operation_id="research_create_schedule", response_model=Schedule)
    def create_schedule(payload: ScheduleCreate, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return ScheduleService(tasks()).save(payload, a)

    @router.put("/schedules/{key}", operation_id="research_update_schedule", response_model=Schedule)
    def update_schedule(key: str, payload: ScheduleCreate, if_match: str | None = Header(None), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return ScheduleService(tasks()).save(payload, a, key=key, expected=if_match, require_existing=True)

    @router.delete("/schedules/{key}", operation_id="research_delete_schedule")
    def delete_schedule(key: str, if_match: str | None = Header(None), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        return ScheduleService(tasks()).delete(key, a, if_match)

    @router.post("/schedules/{key}/run", response_model=Job, status_code=202, operation_id="research_run_schedule")
    def run_schedule(key: str, idempotency_key: str = Header(...), a: Actor = Depends(actor)):
        return ScheduleService(tasks()).run(key, a, idempotency_key)

    @router.get("/schedules/runtime/status", operation_id="research_schedule_status")
    def schedule_status(a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        from .runtime import status
        return {**status(store()), "paused": store().setting("schedules_paused", False)}

    @router.post("/schedules/runtime/{action}", operation_id="research_schedule_control")
    def schedule_control(action: Literal["start", "stop"], a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("schedules:write")
        store().set_setting("schedules_paused", action == "stop")
        if action == "start":
            from .runtime import ensure_running
            ensure_running(store())
        return {"paused": action == "stop"}

    @router.get("/datasets/{dataset_id}/symbols", operation_id="research_dataset_symbols", response_model=Page[str])
    def dataset_symbols(dataset_id: str, cursor: str | None = None, limit: int = Query(50, ge=1, le=200), a: Actor = Depends(actor)):
        a.require("research:read")
        from alphapilot.modules.data_viz.loader import list_symbols
        row = Catalog(engine_factory()).dataset(dataset_id)
        from .execution import ResourceLockService
        with ResourceLockService(store()).hold(Catalog.resources(row)):
            return page(list_symbols(Path(row["raw_dir"])), cursor, limit)

    @router.get("/datasets/{dataset_id}/bars", operation_id="research_dataset_bars")
    def dataset_bars(dataset_id: str, symbol: str, cursor: str | None = None, limit: int = Query(200, ge=1, le=200), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        import pandas as pd
        row = Catalog(engine_factory()).dataset(dataset_id)
        target = Path(row["raw_dir"]) / (opaque(symbol) + ".csv")
        if not target.is_file():
            raise ResearchError("NOT_FOUND", "Symbol bars not found", 404)
        from .execution import ResourceLockService
        with ResourceLockService(store()).hold(Catalog.resources(row)):
            df = pd.read_csv(target)
        return {"symbol": symbol, "dataset_id": dataset_id, **page(json_value(df.to_dict("records")), cursor, limit)}

    @router.post("/commands/plan", operation_id="research_plan_command")
    def command_plan(payload: CommandRequest, a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read", "jobs:submit")
        from alphapilot.systems.notify.commands import plan_natural_language
        return public_value(plan_natural_language(payload.text).to_dict())

    @router.post("/commands/dispatch", operation_id="research_dispatch_command")
    def command_dispatch(payload: CommandRequest, idempotency_key: str = Header(...), a: Actor = Depends(actor)) -> dict[str, JsonValue]:
        a.require("research:read")
        from .channels import dispatch_authenticated
        return dispatch_authenticated(payload.text, a, tasks(), idempotency_key)

    @router.api_route("/{unmatched:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_research_route(unmatched: str):
        raise ResearchError("NOT_FOUND", "Research API route not found", 404)

    # The retired paths remain explicit middleware errors, absent from OpenAPI.
    app.router.routes[:] = [r for r in app.router.routes if not removed(getattr(r, "path", ""))]
    app.include_router(router)
    app.state.research_router = router
