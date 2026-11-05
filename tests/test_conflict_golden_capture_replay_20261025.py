"""The golden capture must store the facts its own replay adapter consumes (D52 triage, PR 2123).

scripts/conflict_golden_capture.py stores each subject's ``truth`` for tests/test_conflict_golden_replay_20261025.py
to replay through scripts/lib/conflicts/adapters.security_inputs_from_truth. That adapter reads
``saved_diagnostics`` through producers.ownership_facts to freeze evaluation on unresolved ownership (R12). The
builder used to drop the field through ``TRUTH_FIELDS``, so the stored golden evidence replayed a DIFFERENT conflict
truth than the decision it captured: the live run stopped at the ownership DATA_ERROR, the replay evaluated past it.

Every input here is synthetic (a made-up symbol, a GUID that belongs to no registry, test-only accounts and dates);
the test builds through the real builder and the real adapter, never a re-implementation of either.
"""
import json
from datetime import datetime, timezone

import pytest

import scripts.conflict_golden_capture as capture
from scripts.lib.conflicts.adapters import evaluate_inputs, security_inputs_from_truth
from scripts.lib.cio_truth import security_inputs_for
from scripts.lib.data_broker.cio_prospect import get_prospects
from scripts.lib.ips_policy import policy_for_security

NOW = datetime(2026, 10, 25, 18, 30, tzinfo=timezone.utc)
GUID = "0d4e6f2a-1b3c-4d5e-8f90-123456789abc"      # present only in this test's temporary registry
SYMBOL = "SYNTHX1"                                 # no such listed security; never a live symbol
CAPTURED_AT = "2026-10-25T18:30:00+00:00"
CONFLICTS = [{
    "field": "held",
    "conflict_id": "synthetic-conflict-1",
    "resolved": False,
    "note": "synthetic unresolved ownership diagnostic",
    "values": [
        {"source": "positions", "value": True, "at": "2026-10-23T20:00:00+00:00"},
        {"source": "fills", "value": False, "at": "2026-10-24T15:00:00+00:00"},
    ],
}]


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture()
def capture_inputs(tmp_path):
    """Synthetic source files plus the truth the LIVE resolver consumes at decision time."""
    state_root = tmp_path / "state"
    _write(state_root / "data/runtime/identity_registry.json", {
        "entities": {GUID: {"subject_guid": GUID, "security_guid": GUID, "entity_type": "SECURITY",
                            "identity_status": "CONFIRMED", "active": True}},
        "by_symbol": {SYMBOL: GUID}})
    watch = _write(tmp_path / "watch.json", {
        "generated_at": "2026-10-25T18:20:00+00:00",
        "items": [{"card": {"symbol": SYMBOL, "security_guid": GUID, "trade_ai_state": "AVOID",
                            "trade_ai_as_of": "2026-10-24T20:00:00+00:00"}}]})
    holdings = _write(tmp_path / "holdings.json", {
        "as_of": "2026-10-23", "total_value": 10000.0,
        "holdings": [{"account_id": "account_a", "symbol": SYMBOL, "quantity": 10}]})
    risk = _write(tmp_path / "risk.json", {"positions": [{
        "security_guid": GUID, "symbol": SYMBOL, "account_id": "account_a", "market_value": 500.0,
        "stop_state": "ACTIVE", "stop_captured_at": "2026-10-24T20:00:00+00:00"}]})
    shadow = _write(tmp_path / "shadow.json", {"as_of": "2026-10-25T13:53:55+00:00", "prospects": [{
        "security_guid": GUID, "symbol": SYMBOL, "stance": "ADD", "conviction": 80,
        "as_of": "2026-10-25T13:00:00+00:00", "revision": 1, "conflicts": CONFLICTS}]})
    reentry = _write(tmp_path / "desk.json", {"rows": []})

    held_doc = json.loads(holdings.read_text(encoding="utf-8"))
    risk_doc = json.loads(risk.read_text(encoding="utf-8"))
    document = {"portfolio": {"holdings": held_doc.get("holdings") or [], "total_usd": held_doc.get("total_value")},
                "positions": {"rows": risk_doc.get("positions") or []}}
    projection = get_prospects(shadow_base=shadow, now=NOW,
                               status={"live": False, "reasons": ["synthetic capture fixture"]})
    live_truth = security_inputs_for(GUID, document=document, projection=projection, now=NOW)
    live_truth["symbol"] = SYMBOL
    live_truth.setdefault("context", {})["concentration_policy"] = policy_for_security(GUID, document=document)
    doc = capture.build(watch_pages=[watch], holdings=holdings, risk=risk, cio_shadow=shadow,
                        reentry_snapshot=reentry, state_root=state_root, captured_at=CAPTURED_AT)
    (subject,) = doc["subjects"]
    return {"live": live_truth, "captured": subject}


def _read_outcome(truth, card):
    """What the adapter derives from one truth: the ownership facts and the engine's finding labels."""
    bundle = security_inputs_from_truth(truth, card=card)
    ownership = [item for item in bundle.inputs if item.metadata.get("ownership")]
    labels = sorted(f"{finding.kind}:{finding.rule}" for finding in evaluate_inputs(bundle, now=NOW))
    return ownership, labels


def test_capture_stores_the_diagnostics_the_adapter_reads(capture_inputs):
    live, subject = capture_inputs["live"], capture_inputs["captured"]
    assert live["saved_diagnostics"], "the synthetic CIO record must expose an unresolved ownership diagnostic"
    # The stored truth carries exactly the diagnostics the CIO record already holds — no more, no less.
    assert subject["truth"]["saved_diagnostics"] == live["saved_diagnostics"]
    # And the stored truth is still only the set the replay adapter consumes.
    assert set(subject["truth"]) == set(capture.TRUTH_FIELDS)


def test_replay_of_the_capture_reproduces_the_live_ownership_decision(capture_inputs):
    live, subject = capture_inputs["live"], capture_inputs["captured"]
    live_ownership, live_labels = _read_outcome(live, subject["card"])
    replay_ownership, replay_labels = _read_outcome(subject["truth"], subject["card"])
    assert live_ownership, "the live decision must freeze on the unresolved ownership diagnostic"
    assert [item.detail for item in replay_ownership] == [item.detail for item in live_ownership]
    assert live_labels == ["DATA_ERROR:R12"]
    assert replay_labels == live_labels, "the stored capture must replay the same conflict truth it captured"
