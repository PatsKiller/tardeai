from datetime import datetime, timedelta, timezone
import pytest
from scripts.settle_agent_commitments import SettlementLedger, validate_commitment

NOW = datetime(2026, 9, 7, tzinfo=timezone.utc)

def commitment(**over):
    d = {"schema_version":"Commitment@v1", "source_sha":"a"*40,
         "produced_at":NOW.isoformat(), "correlation_id":"c", "idempotency_key":"i",
         "parent_kind":"wake", "retention_class":"evidence_2y", "lifecycle_state":"OPEN",
         "provenance":{"producer":"lane-a"}, "commitment_id":"cm1", "wake_id":"w1",
         "subject_guid":"s1", "commitment_kind":"direction", "normalized_claim":"up",
         "observation_window_start":NOW.isoformat(), "observation_window_end":(NOW+timedelta(days=1)).isoformat(),
         "population":"organic", "horizon":"1d"}
    d.update(over); return d

def obs(value="SUCCESS", when=NOW+timedelta(hours=12), oid="o1"):
    return {"commitment_id":"cm1", "observation_id":oid, "observed_at":when.isoformat(),
            "value":value, "evidence":["fixture"]}

def test_lifecycle_and_duplicate_settlement():
    l=SettlementLedger(); l.accept_commitment(commitment()); l.record_observation(obs())
    out=l.settle("cm1", now=NOW+timedelta(days=2)); assert out["lifecycle_state"]=="SUCCESSFUL"
    assert l.settle("cm1", now=NOW+timedelta(days=3)) is out

def test_duplicate_commitment_and_early_late_order():
    l=SettlementLedger(); c=commitment(); assert l.accept_commitment(c) is l.accept_commitment(dict(c))
    assert l.record_observation(obs(when=NOW-timedelta(hours=1)))["window_state"]=="PENDING"
    assert l.record_observation(obs(when=NOW+timedelta(days=2),oid="late"))["window_state"]=="LATE"
    l.record_observation(obs(oid="in-order")); assert l.settle("cm1",now=NOW+timedelta(days=2))["lifecycle_state"]=="SUCCESSFUL"

def test_equivalent_observations_do_not_create_second_outcome():
    l=SettlementLedger(); l.accept_commitment(commitment())
    l.record_observation(obs(oid="first")); l.record_observation(obs(oid="second"))
    first=l.settle("cm1",now=NOW+timedelta(days=2)); second=l.settle("cm1",now=NOW+timedelta(days=2))
    assert first["outcome_id"]==second["outcome_id"] and len(l.outcomes)==1

def test_contradictory_and_special_commitments():
    l=SettlementLedger(); l.accept_commitment(commitment()); l.record_observation(obs("SUCCESS",oid="a")); l.record_observation(obs("FAIL",oid="b"))
    assert l.settle("cm1",now=NOW+timedelta(days=2))["lifecycle_state"]=="AMBIGUOUS"
    for flag, state in (("invalidated","INVALIDATED"),("superseded_by","SUPERSEDED")):
        x=SettlementLedger(); x.accept_commitment(commitment(commitment_id=flag, **{flag: "x"})); assert x.settle(flag,now=NOW+timedelta(days=2))["lifecycle_state"]==state

def test_rejects_missing_wake_and_premature_settlement():
    with pytest.raises(ValueError, match="wake"): validate_commitment(commitment(wake_id=""))
    l=SettlementLedger(); l.accept_commitment(commitment()); assert l.settle("cm1",now=NOW)["lifecycle_state"]=="PENDING"

def test_missing_observation_is_unobservable_and_fixture_is_not_organic():
    l=SettlementLedger(); c=commitment(provenance={"producer":"test"}); l.accept_commitment(c)
    out=l.settle("cm1",now=NOW+timedelta(days=2))
    assert out["lifecycle_state"]=="UNOBSERVABLE" and c["provenance"]["producer"]=="test"

def test_off_state_has_no_side_effect():
    l=SettlementLedger(); assert l.commitments=={} and l.outcomes=={} and l.proposals=={}
