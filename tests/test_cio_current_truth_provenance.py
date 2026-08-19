"""R6.10 — production advisory eligibility, defer revalidation, CIO current truth."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_alex_telegram import (
    deliver_decision,
    due_defers,
    evaluate_outbound,
    format_cio_message,
    record_defer,
    reopen_deferred,
)
from scripts.lib.cio_defer_revisit import plan_row_lookup, process_due_defers
from scripts.lib.cio_investment_product import (
    load_current_production_product,
    persist_product,
)
from scripts.lib.cio_production_eligibility import (
    CioStateIsolationError,
    classify_advisory_record,
    guard_test_cio_write,
    is_forbidden_from_production,
    is_production_advisory_eligible,
    prior_visible_for_what_changed,
    select_current_production_product as select_elig,
    unavailable_current_product,
)
from scripts.lib.cio_product_reassessment import diff_products
from scripts.lib.cio_notification_signal import decide_notification
from scripts.lib.cio_material_publisher import publish_material_decision


LIVE_DEFER = Path(
    "/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio/cio_defer_lineage.jsonl"
)


@pytest.fixture
def iso(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    monkeypatch.setenv("CIO_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("CIO_DEFER_LINEAGE_PATH", str(tmp_path / "data/cio/cio_defer_lineage.jsonl"))
    monkeypatch.setenv("CIO_TELEGRAM_RECEIPT_PATH", str(tmp_path / "data/cio/cio_telegram_receipts.jsonl"))
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(tmp_path / "data/cio/cio_outbound_dedupe.jsonl"))
    monkeypatch.setenv("CIO_TEST_ISOLATION", "1")
    monkeypatch.setenv("MEMORY_BEHAVIOR_INFLUENCE", "0")
    (tmp_path / "data" / "cio").mkdir(parents=True)
    return tmp_path


def _prod_decision(**over):
    d = {
        "decision_id": "dec_64d3c3ea68b4502a",
        "symbol": "SCHD",
        "action": "Trim",
        "stance": "Trim",
        "stance_code": "TRIM",
        "delta_usd": -44863.93,
        "why_now": "Advisory TRIM — SCHD concentration above the fire line",
        "counter_thesis": "Income sleeve may tolerate concentration longer",
        "what_changes_call": "Weight falls under the concentration cap",
        "next_review": "2026-08-21",
        "environment": "PROD",
        "synthetic": False,
        "source_kind": "OPERATOR",
        "producer": "operator",
        "urgency": "high",
        "status": "open",
        "capital": {"free_investable": 322174.75, "deploy_now": 353000.73, "remain_cash": 255936.39},
    }
    d.update(over)
    return d


def _e2e_defer(**over):
    d = {
        "decision_id": "dec_defer_activation_1496572f",
        "symbol": "CASH",
        "action": "HOLD_CASH",
        "reason": "activation_defer_e2e",
        "environment": "E2E",
        "synthetic": True,
        "source_kind": "E2E",
        "producer": "activation_e2e",
        "why_now": "",
    }
    d.update(over)
    return d


def _prod_product(*, as_of: str, product_id: str, extra=None):
    p = {
        "schema": "CIOInvestmentProduct@v1",
        "product_id": product_id,
        "as_of": as_of,
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "environment": "PROD",
        "synthetic": False,
        "source_kind": "PRODUCTION",
        "temperament": {"title": "RISK OFF"},
        "reentry_book": {"names": [], "count": 0},
        "opportunity_book": {"top": [], "count": 0},
        "action_book": {"DO_NOW": []},
        "summary": "hold cash",
    }
    if extra:
        p.update(extra)
    return p


def test_exact_e2e_failure_cannot_become_current(iso, monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    rec = record_defer(_e2e_defer(), revisit_at=past, reason="activation_defer_e2e")
    assert rec["ok"]
    assert rec["environment"] == "E2E"
    assert rec["synthetic"] is True
    assert not is_production_advisory_eligible(rec)
    assert is_forbidden_from_production(rec)

    due = due_defers()
    assert due  # still a workflow item until process quarantines

    monkeypatch.setenv("CIO_OFFICE_API_BASE", "http://127.0.0.1:9")
    out = process_due_defers(dry_run=True)
    assert out["processed"]
    item = out["processed"][0]
    assert item["reopened"] is False
    assert item["published"] is False
    assert item["reason"] == "not_production_advisory_eligible"

    body = format_cio_message(reopen_deferred(rec, decision={"decision_id": rec["decision_id"]}))
    assert "activation_defer_e2e" not in body
    assert "Deferred review due" not in body
    assert "DATA_UNAVAILABLE" in body

    ev = evaluate_outbound(_e2e_defer(why_now="Deferred review due (activation_defer_e2e)."))
    assert ev["production_would_send"] is False
    sent = deliver_decision(_e2e_defer(why_now="x" * 20), dry_run=False)
    assert sent["delivered"] is False
    assert sent["reason"] == "not_production_advisory_eligible"

    pub = publish_material_decision(_e2e_defer(why_now="material sounding why now text"))
    assert pub["published"] is False
    assert pub["reason"] == "not_production_advisory_eligible"

    nd = decide_notification(_e2e_defer(why_now="material sounding why now text"))
    assert nd["notification_class"] == "SUPPRESSED"
    assert nd["suppressed_reason"] == "not_production_advisory_eligible"


def test_newer_e2e_cannot_outrank_older_prod():
    older = _prod_product(as_of="2026-08-19T09:00:00+00:00", product_id="prod_old")
    newer = _prod_product(
        as_of="2026-08-19T09:05:00+00:00", product_id="prod_e2e",
        extra={"environment": "E2E", "synthetic": True, "source_kind": "E2E"},
    )
    assert select_elig([older, newer])["product_id"] == "prod_old"


def test_newer_shadow_cannot_outrank_prod():
    prod = _prod_product(as_of="2026-08-19T09:00:00+00:00", product_id="prod_p")
    shadow = _prod_product(
        as_of="2026-08-19T10:00:00+00:00", product_id="prod_s",
        extra={"environment": "SHADOW", "synthetic": False, "source_kind": "SHADOW"},
    )
    assert select_elig([prod, shadow])["product_id"] == "prod_p"


def test_malformed_missing_origin_not_silently_prod():
    raw = {"decision_id": "mystery", "why_now": "looks real"}
    v = classify_advisory_record(raw)
    assert v["classification"] == "LEGACY_UNPROVEN"
    assert v["eligible"] is False
    assert not is_production_advisory_eligible(raw)


def test_legitimate_operator_defer_revalidates(iso, monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    parent = _prod_decision()
    rec = record_defer(parent, revisit_at=past, reason="operator_defer")
    assert rec["environment"] == "PROD"
    assert rec["synthetic"] is False
    assert is_production_advisory_eligible(rec)

    plan = {
        "ok": True,
        "cash_investable_usd": 1000.0,
        "recommended_deploy_usd": 200.0,
        "post_plan_cash_usd": 800.0,
        "position_decisions": [parent],
    }
    monkeypatch.setattr("scripts.lib.cio_defer_revisit.fetch_capital_plan", lambda: plan)
    monkeypatch.setattr(
        "scripts.lib.cio_defer_revisit.retrieve_symbol_research",
        lambda *a, **k: {"decision_use_audit": {"used": False}},
    )
    out = process_due_defers(dry_run=True)
    item = out["processed"][0]
    assert item["reopened"] is True
    assert item["parent_lookup"] == "exact_decision_id"
    assert item.get("reason") != "exact_parent_unavailable"
    assert item.get("status") != "REVALIDATION_REQUIRED"
    # After reopen, latest status is reopened so a second cycle is not due.
    assert due_defers() == []


def test_duplicate_defer_one_logical_reassessment(iso, monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    parent = _prod_decision()
    record_defer(parent, revisit_at=past, reason="operator_defer")
    plan = {"ok": True, "position_decisions": [parent]}
    monkeypatch.setattr("scripts.lib.cio_defer_revisit.fetch_capital_plan", lambda: plan)
    monkeypatch.setattr(
        "scripts.lib.cio_defer_revisit.retrieve_symbol_research",
        lambda *a, **k: {"decision_use_audit": {}},
    )
    first = process_due_defers(dry_run=True)
    second = process_due_defers(dry_run=True)
    assert first["due"] == 1
    assert second["due"] == 0


def test_parent_missing_fails_closed(iso, monkeypatch):
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    rec = record_defer(_prod_decision(), revisit_at=past, reason="operator_defer")
    monkeypatch.setattr(
        "scripts.lib.cio_defer_revisit.fetch_capital_plan",
        lambda: {"ok": True, "position_decisions": [
            {"decision_id": "dec_other", "symbol": "SCHD", "why_now": "other thesis"}
        ]},
    )
    out = process_due_defers(dry_run=True)
    item = out["processed"][0]
    assert item["reopened"] is False
    assert item["status"] == "REVALIDATION_REQUIRED"
    assert item["reason"] == "exact_parent_unavailable"
    assert item["parent_lookup"] == "symbol_only_refused_for_live"
    body = format_cio_message({"decision_id": rec["decision_id"], "action": "HOLD_CASH",
                               "why_now": f"Deferred review due ({rec['reason']})."})
    assert "activation_defer" not in body
    assert "Deferred review due" not in body


def test_symbol_only_cannot_publish_live():
    plan = {"position_decisions": [
        {"decision_id": "dec_other", "symbol": "CASH", "why_now": "unrelated cash view"}
    ]}
    row, how = plan_row_lookup(plan, "dec_defer_activation_1496572f", "CASH",
                               allow_symbol_fallback=False)
    assert row is None
    assert how == "symbol_only_refused_for_live"
    row2, how2 = plan_row_lookup(plan, "dec_defer_activation_1496572f", "CASH",
                                 allow_symbol_fallback=True)
    assert row2["decision_id"] == "dec_other"
    assert how2 == "symbol_only_diagnostic"


def test_formatter_honest_unavailable():
    body = format_cio_message({
        "decision_id": "dec_64d3c3ea68b4502a",
        "symbol": "SCHD",
        "action": "HOLD_CASH",
        "environment": "PROD",
        "synthetic": False,
    })
    assert "see capital plan" not in body
    assert "None on record." not in body
    assert "DATA_UNAVAILABLE" in body
    assert "DEFAULT REVIEW CONDITION" in body
    assert "NEXT REVIEW" in body
    assert "\n—" not in body.split("NEXT REVIEW")[-1]


def test_formatter_real_capital_and_counter():
    body = format_cio_message(_prod_decision())
    assert "Free investable: $322,175" in body or "Free investable: $322,174" in body
    assert "Income sleeve" in body
    assert "2026-08-21" in body
    assert "DEFAULT REVIEW CONDITION" not in body


def test_what_changed_skips_e2e_between_prod():
    a = _prod_product(as_of="09:00", product_id="prod_a", extra={
        "reentry_book": {"names": [{"symbol": "ANET", "status": "WAIT"}]}
    })
    e2e = _prod_product(as_of="09:03", product_id="prod_e", extra={
        "environment": "E2E", "synthetic": True, "source_kind": "E2E",
        "reentry_book": {"names": [{"symbol": "ANET", "status": "REENTER"}]},
    })
    b = _prod_product(as_of="09:06", product_id="prod_b", extra={
        "reentry_book": {"names": [{"symbol": "ANET", "status": "WAIT"}]}
    })
    assert prior_visible_for_what_changed(e2e, b) == {}
    wc = diff_products(prior_visible_for_what_changed(e2e, b), b)
    # empty prior → adding WAIT is an add, but E2E must not be the compared prior
    wc_ab = diff_products(a, b)
    assert wc_ab["material"] is False


def test_test_state_root_wins_and_production_untouched(iso, tmp_path, monkeypatch):
    decoy = tmp_path / "cwd_decoy"
    (decoy / "data" / "cio").mkdir(parents=True)
    decoy_file = decoy / "data" / "cio" / "cio_defer_lineage.jsonl"
    decoy_file.write_text("{}\n", encoding="utf-8")
    before_live = LIVE_DEFER.read_bytes() if LIVE_DEFER.is_file() else None
    monkeypatch.chdir(decoy)
    record_defer(_prod_decision(), days=1, reason="operator_defer")
    written = Path(iso / "data/cio/cio_defer_lineage.jsonl")
    assert written.is_file()
    assert decoy_file.read_text(encoding="utf-8") == "{}\n"
    if before_live is not None:
        assert LIVE_DEFER.read_bytes() == before_live
    with pytest.raises(CioStateIsolationError):
        guard_test_cio_write(LIVE_DEFER)


def test_adversarial_artifacts_cannot_win():
    prod = _prod_product(as_of="2026-08-19T09:00:00+00:00", product_id="prod_real")
    attacks = [
        {**prod, "product_id": "prod_t1", "environment": "TEST", "synthetic": False,
         "as_of": "2099-01-01T00:00:00+00:00"},
        {**prod, "product_id": "prod_t2", "environment": "PROD", "synthetic": True,
         "as_of": "2099-01-01T00:00:00+00:00"},
        {**prod, "product_id": "mystery", "environment": None, "schema": "",
         "as_of": "2099-01-01T00:00:00+00:00"},
        {"decision_id": "dec_looks_prod", "reason": "prod operator review",
         "environment": "E2E", "synthetic": False, "as_of": "2099-01-01T00:00:00+00:00"},
        {**prod, "product_id": "!!!", "schema": "nope", "environment": None,
         "as_of": "2099-01-01T00:00:00+00:00"},
        {"decision_id": "dec_defer_activation_1496572f", "symbol": "SCHD",
         "environment": "E2E", "synthetic": True, "as_of": "2099-01-01T00:00:00+00:00"},
    ]
    chosen = select_elig([prod, *attacks])
    assert chosen["product_id"] == "prod_real"
    for a in attacks:
        assert not is_production_advisory_eligible(a) or a.get("product_id") == "prod_real"


def test_load_current_unavailable_when_only_e2e(iso):
    persist_product(_prod_product(
        as_of="2026-08-19T09:05:00+00:00", product_id="prod_e2e_only",
        extra={"environment": "E2E", "synthetic": True, "source_kind": "E2E"},
    ), root=iso)
    cur = load_current_production_product(iso)
    assert cur["status"] == "CIO_CURRENT_PRODUCT_UNAVAILABLE"


def test_unavailable_envelope():
    env = unavailable_current_product(reason="no_current_product")
    assert env["status"] == "CIO_CURRENT_PRODUCT_UNAVAILABLE"
    assert env["financial_action"] is False


def test_command_center_card_no_raw_e2e():
    body = format_cio_message({
        "decision_id": "dec_defer_activation_1496572f",
        "symbol": "CASH",
        "action": "HOLD_CASH",
        "why_now": "Deferred review due (activation_defer_e2e).",
        "environment": "E2E",
        "synthetic": True,
    })
    assert "activation_defer_e2e" not in body
    assert "Alex · CIO NOW" in body
