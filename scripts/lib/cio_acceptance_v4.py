"""cio_acceptance_v4.py — fail-closed CIO production acceptance auditor.

Phase 1 of remediation v4.0: the auditor itself cannot award PASS for
detecting a failure, for offline-only capability, or while P0/P1 remain open.

LIVE_ACCEPTANCE is computed only from production snapshots (endpoints,
release stamps, committed manifest, live frontend bundle). Offline/tree
composition belongs under BUILD_CAPABILITY and never flips a live gate.

Authority: READ_ONLY_ADVISORY. This module never sends Telegram and never
places broker orders.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

ACCEPTANCE_VERSION = "cio_acceptance_v4.1.0"
AUTHORITY = "READ_ONLY_ADVISORY"
EXPECTED_AUTHORITY_SURFACES = (
    "capital_plan", "cio_home", "report", "advisory", "telegram_payload",
)

HARD_GATE_IDS = (
    "G1_exact_live_sha",
    "G2_release_manifest_parity",
    "G3_drive_manifest_parity",
    "G4_financial_book_reconciliation",
    "G5_zero_material_price_conflicts",
    "G6_required_freshness",
    "G7_capital_plan_invariants",
    "G8_decision_cross_surface_parity",
    "G9_advisory_ui_provenance_live",
    "G10_report_live_html",
    "G11_report_live_pdf",
    "G12_report_live_docx",
    "G13_report_visual_qa",
    "G14_cio_telegram_isolation",
    "G15_real_cio_e2e_canary",
    "G16_zero_duplicate_notification",
    "G17_authority_read_only",
    "G18_required_ci_green",
    "G19_no_p0_p1_open",
    "G20_strategy_claims_honestly_graded",
)

VERIFIED_BOOK = frozenset({"VERIFIED_CURRENT", "VERIFIED_AS_OF"})
MATERIAL_CONFLICT_TYPES = frozenset({
    "dual_price_conflict",
    "valuation_residual_material",
    "proxy_used_for_valuation",
    "hidden_residual_injection",
    "weight_mismatch",
    "upl_mismatch",
    "upl_pct_mismatch",
})
# source_time_residual / shares×mark vs broker MV is a note, not a G5 material fail.
# Grades that may not be advertised as Trade-AI-reproduced knowledge.
UNVALIDATED_GRADES = frozenset({
    "unverified_source_claim",
    "source_claim_only",
    "D",
    "d",
})


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _sha12(val: Any) -> str:
    s = str(val or "").strip()
    return s[:12] if s else ""


def _full_sha(val: Any) -> str:
    return str(val or "").strip()


def _sha_equal(a: Any, b: Any) -> bool:
    aa, bb = _full_sha(a), _full_sha(b)
    if not aa or not bb:
        return False
    n = min(len(aa), len(bb), 40)
    if n < 12:
        return False
    return aa[:n] == bb[:n] and (len(aa) < 40 or len(bb) < 40 or aa[:40] == bb[:40])


def artifact_hash(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def make_gate(
    gate_id: str,
    *,
    expected: str,
    actual: Any,
    status: str,
    reason: str,
    severity: str = "P0",
    path: str = "",
    sha: str = "",
    now: Optional[datetime] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Canonical gate record. status is PASS | FAIL | NOT_RUN only.

    NOT_RUN is treated as FAIL for required live gates (cannot prove → cannot pass).
    """
    st = str(status or "FAIL").upper()
    if st not in ("PASS", "FAIL", "NOT_RUN"):
        st = "FAIL"
    if st == "NOT_RUN":
        # Fail-closed: absence of proof is not a pass.
        st = "FAIL"
        reason = f"NOT_RUN/unproven: {reason}"
    rec = {
        "gate": gate_id,
        "expected": expected,
        "actual": actual,
        "status": st,
        "reason": reason,
        "severity": severity if st == "FAIL" else None,
        "path": path,
        "sha": sha,
        "timestamp": _now_iso(now),
        "artifact_hash": "",
        "required": True,
    }
    if extra:
        rec["extra"] = extra
    rec["artifact_hash"] = artifact_hash({
        k: rec[k] for k in ("gate", "expected", "actual", "status", "reason")
    })
    return rec


def collect_p0_p1(gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for g in gates:
        if g.get("status") != "FAIL":
            continue
        if g.get("gate") == "G19_no_p0_p1_open":
            continue  # derived last
        sev = g.get("severity") or "P0"
        if sev in ("P0", "P1"):
            out.append({
                "gate": g.get("gate"),
                "severity": sev,
                "reason": g.get("reason"),
            })
    return out


def finalize_verdict(
    gates: list[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    live_sha: str = "",
    main_sha: str = "",
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Compute PRODUCTION ACCEPTANCE. Any P0/P1 FAIL → FAIL. No score override."""
    # G19 last: derived from remaining required fails
    others = [g for g in gates if g.get("gate") != "G19_no_p0_p1_open"]
    defects = collect_p0_p1(others)
    g19_pass = len(defects) == 0
    g19 = make_gate(
        "G19_no_p0_p1_open",
        expected="p0_p1_open == []",
        actual=f"{len(defects)} open P0/P1",
        status="PASS" if g19_pass else "FAIL",
        reason=(
            "No P0/P1 defects."
            if g19_pass
            else "Open P0/P1: " + "; ".join(
                f"{d['gate']}({d['severity']})" for d in defects[:12]
            )
        ),
        severity="P0",
        sha=live_sha,
        now=now,
        extra={"defects": defects},
    )
    all_gates = others + [g19]
    by_id = {g["gate"]: g for g in all_gates}

    failed = [g for g in all_gates if g.get("status") != "PASS"]
    p0 = [g for g in all_gates if g.get("status") == "FAIL" and g.get("severity") == "P0"]
    p1 = [g for g in all_gates if g.get("status") == "FAIL" and g.get("severity") == "P1"]
    p2 = [g for g in all_gates if g.get("status") == "FAIL" and g.get("severity") == "P2"]

    production_pass = len(failed) == 0
    # Hard rule: score cannot override
    if defects or p0 or p1:
        production_pass = False

    categories = {
        "FINANCIAL_TRUTH": _cat(by_id, ["G4_financial_book_reconciliation", "G5_zero_material_price_conflicts"]),
        "RELEASE_TRUTH": _cat(by_id, ["G1_exact_live_sha", "G2_release_manifest_parity", "G3_drive_manifest_parity"]),
        "CIO_UX": _cat(by_id, ["G8_decision_cross_surface_parity", "G9_advisory_ui_provenance_live"]),
        "REPORT": _cat(by_id, ["G10_report_live_html", "G11_report_live_pdf", "G12_report_live_docx", "G13_report_visual_qa"]),
        "TELEGRAM": _cat(by_id, ["G14_cio_telegram_isolation", "G15_real_cio_e2e_canary", "G16_zero_duplicate_notification"]),
        "STOCK_ALMANAC_INTEGRATION": "FAIL",  # never PASS from scaffold; G20 is honesty only
        "BROADER_RESEARCH_BRAIN": "FAIL",
        "RESEARCH_GOVERNANCE_ACCEPTANCE": "NOT_YET_INTEGRATED",
        "AUTHORITY_BOUNDARY": _cat(by_id, ["G17_authority_read_only"]),
        "FRESHNESS": _cat(by_id, ["G6_required_freshness"]),
        "CAPITAL_PLAN": _cat(by_id, ["G7_capital_plan_invariants"]),
        "STRATEGY_GRADING_HONEST": _cat(by_id, ["G20_strategy_claims_honestly_graded"]),
        "CI": _cat(by_id, ["G18_required_ci_green"]),
    }
    # Almanac / research brain stay FAIL until dedicated later phases prove them.
    # Honesty (G20) passing does not mean integration.

    result = {
        "acceptance_version": ACCEPTANCE_VERSION,
        "as_of": _now_iso(now),
        "authority": AUTHORITY,
        "CORE_CIO_PRODUCTION_ACCEPTANCE": "PASS" if production_pass else "FAIL",
        "RESEARCH_GOVERNANCE_ACCEPTANCE": "NOT_YET_INTEGRATED",
        "FULL_INVESTMENT_OFFICE_ACCEPTANCE": "FAIL",
        # Legacy alias — core only. Does not imply Almanac / research-brain integration.
        "PRODUCTION_ACCEPTANCE": "PASS" if production_pass else "FAIL",
        "PRODUCTION_ACCEPTANCE_ALIAS_OF": "CORE_CIO_PRODUCTION_ACCEPTANCE",
        "pass_threshold": production_pass,  # kept for CLI compat; equals CORE_CIO_PRODUCTION_ACCEPTANCE
        "categories": categories,
        "gates": all_gates,
        "OPEN_P0": len(p0),
        "OPEN_P1": len(p1),
        "OPEN_P2": len(p2),
        "p0_p1_open": [
            f"{d['gate']}: {d['reason']}" for d in defects
        ] + ([] if g19_pass else [g19["reason"]]),
        "git_main": main_sha,
        "live_sha": live_sha,
        "note": (
            "LIVE_ACCEPTANCE only. BUILD_CAPABILITY (offline/tree) is recorded "
            "separately and cannot produce PRODUCTION_ACCEPTANCE=PASS. "
            "Any P0/P1 FAIL forces FAIL. Detecting a defect is not a pass."
        ),
    }
    if extra:
        result["extra"] = extra
    return result


def _cat(by_id: dict[str, dict], ids: list[str]) -> str:
    for i in ids:
        g = by_id.get(i)
        if not g or g.get("status") != "PASS":
            return "FAIL"
    return "PASS"


# ─────────────────────────────────────────────────────────────────────────────
# Pure evaluators (snapshots in, gates out). No network.
# ─────────────────────────────────────────────────────────────────────────────

def eval_g1_exact_live_sha(
    *,
    live_sha: str,
    main_sha: str,
    remote_truth: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict:
    truth = remote_truth or {}
    if not truth.get("proven"):
        return make_gate(
            "G1_exact_live_sha",
            expected="fresh remote main SHA; live equals required content SHA",
            actual={"live": _sha12(live_sha), "local_main": _sha12(main_sha), "remote_truth": "missing"},
            status="FAIL",
            reason="Remote main was not freshly resolved (fetch/ls-remote). Stale origin/main cannot receive credit.",
            severity="P0",
            path="/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/BUILD_SHA",
            sha=live_sha,
            now=now,
        )
    if not truth.get("local_matches_remote"):
        return make_gate(
            "G1_exact_live_sha",
            expected="local origin/main == git ls-remote origin refs/heads/main",
            actual={
                "local": _sha12(truth.get("local_origin_main_sha")),
                "remote": _sha12(truth.get("remote_main_sha")),
            },
            status="FAIL",
            reason="Stale local origin/main — acceptance cannot certify GitHub main from an unfetched ref.",
            severity="P0",
            sha=live_sha,
            now=now,
        )
    try:
        from scripts.lib.cio_remote_sha_truth import live_matches_required_content
        ok, why = live_matches_required_content(live_sha=live_sha, truth=truth)
    except Exception as e:
        ok, why = False, f"classifier_error:{type(e).__name__}"
    return make_gate(
        "G1_exact_live_sha",
        expected="live BUILD_SHA equals attested runtime content (not an unfetched origin/main)",
        actual={
            "live": _sha12(live_sha),
            "remote_main": _sha12(truth.get("remote_main_sha")),
            "content": _sha12(truth.get("attested_runtime_content_sha")),
            "class": truth.get("main_commit_class"),
            "why": why,
        },
        status="PASS" if ok else "FAIL",
        reason=(
            f"Remote SHA truth: {why}."
            if ok
            else f"Release SHA truth failed: {why}."
        ),
        severity="P0",
        path="/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/BUILD_SHA",
        sha=live_sha,
        now=now,
    )


def eval_g2_release_manifest_parity(
    *,
    manifest: dict[str, Any],
    live_sha: str,
    main_sha: str,
    now: Optional[datetime] = None,
) -> dict:
    man = manifest or {}
    canon = _full_sha(man.get("canonical_source_sha"))
    backend = _full_sha(man.get("backend_release_sha"))
    status = str(man.get("status") or "")
    origin = _full_sha(man.get("origin_main_sha"))
    pin = {"ok": False}
    try:
        from scripts.cio_release_manifest import pin_only_parent
        pin = pin_only_parent(_full_sha(main_sha), canon)
    except Exception:
        pin = {"ok": False, "reason": "pin_helper_unavailable"}
    checks = {
        "status_production": status == "production",
        "canonical_eq_main": bool(canon) and canon == _full_sha(main_sha),
        "canonical_eq_live": bool(canon) and canon == _full_sha(live_sha),
        "backend_eq_live": bool(backend) and backend == _full_sha(live_sha),
        "origin_eq_main": bool(origin) and origin == _full_sha(main_sha),
        "live_eq_main": bool(live_sha) and _full_sha(live_sha) == _full_sha(main_sha),
        "pin_only_parent": bool(pin.get("ok")),
    }
    # Allowed: exact 5-way match, OR production pin-only parent when live==main
    # (the self-referential pin commit cannot contain its own SHA).
    exact = (
        checks["status_production"]
        and checks["canonical_eq_main"]
        and checks["canonical_eq_live"]
        and checks["backend_eq_live"]
        and checks["origin_eq_main"]
    )
    pin_ok = (
        checks["status_production"]
        and checks["live_eq_main"]
        and checks["pin_only_parent"]
        and (checks["backend_eq_live"] or checks["canonical_eq_live"] or pin.get("ok"))
    )
    # After a pin-only merge, backend/canonical name the content SHA; live/main are the pin.
    if pin_ok and not checks["backend_eq_live"]:
        pin_ok = True  # parent pin is the documented exception
    ok = exact or pin_ok
    return make_gate(
        "G2_release_manifest_parity",
        expected="committed production manifest SHAs == live == origin/main",
        actual={"status": status, "canonical": _sha12(canon), "backend": _sha12(backend),
                "origin_main": _sha12(origin), "checks": checks},
        status="PASS" if ok else "FAIL",
        reason=(
            "Committed manifest matches live runtime and origin/main."
            if ok
            else "Committed manifest is stale, RC, or SHA-mismatched. "
                 "CI must not regenerate-before-validate to hide this."
        ),
        severity="P0",
        path="docs/investment-office/RELEASE_MANIFEST.json",
        sha=canon,
        now=now,
    )


def eval_g3_drive_manifest_parity(
    *,
    git_manifest_hash: str,
    drive_canonical_hash: str = "",
    drive_duplicate_count: Optional[int] = None,
    drive_proven: bool = False,
    drive_canonical_file_id: str = "",
    now: Optional[datetime] = None,
) -> dict:
    """Drive parity. Unproven or unknown uniqueness → FAIL (not PASS)."""
    if not drive_proven:
        return make_gate(
            "G3_drive_manifest_parity",
            expected="canonical Drive file ID hash == Git manifest hash",
            actual={"git_hash": git_manifest_hash, "drive_proven": False,
                    "drive_duplicates": drive_duplicate_count,
                    "file_id": drive_canonical_file_id or None},
            status="FAIL",
            reason="Drive canonical hash was not independently proven this run.",
            severity="P1",
            path="Drive:investment-office/RELEASE_MANIFEST.json",
            now=now,
        )
    # File-ID method: uniqueness-by-name is not required when the object ID is pinned.
    if drive_canonical_file_id:
        ok = bool(git_manifest_hash) and git_manifest_hash == drive_canonical_hash
    elif drive_duplicate_count is None:
        ok = False
    else:
        ok = (
            bool(git_manifest_hash)
            and git_manifest_hash == drive_canonical_hash
            and drive_duplicate_count <= 1
        )
    return make_gate(
        "G3_drive_manifest_parity",
        expected="single Drive canonical manifest hash == Git manifest hash",
        actual={"git_hash": git_manifest_hash, "drive_hash": drive_canonical_hash,
                "duplicates": drive_duplicate_count},
        status="PASS" if ok else "FAIL",
        reason=(
            "Drive canonical matches Git."
            if ok
            else "Drive hash mismatch or multiple unmarked RELEASE_MANIFEST copies."
        ),
        severity="P1",
        now=now,
    )


def eval_g4_financial_book(
    *,
    gate: dict[str, Any],
    now: Optional[datetime] = None,
) -> dict:
    """Detector running is not a pass. Book must be verified, invariants hold."""
    quality = str((gate or {}).get("overall_quality") or "")
    ok_flag = (gate or {}).get("ok")
    inv = (gate or {}).get("book_invariants") or {}
    cash_ok = bool(inv.get("cash_plus_mv_eq_reported_total"))
    accts_ok = bool(inv.get("sum_accounts_eq_derived"))
    verified = quality in VERIFIED_BOOK
    mutated = bool((gate or {}).get("acceptance_mutated_audited_book"))
    proxy_val = bool((gate or {}).get("proxy_valuation_used"))
    hidden = bool((gate or {}).get("hidden_residual_injection"))
    ok = (
        verified and cash_ok and accts_ok and ok_flag is True
        and not mutated and not proxy_val and not hidden
    )
    return make_gate(
        "G4_financial_book_reconciliation",
        expected="verified book; identities; auditor did not mutate; no proxy valuation; no hidden residual",
        actual={
            "overall_quality": quality,
            "ok": ok_flag,
            "exception_count": (gate or {}).get("exception_count"),
            "invariants": inv,
            "mutated": mutated,
            "proxy_valuation_used": proxy_val,
            "hidden_residual_injection": hidden,
            "note_count": (gate or {}).get("nonmaterial_reconciliation_note_count"),
        },
        status="PASS" if ok else "FAIL",
        reason=(
            "Financial book verified; cash+MV and account sums reconcile."
            if ok
            else (
                f"Book is {quality or 'UNKNOWN'} — detecting CONFLICTED/STALE is not a pass. "
                f"exceptions={(gate or {}).get('exception_count')} "
                f"cash+mv={cash_ok} accounts={accts_ok}."
            )
        ),
        severity="P0",
        path="/api/v2/cio/capital-plan#financial_truth_gate",
        now=now,
    )


def eval_g5_zero_material_conflicts(
    *,
    exceptions: list[dict[str, Any]],
    conflicted_symbols: Optional[list[str]] = None,
    exception_count: Optional[int] = None,
    overall_quality: str = "",
    now: Optional[datetime] = None,
) -> dict:
    material = [
        e for e in (exceptions or [])
        if str(e.get("type") or e.get("kind") or "") in MATERIAL_CONFLICT_TYPES
    ]
    symbols = sorted({
        str(e.get("symbol") or "") for e in material if e.get("symbol")
    } | {str(s) for s in (conflicted_symbols or []) if s})
    count = exception_count
    if count is None:
        count = len(exceptions or [])
    dirty_quality = str(overall_quality or "") in ("CONFLICTED", "STALE", "DATA_UNAVAILABLE", "ERROR")
    # Notes (source-time residuals) may appear without being material.
    notes = [
        e for e in (exceptions or [])
        if str(e.get("type") or "") in ("source_time_residual",) or e.get("material") is False
    ]
    # Missing exception detail while the book reports conflicts is FAIL, not a clean pass.
    opaque_conflicts = (count or 0) > 0 and not material and not symbols and not notes
    ok = len(material) == 0 and len(symbols) == 0 and not dirty_quality and not opaque_conflicts
    return make_gate(
        "G5_zero_material_price_conflicts",
        expected="zero unresolved material conflicts; typed source-time residuals may remain as notes",
        actual={
            "material_exceptions": len(material),
            "nonmaterial_reconciliation_note_count": len(notes),
            "conflicted_symbols": symbols,
            "exception_count": count,
            "overall_quality": overall_quality or None,
            "opaque_conflicts": opaque_conflicts,
        },
        status="PASS" if ok else "FAIL",
        reason=(
            "No material price conflicts."
            if ok
            else (
                f"Book reports exception_count={count} quality={overall_quality or 'n/a'} "
                f"but exception rows were not attached — cannot treat as clean."
                if opaque_conflicts
                else f"{len(material)} material exceptions on {len(symbols)} symbols: {symbols[:16]}"
            )
        ),
        severity="P0",
        path="holdings.json / FinancialTruthGate.exceptions",
        now=now,
    )


def eval_g6_required_freshness(
    *,
    decisions: list[dict[str, Any]],
    now: Optional[datetime] = None,
) -> dict:
    """Undated / evaluated_now must never count as fresh. ACT NOW requires timestamps."""
    violations: list[str] = []
    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        sym = str(d.get("symbol") or "?")
        label = str(d.get("action_label") or "")
        act = bool(d.get("act_now")) or label == "ACT_NOW"
        fresh = d.get("freshness") or {}
        board = fresh.get("board") if isinstance(fresh, dict) else None
        decision_rec = {}
        if isinstance(board, list):
            for rec in board:
                if isinstance(rec, dict) and rec.get("name") == "decision":
                    decision_rec = rec
                    break
        detail = str(decision_rec.get("detail") or "")
        if detail in ("evaluated_now", "undated"):
            violations.append(f"{sym}: decision freshness used {detail} loophole")
        generated = d.get("generated_at") or d.get("revalidated_at")
        age = decision_rec.get("age_seconds")
        # Instant-zero age with no persisted timestamp is the same loophole.
        if generated is None and age == 0.0 and decision_rec:
            violations.append(f"{sym}: decision age=0 with no generated_at/revalidated_at")
        if act and not generated:
            violations.append(f"{sym}: ACT NOW without generated_at/revalidated_at")
        if act and detail in ("undated", "evaluated_now", "missing"):
            violations.append(f"{sym}: ACT NOW with undated decision clock")
        if act and not (d.get("decision_evidence_digest") or d.get("decision_input_digest")):
            violations.append(f"{sym}: ACT NOW without decision evidence digest")
        # A builder-now revalidation is not evidence revalidation.
        if str(d.get("decision_revalidation_reason") or "") == "builder_ran_now":
            violations.append(f"{sym}: revalidated_at minted by builder clock")
    ok = not violations
    return make_gate(
        "G6_required_freshness",
        expected="no evaluated_now loophole; ACT NOW requires real decision timestamps",
        actual={"violations": violations[:20], "decision_count": len(decisions or [])},
        status="PASS" if ok else "FAIL",
        reason="Freshness timestamps honest." if ok else "; ".join(violations[:8]),
        severity="P0",
        path="/api/v2/cio/capital-plan#position_decisions.freshness",
        now=now,
    )


def eval_g7_capital_plan_invariants(
    *,
    plan: dict[str, Any],
    now: Optional[datetime] = None,
) -> dict:
    p = plan or {}
    ledger = p.get("account_capital_ledger") or {}
    inv = ledger.get("invariants") if isinstance(ledger, dict) else {}
    if not isinstance(inv, dict):
        inv = {}
    cash = float(p.get("cash_total_usd") or 0)
    earmark = float(p.get("cash_earmarked_redeploy_usd") or 0)
    deploy = float(p.get("net_recommended_deploy_usd") or 0)
    investable = float(p.get("cash_investable_usd") or 0)
    prospective = float((p.get("capital_sources") or {}).get("total_prospective_raise_usd") or 0)
    auth = str(p.get("authority") or "")
    checks = {
        "has_ledger": bool(ledger.get("accounts") or ledger.get("portfolio_aggregate")),
        "earmark_le_cash": earmark <= cash + 0.02,
        "deploy_bounded": deploy <= investable + prospective + 0.02,
        "authority": auth == AUTHORITY,
        "ledger_invariants_ok": False,
    }
    required_inv = ("earmark_le_settled_cash", "deploy_le_free_plus_prospective")
    missing_inv = [k for k in required_inv if k not in inv]
    if missing_inv:
        checks["ledger_invariants_ok"] = False
        checks["missing_required_invariants"] = missing_inv
    else:
        checks["ledger_invariants_ok"] = all(inv.get(k) is True for k in required_inv)
    ok = all(v is True for k, v in checks.items() if k != "missing_required_invariants")
    return make_gate(
        "G7_capital_plan_invariants",
        expected="ledger present; earmark≤cash; deploy≤investable+prospective; READ_ONLY_ADVISORY",
        actual={"checks": checks, "cash": cash, "earmark": earmark, "deploy": deploy},
        status="PASS" if ok else "FAIL",
        reason="Capital-plan invariants hold." if ok else f"Invariant failure: {checks}",
        severity="P0",
        path="/api/v2/cio/capital-plan",
        now=now,
    )


def eval_g8_decision_parity(
    *,
    parity: dict[str, Any],
    now: Optional[datetime] = None,
) -> dict:
    ok = bool((parity or {}).get("ok") is True)
    return make_gate(
        "G8_decision_cross_surface_parity",
        expected="decision_field_parity.ok == true across plan and CIO NOW",
        actual={
            "ok": (parity or {}).get("ok"),
            "mismatches": (parity or {}).get("field_mismatches"),
            "missing_required": (parity or {}).get("missing_required"),
        },
        status="PASS" if ok else "FAIL",
        reason="Cross-surface decision fields match." if ok else "Plan ↔ CIO NOW field parity failed.",
        severity="P0",
        path="/api/v3/cio/home#consistency.decision_field_parity",
        now=now,
    )


def eval_g9_advisory_ui_provenance(
    *,
    advisory_payload: Optional[dict[str, Any]],
    frontend_bundle_text: str = "",
    cio_hub_source: str = "",
    now: Optional[datetime] = None,
) -> dict:
    blob = json.dumps(advisory_payload or {}, default=str)
    has_api = ("advisory_provenance" in blob) or ("canonical_financial_facts" in blob)
    has_bundle = bool(frontend_bundle_text) and (
        "advisory_provenance" in frontend_bundle_text
        or "canonical_financial_facts" in frontend_bundle_text
        or "Current mark" in frontend_bundle_text
    )
    cio_ui = bool(cio_hub_source) and (
        "Material Today" in cio_hub_source
        or "Investment decisions" in cio_hub_source
        or "MATERIAL TODAY" in cio_hub_source
    )
    # Both Advisory provenance on the page/API AND CIO attention labels in UI.
    # Missing either is FAIL — backend-only helper is not "live".
    ok = has_api and has_bundle and cio_ui
    return make_gate(
        "G9_advisory_ui_provenance_live",
        expected="Advisory API+bundle render provenance; CIO UI renders four attention KPIs",
        actual={
            "advisory_api_has_provenance": has_api,
            "bundle_has_provenance_copy": has_bundle,
            "cio_ui_has_attention_labels": cio_ui,
            "bundle_chars": len(frontend_bundle_text or ""),
        },
        status="PASS" if ok else "FAIL",
        reason=(
            "Advisory provenance and CIO attention labels are in the live product."
            if ok
            else "Provenance helper is not on /v3/advisory and/or CIO UI still uses legacy KPI labels."
        ),
        severity="P0",
        path="/api/v3/advisory + /v3/assets/*.js + CioHub.tsx",
        now=now,
    )


def eval_g10_g12_report_formats(
    *,
    html_path: str = "",
    pdf_path: str = "",
    docx_path: str = "",
    source_sha: str = "",
    live_sha: str = "",
    synthetic: bool = False,
    report_instance: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> list[dict]:
    gates = []
    if synthetic:
        reason_prefix = "Synthetic/toy portfolio cannot prove live report. "
    else:
        reason_prefix = ""
    sha_ok = bool(source_sha) and bool(live_sha) and _full_sha(source_sha) == _full_sha(live_sha)
    inst = report_instance or {}

    def _fmt(gid: str, path: str, label: str, sev: str = "P0") -> dict:
        exists = bool(path)
        key = {"HTML": "html_sha256", "PDF": "pdf_sha256", "DOCX": "docx_sha256"}[label]
        hash_ok = bool(inst.get(key)) if inst else True
        inst_ok = bool(inst.get("report_instance_id")) if inst else True
        snap_ok = True
        if inst.get("portfolio_snapshot_hash") and inst.get("expected_portfolio_snapshot_hash"):
            snap_ok = inst.get("portfolio_snapshot_hash") == inst.get("expected_portfolio_snapshot_hash")
        ok = exists and (not synthetic) and sha_ok and hash_ok and inst_ok and snap_ok
        return make_gate(
            gid,
            expected=f"live-portfolio {label} bound to report_instance; source_sha == live SHA",
            actual={"path": path or None, "synthetic": synthetic, "source_sha": _sha12(source_sha),
                    "live_sha": _sha12(live_sha), "instance": inst.get("report_instance_id"),
                    "hash": inst.get(key)},
            status="PASS" if ok else "FAIL",
            reason=(
                f"Live {label} present with matching source SHA."
                if ok
                else reason_prefix + (
                    f"Missing production {label}."
                    if not exists
                    else ("Toy portfolio used." if synthetic else "source_sha does not match live SHA.")
                )
            ),
            severity=sev,
            path=path or f"live {label}",
            sha=source_sha,
            now=now,
        )

    gates.append(_fmt("G10_report_live_html", html_path, "HTML"))
    gates.append(_fmt("G11_report_live_pdf", pdf_path, "PDF"))
    gates.append(_fmt("G12_report_live_docx", docx_path, "DOCX"))
    return gates


def eval_g13_visual_qa(
    *,
    visual_qa_artifact: str = "",
    pages_inspected: int = 0,
    qa_pdf_sha256: str = "",
    report_pdf_sha256: str = "",
    pdf_page_count: int = 0,
    qa_result: str = "",
    qa_instance_id: str = "",
    report_instance_id: str = "",
    now: Optional[datetime] = None,
) -> dict:
    hash_ok = bool(qa_pdf_sha256) and qa_pdf_sha256 == report_pdf_sha256
    pages_ok = bool(pdf_page_count) and pages_inspected == pdf_page_count and pages_inspected > 0
    inst_ok = bool(qa_instance_id) and qa_instance_id == report_instance_id
    result_ok = str(qa_result or "").upper() == "PASS"
    ok = bool(visual_qa_artifact) and hash_ok and pages_ok and inst_ok and result_ok
    return make_gate(
        "G13_report_visual_qa",
        expected="QA bound to this PDF hash/instance; every page inspected; result=PASS",
        actual={
            "artifact": visual_qa_artifact or None,
            "pages_inspected": pages_inspected,
            "pdf_page_count": pdf_page_count,
            "qa_pdf_sha256": (qa_pdf_sha256 or "")[:16] or None,
            "report_pdf_sha256": (report_pdf_sha256 or "")[:16] or None,
            "instance_match": inst_ok,
            "result": qa_result or None,
        },
        status="PASS" if ok else "FAIL",
        reason=(
            f"Visual QA bound to PDF {report_pdf_sha256[:12]} ({pages_inspected}/{pdf_page_count} pages)."
            if ok
            else "Visual QA not bound to the current PDF instance/hash/all pages."
        ),
        severity="P1",
        path=visual_qa_artifact or "missing visual QA pack",
        now=now,
    )


def eval_g14_telegram_isolation(
    *,
    cio_token_env_set: bool,
    general_token_used_in_cio_transport: bool,
    interdict_on: bool,
    live_send_count_this_run: int,
    proof_general_sends: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Isolation: CIO path must not use general bot. Unproven general_not_used ≠ pass.

    A design-only import is not enough. We require: CIO transport does not
    reference general token, and either a measured general-send count of 0
    from a real canary, or interdict proven with zero sends this run *and*
    explicit proof_general_sends == 0 from transport audit.
    """
    if proof_general_sends is None:
        return make_gate(
            "G14_cio_telegram_isolation",
            expected="CIO bot/chat only; general bot send count proven 0",
            actual={
                "cio_token_env_set": cio_token_env_set,
                "general_used_in_cio_transport": general_token_used_in_cio_transport,
                "interdict_on": interdict_on,
                "sends_this_run": live_send_count_this_run,
                "proof_general_sends": None,
            },
            status="FAIL",
            reason="general_not_used was not proven (no transport measurement). Writing True is forbidden.",
            severity="P0",
            path="scripts/lib/cio_telegram_transport.py",
            now=now,
        )
    ok = (
        not general_token_used_in_cio_transport
        and proof_general_sends == 0
        and live_send_count_this_run >= 0
    )
    return make_gate(
        "G14_cio_telegram_isolation",
        expected="CIO bot/chat only; general bot send count proven 0",
        actual={
            "cio_token_env_set": cio_token_env_set,
            "general_used_in_cio_transport": general_token_used_in_cio_transport,
            "proof_general_sends": proof_general_sends,
            "sends_this_run": live_send_count_this_run,
        },
        status="PASS" if ok else "FAIL",
        reason="General bot unused (measured)." if ok else "CIO isolation not proven or general path used.",
        severity="P0",
        now=now,
    )


def eval_g15_real_canary(
    *,
    canary_evidence: Optional[dict[str, Any]],
    live_sha: str,
    now: Optional[datetime] = None,
) -> dict:
    ev = canary_evidence or {}
    sha_ok = bool(ev.get("release_sha")) and _full_sha(ev.get("release_sha")) == _full_sha(live_sha)
    ok = (
        ev.get("sent") is True
        and ev.get("operator_approved") is True
        and ev.get("cio_chat_confirmed") is True
        and ev.get("duplicate") is False
        and sha_ok
    )
    return make_gate(
        "G15_real_cio_e2e_canary",
        expected="operator-approved exact-release CIO canary sent once and ACKed",
        actual={
            "present": bool(ev),
            "sent": ev.get("sent"),
            "operator_approved": ev.get("operator_approved"),
            "release_sha": _sha12(ev.get("release_sha")),
            "live_sha": _sha12(live_sha),
        },
        status="PASS" if ok else "FAIL",
        reason=(
            "Exact-release CIO canary evidenced."
            if ok
            else "No proven exact-current-release CIO Telegram canary (prepare-only ≠ pass)."
        ),
        severity="P1",
        path=str(ev.get("path") or "missing canary receipt"),
        sha=live_sha,
        now=now,
    )


def eval_g16_zero_duplicate(
    *,
    canary_evidence: Optional[dict[str, Any]],
    now: Optional[datetime] = None,
) -> dict:
    ev = canary_evidence or {}
    attempted = ev.get("repeat_attempted") is True
    ok = ev.get("repeat_unchanged_sends") == 0 and ev.get("sent") is True and attempted
    return make_gate(
        "G16_zero_duplicate_notification",
        expected="unchanged repeat was actually attempted and sent 0 additional messages",
        actual={
            "repeat_unchanged_sends": ev.get("repeat_unchanged_sends"),
            "sent": ev.get("sent"),
            "repeat_attempted": ev.get("repeat_attempted"),
        },
        status="PASS" if ok else "FAIL",
        reason=(
            "Duplicate suppression proven on repeat."
            if ok
            else "Duplicate-delivery proof missing (requires real canary + repeat)."
        ),
        severity="P1",
        now=now,
    )


def eval_g17_authority(
    *,
    surfaces: list[dict[str, Any]],
    now: Optional[datetime] = None,
) -> dict:
    bad = []
    present = {str(s.get("name") or "") for s in (surfaces or [])}
    missing = [n for n in EXPECTED_AUTHORITY_SURFACES if n not in present]
    if not surfaces:
        bad.append("empty_surface_list")
    bad.extend(f"missing:{n}" for n in missing)
    for s in surfaces or []:
        auth = str(s.get("authority") or "")
        if auth and auth != AUTHORITY:
            bad.append(f"{s.get('name')}:{auth}")
        if not auth:
            bad.append(f"{s.get('name')}:missing_authority")
    ok = not bad
    return make_gate(
        "G17_authority_read_only",
        expected="READ_ONLY_ADVISORY on capital_plan, cio_home, report, advisory, telegram_payload",
        actual={"bad": bad, "checked": [s.get("name") for s in (surfaces or [])], "missing": missing},
        status="PASS" if ok else "FAIL",
        reason="Authority boundary intact." if ok else f"Authority missing/wrong: {bad}",
        severity="P0",
        now=now,
    )


def eval_g18_ci_green(
    *,
    cio_hardening_required: bool,
    cio_hardening_green_on_sha: bool,
    sha: str = "",
    now: Optional[datetime] = None,
) -> dict:
    ok = cio_hardening_required and cio_hardening_green_on_sha
    return make_gate(
        "G18_required_ci_green",
        expected="cio-hardening required on main and green on the accepted SHA",
        actual={"required": cio_hardening_required, "green_on_sha": cio_hardening_green_on_sha, "sha": _sha12(sha)},
        status="PASS" if ok else "FAIL",
        reason=(
            "cio-hardening required and green."
            if ok
            else "Cannot accept: cio-hardening not required or not proven green on this SHA."
        ),
        severity="P1",
        now=now,
    )


def eval_g20_strategy_honest(
    *,
    facts: list[dict[str, Any]],
    claims_almanac_integrated: bool,
    claims_research_brain_integrated: bool,
    now: Optional[datetime] = None,
) -> dict:
    """Honesty gate — not an integration pass.

    FAIL if unverified claims are labeled reproduced, or if the run claims
    Almanac/research-brain integration without validated reproductions.
    PASS only means grades are not lying.
    """
    lies = []
    reproduced = 0
    for f in facts or []:
        grade = str(f.get("internal_validation_status") or f.get("evidence_grade") or "")
        layers = f.get("layers") or {}
        if not layers.get("source_claim") or not layers.get("current_application"):
            lies.append(f"{f.get('source_id')}: missing required layers")
        repro = str(layers.get("trade_ai_reproduction") or f.get("reproduction_status") or "")
        if grade in UNVALIDATED_GRADES:
            if "reproduced" in grade:
                lies.append(f"{f.get('source_id')}: unverified marked reproduced")
            if re.search(r"\breproduced\b", repro, re.I) and "not yet" not in repro.lower() and "awaiting" not in repro.lower():
                lies.append(f"{f.get('source_id')}: unverified but reproduction text claims done")
        if grade in ("reproduced", "reproduced_oos", "A", "B") and "not yet" not in repro.lower():
            reproduced += 1
    if claims_almanac_integrated:
        lies.append("run claims STOCK_ALMANAC_INTEGRATED without this gate being an integration proof")
    if claims_research_brain_integrated:
        lies.append("run claims BROADER_RESEARCH_BRAIN integrated")
    # Scaffold with honest D/unverified grades and no integration claim → PASS honesty
    ok = not lies
    return make_gate(
        "G20_strategy_claims_honestly_graded",
        expected="source/reproduction/application layers present; no false reproduced labels; no false integration claim",
        actual={
            "fact_count": len(facts or []),
            "reproduced_count": reproduced,
            "claims_almanac_integrated": claims_almanac_integrated,
            "lies": lies,
        },
        status="PASS" if ok else "FAIL",
        reason=(
            f"Grades honest ({len(facts or [])} facts, {reproduced} reproduced). "
            "This is NOT Almanac integration."
            if ok
            else "Dishonest strategy grading or false integration claim: " + "; ".join(lies[:6])
        ),
        severity="P1",
        path="strategy store / scorecard claims",
        now=now,
    )


def evaluate_live_snapshot(snap: dict[str, Any], *, now: Optional[datetime] = None) -> dict[str, Any]:
    """Evaluate a complete live snapshot. No implicit offline fill."""
    now = now or datetime.now(timezone.utc)
    live = _full_sha(snap.get("live_sha"))
    main = _full_sha(snap.get("main_sha"))
    gates: list[dict[str, Any]] = []
    gates.append(eval_g1_exact_live_sha(
        live_sha=live, main_sha=main, remote_truth=snap.get("remote_sha_truth") or {}, now=now,
    ))
    gates.append(eval_g2_release_manifest_parity(
        manifest=snap.get("manifest") or {}, live_sha=live, main_sha=main, now=now,
    ))
    dups = snap.get("drive_duplicate_count")
    gates.append(eval_g3_drive_manifest_parity(
        git_manifest_hash=str(snap.get("git_manifest_hash") or ""),
        drive_canonical_hash=str(snap.get("drive_canonical_hash") or ""),
        drive_duplicate_count=None if dups is None else int(dups),
        drive_proven=bool(snap.get("drive_proven")),
        drive_canonical_file_id=str(snap.get("drive_canonical_file_id") or ""),
        now=now,
    ))
    ft = dict(snap.get("financial_truth_gate") or {})
    if snap.get("acceptance_mutated_audited_book"):
        ft["acceptance_mutated_audited_book"] = True
    gates.append(eval_g4_financial_book(gate=ft, now=now))
    gates.append(eval_g5_zero_material_conflicts(
        exceptions=snap.get("financial_exceptions") or ft.get("exceptions") or [],
        conflicted_symbols=ft.get("conflicted_symbols") or [],
        exception_count=ft.get("exception_count"),
        overall_quality=str(ft.get("overall_quality") or ""),
        now=now,
    ))
    plan = snap.get("capital_plan") or {}
    decs = plan.get("position_decisions") or []
    gates.append(eval_g6_required_freshness(decisions=decs, now=now))
    gates.append(eval_g7_capital_plan_invariants(plan=plan, now=now))
    gates.append(eval_g8_decision_parity(parity=snap.get("decision_parity") or {}, now=now))
    gates.append(eval_g9_advisory_ui_provenance(
        advisory_payload=snap.get("advisory_payload"),
        frontend_bundle_text=str(snap.get("frontend_bundle_text") or ""),
        cio_hub_source=str(snap.get("cio_hub_source") or ""),
        now=now,
    ))
    gates.extend(eval_g10_g12_report_formats(
        html_path=str(snap.get("report_html_path") or ""),
        pdf_path=str(snap.get("report_pdf_path") or ""),
        docx_path=str(snap.get("report_docx_path") or ""),
        source_sha=str(snap.get("report_source_sha") or ""),
        live_sha=live,
        synthetic=bool(snap.get("report_synthetic")),
        report_instance=snap.get("report_instance") or None,
        now=now,
    ))
    gates.append(eval_g13_visual_qa(
        visual_qa_artifact=str(snap.get("visual_qa_artifact") or ""),
        pages_inspected=int(snap.get("visual_qa_pages") or 0),
        qa_pdf_sha256=str(snap.get("qa_pdf_sha256") or ""),
        report_pdf_sha256=str(snap.get("report_pdf_sha256") or ""),
        pdf_page_count=int(snap.get("pdf_page_count") or 0),
        qa_result=str(snap.get("qa_result") or ""),
        qa_instance_id=str(snap.get("qa_instance_id") or ""),
        report_instance_id=str((snap.get("report_instance") or {}).get("report_instance_id") or ""),
        now=now,
    ))
    gates.append(eval_g14_telegram_isolation(
        cio_token_env_set=bool(snap.get("cio_token_env_set")),
        general_token_used_in_cio_transport=bool(snap.get("general_token_used_in_cio_transport")),
        interdict_on=bool(snap.get("telegram_interdict_on")),
        live_send_count_this_run=int(snap.get("telegram_sends_this_run") or 0),
        proof_general_sends=snap.get("proof_general_sends"),  # None → FAIL
        now=now,
    ))
    canary = snap.get("canary_evidence")
    gates.append(eval_g15_real_canary(canary_evidence=canary, live_sha=live, now=now))
    gates.append(eval_g16_zero_duplicate(canary_evidence=canary, now=now))
    gates.append(eval_g17_authority(surfaces=snap.get("authority_surfaces") or [], now=now))
    gates.append(eval_g18_ci_green(
        cio_hardening_required=bool(snap.get("cio_hardening_required")),
        cio_hardening_green_on_sha=bool(snap.get("cio_hardening_green_on_sha")),
        sha=live,
        now=now,
    ))
    gates.append(eval_g20_strategy_honest(
        facts=snap.get("strategy_facts") or [],
        claims_almanac_integrated=bool(snap.get("claims_almanac_integrated")),
        claims_research_brain_integrated=bool(snap.get("claims_research_brain_integrated")),
        now=now,
    ))
    return finalize_verdict(
        gates,
        now=now,
        live_sha=live,
        main_sha=main,
        extra={"build_capability": snap.get("build_capability") or {"note": "not used for live verdict"}},
    )
