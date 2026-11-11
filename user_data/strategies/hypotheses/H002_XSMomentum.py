"""H-002: Weekly Cross-Sectional Momentum Rotation (pre-registered 2026-11-11 04:06 UTC).

Vault note: Hypotheses/Open/H-002 Weekly Cross-Sectional Momentum Rotation.md - rules frozen there.

Rules, implemented exactly:
  * 4h candles, fixed 18-pair universe (hard-coded below so the ranking never depends on
    whatever pairlist a tool passes in).
  * Score = close / close 168 candles ago - 1  (28-day return), closed candles only.
  * Rebalance candle = the 4h candle that CLOSES at Monday 00:00 UTC, i.e. the candle whose
    open time ("date") is Sunday 20:00 UTC. Signals on it fill at Monday 00:00 open.
  * Entry: on a rebalance candle, rank <= 4 among the 18 by score AND score > 0.
  * Exit:  on a rebalance candle, rank > 4 OR score <= 0.  (Pairs still qualifying are kept.)
  * No stoploss (-0.99), ROI disabled.
  * Sizing (run-time): max_open_trades = 4, stake_amount = "unlimited".
  * Rank ties (identical score) broken by universe order (method="first").

Implementation note: startup_candle_count = 169 (a 168-candle-ago close needs 169 rows).
"""
import pandas as pd
from pandas import DataFrame
from freqtrade.strategy import IStrategy

LOOKBACK = 168   # 28 days of 4h candles
TOP_N = 4
UNIVERSE = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "SHIB/USDT",
            "DOT/USDT", "FIL/USDT", "TRX/USDT", "AVAX/USDT", "ATOM/USDT", "AXS/USDT",
            "THETA/USDT", "BCH/USDT", "LINK/USDT", "LTC/USDT", "NEAR/USDT", "CHZ/USDT"]


class H002_XSMomentum(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False
    startup_candle_count = LOOKBACK + 1

    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True

    def _rank_table(self) -> pd.DataFrame:
        """Wide table (date x pair) of rank by 28-day score, built from each pair's own candles."""
        scores = {}
        for p in UNIVERSE:
            df = self.dp.get_pair_dataframe(pair=p, timeframe=self.timeframe)
            if df is None or df.empty:
                continue
            s = df.set_index("date")["close"]
            scores[p] = s / s.shift(LOOKBACK) - 1.0
        wide = pd.DataFrame(scores)
        ranks = wide.rank(axis=1, ascending=False, method="first")
        return wide, ranks

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]
        dataframe["score"] = dataframe["close"] / dataframe["close"].shift(LOOKBACK) - 1.0
        wide, ranks = self._rank_table()
        if pair in ranks.columns:
            r = ranks[pair].rename("xs_rank")
            dataframe = dataframe.merge(r, left_on="date", right_index=True, how="left")
            dataframe["n_ranked"] = dataframe["date"].map(wide.notna().sum(axis=1))
        else:
            dataframe["xs_rank"] = float("nan")
            dataframe["n_ranked"] = 0
        d = dataframe["date"]
        dataframe["rebalance"] = (d.dt.dayofweek == 6) & (d.dt.hour == 20) & (d.dt.minute == 0)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = (dataframe["rebalance"] & (dataframe["xs_rank"] <= TOP_N)
                & (dataframe["score"] > 0) & (dataframe["n_ranked"] == len(UNIVERSE)))
        dataframe.loc[cond, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        cond = dataframe["rebalance"] & ((dataframe["xs_rank"] > TOP_N) | (dataframe["score"] <= 0))
        dataframe.loc[cond, "exit_long"] = 1
        return dataframe
