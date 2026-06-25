#!/usr/bin/env python3
"""Verify removal of the unused backtest engine adapter layer.

Checks:
  A. Static — deleted symbols/files, no repo references
  B. Adapter layer — LLM + data source only; get_backtest_engine gone
  C. Config — BacktestConfig.engine removed; summary unchanged semantics
  D. Backtest system — Qlib path still wired through kernel
  E. Strategy orchestration — still delegates via context.backtest()
"""

from __future__ import annotations

import importlib
import inspect
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REMOVED_SYMBOL_PATTERNS = (
    r"\bget_backtest_engine\b",
    r"\bBACKTEST_REGISTRY\b",
    r"\bBaseBacktestEngine\b",
    r"\bQlibBacktestEngine\b",
    r"\bBacktestRequest\b",
    r"\bBacktestResult\b",
    r"\bALPHAPILOT_BACKTEST_ENGINE\b",
)

REMOVED_PATHS = (
    ROOT / "alphapilot/adapters/base/backtest.py",
    ROOT / "alphapilot/adapters/builtin/backtest/qlib.py",
    ROOT / "alphapilot/adapters/builtin/backtest/__init__.py",
    ROOT / "alphapilot/adapters/builtin/backtest/workspace.py",
    ROOT / "alphapilot/adapters/builtin/qlib_backtest.py",
)

ADAPTER_PACKAGE = ROOT / "alphapilot/adapters"


_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    "docker-data",
    "git_ignore_folder",
    "log",
    "pickle_cache",
    ".mypy_cache",
}


def _rg_python(pattern: str) -> str:
    """Pure-Python fallback for repo search (used when ripgrep is unavailable)."""
    import os
    import re

    regex = re.compile(pattern)
    matches: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            fpath = Path(dirpath) / name
            try:
                text = fpath.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    matches.append(f"{fpath}:{lineno}:{line}")
    return "\n".join(matches).strip()


def _rg(pattern: str) -> str:
    """Search repo for pattern; return stdout (empty if no matches).

    Prefer ripgrep when present; otherwise fall back to a pure-Python walk so
    the test does not hard-depend on the ``rg`` binary being installed.
    """
    try:
        result = subprocess.run(
            ["rg", "-n", pattern, str(ROOT), "--glob", "!.git/**"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return _rg_python(pattern)
    return result.stdout.strip()


class StaticRemovalTests(unittest.TestCase):
    def test_removed_files_absent(self) -> None:
        for path in REMOVED_PATHS:
            with self.subTest(path=path.name):
                self.assertFalse(path.exists(), f"expected deleted: {path}")

    def test_backtest_adapter_directory_gone(self) -> None:
        self.assertFalse(
            (ROOT / "alphapilot/adapters/builtin/backtest").exists(),
            "adapters/builtin/backtest/ should be removed",
        )

    def test_no_repo_references_to_removed_symbols(self) -> None:
        self_name = Path(__file__).name
        hits: list[str] = []
        for pattern in REMOVED_SYMBOL_PATTERNS:
            out = _rg(pattern)
            if not out:
                continue
            for line in out.splitlines():
                path_part = line.split(":", 1)[0]
                # This test file asserts on the removed names by design, and
                # docs/prose may describe the removal — neither is a code reference.
                if Path(path_part).name == self_name or path_part.endswith(".md"):
                    continue
                hits.append(line)
        self.assertEqual(hits, [], "unexpected references:\n" + "\n".join(hits))

    def test_adapters_init_has_no_backtest_exports(self) -> None:
        import alphapilot.adapters as adapters

        public = set(adapters.__all__)
        self.assertNotIn("get_backtest_engine", public)
        self.assertNotIn("BACKTEST_REGISTRY", public)
        self.assertNotIn("BaseBacktestEngine", public)
        self.assertFalse(hasattr(adapters, "get_backtest_engine"))

    def test_registry_has_only_two_registries(self) -> None:
        from alphapilot.adapters import registry

        names = [n for n in dir(registry) if n.endswith("_REGISTRY")]
        self.assertEqual(sorted(names), ["DATA_SOURCE_REGISTRY", "LLM_REGISTRY"])
        self.assertFalse(hasattr(registry, "BACKTEST_REGISTRY"))


class AdapterLayerTests(unittest.TestCase):
    def test_get_llm_default_registered(self) -> None:
        from alphapilot.adapters import LLM_REGISTRY, get_llm

        self.assertIn("openai", LLM_REGISTRY.available())
        llm = get_llm()
        self.assertTrue(callable(getattr(llm, "chat", None)) or callable(getattr(llm, "chat_text", None)))

    def test_get_data_source_default_registered(self) -> None:
        from alphapilot.adapters import DATA_SOURCE_REGISTRY, get_data_source

        self.assertIn("baostock_cn", DATA_SOURCE_REGISTRY.available())
        ds = get_data_source()
        self.assertTrue(callable(getattr(ds, "download", None)))

    def test_get_backtest_engine_import_error(self) -> None:
        with self.assertRaises(ImportError):
            importlib.import_module("alphapilot.adapters.get_backtest_engine")  # noqa: F401

        import alphapilot.adapters as adapters

        with self.assertRaises(AttributeError):
            _ = adapters.get_backtest_engine  # type: ignore[attr-defined]


class ConfigTests(unittest.TestCase):
    def test_backtest_config_has_no_engine_field(self) -> None:
        from alphapilot.kernel.config import BacktestConfig

        fields = {f.name for f in BacktestConfig.__dataclass_fields__.values()}
        self.assertNotIn("engine", fields)
        cfg = BacktestConfig()
        self.assertFalse(hasattr(cfg, "engine"))

    def test_app_config_summary_omits_engine(self) -> None:
        from alphapilot.kernel.config import AppConfig

        summary = AppConfig.load().summary()
        self.assertNotIn("backtest.engine", summary)
        self.assertIn("backtest.use_local=", summary)
        self.assertIn("backtest.workspace_root=", summary)


class BacktestSystemTests(unittest.TestCase):
    def test_backtest_system_exports_intact(self) -> None:
        from alphapilot.systems.backtest import (
            FactorBacktestRequest,
            QlibBacktestSystem,
            QlibFBWorkspace,
            run_factor_evaluation,
        )

        self.assertTrue(inspect.isclass(QlibBacktestSystem))
        self.assertTrue(inspect.isclass(QlibFBWorkspace))
        self.assertTrue(callable(run_factor_evaluation))
        self.assertTrue(inspect.isclass(FactorBacktestRequest))

    def test_build_engine_registers_backtest_system(self) -> None:
        from alphapilot.kernel import build_engine

        engine = build_engine()
        bt = engine.get_system("backtest")
        self.assertEqual(type(bt).__name__, "QlibBacktestSystem")

    def test_strategy_backtest_delegates_to_context_backtest(self) -> None:
        # Data prep moved into the evaluation pipeline; the strategy backtest no longer calls
        # ensure_factor_data directly, so there is nothing to patch here.
        from alphapilot.systems.strategy.backtest import run_strategy_asset_backtest
        from alphapilot.systems.backtest.types import FactorDefinition

        ctx = MagicMock()
        ctx.config.backtest.use_local = True
        mock_result = MagicMock()
        mock_result.experiment = MagicMock(experiment_workspace=MagicMock(workspace_path="/tmp/ws"))
        ctx.backtest.return_value.run_factor_evaluation.return_value = mock_result

        factors = [FactorDefinition(factor_name="f1", factor_expression="Rank($close)")]
        run = run_strategy_asset_backtest(
            ctx,
            mode="retrain",
            factors=factors,
            scenario="factor_backtest",
        )

        ctx.backtest.assert_called_once()
        ctx.backtest.return_value.run_factor_evaluation.assert_called_once()
        self.assertEqual(run.mode, "retrain")
        self.assertEqual(run.workspace_path, "/tmp/ws")


class ReadmeSanityTests(unittest.TestCase):
    def test_adapters_readme_mentions_two_boundaries_only(self) -> None:
        readme = (ADAPTER_PACKAGE / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("get_backtest_engine", readme)
        self.assertNotIn("BaseBacktestEngine", readme)
        self.assertIn("systems/backtest/", readme)
        self.assertIn("Data source", readme)
        self.assertIn("LLM provider", readme)


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for case in (
        StaticRemovalTests,
        AdapterLayerTests,
        ConfigTests,
        BacktestSystemTests,
        ReadmeSanityTests,
    ):
        suite.addTests(loader.loadTestsFromTestCase(case))

    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    print(f"\nVERDICT: {passed}/{result.testsRun} passed")
    if result.wasSuccessful():
        print("Backtest adapter removal verified — adapter layer OK, backtest system OK.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
