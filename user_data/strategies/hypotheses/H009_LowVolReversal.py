"""H-009: Low-Volume Daily Reversal (pre-registered 2026-11-11 07:21 UTC, round 2 - final round).

Vault note: Hypotheses/Open/H-009 Low-Volume Daily Reversal.md - rules frozen there.

Rules, implemented exactly:
  * 4h candles, fixed 18-pair universe (hard-coded), long only.
  * One decision per day on the 4h candle that CLOSES at 00:00 UTC (opens 20:00 UTC); fills at 00:00 open.
  * R  = close / close 6 candles earlier - 1             (previous 24h, closed candles)
  * V  = sum over last 6 candles of volume * close       (daily quote volume)
  * AV = V / mean(V on the previous 30 decision days)    (today excluded)
  * Low-volume set = coins with AV strictly below the cross-sectional median of the 18.
  * Selected = the 3 lowest R within the low-volume set (ties: universe order).
  * Entry: selected and not held.  Exit: at a decision candle, held coin not selected.
  * No stoploss (-0.99), ROI disabled.
  * Sizing (run-time): max_open_trades = 3, stake_amount = "unlimited".
Implementation: decisions require all 18 coins to have R and AV (warm-up only).
startup_candle_count = 192 (31 days x 6 candles + 6).
"""
import pandas as pd
from pandas import DataFrame
from freqtrade.strategy import IStrategy

K = 3
VOL_BASE_DAYS = 30
UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "SHIB/USDT",
            "DOT/USDT", "FIL/USDT", "TRX/USDT", "AVAX/USDT", "ATOM/USDT", "AXS/USDT",
            "THETA/USDT", "BCH/USDT", "LINK/USDT", "LTC/USDT", "NEAR/USDT", "CHZ/USDT"]


def selection_table(frames: dict) -> pd.DataFrame:
    """date (decision candle open time) x pair -> True if selected. Shared with the manual check."""
    R, AV = {}, {}
    for p, df in frames.items():
        d = df.set_index("date")
        r = d["close"] / d["close"].shift(6) - 1.0
        v = (d["volume"] * d["close"]).rolling(6).sum()
        dec = d.index[(d.index.hour == 20) & (d.index.minute == 0)]
        vd = v.loc[dec]
        av = vd / vd.shift(1).rolling(VOL_BASE_DAYS).mean()
        R[p] = r.loc[dec]
        AV[p] = av
    R, AV = pd.DataFrame(R), pd.DataFrame(AV)
    ok = R.notna().all(axis=1) & AV.notna().all(axis=1)
    med = AV.median(axis=1)
    low = AV.lt(med, axis=0)
    r_low = R.where(low)
    rank = r_low.rank(axis=1, ascending=True, method="first")
    sel = (rank <= K) & low
    sel = sel.where(ok, False).astype(bool)
    return sel


class H009_LowVolReversal(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False
    startup_candle_count = 192

    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        frames = {p: self.dp.get_pair_dataframe(pair=p, timeframe=self.timeframe)[["date", "close", "volume"]]
                  for p in UNIVERSE}
        sel = selection_table(frames)
        pair = metadata["pair"]
        d = dataframe["date"]
        dataframe["decision"] = (d.dt.hour == 20) & (d.dt.minute == 0)
        s = sel[pair].rename("selected") if pair in sel.columns else pd.Series(dtype=bool, name="selected")
        dataframe = dataframe.merge(s, left_on="date", right_index=True, how="left")
        dataframe["selected"] = dataframe["selected"].fillna(False).astype(bool)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["decision"] & dataframe["selected"], "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["decision"] & ~dataframe["selected"], "exit_long"] = 1
        return dataframe
