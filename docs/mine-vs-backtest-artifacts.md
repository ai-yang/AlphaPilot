# Mine 与独立回测：文件/缓存冲突说明

本文说明 `alphapilot mine`、`alphapilot backtest`、`alphapilot strategy_backtest` 三条路径在磁盘上的交集、是否会互相覆盖，以及推荐用法。

## 1. 流程与入口（对照）

| 流程 | CLI | 主循环 | 回测执行 | 持久化「策略资产」 |
|------|-----|--------|----------|-------------------|
| 因子挖掘 | `mine` | `AlphaPilotLoop` | `QlibFactorRunner.develop` → `qrun` | `strategy_zoo/<策略名>/`（每轮 `_save_strategy_asset`） |
| 因子回测 | `backtest` | `BacktestLoop` | 同上 | 无（仅 workspace + 日志） |
| 策略复测 | `strategy_backtest` | 经 `run_factor_backtest` 走 `BacktestLoop` | 同上 | 仅 `strategy_zoo/.../retests/` |

三条路径**共用**同一套因子计算与 Qlib 回测实现，因此会写到同一批「全局目录」，但**绝大多数 workspace 按 UUID 隔离**。

## 2. 目录一览（当前机器量级参考）

| 路径 | 典型体积 | 写入方 | 冲突类型 |
|------|----------|--------|----------|
| `pickle_cache/` | ~数百 MB | 因子 `execute`、回测 `develop` | **缓存键碰撞**（逻辑错用旧结果） |
| `git_ignore_folder/RD-Agent_workspace/<uuid>/` | ~1GB+ 累积 | 每次实验新建 UUID 目录 | 一般不互相覆盖；占磁盘 |
| `git_ignore_folder/factor_implementation_source_data/` | 共享只读 | 因子执行 symlink | 并发更新 `daily_pv.h5` 时可能读到半成品 |
| `important_data/factor_qlib_templates/` | 用户可改 | 模板 **拷贝** 进 workspace | 运行中改模板不影响已拷贝目录 |
| `important_data/strategy_zoo/` | 小 | mine 写资产；`strategy_backtest` 写 `retests/` | 仅当**同时**写同一策略目录时需注意 |
| `log/<时间戳>/` | 中等 | mine 快照 + 打分模型；独立回测也可能写入 | **可能覆盖** `rounds/round_01/.../scoring_model` |
| `~/.qlib/qlib_data/` | 大 | Qlib 行情 | 只读为主，多进程读一般无妨 |

内置 Qlib 模板（只读）：`alphapilot/modules/alpha_mining/qlib/experiment/factor_template/`。

## 3. 冲突矩阵

### 3.1 无文件覆盖（安全）

- **RD-Agent workspace**：每个 `FBWorkspace` 使用 `RD-Agent_workspace/<uuid>/`，mine / backtest / strategy_backtest **不会共用一个 uuid 目录**（除非缓存同步复制产物，见下）。
- **strategy_zoo 策略本体**：mine 写 `factors.json`、`artifacts/fitted_model.pkl`；复测写 `retests/<时间>_<mode>/`，文件名空间不同。
- **Qlib 模板**：`inject_code_from_folder` 只把 `.py/.yaml/.md` **复制**进 workspace，不改模板源目录。

### 3.2 逻辑冲突（高风险，已通过代码缓解）

| 问题 | 原因 | 表现 | 缓解 |
|------|------|------|------|
| 回测缓存命中但 workspace 空 | `QlibFactorRunner.develop` 的 pickle 键原先只含 `get_task_information()`（**不含** `factor_expression`） | IC 正常但 `ret.pkl` 缺失，策略复测无法导出日频仓位 | 缓存键加入表达式、qlib 配置、模板路径；命中时从旧 workspace **同步** `ret.pkl` 等 |
| 因子 CSV 与 mine 公式同名 | 任务名相同、描述为空时，回测缓存可能误判为同一实验 | 指标与仓位对不上 | 同上：表达式纳入缓存键 |
| 独立回测写 mine 日志 | `BacktestLoop` 设 `mining_round=1` 会触发 `persist_scoring_model_to_log`，**删除并覆盖** `log/.../rounds/round_01/04_backtest/scoring_model/` | 正在跑的 mine 日志里 round_01 模型被冲掉 | 仅当 `experiment.persist_scoring_model_log=True` 时写入（由 `AlphaPilotLoop` 设置） |

### 3.3 资源竞争（中低风险）

| 问题 | 说明 |
|------|------|
| `pickle_cache` 文件锁 | `use_file_lock=True` 时，相同 hash 的并发调用会串行，不会写坏 pkl，但可能排队 |
| `factor_implementation_source_data` | 各因子 workspace 用 symlink 指向同一 `daily_pv.h5`；若 `prepare_data` 正在重写该文件，极端情况下因子读失败 |
| 环境变量 `ALPHAPILOT_QLIB_DATA_DIR` | `strategy_backtest` 临时修改进程环境；**不要**与 mine 并行跑且依赖不同数据目录 |

### 3.4 仅磁盘增长（非逻辑错误）

- `RD-Agent_workspace` 下大量 uuid 目录（含 `mlruns/`）不会自动清理。
- `pickle_cache` 因子/回测条目会随公式与代码增长。

## 4. 推荐操作习惯

1. **改公式 / 改 qlib yaml / 改模板后**：清理相关缓存再跑  
   `rm -rf pickle_cache/alphapilot.systems.backtest.runners.factor_runner.develop/*`  
   以及（若因子代码变了）`pickle_cache/alphapilot.components.coder.factor_coder.factor.execute/*`

2. **mine 与 strategy_backtest 不要共用同一次 `log/<session>` 的 round_01**（现已避免自动覆盖 scoring_model，但仍建议复测用新终端会话或显式新 log）。

3. **策略复测以 `strategy_zoo/.../retests/<时间>_<mode>/` 为准** 存日频仓位；不要依赖 `RD-Agent_workspace/<uuid>`（会被后续实验替换且可能只含模板）。

4. **并行**：可同时跑 mine + 复测，但共享 `pickle_cache` 时相同因子集可能命中同一条缓存（加速但需确认公式一致）。

## 5. 清理命令速查

```bash
# 仅清回测 develop 缓存（策略复测/ backtest 常用）
rm -rf pickle_cache/alphapilot.systems.backtest.runners.factor_runner.develop/*

# 清因子执行缓存（改过 factor.py 或 Python 解释器）
rm -rf pickle_cache/alphapilot.components.coder.factor_coder.factor.execute/*

# 清历史 workspace（释放磁盘，不影响 strategy_zoo）
rm -rf git_ignore_folder/RD-Agent_workspace/*
```

## 6. 相关代码位置

- Workspace UUID：`alphapilot/core/experiment.py` → `FBWorkspace.__init__`
- 因子执行缓存：`alphapilot/components/coder/factor_coder/factor.py` → `hash_func` / `execute`
- 回测 develop 缓存：`alphapilot/systems/backtest/runners/factor_runner.py`
- 策略复测导出：`alphapilot/systems/strategy/service.py` → `_export_retest_portfolio_artifacts`
- 打分模型落盘：`alphapilot/systems/backtest/scoring_model_export.py` → `persist_scoring_model_to_log`
