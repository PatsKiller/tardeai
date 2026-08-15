"""Phase 1 — acceptance harness integrity.

These tests prove the auditor cannot award PRODUCTION_ACCEPTANCE=PASS for
detecting a failure, using offline/toy data, or while P0/P1 remain open.
"""
from __future__ import annotations

import ast
import hashlib
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_acceptance_v4 import (  # noqa: E402
    ACCEPTANCE_VERSION,
    HARD_GATE_IDS,
    eval_g0_canonical_acceptance_evaluator,
    eval_g1_exact_live_sha,
    eval_g2_release_manifest_parity,
    eval_g4_financial_book,
    eval_g5_zero_material_conflicts,
    eval_g6_required_freshness,
    eval_g10_g12_report_formats,
    eval_g13_visual_qa,
    eval_g14_telegram_isolation,
    eval_g15_real_canary,
    eval_g20_strategy_honest,
    evaluate_live_snapshot,
    finalize_verdict,
    make_gate,
)

_ARTIFACT_DIR = Path(tempfile.mkdtemp(prefix="cio_acc_v4_"))
HOLDINGS_SHA = "hold" + "b" * 60


def _write_bytes(path: Path, tag: bytes) -> str:
    path.write_bytes(b"%PDF-REPORT\n" + tag + (b"\n" * 120))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report_bundle(dest: Path | None = None) -> dict:
    d = dest or _ARTIFACT_DIR
    d.mkdir(parents=True, exist_ok=True)
    html_p = d / "cio_live_report.html"
    pdf_p = d / "cio_live_report.pdf"
    docx_p = d / "cio_live_report.docx"
    qa_p = d / "VISUAL_QA.json"
    html_sha = _write_bytes(html_p, b"HTML")
    pdf_sha = _write_bytes(pdf_p, b"PDF")
    docx_sha = _write_bytes(docx_p, b"DOCX")
    qa_p.write_text('{"result":"PASS","pages_inspected":8}', encoding="utf-8")
    return {
        "html_path": str(html_p),
        "pdf_path": str(pdf_p),
        "docx_path": str(docx_p),
        "qa_path": str(qa_p),
        "html_sha256": html_sha,
        "pdf_sha256": pdf_sha,
        "docx_sha256": docx_sha,
    }


def _pass_g0_attestation(sha: str) -> dict:
    return {
        "proven": True,
        "acceptance_evaluator_commit_sha": sha,
        "git_branch": "main",
        "worktree_clean": True,
        "untracked_count": 0,
        "evaluator_file_sha256": "e" * 64,
        "runner_file_sha256": "r" * 64,
        "remote_main_sha": sha,
        "main_commit_class": "RUNTIME_CONTENT",
        "attested_runtime_content_sha": sha,
        "evaluator_diff_vs_remote_main": [],
        "evaluator_files_match_remote_main": True,
        "evaluator_files_match_attested_content": True,
        "evaluator_files_dirty": False,
        "untracked_evaluator_count": 0,
    }


def _clean_snap(**overrides):
    """A snapshot that *could* pass if all fields were green — tests flip one."""
    sha = "a" * 40
    bundle = _report_bundle()
    base = {
        "live_sha": sha,
        "main_sha": sha,
        "manifest": {
            "status": "production",
            "canonical_source_sha": sha,
            "backend_release_sha": sha,
            "origin_main_sha": sha,
        },
        "git_manifest_hash": "abc",
        "remote_sha_truth": {
            "proven": True,
            "fetch_ok": True,
            "ls_remote_ok": True,
            "local_matches_remote": True,
            "remote_main_sha": sha,
            "local_origin_main_sha": sha,
            "main_commit_class": "RUNTIME_CONTENT",
            "attested_runtime_content_sha": sha,
        },
        "drive_proven": True,
        "drive_canonical_hash": "abc",
        "drive_duplicate_count": 1,
        "drive_canonical_file_id": "file-abc",
        "financial_truth_gate": {
            "overall_quality": "VERIFIED_CURRENT",
            "ok": True,
            "exception_count": 0,
            "conflicted_symbols": [],
            "book_invariants": {
                "cash_plus_mv_eq_reported_total": True,
                "sum_accounts_eq_derived": True,
            },
        },
        "financial_exceptions": [],
        "capital_plan": {
            "authority": "READ_ONLY_ADVISORY",
            "cash_total_usd": 100.0,
            "portfolio_value_usd": 1000.0,
            "cash_earmarked_redeploy_usd": 10.0,
            "cash_reserved_usd": 20.0,
            "cash_investable_usd": 80.0,
            "deployable_usd": 80.0,
            "net_recommended_deploy_usd": 20.0,
            "post_plan_cash_usd": 80.0,
            "capital_sources": {
                "total_prospective_raise_usd": 0,
                "total_raise_usd": 0,
                "trims_usd": 0,
                "exits_usd": 0,
                "maturities_usd": 0,
                "includes_current_cash": False,
                "includes_earmarked_existing_cash": False,
                "realized_historical_proceeds_usd": 0,
            },
            "account_capital_ledger": {
                "accounts": [{
                    "account": "a",
                    "settled_cash_usd": 100.0,
                    "positions_mv_usd": 900.0,
                    "post_plan_cash_usd": 80.0,
                    "negative_cash": False,
                }],
                "portfolio_aggregate": {
                    "settled_cash_usd": 100.0,
                    "reserve_usd": 20.0,
                    "earmarked_usd": 10.0,
                    "prospective_raise_usd": 0.0,
                    "recommended_deploy_usd": 20.0,
                    "post_plan_cash_usd": 80.0,
                    "portfolio_value_usd": 1000.0,
                },
                "invariants": {
                    "earmark_le_settled_cash": True,
                    "deploy_le_free_plus_prospective": True,
                },
            },
            "position_decisions": [{
                "decision_id": "dec-aaa",
                "symbol": "AAA",
                "account": "any",
                "action": "HOLD",
                "action_label": "REVIEW",
                "act_now": False,
                "decision_input_digest": "in1",
                "decision_evidence_digest": "ev1",
                "generated_at": "2026-08-14T00:00:00+00:00",
                "freshness": {"board": [{"name": "decision", "detail": "ok"}]},
            }],
        },
        "decision_parity": {
            "ok": True,
            "surfaces_complete": True,
            "field_mismatches": [],
            "missing_required": [],
            "surfaces": {
                "capital_plan": [{
                    "decision_id": "dec-aaa", "symbol": "AAA", "account": "any",
                    "action": "HOLD", "decision_input_digest": "in1",
                    "decision_evidence_digest": "ev1",
                }],
                "cio_home": [{
                    "decision_id": "dec-aaa", "symbol": "AAA", "account": "any",
                    "action": "HOLD", "decision_input_digest": "in1",
                    "decision_evidence_digest": "ev1",
                }],
                "report": [{
                    "decision_id": "dec-aaa", "symbol": "AAA", "account": "any",
                    "action": "HOLD", "decision_input_digest": "in1",
                    "decision_evidence_digest": "ev1",
                }],
                "telegram": [{
                    "decision_id": "dec-aaa", "symbol": "AAA", "account": "any",
                    "action": "HOLD", "decision_input_digest": "in1",
                    "decision_evidence_digest": "ev1",
                }],
            },
        },
        "advisory_payload": {"advisory_provenance": {"symbol": "AAA"}},
        "frontend_bundle_text": "advisory_provenance Current mark Material Today",
        "cio_hub_source": "Investment decisions / Material Today",
        "evaluator_attestation": _pass_g0_attestation(sha),
        "current_holdings_sha256": HOLDINGS_SHA,
        "report_html_path": bundle["html_path"],
        "report_pdf_path": bundle["pdf_path"],
        "report_docx_path": bundle["docx_path"],
        "report_source_sha": sha,
        "report_synthetic": False,
        "visual_qa_artifact": bundle["qa_path"],
        "visual_qa_pages": 8,
        "qa_page_image_hashes": [f"p{i:02d}" + "c" * 60 for i in range(8)],
        "qa_pdf_sha256": bundle["pdf_sha256"],
        "report_pdf_sha256": bundle["pdf_sha256"],
        "pdf_page_count": 8,
        "qa_result": "PASS",
        "qa_instance_id": "inst-1",
        "report_instance": {
            "report_instance_id": "inst-1",
            "html_sha256": bundle["html_sha256"],
            "pdf_sha256": bundle["pdf_sha256"],
            "docx_sha256": bundle["docx_sha256"],
            "portfolio_snapshot_hash": HOLDINGS_SHA,
            "expected_portfolio_snapshot_hash": HOLDINGS_SHA,
        },
        "cio_token_env_set": True,
        "general_token_used_in_cio_transport": False,
        "telegram_interdict_on": False,
        "telegram_sends_this_run": 1,
        "proof_general_sends": 0,
        "canary_evidence": {
            "sent": True,
            "operator_approved": True,
            "cio_chat_confirmed": True,
            "duplicate": False,
            "release_sha": sha,
            "release_content_sha": sha,
            "decision_id": "dec-aaa",
            "decision_input_digest": "in1",
            "decision_evidence_digest": "ev1",
            "repeat_unchanged_sends": 0,
            "repeat_attempted": True,
        },
        "authority_surfaces": [
            {"name": "capital_plan", "authority": "READ_ONLY_ADVISORY"},
            {"name": "cio_home", "authority": "READ_ONLY_ADVISORY"},
            {"name": "report", "authority": "READ_ONLY_ADVISORY"},
            {"name": "advisory", "authority": "READ_ONLY_ADVISORY"},
            {"name": "telegram_payload", "authority": "READ_ONLY_ADVISORY"},
        ],
        "cio_hardening_required": True,
        "cio_hardening_green_on_sha": True,
        "strategy_facts": [{
            "source_id": "sta_september_seasonality_summary",
            "internal_validation_status": "unverified_source_claim",
            "layers": {
                "source_claim": "September weak (source)",
                "trade_ai_reproduction": "Not yet independently reproduced in Trade AI from raw returns.",
                "current_application": "Context only",
            },
        }],
        "claims_almanac_integrated": False,
        "claims_research_brain_integrated": False,
    }
    base.update(overrides)
    return base


def test_version_and_hard_gates():
    assert ACCEPTANCE_VERSION.startswith("cio_acceptance_v4")
    assert HARD_GATE_IDS[0] == "G0_CANONICAL_ACCEPTANCE_EVALUATOR"
    assert "G1_exact_live_sha" in HARD_GATE_IDS
    assert len(HARD_GATE_IDS) == 21


def test_conflicted_book_is_fail_not_pass():
    g = eval_g4_financial_book(gate={
        "overall_quality": "CONFLICTED",
        "ok": False,
        "exception_count": 39,
        "book_invariants": {
            "cash_plus_mv_eq_reported_total": False,
            "sum_accounts_eq_derived": True,
        },
    })
    assert g["status"] == "FAIL"
    assert g["severity"] == "P0"
    assert "not a pass" in g["reason"].lower() or "CONFLICTED" in g["reason"]


def test_detector_ran_is_not_enough():
    """Gate exists and ran, but book still dirty → FAIL."""
    g = eval_g4_financial_book(gate={
        "overall_quality": "CONFLICTED",
        "ok": False,
        "exception_count": 1,
        "book_invariants": {
            "cash_plus_mv_eq_reported_total": True,
            "sum_accounts_eq_derived": True,
        },
    })
    assert g["status"] == "FAIL"


def test_material_conflicts_fail_g5():
    g = eval_g5_zero_material_conflicts(
        exceptions=[{"type": "dual_price_conflict", "symbol": "DXCM"}],
        conflicted_symbols=["DXCM"],
    )
    assert g["status"] == "FAIL"
    assert "DXCM" in g["reason"]


def test_opaque_exception_count_cannot_pass_g5():
    """exception_count>0 with no row list is FAIL, not a clean book."""
    g = eval_g5_zero_material_conflicts(
        exceptions=[],
        conflicted_symbols=[],
        exception_count=26,
        overall_quality="STALE",
    )
    assert g["status"] == "FAIL"


def test_evaluated_now_loophole_fails_freshness():
    g = eval_g6_required_freshness(decisions=[{
        "symbol": "SCHD",
        "action_label": "REVIEW",
        "freshness": {"board": [{"name": "decision", "detail": "evaluated_now"}]},
    }])
    assert g["status"] == "FAIL"
    assert "evaluated_now" in g["reason"]


def test_zero_age_without_timestamp_fails_freshness():
    g = eval_g6_required_freshness(decisions=[{
        "symbol": "SCHD",
        "action_label": "DATA_CONFLICT",
        "freshness": {"board": [{"name": "decision", "detail": "ok", "age_seconds": 0.0}]},
    }])
    assert g["status"] == "FAIL"


def test_act_now_without_timestamp_fails():
    g = eval_g6_required_freshness(decisions=[{
        "symbol": "AAA",
        "action_label": "ACT_NOW",
        "act_now": True,
    }])
    assert g["status"] == "FAIL"


def test_synthetic_report_cannot_pass_pdf():
    gates = eval_g10_g12_report_formats(
        html_path="/tmp/x.html",
        pdf_path="/tmp/x.pdf",
        docx_path="/tmp/x.docx",
        source_sha="a" * 40,
        live_sha="a" * 40,
        synthetic=True,
    )
    assert all(g["status"] == "FAIL" for g in gates)
    assert any("Synthetic" in g["reason"] or "Toy" in g["reason"] for g in gates)


def test_html_only_does_not_pass_pdf_or_docx():
    d = _ARTIFACT_DIR / "html_only"
    d.mkdir(parents=True, exist_ok=True)
    html_p = d / "only.html"
    html_sha = _write_bytes(html_p, b"HTML-ONLY")
    gates = eval_g10_g12_report_formats(
        html_path=str(html_p),
        pdf_path="",
        docx_path="",
        source_sha="a" * 40,
        live_sha="a" * 40,
        synthetic=False,
        current_holdings_sha256=HOLDINGS_SHA,
        report_instance={
            "report_instance_id": "inst-html",
            "html_sha256": html_sha,
            "pdf_sha256": "",
            "docx_sha256": "",
            "portfolio_snapshot_hash": HOLDINGS_SHA,
        },
    )
    by = {g["gate"]: g for g in gates}
    assert by["G10_report_live_html"]["status"] == "PASS"
    assert by["G11_report_live_pdf"]["status"] == "FAIL"
    assert by["G12_report_live_docx"]["status"] == "FAIL"


def test_nonempty_path_or_hash_field_is_not_enough():
    """G10–G12 must not pass on a path string or hash-field-present."""
    gates = eval_g10_g12_report_formats(
        html_path="/tmp/does-not-exist-cio.html",
        pdf_path="/tmp/does-not-exist-cio.pdf",
        docx_path="/tmp/does-not-exist-cio.docx",
        source_sha="a" * 40,
        live_sha="a" * 40,
        synthetic=False,
        current_holdings_sha256=HOLDINGS_SHA,
        report_instance={
            "report_instance_id": "inst-1",
            "html_sha256": "h" * 64,
            "pdf_sha256": "p" * 64,
            "docx_sha256": "d" * 64,
            "portfolio_snapshot_hash": HOLDINGS_SHA,
        },
    )
    assert all(g["status"] == "FAIL" for g in gates)
    assert any("missing" in g["reason"] for g in gates)


def test_unlike_digest_family_does_not_fail_report_gates(tmp_path):
    """Report-builder digest vs missing/empty live digest is not comparable."""
    html = tmp_path / "r.html"
    pdf = tmp_path / "r.pdf"
    docx = tmp_path / "r.docx"
    h = _write_bytes(html, b"H")
    p = _write_bytes(pdf, b"P")
    d = _write_bytes(docx, b"D")
    gates = eval_g10_g12_report_formats(
        html_path=str(html), pdf_path=str(pdf), docx_path=str(docx),
        source_sha="a" * 40, live_sha="a" * 40,
        current_holdings_sha256=HOLDINGS_SHA,
        live_capital_plan_digest="",
        live_decision_digest="",
        report_instance={
            "report_instance_id": "r1",
            "html_sha256": h,
            "pdf_sha256": p,
            "docx_sha256": d,
            "portfolio_snapshot_hash": HOLDINGS_SHA,
            "capital_plan_digest": "report-family-" + "e" * 48,
        },
    )
    assert all(g["status"] == "PASS" for g in gates)


def test_same_family_digest_mismatch_fails_report_gates(tmp_path):
    html = tmp_path / "r.html"
    pdf = tmp_path / "r.pdf"
    docx = tmp_path / "r.docx"
    h = _write_bytes(html, b"H")
    p = _write_bytes(pdf, b"P")
    d = _write_bytes(docx, b"D")
    gates = eval_g10_g12_report_formats(
        html_path=str(html), pdf_path=str(pdf), docx_path=str(docx),
        source_sha="a" * 40, live_sha="a" * 40,
        current_holdings_sha256=HOLDINGS_SHA,
        live_capital_plan_digest="api-family-" + "a" * 52,
        report_instance={
            "report_instance_id": "r1",
            "html_sha256": h,
            "pdf_sha256": p,
            "docx_sha256": d,
            "portfolio_snapshot_hash": HOLDINGS_SHA,
            "capital_plan_digest": "report-family-" + "e" * 48,
        },
    )
    assert all(g["status"] == "FAIL" for g in gates)
    assert any("capital_plan_digest mismatch" in g["reason"] for g in gates)


def test_evaluate_snapshot_does_not_use_api_plan_digest(tmp_path):
    """Collector-empty live digest must not fall back to API plan.digest."""
    snap = _clean_snap()
    snap["live_capital_plan_digest"] = ""
    snap["live_decision_digest"] = ""
    snap["capital_plan"] = dict(snap["capital_plan"] or {})
    snap["capital_plan"]["digest"] = "api-family-" + "a" * 52
    snap["report_instance"] = dict(snap["report_instance"])
    snap["report_instance"]["capital_plan_digest"] = "report-family-" + "e" * 48
    v = evaluate_live_snapshot(snap)
    by = {g["gate"]: g for g in v["gates"]}
    assert by["G10_report_live_html"]["status"] == "PASS", by["G10_report_live_html"]
    assert by["G11_report_live_pdf"]["status"] == "PASS"
    assert by["G12_report_live_docx"]["status"] == "PASS"


def test_tiny_or_hash_mismatch_report_bytes_fail(tmp_path):
    tiny = tmp_path / "tiny.html"
    tiny.write_bytes(b"<html>nope</html>")
    big = tmp_path / "big.html"
    payload = b"<html>" + (b"x" * 200) + b"</html>"
    big.write_bytes(payload)
    wrong = eval_g10_g12_report_formats(
        html_path=str(tiny),
        pdf_path="",
        docx_path="",
        source_sha="a" * 40,
        live_sha="a" * 40,
        current_holdings_sha256=HOLDINGS_SHA,
        report_instance={
            "report_instance_id": "i",
            "html_sha256": "a" * 64,
            "portfolio_snapshot_hash": HOLDINGS_SHA,
        },
    )
    assert wrong[0]["status"] == "FAIL"
    mismatch = eval_g10_g12_report_formats(
        html_path=str(big),
        pdf_path="",
        docx_path="",
        source_sha="a" * 40,
        live_sha="a" * 40,
        current_holdings_sha256=HOLDINGS_SHA,
        report_instance={
            "report_instance_id": "i",
            "html_sha256": "f" * 64,
            "portfolio_snapshot_hash": HOLDINGS_SHA,
        },
    )
    assert mismatch[0]["status"] == "FAIL"
    assert "sha256" in mismatch[0]["reason"]


def test_g13_requires_actual_pdf_bytes_and_all_pages(tmp_path):
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF" + (b"p" * 200))
    actual = hashlib.sha256(pdf.read_bytes()).hexdigest()
    qa = tmp_path / "VISUAL_QA.json"
    qa.write_text('{"result":"PASS"}', encoding="utf-8")
    fail_hash = eval_g13_visual_qa(
        visual_qa_artifact=str(qa),
        pages_inspected=8,
        qa_pdf_sha256="deadbeef" * 8,
        report_pdf_sha256=actual,
        pdf_page_count=8,
        qa_result="PASS",
        qa_instance_id="inst-1",
        report_instance_id="inst-1",
        pdf_path=str(pdf),
    )
    assert fail_hash["status"] == "FAIL"
    fail_pages = eval_g13_visual_qa(
        visual_qa_artifact=str(qa),
        pages_inspected=3,
        qa_pdf_sha256=actual,
        report_pdf_sha256=actual,
        pdf_page_count=8,
        qa_result="PASS",
        qa_instance_id="inst-1",
        report_instance_id="inst-1",
        pdf_path=str(pdf),
    )
    assert fail_pages["status"] == "FAIL"
    ok = eval_g13_visual_qa(
        visual_qa_artifact=str(qa),
        pages_inspected=8,
        qa_pdf_sha256=actual,
        report_pdf_sha256=actual,
        pdf_page_count=8,
        qa_result="PASS",
        qa_instance_id="inst-1",
        report_instance_id="inst-1",
        pdf_path=str(pdf),
        page_image_hashes=[f"p{i}" for i in range(8)],
    )
    assert ok["status"] == "PASS"


def test_telegram_unproven_general_not_used_fails():
    g = eval_g14_telegram_isolation(
        cio_token_env_set=True,
        general_token_used_in_cio_transport=False,
        interdict_on=True,
        live_send_count_this_run=0,
        proof_general_sends=None,
    )
    assert g["status"] == "FAIL"
    assert "not proven" in g["reason"]


def test_prepare_only_canary_fails_g15():
    g = eval_g15_real_canary(canary_evidence=None, live_sha="a" * 40)
    assert g["status"] == "FAIL"


def test_unverified_facts_do_not_claim_integration():
    g = eval_g20_strategy_honest(
        facts=[{
            "source_id": "sta_september_seasonality_summary",
            "internal_validation_status": "unverified_source_claim",
            "layers": {
                "source_claim": "x",
                "trade_ai_reproduction": "Not yet independently reproduced.",
                "current_application": "context",
            },
        }],
        claims_almanac_integrated=False,
        claims_research_brain_integrated=False,
    )
    assert g["status"] == "PASS"  # honest scaffold
    # Claiming integration is a lie
    g2 = eval_g20_strategy_honest(
        facts=[{
            "source_id": "sta_september_seasonality_summary",
            "internal_validation_status": "unverified_source_claim",
            "layers": {
                "source_claim": "x",
                "trade_ai_reproduction": "Not yet independently reproduced.",
                "current_application": "context",
            },
        }],
        claims_almanac_integrated=True,
        claims_research_brain_integrated=False,
    )
    assert g2["status"] == "FAIL"


def test_live_ne_main_fails_g1():
    g = eval_g1_exact_live_sha(live_sha="f" * 40, main_sha="0" * 40)
    assert g["status"] == "FAIL"


def test_ancestor_or_rc_manifest_fails_g2():
    g = eval_g2_release_manifest_parity(
        manifest={
            "status": "release_candidate",
            "canonical_source_sha": "a" * 40,
            "backend_release_sha": "b" * 40,
            "origin_main_sha": "c" * 40,
        },
        live_sha="d" * 40,
        main_sha="e" * 40,
    )
    assert g["status"] == "FAIL"


def test_p0_open_forces_acceptance_fail():
    gates = [
        make_gate("G1_exact_live_sha", expected="eq", actual="no", status="FAIL",
                  reason="lag", severity="P0"),
    ]
    v = finalize_verdict(gates, live_sha="x", main_sha="y")
    assert v["PRODUCTION_ACCEPTANCE"] == "FAIL"
    assert v["pass_threshold"] is False
    assert v["OPEN_P0"] >= 1
    assert v["p0_p1_open"]


def test_all_green_snapshot_can_pass():
    v = evaluate_live_snapshot(_clean_snap())
    assert v["PRODUCTION_ACCEPTANCE"] == "PASS"
    assert v["CORE_CIO_PRODUCTION_ACCEPTANCE"] == "PASS"
    assert v["RESEARCH_GOVERNANCE_ACCEPTANCE"] == "NOT_YET_INTEGRATED"
    assert v["FULL_INVESTMENT_OFFICE_ACCEPTANCE"] == "FAIL"
    assert v["OPEN_P0"] == 0
    assert v["OPEN_P1"] == 0
    assert v["categories"]["STOCK_ALMANAC_INTEGRATION"] == "FAIL"  # never auto-pass
    assert v["categories"]["BROADER_RESEARCH_BRAIN"] == "FAIL"


def test_conflicted_snapshot_cannot_pass_even_if_other_gates_green():
    snap = _clean_snap()
    snap["financial_truth_gate"]["overall_quality"] = "CONFLICTED"
    snap["financial_truth_gate"]["ok"] = False
    snap["financial_exceptions"] = [{"type": "dual_price_conflict", "symbol": "DXCM"}]
    snap["financial_truth_gate"]["conflicted_symbols"] = ["DXCM"]
    v = evaluate_live_snapshot(snap)
    assert v["PRODUCTION_ACCEPTANCE"] == "FAIL"
    assert v["categories"]["FINANCIAL_TRUTH"] == "FAIL"
    assert v["OPEN_P0"] >= 1


def test_offline_fill_is_not_in_evaluator_signature():
    """evaluate_live_snapshot has no offline/union parameter."""
    import inspect
    sig = inspect.signature(evaluate_live_snapshot)
    assert "offline" not in sig.parameters


def test_source_forbids_or_true_scoring():
    """Static: acceptance runner/lib must not contain `or True` scoring hacks."""
    files = [
        ROOT / "scripts/run_cio_acceptance.py",
        ROOT / "scripts/lib/cio_acceptance_v4.py",
    ]
    for p in files:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                for v in node.values:
                    if isinstance(v, ast.Constant) and v.value is True:
                        hits.append(node.lineno)
        assert hits == [], f"{p} contains `or True` at lines {hits}"


def test_not_run_is_fail_closed():
    g = make_gate("G13_report_visual_qa", expected="qa", actual=None,
                  status="NOT_RUN", reason="no artifact", severity="P1")
    assert g["status"] == "FAIL"
    assert "NOT_RUN" in g["reason"]


def test_missing_g0_attestation_fails_core():
    snap = _clean_snap()
    snap["evaluator_attestation"] = {}
    v = evaluate_live_snapshot(snap)
    by = {g["gate"]: g for g in v["gates"]}
    assert by["G0_CANONICAL_ACCEPTANCE_EVALUATOR"]["status"] == "FAIL"
    assert v["CORE_CIO_PRODUCTION_ACCEPTANCE"] == "FAIL"
    assert v["PRODUCTION_ACCEPTANCE"] == "FAIL"


def test_g2_pin_allows_live_equal_attested_content(monkeypatch):
    """Already-applied parent-pin: live may equal canonical content SHA."""
    monkeypatch.setattr(
        "scripts.cio_release_manifest.pin_only_parent",
        lambda head, canon: {"ok": True, "reason": "pin_only", "parent": canon},
    )
    content = "c" * 40
    pin = "p" * 40
    g = eval_g2_release_manifest_parity(
        manifest={
            "status": "production",
            "canonical_source_sha": content,
            "backend_release_sha": content,
            "origin_main_sha": pin,
        },
        live_sha=content,
        main_sha=pin,
    )
    assert g["status"] == "PASS"


def test_g0_pass_attestation_green():
    g = eval_g0_canonical_acceptance_evaluator(attestation=_pass_g0_attestation("a" * 40))
    assert g["status"] == "PASS"
