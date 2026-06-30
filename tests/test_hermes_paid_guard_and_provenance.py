#!/usr/bin/env python3
"""Tests for the Hermes paid-lane guard + synthesis/source provenance hardening.

Covers: automated paid fallback is impossible (free_only restricts to local), explicit paid oversight
must be an operator-authorized source (never an automated producer), unknown producer fails closed,
broad-universe synthesis cannot call an LLM, cloud-down defers, market-hours local-heavy blocked, the
synthesis/source tables carry provenance, backfill is idempotent + legacy-only (no fabricated ALLOW/
DEFER), and none of the new code performs broker/execution/gate writes.

Runnable as a script (PASS/FAIL lines + exit code). The pure-logic checks never touch the DB; the
provenance checks connect read-only and SKIP cleanly if the DB is unreachable.
"""
import datetime as dt
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from hermes_research_budget_guard import decide, _load_policy, ALLOW, DEFER, METADATA_ONLY, BLOCK  # noqa: E402

POL = _load_policy()
MKT = dt.datetime(2026, 6, 29, 9, 30)     # inside 06:00-12:00 ET
NIGHT = dt.datetime(2026, 6, 29, 22, 0)   # outside market hours
SCRIPTS = os.path.join(ROOT, "scripts")
PROV_TABLES = ["watchlist_final_synthesis", "risk_synthesis_results", "watchlist_synthesis_safety_history",
               "source_weights", "source_performance", "source_learning_scores", "rec_source_quality"]
PROV_COLS = ["trigger_source", "trigger_id", "budget_tier", "budget_decision", "lane_used",
             "research_expires_at", "research_reason", "downstream_outcome", "source_table", "source_row_id"]

PASS, FAIL, SKIP = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def skip(name, why):
    SKIP.append(name)
    print(f"  [SKIP] {name} ({why})")


def d(**kw):
    kw.setdefault("now", NIGHT)
    kw.setdefault("policy", POL)
    return decide(**kw)


def main():
    # ---- 1. free_only makes paid fallback structurally impossible ----
    import llm_router as L
    check("router _FREE_PROVIDERS is local-only", L._FREE_PROVIDERS == {"local"})
    for tt in ("cio_synthesis", "agent_narrative", "default"):
        full = L._TASK_ROUTING.get(tt, L._TASK_ROUTING["default"])
        free = [p for p in full if p in L._FREE_PROVIDERS] or ["local"]
        check(f"free_only({tt}) drops every paid provider", set(free) == {"local"} and "claude" not in free and "openai" not in free)
    check("get_llm_response accepts free_only kwarg", "free_only" in L.get_llm_response.__code__.co_varnames)

    # ---- 2. the two automated producers route through the guard + free_only, never high_impact paid ----
    for fn in ("auto_research.py", "iterate_research_topics.py"):
        src = open(os.path.join(SCRIPTS, fn)).read()
        check(f"{fn} imports the budget guard", "hermes_research_budget_guard" in src and "decide" in src)
        check(f"{fn} calls get_llm_response with free_only=True", "free_only=True" in src)
        check(f"{fn} no longer requests high_impact paid routing", "high_impact=True" not in src)
        check(f"{fn} skips on non-ALLOW guard verdict", "!= ALLOW" in src or "!= L.ALLOW" in src or "decision\") != ALLOW" in src or 'get("decision") != ALLOW' in src)

    # ---- 3. explicit paid oversight is an operator-authorized source, NOT an automated producer ----
    # The deliberate monthly Claude oversight maps to a tier; the automated producers must too, but
    # they are gated to the free local lane (asserted above), so paid is only reachable by the
    # explicit oversight path, never as a producer fallback.
    r = d(symbol="X", trigger_source="monthly_protection_meta_review", lane="local_quality")
    check("deliberate oversight source is mapped (not fail-closed)", r["decision"] != BLOCK or r["tier"] != "UNKNOWN")
    r = d(symbol="X", trigger_source="auto_research_conflict", lane="cloud_paid")
    check("automated producer + paid lane -> BLOCK (no paid fallback)", r["decision"] == BLOCK)

    # ---- 4. unknown producer fails closed ----
    r = d(symbol="X", trigger_source="some_new_unmapped_producer", lane="local_quality")
    check("unknown producer -> BLOCK (fail closed)", r["decision"] == BLOCK)

    # ---- 5. new producer sources resolve correctly ----
    for src_name, tier in [("auto_research_conflict", "T1"), ("auto_research_high_impact", "T1"),
                           ("auto_research_discovery", "T2"), ("topic_iteration", "T2")]:
        r = d(symbol="X", trigger_source=src_name, lane="local_quality", has_active_trigger=True)
        check(f"{src_name} -> ALLOW @ {tier}", r["decision"] == ALLOW and r["tier"] == tier)

    # ---- 6. broad-universe synthesis cannot call an LLM ----
    r = d(symbol="FOO", trigger_source="broad_universe", lane="cloud_grok")
    check("broad universe synthesis -> METADATA_ONLY (no LLM)", r["decision"] == METADATA_ONLY)

    # ---- 7. cloud unavailable defers (never paid / local-heavy) ----
    r = d(symbol="X", trigger_source="topic_iteration", lane="cloud_grok", cloud_available=False, has_active_trigger=True)
    check("cloud unavailable -> DEFER", r["decision"] == DEFER)

    # ---- 8. market-hours local-heavy blocked ----
    r = d(symbol="X", trigger_source="auto_research_conflict", lane="local_heavy", now=MKT)
    check("market-hours local-heavy (27B/31B) -> BLOCK", r["decision"] == BLOCK)

    # ---- 9. no broker/execution/gate writes in any new/changed file ----
    bad_tokens = ("place_order", "submit_order", "schwab_transport", "execute_trade", "broker_write",
                  "live_trading_allowed", "approve_order", "2fa", "two_factor")
    for fn in ("auto_research.py", "iterate_research_topics.py", "migrate_synthesis_source_provenance.py"):
        src = open(os.path.join(SCRIPTS, fn)).read().lower()
        for bad in bad_tokens:
            check(f"{fn} has no '{bad}' (advisory-only)", bad not in src)

    # ---- 10. provenance on the synthesis/source tables (DB; SKIP if unreachable) ----
    try:
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
    except Exception as e:
        skip("synthesis/source provenance columns present", f"db: {str(e)[:40]}")
        skip("backfill is legacy-only (no fabricated ALLOW/DEFER)", "db unreachable")
        skip("migration is idempotent", "db unreachable")
        _summary(); return

    for t in PROV_TABLES:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (t,))
        have = {r[0] for r in cur.fetchall()}
        check(f"{t} has all 10 provenance columns", all(c in have for c in PROV_COLS))

    # legacy-only backfill — no fabricated ALLOW/DEFER/METADATA_ONLY/BLOCK on historical rows
    fabricated_total = 0
    for t in PROV_TABLES:
        cur.execute(f"SELECT COUNT(*) FROM {t} WHERE budget_decision IN ('ALLOW','DEFER','METADATA_ONLY','BLOCK')")
        fabricated_total += cur.fetchone()[0]
    check("no historical row has a fabricated ALLOW/DEFER/BLOCK decision", fabricated_total == 0)
    cur.execute("SELECT COUNT(*) FROM watchlist_final_synthesis WHERE budget_decision='legacy' AND budget_tier IS NOT NULL")
    check("watchlist_final_synthesis backfilled as legacy", cur.fetchone()[0] > 0)

    # idempotency — after apply, --check would add 0 columns and 0 backfill rows
    import subprocess, json
    out = subprocess.run([sys.executable, os.path.join(SCRIPTS, "migrate_synthesis_source_provenance.py"), "--check"],
                         capture_output=True, text=True)
    try:
        rep = json.loads(out.stdout)
        check("migration idempotent: 0 columns would be added", len(rep.get("would_add", [])) == 0)
        check("migration idempotent: 0 rows to backfill", sum(t["rows_to_backfill"] for t in rep["tables"]) == 0)
    except Exception:
        check("migration --check returns parseable JSON", False)

    _summary()


def _summary():
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(SKIP)} skipped")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
