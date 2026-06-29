#!/usr/bin/env python3
"""P0-5: schedule-aware health for all remaining momentum_scalp sources (SEC/Form 4, signal sync,
proposal generation, social scan). Proves no off-hours alert floods + safe SEC auto-remediation."""
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv")
    _d.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _d

import health_agent as ha  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")


def main():
    A = ha._assess_source_stale

    # ---- schedule-awareness: off-window NEVER a finding (no off-hours floods) ----
    check("off-window stale → silent", A(9999, 90, in_window=False)["finding"] is False)
    check("off-window missing → silent", A(None, 90, in_window=False, present=False)["finding"] is False)

    # ---- in-window staleness ----
    check("in-window fresh → no finding", A(10, 90, in_window=True)["finding"] is False)
    check("in-window stale → warning", A(120, 90, in_window=True) == {"finding": True, "severity": "warning", "reason": "stale 120m (>90m)"})
    check("in-window very stale → critical", A(400, 90, in_window=True)["severity"] == "critical")
    check("in-window missing → finding", A(None, 90, in_window=True, present=False)["finding"] is True)
    check("in-window unknown age → no false finding", A(None, 90, in_window=True, present=True)["finding"] is False)

    # ---- collectors registered + never raise ----
    check("multi-source collector registered", ha.collect_momentum_scalp_multi_source_health in ha.COLLECTORS)
    findings = ha.collect_momentum_scalp_multi_source_health()
    check("multi-source collector returns list", isinstance(findings, list))
    check("all findings in pipeline_freshness category",
          all(f.get("category") == "pipeline_freshness" for f in findings))

    # ---- policy wiring: SEC context auto-remediation is safe (source-only, no broker writes) ----
    pol = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config", "health_agent_policy.json")))
    check("sec_form4_context_stale auto-remediable", "sec_form4_context_stale" in pol["auto_remediate"]["finding_types"])
    cmd = pol["remediation_map"].get("sec_form4_context_stale", "")
    check("SEC remediation runs the safe context wrapper", "run_sec_form4_momentum_context.py" in cmd)
    check("SEC remediation has no broker-write script",
          all(x not in cmd for x in ("schwab", "place_order", "alpaca_submit")))

    # Each targeted source has a distinct finding type defined in the collector source.
    src = open(os.path.join(os.path.dirname(__file__), "..", "scripts", "health_agent.py")).read()
    for ftype in ["sec_form4_context_stale", "momentum_scalp_signal_sync_stale",
                  "momentum_scalp_proposal_gen_stale", "momentum_scalp_social_scan_stale"]:
        check(f"finding type defined: {ftype}", ftype in src)

    # ---- 2026-06-29 incident fixes: no pre-market false floods + correct column + condition-aware ----
    coll = src[src.index("def collect_momentum_scalp_multi_source_health"):
               src.index("def collect_momentum_scalp_multi_source_health") + 4200]
    check("signal sync uses fired_at (created_at does NOT exist on strategy_signals)",
          "MAX(fired_at) FROM strategy_signals" in coll and "MAX(created_at) FROM strategy_signals" not in coll)
    check("proposal/signal output checks scoped to active session (09:30+, no pre-market floods)",
          '"09:30"' in coll)
    check("proposal_gen is condition-aware (fresh-GO-not-converting, not bare staleness)",
          "signal_type='GO'" in coll and "not converting" in coll)
    check("SEC context window starts 06:00 (after its 05:45 cron)", '"06:00" <= hhmm <= "12:00"' in coll)
    # The bare-staleness pre-market proposal check (the false-flood source) is gone.
    check("no unconditional 06:00 proposal-output staleness check",
          'MAX(created_at) FROM paper_trade_proposals", in_early' not in coll)

    # Live: right now (whatever the time), the collector must not raise and must return a list.
    check("collector still returns a clean list", isinstance(ha.collect_momentum_scalp_multi_source_health(), list))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
