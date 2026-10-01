"""Advisory run-now dependency-clock contract."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.api_v3_advisory import _dependency_clock  # noqa: E402


def test_run_now_synthesis_does_not_claim_technical_refresh():
    clocks = _dependency_clock(
        [{
            "watch_intelligence": {"technicals": {"as_of": "2026-09-30T15:00:00Z"}},
            "expand": {"analyst": {"target_as_of": "2026-09-29T15:00:00Z"}, "evidence_items": [{"retrieved_at": "2026-09-28T15:00:00Z"}]},
        }],
        {"synthesis": "2026-10-01T15:00:00Z", "synthesis_freshness": "CURRENT", "memory": "2026-09-30T15:00:00Z", "memory_freshness": "OBSERVED"},
    )
    assert clocks["advisory_synthesis"]["source_as_of"] == "2026-10-01T15:00:00Z"
    assert clocks["technicals"]["source_as_of"] == "2026-09-30T15:00:00Z"
    assert clocks["analyst_data"]["source_as_of"] == "2026-09-29T15:00:00Z"
    assert clocks["research"]["source_as_of"] == "2026-09-28T15:00:00Z"
    assert clocks["durable_memory"]["source_as_of"] == "2026-09-30T15:00:00Z"
    assert clocks["technicals"]["source_as_of"] != clocks["advisory_synthesis"]["source_as_of"]
