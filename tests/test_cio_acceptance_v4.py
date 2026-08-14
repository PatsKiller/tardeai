"""Phase 1 — acceptance harness integrity.

These tests prove the auditor cannot award PRODUCTION_ACCEPTANCE=PASS for
detecting a failure, using offline/toy data, or while P0/P1 remain open.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_acceptance_v4 import (  # noqa: E402
    ACCEPTANCE_VERSION,
    HARD_GATE_IDS,
    eval_g1_exact_live_sha,
    eval_g2_release_manifest_parity,
    eval_g4_financial_book,
    eval_g5_zero_material_conflicts,
    eval_g6_required_freshness,
    eval_g10_g12_report_formats,
    eval_g14_telegram_isolation,
    eval_g15_real_canary,
    eval_g20_strategy_honest,
    evaluate_live_snapshot,
    finalize_verdict,
    make_gate,
)


def _clean_snap(**overrides):
    """A snapshot that *could* pass if all fields were green — tests flip one."""
    sha = "a" * 40
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
            "cash_earmarked_redeploy_usd": 10.0,
            "cash_investable_usd": 50.0,
            "net_recommended_deploy_usd": 20.0,
            "capital_sources": {"total_prospective_raise_usd": 0},
            "account_capital_ledger": {
                "accounts": [{"account": "a"}],
                "portfolio_aggregate": {},
                "invariants": {
                    "earmark_le_settled_cash": True,
                    "deploy_le_free_plus_prospective": True,
                },
            },
            "position_decisions": [{
                "symbol": "AAA",
                "action_label": "REVIEW",
                "act_now": False,
                "generated_at": "2026-08-14T00:00:00+00:00",
                "freshness": {"board": [{"name": "decision", "detail": "ok"}]},
            }],
        },
        "decision_parity": {"ok": True, "field_mismatches": [], "missing_required": []},
        "advisory_payload": {"advisory_provenance": {"symbol": "AAA"}},
        "frontend_bundle_text": "advisory_provenance Current mark Material Today",
        "cio_hub_source": "Investment decisions / Material Today",
        "report_html_path": "/tmp/live.html",
        "report_pdf_path": "/tmp/live.pdf",
        "report_docx_path": "/tmp/live.docx",
        "report_source_sha": sha,
        "report_synthetic": False,
        "visual_qa_artifact": "/tmp/qa",
        "visual_qa_pages": 8,
        "qa_pdf_sha256": "pdf" + "a" * 60,
        "report_pdf_sha256": "pdf" + "a" * 60,
        "pdf_page_count": 8,
        "qa_result": "PASS",
        "qa_instance_id": "inst-1",
        "report_instance": {
            "report_instance_id": "inst-1",
            "html_sha256": "h" * 64,
            "pdf_sha256": "pdf" + "a" * 60,
            "docx_sha256": "d" * 64,
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


def test_version_and_twenty_gates():
    assert ACCEPTANCE_VERSION.startswith("cio_acceptance_v4")
    assert len(HARD_GATE_IDS) == 20


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
    gates = eval_g10_g12_report_formats(
        html_path="/tmp/x.html",
        pdf_path="",
        docx_path="",
        source_sha="a" * 40,
        live_sha="a" * 40,
        synthetic=False,
    )
    by = {g["gate"]: g for g in gates}
    assert by["G10_report_live_html"]["status"] == "PASS"
    assert by["G11_report_live_pdf"]["status"] == "FAIL"
    assert by["G12_report_live_docx"]["status"] == "FAIL"


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
