#!/usr/bin/env python3
"""Health monitor coverage for the momentum_scalp Finviz 5-min early lane: schedule-aware staleness
detection + auto-remediation wiring (source/sandbox only, no broker writes)."""
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
    A = ha._assess_momentum_scalp_scan

    # Off-window → never a finding (schedule-aware; no weekend/off-hours floods).
    check("off-window silent (stale log ignored)",
          A(999, "PASS", None, True, in_window=False)["finding"] is False)

    # In-window, fresh log, clean status → no finding.
    check("in-window fresh → no finding", A(3, "PASS", [], True, in_window=True)["finding"] is False)

    # In-window, stale log (>12 min, cron is */5) → warning finding, auto-remediable type.
    r = A(20, "PASS", [], True, in_window=True)
    check("in-window stale log → finding", r["finding"] is True)
    check("stale finding type is scan_stale", r["type"] == "momentum_scalp_finviz_scan_stale")
    check("stale finding severity warning", r["severity"] == "warning")

    # Very stale (>30 min) → critical.
    check("very stale → critical", A(45, "PASS", [], True, in_window=True)["severity"] == "critical")

    # Missing log during window → finding.
    check("missing log in-window → finding", A(None, None, None, False, in_window=True)["finding"] is True)

    # In-window, fresh log but last run PARTIAL/failed → early_lane_error finding.
    r2 = A(3, "PARTIAL", ["proposal_gen"], True, in_window=True)
    check("partial run → early_lane_error", r2["finding"] and r2["type"] == "momentum_scalp_early_lane_error")

    # Collector is registered + never raises.
    check("collector registered in COLLECTORS", ha.collect_momentum_scalp_source_health in ha.COLLECTORS)
    findings = ha.collect_momentum_scalp_source_health()
    check("collector returns a list (never raises)", isinstance(findings, list))
    check("any finding is in pipeline_freshness category",
          all(f.get("category") == "pipeline_freshness" for f in findings))

    # Policy wiring: auto-remediation enabled for the scan-stale finding + safe command.
    pol = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config", "health_agent_policy.json")))
    ft = pol["auto_remediate"]["finding_types"]
    rm = pol["remediation_map"]
    check("scan_stale in auto_remediate finding_types", "momentum_scalp_finviz_scan_stale" in ft)
    check("early_lane_error in auto_remediate finding_types", "momentum_scalp_early_lane_error" in ft)
    cmd = rm.get("momentum_scalp_finviz_scan_stale", "")
    check("remediation command runs the safe scan wrapper", "run_finviz_momentum_scalp_scan.py" in cmd)
    check("remediation is fast (skips finviz refresh)", "--skip-finviz-refresh" in cmd)
    check("remediation has no broker-write script", all(
        x not in cmd for x in ("schwab", "alpaca_submit", "place_order")))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
