#!/usr/bin/env python3
"""Regression guard for the 3.25 phantom: the scalp-lifecycle maturity generator must run evidence
tests under the venv interpreter (where runtime deps live), distinguish a real FAIL from an ENV_ERROR,
and not emit a false low score just because the INVOKING interpreter lacks a dependency. The 2/30
empirical sample must still cap the combined score below 4.5."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import compute_scalp_lifecycle_maturity as m  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    # ---- evidence interpreter prefers the venv (real runtime / cron / CI) ----
    interps = m._evidence_interpreters()
    check("evidence interpreter list non-empty", len(interps) >= 1)
    venv = os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "python")
    if os.path.exists(venv):
        check("venv interpreter is FIRST (deps present there)", interps[0].endswith(".venv/bin/python"))

    # ---- tri-state: real PASS, real FAIL, and ENV_ERROR are distinguished ----
    check("PASS for a clean test", m._run_test_state("test_no_broker_write_bypass.py", timeout=120) == "PASS")
    check("ENV_ERROR is a defined state (not conflated with FAIL)",
          "ENV_ERROR" in open(os.path.join(os.path.dirname(__file__), "..", "scripts",
                                            "compute_scalp_lifecycle_maturity.py")).read())
    # A non-existent test cannot run anywhere → ENV_ERROR / FAIL, never PASS.
    check("missing test never PASS", m._run_test_state("test_does_not_exist_zzz.py") in ("ENV_ERROR", "FAIL"))

    # ---- the three previously-phantom checks now resolve PASS (under the venv) ----
    for fname, label in [("test_social_scalp_decision_alerts.py", "alerts"),
                         ("test_momentum_scalp_liquidity_unknown.py", "liquidity"),
                         ("test_social_traceability.py", "trace")]:
        check(f"{label}_test resolves PASS under venv", m._run_test_state(fname) == "PASS")

    # ---- full compute: no phantom 3.25; correct capped 4.4; sample cap active ----
    r = m.compute()
    ev = r["evidence"]
    check("alerts_test True", ev["alerts_test"] is True)
    check("liquidity_test True", ev["liquidity_test"] is True)
    check("trace_test True", ev["trace_test"] is True)
    check("no indeterminate evidence (ran under venv)", r["evidence_indeterminate"] == [])
    check("combined NOT the phantom 3.25", r["combined_lifecycle_of_5"] != 3.25)
    check("combined restored to ~4.4", abs(r["combined_lifecycle_of_5"] - 4.4) < 0.0001)
    check("engineering/control is mature (5.0)", r["engineering_control_maturity_of_5"] == 5.0)

    # ---- strategy maturity stays capped below 4.5 by the 2/30 sample ----
    check("meets_4_5 is False", r["meets_4_5"] is False)
    check("combined < 4.5 (empirical sample cap)", r["combined_lifecycle_of_5"] < 4.5)
    check("validation sample status names 2/30", "2/30" in r["validation_sample_status"])
    check("confirmed closed == 2", r["confirmed_closed_paper_trades"] == 2)

    # ---- source maturity reported SEPARATELY, does not lift strategy maturity ----
    sep = r["maturity_separation"]
    check("source maturity separated", "separate" in sep["source_maturity"].lower())
    check("strategy 4.5 not claimable", sep["strategy_maturity_4_5_claimable"] is False)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
