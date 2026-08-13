"""Checkpoint 4 — Advisory committee + InvestmentDecision@v1 canaries.

Proves, with zero provider calls and zero live side effects, that the converged
office has:

  * a deterministic committee under a chair (Alex) with quorum, consensus,
    dissent, and a fail-closed defense veto
  * a canonical, hash-pinned InvestmentDecision@v1 contract
  * an evidence gate that blocks execution on missing/blocking evidence
  * a one-decision → one-action → one-notification pipeline (idempotent)

All tests use pure functions / temp-path stores. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import pytest

from scripts.lib.cio_committee import (
    CommitteeVote,
    convene,
    vote,
    POSITION_SUPPORT,
    POSITION_OPPOSE,
    POSITION_NEUTRAL,
    POSITION_DEFER,
    POSITION_INSUFFICIENT_EVIDENCE,
)
from scripts.lib.cio_investment_decision import (
    InvestmentDecision,
    build_decision,
    decision_to_action_payload,
    SCHEMA_VERSION,
    POSITION_BUY,
    POSITION_HOLD,
    POSITION_NO_ACTION,
    POSITION_TRIM,
    ACTIONABILITY_READY,
    ACTIONABILITY_NEEDS_EVIDENCE,
    ACTIONABILITY_CONFLICT,
)
from scripts.lib.cio_evidence_ref import (
    make_ref,
    QUALITY_STATE_AVAILABLE,
    QUALITY_STATE_DATA_UNAVAILABLE,
)


# ── Committee: quorum / consensus / dissent ───────────────────────────────────


def test_committee_unanimous_support():
    r = convene([
        vote("morgan", POSITION_SUPPORT),
        vote("steph", POSITION_SUPPORT),
        vote("maria", POSITION_SUPPORT),
    ])
    assert r.quorum_met is True
    assert r.consensus == "UNANIMOUS_SUPPORT"
    assert r.actionable is True
    assert r.dissenters == []


def test_committee_consensus_support_with_dissent():
    r = convene([
        vote("morgan", POSITION_SUPPORT),
        vote("steph", POSITION_SUPPORT),
        vote("maria", POSITION_SUPPORT),
        vote("ledger", POSITION_OPPOSE),  # minority dissent
    ])
    # 3 support / 4 actionable = 75% → CONSENSUS_SUPPORT, ledger is dissenter
    assert r.consensus == "CONSENSUS_SUPPORT"
    assert r.actionable is True
    assert "ledger" in r.dissenters
    assert r.material_disagreements


def test_committee_mixed_no_supermajority():
    r = convene([
        vote("morgan", POSITION_SUPPORT),
        vote("steph", POSITION_OPPOSE),
    ], quorum=2)
    assert r.consensus == "MIXED"
    assert r.actionable is False
    assert r.quorum_met is True


def test_committee_defense_veto_blocks():
    r = convene([
        vote("morgan", POSITION_SUPPORT),
        vote("steph", POSITION_SUPPORT),
        vote("maria", POSITION_SUPPORT),
        vote("guardian", POSITION_OPPOSE),  # risk officer veto
    ])
    assert r.consensus == "BLOCKED_DEFENSE"
    assert r.actionable is False
    assert r.blocking_vetoes == ["guardian"]


def test_committee_quorum_not_met():
    r = convene([
        vote("morgan", POSITION_SUPPORT),
        vote("steph", POSITION_DEFER),
    ], quorum=3)
    assert r.consensus == "BLOCKED_QUORUM"
    assert r.quorum_met is False
    assert r.actionable is False


def test_committee_neutral_consensus():
    r = convene([
        vote("morgan", POSITION_NEUTRAL),
        vote("steph", POSITION_NEUTRAL),
        vote("maria", POSITION_NEUTRAL),
    ])
    assert r.consensus == "CONSENSUS_NEUTRAL"
    assert r.actionable is False


def test_committee_defer_and_insufficient_do_not_satisfy_quorum():
    # DEFER / INSUFFICIENT_EVIDENCE are non-actionable and do not count toward quorum.
    r = convene([
        vote("morgan", POSITION_NEUTRAL),
        vote("steph", POSITION_DEFER),
        vote("maria", POSITION_INSUFFICIENT_EVIDENCE),
    ], quorum=3)
    assert r.consensus == "BLOCKED_QUORUM"
    assert r.quorum_met is False


def test_committee_invalid_position_rejected():
    with pytest.raises(ValueError):
        CommitteeVote(member_id="morgan", position="BUY_ALL")


def test_committee_confidence_range_enforced():
    with pytest.raises(ValueError):
        vote("morgan", POSITION_SUPPORT, confidence=1.5)


# ── InvestmentDecision@v1 contract ────────────────────────────────────────────


def _ev(symbol="SCHD", quality=QUALITY_STATE_AVAILABLE):
    return make_ref(
        "holdings_detail",
        {"symbol": symbol, "weight_pct": 14.2},
        source="data/portfolios/state/holdings.json",
        quality_state=quality,
        symbol=symbol,
        deterministic_calculation_version="holding-agg-v1",
    )


def _support_votes():
    return [
        vote("morgan", POSITION_SUPPORT, confidence=0.7),
        vote("steph", POSITION_SUPPORT, confidence=0.8),
        vote("maria", POSITION_SUPPORT, confidence=0.6),
    ]


def test_decision_id_is_deterministic_and_hashed():
    d1 = build_decision(
        parent_run_id="run_1",
        final_position=POSITION_HOLD,
        committee_votes=_support_votes(),
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold SCHD; book weight near fire but defer active.",
        conditions_to_change_view=["weight breaches fire without buffer thesis"],
        actionability=ACTIONABILITY_NEEDS_EVIDENCE,
        symbols=["SCHD"],
    )
    d2 = build_decision(
        parent_run_id="run_1",
        final_position=POSITION_HOLD,
        committee_votes=_support_votes(),
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold SCHD; book weight near fire but defer active.",
        conditions_to_change_view=["weight breaches fire without buffer thesis"],
        actionability=ACTIONABILITY_NEEDS_EVIDENCE,
        symbols=["SCHD"],
    )
    assert d1.decision_id == d2.decision_id
    assert len(d1.decision_id) == 64
    assert d1.schema_version == SCHEMA_VERSION


def test_decision_changes_change_hash():
    d1 = build_decision(
        parent_run_id="run_1", final_position=POSITION_HOLD,
        committee_votes=_support_votes(), evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold SCHD.",
        conditions_to_change_view=["x"], symbols=["SCHD"],
    )
    d2 = build_decision(
        parent_run_id="run_1", final_position=POSITION_TRIM,
        committee_votes=_support_votes(), evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold SCHD.",
        conditions_to_change_view=["x"], symbols=["SCHD"],
    )
    assert d1.decision_id != d2.decision_id


def test_decision_valid_hold():
    d = build_decision(
        parent_run_id="run_1", final_position=POSITION_HOLD,
        committee_votes=_support_votes(), evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold SCHD under defer.",
        conditions_to_change_view=["weight breaches fire"],
        actionability=ACTIONABILITY_NEEDS_EVIDENCE, symbols=["SCHD"],
    )
    assert d.validate() == []
    assert d.is_valid() is True


def test_decision_execution_requires_evidence_gate():
    # BUY with missing required domain → fail
    d = build_decision(
        parent_run_id="run_1", final_position=POSITION_BUY,
        committee_votes=_support_votes(), evidence_refs=[],
        rationale_linked_to_evidence="Buy more SCHD.",
        conditions_to_change_view=["x"],
        required_domains=["holdings_detail", "risk"],
        actionability=ACTIONABILITY_READY, symbols=["SCHD"],
        how_disagreements_were_resolved="",
    )
    errs = d.validate()
    assert any("evidence gate" in e for e in errs)


def test_decision_execution_with_blocking_evidence_fails():
    d = build_decision(
        parent_run_id="run_1", final_position=POSITION_BUY,
        committee_votes=_support_votes(),
        evidence_refs=[_ev(quality=QUALITY_STATE_DATA_UNAVAILABLE)],
        rationale_linked_to_evidence="Buy SCHD.",
        conditions_to_change_view=["x"],
        required_domains=["holdings_detail"],
        actionability=ACTIONABILITY_READY, symbols=["SCHD"],
    )
    errs = d.validate()
    assert any("evidence gate" in e for e in errs)


def test_decision_mixed_marked_ready_is_rejected():
    # Committee MIXED (no super-majority) + READY_FOR_OPERATOR → invalid
    d = build_decision(
        parent_run_id="run_1", final_position=POSITION_HOLD,
        committee_votes=[
            vote("morgan", POSITION_SUPPORT),
            vote("steph", POSITION_OPPOSE),
        ],
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold.",
        conditions_to_change_view=["x"],
        actionability=ACTIONABILITY_READY, symbols=["SCHD"],
        quorum=2,
    )
    errs = d.validate()
    assert any("MIXED" in e for e in errs)


def test_decision_material_disagreement_requires_resolution():
    d = build_decision(
        parent_run_id="run_1", final_position=POSITION_HOLD,
        committee_votes=[
            vote("morgan", POSITION_SUPPORT),
            vote("steph", POSITION_SUPPORT),
            vote("maria", POSITION_SUPPORT),
            vote("ledger", POSITION_OPPOSE),  # dissent
        ],
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold.",
        conditions_to_change_view=["x"],
        actionability=ACTIONABILITY_READY, symbols=["SCHD"],
    )
    errs = d.validate()
    assert any("how_disagreements_were_resolved" in e for e in errs)

    # With a resolution, it passes
    d2 = build_decision(
        parent_run_id="run_1", final_position=POSITION_HOLD,
        committee_votes=[
            vote("morgan", POSITION_SUPPORT),
            vote("steph", POSITION_SUPPORT),
            vote("maria", POSITION_SUPPORT),
            vote("ledger", POSITION_OPPOSE),
        ],
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold.",
        conditions_to_change_view=["x"],
        actionability=ACTIONABILITY_READY, symbols=["SCHD"],
        how_disagreements_were_resolved="Ledger's tax concern is noted; defer already active.",
    )
    assert d2.validate() == []


def test_decision_fact_dump_rejected():
    d = build_decision(
        parent_run_id="run_1", final_position=POSITION_NO_ACTION,
        committee_votes=_support_votes(), evidence_refs=[_ev()],
        rationale_linked_to_evidence="Here is the data dump of everything.",
        conditions_to_change_view=["x"], symbols=["SCHD"],
    )
    assert any("fact dump" in e for e in d.validate())


def test_decision_defense_veto_rejected():
    d = build_decision(
        parent_run_id="run_1", final_position=POSITION_TRIM,
        committee_votes=[
            vote("morgan", POSITION_SUPPORT),
            vote("steph", POSITION_SUPPORT),
            vote("maria", POSITION_SUPPORT),
            vote("guardian", POSITION_OPPOSE),
        ],
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Trim SCHD.",
        conditions_to_change_view=["x"],
        actionability=ACTIONABILITY_READY, symbols=["SCHD"],
    )
    errs = d.validate()
    assert any("defense veto" in e for e in errs)


def test_decision_to_action_payload_idempotency():
    d = build_decision(
        parent_run_id="run_1", final_position=POSITION_HOLD,
        committee_votes=_support_votes(), evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold.",
        conditions_to_change_view=["x"], symbols=["SCHD"],
    )
    p1 = decision_to_action_payload(d)
    p2 = decision_to_action_payload(d)
    assert p1["idempotency_key"] == p2["idempotency_key"] == f"decision:{d.decision_id}"
    assert p1["cio_action_id"] == p2["cio_action_id"]
    assert p1["operator_decision_required"] is False  # HOLD, not READY → no operator gate


# ── Pipeline: one decision → one action → one notification (idempotent) ───────


class _FakeActionLedger:
    def __init__(self):
        self.actions = {}
        self.created = []

    def create_action(self, payload, actor_id="alex"):
        key = payload["idempotency_key"]
        if key in self.actions:
            return self.actions[key]
        event = {"event_id": f"ev_{len(self.created)}", "payload": payload}
        self.actions[key] = event
        self.created.append(event)
        return event


class _FakeOutbox:
    def __init__(self):
        self.notes = {}
        self.created = []

    def enqueue(self, note, actor_id="alex"):
        key = note["idempotency_key"]
        if key in self.notes:
            return self.notes[key]
        event = {"event_id": f"n_{len(self.created)}", "payload": note}
        self.notes[key] = event
        self.created.append(event)
        return event


def _ready_decision():
    return build_decision(
        parent_run_id="run_1", final_position=POSITION_HOLD,
        committee_votes=[
            vote("morgan", POSITION_SUPPORT),
            vote("steph", POSITION_SUPPORT),
            vote("maria", POSITION_SUPPORT),
        ],
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold SCHD; defer active, book near fire.",
        conditions_to_change_view=["weight breaches fire"],
        actionability=ACTIONABILITY_READY, symbols=["SCHD"],
    )


def test_pipeline_one_decision_one_action_one_notification():
    from scripts.lib.cio_decision_pipeline import publish_decision

    ledger = _FakeActionLedger()
    outbox = _FakeOutbox()
    d = _ready_decision()

    r1 = publish_decision(d, action_ledger=ledger, notification_outbox=outbox)
    assert r1["ok"] is True
    assert len(ledger.created) == 1
    assert len(outbox.created) == 1

    # Re-publishing the same decision is idempotent — no duplicates.
    r2 = publish_decision(d, action_ledger=ledger, notification_outbox=outbox)
    assert r2["ok"] is True
    assert len(ledger.created) == 1
    assert len(outbox.created) == 1


def test_pipeline_non_ready_decision_no_notification():
    from scripts.lib.cio_decision_pipeline import publish_decision

    ledger = _FakeActionLedger()
    outbox = _FakeOutbox()
    d = build_decision(
        parent_run_id="run_1", final_position=POSITION_HOLD,
        committee_votes=_support_votes(), evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold.",
        conditions_to_change_view=["x"],
        actionability=ACTIONABILITY_NEEDS_EVIDENCE, symbols=["SCHD"],
    )
    r = publish_decision(d, action_ledger=ledger, notification_outbox=outbox)
    assert r["ok"] is True
    assert len(ledger.created) == 1
    assert len(outbox.created) == 0  # needs evidence → no operator notify


def test_pipeline_invalid_decision_publishes_nothing():
    from scripts.lib.cio_decision_pipeline import publish_decision

    ledger = _FakeActionLedger()
    outbox = _FakeOutbox()
    d = build_decision(
        parent_run_id="", final_position=POSITION_HOLD,  # missing parent_run_id
        committee_votes=_support_votes(), evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold.",
        conditions_to_change_view=["x"], symbols=["SCHD"],
    )
    r = publish_decision(d, action_ledger=ledger, notification_outbox=outbox)
    assert r["ok"] is False
    assert r["action_event"] is None
    assert r["notification_event"] is None
    assert len(ledger.created) == 0
    assert len(outbox.created) == 0


def test_pipeline_real_ledger_roundtrip(tmp_path):
    """End-to-end: decision → real CIOActionLedger (temp path), action is durable."""
    from scripts.lib.cio_action_ledger import CIOActionLedger
    from scripts.lib.cio_decision_pipeline import publish_decision

    ledger = CIOActionLedger(event_store_path=tmp_path / "actions.jsonl")
    d = _ready_decision()
    r = publish_decision(d, action_ledger=ledger, notification_outbox=_FakeOutbox())
    assert r["ok"] is True
    aid = r["action_event"]["payload"]["cio_action_id"]
    action = ledger.get_action(aid)
    assert action is not None
    assert action["cio_artifact_id"] == d.decision_id
    assert action["origin_run_id"] == "run_1"
    assert action["current_status"] == "OPEN"
    assert action["affected_symbols"] == ["SCHD"]
    # The envelope carries READ_ONLY_ADVISORY authority; the replayed action is advisory-only.
    assert r["action_event"]["authority"] in ("advisory", "READ_ONLY_ADVISORY")


def test_committee_office_map_display():
    assert CommitteeVote(member_id="guardian", position=POSITION_OPPOSE).office == "Independent Risk Officer"
    assert CommitteeVote(member_id="alex", position=POSITION_SUPPORT).office == "Chief Investment Officer (Chair)"


def test_vote_from_specialist_advisory_dataclass():
    from scripts.lib.cio_advisory_schema import SpecialistAdvisory, SpecialistAdvisoryPosition
    adv = SpecialistAdvisory(
        specialist_id="steph",
        parent_run_id="run_1",
        run_purpose="allocation review",
        position=SpecialistAdvisoryPosition.SUPPORT,
        recommendation="Add to defensive sleeve",
        rationale="Drift toward defensive target.",
        evidence_sources=[],
        evidence_summary="holdings drift",
        confidence=0.8,
        confidence_basis="PARTIAL_EVIDENCE",
        material_risks=[],
        alternatives_considered=[],
        conditions_to_change_view=[],
        evidence_gaps=[],
        deficiencies_acknowledged=[],
    )
    from scripts.lib.cio_committee import vote_from_specialist_advisory
    v = vote_from_specialist_advisory(adv)
    assert v.member_id == "steph"
    assert v.position == "SUPPORT"
    assert v.confidence == 0.8


def test_vote_from_specialist_advisory_dict():
    from scripts.lib.cio_committee import vote_from_specialist_advisory
    v = vote_from_specialist_advisory(
        {"specialist_id": "maria", "position": "OPPOSE", "confidence": 0.4, "rationale": "overvalued"}
    )
    assert v.member_id == "maria"
    assert v.position == "OPPOSE"
    assert v.confidence == 0.4
