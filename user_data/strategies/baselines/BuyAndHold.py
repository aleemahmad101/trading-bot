"""Buy-and-hold baselines (our own code, not from the reference repo).

BuyAndHold: enters every whitelisted pair on the first tradable candle and never
exits by signal/ROI/stop. Freqtrade force-closes open trades at the end of the
backtest, so final profit = buy-and-hold return minus one round trip of fees.

Run it as:
  - BTC only:  -p BTC/USDT  --max-open-trades 1
  - Basket:    all 18 dev pairs, --max-open-trades 18  -> equal-weight at entry
"""
from pandas import DataFrame
from freqtrade.strategy import IStrategy


class BuyAndHold(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    minimal_roi = {"0": 1000.0}   # effectively disabled
    stoploss = -0.99              # effectively disabled
    use_exit_signal = False
    process_only_new_candles = True
    startup_candle_count = 0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 1   # enters once; position is then held to the end
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe
