"""Find instruments whose qlib ``$factor`` is missing — the data flaw behind adjusted-price mode.

qlib's backtest exchange flips the *whole* run into adjusted-price mode (ignoring ``trade_unit`` and
holding fractional adjusted-share amounts) as soon as **any** instrument in the traded window has a
``$close`` but a NaN ``$factor`` (see qlib ``exchange.py``: ``(factor.isna() & ~close.isna()).any()``).
That mode is what made the live daily-trade rebalance hold fractional positions. This script scans
the universe over a recent window and reports exactly which instruments trip that condition, so you
know what to re-dump / convert to restore non-adjusted (whole-lot) trading.

Usage (run with the project env so ``qlib`` is importable):

    python scripts/find_missing_factor.py                 # market=all, last ~15 days
    python scripts/find_missing_factor.py --market csi300
    python scripts/find_missing_factor.py --start 2026-05-20 --end 2026-06-03
    python scripts/find_missing_factor.py --out missing.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", default="all", help="qlib instruments market (default: all)")
    parser.add_argument("--start", default=None, help="window start YYYY-MM-DD (default: end − --days)")
    parser.add_argument("--end", default=None, help="window end YYYY-MM-DD (default: latest calendar day)")
    parser.add_argument("--days", type=int, default=15, help="lookback days when --start omitted (default: 15)")
    parser.add_argument("--qlib-dir", default=None, help="override qlib provider_uri (default: app config)")
    parser.add_argument("--out", default=None, help="also write the offending instrument list to this file")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    if args.qlib_dir:
        qdir = str(Path(args.qlib_dir).expanduser())
    else:
        from alphapilot.kernel.config import AppConfig

        qdir = str(AppConfig().data.qlib_data_dir)
    print(f"qlib_data_dir: {qdir}", flush=True)

    import pandas as pd
    import qlib
    from qlib.data import D

    qlib.init(provider_uri=qdir, region="cn")

    end = pd.Timestamp(args.end) if args.end else pd.Timestamp(max(D.calendar()))
    start = pd.Timestamp(args.start) if args.start else end - pd.Timedelta(days=args.days)
    print(f"window: {start.date()} → {end.date()}  market={args.market}", flush=True)

    instruments = D.instruments(market=args.market)
    df = D.features(instruments, ["$close", "$factor"], start, end, freq="day")
    if df.empty:
        print("No data in this window — widen --start/--end or check the data dir.", flush=True)
        return 1

    n_inst = df.index.get_level_values("instrument").nunique()
    # qlib's exact trigger: a tradeable bar ($close present) whose $factor is NaN.
    bad = df[df["$factor"].isna() & df["$close"].notna()]
    bad_inst = sorted(bad.index.get_level_values("instrument").unique())

    print(f"\nscanned {n_inst} instruments, {len(df)} bars.", flush=True)
    if not bad_inst:
        print("OK ✅  every priced bar has a $factor — qlib will use NON-adjusted (whole-lot) mode.", flush=True)
        return 0

    print(
        f"⚠️  {len(bad_inst)} instrument(s) have a $close but a MISSING $factor — this forces the "
        f"whole exchange into adjusted-price mode (no board lots):",
        flush=True,
    )
    for code in bad_inst:
        dates = sorted({str(d.date()) for d in bad.xs(code, level="instrument").index})
        shown = ", ".join(dates[:5]) + (" …" if len(dates) > 5 else "")
        print(f"  {code}  ({len(dates)} day(s): {shown})", flush=True)

    if args.out:
        Path(args.out).expanduser().write_text("\n".join(bad_inst) + "\n", encoding="utf-8")
        print(f"\nwrote {len(bad_inst)} codes → {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
