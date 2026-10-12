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
