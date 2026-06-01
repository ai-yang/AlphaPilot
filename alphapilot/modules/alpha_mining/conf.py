from alphapilot.components.workflow.conf import BasePropSetting
from alphapilot.core.conf import ExtendedSettingsConfigDict


class ModelBasePropSetting(BasePropSetting):
    model_config = ExtendedSettingsConfigDict(env_prefix="QLIB_MODEL_", protected_namespaces=())

    # 1) override base settings
    scen: str = "alphapilot.modules.alpha_mining.qlib.experiment.model_experiment.QlibModelScenario"
    """Scenario class for Qlib Model"""

    hypothesis_gen: str = "alphapilot.modules.alpha_mining.qlib.proposal.model_proposal.QlibModelHypothesisGen"
    """Hypothesis generation class"""

    hypothesis2experiment: str = "alphapilot.modules.alpha_mining.qlib.proposal.model_proposal.QlibModelHypothesis2Experiment"
    """Hypothesis to experiment class"""

    coder: str = "alphapilot.modules.alpha_mining.qlib.developer.model_coder.QlibModelCoSTEER"
    """Coder class"""

    runner: str = "alphapilot.modules.alpha_mining.qlib.developer.model_runner.QlibModelRunner"
    """Runner class"""

    summarizer: str = "alphapilot.modules.alpha_mining.qlib.developer.feedback.QlibModelHypothesisExperiment2Feedback"
    """Summarizer class"""

    evolving_n: int = 10
    """Number of evolutions"""


class FactorBasePropSetting(BasePropSetting):
    model_config = ExtendedSettingsConfigDict(env_prefix="QLIB_FACTOR_", protected_namespaces=())

    # 1) override base settings
    scen: str = "alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment.QlibFactorScenario"
    """Scenario class for Qlib Factor"""

    hypothesis_gen: str = "alphapilot.modules.alpha_mining.qlib.proposal.factor_proposal.QlibFactorHypothesisGen"
    """Hypothesis generation class"""

    hypothesis2experiment: str = "alphapilot.modules.alpha_mining.qlib.proposal.factor_proposal.QlibFactorHypothesis2Experiment"
    """Hypothesis to experiment class"""

    coder: str = "alphapilot.modules.alpha_mining.qlib.developer.factor_coder.QlibFactorCoSTEER"
    """Coder class"""

    runner: str = "alphapilot.modules.alpha_mining.qlib.developer.factor_runner.QlibFactorRunner"
    """Runner class"""

    summarizer: str = "alphapilot.modules.alpha_mining.qlib.developer.feedback.QlibFactorHypothesisExperiment2Feedback"
    """Summarizer class"""

    evolving_n: int = 10
    """Number of evolutions"""
    

class AlphaPilotFactorBasePropSetting(BasePropSetting):
    model_config = ExtendedSettingsConfigDict(env_prefix="QLIB_FACTOR_", protected_namespaces=())

    # 1) override base settings
    scen: str = "alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment.QlibAlphaPilotScenario"
    """Scenario class for Qlib Factor"""

    hypothesis_gen: str = "alphapilot.modules.alpha_mining.qlib.proposal.factor_proposal.AlphaPilotHypothesisGen"
    """Hypothesis generation class"""

    hypothesis2experiment: str = "alphapilot.modules.alpha_mining.qlib.proposal.factor_proposal.AlphaPilotHypothesis2FactorExpression"
    """Hypothesis to experiment class"""

    # coder: str = "alphapilot.modules.alpha_mining.qlib.developer.factor_coder.QlibFactorCoSTEER"
    coder: str = "alphapilot.modules.alpha_mining.qlib.developer.factor_coder.QlibFactorParser"
    """Coder class"""

    runner: str = "alphapilot.modules.alpha_mining.qlib.developer.factor_runner.QlibFactorRunner"
    """Runner class"""

    summarizer: str = "alphapilot.modules.alpha_mining.qlib.developer.feedback.AlphaPilotQlibFactorHypothesisExperiment2Feedback"
    """Summarizer class"""

    evolving_n: int = 5
    """Number of evolutions"""

class FactorBackTestBasePropSetting(BasePropSetting):
    model_config = ExtendedSettingsConfigDict(env_prefix="QLIB_FACTOR_", protected_namespaces=())

    # 1) override base settings
    scen: str = "alphapilot.modules.alpha_mining.qlib.experiment.factor_experiment.QlibAlphaPilotScenario"
    """Scenario class for Qlib Factor"""

    hypothesis_gen: str = "alphapilot.modules.alpha_mining.qlib.proposal.factor_proposal.EmptyHypothesisGen"
    """Hypothesis generation class"""

    hypothesis2experiment: str = "alphapilot.modules.alpha_mining.qlib.proposal.factor_proposal.BacktestHypothesis2FactorExpression"
    """Hypothesis to experiment class"""

    coder: str = "alphapilot.modules.alpha_mining.qlib.developer.factor_coder.QlibFactorCoder"
    """Coder class"""

    runner: str = "alphapilot.modules.alpha_mining.qlib.developer.factor_runner.QlibFactorRunner"
    """Runner class"""

    summarizer: str = "alphapilot.modules.alpha_mining.qlib.developer.feedback.QlibFactorHypothesisExperiment2Feedback"
    """Summarizer class"""

    evolving_n: int = 1
    """Number of evolutions"""


class FactorFromReportPropSetting(FactorBasePropSetting):
    # 1) override the scen attribute
    scen: str = "alphapilot.modules.alpha_mining.qlib.experiment.factor_from_report_experiment.QlibFactorFromReportScenario"
    """Scenario class for Qlib Factor from Report"""

    # 2) sub task specific:
    report_result_json_file_path: str = "git_ignore_folder/report_list.json"
    """Path to the JSON file listing research reports for factor extraction"""

    max_factors_per_exp: int = 10000
    """Maximum number of factors implemented per experiment"""

    is_report_limit_enabled: bool = False
    """Limits report processing count if True; processes all if False"""


FACTOR_PROP_SETTING = FactorBasePropSetting()
FACTOR_FROM_REPORT_PROP_SETTING = FactorFromReportPropSetting()
MODEL_PROP_SETTING = ModelBasePropSetting()
ALPHAPILOT_FACTOR_PROP_SETTING = AlphaPilotFactorBasePropSetting()
FACTOR_BACK_TEST_PROP_SETTING = FactorBackTestBasePropSetting()