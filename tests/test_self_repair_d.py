from scripts.self_repair_effect import diagnose_and_propose
def test_broken_edge_is_diagnostic_only_and_bounded():
    p=diagnose_and_propose([{"edge_id":"e1","source":"a","target":"b","healthy":False,"reason":"missing"}])
    assert len(p)==1 and p[0]["executable"] is False and p[0]["production_mutation"] is False
    assert p[0]["financial_surface_reachable"] is False and p[0]["provenance"]["inputs"]==["e1"]
