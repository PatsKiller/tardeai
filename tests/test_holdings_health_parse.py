"""Holdings LLM health parse — truncated gemma JSON must salvage, not silent parse_error."""
from lib.cio_agent_contract import (
    parse_holdings_health_result,
    salvage_holdings_health_fields,
)


COMPLETE = '''{"health":"STABLE","confidence":85,"thesis_intact":"yes",
"catalyst_outlook":"neutral","risk_flag":"none","action":"HOLD",
"reasoning":"No thesis break.","evidence":[{"tag":"fact","text":"held"}],
"data_i_doubt":"none"}'''

TRUNCATED = '{"health":"WATCH","confidence":70,"action":"TRIM","reasoning":"RSI stretched and the rest of this object never clo'


def test_complete_json_parses():
    r = parse_holdings_health_result(COMPLETE)
    assert r is not None
    assert r["health"] == "STABLE"
    assert r["action"] == "HOLD"


def test_truncated_json_salvages_health_and_action():
    raw = salvage_holdings_health_fields(TRUNCATED)
    assert raw is not None
    assert raw["health"] == "WATCH"
    assert raw["action"] == "TRIM"
    parsed = parse_holdings_health_result(TRUNCATED)
    assert parsed is not None
    assert parsed["health"] == "WATCH"
    assert parsed["action"] == "TRIM"


def test_garbage_does_not_salvage():
    assert salvage_holdings_health_fields("not json at all") is None
    assert parse_holdings_health_result("not json at all") is None


def test_holdings_refresh_counts_parse_error_and_raises_predict():
    src = open("scripts/holdings_llm_refresh.py", encoding="utf-8").read()
    assert "parse_error" in src
    assert "empty" in src
    assert 'LOCAL_LLM_NUM_PREDICT", "900"' in src
    assert "parse_error raw[:400]" in src
