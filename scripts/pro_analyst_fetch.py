#!/usr/bin/env python3
"""pro_analyst_fetch.py — Gate A: fetch Yahoo professional-analyst consensus for the ACTIONABLE universe.

ADVISORY/READ-ONLY (external Yahoo fetch). Yahoo analyst targets are the authoritative consensus
(recommendation_mean 1-5 + key + analyst count + targets), but were only fetched for held-portfolio symbols
(~36) — leaving scalp/watchlist/proposals uncovered (2/80). This fetches them for held + open trades + open
proposals + today GO/WAIT scalp + active watchlist, persisting via the existing
save_yahoo_analyst_targets_history. Skips ETF/fund-like symbols (no analyst coverage). No trades/scoring change.

  python3 scripts/pro_analyst_fetch.py [--max 80] [--dry-run]

--dry-run builds the universe on a READ ONLY session and stops: no yfinance call, no
yahoo_analyst_targets_history write, no data_source_health report (AGENTS.md §6).
Exit 1 when every attempted symbol errored (was exit 0); no coverage without errors is a finding.

Fetch order (2026-10-20, analyst feed stale 87 days): the universe is ~2,340 symbols (2,299 of them
directive-watch rows) against a --max 250 cap. It used to be an unordered `SELECT DISTINCT` with held
positions appended LAST, then `syms[:mx]` -- so the same ~250 symbols were refetched every day and held
positions (NVDA/PFLT/SPCX last fetched 2026-07-25) were never reached. `prioritize()` now orders the
universe so the cap is spent on what is due: held first, then actionable (trades/proposals/today's
scans/active watchlist), then the directive-watch backlog oldest-fetch-first, then never-covered symbols
in a per-day rotation; anything fetched within DUE_AFTER_HOURS goes last.
"""
import os, sys, json, hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
for ln in (ROOT / ".env").read_text().splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("="); os.environ.setdefault(k.strip(), v.strip().strip("'\""))
import psycopg2

_FIDELITY_PFX = ("FID-", "SS-", "TRP-", "JPM-", "VANG-", "WM-", "AB-", "SP500-", "CASH", "FCNTX")

# A symbol fetched within this many hours is not due again (the lane runs daily at 06:10).
DUE_AFTER_HOURS = 20
# Priority tiers (lower = first). The SQL universe query returns each symbol with its best tier.
TIER_HELD, TIER_ACTIONABLE, TIER_DIRECTIVE = 0, 1, 2
TIER_NEVER_COVERED, TIER_NOT_DUE = 3, 4


def _aware(ts):
    return ts.replace(tzinfo=timezone.utc) if ts is not None and ts.tzinfo is None else ts


def is_due(last_fetched_at, now=None) -> bool:
    """True when a symbol has no row, or its newest row is older than DUE_AFTER_HOURS."""
    if last_fetched_at is None:
        return True
    now = now or datetime.now(timezone.utc)
    return _aware(last_fetched_at) < now - timedelta(hours=DUE_AFTER_HOURS)


def prioritize(tiers: dict, last_fetched: dict, now=None, today: str = "") -> list:
    """Order the fetch universe so `[:max]` spends the cap on what is due.

    tiers: {SYMBOL: TIER_HELD | TIER_ACTIONABLE | TIER_DIRECTIVE}
    last_fetched: {SYMBOL: tz-aware datetime of the newest yahoo_analyst_targets_history row}
    Order: held, actionable, directive-watch backlog (oldest fetch first), then symbols with no row at all
    (never covered by Yahoo -- most are ETFs/micro-caps with no analysts) in a per-day hash rotation so they
    cannot starve covered symbols, then everything fetched within DUE_AFTER_HOURS. Deterministic for a day.
    """
    now = now or datetime.now(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def key(sym):
        tier = tiers[sym]
        lf = _aware(last_fetched.get(sym))
        if not is_due(lf, now):
            return (TIER_NOT_DUE, tier, lf, sym)
        if lf is None and tier == TIER_DIRECTIVE:
            rot = hashlib.sha1(f"{today}:{sym}".encode()).hexdigest()
            return (TIER_NEVER_COVERED, tier, epoch, rot)
        return (tier, 0, lf or epoch, sym)

    return sorted(tiers, key=key)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    mx = int(argv[argv.index("--max") + 1]) if "--max" in argv else 80
    dry_run = "--dry-run" in argv
    c = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                         dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                         password=os.getenv("DB_PASSWORD"))
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly
        enforce_readonly(c)  # dry run: the server refuses any write (AGENTS.md §6)
    cur = c.cursor()
    cur.execute("""
        SELECT DISTINCT symbol, MIN(tier) OVER (PARTITION BY symbol) FROM (
            SELECT symbol, 1 AS tier FROM paper_trades WHERE entry_time>now()-interval '30 days' AND symbol IS NOT NULL
            UNION SELECT symbol, 1 FROM paper_trade_proposals WHERE status IN('PENDING','APPROVED') AND symbol IS NOT NULL
            UNION SELECT symbol, 1 FROM trade_ai_scans WHERE run_date>=current_date AND decision IN('GO','WAIT') AND symbol IS NOT NULL
            UNION SELECT symbol, 1 FROM watchlist_items WHERE status='active' AND symbol IS NOT NULL
            -- operator directives are watch-grade regardless of lifecycle status (2026-06-12:
            -- CIFR/AXTI/DLR sat status='researched' and never got analyst pills)
            UNION SELECT symbol, 2 FROM watchlist_items
                  WHERE in_directive_watch=true AND status<>'removed' AND symbol IS NOT NULL
        ) u WHERE symbol ~ '^[A-Z]{1,5}$'""")
    tiers = {}
    for r in cur.fetchall():
        if r[0].startswith(_FIDELITY_PFX):
            continue
        t = int(r[1]) if len(r) > 1 and r[1] is not None else TIER_DIRECTIVE
        tiers[r[0]] = min(t, tiers.get(r[0], t))
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
        for h in held:
            tiers[h] = TIER_HELD
    except Exception as _e:
        print(f"  (holdings union skipped: {str(_e)[:60]})")
    # Newest fetch per symbol, so the cap goes to what is due (2026-10-20: the unordered universe
    # refetched the same ~250 every day and held positions sat 87 days stale). Read-only SELECT.
    last_fetched = {}
    if tiers:
        try:
            cur.execute("""SELECT upper(symbol), max(created_at) FROM yahoo_analyst_targets_history
                           WHERE upper(symbol) = ANY(%s) GROUP BY 1""", (list(tiers),))
            last_fetched = {r[0]: r[1] for r in cur.fetchall() if r[1] is not None}
        except Exception as _e:
            print(f"  (last-fetch read skipped: {str(_e)[:60]})")
    c.close()
    syms = prioritize(tiers, last_fetched, today=datetime.now().strftime("%Y-%m-%d"))
    _due = sum(1 for s in syms if is_due(last_fetched.get(s)))
    _held = sum(1 for s in syms if tiers[s] == TIER_HELD)
    print(f"actionable symbols to fetch: {len(syms)} (cap {mx}; due {_due}; held {_held})")
    if dry_run:
        # returns before yfinance, save_yahoo_analyst_targets_history and report_source (AGENTS.md §6)
        _sel = syms[:mx]
        print(json.dumps({"dry_run": True, "would_fetch": len(_sel),
                          "would_fetch_sample": _sel[:10],
                          "held_in_batch": sum(1 for s in _sel if tiers[s] == TIER_HELD),
                          "actionable_in_batch": sum(1 for s in _sel if tiers[s] == TIER_ACTIONABLE),
                          "directive_in_batch": sum(1 for s in _sel if tiers[s] == TIER_DIRECTIVE),
                          "oldest_fetch_in_batch": min((str(last_fetched[s]) for s in _sel if s in last_fetched),
                                                       default=None),
                          "never_fetched_in_batch": sum(1 for s in _sel if s not in last_fetched)},
                         indent=2))
        return 0

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
        except Exception as e:
            no_cov.append(s); errors += 1; last_exc = str(e)[:160]
    if payload:
        save_yahoo_analyst_targets_history(date_str, payload)
    # Liveness (2026-09-13): this is the declared writer of analyst_opinion
    # (config/data_source_authority.json) and the only scheduled daily yfinance
    # call (cron `10 6 * * *`), yet the yahoo_finance health row was never touched
    # by it -- it read "healthy" on a 20-day-old success. Success == rows actually
    # persisted; every symbol erroring is a failure, not silence.
    try:
        from lib.data_source_report import report_source
        attempted = len(syms[:mx])
        if payload:
            report_source("yahoo_finance", True, rows=len(payload))
        elif attempted and errors >= attempted:
            report_source("yahoo_finance", False, rows=0,
                          error=f"{errors}/{attempted} symbols errored: {locals().get('last_exc', '')}")
        elif attempted:
            report_source("yahoo_finance", False, rows=0,
                          error=f"0/{attempted} symbols returned analyst coverage ({errors} errors)")
    except Exception:
        pass
    print(json.dumps({"fetched_with_coverage": len(payload), "no_analyst_coverage": len(no_cov),
                      "no_coverage_sample": no_cov[:10]}, indent=2))
    attempted = len(syms[:mx])
    # Every attempted symbol erroring is a failed run (was exit 0, hidden by the cron line's ';'
    # chain); symbols without analyst coverage are a finding. Evidence for the lane is the chain
    # receipt (run_pro_analyst_chain.py) plus the yahoo_finance data_source_health row above.
    return 1 if (attempted and errors >= attempted) else 0


if __name__ == "__main__":
    sys.exit(main())
