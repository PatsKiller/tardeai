#!/usr/bin/env python3
"""Smoke test for the Hermes Research Governance API surface. Read-only; no broker/LLM calls.
Runs the route through api_v2.handle and asserts shape + safety invariants."""
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    import api_v2
    st, body = api_v2.handle("/api/v2/hermes/research-governance", method="GET")
    check("route returns HTTP 200", st == 200)
    check("envelope ok=True", body.get("ok") is True)
    d = body.get("data", {})
    check("has by_tier", isinstance(d.get("by_tier"), dict))
    check("by_tier has T0..T4", all(t in d.get("by_tier", {}) for t in ("T0", "T1", "T2", "T3", "T4")))
    check("has llm_by_lane", isinstance(d.get("llm_by_lane"), dict))
    check("has windows 1d/7d/30d", all(w in (d.get("windows") or {}) for w in ("1d", "7d", "30d")))
    check("has top_expensive_sources", isinstance(d.get("top_expensive_sources"), list))
    check("has duplicate metrics", "redundant_calls" in (d.get("duplicate") or {}))
    pol = d.get("policy", {})
    check("policy: broad-universe LLM blocked", "block" in (pol.get("broad_universe_llm", "")).lower())
    check("policy: paid fallback blocked", "block" in (pol.get("paid_fallback", "")).lower())
    check("read-only note present", "no trades" in (d.get("note") or "").lower())

    # The governance module must not contain any execution/broker write surface.
    src = open(os.path.join(ROOT, "scripts", "hermes_governance_api.py")).read()
    for bad in ("INSERT", "UPDATE ", "DELETE", "place_order", "schwab_transport"):
        check(f"governance module has no '{bad.strip()}'", bad not in src)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
