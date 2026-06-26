#!/usr/bin/env python3
"""hermes_subject_enhance.py — generic external-LLM (free Grok/ChatGPT OAuth) enhancement for any
subject across the site: proposals, open positions, closed trades, sectors, reports.

Reuses hermes_external_researcher.py (free OAuth lanes + hard $/secret redaction; advisory-only). Builds
a $-FREE, well-formatted context + a subject-specific question per item, calls the lane(s), and stores
the verdict in hermes_external_research with trigger_reason='enh_<type>' and symbol=<subject key>. The
generic endpoint /api/v2/hermes/subject-intel?type=&key= reads it back; surfaces reuse the badge/drawer
pattern. NEVER touches orders/stops/holdings.

  python3 scripts/hermes_subject_enhance.py --type position --lanes grok --apply [--limit N]
  types: proposal | position | closed_trade | sector | report | options_proposal
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
FRESH_HOURS = 12
SECTOR_ETF = {"Technology": "XLK", "Financials": "XLF", "Energy": "XLE", "Healthcare": "XLV",
              "Consumer Cyclical": "XLY", "Industrials": "XLI", "Consumer Defensive": "XLP",
              "Utilities": "XLU", "Real Estate": "XLRE", "Basic Materials": "XLB",
              "Communication Services": "XLC"}


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ── subject gatherers → list of {key, question} ($-FREE context only) ─────────────
def gather_proposal(conn, limit):
    cur = conn.cursor()
    cur.execute("""SELECT symbol, strategy_id strat, COALESCE(final_entry,proposed_entry) entry_price,
                     COALESCE(final_stop,proposed_stop) stop_loss,
                     COALESCE(final_target1,proposed_target1) target_price
                   FROM paper_trade_proposals
                   WHERE created_at > now()-interval '3 days'
                     AND COALESCE(status,'') NOT IN ('REJECTED','rejected','EXPIRED','expired','FILLED','filled')
                   ORDER BY created_at DESC LIMIT %s""", (limit,))
    out = []
    for r in _rows(cur):
        rr = None
        try:
            rr = round((float(r["target_price"]) - float(r["entry_price"])) / (float(r["entry_price"]) - float(r["stop_loss"])), 2)
        except Exception:
            pass
        out.append({"key": r["symbol"], "question":
            f"Challenge this PAPER trade proposal BEFORE approval (advisory, no capital figures). "
            f"{r['symbol']}, strategy {r['strat']}, entry {r['entry_price']}, stop {r['stop_loss']}, "
            f"target {r['target_price']}, R:R {rr}. Is the R:R realistic, what is the strongest bear case, "
            f"is the catalyst likely already priced in, and what single thing would invalidate the setup? "
            f"End: VERDICT: approve|caution|reject | CONVICTION: high|med|low."})
    return out


def gather_position(conn, limit):
    cur = conn.cursor()
    cur.execute("""SELECT t.symbol, t.strategy_id strat,
                     GREATEST(0, DATE_PART('day', now()-t.entry_time))::int days, wi.rsi, wi.trend
                   FROM paper_trades t LEFT JOIN watchlist_items wi ON wi.symbol=t.symbol
                   WHERE t.status='open' ORDER BY t.entry_time ASC LIMIT %s""", (limit,))
    out = []
    for r in _rows(cur):
        out.append({"key": r["symbol"], "question":
            f"Review this OPEN paper position (advisory, no dollar P&L). {r['symbol']}, strategy "
            f"{r.get('strat')}, held ~{r.get('days')} days, current RSI {r.get('rsi')}, trend {r.get('trend')}. "
            f"Is the thesis still intact — hold, trim into strength, or exit? What are the 2 biggest risks "
            f"now? End: VERDICT: hold|trim|exit | CONVICTION: high|med|low."})
    return out


def gather_closed_trade(conn, limit):
    cur = conn.cursor()
    cur.execute("""SELECT symbol, strategy_id strat, outcome_verdict outcome, signal_grade entry_grade,
                     GREATEST(0, DATE_PART('day', COALESCE(exit_time,closed_at)-entry_time))::int days
                   FROM paper_trades WHERE status IN ('closed','sold')
                   ORDER BY COALESCE(exit_time,closed_at) DESC LIMIT %s""", (limit,))
    out = []
    for r in _rows(cur):
        out.append({"key": r["symbol"], "question":
            f"Post-mortem this CLOSED paper trade (advisory, no dollar amounts). {r['symbol']}, strategy "
            f"{r.get('strat')}, outcome {r.get('outcome')}, entry grade {r.get('entry_grade')}, held "
            f"~{r.get('days')} days. What did we do right, what did we do wrong, and what is the ONE "
            f"repeatable lesson? End: LESSON: <one line>."})
    return out


def gather_sector(conn, limit):
    cur = conn.cursor()
    cur.execute("SELECT symbol, day_change_pct FROM market_quotes WHERE symbol='SPY' ORDER BY fetched_at DESC LIMIT 1")
    r = cur.fetchone(); spy = float(r[1]) if r and r[1] is not None else 0.0
    out = []
    for sec, etf in list(SECTOR_ETF.items())[:limit]:
        cur.execute("SELECT day_change_pct FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1", (etf,))
        rr = cur.fetchone()
        rel = (float(rr[0]) - spy) if rr and rr[0] is not None else None
        mom = "unknown" if rel is None else "leading" if rel > 0.15 else "lagging" if rel < -0.15 else "in-line"
        out.append({"key": f"SECTOR:{sec}", "question":
            f"Assess the {sec} sector ({etf}) for a swing/position trader right now: it is {mom} vs the S&P "
            f"today. Is it a tailwind or a headwind, what are the 1-2 key catalysts driving it, and which "
            f"sub-theme has the best setup? End: VERDICT: tailwind|neutral|headwind | CONVICTION: high|med|low."})
    return out


def gather_report(conn, limit):
    """Latest daily report summary, if a readable text report exists. Fuzzy/optional.
    Prefers the aegis morning-brief markdown / daily text summaries; skips directories and
    binary dashboard dumps (.html/.docx/.pdf) — the old glob picked the newest path by mtime,
    which became the `weekly/` directory and silently failed read_text(), zeroing the lane."""
    import glob, os
    patterns = [
        str(PROJECT_ROOT / "data" / "portfolios" / "reports" / "*aegis_morning_brief*.md"),
        str(PROJECT_ROOT / "data" / "reports" / "*daily*.md"),
        str(PROJECT_ROOT / "data" / "reports" / "*daily*.txt"),
        str(PROJECT_ROOT / "data" / "portfolios" / "reports" / "*daily*.md"),
        str(PROJECT_ROOT / "data" / "portfolios" / "reports" / "*.md"),
    ]
    cands = []
    for pat in patterns:
        cands = sorted([p for p in glob.glob(pat) if os.path.isfile(p)],
                       key=os.path.getmtime, reverse=True)
        if cands:
            break
    if not cands:
        return []
    try:
        txt = Path(cands[0]).read_text(errors="ignore")[:2500]
    except Exception:
        return []
    if not txt.strip():
        return []
    key = "REPORT:" + Path(cands[0]).stem[:40]
    return [{"key": key, "question":
        f"Second read on today's portfolio intelligence (advisory, ignore any dollar figures). Summary:\n{txt}\n"
        f"What is the single most important thing the operator should focus on tomorrow, and the one risk "
        f"being underweighted? End: FOCUS: <one line>."}][:limit]


def gather_options_proposal(conn, limit):
    """Top options desk proposals — advisory review before manual/auto route."""
    try:
        import options_engine as oe
        summary = oe.build_options_desk_summary()
    except Exception:
        return []
    out = []
    for p in (summary.get("top_proposals") or [])[:limit]:
        sym = p.get("symbol") or ""
        if not sym:
            continue
        out.append({"key": sym, "question":
            f"Review this OPTIONS desk proposal (advisory, no dollar figures). "
            f"{sym} · {p.get('strategy', '').replace('_', ' ')} · {p.get('option_type')} · "
            f"strike ${p.get('strike')} · edge {p.get('edge_score')} · POP {p.get('pop_pct')}%. "
            f"Is the strike/DTE sensible, is IV rank favorable, and what is the biggest assignment "
            f"or gap risk? End: VERDICT: route|caution|pass | CONVICTION: high|med|low."})
    return out


def gather_scalp(conn, limit):
    """gap-and-go / momentum-scalp candidates from the scalp scanner. READ-ONLY advisory context — does
    NOT touch the scalp screeners, the Bucket-1 fast path, or the scalp decision. Intraday-fresh."""
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, score, rvol, gap_pct, float_mm,
                     catalyst_verified, catalyst_confidence
                   FROM scalp_scan_results WHERE scanned_at > now()-interval '8 hours'
                   ORDER BY symbol, scanned_at DESC""")
    rows = sorted(_rows(cur), key=lambda r: -(r.get("score") or 0))[:limit]
    out = []
    for r in rows:
        out.append({"key": r["symbol"], "question":
            f"You are a fast momentum day-trader. {r['symbol']} hit our intraday scalp scanner: "
            f"RVOL {r.get('rvol')}x, gap {r.get('gap_pct')}%, float {r.get('float_mm')}M, catalyst "
            f"{'verified' if r.get('catalyst_verified') else 'unconfirmed'}. For a SAME-DAY gap-and-go / "
            f"momentum scalp: is this a clean setup or a trap? Biggest risk (halt, dilution/offering, "
            f"fade)? Ideal entry trigger and hard-stop logic? Be fast and specific. "
            f"End: VERDICT: go|wait|avoid | CONVICTION: high|med|low."})
    return out


GATHERERS = {"proposal": gather_proposal, "position": gather_position, "closed_trade": gather_closed_trade,
             "sector": gather_sector, "report": gather_report, "scalp": gather_scalp,
             "options_proposal": gather_options_proposal}
# scalp setups are intraday/time-sensitive → shorter freshness; the rest re-curate every 12h
FRESH_BY_TYPE = {"scalp": 4}


def _recent(conn, key, lane, ttype):
    cur = conn.cursor()
    cur.execute("""SELECT 1 FROM hermes_external_research WHERE symbol=%s AND lane=%s AND trigger_reason=%s
                   AND created_at > now()-interval '%s hours' AND status IN ('sent','ok','complete','success')
                   LIMIT 1""", (key, lane, f"enh_{ttype}", FRESH_BY_TYPE.get(ttype, FRESH_HOURS)))
    return cur.fetchone() is not None


def run(ttype, lanes=("grok",), apply=False, limit=20):
    conn = _conn()
    subjects = GATHERERS[ttype](conn, limit)
    rep = {"type": ttype, "subjects": len(subjects), "lanes": list(lanes), "called": 0, "skipped": 0}
    for s in subjects:
        for lane in lanes:
            if _recent(conn, s["key"], lane, ttype):
                rep["skipped"] += 1; continue
            if not apply:
                continue
            try:
                cp = subprocess.run(
                    [sys.executable, str(PROJECT_ROOT / "scripts" / "hermes_external_researcher.py"),
                     "--lane", lane, "--symbol", s["key"], "--question", s["question"],
                     "--trigger", f"enh_{ttype}", "--priority", "P2", "--apply"],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=240)
                rep["called"] += 1 if cp.returncode == 0 else 0
            except Exception:
                pass
    print(json.dumps(rep, indent=2))
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True, choices=list(GATHERERS))
    ap.add_argument("--lanes", default="grok")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()
    run(a.type, tuple(x.strip() for x in a.lanes.split(",") if x.strip()), a.apply, a.limit)


if __name__ == "__main__":
    main()
