"""CIO final-truth adversarial suite (isolated branch).

These tests lock the institutional invariants: the auditor cannot mint the
consistency it certifies. Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_acceptance_purity import compare_audited, snapshot_audited_files
from scripts.lib.cio_acceptance_v4 import (
    eval_g0_canonical_acceptance_evaluator,
    eval_g1_exact_live_sha,
    eval_g3_drive_manifest_parity,
    eval_g5_zero_material_conflicts,
    eval_g7_capital_plan_invariants,
    eval_g10_g12_report_formats,
    eval_g13_visual_qa,
    eval_g16_zero_duplicate,
    eval_g17_authority,
    evaluate_live_snapshot,
)
from scripts.lib.cio_remote_sha_truth import (
    CLASS_ATTESTATION,
    classify_main,
    live_matches_required_content,
)
from scripts.lib.cio_source_residual import (
    EXPECTED_SOURCE_TIMESTAMP_DIFFERENCE,
    classify_valuation_residual,
)
from scripts.portfolio_repricer import _apply_to_holdings, _recalc_totals
sys.path.insert(0, str(ROOT / "tests"))
from test_cio_acceptance_v4 import HOLDINGS_SHA, _clean_snap, _write_bytes  # noqa: E402


def test_01_stale_local_origin_fails_g1():
    g = eval_g1_exact_live_sha(
        live_sha="a" * 40,
        main_sha="a" * 40,
        remote_truth={
            "proven": True,
            "local_matches_remote": False,
            "remote_main_sha": "b" * 40,
            "local_origin_main_sha": "a" * 40,
            "main_commit_class": "RUNTIME_CONTENT",
            "attested_runtime_content_sha": "b" * 40,
        },
    )
    assert g["status"] == "FAIL"
    assert "Stale local" in g["reason"]


def test_02_ls_remote_unproven_fails_g1():
    g = eval_g1_exact_live_sha(live_sha="a" * 40, main_sha="a" * 40, remote_truth={})
    assert g["status"] == "FAIL"
    assert "not freshly resolved" in g["reason"]


def test_03_attestation_only_requires_content_sha():
    truth = {
        "proven": True,
        "local_matches_remote": True,
        "remote_main_sha": "e" * 40,
        "attested_runtime_content_sha": "9" * 40,
        "main_commit_class": CLASS_ATTESTATION,
    }
    ok, why = live_matches_required_content(live_sha="e" * 40, truth=truth)
    assert ok is False
    assert "attestation" in why
    ok2, _ = live_matches_required_content(live_sha="9" * 40, truth=truth)
    assert ok2 is True


def test_05_acceptance_mutation_fails_g4():
    snap = _clean_snap()
    snap["acceptance_mutated_audited_book"] = True
    v = evaluate_live_snapshot(snap)
    assert v["PRODUCTION_ACCEPTANCE"] == "FAIL"
    assert any(g["gate"] == "G4_financial_book_reconciliation" and g["status"] == "FAIL" for g in v["gates"])


def test_07_08_external_mark_does_not_overwrite_broker_mv():
    holdings = [{
        "symbol": "QCOM",
        "account": "ira",
        "shares": 55.0,
        "broker": "schwab",
        "market_value": 9116.25,
        "price": 165.75,
        "mv_basis": "broker",
    }]
    live = {"QCOM": {"price": 165.79, "prev_close": 165.0, "change_pct": 0.1, "source": "finviz_elite"}}
    _apply_to_holdings(holdings, live, {})
    row = holdings[0]
    assert row["broker_market_value"] == 9116.25
    assert row["canonical_mark"] == 165.79
    assert row["analytical_market_value"] == round(55 * 165.79, 2)
    assert row["market_value"] == 9116.25
    residual = classify_valuation_residual(row)
    assert residual["residual_status"] == EXPECTED_SOURCE_TIMESTAMP_DIFFERENCE
    assert residual["material"] is False


def test_09_yahoo_fallback_not_labeled_finviz():
    holdings = [{
        "symbol": "AMANX",
        "account": "ira",
        "shares": 10.0,
        "broker": "schwab",
        "market_value": 800.0,
        "mv_basis": "broker",
    }]
    live = {"AMANX": {"price": 81.5, "prev_close": 81.5, "change_pct": 0, "source": "yahoo_cache_fallback"}}
    _apply_to_holdings(holdings, live, {})
    assert holdings[0]["price_source"] == "yahoo_cache_fallback"
    assert holdings[0]["canonical_mark_source"] == "yahoo_cache_fallback"


def test_10_proxy_cannot_alter_valuation():
    holdings = [{
        "symbol": "JPM-LGCG",
        "account": "fidelity_401k",
        "broker": "fidelity",
        "shares": 3.0,
        "market_value": 1000.0,
        "mv_basis": "broker",
    }]
    _apply_to_holdings(holdings, {}, {
        "JPM-LGCG": {"price": 50.0, "proxy": True, "not_for_valuation": True, "source": "proxy_public_ticker"},
    })
    assert holdings[0]["market_value"] == 1000.0
    assert holdings[0].get("not_for_valuation") is True
    assert "analytical_market_value" not in holdings[0] or holdings[0].get("analytical_market_value") in (None,)


def test_11_12_residual_not_injected_into_cash_or_fund():
    cash = {"symbol": "CASH", "is_cash": True, "account": "fidelity_ira", "market_value": 100.0, "shares": 100.0}
    fund = {"symbol": "FID-CONTRA-F", "account": "fidelity_401k", "market_value": 500.0, "shares": 10.0}
    port = {
        "holdings": [cash, fund],
        "account_summaries": {
            "fidelity_ira": {"source": "fidelity", "reported_total_value": 147.0},
            "fidelity_401k": {"source": "fidelity", "reported_total_value": 547.0},
        },
    }
    _recalc_totals(port)
    assert cash["market_value"] == 100.0
    assert fund["market_value"] == 500.0
    assert port["account_summaries"]["fidelity_ira"]["reconciliation_residual_usd"] == 47.0
    assert port["account_summaries"]["fidelity_401k"]["reconciliation_residual_usd"] == 47.0


def test_16_missing_g7_invariant_fails():
    g = eval_g7_capital_plan_invariants(plan={
        "authority": "READ_ONLY_ADVISORY",
        "cash_total_usd": 100,
        "cash_earmarked_redeploy_usd": 10,
        "cash_investable_usd": 50,
        "net_recommended_deploy_usd": 0,
        "capital_sources": {"total_prospective_raise_usd": 0},
        "account_capital_ledger": {"accounts": [{}], "invariants": {}},
    })
    assert g["status"] == "FAIL"


def test_19_20_21_report_instance_binding():
    gates = eval_g10_g12_report_formats(
        html_path="/tmp/a.html", pdf_path="/tmp/stale.pdf", docx_path="/tmp/a.docx",
        source_sha="a" * 40, live_sha="a" * 40, synthetic=False,
        report_instance={
            "report_instance_id": "r1",
            "html_sha256": "h",
            "pdf_sha256": "new",
            "docx_sha256": "d",
            "portfolio_snapshot_hash": "snap1",
            "expected_portfolio_snapshot_hash": "snap2",
        },
    )
    assert all(g["status"] == "FAIL" for g in gates)  # snapshot mismatch
    qa = eval_g13_visual_qa(
        visual_qa_artifact="/tmp/qa",
        pages_inspected=10,
        qa_pdf_sha256="old",
        report_pdf_sha256="new",
        pdf_page_count=27,
        qa_result="PASS",
        qa_instance_id="r1",
        report_instance_id="r1",
    )
    assert qa["status"] == "FAIL"
    qa2 = eval_g13_visual_qa(
        visual_qa_artifact="/tmp/qa",
        pages_inspected=10,
        qa_pdf_sha256="new",
        report_pdf_sha256="new",
        pdf_page_count=27,
        qa_result="PASS",
        qa_instance_id="r1",
        report_instance_id="r1",
    )
    assert qa2["status"] == "FAIL"  # not every page


def test_22_unknown_drive_dups_cannot_be_zero():
    g = eval_g3_drive_manifest_parity(
        git_manifest_hash="abc",
        drive_canonical_hash="abc",
        drive_duplicate_count=None,
        drive_proven=True,
        drive_canonical_file_id="",
    )
    assert g["status"] == "FAIL"


def test_23_empty_authority_surfaces_fail():
    g = eval_g17_authority(surfaces=[])
    assert g["status"] == "FAIL"


def test_24_canary_without_repeat_attempt_fails_g16():
    g = eval_g16_zero_duplicate(canary_evidence={
        "sent": True, "repeat_unchanged_sends": 0,
    })
    assert g["status"] == "FAIL"


def test_26_research_unintegrated_means_full_office_not_pass():
    v = evaluate_live_snapshot(_clean_snap())
    assert v["CORE_CIO_PRODUCTION_ACCEPTANCE"] == "PASS"
    assert v["RESEARCH_GOVERNANCE_ACCEPTANCE"] == "NOT_YET_INTEGRATED"
    assert v["FULL_INVESTMENT_OFFICE_ACCEPTANCE"] != "PASS"
    assert v["PRODUCTION_ACCEPTANCE"] == v["CORE_CIO_PRODUCTION_ACCEPTANCE"]
    assert v["PRODUCTION_ACCEPTANCE_ALIAS_OF"] == "CORE_CIO_PRODUCTION_ACCEPTANCE"


def test_g0_unmerged_evaluator_cannot_pass_core():
    snap = _clean_snap()
    att = dict(snap["evaluator_attestation"])
    att["acceptance_evaluator_commit_sha"] = "f" * 40
    att["remote_main_sha"] = "b" * 40
    att["evaluator_diff_vs_remote_main"] = ["scripts/lib/cio_acceptance_v4.py"]
    att["evaluator_files_match_remote_main"] = False
    att["git_branch"] = "fix/cio-g2-attestation-pin"
    snap["evaluator_attestation"] = att
    g = eval_g0_canonical_acceptance_evaluator(attestation=att)
    assert g["status"] == "FAIL"
    v = evaluate_live_snapshot(snap)
    assert v["CORE_CIO_PRODUCTION_ACCEPTANCE"] == "FAIL"


def test_report_bytes_must_match_instance_manifest(tmp_path):
    html = tmp_path / "r.html"
    html_sha = _write_bytes(html, b"HTML")
    gates = eval_g10_g12_report_formats(
        html_path=str(html),
        pdf_path=str(tmp_path / "missing.pdf"),
        docx_path="",
        source_sha="a" * 40,
        live_sha="a" * 40,
        current_holdings_sha256=HOLDINGS_SHA,
        report_instance={
            "report_instance_id": "r1",
            "html_sha256": html_sha,
            "pdf_sha256": "p" * 64,
            "docx_sha256": "d" * 64,
            "portfolio_snapshot_hash": HOLDINGS_SHA,
        },
    )
    by = {g["gate"]: g for g in gates}
    assert by["G10_report_live_html"]["status"] == "PASS"
    assert by["G11_report_live_pdf"]["status"] == "FAIL"
    assert by["G12_report_live_docx"]["status"] == "FAIL"


def test_holdings_sha_mismatch_fails_report_gates(tmp_path):
    html = tmp_path / "r.html"
    pdf = tmp_path / "r.pdf"
    docx = tmp_path / "r.docx"
    h = _write_bytes(html, b"H")
    p = _write_bytes(pdf, b"P")
    d = _write_bytes(docx, b"D")
    gates = eval_g10_g12_report_formats(
        html_path=str(html), pdf_path=str(pdf), docx_path=str(docx),
        source_sha="a" * 40, live_sha="a" * 40,
        current_holdings_sha256="live" + "0" * 60,
        report_instance={
            "report_instance_id": "r1",
            "html_sha256": h,
            "pdf_sha256": p,
            "docx_sha256": d,
            "portfolio_snapshot_hash": "stale" + "1" * 59,
        },
    )
    assert all(g["status"] == "FAIL" for g in gates)
    assert any("holdings" in g["reason"] for g in gates)


def test_g13_qa_sha_must_equal_actual_pdf_bytes(tmp_path):
    pdf = tmp_path / "live.pdf"
    pdf.write_bytes(b"%PDF" + (b"x" * 200))
    actual = hashlib.sha256(pdf.read_bytes()).hexdigest()
    qa = tmp_path / "VISUAL_QA.json"
    qa.write_text('{"result":"PASS"}', encoding="utf-8")
    g = eval_g13_visual_qa(
        visual_qa_artifact=str(qa),
        pages_inspected=8,
        qa_pdf_sha256="not-the-file-hash",
        report_pdf_sha256=actual,
        pdf_page_count=8,
        qa_result="PASS",
        qa_instance_id="r1",
        report_instance_id="r1",
        pdf_path=str(pdf),
    )
    assert g["status"] == "FAIL"
    g2 = eval_g13_visual_qa(
        visual_qa_artifact=str(qa),
        pages_inspected=8,
        qa_pdf_sha256=actual,
        report_pdf_sha256=actual,
        pdf_page_count=8,
        qa_result="PASS",
        qa_instance_id="r1",
        report_instance_id="r1",
        pdf_path=str(pdf),
    )
    assert g2["status"] == "PASS"


def test_purity_detects_holdings_hash_change(tmp_path):
    p = tmp_path / "holdings.json"
    p.write_text('{"x":1}')
    before = snapshot_audited_files(holdings=p, extra=[])
    p.write_text('{"x":2}')
    after = snapshot_audited_files(holdings=p, extra=[])
    cmp = compare_audited(before, after)
    assert cmp["audited_state_unchanged"] is False
