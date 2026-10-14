"""External advisory evidence only: no active_trader code, provider, secrets or sends."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
NOW = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def _row(**changes):
    row = {
        "symbol": "ABCD",
        "price": 12,
        "float_m": 8,
        "rvol": 6,
        "gap_pct": 7,
        "catalyst": "Fixture company announces a clinical result",
        "catalyst_source": "fixture-news",
        "catalyst_url": "https://news.example/clinical",
        "catalyst_verified": True,
        "catalyst_verification_method": "PRIMARY_PUBLICATION",
        "catalyst_at": "2026-10-12T14:00:00+00:00",
        "observed_at": "2026-10-12T14:30:00+00:00",
        "run_id": "2026-10-12::0900",
        "decision": "WAIT",
        "scout_pillar_count": 2,
        "scout_pillars_met": ["social_velocity", "market_confirmation"],
        "scout_pillars_missing": ["catalyst_evidence", "structure_tradeability", "strategy_risk_fit"],
    }
    row.update(changes)
    return row


@pytest.fixture
def evidence():
    from lib import momentum_setup_evidence

    return momentum_setup_evidence


def test_five_policy_facts_catalyst_and_scout_are_distinct_and_input_immutable(evidence):
    row = _row()
    before = copy.deepcopy(row)
    out = evidence.build_setup_evidence(row, now=NOW)
    assert row == before
    assert out["schema"] == "MomentumSetupEvidence@v1"
    assert [p["id"] for p in out["pillars"]] == ["price", "float", "rvol", "gap", "catalyst"]
    assert out["passed_count"] == 5 and out["all_five_proven"] is True
    assert out["social_scout"]["reported_count"] == 2
    assert out["catalyst"]["text"] == row["catalyst"]
    assert out["catalyst"]["source"] == "fixture-news"
    assert out["catalyst"]["url"] == row["catalyst_url"]
    assert out["authority"] == "READ_ONLY_ADVISORY" and out["execution_authority"] == "NONE"
    assert out["criteria_source"] == "scripts/lib/scalp_go_criteria.py:FALLBACK"
    assert out["pillar_definition"] == "momentum_policy_five"


def test_verification_relevance_and_confidence_survive_old_publication_independently(evidence):
    out = evidence.build_setup_evidence(
        _row(catalyst_at="2026-10-09T14:00:00Z", catalyst_relevance="RELEVANT", catalyst_confidence=0.97), now=NOW
    )
    assert out["catalyst"]["factual_verification_status"] == "VERIFIED"
    assert out["catalyst"]["relevance"] == "RELEVANT"
    assert out["catalyst"]["model_confidence"] == 0.97
    assert out["catalyst"]["publication_state"] == "STALE_SESSION"
    assert out["all_five_proven"] is False


def test_model_confidence_or_reported_boolean_cannot_establish_publication_verification(evidence):
    row = _row(catalyst_verification_method="MODEL_CONFIDENCE", catalyst_confidence=0.99)
    out = evidence.build_setup_evidence(row, now=NOW)
    assert out["catalyst"]["reported_verified"] is True
    assert out["catalyst"]["factual_verification_status"] == "UNKNOWN"
    assert out["all_five_proven"] is False


def test_advisory_publication_time_does_not_prove_underlying_quote_freshness(evidence):
    row = _row(observed_at=None)
    out = evidence.build_setup_evidence(row, now=NOW, observed_at=NOW.isoformat(), source_name="ACTIVE_TRADER")
    price = next(p for p in out["pillars"] if p["id"] == "price")
    assert price["observed_at"] is None and price["status"] == "UNKNOWN"


def test_projection_does_not_substitute_cache_time_for_original_observation(evidence):
    from lib.scanner_candidate_projection import build_candidate_projection

    cache = {"run_id": "2026-10-12::0900", "latest_run_timestamp": NOW.isoformat(), "tickers": [_row(observed_at=None)]}
    out = build_candidate_projection(cache, [], now=NOW)
    observed = out["candidates"][0]["trade_ai"]["observations"][0]
    assert observed["observed_at"] is None
    assert observed["setup_evidence"]["all_five_proven"] is False


def test_scan_run_aliases_preserve_session_without_borrowing_a_run_finish_clock(evidence):
    from lib.scanner_candidate_projection import build_candidate_projection

    row = _row(
        run_id=None,
        observed_at=None,
        scan_run_date="2026-10-12",
        scan_run_label="0900",
        scanned_at=NOW.isoformat(),
        created_at=NOW.isoformat(),
    )
    cache = {"run_id": "2026-10-12::0900", "latest_run_timestamp": NOW.isoformat(), "tickers": [row]}
    observed = build_candidate_projection(cache, [], now=NOW)["candidates"][0]["trade_ai"]["observations"][0]
    assert observed["run_id"] == "2026-10-12::0900"
    assert observed["lineage"]["session_date"] == "2026-10-12"
    assert observed["observed_at"] is None
    facts = observed["setup_evidence"]
    assert facts["source_observation_state"] == "UNKNOWN"
    assert facts["passed_count"] == 0 and facts["all_five_proven"] is False
    assert facts["pillars"][0]["value"] == 12
    assert facts["catalyst"]["factual_verification_status"] == "VERIFIED"


def test_original_producer_package_wins_over_unrelated_cached_latest_symbol(evidence):
    from lib.scanner_candidate_projection import build_candidate_projection

    source = _row(source_ref="fixture://original/row", observed_at="2026-10-12T14:30:00Z")
    row = evidence.public_scan_observation(
        source, run_id=source["run_id"], run_date="2026-10-12", run_label="0900", source_sha="a" * 40
    )
    cache = {
        "run_id": source["run_id"],
        "_cached_at": NOW.isoformat(),
        "tickers": [_row(decision="GO", observed_at=NOW.isoformat())],
        "source_observations": [row],
    }
    observation = build_candidate_projection(cache, [], now=NOW)["candidates"][0]["trade_ai"]["observations"][0]
    assert observation["verdict"] == "WAIT"
    assert observation["observed_at"] == "2026-10-12T14:30:00+00:00"
    assert observation["lineage"]["source_ref"] == source["source_ref"]


def test_source_snapshot_identity_ignores_cache_composition_time_and_keeps_original_zone(evidence):
    from lib.scanner_candidate_projection import build_candidate_projection

    row = _row(observed_at="2026-10-12T10:30:00-04:00")
    row["lineage"] = evidence.observation_lineage(row, source_name="TRADE_AI")
    cache = {"run_id": row["run_id"], "tickers": [row], "_cached_at": "2026-10-12T14:45:00Z"}
    first = build_candidate_projection(cache, [], now=NOW)
    cache["_cached_at"] = "2026-10-12T14:59:00Z"
    second = build_candidate_projection(cache, [], now=NOW)
    assert first["snapshot_id"] == second["snapshot_id"]
    observation = second["candidates"][0]["trade_ai"]["observations"][0]
    assert observation["lineage"]["original_timestamps"]["observed_at"] == "2026-10-12T10:30:00-04:00"


def test_public_observations_do_not_forward_unrelated_private_nested_fields(evidence):
    row = _row(
        field_observations={
            "price": {"observed_at": "2026-10-12T14:30:00Z", "source_ref": "fixture://price", "account": "PRIVATE"},
            "account": {"value": "PRIVATE"},
        }
    )
    out = evidence.public_scan_observation(row, run_id=row["run_id"], run_date="2026-10-12", run_label="0900")
    assert "PRIVATE" not in str(out)
    assert (
        evidence.build_setup_evidence(_row(catalyst_url="https://news.example/story?access_token=fixture"), now=NOW)[
            "catalyst"
        ]["url"]
        is None
    )


def test_observation_lineage_keeps_per_fact_time_and_source_after_refresh(evidence):
    row = _row(
        security_guid="tradeai:security:fixture",
        event_id="fixture-event",
        source_ref="fixture://scan/row-4",
        event_at="2026-10-12T14:10:00Z",
        field_observations={"price": {"observed_at": "2026-10-09T14:10:00Z", "source_ref": "fixture://quote/4"}},
    )
    before = copy.deepcopy(row)
    out = evidence.build_setup_evidence(row, now=NOW)
    price = next(p for p in out["pillars"] if p["id"] == "price")
    assert price["observed_at"] == "2026-10-09T14:10:00+00:00"
    assert price["source_ref"] == "fixture://quote/4" and price["status"] == "UNKNOWN"
    assert out["lineage"]["event_id"] == "fixture-event"
    assert out["lineage"]["source_ref"] == row["source_ref"] and row == before


def test_different_event_times_and_security_ids_do_not_create_false_decision_conflicts(evidence):
    from lib.scanner_candidate_projection import build_candidate_projection

    cache = {
        "run_id": "2026-10-12::0900",
        "tickers": [
            _row(
                security_guid="tradeai:security:one", event_id="event-1", event_at="2026-10-12T14:10:00Z", decision="GO"
            )
        ],
    }
    journal = [
        {
            "contract": "active-trader-momentum-alert-v1",
            "ts_epoch": NOW.timestamp(),
            "verdict": "VETO",
            "candidate": {
                "symbol": "ABCD",
                "security_guid": "tradeai:security:one",
                "event_id": "event-2",
                "event_at": "2026-10-12T14:20:00Z",
            },
        }
    ]
    out = build_candidate_projection(cache, journal, now=NOW)
    assert len(out["candidates"]) == 2
    assert all("CROSS_SOURCE_DISAGREEMENT" not in c["conflicts"] for c in out["candidates"])
    journal[0]["candidate"].update(
        security_guid="tradeai:security:two", event_id="event-1", event_at="2026-10-12T14:10:00Z"
    )
    assert len(build_candidate_projection(cache, journal, now=NOW)["candidates"]) == 2


@pytest.mark.parametrize(
    "key,value",
    [("price", None), ("float_m", 0), ("rvol", float("nan")), ("gap_pct", True), ("catalyst_verified", "true")],
)
def test_missing_malformed_metrics_never_become_a_pass(evidence, key, value):
    out = evidence.build_setup_evidence(_row(**{key: value}), now=NOW)
    target = {"float_m": "float", "gap_pct": "gap", "catalyst_verified": "catalyst"}.get(key, key)
    assert next(p for p in out["pillars"] if p["id"] == target)["status"] == "UNKNOWN"
    assert out["all_five_proven"] is False and out["passed_count"] < 5


@pytest.mark.parametrize(
    "key,value,pillar",
    [
        ("price", 26, "price"),
        ("float_m", 21, "float"),
        ("rvol", 4.9, "rvol"),
        ("gap_pct", 4.9, "gap"),
        ("catalyst_verified", False, "catalyst"),
    ],
)
def test_failed_policy_fact_is_not_unknown_or_promoted(evidence, key, value, pillar):
    out = evidence.build_setup_evidence(_row(**{key: value}), now=NOW)
    assert next(p for p in out["pillars"] if p["id"] == pillar)["status"] == "FAILED"
    assert out["all_five_proven"] is False


@pytest.mark.parametrize(
    "changed",
    [
        {"catalyst_at": None},
        {"catalyst_at": "2026-10-12T10:00:00"},
        {"catalyst_at": "2026-10-09T14:00:00+00:00"},
        {"catalyst_at": "2026-10-13T14:00:00+00:00"},
        {"catalyst_source": None},
        {"catalyst": None},
        {"observed_at": "2026-10-09T14:00:00+00:00"},
    ],
)
def test_old_incomplete_or_ambiguous_catalyst_cannot_prove_five(evidence, changed):
    out = evidence.build_setup_evidence(_row(**changed), now=NOW)
    assert out["all_five_proven"] is False
    assert next(p for p in out["pillars"] if p["id"] == "catalyst")["status"] == "UNKNOWN"


def test_catalyst_html_and_unsafe_url_are_not_forwarded_as_markup(evidence):
    out = evidence.build_setup_evidence(
        _row(catalyst="<script>alarm</script> & *BUY*", catalyst_url="javascript:alert(1)"), now=NOW
    )
    assert out["catalyst"]["url"] is None
    text = evidence.format_notification_evidence(out)
    assert "<script>" not in text and "javascript:" not in text


def _snapshot(evidence, row=None, now=NOW):
    from lib.scanner_candidate_projection import build_candidate_projection

    row = row or _row()
    cache = {"run_id": row["run_id"], "latest_run_timestamp": row["observed_at"], "tickers": [row]}
    return build_candidate_projection(cache, [], now=now)


def test_shared_projection_keeps_catalyst_per_source_and_does_not_change_verdicts(evidence):
    snap = _snapshot(evidence)
    row = snap["candidates"][0]
    assert row["classification"] == "WAIT"
    observation = row["trade_ai"]["observations"][0]
    assert observation["setup_evidence"]["catalyst"]["text"] == _row()["catalyst"]
    assert observation["setup_evidence"]["social_scout"]["reported_count"] == 2
    assert row["execution_authority"] == "NONE"


def test_notification_hook_binds_one_explicit_symbol_and_only_active_alerts(evidence):
    message = "ACTIVE TRADER · SCALP ALERT\nSymbol: ABCD\nAdvisory observation"
    calls = []
    loader = lambda: calls.append(True) or _snapshot(evidence)
    out = evidence.enrich_active_trader_notification(
        message, message_class="active_trader_scalp_alert", primary_symbols=["ABCD"], snapshot_loader=loader, now=NOW
    )
    assert out.startswith(message) and "Catalyst:" in out and _row()["catalyst"] in out
    assert "5/5" in out and "Price" in out and "Float" in out
    assert len(calls) == 1
    assert (
        evidence.enrich_active_trader_notification(
            out, message_class="active_trader_scalp_alert", primary_symbols=["ABCD"], snapshot_loader=loader, now=NOW
        )
        == out
    )
    assert len(calls) == 1
    ordinary = "ordinary operator action"
    assert (
        evidence.enrich_active_trader_notification(ordinary, primary_symbols=["ABCD"], snapshot_loader=loader, now=NOW)
        == ordinary
    )
    assert len(calls) == 1


@pytest.mark.parametrize("symbols", [[], ["ABCD", "WXYZ"], ["MISSING"]])
def test_missing_or_ambiguous_subject_does_not_borrow_other_catalyst(evidence, symbols):
    message = "ACTIVE TRADER · SCALP ALERT\nSymbol: MISSING"
    out = evidence.enrich_active_trader_notification(
        message, primary_symbols=symbols, snapshot_loader=lambda: _snapshot(evidence), now=NOW
    )
    assert "UNKNOWN" in out and _row()["catalyst"] not in out
    assert "5/5" not in out


def test_notification_does_not_promote_yesterday_same_symbol_or_source_conflict(evidence):
    row = _row(observed_at="2026-10-09T14:30:00+00:00", run_id="2026-10-09::1730")
    message = "ACTIVE TRADER · SCALP ALERT\nSymbol: ABCD"
    out = evidence.enrich_active_trader_notification(
        message, primary_symbols=["ABCD"], snapshot_loader=lambda: _snapshot(evidence, row), now=NOW
    )
    assert "UNKNOWN" in out and "5/5" not in out
    snap = _snapshot(evidence)
    snap["candidates"][0]["conflicts"] = ["TRADE_AI_VERDICT_CONFLICT"]
    out = evidence.enrich_active_trader_notification(
        message, primary_symbols=["ABCD"], snapshot_loader=lambda: snap, now=NOW
    )
    assert "UNKNOWN" in out and "5/5" not in out


def test_existing_catalyst_is_not_duplicated_and_failed_loader_preserves_send_body(evidence):
    message = "ACTIVE TRADER · SCALP ALERT\nSymbol: ABCD\nCatalyst: already declared"
    out = evidence.enrich_active_trader_notification(
        message, primary_symbols=["ABCD"], snapshot_loader=lambda: _snapshot(evidence), now=NOW
    )
    assert out.count("Catalyst:") == 1 and "5/5" in out

    def unavailable():
        raise OSError("synthetic cache unavailable")

    out = evidence.enrich_active_trader_notification(
        message, primary_symbols=["ABCD"], snapshot_loader=unavailable, now=NOW
    )
    assert out.startswith(message) and "UNKNOWN" in out


def test_notification_without_explicit_subject_uses_only_structured_header_binding(evidence):
    message = "ACTIVE TRADER · SCALP ALERT\nSymbol: ABCD\nEarlier unrelated WXYZ mentioned"
    out = evidence.enrich_active_trader_notification(message, snapshot_loader=lambda: _snapshot(evidence), now=NOW)
    assert _row()["catalyst"] in out
    ambiguous = "ACTIVE TRADER · SCALP ALERT\nSymbols: ABCD, WXYZ"
    out = evidence.enrich_active_trader_notification(ambiguous, snapshot_loader=lambda: _snapshot(evidence), now=NOW)
    assert "UNKNOWN" in out and _row()["catalyst"] not in out


def test_explicit_scope_cannot_override_different_header_symbol(evidence):
    message = "ACTIVE TRADER · SCALP ALERT\nSymbol: WXYZ"
    out = evidence.enrich_active_trader_notification(
        message, primary_symbols=["ABCD"], snapshot_loader=lambda: _snapshot(evidence), now=NOW
    )
    assert "UNKNOWN" in out and _row()["catalyst"] not in out


def test_run_identity_old_despite_current_timestamp_does_not_prove_five(evidence):
    row = _row(run_id="2026-10-09::1730")
    facts = evidence.build_setup_evidence(row, now=NOW)
    assert facts["source_observation_state"] == "TIMING_CONFLICT"
    assert facts["all_five_proven"] is False
    out = evidence.enrich_active_trader_notification(
        "ACTIVE TRADER · SCALP ALERT\nSymbol: ABCD",
        primary_symbols=["ABCD"],
        snapshot_loader=lambda: _snapshot(evidence, row),
        now=NOW,
    )
    assert "UNKNOWN" in out and "5/5" not in out


def test_malformed_explicit_policy_is_not_replaced_with_passing_defaults(evidence):
    out = evidence.build_setup_evidence(_row(), now=NOW, criteria={})
    assert all(p["status"] == "UNKNOWN" for p in out["pillars"] if p["id"] != "catalyst")
    assert out["all_five_proven"] is False and out["criteria_source"] == "EXPLICIT_CRITERIA"


def test_unrelated_embedded_alert_header_does_not_enrich_ordinary_message(evidence):
    message = "Daily system report\nEarlier event: ACTIVE TRADER · SCALP ALERT"

    def refused_loader():
        pytest.fail("non-alert message read candidate cache")

    assert evidence.enrich_active_trader_notification(message, snapshot_loader=refused_loader, now=NOW) == message


def test_public_trigger_header_can_bind_only_one_symbol_without_prose_guessing(evidence):
    message = "ACTIVE TRADER · SCALP ALERT\nTRIGGERED · ABCD\nEarlier WXYZ considered"
    out = evidence.enrich_active_trader_notification(message, snapshot_loader=lambda: _snapshot(evidence), now=NOW)
    assert _row()["catalyst"] in out and "5/5" in out


def test_malformed_cached_policy_sections_and_scout_items_remain_unknown(evidence):
    row = _row(scout_pillars_met=[{}, "social_velocity"], scout_pillars_missing=[[], "catalyst_evidence"])
    out = evidence.build_setup_evidence(
        row, now=NOW, criteria={"price": "bad", "float_m": [], "rvol": 8, "gap_pct": True}
    )
    assert all(p["status"] == "UNKNOWN" for p in out["pillars"] if p["id"] != "catalyst")
    assert out["social_scout"]["reported_met"] == ["social_velocity"]
    assert out["social_scout"]["reported_missing"] == ["catalyst_evidence"]


FRIENDLY_LABELS = ["BACK IN BUY ZONE", "TRIGGER FAILED", "STAND DOWN"]


@pytest.mark.parametrize("label", FRIENDLY_LABELS)
@pytest.mark.parametrize("delimiter", ["·", "—", ":"])
def test_friendly_public_trigger_binds_current_single_subject(evidence, monkeypatch, label, delimiter):
    from lib import comms_editor

    monkeypatch.setattr(comms_editor, "_resolve_primary_symbols", lambda explicit: None)
    message = f"ACTIVE TRADER · SCALP ALERT\n↩️ {label} {delimiter} *ABCD*\nEarlier unrelated WXYZ considered"
    assert evidence._structured_subject(message) == ["ABCD"]
    out = evidence.enrich_active_trader_notification(message, snapshot_loader=lambda: _snapshot(evidence), now=NOW)
    assert out.startswith(message) and _row()["catalyst"] in out and "5/5" in out
    assert "Metadata only; trigger and approval unchanged." in out


@pytest.mark.parametrize("label", FRIENDLY_LABELS)
@pytest.mark.parametrize("context", [["WXYZ"], ["ABCD", "WXYZ"]])
def test_friendly_trigger_cannot_override_stale_or_ambiguous_context(evidence, label, context):
    message = f"ACTIVE TRADER · SCALP ALERT\n{label} · ABCD"
    out = evidence.enrich_active_trader_notification(
        message, primary_symbols=context, snapshot_loader=lambda: _snapshot(evidence), now=NOW
    )
    assert "Momentum evidence (advisory): UNKNOWN" in out
    assert _row()["catalyst"] not in out and "5/5" not in out


@pytest.mark.parametrize("label", FRIENDLY_LABELS)
def test_friendly_trigger_multiple_explicit_header_symbols_remain_unknown(evidence, monkeypatch, label):
    from lib import comms_editor

    monkeypatch.setattr(comms_editor, "_resolve_primary_symbols", lambda explicit: None)
    message = f"ACTIVE TRADER · SCALP ALERT\n{label} · ABCD\nSymbols: ABCD, WXYZ"
    assert evidence._structured_subject(message) == ["ABCD", "WXYZ"]
    out = evidence.enrich_active_trader_notification(message, snapshot_loader=lambda: _snapshot(evidence), now=NOW)
    assert "UNKNOWN" in out and _row()["catalyst"] not in out and "5/5" not in out


@pytest.mark.parametrize("label", FRIENDLY_LABELS)
def test_friendly_trigger_does_not_promote_stale_same_symbol_cache(evidence, label):
    row = _row(run_id="2026-10-09::1730", observed_at="2026-10-09T14:30:00+00:00")
    message = f"ACTIVE TRADER · SCALP ALERT\n{label} · ABCD"
    out = evidence.enrich_active_trader_notification(
        message, primary_symbols=["ABCD"], snapshot_loader=lambda: _snapshot(evidence, row), now=NOW
    )
    assert "UNKNOWN" in out and _row()["catalyst"] not in out and "5/5" not in out


@pytest.mark.parametrize(
    "label", ["TRIGGERED", "ARMED", "APPROACHING", "PULLBACK_ZONE", "EXTENDED", "TRIGGER_CANCELLED", "STAND_DOWN"]
)
def test_existing_public_trigger_tokens_still_bind_subject(evidence, label):
    message = f"ACTIVE TRADER · SCALP ALERT\n{label} · ABCD"
    assert evidence._structured_subject(message) == ["ABCD"]
    out = evidence.enrich_active_trader_notification(
        message, primary_symbols=["ABCD"], snapshot_loader=lambda: _snapshot(evidence), now=NOW
    )
    assert _row()["catalyst"] in out and "5/5" in out
