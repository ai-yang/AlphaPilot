"""Factor evaluation data paths (h5) shared by backtest and alpha_mining."""

from __future__ import annotations

import io
import re
import shutil
import sys
from pathlib import Path

import pandas as pd
from jinja2 import Environment, StrictUndefined

from alphapilot.components.coder.factor_coder.config import FACTOR_COSTEER_SETTINGS
from alphapilot.log import logger
from alphapilot.utils.env import QTDockerEnv


def _alphapilot_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_factor_data_template_dir() -> Path:
    """Built-in template folder used to bootstrap ``daily_pv*.h5`` for factor coding."""
    return _alphapilot_root() / "modules/alpha_mining/qlib/experiment/factor_data_template"


def generate_data_folder_from_qlib(
    use_local: bool = True,
    *,
    template_path: Path | None = None,
) -> None:
    template_path = (template_path or default_factor_data_template_dir()).resolve()

    logger.info(f"在{'本地' if use_local else 'Docker容器'}中生成因子数据 -> {template_path}")
    if use_local:
        from alphapilot.systems.data.generate_h5 import generate_daily_pv_h5

        generate_daily_pv_h5(output_dir=template_path)
    else:
        qtde = QTDockerEnv(is_local=False)
        qtde.prepare()
        out = str(template_path).replace("\\", "\\\\")
        entry = (
            f'{sys.executable} -c "from alphapilot.systems.data.generate_h5 import '
            f"generate_daily_pv_h5; generate_daily_pv_h5(output_dir=r'{out}')\""
        )
        qtde.run(local_path=str(_repo_root()), entry=entry)

    daily_pv_all = template_path / "daily_pv_all.h5"
    daily_pv_debug = template_path / "daily_pv_debug.h5"
    assert daily_pv_all.exists(), "daily_pv_all.h5 is not generated."
    assert daily_pv_debug.exists(), "daily_pv_debug.h5 is not generated."

    logger.info("复制生成的数据文件到工作目录")
    Path(FACTOR_COSTEER_SETTINGS.data_folder).mkdir(parents=True, exist_ok=True)
    shutil.copy(daily_pv_all, Path(FACTOR_COSTEER_SETTINGS.data_folder) / "daily_pv.h5")
    shutil.copy(template_path / "README.md", Path(FACTOR_COSTEER_SETTINGS.data_folder) / "README.md")

    Path(FACTOR_COSTEER_SETTINGS.data_folder_debug).mkdir(parents=True, exist_ok=True)
    shutil.copy(daily_pv_debug, Path(FACTOR_COSTEER_SETTINGS.data_folder_debug) / "daily_pv.h5")
    shutil.copy(template_path / "README.md", Path(FACTOR_COSTEER_SETTINGS.data_folder_debug) / "README.md")
    logger.info("数据准备完成")


def ensure_factor_data(use_local: bool = True) -> None:
    """Ensure factor coder h5 folders exist (generates from qlib when missing)."""
    if (
        Path(FACTOR_COSTEER_SETTINGS.data_folder).exists()
        and Path(FACTOR_COSTEER_SETTINGS.data_folder_debug).exists()
    ):
        return
    generate_data_folder_from_qlib(use_local=use_local)


def get_file_desc(p: Path, variable_list: list | None = None) -> str:
    p = Path(p)
    variable_list = variable_list or []

    jj_tpl = Environment(undefined=StrictUndefined).from_string(
        """
{{file_name}}
```{{type_desc}}
{{content}}
```
"""
    )

    if p.name.endswith(".h5"):
        df = pd.read_hdf(p)
        pd.set_option("display.max_columns", None)
        pd.set_option("display.max_rows", None)
        pd.set_option("display.max_colwidth", None)

        if isinstance(df.index, pd.MultiIndex):
            df_info = f"MultiIndex names:, {df.index.names})\n"
        else:
            df_info = f"Index name: {df.index.name}\n"
        columns = df.dtypes.to_dict()
        filtered_columns = [f"{i, j}" for i, j in columns.items() if i in variable_list]
        if filtered_columns:
            df_info += "Related Data columns: \n"
            df_info += ",".join(filtered_columns)
        else:
            df_info += "Data columns: \n"
            df_info += ",".join(str(c) for c in columns)
        df_info += "\n"
        if "REPORT_PERIOD" in df.columns:
            one_instrument = df.index.get_level_values("instrument")[0]
            df_on_one_instrument = df.loc[pd.IndexSlice[:, one_instrument], ["REPORT_PERIOD"]]
            df_info += f"""
A snapshot of one instrument, from which you can tell the distribution of the data:
{df_on_one_instrument.head(5)}
"""
        return jj_tpl.render(file_name=p.name, type_desc="h5 info", content=df_info)
    if p.name.endswith(".md"):
        content = p.read_text()
        return jj_tpl.render(file_name=p.name, type_desc="markdown", content=content)
    raise NotImplementedError(f"file type {p.name} is not supported.")


def get_data_folder_intro(
    fname_reg: str = ".*",
    flags: int = 0,
    variable_mapping: dict | None = None,
    use_local: bool = True,
) -> str:
    ensure_factor_data(use_local=use_local)
    content_l: list[str] = []
    for p in Path(FACTOR_COSTEER_SETTINGS.data_folder_debug).iterdir():
        if re.match(fname_reg, p.name, flags) is not None:
            if variable_mapping:
                content_l.append(get_file_desc(p, variable_mapping.get(p.stem, [])))
            else:
                content_l.append(get_file_desc(p))
    return "\n----------------- file splitter -------------\n".join(content_l)
