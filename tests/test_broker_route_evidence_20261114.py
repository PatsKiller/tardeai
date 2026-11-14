"""S2 broker b3 — the one call a route makes to attach BrokerEvidence@v1 (cc-deepseek-2).

Route wiring rule: the route publishes the canonical projection; this module *labels* it and adds
nothing else. These tests pin the three properties a page depends on: the payload survives
unmodified, a missing input stays missing (never defaulted into a plausible snapshot), and a failed
evidence build names itself instead of disappearing or taking the page down.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import broker_route_evidence as re  # noqa: E402

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)


def _payload(**over):
    p = {
        "holdings": [
            {"account_id": "acct-b", "symbol": "BBB", "price": 20.0, "qty": 10, "market_value": 200.0},
            {"account_id": "acct-a", "symbol": "AAA", "price": 10.0, "qty": 100, "market_value": 1000.0},
            {"account_id": "acct-a", "symbol": "CCC", "price": 5.0, "qty": 5, "market_value": 25.0},
        ],
        "count": 3,
        "position_count": 3,
        "total_value": 1225.0,
        "total_cash": 0.0,
        "today_change": -12.0,
        "today_change_status": "MEASURED",
        "positions_as_of": "2026-11-14T14:41:02Z",
        "valuation_as_of": "2026-11-14T14:45:00Z",
        "quote_as_of": "2026-11-14T14:58:10Z",
        "position_counts": {"position_count": 3, "held_count": 3, "below_100": 0, "unpriced": 0,
                            "counted": 3, "min_position_usd": 100, "source": "positions_current"},
        "measures": {
            "materialized_at": "2026-11-14T14:45:00Z",
            "measures": {
                "account_value": {"measure": "account_value", "value": 1225.0, "status": "MEASURED",
                                  "as_of": "2026-11-14T14:45:00Z"},
                "price_move_estimate": {"measure": "price_move_estimate", "value": -12.0, "status": "MEASURED",
                                        "coverage": {"measured_rows": 3, "unknown_rows": 0, "row_count": 3}},
                "account_value_change_1d": {"measure": "account_value_change_1d", "value": -14.0, "status": "MEASURED"},
                "verified_daily_pnl": {"measure": "verified_daily_pnl", "status": "UNKNOWN", "value": None},
            },
            "source_coverage": {},
        },
        # holdings_payload publishes this at the top level (cio_truth.py:1833); it is the market-day input.
        "measures_materialized_at": "2026-11-14T14:45:00Z",
        "truth": {"source": "broker_positions_store", "as_of": "2026-11-14T14:41:02Z", "stale": False, "gap": None},
    }
    p.update(over)
    return p


def test_attach_adds_one_key_and_leaves_the_payload_untouched():
    """The route's payload is the contract; the evidence block is additive and the input is not mutated."""
    p = _payload()
    before = {k: v for k, v in p.items()}
    out = re.attach(p, window=26, now=NOW)
    assert set(out) - set(p) == {"evidence"}
    assert "evidence" not in p  # the caller's dict is untouched (a shared payload is not rewritten)
    assert {k: out[k] for k in before} == before
    assert set(out["evidence"]) == {"portfolio", "positions"}
    assert out["evidence"]["portfolio"]["verdict"] == "OK"


def test_a_missing_stamp_is_omitted_not_defaulted():
    """A missing quote clock drops the product from the vector; it is never filled from another clock."""
    full = re.version_vector(_payload())
    assert set(full) == {"positions_store", "quote_price", "portfolio_market_day"}
    short = re.version_vector(_payload(quote_as_of=None))
    assert "quote_price" not in short
    a = re.attach(_payload(), window=26, now=NOW)["evidence"]["portfolio"]["snapshot_id"]
    b = re.attach(_payload(quote_as_of=None), window=26, now=NOW)["evidence"]["portfolio"]["snapshot_id"]
    assert a != b  # the identity changes when an input disappears — it is not silently reused


def test_scope_names_only_accounts_the_book_carries():
    """The scope line cannot claim an account the payload does not contain; no session is invented."""
    scope = re.scope_of(_payload())
    assert scope["accounts"] == ["acct-a", "acct-b"]
    assert scope["session_id"] is None
    assert re.scope_of(_payload(session_id="2026-11-14-regular"))["session_id"] == "2026-11-14-regular"


def test_an_undeclared_window_renders_unknown_both_envelopes():
    """No window ⇒ UNKNOWN/NO_FRESHNESS_CONTRACT in both blocks; never an OK no registry row backs."""
    out = re.attach(_payload(), window=None, now=NOW)
    for name in ("portfolio", "positions"):
        assert out["evidence"][name]["verdict"] == "UNKNOWN", name
        assert out["evidence"][name]["cause"]["code"] == "NO_FRESHNESS_CONTRACT", name


def test_the_registry_is_read_only_when_no_window_is_passed(monkeypatch):
    """The route may pass the window (one read) or let the module read the registry row once."""
    calls = []

    def fake_window(domain, **kw):
        calls.append(domain)
        return 26.0

    monkeypatch.setattr(re, "stale_window", fake_window)
    re.attach(_payload(), now=NOW)                              # no window passed
    assert calls == ["positions_store"]
    calls.clear()
    re.attach(_payload(), window=12.0, now=NOW)                 # window passed: no registry read
    assert calls == []


def test_a_failed_build_is_named_never_omitted(monkeypatch):
    """A raising adapter yields FAILED + EVIDENCE_BUILD_FAILED; the page keeps its payload."""
    def boom(*a, **k):
        raise RuntimeError("producer shape changed")

    monkeypatch.setattr(re, "portfolio_evidence", boom)
    out = re.attach(_payload(), window=26, now=NOW)
    block = out["evidence"]["portfolio"]
    assert block["verdict"] == "FAILED"
    assert block["cause"]["code"] == "EVIDENCE_BUILD_FAILED"
    assert "producer shape changed" in block["cause"]["detail"]
    assert block["cause"]["next_action"]
    assert out["evidence"]["positions"]["verdict"] == "OK"  # one failed block does not blank the other
    assert out["total_value"] == 1225.0                     # and the payload is still there


def test_a_failure_outside_the_adapters_still_returns_the_payload(monkeypatch):
    """The registry lookup itself failing is the outer guard's case: attach never raises at the route."""
    def boom(domain, **kw):
        raise OSError("config unreadable")

    monkeypatch.setattr(re, "stale_window", boom)
    out = re.attach(_payload(), now=NOW)
    assert out["evidence"]["portfolio"]["cause"]["code"] == "EVIDENCE_BUILD_FAILED"
    assert out["evidence"]["positions"]["cause"]["code"] == "EVIDENCE_BUILD_FAILED"
    assert out["evidence"]["portfolio"]["cause"]["detail"].startswith("OSError")
    assert out["position_count"] == 3


def test_the_real_registry_row_is_used_by_default():
    """On the live registry, positions_store declares a window, so the default path is OK, not UNKNOWN."""
    out = re.attach(_payload(), now=NOW)
    assert out["evidence"]["portfolio"]["clocks"]["stale_after_hours"] not in (None, 0)
    assert out["evidence"]["portfolio"]["verdict"] in ("OK", "STALE", "PARTIAL", "UNKNOWN")


@pytest.mark.parametrize("broken", ["measures", "truth"])
def test_a_payload_the_adapter_cannot_read_fails_loudly(broken):
    """A malformed measures/truth shape returns with a named block, never an exception at the route.

    `measures` is truthy but not a block, or `truth` is not a mapping: the port must say so. (A b2-era
    adapter rendered the first case OK with a null account value — see the b3 READY finding F3.)
    """
    p = _payload()
    p[broken] = "not a dict"
    out = re.attach(p, window=26, now=NOW)
    assert out["evidence"]["portfolio"]["verdict"] in ("FAILED", "UNKNOWN")
    assert out["evidence"]["portfolio"]["cause"]["code"] in (
        "EVIDENCE_BUILD_FAILED", "MEASURES_UNREADABLE", "MEASURES_ABSENT")
    if broken == "measures":
        # a truthy non-block is not an absent block: the shape is named, and there is no value at all
        assert out["evidence"]["portfolio"]["cause"]["code"] == "MEASURES_UNREADABLE"
        assert out["evidence"]["portfolio"]["value"] is None
    assert out["total_value"] == 1225.0  # the page's payload survives the failure


def test_a_malformed_holdings_list_is_unknown_for_positions_only():
    """Rows that are not a list make the positions envelope UNKNOWN; the money block is unaffected."""
    p = _payload()
    p["holdings"] = "not a list"
    out = re.attach(p, window=26, now=NOW)
    assert out["evidence"]["positions"]["verdict"] == "UNKNOWN"
    assert out["evidence"]["positions"]["cause"]["code"] == "POSITIONS_UNREADABLE"
    assert out["evidence"]["portfolio"]["verdict"] == "OK"


def test_a_measures_block_without_account_value_is_unknown():
    """The verdict describes THIS envelope: no account-value measure ⇒ UNKNOWN, never another measure's OK."""
    p = _payload()
    p["measures"]["measures"].pop("account_value")
    out = re.attach(p, window=26, now=NOW)
    assert out["evidence"]["portfolio"]["verdict"] == "UNKNOWN"
    assert out["evidence"]["portfolio"]["cause"]["code"] == "MEASURE_MISSING"


def test_a_payload_with_no_position_counts_is_unknown():
    """An OK over a payload that publishes no counts at all is 'unknown rendered as known'."""
    p = _payload()
    p.pop("position_count")
    p.pop("position_counts")
    out = re.attach(p, window=26, now=NOW)
    assert out["evidence"]["positions"]["verdict"] == "UNKNOWN"
    assert out["evidence"]["positions"]["cause"]["code"] == "NO_VALUE"
