from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alphapilot.components.coder.CoSTEER.knowledge_management import (
    CoSTEERKnowledgeBaseV2,
    CoSTEERRAGStrategyV2,
)


@pytest.fixture
def knowledge_base() -> CoSTEERKnowledgeBaseV2:
    # Avoid loading a persisted graph or calling external models in unit tests.
    kb = CoSTEERKnowledgeBaseV2.__new__(CoSTEERKnowledgeBaseV2)
    kb.graph = Mock()
    kb.working_trace_knowledge = {}
    kb.working_trace_error_analysis = {}
    kb.success_task_to_knowledge_dict = {}
    kb.node_to_implementation_knowledge_dict = {}
    kb.task_to_component_nodes = {}
    return kb


def _trace(task):
    workspace = Mock()
    workspace.copy.return_value = SimpleNamespace(
        code={"factor.py": "repaired code"}
    )
    return [
        SimpleNamespace(
            evolvable_subjects=SimpleNamespace(
                sub_tasks=[task], sub_workspace_list=[workspace]
            ),
            feedback=[SimpleNamespace(final_decision=True)],
        )
    ]


@pytest.mark.parametrize("components", [[], [object(), object()]])
def test_repaired_factor_success_analyzes_new_task_before_graph_update(
    knowledge_base, components
) -> None:
    kb = knowledge_base
    task = SimpleNamespace(expression="original expression")
    task.get_task_information = lambda: task.expression
    kb.task_to_component_nodes[task.get_task_information()] = [object()]
    rag = CoSTEERRAGStrategyV2(kb, SimpleNamespace())
    rag.analyze_component = Mock(return_value=components)
    trace = _trace(task)
    # The factor coder changes the expression after the initial RAG query.
    task.expression = "repaired expression"

    rag.generate_knowledge(trace)

    rag.analyze_component.assert_called_once_with("repaired expression")
    assert kb.task_to_component_nodes["repaired expression"] == components
    assert "repaired expression" in kb.success_task_to_knowledge_dict
    calls = kb.graph.add_nodes.call_args_list
    assert calls[0].kwargs["neighbors"] == components
    assert calls[-1].kwargs["node"].label == "task_success_implement"
    assert len(kb.node_to_implementation_knowledge_dict) == 1
    # A repeated pass must not analyze or insert the success again.
    rag.generate_knowledge(trace)
    assert rag.analyze_component.call_count == 1
    assert kb.graph.add_nodes.call_count == 2


def test_success_reuses_components_when_task_information_has_not_changed(
    knowledge_base,
) -> None:
    kb = knowledge_base
    components = [object()]
    kb.task_to_component_nodes = {"unchanged task": components}
    rag = CoSTEERRAGStrategyV2(kb, SimpleNamespace())
    rag.analyze_component = Mock()
    task = SimpleNamespace(get_task_information=lambda: "unchanged task")

    rag.generate_knowledge(_trace(task))

    rag.analyze_component.assert_not_called()
    assert kb.graph.add_nodes.call_args_list[0].kwargs["neighbors"] is components
