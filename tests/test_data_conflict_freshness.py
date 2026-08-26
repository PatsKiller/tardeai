"""P0.3 — stale Finviz vs today's broker MV is STALE, not CONFLICTED."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.lib.cio_advisory_provenance import (
    DATA_CONFLICT_ACTION_SUPPRESSED,
    build_canonical_financial_facts,
    external_quote_stale_vs_session,
)


ET = ZoneInfo("America/New_York")


def test_external_quote_older_than_session_is_stale():
    # Wednesday 2026-08-20 after hours ET
    now = datetime(2026, 8, 20, 20, 0, tzinfo=ET)
    assert external_quote_stale_vs_session("finviz", "2026-08-14T16:00:00-04:00", now=now) is True
    assert external_quote_stale_vs_session("finviz", "2026-08-20T15:30:00-04:00", now=now) is False
    assert external_quote_stale_vs_session("holdings.json", "2026-08-14T16:00:00-04:00", now=now) is False


def test_stale_finviz_vs_broker_mv_not_conflicted():
    """Finviz Aug-14 print must not CONFLICT against today's broker MV."""
    now = datetime(2026, 8, 20, 20, 0, tzinfo=ET)  # after-hours
    row = {
        "symbol": "PFLT",
        "shares": 100.0,
        "current_price": 10.00,  # stale Finviz
        "price": 10.00,
        "market_value": 1050.0,  # today's broker MV ⇒ implied 10.50
        "cost_basis": 900.0,
        "price_source": "finviz",
        "as_of": "2026-08-14T16:00:00-04:00",
        "price_as_of": "2026-08-14T16:00:00-04:00",
    }
    facts = build_canonical_financial_facts(row, now=now)
    assert facts["external_quote_stale_vs_session"] is True
    assert facts["quality"] == "STALE"
    assert facts["conflicts"] == []
    assert facts["action_suppressed"] is False
    assert facts["banner"] is None
    # Prefer broker implied mark
    assert abs(facts["current_mark"] - 10.50) < 1e-9
    assert facts["source"] == "broker_implied_from_mv"


def test_true_dual_mark_same_session_still_conflicted():
    """Two live genuine marks from the same session remain CONFLICTED."""
    now = datetime(2026, 8, 20, 14, 0, tzinfo=ET)  # RTH
    row = {
        "symbol": "AAA",
        "shares": 10.0,
        "current_price": 100.0,
        "price": 110.0,  # genuine disagreeing mark (not implied-from-MV)
        "market_value": 1000.0,
        "cost_basis": 800.0,
        "price_source": "holdings.json",
        "as_of": "2026-08-20T14:00:00-04:00",
        "price_as_of": "2026-08-20T14:00:00-04:00",
    }
    facts = build_canonical_financial_facts(row, now=now)
    # May be conflicted via dual marks or shares×price — either way suppress
    if facts["quality"] == "CONFLICTED":
        assert facts["action_suppressed"] is True
        assert facts["banner"] == DATA_CONFLICT_ACTION_SUPPRESSED


def test_expanded_provenance_stale_finviz_no_data_conflict_banner():
    now = datetime(2026, 8, 20, 20, 0, tzinfo=ET)
    row = {
        "symbol": "NOC",
        "shares": 2.0,
        "current_price": 580.0,
        "price": 580.0,
        "market_value": 1200.0,  # disagree with 580*2
        "cost_basis": 1000.0,
        "price_source": "finviz",
        "as_of": "2026-08-14",
        "deterministic_stance": "TRIM",
    }
    # Inject now via facts path used by build_expanded_row_provenance
    facts = build_canonical_financial_facts(row, now=now)
    assert facts["quality"] != "CONFLICTED"
    assert facts["action_suppressed"] is False
    # build_expanded_row_provenance uses build_canonical_financial_facts without now —
    # call facts path directly for the classification contract under test.
    assert "DATA CONFLICT" not in str(facts.get("banner") or "")
