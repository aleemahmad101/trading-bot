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

Implementation notes:
  * Freqtrade refuses a startup_candle_count above 5x the exchange's per-call candle limit
    (OKX 1h: 1499). The BTC 200-day SMA (4800 1h candles) is therefore computed from the
    downloaded BTC/USDT 1h data file itself (rolling mean of PAST closes only, merged on date),
    so the rule is unchanged. startup_candle_count = 721 covers the sigma window.
  * Until 4800 BTC candles exist (data starts 2021-11-10), btc_sma is NaN, so there are no
    entries before ~2022-05-29 - same effective start as stated in the note.
  * Phase 6 (dry-run) would need this file kept up to date; noted for later.
"""
from datetime import timedelta
from pathlib import Path
import numpy as np
import pandas as pd
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
    startup_candle_count = SIGMA_WINDOW + 1
    _btc_cache = None

    minimal_roi = {"0": 100.0}
    stoploss = -0.10
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    process_only_new_candles = True

    def _btc_regime(self) -> DataFrame:
        if H004_ShockRebound._btc_cache is None:
            f = Path(self.config["datadir"]) / "BTC_USDT-1h.feather"
            btc = pd.read_feather(f)[["date", "close"]].sort_values("date")
            btc["date"] = pd.to_datetime(btc["date"], utc=True)
            btc["btc_sma"] = btc["close"].rolling(SMA_WINDOW).mean()   # past closes only
            H004_ShockRebound._btc_cache = btc.rename(columns={"close": "btc_close"})
        return H004_ShockRebound._btc_cache

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["r"] = np.log(dataframe["close"] / dataframe["close"].shift(1))
        dataframe["sigma"] = dataframe["r"].rolling(SIGMA_WINDOW).std().shift(1)
        dataframe = dataframe.merge(self._btc_regime()[["date", "btc_close", "btc_sma"]], on="date", how="left")
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
