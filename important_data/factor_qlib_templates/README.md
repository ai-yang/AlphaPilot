# 自定义 Qlib 回测模板目录

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

**`provider_uri`**：yaml 中须与当前 Qlib 二进制目录一致。迁移到分数据源目录后，baostock 推荐：

```yaml
provider_uri: "~/.qlib/qlib_data/cn_data/baostock/qlib"
```

（Tushare 用 `.../tushare/qlib`。可与 `.env` 的 `ALPHAPILOT_QLIB_DATA_DIR` 保持一致。）

## 用 `qlib_yaml_generate` 生成配置

可用 CLI 从结构化参数 + 可选 LLM 自然语言描述生成新的 qrun YAML（不会直接让 LLM 写整份带锚点的 YAML，而是渲染内置 Jinja2 模板）：

```bash
# 基线模板，改 topk 与输出路径
alphapilot qlib_yaml_generate \
  --output=important_data/factor_qlib_templates/my_conf.yaml \
  --template=baseline \
  --topk=20

# 结构化 JSON + LLM 补充
alphapilot qlib_yaml_generate \
  --output=important_data/factor_qlib_templates/my_conf.yaml \
  --template=combined \
  --params_file=my_params.json \
  --prompt="回测区间改到2025年底，topk改为20" \
  --copy_helpers

# 仅校验已有 yaml（静态 + Qlib handler 冒烟，不跑完整 qrun）
alphapilot qlib_yaml_validate \
  --config=important_data/factor_qlib_templates/conf.yaml \
  --skip_smoke
```

常用参数：

| 参数 | 说明 |
|------|------|
| `--template` | `baseline`（单 QlibDataLoader）或 `combined`（NestedDataLoader + pkl） |
| `--params_file` | JSON 补丁，字段见 `QlibYamlParams`（market、segments、topk、feature_expressions 等） |
| `--prompt` | 自然语言描述，由 LLM 生成 JSON 补丁 |
| `--skip_smoke` | 只做静态校验，跳过 Qlib 数据加载冒烟 |
| `--workspace` | combined 模板时检查 `combined_factors_df.pkl` 是否存在 |

更完整说明见项目根目录 [README.md](../../../README.md)。
