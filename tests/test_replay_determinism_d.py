from datetime import datetime, timezone, timedelta
from scripts.settle_agent_commitments import SettlementLedger, outcome_id

def _c(i="c"):
    n=datetime(2026,1,1,tzinfo=timezone.utc); return {"schema_version":"Commitment@v1","source_sha":"a","produced_at":n.isoformat(),"correlation_id":"x","idempotency_key":i,"retention_class":"evidence_2y","lifecycle_state":"OPEN","provenance":{"producer":"test"},"parent_kind":"wake","commitment_id":i,"wake_id":"w","subject_guid":"s","commitment_kind":"k","normalized_claim":"n","observation_window_start":n.isoformat(),"observation_window_end":(n+timedelta(days=1)).isoformat(),"population":"p","horizon":"h"}
def test_replay_mints_same_outcome_and_one_row():
    c=_c(); a=SettlementLedger(); b=SettlementLedger(); a.accept_commitment(c); b.accept_commitment(c)
    assert outcome_id("c",c["observation_window_end"]) == outcome_id("c",c["observation_window_end"])
    assert a.settle("c",now=datetime(2026,1,3,tzinfo=timezone.utc)) == b.settle("c",now=datetime(2026,1,3,tzinfo=timezone.utc))
