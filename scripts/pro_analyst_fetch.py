#!/usr/bin/env python3
"""pro_analyst_fetch.py — Gate A: fetch Yahoo professional-analyst consensus for the ACTIONABLE universe.

ADVISORY/READ-ONLY (external Yahoo fetch). Yahoo analyst targets are the authoritative consensus
(recommendation_mean 1-5 + key + analyst count + targets), but were only fetched for held-portfolio symbols
(~36) — leaving scalp/watchlist/proposals uncovered (2/80). This fetches them for held + open trades + open
proposals + today GO/WAIT scalp + active watchlist, persisting via the existing
save_yahoo_analyst_targets_history. Skips ETF/fund-like symbols (no analyst coverage). No trades/scoring change.

  python3 scripts/pro_analyst_fetch.py [--max 80]
"""
import os, sys, json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2

_FIDELITY_PFX = ("FID-", "SS-", "TRP-", "JPM-", "VANG-", "WM-", "AB-", "SP500-", "CASH", "FCNTX")


def main():
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 80
    c = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                         dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                         password=os.getenv("DB_PASSWORD")); cur = c.cursor()
    cur.execute("""
        SELECT DISTINCT symbol FROM (
            SELECT symbol FROM paper_trades WHERE entry_time>now()-interval '30 days' AND symbol IS NOT NULL
            UNION SELECT symbol FROM paper_trade_proposals WHERE status IN('PENDING','APPROVED') AND symbol IS NOT NULL
            UNION SELECT symbol FROM trade_ai_scans WHERE run_date>=current_date AND decision IN('GO','WAIT') AND symbol IS NOT NULL
            UNION SELECT symbol FROM watchlist_items WHERE status='active' AND symbol IS NOT NULL
            -- operator directives are watch-grade regardless of lifecycle status (2026-06-12:
            -- CIFR/AXTI/DLR sat status='researched' and never got analyst pills)
            UNION SELECT symbol FROM watchlist_items
                  WHERE in_directive_watch=true AND status<>'removed' AND symbol IS NOT NULL
        ) u WHERE symbol ~ '^[A-Z]{1,5}$'""")
    syms = [r[0] for r in cur.fetchall() if not r[0].startswith(_FIDELITY_PFX)]
    c.close()
    # Also include HELD positions (2026-06-20): the SQL universe is watchlist/proposals/scans only, so held
    # stocks not also on the watchlist (TDG/NEE/DRS/KTOS) had no analyst consensus → the portfolio card's
    # analyst section was blank for them. Add holdings.json tickers so every held stock is covered.
    try:
        import json as _j, re as _re
        hj = _j.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        held = [str(h.get("symbol", "")).upper() for h in hj.get("holdings", [])
                if h.get("symbol") and not h.get("is_cash")
                and _re.fullmatch(r"[A-Z]{1,5}", str(h.get("symbol")).upper())
                and not str(h.get("symbol")).upper().startswith(_FIDELITY_PFX)]
        before = set(syms)
        for h in held:
            if h not in before:
                syms.append(h)
    except Exception as _e:
        print(f"  (holdings union skipped: {str(_e)[:60]})")
    # Rotate least-recently-ATTEMPTED first. The universe SELECT has no ORDER BY,
    # so `syms[:mx]` re-fetched the same arbitrary cap-full daily and starved the
    # rest (07-23 audit: 298 names stale >7d while the cron ran green). Attempts
    # are tracked in a state file because no-coverage names write no history row
    # and would otherwise hog every run.
    _attempts_path = ROOT / "data" / "runtime" / "pro_analyst_last_attempt.json"
    try:
        _attempts = json.loads(_attempts_path.read_text())
    except Exception:
        _attempts = {}
    syms.sort(key=lambda s: _attempts.get(s, ""))
    print(f"actionable symbols to fetch: {len(syms)} (cap {mx})")

    try:
        import yfinance as yf
        from db_adapter import save_yahoo_analyst_targets_history
    except Exception as e:
        print(f"ABORT: deps unavailable ({e})"); sys.exit(1)

    import time as _t
    date_str = datetime.now().strftime("%Y-%m-%d")
    payload, no_cov, errors = [], [], 0
    for s in syms[:mx]:
        _t.sleep(1.5)  # politeness — yfinance rate-limits bulk requests
        try:
            info = yf.Ticker(s).info
            tm = info.get("targetMeanPrice")
            nop = info.get("numberOfAnalystOpinions")
            if tm is None and not nop:
                no_cov.append(s); continue
            payload.append({"symbol": s, "current_price": info.get("currentPrice"),
                            "target_mean_price": tm, "target_high_price": info.get("targetHighPrice"),
                            "target_low_price": info.get("targetLowPrice"), "target_median_price": info.get("targetMedianPrice"),
                            "recommendation_mean": info.get("recommendationMean"),
                            "recommendation_key": info.get("recommendationKey"),
                            "number_of_analyst_opinions": nop})
        except Exception:
            no_cov.append(s)
    if payload:
        save_yahoo_analyst_targets_history(date_str, payload)
    try:
        _now_iso = datetime.now().isoformat(timespec="seconds")
        for s in syms[:mx]:
            _attempts[s] = _now_iso
        _attempts_path.parent.mkdir(parents=True, exist_ok=True)
        _attempts_path.write_text(json.dumps(_attempts, indent=0))
    except Exception as _e:
        print(f"  (attempt-state write skipped: {str(_e)[:60]})")
    print(json.dumps({"fetched_with_coverage": len(payload), "no_analyst_coverage": len(no_cov),
                      "no_coverage_sample": no_cov[:10]}, indent=2))


if __name__ == "__main__":
    main()
