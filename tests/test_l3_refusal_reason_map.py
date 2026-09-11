from scripts.lib.judgment_schema import (
    CRITIC_PROVIDER_COLLISION,
    PROVIDER_OUTAGE,
    SCHEMA_INVALID,
    REFUSAL_REASON_MAP,
    build_refusal_output,
)


def test_critic_collision_not_schema_invalid():
    assert REFUSAL_REASON_MAP[CRITIC_PROVIDER_COLLISION] != "schema_invalid"
    assert REFUSAL_REASON_MAP[CRITIC_PROVIDER_COLLISION] == "provider_refusal"
    out = build_refusal_output(grounded={}, gate_state=CRITIC_PROVIDER_COLLISION, reasons=["author_critic_same_provider"])
    assert out["refusal_reason"] == "provider_refusal"
    assert out["refusal_state"] == CRITIC_PROVIDER_COLLISION


def test_provider_outage_maps_cleanly():
    out = build_refusal_output(grounded={}, gate_state=PROVIDER_OUTAGE, reasons=["AUTH_MISSING"])
    assert out["refusal_reason"] == "provider_outage"
    assert out["refusal_state"] == PROVIDER_OUTAGE


def test_schema_invalid_still_schema_invalid():
    out = build_refusal_output(grounded={}, gate_state=SCHEMA_INVALID, reasons=["non_json"])
    assert out["refusal_reason"] == "schema_invalid"
