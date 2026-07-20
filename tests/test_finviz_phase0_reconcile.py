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
                        db={"active": True, "last_run": fresh}, mem={"historical": 10, "present_this_run": 10})
    assert st == "ACTIVE"

    st, _ = fr.classify("x", in_yaml=False, in_registry=False,
                        db={"active": True, "last_run": fresh}, mem={"historical": 10, "present_this_run": 10})
    assert st == "SHADOW"

    stale = fresh - timedelta(days=5)
    st, _ = fr.classify("x", in_yaml=False, in_registry=True,
                        db={"active": True, "last_run": stale}, mem={"historical": 3, "present_this_run": 3})
    assert st == "BROKEN"

    st, _ = fr.classify("x", in_yaml=False, in_registry=True,
                        db={"active": False, "last_run": fresh}, mem={"historical": 3, "present_this_run": 3})
    assert st == "RETIRED_EVIDENCE"


# ── earnings_provider: the replacement source of record ────────────────────

def test_provider_three_states_are_distinct():
    import earnings_provider as ep
    assert len({ep.SCHEDULED, ep.NONE_SCHEDULED, ep.UNKNOWN}) == 3


def test_stale_profile_row_is_unknown_not_none_scheduled(monkeypatch):
    """A profile last enriched long ago cannot certify 'nothing scheduled'."""
    import earnings_provider as ep
    from datetime import datetime, timezone, timedelta

    class Cur:
        def execute(self, *a, **k): pass
        def fetchall(self):
            old = datetime.now(timezone.utc) - timedelta(days=90)
            return [("AAPL", None, old)]

    monkeypatch.setattr(ep, "_conn", lambda: type("C", (), {"cursor": lambda s: Cur()})())
    got = ep._from_profiles(["AAPL"])["AAPL"]
    assert got.state == ep.UNKNOWN
    assert "stale" in got.reason


def test_fresh_profile_with_null_date_is_none_scheduled(monkeypatch):
    """Recently enriched + no date == provider looked and found nothing."""
    import earnings_provider as ep
    from datetime import datetime, timezone

    class Cur:
        def execute(self, *a, **k): pass
        def fetchall(self):
            return [("SCHD", None, datetime.now(timezone.utc))]

    monkeypatch.setattr(ep, "_conn", lambda: type("C", (), {"cursor": lambda s: Cur()})())
    got = ep._from_profiles(["SCHD"])["SCHD"]
    assert got.state == ep.NONE_SCHEDULED


def test_missing_profile_row_is_unknown(monkeypatch):
    import earnings_provider as ep

    class Cur:
        def execute(self, *a, **k): pass
        def fetchall(self): return []

    monkeypatch.setattr(ep, "_conn", lambda: type("C", (), {"cursor": lambda s: Cur()})())
    got = ep._from_profiles(["ZZZZ"])["ZZZZ"]
    assert got.state == ep.UNKNOWN


def test_db_failure_is_unknown_never_clearing(monkeypatch):
    """A DB outage must not read as 'no earnings' for every symbol."""
    import earnings_provider as ep

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(ep, "_conn", boom)
    got = ep._from_profiles(["AAPL", "MSFT"])
    assert all(i.state == ep.UNKNOWN for i in got.values())


def test_days_until_only_for_scheduled():
    import earnings_provider as ep
    from datetime import date, timedelta
    d = date.today() + timedelta(days=4)
    assert ep.EarningsInfo("X", ep.SCHEDULED, date=d).days_until() == 4
    assert ep.EarningsInfo("X", ep.NONE_SCHEDULED).days_until() is None
    assert ep.EarningsInfo("X", ep.UNKNOWN).days_until() is None


# ── P0.1: malformed earnings values must fail CLOSED ───────────────────────

MALFORMED = [
    ("garbage", "not a date at all"),
    ("2026-13-45", "impossible date"),
    ("07/21/2026", "unsupported format"),
    ("Jul 21 2026", "human format"),
    (12345, "non-string numeric"),
    (["2026-07-21"], "non-string container"),
    ({"date": "2026-07-21"}, "dict payload"),
    ("2026-07", "partial date"),
]


@pytest.mark.parametrize("bad,label", MALFORMED)
def test_malformed_earnings_value_fails_closed(monkeypatch, bad, label):
    """Unparseable timing is UNKNOWN, never proof that no event exists."""
    import options_desk_enterprise as ent
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {s: bad for s in syms})
    r = ent.earnings_blackout_check("AAPL", dte=30, strategy="covered_call")
    assert r["in_blackout"] is True, f"FAILED OPEN on {label}: {bad!r}"
    assert r["refusal_code"] == "EARNINGS_TIMESTAMP_INVALID"
    assert r.get("data_blocked") is True


def test_real_date_object_is_accepted(monkeypatch):
    """A datetime.date (not just an ISO string) must still parse normally."""
    import options_desk_enterprise as ent
    from datetime import date, timedelta
    d = date.today() + timedelta(days=3)
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {s: d for s in syms})
    r = ent.earnings_blackout_check("AAPL", dte=30, strategy="covered_call")
    assert r["in_blackout"] is True
    assert r["days_to_earnings"] == 3
    assert "refusal_code" not in r        # a real blackout, not a data defect


# ── P0.1: specific refusal codes survive to the top level ──────────────────

@pytest.mark.parametrize("sentinel,expected", [
    ("UNKNOWN", "EARNINGS_TIMESTAMP_UNKNOWN"),
    ("garbage-date", "EARNINGS_TIMESTAMP_INVALID"),
])
def test_hard_block_preserves_specific_refusal_code(monkeypatch, sentinel, expected):
    """evaluate_hard_risk_blocks must not flatten these to 'earnings_blackout'."""
    import options_desk_enterprise as ent
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {s: sentinel for s in syms})
    blocks = ent.evaluate_hard_risk_blocks(
        {"symbol": "AAPL", "strategy": "covered_call", "dte": 30, "contracts": 1})
    codes = [b.get("code") for b in blocks]
    assert expected in codes, f"specific code lost; got {codes}"


def test_genuine_blackout_keeps_generic_code(monkeypatch):
    """A real scheduled blackout stays 'earnings_blackout' — codes stay distinguishable."""
    import options_desk_enterprise as ent
    from datetime import date, timedelta
    soon = (date.today() + timedelta(days=4)).isoformat()
    monkeypatch.setattr(ent, "earnings_calendar", lambda syms: {s: soon for s in syms})
    blocks = ent.evaluate_hard_risk_blocks(
        {"symbol": "AAPL", "strategy": "covered_call", "dte": 30, "contracts": 1})
    codes = [b.get("code") for b in blocks]
    assert "earnings_blackout" in codes
    assert "EARNINGS_TIMESTAMP_UNKNOWN" not in codes
    assert "EARNINGS_TIMESTAMP_INVALID" not in codes
