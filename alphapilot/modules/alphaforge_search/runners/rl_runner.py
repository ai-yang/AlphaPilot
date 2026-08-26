"""RL runner -- PPO-over-expression-tokens alpha mining.

Faithful refactor of ``AlphaForge/train_RL.py``: a ``MaskablePPO`` agent builds
formulaic alphas token-by-token in ``AlphaEnv``; accepted factors accumulate in
an ``AlphaPool``. We train without the heavy per-rollout reporting callback and
read the final pool. ``tensorboard_log`` is disabled (tensorboard is optional).

NOTE: the vendored RL stack imports the unmaintained ``gym`` (no official
NumPy-2 support). It may need ``gym``/``shimmy`` shimming on this env; that is
the documented "fix compat as it surfaces" risk for the RL backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class RLRunner:
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
        steps: int = 200_000,
        pool_capacity: int = 10,
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
        self.steps = steps
        self.pool_capacity = pool_capacity
        self.target_spec = TargetSpec(target_horizon, target_price)
        self.target_horizon = self.target_spec.horizon
        self.target_price = self.target_spec.price
        self.vwap_spec = VwapSpec(vwap_mode)
        self.device_pref = device
        self.qlib_dir = qlib_dir
        self.raw = raw
        self.training_data: LoadedTrainingData | None = None

    def run(self) -> tuple[list[Any], list[float]]:
        from sb3_contrib.ppo_mask import MaskablePPO
        from alphagen.models.alpha_pool import AlphaPool
        from alphagen.rl.env.wrapper import AlphaEnv
        from alphagen.rl.policy import LSTMSharedNet
        from alphagen.utils.random import reseed_everything

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

        pool = AlphaPool(capacity=self.pool_capacity, stock_data=data, target=target, ic_lower_bound=None)
        env = AlphaEnv(pool=pool, device=dev, print_expr=False)

        model = MaskablePPO(
            "MlpPolicy", env,
            policy_kwargs=dict(
                features_extractor_class=LSTMSharedNet,
                features_extractor_kwargs=dict(n_layers=2, d_model=128, dropout=0.1, device=dev),
            ),
            gamma=1.0, ent_coef=0.01, batch_size=128,
            tensorboard_log=None, device=str(dev), verbose=0,
        )
        model.learn(total_timesteps=self.steps)

        state = pool.state
        exprs = list(state.get("exprs", []))
        scores = list(state.get("ics_ret", [])) or [0.0] * len(exprs)
        return exprs, scores
