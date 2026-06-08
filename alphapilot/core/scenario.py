from abc import ABC, abstractmethod

from alphapilot.core.experiment import Task


class Scenario(ABC):
    @property
    @abstractmethod
    def background(self) -> str:
        """Background information"""

    # TODO: We have to change all the sub classes to override get_source_data_desc instead of `source_data`
    def get_source_data_desc(self, task: Task | None = None) -> str:  # noqa: ARG002
        """
        Source data description

        The choice of data may vary based on the specific task at hand.
        """
        return ""

    @property
    def source_data(self) -> str:
        """
        A convenient shortcut for describing source data
        """
        return self.get_source_data_desc()

    @property
    @abstractmethod
    def interface(self) -> str:
        """Interface description about how to run the code"""

    @property
    @abstractmethod
    def output_format(self) -> str:
        """Output format description"""

    @property
    @abstractmethod
    def simulator(self) -> str:
        """Simulator description"""

    @property
    @abstractmethod
    def rich_style_description(self) -> str:
        """Rich style description to present"""

    @abstractmethod
    def get_scenario_all_desc(
        self,
        task: Task | None = None,
        filtered_tag: str | None = None,
        simple_background: bool | None = None,
    ) -> str:
        """
        Combine all descriptions together

        The scenario description varies based on the task being performed.
        """

    @property
    def experiment_setting(self) -> str | None:
        """Get experiment setting and return as rich text string"""
        return None

    # ---- UI presentation traits ----
    #
    # Overridable metadata the log UI consumes to decide how to render a
    # trace, without importing concrete scenario classes (keeps the infra
    # ``log`` layer decoupled from feature modules). Defaults suit
    # non-mining / evaluation scenarios.

    @property
    def is_mining_scenario(self) -> bool:
        """True for LLM-driven evolving mining scenarios whose logs follow the
        round / hypothesis / evolving-code UI layout."""
        return False

    @property
    def has_alpha158_baseline(self) -> bool:
        """True if runner results carry an Alpha158 baseline row the UI charts."""
        return False

    @property
    def uses_qlib_metric_index(self) -> bool:
        """True if result Series are indexed by qlib metric names, so the UI can
        slice them down to the selected metric subset."""
        return False
