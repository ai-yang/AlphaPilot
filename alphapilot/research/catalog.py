"""Server-owned resource catalog; public IDs resolve here, never on the client."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

from .common import ResearchError, digest, json_value
from .execution import resource_path
from .models import BacktestOptions


class Catalog:
    def __init__(self, engine):
        self.engine = engine

    def datasets(self, *, private: bool = False) -> list[dict]:
        from alphapilot.systems.data import data_paths as paths
        from alphapilot.systems.data.frequency import FREQUENCIES
        data = self.engine.get_system("data")
        rows = []
        for source in ("baostock_cn", "tushare_cn"):
            for mode in ("none", "forward", "backward"):
                rows.append({"dataset_id": f"{source}:day:{mode}", "source": source, "freq": "day",
                             "adjust_mode": mode, "raw_dir": str(data._source_raw_dir(mode, source)),
                             "qlib_dir": str(data._source_qlib_dir(source)),
                             "factor_dir": str(data._source_factor_dir(source)),
                             "write_roots": [str(data._source_raw_dir(m, source)) for m in ("none", "forward", "backward")]})
        for freq, spec in FREQUENCIES.items():
            if spec.is_intraday:
                rows.append({"dataset_id": f"baostock_cn:{freq}:none", "source": "baostock_cn",
                             "freq": freq, "adjust_mode": "none", "raw_dir": str(paths.baostock_minute_raw_dir(freq)),
                             "qlib_dir": str(paths.baostock_qlib_dir(freq)), "factor_dir": str(paths.existing_baostock_factor_dir())})
        configured = self._config().get("datasets", [])
        by_id = {row["dataset_id"]: row for row in rows}
        by_id.update({row["dataset_id"]: row for row in configured})
        result = []
        for row in by_id.values():
            row = dict(row)
            row.setdefault("unadjusted_raw_dir", str(data._source_raw_dir("none", row["source"])))
            for key in ("raw_dir", "qlib_dir", "factor_dir", "unadjusted_raw_dir"):
                row[key] = str(Path(row[key]).expanduser().resolve())
            qlib = Path(row["qlib_dir"])
            marker = qlib / ".research-revision.json"
            revision = json.loads(marker.read_text()) if marker.is_file() else {}
            present = (qlib / "features").is_dir() and (qlib / "calendars").is_dir()
            bound = revision.get("source") == row["source"] and revision.get("adjust_mode") == row["adjust_mode"]
            ready = present and bound and not (qlib / ".research-dirty.json").exists()
            row.update(label=row.get("label", row["dataset_id"]), ready=ready,
                       unavailable_reason=None if ready else "Convert this dataset to publish its adjustment mode and a consistent data revision",
                       revision=self.revision(row))
            if not private:
                row = {k: row[k] for k in ("dataset_id", "source", "freq", "adjust_mode", "label", "ready", "unavailable_reason", "revision")}
            result.append(row)
        return result

    @staticmethod
    def _config() -> dict:
        path = os.getenv("ALPHAPILOT_RESEARCH_CATALOG")
        return json.loads(Path(path).read_text()) if path else {}

    def dataset(self, key: str) -> dict:
        row = next((r for r in self.datasets(private=True) if r["dataset_id"] == key), None)
        if row is None:
            raise ResearchError("NOT_FOUND", "Dataset ID is not registered", 404)
        return row

    @staticmethod
    def revision(row: dict) -> str:
        root = Path(row["qlib_dir"])
        # Includes the published revision marker and calendars/instruments. Feature
        # mutations through the common data service update the marker under a write lock.
        paths = [root / ".research-revision.json"]
        for folder in ("calendars", "instruments"):
            paths.extend(sorted((root / folder).glob("*.txt")))
        return digest([(str(p.relative_to(root)), p.stat().st_mtime_ns, p.stat().st_size)
                       for p in paths if p.is_file()])

    @staticmethod
    def resources(row: dict, mode: str = "read") -> list[dict]:
        return [{"resource": resource_path(root), "mode": mode}
                for root in [*(row[key] for key in ("raw_dir", "qlib_dir", "factor_dir")),
                             *([row["unadjusted_raw_dir"]] if mode == "write" and row.get("unadjusted_raw_dir") else []),
                             *(row.get("write_roots", []) if mode == "write" else [])]]

    def templates(self, *, private: bool = False) -> list[dict]:
        from alphapilot.kernel.paths import factor_qlib_templates_dir
        from alphapilot.systems.backtest.qlib_yaml.schema import QlibYamlParams
        from alphapilot.systems.backtest.qlib.template_paths import DEFAULT_QLIB_FACTOR_TEMPLATE_DIR
        directory = factor_qlib_templates_dir()
        if not directory.is_dir():
            directory = DEFAULT_QLIB_FACTOR_TEMPLATE_DIR
        rows = [
            {"template_id": "combined", "label": "Combined factor model", "template_type": "combined",
             "config_name": "conf_cn_combined_kdd_ver.yaml", "directory": str(directory)},
            {"template_id": "baseline", "label": "Baseline model", "template_type": "baseline",
             "config_name": "conf.yaml", "directory": str(directory)},
        ]
        rows.extend(self._config().get("templates", []))
        result = []
        for row in rows:
            row = dict(row)
            defaults = QlibYamlParams(template_type=row["template_type"]).model_dump(mode="json")
            row["parameters"] = {k: defaults[k] for k in BacktestOptions.model_fields}
            path = Path(row["directory"]).expanduser() / row["config_name"]
            if path.is_file():
                row["parameters"].update(template_parameters(path))
            row["parameters"].update(row.get("defaults", {}))
            row["parameters"] = BacktestOptions.model_validate(row["parameters"]).model_dump(mode="json")
            row["ready"] = (Path(row["directory"]).expanduser() / row["config_name"]).is_file()
            row.pop("defaults", None)
            if not private:
                row = {k: v for k, v in row.items() if k not in {"directory", "config_name"}}
            result.append(row)
        return result

    def template(self, key: str) -> dict:
        row = next((r for r in self.templates(private=True) if r["template_id"] == key), None)
        if not row:
            raise ResearchError("NOT_FOUND", "Template ID is not registered", 404)
        return row

    def models(self) -> list[dict]:
        return [{"model_id": "lgbm", "label": "LightGBM", "parameters_schema": "BacktestOptions"}]

    @staticmethod
    def dsl() -> dict:
        import dataclasses
        from alphapilot.components.coder.factor_coder import factor_ast
        operators = [{"name": name, **dataclasses.asdict(spec)}
                     for name, spec in factor_ast._FUNCTION_SIGNATURES.items()]
        from alphapilot.systems.data.qlib_convert import DEFAULT_INCLUDE_FIELDS
        return {"operators": operators, "variables": ["$" + field for field in DEFAULT_INCLUDE_FIELDS.split(",")],
                "validation": "Existing factor syntax and temporal semantics validator",
                "schema_version": "1"}

    @staticmethod
    def algorithms() -> list[dict]:
        return [{"kind": kind, "available": all(importlib.util.find_spec(dep) is not None for dep in deps),
                 "may_use_llm": kind not in {"data", "daily_signals"},
                 "required_dependencies": deps}
                for kind, deps in [("mine", []), ("mine_aff", ["torch"]), ("mine_gp", ["torch"]),
                                   ("mine_rl", ["torch", "stable_baselines3", "sb3_contrib"]),
                                   ("factor_backtest", []), ("strategy_backtest", []), ("data", []),
                                   ("daily_signals", []), ("report_factor_extract", [])]]


def template_parameters(path: Path) -> dict:
    """Read supported defaults from a server-owned Qlib YAML template.

    The v1 model/parameter allowlist is deliberately separate from executable
    Qlib class paths. Registered templates are baseline/combined presets.
    """
    import yaml
    document = yaml.safe_load(path.read_text())
    task = document.get("task", {})
    handler = document.get("data_handler_config", {})
    portfolio = document.get("port_analysis_config", {})
    backtest = portfolio.get("backtest", {})
    values = {"benchmark": document.get("benchmark")}
    for mapping in (handler, task.get("model", {}).get("kwargs", {}),
                    portfolio.get("strategy", {}).get("kwargs", {}),
                    backtest.get("exchange_kwargs", {})):
        values.update({k: v for k, v in mapping.items() if k in BacktestOptions.model_fields})
    values.update({"account": backtest.get("account"), "backtest_start": backtest.get("start_time"),
                   "backtest_end": backtest.get("end_time")})
    segments = task.get("dataset", {}).get("kwargs", {}).get("segments", {})
    for key in ("train", "valid", "test"):
        if key in segments:
            values[key + "_start"], values[key + "_end"] = segments[key]
    for record in task.get("record", []):
        if isinstance(record, dict) and record.get("class") == "SigAnaRecord":
            values.update({k: v for k, v in record.get("kwargs", {}).items() if k in {"ann_scaler", "ana_long_short"}})
    return json_value({k: v for k, v in values.items() if v is not None})
