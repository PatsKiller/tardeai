#!/usr/bin/env python3
"""Tests for the Hermes research budget guard. Runnable as a script (PASS/FAIL lines + exit code),
same convention as tests/test_llm_budget_guard.py. Pure / DB-free / no broker or LLM calls."""
import datetime as dt
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from hermes_research_budget_guard import decide, _load_policy, ALLOW, DEFER, METADATA_ONLY, BLOCK  # noqa: E402

POL = _load_policy()
MKT = dt.datetime(2026, 6, 29, 9, 30)     # inside 06:00-12:00 ET
NIGHT = dt.datetime(2026, 6, 29, 22, 0)   # outside market hours

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def d(**kw):
    kw.setdefault("now", NIGHT)
    kw.setdefault("policy", POL)
    return decide(**kw)


def main():
    # 1. broad universe cannot call LLM
    r = d(symbol="FOO", trigger_source="broad_universe", lane="cloud_grok")
    check("broad universe LLM request -> METADATA_ONLY", r["decision"] == METADATA_ONLY)
    r = d(symbol="FOO", trigger_source="top20_curation", lane="cloud_chatgpt")
    check("top20_curation (broad driver) -> METADATA_ONLY (no LLM)", r["decision"] == METADATA_ONLY)
    r = d(symbol="FOO", trigger_source="ticker_snapshot", lane="local_quality")
    check("ticker_snapshot local LLM -> METADATA_ONLY", r["decision"] == METADATA_ONLY)

    # 2. unknown trigger fails closed
    r = d(symbol="X", trigger_source="totally_unknown", lane="cloud_grok")
    check("unknown trigger_source -> BLOCK (fail closed)", r["decision"] == BLOCK)
    r = d(symbol="X", trigger_source="", lane="cloud_grok")
    check("empty trigger_source -> BLOCK (fail closed)", r["decision"] == BLOCK)

    # 3. market-hours local heavy model blocked
    r = d(symbol="AAPL", trigger_source="holdings", lane="local_heavy", now=MKT)
    check("market-hours local heavy (27B/31B) -> BLOCK", r["decision"] == BLOCK)
    r = d(symbol="AAPL", trigger_source="holdings", lane="gemma4-31b", now=MKT)
    check("market-hours gemma4-31b -> BLOCK", r["decision"] == BLOCK)
    r = d(symbol="AAPL", trigger_source="holdings", lane="local_heavy", now=NIGHT)
    check("overnight local heavy -> ALLOW", r["decision"] == ALLOW)

    # 4. free-OAuth unavailable causes defer, not paid fallback
    r = d(symbol="AAPL", trigger_source="holdings", lane="cloud_grok", cloud_available=False)
    check("cloud unavailable -> DEFER (not paid)", r["decision"] == DEFER)
    r = d(symbol="AAPL", trigger_source="holdings", lane="cloud_paid")
    check("paid lane -> BLOCK (no paid fallback ever)", r["decision"] == BLOCK)
    check("policy asserts no_paid_fallback", POL.get("no_paid_fallback") is True)

    # 5. Tier 0 holdings allowed
    r = d(symbol="AAPL", trigger_source="holdings", lane="cloud_grok")
    check("T0 holdings cloud -> ALLOW", r["decision"] == ALLOW and r["tier"] == "T0")
    r = d(symbol="AAPL", trigger_source="open_position", lane="local_fast")
    check("T0 open_position local -> ALLOW", r["decision"] == ALLOW and r["tier"] == "T0")

    # 6. Tier 1 GO candidates allowed with cap
    r = d(symbol="NVDA", trigger_source="go_candidate", lane="cloud_grok")
    check("T1 go_candidate -> ALLOW", r["decision"] == ALLOW and r["tier"] == "T1")
    r = d(symbol="NVDA", trigger_source="go_candidate", lane="cloud_grok", calls_today=10_000)
    check("T1 over daily cap -> DEFER", r["decision"] == DEFER)
    r = d(symbol="NVDA", trigger_source="go_candidate", lane="cloud_grok", symbols_this_run=10_000)
    check("T1 over per-run symbol cap -> DEFER", r["decision"] == DEFER)

    # 7. Tier 2 directive allowed only with trigger
    r = d(symbol="SMCI", trigger_source="active_directive", lane="cloud_grok", has_active_trigger=True)
    check("T2 directive WITH trigger -> ALLOW", r["decision"] == ALLOW and r["tier"] == "T2")
    r = d(symbol="SMCI", trigger_source="active_directive", lane="cloud_grok", has_active_trigger=False)
    check("T2 directive WITHOUT trigger -> METADATA_ONLY (downgraded)", r["decision"] == METADATA_ONLY)

    # 8. duplicate research suppressed
    r = d(symbol="AAPL", trigger_source="holdings", lane="cloud_grok", dedup_fresh=True)
    check("duplicate (fresh) -> DEFER", r["decision"] == DEFER)

    # 9. expiry works
    r = d(symbol="AAPL", trigger_source="holdings", lane="cloud_grok")
    check("ALLOW returns expires_at", bool(r.get("expires_at")))
    check("expires_at is in the future", r["expires_at"] > NIGHT.isoformat())
    r = d(symbol="ZZZ", trigger_source="cold_universe", lane="metadata")
    check("T4 cold universe -> BLOCK (no research)", r["decision"] == BLOCK)

    # 10. no broker/execution writes — guard is pure advisory metadata
    r = d(symbol="AAPL", trigger_source="holdings", lane="cloud_grok")
    check("decision dict is advisory_only", r.get("advisory_only") is True)
    src = open(os.path.join(ROOT, "scripts", "hermes_research_budget_guard.py")).read()
    for bad in ("place_order", "submit_order", "schwab_transport", "broker_write", "execute_trade"):
        check(f"guard source has no '{bad}'", bad not in src)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
