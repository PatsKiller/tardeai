"""Checkpoint 4b — committee → InvestmentDecision@v1 synthesis wiring canaries.

Proves the deterministic bridge that CIORunWorker can drop in as `synthesis_fn`:
specialist advisories → committee votes → chair reconciliation → decision →
recommendation rows. Zero provider calls, zero live side effects.
"""
from __future__ import annotations

import pytest

from scripts.lib.cio_advisory_schema import (
    SpecialistAdvisory,
    SpecialistAdvisoryPosition,
    EvidenceSource,
)
from scripts.lib.cio_committee import POSITION_SUPPORT, POSITION_OPPOSE
from scripts.lib.cio_committee_synthesis import (
    reconcile_committee,
    synthesize_decision,
    recommendations_from_decision,
    build_committee_synthesis_fn,
)
from scripts.lib.cio_committee import convene, vote
from scripts.lib.cio_investment_decision import (
    POSITION_BUY,
    POSITION_HOLD,
    POSITION_NO_ACTION,
    POSITION_DEFER,
    ACTIONABILITY_READY,
    ACTIONABILITY_NEEDS_EVIDENCE,
    ACTIONABILITY_CONFLICT,
)
from scripts.lib.cio_evidence_ref import make_ref


def _adv(specialist_id="steph", position=SpecialistAdvisoryPosition.SUPPORT, confidence=0.7):
    return SpecialistAdvisory(
        specialist_id=specialist_id,
        parent_run_id="run_1",
        run_purpose="allocation review",
        position=position,
        recommendation="Adjust allocation.",
        rationale="Drift toward target.",
        evidence_sources=[EvidenceSource(source_id="ds-1", domain="portfolio", quality_state="AVAILABLE")],
        evidence_summary="ok",
        confidence=confidence,
        confidence_basis="PARTIAL_EVIDENCE",
        material_risks=[],
        alternatives_considered=[],
        conditions_to_change_view=[],
        evidence_gaps=[],
        deficiencies_acknowledged=[],
    )


def _ev(symbol="SCHD"):
    return make_ref(
        "holdings_detail",
        {"symbol": symbol, "weight_pct": 14.2},
        source="data/portfolios/state/holdings.json",
        quality_state="AVAILABLE",
        symbol=symbol,
        deterministic_calculation_version="holding-agg-v1",
    )


# ── reconcile_committee ───────────────────────────────────────────────────────


def test_reconcile_support_stands():
    r = convene([vote("steph", POSITION_SUPPORT), vote("morgan", POSITION_SUPPORT), vote("maria", POSITION_SUPPORT)])
    out = reconcile_committee(POSITION_HOLD, r)
    assert out["final_position"] == POSITION_HOLD
    assert out["actionability"] == ACTIONABILITY_READY
    assert out["overridden"] is False


def test_reconcile_defense_veto_downgrades_execution():
    r = convene([
        vote("steph", POSITION_SUPPORT), vote("morgan", POSITION_SUPPORT),
        vote("maria", POSITION_SUPPORT), vote("guardian", POSITION_OPPOSE),
    ])
    out = reconcile_committee(POSITION_BUY, r)
    assert out["final_position"] == POSITION_HOLD
    assert out["actionability"] == ACTIONABILITY_CONFLICT
    assert out["overridden"] is True


def test_reconcile_blocked_quorum_defers():
    r = convene([vote("steph", POSITION_SUPPORT)], quorum=3)
    out = reconcile_committee(POSITION_BUY, r)
    assert out["final_position"] == POSITION_DEFER
    assert out["actionability"] == ACTIONABILITY_NEEDS_EVIDENCE


def test_reconcile_mixed_requires_resolution():
    r = convene([vote("steph", POSITION_SUPPORT), vote("ledger", POSITION_OPPOSE)], quorum=2)
    out = reconcile_committee(POSITION_HOLD, r)
    assert out["actionability"] == ACTIONABILITY_CONFLICT

    out2 = reconcile_committee(POSITION_HOLD, r, how_disagreements_were_resolved="chair override documented")
    assert out2["actionability"] == ACTIONABILITY_READY
    assert out2["final_position"] == POSITION_HOLD


def test_reconcile_oppose_downgrades_execution():
    r = convene([
        vote("steph", POSITION_OPPOSE), vote("morgan", POSITION_OPPOSE), vote("maria", POSITION_OPPOSE),
    ])
    out = reconcile_committee(POSITION_BUY, r)
    assert out["final_position"] == POSITION_HOLD
    assert out["actionability"] == ACTIONABILITY_NEEDS_EVIDENCE


def test_reconcile_neutral_defers_execution():
    r = convene([vote("steph", "NEUTRAL"), vote("morgan", "NEUTRAL"), vote("maria", "NEUTRAL")])
    out = reconcile_committee(POSITION_BUY, r)
    assert out["final_position"] == POSITION_DEFER
    assert out["actionability"] == ACTIONABILITY_NEEDS_EVIDENCE


def test_reconcile_invalid_intended_position_rejected():
    r = convene([vote("steph", POSITION_SUPPORT), vote("morgan", POSITION_SUPPORT), vote("maria", POSITION_SUPPORT)])
    with pytest.raises(ValueError):
        reconcile_committee("YOLO", r)


# ── synthesize_decision ───────────────────────────────────────────────────────


def test_synthesize_decision_valid_hold():
    d = synthesize_decision(
        parent_run_id="run_1",
        intended_position=POSITION_HOLD,
        specialist_advisories=[
            _adv("steph"), _adv("morgan"), _adv("maria"),
        ],
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold SCHD; defer active.",
        conditions_to_change_view=["weight breaches fire"],
        symbols=["SCHD"],
    )
    assert d.validate() == []
    assert d.final_position == POSITION_HOLD
    assert d.committee.consensus == "UNANIMOUS_SUPPORT"
    assert d.actionability == ACTIONABILITY_READY


def test_synthesize_decision_defense_veto_is_blocked():
    d = synthesize_decision(
        parent_run_id="run_1",
        intended_position=POSITION_BUY,
        specialist_advisories=[
            _adv("steph"), _adv("morgan"), _adv("maria"),
            _adv("guardian", SpecialistAdvisoryPosition.OPPOSE),
        ],
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Buy SCHD.",
        conditions_to_change_view=["x"],
        required_domains=["holdings_detail", "risk"],
        symbols=["SCHD"],
    )
    # Reconcile downgrades to HOLD, but the committee is still BLOCKED_DEFENSE
    # so the decision is invalid (must escalate to operator, not finalize).
    assert d.final_position == POSITION_HOLD
    assert d.committee.consensus == "BLOCKED_DEFENSE"
    assert any("defense veto" in e for e in d.validate())


def test_recommendations_from_decision_shape():
    d = synthesize_decision(
        parent_run_id="run_1",
        intended_position=POSITION_HOLD,
        specialist_advisories=[_adv("steph"), _adv("morgan"), _adv("maria")],
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold SCHD.",
        conditions_to_change_view=["x"],
        symbols=["SCHD"],
    )
    rows = recommendations_from_decision(d)
    assert len(rows) == 1
    row = rows[0]
    assert row["action"] == "HOLD"
    assert row["action_type"] == "HOLD"
    assert row["cio_decision_id"] == d.decision_id
    assert row["title"]
    assert row["rationale"] == "Hold SCHD."


def test_recommendations_defer_maps_to_no_action():
    d = synthesize_decision(
        parent_run_id="run_1",
        intended_position=POSITION_BUY,
        specialist_advisories=[_adv("steph", SpecialistAdvisoryPosition.DEFER)],
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Defer.",
        conditions_to_change_view=["x"],
        symbols=["SCHD"],
        quorum=2,
    )
    rows = recommendations_from_decision(d)
    assert rows[0]["action_type"] == "NO_ACTION"


# ── build_committee_synthesis_fn (CIORunWorker-compatible) ────────────────────


def test_build_synthesis_fn_returns_decision_and_recommendations():
    fn = build_committee_synthesis_fn(intended_position=POSITION_HOLD)
    out = fn(
        run={"run_id": "run_1", "symbols": ["SCHD"], "conditions_to_change_view": ["x"]},
        snapshot={"summary": "portfolio snapshot"},
        specialist_result={"artifacts": [_adv("steph"), _adv("morgan"), _adv("maria")]},
        hermes_result={},
    )
    assert out["decision_id"]
    assert out["final_position"] == POSITION_HOLD
    assert out["recommendations"]
    assert out["recommendations"][0]["cio_decision_id"] == out["decision_id"]


def test_build_synthesis_fn_defense_veto_produces_no_recommendations():
    fn = build_committee_synthesis_fn(intended_position=POSITION_BUY)
    out = fn(
        run={
            "run_id": "run_1",
            "symbols": ["SCHD"],
            "conditions_to_change_view": ["x"],
            "required_domains": ["holdings_detail"],
        },
        snapshot={"summary": "portfolio snapshot"},
        specialist_result={"artifacts": [
            _adv("steph"), _adv("morgan"), _adv("maria"),
            _adv("guardian", SpecialistAdvisoryPosition.OPPOSE),
        ]},
        hermes_result={},
    )
    assert out["blocked"] is True
    assert out["block_reason_code"] == "DECISION_GATE"
    assert out["recommendations"] == []
    assert "defense veto" in out["summary"]


def test_build_synthesis_fn_invalid_advisory_fails_closed():
    fn = build_committee_synthesis_fn(intended_position=POSITION_HOLD)
    with pytest.raises(ValueError):
        fn(
            run={"run_id": "run_1"},
            snapshot={"summary": "snapshot"},
            specialist_result={"artifacts": [{"specialist_id": "", "position": ""}]},
            hermes_result={},
        )


def test_build_synthesis_fn_reads_evidence_refs_from_snapshot():
    fn = build_committee_synthesis_fn(intended_position=POSITION_HOLD)
    out = fn(
        run={"run_id": "run_1", "symbols": ["SCHD"], "conditions_to_change_view": ["x"]},
        snapshot={"summary": "snapshot", "evidence_refs": [_ev()]},
        specialist_result={"artifacts": [_adv("steph"), _adv("morgan"), _adv("maria")]},
        hermes_result={},
    )
    d = out["decision"]
    assert d["evidence_refs"]
    assert d["evidence_refs"][0]["domain"] == "holdings_detail"


# ── End-to-end CIORunWorker integration (committee synthesis_fn) ──────────────


def test_worker_execute_end_to_end_committee_synthesis(tmp_path):
    """CIORunWorker.execute() with a committee synthesis_fn produces actions."""
    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_run_worker import CIORunWorker
    from scripts.lib.cio_domain_registry import CIODomainRegistry

    store = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    store.initialize()
    created = store.create_run(trigger_type="SCHEDULED_DAILY", required_domains=[])
    run_id = created["payload"]["run_id"]

    all_domains = CIODomainRegistry.load().domain_ids
    force_snapshot = {
        "snapshot_id": "snap-1",
        "content_hash": "abc123",
        "summary": "portfolio snapshot",
        "domain_states": {d: "AVAILABLE" for d in all_domains},
    }

    class FakeLedger:
        def __init__(self):
            self.actions = []

        def create_action(self, action, actor_id=None, actor_type=None, authority=None):
            self.actions.append(action)
            return {"payload": {"cio_action_id": action["cio_action_id"]}}

    class FakeOutbox:
        def __init__(self):
            self.notes = []

        def enqueue(self, note, actor_id=None):
            self.notes.append(note)
            return {"notification_id": note["notification_id"]}

    ledger = FakeLedger()
    outbox = FakeOutbox()

    fn = build_committee_synthesis_fn(
        intended_position=POSITION_HOLD,
        evidence_refs=[_ev()],
        rationale_linked_to_evidence="Hold SCHD; defer active.",
        conditions_to_change_view=["weight breaches fire without buffer thesis"],
        symbols=["SCHD"],
    )
    # The worker's _route_specialists hardcodes artifacts:[] (specialist-artifact
    # resolution is the remaining live gap). Inject the 3 SUPPORT advisories here
    # to prove the full worker→committee→decision→action path when artifacts exist.
    base_fn = fn

    def inject_fn(run, snapshot, specialist_result, hermes_result):
        specialist_result = dict(specialist_result)
        specialist_result["artifacts"] = [_adv("steph"), _adv("morgan"), _adv("maria")]
        return base_fn(run, snapshot, specialist_result, hermes_result)

    worker = CIORunWorker(
        run_store=store,
        action_ledger=ledger,
        notification_outbox=outbox,
        synthesis_fn=inject_fn,
    )

    result = worker.execute(run_id, force_health_state="HEALTHY", force_snapshot=force_snapshot)

    assert result["status"] == "COMPLETED", result
    # A HOLD recommendation should pass post-synthesis evidence validation.
    assert len(ledger.actions) >= 1
    hold_actions = [a for a in ledger.actions if a.get("action_type") == "HOLD"]
    assert hold_actions
    # A notification was enqueued for the action.
    assert len(outbox.notes) >= 1


def test_worker_execute_defense_veto_creates_status_not_execution(tmp_path):
    """A defense-vetoed run produces a STATUS action, never an execution action."""
    from scripts.lib.cio_run import CIORunStore
    from scripts.lib.cio_run_worker import CIORunWorker
    from scripts.lib.cio_domain_registry import CIODomainRegistry

    store = CIORunStore(store_path=str(tmp_path / "runs.jsonl"))
    store.initialize()
    created = store.create_run(trigger_type="SCHEDULED_DAILY", required_domains=[])
    run_id = created["payload"]["run_id"]

    all_domains = CIODomainRegistry.load().domain_ids
    force_snapshot = {
        "snapshot_id": "snap-1",
        "content_hash": "abc123",
        "summary": "portfolio snapshot",
        "domain_states": {d: "AVAILABLE" for d in all_domains},
    }

    class FakeLedger:
        def __init__(self):
            self.actions = []

        def create_action(self, action, actor_id=None, actor_type=None, authority=None):
            self.actions.append(action)
            return {"payload": {"cio_action_id": action["cio_action_id"]}}

    class FakeOutbox:
        def __init__(self):
            self.notes = []

        def enqueue(self, note, actor_id=None):
            self.notes.append(note)
            return {"notification_id": note["notification_id"]}

    ledger = FakeLedger()
    outbox = FakeOutbox()

    fn = build_committee_synthesis_fn(
        intended_position=POSITION_BUY,
        evidence_refs=[_ev()],
    )
    # Inject a guardian OPPOSE via a custom intended-path that also injects artifacts.
    # We wrap fn so the specialist_result carries the guardian dissent.
    base_fn = fn

    def veto_fn(run, snapshot, specialist_result, hermes_result):
        specialist_result = dict(specialist_result)
        specialist_result["artifacts"] = [
            _adv("steph"), _adv("morgan"), _adv("maria"),
            _adv("guardian", SpecialistAdvisoryPosition.OPPOSE),
        ]
        return base_fn(run, snapshot, specialist_result, hermes_result)

    worker = CIORunWorker(
        run_store=store,
        action_ledger=ledger,
        notification_outbox=outbox,
        synthesis_fn=veto_fn,
    )

    result = worker.execute(run_id, force_health_state="HEALTHY", force_snapshot=force_snapshot)
    assert result["status"] == "COMPLETED", result

    execution_types = {"BUY", "SELL", "SELL_TAXABLE", "TRIM"}
    execution_actions = [a for a in ledger.actions if a.get("action_type") in execution_types]
    assert execution_actions == []
    # The worker falls back to a STATUS action (no recommendations).
    status_actions = [a for a in ledger.actions if a.get("action_type") == "STATUS"]
    assert status_actions
