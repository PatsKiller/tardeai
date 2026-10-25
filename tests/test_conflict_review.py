from datetime import timedelta

from scripts.lib.conflicts.review import complete_review
from tests.test_conflict_ledger import NOW, SUBJECT, KEY, conflict, ledger


def kwargs(saved, update):
    return dict(request_id="fixture-review", canonical={"security_guid": "guid", "stance": "WATCH", "as_of": NOW.isoformat()},
                reason="CIO considered both sides", evidence_refs=["thesis:v2"], producer_update=update,
                producer_readback=lambda: saved, at=NOW, expires_at=NOW + timedelta(days=7))


def test_review_completion_requires_decision_and_superseded_input_readback(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    saved = {}
    preview = complete_review(st, KEY, **kwargs(saved, lambda patch: (_ for _ in ()).throw(AssertionError("dry run"))))
    assert not preview["applied"] and len(st.events()) == 1
    failed = complete_review(st, KEY, **kwargs(saved, lambda patch: False), apply=True)
    assert not failed["resolution_proven"] and st.records()[KEY]["state"] == "DECIDED"
    result = complete_review(st, KEY, **kwargs(saved, lambda patch: saved.update(patch) or True), apply=True)
    assert result["resolution_proven"] and not result["cleared"]
    assert saved["verdict"] == "WATCH" and saved["conflict_key"] == KEY
    agreed = conflict(kind="AGREEMENT", rule="R6", key="security:guid:R6:desk")
    st.reconcile(SUBJECT, [agreed], at=NOW, apply=True)
    assert st.records()[KEY]["state"] == "CLEARED"
    assert st.records()[KEY]["decision"]["request_id"] == "fixture-review"


def test_queue_transition_requires_persisted_confirmed_identity(tmp_path):
    from scripts.lib.conflicts.review import record_review_queued
    import pytest
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    with pytest.raises(ValueError, match="identity/lineage"):
        record_review_queued(st, KEY, request_id="request", queue_readback=lambda _: {}, at=NOW, apply=True)
    record_review_queued(st, KEY, request_id="request", queue_readback=lambda _: {"request_id": "request",
        "security_guid": "guid", "symbol": "SYM", "identity_status": "CONFIRMED"}, at=NOW, apply=True)
    assert st.records()[KEY]["state"] == "UNDER_REVIEW"
    assert st.events()[-1]["request_id"] == "request"
