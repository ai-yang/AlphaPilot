"""Versioned research assets backed by the existing domain systems."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

from .artifacts import public_value
from .auth import Actor, AuthService
from .catalog import Catalog
from .common import ResearchError, digest, json_value
from .execution import ResourceLockService, resource_path
from .models import FactorCreate, FactorUpdate, StockPoolCreate, StockPoolUpdate, StrategyCreate
from .store import Store
from .tasks import page


class AssetService:
    def __init__(self, engine, store: Store):
        self.engine, self.store = engine, store
        self.catalog = Catalog(engine)
        self.locks = ResourceLockService(store)

    def resource(self, kind: str, name: str | None = None) -> str:
        from alphapilot.kernel.paths import stock_pools_dir
        from alphapilot.systems.backtest.live.session import default_sessions_root
        roots = {"factor": self.engine.config.factor.zoo_dir, "factor_category": self.engine.config.factor.zoo_dir,
                 "strategy": self.engine.config.strategy.param_dir,
                 "stock_pool": stock_pools_dir(), "signal_session": default_sessions_root()}
        root = roots[kind]
        if name and kind in {"strategy", "signal_session"}:
            from alphapilot.systems.strategy.database import FileStrategyParamDatabase
            root = Path(root) / FileStrategyParamDatabase._sanitize_name(name)
        return resource_path(root)

    def lock(self, kind: str, mode: str = "read", extra: list | None = None):
        return self.locks.hold([{"resource": self.resource(kind), "mode": mode}, *(extra or [])])

    def _records(self, kind: str) -> list[dict]:
        if kind == "factor_category":
            system = self.engine.get_system("factor")
            system.database.reload()
            return [{"name": name, "members": [r["factor_name"] for r in system.factors_in_category(name)]} for name in system.list_categories()]
        if kind == "factor":
            system = self.engine.get_system("factor")
            # Regulator caches are process-local; reload before reading a shared zoo.
            system.database.reload()
            return [{**row, "name": row["factor_name"], "expression": row["factor_expression"]}
                    for row in system.list_factors()]
        if kind == "strategy":
            return [{**json_value(r), "name": r.strategy_name}
                    for r in self.engine.get_system("strategy").list_strategy_records()]
        if kind == "stock_pool":
            module = self.engine.get_module("stock_pool")
            return [module.pool_show(row["name"]) for row in module.pool_list()]
        if kind == "signal_session":
            from alphapilot.systems.backtest.live import session
            return [session.load_session(row["name"]) for row in session.list_sessions()]
        raise ResearchError("INVALID_ASSET", "Unknown research asset type", 422)

    def _indexed(self, kind: str, records: list[dict]) -> list[dict]:
        output = []
        with self.store.connect(write=True) as db:
            for record in records:
                name = record.get("name") or record.get("manifest", {}).get("name")
                fingerprint = digest(record)
                row = db.execute("SELECT * FROM assets WHERE kind=? AND name=?", (kind, name)).fetchone()
                if row and row["deleted"]:
                    db.execute("UPDATE assets SET name=? WHERE id=?", ("deleted:" + row["id"], row["id"]))
                    row = None
                if row:
                    key = row["id"]
                    revision = row["revision"] + int(row["fingerprint"] != fingerprint or bool(row["deleted"]))
                    db.execute("UPDATE assets SET revision=?,fingerprint=?,deleted=0 WHERE id=?", (revision, fingerprint, key))
                else:
                    key, revision = uuid.uuid4().hex, 1
                    db.execute("INSERT INTO assets VALUES (?,?,?,?,?,0)", (key, kind, name, revision, fingerprint))
                output.append({**record, "id": key, "name": name, "revision": revision, "kind": kind})
            live_ids = {record["id"] for record in output}
            for row in db.execute("SELECT id FROM assets WHERE kind=? AND deleted=0", (kind,)).fetchall():
                if row[0] not in live_ids:
                    db.execute("UPDATE assets SET deleted=1,revision=revision+1 WHERE id=?", (row[0],))
        return output

    def all(self, kind: str, actor: Actor, *, private: bool = False) -> list[dict]:
        actor.require("research:read")
        with self.lock(kind):
            rows = self._indexed(kind, self._records(kind))
        return rows if private else public_value(rows)

    def list(self, kind: str, actor: Actor, *, cursor=None, limit=50) -> dict:
        return page(sorted(self.all(kind, actor), key=lambda row: row["id"]), cursor, limit)

    def get(self, kind: str, key: str, actor: Actor, *, private: bool = False) -> dict:
        row = next((row for row in self.all(kind, actor, private=private) if row["id"] == key), None)
        if not row:
            raise ResearchError("NOT_FOUND", f"{kind} asset not found", 404)
        return row

    @staticmethod
    def check_version(row: dict, expected: str | int | None) -> None:
        if expected is None:
            raise ResearchError("PRECONDITION_REQUIRED", "If-Match asset revision is required", 428)
        if str(expected).strip('"') != str(row["revision"]):
            raise ResearchError("VERSION_CONFLICT", "Asset changed; reload before editing", 412,
                                details={"current_revision": row["revision"]})

    def factor_create(self, request: FactorCreate, actor: Actor) -> dict:
        actor.require("research:read", "research:write")
        with self.lock("factor", "write"):
            system = self.engine.get_system("factor")
            system.database.reload()
            result = system.add_factor(request.name, request.expression, categories=request.categories)
            if not result.acceptable:
                raise ResearchError(result.code, result.message, 422, details=json_value(result.details))
            row = next(r for r in self.all("factor", actor) if r["name"] == request.name)
        self._audit(actor, "factor.create", row)
        return row

    def factor_update(self, key: str, request: FactorUpdate, expected, actor: Actor) -> dict:
        actor.require("research:read", "research:write")
        with self.lock("factor", "write"):
            row = self.get("factor", key, actor)
            self.check_version(row, expected)
            system = self.engine.get_system("factor")
            name = row["name"]
            if request.name and request.name != name:
                system.rename_factor(name, request.name)
                self._rename("factor", key, request.name)
                name = request.name
            if request.categories is not None:
                system.set_factor_categories(name, request.categories)
            result = self.get("factor", key, actor)
        self._audit(actor, "factor.update", result)
        return result

    def _rename(self, kind: str, key: str, name: str) -> None:
        with self.store.connect(write=True) as db:
            other = db.execute("SELECT id FROM assets WHERE kind=? AND name=? AND id<>?", (kind, name, key)).fetchone()
            if other:
                # The domain has already checked a live-name collision. A deleted
                # registry name must not steal the renamed asset's stable ID.
                db.execute("UPDATE assets SET name=? WHERE id=?", ("deleted:" + other[0], other[0]))
            db.execute("UPDATE assets SET name=? WHERE id=?", (name, key))

    def strategy_create(self, request: StrategyCreate, actor: Actor, *, replace_id=None, expected=None) -> dict:
        actor.require("research:read", "research:write")
        with self.lock("strategy", "write", [{"resource": self.resource("factor"), "mode": "read"}, {"resource": self.resource("strategy", request.name), "mode": "write"}]):
            rows = self.all("strategy", actor)
            if replace_id:
                old = self.get("strategy", replace_id, actor)
                self.check_version(old, expected)
                if old["name"] != request.name:
                    raise ResearchError("INVALID_NAME", "Strategy updates preserve the name; create a new asset to rename", 422)
            elif any(r["name"] == request.name for r in rows):
                raise ResearchError("ALREADY_EXISTS", "Strategy name already exists", 409)
            names = [self.get("factor", key, actor)["name"] for key in request.factor_ids]
            dataset = self.catalog.dataset(request.dataset_id)
            template = self.catalog.template(request.template_id)
            if request.model_id != "lgbm":
                raise ResearchError("NOT_FOUND", "Model is not registered", 404)
            pool = self.get("stock_pool", request.stock_pool_id, actor)["name"] if request.stock_pool_id else "all"
            params = {**template["parameters"], **request.parameters.model_dump(mode="json", exclude_none=True),
                      "provider_uri": dataset["qlib_dir"], "freq": dataset["freq"], "template_type": template["template_type"]}
            from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams
            QlibYamlParams(**params)
            self.engine.get_system("strategy").create_strategy_from_factors(
                strategy_name=request.name, factor_names=names, model_name="LGBModel", market=pool, yaml_params=params)
            system = self.engine.get_system("strategy")
            record = system.get_strategy(request.name)
            record.metadata["research_recipe"] = request.model_dump(mode="json")
            system.register_strategy(record)
            result = next(r for r in self.all("strategy", actor) if r["name"] == request.name)
        self._audit(actor, "strategy.save", result)
        return result

    def strategy_import(self, request, actor: Actor) -> dict:
        """Import a portable research recipe, without trusting executable state."""
        from .models import PortableStrategy
        from .validation import validate_expression
        from alphapilot.systems.strategy.base import StrategyRecord, StrategyModelSpec
        from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams
        request = PortableStrategy.model_validate(request)
        actor.require("research:read", "research:write")
        if not request.dataset_id:
            raise ResearchError("DATASET_REQUIRED", "Select a target dataset_id when importing a historical strategy", 422)
        dataset = self.catalog.dataset(request.dataset_id)
        template = self.catalog.template(request.template_id)
        params = {**template["parameters"], **request.parameters.model_dump(mode="json", exclude_none=True),
                  "template_type": template["template_type"], "provider_uri": dataset["qlib_dir"], "freq": dataset["freq"]}
        QlibYamlParams(**params)
        with self.lock("strategy", "write", [{"resource": self.resource("factor"), "mode": "read"}]):
            if any(r["name"] == request.name for r in self.all("strategy", actor)):
                raise ResearchError("ALREADY_EXISTS", "Strategy name already exists", 409)
            if request.stock_pool_name and request.stock_pool_name not in {r["name"] for r in self.all("stock_pool", actor)}:
                raise ResearchError("NOT_FOUND", "Register the strategy's stock pool before importing", 404)
            system = self.engine.get_system("factor")
            expressions = []
            for expression in request.factor_expressions:
                check = validate_expression(system, expression)
                if not check["valid"]:
                    raise ResearchError("INVALID_EXPRESSION", "Imported strategy expression is invalid", 422, details=check)
                expressions.append(check["normalized_expression"])
            market = request.stock_pool_name or "all"
            params["market"] = market
            self.engine.get_system("strategy").register_strategy(StrategyRecord(
                strategy_name=request.name, factor_formulas=expressions, model=StrategyModelSpec(model_name="LGBModel"),
                metadata={"source": "portable_import", "market": market, "yaml_params": params,
                          "research_import": request.model_dump(mode="json"), "requires_retrain": True}))
            row = next(r for r in self.all("strategy", actor) if r["name"] == request.name)
        self._audit(actor, "strategy.import", row)
        return row

    def pool_save(self, request: StockPoolCreate | StockPoolUpdate, actor: Actor, *, key=None, expected=None) -> dict:
        actor.require("research:read", "research:write", "data:write")
        dataset = self.catalog.dataset(request.dataset_id)
        with self.lock("stock_pool", "write", self.catalog.resources(dataset, "write")):
            from alphapilot.systems.data.stock_pool import StockPoolRepository
            config = copy.copy(self.engine.config.data)
            config.qlib_data_dir, config.raw_data_dir = Path(dataset["qlib_dir"]), Path(dataset["raw_dir"])
            repository = StockPoolRepository(config)
            if key:
                old = self.get("stock_pool", key, actor)
                self.check_version(old, expected)
                name = old["name"]
                if request.name and request.name != name:
                    repository.rename_pool(name, request.name)
                    self._rename("stock_pool", key, request.name)
                    name = request.name
                repository.save_pool(name, request.symbols if request.symbols is not None else old["symbols"],
                                     request.description if request.description is not None else old.get("description", ""), replace=True)
            else:
                name = request.name
                repository.save_pool(name, request.symbols, request.description, replace=False)
            result = next(r for r in self.all("stock_pool", actor) if r["name"] == name)
        self._audit(actor, "stock_pool.save", result)
        return result

    def delete(self, kind: str, key: str, expected, actor: Actor, *, dataset_id=None) -> dict:
        actor.require("research:read", "signals:write" if kind == "signal_session" else "research:write")
        observed = self.get(kind, key, actor)
        extra = [{"resource": self.resource(kind, observed["name"]), "mode": "write"}] if kind in {"strategy", "signal_session"} else []
        if kind == "stock_pool":
            actor.require("data:write")
            if not dataset_id:
                raise ResearchError("DATASET_REQUIRED", "Deleting a stock pool requires its target dataset_id", 422)
            extra = self.catalog.resources(self.catalog.dataset(dataset_id), "write")
        with self.lock(kind, "write", extra):
            row = self.get(kind, key, actor)
            self.check_version(row, expected)
            name = row["name"]
            if kind == "factor":
                self.engine.get_system("factor").delete_factor(name)
            elif kind == "strategy":
                self.engine.get_system("strategy").delete_strategy(name)
            elif kind == "stock_pool":
                from alphapilot.systems.data.stock_pool import StockPoolRepository
                config = copy.copy(self.engine.config.data)
                config.qlib_data_dir = Path(self.catalog.dataset(dataset_id)["qlib_dir"])
                StockPoolRepository(config).delete_pool(name)
            else:
                from alphapilot.systems.backtest.live.session import delete_session
                delete_session(name)
            with self.store.connect(write=True) as db:
                db.execute("UPDATE assets SET deleted=1,revision=revision+1 WHERE id=?", (key,))
        self._audit(actor, kind + ".delete", row)
        return {"id": key, "deleted": True}

    def _audit(self, actor: Actor, action: str, row: dict) -> None:
        AuthService(self.store).audit(actor, action, {"id": row["id"], "revision": row["revision"]})
