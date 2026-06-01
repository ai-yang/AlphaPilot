"""Deprecated: use `alphapilot prepare_data h5 --market <pool>` from the AlphaPilot project root."""

from alphapilot.systems.data.generate_h5 import generate_daily_pv_h5

if __name__ == "__main__":
    generate_daily_pv_h5(market="main_stock_2026_4_27")
