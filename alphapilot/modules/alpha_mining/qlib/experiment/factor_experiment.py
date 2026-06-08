from copy import deepcopy
from pathlib import Path

from alphapilot.core.experiment import Task
from alphapilot.core.prompts import Prompts
from alphapilot.core.scenario import Scenario
from alphapilot.modules.alpha_mining.qlib.experiment.template_paths import resolve_qlib_template_dir
from alphapilot.modules.alpha_mining.qlib.experiment.utils import get_data_folder_intro

rdagent_prompt_dict = Prompts(file_path=Path(__file__).parent / "prompts_rdagent.yaml")

__all__ = [
    "QlibFactorScenario",
    "QlibAlphaPilotScenario",
]


class QlibFactorScenario(Scenario):
    def __init__(self, qlib_template_dir: str | Path | None = None) -> None:
        super().__init__()
        self.qlib_template_dir = resolve_qlib_template_dir(qlib_template_dir)
        self._background = deepcopy(rdagent_prompt_dict["qlib_factor_background"])
        self._source_data = deepcopy(get_data_folder_intro())
        self._output_format = deepcopy(rdagent_prompt_dict["qlib_factor_output_format"])
        self._interface = deepcopy(rdagent_prompt_dict["qlib_factor_interface"])
        self._strategy = deepcopy(rdagent_prompt_dict["qlib_factor_strategy"])
        self._simulator = deepcopy(rdagent_prompt_dict["qlib_factor_simulator"])
        self._rich_style_description = deepcopy(rdagent_prompt_dict["qlib_factor_rich_style_description"])
        self._experiment_setting = deepcopy(rdagent_prompt_dict["qlib_factor_experiment_setting"])

    @property
    def background(self) -> str:
        return self._background

    def get_source_data_desc(self, task: Task | None = None) -> str:
        return self._source_data

    @property
    def output_format(self) -> str:
        return self._output_format

    @property
    def interface(self) -> str:
        return self._interface

    @property
    def simulator(self) -> str:
        return self._simulator

    @property
    def rich_style_description(self) -> str:
        return self._rich_style_description

    @property
    def experiment_setting(self) -> str:
        return self._experiment_setting

    @property
    def is_mining_scenario(self) -> bool:
        return True

    @property
    def has_alpha158_baseline(self) -> bool:
        return True

    @property
    def uses_qlib_metric_index(self) -> bool:
        return True

    def get_scenario_all_desc(
        self, task: Task | None = None, filtered_tag: str | None = None, simple_background: bool | None = None
    ) -> str:
        """A static scenario describer"""
        if simple_background:
            return f"""Background of the scenario:
{self.background}"""
        return f"""Background of the scenario:
{self.background}
The source data you can use:
{self.get_source_data_desc(task)}
The interface you should follow to write the runnable code:
{self.interface}
The output of your code should be in the format:
{self.output_format}
The simulator user can use to test your factor:
{self.simulator}
"""



alphapilot_prompt_dict = Prompts(file_path=Path(__file__).parent / "prompts_alphapilot.yaml")
class QlibAlphaPilotScenario(Scenario):
    def __init__(self, use_local: bool = True, qlib_template_dir: str | Path | None = None) -> None:
        super().__init__()
        self.qlib_template_dir = resolve_qlib_template_dir(qlib_template_dir)
        self._background = deepcopy(alphapilot_prompt_dict["qlib_factor_background"])
        self._source_data = deepcopy(get_data_folder_intro(use_local=use_local))
        self._output_format = deepcopy(alphapilot_prompt_dict["qlib_factor_output_format"])
        self._interface = deepcopy(alphapilot_prompt_dict["qlib_factor_interface"])
        self._strategy = deepcopy(alphapilot_prompt_dict["qlib_factor_strategy"])
        self._simulator = deepcopy(alphapilot_prompt_dict["qlib_factor_simulator"])
        self._rich_style_description = deepcopy(alphapilot_prompt_dict["qlib_factor_rich_style_description"])
        self._experiment_setting = deepcopy(alphapilot_prompt_dict["qlib_factor_experiment_setting"])

    @property
    def background(self) -> str:
        return self._background

    def get_source_data_desc(self, task: Task | None = None) -> str:
        return self._source_data

    @property
    def output_format(self) -> str:
        return self._output_format

    @property
    def interface(self) -> str:
        return self._interface

    @property
    def simulator(self) -> str:
        return self._simulator

    @property
    def rich_style_description(self) -> str:
        return self._rich_style_description

    @property
    def experiment_setting(self) -> str:
        return self._experiment_setting

    @property
    def is_mining_scenario(self) -> bool:
        return True

    def get_scenario_all_desc(
        self, task: Task | None = None, filtered_tag: str | None = None, simple_background: bool | None = None
    ) -> str:
        """A static scenario describer"""
        if simple_background:
            return f"""Background of the scenario:
{self.background}"""
        return f"""Background of the scenario:
{self.background}
The source data you can use:
{self.get_source_data_desc(task)}
The interface you should follow to write the runnable code:
{self.interface}
The simulator user can use to test your factor:
{self.simulator}
"""