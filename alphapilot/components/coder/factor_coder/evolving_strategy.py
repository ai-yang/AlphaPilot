from __future__ import annotations

import ast
import json
from pathlib import Path
from jinja2 import Environment, StrictUndefined

from alphapilot.components.coder.CoSTEER.evolving_strategy import (
    MultiProcessEvolvingStrategy,
)
from alphapilot.components.coder.CoSTEER.knowledge_management import (
    CoSTEERQueriedKnowledge,
    CoSTEERQueriedKnowledgeV2,
)
from alphapilot.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
from alphapilot.components.coder.factor_coder.factor import FactorFBWorkspace, FactorTask
from alphapilot.components.coder.factor_coder.factor_ast import (
    ExpressionSemanticError,
    validate_expression_semantics,
)
from alphapilot.core.prompts import Prompts
from alphapilot.core.template import CodeTemplate
from alphapilot.oai.llm_conf import LLM_SETTINGS
from alphapilot.adapters import get_llm
from alphapilot.core.utils import multiprocessing_wrapper
from alphapilot.core.conf import RD_AGENT_SETTINGS

code_template = CodeTemplate(template_path=Path(__file__).parent / "template.jinjia2")
implement_prompts = Prompts(file_path=Path(__file__).parent / "prompts.yaml")


def _render_factor_code(*, expression: str, factor_name: str) -> str:
    """Render expressions that satisfy the public causal DSL contract."""
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionSemanticError(
            "Factor expression must be a non-empty string.",
            code="empty_expression",
        )
    expression = expression.strip()
    validate_expression_semantics(expression)
    return code_template.render(expression=expression, factor_name=str(factor_name))


def _expression_from_rendered_code(code: str) -> str:
    """Read the literal expression embedded in the generated factor program."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise ValueError(f"Generated factor code is not valid Python: {exc.msg}") from exc

    values: list[str] = []

    class ModuleAssignmentVisitor(ast.NodeVisitor):
        """Inspect executable module control flow without entering nested scopes."""

        def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
            if (
                isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and any(
                    isinstance(target, ast.Name) and target.id == "expr"
                    for target in node.targets
                )
            ):
                values.append(node.value.value)

        def visit_FunctionDef(self, _node: ast.FunctionDef) -> None:  # noqa: N802
            return

        def visit_AsyncFunctionDef(  # noqa: N802
            self, _node: ast.AsyncFunctionDef
        ) -> None:
            return

        def visit_ClassDef(self, _node: ast.ClassDef) -> None:  # noqa: N802
            return

        def visit_Lambda(self, _node: ast.Lambda) -> None:  # noqa: N802
            return

    ModuleAssignmentVisitor().visit(tree)
    if len(values) != 1:
        raise ValueError(
            "Generated factor code must contain exactly one literal expr assignment."
        )
    expression = values[0].strip()
    if not expression:
        raise ValueError("Generated factor code contains an empty expr assignment.")
    return expression


def _repaired_expression_from_response(response: object) -> str:
    """Decode one LLM repair response and enforce its minimal JSON schema."""
    if not isinstance(response, str):
        raise ExpressionSemanticError(
            "Repair response must be a JSON string.",
            code="invalid_repair_response",
        )
    try:
        response_dict = json.loads(response)
    except json.decoder.JSONDecodeError as exc:
        raise ExpressionSemanticError(
            "Repair response is not valid JSON.",
            code="invalid_repair_response",
        ) from exc
    if not isinstance(response_dict, dict) or not isinstance(
        response_dict.get("expr"), str
    ):
        raise ExpressionSemanticError(
            "Repair response must contain a string field named 'expr'.",
            code="invalid_repair_response",
        )
    expression = response_dict["expr"].strip()
    if not expression:
        raise ExpressionSemanticError(
            "Repair response field 'expr' must not be empty.",
            code="invalid_repair_response",
        )
    return expression


def _assign_factor_codes(code_list, evo):
    """Inject code and keep the task/workspace expression equal to executed code."""
    if len(code_list) != len(evo.sub_tasks):
        raise ValueError("Generated code count must match the factor task count.")
    for index, code in enumerate(code_list):
        if code is None:
            continue
        executed_expression = _expression_from_rendered_code(code)
        validate_expression_semantics(executed_expression)
        target_task = evo.sub_tasks[index]
        if evo.sub_workspace_list[index] is None:
            evo.sub_workspace_list[index] = FactorFBWorkspace(target_task=target_task)
        workspace = evo.sub_workspace_list[index]
        workspace.inject_code(**{"factor.py": code})
        target_task.factor_expression = executed_expression
        if getattr(workspace, "target_task", None) is not None:
            workspace.target_task.factor_expression = executed_expression
        # Persist an explicit audit field even if a caller later replaces the
        # task object.  The executable source remains the cache authority.
        workspace.executed_factor_expression = executed_expression
    return evo


class FactorMultiProcessEvolvingStrategy(MultiProcessEvolvingStrategy):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.num_loop = 0
        self.haveSelected = False


    def error_summary(
        self,
        target_task: FactorTask,
        queried_former_failed_knowledge_to_render: list,
        queried_similar_error_knowledge_to_render: list,
    ) -> str:
        error_summary_system_prompt = (
            Environment(undefined=StrictUndefined)
            .from_string(implement_prompts["evolving_strategy_error_summary_v2_system"])
            .render(
                scenario=self.scen.get_scenario_all_desc(target_task),
                factor_information_str=target_task.get_task_information(),
                code_and_feedback=queried_former_failed_knowledge_to_render[-1].get_implementation_and_feedback_str(),
            )
            .strip("\n")
        )
        for _ in range(10):  # max attempt to reduce the length of error_summary_user_prompt
            error_summary_user_prompt = (
                Environment(undefined=StrictUndefined)
                .from_string(implement_prompts["evolving_strategy_error_summary_v2_user"])
                .render(
                    queried_similar_error_knowledge=queried_similar_error_knowledge_to_render,
                )
                .strip("\n")
            )
            if (
                get_llm().count_tokens(
                    user_prompt=error_summary_user_prompt, system_prompt=error_summary_system_prompt
                )
                < LLM_SETTINGS.chat_token_limit
            ):
                break
            elif len(queried_similar_error_knowledge_to_render) > 0:
                queried_similar_error_knowledge_to_render = queried_similar_error_knowledge_to_render[:-1]
        error_summary_critics = get_llm(
            use_chat_cache=FACTOR_COSTEER_SETTINGS.coder_use_cache
        ).chat_completion(
            user_prompt=error_summary_user_prompt, system_prompt=error_summary_system_prompt, json_mode=False
        )
        return error_summary_critics

    def implement_one_task(
        self,
        target_task: FactorTask,
        queried_knowledge: CoSTEERQueriedKnowledge,
    ) -> str:
        target_factor_task_information = target_task.get_task_information()

        queried_similar_successful_knowledge = (
            queried_knowledge.task_to_similar_task_successful_knowledge[target_factor_task_information]
            if queried_knowledge is not None
            else []
        )  # A list, [success task implement knowledge]

        if isinstance(queried_knowledge, CoSTEERQueriedKnowledgeV2):
            queried_similar_error_knowledge = (
                queried_knowledge.task_to_similar_error_successful_knowledge[target_factor_task_information]
                if queried_knowledge is not None
                else {}
            )  # A dict, {{error_type:[[error_imp_knowledge, success_imp_knowledge],...]},...}
        else:
            queried_similar_error_knowledge = {}

        queried_former_failed_knowledge = (
            queried_knowledge.task_to_former_failed_traces[target_factor_task_information][0]
            if queried_knowledge is not None
            else []
        )

        queried_former_failed_knowledge_to_render = queried_former_failed_knowledge

        latest_attempt_to_latest_successful_execution = queried_knowledge.task_to_former_failed_traces[
            target_factor_task_information
        ][1]

        system_prompt = (
            Environment(undefined=StrictUndefined)
            .from_string(
                implement_prompts["evolving_strategy_factor_implementation_v1_system"],
            )
            .render(
                scenario=self.scen.get_scenario_all_desc(target_task, filtered_tag="feature"),
                queried_former_failed_knowledge=queried_former_failed_knowledge_to_render,
            )
        )
        queried_similar_successful_knowledge_to_render = queried_similar_successful_knowledge
        queried_similar_error_knowledge_to_render = queried_similar_error_knowledge
        # 动态地防止prompt超长
        for _ in range(10):  # max attempt to reduce the length of user_prompt
            # 总结error（可选）
            if (
                isinstance(queried_knowledge, CoSTEERQueriedKnowledgeV2)
                and FACTOR_COSTEER_SETTINGS.v2_error_summary
                and len(queried_similar_error_knowledge_to_render) != 0
                and len(queried_former_failed_knowledge_to_render) != 0
            ):
                error_summary_critics = self.error_summary(
                    target_task,
                    queried_former_failed_knowledge_to_render,
                    queried_similar_error_knowledge_to_render,
                )
            else:
                error_summary_critics = None
            # 构建user_prompt。开始写代码
            user_prompt = (
                Environment(undefined=StrictUndefined)
                .from_string(
                    implement_prompts["evolving_strategy_factor_implementation_v2_user"],
                )
                .render(
                    # factor_information_str=target_factor_task_information,
                    # queried_similar_successful_knowledge=queried_similar_successful_knowledge_to_render,
                    # queried_similar_error_knowledge=queried_similar_error_knowledge_to_render,
                    # error_summary_critics=error_summary_critics,
                    # latest_attempt_to_latest_successful_execution=latest_attempt_to_latest_successful_execution,
                    factor_information_str=target_task.get_task_description(),
                    queried_similar_error_knowledge=queried_similar_error_knowledge_to_render,
                    error_summary_critics=error_summary_critics,
                    similar_successful_factor_description=queried_similar_successful_knowledge_to_render[0].target_task.get_task_description(),
                    similar_successful_expression=self.extract_expr(queried_similar_successful_knowledge_to_render[0].implementation.code),
                    latest_attempt_to_latest_successful_execution=latest_attempt_to_latest_successful_execution,
                )
                .strip("\n")
            )
            if (
                get_llm().count_tokens(user_prompt=user_prompt, system_prompt=system_prompt)
                < LLM_SETTINGS.chat_token_limit
            ):
                break
            elif len(queried_former_failed_knowledge_to_render) > 1:
                queried_former_failed_knowledge_to_render = queried_former_failed_knowledge_to_render[1:]
            elif len(queried_similar_successful_knowledge_to_render) > len(
                queried_similar_error_knowledge_to_render,
            ):
                queried_similar_successful_knowledge_to_render = queried_similar_successful_knowledge_to_render[:-1]
            elif len(queried_similar_error_knowledge_to_render) > 0:
                queried_similar_error_knowledge_to_render = queried_similar_error_knowledge_to_render[:-1]
        for _ in range(10):
            try:
                code = json.loads(
                    get_llm(
                        use_chat_cache=FACTOR_COSTEER_SETTINGS.coder_use_cache
                    ).chat_completion(
                        user_prompt=user_prompt, system_prompt=system_prompt, json_mode=True
                    )
                )["code"]
                return code
            except json.decoder.JSONDecodeError:
                pass
        else:
            return ""  # return empty code if failed to get code after 10 attempts

    def assign_code_list_to_evo(self, code_list, evo):
        for index in range(len(evo.sub_tasks)):
            if code_list[index] is None:
                continue
            if evo.sub_workspace_list[index] is None:
                evo.sub_workspace_list[index] = FactorFBWorkspace(target_task=evo.sub_tasks[index])
            evo.sub_workspace_list[index].inject_code(**{"factor.py": code_list[index]})
        return evo



alphapilot_implement_prompts = Prompts(file_path=Path(__file__).parent / "prompts_alphapilot.yaml")
class FactorParsingStrategy(MultiProcessEvolvingStrategy):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.num_loop = 0
        self.haveSelected = False

    def extract_expr(self, code_str: str) -> str:
        """从代码字符串中提取expr表达式"""
        try:
            return _expression_from_rendered_code(code_str)
        except (ExpressionSemanticError, ValueError):
            return ""


    def implement_one_task(
        self,
        target_task: FactorTask,
        queried_knowledge: CoSTEERQueriedKnowledge,
    ) -> str:
        """
        实现单个因子任务的代码生成逻辑
        
        该函数有两种工作模式：
        1. 首次执行时：直接使用模板生成代码
        2. 之前有报错时：提供报错信息和成功/失败案例给LLM，由其重写表达式
        
        Args:
            target_task: 要实现的目标因子任务
            queried_knowledge: 查询到的知识库，包含相似的成功案例和失败案例
            
        Returns:
            str: 生成的因子代码
        """
        # 获取目标任务信息
        target_factor_task_information = target_task.get_task_information()

        # 获取相似的成功实现案例列表
        queried_similar_successful_knowledge = (
            queried_knowledge.task_to_similar_task_successful_knowledge[target_factor_task_information]
            if queried_knowledge is not None
            else []
        )  # A list, [success task implement knowledge]

        # 获取相似的错误实现案例字典（如果使用V2版本的知识管理）
        if isinstance(queried_knowledge, CoSTEERQueriedKnowledgeV2):
            queried_similar_error_knowledge = (
                queried_knowledge.task_to_similar_error_successful_knowledge[target_factor_task_information]
                if queried_knowledge is not None
                else {}
            )  # A dict, {{error_type:[[error_imp_knowledge, success_imp_knowledge],...]},...}
        else:
            queried_similar_error_knowledge = {}

        # 获取此任务之前的失败实现列表
        queried_former_failed_knowledge = (
            queried_knowledge.task_to_former_failed_traces[target_factor_task_information][0]
            if queried_knowledge is not None
            else []
        )

        queried_former_failed_knowledge_to_render = queried_former_failed_knowledge
        
        # 首次执行时：直接使用模板生成代码
        if len(queried_former_failed_knowledge) == 0:
            rendered_code = _render_factor_code(
                expression=target_task.factor_expression,
                factor_name=target_task.factor_name,
            )
            return rendered_code
        
        # 之前有报错时：提供报错信息和案例给LLM，重写表达式
        else:
            # 获取最近一次尝试到最近一次成功执行的信息
            latest_attempt_to_latest_successful_execution = queried_knowledge.task_to_former_failed_traces[
                target_factor_task_information
            ][1]

            # 构建系统提示
            system_prompt = (
                Environment(undefined=StrictUndefined)
                .from_string(
                    alphapilot_implement_prompts["evolving_strategy_factor_implementation_v1_system"],
                )
                .render(
                    scenario=self.scen.get_scenario_all_desc(target_task, filtered_tag="feature"),
                    # former_expression=self.extract_expr(queried_former_failed_knowledge_to_render[-1].implementation.code),
                    # former_feedback=queried_former_failed_knowledge_to_render[-1].feedback,
                )
            )
            queried_similar_successful_knowledge_to_render = queried_similar_successful_knowledge
            queried_similar_error_knowledge_to_render = queried_similar_error_knowledge
            
            # 动态调整提示长度，防止超出token限制
            for _ in range(10):  # 最多尝试10次减少用户提示长度
                # 生成错误摘要（可选功能）
                if (
                    isinstance(queried_knowledge, CoSTEERQueriedKnowledgeV2)
                    and FACTOR_COSTEER_SETTINGS.v2_error_summary
                    and len(queried_similar_error_knowledge_to_render) != 0
                    and len(queried_former_failed_knowledge_to_render) != 0
                ):
                    error_summary_critics = self.error_summary(
                        target_task,
                        queried_former_failed_knowledge_to_render,
                        queried_similar_error_knowledge_to_render,
                    )
                else:
                    error_summary_critics = None
                    
                # 构建用户提示
                user_prompt = (
                    Environment(undefined=StrictUndefined)
                    .from_string(
                        alphapilot_implement_prompts["evolving_strategy_factor_implementation_v2_user"],
                    )
                    .render(
                        factor_information_str=target_task.get_task_description(),
                        queried_similar_error_knowledge=queried_similar_error_knowledge_to_render,
                        former_expression=self.extract_expr(queried_former_failed_knowledge_to_render[-1].implementation.code),
                        former_feedback=queried_former_failed_knowledge_to_render[-1].feedback,
                        error_summary_critics=error_summary_critics,
                        similar_successful_factor_description=queried_similar_successful_knowledge_to_render[-1].target_task.get_task_description(),
                        similar_successful_expression=self.extract_expr(queried_similar_successful_knowledge_to_render[-1].implementation.code),
                        latest_attempt_to_latest_successful_execution=latest_attempt_to_latest_successful_execution,
                    )
                    .strip("\n")
                )

                # 检查token数量是否超限，若超限则逐步减少要渲染的知识
                if (
                    get_llm().count_tokens(user_prompt=user_prompt, system_prompt=system_prompt)
                    < LLM_SETTINGS.chat_token_limit
                ):
                    break
                elif len(queried_former_failed_knowledge_to_render) > 1:
                    # 减少历史失败案例
                    queried_former_failed_knowledge_to_render = queried_former_failed_knowledge_to_render[1:]
                elif len(queried_similar_successful_knowledge_to_render) > len(
                    queried_similar_error_knowledge_to_render,
                ):
                    # 减少成功案例
                    queried_similar_successful_knowledge_to_render = queried_similar_successful_knowledge_to_render[:-1]
                elif len(queried_similar_error_knowledge_to_render) > 0:
                    # 减少错误案例
                    queried_similar_error_knowledge_to_render = queried_similar_error_knowledge_to_render[:-1]
                    
            # 尝试最多10次从LLM获取表达式
            repair_user_prompt = user_prompt
            last_error: Exception | None = None
            for attempt in range(1, 11):
                try:
                    # 调用API获取新的表达式
                    response = get_llm(
                        use_chat_cache=FACTOR_COSTEER_SETTINGS.coder_use_cache
                    ).chat_completion(
                        user_prompt=repair_user_prompt,
                        system_prompt=system_prompt,
                        json_mode=True,
                        reasoning_flag=False,
                    )
                    expr = _repaired_expression_from_response(response)
                    return _render_factor_code(
                        expression=expr,
                        factor_name=target_task.factor_name,
                    )
                except ExpressionSemanticError as exc:
                    last_error = exc
                    repair_user_prompt = (
                        user_prompt
                        + "\n\nThe previous repaired expression was rejected by the local "
                        f"validator on attempt {attempt}: {exc}. Return a different, safe "
                        "expression in the required JSON schema."
                    )
            raise ValueError(
                f"Unable to obtain a semantically valid repaired expression: {last_error}"
            ) from last_error
    
    def assign_code_list_to_evo(self, code_list, evo):
        return _assign_factor_codes(code_list, evo)
    
    
    
class FactorRunningStrategy(MultiProcessEvolvingStrategy):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.num_loop = 0
        self.haveSelected = False


    def implement_one_task(
        self,
        target_task: FactorTask,
        queried_knowledge: CoSTEERQueriedKnowledge,
    ) -> str:

        rendered_code = _render_factor_code(
            expression=target_task.factor_expression,
            factor_name=target_task.factor_name,
        )
        return rendered_code
        
    
    def assign_code_list_to_evo(self, code_list, evo):
        return _assign_factor_codes(code_list, evo)
    
    
    def evolve(
        self,
        *,
        evo: EvolvingItem,
        queried_knowledge: CoSTEERQueriedKnowledge | None = None,
        **kwargs,
    ) -> EvolvingItem:
        # 1.找出需要evolve的task
        to_be_finished_task_index = []
        for index, target_task in enumerate(evo.sub_tasks):
            to_be_finished_task_index.append(index)

        result = multiprocessing_wrapper(
            [
                (self.implement_one_task, (evo.sub_tasks[target_index], queried_knowledge))
                for target_index in to_be_finished_task_index
            ],
            n=RD_AGENT_SETTINGS.multi_proc_n,
        )
        code_list = [None for _ in range(len(evo.sub_tasks))]
        for index, target_index in enumerate(to_be_finished_task_index):
            code_list[target_index] = result[index]

        evo = self.assign_code_list_to_evo(code_list, evo)
        evo.corresponding_selection = to_be_finished_task_index

        return evo
