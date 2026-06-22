"""Streamlit unified web portal for systems + pluggable modules."""

from __future__ import annotations

import inspect
import json
import logging
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from alphapilot.modules.portal.i18n import (
    format_factor_rejection,
    get_lang,
    init_lang,
    language_selector,
    t,
)


# Heavy data ops (convert / build_h5) spawn worker processes & threads (dump_bin's
# ProcessPoolExecutor, qlib's parallel loading) that run outside Streamlit's
# ScriptRunContext. Their "missing ScriptRunContext" / "session_state does not
# function" warnings are benign but flood the console — silence just those loggers.
for _noisy_logger in (
    "streamlit.runtime.scriptrunner_utils.script_run_context",
    "streamlit.runtime.state.session_state_proxy",
):
    logging.getLogger(_noisy_logger).setLevel(logging.ERROR)


init_lang()

st.set_page_config(
    page_title=t("page_title"),
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource(show_spinner=False)
def _load_engine():
    from alphapilot.kernel import build_engine

    return build_engine(discover=True)


def _safe_json_load(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(t("json_kwargs_error"))
    return value


def _safe_metric(fn: Callable[[], Any], default: Any = "—") -> Any:
    """Compute a dashboard metric, degrading to *default* on any error."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def _nonempty_kwargs(raw: dict[str, Any]) -> dict[str, Any]:
    """Drop blank optional form fields while preserving falsey booleans/zeroes."""
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            if value.strip():
                out[key] = value.strip()
        elif value is not None:
            out[key] = value
    return out


def _recent_mining_sessions(log_dir: Path | str, limit: int = 5) -> list[str]:
    """Most-recent mining session folder names under *log_dir* (by mtime)."""
    root = Path(log_dir)
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.name for p in dirs[:limit]]


def _available_instrument_sets(engine: Any) -> list[str]:
    """Instrument-set names in the qlib dump (avoids the absent-csi300 pitfall)."""
    try:
        inst_dir = Path(engine.config.data.qlib_data_dir) / "instruments"
        return sorted(p.stem for p in inst_dir.glob("*.txt"))
    except Exception:  # noqa: BLE001
        return []


_COMMAND_KWARGS_EXAMPLES: dict[tuple[str, str], dict[str, Any]] = {
    ("alpha_mining", "mine"): {
        "step_n": 5,
        "scenario": "alpha_factor_mining",
        "direction": "验证低波动反转因子",
    },
    ("alpha_mining", "backtest"): {
        "factor_path": "important_data/factors.csv",
        "scenario": "factor_backtest",
    },
    ("alphaforge_aff", "mine_aff"): {
        "instruments": "test_stock_pool_80",
        "zoo_size": 100,
        "ic_thresh": 0.03,
        "top_n": 50,
        "raw": True,
    },
    ("alphaforge_search", "mine_gp"): {
        "instruments": "test_stock_pool_80",
        "population_size": 200,
        "generations": 10,
        "top_n": 50,
        "raw": True,
    },
    ("alphaforge_search", "mine_rl"): {
        "instruments": "test_stock_pool_80",
        "steps": 50_000,
        "pool_capacity": 10,
        "raw": True,
    },
    ("platform", "prepare_data"): {
        "action": "pipeline",
        "source": "tushare_cn",
        "start_date": "2005-01-01",
        "stock_csv": "important_data/stock_lists/main_stock_2026_4_27.csv",
        "all_market": False,
    },
    ("platform", "delete_stock"): {
        "symbol": "sh.600000",
        "adjust_mode": "all",
        "dry_run": True,
    },
    ("platform", "trim_stock"): {
        "symbol": "sh.600000",
        "start_date": "2020-01-01",
        "end_date": "2024-12-31",
        "drop_dates": "2023-01-03,2023-01-04",
        "dry_run": True,
    },
    ("platform", "refresh_stock"): {
        "symbol": "sh.600000",
        "adjust_mode": "backward",
        "start_date": "2016-12-31",
        "rebuild_h5": False,
    },
    ("qlib_yaml", "qlib_yaml_generate"): {
        "output": "important_data/factor_qlib_templates/custom.yaml",
        "template": "baseline",
        "market": "all",
        "topk": 50,
        "skip_smoke": True,
    },
    ("qlib_yaml", "qlib_yaml_validate"): {
        "config": "important_data/factor_qlib_templates/conf.yaml",
        "skip_smoke": True,
    },
    ("strategy_backtest", "strategy_backtest"): {
        "strategy_name": "my_strategy",
        "mode": "retrain",
        "scenario": "factor_backtest",
        "run_tag": "portal_test",
    },
    ("portal", "portal"): {"port": 19901, "host": "0.0.0.0"},
    ("portal", "scheduler"): {"interval": 30},
    ("data_viz", "data_viz"): {"port": 19902, "host": "0.0.0.0"},
    ("backtest_viz", "backtest_viz"): {"port": 19903, "host": "0.0.0.0"},
}

_COMMAND_EXTRA_NOTES: dict[tuple[str, str], dict[str, str]] = {
    ("alphaforge_aff", "mine_aff"): {
        "en": (
            "`**kwargs` is passed to AFFMiner. Common fields: `batch_size`, `num_epochs_g`, "
            "`num_epochs_p`, `init_collect`, `iter_collect`, `max_loops`, `raw`, `top_n`."
        ),
        "zh": (
            "`**kwargs` 会继续传给 AFFMiner，常用：`batch_size`, `num_epochs_g`, "
            "`num_epochs_p`, `init_collect`, `iter_collect`, `max_loops`, `raw`, `top_n`。"
        ),
    },
    ("alphaforge_search", "mine_gp"): {
        "en": "`**kwargs` is passed to GPRunner. Common fields: `tournament_size`, `top_n`, `raw`.",
        "zh": "`**kwargs` 会继续传给 GPRunner，常用：`tournament_size`, `top_n`, `raw`。",
    },
    ("alphaforge_search", "mine_rl"): {
        "en": "`**kwargs` is passed to RLRunner. Common field: `raw`.",
        "zh": "`**kwargs` 会继续传给 RLRunner，常用：`raw`。",
    },
    ("platform", "prepare_data"): {
        "en": (
            "`**options` is passed to the selected data action. Common fields: `source`, `token`, "
            "`all_market`, `code_column`, `factor_dir`, `include_daily_basic`, `target_mode`."
        ),
        "zh": (
            "`**options` 会继续传给具体数据动作，常用：`source`, `token`, `all_market`, "
            "`code_column`, `factor_dir`, `include_daily_basic`, `target_mode`。"
        ),
    },
    ("strategy_backtest", "strategy_backtest"): {
        "en": "`**options` is passed into the strategy backtest request for model/template extensions.",
        "zh": "`**options` 会作为策略回测的附加 options 传入，适合放模型或模板支持的扩展项。",
    },
}

_ALPHAFORGE_EXTRA_KWARGS_EXAMPLES: dict[str, dict[str, Any]] = {
    "mine_aff": {"top_n": 50, "raw": True, "num_epochs_g": 50, "max_loops": 10},
    "mine_gp": {"top_n": 50, "raw": True, "tournament_size": 20},
    "mine_rl": {"raw": True},
}

_COMMAND_EXTRA_PARAM_NAMES: dict[tuple[str, str], list[str]] = {
    ("alphaforge_aff", "mine_aff"): [
        "batch_size",
        "num_epochs_g",
        "num_epochs_p",
        "init_collect",
        "iter_collect",
        "max_loops",
        "top_n",
        "raw",
    ],
    ("alphaforge_search", "mine_gp"): ["tournament_size", "top_n", "raw"],
    ("alphaforge_search", "mine_rl"): ["raw"],
    ("platform", "prepare_data"): [
        "source",
        "token",
        "all_market",
        "code_column",
        "factor_dir",
        "include_daily_basic",
        "target_mode",
    ],
}

_PARAMETER_DETAILS: dict[str, dict[str, dict[str, str]]] = {
    "action": {
        "en": {
            "desc": "Data operation to run.",
            "range": "`pipeline`, `download`, `apply_adjust`, `convert`, `build_h5`.",
        },
        "zh": {
            "desc": "要执行的数据操作。",
            "range": "`pipeline`、`download`、`apply_adjust`、`convert`、`build_h5`。",
        },
    },
    "adjust_mode": {
        "en": {
            "desc": "Price-adjustment mode for downloaded/converted bars.",
            "range": "`backward` is the usual backtest default; use `forward` for forward-adjusted charts, `none` for raw bars.",
        },
        "zh": {
            "desc": "下载/转换行情的复权方式。",
            "range": "回测通常用 `backward`；看前复权走势用 `forward`；需要未复权行情和复权因子时用 `none`。",
        },
    },
    "all_market": {
        "en": {
            "desc": "Ignore stock CSV and download the whole market.",
            "range": "Usually `false`; set `true` only for large full-market refreshes.",
        },
        "zh": {
            "desc": "忽略股票 CSV，改为下载全市场。",
            "range": "一般填 `false`；只有需要大规模全市场刷新时填 `true`。",
        },
    },
    "backtest": {
        "en": {
            "desc": "Run a backtest after accepted factors are mined.",
            "range": "Use `false` for quick mining; `true` when you want immediate validation.",
        },
        "zh": {"desc": "因子通过后是否立即回测。", "range": "快速挖掘填 `false`；需要立刻验证收益表现时填 `true`。"},
    },
    "batch_size": {
        "en": {
            "desc": "AFF training batch size.",
            "range": "Try `32`-`256`; reduce it if memory is tight.",
        },
        "zh": {"desc": "AFF 训练 batch size。", "range": "建议 `32`-`256`；显存/内存紧张时调小。"},
    },
    "code_column": {
        "en": {
            "desc": "Column name for stock codes in the CSV.",
            "range": "Common values: `code`, `symbol`, `ts_code`; Tushare CSV often uses `ts_code`.",
        },
        "zh": {
            "desc": "股票列表 CSV 里的代码列名。",
            "range": "常见为 `code`、`symbol`、`ts_code`；Tushare 常用 `ts_code`。",
        },
    },
    "corr_thresh": {
        "en": {
            "desc": "Maximum correlation allowed between newly accepted factors and the pool.",
            "range": "`0.5`-`0.8`; stricter pools use `0.5`-`0.7`.",
        },
        "zh": {
            "desc": "新因子与池内因子的最高相关性阈值。",
            "range": "建议 `0.5`-`0.8`；想更去重可用 `0.5`-`0.7`。",
        },
    },
    "device": {
        "en": {
            "desc": "Compute device.",
            "range": "`auto`/unset is safest; use `cpu`, `mps`, or `cuda` when you know the environment.",
        },
        "zh": {"desc": "计算设备。", "range": "最稳妥是 `auto`/不填；明确环境时可填 `cpu`、`mps`、`cuda`。"},
    },
    "direction": {
        "en": {
            "desc": "Natural-language research direction for LLM mining.",
            "range": "Keep it specific: one hypothesis or factor family in 1-3 sentences.",
        },
        "zh": {"desc": "LLM 挖掘的自然语言研究方向。", "range": "建议具体一些：用 1-3 句话描述一个假说或一个因子族。"},
    },
    "dry_run": {
        "en": {
            "desc": "Preview a destructive data-management operation.",
            "range": "Use `true` before delete/trim; switch to `false` only after checking the report.",
        },
        "zh": {
            "desc": "预演删除/裁剪等数据管理操作。",
            "range": "删除/裁剪前建议先填 `true`；确认报告后再改 `false`。",
        },
    },
    "end_date": {
        "en": {
            "desc": "End date, inclusive.",
            "range": "`YYYY-MM-DD`; leave empty/omit to use the latest available date.",
        },
        "zh": {"desc": "结束日期，通常包含当天。", "range": "`YYYY-MM-DD`；不填通常表示拉到最新可用日期。"},
    },
    "factor_dir": {
        "en": {
            "desc": "Directory for adjustment-factor CSV files.",
            "range": "Leave unset unless you maintain a custom data layout.",
        },
        "zh": {"desc": "复权因子 CSV 目录。", "range": "一般不填，除非你维护了自定义数据目录。"},
    },
    "factor_path": {
        "en": {
            "desc": "CSV file containing factors to backtest.",
            "range": "Use an existing factor CSV; relative paths are resolved from the project root.",
        },
        "zh": {"desc": "要回测的因子 CSV 文件。", "range": "填写已存在的因子 CSV；相对路径按项目根目录理解。"},
    },
    "freq": {
        "en": {
            "desc": "Data frequency.",
            "range": "Use `day` for the current daily-bar workflow.",
        },
        "zh": {"desc": "数据频率。", "range": "当前日频流程建议填 `day`。"},
    },
    "generations": {
        "en": {
            "desc": "GP evolution generations.",
            "range": "Fast smoke test: `3`-`10`; normal run: `10`-`50`; larger values take longer.",
        },
        "zh": {"desc": "GP 遗传迭代代数。", "range": "快速试跑 `3`-`10`；常规 `10`-`50`；越大耗时越长。"},
    },
    "host": {
        "en": {
            "desc": "Host address for Streamlit apps.",
            "range": "`127.0.0.1` for local-only; `0.0.0.0` for LAN/container access.",
        },
        "zh": {
            "desc": "Streamlit 应用监听地址。",
            "range": "只本机访问用 `127.0.0.1`；局域网/容器访问用 `0.0.0.0`。",
        },
    },
    "ic_thresh": {
        "en": {
            "desc": "Minimum IC threshold for accepting mined factors.",
            "range": "`0.01`-`0.05`; `0.03` is a common starting point.",
        },
        "zh": {"desc": "挖掘因子通过筛选的最低 IC 阈值。", "range": "建议 `0.01`-`0.05`；常用起点是 `0.03`。"},
    },
    "icir_thresh": {
        "en": {
            "desc": "Minimum ICIR threshold for accepting mined factors.",
            "range": "`0.05`-`0.5`; start around `0.1`.",
        },
        "zh": {"desc": "挖掘因子通过筛选的最低 ICIR 阈值。", "range": "建议 `0.05`-`0.5`；可从 `0.1` 开始。"},
    },
    "include_daily_basic": {
        "en": {
            "desc": "Download Tushare daily_basic fields.",
            "range": "Usually `false`; set `true` only when you need turnover/PE/PB/PS and have enough Tushare quota.",
        },
        "zh": {
            "desc": "是否下载 Tushare daily_basic 每日指标。",
            "range": "一般填 `false`；需要换手率/PE/PB/PS 且 Tushare 积分足够时填 `true`。",
        },
    },
    "init_collect": {
        "en": {
            "desc": "Initial samples collected before AFF training loops.",
            "range": "`500`-`5000`; larger values improve diversity but slow startup.",
        },
        "zh": {"desc": "AFF 训练循环前的初始采样数量。", "range": "建议 `500`-`5000`；越大多样性更好但启动更慢。"},
    },
    "instruments": {
        "en": {
            "desc": "Qlib instrument set name.",
            "range": "Use a file under `<qlib_data_dir>/instruments`; for tests use `test_stock_pool_80`, for full runs use `all` if present.",
        },
        "zh": {
            "desc": "Qlib 股票池名称。",
            "range": "需存在于 `<qlib_data_dir>/instruments`；测试可用 `test_stock_pool_80`，全量可用存在的 `all`。",
        },
    },
    "interval": {
        "en": {
            "desc": "Scheduler daemon polling interval in seconds.",
            "range": "`10`-`120`; default `30` is usually enough.",
        },
        "zh": {"desc": "定时任务守护进程轮询间隔（秒）。", "range": "建议 `10`-`120`；默认 `30` 通常足够。"},
    },
    "iter_collect": {
        "en": {
            "desc": "New samples collected in each AFF loop.",
            "range": "`100`-`2000`; increase when accepted factors are too few.",
        },
        "zh": {"desc": "AFF 每轮新增采样数量。", "range": "建议 `100`-`2000`；通过因子太少时可调大。"},
    },
    "market": {
        "en": {
            "desc": "Qlib market/instrument name used by templates or h5 rebuilds.",
            "range": "Common values: `all`, `csi300`, `csi500`; must exist in local instruments for Qlib runs.",
        },
        "zh": {
            "desc": "模板或 h5 重建使用的 Qlib market/instrument 名称。",
            "range": "常见 `all`、`csi300`、`csi500`；Qlib 运行时需本地 instruments 存在。",
        },
    },
    "max_len": {
        "en": {
            "desc": "Maximum generated expression length for AFF.",
            "range": "Default `20`; try `10`-`30`; longer expressions are harder to interpret.",
        },
        "zh": {"desc": "AFF 生成表达式的最大长度。", "range": "默认 `20`；可试 `10`-`30`；越长越难解释。"},
    },
    "max_loops": {
        "en": {
            "desc": "Maximum AFF training/mining loops.",
            "range": "`3`-`20`; use lower values for smoke tests.",
        },
        "zh": {"desc": "AFF 最大训练/挖掘循环数。", "range": "建议 `3`-`20`；冒烟测试用较小值。"},
    },
    "mode": {
        "en": {
            "desc": "Strategy backtest mode.",
            "range": "`retrain` for a fresh model; `reuse_model` when a saved model artifact exists.",
        },
        "zh": {"desc": "策略回测模式。", "range": "重新训练用 `retrain`；已有模型产物时可用 `reuse_model`。"},
    },
    "num_epochs_g": {
        "en": {
            "desc": "AFF generator training epochs.",
            "range": "`10`-`100`; start with `50`.",
        },
        "zh": {"desc": "AFF 生成器训练 epoch 数。", "range": "建议 `10`-`100`；可从 `50` 开始。"},
    },
    "num_epochs_p": {
        "en": {
            "desc": "AFF predictor training epochs.",
            "range": "`10`-`100`; start with `50`.",
        },
        "zh": {"desc": "AFF 预测器训练 epoch 数。", "range": "建议 `10`-`100`；可从 `50` 开始。"},
    },
    "pool_capacity": {
        "en": {
            "desc": "Maximum number of factors kept in the search pool.",
            "range": "`5`-`50`; `10` is a good quick default.",
        },
        "zh": {"desc": "搜索池保留的最大因子数量。", "range": "建议 `5`-`50`；快速运行可用 `10`。"},
    },
    "population_size": {
        "en": {
            "desc": "GP population size.",
            "range": "Smoke test: `50`-`300`; normal run: `500`-`5000`; larger values improve search but cost CPU.",
        },
        "zh": {
            "desc": "GP 种群规模。",
            "range": "冒烟 `50`-`300`；常规 `500`-`5000`；越大搜索更充分但更耗 CPU。",
        },
    },
    "port": {
        "en": {
            "desc": "Local HTTP port for a Streamlit app.",
            "range": "`1024`-`65535`; portal defaults to `19901`.",
        },
        "zh": {
            "desc": "Streamlit 应用的本地 HTTP 端口。",
            "range": "可用 `1024`-`65535`；portal 默认 `19901`。",
        },
    },
    "qlib_config_name": {
        "en": {
            "desc": "Named Qlib config/template variant.",
            "range": "Usually omit; set only when the scenario/template defines a specific config name.",
        },
        "zh": {"desc": "Qlib 配置/模板变体名称。", "range": "通常不填；只有场景/模板定义了特定配置名时填写。"},
    },
    "qlib_dir": {
        "en": {
            "desc": "Override Qlib data directory.",
            "range": "Usually omit and use project config; set to a valid local qlib data root when testing another dataset.",
        },
        "zh": {
            "desc": "覆盖 Qlib 数据目录。",
            "range": "通常不填，使用项目配置；测试其他数据集时填有效的本地 qlib 数据根目录。",
        },
    },
    "qlib_template_dir": {
        "en": {
            "desc": "Directory containing Qlib YAML templates/helper scripts.",
            "range": "Usually omit; use `important_data/factor_qlib_templates` for custom factor templates.",
        },
        "zh": {
            "desc": "Qlib YAML 模板和辅助脚本目录。",
            "range": "通常不填；自定义因子模板可用 `important_data/factor_qlib_templates`。",
        },
    },
    "raw": {
        "en": {
            "desc": "Return/raw-log extra mined expressions instead of only accepted factors where supported.",
            "range": "Use `false`/omit for normal runs; `true` for debugging or analysis.",
        },
        "zh": {
            "desc": "支持时返回/记录更多原始挖掘表达式，而不只看通过因子。",
            "range": "常规运行不填或 `false`；调试/分析时填 `true`。",
        },
    },
    "rebuild_h5": {
        "en": {
            "desc": "Rebuild daily_pv h5 after single-stock changes.",
            "range": "Usually `false` during batches; run once with `true` after all edits.",
        },
        "zh": {
            "desc": "单股改动后是否重建 daily_pv h5。",
            "range": "批量处理时通常先 `false`；全部改完后再统一 `true`。",
        },
    },
    "run_tag": {
        "en": {
            "desc": "Human-readable backtest run label.",
            "range": "Optional; use short stable labels like `portal_test` or `my_strategy_202606`.",
        },
        "zh": {
            "desc": "回测运行标签。",
            "range": "可选；建议短且稳定，如 `portal_test`、`my_strategy_202606`。",
        },
    },
    "save": {
        "en": {
            "desc": "Save accepted factors into the factor zoo.",
            "range": "Use `true` for productive runs; `false` for experiments you do not want persisted.",
        },
        "zh": {"desc": "是否把通过的因子保存进因子库。", "range": "正式挖掘填 `true`；只实验不想入库时填 `false`。"},
    },
    "scenario": {
        "en": {
            "desc": "Registered scenario name controlling loop/template behavior.",
            "range": "Mining usually uses `alpha_factor_mining`; factor backtest uses `factor_backtest`.",
        },
        "zh": {
            "desc": "控制循环/模板行为的已注册场景名。",
            "range": "因子挖掘通常用 `alpha_factor_mining`；因子回测用 `factor_backtest`。",
        },
    },
    "seed": {
        "en": {
            "desc": "Random seed for reproducibility.",
            "range": "`0`-`10000000`; keep fixed when comparing methods.",
        },
        "zh": {"desc": "随机种子，用于复现实验。", "range": "`0`-`10000000`；比较不同方法时建议固定。"},
    },
    "skip_smoke": {
        "en": {
            "desc": "Skip Qlib smoke validation.",
            "range": "Use `false` for final configs; `true` only when dependencies/data are unavailable or you need fast generation.",
        },
        "zh": {
            "desc": "是否跳过 Qlib 冒烟校验。",
            "range": "最终配置建议 `false`；依赖/数据不可用或只想快速生成时用 `true`。",
        },
    },
    "smoke_timeout": {
        "en": {
            "desc": "Timeout for Qlib smoke validation in seconds.",
            "range": "`60`-`600`; default `120` is enough for small configs.",
        },
        "zh": {"desc": "Qlib 冒烟校验超时时间（秒）。", "range": "建议 `60`-`600`；小配置默认 `120` 足够。"},
    },
    "source": {
        "en": {
            "desc": "Market data source.",
            "range": "`baostock_cn` for no-token local-friendly runs; `tushare_cn` when Tushare token/quota is available.",
        },
        "zh": {
            "desc": "行情数据源。",
            "range": "无需 token 的本地友好流程用 `baostock_cn`；有 Tushare token/积分时可用 `tushare_cn`。",
        },
    },
    "start_date": {
        "en": {
            "desc": "Start date.",
            "range": "`YYYY-MM-DD`; daily Chinese-stock workflows often start from `2005-01-01` or later.",
        },
        "zh": {"desc": "开始日期。", "range": "`YYYY-MM-DD`；A 股日频常从 `2005-01-01` 或之后开始。"},
    },
    "steps": {
        "en": {
            "desc": "RL training/search steps.",
            "range": "Smoke test: `1000`-`10000`; normal run: `50000`-`500000`.",
        },
        "zh": {
            "desc": "RL 训练/搜索步数。",
            "range": "冒烟 `1000`-`10000`；常规 `50000`-`500000`。",
        },
    },
    "step_n": {
        "en": {
            "desc": "Number of LLM mining/backtest loop steps.",
            "range": "Smoke test: `1`-`3`; exploratory run: `5`-`20`; larger runs cost more LLM/API time.",
        },
        "zh": {
            "desc": "LLM 挖掘/回测循环步数。",
            "range": "冒烟 `1`-`3`；探索 `5`-`20`；更大值会显著增加 LLM/API 成本。",
        },
    },
    "stock_csv": {
        "en": {
            "desc": "CSV file listing target stocks.",
            "range": "Use a small pool for tests; use main stock list for production downloads.",
        },
        "zh": {"desc": "目标股票列表 CSV。", "range": "测试用小股票池；正式下载用主股票列表。"},
    },
    "strategy_name": {
        "en": {
            "desc": "Saved strategy asset name.",
            "range": "Must exist in the strategy database for strategy backtests.",
        },
        "zh": {"desc": "已保存的策略资产名称。", "range": "策略回测时必须存在于策略库。"},
    },
    "target_mode": {
        "en": {
            "desc": "Final adjustment mode synthesized after raw download.",
            "range": "`forward` for forward-adjusted output; `backward` for backtest-style adjusted output.",
        },
        "zh": {
            "desc": "未复权下载后最终合成的复权类型。",
            "range": "输出前复权用 `forward`；偏回测使用的后复权用 `backward`。",
        },
    },
    "template": {
        "en": {
            "desc": "Qlib YAML template family.",
            "range": "`baseline` for simple configs; `combined` for the combined KDD-style template.",
        },
        "zh": {
            "desc": "Qlib YAML 模板类型。",
            "range": "简单配置用 `baseline`；组合 KDD 风格模板用 `combined`。",
        },
    },
    "token": {
        "en": {
            "desc": "Tushare token.",
            "range": "Prefer leaving empty and using `TUSHARE_TOKEN`; paste only for temporary portal runs.",
        },
        "zh": {
            "desc": "Tushare token。",
            "range": "优先留空并使用环境变量 `TUSHARE_TOKEN`；只在临时 portal 运行时粘贴。",
        },
    },
    "top_n": {
        "en": {
            "desc": "Keep/evaluate the top-N mined expressions where supported.",
            "range": "`10`-`200`; start with `50`.",
        },
        "zh": {"desc": "支持时保留/评估排名前 N 的挖掘表达式。", "range": "建议 `10`-`200`；可从 `50` 开始。"},
    },
    "topk": {
        "en": {
            "desc": "Portfolio TopK value in generated Qlib config.",
            "range": "`10`-`100`; common starting point is `50`.",
        },
        "zh": {"desc": "生成 Qlib 配置中的组合 TopK。", "range": "建议 `10`-`100`；常用起点 `50`。"},
    },
    "tournament_size": {
        "en": {
            "desc": "GP tournament size for parent selection.",
            "range": "`5`-`50`; start around `20`.",
        },
        "zh": {"desc": "GP 父代选择的锦标赛规模。", "range": "建议 `5`-`50`；可从 `20` 开始。"},
    },
    "train_end_year": {
        "en": {
            "desc": "Last year included in the training segment.",
            "range": "`2018`-`2022` is common; default `2020` leaves later years for validation/test.",
        },
        "zh": {
            "desc": "训练集包含的最后年份。",
            "range": "常见 `2018`-`2022`；默认 `2020` 会把后续年份留给验证/测试。",
        },
    },
    "zoo_size": {
        "en": {
            "desc": "Target number of factors in the AFF candidate zoo.",
            "range": "Smoke test: `20`-`100`; normal run: `100`-`1000`.",
        },
        "zh": {"desc": "AFF 候选因子池目标大小。", "range": "冒烟 `20`-`100`；常规 `100`-`1000`。"},
    },
}


def _json_example_value(name: str, param: inspect.Parameter) -> Any:
    samples: dict[str, Any] = {
        "action": "pipeline",
        "adjust_mode": "backward",
        "benchmark": "SH000300",
        "config": "important_data/factor_qlib_templates/conf.yaml",
        "direction": "验证一个新的量价因子假说",
        "end_date": "2024-12-31",
        "factor_path": "important_data/factors.csv",
        "host": "0.0.0.0",
        "instruments": "test_stock_pool_80",
        "market": "all",
        "mode": "retrain",
        "output": "important_data/factor_qlib_templates/custom.yaml",
        "path": "log/session_name",
        "qlib_config_name": "conf.yaml",
        "qlib_data_dir": "git_ignore_folder/qlib_data/cn_data",
        "qlib_dir": "git_ignore_folder/qlib_data/cn_data",
        "qlib_template_dir": "important_data/factor_qlib_templates",
        "run_tag": "portal_test",
        "scenario": "factor_backtest",
        "source": "baostock_cn",
        "start_date": "2020-01-01",
        "stock_csv": "important_data/stock_lists/main_stock_2026_4_27.csv",
        "strategy_name": "my_strategy",
        "symbol": "sh.600000",
        "template": "baseline",
    }
    if name in samples:
        return samples[name]
    if param.default is not inspect._empty and param.default is not None:
        return param.default
    annotation = param.annotation
    if annotation is bool or isinstance(param.default, bool):
        return False
    if annotation is int or isinstance(param.default, int):
        return 1
    if annotation is float or isinstance(param.default, float):
        return 0.1
    return f"<{name}>"


def _command_kwargs_example(
    module_name: str,
    command_name: str,
    sig: inspect.Signature | str,
) -> dict[str, Any]:
    override = _COMMAND_KWARGS_EXAMPLES.get((module_name, command_name))
    if override is not None:
        return override
    if not isinstance(sig, inspect.Signature):
        return {}

    required: dict[str, Any] = {}
    optional: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if param.kind in (
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            continue
        if param.default is inspect._empty:
            required[name] = _json_example_value(name, param)
        elif len(optional) < 3:
            optional[name] = _json_example_value(name, param)
    return required or optional


def _format_command_parameters(
    sig: inspect.Signature | str,
) -> tuple[list[str], list[str], str | None]:
    if not isinstance(sig, inspect.Signature):
        return [], [], None

    required: list[str] = []
    optional: list[str] = []
    var_kw: str | None = None
    for name, param in sig.parameters.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            var_kw = name
            continue
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            continue
        if param.default is inspect._empty:
            required.append(name)
        else:
            try:
                default = json.dumps(param.default, ensure_ascii=False, default=str)
            except TypeError:
                default = repr(param.default)
            optional.append(f"{name}={default}")
    return required, optional, var_kw


def _command_parameter_names(
    module_name: str,
    command_name: str,
    sig: inspect.Signature | str,
    example: dict[str, Any],
) -> list[str]:
    names: list[str] = []
    if isinstance(sig, inspect.Signature):
        names.extend(
            name
            for name, param in sig.parameters.items()
            if param.kind
            not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
        )
    names.extend(example.keys())
    names.extend(_COMMAND_EXTRA_PARAM_NAMES.get((module_name, command_name), []))
    return list(dict.fromkeys(names))


def _render_parameter_details(names: list[str]) -> None:
    rows: list[dict[str, str]] = []
    lang = get_lang()
    for name in names:
        localized = _PARAMETER_DETAILS.get(name, {}).get(lang)
        if not localized:
            continue
        rows.append(
            {
                t("param_detail_name"): name,
                t("param_detail_desc"): localized["desc"],
                t("param_detail_range"): localized["range"],
            }
        )
    if not rows:
        return
    with st.expander(t("param_detail_heading"), expanded=False):
        st.dataframe(rows, width="stretch", hide_index=True)


def _render_command_kwargs_help(
    module_name: str,
    command_name: str,
    command_fn: Callable[..., Any],
    sig: inspect.Signature | str,
) -> None:
    required, optional, var_kw = _format_command_parameters(sig)
    example = _command_kwargs_example(module_name, command_name, sig)
    doc = inspect.getdoc(command_fn) or ""
    doc_first_line = doc.splitlines()[0] if doc else ""

    st.markdown(f"**{t('command_kwargs_guide_title')}**")
    st.caption(t("command_kwargs_guide_caption"))
    if doc_first_line:
        st.caption(doc_first_line)
    if required:
        st.write(
            t("command_required_params", params=", ".join(f"`{p}`" for p in required))
        )
    if optional:
        st.write(
            t(
                "command_optional_params",
                params=", ".join(f"`{p}`" for p in optional[:12]),
            )
        )
        if len(optional) > 12:
            st.caption(t("command_optional_more", count=len(optional) - 12))
    if var_kw:
        st.write(t("command_var_kwargs", name=var_kw))
    extra_note = _COMMAND_EXTRA_NOTES.get((module_name, command_name))
    if extra_note:
        st.info(extra_note.get(get_lang(), extra_note["en"]))
    _render_parameter_details(
        _command_parameter_names(module_name, command_name, sig, example)
    )
    st.write(t("command_example_json"))
    st.code(json.dumps(example, ensure_ascii=False, indent=2), language="json")
    st.caption(t("command_empty_json_hint"))


def _render_alphaforge_extra_kwargs_help(method: str) -> None:
    module_name = "alphaforge_aff" if method == "mine_aff" else "alphaforge_search"
    extra_note = _COMMAND_EXTRA_NOTES.get((module_name, method))

    st.markdown(f"**{t('af_extra_kwargs_guide_title')}**")
    st.caption(t("af_extra_kwargs_guide_caption"))
    if extra_note:
        st.info(extra_note.get(get_lang(), extra_note["en"]))
    names = list(_ALPHAFORGE_EXTRA_KWARGS_EXAMPLES.get(method, {}).keys())
    names.extend(_COMMAND_EXTRA_PARAM_NAMES.get((module_name, method), []))
    _render_parameter_details(list(dict.fromkeys(names)))
    st.write(t("command_example_json"))
    st.code(
        json.dumps(
            _ALPHAFORGE_EXTRA_KWARGS_EXAMPLES.get(method, {}),
            ensure_ascii=False,
            indent=2,
        ),
        language="json",
    )
    st.caption(t("command_empty_json_hint"))


def _render_overview(engine: Any) -> None:
    st.subheader(t("overview_subheader"))
    st.write(t("overview_description"))

    st.markdown(f"#### {t('systems_heading')}")
    for name, system in engine.systems.items():
        with st.expander(
            t("system_expander", name=name, class_name=type(system).__name__),
            expanded=False,
        ):
            st.write(
                t(
                    "type_label",
                    module=type(system).__module__,
                    name=type(system).__name__,
                )
            )

    st.markdown(f"#### {t('modules_heading')}")
    for name, module in engine.modules.items():
        commands = sorted(module.commands().keys())
        with st.expander(
            t("module_expander", name=name, count=len(commands)), expanded=False
        ):
            st.write(
                t(
                    "type_label",
                    module=type(module).__module__,
                    name=type(module).__name__,
                )
            )
            st.write(t("commands_label"))
            for cmd in commands:
                st.write(t("command_item", cmd=cmd))


def _render_data_tab(engine: Any) -> None:
    st.subheader(t("data_subheader"))
    data_system = engine.get_system("data")
    cfg = engine.config.data
    from alphapilot.kernel.paths import default_stock_csv_path

    c1, c2, c3 = st.columns(3)
    c1.text_input(t("qlib_data_dir"), str(cfg.qlib_data_dir), disabled=True)
    c2.text_input(t("raw_data_dir"), str(cfg.raw_data_dir), disabled=True)
    c3.text_input(t("adjust_factor_dir"), str(cfg.factor_dir), disabled=True)

    st.markdown(f"#### {t('universe_heading')}")
    if st.button(t("load_universe")):
        try:
            universe = data_system.get_universe()
            st.success(t("universe_loaded", count=len(universe)))
            st.dataframe({"symbol": universe[:500]}, width="stretch", hide_index=True)
        except Exception as exc:  # noqa: BLE001
            st.error(t("universe_failed", error=exc))

    st.markdown(f"#### {t('data_ops_heading')}")
    action = st.selectbox(
        t("data_action"),
        ["pipeline", "download", "apply_adjust", "convert", "build_h5"],
        key="data_action",
    )

    # download / apply_adjust / pipeline are source-aware; convert/build_h5 use defaults.
    is_download = action == "download"
    is_apply_adjust = action == "apply_adjust"
    is_pipeline = action == "pipeline"
    source = "baostock_cn"
    if is_download or is_apply_adjust or is_pipeline:
        source_key = (
            "data_dl_source"
            if is_download
            else "data_apply_source"
            if is_apply_adjust
            else "data_pipeline_source"
        )
        source = st.selectbox(
            t("data_source"), ["baostock_cn", "tushare_cn"], key=source_key
        )
    is_tushare = source == "tushare_cn"

    start_date = end_date = ""
    if action in ("pipeline", "download"):
        start_date = st.text_input(t("start_date"), "2005-01-01")
        end_date = st.text_input(t("end_date"), "")
    elif action == "build_h5":
        start_date = st.text_input(t("start_date"), "2005-01-01")

    stock_csv = ""
    if action in ("pipeline", "download", "convert"):
        stock_csv = st.text_input(t("stock_csv"), str(default_stock_csv_path()))

    apply_raw_dir = apply_factor_dir = apply_output_dir = ""
    apply_default_raw_dir = apply_default_factor_dir = apply_default_output_dir = ""
    refresh_factors_if_needed = False
    target_mode = "forward"
    show_target_mode = False
    pipeline_token = ""
    if is_apply_adjust:
        from alphapilot.systems.data.data_paths import (
            canonical_baostock_raw_dir,
            canonical_tushare_factor_dir,
            canonical_tushare_raw_dir,
            existing_baostock_factor_dir,
            existing_baostock_raw_dir,
        )

        st.info(t("apply_adjust_note"))
        adjust_mode = st.selectbox(
            t("apply_adjust_target_mode"),
            ["forward", "backward"],
            index=0,
            key="data_apply_adjust_mode",
        )
        if is_tushare:
            apply_default_raw_dir = str(canonical_tushare_raw_dir("none"))
            apply_default_factor_dir = str(canonical_tushare_factor_dir())
            apply_default_output_dir = str(canonical_tushare_raw_dir(adjust_mode))
            st.info(t("apply_adjust_tushare_note"))
        else:
            apply_default_raw_dir = str(existing_baostock_raw_dir("none"))
            apply_default_factor_dir = str(existing_baostock_factor_dir())
            apply_default_output_dir = str(canonical_baostock_raw_dir(adjust_mode))
        with st.expander(t("apply_adjust_custom_params")):
            apply_raw_dir = st.text_input(
                t("apply_adjust_raw_dir"),
                apply_default_raw_dir,
                key=f"data_apply_raw_dir_{source}",
            )
            apply_factor_dir = st.text_input(
                t("apply_adjust_factor_dir"),
                apply_default_factor_dir,
                key=f"data_apply_factor_dir_{source}",
            )
            apply_output_dir = st.text_input(
                t("apply_adjust_output_dir"),
                apply_default_output_dir,
                key=f"data_apply_output_dir_{source}_{adjust_mode}",
            )
            if not is_tushare:
                refresh_factors_if_needed = st.checkbox(
                    t("apply_adjust_refresh_factors"),
                    value=False,
                    key="data_apply_refresh_factors",
                )
    elif is_pipeline:
        # Pipeline = download -> (apply_adjust) -> convert. Tushare can only download
        # 除权(none), so the final 前/后复权 is chosen via target_mode.
        if is_tushare:
            adjust_mode = "none"
            st.info(t("tushare_adjust_note"))
            show_target_mode = True
        else:
            adjust_mode = st.selectbox(
                t("adjust_mode"),
                ["none", "forward", "backward"],
                index=0,
                key="data_pipeline_adjust_mode",
            )
            show_target_mode = adjust_mode == "none"
        if show_target_mode:
            target_mode = st.selectbox(
                t("pipeline_target_mode"),
                ["forward", "backward"],
                index=0,
                key="data_pipeline_target_mode",
            )
        if is_tushare:
            pipeline_token = st.text_input(
                t("tushare_token"), "", type="password", key="data_pipeline_token"
            )
    else:
        adjust_mode = st.selectbox(
            t("adjust_mode"), ["backward", "forward", "none"], index=0
        )
        if is_tushare:
            st.info(t("tushare_adjust_note"))

    output_dir = factor_dir = code_column = token = ""
    all_market = include_daily_basic = False
    parallel_price_factor = False
    if is_download:
        with st.expander(t("download_custom_params")):
            output_dir = st.text_input(
                t("download_output_dir"), "", key="data_dl_output_dir"
            )
            factor_dir = st.text_input(
                t("download_factor_dir"), "", key="data_dl_factor_dir"
            )
            code_column = st.text_input(
                t("download_code_column"), "", key="data_dl_code_column"
            )
            all_market = st.checkbox(
                t("download_all_market"), value=False, key="data_dl_all_market"
            )
            if is_tushare:
                token = st.text_input(
                    t("tushare_token"), "", type="password", key="data_dl_token"
                )
                include_daily_basic = st.checkbox(
                    t("include_daily_basic"), value=False, key="data_dl_daily_basic"
                )
    if action in ("download", "pipeline") and adjust_mode == "none":
        parallel_price_factor = st.checkbox(
            t("parallel_price_factor"),
            value=False,
            key=f"data_parallel_price_factor_{action}_{source}",
        )
        st.caption(t("parallel_price_factor_hint"))
    if st.button(t("run_data_action")):
        try:
            kwargs: dict[str, Any] = {}

            if action == "build_h5":
                if start_date.strip():
                    kwargs["start_date"] = start_date.strip()
            elif action == "apply_adjust":
                kwargs["adjust_mode"] = adjust_mode
                kwargs["raw_dir"] = apply_raw_dir.strip() or apply_default_raw_dir
                kwargs["factor_dir"] = (
                    apply_factor_dir.strip() or apply_default_factor_dir
                )
                kwargs["output_dir"] = (
                    apply_output_dir.strip() or apply_default_output_dir
                )
                if refresh_factors_if_needed and not is_tushare:
                    kwargs["refresh_factors_if_needed"] = True
            else:
                if end_date.strip():
                    kwargs["end_date"] = end_date.strip()
                if stock_csv.strip() and not all_market:
                    kwargs["stock_csv"] = stock_csv.strip()

            if action in ("pipeline", "convert"):
                kwargs["adjust_mode"] = adjust_mode
            if action in ("pipeline", "download"):
                kwargs["start_date"] = start_date.strip()

            if is_pipeline:
                kwargs["source"] = source
                if show_target_mode:
                    kwargs["target_mode"] = target_mode
                if is_tushare:
                    kwargs["adjust_mode"] = "none"
                    if pipeline_token.strip():
                        kwargs["token"] = pipeline_token.strip()
                if parallel_price_factor:
                    kwargs["parallel_price_factor"] = True

            if is_download:
                if not all_market and not stock_csv.strip():
                    st.warning(t("download_requires_stock_csv"))
                    return
                kwargs["adjust_mode"] = adjust_mode
                kwargs["source"] = source
                if output_dir.strip():
                    kwargs["output_dir"] = output_dir.strip()
                if factor_dir.strip():
                    kwargs["factor_dir"] = factor_dir.strip()
                if code_column.strip():
                    kwargs["code_column"] = code_column.strip()
                if all_market:
                    kwargs["all_market"] = True
                if is_tushare:
                    if token.strip():
                        kwargs["token"] = token.strip()
                    if include_daily_basic:
                        kwargs["include_daily_basic"] = True
                if parallel_price_factor:
                    kwargs["parallel_price_factor"] = True

            result = getattr(data_system, action)(**kwargs)
            st.success(t("data_action_finished", action=action))
            st.write(result)
        except Exception as exc:  # noqa: BLE001
            st.error(t("data_action_failed", error=exc))

    _render_stock_manage(data_system)


def _render_h5_rebuild(data_system: Any, *, source: str = "baostock_cn") -> None:
    """Deferred daily_pv h5 rebuild, shown once a modify/delete marks it stale."""
    if not st.session_state.get("portal_stock_h5_stale"):
        return
    st.warning(t("stock_h5_stale_warning"))
    market = st.text_input(
        t("stock_rebuild_h5_market"), value="", key="portal_stock_h5_market"
    )
    if st.button(t("stock_rebuild_h5_btn"), key="portal_stock_h5_btn"):
        try:
            kwargs: dict[str, Any] = {}
            if source == "tushare_cn":
                from alphapilot.systems.data.data_paths import existing_tushare_qlib_dir

                kwargs["qlib_dir"] = str(existing_tushare_qlib_dir())
            if market.strip():
                kwargs["market"] = market.strip()
            if kwargs:
                data_system.rebuild_h5(**kwargs)
            else:
                data_system.rebuild_h5()
            st.session_state["portal_stock_h5_stale"] = False
            st.success(t("stock_h5_rebuilt"))
        except Exception as exc:  # noqa: BLE001
            st.error(t("stock_h5_rebuild_failed", error=exc))


def _render_stock_manage(data_system: Any) -> None:
    """Single-stock delete / refresh / trim controls in the Data tab."""
    st.markdown(f"#### {t('stock_manage_heading')}")
    st.info(t("stock_manage_baostock_only"))
    st.caption(t("stock_manage_caption"))
    source = st.selectbox(
        t("data_source"),
        ["baostock_cn", "tushare_cn"],
        key="portal_stock_manage_source",
    )
    is_tushare = source == "tushare_cn"
    try:
        by_mode = data_system.list_symbols(source=source)
    except Exception as exc:  # noqa: BLE001
        st.error(t("data_action_failed", error=exc))
        return

    all_symbols = sorted({s for syms in by_mode.values() for s in syms})
    if not all_symbols:
        st.info(t("stock_manage_no_symbols"))
        _render_h5_rebuild(data_system, source=source)
        return

    available_modes = [m for m, syms in by_mode.items() if syms]
    symbol = st.selectbox(
        t("stock_select_symbol"), all_symbols, key=f"portal_stock_symbol_{source}"
    )
    modes = st.multiselect(
        t("stock_adjust_modes"),
        list(by_mode.keys()),
        default=available_modes,
        key=f"portal_stock_modes_{source}",
    )
    qlib_mode = st.selectbox(
        t("stock_qlib_adjust_mode"),
        ["backward", "forward", "none"],
        index=0,
        key=f"portal_stock_qlib_mode_{source}",
    )

    # --- Delete ---
    st.markdown(f"##### {t('stock_delete_heading')}")
    del_confirm = st.checkbox(t("delete_confirm"), key="portal_stock_del_confirm")
    if st.button(t("stock_delete_btn"), key="portal_stock_del_btn"):
        if not del_confirm:
            st.warning(t("delete_confirm"))
        else:
            try:
                report = data_system.delete_symbol(
                    symbol,
                    adjust_mode=modes or None,
                    source=source,
                )
                st.session_state["portal_stock_h5_stale"] = True
                st.cache_data.clear()
                st.success(
                    t(
                        "stock_deleted",
                        name=symbol,
                        detail=f"{len(report.get('deleted', []))} items",
                    )
                )
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(t("stock_delete_failed", error=exc))

    # --- Refresh / re-download ---
    st.markdown(f"##### {t('stock_refresh_heading')}")
    refresh_start = st.text_input(
        t("start_date"), value="2016-12-31", key="portal_stock_refresh_start"
    )
    refresh_end = st.text_input(t("end_date"), value="", key="portal_stock_refresh_end")
    refresh_token = ""
    if is_tushare:
        refresh_token = st.text_input(
            t("tushare_token"), "", type="password", key="portal_stock_refresh_token"
        )
    if st.button(t("stock_refresh_btn"), key="portal_stock_refresh_btn"):
        try:
            refresh_kwargs: dict[str, Any] = {}
            if refresh_token.strip():
                refresh_kwargs["token"] = refresh_token.strip()
            data_system.refresh_symbol(
                symbol,
                adjust_mode=modes or "backward",
                source=source,
                start_date=refresh_start.strip() or "2016-12-31",
                end_date=refresh_end.strip() or None,
                qlib_adjust_mode=qlib_mode,
                **refresh_kwargs,
            )
            st.session_state["portal_stock_h5_stale"] = True
            st.cache_data.clear()
            st.success(t("stock_refreshed", name=symbol))
        except Exception as exc:  # noqa: BLE001
            st.error(t("stock_refresh_failed", error=exc))

    # --- Apply adjust (unadjusted + factors -> forward/backward CSV) ---
    st.markdown(f"##### {t('stock_apply_adjust_heading')}")
    st.caption(t("stock_apply_adjust_caption"))
    apply_target = st.selectbox(
        t("stock_apply_adjust_target"),
        ["forward", "backward"],
        index=0,
        key="portal_stock_apply_target",
    )
    if st.button(t("stock_apply_adjust_btn"), key="portal_stock_apply_btn"):
        try:
            report = data_system.apply_adjust_symbol(
                symbol,
                target_mode=apply_target,
                source=source,
            )
            st.cache_data.clear()
            st.success(t("stock_apply_adjusted", name=symbol, mode=apply_target))
            st.json(report)
        except Exception as exc:  # noqa: BLE001
            st.error(t("stock_apply_adjust_failed", error=exc))

    # --- Trim ---
    st.markdown(f"##### {t('stock_trim_heading')}")
    trim_start = st.text_input(
        t("stock_trim_start"), value="", key="portal_stock_trim_start"
    )
    trim_end = st.text_input(t("stock_trim_end"), value="", key="portal_stock_trim_end")
    drop_dates = st.text_input(
        t("stock_drop_dates"), value="", key="portal_stock_drop_dates"
    )
    if st.button(t("stock_trim_btn"), key="portal_stock_trim_btn"):
        try:
            data_system.trim_symbol(
                symbol,
                adjust_mode=modes or None,
                source=source,
                start=trim_start.strip() or None,
                end=trim_end.strip() or None,
                drop_dates=drop_dates.strip() or None,
                qlib_adjust_mode=qlib_mode,
            )
            st.session_state["portal_stock_h5_stale"] = True
            st.cache_data.clear()
            st.success(t("stock_trimmed", name=symbol))
        except Exception as exc:  # noqa: BLE001
            st.error(t("stock_trim_failed", error=exc))

    _render_h5_rebuild(data_system, source=source)


def _factor_store_path(engine: Any, factor_system: Any) -> Path:
    database = getattr(factor_system, "database", None)
    for attr in ("db_path", "zoo_path", "csv_path"):
        path = getattr(database, attr, None)
        if path:
            return Path(path)
    backend = getattr(engine.config.factor, "database_backend", "")
    filename = "factor_zoo.db" if backend == "sqlite" else "factor_zoo.csv"
    return Path(engine.config.factor.zoo_dir) / filename


def _render_factor_backtest_options(key_prefix: str) -> dict[str, Any]:
    st.markdown(f"##### {t('factor_bt_options_heading')}")
    st.info(t("factor_bt_launch_hint"))
    st.caption(t("factor_bt_options_caption"))
    c1, c2 = st.columns(2)
    mode = c1.selectbox(
        t("bt_factor_mode"),
        ["multi_combined", "single_ic", "multi_sequential"],
        index=0,
        key=f"{key_prefix}_mode",
        help=t("factor_bt_mode_help"),
    )
    scenario = c2.text_input(
        t("bt_scenario"),
        value="factor_backtest",
        key=f"{key_prefix}_scenario",
    )
    qlib_config_name = c1.text_input(
        t("qlib_config_name"),
        value="",
        key=f"{key_prefix}_qlib_config",
    )
    qlib_template_dir = c2.text_input(
        t("qlib_template_dir"),
        value="",
        key=f"{key_prefix}_qlib_template",
    )
    yaml_params = st.text_area(
        t("bt_yaml_params_json"),
        value="",
        height=110,
        placeholder='{"topk": 30, "n_drop": 5, "backtest_start": "2024-01-01"}',
        key=f"{key_prefix}_yaml_params",
    )
    return _nonempty_kwargs(
        {
            "scenario": scenario,
            "qlib_config_name": qlib_config_name,
            "qlib_template_dir": qlib_template_dir,
            "mode": mode,
            "yaml_params": yaml_params,
        }
    )


def _remember_factor_backtest_job(job: dict[str, Any], kwargs: dict[str, Any]) -> None:
    st.session_state["portal_factor_backtest_notice"] = {
        "job_id": job.get("job_id", ""),
        "mode": kwargs.get("mode", "multi_combined"),
    }


def _render_factor_backtest_notice() -> None:
    notice = st.session_state.get("portal_factor_backtest_notice")
    if not notice:
        return
    st.info(
        t(
            "factor_bt_running_notice",
            job_id=notice.get("job_id", ""),
            mode=notice.get("mode", "multi_combined"),
        )
    )


def _render_factor_tab(engine: Any) -> None:
    st.subheader(t("factor_subheader"))
    _render_factor_backtest_notice()
    factor_system = engine.get_system("factor")
    store_path = _factor_store_path(engine, factor_system)
    has_categories = bool(getattr(factor_system, "supports_categories", False))

    try:
        factors = factor_system.list_factors()
    except Exception as exc:  # noqa: BLE001
        factors = []
        st.warning(t("factor_zoo_preview_failed", error=exc))
    all_categories = factor_system.list_categories() if has_categories else []

    factor_names = [f["factor_name"] for f in factors]
    category_counts: dict[str, int] = {cat: 0 for cat in all_categories}
    for factor in factors:
        for cat in factor.get("categories", []):
            category_counts[cat] = category_counts.get(cat, 0) + 1

    # ---- Factor list (source of truth = factor system; shows categories) ----
    selected_factor_names: list[str] = []
    if factors:
        filter_cats = (
            st.multiselect(
                t("factor_filter_by_category"),
                all_categories,
                key="portal_factor_filter",
            )
            if has_categories and all_categories
            else []
        )
        search_text = st.text_input(t("factor_search"), key="portal_factor_search")
        query = search_text.strip().lower()
        rows = [
            {
                "factor_name": f["factor_name"],
                "factor_expression": f["factor_expression"],
                "categories": ", ".join(f.get("categories", [])),
            }
            for f in factors
            if not filter_cats or (set(filter_cats) & set(f.get("categories", [])))
        ]
        if query:
            rows = [
                row
                for row in rows
                if query
                in " ".join(
                    [
                        str(row["factor_name"]),
                        str(row["factor_expression"]),
                        str(row["categories"]),
                    ]
                ).lower()
            ]
        st.success(t("factor_zoo_rows", count=len(rows)))
        table_state = st.dataframe(
            rows,
            width="stretch",
            hide_index=True,
            key="portal_factor_table",
            on_select="rerun",
            selection_mode="multi-row",
        )
        selection = getattr(table_state, "selection", None)
        if selection is None and isinstance(table_state, dict):
            selection = table_state.get("selection", {})
        selected_rows = getattr(selection, "rows", None)
        if selected_rows is None and isinstance(selection, dict):
            selected_rows = selection.get("rows", [])
        selected_factor_names = [
            rows[i]["factor_name"] for i in (selected_rows or []) if 0 <= i < len(rows)
        ]
        st.caption(
            t(
                "factor_selection_summary",
                shown=len(rows),
                selected=len(selected_factor_names),
            )
        )
        with st.expander(t("selected_backtest_settings"), expanded=False):
            selected_backtest_kwargs = _render_factor_backtest_options("portal_sel_bt")
        if st.button(
            t("selected_backtest_btn"),
            key="portal_sel_bt_btn",
            disabled=not selected_factor_names,
        ):
            import tempfile
            import time

            import pandas as pd

            from alphapilot.modules.portal import jobs as portal_jobs

            tmp = (
                Path(tempfile.gettempdir())
                / f"alphapilot_selected_{int(time.time())}.csv"
            )
            try:
                sel = [
                    {
                        "factor_name": rows[i]["factor_name"],
                        "factor_expression": rows[i]["factor_expression"],
                    }
                    for i in (selected_rows or [])
                    if 0 <= i < len(rows)
                ]
                if not sel:
                    st.warning(t("selected_empty"))
                else:
                    pd.DataFrame(sel).to_csv(tmp, index=False)
                    job_kwargs = {
                        **selected_backtest_kwargs,
                        "factor_path": str(tmp),
                    }
                    job = portal_jobs.start_job("factor_backtest", job_kwargs)
                    _remember_factor_backtest_job(job, job_kwargs)
                    st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(t("job_start_failed", error=exc))
    else:
        st.info(t("factor_zoo_missing"))
    st.text_input(t("factor_zoo_csv"), str(store_path), disabled=True)

    # ---- Bulk category assignment/removal ----
    if has_categories and factors:
        st.markdown(f"#### {t('bulk_category_heading')}")
        st.caption(t("bulk_category_caption"))
        last_bulk_summary = st.session_state.get("portal_bulk_category_last")
        if last_bulk_summary:
            st.success(
                t(
                    "bulk_category_result",
                    changed=len(last_bulk_summary.get("changed", [])),
                    unchanged=len(last_bulk_summary.get("unchanged", [])),
                    missing=len(last_bulk_summary.get("missing", [])),
                )
            )
            with st.expander(t("bulk_category_result_details"), expanded=False):
                st.json(last_bulk_summary)
        bc1, bc2 = st.columns(2)
        existing_target = bc1.selectbox(
            t("bulk_category_existing"),
            [""] + all_categories,
            format_func=lambda name: t("bulk_category_existing_placeholder")
            if not name
            else name,
            key="portal_bulk_cat_existing",
        )
        new_target = bc2.text_input(t("bulk_category_new"), key="portal_bulk_cat_new")
        target_category = new_target.strip() or str(existing_target).strip()
        disabled_bulk = not selected_factor_names or not target_category
        ba, br = st.columns(2)
        if ba.button(
            t("bulk_category_add_btn"),
            key="portal_bulk_cat_add",
            disabled=disabled_bulk,
            width="stretch",
        ):
            try:
                summary = factor_system.add_factors_to_category(
                    selected_factor_names, target_category
                )
                st.session_state["portal_bulk_category_last"] = summary
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                ba.error(t("bulk_category_failed", error=exc))
        if br.button(
            t("bulk_category_remove_btn"),
            key="portal_bulk_cat_remove",
            disabled=disabled_bulk,
            width="stretch",
        ):
            try:
                summary = factor_system.remove_factors_from_category(
                    selected_factor_names, target_category
                )
                st.session_state["portal_bulk_category_last"] = summary
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                br.error(t("bulk_category_failed", error=exc))
        if disabled_bulk:
            st.caption(t("bulk_category_disabled_hint"))

    # ---- Category registry management ----
    if has_categories:
        st.markdown(f"#### {t('category_manage_heading')}")
        if category_counts:
            st.dataframe(
                [
                    {
                        t("category_table_name"): cat,
                        t("category_table_factor_count"): category_counts.get(cat, 0),
                    }
                    for cat in sorted(category_counts)
                ],
                width="stretch",
                hide_index=True,
            )
        new_cat = st.text_input(t("category_new_name"), key="portal_cat_new")
        if st.button(t("category_create_btn"), key="portal_cat_create"):
            if new_cat.strip() and factor_system.create_category(new_cat.strip()):
                st.success(t("category_created", name=new_cat.strip()))
                st.rerun()
        if all_categories:
            rc, dc = st.columns(2)
            with rc:
                ren_old = st.selectbox(
                    t("category_rename_old"), all_categories, key="portal_cat_ren_old"
                )
                ren_new = st.text_input(
                    t("category_rename_new"), key="portal_cat_ren_new"
                )
                if st.button(t("category_rename_btn"), key="portal_cat_ren_btn"):
                    if ren_new.strip() and factor_system.rename_category(
                        ren_old, ren_new.strip()
                    ):
                        st.success(
                            t("category_renamed", old=ren_old, new=ren_new.strip())
                        )
                        st.rerun()
            with dc:
                del_cat = st.selectbox(
                    t("category_delete_select"),
                    all_categories,
                    key="portal_cat_del_sel",
                )
                del_ok = st.checkbox(t("delete_confirm"), key="portal_cat_del_confirm")
                if st.button(t("category_delete_btn"), key="portal_cat_del_btn"):
                    if not del_ok:
                        st.warning(t("delete_confirm"))
                    elif factor_system.delete_category(del_cat):
                        st.success(t("category_deleted", name=del_cat))
                        st.rerun()

    # ---- Delete factor ----
    if factors:
        st.markdown(f"#### {t('delete_heading')}")
        delete_factor_name = st.selectbox(
            t("select_factor_to_delete"), factor_names, key="portal_delete_factor"
        )
        delete_factor_confirm = st.checkbox(
            t("delete_confirm"), key="portal_delete_factor_confirm"
        )
        if st.button(t("delete_factor_btn"), key="portal_delete_factor_btn"):
            if not delete_factor_confirm:
                st.warning(t("delete_confirm"))
            else:
                try:
                    if factor_system.delete_factor(delete_factor_name):
                        st.success(t("factor_deleted", name=delete_factor_name))
                        st.rerun()
                    else:
                        st.error(t("factor_delete_failed", name=delete_factor_name))
                except Exception as exc:  # noqa: BLE001
                    st.error(t("factor_delete_error", error=exc))

    # ---- Edit a single factor's categories ----
    if has_categories and factors:
        with st.expander(t("factor_edit_categories_heading"), expanded=False):
            edit_factor = st.selectbox(
                t("factor_edit_select"), factor_names, key="portal_fcat_sel"
            )
            current = next(
                (
                    f.get("categories", [])
                    for f in factors
                    if f["factor_name"] == edit_factor
                ),
                [],
            )
            chosen = st.multiselect(
                t("factor_edit_categories"),
                all_categories,
                default=current,
                key="portal_fcat_ms",
            )
            extra = st.text_input(
                t("factor_edit_new_categories"), key="portal_fcat_extra"
            )
            if st.button(t("factor_edit_save"), key="portal_fcat_save"):
                cats = list(chosen) + [c.strip() for c in extra.split(",") if c.strip()]
                if factor_system.set_factor_categories(edit_factor, cats):
                    st.success(t("factor_categories_updated", name=edit_factor))
                    st.rerun()

    # ---- Category-scoped actions: export / backtest ----
    if has_categories and all_categories:
        st.markdown(f"#### {t('category_actions_heading')}")
        act_cat = st.selectbox(
            t("category_action_select"), all_categories, key="portal_cat_act_sel"
        )
        safe_name = "".join(ch if ch.isalnum() else "_" for ch in act_cat)
        ec, bc = st.columns(2)
        exp_path = ec.text_input(
            t("category_export_path"),
            value=str(store_path.parent / f"category_{safe_name}.csv"),
            key="portal_cat_exp_path",
        )
        with st.expander(t("category_backtest_settings"), expanded=False):
            category_backtest_kwargs = _render_factor_backtest_options("portal_cat_bt")
        if ec.button(t("category_export_btn"), key="portal_cat_exp_btn"):
            try:
                n = factor_system.export_category_csv(act_cat, exp_path.strip())
                ec.success(t("category_exported", count=n, path=exp_path.strip()))
            except Exception as exc:  # noqa: BLE001
                ec.error(t("category_export_failed", error=exc))
        if bc.button(t("category_backtest_btn"), key="portal_cat_bt_btn"):
            import tempfile

            from alphapilot.modules.portal import jobs as portal_jobs

            tmp = Path(tempfile.gettempdir()) / f"alphapilot_category_{safe_name}.csv"
            try:
                n = factor_system.export_category_csv(act_cat, tmp)
                if n == 0:
                    bc.warning(t("category_empty"))
                else:
                    job_kwargs = {
                        **category_backtest_kwargs,
                        "factor_path": str(tmp),
                    }
                    job = portal_jobs.start_job("factor_backtest", job_kwargs)
                    _remember_factor_backtest_job(job, job_kwargs)
                    st.rerun()
            except Exception as exc:  # noqa: BLE001
                bc.error(t("job_start_failed", error=exc))

    # ---- Validate / Add ----
    st.markdown(f"#### {t('factor_validate_heading')}")
    expr = st.text_area(
        t("expression"),
        value="",
        height=100,
        placeholder=t("expression_placeholder"),
    )
    factor_name = st.text_input(t("factor_name"), value="")
    add_cats: list[str] = []
    add_extra = ""
    if has_categories:
        add_cats = st.multiselect(
            t("factor_add_categories"), all_categories, key="portal_add_cats"
        )
        add_extra = st.text_input(
            t("factor_add_new_categories"), key="portal_add_new_cats"
        )
    c1, c2 = st.columns(2)
    if c1.button(t("check_expression")):
        try:
            result = factor_system.validate_expression(expr)
            if result.acceptable:
                st.success(t("expression_acceptable"))
            else:
                reason = format_factor_rejection(
                    result.code, result.message, result.details
                )
                st.error(t("expression_not_acceptable"))
                st.caption(reason)
            if result.details:
                with st.expander(t("factor_validation_details")):
                    st.json(result.details)
        except Exception as exc:  # noqa: BLE001
            st.error(t("check_failed", error=exc))
    if c2.button(t("add_to_factor_db")):
        try:
            new_cats = list(add_cats) + [
                c.strip() for c in add_extra.split(",") if c.strip()
            ]
            result = factor_system.add_factor(
                factor_name.strip(), expr.strip(), categories=new_cats or None
            )
            if result.acceptable:
                st.success(t("factor_added"))
                st.rerun()
            else:
                reason = format_factor_rejection(
                    result.code, result.message, result.details
                )
                st.warning(t("factor_not_added", reason=reason))
                if result.details:
                    with st.expander(t("factor_validation_details")):
                        st.json(result.details)
        except Exception as exc:  # noqa: BLE001
            st.error(t("add_failed", error=exc))

    st.markdown(f"#### {t('import_export_heading')}")
    import_kind = st.selectbox(t("import_kind"), ["csv", "json", "pdf"], index=0)
    import_source = st.text_input(t("import_source"))
    c3, c4 = st.columns(2)
    if c3.button(t("import_factors")):
        try:
            source: Any = import_source.strip()
            if import_kind == "json":
                source = json.loads(Path(source).read_text(encoding="utf-8"))
            result = factor_system.import_factors(source, kind=import_kind)
            st.success(t("factors_imported"))
            st.write(result)
        except Exception as exc:  # noqa: BLE001
            st.error(t("import_failed", error=exc))
    export_path = st.text_input(
        t("export_path"), value=str(store_path.with_suffix(".csv"))
    )
    if c4.button(t("export_factor_db")):
        try:
            factor_system.database.save(export_path.strip())
            st.success(t("exported_to", path=export_path))
        except Exception as exc:  # noqa: BLE001
            st.error(t("export_failed", error=exc))


def _render_strategy_tab(engine: Any) -> None:
    st.subheader(t("strategy_subheader"))
    strategy_system = engine.get_system("strategy")
    db = strategy_system.param_database

    strategies = db.list_strategies()
    st.write(t("stored_strategy_sets", count=len(strategies)))
    if strategies:
        selected = st.selectbox(t("select_strategy"), strategies)
        params = db.load(selected)
        st.json(params or {})
        st.markdown(f"#### {t('delete_heading')}")
        delete_strategy_confirm = st.checkbox(
            t("delete_confirm"), key="portal_delete_strategy_confirm"
        )
        if st.button(t("delete_strategy_btn"), key="portal_delete_strategy_btn"):
            if not delete_strategy_confirm:
                st.warning(t("delete_confirm"))
            else:
                try:
                    if strategy_system.delete_strategy(selected):
                        st.success(t("strategy_deleted", name=selected))
                        st.rerun()
                    else:
                        st.error(t("strategy_delete_failed", name=selected))
                except Exception as exc:  # noqa: BLE001
                    st.error(t("strategy_delete_error", error=exc))
    else:
        st.info(t("no_stored_params"))

    st.markdown(f"#### {t('save_export_heading')}")
    strategy_name = st.text_input(t("strategy_name"), value="")
    params_raw = st.text_area(t("params_json"), value="{}", height=140)
    c1, c2 = st.columns(2)
    if c1.button(t("save_params")):
        try:
            db.save(strategy_name.strip(), json.loads(params_raw))
            st.success(t("params_saved"))
        except Exception as exc:  # noqa: BLE001
            st.error(t("save_failed", error=exc))
    export_strategy_name = st.text_input(t("export_strategy_name"), value=strategy_name)
    export_strategy_path = st.text_input(t("export_file_path"), value="")
    if c2.button(t("export_params")):
        try:
            payload = db.load(export_strategy_name.strip())
            if payload is None:
                raise ValueError(t("strategy_params_not_found"))
            out = Path(export_strategy_path.strip())
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            st.success(t("params_exported", name=export_strategy_name, path=out))
        except Exception as exc:  # noqa: BLE001
            st.error(t("export_failed", error=exc))

    st.markdown(f"#### {t('import_pdf_heading')}")
    pdf_path = st.text_input(t("pdf_path"))
    if st.button(t("import_strategy_pdf")):
        try:
            result = strategy_system.import_strategy(pdf_path.strip(), kind="pdf")
            st.success(t("strategy_imported"))
            st.write(result)
        except Exception as exc:  # noqa: BLE001
            st.error(t("import_failed", error=exc))


def _render_module_hub(engine: Any) -> None:
    st.subheader(t("module_hub_subheader"))
    st.caption(t("module_hub_caption"))

    module_names = sorted(engine.modules.keys())
    if not module_names:
        st.warning(t("no_modules_loaded"))
        return

    for module_name in module_names:
        module = engine.modules[module_name]
        with st.expander(f"`{module_name}`", expanded=False):
            for command_name, command_fn in module.commands().items():
                try:
                    sig = inspect.signature(command_fn)
                except Exception:  # noqa: BLE001
                    sig = "(signature unavailable)"
                st.code(f"{command_name}{sig}", language=None)

    st.markdown(f"#### {t('run_module_command')}")
    selected_module = st.selectbox(t("module_label"), module_names)
    selected_commands = engine.modules[selected_module].commands()
    selected_command = st.selectbox(
        t("command_label"), sorted(selected_commands.keys())
    )
    selected_fn = selected_commands[selected_command]
    try:
        selected_sig: inspect.Signature | str = inspect.signature(selected_fn)
    except Exception:  # noqa: BLE001
        selected_sig = "(signature unavailable)"
    kwargs_col, help_col = st.columns([1.1, 1], vertical_alignment="top")
    with kwargs_col:
        raw_kwargs = st.text_area(
            t("command_kwargs"),
            value="{}",
            height=220,
            help=t("command_kwargs_help"),
        )
    with help_col:
        _render_command_kwargs_help(
            selected_module, selected_command, selected_fn, selected_sig
        )
    if st.button(t("run_command")):
        try:
            kwargs = _safe_json_load(raw_kwargs)
            result = selected_fn(**kwargs)
            st.success(t("command_executed"))
            st.write(result)
        except Exception as exc:  # noqa: BLE001
            st.error(t("command_failed", error=exc))


def _accepted_factors_csv(accepted: list[dict[str, Any]]) -> str:
    import pandas as pd

    return pd.DataFrame(accepted).to_csv(index=False)


def _render_alphaforge_result(summary: dict[str, Any], *, key: str) -> None:
    """Rich rendering of an AlphaForge mining summary (``emit_factors`` output).

    Shared by every method (GP / RL / AFF) since they emit the same shape:
    counts + accepted/rejected factor lists + an optional backtest block.
    """
    import pandas as pd

    source = str(summary.get("source", "alphaforge"))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric(t("af_result_mined"), summary.get("mined", "—"))
    m2.metric(
        t("af_result_accepted"),
        summary.get("n_accepted", len(summary.get("accepted") or [])),
    )
    m3.metric(
        t("af_result_rejected"),
        summary.get("n_rejected", len(summary.get("rejected") or [])),
    )
    m4.metric(t("af_result_untranslatable"), summary.get("untranslatable", "—"))
    st.caption(t("af_result_source", source=source))

    accepted = summary.get("accepted") or []
    if accepted:
        st.markdown(f"##### {t('af_result_accepted_heading')}")
        df = pd.DataFrame(accepted)
        if "score" in df.columns:
            df["_abs"] = pd.to_numeric(df["score"], errors="coerce").abs()
            df = df.sort_values("_abs", ascending=False, na_position="last").drop(
                columns="_abs"
            )
        ordered = [c for c in ("name", "score", "dsl") if c in df.columns]
        df = df[ordered + [c for c in df.columns if c not in ordered]].reset_index(
            drop=True
        )
        df.insert(0, "#", range(1, len(df) + 1))
        st.dataframe(df, width="stretch", hide_index=True)
        st.download_button(
            t("af_result_download"),
            data=_accepted_factors_csv(accepted),
            file_name=f"{source}_accepted.csv",
            mime="text/csv",
            key=f"af_dl_{key}",
        )
    else:
        st.info(t("af_result_no_accepted"))

    rejected = summary.get("rejected") or []
    if rejected:
        with st.expander(
            t("af_result_rejected_heading", count=len(rejected)), expanded=False
        ):
            rdf = pd.DataFrame(rejected)
            ordered = [c for c in ("name", "code", "reason", "dsl") if c in rdf.columns]
            rdf = rdf[ordered + [c for c in rdf.columns if c not in ordered]]
            st.dataframe(rdf, width="stretch", hide_index=True)

    backtest = summary.get("backtest")
    if isinstance(backtest, dict):
        st.markdown(f"##### {t('af_result_backtest_heading')}")
        if backtest.get("ok"):
            metrics = backtest.get("metrics")
            if isinstance(metrics, dict) and metrics:
                st.dataframe(
                    pd.DataFrame(
                        [{"metric": k, "value": v} for k, v in metrics.items()]
                    ),
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.success(t("af_result_backtest_ok"))
        else:
            st.error(t("af_result_backtest_failed", error=backtest.get("error", "")))


def _render_portal_jobs_panel(key_prefix: str) -> None:
    from alphapilot.modules.portal import jobs as portal_jobs

    st.markdown(f"#### {t('jobs_heading')}")
    st.caption(t("jobs_caption"))
    cols = st.columns([1, 1, 2])
    if cols[0].button(t("jobs_refresh"), key=f"{key_prefix}_jobs_refresh"):
        st.rerun()
    if cols[1].button(
        t("jobs_clear_finished"), key=f"{key_prefix}_jobs_clear_finished"
    ):
        removed = portal_jobs.clear_finished_jobs()
        st.success(t("jobs_cleared", n=removed))
        st.rerun()
    cols[2].text_input(
        t("jobs_root"),
        value=str(portal_jobs.default_job_root()),
        disabled=True,
        key=f"{key_prefix}_jobs_root",
    )

    jobs = portal_jobs.list_jobs()
    if not jobs:
        st.info(t("jobs_empty"))
        return

    rows = [
        {
            "job_id": job.get("job_id"),
            "kind": job.get("kind"),
            "status": job.get("status"),
            "pid": job.get("pid"),
            "started_at": job.get("started_at") or job.get("created_at"),
            "finished_at": job.get("finished_at"),
            "summary": job.get("result_summary") or job.get("error") or "",
        }
        for job in jobs
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    selected_id = st.selectbox(
        t("jobs_select"),
        [job["job_id"] for job in jobs],
        format_func=lambda job_id: _format_job_label(
            next(j for j in jobs if j["job_id"] == job_id)
        ),
        key=f"{key_prefix}_jobs_select",
    )
    selected = next(job for job in jobs if job["job_id"] == selected_id)
    st.json(selected, expanded=False)
    if selected.get("status") == "succeeded":
        st.success(t("jobs_finished_hint"))
    elif selected.get("status") in {"failed", "lost"}:
        st.error(t("jobs_failed_hint"))

    is_running = selected.get("status") == "running"
    if is_running:
        if st.button(t("jobs_cancel"), key=f"{key_prefix}_jobs_cancel_{selected_id}"):
            try:
                portal_jobs.cancel_job(selected_id)
                st.warning(t("jobs_cancelled", job_id=selected_id))
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(t("jobs_cancel_failed", error=exc))

    del_cols = st.columns([2, 1], vertical_alignment="bottom")
    confirm_delete = del_cols[0].checkbox(
        t("jobs_delete_confirm"),
        key=f"{key_prefix}_jobs_delete_confirm_{selected_id}",
        disabled=is_running,
    )
    if del_cols[1].button(
        t("jobs_delete"),
        key=f"{key_prefix}_jobs_delete_{selected_id}",
        disabled=is_running,
        width="stretch",
    ):
        if not confirm_delete:
            st.warning(t("jobs_delete_confirm"))
        else:
            try:
                portal_jobs.delete_job(selected_id)
                st.success(t("jobs_deleted", job_id=selected_id))
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(t("jobs_delete_failed", error=exc))
    if is_running:
        st.caption(t("jobs_delete_running_hint"))

    log_tail = portal_jobs.read_log_tail(selected_id)
    with st.expander(t("jobs_log_tail"), expanded=True):
        st.code(log_tail or t("jobs_log_empty"), language=None)

    result = portal_jobs.read_result(selected_id)
    if result is not None:
        payload = result.get("result") if isinstance(result, dict) else None
        if selected.get("kind") in _ALPHAFORGE_METHODS and isinstance(payload, dict):
            st.markdown(f"#### {t('af_result_title')}")
            _render_alphaforge_result(payload, key=selected_id)
            with st.expander(t("jobs_result_raw"), expanded=False):
                st.json(result)
        else:
            with st.expander(t("jobs_result"), expanded=False):
                st.json(result)


def _format_job_label(job: dict[str, Any]) -> str:
    return f"{job.get('job_id')} [{job.get('kind')} / {job.get('status')}]"


def _render_mine_launcher() -> None:
    from alphapilot.modules.portal import jobs as portal_jobs

    st.markdown(f"#### {t('mine_start_heading')}")
    st.info(t("jobs_resource_warning"))
    with st.form("portal_mine_start_form"):
        c1, c2 = st.columns(2)
        step_n = c1.number_input(
            t("mine_step_n"), min_value=1, max_value=1000, value=1, step=1
        )
        scenario = c2.text_input(t("mine_scenario"), value="alpha_factor_mining")
        direction = st.text_area(t("mine_direction"), value="", height=90)
        with st.expander(t("advanced_options"), expanded=False):
            path = st.text_input(t("mine_resume_path"), value="")
            qlib_config_name = st.text_input(
                t("qlib_config_name"), value="", key="mine_qlib_config"
            )
            qlib_template_dir = st.text_input(
                t("qlib_template_dir"), value="", key="mine_qlib_template"
            )
        submitted = st.form_submit_button(t("mine_start_btn"), type="primary")

    if submitted:
        kwargs = _nonempty_kwargs(
            {
                "step_n": int(step_n),
                "scenario": scenario,
                "direction": direction,
                "path": path,
                "qlib_config_name": qlib_config_name,
                "qlib_template_dir": qlib_template_dir,
            }
        )
        try:
            job = portal_jobs.start_job("mine", kwargs)
            st.success(t("job_started", job_id=job["job_id"]))
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(t("job_start_failed", error=exc))


_ALPHAFORGE_METHODS = ["mine_gp", "mine_rl", "mine_aff"]


def _render_alphaforge_launcher(engine: Any) -> None:
    """LLM-free formulaic alpha mining (AlphaForge: GP / RL / AFF)."""
    from alphapilot.modules.portal import jobs as portal_jobs

    st.markdown(f"#### {t('af_start_heading')}")
    st.caption(t("af_start_caption"))
    st.info(t("jobs_resource_warning"))

    # Method picker lives OUTSIDE the form so the per-method fields re-render
    # immediately when it changes (in-form widgets don't rerun until submit).
    method = st.selectbox(
        t("af_method"),
        _ALPHAFORGE_METHODS,
        format_func=lambda m: t(f"af_method_{m}"),
        key="af_method",
    )
    instrument_sets = _available_instrument_sets(engine)

    with st.form("portal_alphaforge_form"):
        if instrument_sets:
            default_idx = (
                instrument_sets.index("test_stock_pool_80")
                if "test_stock_pool_80" in instrument_sets
                else 0
            )
            instruments = st.selectbox(
                t("af_instruments"),
                instrument_sets,
                index=default_idx,
                key="af_instruments",
            )
        else:
            instruments = st.text_input(
                t("af_instruments"),
                value="test_stock_pool_80",
                key="af_instruments_text",
            )
            st.caption(t("af_instruments_hint"))

        c1, c2, c3 = st.columns(3)
        train_end_year = c1.number_input(
            t("af_train_end_year"), min_value=2000, max_value=2100, value=2020, step=1
        )
        device = c2.selectbox(
            t("af_device"), ["auto", "cpu", "mps", "cuda"], index=0, key="af_device"
        )
        seed = c3.number_input(
            t("af_seed"), min_value=0, max_value=10_000_000, value=0, step=1
        )

        method_kwargs: dict[str, Any] = {}
        if method == "mine_aff":
            st.caption(t("af_aff_note"))
            a1, a2 = st.columns(2)
            method_kwargs["zoo_size"] = int(
                a1.number_input(
                    t("af_zoo_size"), min_value=1, max_value=10_000, value=100, step=1
                )
            )
            method_kwargs["ic_thresh"] = float(
                a2.number_input(
                    t("af_ic_thresh"),
                    min_value=0.0,
                    max_value=1.0,
                    value=0.03,
                    step=0.01,
                    format="%.3f",
                )
            )
            a3, a4 = st.columns(2)
            method_kwargs["corr_thresh"] = float(
                a3.number_input(
                    t("af_corr_thresh"),
                    min_value=0.0,
                    max_value=1.0,
                    value=0.7,
                    step=0.05,
                    format="%.2f",
                )
            )
            method_kwargs["icir_thresh"] = float(
                a4.number_input(
                    t("af_icir_thresh"),
                    min_value=0.0,
                    max_value=10.0,
                    value=0.1,
                    step=0.05,
                    format="%.2f",
                )
            )
        elif method == "mine_gp":
            g1, g2 = st.columns(2)
            method_kwargs["population_size"] = int(
                g1.number_input(
                    t("af_population_size"),
                    min_value=10,
                    max_value=100_000,
                    value=200,
                    step=10,
                )
            )
            method_kwargs["generations"] = int(
                g2.number_input(
                    t("af_generations"), min_value=1, max_value=1000, value=10, step=1
                )
            )
        elif method == "mine_rl":
            r1, r2 = st.columns(2)
            method_kwargs["steps"] = int(
                r1.number_input(
                    t("af_steps"),
                    min_value=1000,
                    max_value=10_000_000,
                    value=50_000,
                    step=1000,
                )
            )
            method_kwargs["pool_capacity"] = int(
                r2.number_input(
                    t("af_pool_capacity"), min_value=1, max_value=200, value=10, step=1
                )
            )

        s1, s2 = st.columns(2)
        save = s1.checkbox(t("af_save"), value=True, key="af_save")
        backtest = s2.checkbox(t("af_backtest"), value=False, key="af_backtest")

        with st.expander(t("advanced_options"), expanded=False):
            qlib_dir = st.text_input(t("af_qlib_dir"), value="", key="af_qlib_dir")
            freq = st.text_input(t("af_freq"), value="day", key="af_freq")
            extra_col, extra_help_col = st.columns([1.1, 1], vertical_alignment="top")
            with extra_col:
                raw_kwargs = st.text_area(
                    t("af_advanced_kwargs"),
                    value="{}",
                    height=150,
                    help=t("af_advanced_kwargs_help"),
                )
            with extra_help_col:
                _render_alphaforge_extra_kwargs_help(method)

        submitted = st.form_submit_button(t("af_start_btn"), type="primary")

    if submitted:
        try:
            kwargs: dict[str, Any] = {
                "instruments": str(instruments).strip(),
                "train_end_year": int(train_end_year),
                "seed": int(seed),
                "freq": freq.strip() or "day",
                "save": bool(save),
                "backtest": bool(backtest),
                **method_kwargs,
            }
            if device != "auto":
                kwargs["device"] = device
            if qlib_dir.strip():
                kwargs["qlib_dir"] = qlib_dir.strip()
            kwargs.update(_safe_json_load(raw_kwargs))
            job = portal_jobs.start_job(method, kwargs)
            st.success(t("job_started", job_id=job["job_id"]))
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(t("job_start_failed", error=exc))


def _render_mine_log_tab(engine: Any) -> None:
    from alphapilot.log.ui.panel import render_log_ui_panel

    llm_tab, af_tab = st.tabs([t("mine_tab_llm"), t("mine_tab_alphaforge")])
    with llm_tab:
        _render_mine_launcher()
    with af_tab:
        _render_alphaforge_launcher(engine)
    st.divider()
    _render_portal_jobs_panel("portal_mine")
    st.divider()
    mining_module = engine.get_module("alpha_mining")
    render_log_ui_panel(
        log_dir=engine.config.log_dir,
        translate=t,
        use_sidebar=False,
        show_heading=True,
        key_prefix="portal_log",
        delete_session_fn=mining_module.delete_mining_session,
    )


def _render_data_viz_tab() -> None:
    from alphapilot.modules.data_viz.panel import render_data_viz_panel

    render_data_viz_panel(
        translate=t,
        use_sidebar=False,
        show_heading=True,
        key_prefix="portal_dv",
    )


def _render_backtest_launcher(engine: Any) -> None:
    from alphapilot.modules.portal import jobs as portal_jobs

    st.markdown(f"#### {t('bt_start_heading')}")
    st.info(t("jobs_resource_warning"))
    _render_factor_backtest_notice()
    factor_tab, strategy_tab = st.tabs(
        [t("bt_start_factor_csv"), t("bt_start_strategy_asset")]
    )

    with factor_tab:
        with st.form("portal_factor_backtest_form"):
            factor_path = st.text_input(t("factor_path"), value="")
            backtest_kwargs = _render_factor_backtest_options("factor_bt")
            submitted = st.form_submit_button(t("bt_start_factor_btn"), type="primary")
        if submitted:
            if not factor_path.strip():
                st.warning(t("factor_path_required"))
            else:
                kwargs = {**backtest_kwargs, "factor_path": factor_path.strip()}
                try:
                    job = portal_jobs.start_job("factor_backtest", kwargs)
                    _remember_factor_backtest_job(job, kwargs)
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(t("job_start_failed", error=exc))

    with strategy_tab:
        strategies = _safe_metric(
            lambda: engine.get_system("strategy").param_database.list_strategies(),
            default=[],
        )
        with st.form("portal_strategy_backtest_form"):
            if isinstance(strategies, list) and strategies:
                strategy_name = st.selectbox(
                    t("strategy_name"), strategies, key="bt_strategy_name_select"
                )
            else:
                strategy_name = st.text_input(
                    t("strategy_name"), value="", key="bt_strategy_name_text"
                )
                st.caption(t("no_stored_params"))
            c1, c2 = st.columns(2)
            mode = c1.selectbox(
                t("bt_strategy_mode"), ["retrain", "reuse_model"], index=0
            )
            scenario = c2.text_input(
                t("bt_scenario"), value="factor_backtest", key="strategy_bt_scenario"
            )
            qlib_data_dir = st.text_input(
                t("qlib_data_dir"), value="", key="strategy_bt_qlib_data"
            )
            qlib_config_name = st.text_input(
                t("qlib_config_name"), value="", key="strategy_bt_qlib_config"
            )
            qlib_template_dir = st.text_input(
                t("qlib_template_dir"), value="", key="strategy_bt_qlib_template"
            )
            run_tag = st.text_input(
                t("bt_run_tag"), value="", key="strategy_bt_run_tag"
            )
            submitted = st.form_submit_button(
                t("bt_start_strategy_btn"), type="primary"
            )
        if submitted:
            if not str(strategy_name).strip():
                st.warning(t("strategy_name_required"))
            else:
                kwargs = _nonempty_kwargs(
                    {
                        "strategy_name": strategy_name,
                        "mode": mode,
                        "scenario": scenario,
                        "qlib_data_dir": qlib_data_dir,
                        "qlib_config_name": qlib_config_name,
                        "qlib_template_dir": qlib_template_dir,
                        "run_tag": run_tag,
                    }
                )
                try:
                    job = portal_jobs.start_job("strategy_backtest", kwargs)
                    st.success(t("job_started", job_id=job["job_id"]))
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(t("job_start_failed", error=exc))


def _render_backtest_tab(engine: Any) -> None:
    st.subheader(t("backtest_subheader"))
    tab_start, tab_list, tab_detail = st.tabs(
        [t("bt_tab_start"), t("bt_tab_runs"), t("bt_tab_detail")]
    )
    with tab_start:
        _render_backtest_launcher(engine)
        st.divider()
        _render_portal_jobs_panel("portal_bt")
    with tab_list:
        backtest_system = engine.get_system("backtest")
        st.text_input(
            t("workspace_root"),
            value=str(engine.config.backtest.workspace_root),
            disabled=True,
            key="portal_bt_workspace_root",
        )
        try:
            runs = backtest_system.results.list_runs()
            st.success(t("backtest_runs_found", count=len(runs)))
            if runs:
                workspace_ids = [p.name for p in runs[:500]]
                st.dataframe(
                    {"workspace": workspace_ids}, width="stretch", hide_index=True
                )
                st.markdown(f"#### {t('delete_heading')}")
                delete_workspace_id = st.selectbox(
                    t("select_backtest_workspace"),
                    workspace_ids,
                    key="portal_delete_backtest_ws",
                )
                delete_backtest_confirm = st.checkbox(
                    t("delete_confirm"), key="portal_delete_backtest_confirm"
                )
                if st.button(
                    t("delete_backtest_btn"), key="portal_delete_backtest_btn"
                ):
                    if not delete_backtest_confirm:
                        st.warning(t("delete_confirm"))
                    else:
                        try:
                            if backtest_system.delete_workspace(delete_workspace_id):
                                st.success(
                                    t("backtest_deleted", name=delete_workspace_id)
                                )
                                st.rerun()
                            else:
                                st.error(
                                    t(
                                        "backtest_delete_failed",
                                        name=delete_workspace_id,
                                    )
                                )
                        except Exception as exc:  # noqa: BLE001
                            st.error(t("backtest_delete_error", error=exc))
        except Exception as exc:  # noqa: BLE001
            st.error(t("list_runs_failed", error=exc))
    with tab_detail:
        from alphapilot.modules.backtest_viz.panel import render_backtest_panel

        render_backtest_panel(
            workspace_root=engine.config.backtest.workspace_root,
            log_root=engine.config.log_dir,
            translate=t,
            use_sidebar=False,
            show_heading=False,
            key_prefix="portal_bt",
            load_fn=backtest_system.results.load,
        )


def _render_library(engine: Any) -> None:
    """Factor + strategy asset management under one page."""
    tab_factor, tab_strategy = st.tabs([t("lib_tab_factor"), t("lib_tab_strategy")])
    with tab_factor:
        _render_factor_tab(engine)
    with tab_strategy:
        _render_strategy_tab(engine)


def _render_market_data(engine: Any) -> None:
    """Data download / management + K-line viewer under one page."""
    tab_manage, tab_kline = st.tabs([t("market_tab_manage"), t("market_tab_kline")])
    with tab_manage:
        _render_data_tab(engine)
    with tab_kline:
        _render_data_viz_tab()


def _render_advanced(engine: Any) -> None:
    """Developer surfaces: runtime info, system/module overview, command runner."""
    st.subheader(t("advanced_subheader"))
    st.caption(t("advanced_caption"))
    c1, c2, c3 = st.columns(3)
    c1.metric(t("metric_systems"), len(engine.systems))
    c2.metric(t("metric_modules"), len(engine.modules))
    c3.metric(t("metric_module_commands"), len(engine.collect_commands()))
    with st.expander(t("sidebar_runtime"), expanded=False):
        st.code(engine.config.summary(), language=None)
        if st.button(t("sidebar_reload"), key="advanced_reload"):
            st.cache_resource.clear()
            st.rerun()
    st.divider()
    _render_overview(engine)
    st.divider()
    _render_module_hub(engine)


def _render_schedule_form(sched: Any) -> None:
    """Create-schedule form: friendly per-kind fields + advanced JSON override."""
    import json as _json
    from datetime import time as _dt_time

    from alphapilot.modules.portal import jobs as portal_jobs

    name = st.text_input(t("sched_name"), key="sched_new_name")
    kind = st.selectbox(
        t("sched_kind"),
        list(sched.SCHEDULE_KINDS),
        format_func=lambda k: t(f"sched_kind_{k}"),
        key="sched_new_kind",
    )
    tcol1, tcol2 = st.columns([1, 1], vertical_alignment="bottom")
    run_time = tcol1.time_input(
        t("sched_time"), value=_dt_time(7, 30), key="sched_new_time"
    )
    enabled = tcol2.checkbox(t("sched_enabled"), value=True, key="sched_new_enabled")
    notify_done = st.checkbox(t("sched_notify"), value=False, key="sched_new_notify")

    kwargs: dict[str, Any] = {}
    if kind == "data":
        kwargs["action"] = st.selectbox(
            t("sched_data_action"),
            list(portal_jobs.DATA_ACTIONS),
            key="sched_new_data_action",
        )
        kwargs["source"] = st.selectbox(
            t("data_source"), ["baostock_cn", "tushare_cn"], key="sched_new_data_source"
        )
        dcol1, dcol2 = st.columns(2)
        start_date = dcol1.text_input(t("sched_start_date"), key="sched_new_start")
        end_date = dcol2.text_input(t("sched_end_date"), key="sched_new_end")
        stock_csv = st.text_input(t("sched_stock_csv"), key="sched_new_csv")
        token = st.text_input(
            t("tushare_token"), "", type="password", key="sched_new_token"
        )
        if start_date.strip():
            kwargs["start_date"] = start_date.strip()
        if end_date.strip():
            kwargs["end_date"] = end_date.strip()
        if stock_csv.strip():
            kwargs["stock_csv"] = stock_csv.strip()
        if token.strip():
            kwargs["token"] = token.strip()
    elif kind == "mine":
        steps = st.number_input(
            t("sched_step_n"), min_value=0, value=0, step=1, key="sched_new_mine_step"
        )
        if int(steps) > 0:
            kwargs["step_n"] = int(steps)
        scenario = st.text_input(
            t("sched_scenario"), value="alpha_factor_mining", key="sched_new_mine_scn"
        )
        if scenario.strip():
            kwargs["scenario"] = scenario.strip()
        tmpl = st.text_input(t("sched_qlib_template_dir"), key="sched_new_mine_tmpl")
        if tmpl.strip():
            kwargs["qlib_template_dir"] = tmpl.strip()
    elif kind == "factor_backtest":
        steps = st.number_input(
            t("sched_step_n"), min_value=0, value=0, step=1, key="sched_new_bt_step"
        )
        if int(steps) > 0:
            kwargs["step_n"] = int(steps)
        factor_path = st.text_input(t("sched_factor_path"), key="sched_new_bt_fp")
        if factor_path.strip():
            kwargs["factor_path"] = factor_path.strip()
        tmpl = st.text_input(t("sched_qlib_template_dir"), key="sched_new_bt_tmpl")
        if tmpl.strip():
            kwargs["qlib_template_dir"] = tmpl.strip()

    advanced = st.text_area(
        t("sched_advanced_kwargs"),
        value="",
        key="sched_new_adv",
        help=t("sched_advanced_help"),
    )
    if advanced.strip():
        try:
            extra = _json.loads(advanced)
        except Exception:  # noqa: BLE001
            st.warning(t("sched_advanced_invalid"))
            return
        if not isinstance(extra, dict):
            st.warning(t("sched_advanced_invalid"))
            return
        kwargs.update(extra)

    if notify_done:
        kwargs["notify"] = True  # control key consumed by the job worker

    if st.button(t("sched_create_btn"), key="sched_new_submit", type="primary"):
        if not name.strip():
            st.warning(t("sched_name_required"))
            return
        try:
            sched.create_schedule(
                name=name.strip(),
                kind=kind,
                time=run_time.strftime("%H:%M"),
                kwargs=kwargs,
                enabled=enabled,
            )
            st.success(t("sched_created", name=name.strip()))
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(t("sched_create_failed", error=exc))


def _render_schedule_row(sched: Any, s: dict[str, Any]) -> None:
    sid = s["schedule_id"]
    with st.container(border=True):
        cols = st.columns([3, 1, 1, 1], vertical_alignment="center")
        next_run = (
            sched.next_run_at(s).strftime("%Y-%m-%d %H:%M") if s.get("enabled") else "—"
        )
        cols[0].markdown(
            f"**{s.get('name')}** · `{t('sched_kind_' + s['kind'])}` · ⏰ {s.get('time')}\n\n"
            f"{t('sched_next_run')}: {next_run} · {t('sched_last_run')}: {s.get('last_run_date') or '—'}"
        )
        new_enabled = cols[1].toggle(
            t("sched_enabled"), value=bool(s.get("enabled")), key=f"sched_en_{sid}"
        )
        if new_enabled != bool(s.get("enabled")):
            sched.set_enabled(sid, new_enabled)
            st.rerun()
        if cols[2].button(t("sched_run_now"), key=f"sched_run_{sid}", width="stretch"):
            try:
                job = sched.run_now(sid)
                st.success(t("sched_ran_now", job_id=job.get("job_id")))
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(t("sched_run_failed", error=exc))
        if cols[3].button(t("sched_delete"), key=f"sched_del_{sid}", width="stretch"):
            st.session_state[f"sched_confirm_{sid}"] = True
        if st.session_state.get(f"sched_confirm_{sid}"):
            dc1, dc2 = st.columns([3, 1], vertical_alignment="center")
            dc1.warning(t("sched_delete_confirm"))
            if dc2.button(
                t("sched_delete_yes"), key=f"sched_delyes_{sid}", width="stretch"
            ):
                try:
                    sched.delete_schedule(sid)
                finally:
                    st.session_state.pop(f"sched_confirm_{sid}", None)
                st.rerun()
        with st.expander(t("sched_params"), expanded=False):
            st.json(s.get("kwargs") or {})


def _render_scheduler_page() -> None:
    """Daily scheduler: manage the daemon and the saved task schedules."""
    from alphapilot.modules.portal import schedules as sched

    st.header(f"⏰ {t('sched_title')}")
    st.caption(t("sched_caption"))

    status = sched.daemon_status()
    with st.container(border=True):
        c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="center")
        if status["running"] and not status["stale"]:
            c1.success(
                t("sched_daemon_running", pid=status["pid"], hb=status["heartbeat_at"])
            )
        elif status["running"] and status["stale"]:
            c1.warning(t("sched_daemon_stale", pid=status["pid"]))
        else:
            c1.error(t("sched_daemon_stopped"))
        running_ok = bool(status["running"]) and not status["stale"]
        if c2.button(
            t("sched_daemon_start"),
            key="sched_daemon_start",
            disabled=running_ok,
            width="stretch",
        ):
            sched.start_daemon()
            st.rerun()
        if c3.button(
            t("sched_daemon_stop"),
            key="sched_daemon_stop",
            disabled=not status["running"],
            width="stretch",
        ):
            sched.stop_daemon()
            st.rerun()
        st.caption(t("sched_daemon_hint"))

    with st.expander(f"➕ {t('sched_create')}", expanded=False):
        _render_schedule_form(sched)

    st.markdown(f"#### {t('sched_list_heading')}")
    rows = sched.list_schedules()
    if not rows:
        st.info(t("sched_empty"))
        return
    for s in rows:
        _render_schedule_row(sched, s)


def _render_notify_page() -> None:
    """Configure notification channels (email / Feishu / Telegram) + test send."""
    from alphapilot.systems import notify as notify_pkg

    st.header(f"📣 {t('notify_title')}")
    st.caption(t("notify_caption"))

    cfg = notify_pkg.load_file_config()
    configured = notify_pkg.configured_channel_names()
    if configured:
        st.success(t("notify_active", channels=", ".join(configured)))
    else:
        st.info(t("notify_none"))
    st.caption(t("notify_path", path=notify_pkg.credentials_path()))

    new_cfg: dict[str, Any] = {
        ch: dict(cfg.get(ch, {})) for ch in notify_pkg.CHANNEL_FIELDS
    }
    new_cfg["options"] = {
        "notify_on_all_jobs": st.checkbox(
            t("notify_on_all_jobs"),
            value=bool(cfg.get("options", {}).get("notify_on_all_jobs", False)),
            key="notify_opt_all",
        )
    }

    for ch, fields in notify_pkg.CHANNEL_FIELDS.items():
        with st.expander(t(f"notify_ch_{ch}"), expanded=False):
            for name, ftype in fields:
                key = f"notify_{ch}_{name}"
                cur = cfg.get(ch, {}).get(name)
                label = name.replace("_", " ")
                if ftype == "bool":
                    new_cfg[ch][name] = st.checkbox(label, value=bool(cur), key=key)
                elif ftype == "int":
                    new_cfg[ch][name] = st.number_input(
                        label, value=int(cur or 0), step=1, key=key
                    )
                elif ftype == "secret":
                    new_cfg[ch][name] = st.text_input(
                        label, value=str(cur or ""), type="password", key=key
                    )
                elif ftype == "list":
                    raw = ", ".join(cur) if isinstance(cur, list) else str(cur or "")
                    new_cfg[ch][name] = st.text_input(
                        f"{label} (a, b, c)", value=raw, key=key
                    )
                else:
                    new_cfg[ch][name] = st.text_input(
                        label, value=str(cur or ""), key=key
                    )

    if st.button(t("notify_save"), type="primary", key="notify_save"):
        notify_pkg.save_notify_config(new_cfg)
        st.success(t("notify_saved", path=notify_pkg.credentials_path()))
        st.rerun()

    st.markdown(f"#### {t('notify_test_heading')}")
    st.caption(t("notify_test_hint"))
    test_cols = st.columns(len(notify_pkg.CHANNEL_FIELDS) + 1)
    if test_cols[0].button(
        t("notify_test_all"), key="notify_test_all", width="stretch"
    ):
        st.write(notify_pkg.test_send())
    for i, ch in enumerate(notify_pkg.CHANNEL_FIELDS, start=1):
        if test_cols[i].button(ch, key=f"notify_test_{ch}", width="stretch"):
            st.write(notify_pkg.test_send(ch))


def _render_home(engine: Any) -> None:
    """Trader-facing landing page: status at a glance + quick actions."""
    pages = st.session_state.get("_nav_pages", {})
    st.title(t("header_title"))
    st.caption(t("home_caption"))

    data_system = engine.get_system("data")
    factor_system = engine.get_system("factor")
    strategy_system = engine.get_system("strategy")
    backtest_system = engine.get_system("backtest")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        t("home_metric_symbols"),
        _safe_metric(
            lambda: len(
                {s for syms in data_system.list_symbols().values() for s in syms}
            )
        ),
    )
    c2.metric(
        t("home_metric_factors"),
        _safe_metric(lambda: len(factor_system.list_factors())),
    )
    c3.metric(
        t("home_metric_strategies"),
        _safe_metric(lambda: len(strategy_system.param_database.list_strategies())),
    )
    runs = _safe_metric(lambda: list(backtest_system.results.list_runs()), default=[])
    c4.metric(t("home_metric_backtests"), len(runs) if isinstance(runs, list) else "—")
    if isinstance(runs, list) and runs:
        try:
            latest = max(runs, key=lambda p: p.stat().st_mtime).name
            st.caption(t("home_latest_backtest", name=latest))
        except Exception:  # noqa: BLE001
            pass

    st.divider()
    st.markdown(f"#### 🔬 {t('home_recent_mining')}")
    sessions = _recent_mining_sessions(engine.config.log_dir)
    if sessions:
        for name in sessions:
            st.write(f"- `{name}`")
    else:
        st.info(t("home_no_mining"))
    if pages.get("mining") and st.button(
        f"🔬 {t('home_go_mining')}",
        type="primary",
        width="stretch",
        key="home_go_mining",
    ):
        st.switch_page(pages["mining"])

    st.divider()
    st.markdown(f"#### {t('home_quick_actions')}")
    q1, q2, q3 = st.columns(3)
    if pages.get("market") and q1.button(
        f"📈 {t('home_go_data')}", width="stretch", key="home_go_data"
    ):
        st.switch_page(pages["market"])
    if pages.get("backtest") and q2.button(
        f"📊 {t('home_go_backtest')}", width="stretch", key="home_go_backtest"
    ):
        st.switch_page(pages["backtest"])
    if pages.get("library") and q3.button(
        f"📚 {t('home_go_library')}", width="stretch", key="home_go_library"
    ):
        st.switch_page(pages["library"])


def _page_home() -> None:
    _render_home(_load_engine())


def _page_mining() -> None:
    _render_mine_log_tab(_load_engine())


def _page_backtest() -> None:
    _render_backtest_tab(_load_engine())


def _page_library() -> None:
    _render_library(_load_engine())


def _page_market() -> None:
    _render_market_data(_load_engine())


def _page_advanced() -> None:
    _render_advanced(_load_engine())


def _page_scheduler() -> None:
    _render_scheduler_page()


def _page_notify() -> None:
    _render_notify_page()


def _render_daily_trade(engine: Any) -> None:
    from alphapilot.modules.portal import jobs as portal_jobs

    st.markdown(f"#### {t('daily_trade_heading')}")
    st.info(t("daily_trade_caption"))

    try:
        strategies = list(
            engine.get_system("strategy").param_database.list_strategies()
        )
    except Exception:  # noqa: BLE001
        strategies = []

    with st.form("portal_daily_trade_form"):
        use_asset = st.checkbox(t("daily_trade_use_asset"), value=bool(strategies))
        strategy_name = (
            st.selectbox(t("strategy_name"), strategies)
            if strategies
            else st.text_input(t("strategy_name"), value="")
        )
        c1, c2 = st.columns(2)
        date = c1.text_input(t("daily_trade_date"), value="", placeholder="YYYY-MM-DD")
        init_cash = c2.text_input(t("daily_trade_init_cash"), value="")
        state_path = st.text_input(t("daily_trade_state_path"), value="")
        with st.expander(t("daily_trade_manual"), expanded=not strategies):
            factor_path = st.text_input(
                t("factor_path"), value="", key="daily_factor_path"
            )
            model_pickle_path = st.text_input(t("daily_trade_model_pkl"), value="")
            yaml_params = st.text_area(
                t("bt_yaml_params_json"), value="", height=100, key="daily_yaml"
            )
        refresh_data = st.checkbox(t("daily_trade_refresh"), value=False)
        submitted = st.form_submit_button(t("daily_trade_btn"), type="primary")

    if submitted:
        kwargs: dict[str, Any] = {}
        if use_asset and strategy_name.strip():
            kwargs["strategy_name"] = strategy_name.strip()
        if factor_path.strip():
            kwargs["factor_path"] = factor_path.strip()
        if model_pickle_path.strip():
            kwargs["model_pickle_path"] = model_pickle_path.strip()
        if yaml_params.strip():
            kwargs["yaml_params"] = yaml_params
        if date.strip():
            kwargs["date"] = date.strip()
        if state_path.strip():
            kwargs["state_path"] = state_path.strip()
        if init_cash.strip():
            try:
                kwargs["init_cash"] = float(init_cash)
            except ValueError:
                st.warning(t("daily_trade_bad_cash"))
                return
        if refresh_data:
            kwargs["refresh_data"] = True

        if "strategy_name" not in kwargs and "model_pickle_path" not in kwargs:
            st.warning(t("daily_trade_need_source"))
            return
        try:
            job = portal_jobs.start_job("daily_signals", kwargs)
            st.success(t("job_started", job_id=job["job_id"]))
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(t("job_start_failed", error=exc))


def _page_daily_trade() -> None:
    _render_daily_trade(_load_engine())


def main() -> None:
    with st.spinner(t("loading_engine")):
        _load_engine()
    language_selector()

    home_page = st.Page(_page_home, title=t("page_home"), icon="🏠", default=True)
    mining_page = st.Page(_page_mining, title=t("page_mining"), icon="🔬")
    backtest_page = st.Page(_page_backtest, title=t("page_backtest"), icon="📊")
    library_page = st.Page(_page_library, title=t("page_library"), icon="📚")
    market_page = st.Page(_page_market, title=t("page_market"), icon="📈")
    daily_trade_page = st.Page(_page_daily_trade, title=t("page_daily_trade"), icon="🧾")
    scheduler_page = st.Page(_page_scheduler, title=t("page_scheduler"), icon="⏰")
    notify_page = st.Page(_page_notify, title=t("page_notify"), icon="📣")
    advanced_page = st.Page(_page_advanced, title=t("page_advanced"), icon="⚙️")

    # Stash page handles before nav.run() so the Home page can st.switch_page() to them.
    st.session_state["_nav_pages"] = {
        "home": home_page,
        "mining": mining_page,
        "backtest": backtest_page,
        "library": library_page,
        "market": market_page,
        "daily_trade": daily_trade_page,
        "scheduler": scheduler_page,
        "notify": notify_page,
        "advanced": advanced_page,
    }

    st.navigation(
        {
            t("nav_group_overview"): [home_page],
            t("nav_group_data"): [market_page],
            t("nav_group_research"): [mining_page, backtest_page, library_page],
            t("nav_group_automation"): [daily_trade_page, scheduler_page, notify_page],
            t("nav_group_system"): [advanced_page],
        }
    ).run()


if __name__ == "__main__":
    main()
