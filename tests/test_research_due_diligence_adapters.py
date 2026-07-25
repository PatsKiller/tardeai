from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import research_due_diligence_adapters as adapters


NOW = "2026-07-25T16:00:00+00:00"


def watch_packet(*, quality="ADMITTED", validation="PASS", freshness="CURRENT"):
    return {
        "symbol": "AAPL",
        "evaluated_at": NOW,
        "facts_as_of": NOW,
        "action_policy_version": "watch-action-policy-v1",
        "current_price": 200.0,
        "price_used": 200.0,
        "freshness": {"overall_state": freshness, "last_strategy_build_at": NOW},
        "current_input_snapshot": {
            "market": {"price": 200.0, "price_as_of": NOW,
                       "technical_as_of": NOW, "rvol": 1.2},
        },
        "event_state": {"state": "CLEAR", "blocks_action": False, "as_of": NOW},
        "current_actionable_plan": {
            "structure": "LONG_STOCK",
            "ticket_validation": {
                "state": validation,
                "validator_version": "ticket-validator-v1.1",
                "ticket_hash": "ticket-hash",
                "quality_admission": {
                    "state": quality,
                    "new_entry_allowed": quality == "ADMITTED",
                    "policy_version": "watch-quality-admission-v1",
                    "facts_used": {"float_m": 100.0, "atr_pct": 2.0},
                    "reasons": [],
                },
            },
        },
    }


def proposal():
    return {
        "id": 11,
        "symbol": "AAPL",
        "strategy_id": "long_stock",
        "status": "PENDING",
        "proposed_entry": 198.0,
        "proposed_stop": 190.0,
        "proposed_target1": 214.0,
        "risk_reward": 2.0,
        "created_at": NOW,
    }


def account_context():
    return {
        "account": "taxable",
        "sizing": {"shares": 25, "dollars": 4950},
        "capacity": {"remaining_dollars": 10000},
        "as_of": NOW,
        "policy_version": "account-risk-v1",
    }


def sector_snapshot(capture_as_of=NOW):
    truth = {
        "source": "ticker_prices distinct closes",
        "source_as_of": capture_as_of,
        "calculation_version": "sector-rs-v4",
        "cadence": "daily close",
        "quality": "ok",
    }
    breadth = {
        "source": "ticker_prices exact 20 distinct sessions",
        "source_as_of": capture_as_of,
        "calculation_version": "breadth-exact20-v1",
        "cadence": "daily close",
        "quality": "ok",
        "coverage_n": 50,
        "coverage_total": 60,
    }
    row = {
        "sector": "Technology",
        "etf": "XLK",
        "state": "LEADING",
        "rs5": 1.0,
        "rs20": 3.0,
        "rs60": 6.0,
        "slope": 0.5,
        "breadth_pct": 63,
        "breadth_coverage_n": 50,
        "breadth_membership_n": 60,
        "breadth_quality": "ok",
        "freshness": {"stale": False, "quality": "ok"},
        "quarantined": False,
        "calculation_version": "sector-rs-v4",
        "truth": truth,
    }
    snapshot = {
        "as_of": capture_as_of,
        "calculation_version": "sector-rs-v4",
        "truth_ledger": {"sector_returns": truth, "breadth": breadth},
        "rows": [row],
    }
    return row, snapshot


def industry_snapshot(*, capture_kind="close"):
    row = {
        "industry": "Semiconductors",
        "sector": "Technology",
        "mapping_quality": "exact",
        "mapping_version": "industry-map-v1",
        "rel1w": 1.1,
        "rel1m": 2.4,
        "state": "LEADING",
        "truth": {
            "source": "finviz_elite_view_141",
            "source_as_of": NOW,
            "calculation_version": "industry-rs-v3",
            "cadence": "midday refresh + close capture",
            "quality": "same_vendor_same_run",
        },
    }
    snapshot = {
        "captured_at": NOW,
        "capture_kind": capture_kind,
        "calculation_version": "industry-rs-v3",
        "quadrant_mapping": "level=month-SPY month, direction=week-SPY week",
        "spy_baseline": {
            "provider": "finviz_elite_view_141",
            "captured_at": NOW,
            "quality": "same_vendor_same_run",
            "w1": 1.0,
            "m1": 2.0,
        },
        "data_quality": {"mapping_version": "industry-map-v1"},
    }
    return row, snapshot


def defense_card():
    return {
        "id": "rotatein-XLK",
        "group": "get_into",
        "title": "ROTATE-IN · Technology",
        "mode": "SHADOW",
        "as_of": NOW,
        "invalidation": "Technology exits leading state",
        "levels": {"entry_zone": "pullback toward 20DMA"},
        "allocation_policy": {
            "taxable": {
                "eligible": True,
                "current_account_weight_pct": 8.0,
                "risk_target_pct": 11.0,
                "capacity_pct": 3.0,
            },
        },
        "account_sizing": {
            "taxable": {"pct_band": [1.0, 2.0], "dollar_band": [5000, 10000]},
        },
        "account_exposure": {"taxable": {"current_sector_pct": 8.0}},
        "risk_context": {"quality": "ok", "annualized_vol_pct": 20.0, "correlation": 0.7},
        "quality_gate": {"stock_picks_passed": 2, "version": "defense-v11"},
    }


def test_proposal_pass_requires_exact_arithmetic_watch_admission_account_and_event():
    packet = adapters.proposal_due_diligence(
        proposal(), watch_packet(), account_context=account_context(),
        event_context={"state": "CLEAR", "blocks_action": False,
                       "as_of": NOW, "policy_version": "event-v1"},
    )
    assert packet["deterministic_state"] == "PASS"
    assert packet["downstream"]["proposal_research_complete"] is True
    assert packet["downstream"]["model_may_amend_ticket"] is False


def test_proposal_blocks_unassessed_quality_before_any_model_review():
    packet = adapters.proposal_due_diligence(
        proposal(), watch_packet(quality="UNASSESSED"),
        account_context=account_context(),
        event_context={"state": "CLEAR", "blocks_action": False,
                       "as_of": NOW, "policy_version": "event-v1"},
    )
    assert packet["deterministic_state"] == "BLOCKED"
    assert packet["model_oversight"]["allowed"] is False
    assert "UNASSESSED" in " ".join(packet["hard_failures"])


def test_proposal_blocks_missing_account_specific_capacity():
    incomplete = {"account": "taxable", "sizing": {"shares": 10},
                  "as_of": NOW, "policy_version": "account-risk-v1"}
    packet = adapters.proposal_due_diligence(
        proposal(), watch_packet(), account_context=incomplete,
        event_context={"state": "CLEAR", "blocks_action": False,
                       "as_of": NOW, "policy_version": "event-v1"},
    )
    assert packet["deterministic_state"] == "BLOCKED"
    assert "capacity" in " ".join(packet["hard_failures"]).lower()


def test_sector_adapter_passes_only_complete_current_exact_breadth_row():
    row, snapshot = sector_snapshot()
    packet = adapters.sector_due_diligence(row, snapshot, benchmark="SPY")
    assert packet["deterministic_state"] == "PASS"
    assert packet["downstream"]["rotation_recommendation_eligible"] is True
    assert packet["evidence"]["breadth"]["universe"].startswith("covered screener")


def test_sector_adapter_blocks_insufficient_breadth_coverage():
    row, snapshot = sector_snapshot()
    row["breadth_quality"] = "insufficient_membership_coverage"
    row["breadth_pct"] = None
    packet = adapters.sector_due_diligence(row, snapshot)
    assert packet["deterministic_state"] == "BLOCKED"


def test_industry_midday_is_review_required_and_close_is_pass():
    row, refresh = industry_snapshot(capture_kind="refresh")
    midday = adapters.industry_due_diligence(row, refresh)
    assert midday["deterministic_state"] == "REVIEW_REQUIRED"
    assert midday["downstream"]["proposal_or_rotation_eligible"] is False

    row, close = industry_snapshot(capture_kind="close")
    closed = adapters.industry_due_diligence(row, close)
    assert closed["deterministic_state"] == "PASS"
    assert closed["downstream"]["proposal_or_rotation_eligible"] is True


def test_industry_unmapped_is_blocked_even_when_momentum_is_strong():
    row, snapshot = industry_snapshot(capture_kind="close")
    row.update(sector=None, mapping_quality="unmapped", rel1w=5.0, rel1m=10.0)
    packet = adapters.industry_due_diligence(row, snapshot)
    assert packet["deterministic_state"] == "BLOCKED"


def test_defense_card_requires_passing_sector_and_account_specific_math():
    row, snapshot = sector_snapshot()
    sector_packet = adapters.sector_due_diligence(row, snapshot)
    packet = adapters.defense_due_diligence(
        defense_card(), snapshot, sector_packet=sector_packet,
    )
    assert packet["deterministic_state"] == "PASS"
    assert packet["downstream"]["recommendation_card_eligible"] is True
    assert packet["downstream"]["oversight_is_critique_only"] is True


def test_defense_model_oversight_cannot_rescue_missing_account_sizing():
    row, snapshot = sector_snapshot()
    sector_packet = adapters.sector_due_diligence(row, snapshot)
    card = defense_card()
    card["account_sizing"] = {}
    packet = adapters.defense_due_diligence(
        card,
        snapshot,
        sector_packet=sector_packet,
        oversight={"generated_at": NOW, "cards": [{"verdict": "CONCUR"}]},
    )
    assert packet["deterministic_state"] == "BLOCKED"
    assert packet["model_oversight"]["may_override_deterministic_state"] is False
