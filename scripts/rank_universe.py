"""Rank OKX USDT spot pairs by quote volume at the START of the data window.

Purpose: choose the pair universe using liquidity as it was in Oct-Nov 2021,
not today's (reduces survivorship / hindsight bias). Also flags whether each
pair still trades today and whether a USDT perpetual swap exists.
Output: data/universe_rank.csv
"""
import csv, json, time, urllib.request, datetime as dt
from pathlib import Path

BASE = "https://www.okx.com"
START = int(dt.datetime(2021, 10, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
END = int(dt.datetime(2021, 11, 10, tzinfo=dt.timezone.utc).timestamp() * 1000)
OUT = Path(__file__).resolve().parent.parent / "data" / "universe_rank.csv"


def get(path):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "research-script/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def main():
    spot = get("/api/v5/public/instruments?instType=SPOT")["data"]
    swaps = {i["instId"] for i in get("/api/v5/public/instruments?instType=SWAP")["data"]}
    pairs = [i for i in spot if i["quoteCcy"] == "USDT" and i["state"] == "live"]
    rows = []
    for i in pairs:
        inst = i["instId"]
        # daily candles ending before END; 'after' returns records older than ts
        d = get(f"/api/v5/market/history-candles?instId={inst}&bar=1Dutc&after={END}&limit=100")["data"]
        d = [c for c in d if int(c[0]) >= START]
        qvol = sum(float(c[7]) for c in d)
        rows.append({"pair": inst, "days": len(d), "quote_vol_usdt": round(qvol),
                     "has_swap": f"{i['baseCcy']}-USDT-SWAP" in swaps,
                     "list_time": i.get("listTime", "")})
        time.sleep(0.12)  # stay well under rate limits
    rows.sort(key=lambda r: -r["quote_vol_usdt"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    for r in rows[:35]:
        print(r)


if __name__ == "__main__":
    main()
