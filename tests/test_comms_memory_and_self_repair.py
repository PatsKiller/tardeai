"""Lane-D safety controls: diagnostics and learning cannot reach live behavior."""
from scripts.self_repair_effect import diagnose_and_propose
from scripts.settle_agent_commitments import SettlementLedger

def test_duplicate_and_replay_controls_have_one_derived_effect():
    assert diagnose_and_propose([{"edge_id":"x","source":"a","target":"b","healthy":False}])[0]["idempotency_key"] == diagnose_and_propose([{"edge_id":"x","source":"a","target":"b","healthy":False}])[0]["idempotency_key"]
    assert not hasattr(SettlementLedger(), "live_weights")

def test_proposals_cannot_mutate_live_financial_behavior():
    p=diagnose_and_propose([{"edge_id":"x","source":"a","target":"b","healthy":False}])[0]
    assert p["production_mutation"] is False and p["financial_surface_reachable"] is False
