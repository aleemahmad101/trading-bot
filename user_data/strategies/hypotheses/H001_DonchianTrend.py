"""H-001: Donchian Trend Across Pairs (pre-registered 2026-11-11 04:06 UTC).

Vault note: Hypotheses/Open/H-001 Donchian Trend Across Pairs.md - rules are frozen there.

Rules, implemented exactly:
  * 4h candles, 18 dev pairs, each independent, long only.
  * Entry: close > highest HIGH of the previous 120 candles (20 days), current candle excluded.
  * Exit:  close < lowest LOW of the previous 60 candles (10 days), current candle excluded.
  * Fills at next candle open (Freqtrade default for signals).
  * No stoploss (-0.99, effectively off), ROI disabled, no trailing stop.
  * Sizing (run-time): max_open_trades = 18, stake_amount = "unlimited".

Implementation note: startup_candle_count = 121 because a 120-candle rolling max of the
*previous* candles (shift(1)) needs 121 rows before its first valid value. This does not
change any rule.
"""
from pandas import DataFrame
from freqtrade.strategy import IStrategy

ENTRY_LOOKBACK = 120  # 20 days of 4h candles
EXIT_LOOKBACK = 60    # 10 days of 4h candles


class H001_DonchianTrend(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False
    startup_candle_count = ENTRY_LOOKBACK + 1

    minimal_roi = {"0": 100.0}   # disabled
    stoploss = -0.99             # disabled (channel exit is the only exit)
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # shift(1): channel built only from candles BEFORE the current one
        dataframe["upper"] = dataframe["high"].rolling(ENTRY_LOOKBACK).max().shift(1)
        dataframe["lower"] = dataframe["low"].rolling(EXIT_LOOKBACK).min().shift(1)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] > dataframe["upper"], "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["close"] < dataframe["lower"], "exit_long"] = 1
        return dataframe
