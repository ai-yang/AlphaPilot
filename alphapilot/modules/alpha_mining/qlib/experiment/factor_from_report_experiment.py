from copy import deepcopy
from pathlib import Path

from alphapilot.core.prompts import Prompts
from alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment import QlibFactorScenario

prompt_dict = Prompts(file_path=Path(__file__).parent / "prompts_rdagent.yaml")


class QlibFactorFromReportScenario(QlibFactorScenario):
    def __init__(self) -> None:
        super().__init__()
        self._rich_style_description = deepcopy(prompt_dict["qlib_factor_from_report_rich_style_description"])

    @property
    def rich_style_description(self) -> str:
        return self._rich_style_description
