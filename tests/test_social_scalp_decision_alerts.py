#!/usr/bin/env python3
"""P0-2: social alerts key off the FINAL capped decision, not the raw score.

A social-only unverified setup with a high raw score is downgraded to WAIT and must send
a WAIT alert (never a GO-style alert or proposals-channel mirror). The saved DB decision
and the 'alerted' flag must reflect the final capped decision.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from social_scalp_scanner import apply_social_only_cap, alert_action_for  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def _alerted_flag(decision):  # mirrors save_scan_result's column logic (P0-2)
    return decision == "GO"


def main():
    # 1. Raw score 50 + social-only unverified → WAIT/B, WAIT alert.
    d, g, capped = apply_social_only_cap("GO", "A+", {})  # no catalyst evidence
    check("social-only GO → capped", capped and d == "WAIT" and g == "B")
    check("capped social-only sends WAIT alert", alert_action_for(d, g) == "WAIT")
    check("capped social-only is NOT a GO alert", alert_action_for(d, g) != "GO")
    check("capped social-only DB decision != GO", d != "GO")
    check("capped social-only alerted flag False", _alerted_flag(d) is False)

    # 2. Raw score 50 + verified catalyst → stays GO/A+, GO alert.
    d, g, capped = apply_social_only_cap("GO", "A+", {"catalyst_verified": True})
    check("verified catalyst not capped", (not capped) and d == "GO" and g == "A+")
    check("verified catalyst sends GO alert", alert_action_for(d, g) == "GO")
    check("verified catalyst alerted flag True", _alerted_flag(d) is True)

    # 2b. Credible news source (not RAG-verified flag) also escapes the cap.
    d, g, capped = apply_social_only_cap("GO", "A", {"catalyst": True, "catalyst_source": "SEC 8-K filing"})
    check("news-sourced catalyst not capped", (not capped) and d == "GO")

    # 3. Raw score 35 WAIT → WAIT alert.
    check("WAIT decision sends WAIT alert", alert_action_for("WAIT") == "WAIT")

    # 4. Raw score 20 AVOID → no alert.
    check("AVOID sends no alert", alert_action_for("AVOID") == "NONE")
    check("AVOID alerted flag False", _alerted_flag("AVOID") is False)

    # 5. A-grade social-only is downgraded too (not just A+).
    d, g, capped = apply_social_only_cap("GO", "A", {})
    check("A-grade social-only capped to WAIT/B", capped and d == "WAIT" and g == "B")

    # 6. Already-WAIT decision is unchanged (cap only fires on GO / A+ / A).
    d, g, capped = apply_social_only_cap("WAIT", "B", {})
    check("already-WAIT unverified not re-capped", (not capped) and d == "WAIT" and g == "B")

    # 7. Case/whitespace robustness on the alert dispatch.
    check("lowercase 'go' still GO alert", alert_action_for(" go ") == "GO")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
