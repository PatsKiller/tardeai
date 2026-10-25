from datetime import datetime, timedelta, timezone
import json

import pytest

from scripts.lib.conflicts.engine import Finding, Input, Subject, evaluate
from scripts.lib.conflicts.ledger import ConflictLedger, DECISION_SCHEMA, list_records
from scripts.lib.conflicts.profiles import SecurityStanceProfile

NOW = datetime(2026, 10, 24, 23, tzinfo=timezone.utc)
SUBJECT = Subject("security", "guid", "SYM", {"held": False})
KEY = "security:guid:U7:desk"


def conflict(**kwargs):
    return Finding(**{"kind": "CONFLICT", "rule": "U7", "summary": "CIO WATCH vs desk ADD", "clears_when": "CIO decides",
        "key": KEY, "sides": [{"source": "curator", "value": "WATCH", "as_of": NOW.isoformat(), "account": None},
                             {"source": "desk", "value": "ADD", "as_of": NOW.isoformat(), "account": None}], **kwargs})


def ledger(tmp_path, writes=None):
    writes = writes if writes is not None else []
    return ConflictLedger(tmp_path, memory_writer=lambda event: writes.append(event["event_id"]) or True)


def decision(**kwargs):
    return {"schema": DECISION_SCHEMA, "actor_kind": "cio", "actor": "cio", "reason": "evidence reviewed",
            "chosen_side": "WATCH", "evidence_refs": ["thesis:v2"], "expires_at": (NOW + timedelta(days=7)).isoformat(), **kwargs}


def test_dry_run_creates_no_directory_ledger_or_memory(tmp_path):
    root = tmp_path / "absent"
    st = ledger(root)
    assert st.reconcile(SUBJECT, [conflict()], at=NOW)
    assert not root.exists()


def test_poll_dedupes_and_memory_has_one_delivery_per_state_change(tmp_path):
    writes = []
    st = ledger(tmp_path, writes)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    for _ in range(3):
        assert st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True) == []
    assert len(st.events()) == len(writes) == 1
    record = list_records(tmp_path)["records"][0]
    assert record["schema"] == "ConflictRecord@v1" and record["state"] == "OPEN"
    st.transition(KEY, "review_queued", at=NOW, review_request_id="actual-fixture-request", apply=True)
    assert len(writes) == 2 and st.records()[KEY]["state"] == "UNDER_REVIEW"


def test_decision_does_not_clear_until_actual_sources_agree(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    st.transition(KEY, "decided", at=NOW, decision=decision(), apply=True)
    assert st.records()[KEY]["state"] == "DECIDED"
    agreed = conflict(kind="AGREEMENT", rule="R6", key="security:guid:R6:desk")
    st.reconcile(SUBJECT, [agreed], at=NOW, observed_sources=["curator", "desk"], apply=True)
    assert st.records()[KEY]["state"] == "CLEARED"
    st.reconcile(SUBJECT, [conflict()], at=NOW + timedelta(hours=1), apply=True)
    assert st.records()[KEY]["state"] == "REOPENED"


def test_hysteresis_observation_is_not_a_clear(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    st.reconcile(SUBJECT, [conflict(kind="AGREEMENT", rule="R15")], at=NOW, apply=True)
    assert st.records()[KEY]["state"] == "OPEN"


def test_missing_producer_or_failed_opinion_never_clears(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    st.reconcile(SUBJECT, [], at=NOW, apply=True)
    assert st.records()[KEY]["state"] == "OPEN"


def test_never_auto_and_fact_safety_not_decidable(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict(kind="DATA_ERROR", rule="R12", never_auto=True, tier=1)], at=NOW, apply=True)
    with pytest.raises(ValueError, match="source repair"):
        st.transition(KEY, "decided", at=NOW, decision=decision(actor_kind="operator"), apply=True)
    st.reconcile(SUBJECT, [conflict(kind="AGREEMENT", rule="R6", key="security:guid:R6:desk")], at=NOW, apply=True)
    assert st.records()[KEY]["state"] == "OPEN"


@pytest.mark.parametrize("patch", [{"reason": ""}, {"evidence_refs": []}, {"actor_kind": "agent"},
    {"expires_at": NOW.isoformat()}, {"expires_at": "2026-10-25"}, {"chosen_side": "UNMAPPED"}])
def test_incomplete_or_expired_decision_refuses_before_append(tmp_path, patch):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    before = st.path.read_bytes()
    with pytest.raises(ValueError):
        st.transition(KEY, "decided", at=NOW, decision=decision(**patch), apply=True)
    assert st.path.read_bytes() == before


def test_stale_revision_and_corrupt_history_fail_closed(tmp_path):
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    with pytest.raises(ValueError, match="stale"):
        st.transition(KEY, "decided", at=NOW, expected_revision=99, decision=decision(), apply=True)
    with st.path.open("a") as f:
        f.write("truncated")
    with pytest.raises(ValueError, match="invalid conflict ledger"):
        st.records()


def test_pending_memory_is_durable_and_can_be_recovered_without_duplicate_event(tmp_path):
    st = ConflictLedger(tmp_path)
    with pytest.raises(RuntimeError, match="cio_memory pending"):
        st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    assert len(st.events()) == 1
    recovered = ledger(tmp_path)
    recovered.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    assert len(recovered.events()) == 1


def test_queue_requires_actual_request_receipt_and_pg_is_explicitly_gated(tmp_path):
    from unittest.mock import Mock
    pg = Mock(return_value=True)
    st = ConflictLedger(tmp_path, memory_writer=lambda event: True, pg_writer=pg)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    pg.assert_not_called()
    with pytest.raises(ValueError, match="request receipt"):
        st.transition(KEY, "review_queued", at=NOW, apply=True)


def test_cio_promotion_requires_current_decision_and_missing_ledger_is_a_gap(tmp_path):
    from scripts.lib.conflicts.cio import context_for
    assert context_for(tmp_path, "guid", now=NOW)["gap"]
    st = ledger(tmp_path)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    assert context_for(tmp_path, "guid", now=NOW)["blocks_promotion"]
    st.transition(KEY, "decided", at=NOW, decision=decision(), apply=True)
    assert not context_for(tmp_path, "guid", now=NOW)["blocks_promotion"]
    assert context_for(tmp_path, "guid", now=NOW + timedelta(days=8))["blocks_promotion"]


def test_enabled_pg_mirror_uses_parameterized_idempotent_insert_and_acks_once(tmp_path):
    from unittest.mock import Mock
    from scripts.lib.conflicts.ledger import postgres_sink
    connection = Mock()
    factory = Mock(return_value=connection)
    st = ConflictLedger(tmp_path, memory_writer=lambda event: True, pg_writer=postgres_sink(factory), pg_enabled=True)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    assert factory.call_count == 1
    sql, params = connection.cursor.return_value.execute.call_args.args
    assert "ON CONFLICT(event_id) DO NOTHING" in sql
    assert params[0] == st.events()[0]["event_id"] and json.loads(params[-1])["schema"] == "ConflictEvent@v1"
    connection.commit.assert_called_once()
    connection.close.assert_called_once()


def test_pg_mirror_failure_keeps_event_durable_for_retry(tmp_path):
    from unittest.mock import Mock
    from scripts.lib.conflicts.ledger import postgres_sink
    connection = Mock()
    connection.cursor.return_value.execute.side_effect = RuntimeError("fixture failure")
    st = ConflictLedger(tmp_path, memory_writer=lambda event: True,
                        pg_writer=postgres_sink(lambda: connection), pg_enabled=True)
    with pytest.raises(RuntimeError, match="pg pending"):
        st.reconcile(SUBJECT, [conflict()], at=NOW, apply=True)
    assert len(st.events()) == 1
    connection.rollback.assert_called_once()
