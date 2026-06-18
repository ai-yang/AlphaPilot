"""AlphaForgeAFFModule: AFF (GAN-style) alpha factor mining.

The novelty of AlphaForge stage-1: a generator network proposes formulaic
alphas (as token sequences), a predictor network acts as a cheap surrogate
for the factor's IC, and the generator is trained to produce high-IC,
low-correlation factors. We run that miner internally on the vendored
alphagen torch engine, then translate the surviving ``Expression`` objects
into alphapilot's native DSL and push them through the factor + backtest
systems.

Heavy imports (torch + the vendored networks) are deferred into the command
body so that merely loading this module (e.g. for ``--help`` / command
discovery) stays cheap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class AlphaForgeAFFModule(BaseModule):
    """LLM-free, GAN-style formulaic alpha mining (AlphaForge AFF)."""

    name = "alphaforge_aff"

    def setup(self, context: "Context") -> None:
        self.context = context

    def mine_aff(
        self,
        instruments: str = "csi300",
        train_end_year: int = 2020,
        freq: str = "day",
        seed: int = 0,
        zoo_size: int = 100,
        corr_thresh: float = 0.7,
        ic_thresh: float = 0.03,
        icir_thresh: float = 0.1,
        max_len: int = 20,
        device: str | None = None,
        qlib_dir: str | None = None,
        backtest: bool = False,
        save: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mine a zoo of alpha factors with the AFF generator-predictor loop.

        Mined factors are translated to alphapilot DSL, validated against the
        factor zoo, optionally backtested, and (when *save*) added to the zoo.
        Extra training knobs (``batch_size``, ``num_epochs_g``, ``num_epochs_p``,
        ``init_collect``, ``iter_collect``, ``max_loops``, ``raw`` ...) pass
        through ``**kwargs`` to :class:`AFFMiner`.
        """
        from alphapilot.modules.alphaforge_aff.miner import AFFMiner

        miner = AFFMiner(
            context=self.context,
            instruments=instruments,
            train_end_year=train_end_year,
            freq=freq,
            seed=seed,
            zoo_size=zoo_size,
            corr_thresh=corr_thresh,
            ic_thresh=ic_thresh,
            icir_thresh=icir_thresh,
            max_len=max_len,
            device=device,
            qlib_dir=qlib_dir,
            **kwargs,
        )
        exprs, scores = miner.run()

        from alphapilot.modules.alphaforge.pipeline import emit_factors

        return emit_factors(
            self.context,
            exprs,
            scores,
            source="alphaforge_aff",
            backtest=backtest,
            save=save,
        )

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {"mine_aff": self.mine_aff}
