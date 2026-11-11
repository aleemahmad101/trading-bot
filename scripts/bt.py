"""Single entry point for every backtest in this project.

Guarantees:
  * split dates come from splits.json (no hand-typed timeranges)
  * the locked test split is refused unless --unlock-test is passed AND the strategy
    has never been run on test before (checked against the ledger)
  * fees+slippage are always applied (default 0.0015/side, see vault note)
  * every run, including crashes, is appended to data/trial_ledger.csv and gets a
    note in the vault (Experiments/ or Baselines/)

Example:
  .venv/Scripts/python -I scripts/bt.py --kind baseline --id B-BTC-HOLD --strategy BuyAndHold \
      --split train --pairs BTC/USDT --max-open-trades 1 --reason "BTC buy-and-hold baseline"
"""
import argparse, csv, datetime as dt, io, json, subprocess, sys, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from exposure import exposure_metrics, illiquid_flag  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
VAULT = Path.home() / "Documents" / "Trading Research"
FT = ROOT / ".venv" / "Scripts" / "freqtrade.exe"
CONFIG = ROOT / "user_data" / "config.json"
LEDGER = ROOT / "data" / "trial_ledger.csv"
RESULTS = ROOT / "user_data" / "backtest_results"
SPLITS = json.loads((ROOT / "splits.json").read_text())
LEDGER_COLS = ["run_at", "id", "kind", "hypothesis", "variation", "strategy", "split", "timerange",
               "fee", "pairs", "timeframe_detail", "status", "total_trades", "profit_total_pct",
               "profit_factor", "wallet_max_dd_pct", "wallet_sharpe", "result_file", "reason",
               "time_in_market_pct", "avg_exposure_pct", "btc_matched_return_pct", "btc_matched_max_dd_pct",
               "illiquid_profit_share_pct"]


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True).stdout.strip() or "uncommitted"
    except Exception:
        return "unknown"


def git_dirty():
    r = subprocess.run(["git", "status", "--porcelain", "user_data/strategies", "scripts"], cwd=ROOT,
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def ledger_rows():
    if not LEDGER.exists():
        return []
    with open(LEDGER, newline="") as f:
        return list(csv.DictReader(f))


def append_ledger(row):
    new = not LEDGER.exists()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in LEDGER_COLS})


def pct(x, nd=2):
    return None if x is None else round(100 * x, nd)


def parse_result(zip_path, strategy):
    z = zipfile.ZipFile(zip_path)
    name = [n for n in z.namelist() if n.endswith(".json") and not n.endswith("_config.json")][0]
    s = json.loads(z.read(name))["strategy"][strategy]
    w = s.get("wallet_stats", {}) or {}
    out = {
        "total_trades": s["total_trades"],
        "win_rate": pct(s.get("winrate")),
        "profit_total_pct": pct(s.get("profit_total")),
        "cagr_pct": pct(s.get("cagr")),
        "profit_factor": round(s.get("profit_factor") or 0, 3),
        "expectancy_ratio": round(s.get("expectancy_ratio") or 0, 3),
        "closed_trade_max_dd_pct": pct(s.get("max_relative_drawdown")),
        "wallet_max_dd_pct": pct(w.get("max_relative_drawdown")),
        "wallet_sharpe": round(w["sharpe"], 3) if "sharpe" in w else None,
        "wallet_sortino": round(w["sortino"], 3) if "sortino" in w else None,
        "wallet_calmar": round(w["calmar"], 3) if "calmar" in w else None,
        "avg_duration": s.get("holding_avg"),
        "trades_per_day": round(s.get("trades_per_day") or 0, 3),
        "market_change_pct": pct(s.get("market_change")),
        "backtest_start": s.get("backtest_start"), "backtest_end": s.get("backtest_end"),
        "timeframe": s.get("timeframe"),
        "avg_profit_per_trade_pct": round(100 * (s.get("profit_mean") or 0), 3),
    }
    out.update(exposure_metrics(zip_path, strategy, s["backtest_start"], s["backtest_end"]))
    flag = illiquid_flag(s.get("results_per_pair", []), s.get("timeframe"), s.get("profit_total_abs") or 0,
                         s.get("starting_balance") or 10000)
    out["illiquid"] = flag
    return out


def yaml_val(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(f'"{x}"' for x in v) + "]"
    return f'"{v}"'


def write_note(a, meta, res, status, err_tail):
    folder = VAULT / ("Baselines" if a.kind == "baseline" else "Experiments")
    folder.mkdir(parents=True, exist_ok=True)
    note = folder / f"{a.id} {a.split}.md"
    fm = {
        "type": a.kind, "id": a.id, "hypothesis": f"[[{a.hypothesis}]]" if a.hypothesis else None,
        "variation": a.variation, "date": dt.date.today().isoformat(), "outcome": status,
        "split": a.split, "date_range": meta["timerange"], "timeframe": (res or {}).get("timeframe"),
        "timeframe_detail": a.timeframe_detail, "pairs": meta["pairs"], "pair_count": len(meta["pairs"]),
        "trading_mode": "spot", "strategy_class": a.strategy, "git_commit": meta["commit"],
        "freqtrade_version": meta["ft_version"], "fee_per_side": 0.001, "slippage_per_side": round(a.fee - 0.001, 6),
        "effective_fee": a.fee, "max_open_trades": a.max_open_trades,
        "result_file": meta.get("result_file"),
    }
    if res:
        fm.update({k: res[k] for k in ["total_trades", "win_rate", "profit_total_pct", "cagr_pct", "profit_factor",
                                       "wallet_max_dd_pct", "closed_trade_max_dd_pct", "wallet_sharpe",
                                       "wallet_sortino", "wallet_calmar", "avg_duration", "market_change_pct"]})
        fm["max_drawdown_pct"] = res["wallet_max_dd_pct"]   # dashboard column = wallet (mark-to-market) DD
        fm["sharpe"] = res["wallet_sharpe"]
        fm.update({k: res.get(k) for k in ["avg_profit_per_trade_pct", "time_in_market_pct", "avg_exposure_pct",
                                           "btc_matched_return_pct", "btc_matched_max_dd_pct", "btc_matched_sharpe"]})
        if res.get("illiquid"):
            fm["illiquid_5m_flag"] = True
            fm["illiquid_profit_share_pct"] = res["illiquid"]["illiquid_profit_share_pct"]
    fm["tags"] = [a.kind]
    lines = ["---"] + [f"{k}: {yaml_val(v)}" for k, v in fm.items()] + ["---", ""]
    lines += [f"# {a.id}: {a.strategy} on {a.split}", ""]
    if a.hypothesis:
        lines += [f"**Hypothesis:** [[{a.hypothesis}]]  ", f"**Variation:** {a.variation}  "]
    lines += [f"**Reason for this run:** {a.reason}", "", "## Command", "```bash", meta["cmd"], "```", ""]
    if res:
        lines += ["## Results (fees+slippage included)", "| Metric | Value |", "|---|---|",
                  f"| Total trades | {res['total_trades']} |", f"| Win rate | {res['win_rate']}% |",
                  f"| Total profit | {res['profit_total_pct']}% |", f"| CAGR | {res['cagr_pct']}% |",
                  f"| Profit factor | {res['profit_factor']} |",
                  f"| Max drawdown (wallet, mark-to-market) | {res['wallet_max_dd_pct']}% |",
                  f"| Max drawdown (closed trades only) | {res['closed_trade_max_dd_pct']}% |",
                  f"| Sharpe / Sortino / Calmar (daily wallet) | {res['wallet_sharpe']} / {res['wallet_sortino']} / {res['wallet_calmar']} |",
                  f"| Avg trade duration | {res['avg_duration']} |", f"| Trades per day | {res['trades_per_day']} |",
                  f"| Market change over period (avg of pairs) | {res['market_change_pct']}% |",
                  f"| Avg profit per trade (after costs) | {res['avg_profit_per_trade_pct']}% |",
                  f"| Backtested | {res['backtest_start']} → {res['backtest_end']} |", ""]
        if "avg_exposure_pct" in res:
            beat_ret = res["profit_total_pct"] > res["btc_matched_return_pct"]
            lines += ["## Exposure vs BTC hold at the same exposure",
                      "BTC benchmark = constant fraction of wallet in BTC equal to this run's average exposure, "
                      "rebalanced daily, no fees. Same average risk budget, no timing.", "",
                      "| | This run | BTC hold, exposure-matched | BTC hold, 100% |", "|---|---|---|---|",
                      f"| Time in market | {res['time_in_market_pct']}% | 100% | 100% |",
                      f"| Avg capital exposure | {res['avg_exposure_pct']}% | {res['avg_exposure_pct']}% | 100% |",
                      f"| Total return | {res['profit_total_pct']}% | {res['btc_matched_return_pct']}% | {res['btc_hold_return_pct']}% |",
                      f"| Max drawdown | {res['wallet_max_dd_pct']}% | {res['btc_matched_max_dd_pct']}% | {res['btc_hold_max_dd_pct']}% |",
                      f"| Sharpe (daily) | {res['wallet_sharpe']} | {res['btc_matched_sharpe']} | {res['btc_matched_sharpe']} |",
                      "", f"**Beats exposure-matched BTC on return:** {'yes' if beat_ret else 'no'}", ""]
        il = res.get("illiquid")
        if il:
            lines += ["> [!warning] Illiquid 5m pairs included (THETA/AXS/CHZ)",
                      f"> {il['illiquid_trades']} trades on {', '.join(il['illiquid_pairs_included'])}, "
                      f"contributing {il['illiquid_profit_abs']} USDT ({il['illiquid_profit_share_pct']}% of total profit).",
                      f"> Approx. total profit **without** them: {il['profit_total_pct_ex_illiquid']}% "
                      "(simple subtraction; ignores compounding and freed-up slots). Prefer re-running without these pairs.", ""]
    else:
        lines += ["## Run failed", "```", err_tail, "```", ""]
    lines += ["## Observations", a.notes or "", "", "## Raw output", f"`{meta.get('result_file')}`", ""]
    note.write_text("\n".join(lines), encoding="utf-8")
    return note


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--kind", choices=["baseline", "experiment"], required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--strategy", required=True)
    p.add_argument("--split", choices=["train", "validation", "test"], required=True)
    p.add_argument("--hypothesis", default="")
    p.add_argument("--variation", type=int, default=0)
    p.add_argument("--reason", required=True)
    p.add_argument("--notes", default="")
    p.add_argument("--pairs", nargs="*")
    p.add_argument("--max-open-trades", type=int, default=5)
    p.add_argument("--fee", type=float, default=0.0015)
    p.add_argument("--timeframe-detail")
    p.add_argument("--unlock-test", action="store_true")
    p.add_argument("--allow-dirty", action="store_true", help="allow uncommitted strategy/script changes")
    a = p.parse_args()

    if a.kind == "experiment" and not a.hypothesis:
        sys.exit("experiment runs must name --hypothesis")
    if a.split == "test":
        if not (a.unlock_test and SPLITS["test"].get("locked")):
            sys.exit("REFUSED: test split is locked. Phase 5 only, with --unlock-test.")
        if any(r["strategy"] == a.strategy and r["split"] == "test" for r in ledger_rows()):
            sys.exit(f"REFUSED: {a.strategy} has already had its one run on the test split.")
    if a.fee < 0.0015:
        sys.exit("REFUSED: fee below project minimum 0.0015/side (fee+slippage).")
    if "timeframe" in json.loads(CONFIG.read_text()):
        sys.exit("REFUSED: config.json sets 'timeframe', which silently overrides every strategy's own timeframe.")
    if git_dirty() and not a.allow_dirty:
        sys.exit("REFUSED: commit strategy/script changes first so the run is reproducible (or --allow-dirty).")

    timerange = SPLITS[a.split]["timerange"]
    out_dir = RESULTS / a.id / a.split
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(FT), "backtesting", "-c", str(CONFIG), "--userdir", str(ROOT / "user_data"),
           "-s", a.strategy, "--timerange", timerange, "--fee", str(a.fee),
           "--max-open-trades", str(a.max_open_trades), "--export", "trades", "--cache", "none",
           "--backtest-directory", str(out_dir), "--breakdown", "year"]
    if a.pairs:
        cmd += ["-p", *a.pairs]
    if a.timeframe_detail:
        cmd += ["--timeframe-detail", a.timeframe_detail]
    pairs = a.pairs or json.loads(CONFIG.read_text())["exchange"]["pair_whitelist"]
    ft_version = subprocess.run([str(FT), "--version"], capture_output=True, text=True).stdout
    ft_version = next((l.split()[-1] for l in ft_version.splitlines() if l.startswith("Freqtrade Version")), "?")
    meta = {"timerange": timerange, "pairs": pairs, "commit": git_commit(), "ft_version": ft_version,
            "cmd": " ".join(cmd[1:]).replace(str(ROOT) + "\\", "").replace(str(ROOT), ".")}

    before = set(out_dir.glob("*.zip"))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    (out_dir / "last_run.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")
    new = sorted(set(out_dir.glob("*.zip")) - before)
    res, status, err_tail = None, "failed", ""
    if proc.returncode == 0 and new:
        meta["result_file"] = str(new[-1].relative_to(ROOT))
        res, status = parse_result(new[-1], a.strategy), "completed"
    else:
        err_tail = "\n".join((proc.stdout + proc.stderr).splitlines()[-25:])
    note = write_note(a, meta, res, status, err_tail)
    append_ledger({"run_at": dt.datetime.now().isoformat(timespec="seconds"), "id": a.id, "kind": a.kind,
                   "hypothesis": a.hypothesis, "variation": a.variation, "strategy": a.strategy,
                   "split": a.split, "timerange": timerange, "fee": a.fee, "pairs": len(pairs),
                   "timeframe_detail": a.timeframe_detail or "", "status": status,
                   "total_trades": (res or {}).get("total_trades", ""),
                   "profit_total_pct": (res or {}).get("profit_total_pct", ""),
                   "profit_factor": (res or {}).get("profit_factor", ""),
                   "wallet_max_dd_pct": (res or {}).get("wallet_max_dd_pct", ""),
                   "wallet_sharpe": (res or {}).get("wallet_sharpe", ""),
                   "result_file": meta.get("result_file", ""), "reason": a.reason,
                   "time_in_market_pct": (res or {}).get("time_in_market_pct", ""),
                   "avg_exposure_pct": (res or {}).get("avg_exposure_pct", ""),
                   "btc_matched_return_pct": (res or {}).get("btc_matched_return_pct", ""),
                   "btc_matched_max_dd_pct": (res or {}).get("btc_matched_max_dd_pct", ""),
                   "illiquid_profit_share_pct": ((res or {}).get("illiquid") or {}).get("illiquid_profit_share_pct", "")})
    print(json.dumps({"status": status, "note": str(note), **(res or {"error": err_tail[-800:]})}, indent=1, default=str))


if __name__ == "__main__":
    main()
