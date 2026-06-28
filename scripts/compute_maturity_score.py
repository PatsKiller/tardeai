#!/usr/bin/env python3
"""Transparent, evidence-based maturity score for Trade AI (PO-3).

Computes a weighted 0–5 maturity score from machine-derived evidence (validators + tests +
execution state), then applies hard CAPS so the score must be EARNED, not asserted. Every
line of the score is explainable. Read-only — performs no broker writes.

Usage:
  python3 scripts/compute_maturity_score.py --json
  python3 scripts/compute_maturity_score.py --markdown > docs/diligence/current/MATURITY_SCORE_LATEST.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# (key, label, weight) — weights sum to 1.00.
WEIGHTS = [
    ("execution_state_clarity", "Execution-state clarity", 0.10),
    ("central_readiness_resolver", "Central readiness resolver", 0.15),
    ("broker_write_safety", "Broker write safety", 0.15),
    ("operator_approval_evidence_binding", "Operator approval evidence binding", 0.10),
    ("options_hard_risk_blocks", "Options hard-risk blocks", 0.10),
    ("kill_switches", "Kill switches", 0.08),
    ("broker_lifecycle_reconciliation", "Broker lifecycle / reconciliation", 0.10),
    ("audit_ledger", "Audit ledger", 0.08),
    ("release_readiness", "Release readiness", 0.10),
    ("post_trade_methodology", "Post-trade methodology / critique loop", 0.04),
]


def _run(cmd: list[str], timeout: int = 200) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def _run_json(cmd: list[str], timeout: int = 200) -> dict:
    rc, out = _run(cmd, timeout)
    try:
        # tolerate trailing log lines — take the last JSON object
        start = out.index("{")
        return json.loads(out[start:])
    except Exception:
        return {"_rc": rc, "_raw": out[:300]}


def gather_evidence() -> dict:
    ev: dict = {}

    # Execution state
    state = _run_json(["python3", "scripts/execution_state.py", "--json"], timeout=60)
    ev["execution_state"] = state
    unlock = state.get("live_unlock") or {}
    ev["execution_state_unknown_inspection"] = bool(unlock.get("inspect_error"))
    ev["live_adjacent_dirty_count"] = int(state.get("live_adjacent_dirty_count") or 0)
    ev["autonomous_blocked"] = state.get("autonomous_live_submit_allowed") is False
    ev["per_order_2fa_required"] = bool(state.get("per_order_2fa_required"))

    # Release readiness (authoritative status + dirty classification)
    rel = _run_json(["python3", "scripts/validate_release_readiness.py", "--json", "--skip-build"], timeout=200)
    ev["release_status"] = rel.get("status", "UNKNOWN")
    ev["release_live_adjacent_dirty"] = (rel.get("dirty_classification") or {}).get("live_adjacent") or []

    # Schwab write policy
    rc, out = _run(["python3", "scripts/validate_schwab_write_policy.py"], timeout=200)
    ev["schwab_write_policy_pass"] = rc == 0
    ev["schwab_write_policy_tail"] = out.strip().splitlines()[-1].strip() if out.strip() else ""

    # No-bypass test + scanner
    rc_nb, _ = _run(["python3", "tests/test_no_broker_write_bypass.py"], timeout=120)
    ev["no_bypass_test_pass"] = rc_nb == 0
    try:
        import broker_write_scanner as bws
        scan = bws.scan()
        ev["scanner_clean"] = scan["ok"]
        ev["scanner_findings"] = scan["finding_count"]
    except Exception as e:
        ev["scanner_clean"] = False
        ev["scanner_findings"] = -1
        ev["scanner_error"] = str(e)[:120]

    # Central readiness resolver present
    ev["readiness_resolver_present"] = (ROOT / "scripts" / "brokers" / "execution_readiness.py").exists()

    # Unit-test signals (fast)
    tests = {
        "execution_readiness": "tests/test_execution_readiness.py",
        "evidence_bound_approval": "tests/test_evidence_bound_approval.py",
        "intraday_window": "tests/test_intraday_window_fail_closed.py",
        "order_lifecycle": "tests/test_order_lifecycle.py",
        "reconcile_orders": "tests/test_reconcile_orders.py",
        "audit_ledger": "tests/test_audit_ledger.py",
        "options_matrix": "tests/test_options_hard_risk_blocks_matrix.py",
        "journal_ai_critique": "tests/test_journal_ai_critique.py",
    }
    ev["tests"] = {}
    for name, path in tests.items():
        rc, _ = _run(["python3", path], timeout=120)
        ev["tests"][name] = rc == 0

    # Kill switches status
    rc_ks, _ = _run(["python3", "scripts/brokers/kill_switches.py", "--status"], timeout=30)
    ev["kill_switches_ok"] = rc_ks == 0

    return ev


def score_dimensions(ev: dict) -> dict:
    t = ev.get("tests", {})
    dims = {}

    dims["execution_state_clarity"] = (
        0.4 * (1 if ev.get("autonomous_blocked") else 0)
        + 0.3 * (1 if ev.get("per_order_2fa_required") else 0)
        + 0.3 * (0 if ev.get("execution_state_unknown_inspection") else 1)
    )
    dims["central_readiness_resolver"] = (
        0.5 * (1 if ev.get("readiness_resolver_present") else 0)
        + 0.5 * (1 if t.get("execution_readiness") else 0)
    )
    dims["broker_write_safety"] = (
        0.5 * (1 if ev.get("schwab_write_policy_pass") else 0)
        + 0.3 * (1 if ev.get("no_bypass_test_pass") else 0)
        + 0.2 * (1 if ev.get("scanner_clean") else 0)
    )
    dims["operator_approval_evidence_binding"] = 1.0 if t.get("evidence_bound_approval") else 0.0
    dims["options_hard_risk_blocks"] = 1.0 if t.get("options_matrix") else 0.0
    dims["kill_switches"] = 1.0 if ev.get("kill_switches_ok") else 0.0
    dims["broker_lifecycle_reconciliation"] = (
        0.5 * (1 if t.get("order_lifecycle") else 0)
        + 0.5 * (1 if t.get("reconcile_orders") else 0)
    )
    dims["audit_ledger"] = 1.0 if t.get("audit_ledger") else 0.0
    rel_status = ev.get("release_status")
    dims["release_readiness"] = {"PASS": 1.0, "WARN_NON_LIVE_ADJACENT": 0.9,
                                 "WARN": 0.6, "FAIL": 0.2}.get(rel_status, 0.2)
    dims["post_trade_methodology"] = (
        0.5 * (1 if t.get("journal_ai_critique") else 0)
        + 0.5 * (1 if t.get("intraday_window") else 0)
    )
    return dims


def apply_caps(raw_score: float, ev: dict) -> tuple[float, list[dict]]:
    caps: list[dict] = []
    rel = ev.get("release_status")

    if rel == "FAIL":
        caps.append({"cap": 3.75, "reason": "release readiness FAIL"})
    elif rel == "WARN":
        caps.append({"cap": 4.35, "reason": "release WARN (not classified non-live-adjacent)"})
    # WARN_NON_LIVE_ADJACENT and PASS do not cap (warnings explicitly non-live-adjacent + documented).

    if not ev.get("readiness_resolver_present"):
        caps.append({"cap": 3.5, "reason": "missing central readiness resolver"})
    if not ev.get("no_bypass_test_pass"):
        caps.append({"cap": 3.6, "reason": "no-broker-write-bypass test failed"})
    if not ev.get("schwab_write_policy_pass"):
        caps.append({"cap": 3.6, "reason": "Schwab write policy validator failed"})
    if ev.get("live_adjacent_dirty_count", 0) > 0 or ev.get("release_live_adjacent_dirty"):
        caps.append({"cap": 4.0, "reason": "live-adjacent dirty file present"})
    if ev.get("execution_state_unknown_inspection"):
        caps.append({"cap": 4.0, "reason": "unknown execution-state inspection (fail-closed)"})
    if not ev.get("scanner_clean"):
        caps.append({"cap": 3.5, "reason": "broker write path outside approved modules"})

    final = raw_score
    applied = []
    for c in sorted(caps, key=lambda x: x["cap"]):
        if final > c["cap"]:
            applied.append({**c, "lowered_from": round(final, 3)})
            final = c["cap"]
    return final, applied


def compute() -> dict:
    ev = gather_evidence()
    dims = score_dimensions(ev)
    lines = []
    raw = 0.0
    for key, label, weight in WEIGHTS:
        s = round(dims.get(key, 0.0), 4)
        contribution = round(weight * s * 5.0, 4)
        raw += weight * s * 5.0
        lines.append({"key": key, "label": label, "weight": weight,
                      "dimension_score_0_1": s, "weighted_points_of_5": contribution})
    raw = round(raw, 4)
    final, caps_applied = apply_caps(raw, ev)
    return {
        "ok": True,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "raw_weighted_score_of_5": round(raw, 3),
        "final_maturity_score_of_5": round(final, 3),
        "meets_4_5": round(final, 3) >= 4.5,
        "caps_applied": caps_applied,
        "score_lines": lines,
        "evidence": ev,
        "note": "Read-only computation. No broker writes. LLMs are advisory only.",
    }


def to_markdown(report: dict) -> str:
    ev = report["evidence"]
    rows = "\n".join(
        f"| {l['label']} | {l['weight']:.2f} | {l['dimension_score_0_1']:.2f} | "
        f"{l['weighted_points_of_5']:.3f} |" for l in report["score_lines"]
    )
    caps = report["caps_applied"]
    caps_md = ("\n".join(f"- Capped to **{c['cap']}** (from {c['lowered_from']}): {c['reason']}" for c in caps)
               if caps else "- None — no caps triggered.")
    verdict = "✅ **4.5 MET**" if report["meets_4_5"] else "⛔ **4.5 NOT YET MET**"
    return f"""# Trade AI — Maturity Score

_Generated: {report['generated_at']}_
_Source: `python3 scripts/compute_maturity_score.py --json`_

## Result

- Raw weighted score: **{report['raw_weighted_score_of_5']} / 5**
- Final maturity (after caps): **{report['final_maturity_score_of_5']} / 5**
- {verdict}

The score is earned from machine-derived evidence and bounded by hard caps below — it is
never asserted. LLMs are advisory only and cannot affect any gate.

## Weighted breakdown

| Dimension | Weight | Score (0–1) | Points (of 5) |
|-----------|--------|-------------|---------------|
{rows}

## Caps applied

{caps_md}

## Evidence snapshot

| Signal | Value |
|--------|-------|
| Release status | `{ev.get('release_status')}` |
| Schwab write policy | {'PASS' if ev.get('schwab_write_policy_pass') else 'FAIL'} ({ev.get('schwab_write_policy_tail','')}) |
| No-broker-write-bypass test | {'PASS' if ev.get('no_bypass_test_pass') else 'FAIL'} |
| Broker-write scanner | {'clean' if ev.get('scanner_clean') else 'FINDINGS'} ({ev.get('scanner_findings')}) |
| Central readiness resolver present | {ev.get('readiness_resolver_present')} |
| Autonomous live submit blocked | {ev.get('autonomous_blocked')} |
| Per-order 2FA required | {ev.get('per_order_2fa_required')} |
| Live-adjacent dirty count | {ev.get('live_adjacent_dirty_count')} |
| Unknown execution-state inspection | {ev.get('execution_state_unknown_inspection')} |
| Kill switches inspectable | {ev.get('kill_switches_ok')} |
| Unit tests passing | {sum(1 for v in ev.get('tests',{}).values() if v)}/{len(ev.get('tests',{}))} |

*Autonomous live submit remains disabled. Operator-approved broker submit path is gated by
deterministic controls. Broker truth is authoritative after submit.*
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--markdown", action="store_true")
    args = ap.parse_args()
    report = compute()
    # Always persist the JSON artifact for downstream consumers.
    try:
        out = ROOT / "data" / "runtime" / "maturity_score_latest.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception:
        pass
    if args.markdown:
        print(to_markdown(report))
    else:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
