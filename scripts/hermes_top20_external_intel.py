#!/usr/bin/env python3
"""hermes_top20_external_intel.py — curate the top-N Hermes-ranked watchlist names into a well-formatted
context and send each to the FREE external LLM lanes (ChatGPT via openai-codex OAuth + Grok via xAI) for
enhanced intelligence. Reuses hermes_external_researcher.py (auth, capability cache, storage to
hermes_external_research). ADVISORY — never trades.

Skips a (symbol, lane) pair already researched in the last FRESH_HOURS. Cadence via cron.

  python3 scripts/hermes_top20_external_intel.py [--top 20] [--lanes chatgpt,grok] [--apply]
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
from cio_agent_contract import contract_header
FRESH_HOURS = 12


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _named(conn, symbols):
    """Explicit symbol list (operator runs, e.g. 'all buy/strong_buy watchlist items' 2026-06-12)."""
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, hermes_rank, hermes_composite_score,
                     hermes_score_components, rsi, trend
                   FROM watchlist_items WHERE symbol = ANY(%s)
                   ORDER BY symbol, hermes_composite_score DESC""", (sorted({s.upper() for s in symbols}),))
    return [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]


def _top(conn, n):
    """Top-N by Hermes rank PLUS every operator-directive symbol regardless of rank (2026-06-12:
    CIFR #326 / DLR #1172 / AXTI #1627 never made the top-20 cut — operator standing instructions
    outrank scores)."""
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, hermes_rank, hermes_composite_score,
                     hermes_score_components, rsi, trend
                   FROM watchlist_items
                   WHERE (hermes_rank IS NOT NULL AND hermes_rank <= %s)
                      OR (in_directive_watch=true AND status<>'removed')
                   ORDER BY symbol, hermes_composite_score DESC""", (n,))
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    rows.sort(key=lambda r: (r["hermes_rank"] is None, r["hermes_rank"] or 0))
    return rows


def _question(r):
    c = r.get("hermes_score_components") or {}
    facs = "; ".join(f"{k}={v.get('score')}({v.get('detail')})" for k, v in c.items() if not k.startswith("_"))
    return (
        f"You are an elite equity analyst. {r['symbol']} ranks #{r['hermes_rank']} on our watchlist "
        f"(internal composite {r['hermes_composite_score']}/100, confidence {c.get('_confidence')}). "
        f"RSI {r.get('rsi')}, trend {r.get('trend')}. Factor reads — {facs}. "
        "Give ENHANCED intelligence, concise and specific (no boilerplate): "
        "(1) your conviction high/medium/low + a one-line thesis; "
        "(2) the 2-3 most important catalysts or risks we may be missing; "
        "(3) is the current trade setup valid — better entry / invalidation level; "
        "(4) any competitive or sector dynamic that changes the picture. "
        "End with a single line: VERDICT: <bullish|neutral|bearish> | CONVICTION: <high|med|low>. "
        f"{contract_header()} External researcher will parse tagged evidence + data_i_doubt from your analysis."
    )


def _recent(conn, symbol, lane):
    cur = conn.cursor()
    cur.execute("""SELECT 1 FROM hermes_external_research WHERE symbol=%s AND lane=%s
                   AND created_at > now() - interval '%s hours'
                   AND status IN ('sent','ok','complete','success') LIMIT 1""",
                (symbol, lane, FRESH_HOURS))
    return cur.fetchone() is not None


# Symbols actually held / proposed / under an active directive. Cached once per run so the budget
# guard can tier each candidate without a per-symbol round-trip.
def _trigger_context(conn):
    cur = conn.cursor()
    ctx = {"holdings": set(), "proposals": set(), "directive": set()}
    # held-symbol set from canonical holdings.json — the latest_holdings VIEW was retired
    # 2026-07-03 (it read the dead `holdings` table, frozen at 2026-04-19, so budget tiering
    # treated current positions as not-held for months).
    try:
        _hp = Path(__file__).resolve().parents[1] / "data" / "portfolios" / "state" / "holdings.json"
        d = json.loads(_hp.read_text()) if _hp.exists() else {}
        items = d if isinstance(d, list) else (d.get("holdings") or d.get("positions") or [])
        for it in items:
            if isinstance(it, dict) and not it.get("is_cash"):
                s = (it.get("symbol") or it.get("ticker") or "").upper().strip()
                if s and s not in ("CASH", "USD"):
                    ctx["holdings"].add(s)
    except Exception:
        pass
    for key, sql in [
        ("proposals", "SELECT DISTINCT symbol FROM paper_trade_proposals WHERE status IN ('pending','approved','open','active','proposed')"),
        ("directive", "SELECT DISTINCT symbol FROM watch_directive_hits"),
    ]:
        try:
            cur.execute(sql)
            for r in cur.fetchall():
                if r[0]:
                    ctx[key].add(str(r[0]).upper().strip())
        except Exception:
            pass
    return ctx


def _trigger_for(r, ctx):
    """Map a candidate row to (trigger_source, has_active_trigger) for the budget guard.
    Strongest trigger wins: held > proposed > directive > high-rank > broad."""
    sym = (r.get("symbol") or "").upper().strip()
    if sym in ctx["holdings"]:
        return "holdings", True
    if sym in ctx["proposals"]:
        return "open_proposal", True
    if sym in ctx["directive"]:
        return "active_directive", True
    score = r.get("hermes_composite_score") or 0
    rank = r.get("hermes_rank")
    if (score and score >= 70) or (rank is not None and rank <= 20):
        return "high_rank_watchlist", True
    # Everything else is broad-universe curation — metadata only, the guard will not call an LLM.
    return "top20_curation", False


def run(top=20, lanes=("chatgpt", "grok"), apply=False, symbols=None):
    conn = _conn()
    rows = _named(conn, symbols) if symbols else _top(conn, top)
    report = {"top": len(rows), "lanes": list(lanes), "called": 0, "skipped": 0,
              "metadata_only": 0, "deferred": 0, "blocked": 0, "detail": []}
    # Budget guard: broad-universe names get METADATA_ONLY (no cloud LLM); only held / proposed /
    # directive / high-rank names reach a free-OAuth lane. Eliminates the broad-universe LLM fan-out.
    try:
        from hermes_research_budget_guard import decide as _budget_decide, _load_policy as _load_bpol
        _bpol = _load_bpol()
        _tier_of = _bpol.get("trigger_source_tier", {})
    except Exception:
        _budget_decide = None
        _bpol, _tier_of = None, {}
    ctx = _trigger_context(conn)
    tier_count = {}            # per-tier symbols already ALLOWed this run -> enforces per-run caps
    for r in rows:
        q = _question(r)
        trig, has_trig = _trigger_for(r, ctx)
        tier = _tier_of.get(trig, "T3")
        for lane in lanes:
            recent = _recent(conn, r["symbol"], lane)
            decision = "ALLOW"
            if _budget_decide is not None:
                gd = _budget_decide(symbol=r["symbol"], trigger_source=trig,
                                    research_type="enhanced_intel", lane="cloud_" + lane,
                                    urgency="normal", has_active_trigger=has_trig, dedup_fresh=recent,
                                    symbols_this_run=tier_count.get(tier, 0))
                decision = gd["decision"]
                if decision == "ALLOW":
                    tier_count[tier] = tier_count.get(tier, 0) + 1
            elif recent:
                decision = "DEFER"
            if decision != "ALLOW":
                report[{"METADATA_ONLY": "metadata_only", "DEFER": "deferred",
                        "BLOCK": "blocked"}.get(decision, "skipped")] += 1
                report["detail"].append({"symbol": r["symbol"], "lane": lane, "trigger_source": trig,
                                         "budget_decision": decision})
                continue
            if not apply:
                report["detail"].append({"symbol": r["symbol"], "lane": lane,
                                         "trigger_source": trig, "budget_decision": "ALLOW",
                                         "action": "dry-run"})
                continue
            try:
                cp = subprocess.run(
                    [sys.executable, str(PROJECT_ROOT / "scripts" / "hermes_external_researcher.py"),
                     "--lane", lane, "--symbol", r["symbol"], "--question", q,
                     "--trigger", trig, "--priority", "P2", "--apply"],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=180)
                ok = cp.returncode == 0
                report["called"] += 1 if ok else 0
                report["detail"].append({"symbol": r["symbol"], "lane": lane, "ok": ok})
            except Exception as e:
                report["detail"].append({"symbol": r["symbol"], "lane": lane, "error": str(e)[:80]})
    print(json.dumps({k: report[k] for k in ("top", "lanes", "called", "skipped",
                                              "metadata_only", "deferred", "blocked")}, indent=2))
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--lanes", default="chatgpt,grok")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--symbols", help="explicit comma-separated symbol list (overrides --top)")
    a = ap.parse_args()
    run(top=a.top, lanes=tuple(x.strip() for x in a.lanes.split(",") if x.strip()), apply=a.apply,
        symbols=a.symbols.split(",") if a.symbols else None)


if __name__ == "__main__":
    main()
