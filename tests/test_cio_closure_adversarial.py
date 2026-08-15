"""Closure v4 adversarial battery — dry, no live Telegram/Drive/deploy."""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from scripts.lib.cio_acceptance_v4 import (  # noqa: E402
    eval_g2_release_manifest_parity,
    eval_g7_capital_plan_invariants,
    eval_g8_decision_parity,
    eval_g10_g12_report_formats,
    eval_g13_visual_qa,
    eval_g15_real_canary,
    eval_g16_zero_duplicate,
    eval_g18_ci_green,
    evaluate_live_snapshot,
)
from scripts.lib.cio_capital_invariants import (  # noqa: E402
    capital_invariants_ok,
    evaluate_capital_invariants,
)
from scripts.lib.cio_decision_parity import compare_decision_surfaces  # noqa: E402
from scripts.lib.cio_disposition_identity import (  # noqa: E402
    applicable_dispositions,
    lookup_decision,
    validate_post,
)
from scripts.lib.cio_delivery_mode import classify_delivery_mode  # noqa: E402
from scripts.lib.cio_market_session import get_market_session  # noqa: E402
from scripts.sync_cio_release_manifest_drive import CANONICAL_FILE_ID, run  # noqa: E402

# Local copies — do not import sibling test modules (pytest collection).
import tempfile as _tempfile

_ARTIFACT_DIR = Path(_tempfile.mkdtemp(prefix="cio_close_"))
HOLDINGS_SHA = "hold" + "b" * 60


def _write_bytes(path: Path, tag: bytes) -> str:
    path.write_bytes(b"%PDF-REPORT\n" + tag + (b"\n" * 120))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report_bundle(dest: Path | None = None) -> dict:
    d = dest or _ARTIFACT_DIR
    d.mkdir(parents=True, exist_ok=True)
    html_p, pdf_p, docx_p = d / "a.html", d / "a.pdf", d / "a.docx"
    qa_p = d / "VISUAL_QA.json"
    html_sha = _write_bytes(html_p, b"HTML")
    pdf_sha = _write_bytes(pdf_p, b"PDF")
    docx_sha = _write_bytes(docx_p, b"DOCX")
    qa_p.write_text('{"result":"PASS","pages_inspected":8}', encoding="utf-8")
    return {
        "html_path": str(html_p), "pdf_path": str(pdf_p), "docx_path": str(docx_p),
        "qa_path": str(qa_p), "html_sha256": html_sha, "pdf_sha256": pdf_sha,
        "docx_sha256": docx_sha,
    }


def _clean_snap():
    import test_cio_acceptance_v4 as acc
    return acc._clean_snap()

ET = ZoneInfo("America/New_York")


def test_g2_pin_only_live_equals_content():
    content, attest = "c" * 40, "a" * 40
    g = eval_g2_release_manifest_parity(
        manifest={
            "status": "production",
            "release_content_sha": content,
            "release_attestation_sha": attest,
            "canonical_source_sha": content,
            "backend_release_sha": content,
            "remote_main_sha_at_manifest": attest,
        },
        live_sha=content,
        main_sha=attest,
    )
    # pin_only_parent may be false without git; v2_attest needs pin. At least
    # live==content + v2 fields are recorded.
    assert g["actual"]["checks"]["live_eq_content"] is True
    assert g["actual"]["checks"]["v2_fields"] is True


def test_g2_runtime_content_v2_pass():
    sha = "b" * 40
    g = eval_g2_release_manifest_parity(
        manifest={
            "status": "production",
            "release_content_sha": sha,
            "canonical_source_sha": sha,
            "backend_release_sha": sha,
            "origin_main_sha": sha,
        },
        live_sha=sha,
        main_sha=sha,
    )
    assert g["status"] == "PASS"


def test_missing_capital_invariant_fails():
    g = eval_g7_capital_plan_invariants(plan={"authority": "READ_ONLY_ADVISORY"})
    assert g["status"] == "FAIL"
    assert g["actual"]["failed"]


def test_negative_account_cash_fails_g7():
    snap = _clean_snap()
    plan = snap["capital_plan"]
    plan["account_capital_ledger"]["accounts"][0]["settled_cash_usd"] = -5
    plan["account_capital_ledger"]["accounts"][0]["post_plan_cash_usd"] = -5
    g = eval_g7_capital_plan_invariants(plan=plan)
    assert g["status"] == "FAIL"
    assert "no_negative_account_cash" in g["actual"]["failed"]


def test_cash_as_prospective_raise_fails():
    plan = _clean_snap()["capital_plan"]
    plan["capital_sources"]["total_prospective_raise_usd"] = 100
    plan["capital_sources"]["trims_usd"] = 0
    plan["capital_sources"]["exits_usd"] = 0
    recs = {r["name"]: r for r in evaluate_capital_invariants(plan)}
    assert recs["prospective_raise_excludes_current_cash"]["pass"] is False
    assert capital_invariants_ok(plan) is False


def test_g8_plan_report_mismatch_fails():
    surfaces = {
        "capital_plan": [{"decision_id": "d1", "symbol": "SCHD", "action": "TRIM",
                          "decision_input_digest": "a", "decision_evidence_digest": "b"}],
        "cio_home": [{"decision_id": "d1", "symbol": "SCHD", "action": "TRIM",
                      "decision_input_digest": "a", "decision_evidence_digest": "b"}],
        "report": [{"decision_id": "d1", "symbol": "SCHD", "action": "HOLD",
                    "decision_input_digest": "a", "decision_evidence_digest": "b"}],
        "telegram": [{"decision_id": "d1", "symbol": "SCHD", "action": "TRIM",
                      "decision_input_digest": "a", "decision_evidence_digest": "b"}],
    }
    g = eval_g8_decision_parity(parity={"surfaces": surfaces})
    assert g["status"] == "FAIL"


def test_g8_telegram_digest_mismatch_fails():
    surfaces = {
        "capital_plan": [{"decision_id": "d1", "symbol": "AAA", "action": "TRIM",
                          "decision_input_digest": "in1", "decision_evidence_digest": "ev1",
                          "recommended_delta_usd": -100}],
        "cio_home": [{"decision_id": "d1", "symbol": "AAA", "action": "TRIM",
                      "decision_input_digest": "in1", "decision_evidence_digest": "ev1",
                      "recommended_delta_usd": -100}],
        "report": [{"decision_id": "d1", "symbol": "AAA", "action": "TRIM",
                    "decision_input_digest": "in1", "decision_evidence_digest": "ev1",
                    "recommended_delta_usd": -100}],
        "telegram": [{"decision_id": "d1", "symbol": "AAA", "action": "TRIM",
                      "decision_input_digest": "OTHER", "decision_evidence_digest": "ev1",
                      "recommended_delta_usd": -100}],
    }
    cmp = compare_decision_surfaces(
        plan=surfaces["capital_plan"],
        cio_home=surfaces["cio_home"],
        report=surfaces["report"],
        telegram_payload=surfaces["telegram"],
    )
    assert cmp["ok"] is False
    assert cmp["digest_mismatch"] or cmp["field_mismatch"]


def test_report_path_string_only_fails():
    gates = eval_g10_g12_report_formats(
        html_path="/tmp/does-not-exist-cio.html",
        pdf_path="/tmp/does-not-exist-cio.pdf",
        docx_path="/tmp/does-not-exist-cio.docx",
        source_sha="a" * 40,
        live_sha="a" * 40,
        report_instance={
            "report_instance_id": "x",
            "html_sha256": "0" * 64,
            "pdf_sha256": "1" * 64,
            "docx_sha256": "2" * 64,
            "portfolio_snapshot_hash": "h" * 64,
        },
        current_holdings_sha256="h" * 64,
    )
    assert all(g["status"] == "FAIL" for g in gates)


def test_stale_pdf_hash_fails():
    bundle = _report_bundle()
    gates = eval_g10_g12_report_formats(
        html_path=bundle["html_path"],
        pdf_path=bundle["pdf_path"],
        docx_path=bundle["docx_path"],
        source_sha="a" * 40,
        live_sha="a" * 40,
        report_instance={
            "report_instance_id": "inst-1",
            "html_sha256": bundle["html_sha256"],
            "pdf_sha256": "dead" * 16,
            "docx_sha256": bundle["docx_sha256"],
            "portfolio_snapshot_hash": "hold" + "b" * 60,
        },
        current_holdings_sha256="hold" + "b" * 60,
    )
    by = {g["gate"]: g for g in gates}
    assert by["G11_report_live_pdf"]["status"] == "FAIL"


def test_qa_missing_page_hashes_fails():
    bundle = _report_bundle()
    g = eval_g13_visual_qa(
        visual_qa_artifact=bundle["qa_path"],
        pages_inspected=8,
        qa_pdf_sha256=bundle["pdf_sha256"],
        report_pdf_sha256=bundle["pdf_sha256"],
        pdf_page_count=8,
        qa_result="PASS",
        qa_instance_id="inst-1",
        report_instance_id="inst-1",
        pdf_path=bundle["pdf_path"],
        page_image_hashes=["only-one"],
    )
    assert g["status"] == "FAIL"


def test_old_release_canary_fails():
    g = eval_g15_real_canary(
        canary_evidence={
            "sent": True, "operator_approved": True, "cio_chat_confirmed": True,
            "duplicate": False, "release_sha": "0" * 40,
            "decision_id": "d1", "decision_input_digest": "x",
        },
        live_sha="a" * 40,
    )
    assert g["status"] == "FAIL"


def test_canary_without_decision_digest_fails():
    sha = "a" * 40
    g = eval_g15_real_canary(
        canary_evidence={
            "sent": True, "operator_approved": True, "cio_chat_confirmed": True,
            "duplicate": False, "release_sha": sha,
        },
        live_sha=sha,
    )
    assert g["status"] == "FAIL"


def test_g16_without_repeat_attempt_fails():
    g = eval_g16_zero_duplicate(canary_evidence={
        "sent": True, "repeat_unchanged_sends": 0, "repeat_attempted": False,
    })
    assert g["status"] == "FAIL"


def test_g18_attestation_sha_not_green_fails():
    g = eval_g18_ci_green(
        cio_hardening_required=True,
        cio_hardening_green_on_sha=True,
        sha="c" * 40,
        content_sha="c" * 40,
        attestation_sha="a" * 40,
        content_hardening_green=True,
        attestation_hardening_green=False,
    )
    assert g["status"] == "FAIL"


def test_legacy_disposition_does_not_apply_to_new_decision():
    latest = {
        "position:SCHD:ira": {"disposition": "reject", "decision_key": "position:SCHD:ira"},
    }
    assert applicable_dispositions(latest, decision_id="dec-new") is None


def test_unknown_and_wrong_digest_disposition_rejected():
    store = [{"decision_id": "dec-1", "decision_input_digest": "in1",
              "decision_evidence_digest": "ev1"}]
    bad = validate_post(decision_key="dec-missing", body={"disposition": "ack",
                                                         "decision_id": "dec-missing"}, store=store)
    assert bad["ok"] is False
    mismatch = validate_post(
        decision_key="decision:dec-1",
        body={"disposition": "ack", "decision_id": "dec-1", "decision_input_digest": "WRONG"},
        store=store,
    )
    assert mismatch["ok"] is False
    ok = validate_post(
        decision_key="decision:dec-1",
        body={"disposition": "ack", "decision_id": "dec-1", "decision_input_digest": "in1"},
        store=store,
    )
    assert ok["ok"] is True


def test_labor_day_and_thanksgiving_closed():
    labor = get_market_session(datetime(2026, 9, 7, 15, 0, tzinfo=ET))
    thanks = get_market_session(datetime(2026, 11, 26, 15, 0, tzinfo=ET))
    assert labor["state"] == "CLOSED"
    assert thanks["state"] == "CLOSED"
    friday = get_market_session(datetime(2026, 11, 27, 12, 0, tzinfo=ET))
    assert friday["early_close"] is True


def test_delivery_mode_interdict_is_not_live():
    rec = classify_delivery_mode({
        "CIO_TELEGRAM_INTERDICT": "1",
        "ENABLE_TELEGRAM": "true",
        "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY": "1",
        "TELEGRAM_CIO_BOT_TOKEN": "x",
        "TELEGRAM_CIO_CHAT_IDS": "1",
    })
    assert rec["CIO_DELIVERY_MODE"] == "INTERDICTED"
    assert rec["proactive_delivery_ready"] is False


def test_cio_only_live_cannot_be_confused_with_general_bot():
    rec = classify_delivery_mode({
        "CIO_TELEGRAM_INTERDICT": "0",
        "ENABLE_TELEGRAM": "true",
        "AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY": "1",
        "TELEGRAM_CIO_BOT_TOKEN": "cio",
        "TELEGRAM_CIO_CHAT_IDS": "99",
        "TELEGRAM_BOT_TOKEN": "general",
    })
    assert rec["CIO_DELIVERY_MODE"] == "CIO_ONLY_LIVE"
    assert rec["general_token_present"] is True


def test_drive_sync_without_secret_is_blocked(tmp_path, monkeypatch):
    monkeypatch.delenv("GOG_KEYRING_PASSWORD", raising=False)
    rec = run(
        apply=True,
        file_id=CANONICAL_FILE_ID,
        expected_local_sha="not-the-real-hash",
        expected_remote_main="a" * 40,
        account="nobody@example.com",
    )
    assert rec["ok"] is False
    assert rec["wrote"] is False
    assert rec["status"] in {
        "BLOCKED_LOCAL_SHA_MISMATCH",
        "BLOCKED_SECRET_NOT_AVAILABLE",
        "BLOCKED_REMOTE_MAIN_REQUIRED",
    }


def test_full_office_stays_fail_when_core_green():
    v = evaluate_live_snapshot(_clean_snap())
    assert v["RESEARCH_GOVERNANCE_ACCEPTANCE"] == "NOT_YET_INTEGRATED"
    assert v["FULL_INVESTMENT_OFFICE_ACCEPTANCE"] == "FAIL"
    if v["CORE_CIO_PRODUCTION_ACCEPTANCE"] != "PASS":
        failed = [g["gate"] for g in v["gates"] if g["status"] != "PASS"]
        pytest.fail("core snapshot not green: " + ", ".join(failed))
