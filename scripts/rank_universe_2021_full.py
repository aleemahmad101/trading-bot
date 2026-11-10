"""Survivorship check: rank ALL OKX USDT spot pairs that traded in early Nov 2021,
including ones delisted since, using OKX's own trade archives.

Source: static.okx.com/cdn/okex/traderecords/aggtrades/monthly/202111/allspot-aggtrades-YYYY-MM-DD.zip
Row format: instId, trade_id, side, size(base), price(quote), ts_ms
Window: 2021-11-03 .. 2021-11-09 (7 days, inside the original Oct 1 - Nov 10 ranking window).

Compares against today's live instruments and our chosen universe.
Output: data/universe_rank_2021_full.csv
"""
import csv, io, json, time, urllib.request, zipfile, datetime as dt
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "okx_aggtrades_2021"
OUT = ROOT / "data" / "universe_rank_2021_full.csv"
URL = "https://static.okx.com/cdn/okex/traderecords/aggtrades/monthly/202111/allspot-aggtrades-{d}.zip"
DAYS = [dt.date(2021, 11, 3) + dt.timedelta(days=i) for i in range(7)]
UA = {"User-Agent": "research-script/1.0"}
DEV = ["BTC", "ETH", "SOL", "XRP", "DOGE", "SHIB", "DOT", "FIL", "TRX", "AVAX", "ATOM", "AXS",
       "THETA", "BCH", "LINK", "LTC", "NEAR", "CHZ"]
HOLDOUT = ["XLM", "ETC", "ALGO", "UNI", "CRV", "GRT", "XTZ", "AAVE", "MANA", "EGLD"]


def get(path):
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request("https://www.okx.com" + path, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(2 * 2 ** attempt)
    raise RuntimeError("rate limited: " + path)


def fetch(day):
    dest = RAW / f"{day.isoformat()}.zip"
    if not (dest.exists() and dest.stat().st_size > 1_000_000):
        with urllib.request.urlopen(urllib.request.Request(URL.format(d=day.isoformat()), headers=UA), timeout=600) as r:
            dest.write_bytes(r.read())
    return dest


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    qvol, ntr = defaultdict(float), defaultdict(int)
    for day in DAYS:
        with zipfile.ZipFile(fetch(day)) as z:
            for name in z.namelist():
                with z.open(name) as fh:
                    for rec in csv.reader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace")):
                        if len(rec) < 6 or not rec[0].endswith("-USDT"):
                            continue
                        try:
                            qvol[rec[0]] += float(rec[3]) * float(rec[4]); ntr[rec[0]] += 1
                        except ValueError:
                            pass
        print("done", day, flush=True)
    live_spot = {i["instId"]: i for i in get("/api/v5/public/instruments?instType=SPOT")["data"]}
    # does today's listing (if any) still serve candles from Nov 2021? (detects reused tickers like LUNA)
    rows = []
    ranked = sorted(qvol.items(), key=lambda kv: -kv[1])
    for rank, (inst, v) in enumerate(ranked, 1):
        base = inst.split("-")[0]
        live = inst in live_spot and live_spot[inst]["state"] == "live"
        has_2021_history = ""
        if live and rank <= 60:
            d = get(f"/api/v5/market/history-candles?instId={inst}&bar=1Dutc&after=1636502400000&limit=2")["data"]
            has_2021_history = bool(d); time.sleep(0.6)
        rows.append({"rank": rank, "pair": inst, "quote_vol_usdt_7d": round(v), "trades": ntr[inst],
                     "live_today": live, "today_listing_has_2021_history": has_2021_history,
                     "in_universe": "dev" if base in DEV else ("holdout" if base in HOLDOUT else "")})
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    for r in rows[:50]:
        print(r)


if __name__ == "__main__":
    main()
