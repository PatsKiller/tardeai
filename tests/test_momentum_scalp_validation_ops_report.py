#!/usr/bin/env python3
"""P1: validation ops report — read-only, gate honesty, next action, no live claim."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from momentum_scalp_validation_ops_report import build, to_markdown, GATE  # noqa: E402

PASS, FAIL, WARN = [], [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    r = build(30)
    check("report runs", r.get("ok") is True)
    check("validation taxonomy (validation_fast_path present)", "validation_fast_path" in r)
    check("validation gate uses min_closed_validation_trades",
          r["validation_gate"].get("min_closed_validation_trades") == GATE["min_closed_validation_trades"])
    check("never claims live-ready", r.get("live_ready_claim") is False)
    check("validation_gate_met is boolean", isinstance(r.get("validation_gate_met"), bool))
    check("has next operational action", bool(r.get("next_operational_action")))
    check("next action says do not promote OR collect samples",
          ("Do NOT promote" in r["next_operational_action"]) or ("collect" in r["next_operational_action"].lower())
          or ("No confirmed validation sample" in r["next_operational_action"]))
    check("note affirms no broker writes + sandbox + live unchanged",
          "No broker writes" in r["note"] and "sandbox" in r["note"].lower() and "2FA" in r["note"])
    check("markdown renders", "Momentum Scalp Validation Ops" in to_markdown(r))
    # With the current 2/30 sample the gate must not be met.
    cc = r["validation_gate"].get("confirmed_closed_validation_trades")
    if cc is not None:
        check("gate not met on insufficient sample", (cc < 30) == (not r["validation_gate_met"]))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed, {len(WARN)} warn")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
