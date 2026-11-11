"""Survivorship stress test (user rule for H-004): double the size of the worst 5% of trades.

Post-processes a saved backtest result - no new backtest, no new trial.
Method: take the worst 5% of trades by profit ratio; their USDT P&L is counted twice
(as if the position had been 2x). The extra P&L is applied to the daily wallet equity
from each trade's close date onward, then total return, max drawdown and daily Sharpe
are recomputed. Compounding effects on later stakes are ignored (rough stress, by design).

Usage: python -I scripts/stress_worst5.py <result.zip> <StrategyName>
"""
import io, json, math, sys, zipfile
import numpy as np
import pandas as pd


def main(zp, strat):
    z = zipfile.ZipFile(zp)
    s = json.loads(z.read([n for n in z.namelist() if n.endswith(".json") and not n.endswith("_config.json")][0]))["strategy"][strat]
    tr = pd.DataFrame(s["trades"])
    tr["close"] = pd.to_datetime(tr["close_date"], utc=True)
    n = max(1, math.ceil(0.05 * len(tr)))
    worst = tr.nsmallest(n, "profit_ratio")
    w = pd.read_feather(io.BytesIO(z.read([x for x in z.namelist() if x.endswith(f"_{strat}_wallet.feather")][0])))
    w["date"] = pd.to_datetime(w["date"], utc=True)
    eq = w.groupby("date")["total_quote"].sum().resample("1D").last().dropna()
    extra = pd.Series(0.0, index=eq.index)
    for _, t in worst.iterrows():
        extra[extra.index >= t["close"].normalize()] += t["profit_abs"]
    stressed = eq + extra
    start = s["starting_balance"]

    def stats(e):
        r = e.pct_change().dropna()
        return {"total_return_pct": round(100 * (e.iloc[-1] / start - 1), 2),
                "max_dd_pct": round(100 * float((1 - e / e.cummax()).max()), 2),
                "sharpe": round(float(r.mean() / r.std() * np.sqrt(365)), 3) if r.std() > 0 else 0.0}
    out = {"n_trades": len(tr), "n_doubled": n, "worst_trades_profit_abs": round(worst["profit_abs"].sum(), 2),
           "worst_trades_min_ratio_pct": round(100 * worst["profit_ratio"].min(), 2),
           "worst_trades_max_ratio_pct": round(100 * worst["profit_ratio"].max(), 2),
           "as_run": stats(eq), "stressed": stats(stressed)}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
