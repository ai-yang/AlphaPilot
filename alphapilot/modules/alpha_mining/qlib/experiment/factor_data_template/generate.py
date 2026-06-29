"""Deprecated: factor h5 cache is generated automatically by factor/backtest tasks."""

from alphapilot.systems.data.generate_h5 import generate_daily_pv_h5

if __name__ == "__main__":
    generate_daily_pv_h5(market="main_stock_2026_4_27")
