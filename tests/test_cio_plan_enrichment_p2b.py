"""P2b plan enrichment: evidence pack, validator, template/cap paths, SpaceX."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def spacex_plan() -> dict:
    return {
        "plan_id": "plan_spacex_p2b",
        "situation_type": "S1_POSITION_LIFECYCLE",
        "symbols": ["SPACEX_TEST"],
        "status": "draft",
        "title": "S1 POSITION_LIFECYCLE — SPACEX_TEST",
        "summary": "Held SPACEX_TEST; basis=210; last=138; trough=108; street_mean_target=200",
        "options": [
            {"id": "hold", "label": "Hold", "pros": "a", "cons": "b"},
            {
                "id": "hold_stop_above_be",
                "label": "Hold + stop above break-even once last ≥ basis",
                "pros": "Protect reclaim",
                "cons": "Operator places stop",
            },
            {"id": "trim", "label": "Trim", "pros": "c", "cons": "d"},
        ],
        "recommendation": "Review hold vs stop-above-BE (basis=210) vs trim. Last=138.",
        "risks": ["Further drawdown"],
        "evidence_refs": [
            {
                "domain": "holdings_detail",
                "as_of": "2026-08-11T12:00:00+00:00",
                "fields_used": ["basis", "last", "trough"],
                "basis": 210.0,
                "last": 138.0,
                "trough": 108.0,
            },
            {
                "domain": "analyst_rollup",
                "as_of": "2026-08-11T12:00:00+00:00",
                "fields_used": ["mean_target"],
                "mean_target": 200.0,
            },
            {
                "domain": "risk_snapshot",
                "as_of": "2026-08-11T12:00:00+00:00",
                "fields_used": ["stop"],
            },
        ],
        "revisit_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
        "owner_agent": "alex",
        "fire_reasons": ["deep_drawdown_from_basis", "major_catalyst_while_held"],
        "authority": "READ_ONLY_ADVISORY",
    }


@pytest.fixture
def plan_store(tmp_path):
    from scripts.lib.cio_plans import CIOPlanStore
    return CIOPlanStore(
        event_path=tmp_path / "plans.jsonl",
        projection_path=tmp_path / "plans_proj.json",
    )


def test_evidence_pack_numbers_only_from_refs():
    from scripts.lib.cio_plan_enrichment import build_evidence_pack, collect_allowed_numbers
    plan = spacex_plan()
    pack = build_evidence_pack(plan)
    assert pack["authority"] == "READ_ONLY_ADVISORY"
    allowed = collect_allowed_numbers(pack)
    assert "210" in allowed or "210.0" in allowed
    assert "138" in allowed or "138.0" in allowed
    assert "200" in allowed or "200.0" in allowed
    # invented high number not in pack
    assert "99999" not in allowed


def test_notify_once_per_fingerprint(tmp_path, monkeypatch):
    """Same plan_id + same evidence must not re-notify; force bypasses."""
    from scripts.lib import cio_plan_enrichment as enr

    ledger = tmp_path / "notify_ledger.json"
    plan = spacex_plan()
    # The delivery bar is S6-only as of the 2026-08-29 operator sentence, and
    # the shared fixture is S1. This test is about fingerprint dedupe, not
    # about which type qualifies — so use a type that actually delivers, or the
    # dedupe assertions pass vacuously against a row the bar already dropped.
    plan["situation_type"] = "S6_CONCENTRATION_OR_DISPOSITION"
    plan["status"] = "proposed"
    plan["narrative_source"] = "llm"
    plan["evidence_hash"] = enr.evidence_hash(plan)

    monkeypatch.setenv("CIO_SITUATION_NOTIFY", "1")
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "999001")
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "fake-token")

    sends: list[tuple] = []

    def fake_send(chat_id, text, **kw):
        sends.append((chat_id, text))
        return {"ok": True}

    monkeypatch.setattr(
        "scripts.lib.cio_telegram_converse.send_cio_message",
        fake_send,
    )
    monkeypatch.setattr(
        "scripts.lib.cio_telegram_converse.allowlist_chat_ids",
        lambda: {"999001"},
    )

    pol = enr.load_llm_policy()
    pol["situation_notify_telegram"] = True

    # first notify → send
    assert enr.maybe_notify_plan(plan, policy=pol, ledger_path=ledger) is True
    assert len(sends) == 1
    # second notify same fingerprint → skip
    assert enr.maybe_notify_plan(plan, policy=pol, ledger_path=ledger) is False
    assert len(sends) == 1
    # force → send again
    assert enr.maybe_notify_plan(plan, policy=pol, force=True, ledger_path=ledger) is True
    assert len(sends) == 2
    # material evidence change → allow without force
    plan2 = dict(plan)
    plan2["evidence_refs"] = list(plan["evidence_refs"]) + [
        {"domain": "cash", "as_of": "2026-08-11", "cash_pct": 50.0}
    ]
    plan2["evidence_hash"] = enr.evidence_hash(plan2)
    plan2["fire_reasons"] = ["cash_pct_above_band", "quality_PARTIAL"]
    # min_gap may block if too soon — force policy gap to 0
    pol["notify_min_gap_minutes"] = 0
    assert enr.maybe_notify_plan(plan2, policy=pol, ledger_path=ledger) is True
    assert len(sends) == 3


def test_should_skip_notify_reasons(tmp_path):
    from scripts.lib.cio_plan_enrichment import (
        evidence_hash,
        notify_fingerprint,
        record_notify,
        should_skip_notify,
    )
    ledger = tmp_path / "ledger.json"
    plan = spacex_plan()
    plan["evidence_hash"] = evidence_hash(plan)
    skip, reason = should_skip_notify(plan, ledger_path=ledger)
    assert skip is False
    assert reason == "first_notify"
    record_notify(plan, ok=True, ledger_path=ledger)
    skip2, reason2 = should_skip_notify(plan, ledger_path=ledger)
    assert skip2 is True
    assert reason2 == "already_notified_same_fingerprint"
    assert notify_fingerprint(plan)


def test_validator_rejects_invented_price():
    from scripts.lib.cio_plan_enrichment import build_evidence_pack, validate_narrative
    pack = build_evidence_pack(spacex_plan())
    bad = {
        "summary": "Target is 99999 and last is 138",
        "options": [{"id": "hold", "label": "Hold", "pros": "", "cons": ""}],
        "recommendation": "Buy at 99999",
        "risks": ["x"],
        "cited_fields": ["last"],
    }
    ok, errs = validate_narrative(bad, pack)
    assert not ok
    assert any("invented" in e for e in errs)

    good = {
        "summary": "Basis 210, last 138, mean target 200. No stop above BE.",
        "options": [
            {"id": "hold", "label": "Hold", "pros": "", "cons": ""},
            {"id": "stop_above_be", "label": "Stop above break-even", "pros": "", "cons": ""},
        ],
        "recommendation": "Prefer hold + stop-above-BE once last approaches basis 210.",
        "risks": ["drawdown"],
        "cited_fields": ["basis", "last", "mean_target"],
    }
    ok2, errs2 = validate_narrative(good, pack)
    assert ok2, errs2


def test_cap_blocked_template_path(plan_store, monkeypatch, tmp_path):
    from scripts.lib import cio_plan_enrichment as enr
    # force local hour cap already full
    counter = tmp_path / "hour.json"
    counter.write_text(json.dumps({"hour": enr._hour_bucket(), "count": 999}))
    monkeypatch.setattr(enr, "DEFAULT_CALL_COUNTER", counter)
    monkeypatch.setattr(enr, "DEFAULT_ENRICH_LOG", tmp_path / "log.jsonl")

    plan = spacex_plan()
    # seed plan in store
    created = plan_store.create_plan(
        situation_type=plan["situation_type"],
        symbols=plan["symbols"],
        title=plan["title"],
        summary=plan["summary"],
        options=plan["options"],
        recommendation=plan["recommendation"],
        risks=plan["risks"],
        evidence_refs=plan["evidence_refs"],
        revisit_at=plan["revisit_at"],
        owner_agent="alex",
        plan_id=plan["plan_id"],
        extra={"fire_reasons": plan["fire_reasons"]},
    )
    res = enr.enrich_plan(
        created,
        source="S1_POSITION_LIFECYCLE",
        plan_store=plan_store,
        policy={
            "enabled": True,
            "material_sources": ["S1_POSITION_LIFECYCLE"],
            "llm": {"enabled": True, "max_calls_per_hour": 1, "enrich_dedup_hours": 6},
            "validator": {"reject_invented_numbers": True, "max_retries": 0},
        },
    )
    assert res["llm"] == "blocked_cap"
    assert res["narrative_source"] == "template"
    p = res["plan"]
    assert p is not None
    # Material template is desk-synthesis (no "LLM deferred" spam); still thesis-aware
    rec = (p.get("recommendation") or "").lower()
    assert (
        "desk@" in (p.get("thesis_version") or "")
        or "desk@" in rec
        or "highest-signal" in rec
        or p.get("thesis_alignment")
    )
    # still updated
    got = plan_store.get_plan(plan["plan_id"])
    assert got is not None


def test_material_vs_non_material():
    from scripts.lib.cio_plan_enrichment import is_material_source, load_llm_policy
    pol = load_llm_policy()
    assert is_material_source("S1_POSITION_LIFECYCLE", pol)
    assert is_material_source("OPERATOR_MESSAGE", pol)
    assert not is_material_source("system.heartbeat_ok", pol)
    assert not is_material_source("cio_slash_status", pol)


def test_enrichment_dedup(plan_store, monkeypatch, tmp_path):
    from scripts.lib import cio_plan_enrichment as enr
    monkeypatch.setattr(enr, "DEFAULT_ENRICH_LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(enr, "DEFAULT_CALL_COUNTER", tmp_path / "hour.json")

    plan = spacex_plan()
    created = plan_store.create_plan(
        situation_type=plan["situation_type"],
        symbols=plan["symbols"],
        title=plan["title"],
        summary=plan["summary"],
        options=plan["options"],
        recommendation=plan["recommendation"],
        risks=plan["risks"],
        evidence_refs=plan["evidence_refs"],
        revisit_at=plan["revisit_at"],
        owner_agent="alex",
        plan_id="plan_dedup1",
        extra={"fire_reasons": plan["fire_reasons"]},
    )
    # force template first pass
    r1 = enr.enrich_plan(created, source="S1_POSITION_LIFECYCLE", force_template=True, plan_store=plan_store)
    assert r1["narrative_source"] == "template"
    p1 = plan_store.get_plan("plan_dedup1")
    r2 = enr.enrich_plan(p1, source="S1_POSITION_LIFECYCLE", plan_store=plan_store)
    assert r2["llm"] == "skipped_dedup"


def test_spacex_template_enrich_mentions_fixture_numbers(plan_store, monkeypatch, tmp_path):
    from scripts.lib import cio_plan_enrichment as enr
    monkeypatch.setattr(enr, "DEFAULT_ENRICH_LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(enr, "DEFAULT_CALL_COUNTER", tmp_path / "hour.json")
    plan = spacex_plan()
    created = plan_store.create_plan(
        situation_type=plan["situation_type"],
        symbols=plan["symbols"],
        title=plan["title"],
        summary=plan["summary"],
        options=plan["options"],
        recommendation=plan["recommendation"],
        risks=plan["risks"],
        evidence_refs=plan["evidence_refs"],
        revisit_at=plan["revisit_at"],
        owner_agent="alex",
        plan_id="plan_spacex_enr",
        extra={"fire_reasons": plan["fire_reasons"]},
    )
    res = enr.enrich_plan(created, source="S1_POSITION_LIFECYCLE", force_template=True, plan_store=plan_store)
    p = res["plan"]
    blob = f"{p.get('summary')} {p.get('recommendation')} {json.dumps(p.get('options'))}"
    assert "210" in blob
    assert "138" in blob
    assert "200" in blob
    assert "stop" in blob.lower() and ("break-even" in blob.lower() or "be" in blob.lower() or "basis" in blob.lower())
    # no invented 99999
    assert "99999" not in blob


def test_forced_llm_provider_fail_falls_to_template(plan_store, monkeypatch, tmp_path):
    from scripts.lib import cio_plan_enrichment as enr
    monkeypatch.setattr(enr, "DEFAULT_ENRICH_LOG", tmp_path / "log.jsonl")
    monkeypatch.setattr(enr, "DEFAULT_CALL_COUNTER", tmp_path / "hour.json")

    def boom(*a, **k):
        return {"ok": False, "error": "PROVIDER_BLOCKED", "governance_refused": True, "governance_code": "PROVIDER_BLOCKED"}

    monkeypatch.setattr(enr, "call_governed_llm", boom)
    plan = spacex_plan()
    created = plan_store.create_plan(
        situation_type=plan["situation_type"],
        symbols=plan["symbols"],
        title=plan["title"],
        summary=plan["summary"],
        options=plan["options"],
        recommendation=plan["recommendation"],
        risks=plan["risks"],
        evidence_refs=plan["evidence_refs"],
        revisit_at=plan["revisit_at"],
        owner_agent="alex",
        plan_id="plan_provfail",
    )
    res = enr.enrich_plan(
        created,
        source="OPERATOR_MESSAGE",
        force_llm=True,
        plan_store=plan_store,
        policy={
            "enabled": True,
            "material_sources": ["OPERATOR_MESSAGE"],
            "llm": {"enabled": True, "max_calls_per_hour": 100, "enrich_dedup_hours": 0, "pro_for": []},
            "validator": {"reject_invented_numbers": True, "max_retries": 0},
        },
    )
    assert res["llm"] == "blocked_provider"
    assert res["narrative_source"] == "template"
    assert res.get("plan") is not None


def test_no_broker_imports_in_enrichment_module():
    import scripts.lib.cio_plan_enrichment as m
    src = Path(m.__file__).read_text()
    assert "broker" not in src.lower() or "READ_ONLY" in src
    # no schwab/alpaca order verbs
    for bad in ("place_order", "submit_order", "schwab_order", "alpaca_submit"):
        assert bad not in src
