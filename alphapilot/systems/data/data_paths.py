"""Canonical on-disk layout for CN market data (baostock / tushare)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

AdjustMode = Literal["none", "forward", "backward"]

CN_DATA_ROOT = Path("~/.qlib/qlib_data/cn_data")
BAOSTOCK_ROOT = CN_DATA_ROOT / "baostock"
TUSHARE_ROOT = CN_DATA_ROOT / "tushare"

BAOSTOCK_SOURCE = "baostock_cn"
TUSHARE_SOURCE = "tushare_cn"

BAOSTOCK_RAW_DIR_BY_MODE: dict[AdjustMode, Path] = {
    "none": BAOSTOCK_ROOT / "raw_data_no_adjust",
    "forward": BAOSTOCK_ROOT / "raw_data_forward_adjust",
    "backward": BAOSTOCK_ROOT / "raw_data_back_adjust",
}
BAOSTOCK_FACTOR_DIR = BAOSTOCK_ROOT / "adjust_factors"
BAOSTOCK_QLIB_DIR = BAOSTOCK_ROOT / "qlib"

TUSHARE_RAW_DIR_BY_MODE: dict[AdjustMode, Path] = {
    "none": TUSHARE_ROOT / "raw_data_no_adjust",
    "forward": TUSHARE_ROOT / "raw_data_forward_adjust",
    "backward": TUSHARE_ROOT / "raw_data_back_adjust",
}
TUSHARE_FACTOR_DIR = TUSHARE_ROOT / "adjust_factors"
TUSHARE_QLIB_DIR = TUSHARE_ROOT / "qlib"

# Pre-unification paths (directly under ``cn_data/``).
LEGACY_BAOSTOCK_RAW_DIR_BY_MODE: dict[AdjustMode, Path] = {
    "none": CN_DATA_ROOT / "raw_data_no_adjust",
    "forward": CN_DATA_ROOT / "raw_data_forward_adjust",
    "backward": CN_DATA_ROOT / "raw_data_back_adjust",
}
LEGACY_BAOSTOCK_FACTOR_DIR = CN_DATA_ROOT / "adjust_factors"
LEGACY_BAOSTOCK_QLIB_DIR = CN_DATA_ROOT
LEGACY_TUSHARE_QLIB_DIR = Path("~/.qlib/qlib_data/cn_data_tushare")


def _expanded(path: Path) -> Path:
    return path.expanduser()


def _dir_has_csv(path: Path) -> bool:
    return path.is_dir() and any(path.glob("*.csv"))


def _pick_data_dir(canonical: Path, legacy: Path) -> Path:
    """Prefer canonical layout; fall back to legacy when only old data exists."""
    canonical_path = _expanded(canonical)
    legacy_path = _expanded(legacy)
    if _dir_has_csv(canonical_path):
        return canonical_path
    if _dir_has_csv(legacy_path):
        return legacy_path
    return canonical_path


def _pick_qlib_dir(canonical: Path, *legacy_candidates: Path) -> Path:
    canonical_path = _expanded(canonical)
    if (canonical_path / "features").is_dir() or (canonical_path / "calendars").is_dir():
        return canonical_path
    for legacy in legacy_candidates:
        legacy_path = _expanded(legacy)
        if (legacy_path / "features").is_dir() or (legacy_path / "calendars").is_dir():
            return legacy_path
    return canonical_path


def canonical_baostock_raw_dir(adjust_mode: AdjustMode) -> Path:
    return _expanded(BAOSTOCK_RAW_DIR_BY_MODE[adjust_mode])


def existing_baostock_raw_dir(adjust_mode: AdjustMode) -> Path:
    return _pick_data_dir(
        BAOSTOCK_RAW_DIR_BY_MODE[adjust_mode],
        LEGACY_BAOSTOCK_RAW_DIR_BY_MODE[adjust_mode],
    )


def canonical_baostock_factor_dir() -> Path:
    return _expanded(BAOSTOCK_FACTOR_DIR)


def existing_baostock_factor_dir() -> Path:
    return _pick_data_dir(BAOSTOCK_FACTOR_DIR, LEGACY_BAOSTOCK_FACTOR_DIR)


def canonical_baostock_qlib_dir() -> Path:
    return _expanded(BAOSTOCK_QLIB_DIR)


def existing_baostock_qlib_dir() -> Path:
    return _pick_qlib_dir(BAOSTOCK_QLIB_DIR, LEGACY_BAOSTOCK_QLIB_DIR)


def canonical_tushare_raw_dir(adjust_mode: AdjustMode) -> Path:
    return _expanded(TUSHARE_RAW_DIR_BY_MODE[adjust_mode])


def existing_tushare_raw_dir(adjust_mode: AdjustMode) -> Path:
    return canonical_tushare_raw_dir(adjust_mode)


def canonical_tushare_factor_dir() -> Path:
    return _expanded(TUSHARE_FACTOR_DIR)


def existing_tushare_factor_dir() -> Path:
    return canonical_tushare_factor_dir()


def canonical_tushare_qlib_dir() -> Path:
    return _expanded(TUSHARE_QLIB_DIR)


def existing_tushare_qlib_dir() -> Path:
    return _pick_qlib_dir(TUSHARE_QLIB_DIR, LEGACY_TUSHARE_QLIB_DIR)


def download_state_path_for_raw_dir(raw_dir: str | Path) -> Path:
    """``download_state.csv`` lives beside mode directories under each provider root."""
    return _expanded(Path(raw_dir)).parent / "download_state.csv"
