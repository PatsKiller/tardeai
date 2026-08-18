"""Advisory Desk operator-grade truth — cache, field-state, joins, health."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib.advisory_desk_operator import (  # noqa: E402
    AVAILABLE,
    DATA_UNAVAILABLE,
    FRESH_CURRENT,
    FRESH_EXPIRED,
    FRESH_STALE,
    HEALTHY,
    NOT_APPLICABLE,
    OPERATOR_TRUTH_VERSION,
    PARTIAL,
    SETUP_BLOCKED,
    STALE as HEALTH_STALE,
    assess_watchdog_advisory,
    cache_meta,
    classify_freshness,
    compute_desk_health,
    derive_setup_state,
    enrich_row,
    field_state,
    holdings_field_states,
    na,
    project_reentry,
    project_watch,
    why_advisory_call,
)


NOW = datetime(2026, 8, 18, 13, 30, tzinfo=timezone.utc)


def test_field_state_contract_not_bare_null():
    fs = field_state(34.52, state=AVAILABLE, source="holdings.json", as_of="2026-08-18", reason=None)
    assert set(fs) >= {"value", "state", "source", "as_of", "freshness", "quality", "reason"}
    assert fs["value"] == 34.52
    n = na("no_open_position")
    assert n["state"] == NOT_APPLICABLE
    assert n["display"] == "N/A"


def test_watchlist_shares_not_applicable():
    out = holdings_field_states({"row_class": "watchlist", "symbol": "PLTR"})
    assert out["shares"]["state"] == NOT_APPLICABLE
    assert out["shares"]["reason"] == "no_open_position"
    assert out["current_mark"]["state"] == NOT_APPLICABLE


def test_closed_mv_not_applicable():
    out = holdings_field_states({"row_class": "closed_journal", "symbol": "FATN"})
    assert out["market_value"]["state"] == NOT_APPLICABLE
    assert out["market_value"]["reason"] == "position_closed"


def test_implied_price_is_derived_reference_not_canonical():
    row = {
        "row_class": "holding",
        "symbol": "SPCX",
        "market_value": 5600.0,
        "shares": 40.0,
        "canonical_financial_facts": {"market_value": 5600.0, "shares": 40.0, "current_mark": None},
    }
    out = holdings_field_states(row, live={"symbol": "SPCX", "shares": 40.0, "market_value": 5600.0})
    assert out["current_mark"]["state"] == DATA_UNAVAILABLE
    assert out["implied_price"]["quality"] == "DERIVED_REFERENCE"
    assert out["implied_price"]["value"] == 140.0
    assert any("implied_price" in x for x in out["why_missing"])


def test_account_specific_holdings_not_last_symbol_wins():
    """Taxable SCHD must not inherit IRA shares from symbol-keyed provenance."""
    row = {
        "row_class": "holding",
        "symbol": "SCHD",
        "account": "schwab_taxable",
        "shares": 406.54,
        "market_value": 14005.43,
        "canonical_financial_facts": {
            "shares": 6155.25,
            "market_value": 212048.39,
            "current_mark": 34.52,
            "as_of": "2026-08-14",
        },
    }
    live = {
        "symbol": "SCHD",
        "account": "schwab_taxable",
        "shares": 406.54,
        "market_value": 14005.43,
        "canonical_mark": 34.52,
        "canonical_mark_as_of": "2026-08-14",
        "cost_basis": 12687.73,
    }
    out = holdings_field_states(row, live=live)
    assert out["shares"]["value"] == 406.54
    assert out["market_value"]["value"] == 14005.43
    assert abs(out["implied_price"]["value"] - 34.45) < 0.02


def test_reference_snapshot_not_promoted():
    live = {
        "symbol": "SPCX",
        "shares": 40.0,
        "market_value": 5679.2,
        "canonical_mark": 140.0,
        "canonical_mark_as_of": "2026-08-14",
        "canonical_mark_source": "finviz",
        "price": 141.98,
        "current_price": 141.98,
        "price_source": "finviz",
        "updated_at": "2026-08-18T13:07:03+00:00",
    }
    row = {"row_class": "holding", "symbol": "SPCX", "canonical_financial_facts": {"current_mark": 140.0, "shares": 40, "market_value": 5600, "as_of": "2026-08-14", "source": "finviz"}}
    out = holdings_field_states(row, live=live)
    assert out["current_mark"]["value"] == 140.0
    assert out["reference_market_snapshot"]["quality"] == "NON_CANONICAL_REFERENCE"
    assert out["reference_market_snapshot"]["value"] == 141.98


def test_freshness_expired_vs_current():
    assert classify_freshness(NOW - timedelta(seconds=60), stale_s=300, expired_s=3600, now=NOW) == FRESH_CURRENT
    assert classify_freshness(NOW - timedelta(hours=10), stale_s=6 * 3600, expired_s=24 * 3600, now=NOW) == FRESH_STALE
    assert classify_freshness(NOW - timedelta(hours=30), stale_s=6 * 3600, expired_s=24 * 3600, now=NOW) == FRESH_EXPIRED
    assert classify_freshness(None, stale_s=300, expired_s=3600, now=NOW) == "UNAVAILABLE"


def test_desk_health_stale_not_healthy():
    h = compute_desk_health(
        structural_ok=True,
        plausibility_pass=True,
        fact_freshness=FRESH_STALE,
        source_completeness=HEALTHY,
        opinion_freshness=FRESH_CURRENT,
        reentry_freshness=FRESH_CURRENT,
        watch_freshness=FRESH_CURRENT,
        memory_health=HEALTHY,
    )
    assert h["overall"] == HEALTH_STALE
    assert h["overall"] != HEALTHY


def test_desk_health_partial_when_watch_missing():
    h = compute_desk_health(
        structural_ok=True,
        plausibility_pass=True,
        fact_freshness=FRESH_CURRENT,
        source_completeness=PARTIAL,
        opinion_freshness=FRESH_STALE,
        reentry_freshness=FRESH_CURRENT,
        watch_freshness="UNAVAILABLE",
        memory_health=HEALTHY,
    )
    assert h["overall"] == PARTIAL


def test_cache_meta_labels_day_old_ok_blob():
    computed = (NOW - timedelta(hours=23, minutes=45)).isoformat()
    desk = {"ok": True, "cache_hit": True, "data": {"computed_at": computed}}
    meta = cache_meta(desk, now=NOW)
    assert meta["desk_cache_hit"] is True
    assert meta["desk_freshness_state"] in {FRESH_STALE, FRESH_EXPIRED}
    assert meta["desk_freshness_state"] != FRESH_CURRENT


def test_load_desk_uses_builder_age_not_ok_only():
    src = (ROOT / "scripts" / "api_v3_advisory.py").read_text(encoding="utf-8")
    assert "if cached.get(\"ok\")" not in src
    assert "DEFAULT_MAX_AGE_S" in src
    assert "build_advisory_desk" in src


def test_row_view_exposes_reentry_fields():
    src = (ROOT / "scripts" / "api_v3_advisory.py").read_text(encoding="utf-8")
    assert '"reentry_state"' in src
    assert '"reentry_entry_low"' in src
    assert '"watch_intelligence"' in src
    assert '"durable_memory"' in src


def test_project_reentry_ready_panel():
    raw = {
        "symbol": "FATN",
        "price": 6.16,
        "entry_low": 5.7,
        "entry_high": 6.2,
        "rsi": 54.3,
        "intel": {
            "state": "READY TO REVIEW",
            "reason": "Price is inside the entry zone and RSI 54.3 is in the constructive band (40–70).",
            "action": "Review re-entry now",
            "distance_pct": 0.0,
            "wash_blocked": False,
        },
    }
    panel = project_reentry("FATN", raw, as_of="2026-08-18T13:05:34+00:00", freshness=FRESH_CURRENT)
    assert panel["available"] is True
    assert panel["state"]["value"] == "READY TO REVIEW"
    assert panel["distance_label"] == "IN ZONE"
    assert panel["entry_zone_display"] == "$5.70–$6.20"
    assert panel["wash_status"] == "CLEAR"
    assert panel["next_action"]["value"] == "Review re-entry now"


def test_project_watch_pltr_shape():
    composed = {
        "ok": True,
        "card": {
            "symbol": "PLTR",
            "last": 172.535,
            "price_as_of": "2026-08-18T09:07:18-04:00",
            "price_source": "market_quotes",
            "freshness_state": "PREMARKET_CURRENT",
            "trade_ai_state": "DETERMINISTIC_FAIL",
            "operator_meaning": "NO TRADE MECHANICS — quality or ticket validation failed",
            "next_operator_action": "NO TRADE ACTION",
            "primary_risk": "quality admission: technical snapshot is STALE",
            "rsi": 72.1,
            "support": 122.21,
            "resistance": 178.05,
            "street_rating": "BUY",
            "street_consensus": {
                "rating": "BUY",
                "analyst_count": 27,
                "target_mean": 182.2,
                "as_of": "2026-07-26",
                "source": "yahoo_analyst_targets_history",
                "implied_upside_pct": 5.6,
            },
            "catalyst_summary": "Next earnings: 2026-11-02",
        },
        "item": {"domains": {"CanonicalQuote": {}}},
    }
    w = project_watch(composed)
    assert w["available"] is True
    assert w["quote"]["last"]["value"] == 172.535
    assert w["street"]["target"]["value"] == 182.2
    assert w["street"]["analyst_count"]["value"] == 27
    setup = derive_setup_state(w, verdict="WAIT")
    assert setup == SETUP_BLOCKED
    why = why_advisory_call({"verdict": "WAIT", "row_class": "watchlist"}, watch=w, reentry=None)
    assert "DETERMINISTIC_FAIL" in why or "NO TRADE" in why


def test_enrich_row_watch_and_reentry_pass_through():
    watch_join = {
        "items": {
            "PLTR": {
                "ok": True,
                "card": {
                    "symbol": "PLTR",
                    "last": 172.5,
                    "price_source": "market_quotes",
                    "freshness_state": "PREMARKET_CURRENT",
                    "trade_ai_state": "WAIT",
                    "operator_meaning": "awaiting setup",
                },
                "item": {"domains": {}},
            }
        }
    }
    reentry_join = {
        "as_of": "2026-08-18T13:05:34+00:00",
        "freshness": FRESH_CURRENT,
        "by_symbol": {
            "FATN": {
                "price": 6.16,
                "entry_low": 5.7,
                "entry_high": 6.2,
                "rsi": 54.3,
                "intel": {"state": "READY TO REVIEW", "reason": "in zone", "action": "Review re-entry now", "distance_pct": 0},
            }
        },
    }
    mem = {"available": True, "retrieval_status": "EMPTY", "by_symbol": {}, "influence_mode": "ACTIVE_ADVISORY", "memory_behavior_influence": "0", "provider": "DurableJsonlMemoryProvider"}
    senses = {"by_symbol": {}, "influence_mode": "ACTIVE_ADVISORY", "state": "NOT_RUN"}
    live = {}
    watch_row = enrich_row(
        {"symbol": "PLTR", "row_class": "watchlist", "verdict": "WAIT", "confidence": 0.3, "rationale": "thin"},
        watch_join=watch_join, reentry_join=reentry_join, memory_join=mem, senses_join=senses, live_holdings=live,
    )
    assert watch_row["watch_intelligence"]["available"] is True
    assert watch_row["field_states"]["shares"]["state"] == NOT_APPLICABLE
    assert watch_row["setup_state"]
    fatn = enrich_row(
        {"symbol": "FATN", "row_class": "closed_journal", "verdict": "RE_ENTER", "confidence": 0.55},
        watch_join={"items": {}}, reentry_join=reentry_join, memory_join=mem, senses_join=senses, live_holdings=live,
    )
    assert fatn["reentry_state"] == "READY TO REVIEW"
    assert fatn["reentry_entry_low"] == 5.7
    assert fatn["reentry"]["distance_label"] == "IN ZONE"


def test_does_not_import_watch_decision_desk():
    src = (ROOT / "scripts" / "lib" / "advisory_desk_operator.py").read_text(encoding="utf-8")
    assert "from lib.data_broker.watch_decision_desk" not in src
    assert "import watch_decision_desk" not in src
    api = (ROOT / "scripts" / "api_v3_advisory.py").read_text(encoding="utf-8")
    assert "watch_decision_desk" not in api


def test_authority_fence_in_operator_module():
    src = (ROOT / "scripts" / "lib" / "advisory_desk_operator.py").read_text(encoding="utf-8")
    assert "READ_ONLY_ADVISORY" in src
    assert "MEMORY_BEHAVIOR_INFLUENCE" in src
    assert "broker_write_authority" in src or "Zero broker" in src


def test_ui_has_class_aware_cards():
    ui = (ROOT / "apps" / "command-center-v3" / "src" / "pages" / "AdvisoryDeskHub.tsx").read_text(encoding="utf-8")
    assert "WatchIntelCard" in ui
    assert "ReentryCard" in ui
    assert "FieldStateView" in ui
    assert "FACTS AS OF" in ui
    assert "PRIOR SYNTHESIS" in ui
    assert "durable" in ui.lower()
    assert "NOT_APPLICABLE" in ui


def test_banners_no_longer_healthy_on_validation_only():
    src = (ROOT / "scripts" / "api_v3_advisory.py").read_text(encoding="utf-8")
    assert "Desk HEALTHY" in src
    assert "Desk STALE" in src
    assert "desk_health" in src


def test_provenance_quality_without_mark_is_unavailable():
    from lib.cio_advisory_provenance import build_canonical_financial_facts
    facts = build_canonical_financial_facts({
        "symbol": "SPCX",
        "market_value": 5600.0,
        "shares": None,
        "price": None,
        "current_price": None,
    })
    assert facts["current_mark"] is None
    assert facts["quality"] == "DATA_UNAVAILABLE"


def test_watchdog_assess_reads_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runtime = tmp_path / "data" / "runtime"
    runtime.mkdir(parents=True)
    payload = {
        "ok": True,
        "data": {
            "computed_at": (NOW - timedelta(hours=23)).isoformat(),
            "rows": [
                {"symbol": "PLTR", "row_class": "watchlist"},
                {"symbol": "FATN", "row_class": "closed_journal", "verdict": "RE_ENTER", "reentry_state": "READY TO REVIEW"},
            ],
        },
    }
    (runtime / "advisory_desk_latest.json").write_text(json.dumps(payload))
    monkeypatch.setattr("lib.advisory_desk_operator._RUNTIME", runtime)
    facts = assess_watchdog_advisory(now=NOW)
    assert facts["facts_freshness"] in {FRESH_STALE, FRESH_EXPIRED}
    assert facts["watch_rows"] == 1
    assert facts["reentry_fields_present"] == 1


def test_operator_truth_version_constant():
    assert OPERATOR_TRUTH_VERSION.startswith("advisory.operator.")


def test_compute_banners_stale_is_not_healthy():
    from api_v3_advisory import compute_banners
    banners = compute_banners(
        {"validation_ok": True, "plausibility_gate": "PASS", "holdings_rows": 10},
        {"desk_health": {"overall": "STALE", "reason": "deterministic facts expired"}, "llm_in_path": False},
    )
    titles = [b["title"] for b in banners]
    assert any("STALE" in t for t in titles)
    assert not any(t.lower() == "desk healthy" for t in titles)


def test_no_broker_write_in_operator_sources():
    for rel in (
        "scripts/lib/advisory_desk_operator.py",
        "scripts/api_v3_advisory.py",
    ):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for banned in ("place_order", "create_order", "cancel_order", "mutate_stop", "submit_order"):
            assert banned not in src
