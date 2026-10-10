"""The coordination gateway allows the relay's POST /event lane (n8n-workflow-error).

Root cause RC8 (2026-10-10 W0 rollback): the generic workflows' Error Trigger posts workflow
errors to the relay's /event, which forwards one accept_event on lane `n8n-workflow-error`.
Without that lane in the gateway unit's TRADEAI_N8N_GATEWAY_EXTRA_LANES the gateway answers
`unknown_lane`. The existing lanes must stay.
"""
from pathlib import Path

UNIT = Path(__file__).resolve().parents[1] / "config" / "systemd" / "user" / "tradeai-n8n-coordination-gateway.service"


def _lanes() -> list[str]:
    line = next(l for l in UNIT.read_text().splitlines() if "TRADEAI_N8N_GATEWAY_EXTRA_LANES=" in l)
    return line.split("TRADEAI_N8N_GATEWAY_EXTRA_LANES=", 1)[1].strip().strip('"').split()


def test_workflow_error_lane_is_allowed():
    assert "n8n-workflow-error" in _lanes()


def test_existing_lanes_are_kept():
    lanes = _lanes()
    assert "incident-fanin" in lanes and "research-intake" in lanes


def test_lane_list_has_no_duplicates():
    lanes = _lanes()
    assert len(lanes) == len(set(lanes))
