"""AlphaForgeSearchModule: GP / DSO / RL formulaic alpha mining.

These are the three non-GAN baselines bundled with AlphaForge, merged into a
single module:

* ``mine_gp``  -- genetic programming (vendored ``gplearn``); lightest deps.
* ``mine_rl``  -- PPO over expression tokens (``stable-baselines3`` +
  ``sb3-contrib``); medium deps.
* ``mine_dso`` -- deep symbolic optimization (vendored ``dso``); requires
  TensorFlow + a compiled Cython ``cyfunc`` extension, so it is an OPTIONAL
  lazy dependency -- ``mine_gp`` / ``mine_rl`` work without it.

All three share the vendored alphagen expression engine for evaluation and,
on output, the same translate -> validate -> backtest pipeline as the AFF
module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from alphapilot.kernel.base import BaseModule

if TYPE_CHECKING:
    from alphapilot.kernel.context import Context


class AlphaForgeSearchModule(BaseModule):
    """LLM-free formulaic alpha mining via GP / DSO / RL search."""

    name = "alphaforge_search"

    def setup(self, context: "Context") -> None:
        self.context = context

    # ---- shared output helper ----

    def _emit(self, exprs: list, scores: list, *, source: str, backtest: bool, save: bool) -> dict[str, Any]:
        from alphapilot.modules.alphaforge.pipeline import emit_factors

        return emit_factors(
            self.context, exprs, scores, source=source, backtest=backtest, save=save
        )

    # ---- GP (light) ----

    def mine_gp(
        self,
        instruments: str = "csi300",
        train_end_year: int = 2020,
        freq: str = "day",
        seed: int = 0,
        population_size: int = 1000,
        generations: int = 40,
        device: str | None = None,
        qlib_dir: str | None = None,
        backtest: bool = False,
        save: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mine factors via genetic programming (gplearn). Extra knobs
        (``tournament_size``, ``top_n``, ``raw``) pass through to ``GPRunner``."""
        from alphapilot.modules.alphaforge_search.runners.gp_runner import GPRunner

        runner = GPRunner(
            context=self.context, instruments=instruments, train_end_year=train_end_year,
            freq=freq, seed=seed, population_size=population_size, generations=generations,
            device=device, qlib_dir=qlib_dir, **kwargs,
        )
        exprs, scores = runner.run()
        return self._emit(exprs, scores, source="alphaforge_gp", backtest=backtest, save=save)

    # ---- RL (medium) ----

    def mine_rl(
        self,
        instruments: str = "csi300",
        train_end_year: int = 2020,
        freq: str = "day",
        seed: int = 0,
        steps: int = 200_000,
        pool_capacity: int = 10,
        device: str | None = None,
        qlib_dir: str | None = None,
        backtest: bool = False,
        save: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mine factors via PPO RL search (stable-baselines3 + sb3-contrib).
        Extra knobs (``raw`` ...) pass through to ``RLRunner``."""
        from alphapilot.modules.alphaforge_search.runners.rl_runner import RLRunner

        runner = RLRunner(
            context=self.context, instruments=instruments, train_end_year=train_end_year,
            freq=freq, seed=seed, steps=steps, pool_capacity=pool_capacity,
            device=device, qlib_dir=qlib_dir, **kwargs,
        )
        exprs, scores = runner.run()
        return self._emit(exprs, scores, source="alphaforge_rl", backtest=backtest, save=save)

    # ---- DSO (optional / heavy) ----

    def mine_dso(
        self,
        instruments: str = "csi300",
        train_end_year: int = 2020,
        freq: str = "day",
        seed: int = 0,
        n_samples: int = 5000,
        pool_capacity: int = 10,
        device: str | None = None,
        qlib_dir: str | None = None,
        backtest: bool = False,
        save: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Mine factors via deep symbolic optimization (requires TensorFlow + Cython).

        DSO is an optional dependency. If TensorFlow / the compiled ``cyfunc``
        extension are missing, the runner raises a clear install hint. Extra
        knobs (``raw`` ...) pass through to ``DSORunner``.
        """
        from alphapilot.modules.alphaforge_search.runners.dso_runner import DSORunner

        runner = DSORunner(
            context=self.context, instruments=instruments, train_end_year=train_end_year,
            freq=freq, seed=seed, n_samples=n_samples, pool_capacity=pool_capacity,
            device=device, qlib_dir=qlib_dir, **kwargs,
        )
        exprs, scores = runner.run()
        return self._emit(exprs, scores, source="alphaforge_dso", backtest=backtest, save=save)

    def commands(self) -> dict[str, Callable[..., Any]]:
        return {
            "mine_gp": self.mine_gp,
            "mine_rl": self.mine_rl,
            "mine_dso": self.mine_dso,
        }
