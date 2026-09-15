"""Validated public requests -> frozen inputs -> existing domain executors."""
from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

from .artifacts import public_value, record_output
from .assets import AssetService
from .auth import Actor
from .catalog import Catalog
from .common import ResearchError, atomic_json, json_value
from .execution import ResourceLockService
from .store import Store


def prepare(engine, store: Store, spec, folder: Path, actor: Actor) -> tuple[dict, dict]:
    assets, catalog = AssetService(engine, store), Catalog(engine)
    input_dir = folder / "inputs"
    input_dir.mkdir()
    normalized = spec.input.model_dump(mode="json")
    data = spec.input
    execution = {"kind": spec.kind, "input": spec.input.model_dump(mode="json"), "resources": [], "folder": str(folder)}
    snapshot_kinds = (["factor"] if spec.kind == "factor_backtest" else []) + (["strategy"] if getattr(data, "strategy_id", None) else []) + (["stock_pool"] if getattr(data, "stock_pool_id", None) else [])
    with ResourceLockService(store).hold([{"resource": assets.resource(k), "mode": "read"} for k in snapshot_kinds]):
        if hasattr(data, "dataset_id"):
            dataset = catalog.dataset(data.dataset_id)
            if spec.kind == "data" and data.action in {"apply_adjust", "apply_adjust_symbol"} and (dataset["freq"] != "day" or dataset["adjust_mode"] == "none"):
                raise ResearchError("INVALID_DATA_OPERATION", "Adjustment synthesis requires a forward/backward daily dataset", 422)
            if spec.kind != "data" and not dataset["ready"]:
                raise ResearchError("DATASET_NOT_READY", "Download and convert the selected dataset first", 409)
            execution["dataset"] = dataset
            write_data = spec.kind == "data" or getattr(data, "refresh_data", False)
            execution["resources"].extend(catalog.resources(dataset, "write" if write_data else "read"))
            if getattr(data, "stock_pool_id", None):
                pool = assets.get("stock_pool", data.stock_pool_id, actor)
                execution["pool"] = pool
                atomic_json(input_dir / "stock_pool.json", pool)
                normalized["stock_pool_revision"] = pool["revision"]
            if hasattr(data, "template_id"):
                template = catalog.template(data.template_id)
                if not template["ready"]:
                    raise ResearchError("TEMPLATE_NOT_READY", "The registered template is unavailable", 409)
                if data.model_id not in {row["model_id"] for row in catalog.models()}:
                    raise ResearchError("NOT_FOUND", "Unknown model ID", 404)
                template_copy = input_dir / "template"
                shutil.copytree(Path(template["directory"]).expanduser(), template_copy)
                execution["template"] = {**template, "directory": str(template_copy)}
                params = {**template["parameters"], **data.parameters.model_dump(mode="json", exclude_none=True)}
                from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams
                QlibYamlParams(**params)
                normalized["parameters"] = params
                execution["parameters"] = {**params, "template_type": template["template_type"]}
        if spec.kind == "factor_backtest":
            if data.factor_source.type == "library":
                factors = [assets.get("factor", key, actor) for key in data.factor_source.factor_ids]
            else:
                factors = [f.model_dump() for f in data.factor_source.factors]
            names = set()
            factor_system = engine.get_system("factor")
            for factor in factors:
                if factor["name"] in names:
                    raise ResearchError("DUPLICATE_FACTOR", "Factor names must be unique in a backtest", 422)
                names.add(factor["name"])
                from .validation import validate_expression
                validation = validate_expression(factor_system, factor["expression"])
                if not validation["valid"]:
                    raise ResearchError("INVALID_EXPRESSION", "Factor syntax or temporal semantics are invalid", 422, details=validation)
                factor["expression"] = validation["normalized_expression"]
            with (input_dir / "factors.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["factor_name", "factor_expression"])
                writer.writeheader()
                writer.writerows({"factor_name": f["name"], "factor_expression": f["expression"]} for f in factors)
            normalized["factors_snapshot"] = factors
        if getattr(data, "strategy_id", None):
            row = assets.get("strategy", data.strategy_id, actor, private=True)
            system = engine.get_system("strategy")
            from alphapilot.systems.strategy.database import FileStrategyParamDatabase
            snapshot = FileStrategyParamDatabase(input_dir / "strategies")
            snapshot.save_record(system.get_strategy(row["name"]))
            execution["strategy_name"] = row["name"]
            normalized["strategy_revision"] = row["revision"]
            if spec.kind == "strategy_backtest":
                execution["resources"].append({"resource": assets.resource("strategy", row["name"]), "mode": "write"})
        if getattr(data, "session_id", None):
            row = assets.get("signal_session", data.session_id, actor)
            execution["session_name"] = row["name"]
            normalized["session_snapshot"] = {"id": row["id"], "revision": row["revision"],
                                               "manifest": row.get("manifest", {})}
            execution["resources"].append({"resource": assets.resource("signal_session", row["name"]),
                                            "mode": "write" if data.mode == "advance" else "read"})
        if spec.kind == "report_factor_extract":
            with store.connect() as db:
                upload = db.execute("SELECT * FROM uploads WHERE id=?", (data.upload_id,)).fetchone()
            if not upload or Path(upload["path"]).suffix.lower() != ".pdf":
                raise ResearchError("NOT_FOUND", "PDF upload not found", 404)
            shutil.copyfile(upload["path"], input_dir / "report.pdf")
        if getattr(data, "save_as", None):
            execution["resources"].append({"resource": assets.resource("strategy", data.save_as), "mode": "write"})
        if getattr(data, "resume_run_id", None):
            with store.connect() as db:
                run = db.execute("SELECT path,payload FROM runs WHERE id=?", (data.resume_run_id,)).fetchone()
            payload = json.loads(run["payload"]) if run else {}
            session_path = payload.get("session_path")
            if not session_path or not Path(session_path).exists():
                raise ResearchError("RESUME_UNAVAILABLE", "This run has no resumable mining session", 409)
            shutil.copytree(session_path, input_dir / "mining_session")
            execution["resume_path"] = str(input_dir / "mining_session")
    atomic_json(input_dir / "request.json", normalized)
    return execution, normalized


def bind_dataset(execution: dict) -> dict:
    """Pin the actual data revision at execution and freeze instrument membership.

    Feature/calendar symlinks stay under the original dataset's read lock; the
    private instruments directory ensures queued pool edits cannot alter a run.
    """
    dataset = execution["dataset"]
    source = Path(dataset["qlib_dir"])
    marker = source / ".research-revision.json"
    revision_info = json.loads(marker.read_text()) if marker.is_file() else {}
    if (not (source / "features").is_dir() or (source / ".research-dirty.json").exists()
            or revision_info.get("source") != dataset["source"]
            or revision_info.get("adjust_mode") != dataset["adjust_mode"]):
        raise ResearchError("DATASET_NOT_READY", "Dataset is unavailable at execution time", 409)
    view = Path(execution["folder"]) / "inputs" / "dataset"
    view.mkdir(exist_ok=True)
    for name in ("features", "calendars"):
        target = view / name
        if not target.exists():
            target.symlink_to(source / name, target_is_directory=True)
    instruments = view / "instruments"
    if not instruments.exists():
        shutil.copytree(source / "instruments", instruments)
    pool = execution.get("pool")
    market = pool["name"] if pool else "all"
    if pool:
        from alphapilot.systems.data.stock_list import baostock_to_qlib_instrument, normalize_to_baostock
        members = {baostock_to_qlib_instrument(normalize_to_baostock(s)) for s in pool["symbols"]}
        all_rows = (instruments / "all.txt").read_text().splitlines()
        selected = [line for line in all_rows if line.split()[0] in members]
        if not selected:
            raise ResearchError("EMPTY_UNIVERSE", "Stock pool has no instruments in this dataset", 422)
        (instruments / f"{market}.txt").write_text("\n".join(selected) + "\n")
    atomic_json(view / ".research-source.json", {"source": str(source.resolve())})
    revision = Catalog.revision(dataset)
    atomic_json(Path(execution["folder"]) / "inputs" / "dataset_revision.json",
                {"dataset_id": dataset["dataset_id"], "revision": revision, "policy": "latest_at_start"})
    return {"provider_uri": str(view), "freq": dataset["freq"], "market": market, "dataset_revision": revision}


def execute(execution: dict):
    from alphapilot.kernel import build_engine
    from alphapilot.systems.run_workspace import run_workspace
    engine = build_engine(discover=True)
    kind, data = execution["kind"], execution["input"]
    folder = Path(execution["folder"])
    try:
        if execution.get("session_name"):
            # Session state may advance while queued, but a deleted/recreated
            # session with the same name must never receive an older command.
            row = AssetService(engine, Store()).get("signal_session", data["session_id"], Actor.local("worker"))
            if row["name"] != execution["session_name"]:
                raise ResearchError("SESSION_CHANGED", "The selected signal session was replaced", 409)
        prior_day = None
        if execution.get("session_name") and data.get("mode") == "advance":
            from alphapilot.systems.backtest.live import session
            prior_day = session.read_history_day(execution["session_name"], data["date"])
        if kind == "daily_signals" and data.get("refresh_data") and prior_day is None:
            refresh = {**execution, "input": {"action": "pipeline", "start_date": data["date"], "end_date": data["date"]}}
            execute_data(engine, refresh)
        binding = bind_dataset(execution) if "dataset" in execution and kind != "data" else {}
        params = {**execution.get("parameters", {}), **{k: v for k, v in binding.items() if k != "dataset_revision"}}
        template = execution.get("template", {})
        if execution.get("strategy_name"):
            from alphapilot.systems.strategy.database import FileStrategyParamDatabase
            snapshot = FileStrategyParamDatabase(folder / "inputs" / "strategies")
            system = engine.get_system("strategy")
            original_get = system.get_strategy
            system.get_strategy = lambda name: snapshot.load_record(name) if name == execution["strategy_name"] else original_get(name)
        with run_workspace(command=kind, market=binding.get("market")) as run:
            run.record(job_id=os.getenv("ALPHAPILOT_PORTAL_JOB_ID"), attempt=os.getenv("ALPHAPILOT_JOB_ATTEMPT"),
                       normalized_input=json.loads((folder / "inputs" / "request.json").read_text()),
                       dataset_revision=binding.get("dataset_revision"))
            if execution.get("session_name"):
                from alphapilot.systems.backtest.live import session
                snapshot = session.load_session(execution["session_name"], history_limit=1)
                atomic_json(folder / "inputs" / "session_at_start.json", snapshot)
                run.record(session_at_start=public_value(snapshot))
            if kind == "factor_backtest":
                result = engine.get_module("alpha_mining").run_backtest(
                    factor_path=str(folder / "inputs" / "factors.csv"), mode=data["mode"],
                    qlib_config_name=template["config_name"], qlib_template_dir=template["directory"],
                    market=binding["market"], freq=binding["freq"], yaml_params=params)
            elif kind == "mine":
                result = engine.get_module("alpha_mining").run_mining(
                    step_n=data["max_steps"], direction=data.get("direction"), path=execution.get("resume_path"),
                    qlib_config_name=template["config_name"], qlib_template_dir=template["directory"],
                    qlib_dir=binding["provider_uri"], market=binding["market"], freq=binding["freq"], yaml_params=params,
                    save_factors_to_library=data["save_factors_to_library"], random_seed=data.get("random_seed"),
                    campaign_id=data.get("campaign_id"))
            elif kind in {"mine_aff", "mine_gp", "mine_rl"}:
                kwargs = {k: v for k, v in data.items() if k not in
                          {"dataset_id", "stock_pool_id", "template_id", "model_id", "parameters"} and v is not None}
                kwargs.update(instruments=binding["market"], freq=binding["freq"], qlib_dir=binding["provider_uri"], backtest=False)
                module = engine.get_module("alphaforge_aff" if kind == "mine_aff" else "alphaforge_search")
                result = getattr(module, kind)(**kwargs)
                if data["backtest"] and result.get("accepted"):
                    record_output(result, "mining_factors")
                    from alphapilot.systems.backtest.types import FactorBacktestRequest, FactorDefinition
                    evaluation = engine.get_system("backtest").run_factor_evaluation(FactorBacktestRequest(
                        factors=[FactorDefinition(factor_name=r["name"], factor_expression=r["dsl"]) for r in result["accepted"]],
                        mode="multi_combined", market=binding["market"], freq=binding["freq"], yaml_params=params,
                        qlib_config_name=template["config_name"], qlib_template_dir=template["directory"],
                        use_local=engine.config.backtest.use_local))
                    result["backtest"] = serialize_result(evaluation)
            elif kind == "strategy_backtest":
                result = engine.get_module("strategy_backtest").strategy_backtest(
                    strategy_name=execution["strategy_name"], mode=data["mode"], save_as=data.get("save_as"),
                    qlib_data_dir=binding["provider_uri"], qlib_config_name=template["config_name"],
                    qlib_template_dir=template["directory"], yaml_params=params, run_tag=run.run_id)
                errors = [r["error"] for r in result if r.get("error")]
                if errors:
                    record_output(result, "strategy_retest")
                    raise ResearchError("STRATEGY_BACKTEST_FAILED", "; ".join(errors), 422)
            elif kind == "data":
                result = execute_data(engine, execution)
            elif kind == "daily_signals":
                result = execute_daily(engine, execution, params)
            elif kind == "report_factor_extract":
                from .runtime import progress
                result = engine.get_module("report_factor").extract_pdf(
                    str(folder / "inputs" / "report.pdf"), ocr_mode=data.get("ocr_provider") or "auto",
                    market=data["market"], frequency=data["frequency"], available_data=data.get("available_data"),
                    progress_callback=progress)
            else:
                raise ResearchError("UNSUPPORTED_JOB", "Unknown job executor", 422)
            result = serialize_result(result)
            record_output(result, "result")
            return result
    finally:
        shutdown = getattr(engine, "shutdown", None)
        if callable(shutdown):
            shutdown()


def serialize_result(result):
    from alphapilot.systems.backtest.types import FactorBacktestResult
    if isinstance(result, FactorBacktestResult):
        return {"mode": result.mode, "metrics": public_value(result.metrics),
                "per_factor": public_value(result.per_factor), "run_ids": getattr(result, "run_ids", [])}
    return public_value(result)


def execute_data(engine, execution):
    data, dataset = execution["input"], execution["dataset"]
    system = engine.get_system("data")
    action = data["action"]
    dirty = Path(dataset["qlib_dir"]) / ".research-dirty.json"
    was_dirty = dirty.exists()
    if not data.get("dry_run"):
        atomic_json(dirty, {"action": action, "job_id": os.getenv("ALPHAPILOT_PORTAL_JOB_ID")})
    pool = execution.get("pool")
    symbols = pool["symbols"] if pool else data.get("symbols")
    options = {"source": dataset["source"], "adjust_mode": dataset["adjust_mode"]}
    unadjusted = dataset.get("unadjusted_raw_dir") or str(system._source_raw_dir("none", dataset["source"]))
    if action in {"download", "update", "pipeline"}:
        raw = dataset["raw_dir"]
        tushare = dataset["source"] == "tushare_cn"
        if tushare and dataset["adjust_mode"] != "none":
            raw = unadjusted
        download_options = {**options, "start_date": data["start_date"], "end_date": data.get("end_date"),
                            "symbols": symbols, "output_dir": raw, "freq": dataset["freq"],
                            "max_workers": data.get("workers", 1), "all_market": not bool(symbols),
                            "factor_dir": dataset["factor_dir"]}
        if tushare:
            download_options.update(adjust_mode="none", include_daily_basic=data.get("include_daily_basic", True),
                                    include_delisted=data.get("include_delisted", False))
        result = system.download(**download_options)
        if tushare and dataset["adjust_mode"] != "none":
            system.apply_adjust(source=dataset["source"], target_mode=dataset["adjust_mode"],
                                raw_dir=raw, factor_dir=dataset["factor_dir"], output_dir=dataset["raw_dir"])
    if action in {"convert", "pipeline"}:
        convert_options = {"data_path": dataset["raw_dir"], "qlib_dir": dataset["qlib_dir"],
                           "freq": dataset["freq"], "adjust_mode": dataset["adjust_mode"],
                           "benchmark_source": dataset["source"], "all_market": not bool(symbols)}
        if symbols:
            path = Path(execution["folder"]) / "inputs" / "stocks.csv"
            with path.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["code"])
                writer.writerows([symbol] for symbol in symbols)
            convert_options.update(stock_csv=str(path), market=pool["name"] if pool else "all")
        result = system.convert(**convert_options)
    elif action == "apply_adjust":
        result = system.apply_adjust(source=dataset["source"], target_mode=dataset["adjust_mode"],
                                     raw_dir=unadjusted,
                                     factor_dir=dataset["factor_dir"], output_dir=dataset["raw_dir"])
    elif action not in {"download", "update", "pipeline"}:
        options["symbol"] = data["symbol"]
        if action == "trim_symbol":
            options.update(start=data.get("start_date"), end=data.get("end_date"), drop_dates=data.get("drop_dates"),
                           qlib_adjust_mode=dataset["adjust_mode"], dry_run=data.get("dry_run", False),
                           raw_dir=dataset["raw_dir"], qlib_dir=dataset["qlib_dir"], freq=dataset["freq"])
        elif action == "refresh_symbol":
            options.update(start_date=data.get("start_date") or "2005-01-01", end_date=data.get("end_date"),
                           qlib_adjust_mode=dataset["adjust_mode"], raw_dir=dataset["raw_dir"],
                           qlib_dir=dataset["qlib_dir"], freq=dataset["freq"], factor_dir=dataset["factor_dir"])
            if data.get("dry_run"):
                return {"dry_run": True, "action": action, "symbol": data["symbol"]}
        elif action == "apply_adjust_symbol":
            options.pop("adjust_mode")
            options.update(target_mode=dataset["adjust_mode"], raw_dir=unadjusted,
                           factor_dir=dataset["factor_dir"], output_dir=dataset["raw_dir"], dry_run=data.get("dry_run", False))
        else:
            options["dry_run"] = data.get("dry_run", False)
            options.update(raw_dir=dataset["raw_dir"], qlib_dir=dataset["qlib_dir"], factor_dir=dataset["factor_dir"])
        result = getattr(system, action)(**options)
    if not data.get("dry_run"):
        marker = Path(dataset["qlib_dir"]) / ".research-revision.json"
        revision = json.loads(marker.read_text()) if marker.exists() else {}
        if action in {"convert", "pipeline"}:
            revision.update(source=dataset["source"], adjust_mode=dataset["adjust_mode"])
        atomic_json(marker, {**revision, "updated_at": __import__("time").time_ns()})
        if not was_dirty or action in {"convert", "pipeline"}:
            dirty.unlink(missing_ok=True)
    return result


def execute_daily(engine, execution, params):
    from alphapilot.modules.daily_trade.module import summarize
    from alphapilot.systems.backtest.live import DailySignalRequest, generate_daily_signal, session
    data = execution["input"]
    name = execution.get("session_name")
    if name and data["mode"] == "advance":
        previous = session.read_history_day(name, data["date"])
        if previous:
            return previous
    request = DailySignalRequest(strategy_name=execution.get("strategy_name"), session=name,
                                 date=data["date"], yaml_params=params, market=params.get("market"),
                                 init_cash=data.get("init_cash"), refresh_data=False,
                                 use_local=engine.config.backtest.use_local)
    result = generate_daily_signal(engine.context, request, persist_state=False)
    summary = summarize(result)
    if data["mode"] == "advance":
        return session.commit_day(name, result.new_state, summary)
    return summary
