#!/usr/bin/env python3
"""hermes_research_scope_audit.py — Read-only audit of how much Hermes researches and at what cost.

Same methodology as the Finviz/LLM governance work: measure first, then govern. Counts symbols
touched by source/window, LLM calls by lane (local GPU vs free-OAuth cloud vs paid), research with
no active trigger, duplicate/stale research, downstream outcome, and the top-25 most expensive
sources. Pure SELECTs — no writes, no broker calls, no LLM calls.

  python3 scripts/hermes_research_scope_audit.py --json
  python3 scripts/hermes_research_scope_audit.py --markdown > docs/HERMES_RESEARCH_SCOPE_AUDIT.md
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# Free-OAuth lanes (no paid key). Paid models flagged separately — they must never be a fallback.
FREE_OAUTH_MODELS = {"grok-3-mini", "gpt-5.4", "gpt-5-codex", "grok", "grok-3"}
PAID_MODELS = {"claude-sonnet-4-6", "claude-opus-4-8", "gpt-4o", "gpt-4-turbo"}
LOCAL_MODELS = {"gemma3:4b", "gemma3:12b", "gemma3:27b", "gemma4-31b", "qwen3:8b", "nomic-embed-text",
                "librarian_loop"}


def _exec(sql, p=None, fetch="all"):
    from db_adapter import _execute, USE_DB
    if not USE_DB:
        return None
    try:
        return _execute(sql, p, fetch=fetch)
    except Exception:
        return None


def _val(r):
    return (list(r.values())[0] if isinstance(r, dict) else r[0]) if r else 0


def _one(sql, p=None):
    return _val(_exec(sql, p, fetch="one"))


def _rows(sql, p=None):
    return _exec(sql, p, fetch="all") or []


def _lane_of_model(m):
    m = (m or "").lower()
    if m in {x.lower() for x in PAID_MODELS}:
        return "cloud_paid"
    if m in {x.lower() for x in FREE_OAUTH_MODELS} or m.startswith("grok") or m.startswith("gpt-"):
        return "cloud_free_oauth"
    if m in {x.lower() for x in LOCAL_MODELS} or m.startswith("gemma") or m.startswith("qwen"):
        return "local_gpu"
    return "other_nonllm"


def build():
    """Return the full audit dict. Read-only."""
    out = {"ok": True, "generated_at": None, "windows": {}, "by_source": {},
           "llm_by_lane": {}, "local_gpu": {}, "no_active_trigger": {}, "duplicate": {},
           "stale": {}, "downstream": {}, "top_expensive_sources": [], "findings": [],
           "note": "Read-only Hermes research scope audit. No writes, no broker calls, no LLM calls."}

    # 1) Symbols touched per window — external (cloud) + local intelligence
    for lbl, d in [("1d", "1 day"), ("7d", "7 days"), ("30d", "30 days")]:
        ext_rows = _one("SELECT COUNT(*) FROM hermes_external_research WHERE created_at>now()-interval %s", (d,))
        ext_sym = _one("SELECT COUNT(DISTINCT symbol) FROM hermes_external_research WHERE created_at>now()-interval %s AND symbol IS NOT NULL", (d,))
        loc_rows = _one("SELECT COUNT(*) FROM hermes_research_intelligence WHERE created_at>now()-interval %s", (d,))
        loc_sym = _one("SELECT COUNT(DISTINCT symbol) FROM hermes_research_intelligence WHERE created_at>now()-interval %s AND symbol IS NOT NULL", (d,))
        out["windows"][lbl] = {
            "external_calls": ext_rows, "external_distinct_symbols": ext_sym,
            "local_calls": loc_rows, "local_distinct_symbols": loc_sym,
            "total_calls": (ext_rows or 0) + (loc_rows or 0),
        }

    # 2) Current source-of-truth symbol counts (the trigger universe)
    src = {}
    src["holdings"] = _holdings_count()
    src["open_positions"] = src["holdings"]  # holdings mirror open positions in this system
    src["open_proposals"] = _one("SELECT COUNT(DISTINCT symbol) FROM paper_trade_proposals WHERE status IN ('pending','approved','open','active','proposed')")
    src["watchlist_items_active"] = _one("SELECT COUNT(DISTINCT symbol) FROM watchlist_items WHERE COALESCE(status,'') NOT IN ('removed','archived','sunset')")
    src["watchlist_high_rank(score>=70)"] = _one("SELECT COUNT(DISTINCT symbol) FROM watchlist_items WHERE score>=70 AND COALESCE(status,'') NOT IN ('removed','archived','sunset')")
    src["watch_directive_hits"] = _one("SELECT COUNT(DISTINCT symbol) FROM watch_directive_hits")
    src["incubator_universe"] = _one("SELECT COUNT(DISTINCT symbol) FROM incubator_universe WHERE COALESCE(status,'active')='active'")
    src["strategy_watchpool"] = _one("SELECT COUNT(DISTINCT symbol) FROM strategy_watchpool")
    src["finviz_hits(30d snapshot)"] = _one("SELECT COUNT(DISTINCT symbol) FROM ticker_snapshot_daily WHERE source ILIKE '%%finviz%%' AND snapshot_date>now()-interval '30 days'")
    src["ticker_snapshot_daily(30d,broad)"] = _one("SELECT COUNT(DISTINCT symbol) FROM ticker_snapshot_daily WHERE snapshot_date>now()-interval '30 days'")
    src["catalyst_events(30d)"] = _one("SELECT COUNT(DISTINCT symbol) FROM catalyst_events WHERE created_at>now()-interval '30 days'")
    src["news_articles(7d)"] = _one("SELECT COUNT(DISTINCT symbol) FROM news_articles WHERE published_at>now()-interval '7 days'")
    out["by_source"] = src

    # 3) LLM calls by lane (external 30d) + model
    lanes = {}
    for r in _rows("SELECT COALESCE(model,'(null)') m, COUNT(*) n, COUNT(DISTINCT symbol) sym FROM hermes_external_research WHERE created_at>now()-interval '30 days' GROUP BY 1"):
        lane = _lane_of_model(r["m"] if isinstance(r, dict) else r[0])
        n = r["n"] if isinstance(r, dict) else r[1]
        lanes.setdefault(lane, {"calls": 0, "models": {}})
        lanes[lane]["calls"] += n
        lanes[lane]["models"][r["m"] if isinstance(r, dict) else r[0]] = n
    # local intelligence model_used (30d)
    for r in _rows("SELECT COALESCE(model_used,'(null)') m, COUNT(*) n FROM hermes_research_intelligence WHERE created_at>now()-interval '30 days' GROUP BY 1"):
        m = r["m"] if isinstance(r, dict) else r[0]
        n = r["n"] if isinstance(r, dict) else r[1]
        lane = _lane_of_model(m)
        lanes.setdefault(lane, {"calls": 0, "models": {}})
        lanes[lane]["calls"] += n
        lanes[lane]["models"][m] = lanes[lane]["models"].get(m, 0) + n
    out["llm_by_lane"] = lanes
    out["local_gpu"] = {"calls_30d": lanes.get("local_gpu", {}).get("calls", 0),
                        "models": lanes.get("local_gpu", {}).get("models", {})}

    # 4) Researched with NO active trigger (30d)
    trigger = _trigger_symbol_set()
    researched = set()
    for r in _rows("SELECT DISTINCT symbol FROM hermes_external_research WHERE created_at>now()-interval '30 days' AND symbol IS NOT NULL"):
        researched.add((r["symbol"] if isinstance(r, dict) else r[0]).upper())
    for r in _rows("SELECT DISTINCT symbol FROM hermes_research_intelligence WHERE created_at>now()-interval '30 days' AND symbol IS NOT NULL"):
        researched.add((r["symbol"] if isinstance(r, dict) else r[0]).upper())
    no_trig = researched - trigger
    out["no_active_trigger"] = {
        "researched_distinct_30d": len(researched),
        "active_trigger_universe": len(trigger),
        "researched_with_no_trigger": len(no_trig),
        "pct": round(100 * len(no_trig) / max(1, len(researched)), 1),
        "sample": sorted(no_trig)[:25],
    }

    # 5) Duplicate research (external, 30d)
    dup_pairs = _one("SELECT COUNT(*) FROM (SELECT symbol,question,COUNT(*) c FROM hermes_external_research WHERE created_at>now()-interval '30 days' GROUP BY 1,2 HAVING COUNT(*)>1) x")
    redundant = _one("SELECT COALESCE(SUM(c-1),0) FROM (SELECT symbol,question,COUNT(*) c FROM hermes_external_research WHERE created_at>now()-interval '30 days' GROUP BY 1,2 HAVING COUNT(*)>1) x")
    out["duplicate"] = {"repeated_pairs": dup_pairs, "redundant_calls": redundant,
                        "pct_of_external": round(100 * (redundant or 0) / max(1, out["windows"]["30d"]["external_calls"]), 1)}

    # 6) Stale research — symbols whose most-recent research is aging
    stale = {}
    for r in _rows("SELECT CASE WHEN created_at>now()-interval '7 days' THEN 'fresh_0_7d' WHEN created_at>now()-interval '30 days' THEN 'aging_7_30d' ELSE 'stale_gt30d' END age, COUNT(DISTINCT symbol) sym FROM hermes_external_research GROUP BY 1"):
        stale[r["age"] if isinstance(r, dict) else r[0]] = r["sym"] if isinstance(r, dict) else r[1]
    out["stale"] = stale

    # 7) Downstream outcome
    down = {}
    for r in _rows("SELECT COALESCE(status,'(null)') st, COUNT(*) n, COUNT(*) FILTER (WHERE promoted_to_table IS NOT NULL) promoted FROM hermes_research_intelligence WHERE created_at>now()-interval '30 days' GROUP BY 1"):
        st = r["st"] if isinstance(r, dict) else r[0]
        down[st] = {"rows": r["n"] if isinstance(r, dict) else r[1], "promoted_to_table": r["promoted"] if isinstance(r, dict) else r[2]}
    out["downstream"] = down

    # 8) Top-25 most expensive sources (calls * lane-weight; cloud_paid heaviest, local light)
    weight = {"cloud_paid": 10, "cloud_free_oauth": 3, "local_gpu": 1, "other_nonllm": 0.2}
    expensive = []
    for r in _rows("SELECT COALESCE(trigger_reason,'(null)') t, COALESCE(model,'(null)') m, COUNT(*) n, COUNT(DISTINCT symbol) sym FROM hermes_external_research WHERE created_at>now()-interval '30 days' GROUP BY 1,2"):
        t = r["t"] if isinstance(r, dict) else r[0]
        m = r["m"] if isinstance(r, dict) else r[1]
        n = r["n"] if isinstance(r, dict) else r[2]
        sym = r["sym"] if isinstance(r, dict) else r[3]
        lane = _lane_of_model(m)
        expensive.append({"source": t, "lane": lane, "model": m, "calls": n, "symbols": sym,
                          "cost_units": round(n * weight.get(lane, 1), 1)})
    for r in _rows("SELECT COALESCE(research_type,'(null)') t, COALESCE(model_used,'(null)') m, COUNT(*) n, COUNT(DISTINCT symbol) sym FROM hermes_research_intelligence WHERE created_at>now()-interval '30 days' GROUP BY 1,2"):
        t = r["t"] if isinstance(r, dict) else r[0]
        m = r["m"] if isinstance(r, dict) else r[1]
        n = r["n"] if isinstance(r, dict) else r[2]
        sym = r["sym"] if isinstance(r, dict) else r[3]
        lane = _lane_of_model(m)
        expensive.append({"source": "hri:" + t, "lane": lane, "model": m, "calls": n, "symbols": sym,
                          "cost_units": round(n * weight.get(lane, 1), 1)})
    expensive.sort(key=lambda x: x["cost_units"], reverse=True)
    out["top_expensive_sources"] = expensive[:25]

    # Findings
    f = out["findings"]
    paid = lanes.get("cloud_paid", {}).get("calls", 0)
    if paid:
        f.append({"severity": "warning", "type": "paid_llm_calls",
                  "message": f"{paid} paid-model research calls in 30d ({lanes.get('cloud_paid',{}).get('models',{})}) — must be deliberate cost-gated oversight, never a fallback."})
    if (redundant or 0) > 0:
        f.append({"severity": "warning", "type": "duplicate_research",
                  "message": f"{redundant} redundant repeat external calls in 30d ({out['duplicate']['pct_of_external']}% of external) — dedup/expiry under-enforced."})
    biggest = expensive[0] if expensive else None
    if biggest and biggest["symbols"] > 200:
        f.append({"severity": "warning", "type": "broad_universe_llm",
                  "message": f"Source '{biggest['source']}' drove LLM research on {biggest['symbols']} symbols ({biggest['calls']} calls) — broad-universe LLM research; should be tiered/capped."})
    out["status"] = "WARN" if f else "PASS"
    return out


def _holdings_count():
    r = _exec("SELECT data FROM latest_holdings", fetch="one")
    if not r:
        return 0
    d = r["data"] if isinstance(r, dict) else r[0]
    try:
        if isinstance(d, str):
            d = json.loads(d)
    except Exception:
        return 0
    items = d if isinstance(d, list) else (d.get("holdings") or d.get("positions") or [])
    syms = set()
    for it in items:
        if isinstance(it, dict):
            s = (it.get("symbol") or it.get("ticker") or "").upper().strip()
            if s and s not in ("CASH", "USD", "$$CASH"):
                syms.add(s)
    return len(syms)


def _trigger_symbol_set():
    """Active-trigger universe: holdings + open proposals + active watchlist + directive hits + watchpool."""
    out = set()
    r = _exec("SELECT data FROM latest_holdings", fetch="one")
    if r:
        d = r["data"] if isinstance(r, dict) else r[0]
        try:
            if isinstance(d, str):
                d = json.loads(d)
            items = d if isinstance(d, list) else (d.get("holdings") or d.get("positions") or [])
            for it in items:
                if isinstance(it, dict):
                    s = (it.get("symbol") or it.get("ticker") or "").upper().strip()
                    if s and s not in ("CASH", "USD"):
                        out.add(s)
        except Exception:
            pass
    for sql in [
        "SELECT DISTINCT symbol FROM paper_trade_proposals WHERE status IN ('pending','approved','open','active','proposed')",
        "SELECT DISTINCT symbol FROM watchlist_items WHERE COALESCE(status,'') NOT IN ('removed','archived','sunset')",
        "SELECT DISTINCT symbol FROM watch_directive_hits",
        "SELECT DISTINCT symbol FROM strategy_watchpool",
    ]:
        for r in _rows(sql):
            v = r["symbol"] if isinstance(r, dict) else r[0]
            if v:
                out.add(str(v).upper().strip())
    return out


def to_markdown(d):
    L = []
    L.append("# Hermes Research Scope Audit")
    L.append("")
    L.append(f"_Status: **{d.get('status')}** — auto-generated by `scripts/hermes_research_scope_audit.py` (read-only)._")
    L.append("")
    L.append("Same governance methodology as the Finviz/LLM control plane: measure exactly how much "
             "Hermes researches and at what cost, then tier and cap it. All numbers below are live DB counts.")
    L.append("")
    L.append("## Symbols touched by window")
    L.append("")
    L.append("| Window | External (cloud) calls | External distinct symbols | Local calls | Local distinct symbols | Total calls |")
    L.append("|---|---|---|---|---|---|")
    for w in ("1d", "7d", "30d"):
        x = d["windows"].get(w, {})
        L.append(f"| {w} | {x.get('external_calls')} | {x.get('external_distinct_symbols')} | {x.get('local_calls')} | {x.get('local_distinct_symbols')} | {x.get('total_calls')} |")
    L.append("")
    L.append("## Current source-of-truth symbol counts (the trigger universe)")
    L.append("")
    L.append("| Source | Distinct symbols |")
    L.append("|---|---|")
    for k, v in d["by_source"].items():
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## LLM calls by lane (30d)")
    L.append("")
    L.append("| Lane | Calls | Models |")
    L.append("|---|---|---|")
    for lane, info in sorted(d["llm_by_lane"].items(), key=lambda x: -x[1]["calls"]):
        models = ", ".join(f"{m}:{n}" for m, n in sorted(info["models"].items(), key=lambda x: -x[1]))
        L.append(f"| {lane} | {info['calls']} | {models} |")
    L.append("")
    L.append(f"**Local GPU calls (30d):** {d['local_gpu']['calls_30d']}")
    L.append("")
    nt = d["no_active_trigger"]
    L.append("## Research with no active trigger (30d)")
    L.append("")
    L.append(f"- Distinct researched: **{nt['researched_distinct_30d']}**")
    L.append(f"- Active-trigger universe: **{nt['active_trigger_universe']}**")
    L.append(f"- Researched with NO active trigger: **{nt['researched_with_no_trigger']}** ({nt['pct']}%)")
    L.append(f"- Sample: {', '.join(nt['sample']) or '(none)'}")
    L.append("")
    du = d["duplicate"]
    L.append("## Duplicate research (30d)")
    L.append("")
    L.append(f"- Repeated (symbol, question) pairs: **{du['repeated_pairs']}**")
    L.append(f"- Redundant repeat calls (beyond first): **{du['redundant_calls']}** ({du['pct_of_external']}% of all external calls)")
    L.append("")
    L.append("## Stale research")
    L.append("")
    L.append("| Bucket | Distinct symbols |")
    L.append("|---|---|")
    for k, v in d["stale"].items():
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("## Downstream outcome (local intelligence, 30d)")
    L.append("")
    L.append("| Status | Rows | Promoted to table |")
    L.append("|---|---|---|")
    for st, info in sorted(d["downstream"].items(), key=lambda x: -x[1]["rows"]):
        L.append(f"| {st} | {info['rows']} | {info['promoted_to_table']} |")
    L.append("")
    L.append("## Top-25 most expensive sources (calls × lane weight)")
    L.append("")
    L.append("| # | Source | Lane | Model | Calls | Symbols | Cost units |")
    L.append("|---|---|---|---|---|---|---|")
    for i, e in enumerate(d["top_expensive_sources"], 1):
        L.append(f"| {i} | {e['source']} | {e['lane']} | {e['model']} | {e['calls']} | {e['symbols']} | {e['cost_units']} |")
    L.append("")
    if d.get("findings"):
        L.append("## Findings")
        L.append("")
        for f in d["findings"]:
            L.append(f"- **[{f['severity']}]** {f['message']}")
        L.append("")
    L.append("---")
    L.append("")
    L.append("_Read-only audit. No writes, no broker calls, no LLM calls. See "
             "`docs/HERMES_RESEARCH_BUDGET_POLICY.md` for the tiering that governs this scope._")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    a = ap.parse_args()
    d = build()
    if a.markdown:
        print(to_markdown(d))
    else:
        print(json.dumps(d, indent=2, default=str))


if __name__ == "__main__":
    main()
