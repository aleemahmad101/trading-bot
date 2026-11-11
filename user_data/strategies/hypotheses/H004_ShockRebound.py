"""H-004: Large Hourly Shock Rebound (pre-registered 2026-11-11 04:06 UTC).

Vault note: Hypotheses/Open/H-004 Large Hourly Shock Rebound.md - rules frozen there.

Rules, implemented exactly:
  * 1h candles, 18 dev pairs, long only.
  * r = ln(close / close.shift(1)); sigma = std of r over the PREVIOUS 720 candles (current excluded).
  * Shock: r <= -3 * sigma.
  * Regime filter: BTC/USDT 1h close > BTC/USDT 200-day SMA (4800 1h candles), closed candles only.
  * Entry: shock AND regime filter. Fill at next candle open.
  * Exit: 24h after entry (custom_exit; Freqtrade fills it at the open of the candle on which it
    fires, i.e. exactly 24h), or stoploss -10% (with 5m timeframe-detail at run time).
  * Sizing (run-time): max_open_trades = 5, stake_amount = "unlimited".

Implementation note: startup_candle_count = 4800 (BTC 200-day SMA needs 4800 rows; the 721-row
sigma window is covered by it).
"""
from datetime import timedelta
import numpy as np
from pandas import DataFrame
from freqtrade.strategy import IStrategy

SIGMA_WINDOW = 720       # 30 days of 1h candles
SHOCK_SIGMAS = 3.0
SMA_WINDOW = 4800        # 200 days of 1h candles
HOLD = timedelta(hours=24)


class H004_ShockRebound(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short = False
    startup_candle_count = SMA_WINDOW

    minimal_roi = {"0": 100.0}
    stoploss = -0.10
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True

    def informative_pairs(self):
        return [("BTC/USDT", self.timeframe)]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["r"] = np.log(dataframe["close"] / dataframe["close"].shift(1))
        dataframe["sigma"] = dataframe["r"].rolling(SIGMA_WINDOW).std().shift(1)
        btc = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe=self.timeframe)[["date", "close"]].copy()
        btc["btc_sma"] = btc["close"].rolling(SMA_WINDOW).mean()
        btc = btc.rename(columns={"close": "btc_close"})
        dataframe = dataframe.merge(btc[["date", "btc_close", "btc_sma"]], on="date", how="left")
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        shock = dataframe["r"] <= -SHOCK_SIGMAS * dataframe["sigma"]
        regime = dataframe["btc_close"] > dataframe["btc_sma"]
        dataframe.loc[shock & regime, "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe  # only time exit and stoploss

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if current_time - trade.open_date_utc >= HOLD:
            return "time_24h"
        return None
