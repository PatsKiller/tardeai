"""Lane-D safety controls: diagnostics and learning cannot reach live behavior."""
from scripts.self_repair_effect import diagnose_and_propose
from scripts.settle_agent_commitments import SettlementLedger

def test_duplicate_and_replay_controls_have_one_derived_effect():
    assert diagnose_and_propose([{"edge_id":"x","source":"a","target":"b","healthy":False}])[0]["idempotency_key"] == diagnose_and_propose([{"edge_id":"x","source":"a","target":"b","healthy":False}])[0]["idempotency_key"]
    assert not hasattr(SettlementLedger(), "live_weights")

def test_proposals_cannot_mutate_live_financial_behavior():
    p=diagnose_and_propose([{"edge_id":"x","source":"a","target":"b","healthy":False}])[0]
    assert p["production_mutation"] is False and p["financial_surface_reachable"] is False


# ── Reconstructed by the integration owner at INTEGRATION_ORDER.md step 5 ──
# Source: e7e47e28e "fix(comms): a bigger move is not the same notice — found by
# mutation testing" (2026-09-07 12:21, pre-campaign, on the prior-art branches).
# That commit does NOT descend from the campaign baseline, so it was not merged.
# Its IMPLEMENTATION survives in lane B's accepted comms_memory.py (numbers are
# bucketed to their integer part). Its GUARD TESTS did not survive into any
# accepted lane, leaving the fix live but unprotected — which is exactly how the
# original bug persisted: the unit test "had been passing for the wrong reason".
# Reconstructed here, not cherry-picked; lane history is untouched (instruction 7).

def test_a_bigger_move_is_not_the_same_notice():
    """5% and 90% must not collapse — a genuine escalation must not be
    suppressed as a duplicate. This is the failure mutation testing caught."""
    import scripts.lib.comms_memory as CM
    assert CM.normalized_hash("NOC up 5%") != CM.normalized_hash("NOC up 90%")


def test_spurious_precision_still_collapses():
    """Magnitude survives; spurious precision does not."""
    import scripts.lib.comms_memory as CM
    assert CM.normalized_hash("NOC up 12.5%") == CM.normalized_hash("NOC up 12.53%")
    assert CM.normalized_hash("moved 12.5%") == CM.normalized_hash("<b>moved 12.53% </b>")
