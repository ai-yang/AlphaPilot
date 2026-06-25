#!/usr/bin/env python3
"""Verify log/ui decoupling from alpha_mining scenarios (trait-based predicates)."""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alphapilot.core.scenario import Scenario


class PicklableFakeScenario(Scenario):
    """Pickle-friendly Scenario stub for resolve_scenario_from_log tests."""

    @property
    def background(self) -> str:
        return "bg"

    @property
    def interface(self) -> str:
        return "iface"

    @property
    def output_format(self) -> str:
        return "fmt"

    @property
    def simulator(self) -> str:
        return "sim"

    @property
    def rich_style_description(self) -> str:
        return "rich"

    @property
    def is_mining_scenario(self) -> bool:
        return True

    def get_scenario_all_desc(self, task=None, filtered_tag=None, simple_background=None) -> str:
        return "all"


LOG_UI_FILES = (
    ROOT / "alphapilot/log/ui/session.py",
    ROOT / "alphapilot/log/ui/views.py",
    ROOT / "alphapilot/log/ui/panel.py",
    ROOT / "alphapilot/log/ui/app.py",
    ROOT / "alphapilot/log/tag_utils.py",
)


class ArchitectureTests(unittest.TestCase):
    """Static checks: log layer must not import alpha_mining."""

    def test_log_tree_no_alpha_mining_imports(self) -> None:
        log_dir = ROOT / "alphapilot/log"
        hits: list[str] = []
        for py in log_dir.rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            if "alpha_mining" in text:
                hits.append(str(py.relative_to(ROOT)))
        self.assertEqual(hits, [], f"log still references alpha_mining: {hits}")

    def test_no_similar_scenarios_tuple(self) -> None:
        for path in LOG_UI_FILES:
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("SIMILAR_SCENARIOS", text, f"SIMILAR_SCENARIOS still in {path.name}")

    def test_session_uses_scenario_traits(self) -> None:
        src = (ROOT / "alphapilot/log/ui/session.py").read_text(encoding="utf-8")
        self.assertIn("from alphapilot.core.scenario import Scenario", src)
        self.assertIn("def scenario_is_mining", src)
        self.assertIn("def scenario_has_alpha158_baseline", src)
        self.assertIn("def scenario_uses_qlib_metric_index", src)

    def test_core_scenario_has_ui_traits(self) -> None:
        from alphapilot.core.scenario import Scenario

        defaults = Scenario.__dict__
        for prop in ("is_mining_scenario", "has_alpha158_baseline", "uses_qlib_metric_index"):
            self.assertIn(prop, defaults, f"missing Scenario.{prop}")


class ImportIsolationTests(unittest.TestCase):
    """Importing log UI modules must not load alpha_mining."""

    def test_log_ui_session_import_without_alpha_mining_module(self) -> None:
        to_drop = [k for k in list(sys.modules) if k.startswith("alphapilot.log.ui")]
        for k in to_drop:
            del sys.modules[k]

        before = set(sys.modules)
        importlib.import_module("alphapilot.log.ui.session")
        after = set(sys.modules)

        loaded = {m for m in after - before if "alpha_mining" in m}
        self.assertEqual(loaded, set(), f"alpha_mining loaded via log/ui.session: {loaded}")


class ScenarioPredicateTests(unittest.TestCase):
    """Predicate helpers are None-safe and read Scenario traits."""

    def setUp(self) -> None:
        from alphapilot.log.ui.session import (
            scenario_has_alpha158_baseline,
            scenario_is_mining,
            scenario_uses_qlib_metric_index,
        )

        self.is_mining = scenario_is_mining
        self.has_alpha158 = scenario_has_alpha158_baseline
        self.uses_qlib_idx = scenario_uses_qlib_metric_index

    def test_none_scenario_all_false(self) -> None:
        self.assertFalse(self.is_mining(None))
        self.assertFalse(self.has_alpha158(None))
        self.assertFalse(self.uses_qlib_idx(None))

    def test_custom_scenario_traits(self) -> None:
        scen = SimpleNamespace(
            is_mining_scenario=True,
            has_alpha158_baseline=False,
            uses_qlib_metric_index=True,
        )
        self.assertTrue(self.is_mining(scen))
        self.assertFalse(self.has_alpha158(scen))
        self.assertTrue(self.uses_qlib_idx(scen))


class TraitParityTests(unittest.TestCase):
    """New trait predicates match the old isinstance branching semantics."""

    @classmethod
    def setUpClass(cls) -> None:
        from alphapilot.log.ui.session import (
            scenario_has_alpha158_baseline,
            scenario_is_mining,
            scenario_uses_qlib_metric_index,
        )

        cls.is_mining = scenario_is_mining
        cls.has_alpha158 = scenario_has_alpha158_baseline
        cls.uses_qlib_idx = scenario_uses_qlib_metric_index

        with patch(
            "alphapilot.modules.alpha_mining.qlib.experiment.utils.get_data_folder_intro",
            return_value="stub data intro",
        ):
            from alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment import (
                QlibAlphaPilotScenario,
                QlibFactorScenario,
            )
            from alphapilot.modules.alpha_mining.qlib.experiment.factor_from_report_experiment import (
                QlibFactorFromReportScenario,
            )
            from alphapilot.modules.alpha_mining.qlib.experiment.model_experiment import QlibModelScenario

            cls.scenarios = {
                "QlibAlphaPilotScenario": QlibAlphaPilotScenario(use_local=True),
                "QlibFactorScenario": QlibFactorScenario(),
                "QlibFactorFromReportScenario": QlibFactorFromReportScenario(),
                "QlibModelScenario": QlibModelScenario(),
            }

        from alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment import (
            QlibAlphaPilotScenario as AP,
            QlibFactorScenario as FS,
        )
        from alphapilot.modules.alpha_mining.qlib.experiment.factor_from_report_experiment import (
            QlibFactorFromReportScenario as FR,
        )
        from alphapilot.modules.alpha_mining.qlib.experiment.model_experiment import QlibModelScenario as MS

        cls.old_similar = (AP, MS, MS, FS, FR)

    def test_mining_flag_matches_old_similar_scenarios_tuple(self) -> None:
        for name, scen in self.scenarios.items():
            old = isinstance(scen, self.old_similar)
            new = type(self).is_mining(scen)
            self.assertEqual(new, old, f"{name}: is_mining parity")

    def test_alpha158_flag_matches_old_factor_scenario_only(self) -> None:
        from alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment import QlibFactorScenario

        for name, scen in self.scenarios.items():
            old = isinstance(scen, QlibFactorScenario)
            new = type(self).has_alpha158(scen)
            self.assertEqual(new, old, f"{name}: alpha158 parity")

    def test_qlib_metric_index_matches_old_model_factor_rules(self) -> None:
        from alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment import QlibFactorScenario
        from alphapilot.modules.alpha_mining.qlib.experiment.factor_from_report_experiment import (
            QlibFactorFromReportScenario,
        )
        from alphapilot.modules.alpha_mining.qlib.experiment.model_experiment import QlibModelScenario

        old_types = (QlibModelScenario, QlibFactorFromReportScenario, QlibFactorScenario)
        for name, scen in self.scenarios.items():
            old = isinstance(scen, old_types)
            new = type(self).uses_qlib_idx(scen)
            self.assertEqual(new, old, f"{name}: qlib metric index parity")


class ResolveScenarioTests(unittest.TestCase):
    """resolve_scenario_from_log uses Scenario ABC, not alpha_mining imports."""

    def test_resolve_returns_scenario_subclass_from_pickle(self) -> None:
        import pickle
        import tempfile

        from alphapilot.core.scenario import Scenario
        from alphapilot.log.tag_utils import resolve_scenario_from_log

        with tempfile.TemporaryDirectory() as tmp:
            log_root = Path(tmp)
            scen_dir = log_root / "init" / "scenario"
            scen_dir.mkdir(parents=True)
            pkl = scen_dir / "scenario.pkl"
            with pkl.open("wb") as f:
                pickle.dump(PicklableFakeScenario(), f)

            resolved = resolve_scenario_from_log(log_root)
            self.assertIsInstance(resolved, Scenario)
            self.assertTrue(resolved.is_mining_scenario)


class ViewsIntegrationSmokeTests(unittest.TestCase):
    """Smoke: views module source uses trait predicates, not concrete scenarios."""

    def test_views_source_uses_predicates_not_concrete_classes(self) -> None:
        src = (ROOT / "alphapilot/log/ui/views.py").read_text(encoding="utf-8")
        self.assertIn("scenario_is_mining", src)
        self.assertIn("scenario_has_alpha158_baseline", src)
        self.assertIn("scenario_uses_qlib_metric_index", src)
        self.assertNotIn("QlibFactorScenario", src)
        self.assertNotIn("alpha_mining", src)

        for fn in ("summary_window", "research_window", "feedback_window", "evolving_window"):
            self.assertIn(f"def {fn}", src, f"missing {fn}")


class PanelSmokeTests(unittest.TestCase):
    """panel.py uses scenario_is_mining instead of SIMILAR_SCENARIOS."""

    def test_panel_source_uses_scenario_is_mining(self) -> None:
        src = (ROOT / "alphapilot/log/ui/panel.py").read_text(encoding="utf-8")
        self.assertIn("scenario_is_mining", src)
        self.assertIn("def render_log_ui_panel", src)
        self.assertNotIn("SIMILAR_SCENARIOS", src)
        self.assertNotIn("alpha_mining", src)


def main() -> int:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in (
        ArchitectureTests,
        ImportIsolationTests,
        ScenarioPredicateTests,
        TraitParityTests,
        ResolveScenarioTests,
        ViewsIntegrationSmokeTests,
        PanelSmokeTests,
    ):
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print("\n" + "=" * 60)
    print(f"Ran {result.testsRun} tests")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    if result.wasSuccessful():
        print("VERDICT: PASS — log/ui decoupled from alpha_mining scenarios")
        return 0
    print("VERDICT: FAIL — see failures/errors above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
