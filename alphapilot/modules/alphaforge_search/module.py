"""AlphaForgeSearchModule: GP / RL formulaic alpha mining.

These are the non-GAN baselines bundled with AlphaForge, merged into a
single module:

* ``mine_gp``  -- genetic programming (vendored ``gplearn``); lightest deps.
* ``mine_rl``  -- PPO over expression tokens (``stable-baselines3`` +
  ``sb3-contrib``); medium deps.

Both share the vendored alphagen expression engine for evaluation and,
on output, the same translate -> validate -> backtest pipeline as the AFF
module.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class AlphaForgeSearchModule(BaseModule):
    """LLM-free formulaic alpha mining via GP / RL search."""

    name = "alphaforge_search"

    def setup(self, context: "Context") -> None:
        self.context = context

    # ---- shared output helper ----

    def _emit(
        self,
        exprs: list,
        scores: list,
        *,
        source: str,
        backtest: bool,
        save: bool,
        research_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from alphapilot.modules.alphaforge.pipeline import emit_factors

        return emit_factors(
            self.context,
            exprs,
            scores,
            source=source,
            backtest=backtest,
            save=save,
            research_metadata=research_metadata,
        )

    # ---- GP (light) ----

    def mine_gp(
        self,
        instruments: str = "csi300",
        train_end_year: int = 2020,
        train_start_date: str | None = None,
        train_end_date: str | None = None,
        freq: str = "day",
        seed: int = 0,
        population_size: int = 1000,
        generations: int = 40,
        target_horizon: int = 20,
        target_price: str = "vwap",
        vwap_mode: str = "amount_volume",
        device: str | None = None,
        qlib_dir: str | None = None,
        backtest: bool = False,
        save: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mine factors via genetic programming (gplearn).

        ``raw`` controls non-VWAP OHLCV adjustment; ``vwap_mode`` independently
        selects VWAP construction. Extra knobs such as ``tournament_size`` and
        ``top_n`` pass through to ``GPRunner``.
        """
        from alphapilot.modules.alphaforge_search.runners.gp_runner import GPRunner

        runner = GPRunner(
            context=self.context, instruments=instruments, train_end_year=train_end_year,
            train_start_date=train_start_date, train_end_date=train_end_date,
            freq=freq, seed=seed, population_size=population_size, generations=generations,
            target_horizon=target_horizon, target_price=target_price,
            vwap_mode=vwap_mode,
            device=device, qlib_dir=qlib_dir, **kwargs,
        )
        exprs, scores = runner.run()
        return self._emit(
            exprs, scores, source="alphaforge_gp", backtest=backtest, save=save
        )

    # ---- RL (medium) ----

    def mine_rl(
        self,
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
        campaign_id: str | None = None,
        research_hypothesis: str = "rl_symbolic_factor_search",
        device: str | None = None,
        qlib_dir: str | None = None,
        backtest: bool = False,
        save: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mine factors via PPO RL search (stable-baselines3 + sb3-contrib).

        ``raw`` controls non-VWAP OHLCV adjustment; ``vwap_mode`` independently
        selects VWAP construction. Other extra knobs pass through to ``RLRunner``.
        """
        from alphapilot.modules.alphaforge_search.runners.rl_runner import RLRunner

        runner = RLRunner(
            context=self.context, instruments=instruments, train_end_year=train_end_year,
            train_start_date=train_start_date, train_end_date=train_end_date,
            freq=freq, seed=seed, steps=steps, pool_capacity=pool_capacity,
            target_horizon=target_horizon, target_price=target_price,
            vwap_mode=vwap_mode,
            device=device, qlib_dir=qlib_dir, **kwargs,
        )
        exprs, scores = runner.run()
        if runner.training_data is None:
            raise RuntimeError("RL runner completed without a resolved training contract")
        training_data = runner.training_data
        provider_uri = str(
            Path(qlib_dir or self.context.config.data.qlib_data_dir)
            .expanduser()
            .resolve()
        )
        search_config = {
            "algorithm": "MaskablePPO",
            "steps": steps,
            "pool_capacity": pool_capacity,
            "target_horizon": training_data.target_spec.horizon,
            "target_price": training_data.target_spec.price,
            "vwap_mode": training_data.vwap_spec.mode,
            "instruments": instruments,
            "training_source": training_data.training_spec.source,
            "train_start_date": training_data.training_spec.requested_start_date,
            "train_end_date": training_data.training_spec.requested_end_date,
            "freq": freq,
            "seed": seed,
        }
        config_hash = hashlib.sha256(
            json.dumps(search_config, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        try:
            from alphapilot.systems.data.factor_h5 import FactorDataSpec

            data_fingerprint = FactorDataSpec(
                qlib_dir=Path(provider_uri), market=instruments, freq=freq
            ).fingerprint()
        except Exception as exc:
            if campaign_id and save:
                raise RuntimeError(
                    "campaign RL factors require a valid factor-data fingerprint"
                ) from exc
            data_fingerprint = ""
        metadata = {
            "campaign_id": campaign_id,
            "market": instruments,
            "provider_uri": provider_uri,
            "factor_data_fingerprint": data_fingerprint,
            "data_split": training_data.data_split_metadata(),
            "hypothesis": research_hypothesis,
            "mining_round": 1,
            "seed": seed,
            "target_expression": training_data.target_spec.qlib_expression,
            "vwap_mode": training_data.vwap_spec.mode,
            "search_config": search_config,
            "model_fingerprint": config_hash,
            "qlib_template_fingerprint": "",
        }
        return self._emit(
            exprs,
            scores,
            source="alphaforge_rl",
            backtest=backtest,
            save=save,
            research_metadata=metadata,
        )

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "mine_gp": self.mine_gp,
            "mine_rl": self.mine_rl,
        }
