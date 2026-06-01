"""Compatibility wrapper for factor loader location."""

from alphapilot.systems.factor.loaders.json_loader import (
    FactorExperimentLoaderFromDict,
    FactorExperimentLoaderFromJsonFile,
    FactorExperimentLoaderFromJsonString,
    FactorTestCaseLoaderFromJsonFile,
)

__all__ = [
    "FactorExperimentLoaderFromDict",
    "FactorExperimentLoaderFromJsonFile",
    "FactorExperimentLoaderFromJsonString",
    "FactorTestCaseLoaderFromJsonFile",
]
