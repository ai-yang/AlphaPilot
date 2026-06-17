"""Streamlit unified web portal for systems + pluggable modules."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Callable

import streamlit as st

from alphapilot.modules.portal.i18n import format_factor_rejection, init_lang, language_selector, t


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
            st.dataframe({"symbol": universe[:500]}, use_container_width=True, hide_index=True)
        except Exception as exc:  # noqa: BLE001
            st.error(t("universe_failed", error=exc))

    st.markdown(f"#### {t('data_ops_heading')}")
    action = st.selectbox(
        t("data_action"),
        ["pipeline", "download", "apply_adjust", "convert", "build_h5"],
        key="data_action",
    )

    # Pipeline/convert still use the data system defaults; download/apply_adjust are source-aware.
    is_download = action == "download"
    is_apply_adjust = action == "apply_adjust"
    source = "baostock_cn"
    if is_download or is_apply_adjust:
        source_key = "data_dl_source" if is_download else "data_apply_source"
        source = st.selectbox(t("data_source"), ["baostock_cn", "tushare_cn"], key=source_key)
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
    else:
        adjust_mode = st.selectbox(t("adjust_mode"), ["backward", "forward", "none"], index=0)
        if is_tushare:
            st.info(t("tushare_adjust_note"))

    output_dir = factor_dir = code_column = token = ""
    all_market = include_daily_basic = False
    if is_download:
        with st.expander(t("download_custom_params")):
            output_dir = st.text_input(t("download_output_dir"), "", key="data_dl_output_dir")
            factor_dir = st.text_input(t("download_factor_dir"), "", key="data_dl_factor_dir")
            code_column = st.text_input(t("download_code_column"), "", key="data_dl_code_column")
            all_market = st.checkbox(t("download_all_market"), value=False, key="data_dl_all_market")
            if is_tushare:
                token = st.text_input(t("tushare_token"), "", type="password", key="data_dl_token")
                include_daily_basic = st.checkbox(
                    t("include_daily_basic"), value=False, key="data_dl_daily_basic"
                )
    if is_download and is_tushare:
        st.warning(t("tushare_manage_boundary"))

    if st.button(t("run_data_action")):
        try:
            kwargs: dict[str, Any] = {}

            if action == "build_h5":
                if start_date.strip():
                    kwargs["start_date"] = start_date.strip()
            elif action == "apply_adjust":
                kwargs["adjust_mode"] = adjust_mode
                kwargs["raw_dir"] = apply_raw_dir.strip() or apply_default_raw_dir
                kwargs["factor_dir"] = apply_factor_dir.strip() or apply_default_factor_dir
                kwargs["output_dir"] = apply_output_dir.strip() or apply_default_output_dir
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

            result = getattr(data_system, action)(**kwargs)
            st.success(t("data_action_finished", action=action))
            st.write(result)
        except Exception as exc:  # noqa: BLE001
            st.error(t("data_action_failed", error=exc))

    _render_stock_manage(data_system)


def _render_h5_rebuild(data_system: Any) -> None:
    """Deferred daily_pv h5 rebuild, shown once a modify/delete marks it stale."""
    if not st.session_state.get("portal_stock_h5_stale"):
        return
    st.warning(t("stock_h5_stale_warning"))
    market = st.text_input(t("stock_rebuild_h5_market"), value="", key="portal_stock_h5_market")
    if st.button(t("stock_rebuild_h5_btn"), key="portal_stock_h5_btn"):
        try:
            if market.strip():
                data_system.rebuild_h5(market=market.strip())
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
    try:
        by_mode = data_system.list_symbols()
    except Exception as exc:  # noqa: BLE001
        st.error(t("data_action_failed", error=exc))
        return

    all_symbols = sorted({s for syms in by_mode.values() for s in syms})
    if not all_symbols:
        st.info(t("stock_manage_no_symbols"))
        _render_h5_rebuild(data_system)
        return

    available_modes = [m for m, syms in by_mode.items() if syms]
    symbol = st.selectbox(t("stock_select_symbol"), all_symbols, key="portal_stock_symbol")
    modes = st.multiselect(
        t("stock_adjust_modes"),
        list(by_mode.keys()),
        default=available_modes,
        key="portal_stock_modes",
    )
    qlib_mode = st.selectbox(
        t("stock_qlib_adjust_mode"),
        ["backward", "forward", "none"],
        index=0,
        key="portal_stock_qlib_mode",
    )

    # --- Delete ---
    st.markdown(f"##### {t('stock_delete_heading')}")
    del_confirm = st.checkbox(t("delete_confirm"), key="portal_stock_del_confirm")
    if st.button(t("stock_delete_btn"), key="portal_stock_del_btn"):
        if not del_confirm:
            st.warning(t("delete_confirm"))
        else:
            try:
                report = data_system.delete_symbol(symbol, adjust_mode=modes or None)
                st.session_state["portal_stock_h5_stale"] = True
                st.cache_data.clear()
                st.success(
                    t("stock_deleted", name=symbol, detail=f"{len(report.get('deleted', []))} items")
                )
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(t("stock_delete_failed", error=exc))

    # --- Refresh / re-download ---
    st.markdown(f"##### {t('stock_refresh_heading')}")
    refresh_start = st.text_input(t("start_date"), value="2016-12-31", key="portal_stock_refresh_start")
    refresh_end = st.text_input(t("end_date"), value="", key="portal_stock_refresh_end")
    if st.button(t("stock_refresh_btn"), key="portal_stock_refresh_btn"):
        try:
            data_system.refresh_symbol(
                symbol,
                adjust_mode=modes or "backward",
                start_date=refresh_start.strip() or "2016-12-31",
                end_date=refresh_end.strip() or None,
                qlib_adjust_mode=qlib_mode,
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
            report = data_system.apply_adjust_symbol(symbol, target_mode=apply_target)
            st.cache_data.clear()
            st.success(t("stock_apply_adjusted", name=symbol, mode=apply_target))
            st.json(report)
        except Exception as exc:  # noqa: BLE001
            st.error(t("stock_apply_adjust_failed", error=exc))

    # --- Trim ---
    st.markdown(f"##### {t('stock_trim_heading')}")
    trim_start = st.text_input(t("stock_trim_start"), value="", key="portal_stock_trim_start")
    trim_end = st.text_input(t("stock_trim_end"), value="", key="portal_stock_trim_end")
    drop_dates = st.text_input(t("stock_drop_dates"), value="", key="portal_stock_drop_dates")
    if st.button(t("stock_trim_btn"), key="portal_stock_trim_btn"):
        try:
            data_system.trim_symbol(
                symbol,
                adjust_mode=modes or None,
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

    _render_h5_rebuild(data_system)


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

    factors = factor_system.list_factors()
    if factors:
        st.markdown(f"#### {t('delete_heading')}")
        factor_names = [item["factor_name"] for item in factors]
        delete_factor_name = st.selectbox(t("select_factor_to_delete"), factor_names, key="portal_delete_factor")
        delete_factor_confirm = st.checkbox(t("delete_confirm"), key="portal_delete_factor_confirm")
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
            result = factor_system.validate_expression(expr)
            if result.acceptable:
                st.success(t("expression_acceptable"))
            else:
                reason = format_factor_rejection(result.code, result.message, result.details)
                st.error(t("expression_not_acceptable"))
                st.caption(reason)
            if result.details:
                with st.expander(t("factor_validation_details")):
                    st.json(result.details)
        except Exception as exc:  # noqa: BLE001
            st.error(t("check_failed", error=exc))
    if c2.button(t("add_to_factor_db")):
        try:
            result = factor_system.add_factor(factor_name.strip(), expr.strip())
            if result.acceptable:
                st.success(t("factor_added"))
                st.rerun()
            else:
                reason = format_factor_rejection(result.code, result.message, result.details)
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
    export_path = st.text_input(t("export_path"), value=str(zoo_path))
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
        delete_strategy_confirm = st.checkbox(t("delete_confirm"), key="portal_delete_strategy_confirm")
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
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
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


def _render_portal_jobs_panel(key_prefix: str) -> None:
    from alphapilot.modules.portal import jobs as portal_jobs

    st.markdown(f"#### {t('jobs_heading')}")
    st.caption(t("jobs_caption"))
    cols = st.columns([1, 1, 2])
    if cols[0].button(t("jobs_refresh"), key=f"{key_prefix}_jobs_refresh"):
        st.rerun()
    cols[1].text_input(
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
    st.dataframe(rows, use_container_width=True, hide_index=True)

    selected_id = st.selectbox(
        t("jobs_select"),
        [job["job_id"] for job in jobs],
        format_func=lambda job_id: _format_job_label(next(j for j in jobs if j["job_id"] == job_id)),
        key=f"{key_prefix}_jobs_select",
    )
    selected = next(job for job in jobs if job["job_id"] == selected_id)
    st.json(selected, expanded=False)
    if selected.get("status") == "succeeded":
        st.success(t("jobs_finished_hint"))
    elif selected.get("status") in {"failed", "lost"}:
        st.error(t("jobs_failed_hint"))

    if selected.get("status") == "running":
        if st.button(t("jobs_cancel"), key=f"{key_prefix}_jobs_cancel_{selected_id}"):
            try:
                portal_jobs.cancel_job(selected_id)
                st.warning(t("jobs_cancelled", job_id=selected_id))
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(t("jobs_cancel_failed", error=exc))

    log_tail = portal_jobs.read_log_tail(selected_id)
    with st.expander(t("jobs_log_tail"), expanded=True):
        st.code(log_tail or t("jobs_log_empty"), language=None)

    result = portal_jobs.read_result(selected_id)
    if result is not None:
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
        step_n = c1.number_input(t("mine_step_n"), min_value=1, max_value=1000, value=1, step=1)
        scenario = c2.text_input(t("mine_scenario"), value="alpha_factor_mining")
        direction = st.text_area(t("mine_direction"), value="", height=90)
        with st.expander(t("advanced_options"), expanded=False):
            path = st.text_input(t("mine_resume_path"), value="")
            qlib_config_name = st.text_input(t("qlib_config_name"), value="", key="mine_qlib_config")
            qlib_template_dir = st.text_input(t("qlib_template_dir"), value="", key="mine_qlib_template")
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


def _render_mine_log_tab(engine: Any) -> None:
    from alphapilot.log.ui.panel import render_log_ui_panel

    _render_mine_launcher()
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
    factor_tab, strategy_tab = st.tabs([t("bt_start_factor_csv"), t("bt_start_strategy_asset")])

    with factor_tab:
        with st.form("portal_factor_backtest_form"):
            factor_path = st.text_input(t("factor_path"), value="")
            c1, c2 = st.columns(2)
            scenario = c1.text_input(t("bt_scenario"), value="factor_backtest", key="factor_bt_scenario")
            qlib_config_name = c2.text_input(t("qlib_config_name"), value="", key="factor_bt_qlib_config")
            qlib_template_dir = st.text_input(t("qlib_template_dir"), value="", key="factor_bt_qlib_template")
            submitted = st.form_submit_button(t("bt_start_factor_btn"), type="primary")
        if submitted:
            if not factor_path.strip():
                st.warning(t("factor_path_required"))
            else:
                kwargs = _nonempty_kwargs(
                    {
                        "factor_path": factor_path,
                        "scenario": scenario,
                        "qlib_config_name": qlib_config_name,
                        "qlib_template_dir": qlib_template_dir,
                    }
                )
                try:
                    job = portal_jobs.start_job("factor_backtest", kwargs)
                    st.success(t("job_started", job_id=job["job_id"]))
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
                strategy_name = st.selectbox(t("strategy_name"), strategies, key="bt_strategy_name_select")
            else:
                strategy_name = st.text_input(t("strategy_name"), value="", key="bt_strategy_name_text")
                st.caption(t("no_stored_params"))
            c1, c2 = st.columns(2)
            mode = c1.selectbox(t("bt_strategy_mode"), ["both", "retrain", "reuse_model"], index=0)
            scenario = c2.text_input(t("bt_scenario"), value="factor_backtest", key="strategy_bt_scenario")
            qlib_data_dir = st.text_input(t("qlib_data_dir"), value="", key="strategy_bt_qlib_data")
            qlib_config_name = st.text_input(t("qlib_config_name"), value="", key="strategy_bt_qlib_config")
            qlib_template_dir = st.text_input(t("qlib_template_dir"), value="", key="strategy_bt_qlib_template")
            run_tag = st.text_input(t("bt_run_tag"), value="", key="strategy_bt_run_tag")
            submitted = st.form_submit_button(t("bt_start_strategy_btn"), type="primary")
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
    tab_start, tab_list, tab_detail = st.tabs([t("bt_tab_start"), t("bt_tab_runs"), t("bt_tab_detail")])
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
                st.dataframe({"workspace": workspace_ids}, use_container_width=True, hide_index=True)
                st.markdown(f"#### {t('delete_heading')}")
                delete_workspace_id = st.selectbox(
                    t("select_backtest_workspace"),
                    workspace_ids,
                    key="portal_delete_backtest_ws",
                )
                delete_backtest_confirm = st.checkbox(t("delete_confirm"), key="portal_delete_backtest_confirm")
                if st.button(t("delete_backtest_btn"), key="portal_delete_backtest_btn"):
                    if not delete_backtest_confirm:
                        st.warning(t("delete_confirm"))
                    else:
                        try:
                            if backtest_system.delete_workspace(delete_workspace_id):
                                st.success(t("backtest_deleted", name=delete_workspace_id))
                                st.rerun()
                            else:
                                st.error(t("backtest_delete_failed", name=delete_workspace_id))
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
        _safe_metric(lambda: len({s for syms in data_system.list_symbols().values() for s in syms})),
    )
    c2.metric(t("home_metric_factors"), _safe_metric(lambda: len(factor_system.list_factors())))
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
        f"🔬 {t('home_go_mining')}", type="primary", use_container_width=True, key="home_go_mining"
    ):
        st.switch_page(pages["mining"])

    st.divider()
    st.markdown(f"#### {t('home_quick_actions')}")
    q1, q2, q3 = st.columns(3)
    if pages.get("market") and q1.button(
        f"📈 {t('home_go_data')}", use_container_width=True, key="home_go_data"
    ):
        st.switch_page(pages["market"])
    if pages.get("backtest") and q2.button(
        f"📊 {t('home_go_backtest')}", use_container_width=True, key="home_go_backtest"
    ):
        st.switch_page(pages["backtest"])
    if pages.get("library") and q3.button(
        f"📚 {t('home_go_library')}", use_container_width=True, key="home_go_library"
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


def main() -> None:
    with st.spinner(t("loading_engine")):
        _load_engine()
    language_selector()

    home_page = st.Page(_page_home, title=t("page_home"), icon="🏠", default=True)
    mining_page = st.Page(_page_mining, title=t("page_mining"), icon="🔬")
    backtest_page = st.Page(_page_backtest, title=t("page_backtest"), icon="📊")
    library_page = st.Page(_page_library, title=t("page_library"), icon="📚")
    market_page = st.Page(_page_market, title=t("page_market"), icon="📈")
    advanced_page = st.Page(_page_advanced, title=t("page_advanced"), icon="⚙️")

    # Stash page handles before nav.run() so the Home page can st.switch_page() to them.
    st.session_state["_nav_pages"] = {
        "home": home_page,
        "mining": mining_page,
        "backtest": backtest_page,
        "library": library_page,
        "market": market_page,
        "advanced": advanced_page,
    }

    st.navigation(
        {
            t("nav_group_overview"): [home_page],
            t("nav_group_data"): [market_page],
            t("nav_group_research"): [mining_page, backtest_page, library_page],
            t("nav_group_system"): [advanced_page],
        }
    ).run()


if __name__ == "__main__":
    main()
