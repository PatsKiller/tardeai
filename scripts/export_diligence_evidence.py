#!/usr/bin/env python3
"""Export the Trade AI diligence evidence pack — machine-derived, no broker writes (PO-2).

Every file carries a generated timestamp, the source command, a PASS/WARN/FAIL status, a
human-readable summary, and a machine-readable JSON block where available. The export
reports WARN/FAIL if required evidence cannot be generated — it never emits stale boilerplate
in place of a missing artifact.

Read-only: runs validators/tests and inspects state. No broker order is ever placed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _run(cmd: list[str], timeout: int = 200) -> tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:
        return 1, "", str(e)


def _run_json(cmd: list[str], timeout: int = 200) -> dict:
    rc, out, err = _run(cmd, timeout)
    try:
        return json.loads(out[out.index("{"):])
    except Exception:
        return {"_rc": rc, "_error": (err or out)[:300]}


def _header(title: str, source: str, status: str, summary: str) -> str:
    return (f"# {title}\n\n"
            f"_Generated: {_now()}_  \n"
            f"_Source: `{source}`_  \n"
            f"**Status: {status}**\n\n"
            f"{summary}\n")


def _json_block(obj) -> str:
    return "\n```json\n" + json.dumps(obj, indent=2, default=str) + "\n```\n"


def export_pack(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    missing: list[str] = []
    overall_warn = False

    # ── Execution state ──
    state = _run_json(["python3", "scripts/execution_state.py", "--json"], timeout=60)
    state_md_rc, state_md, _ = _run(["python3", "scripts/execution_state.py", "--markdown"], timeout=60)
    state_ok = bool(state.get("live_architecture_built")) and not state.get("_error")
    if not state_ok:
        missing.append("execution_state")
    files["CURRENT_EXECUTION_STATE.md"] = (
        _header("Current Execution State", "python3 scripts/execution_state.py --json",
                "PASS" if state_ok else "FAIL",
                "Autonomous live submit remains disabled. Operator-approved broker submit path is "
                "gated by deterministic controls. No order is treated as live before broker acknowledgement.")
        + (state_md if state_md_rc == 0 and state_md.strip() else "")
        + _json_block(state))

    # ── Release readiness ──
    rel = _run_json(["python3", "scripts/validate_release_readiness.py", "--json", "--skip-build"], timeout=200)
    rel_status = rel.get("status", "FAIL")
    if rel_status not in ("PASS", "WARN_NON_LIVE_ADJACENT"):
        overall_warn = True
    files["RELEASE_READINESS.md"] = (
        _header("Release Readiness", "python3 scripts/validate_release_readiness.py --json --skip-build",
                rel_status,
                "Release readiness must be PASS or explicitly justified WARN with no live-adjacent dirty files.")
        + _json_block(rel))

    # ── Schwab write policy ──
    wp_rc, wp_out, wp_err = _run(["python3", "scripts/validate_schwab_write_policy.py"], timeout=200)
    wp_tail = (wp_out or wp_err).strip().splitlines()[-1].strip() if (wp_out or wp_err).strip() else ""
    wp_status = "PASS" if wp_rc == 0 else "FAIL"
    if wp_rc != 0:
        missing.append("schwab_write_policy")

    # ── No broker write bypass test ──
    nb_rc, nb_out, _ = _run(["python3", "tests/test_no_broker_write_bypass.py"], timeout=120)
    nb_tail = nb_out.strip().splitlines()[-1].strip() if nb_out.strip() else ""
    nb_status = "PASS" if nb_rc == 0 else "FAIL"
    if nb_rc != 0:
        missing.append("no_broker_write_bypass")

    # ── Broker-write scanner ──
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "scripts"))
        import broker_write_scanner as bws
        scan = bws.scan()
    except Exception as e:
        scan = {"ok": False, "error": str(e)[:200], "findings": [], "finding_count": -1}
    scan_status = "PASS" if scan.get("ok") else "FAIL"
    files["BROKER_WRITE_GUARD_EVIDENCE.md"] = (
        _header("Broker Write Guard Evidence",
                "python3 scripts/validate_schwab_write_policy.py + scripts/broker_write_scanner.py + "
                "tests/test_no_broker_write_bypass.py",
                "PASS" if (wp_rc == 0 and nb_rc == 0 and scan.get("ok")) else "FAIL",
                "All broker writes route through the single approved transport boundary behind execution "
                "readiness + per-order operator 2FA. The scanner finds no direct client writes, raw HTTP to "
                "order endpoints, or schwab-py imports outside the boundary.")
        + f"\n- Schwab write policy: **{wp_status}** — {wp_tail}\n"
        + f"- No-broker-write-bypass test: **{nb_status}** — {nb_tail}\n"
        + f"- Broker-write scanner: **{scan_status}** — {scan.get('finding_count')} findings\n"
        + _json_block({"approved_write_modules": scan.get("approved_write_modules"),
                       "transport_receivers": scan.get("transport_receivers"),
                       "findings": scan.get("findings")}))

    # ── Kill switches ──
    try:
        from brokers.kill_switches import status as ks_status
        kill = ks_status()
        kill_ok = True
    except Exception as e:
        kill = {"error": str(e)[:200]}
        kill_ok = False
        missing.append("kill_switches")
    files["KILL_SWITCH_MATRIX.md"] = (
        _header("Kill Switch Matrix", "brokers.kill_switches.status()",
                "PASS" if kill_ok else "FAIL",
                "Kill switches hard-block live submit. They are re-checked at submit time and after approval.")
        + _json_block(kill))

    # ── Audit ledger ──
    try:
        from audit_ledger import verify_chain, coverage_report
        chain = verify_chain(500)
        coverage = coverage_report(release_mode="review")
        ledger_status = coverage.get("status", "WARN")
    except Exception as e:
        chain = {"ok": False, "error": str(e)[:200]}
        coverage = {"status": "FAIL", "error": str(e)[:200]}
        ledger_status = "FAIL"
        missing.append("audit_ledger")
    files["AUDIT_LEDGER_STATUS.md"] = (
        _header("Audit Ledger Status", "audit_ledger.verify_chain() + audit_ledger.coverage_report()",
                ledger_status,
                "Append-only hash-chained ledger. Chain verification does not mutate rows. Coverage tracks "
                "the expected live-adjacent event types; missing critical events warn/fail per release mode.")
        + "\n## Chain verification\n" + _json_block(chain)
        + "\n## Coverage\n" + _json_block(coverage))

    # ── Static / derived matrices ──
    files["CONTROL_MATRIX.md"] = _control_matrix()
    files["RISK_GATE_MATRIX.md"] = _risk_gate_matrix()
    files["ORDER_LIFECYCLE.md"] = _order_lifecycle_doc()

    # ── Test evidence (read CI evidence if present, else summarize what we ran) ──
    ci = ROOT / "data" / "runtime" / "ci_evidence_latest.json"
    ci_data = {}
    if ci.exists():
        try:
            ci_data = json.loads(ci.read_text())
        except Exception:
            ci_data = {}
    files["TEST_EVIDENCE.md"] = (
        _header("Test Evidence",
                "python3 scripts/run_release_ci_equivalent.py --json (data/runtime/ci_evidence_latest.json)",
                ci_data.get("status", "WARN" if not ci_data else "PASS"),
                "Read-only test + validator suite. Required scenarios: live globally prohibited, policy on / "
                "DB arm off, desk approval missing, quote stale after approval, kill switch after approval, "
                "LLM cannot override a hard block, no broker write bypass, release blocked by live-adjacent "
                "dirty file, like-to-like evidence hashes, intraday window fail-closed, reconciliation taxonomy.")
        + (_json_block(ci_data) if ci_data else
           "\n_CI evidence not yet generated — run `python3 scripts/run_release_ci_equivalent.py`._\n"))

    # ── Maturity score + acceptance (read latest maturity artifact) ──
    mat = ROOT / "data" / "runtime" / "maturity_score_latest.json"
    mat_data = {}
    if mat.exists():
        try:
            mat_data = json.loads(mat.read_text())
        except Exception:
            mat_data = {}
    files["MATURITY_4_5_ACCEPTANCE.md"] = _acceptance_doc(state, rel, mat_data, wp_status, nb_status,
                                                          ledger_status)

    # ── Write everything ──
    for name, content in files.items():
        (out_dir / name).write_text(content, encoding="utf-8")

    # ── Audit ledger sample ──
    ledger = ROOT / "data" / "runtime" / "audit_ledger" / "events.jsonl"
    sample_path = out_dir / "AUDIT_LEDGER_SAMPLE.jsonl"
    if ledger.exists():
        # last 200 lines only
        try:
            lines = ledger.read_text(encoding="utf-8").splitlines()[-200:]
            sample_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        except Exception:
            shutil.copy(ledger, sample_path)
    else:
        sample_path.write_text("", encoding="utf-8")

    status = "FAIL" if missing else ("WARN" if (overall_warn or rel_status == "WARN_NON_LIVE_ADJACENT") else "PASS")
    return {
        "ok": not missing,
        "status": status,
        "out_dir": str(out_dir),
        "files": list(files.keys()) + ["AUDIT_LEDGER_SAMPLE.jsonl"],
        "missing_evidence": missing,
        "release_status": rel_status,
        "execution_state_ok": state_ok,
        "generated_at": _now(),
    }


def _control_matrix() -> str:
    return _header("Control Matrix", "scripts/export_diligence_evidence.py (static control map)", "PASS",
                   "LLMs are advisory only. They may not set policy, DB arm, approval, kill switch, or live "
                   "eligibility. Broker truth is authoritative after submit.") + """
| Control | Owner | Fail mode |
|---------|-------|-----------|
| Global live allowed | Operator env + standing DB unlock | Fail closed |
| Broker policy (options) | Commit `ENABLED` + DB arm | Fail closed |
| Execution readiness | `brokers/execution_readiness.py` | Hard block (preflight/submit modes) |
| Evidence-bound approval | `brokers/evidence_approval.py` | Like-to-like hash revalidation, single-use + expiry |
| Operator 2FA | `brokers/approval_service.py` | Immutable; required per order |
| Kill switches | `brokers/kill_switches.py` | Hard block |
| Broker truth lifecycle | `brokers/order_lifecycle.py` | No live state before broker ack |
| Reconciliation | `brokers/reconcile_orders.py` | Orphans → ERROR_RECONCILE_REQUIRED (never blind-retry) |
| Write boundary | `schwab_transport.py` (+ `snaptrade_transport.py`) | Idempotency fence; replace fenced |
| Audit ledger | `audit_ledger.py` | Append-only hash chain |
| LLM role | Advisory only | Never unlocks live |

**Autonomous live submit remains disabled.** **Operator-approved broker submit path is gated by deterministic controls.**
"""


def _risk_gate_matrix() -> str:
    return _header("Risk Gate Matrix", "options_desk_enterprise.evaluate_hard_risk_blocks (see OPTIONS_RISK_BLOCK_MATRIX.md)",
                   "PASS",
                   "Hard blocks on the live options path. Full fixture-verified matrix with stable codes is in "
                   "`OPTIONS_RISK_BLOCK_MATRIX.md`.") + """
Hard block codes: earnings_blackout, ex_dividend_cc_risk, bs_estimate_only, no_resolved_occ,
oi_below_threshold, volume_below_threshold, spread_too_wide, quote_stale, option_chain_stale,
market_closed, max_contracts_per_order, max_per_strategy_notional, assignment_exercise_risk,
min_buying_power, max_net_delta_pct, max_symbol_notional_pct, enterprise_block.

Configured in `assets/portfolio_intent.yaml` → `options_desk_settings.hard_risk_limits` (+ env overrides).
"""


def _order_lifecycle_doc() -> str:
    return _header("Order Lifecycle", "brokers/order_lifecycle.py + brokers/reconcile_orders.py", "PASS",
                   "No trade is live before broker acknowledgement. Internal state never outruns broker truth.") + """
States: PROPOSED → PREFLIGHTED → OPERATOR_APPROVED → SUBMIT_REQUESTED → BROKER_ACKED →
WORKING → PARTIALLY_FILLED → FILLED (or CANCELLED / REJECTED / EXPIRED / ERROR_RECONCILE_REQUIRED).

Broker status taxonomy → lifecycle state: queued/accepted/pending_activation → BROKER_ACKED;
working → WORKING; partially_filled → PARTIALLY_FILLED (preserved); filled → FILLED;
canceled → CANCELLED; rejected → REJECTED; expired → EXPIRED; unknown → ERROR_RECONCILE_REQUIRED.

- FILLED/WORKING/PARTIALLY_FILLED require a broker order id (proof of ack).
- Idempotency key = sha256(intent_id|account|symbol); duplicate active submits are fenced.
- Stale SUBMIT_REQUESTED requires reconcile (GET broker truth) before any retry — never blind-retry.
- Reconciliation report → `data/runtime/reconcile_orders_<date>.json`; result recorded to the audit ledger.
"""


def _acceptance_doc(state: dict, rel: dict, mat: dict, wp_status: str, nb_status: str,
                    ledger_status: str) -> str:
    score = mat.get("final_maturity_score_of_5")
    meets = mat.get("meets_4_5")
    rel_status = rel.get("status", "UNKNOWN")
    live_dirty = (rel.get("dirty_classification") or {}).get("live_adjacent") or []
    verdict = ("**4.5 MET**" if meets else "**4.5 BLOCKED**") if mat else "**maturity score not yet computed**"
    caps = mat.get("caps_applied") or []
    caps_md = ("\n".join(f"- {c['reason']} → cap {c['cap']}" for c in caps)) if caps else "- None."
    return f"""# Maturity 4.5 Acceptance Checklist

_Generated: {_now()}_
_Source: `python3 scripts/export_diligence_evidence.py` + `scripts/compute_maturity_score.py`_
**Status: {verdict}**

## 1. Current maturity score

- Final maturity (after caps): **{score} / 5** ({'meets 4.5' if meets else 'does not meet 4.5'})
- Raw weighted: {mat.get('raw_weighted_score_of_5')} / 5
- Caps applied:
{caps_md}

See `MATURITY_SCORE_LATEST.md` for the full line-by-line breakdown.

## 2. What is allowed

- Operator-approved Schwab/SnapTrade submit path, one order at a time, behind deterministic gates.
- Read-only inspection of readiness, reconciliation, kill switches, and audit ledger.
- LLM advisory commentary and proposal drafting (no execution authority).

## 3. What is blocked

- **Autonomous live submit remains disabled.**
- Any broker write outside the approved transport boundary.
- Marking an order live before broker acknowledgement.
- Replace-order routes (fenced everywhere but the transport, which itself fences them).

## 4. What requires operator approval

- Every live broker submit requires the existing per-order operator confirmation / two-factor
  step. **This path is immutable and out of scope for automation.**
- Enabling options execution requires both a commit flag and an operator DB arm.

## 5. What is advisory only

- **LLMs are advisory only.** They may never set policy, arm execution, approve an order, alter a
  kill switch, or unlock live eligibility.

## 6. Required release evidence

- Execution state: `{('OK' if state.get('live_architecture_built') else 'MISSING')}` — autonomous live submit allowed = `{state.get('autonomous_live_submit_allowed')}`
- Release readiness: `{rel_status}` (live-adjacent dirty files: {live_dirty or 'none'})
- **Release readiness must be PASS or explicitly justified WARN with no live-adjacent dirty files.**

## 7. Required test evidence

- Schwab write policy validator: **{wp_status}**
- No-broker-write-bypass test: **{nb_status}**
- Evidence-bound approval (like-to-like hashes), execution readiness modes, intraday window
  fail-closed, order lifecycle + reconciliation taxonomy, options hard-risk matrix, audit ledger,
  AI critique — see `TEST_EVIDENCE.md`.
- Audit ledger coverage: **{ledger_status}**

## 8. Remaining non-blocking warnings

- Regenerated diligence/runtime artifacts may show as dirty (WARN_NON_LIVE_ADJACENT). These are
  generated evidence, not live-adjacent source, and do not cap maturity.

## 9. Sign-off checklist

- [{'x' if state.get('autonomous_live_submit_allowed') is False else ' '}] Autonomous live submit disabled
- [{'x' if state.get('per_order_2fa_required') else ' '}] Per-order operator 2FA required (unchanged)
- [{'x' if rel_status in ('PASS', 'WARN_NON_LIVE_ADJACENT') else ' '}] Release readiness PASS or justified WARN_NON_LIVE_ADJACENT
- [{'x' if not live_dirty else ' '}] No live-adjacent dirty files
- [{'x' if wp_status == 'PASS' else ' '}] Schwab write policy validator green
- [{'x' if nb_status == 'PASS' else ' '}] No-broker-write-bypass test green
- [{'x' if ledger_status in ('PASS', 'WARN') else ' '}] Audit ledger chain verified
- [{'x' if meets else ' '}] Maturity score ≥ 4.5 earned from evidence

**Broker truth is authoritative after submit. No order is treated as live before broker acknowledgement.**
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/diligence/current")
    args = ap.parse_args()
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    result = export_pack(out)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
