"""H-008: Turn-of-the-Month Hold (pre-registered 2026-11-11 07:21 UTC, round 2 - final round).

Vault note: Hypotheses/Open/H-008 Turn-of-the-Month Hold.md - rules frozen there.

Rules, implemented exactly:
  * 4h candles, 18 dev pairs, each independent, long only.
  * Entry at 00:00 UTC on the LAST calendar day of each month: the signal is set on the 4h
    candle that closes at that moment (opens 20:00 UTC the day before) and fills at the 00:00 open.
  * Exit at 00:00 UTC on the 4th calendar day of the next month. Last day 00:00 + 96h is always
    the 4th at 00:00, so the exit is a 96h time exit (custom_exit fills at that candle's open).
  * No stoploss (-0.99), ROI disabled.
  * Sizing (run-time): max_open_trades = 18, stake_amount = "unlimited".
"""
from datetime import timedelta
import pandas as pd
from pandas import DataFrame
from freqtrade.strategy import IStrategy

HOLD = timedelta(hours=96)


class H008_TurnOfMonth(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "4h"
    can_short = False
    startup_candle_count = 1

    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        close_time = dataframe["date"] + pd.Timedelta(hours=4)          # when this candle closes
        is_midnight = (close_time.dt.hour == 0) & (close_time.dt.minute == 0)
        is_last_day = (close_time + pd.Timedelta(days=1)).dt.month != close_time.dt.month
        dataframe["tom_entry"] = is_midnight & is_last_day
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["tom_entry"], "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe  # time exit only

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if current_time - trade.open_date_utc >= HOLD:
            return "tom_end"
        return None
