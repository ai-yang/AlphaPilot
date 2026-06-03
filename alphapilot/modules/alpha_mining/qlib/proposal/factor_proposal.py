import json
from pathlib import Path
from typing import List, Tuple

from jinja2 import Environment, StrictUndefined

from alphapilot.components.coder.factor_coder.factor import FactorExperiment, FactorTask
from alphapilot.components.proposal import FactorHypothesis2Experiment, FactorHypothesisGen
from alphapilot.core.prompts import Prompts
from alphapilot.core.proposal import Hypothesis, Scenario, Trace
from alphapilot.core.experiment import Experiment
from alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment import QlibFactorExperiment
from alphapilot.adapters import get_llm


def _qlib_template_dir_from_trace(trace: Trace) -> str | Path | None:
    scen = getattr(trace, "scen", None)
    if scen is None:
        return None
    return getattr(scen, "qlib_template_dir", None)


import os
import pandas as pd
from alphapilot.log import logger
from alphapilot.modules.alpha_mining.qlib.regulator.factor_regulator import FactorRegulator

QlibFactorHypothesis = Hypothesis
alphapilot_prompt_dict = Prompts(file_path=Path(__file__).parent / "prompts_alphapilot.yaml")

class AlphaPilotHypothesis(Hypothesis):
    """
    AlphaPilotHypothesis extends the Hypothesis class to include a potential_direction,
    which represents the initial idea or starting point for the hypothesis.
    """

    def __init__(
        self,
        hypothesis: str,
        concise_observation: str,
        concise_justification: str,
        concise_knowledge: str,
        concise_specification: str
    ) -> None:
        super().__init__(
            hypothesis,
            "",
            "",
            concise_observation,
            concise_justification,
            concise_knowledge,
        )
        self.concise_specification = concise_specification
        
    def __str__(self) -> str:
        return f"""Hypothesis: {self.hypothesis}
                Concise Observation: {self.concise_observation}
                Concise Justification: {self.concise_justification}
                Concise Knowledge: {self.concise_knowledge}
                concise Specification: {self.concise_specification}
                """

rdagent_prompt_dict = Prompts(file_path=Path(__file__).parent.parent / "prompts_rdagent.yaml")

class QlibFactorHypothesisGen(FactorHypothesisGen):
    def __init__(self, scen: Scenario) -> Tuple[dict, bool]:
        super().__init__(scen)

    def prepare_context(self, trace: Trace) -> Tuple[dict, bool]:
        hypothesis_and_feedback = (
            (
                Environment(undefined=StrictUndefined)
                .from_string(rdagent_prompt_dict["hypothesis_and_feedback"])
                .render(trace=trace)
            )
            if len(trace.hist) > 0
            else "No previous hypothesis and feedback available since it's the first round."
        )
        context_dict = {
            "hypothesis_and_feedback": hypothesis_and_feedback,
            "RAG": None,
            "hypothesis_output_format": rdagent_prompt_dict["hypothesis_output_format"],
            "hypothesis_specification": rdagent_prompt_dict["factor_hypothesis_specification"],
        }
        return context_dict, True

    def convert_response(self, response: str) -> Hypothesis:
        response_dict = json.loads(response)
        hypothesis = QlibFactorHypothesis(
            hypothesis=response_dict["hypothesis"],
            reason=response_dict["reason"],
            concise_reason=response_dict["concise_reason"],
            concise_observation=response_dict["concise_observation"],
            concise_justification=response_dict["concise_justification"],
            concise_knowledge=response_dict["concise_knowledge"],
        )
        return hypothesis


class QlibFactorHypothesis2Experiment(FactorHypothesis2Experiment):
    def prepare_context(self, hypothesis: Hypothesis, trace: Trace) -> Tuple[dict | bool]:
        scenario = trace.scen.get_scenario_all_desc()
        experiment_output_format = rdagent_prompt_dict["factor_experiment_output_format"]

        hypothesis_and_feedback = (
            (
                Environment(undefined=StrictUndefined)
                .from_string(rdagent_prompt_dict["hypothesis_and_feedback"])
                .render(trace=trace)
            )
            if len(trace.hist) > 0
            else "No previous hypothesis and feedback available since it's the first round."
        )

        experiment_list: List[FactorExperiment] = [t[1] for t in trace.hist]

        factor_list = []
        for experiment in experiment_list:
            factor_list.extend(experiment.sub_tasks)

        return {
            "target_hypothesis": str(hypothesis),
            "scenario": scenario,
            "hypothesis_and_feedback": hypothesis_and_feedback,
            "experiment_output_format": experiment_output_format,
            "target_list": factor_list,
            "RAG": None,
        }, True

    def convert_response(self, response: str, trace: Trace) -> FactorExperiment:
        response_dict = json.loads(response)
        tasks = []

        for factor_name in response_dict:
            description = response_dict[factor_name]["description"]
            formulation = response_dict[factor_name]["formulation"]
            # expression = response_dict[factor_name]["expression"]
            variables = response_dict[factor_name]["variables"]
            tasks.append(
                FactorTask(
                    factor_name=factor_name,
                    factor_description=description,
                    factor_formulation=formulation,
                    # factor_expression=expression,
                    variables=variables,
                )
            )

        tpl = _qlib_template_dir_from_trace(trace)
        exp = QlibFactorExperiment(tasks, template_folder_path=tpl)
        exp.based_experiments = [QlibFactorExperiment(sub_tasks=[], template_folder_path=tpl)] + [
            t[1] for t in trace.hist if t[2]
        ]

        unique_tasks = []

        for task in tasks:
            duplicate = False
            for based_exp in exp.based_experiments:
                for sub_task in based_exp.sub_tasks:
                    if task.factor_name == sub_task.factor_name:
                        duplicate = True
                        break
                if duplicate:
                    break
            if not duplicate:
                unique_tasks.append(task)

        exp.tasks = unique_tasks
        return exp



alphapilot_prompt_dict = Prompts(file_path=Path(__file__).parent.parent / "prompts_alphapilot.yaml")

# prompt_dict不能作为属性，因为后续整个类的实例要被转为pickle，而prompt_dict不能转
class AlphaPilotHypothesisGen(FactorHypothesisGen):
    def __init__(self, scen: Scenario, potential_direction: str=None) -> Tuple[dict, bool]:
        super().__init__(scen)
        self.potential_direction = potential_direction

    def prepare_context(self, trace: Trace) -> Tuple[dict, bool]:
        
        if len(trace.hist) > 0:
            hypothesis_and_feedback = (
                    Environment(undefined=StrictUndefined)
                    .from_string(alphapilot_prompt_dict["hypothesis_and_feedback"])
                    .render(trace=trace)
                )
            
        elif self.potential_direction is not None: 
            hypothesis_and_feedback = (
                Environment(undefined=StrictUndefined)
                .from_string(alphapilot_prompt_dict["potential_direction_transformation"])
                .render(potential_direction=self.potential_direction)
            ) # 
        else:
            hypothesis_and_feedback = "No previous hypothesis and feedback available since it's the first round. You are encouraged to propose an innovative hypothesis that diverges significantly from existing perspectives."
            
        context_dict = {
            "hypothesis_and_feedback": hypothesis_and_feedback,
            "RAG": None,
            "hypothesis_output_format": alphapilot_prompt_dict["hypothesis_output_format"],
            "hypothesis_specification": alphapilot_prompt_dict["factor_hypothesis_specification"],
        }
        return context_dict, True

    def convert_response(self, response: str) -> AlphaPilotHypothesis:
        response_dict = json.loads(response)
        hypothesis = AlphaPilotHypothesis(
            hypothesis=response_dict["hypothesis"],
            concise_observation=response_dict["concise_observation"],
            concise_knowledge=response_dict["concise_knowledge"],
            concise_justification=response_dict["concise_justification"],
            concise_specification=response_dict["concise_specification"],
        )
        return hypothesis
    
    def gen(self, trace: Trace) -> AlphaPilotHypothesis:
        context_dict, json_flag = self.prepare_context(trace)
        system_prompt = (
            Environment(undefined=StrictUndefined)
            .from_string(alphapilot_prompt_dict["hypothesis_gen"]["system_prompt"])
            .render(
                targets=self.targets,
                scenario=self.scen.get_scenario_all_desc(filtered_tag="hypothesis_and_experiment"),
                hypothesis_output_format=context_dict["hypothesis_output_format"],
                hypothesis_specification=context_dict["hypothesis_specification"],
            )
        )
        user_prompt = (
            Environment(undefined=StrictUndefined)
            .from_string(alphapilot_prompt_dict["hypothesis_gen"]["user_prompt"])
            .render(
                targets=self.targets,
                hypothesis_and_feedback=context_dict["hypothesis_and_feedback"],
                RAG=context_dict["RAG"],
                round=len(trace.hist)
            )
        )

        resp = get_llm().chat_completion(user_prompt, system_prompt, json_mode=json_flag)

        hypothesis = self.convert_response(resp)

        return hypothesis
    
    

class EmptyHypothesisGen(FactorHypothesisGen):
    def __init__(self, scen: Scenario) -> Tuple[dict, bool]:
        super().__init__(scen)
        
    def convert_response(self, *args, **kwargs) -> AlphaPilotHypothesis: 
        return super().convert_response(*args, **kwargs)  
    
    def prepare_context(self, *args, **kwargs) -> Tuple[dict | bool]:
        return super().prepare_context(*args, **kwargs)

    def gen(self, trace: Trace) -> AlphaPilotHypothesis:

        hypothesis = AlphaPilotHypothesis(
            hypothesis="",
            concise_observation="",
            concise_justification="",
            concise_knowledge="",
            concise_specification=""
        )

        return hypothesis




class AlphaPilotHypothesis2FactorExpression(FactorHypothesis2Experiment):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.factor_regulator = FactorRegulator()

    def _render_hypothesis2experiment_user_prompt(
        self,
        context: dict,
        *,
        expression_validation_errors: str | None = None,
        expression_duplication: str | None = None,
    ) -> str:
        return (
            Environment(undefined=StrictUndefined)
            .from_string(alphapilot_prompt_dict["hypothesis2experiment"]["user_prompt"])
            .render(
                targets=self.targets,
                target_hypothesis=context["target_hypothesis"],
                hypothesis_and_feedback=context["hypothesis_and_feedback"],
                function_lib_description=context["function_lib_description"],
                target_list=context["target_list"],
                RAG=context["RAG"],
                expression_validation_errors=expression_validation_errors,
                expression_duplication=expression_duplication,
            )
        )

    def _append_expression_validation_error(
        self,
        current: str | None,
        *,
        factor_name: str,
        expression: str,
        error_message: str,
    ) -> str:
        block = (
            Environment(undefined=StrictUndefined)
            .from_string(alphapilot_prompt_dict["expression_validation_error"])
            .render(
                factor_name=factor_name,
                prev_expression=expression,
                error_message=error_message,
            )
        )
        if current:
            return "\n\n".join([current, block])
        return block

    def prepare_context(self, hypothesis: Hypothesis, trace: Trace) -> Tuple[dict | bool]:
        scenario = trace.scen.get_scenario_all_desc()
        experiment_output_format = alphapilot_prompt_dict["factor_experiment_output_format"]
        function_lib_description = alphapilot_prompt_dict['function_lib_description']
        hypothesis_and_feedback = (
            (
                Environment(undefined=StrictUndefined)
                .from_string(alphapilot_prompt_dict["hypothesis_and_feedback"])
                .render(trace=trace)
            )
            if len(trace.hist) > 0
            else "No previous hypothesis and feedback available since it's the first round."
        )

        experiment_list: List[FactorExperiment] = [t[1] for t in trace.hist]

        factor_list = []
        for experiment in experiment_list:
            factor_list.extend(experiment.sub_tasks)

        return {
            "target_hypothesis": str(hypothesis),
            "scenario": scenario,
            "hypothesis_and_feedback": hypothesis_and_feedback,
            "function_lib_description": function_lib_description,
            "experiment_output_format": experiment_output_format,
            "target_list": factor_list,
            "RAG": None,
        }, True
        
    def convert(self, hypothesis: Hypothesis, trace: Trace) -> Experiment:
        context, json_flag = self.prepare_context(hypothesis, trace)
        system_prompt = (
            Environment(undefined=StrictUndefined)
            .from_string(alphapilot_prompt_dict["hypothesis2experiment"]["system_prompt"])
            .render(
                targets=self.targets,
                scenario=trace.scen.background, # get_scenario_all_desc(filtered_tag="hypothesis_and_experiment"),
                experiment_output_format=context["experiment_output_format"],
            )
        )
        expression_validation_prompt: str | None = None
        expression_duplication_prompt: str | None = None
        user_prompt = self._render_hypothesis2experiment_user_prompt(
            context,
            expression_validation_errors=expression_validation_prompt,
            expression_duplication=expression_duplication_prompt,
        )

        # Detect duplicated sub-expressions; retry with feedback on parse / evaluate / duplication errors
        flag = False
        while True:
            if flag:
                break

            resp = get_llm().chat_completion(user_prompt, system_prompt, json_mode=json_flag)
            response_dict = json.loads(resp)
            proposed_names = []
            proposed_exprs = []

            for i, factor_name in enumerate(response_dict):
                expr = response_dict[factor_name]["expression"]

                ok, eval_dict, error_message = self.factor_regulator.check_expression(expr)
                if not ok:
                    logger.info(
                        f"Factor expression validation failed for {factor_name!r}: {error_message}; retrying with feedback."
                    )
                    expression_validation_prompt = self._append_expression_validation_error(
                        expression_validation_prompt,
                        factor_name=factor_name,
                        expression=expr,
                        error_message=error_message or "Unknown validation error.",
                    )
                    user_prompt = self._render_hypothesis2experiment_user_prompt(
                        context,
                        expression_validation_errors=expression_validation_prompt,
                        expression_duplication=expression_duplication_prompt,
                    )
                    break

                # If expression has problems, regenerate with feedback
                if not self.factor_regulator.is_expression_acceptable(eval_dict):
                    if expression_duplication_prompt is not None:
                        expression_duplication_prompt = "\n\n".join(
                            [
                                expression_duplication_prompt,
                                (
                                    Environment(undefined=StrictUndefined)
                                    .from_string(alphapilot_prompt_dict["expression_duplication"])
                                    .render(
                                        prev_expression=expr,
                                        duplicated_subtree_size=eval_dict["duplicated_subtree_size"],
                                        duplicated_subtree=eval_dict["duplicated_subtree"],
                                    )
                                ),
                            ]
                        )
                    else:
                        expression_duplication_prompt = (
                            Environment(undefined=StrictUndefined)
                            .from_string(alphapilot_prompt_dict["expression_duplication"])
                            .render(
                                prev_expression=expr,
                                duplicated_subtree_size=eval_dict["duplicated_subtree_size"],
                                duplicated_subtree=eval_dict["duplicated_subtree"],
                            )
                        )

                    user_prompt = self._render_hypothesis2experiment_user_prompt(
                        context,
                        expression_validation_errors=expression_validation_prompt,
                        expression_duplication=expression_duplication_prompt,
                    )
                    break

                proposed_names.append(factor_name)
                proposed_exprs.append(expr)
                if i == len(response_dict) - 1:
                    flag = True
        

        # Add valid factors to the factor regulator
        self.factor_regulator.add_factor(proposed_names, proposed_exprs)
                
                
        return self.convert_response(resp, trace)
    

    def convert_response(self, response: str, trace: Trace) -> FactorExperiment:
        response_dict = json.loads(response)
        tasks = []

        for factor_name in response_dict:
            description = response_dict[factor_name]["description"]
            formulation = response_dict[factor_name]["formulation"]
            expression = response_dict[factor_name]["expression"]
            variables = response_dict[factor_name]["variables"]
            tasks.append(
                FactorTask(
                    factor_name=factor_name,
                    factor_description=description,
                    factor_formulation=formulation,
                    factor_expression=expression,
                    variables=variables,
                )
            )
            
        tpl = _qlib_template_dir_from_trace(trace)
        exp = QlibFactorExperiment(tasks, template_folder_path=tpl)
        exp.based_experiments = [QlibFactorExperiment(sub_tasks=[], template_folder_path=tpl)] + [
            t[1] for t in trace.hist if t[2]
        ]

        unique_tasks = []

        for task in tasks:
            duplicate = False
            for based_exp in exp.based_experiments:
                for sub_task in based_exp.sub_tasks:
                    if task.factor_name == sub_task.factor_name:
                        duplicate = True
                        break
                if duplicate:
                    break
            if not duplicate:
                unique_tasks.append(task)

        exp.tasks = unique_tasks
        return exp



class BacktestHypothesis2FactorExpression(FactorHypothesis2Experiment):
    def __init__(self, factor_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.factor_path = factor_path
        
    def convert_response(self, *args, **kwargs) -> FactorExperiment:
        return super().convert_response(*args, **kwargs)
        
    def prepare_context(self, *args, **kwargs) -> Tuple[dict | bool]:
        return super().prepare_context(*args, **kwargs)
        
    def convert(self, hypothesis: Hypothesis, trace: Trace) -> FactorExperiment:
        if os.path.exists(self.factor_path):
            tasks = []
            factor_df = pd.read_csv(self.factor_path, usecols=["factor_name", "factor_expression"], index_col=None)
            for index, row in factor_df.iterrows():
                tasks.append(
                    FactorTask(
                        factor_name=row["factor_name"],
                        factor_description="",
                        factor_formulation="",
                        factor_expression=row["factor_expression"],
                        variables="",
                    )
                )
            
            tpl = _qlib_template_dir_from_trace(trace)
            exp = QlibFactorExperiment(tasks, template_folder_path=tpl)
            exp.based_experiments = [QlibFactorExperiment(sub_tasks=[], template_folder_path=tpl)] + [
                t[1] for t in trace.hist if t[2]
            ]

            unique_tasks = []

            for task in tasks:
                duplicate = False
                for based_exp in exp.based_experiments:
                    for sub_task in based_exp.sub_tasks:
                        if task.factor_name == sub_task.factor_name:
                            duplicate = True
                            break
                    if duplicate:
                        break
                if not duplicate:
                    unique_tasks.append(task)

            exp.tasks = unique_tasks
            return exp
            
        else:
            raise ValueError(f"File {self.factor_csv_path} does not exist. ")
        
    