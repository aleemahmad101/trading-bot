"""Round-3 intraday signal studies (pre-registered protocol, Research Rules > Round 3 intraday).

Usage:  .venv/Scripts/python scripts/signal_study.py H-012|H-013|H-014 --id E-006

Protocol (frozen 2026-11-11 before any study ran):
  * Train split only, 1h candles, 18 dev pairs. Data outside train is cut off BEFORE anything is computed;
    events whose 24h forward window would leave train are dropped.
  * Signal on closed candle t; entry at open of t+1. Gross forward return at h in {1,4,12,24}:
        open(t+1+h) / open(t+1) - 1        (no fees)
  * No overlap: per pair, after an accepted event, events with entry < previous entry + 24h are ignored.
  * Random baseline: random entry candles from the same pair within train (same validity mask as the signal),
    10,000 draws of the same number of events.
  * Pass/fail at the hypothesis's PRIMARY horizon only:
        n >= 150  AND  mean gross > 0.60%  AND  day-clustered bootstrap p < 0.05 (mean excess over the
        pair-matched random-entry expectation; events grouped by UTC entry day, 10,000 resamples).
Each run is one trial: it is appended to data/trial_ledger.csv.
"""
import argparse, csv, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "user_data" / "data" / "okx"
SPLITS = json.loads((ROOT / "splits.json").read_text())
TRAIN_START = pd.Timestamp(SPLITS["train"]["start"], tz="UTC")
TRAIN_END = pd.Timestamp(SPLITS["train"]["end"], tz="UTC")          # exclusive
PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT", "SHIB/USDT", "DOT/USDT", "FIL/USDT",
         "TRX/USDT", "AVAX/USDT", "ATOM/USDT", "AXS/USDT", "THETA/USDT", "BCH/USDT", "LINK/USDT", "LTC/USDT",
         "NEAR/USDT", "CHZ/USDT"]
ILLIQUID = {"THETA/USDT", "AXS/USDT", "CHZ/USDT"}
HORIZONS = [1, 4, 12, 24]
SIG_WIN = 720
N_BOOT = 10_000
GATE = 0.006
SEED = 20261111

HYP = {
    "H-012": {"name": "H-012 Abnormal Up-Hour Continuation", "primary": 24},
    "H-013": {"name": "H-013 BTC-Leads-Alts Catch-Up", "primary": 4},
    "H-014": {"name": "H-014 Volatility-Squeeze Breakout", "primary": 24},
}


# ---------------------------------------------------------------- data
def load(pair: str) -> pd.DataFrame:
    df = pd.read_feather(DATA / f"{pair.replace('/', '_')}-1h.feather")
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df[(df["date"] >= TRAIN_START) & (df["date"] < TRAIN_END)]          # train only, before anything else
    grid = pd.date_range(TRAIN_START, TRAIN_END - pd.Timedelta(hours=1), freq="1h", tz="UTC")
    df = df.set_index("date").reindex(grid)                                   # gaps -> NaN, never bridged
    df.index.name = "date"
    assert df.index.max() < TRAIN_END
    return df[["open", "high", "low", "close", "volume"]]


def forward(df: pd.DataFrame) -> pd.DataFrame:
    entry = df["open"].shift(-1)
    return pd.DataFrame({h: df["open"].shift(-(1 + h)) / entry - 1.0 for h in HORIZONS}, index=df.index)


def sigma(df: pd.DataFrame) -> pd.Series:
    lr = np.log(df["close"] / df["close"].shift(1))
    return lr.rolling(SIG_WIN).std().shift(1)          # previous 720 candles, current excluded


def logret(df):
    return np.log(df["close"] / df["close"].shift(1))


def dedupe(times: pd.DatetimeIndex) -> pd.DatetimeIndex:
    keep, last = [], None
    for t in times.sort_values():
        if last is None or t >= last + pd.Timedelta(hours=24):
            keep.append(t); last = t
    return pd.DatetimeIndex(keep)


# ---------------------------------------------------------------- signals
def signals(hid: str, frames: dict):
    """Returns {pair: (signal bool Series, valid-mask bool Series)} and optional placebo dict of same shape."""
    out, placebo = {}, {}
    if hid == "H-012":
        for p, df in frames.items():
            s, r = sigma(df), logret(df)
            valid = s.notna() & r.notna()
            out[p] = ((r >= 3 * s) & valid, valid)
    elif hid == "H-013":
        b = frames["BTC/USDT"]; bs, br = sigma(b), logret(b)
        btc_jump = (br >= 3 * bs) & bs.notna() & br.notna()
        for p, df in frames.items():
            if p == "BTC/USDT":
                continue
            r = logret(df)
            valid = bs.notna() & br.notna() & r.notna()
            out[p] = (btc_jump & (r < 0.5 * br) & valid, valid)
            placebo[p] = (btc_jump & (r >= 0.5 * br) & valid, valid)
    elif hid == "H-014":
        for p, df in frames.items():
            hi24 = df["high"].rolling(24).max(); lo24 = df["low"].rolling(24).min()
            W = (hi24 - lo24) / df["close"]
            q = W.rolling(SIG_WIN).quantile(0.10).shift(1)          # previous 720 values of W, current excluded
            squeeze = W <= q
            prev_box_high = hi24.shift(1)                           # max high of the 24 candles before t
            brk = df["close"] > prev_box_high
            valid = q.shift(1).notna() & W.shift(1).notna() & prev_box_high.notna() & df["close"].notna()
            out[p] = (squeeze.shift(1, fill_value=False).astype(bool) & brk & valid, valid)
            placebo[p] = (~squeeze.shift(1, fill_value=False).astype(bool) & brk & valid, valid)
    return out, placebo


# ---------------------------------------------------------------- stats
def collect(sigs: dict, fwds: dict):
    rows, pools = [], {}
    for p, (sig, valid) in sigs.items():
        f = fwds[p]
        ok = valid & f[24].notna()                                     # 24h window must stay inside train
        pools[p] = f[ok]                                               # random-entry pool for this pair
        t = dedupe(sig[sig & ok].index)
        for ti in t:
            rows.append({"pair": p, "signal_time": ti, "entry_time": ti + pd.Timedelta(hours=1),
                         **{f"r{h}": f.at[ti, h] for h in HORIZONS}})
    ev = pd.DataFrame(rows)
    return ev, pools


def analyse(ev: pd.DataFrame, pools: dict, primary: int, rng) -> dict:
    res = {"n": int(len(ev)), "primary": primary, "horizons": {}}
    if ev.empty:
        return res
    ev = ev.copy()
    ev["day"] = ev["entry_time"].dt.floor("D")
    for h in HORIZONS:
        r = ev[f"r{h}"].to_numpy()
        mu_pair = {p: pools[p][h].mean() for p in pools}
        exp = ev["pair"].map(mu_pair).to_numpy()
        # random-entry distribution: same pair, same count, 10,000 draws
        rand_means = np.zeros(N_BOOT)
        for p, g in ev.groupby("pair"):
            pool = pools[p][h].to_numpy()
            idx = rng.integers(0, len(pool), size=(N_BOOT, len(g)))
            rand_means += pool[idx].sum(axis=1)
        rand_means /= len(ev)
        p_rand = float((rand_means >= r.mean()).mean())
        # day-clustered bootstrap of the excess over the pair-matched random expectation
        ex = pd.Series(r - exp).groupby(ev["day"].to_numpy())
        day_sum = ex.sum().to_numpy(); day_n = ex.count().to_numpy()
        obs = day_sum.sum() / day_n.sum()
        k = len(day_sum)
        idx = rng.integers(0, k, size=(N_BOOT, k))
        boot = day_sum[idx].sum(axis=1) / day_n[idx].sum(axis=1)
        p_clu = float(((boot - obs) >= obs).mean())
        res["horizons"][h] = {
            "mean": float(r.mean()), "median": float(np.median(r)), "win": float((r > 0).mean()),
            "random_mean": float(exp.mean()), "random_draw_p95": float(np.quantile(rand_means, 0.95)),
            "p_random_draw": p_rand, "excess": float(obs), "p_day_cluster": p_clu, "days": int(k),
        }
    hp = res["horizons"][primary]
    rp = ev[f"r{primary}"]
    pos_total = rp.sum()
    top = rp.sort_values(ascending=False).head(max(1, int(np.ceil(0.05 * len(rp))))).sum()
    res["top5pct_share_of_total"] = float(top / pos_total) if pos_total > 0 else None
    res["illiquid_share_of_total"] = float(rp[ev["pair"].isin(ILLIQUID)].sum() / pos_total) if pos_total > 0 else None
    res["by_year"] = {int(y): {"n": int(len(g)), "mean": float(g[f"r{primary}"].mean())}
                      for y, g in ev.groupby(ev["entry_time"].dt.year)}
    res["by_pair"] = {p: {"n": int(len(g)), "mean": float(g[f"r{primary}"].mean())} for p, g in ev.groupby("pair")}
    res["checks"] = {"n>=150": res["n"] >= 150, "mean>0.60%": hp["mean"] > GATE, "p_day_cluster<0.05": hp["p_day_cluster"] < 0.05}
    res["pass"] = all(res["checks"].values())
    return res


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hyp", choices=list(HYP))
    ap.add_argument("--id", required=True)
    ap.add_argument("--allow-dirty", action="store_true")
    a = ap.parse_args()

    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty and not a.allow_dirty:
        sys.exit(f"Refusing: uncommitted changes in trading-bot:\n{dirty}")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    rng = np.random.default_rng(SEED)
    frames = {p: load(p) for p in PAIRS}
    fwds = {p: forward(df) for p, df in frames.items()}
    sigs, plac = signals(a.hyp, frames)
    ev, pools = collect(sigs, fwds)
    res = analyse(ev, pools, HYP[a.hyp]["primary"], rng)
    if plac:
        pev, ppools = collect(plac, fwds)
        res["placebo"] = analyse(pev, ppools, HYP[a.hyp]["primary"], rng)
    res.update({"id": a.id, "hypothesis": HYP[a.hyp]["name"], "commit": commit,
                "train": [str(TRAIN_START), str(TRAIN_END)], "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "missing_candles": {p: int(df["open"].isna().sum()) for p, df in frames.items()}})

    outdir = ROOT / "data" / "signal_studies"; outdir.mkdir(exist_ok=True)
    (outdir / f"{a.id}.json").write_text(json.dumps(res, indent=2, default=str))
    ev.to_csv(outdir / f"{a.id}_events.csv", index=False)

    hp = res["horizons"].get(res["primary"], {})
    ledger = ROOT / "data" / "trial_ledger.csv"
    with ledger.open(newline="") as fh:
        cols = next(csv.reader(fh))
    row = {c: "" for c in cols}
    row.update({"run_at": res["run_at"][:19], "id": a.id, "kind": "signal_study", "hypothesis": res["hypothesis"],
                "variation": 0, "strategy": "scripts/signal_study.py", "split": "train",
                "timerange": SPLITS["train"]["timerange"], "fee": 0, "pairs": len(sigs), "status": "completed",
                "total_trades": res["n"], "result_file": f"data/signal_studies/{a.id}.json",
                "reason": (f"Signal study (gross, no fees). Primary {res['primary']}h: mean {hp.get('mean', float('nan'))*100:.3f}%, "
                           f"p_day_cluster {hp.get('p_day_cluster', float('nan')):.4f}. {'PASS' if res.get('pass') else 'FAIL'}")})
    with ledger.open("a", newline="") as fh:
        csv.DictWriter(fh, fieldnames=cols).writerow(row)

    print(json.dumps({k: res[k] for k in ("id", "hypothesis", "n", "primary", "horizons", "checks", "pass",
                                          "top5pct_share_of_total", "illiquid_share_of_total", "by_year")}, indent=1, default=str))
    if "placebo" in res:
        pl = res["placebo"]
        print("PLACEBO n", pl["n"], "primary mean", pl["horizons"].get(res["primary"], {}).get("mean"))


if __name__ == "__main__":
    main()
