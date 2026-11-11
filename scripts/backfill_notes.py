"""Regenerate vault notes for EXISTING ledger runs from their saved result zips.

Used when new metrics are added to bt.py (e.g. exposure, 2026-11-10). Does NOT run any
backtest and does NOT add ledger rows, so trial counts are unchanged. Only rows with
status == completed are regenerated. Ledger exposure columns are filled in place.
"""
import argparse, csv, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util
spec = importlib.util.spec_from_file_location("bt", Path(__file__).resolve().parent / "bt.py")
bt = importlib.util.module_from_spec(spec); spec.loader.exec_module(bt)

rows = list(csv.DictReader(open(bt.LEDGER, newline="")))
cfg_pairs = __import__("json").loads(bt.CONFIG.read_text())["exchange"]["pair_whitelist"]
for r in rows:
    if r["status"] != "completed" or not r["result_file"]:
        continue
    zp = bt.ROOT / r["result_file"]
    res = bt.parse_result(zp, r["strategy"])
    pairs = ["BTC/USDT"] if r["pairs"] == "1" else cfg_pairs
    a = argparse.Namespace(kind=r["kind"], id=r["id"], strategy=r["strategy"], split=r["split"],
                           hypothesis=r["hypothesis"], variation=int(r["variation"] or 0), reason=r["reason"],
                           notes="(Note regenerated 2026-11-10 to add exposure metrics; no new backtest.)",
                           timeframe_detail=r["timeframe_detail"] or None, fee=float(r["fee"]),
                           max_open_trades=1 if r["pairs"] == "1" else (18 if "BASKET" in r["id"] else 5))
    cmd = f"backtesting -s {r['strategy']} --timerange {r['timerange']} --fee {r['fee']} --max-open-trades {a.max_open_trades}" \
          + (" -p BTC/USDT" if r["pairs"] == "1" else "") + (f" --timeframe-detail {a.timeframe_detail}" if a.timeframe_detail else "")
    meta = {"timerange": r["timerange"], "pairs": pairs, "commit": "374a16e", "ft_version": "2026.10",
            "cmd": cmd, "result_file": r["result_file"]}
    bt.write_note(a, meta, res, "completed", "")
    for k in ["time_in_market_pct", "avg_exposure_pct", "btc_matched_return_pct", "btc_matched_max_dd_pct"]:
        r[k] = res.get(k, "")
    r["illiquid_profit_share_pct"] = (res.get("illiquid") or {}).get("illiquid_profit_share_pct", "")
    print(r["id"], r["split"], {k: res.get(k) for k in ["profit_total_pct", "time_in_market_pct", "avg_exposure_pct",
                                                       "btc_matched_return_pct", "btc_matched_max_dd_pct", "wallet_max_dd_pct"]})
with open(bt.LEDGER, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=bt.LEDGER_COLS); w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in bt.LEDGER_COLS})
