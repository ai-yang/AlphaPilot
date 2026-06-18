"""DSO runner -- deep symbolic optimization alpha mining (vendored dso).

Faithful refactor of ``AlphaForge/train_DSO.py``. DSO is the heaviest backend:
it needs TensorFlow and the compiled Cython ``dso/cyfunc`` extension. Those are
OPTIONAL deps -- imported lazily here so that ``mine_gp`` / ``mine_rl`` work
without them; a missing dep raises a clear install hint.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

# sys.path shim for vendored packages.
import alphapilot.modules.alphaforge  # noqa: F401
from alphapilot.modules.alphaforge.data_adapter import default_target, get_data_splits
from alphapilot.modules.alphaforge.device import resolve_device, use_fork_start_method

# Names referenced by ``eval(expr_str)`` in the evaluator.
from alphagen.data.expression import *  # noqa: F401,F403
from alphagen_generic.features import *  # noqa: F401,F403

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context

_CONSTANTS = [-30.0, -10.0, -5.0, -2.0, -1.0, -0.5, -0.01, 0.01, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]

_INSTALL_HINT = (
    "DSO mining requires optional dependencies that are not installed:\n"
    "  pip install tensorflow cython\n"
    "and the dso Cython extension must be built (cyfunc):\n"
    "  cd alphapilot/modules/alphaforge/vendor/dso && python setup.py build_ext --inplace\n"
    "GP and RL backends do not need these. Original import error: {err}"
)


class DSORunner:
    def __init__(
        self,
        *,
        context: "Context",
        instruments: str = "csi300",
        train_end_year: int = 2020,
        freq: str = "day",
        seed: int = 0,
        n_samples: int = 5000,
        pool_capacity: int = 10,
        device: str | None = None,
        qlib_dir: str | None = None,
        raw: bool = False,
    ):
        self.context = context
        self.instruments = instruments
        self.train_end_year = train_end_year
        self.freq = freq
        self.seed = seed
        self.n_samples = n_samples
        self.pool_capacity = pool_capacity
        self.device_pref = device
        self.qlib_dir = qlib_dir
        self.raw = raw

    def run(self) -> tuple[list[Any], list[float]]:
        try:
            import tensorflow as tf
            from dso import DeepSymbolicRegressor, functions
            from dso.library import HardCodedConstant, Token
        except Exception as err:  # noqa: BLE001 - optional heavy deps
            raise RuntimeError(_INSTALL_HINT.format(err=err)) from err

        from alphagen.models.alpha_pool import AlphaPool
        from alphagen.utils.random import reseed_everything
        from alphagen_generic.operators import funcs as generic_funcs

        use_fork_start_method()
        dev = resolve_device(self.device_pref)
        # TF1/TF2 seed API compatibility.
        if hasattr(tf, "set_random_seed"):
            tf.set_random_seed(self.seed)
        else:
            tf.random.set_seed(self.seed)
        reseed_everything(self.seed)

        splits = get_data_splits(
            self.context, instruments=self.instruments, train_end_year=self.train_end_year,
            freq=self.freq, device=dev, raw=self.raw, qlib_dir=self.qlib_dir,
        )
        data = splits.train
        target = default_target()

        funcs = {func.name: Token(complexity=1, **func._asdict()) for func in generic_funcs}
        for i, feat in enumerate(["open", "close", "high", "low", "volume", "vwap"]):
            funcs[f"x{i + 1}"] = Token(name=feat, arity=0, complexity=1, function=None, input_var=i)
        for v in _CONSTANTS:
            funcs[f"Constant({v})"] = HardCodedConstant(name=f"Constant({v})", value=v)
        functions.function_map = funcs

        pool = AlphaPool(capacity=self.pool_capacity, stock_data=data, target=target, ic_lower_bound=None)

        class _Ev:
            def __init__(self, pool):
                self.cnt = 0
                self.pool = pool

            def alpha_ev_fn(self, key):
                try:
                    self.pool.try_new_expr(eval(key))
                except Exception:  # noqa: BLE001
                    pass
                self.cnt += 1
                return -1.0

        ev = _Ev(pool)
        config = dict(
            task=dict(
                task_type="regression",
                function_set=list(funcs.keys()),
                metric="alphagen",
                metric_params=[lambda key: ev.alpha_ev_fn(key)],
            ),
            training={"n_samples": self.n_samples, "batch_size": 128, "epsilon": 0.05},
            prior={"length": {"min_": 2, "max_": 20, "on": True}},
            experiment={"seed": self.seed},
        )

        x = np.array([["open_", "close", "high", "low", "volume", "vwap"]])
        y = np.array([[1]])
        model = DeepSymbolicRegressor(config=config)
        model.fit(x, y)

        state = pool.state
        exprs = list(state.get("exprs", []))
        scores = list(state.get("ics_ret", [])) or [0.0] * len(exprs)
        return exprs, scores
