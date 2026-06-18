"""CLI entry: A-share data download, adjustment, and Qlib preparation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from alphapilot.log import logger
from alphapilot.systems.data.adjust_prices import apply_adjust_directory
from alphapilot.systems.data.generate_h5 import generate_daily_pv_h5
from alphapilot.systems.data.prepare_cn import (
    DEFAULT_STOCK_CSV,
    FACTOR_HISTORY_START_DATE,
    default_raw_dir,
    download_cn_data,
    existing_factor_dir,
    existing_raw_dir,
    factor_covers_price_history,
    normalize_adjust_mode,
    refresh_adjust_factors,
    refresh_adjust_factors_for_raw_dir,
    resolve_factor_dir,
    resolve_raw_dir,
)
from alphapilot.systems.data.qlib_convert import (
    DEFAULT_INCLUDE_FIELDS,
    DEFAULT_QLIB_DIR,
    dump_csv_to_qlib,
    extend_future_calendar,
)
from alphapilot.systems.data.stock_list import (
    default_market_name,
    load_stocks_from_file,
    write_qlib_instruments,
)


def _resolve_market(
    stock_csv: str | Path | None,
    market: str | None,
    all_market: bool,
) -> str:
    if market:
        return market
    if all_market:
        return "all"
    return default_market_name(stock_csv)


class PrepareDataCLI:
    """Download CSV, apply adjustment, convert to Qlib, and build factor h5."""

    def download(
        self,
        stock_csv: str = str(DEFAULT_STOCK_CSV),
        code_column: str | None = None,
        all_market: bool = False,
        start_date: str = "2016-12-31",
        end_date: str | None = None,
        data_dir: str | None = None,
        qlib_dir: str = str(DEFAULT_QLIB_DIR),
        market: str | None = None,
        sync_instruments: bool = True,
        max_workers: int = 1,
        adjust_mode: str = "none",
        factor_dir: str | None = None,
        download_state_path: str | None = None,
    ) -> None:
        """
        下载行情 CSV（默认除权/不复权 + 复权因子），不转 Qlib、不生成 h5。

        行情 CSV 支持增量：若本地 CSV 已到 ``end_date`` 则完全跳过（零网络请求）。
        有缺口时只补 ``last_date+1 ~ end_date`` 的行情；``adjust_mode=none`` 时在同一
        窗口探测除权，仅当窗口内有除权事件才全量刷新因子（自 1990 年起）。
        强制全量刷新因子请用 ``refresh_factors``。

        推荐流程::

            alphapilot prepare_data download --stock_csv pools.csv --adjust_mode none
            alphapilot prepare_data apply_adjust --adjust_mode forward
            alphapilot prepare_data convert --data_path ~/.qlib/.../raw_data_forward_adjust --market pools
        """
        end = end_date or datetime.now().strftime("%Y-%m-%d")
        pool = _resolve_market(stock_csv if not all_market else None, market, all_market)
        raw_dir = resolve_raw_dir(data_dir, adjust_mode)

        if all_market:
            codes = download_cn_data(
                start_date=start_date,
                end_date=end,
                data_dir=raw_dir,
                stock_csv=None,
                all_market=True,
                max_workers=max_workers,
                adjust_mode=adjust_mode,
                factor_dir=factor_dir,
                download_state_path=download_state_path,
            )
        else:
            codes = download_cn_data(
                start_date=start_date,
                end_date=end,
                data_dir=raw_dir,
                stock_csv=stock_csv,
                code_column=code_column,
                all_market=False,
                max_workers=max_workers,
                adjust_mode=adjust_mode,
                factor_dir=factor_dir,
                download_state_path=download_state_path,
            )

        if sync_instruments and not all_market:
            write_qlib_instruments(
                codes,
                qlib_dir,
                pool,
                start_date=start_date,
                end_date=end,
                data_dir=raw_dir,
            )
            logger.info(
                f"已写入股票池 {pool!r}。复权后运行 apply_adjust，再 convert；"
                f"conf.yaml 中 market 请设为 {pool!r}"
            )
        logger.info(
            "下载完成。下一步: apply_adjust -> convert；"
            "一键全流程请使用 prepare_data pipeline"
        )

    def refresh_factors(
        self,
        stock_csv: str = str(DEFAULT_STOCK_CSV),
        code_column: str | None = None,
        all_market: bool = False,
        raw_dir: str | None = None,
        factor_dir: str | None = None,
        end_date: str | None = None,
        max_workers: int = 1,
    ) -> None:
        """
        仅刷新复权因子（从 1990 年起全量覆盖），不下载行情（baostock 须单线程）。

        若早期后复权价格仍等于除权价，请先运行本命令再 apply_adjust。
        """
        end = end_date or datetime.now().strftime("%Y-%m-%d")
        raw_path = Path(raw_dir).expanduser() if raw_dir else existing_raw_dir("none")
        factor_path = resolve_factor_dir(factor_dir)

        if all_market:
            import baostock as bs
            from alphapilot.systems.data.prepare_cn import get_all_stocks_in_period

            lg = bs.login()
            if lg.error_code != "0":
                raise RuntimeError(f"baostock 登录失败: {lg.error_msg}")
            try:
                codes = get_all_stocks_in_period(FACTOR_HISTORY_START_DATE, end)
            finally:
                bs.logout()
            refresh_adjust_factors(codes, end, factor_path, max_workers=max_workers)
        elif stock_csv:
            codes = load_stocks_from_file(stock_csv, code_column=code_column)
            refresh_adjust_factors(codes, end, factor_path, max_workers=max_workers)
        else:
            refresh_adjust_factors_for_raw_dir(
                raw_path, factor_path, end, max_workers=max_workers
            )
        logger.info("复权因子刷新完成。")

    def apply_adjust(
        self,
        adjust_mode: str = "forward",
        target_mode: str | None = None,
        raw_dir: str | None = None,
        factor_dir: str | None = None,
        output_dir: str | None = None,
        max_workers: int = 4,
        refresh_factors_if_needed: bool = False,
    ) -> None:
        """
        将除权 CSV + 复权因子合成为前复权或后复权 CSV（供训练/convert 使用）。

        复权计算只读本地 CSV，不访问 baostock；仅 ``refresh_factors_if_needed=True`` 时会联网补因子。

        Args:
            adjust_mode: ``forward`` / ``backward``（或 前复权 / 后复权）.
            target_mode: 与 ``adjust_mode`` 相同（旧参数名，二选一即可）.
            raw_dir: 除权行情目录，默认 ``raw_data_no_adjust``.
            factor_dir: 复权因子目录，默认 ``adjust_factors``.
            output_dir: 输出目录，默认 ``raw_data_forward_adjust`` / ``raw_data_back_adjust``.
            refresh_factors_if_needed: 检测到因子不全时是否自动联网刷新（默认 False）.
        """
        if target_mode is not None:
            if adjust_mode != "forward" and normalize_adjust_mode(adjust_mode) != normalize_adjust_mode(
                target_mode
            ):
                logger.warning(
                    f"同时指定 adjust_mode={adjust_mode!r} 与 target_mode={target_mode!r}，"
                    f"以 adjust_mode 为准。"
                )
            else:
                adjust_mode = target_mode

        import pandas as pd

        mode = normalize_adjust_mode(adjust_mode)
        raw_path = Path(raw_dir).expanduser() if raw_dir else existing_raw_dir("none")
        factor_path = Path(factor_dir).expanduser() if factor_dir else existing_factor_dir()
        out_path = (
            Path(output_dir).expanduser()
            if output_dir
            else default_raw_dir(mode)
        )

        if refresh_factors_if_needed:
            end = datetime.now().strftime("%Y-%m-%d")
            incomplete = 0
            for csv_file in raw_path.glob("*.csv"):
                price_df = pd.read_csv(csv_file)
                factor_file = factor_path / csv_file.name
                if not factor_file.exists():
                    incomplete += 1
                    continue
                factor_df = pd.read_csv(factor_file)
                if not factor_covers_price_history(factor_df, price_df):
                    incomplete += 1
            if incomplete:
                msg = (
                    f"{incomplete} 只股票复权因子不完整（缺少 {FACTOR_HISTORY_START_DATE} 起的早期除权记录）。"
                    "请先运行: alphapilot prepare_data refresh_factors --stock_csv <你的列表>"
                )
                if refresh_factors_if_needed:
                    logger.warning(msg + " 正在自动刷新全量因子...")
                    refresh_adjust_factors_for_raw_dir(
                        raw_path, factor_path, end, max_workers=1
                    )
                else:
                    logger.warning(msg)
                    return

        logger.info(f"复权类型: {mode} -> 输出目录: {out_path}")
        apply_adjust_directory(
            raw_dir=raw_path,
            factor_dir=factor_path,
            output_dir=out_path,
            target_mode=mode,
            max_workers=max_workers,
        )

    def dump(
        self,
        data_path: str | None = None,
        adjust_mode: str = "forward",
        qlib_dir: str = str(DEFAULT_QLIB_DIR),
        include_fields: str = DEFAULT_INCLUDE_FIELDS,
        date_field_name: str = "date",
        symbol_field_name: str = "code",
        max_workers: int = 16,
    ) -> None:
        """Convert CSV directory to Qlib binary format."""
        path = resolve_raw_dir(data_path, adjust_mode) if data_path is None else Path(data_path).expanduser()
        dump_csv_to_qlib(
            data_path=path,
            qlib_dir=qlib_dir,
            include_fields=include_fields,
            date_field_name=date_field_name,
            symbol_field_name=symbol_field_name,
            max_workers=max_workers,
        )

    def calendar(
        self,
        qlib_dir: str = str(DEFAULT_QLIB_DIR),
        region: str = "cn",
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> None:
        """Extend day_future.txt trading calendar."""
        extend_future_calendar(
            qlib_dir=qlib_dir,
            region=region,
            start_date=start_date,
            end_date=end_date,
        )

    def h5(
        self,
        qlib_dir: str = str(DEFAULT_QLIB_DIR),
        market: str | None = None,
        start_date: str = "2015-01-01",
    ) -> None:
        """Generate daily_pv_all.h5 / daily_pv_debug.h5 for factor code."""
        pool = market or default_market_name(DEFAULT_STOCK_CSV)
        generate_daily_pv_h5(qlib_dir=qlib_dir, market=pool, start_date=start_date)

    def convert(
        self,
        stock_csv: str = str(DEFAULT_STOCK_CSV),
        code_column: str | None = None,
        all_market: bool = False,
        data_path: str | None = None,
        adjust_mode: str = "forward",
        qlib_dir: str = str(DEFAULT_QLIB_DIR),
        include_fields: str = DEFAULT_INCLUDE_FIELDS,
        region: str = "cn",
        market: str | None = None,
        start_date: str = "2016-12-31",
        end_date: str | None = None,
        sync_instruments: bool = True,
        max_workers: int = 16,
    ) -> None:
        """Run dump + calendar + h5 (skip download)."""
        end = end_date or datetime.now().strftime("%Y-%m-%d")
        pool = _resolve_market(stock_csv if not all_market else None, market, all_market)

        path = Path(data_path).expanduser() if data_path else resolve_raw_dir(None, adjust_mode)

        if sync_instruments and not all_market:
            codes = load_stocks_from_file(stock_csv, code_column=code_column)
            write_qlib_instruments(
                codes,
                qlib_dir,
                pool,
                start_date=start_date,
                end_date=end,
                data_dir=path,
            )
        self.dump(
            data_path=str(path),
            adjust_mode=adjust_mode,
            qlib_dir=qlib_dir,
            include_fields=include_fields,
            max_workers=max_workers,
        )
        self.calendar(qlib_dir=qlib_dir, region=region)
        self.h5(qlib_dir=qlib_dir, market=pool if not all_market else "all")

    def pipeline(
        self,
        stock_csv: str = str(DEFAULT_STOCK_CSV),
        code_column: str | None = None,
        all_market: bool = False,
        start_date: str = "2016-12-31",
        end_date: str | None = None,
        data_dir: str | None = None,
        qlib_dir: str | None = None,
        market: str | None = None,
        include_fields: str = DEFAULT_INCLUDE_FIELDS,
        region: str = "cn",
        sync_instruments: bool = True,
        max_workers: int = 1,
        dump_workers: int = 16,
        adjust_mode: str = "none",
        factor_dir: str | None = None,
        download_state_path: str | None = None,
        target_mode: str = "forward",
        apply_adjust_after_download: bool = True,
        source: str = "baostock_cn",
        token: str | None = None,
    ) -> None:
        """
        全流程: download -> (可选 apply_adjust) -> convert，支持 baostock / tushare。

        默认先下除权数据，再按 ``target_mode`` 合成前复权(默认)或后复权 CSV，最后转 Qlib。
        Tushare 仅支持除权下载，``source=tushare_cn`` 时强制 ``adjust_mode=none``，
        最终复权由 ``target_mode`` 决定，且各目录默认落在 ``cn_data/tushare/`` 下。
        """
        is_tushare = source == "tushare_cn"  # adapter registry name
        pool = _resolve_market(stock_csv if not all_market else None, market, all_market)
        end = end_date or datetime.now().strftime("%Y-%m-%d")

        if is_tushare:
            from alphapilot.systems.data import prepare_tushare
            from alphapilot.systems.data.data_paths import (
                canonical_tushare_factor_dir,
                canonical_tushare_qlib_dir,
                canonical_tushare_raw_dir,
            )

            if normalize_adjust_mode(adjust_mode) != "none":
                logger.warning("Tushare 仅支持除权下载，已将 adjust_mode 调整为 none。")
            adjust_mode = "none"
            raw_none_dir = Path(data_dir).expanduser() if data_dir else canonical_tushare_raw_dir("none")
            factor_path = Path(factor_dir).expanduser() if factor_dir else canonical_tushare_factor_dir()
            resolved_qlib = qlib_dir or str(canonical_tushare_qlib_dir())
            codes = prepare_tushare.download_cn_data(
                start_date=start_date,
                end_date=end,
                data_dir=raw_none_dir,
                stock_csv=None if all_market else stock_csv,
                code_column=code_column,
                all_market=all_market,
                adjust_mode="none",
                factor_dir=factor_path,
                download_state_path=download_state_path,
                token=token,
            )
            if sync_instruments and not all_market:
                write_qlib_instruments(
                    codes, resolved_qlib, pool,
                    start_date=start_date, end_date=end, data_dir=raw_none_dir,
                )
        else:
            resolved_qlib = qlib_dir or str(DEFAULT_QLIB_DIR)
            self.download(
                stock_csv=stock_csv,
                code_column=code_column,
                all_market=all_market,
                start_date=start_date,
                end_date=end,
                data_dir=data_dir,
                qlib_dir=resolved_qlib,
                market=pool,
                sync_instruments=sync_instruments,
                max_workers=max_workers,
                adjust_mode=adjust_mode,
                factor_dir=factor_dir,
                download_state_path=download_state_path,
            )

        convert_mode = adjust_mode
        convert_path = data_dir
        if normalize_adjust_mode(adjust_mode) == "none" and apply_adjust_after_download:
            if is_tushare:
                out_dir = canonical_tushare_raw_dir(normalize_adjust_mode(target_mode))
                self.apply_adjust(
                    target_mode=target_mode,
                    raw_dir=str(raw_none_dir),
                    factor_dir=str(factor_path),
                    output_dir=str(out_dir),
                )
                convert_path = str(out_dir)
            else:
                self.apply_adjust(
                    target_mode=target_mode,
                    raw_dir=data_dir or str(default_raw_dir("none")),
                    factor_dir=factor_dir,
                )
                convert_path = None
            convert_mode = target_mode

        self.convert(
            stock_csv=stock_csv,
            code_column=code_column,
            all_market=all_market,
            data_path=convert_path,
            adjust_mode=convert_mode,
            qlib_dir=resolved_qlib,
            include_fields=include_fields,
            region=region,
            market=pool,
            start_date=start_date,
            end_date=end,
            sync_instruments=False,
            max_workers=dump_workers,
        )
        logger.info(f"全流程完成。source={source} market={pool!r}，请确认 conf.yaml 一致。")


def main():
    import fire

    fire.Fire(PrepareDataCLI)
