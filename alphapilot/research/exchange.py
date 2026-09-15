"""Portable, non-executable research asset import/export."""
from __future__ import annotations

import csv
import json

from .artifacts import ArtifactService
from .assets import AssetService
from .common import ResearchError, json_value
from .models import ASSET_BUNDLE_ADAPTER, BacktestOptions, FactorCreate, StockPoolCreate, PortableStrategy
from .uploads import UploadService


def export_assets(service: AssetService, kind: str, ids: list[str], actor):
    rows = [service.get(kind, key, actor) for key in ids]
    if kind == "factor":
        items = [{"name": r["name"], "expression": r["expression"], "categories": r.get("categories", [])} for r in rows]
    elif kind == "strategy":
        items = []
        for row in rows:
            metadata = row.get("metadata", {})
            recipe = metadata.get("research_recipe") or metadata.get("research_import", {})
            model = row.get("model") or {}
            if model.get("model_name", "lgbm").lower() not in {"lgbm", "lgbmodel", "lightgbm"}:
                raise ResearchError("UNSUPPORTED_MODEL", "Register this strategy model before portable export", 422)
            parameters = metadata.get("yaml_params", recipe.get("parameters", {})) or {}
            pool = metadata.get("market")
            item = PortableStrategy(name=row["name"], factor_expressions=row["factor_formulas"],
                dataset_id=recipe.get("dataset_id"), stock_pool_name=pool if pool and pool != "all" else None,
                template_id=recipe.get("template_id", "combined"),
                parameters={k: v for k, v in parameters.items() if k in BacktestOptions.model_fields})
            items.append(item.model_dump(mode="json"))
    else:
        items = [{"name": r["name"], "symbols": r["symbols"], "description": r.get("description", "")} for r in rows]
    return ArtifactService(service.store).register_json({"schema_version": "1", "kind": kind, "items": items}, kind=f"{kind}_export")


def import_assets(service: AssetService, kind: str, upload_id: str, actor, dataset_id=None):
    actor.require("research:read", "research:write")
    path = UploadService(service.store).get(upload_id, actor, content=True)
    if path.suffix == ".csv" and kind == "factor":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            items = [{"name": r.get("name") or r.get("factor_name"), "expression": r.get("expression") or r.get("factor_expression")} for r in csv.DictReader(stream)]
    elif path.suffix == ".json":
        bundle = json.loads(path.read_text())
        if not isinstance(bundle, dict) or bundle.get("schema_version") != "1" or bundle.get("kind") != kind:
            raise ResearchError("INVALID_IMPORT", "Expected a v1 asset export bundle", 422)
        items = [row.model_dump(mode="json", exclude_none=True) for row in ASSET_BUNDLE_ADAPTER.validate_python(bundle).items]
    else:
        raise ResearchError("INVALID_IMPORT", "Use a JSON export bundle or a factor CSV", 422)
    if not isinstance(items, list) or not 1 <= len(items) <= 1000:
        raise ResearchError("INVALID_IMPORT", "Import requires 1–1000 items", 422)
    model = {"factor": FactorCreate, "strategy": PortableStrategy, "stock_pool": StockPoolCreate}[kind]
    requests = [model.model_validate({**row, **({"dataset_id": dataset_id} if dataset_id and kind in {"stock_pool", "strategy"} else {})}) for row in items]
    results = []
    # Independent item outcomes are explicit. Retrying an import does not overwrite
    # existing assets; edits always require an observed asset revision.
    for request in requests:
        try:
            fn = {"factor": service.factor_create, "strategy": service.strategy_import, "stock_pool": service.pool_save}[kind]
            row = fn(request, actor)
            results.append({"name": request.name, "id": row["id"], "revision": row["revision"], "error": None})
        except ResearchError as exc:
            results.append({"name": request.name, "id": None, "revision": None, "error": exc.payload(actor.request_id)})
    return {"items": results, "imported": sum(r["error"] is None for r in results)}
