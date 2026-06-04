# 自定义 Qlib 回测模板目录

本目录从内置 `alphapilot/modules/alpha_mining/qlib/experiment/factor_template/` 复制而来，便于在**不修改仓库内置文件**的前提下调整回测 YAML 与辅助脚本。

## 目录内文件

| 文件 | 作用 |
|------|------|
| `conf.yaml` | 单因子 / 基线回测配置 |
| `conf_cn_combined_kdd_ver.yaml` | 多因子合并回测（mine 常用，读取 `combined_factors_df.pkl`） |
| `read_exp_res.py` | `qrun` 结束后从 Qlib Recorder 导出 `qlib_res.csv`、`ret.pkl` |

每次因子回测会将该目录下所有 `.py` / `.yaml` / `.md` 拷贝进当次 `git_ignore_folder/RD-Agent_workspace/<uuid>/` 再执行 `qrun`。

## 启用方式

在项目根 `.env` 中（路径相对**运行 `alphapilot` 时的当前工作目录**，一般为项目根）：

```bash
QLIB_FACTOR_QLIB_TEMPLATE_DIR=important_data/factor_qlib_templates
QLIB_FACTOR_QLIB_CONFIG_NAME=conf_cn_combined_kdd_ver.yaml
```

或通过 CLI 覆盖（优先级高于 `.env`）：

```bash
alphapilot mine --qlib_template_dir=important_data/factor_qlib_templates
alphapilot strategy_backtest --strategy_name='...' --qlib_config_name=conf_cn_combined_kdd_ver.yaml
```

未配置时，`mine` / `backtest` 默认仍使用内置 `factor_template/`。

更完整说明见项目根目录 [README.md](../../../README.md)。
