# trading-bot

Code, configs and trial log for an honest edge-research project: **do simple, original, spot long-only crypto strategies built with [Freqtrade](https://www.freqtrade.io/) have a real edge after realistic costs?**

**Answer: no edge was found.** See the [Conclusion note](https://github.com/aleemahmad101/trading-research-vault/blob/main/Conclusion.md) in the research vault ([vault repo](https://github.com/aleemahmad101/trading-research-vault)).

## Rules the project ran under
- Backtests and Freqtrade dry-run only. No live trading, no real exchange API keys, no real money.
- Every backtest includes 0.10% taker fee + 0.05% slippage per side (`--fee 0.0015`).
- Every run is logged, failures included, in [`data/trial_ledger.csv`](data/trial_ledger.csv) and as a vault note.
- Hypotheses are pre-registered before coding; at most 5 variations, no hyperopt, never tuned before passing.
- Data split 60/20/20 by date: train 2021-11-10 → 2024-11-10, validation → 2025-11-10, locked test → 2026-11-09. The locked test is touched only once per surviving strategy.

## Setup
- Freqtrade 2026.10, Python 3.12, OKX spot data (5m/15m/1h/4h) for 18 USDT pairs plus a 10-pair holdout list.
- Funding rates from the OKX archive (`data/funding/`), used only for the coverage analysis.
- Pass bar: ≥150 train trades, profitable after costs, better wallet Sharpe than BTC buy-and-hold, and better than BTC held at the same average exposure.

## Results (train split)
| Hypothesis | Mechanism | Trades | Return | BTC at same exposure | Result |
|---|---|---|---|---|---|
| H-001 Donchian trend | Time-series trend | 302 | +20.3% | +21.5% | ❌ |
| H-002 Weekly cross-sectional momentum | Cross-sectional momentum | 180 | +2.5% | +49.1% | ❌ |
| H-004 Large hourly shock rebound | Overreaction reversal | 831 | −49.9% | +12.7% | ❌ |
| H-008 Turn-of-the-month hold | Calendar flows | 648 | −34.5% | +7.3% | ❌ |
| H-009 Low-volume daily reversal | Liquidity provision | 2,416 | −98.2% | +55.6% | ❌ |

5 hypothesis trials, 0 survivors. No validation or locked-test runs were made, so the locked test period is still clean. None of the 5 reference baselines beat BTC buy-and-hold either.

## Layout
| Path | Contents |
|---|---|
| `scripts/bt.py` | Single entry point for every backtest. Enforces the rules (fee floor, locked test, clean git tree, no config timeframe), writes the vault note and appends to the ledger. |
| `scripts/exposure.py`, `stress_worst5.py` | Time-in-market / exposure-matched BTC benchmark; worst-5%-doubled stress test. |
| `scripts/check_data.py`, `rank_universe*.py`, `fetch_okx_funding*.py` | Data quality, universe/survivorship ranking, funding download. |
| `user_data/strategies/hypotheses/` | The five hypothesis strategies, coded from the pre-registered notes. |
| `user_data/strategies/baselines/` | Buy-and-hold plus reference strategies from `freqtrade/freqtrade-strategies`. |
| `user_data/config.json`, `splits.json`, `holdout_pairs.json` | Backtest config (dry-run, empty keys), date splits, holdout pairs. |
| `data/trial_ledger.csv` | Every run, including invalidated ones. |

Not in the repo (see `.gitignore`): the virtualenv, raw and downloaded candle data, backtest result zips, and the reference strategy clone.

## Reproducing
```bash
python -m venv .venv && .venv/Scripts/pip install freqtrade
.venv/Scripts/freqtrade download-data --config user_data/config.json --timeframes 5m 15m 1h 4h --timerange 20211001-
python scripts/bt.py --help
```
