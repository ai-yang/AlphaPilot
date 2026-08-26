"""GP runner -- genetic-programming alpha mining (vendored gplearn).

Faithful refactor of ``AlphaForge/train_GP.py``: a gplearn ``SymbolicRegressor``
searches formula strings whose fitness is the in-sample IC (computed on the
vendored alphagen torch engine). We drop the expensive per-generation
AlphaPool reporting callback -- the ``cache`` of ``{expr_str: ic}`` is filled
during fitness evaluation regardless -- and return the top-N cached factors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

# sys.path shim for vendored packages.
import alphapilot.modules.alphaforge  # noqa: F401
from alphapilot.modules.alphaforge.data_adapter import (
    LoadedTrainingData,
    TargetSpec,
    TrainingSpec,
    VwapSpec,
    get_train_data,
)
from alphapilot.modules.alphaforge.device import resolve_device, use_fork_start_method

# Names referenced by ``eval(expr_str)`` must be in module globals.
from alphagen.data.expression import *  # noqa: F401,F403
from alphagen_generic.features import *  # noqa: F401,F403

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context

_CONSTANTS = [-30.0, -10.0, -5.0, -2.0, -1.0, -0.5, -0.01, 0.01, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]


class GPRunner:
    def __init__(
        self,
        *,
        context: "Context",
        instruments: str = "csi300",
        train_end_year: int = 2020,
        train_start_date: str | None = None,
        train_end_date: str | None = None,
        freq: str = "day",
        seed: int = 0,
        population_size: int = 1000,
        generations: int = 40,
        tournament_size: int = 600,
        top_n: int = 20,
        target_horizon: int = 20,
        target_price: str = "vwap",
        vwap_mode: str = "amount_volume",
        device: str | None = None,
        qlib_dir: str | None = None,
        raw: bool = False,
    ):
        self.context = context
        self.instruments = instruments
        self.train_end_year = train_end_year
        self.train_start_date = train_start_date
        self.train_end_date = train_end_date
        self.training_spec = TrainingSpec.resolve(
            train_end_year=train_end_year,
            train_start_date=train_start_date,
            train_end_date=train_end_date,
        )
        self.freq = freq
        self.seed = seed
        self.population_size = population_size
        self.generations = generations
        self.tournament_size = tournament_size
        self.top_n = top_n
        self.target_spec = TargetSpec(target_horizon, target_price)
        self.target_horizon = self.target_spec.horizon
        self.target_price = self.target_spec.price
        self.vwap_spec = VwapSpec(vwap_mode)
        self.device_pref = device
        self.qlib_dir = qlib_dir
        self.raw = raw
        self.training_data: LoadedTrainingData | None = None

    def run(self) -> tuple[list[Any], list[float]]:
        import torch
        from collections import Counter
        from gplearn.fitness import make_fitness
        from gplearn.functions import make_function
        from gplearn.genetic import SymbolicRegressor
        from alphagen.utils.correlation import batch_pearsonr
        from alphagen.utils.pytorch_utils import normalize_by_day
        from alphagen.utils.random import reseed_everything
        from alphagen_generic.operators import funcs as generic_funcs

        use_fork_start_method()
        dev = resolve_device(self.device_pref)
        reseed_everything(self.seed)
        target = self.target_spec.build_expression()
        training_data = get_train_data(
            self.context,
            training_spec=self.training_spec,
            target_spec=self.target_spec,
            vwap_spec=self.vwap_spec,
            instruments=self.instruments,
            freq=self.freq, device=dev, raw=self.raw, qlib_dir=self.qlib_dir,
        )
        self.training_data = training_data
        data = training_data.data
        target_factor = target.evaluate(data)
        cache: dict[str, float] = {}

        def _metric(x, y, w):
            key = y[0]
            if key in cache:
                return cache[key]
            if key.count("(") + key.count(")") > 20:
                return -1.0
            try:
                factor = normalize_by_day(eval(key).evaluate(data))
                ic = torch.nan_to_num(batch_pearsonr(factor, target_factor)).mean().item()
            except Exception:  # noqa: BLE001 - illegal expr -> worst fitness
                ic = -1.0
            if np.isnan(ic):
                ic = -1.0
            cache[key] = ic
            return ic

        metric = make_fitness(function=_metric, greater_is_better=True)
        funcs = [make_function(**f._asdict()) for f in generic_funcs]
        features = ["open_", "close", "high", "low", "volume", "vwap"]
        terminals = features + [f"Constant({v})" for v in _CONSTANTS]
        x_train = np.array([terminals])
        y_train = np.array([[1]])

        est = SymbolicRegressor(
            population_size=self.population_size,
            generations=self.generations,
            init_depth=(2, 6),
            tournament_size=min(self.tournament_size, max(2, self.population_size)),
            stopping_criteria=1.0,
            p_crossover=0.3, p_subtree_mutation=0.1, p_hoist_mutation=0.01,
            p_point_mutation=0.1, p_point_replace=0.6,
            max_samples=0.9, verbose=0, parsimony_coefficient=0.0,
            random_state=self.seed, function_set=funcs, metric=metric,
            const_range=None, n_jobs=1,
        )
        est.fit(x_train, y_train)

        exprs: list[Any] = []
        scores: list[float] = []
        for key, ic in Counter(cache).most_common(self.top_n):
            if ic <= -1.0:
                continue
            try:
                exprs.append(eval(key))
                scores.append(ic)
            except Exception:  # noqa: BLE001
                continue
        return exprs, scores
