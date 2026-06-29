#!/usr/bin/env python3
"""hermes_governance_api.py — read-only data for the Command Center v3 Hermes Governance panel.

Surfaces the research-scope audit + budget-guard posture so the operator can see, at a glance, how
much Hermes researches, by tier and lane, and what the budget guard is deferring/blocking.

Read-only. No writes, no broker calls, no LLM calls, no gate bypass.
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# Disk TTL cache — the summary runs the full research-scope audit (~3-4s of SELECTs), too heavy for
# the request path. Served from a pre-warmed cache like the other heavy endpoints (finviz-strip-map).
# `fresh=True` (route `?fresh=1`) forces recompute. Pre-warm via `--warm` on a cron out of band.
_CACHE_PATH = os.path.join(ROOT, "data", "runtime", "hermes_governance_cache.json")
_TTL_SEC = int(os.getenv("HERMES_GOV_TTL_SEC", "600"))  # 10 min

# trigger_reason / trigger_source -> tier (mirror of config/hermes_research_budget.yaml, for
# historical rows that pre-date the budget_tier column).
_TIER_HINT = {
    "holdings": "T0", "open_position": "T0", "open_positions": "T0", "enh_position": "T0",
    "open_proposal": "T0", "open_proposals": "T0", "proposal_review": "T0", "enh_closed_trade": "T0",
    "monthly_protection_meta_review": "T0", "paper_postmortem": "T0", "position_protection": "T0",
    "go_candidate": "T1", "approval_queue": "T1", "high_rank_watchlist": "T1", "enh_proposal": "T1",
    "enh_scalp": "T1", "manual": "T1", "operator_telegram": "T1",
    "active_directive": "T2", "watch_directive": "T2", "sector_theme": "T2", "enh_sector": "T2",
    "wait_candidate": "T2", "topic_research": "T2", "research_scheduler": "T2", "enh_report": "T2",
    "incubator": "T2", "feedback-seed": "T2",
    "broad_universe": "T3", "ticker_snapshot": "T3", "top20_curation": "T3", "finviz_broad": "T3",
    "cold_watchlist": "T3", "cold_universe": "T4", "unranked": "T4",
}


def _exec(sql, p=None, fetch="all"):
    from db_adapter import _execute, USE_DB
    if not USE_DB:
        return None
    try:
        return _execute(sql, p, fetch=fetch)
    except Exception:
        return None


def _rows(sql, p=None):
    return _exec(sql, p, fetch="all") or []


def governance_summary(fresh=False):
    """Cached entry point for the panel. Serves a pre-warmed disk TTL cache so the heavy audit never
    blocks the request path; `fresh=True` (or an expired/absent cache) recomputes. Read-only."""
    if not fresh:
        try:
            if os.path.exists(_CACHE_PATH):
                cached = json.loads(open(_CACHE_PATH).read())
                if time.time() - float(cached.get("_cached_at") or 0) < _TTL_SEC:
                    cached["cached"] = True
                    return cached
        except Exception:
            pass
    out = _governance_summary_compute()
    try:
        out["_cached_at"] = time.time()
        out["cached"] = False
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        tmp = _CACHE_PATH + ".tmp"
        with open(tmp, "w") as f:
            f.write(json.dumps(out, default=str))
        os.replace(tmp, _CACHE_PATH)
    except Exception:
        pass
    return out


def _governance_summary_compute():
    """Everything the Hermes Governance panel needs. Read-only. Heavy (~3-4s) — call via the cache."""
    from hermes_research_scope_audit import build as _audit_build
    audit = _audit_build()

    # Research counts by tier (30d) — use budget_tier where present, else infer from trigger_reason.
    tiers = {t: {"calls": 0, "symbols": set()} for t in ("T0", "T1", "T2", "T3", "T4", "UNMAPPED")}
    for r in _rows("""SELECT COALESCE(budget_tier,'') bt, COALESCE(trigger_reason,'') tr,
                             symbol, COUNT(*) OVER () dummy
                      FROM hermes_external_research WHERE created_at>now()-interval '30 days'"""):
        bt = (r["bt"] if isinstance(r, dict) else r[0]) or ""
        tr = (r["tr"] if isinstance(r, dict) else r[1]) or ""
        sym = r["symbol"] if isinstance(r, dict) else r[2]
        tier = bt if bt in tiers else _TIER_HINT.get(tr.split(":")[0], "UNMAPPED")
        tiers[tier]["calls"] += 1
        if sym:
            tiers[tier]["symbols"].add(sym)
    by_tier = {t: {"calls": v["calls"], "symbols": len(v["symbols"])} for t, v in tiers.items()}

    # Budget decisions recorded so far (post-migration rows)
    decisions = {}
    for r in _rows("""SELECT COALESCE(budget_decision,'(unrecorded)') d, COUNT(*) n
                      FROM hermes_external_research WHERE created_at>now()-interval '30 days' GROUP BY 1"""):
        decisions[r["d"] if isinstance(r, dict) else r[0]] = r["n"] if isinstance(r, dict) else r[1]

    return {
        "ok": True,
        "status": audit.get("status"),
        "windows": audit.get("windows"),
        "by_tier": by_tier,
        "llm_by_lane": {k: v["calls"] for k, v in audit.get("llm_by_lane", {}).items()},
        "local_gpu_calls_30d": audit.get("local_gpu", {}).get("calls_30d"),
        "budget_decisions": decisions,
        "no_active_trigger": audit.get("no_active_trigger"),
        "duplicate": audit.get("duplicate"),
        "stale": audit.get("stale"),
        "top_expensive_sources": audit.get("top_expensive_sources", [])[:15],
        "findings": audit.get("findings"),
        "policy": {
            "tiers": "T0 held · T1 actionable · T2 themed · T3 broad metadata-only · T4 cold no-research",
            "broad_universe_llm": "blocked (METADATA_ONLY)",
            "paid_fallback": "blocked",
            "market_hours_local_heavy": "blocked (27B/31B)",
        },
        "note": "Read-only Hermes research governance. Advisory only — no trades, no broker writes, "
                "no gate bypass. Broad universe never calls an LLM.",
    }


if __name__ == "__main__":
    # `--warm` recomputes and writes the disk cache (cron, out of the request path).
    # `--json` prints the (possibly cached) summary.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--warm", action="store_true", help="recompute + write cache, then exit")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    d = governance_summary(fresh=a.warm)
    if a.warm:
        print(json.dumps({"warmed": True, "cached_path": _CACHE_PATH, "ttl_sec": _TTL_SEC,
                          "compute_sec": round(time.time() - t0, 2), "status": d.get("status")}, indent=2))
    else:
        print(json.dumps(d, indent=2, default=str))
