"""Data-quality report for downloaded OHLCV (feather) files.

For every pair/timeframe: first/last candle, expected vs actual candle count,
number of missing candles, longest gap, and share of zero-volume candles.
Usage: .venv/Scripts/python -I scripts/check_data.py [data_dir]
Writes: data/data_quality.csv
"""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "user_data" / "data" / "okx"
FREQ = {"5m": "5min", "15m": "15min", "1h": "1h", "4h": "4h"}

rows = []
for f in sorted(DATA.glob("*.feather")):
    stem = f.stem                       # e.g. BTC_USDT-5m
    pair, tf = stem.rsplit("-", 1)
    if tf not in FREQ:
        continue
    df = pd.read_feather(f)
    d = pd.to_datetime(df["date"], utc=True).sort_values()
    step = pd.Timedelta(FREQ[tf])
    full = pd.date_range(d.iloc[0], d.iloc[-1], freq=step)
    gaps = d.diff().dropna()
    rows.append({
        "pair": pair.replace("_", "/"), "tf": tf,
        "first": d.iloc[0].strftime("%Y-%m-%d %H:%M"), "last": d.iloc[-1].strftime("%Y-%m-%d %H:%M"),
        "candles": len(d), "expected": len(full), "missing": len(full) - len(d),
        "longest_gap_h": round(gaps.max() / pd.Timedelta("1h"), 2) if len(gaps) else 0,
        "zero_vol_pct": round(100 * (df["volume"] == 0).mean(), 3),
    })

out = pd.DataFrame(rows)
out.to_csv(ROOT / "data" / "data_quality.csv", index=False)
pd.set_option("display.width", 200)
print(out.to_string(index=False))
