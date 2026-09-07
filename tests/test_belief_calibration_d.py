from datetime import datetime, timezone, timedelta
import pytest
from scripts.settle_agent_commitments import SettlementLedger

def row(i, pop="p", hor="h", state="SUCCESSFUL"):
    return {"outcome_id":f"o{i}","commitment_id":f"c{i}","wake_id":f"w{i}","population":pop,"horizon":hor,"lifecycle_state":state}

def test_mixed_rejected_insufficient_silent_and_provenance():
    l=SettlementLedger(); rows=[row(i) for i in range(4)]
    assert l.propose_belief(belief_key="k",outcomes=rows,population="p",horizon="h") is None
    with pytest.raises(ValueError,match="mixed"): l.calibration(rows+[row(9,pop="backtest")],population="p",horizon="h")

def test_proposal_provenance_reproducibility_and_shadow_rollback():
    rows=[row(i) for i in range(5)]; a=SettlementLedger(); b=SettlementLedger()
    p=a.propose_belief(belief_key="k",outcomes=rows,population="p",horizon="h")
    q=b.propose_belief(belief_key="k",outcomes=rows,population="p",horizon="h")
    assert p["belief_proposal_id"]==q["belief_proposal_id"]; assert p["provenance"]["outcome_ids"]==[f"o{i}" for i in range(5)]
    a.accept_shadow(p["belief_proposal_id"]); assert a.shadow_state; a.rollback_shadow(p["belief_proposal_id"]); assert not a.shadow_state
    assert p["live_mutation"] is False and p["financial_behavior_change"] is False

