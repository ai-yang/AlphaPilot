# important_data

项目根目录下存放**需要长期保留、与仓库代码分离**的数据，已加入 `.gitignore`。

| 子目录 | 说明 | 默认配置 |
|--------|------|----------|
| `strategy_zoo/` | `mine` 保存的策略资产、`strategy_backtest` 的 `retests/` | `ALPHAPILOT_STRATEGY_PARAM_DIR`（默认本目录） |
| `factor_qlib_templates/` | 自定义 Qlib 回测模板（yaml、`read_exp_res.py`） | `QLIB_FACTOR_QLIB_TEMPLATE_DIR` |

可选环境变量：

```bash
# 若整个 important_data 想放到其他盘
ALPHAPILOT_IMPORTANT_DATA_DIR=/path/to/important_data
```

旧路径 `git_ignore_folder/strategy_zoo` 与 `git_ignore_folder/factor_qlib_templates` 会在运行时自动映射到本目录。
