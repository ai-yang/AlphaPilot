# AlphaForge mining modules

LLM-free, programmatic alpha-factor mining ported from
[AlphaForge](https://github.com/DulyHao/AlphaForge) / AlphaGen, exposed as two
pluggable alphapilot modules:

| Module | Command(s) | Method | Deps |
|---|---|---|---|
| `alphaforge_aff` | `mine_aff` | **AFF** — GAN-style generator+predictor search (the AlphaForge paper's stage-1) | torch |
| `alphaforge_search` | `mine_gp` / `mine_rl` | **GP** (gplearn), **RL** (PPO/sb3) | torch; sb3+sb3-contrib (RL) |

Both mine internally on the **vendored alphagen torch engine** (fast batch
evaluation), then translate each surviving `Expression` into alphapilot's
native factor DSL and push it through the factor + backtest systems. No
alphagen objects leak past the output boundary.

## Architecture

```
alphaforge/                 shared base (NOT a registered module)
  vendor/                   verbatim AlphaForge subset (alphagen, gan, gplearn, ...)
  __init__.py               puts vendor/ on sys.path so `import alphagen` resolves
  device.py                 resolve_device (cuda/mps/cpu) + use_fork_start_method()
  data_adapter.py           build StockData from context.config.data.qlib_data_dir
  translate.py              Expression AST  ->  alphapilot DSL string  (the boundary)
  pipeline.py               emit_factors(): translate -> validate/add -> optional backtest
alphaforge_aff/             AFFMiner (refactor of train_AFF) + module
alphaforge_search/          GP/RL runners (refactor of train_{GP,RL}) + module
```

## Usage

```bash
# AFF (GAN). max_len must be 20 (the DCGAN generator is fixed to length-20).
alphapilot mine_aff --instruments=test_stock_pool_80 --zoo_size=20 --device=cpu --backtest=True

# GP / RL
alphapilot mine_gp --instruments=test_stock_pool_80 --population_size=200 --generations=10
alphapilot mine_rl --instruments=test_stock_pool_80 --steps=50000 --pool_capacity=10
```

`--save=True` (default) adds accepted factors to the factor zoo; `--backtest=True`
runs them through the qlib backtest system. Extra training knobs pass through
via `**kwargs` (e.g. `--num_epochs_g=50`, `--max_loops=10`, `--top_n=50`, `--raw=True`).

Install extras: `pip install -e ".[alphaforge]"` (AFF+GP+RL).

## Environment notes (this repo / macOS)

These were needed to run on the current env (numpy 2.x, torch 2.x, py3.11, macOS):

- **Device**: code is device-configurable (`--device cpu|mps|cuda`, auto-detected
  when omitted); the vendored hardcoded `cuda:0` is centralised in `device.py`.
- **Multiprocessing**: `use_fork_start_method()` forces the `fork` start method
  (AlphaForge assumes Linux). macOS defaults to `spawn`, under which qlib/joblib
  worker pools re-import `__main__` and fork-bomb. Called at the start of every
  miner/runner.
- **RL**: the vendored `alphagen/rl/{env,policy}` were migrated `gym` →
  `gymnasium` for stable-baselines3 ≥ 2 (reset returns `(obs, info)`, step
  returns a 5-tuple). `tensorboard_log` is disabled (tensorboard not required).

## Data caveats

The miners default to `instruments="csi300"`, but this repo's baostock qlib dump
has **no `csi300`/`csi500` instrument set** — use `test_stock_pool_80` (80 stocks)
or `all`. The dump also has **no native `vwap` and no `$factor`**, so:

- `vwap` is mapped to `$amount/$volume` (patched in `vendor/alphagen_qlib/stock_data.py`).
- `raw` defaults to `False` (no adjustment-factor rewrite). Set `--raw=True` only
  if your qlib data carries `$factor`.

## Verified

- `tests/test_alphaforge_translate.py` — 44 translator round-trip tests (every
  active operator → parseable alphapilot DSL).
- Smoke (real baostock data, CPU): AFF mined 208 factors; GP and RL produced and
  translated factors; end-to-end `mine → translate → factor zoo` confirmed.
