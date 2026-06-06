#!/usr/bin/env python3
"""validate_hermes_summary_recovery.py — unit tests for bounded Hermes summary recovery. Read-only.
  python3 scripts/validate_hermes_summary_recovery.py [--json PATH] [--markdown PATH]
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hermes_output_recovery import recover_summary_from_output as R

SPECIFIC = "AAPL trade closed for a +1.8R gain; entry was late vs the breakout, stop held, lesson: enter on the first pullback not the chase."
GENERIC = "This was a trade. It happened. Some things occurred during the period under review here today."
EVASIVE = "I cannot analyze this trade because there is not enough information available to me right now."


def main():
    checks = []
    def chk(n, ok, d=""):
        checks.append({"name": n, "pass": bool(ok), "detail": str(d)})

    # strict valid summary passes (recovered from 'summary' key, high confidence)
    r = R({"summary": SPECIFIC}, symbol="AAPL")
    chk("strict summary recovers high", r["recovered"] and r["confidence"] == "high" and r["source_key"] == "summary")
    # alternate executive_summary recovers
    r = R({"executive_summary": SPECIFIC}, symbol="AAPL")
    chk("executive_summary recovers (medium)", r["recovered"] and r["source_key"] == "executive_summary")
    # alternate analysis recovers
    r = R({"analysis": SPECIFIC}, symbol="AAPL")
    chk("analysis recovers", r["recovered"] and r["source_key"] == "analysis")
    # raw text paragraph recovers only if specific
    r = R("no json here\n\n" + SPECIFIC, symbol="AAPL")
    chk("raw paragraph recovers when specific", r["recovered"] and r["recovery_method"] == "raw_paragraph")
    # generic rejected
    r = R({"summary": GENERIC}, symbol="AAPL")
    chk("generic rejected", not r["recovered"], r["rejection_reason"])
    # evasive rejected
    r = R({"summary": EVASIVE}, symbol="AAPL")
    chk("evasive/insufficient rejected", not r["recovered"], r["rejection_reason"])
    # too short rejected
    r = R({"summary": "AAPL won."}, symbol="AAPL")
    chk("too-short rejected", not r["recovered"], r["rejection_reason"])
    # missing symbol AND no context rejected (boilerplate w/o trade terms)
    r = R({"summary": "The weather was pleasant and the meeting went reasonably well for everyone involved overall today."}, symbol="AAPL")
    chk("generic-no-context rejected", not r["recovered"], r["rejection_reason"])
    # malformed/no useful text rejected
    r = R({"foo": 1, "bar": []}, symbol="AAPL")
    chk("no recoverable text rejected", not r["recovered"], r["rejection_reason"])
    # context-only (no symbol) still recovers (trade terms present)
    r = R({"summary": "The position was entered near resistance, the stop held, and it exited at target for a solid gain; lesson on patience."}, symbol="ZZZZ")
    chk("context-only (trade terms) recovers", r["recovered"])

    ok = all(c["pass"] for c in checks)
    for c in checks:
        print(f"  [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}" + (f" — {c['detail']}" if c['detail'] and not c['pass'] else ""))
    print(f"\n{sum(1 for c in checks if c['pass'])}/{len(checks)} PASS — {'GREEN' if ok else 'FAILED'}")
    res = {"pass": ok, "checks": checks}
    if "--json" in sys.argv:
        json.dump(res, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=2)
    if "--markdown" in sys.argv:
        open(sys.argv[sys.argv.index("--markdown") + 1], "w").write("# Hermes summary recovery validation\n\n" + "\n".join(f"- [{'PASS' if c['pass'] else 'FAIL'}] {c['name']}" for c in checks))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
