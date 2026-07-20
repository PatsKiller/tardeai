#!/usr/bin/env python3
"""Phase 0 regression tests: earnings event-gate integrity + registry reconciliation.

The defect these lock down (found 2026-07-20): FMP's v3 earning_calendar began
returning HTTP 403 for non-legacy keys. `_get_earnings_dates` swallowed it
(`if not resp.ok: return {}` + bare except), so `earnings_blackout_check` saw
"" for every symbol and returned in_blackout=False — the event gate failed OPEN
for covered_call, cash_secured_put, credit_spread and long_call.

Pure tests only: no network, no broker, no DB writes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ── provider-error contract ────────────────────────────────────────────────

def test_missing_key_raises_not_silent_empty():
    """No API key must RAISE, never return {} (which reads as 'no earnings')."""
    import portfolio_options as po
    import os
    old = os.environ.get("FMP_API_KEY")
    os.environ["FMP_API_KEY"] = ""
    try:
        with pytest.raises(po.EarningsProviderError):
            po._get_earnings_dates(["AAPL"], ROOT)
    finally:
        if old is not None:
            os.environ["FMP_API_KEY"] = old


def test_http_403_raises(monkeypatch):
    """A 403 (the live FMP legacy-endpoint failure) must raise, not return {}."""
    import portfolio_options as po

    class Resp:
        ok = False
        status_code = 403
        text = '{"Error Message": "Legacy Endpoint : ... prior August 31, 2025"}'

    monkeypatch.setenv("FMP_API_KEY", "x" * 32)
    monkeypatch.setattr(po.requests, "get", lambda *a, **k: Resp())
    with pytest.raises(po.EarningsProviderError) as e:
        po._get_earnings_dates(["AAPL"], ROOT)
    assert "403" in str(e.value)


def test_successful_empty_response_is_not_an_error(monkeypatch):
    """Provider answered but nobody reports in 90d -> {} is legitimate."""
    import portfolio_options as po

    class Resp:
        ok = True
        status_code = 200
        text = "[]"

        def json(self):
            return []

    monkeypatch.setenv("FMP_API_KEY", "x" * 32)
    monkeypatch.setattr(po.requests, "get", lambda *a, **k: Resp())
    assert po._get_earnings_dates(["AAPL"], ROOT) == {}


# ── event gate fails CLOSED ────────────────────────────────────────────────

BLOCKING = ["covered_call", "cash_secured_put", "credit_spread", "long_call"]


@pytest.mark.parametrize("strategy", BLOCKING)
def test_provider_down_blocks_every_blocking_strategy(monkeypatch, strategy):
    import options_desk_enterprise as ent
    monkeypatch.setattr(ent, "earnings_calendar",
                        lambda syms: {s: ent.EARNINGS_UNKNOWN for s in syms})
    r = ent.earnings_blackout_check("AAPL", dte=30, strategy=strategy)
    assert r["in_blackout"] is True, f"{strategy} FAILED OPEN on unknown earnings timing"
    assert r["refusal_code"] == "EARNINGS_TIMESTAMP_UNKNOWN"
    assert r.get("data_blocked") is True


def test_unknown_sentinel_is_distinct_from_no_earnings():
    """'' (no scheduled earnings) and UNKNOWN (provider down) must not collide."""
    import options_desk_enterprise as ent
    assert ent.EARNINGS_UNKNOWN != ""
    assert ent.EARNINGS_UNKNOWN


def test_genuine_no_earnings_still_clears(monkeypatch):
    """A working provider reporting no earnings must NOT block — no over-blocking."""
    import options_desk_enterprise as ent
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {s: "" for s in syms})
    r = ent.earnings_blackout_check("AAPL", dte=30, strategy="covered_call")
    assert r["in_blackout"] is False
    assert "refusal_code" not in r


def test_non_blocking_strategy_unaffected(monkeypatch):
    """deep_itm_call is outside BLOCKING_STRATEGIES — the paper canary path."""
    import options_desk_enterprise as ent
    monkeypatch.setattr(ent, "earnings_calendar",
                        lambda syms: {s: ent.EARNINGS_UNKNOWN for s in syms})
    r = ent.earnings_blackout_check("RTX", dte=60, strategy="deep_itm_call")
    assert r["in_blackout"] is False


def test_earnings_inside_contract_still_blocks(monkeypatch):
    """The original blackout logic must survive the fail-closed patch."""
    import options_desk_enterprise as ent
    from datetime import date, timedelta
    soon = (date.today() + timedelta(days=5)).isoformat()
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {s: soon for s in syms})
    r = ent.earnings_blackout_check("AAPL", dte=30, strategy="covered_call")
    assert r["in_blackout"] is True
    assert r["days_to_earnings"] == 5


# ── registry reconciliation ────────────────────────────────────────────────

def test_screeners_yaml_declares_it_is_not_the_executor():
    """The dead-YAML warning must stay — re-adding screens there is a trap."""
    txt = (ROOT / "assets" / "screeners.yaml").read_text()
    assert "NOT THE EXECUTOR OF RECORD" in txt
    assert "finviz_screeners" in txt


def test_covered_call_screen_no_longer_claims_iv_rank():
    """Finviz's stock screener cannot filter IV rank; the claim was false."""
    import yaml
    d = yaml.safe_load((ROOT / "assets" / "screeners.yaml").read_text())
    desc = d["screeners"]["covered_call_candidates"]["description"]
    # The phrase may appear inside the correction note ("previously claimed
    # ...") — what must NOT survive is the claim presented as fact, i.e. the
    # description asserting the screen selects on IV rank.
    assert "cannot filter" in desc, "correction note missing"
    assert "UNAVAILABLE" in desc, "must state IV rank is unavailable, not proxied"
    assert not desc.strip().startswith("Established holdings with elevated IV rank")


def test_options_chain_provider_is_not_stale():
    """Registry must name the live Schwab chain, not NOT_CONFIGURED."""
    import yaml
    d = yaml.safe_load((ROOT / "config" / "candidate_sources.yaml").read_text())
    oc = d["sources"]["options_chain"]
    assert oc["provider"] != "NOT_CONFIGURED"
    assert "schwab" in str(oc["provider"]).lower()
    assert oc["status"] != "BLOCKED_PROVIDER_MISSING"


def test_reconciler_classifies_without_db(monkeypatch):
    """classify() is pure — verify the state machine independent of Postgres."""
    import finviz_registry_reconcile as fr
    from datetime import datetime, timezone, timedelta
    fresh = datetime.now(timezone.utc)

    st, _ = fr.classify("x", in_yaml=True, in_registry=True, db=None, mem=None)
    assert st == "ORPHANED"

    st, _ = fr.classify("x", in_yaml=False, in_registry=True,
                        db={"active": True, "last_run": fresh}, mem={"members": 10})
    assert st == "ACTIVE"

    st, _ = fr.classify("x", in_yaml=False, in_registry=False,
                        db={"active": True, "last_run": fresh}, mem={"members": 10})
    assert st == "SHADOW"

    stale = fresh - timedelta(days=5)
    st, _ = fr.classify("x", in_yaml=False, in_registry=True,
                        db={"active": True, "last_run": stale}, mem={"members": 3})
    assert st == "BROKEN"

    st, _ = fr.classify("x", in_yaml=False, in_registry=True,
                        db={"active": False, "last_run": fresh}, mem={"members": 3})
    assert st == "RETIRED_EVIDENCE"
