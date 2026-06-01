"""JSON/dict factor loaders owned by factor system."""

from __future__ import annotations

import json
import os
from importlib import import_module
from pathlib import Path
from typing import Any, Mapping, Sequence

from alphapilot.components.benchmark.eval_method import TestCase, TestCases
from alphapilot.components.coder.factor_coder.factor import FactorFBWorkspace, FactorTask
from alphapilot.components.loader.experiment_loader import FactorExperimentLoader

DEFAULT_FACTOR_EXPERIMENT_CLASS = (
    "alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment.QlibFactorExperiment"
)


def _resolve_factor_experiment_class() -> type:
    class_path = os.getenv("ALPHAPILOT_FACTOR_EXPERIMENT_CLASS", DEFAULT_FACTOR_EXPERIMENT_CLASS)
    module_path, class_name = class_path.rsplit(".", 1)
    return getattr(import_module(module_path), class_name)


def _build_task_from_mapping(item: Mapping[str, Any], default_name: str | None = None) -> FactorTask:
    factor_name = (
        item.get("factor_name")
        or item.get("name")
        or default_name
        or "unnamed_factor"
    )
    formulation = item.get("formulation") or item.get("factor_expression") or ""
    description = item.get("description") or item.get("factor_description") or str(factor_name)
    variables = item.get("variables") or {}
    return FactorTask(
        factor_name=factor_name,
        factor_description=description,
        factor_formulation=formulation,
        variables=variables,
    )


class FactorExperimentLoaderFromDict(FactorExperimentLoader):
    """Load factor tasks from dict-like payloads."""

    def load(self, factor_dict: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> Any:
        task_l: list[FactorTask] = []

        if isinstance(factor_dict, Sequence) and not isinstance(factor_dict, (str, bytes, bytearray)):
            for item in factor_dict:
                task_l.append(_build_task_from_mapping(item))
        else:
            for factor_name, factor_data in factor_dict.items():
                if not isinstance(factor_data, Mapping):
                    continue
                task_l.append(_build_task_from_mapping(factor_data, default_name=factor_name))

        exp_cls = _resolve_factor_experiment_class()
        return exp_cls(sub_tasks=task_l)


class FactorExperimentLoaderFromJsonFile(FactorExperimentLoader):
    def load(self, json_file_path: Path) -> Any:
        with open(json_file_path, "r", encoding="utf-8") as file:
            factor_dict = json.load(file)
        return FactorExperimentLoaderFromDict().load(factor_dict)


class FactorExperimentLoaderFromJsonString(FactorExperimentLoader):
    def load(self, json_string: str) -> Any:
        factor_dict = json.loads(json_string)
        return FactorExperimentLoaderFromDict().load(factor_dict)


class FactorTestCaseLoaderFromJsonFile:
    def load(self, json_file_path: Path) -> TestCases:
        with open(json_file_path, "r", encoding="utf-8") as file:
            factor_dict = json.load(file)
        test_cases = TestCases()
        for factor_name, factor_data in factor_dict.items():
            task = _build_task_from_mapping(factor_data, default_name=factor_name)
            gt = FactorFBWorkspace(task, raise_exception=False)
            code = {"factor.py": factor_data["gt_code"]}
            gt.inject_code(**code)
            test_cases.test_case_l.append(TestCase(task, gt))
        return test_cases
