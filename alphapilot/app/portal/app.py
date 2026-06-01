"""Unified web portal for systems + pluggable modules."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import streamlit as st

from alphapilot.app.portal.i18n import init_lang, language_selector, t


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


def _show_header(engine: Any) -> None:
    st.title(t("header_title"))
    st.caption(t("header_caption"))
    c1, c2, c3 = st.columns(3)
    c1.metric(t("metric_systems"), len(engine.systems))
    c2.metric(t("metric_modules"), len(engine.modules))
    c3.metric(t("metric_module_commands"), len(engine.collect_commands()))


def _show_sidebar(engine: Any) -> None:
    language_selector()
    st.sidebar.divider()
    st.sidebar.header(t("sidebar_runtime"))
    st.sidebar.code(engine.config.summary(), language=None)
    if st.sidebar.button(t("sidebar_reload")):
        st.cache_resource.clear()
        st.rerun()
    st.sidebar.divider()
    st.sidebar.subheader(t("sidebar_loaded_modules"))
    for name, module in engine.modules.items():
        st.sidebar.write(t("sidebar_module_entry", name=name, count=len(module.commands())))


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
        with st.expander(t("module_expander", name=name, count=len(commands)), expanded=False):
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

    c1, c2, c3 = st.columns(3)
    c1.text_input(t("qlib_data_dir"), str(cfg.qlib_data_dir), disabled=True)
    c2.text_input(t("raw_data_dir"), str(cfg.raw_data_dir), disabled=True)
    c3.text_input(t("adjust_factor_dir"), str(cfg.factor_dir), disabled=True)

    st.markdown(f"#### {t('universe_heading')}")
    if st.button(t("load_universe")):
        try:
            universe = data_system.get_universe()
            st.success(t("universe_loaded", count=len(universe)))
            st.dataframe({"symbol": universe[:500]}, use_container_width=True, hide_index=True)
        except Exception as exc:  # noqa: BLE001
            st.error(t("universe_failed", error=exc))

    st.markdown(f"#### {t('data_ops_heading')}")
    action = st.selectbox(t("data_action"), ["pipeline", "download", "convert", "build_h5"], key="data_action")
    start_date = st.text_input(t("start_date"), "2005-01-01")
    end_date = st.text_input(t("end_date"), "")
    stock_csv = st.text_input(t("stock_csv"), "")
    adjust_mode = st.selectbox(t("adjust_mode"), ["backward", "forward"], index=0)
    if st.button(t("run_data_action")):
        try:
            kwargs: dict[str, Any] = {}
            if end_date.strip():
                kwargs["end_date"] = end_date.strip()
            if stock_csv.strip():
                kwargs["stock_csv"] = stock_csv.strip()
            if action in ("pipeline", "convert"):
                kwargs["adjust_mode"] = adjust_mode
            if action in ("pipeline", "download"):
                kwargs["start_date"] = start_date.strip()
            result = getattr(data_system, action)(**kwargs)
            st.success(t("data_action_finished", action=action))
            st.write(result)
        except Exception as exc:  # noqa: BLE001
            st.error(t("data_action_failed", error=exc))


def _render_factor_tab(engine: Any) -> None:
    st.subheader(t("factor_subheader"))
    factor_system = engine.get_system("factor")
    zoo_path = Path(engine.config.factor.zoo_dir) / "factor_zoo.csv"

    st.text_input(t("factor_zoo_csv"), str(zoo_path), disabled=True)

    if zoo_path.exists():
        try:
            import pandas as pd

            df = pd.read_csv(zoo_path)
            st.success(t("factor_zoo_rows", count=len(df)))
            st.dataframe(df.head(200), use_container_width=True, hide_index=True)
        except Exception as exc:  # noqa: BLE001
            st.warning(t("factor_zoo_preview_failed", error=exc))
    else:
        st.info(t("factor_zoo_missing"))

    st.markdown(f"#### {t('factor_validate_heading')}")
    expr = st.text_area(
        t("expression"),
        value="",
        height=100,
        placeholder=t("expression_placeholder"),
    )
    factor_name = st.text_input(t("factor_name"), value="")
    c1, c2 = st.columns(2)
    if c1.button(t("check_expression")):
        try:
            ok = factor_system.is_acceptable(expr)
            if ok:
                st.success(t("expression_acceptable"))
            else:
                st.error(t("expression_not_acceptable"))
        except Exception as exc:  # noqa: BLE001
            st.error(t("check_failed", error=exc))
    if c2.button(t("add_to_factor_db")):
        try:
            added = factor_system.database.add(factor_name.strip(), expr.strip())
            factor_system.database.save()
            if added:
                st.success(t("factor_added"))
            else:
                st.warning(t("factor_not_added"))
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
    export_path = st.text_input(t("export_path"), value=str(zoo_path))
    if c4.button(t("export_factor_db")):
        try:
            factor_system.database.save(export_path.strip())
            st.success(t("exported_to", path=export_path))
        except Exception as exc:  # noqa: BLE001
            st.error(t("export_failed", error=exc))


def _render_model_tab(engine: Any) -> None:
    st.subheader(t("model_subheader"))
    model_system = engine.get_system("model")
    db = model_system.param_database

    models = db.list_models()
    st.write(t("stored_model_sets", count=len(models)))
    if models:
        selected = st.selectbox(t("select_model"), models)
        params = db.load(selected)
        st.json(params or {})
    else:
        st.info(t("no_stored_params"))

    st.markdown(f"#### {t('save_export_heading')}")
    model_name = st.text_input(t("model_name"), value="")
    params_raw = st.text_area(t("params_json"), value="{}", height=140)
    c1, c2 = st.columns(2)
    if c1.button(t("save_params")):
        try:
            db.save(model_name.strip(), json.loads(params_raw))
            st.success(t("params_saved"))
        except Exception as exc:  # noqa: BLE001
            st.error(t("save_failed", error=exc))
    export_model_name = st.text_input(t("export_model_name"), value=model_name)
    export_model_path = st.text_input(t("export_file_path"), value="")
    if c2.button(t("export_params")):
        try:
            payload = db.load(export_model_name.strip())
            if payload is None:
                raise ValueError(t("model_params_not_found"))
            out = Path(export_model_path.strip())
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            st.success(t("params_exported", name=export_model_name, path=out))
        except Exception as exc:  # noqa: BLE001
            st.error(t("export_failed", error=exc))

    st.markdown(f"#### {t('import_pdf_heading')}")
    pdf_path = st.text_input(t("pdf_path"))
    if st.button(t("import_model_pdf")):
        try:
            result = model_system.import_model(pdf_path.strip(), kind="pdf")
            st.success(t("model_imported"))
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
    selected_command = st.selectbox(t("command_label"), sorted(selected_commands.keys()))
    raw_kwargs = st.text_area(
        t("command_kwargs"),
        value="{}",
        height=120,
        help=t("command_kwargs_help"),
    )
    if st.button(t("run_command")):
        try:
            kwargs = _safe_json_load(raw_kwargs)
            result = selected_commands[selected_command](**kwargs)
            st.success(t("command_executed"))
            st.write(result)
        except Exception as exc:  # noqa: BLE001
            st.error(t("command_failed", error=exc))


def _render_data_viz_tab() -> None:
    from alphapilot.modules.data_viz.panel import render_data_viz_panel

    render_data_viz_panel(
        translate=t,
        use_sidebar=False,
        show_heading=True,
        key_prefix="portal_dv",
    )


def _render_backtest_tab(engine: Any) -> None:
    st.subheader(t("backtest_subheader"))
    backtest_system = engine.get_system("backtest")
    st.text_input(
        t("workspace_root"),
        value=str(engine.config.backtest.workspace_root),
        disabled=True,
    )
    if st.button(t("list_backtest_runs")):
        try:
            runs = backtest_system.results.list_runs()
            st.success(t("backtest_runs_found", count=len(runs)))
            st.dataframe({"workspace": [str(p) for p in runs[:500]]}, use_container_width=True, hide_index=True)
        except Exception as exc:  # noqa: BLE001
            st.error(t("list_runs_failed", error=exc))


def main() -> None:
    with st.spinner(t("loading_engine")):
        engine = _load_engine()
    _show_header(engine)
    _show_sidebar(engine)

    tab_overview, tab_data, tab_data_viz, tab_factor, tab_model, tab_backtest, tab_module = st.tabs(
        [
            t("tab_overview"),
            t("tab_data"),
            t("tab_data_viz"),
            t("tab_factor"),
            t("tab_model"),
            t("tab_backtest"),
            t("tab_modules"),
        ]
    )
    with tab_overview:
        _render_overview(engine)
    with tab_data:
        _render_data_tab(engine)
    with tab_data_viz:
        _render_data_viz_tab()
    with tab_factor:
        _render_factor_tab(engine)
    with tab_model:
        _render_model_tab(engine)
    with tab_backtest:
        _render_backtest_tab(engine)
    with tab_module:
        _render_module_hub(engine)


if __name__ == "__main__":
    main()
