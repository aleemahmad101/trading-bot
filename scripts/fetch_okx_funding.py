"""Download OKX historical funding-rate archives (daily zips) and build a clean table.

Why: OKX's REST API only serves ~3 months of funding history, and Freqtrade's
docs note OKX futures backtests deviate before that. OKX publishes daily archive
files (CDN) going back years; we use those.

Archive row format (no header): instId, instType, funding_rate, realized_rate, funding_time_ms
funding_time_ms = settlement time (UTC). A settled rate is only KNOWN at/after this
timestamp -> any strategy must align it so it is usable only from that candle onward.

Usage: python -I scripts/fetch_okx_funding.py 2021-11-10 2026-11-09
Outputs:
  data/raw/okx_funding/YYYY-MM-DD.zip   (raw archives, untouched)
  data/funding/okx_funding_rates.csv    (date_utc, pair, funding_rate, realized_rate)
  data/funding/missing_days.txt
"""
import csv, io, sys, time, zipfile, urllib.request, urllib.error, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "okx_funding"
OUT = ROOT / "data" / "funding"
URL = "https://static.okx.com/cdn/okex/traderecords/swaprate/monthly/{ym}/allswaprate-swaprate-{d}.zip"
PAIRS = ["BTC", "ETH", "SOL", "XRP", "DOGE", "SHIB", "DOT", "FIL", "TRX", "AVAX", "ATOM",
         "AXS", "THETA", "BCH", "LINK", "LTC", "NEAR", "CHZ",
         # Phase 5 holdout pairs
         "XLM", "ETC", "ALGO", "UNI", "CRV", "GRT", "XTZ", "AAVE", "MANA", "EGLD"]
WANT = {f"{p}-USDT-SWAP": f"{p}/USDT" for p in PAIRS}


def fetch(day: dt.date) -> Path | None:
    dest = RAW / f"{day.isoformat()}.zip"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = URL.format(ym=day.strftime("%Y%m"), d=day.isoformat())
    req = urllib.request.Request(url, headers={"User-Agent": "research-script/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                dest.write_bytes(r.read())
            return dest
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    return None


def main(start: str, end: str):
    RAW.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    rows, missing, bad = {}, [], []
    day = d0
    while day <= d1:
        p = fetch(day)
        if p is None:
            missing.append(day.isoformat())
        else:
            try:
                with zipfile.ZipFile(p) as z:
                    for name in z.namelist():
                        text = z.read(name).decode("utf-8", "replace")
                        for rec in csv.reader(io.StringIO(text)):
                            if len(rec) < 5 or rec[0] not in WANT:
                                continue
                            def num(s):
                                try:
                                    return float(s)
                                except ValueError:
                                    return None
                            try:
                                ts = int(rec[4])
                            except ValueError:
                                bad.append(f"{day.isoformat()} {rec}")
                                continue
                            fr, rr = num(rec[2]), num(rec[3])
                            if fr is None and rr is None:
                                bad.append(f"{day.isoformat()} {rec}")
                                continue
                            rows[(WANT[rec[0]], ts)] = (fr, rr)
            except zipfile.BadZipFile:
                missing.append(day.isoformat() + " (bad zip)")
        day += dt.timedelta(days=1)
        time.sleep(0.05)
    with open(OUT / "okx_funding_rates.csv", "w", newline="") as f:
        w = csv.writer(f)
        # rate = realized (actually settled) rate when present, else quoted funding_rate
        w.writerow(["date_utc", "pair", "rate", "funding_rate", "realized_rate"])
        for (pair, ts), (fr, rr) in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            rate = rr if rr is not None else fr
            w.writerow([dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                        pair, rate, "" if fr is None else fr, "" if rr is None else rr])
    (OUT / "missing_days.txt").write_text("\n".join(missing))
    (OUT / "unparseable_rows.txt").write_text("\n".join(bad))
    print(f"rows={len(rows)} missing_days={len(missing)} unparseable_rows={len(bad)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
