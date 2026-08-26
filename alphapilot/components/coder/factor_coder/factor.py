from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Tuple, Union

import pandas as pd
from filelock import FileLock

from alphapilot.components.coder.CoSTEER.task import CoSTEERTask
from alphapilot.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS, resolve_factor_python_bin
from alphapilot.components.coder.factor_coder.data import (
    resolve_factor_data_dir,
    resolve_factor_data_fingerprint,
)
from alphapilot.core.exception import CodeFormatError, CustomRuntimeError, NoOutputError
from alphapilot.core.experiment import Experiment, FBWorkspace
from alphapilot.core.utils import cache_with_pickle
from alphapilot.log import logger
from alphapilot.oai.llm_utils import md5_hash


_FACTOR_ENV_ALLOWLIST = frozenset(
    {
        "CONDA_DEFAULT_ENV",
        "CONDA_PREFIX",
        "CUDA_HOME",
        "CUDA_PATH",
        "CUDA_VISIBLE_DEVICES",
        "DYLD_LIBRARY_PATH",
        "LANG",
        "LANGUAGE",
        "LC_ALL",
        "LD_LIBRARY_PATH",
        "PATH",
        "PATHEXT",
        "PYTHONHASHSEED",
        "PYTHONIOENCODING",
        "PYTHONNOUSERSITE",
        "PYTHONPATH",
        "PYTHONUTF8",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
        "VIRTUAL_ENV",
        "WINDIR",
    }
)
_FACTOR_ENV_PREFIX_ALLOWLIST = (
    "ALPHAPILOT_FACTOR_",
    "KMP_",
    "LC_",
    "MKL_",
    "NUMEXPR_",
    "OMP_",
    "OPENBLAS_",
)

_RUNTIME_PROBE_PREFIX = "__ALPHAPILOT_FACTOR_RUNTIME__="
_RUNTIME_PROBE = rf"""
import hashlib
import importlib.metadata
import importlib.util
import json
import pathlib
import platform
import sys

packages = {{}}
for package in ("numpy", "pandas", "tables", "joblib", "pyparsing"):
    try:
        packages[package] = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        packages[package] = "missing"

sources = {{}}
for module_name in (
    "alphapilot.components.coder.factor_coder.expr_parser",
    "alphapilot.components.coder.factor_coder.function_lib",
):
    spec = importlib.util.find_spec(module_name)
    origin = getattr(spec, "origin", None) if spec is not None else None
    if not origin:
        raise RuntimeError(f"Cannot resolve runtime module {{module_name}}")
    path = pathlib.Path(origin).resolve()
    sources[module_name] = {{
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }}

payload = {{
    "cache_tag": getattr(sys.implementation, "cache_tag", None),
    "executable": str(pathlib.Path(sys.executable).resolve()),
    "packages": packages,
    "platform": platform.platform(),
    "python": sys.version,
    "sources": sources,
}}
print({_RUNTIME_PROBE_PREFIX!r} + json.dumps(payload, sort_keys=True, separators=(",", ":")))
"""


def _factor_subprocess_env(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a minimal execution environment for generated factor code.

    This reduces accidental credential inheritance; it is not a filesystem or
    network sandbox.  Only Python/runtime paths, numerical-library tuning, and
    factor-data variables are passed through.
    """

    source = os.environ if environ is None else environ
    return {
        key: value
        for key, value in source.items()
        if key.upper() in _FACTOR_ENV_ALLOWLIST
        or key.upper().startswith(_FACTOR_ENV_PREFIX_ALLOWLIST)
    }


def _factor_runtime_fingerprint(python_bin: str) -> str | None:
    """Fingerprint the interpreter and sources used by the factor subprocess.

    The probe intentionally runs for every cache-key calculation.  This avoids
    stale results when an external environment or editable source tree changes
    while the parent AlphaPilot process stays alive.  Probe failure disables
    caching for the call instead of falling back to the parent runtime.
    """

    try:
        output = subprocess.check_output(
            [python_bin, "-c", _RUNTIME_PROBE],
            env=_factor_subprocess_env(),
            stderr=subprocess.STDOUT,
            timeout=min(30, FACTOR_COSTEER_SETTINGS.file_based_execution_timeout),
            text=True,
        )
        payload_line = next(
            line for line in reversed(output.splitlines())
            if line.startswith(_RUNTIME_PROBE_PREFIX)
        )
        payload = json.loads(payload_line.removeprefix(_RUNTIME_PROBE_PREFIX))
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"Factor runtime fingerprint probe failed for {python_bin!r}; "
            f"pickle cache disabled: {exc}"
        )
        return None


class FactorTask(CoSTEERTask):
    # TODO:  generalized the attributes into the Task
    # - factor_* -> *
    def __init__(
        self,
        factor_name,
        factor_description,
        factor_formulation,
        factor_expression = None,
        *args,
        variables: dict = {},
        resource: str = None,
        factor_implementation: bool = False,
        **kwargs,
    ) -> None:
        self.factor_name = (
            factor_name  # TODO: remove it in the later version. Keep it only for pickle version compatibility
        )
        self.factor_description = factor_description
        self.factor_formulation = factor_formulation
        self.factor_expression = factor_expression
        self.variables = variables
        self.factor_resources = resource
        self.factor_implementation = factor_implementation
        super().__init__(name=factor_name, *args, **kwargs)

    def get_task_information(self):
        expr_line = ""
        if self.factor_expression:
            expr_line = f"\nfactor_expression: {self.factor_expression}"
        return f"""factor_name: {self.factor_name}
factor_description: {self.factor_description}
factor_formulation: {self.factor_formulation}
variables: {str(self.variables)}{expr_line}"""
    

    def get_task_description(self):
        return f"""factor_name: {self.factor_name}
factor_description: {self.factor_description}"""

    def get_task_information_and_implementation_result(self):
        return {
            "factor_name": self.factor_name,
            "factor_description": self.factor_description,
            "factor_formulation": self.factor_formulation,
            "factor_expression": self.factor_expression,
            "variables": str(self.variables),
            "factor_implementation": str(self.factor_implementation),
        }

    @staticmethod
    def from_dict(dict):
        return FactorTask(**dict)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}[{self.factor_name}]>"


class FactorFBWorkspace(FBWorkspace):
    """
    This class is used to implement a factor by writing the code to a file.
    Input data and output factor value are also written to files.
    """

    # TODO: (Xiao) think raising errors may get better information for processing
    FB_EXEC_SUCCESS = "Execution succeeded without error."
    FB_CODE_NOT_SET = "code is not set."
    FB_EXECUTION_SUCCEEDED = "Execution succeeded without error."
    FB_OUTPUT_FILE_NOT_FOUND = "\nExpected output file not found."
    FB_OUTPUT_FILE_FOUND = "\nExpected output file found."

    def __init__(
        self,
        *args,
        raise_exception: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.raise_exception = raise_exception

    def hash_func(self, data_type: str = "Debug") -> str | None:
        if "factor.py" not in self.code_dict or self.raise_exception:
            return None
        python_bin = resolve_factor_python_bin()
        runtime_fingerprint = _factor_runtime_fingerprint(python_bin)
        if runtime_fingerprint is None:
            return None
        return md5_hash(
            json.dumps(
                {
                    "data_fingerprint": resolve_factor_data_fingerprint(self),
                    "data_type": data_type,
                    "factor_source": self.code_dict["factor.py"],
                    "python_bin": python_bin,
                    "runtime_fingerprint": runtime_fingerprint,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _execute_cacheable(result: tuple[str, pd.DataFrame | None] | Any) -> bool:
        if not isinstance(result, tuple) or len(result) < 2:
            return False
        return result[1] is not None

    @cache_with_pickle(hash_func, cache_if=_execute_cacheable)
    def execute(self, data_type: str = "Debug") -> Tuple[str, pd.DataFrame]:
        """
        execute the implementation and get the factor value by the following steps:
        1. make the directory in workspace path
        2. write the code to the file in the workspace path
        3. link all the source data to the workspace path folder
        if call_factor_py is True:
            4. execute the code
        else:
            4. generate a script from template to import the factor.py dump get the factor value to result.h5
        5. read the factor value from the output file in the workspace path folder
        returns the execution feedback as a string and the factor value as a pandas dataframe


        Regarding the cache mechanism:
        1. We will store the function's return value to ensure it behaves as expected.
        - The cached information will include a tuple with the following: (execution_feedback, executed_factor_value_dataframe, Optional[Exception])

        """
        super().execute()
        if self.code_dict is None or "factor.py" not in self.code_dict:
            if self.raise_exception:
                raise CodeFormatError(self.FB_CODE_NOT_SET)
            else:
                return self.FB_CODE_NOT_SET, None
        with FileLock(self.workspace_path / "execution.lock"):
            if self.target_task.version == 1:
                # Resolves to the task's FactorDataContext dir (attached or via env), falling
                # back to the legacy global folders when no context is present.
                source_data_path = resolve_factor_data_dir(self, data_type)

            source_data_path.mkdir(exist_ok=True, parents=True)
            code_path = self.workspace_path / f"factor.py"

            self.link_all_files_in_folder_to_workspace(source_data_path, self.workspace_path)

            execution_feedback = self.FB_EXECUTION_SUCCEEDED
            execution_success = False
            execution_error = None

            if self.target_task.version == 1:
                execution_code_path = code_path
            elif self.target_task.version == 2:
                execution_code_path = self.workspace_path / f"{uuid.uuid4()}.py"
                execution_code_path.write_text((Path(__file__).parent / "factor_execution_template.txt").read_text())

            python_bin = resolve_factor_python_bin()
            try:
                subprocess.check_output(
                    [python_bin, str(execution_code_path)],
                    cwd=self.workspace_path,
                    env=_factor_subprocess_env(),
                    stderr=subprocess.STDOUT,
                    timeout=FACTOR_COSTEER_SETTINGS.file_based_execution_timeout,
                )
                execution_success = True
            except subprocess.CalledProcessError as e:
                import site

                execution_feedback = (
                    e.output.decode()
                    .replace(str(execution_code_path.parent.absolute()), r"/path/to")
                    .replace(str(site.getsitepackages()[0]), r"/path/to/site-packages")
                )
                if len(execution_feedback) > 2000:
                    execution_feedback = (
                        execution_feedback[:1000] + "....hidden long error message...." + execution_feedback[-1000:]
                    )
                if self.raise_exception:
                    raise CustomRuntimeError(execution_feedback)
                else:
                    execution_error = CustomRuntimeError(execution_feedback)
            except subprocess.TimeoutExpired:
                execution_feedback += f"Execution timeout error and the timeout is set to {FACTOR_COSTEER_SETTINGS.file_based_execution_timeout} seconds."
                if self.raise_exception:
                    raise CustomRuntimeError(execution_feedback)
                else:
                    execution_error = CustomRuntimeError(execution_feedback)

            workspace_output_file_path = self.workspace_path / "result.h5"
            if workspace_output_file_path.exists() and execution_success:
                try:
                    executed_factor_value_dataframe = pd.read_hdf(workspace_output_file_path)
                    execution_feedback += self.FB_OUTPUT_FILE_FOUND
                except Exception as e:
                    execution_feedback += f"Error found when reading hdf file: {e}"[:1000]
                    executed_factor_value_dataframe = None
            else:
                execution_feedback += self.FB_OUTPUT_FILE_NOT_FOUND
                executed_factor_value_dataframe = None
                if self.raise_exception:
                    raise NoOutputError(execution_feedback)
                else:
                    execution_error = NoOutputError(execution_feedback)

        return execution_feedback, executed_factor_value_dataframe

    def __str__(self) -> str:
        # NOTE:
        # If the code cache works, the workspace will be None.
        return f"File Factor[{self.target_task.factor_name}]: {self.workspace_path}"

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def from_folder(task: FactorTask, path: Union[str, Path], **kwargs):
        path = Path(path)
        code_dict = {}
        for file_path in path.iterdir():
            if file_path.suffix == ".py":
                code_dict[file_path.name] = file_path.read_text()
        return FactorFBWorkspace(target_task=task, code_dict=code_dict, **kwargs)


FactorExperiment = Experiment
FeatureExperiment = Experiment
