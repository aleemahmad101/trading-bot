"""Snapshot OKX's REST funding-rate history (rolling ~3-month window) before it rolls off.

The CDN archive ends 2025-09-07; this endpoint only keeps ~3 months, so each run should
be saved permanently. Output: data/funding/okx_funding_rates_api_<YYYYMMDD>.csv
(same columns as the archive table: date_utc, pair, rate, funding_rate, realized_rate)
"""
import csv, json, time, urllib.request, datetime as dt
from pathlib import Path
from fetch_okx_funding import PAIRS

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "research-script/1.0"}


def get(p):
    return json.load(urllib.request.urlopen(urllib.request.Request("https://www.okx.com" + p, headers=UA), timeout=20))


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


rows = []
for base in PAIRS:
    after = ""
    for _ in range(30):
        d = get(f"/api/v5/public/funding-rate-history?instId={base}-USDT-SWAP&limit=100" + (f"&after={after}" if after else ""))["data"]
        if not d:
            break
        for r in d:
            fr, rr = num(r.get("fundingRate")), num(r.get("realizedRate"))
            ts = int(r["fundingTime"])
            rows.append([dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                         f"{base}/USDT", rr if rr is not None else fr, "" if fr is None else fr, "" if rr is None else rr])
        after = d[-1]["fundingTime"]
        time.sleep(0.25)
rows.sort(key=lambda r: (r[1], r[0]))
out = ROOT / "data" / "funding" / f"okx_funding_rates_api_{dt.date.today():%Y%m%d}.csv"
with open(out, "w", newline="") as f:
    w = csv.writer(f); w.writerow(["date_utc", "pair", "rate", "funding_rate", "realized_rate"]); w.writerows(rows)
print(out, len(rows), rows[0][0] if rows else None, rows[-1][0] if rows else None)
