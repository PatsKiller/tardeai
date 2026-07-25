from pathlib import Path
import copy
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from watch_research_due_diligence import watch_due_diligence


NOW = "2026-07-25T16:00:00+00:00"


def packet():
    return {
        "symbol": "AAPL",
        "packet_version": "1.1.0-shadow",
        "evaluated_at": NOW,
        "facts_as_of": NOW,
        "fundamentals_as_of": NOW,
        "action_policy_version": "watch-action-policy-v1",
        "freshness": {
            "overall_state": "CURRENT",
            "last_strategy_build_at": NOW,
        },
        "current_input_snapshot": {
            "market": {
                "price": 200.0,
                "price_as_of": NOW,
                "technical_as_of": NOW,
            },
            "fundamentals": {
                "provider": "finviz_enrichment",
                "fetched_at": NOW,
                "content_hash": "fund-hash",
                "coverage_count": 12,
            },
            "events": {
                "event_content_hash": "event-hash",
                "latest_catalyst_at": NOW,
                "earnings_state": "CLEAR",
            },
        },
        "technical_state": {
            "schema_version": "technical-intelligence-v1",
            "computed_at": NOW,
            "overall_freshness": "CURRENT",
            "overall_direction": "SUPPORTIVE",
            "source_hash": "technical-hash",
        },
        "current_actionable_plan": {
            "family": "SWING",
            "structure": "LONG_STOCK",
            "ticket_validation": {
                "state": "PASS",
                "validator_version": "strategy-ticket-validator-v1.1",
                "ticket_hash": "ticket-hash",
                "hard_failures": [],
                "warnings": [],
                "quality_admission": {
                    "policy_version": "watch-quality-admission-v1",
                    "state": "ADMITTED",
                    "new_entry_allowed": True,
                    "reasons": [],
                },
            },
        },
        "plan_families": {},
    }


def test_complete_watch_packet_passes_shared_research_standard():
    result = watch_due_diligence(packet())
    assert result["deterministic_state"] == "PASS"
    assert result["downstream"]["watch_research_complete"] is True
    assert result["downstream"]["proposal_research_may_consume"] is True
    assert result["coverage"]["required_source_coverage_pct"] == 100.0


def test_unassessed_quality_blocks_downstream_consumers():
    value = packet()
    value["current_actionable_plan"]["ticket_validation"]["quality_admission"] = {}
    result = watch_due_diligence(value)
    assert result["deterministic_state"] == "BLOCKED"
    assert result["model_oversight"]["allowed"] is False
    assert "UNASSESSED" in " ".join(result["hard_failures"])


def test_stale_packet_blocks_even_when_ticket_validation_passed():
    value = packet()
    value["freshness"]["overall_state"] = "STALE"
    result = watch_due_diligence(value)
    assert result["deterministic_state"] == "BLOCKED"
    assert any("STALE" in reason or "stale" in reason for reason in result["hard_failures"])


def test_persisted_wait_ready_conflict_blocks_shared_packet():
    value = copy.deepcopy(packet())
    value["operator_presentation"] = {"header_state": "WAIT"}
    value["plan_families"] = {
        "long_term": {"action_state": "READY", "structures": []},
    }
    result = watch_due_diligence(value)
    assert result["deterministic_state"] == "BLOCKED"
    assert "non-primary long_term action_state READY" in " ".join(result["hard_failures"])
