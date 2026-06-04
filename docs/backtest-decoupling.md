# Backtest ↔ Alpha Mining Decoupling

## Boundary

| Layer | Owns |
|-------|------|
| `systems/backtest/pipelines/` | CSV / factor list → calculate → qlib (`FactorEvaluationPipeline`) |
| `systems/backtest/` | Prepared experiment → `QlibFactorRunner` / workspace `qrun` |
| `modules/alpha_mining/` | LLM mine loop + thin CLI delegates to backtest |

**Rule:** `alphapilot/systems/backtest/**` must not import `alphapilot.modules.alpha_mining`.

## Entry points

- CLI `alphapilot backtest` → `AlphaMiningModule.run_backtest` → `context.backtest().run_factor_evaluation`
- Mining loop `factor_backtest` step → `context.backtest().run_factor_experiment(...)`
- Strategy retrain / reuse_model → `context.module("alpha_mining").run_strategy_asset_backtest` → backtest pipelines

## Public backtest API (user factors)

```python
ctx.backtest().run_factor_evaluation(FactorBacktestRequest(factor_path="f.csv"))
ctx.backtest().run_saved_model_evaluation(SavedModelBacktestRequest(...))
ctx.backtest().run_factor_experiment(FactorExperimentBacktestRequest(...))  # pre-built experiment
ctx.backtest().execute_workspace(WorkspaceBacktestRequest(...))
```

## Phases (complete)

1. Orchestration moved out of backtest service into pipelines.
2. Protocols + Loop single-channel to `context.backtest()`.
3. Qlib templates under `systems/backtest/qlib/templates/`.
4. `QlibFactorExperiment` in backtest system.
5. Runner shims removed; factor conf presets omit `runner`.
6. Strategy backtest delegates to backtest pipelines.
7. **`BacktestLoop` removed**; replaced by `FactorEvaluationPipeline` in backtest.

## Smoke test

```bash
/fm2/wangrui/miniconda3/envs/alphabot/bin/python scripts/smoke_backtest_decoupling.py
```
