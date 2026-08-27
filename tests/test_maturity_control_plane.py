"""Maturity control plane — Phase 11 promotion, learning, notification, GET-only."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.maturity_control import promotion as P
from scripts.lib.maturity_control import store
from scripts.lib.maturity_control.lessons import collect_lessons
from scripts.lib.maturity_control.notification_view import collect_notification_gate
from scripts.lib.maturity_control.redaction import redact
from scripts.lib.maturity_control.schema import (
    ACK_TOKEN,
    authority_violations,
    content_hash,
    map_kb_status_to_lesson_state,
    validate_promotion_record,
)
from scripts.lib.maturity_control.telegram_receipts import collect_telegram_receipts
from scripts import api_v3_maturity as api
from scripts.maturity_promotion import main as cli_main


SHA = "8d18a6681b7fee17fc3eba0e3581c7927afe25f9"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "data" / "cio").mkdir(parents=True)
    (tmp_path / "data" / "runtime").mkdir(parents=True)
    (tmp_path / "SOURCE_COMMIT").write_text(SHA + "\n")
    monkeypatch.setenv("TRADEAI_ROOT", str(tmp_path))
    monkeypatch.setenv("MATURITY_CONTROL_ROOT", str(tmp_path))
    return tmp_path


def _bundle(**kw):
    return {"reviews": 2, "scores": 2, "reviewer": "iris", "scorer": "darwin", **kw}


def _draft(root: Path, **kw) -> dict:
    rec = P.new_promotion(
        capability_type=kw.get("capability_type", "lesson_ratified_to_shadow_influence"),
        from_state=kw.get("from_state", "RATIFIED_CONTEXT"),
        requested_state=kw.get("requested_state", "SHADOW_INFLUENCE"),
        exact_source_sha=kw.get("sha", SHA),
        requested_by="operator",
        lesson_id=kw.get("lesson_id", "les_1"),
        agent_id=kw.get("agent_id"),
        evidence_bundle=kw.get("evidence_bundle", _bundle()),
        matured_outcome_count=kw.get("matured", 3),
        shadow_sample_size=kw.get("shadow_n", 12),
        quality_metrics={"score": 80},
        safety_metrics={"authority_violations": 0},
        rollback_target="RATIFIED_CONTEXT",
        root=root,
    )
    return rec


def test_lesson_lifecycle_mapping():
    assert map_kb_status_to_lesson_state("candidate") == "CANDIDATE"
    assert map_kb_status_to_lesson_state("ratified") == "RATIFIED_CONTEXT"
    assert map_kb_status_to_lesson_state("ratified", "SHADOW_INFLUENCE") == "SHADOW_INFLUENCE"
    assert map_kb_status_to_lesson_state("retired") == "RETIRED"


def test_collect_lessons_from_kb(root: Path):
    p = root / "data" / "runtime" / "advisory_kb_lessons.jsonl"
    p.write_text(json.dumps({
        "id": "abc", "status": "ratified", "title": "trim concentration",
        "body": "SCHD fire line", "symbols": ["SCHD"], "source": "iris",
        "applications": 4, "hits": 3, "hit_rate": 0.75, "citations": 1,
        "ratified_at": "2026-08-01T00:00:00+00:00", "ratified_by": "iris",
        "evidence_refs": ["case_1"],
    }) + "\n")
    view = collect_lessons(root=root)
    assert view["counts"]["RATIFIED_CONTEXT"] == 1
    les = view["lessons"][0]
    assert les["lifecycle"] == "RATIFIED_CONTEXT"
    assert les["not_production_policy"] is True
    assert les["hit_rate"] == 0.75


def test_promotion_schema_and_authority(root: Path):
    rec = _draft(root)
    assert validate_promotion_record(rec) == []
    bad = dict(rec, capability_type="broker_write")
    assert any("capability" in e or "authority" in e for e in validate_promotion_record(bad))
    assert authority_violations({"grants": ["broker_write"]})


def test_opaque_ids_do_not_trip_authority_gate(root: Path):
    """Hex ids/digests must not be substring-scanned for authority tokens.

    A 16-hex promotion_id contains "2fa" ~0.35% of the time and a 40-hex commit
    SHA ~0.9%, which used to raise a phantom "2FA" violation and fail preflight
    on a compliant record. Real tokens in semantic fields must still be caught.
    """
    rec = _draft(root)
    for field, value in (
        ("promotion_id", "prm_a12fa9c3d4e5f607"),
        ("exact_source_sha", "a12fa9c3d4e5f607" + "b" * 24),
        ("evidence_bundle_hash", "c12fa9" + "d" * 58),
    ):
        assert authority_violations(dict(rec, **{field: value})) == [], field
    # the gate still fires on forbidden authorities in semantic fields
    assert authority_violations(dict(rec, grants=["2FA"])) == ["2FA"]
    assert authority_violations(dict(rec, financial_action=True)) == ["financial_action"]


def test_invalid_signature(root: Path):
    rec = _draft(root)
    rec = P.preflight(rec, live_sha=SHA, has_review=True, has_score=True, root=root)
    with pytest.raises(P.PromotionError) as ei:
        P.sign(rec, operator="op", ack="WRONG", live_sha=SHA, root=root)
    assert ei.value.code == "invalid_signature"


def test_expired_promotion(root: Path):
    rec = _draft(root)
    rec["expires_at"] = "2020-01-01T00:00:00+00:00"
    rec = P.preflight(rec, live_sha=SHA, has_review=True, has_score=True, root=root)
    assert rec["status"] == "PREFLIGHT_FAILED"
    assert "expired" in rec["preflight_errors"]


def test_sha_mismatch(root: Path):
    rec = _draft(root)
    rec = P.preflight(rec, live_sha="0" * 40, has_review=True, has_score=True, root=root)
    assert "sha_mismatch" in rec["preflight_errors"]


def test_evidence_hash_mismatch(root: Path):
    rec = _draft(root)
    rec["evidence_bundle"] = {"tampered": True}
    rec = P.preflight(rec, live_sha=SHA, has_review=True, has_score=True, root=root)
    assert "evidence_hash_mismatch" in rec["preflight_errors"]


def test_promotion_without_review_or_score(root: Path):
    rec = _draft(root)
    rec = P.preflight(rec, live_sha=SHA, has_review=False, has_score=False, root=root)
    assert "missing_independent_review" in rec["preflight_errors"]
    assert "missing_independent_score" in rec["preflight_errors"]


def test_promotion_authority_violation(root: Path):
    rec = _draft(root, capability_type="order_write")
    rec = P.preflight(rec, live_sha=SHA, has_review=True, has_score=True, root=root)
    assert rec["status"] == "PREFLIGHT_FAILED"
    assert any("capability" in e or "authority" in e for e in rec["preflight_errors"])


def test_dry_canary_sign_restrict_rollback(root: Path):
    rec = _draft(root)
    rec = P.preflight(rec, live_sha=SHA, has_review=True, has_score=True, root=root)
    assert rec["status"] == "READY_FOR_SIGNOFF"
    rec = P.sign(rec, operator="john", ack=ACK_TOKEN, live_sha=SHA, root=root)
    assert rec["status"] == "SIGNED"
    assert P.verify_signoff(rec)
    rec = P.activate_canary(rec, root=root)
    assert rec["status"] == "CANARY"
    overlays = store.load_json_map("lessons", root=root)
    assert overlays["les_1"]["state"] == "SHADOW_INFLUENCE"
    rec = P.restrict(rec, reason="test", root=root)
    assert rec["status"] == "RESTRICTED"
    rec = P.rollback(rec, reason="test", root=root)
    assert rec["status"] == "ROLLED_BACK"
    events = store.load_events(root=root)
    assert len(events) >= 5
    assert all(e.get("financial_action") is not True for e in events)


def test_cli_inspect_roundtrip(root: Path, capsys):
    rec = _draft(root)
    rec = P.preflight(rec, live_sha=SHA, has_review=True, has_score=True, root=root)
    rc = cli_main(["--root", str(root), "--sha", SHA, "inspect", rec["promotion_id"]])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["promotion"]["promotion_id"] == rec["promotion_id"]


def test_notification_ui_mapping(root: Path):
    row = {
        "decision_lineage_id": "cash_posture:CASH",
        "evidence_generation_id": "ev1",
        "material_generation_id": "mat1",
        "notification_class": "SUPPRESSED",
        "suppressed_reason": "unchanged_replay",
        "created_at": "2026-08-18T00:00:00+00:00",
        "telegram_message_id": 42,
        "TELEGRAM_BOT_TOKEN": "should-not-leak",
    }
    (root / "data" / "cio" / "cio_notification_state.jsonl").write_text(json.dumps(row) + "\n")
    view = collect_notification_gate(root=root)
    lin = view["lineages"][0]
    assert lin["decision_lineage_id"] == "cash_posture:CASH"
    assert lin["notification_class"] == "SUPPRESSED"
    assert lin["telegram_message_id"] == 42
    blob = json.dumps(view)
    assert "should-not-leak" not in blob


def test_telegram_receipt_mapping_and_redaction(root: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "1")
    monkeypatch.setenv("TELEGRAM_CIO_BOT_TOKEN", "SECRETTOKENVALUE")
    monkeypatch.setenv("TELEGRAM_CIO_CHAT_IDS", "1")
    rec = {
        "at": "2026-08-18T00:00:00+00:00",
        "ok": True,
        "message_id": 99,
        "dedupe_key": "ntf_1",
        "kind": "delivery",
        "bot_token": "SECRETTOKENVALUE",
    }
    (root / "data" / "cio" / "cio_telegram_delivery.jsonl").write_text(json.dumps(rec) + "\n")
    view = collect_telegram_receipts(root=root)
    assert view["interdicted"] is True
    assert view["receipts"][0]["message_id"] == 99
    blob = json.dumps(view)
    assert "SECRETTOKENVALUE" not in blob
    assert view["credentials_ready"] is True  # token set (boolean only)


def test_secret_redaction_helper():
    obj = {"bot_token": "abc", "ok": True, "note": "Bearer ABCDEFGHIJKLMNOP"}
    out = redact(obj)
    assert out["bot_token"] == "[REDACTED]"
    assert "ABCDEFGHIJKLMNOP" not in json.dumps(out)


def test_get_only_runtime_api(root: Path):
    code, body = api.handle_get("learning")
    assert code == 200
    assert body["mutation"] is False
    assert body["financial_action"] is False
    assert body["auto_promotion_to_trading"] is False
    code, body = api.handle_control_post("sign", {"promotion_id": "x"})
    assert code == 403
    assert body["error"] == "control_disabled"


def test_scorecard_get_route(root: Path):
    code, body = api.handle_get("scorecard")
    assert code == 200
    assert body["ok"] is True
    assert body["financial_action"] is False
    assert body["authority"] == "READ_ONLY_ADVISORY"
    assert body["schema"] == "MaturityScorecard@v1"
    assert body["mutation"] is False
    assert "research_skip" in body["dimensions"]
    assert body["dimensions"]["memory_influence"]["score"] == 0


def test_notification_immediate_then_suppressed_fixture(root: Path):
    p = root / "data" / "cio" / "cio_notification_state.jsonl"
    rows = [
        {"decision_lineage_id": "reentry:BOOK", "notification_class": "IMMEDIATE",
         "material_generation_id": "g1", "created_at": "2026-08-18T00:00:00+00:00"},
        {"decision_lineage_id": "reentry:BOOK", "notification_class": "SUPPRESSED",
         "suppressed_reason": "unchanged_replay", "material_generation_id": "g1",
         "created_at": "2026-08-18T00:05:00+00:00"},
    ]
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    view = collect_notification_gate(root=root)
    lin = view["lineages"][0]
    assert lin["notification_class"] == "SUPPRESSED"
    assert lin["suppression_reason"] == "unchanged_replay"


def test_cc_typescript_tabs_present():
    agents = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/AgentRuntimeHub.tsx").read_text()
    cio = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/CioHub.tsx").read_text()
    health = (Path(__file__).resolve().parent.parent / "apps/command-center-v3/src/pages/HealthHub.tsx").read_text()
    for name in ("Learning", "Promotion", "Cases", "Evidence"):
        assert name in agents
    for name in ("notification-gate", "telegram-receipts", "senses-evidence"):
        assert name in cio
    assert "intelligence-loop" in health
    assert "AUTO-PROMOTION TO TRADING" in agents
