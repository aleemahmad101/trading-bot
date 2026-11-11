"""Exposure metrics + exposure-matched BTC benchmark, and the illiquid-5m-pair flag.

Exposure is computed from Freqtrade's per-candle wallet export (<result>_<Strategy>_wallet.feather):
for every timestamp, exposure = value held in coins / total wallet value.

  time_in_market_pct : % of wallet timestamps with exposure > 0
  avg_exposure_pct   : mean exposure over all timestamps (0-100)

Benchmark "BTC hold scaled to the same exposure": a constant fraction e = avg_exposure of the
wallet in BTC, rest in USDT, rebalanced daily (daily return = e * BTC daily return), no fees.
Sharpe is unchanged by constant scaling, so the comparison that matters is return and drawdown
at the same average risk budget. Sharpe here: daily returns, mean/std * sqrt(365).
"""
import io, zipfile
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
BTC_FILE = ROOT / "user_data" / "data" / "okx" / "BTC_USDT-1h.feather"
ILLIQUID_5M = ["THETA/USDT", "AXS/USDT", "CHZ/USDT"]


def _sharpe(daily):
    daily = daily.dropna()
    return float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else 0.0


def _max_dd(equity):
    return float((1 - equity / equity.cummax()).max())


def exposure_metrics(zip_path, strategy, start, end):
    z = zipfile.ZipFile(zip_path)
    wname = [n for n in z.namelist() if n.endswith(f"_{strategy}_wallet.feather")]
    if not wname:
        return {}
    w = pd.read_feather(io.BytesIO(z.read(wname[0])))
    w["date"] = pd.to_datetime(w["date"], utc=True)
    tot = w.groupby("date")["total_quote"].sum()
    coins = w[w["currency"] != "USDT"].groupby("date")["total_quote"].sum().reindex(tot.index, fill_value=0.0)
    expo = (coins / tot).clip(0, 1)
    e = float(expo.mean())

    btc = pd.read_feather(BTC_FILE)
    btc["date"] = pd.to_datetime(btc["date"], utc=True)
    s, t = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    h = btc.set_index("date").loc[s:t]
    # start from the price at the backtest start (first hourly open), then daily closes
    px = pd.concat([pd.Series([h["open"].iloc[0]], index=[s - pd.Timedelta("1s")]),
                    h["close"].resample("1D").last().dropna()])
    r = px.pct_change().dropna()
    scaled = (1 + e * r).cumprod()
    full = (1 + r).cumprod()

    # strategy daily wallet (for an apples-to-apples Sharpe on the same calendar)
    sw = tot.resample("1D").last().dropna()
    return {
        "time_in_market_pct": round(100 * float((expo > 1e-9).mean()), 2),
        "avg_exposure_pct": round(100 * e, 2),
        "btc_hold_return_pct": round(100 * float(full.iloc[-1] - 1), 2),
        "btc_hold_max_dd_pct": round(100 * _max_dd(full), 2),
        "btc_matched_return_pct": round(100 * float(scaled.iloc[-1] - 1), 2),
        "btc_matched_max_dd_pct": round(100 * _max_dd(scaled), 2),
        "btc_matched_sharpe": round(_sharpe(e * r), 3),
        "strategy_daily_sharpe_check": round(_sharpe(sw.pct_change()), 3),
    }


def illiquid_flag(per_pair, timeframe, total_profit_abs, start_balance):
    """For 5m runs that include THETA/AXS/CHZ: their profit contribution and the result without them."""
    if timeframe != "5m":
        return None
    rows = [r for r in per_pair if r.get("key") in ILLIQUID_5M]
    if not rows:
        return None
    contrib = sum(r["profit_total_abs"] for r in rows)
    trades = sum(r["trades"] for r in rows)
    return {
        "illiquid_pairs_included": [r["key"] for r in rows],
        "illiquid_trades": trades,
        "illiquid_profit_abs": round(contrib, 2),
        "illiquid_profit_share_pct": round(100 * contrib / total_profit_abs, 1) if total_profit_abs else None,
        "profit_total_pct_ex_illiquid": round(100 * (total_profit_abs - contrib) / start_balance, 2),
    }
