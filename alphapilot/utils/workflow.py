"""
This is a class that try to store/resume/traceback the workflow session


Postscripts:
- Originally, I want to implement it in a more general way with python generator.
  However, Python generator is not picklable (dill does not support pickle as well)

"""

import datetime
import pickle
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tqdm.auto import tqdm

from alphapilot.core.exception import CoderError
from alphapilot.log import logger
from alphapilot.log.mine_paths import mining_round_tag, session_snapshot_path
import threading

class LoopMeta(type):
    @staticmethod
    def _get_steps(bases):
        """
        Recursively get all the `steps` from the base classes and combine them into a single list.

        Args:
            bases (tuple): A tuple of base classes.

        Returns:
            List[Callable]: A list of steps combined from all base classes.
        """
        # import pdb; pdb.set_trace()
        steps = []
        for base in bases:
            for step in LoopMeta._get_steps(base.__bases__) + getattr(base, "steps", []):
                if step not in steps:
                    steps.append(step)
        return steps

    def __new__(cls, clsname, bases, attrs):
        """
        Create a new class with combined steps from base classes and current class.

        Args:
            clsname (str): Name of the new class.
            bases (tuple): Base classes.
            attrs (dict): Attributes of the new class.

        Returns:
            LoopMeta: A new instance of LoopMeta.
        """
        steps = LoopMeta._get_steps(bases)  # all the base classes of parents
        for name, attr in attrs.items():
            # Only public methods are workflow steps. Any name starting with an
            # underscore is a private helper (e.g. ``_save_strategy_asset``,
            # ``_save_factors_to_library``) that the steps call internally — it
            # must NOT be auto-registered as a standalone step, or it would run
            # an extra time per round (double-saving, bypassing flag gates).
            if not name.startswith("_") and isinstance(attr, Callable):
                if name not in steps:
                    # NOTE: if we override the step in the subclass
                    # Then it is not the new step. So we skip it.
                    steps.append(name)
        attrs["steps"] = steps
        return super().__new__(cls, clsname, bases, attrs)


@dataclass
class LoopTrace:
    start: datetime.datetime  # the start time of the trace
    end: datetime.datetime  # the end time of the trace
    # TODO: more information about the trace


_FACTOR_MINING_STEP_LABELS: dict[str, str] = {
    "factor_propose": "假说生成",
    "factor_construct": "因子表达式构造",
    "factor_calculate": "因子值计算",
    "factor_backtest": "Qlib 回测",
    "feedback": "回测反馈总结",
}


class LoopBase:
    steps: list[Callable]  # a list of steps to work on
    loop_trace: dict[int, list[LoopTrace]]

    skip_loop_error: tuple[Exception] = field(
        default_factory=tuple
    )  # you can define a list of error that will skip current loop

    def __init__(self):
        self.loop_idx = 0  # current loop index
        self.step_idx = 0  # the index of next step to be run
        self.loop_prev_out = {}  # the step results of current loop
        self.loop_trace = defaultdict(list[LoopTrace])  # the key is the number of loop
        self.session_folder = logger.log_trace_path / "session_snapshots"

    def _is_factor_mining_workflow(self) -> bool:
        return "factor_propose" in getattr(self, "steps", [])

    def _log_factor_mining_round_start(self, loop_idx: int) -> None:
        round_no = loop_idx + 1
        logger.info("=" * 72)
        logger.info(
            f"[因子挖掘] >>> 第 {round_no} 轮开始 <<<  (loop_index={loop_idx}, "
            f"共 {len(self.steps)} 步/轮)"
        )
        logger.info("=" * 72)

    def _log_factor_mining_step_start(self, loop_idx: int, step_idx: int, step_name: str) -> None:
        round_no = loop_idx + 1
        step_no = step_idx + 1
        label = _FACTOR_MINING_STEP_LABELS.get(step_name, step_name)
        logger.info(
            f"[因子挖掘] 第 {round_no} 轮 | 步骤 {step_no}/{len(self.steps)}: {label} ({step_name})"
        )

    def _log_factor_mining_round_end(self, loop_idx: int) -> None:
        round_no = loop_idx + 1
        logger.info("-" * 72)
        logger.info(f"[因子挖掘] <<< 第 {round_no} 轮结束 >>>  (loop_index={loop_idx})")
        logger.info("-" * 72)

    def run(self, step_n: int | None = None, stop_event: threading.Event = None):
        """

        Parameters
        ----------
        step_n : int | None
            How many steps to run;
            `None` indicates to run forever until error or KeyboardInterrupt
        """
        with tqdm(total=len(self.steps), desc="Workflow Progress", unit="step") as pbar:
            while True:
                if step_n is not None:
                    if step_n <= 0:
                        break
                    step_n -= 1

                li, si = self.loop_idx, self.step_idx

                start = datetime.datetime.now(datetime.timezone.utc)

                name = self.steps[si]
                if self._is_factor_mining_workflow() and si == 0:
                    self._log_factor_mining_round_start(li)
                if self._is_factor_mining_workflow():
                    self._log_factor_mining_step_start(li, si, name)
                func = getattr(self, name)
                try:
                    if self._is_factor_mining_workflow():
                        round_no = li + 1
                        with logger.tag(mining_round_tag(round_no, name)):
                            self.loop_prev_out[name] = func(self.loop_prev_out)
                    else:
                        self.loop_prev_out[name] = func(self.loop_prev_out)

                    # TODO: Fix the error logger.exception(f"Skip loop {li} due to {e}")
                except self.skip_loop_error as e:
                    logger.warning(f"Skip loop {li} due to {e}")
                    self.loop_idx += 1
                    self.step_idx = 0
                    continue
                except CoderError as e:
                    logger.warning(f"Traceback loop {li} due to {e}")
                    self.step_idx = 0
                    continue

                end = datetime.datetime.now(datetime.timezone.utc)

                self.loop_trace[li].append(LoopTrace(start, end))

                # Update tqdm progress bar
                pbar.set_postfix(loop_index=li, step_index=si, step_name=name)
                pbar.update(1)

                # index increase and save session
                finished_last_step_of_round = (self.step_idx + 1) % len(self.steps) == 0
                if self._is_factor_mining_workflow() and finished_last_step_of_round:
                    self._log_factor_mining_round_end(li)
                self.step_idx = (self.step_idx + 1) % len(self.steps)
                if self.step_idx == 0:  # reset to step 0 in next round
                    self.loop_idx += 1
                    self.loop_prev_out = {}
                    pbar.reset()  # reset the progress bar for the next loop
                snapshot_path = session_snapshot_path(
                    logger.log_trace_path, li, si, name
                )
                self.dump(snapshot_path)
                
                if stop_event is not None and stop_event.is_set():
                    # break
                    raise Exception("Mining stopped by user")
                    
                
    def dump(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str | Path):
        path = Path(path)
        with path.open("rb") as f:
            session = pickle.load(f)
        logger.set_trace_path(session.session_folder.parent)

        max_loop = max(session.loop_trace.keys())
        logger.storage.truncate(time=session.loop_trace[max_loop][-1].end)
        return session
