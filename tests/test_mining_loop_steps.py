"""Tier 1 (offline): the mining workflow's step registry.

``LoopMeta`` auto-collects a class's methods into ``steps``. Only *public*
methods are real workflow steps; single-underscore helpers (e.g.
``_save_strategy_asset``) are called *inside* a step and must never be
registered as standalone steps — otherwise they run an extra time per round
(double-saving the strategy asset, and saving factors to the library while
ignoring the ``save_factors_to_library`` gate). This locks that contract.
"""

from __future__ import annotations

from alphapilot.components.workflow.rd_loop import RDLoop
from alphapilot.modules.alpha_mining.loops.alphapilot_loop import AlphaPilotLoop

# The intended logical mining pipeline: propose -> construct -> calculate ->
# backtest -> feedback. Exactly five steps, no more.
EXPECTED_ALPHAPILOT_STEPS = [
    "factor_propose",
    "factor_construct",
    "factor_calculate",
    "factor_backtest",
    "feedback",
]

EXPECTED_RD_STEPS = ["propose", "exp_gen", "coding", "running", "feedback"]


def test_alphapilot_loop_runs_exactly_five_steps() -> None:
    assert AlphaPilotLoop.steps == EXPECTED_ALPHAPILOT_STEPS


def test_private_helpers_are_not_registered_as_steps() -> None:
    # These are real methods on the class but must stay out of the step registry.
    assert callable(AlphaPilotLoop._save_strategy_asset)
    assert callable(AlphaPilotLoop._save_factors_to_library)
    assert "_save_strategy_asset" not in AlphaPilotLoop.steps
    assert "_save_factors_to_library" not in AlphaPilotLoop.steps
    # No underscore-prefixed name should ever leak into steps.
    assert not any(s.startswith("_") for s in AlphaPilotLoop.steps)


def test_rd_loop_step_registry_unaffected() -> None:
    assert RDLoop.steps == EXPECTED_RD_STEPS
