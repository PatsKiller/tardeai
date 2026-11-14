"""SPRINT 8H-2 b1 — the shared evidence/snapshot contract (cc-deepseek-2).

Package §4 requires one canonical read model per domain that binds every payload to a
``snapshot_id``/input version vector and a declared scope, while keeping ``source_as_of``,
``built_at``, ``checked_at``, ``served_at``, ``stale_after``, ``expires_at`` and ``session_id``
DISTINCT: "A fresh wrapper/build cannot rejuvenate stale contents." The existing
``BrokerReadEnvelope@v1`` (``scripts/lib/data_broker/envelope.py``, 250 call sites) carries only
``as_of``/``age_hours``/``stale`` and stays the wire shape for existing consumers; this contract is
additive beside it and can be rendered back to it.

Every test pins ONE property, named in its docstring, and the mutants that would break it are noted
so a reviewer can reproduce the teeth.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import broker_contract as bc  # noqa: E402

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
SCOPE = {"accounts": ["acct-a"], "session_id": "2026-11-14-regular", "cutoff": "2026-11-14T14:30:00Z"}
VERSIONS = {"positions_store": "2026-11-14T14:41:02Z", "quote_price": "2026-11-14T14:58:10Z"}


def _evidence(**kw):
    args = dict(
        domain="positions_store",
        verdict="OK",
        versions=VERSIONS,
        scope=SCOPE,
        source_as_of="2026-11-14T14:41:02Z",
        built_at=NOW,
        checked_at=NOW,
        served_at=NOW,
        stale_after_hours=26,
        session_id="2026-11-14-regular",
        now=NOW,
    )
    args.update(kw)
    return bc.build_evidence(**args)


def test_snapshot_id_is_stable_and_input_sensitive():
    """Same versions+scope ⇒ one identity; any input version changing ⇒ a new identity."""
    a = _evidence()
    b = _evidence(served_at=NOW + timedelta(minutes=5))
    assert a["snapshot_id"] == b["snapshot_id"]  # serving later is not a new snapshot
    assert a["snapshot_id"].startswith("snap_")
    c = _evidence(versions={**VERSIONS, "quote_price": "2026-11-14T14:59:00Z"})
    assert c["snapshot_id"] != a["snapshot_id"]
    d = _evidence(scope={**SCOPE, "accounts": ["acct-a", "acct-b"]})
    assert d["snapshot_id"] != a["snapshot_id"]


def test_seven_clocks_stay_distinct():
    """built_at/checked_at/served_at are never folded into source_as_of."""
    e = _evidence()
    clocks = e["clocks"]
    assert clocks["source_as_of"] == "2026-11-14T14:41:02Z"
    assert clocks["built_at"] == NOW.isoformat()
    assert clocks["checked_at"] == NOW.isoformat()
    assert clocks["served_at"] == NOW.isoformat()
    assert clocks["session_id"] == "2026-11-14-regular"
    assert clocks["stale_after_hours"] == 26
    assert clocks["expires_at"] is None
    for k in ("source_as_of", "built_at", "checked_at", "served_at", "stale_after_hours", "expires_at", "session_id"):
        assert k in clocks


def test_fresh_build_cannot_rejuvenate_stale_source():
    """A build at NOW over a 3-day-old source is STALE, however recently it was assembled."""
    e = _evidence(domain="quote_price", source_as_of="2026-11-11T15:00:00Z", stale_after_hours=26)
    assert e["verdict"] == "STALE"
    assert e["clocks"]["source_as_of"] == "2026-11-11T15:00:00Z"
    assert e["gap"]["kind"] == "stale"


def test_future_observation_is_refused():
    """An observation timestamp after the evaluation clock is invalid evidence, not freshness."""
    with pytest.raises(ValueError, match="future"):
        _evidence(source_as_of="2026-11-14T19:00:00Z")
    # and it is never silently coerced to OK at read time
    with pytest.raises(ValueError):
        bc.validate(_evidence() | {"clocks": _evidence()["clocks"] | {"source_as_of": "2026-11-14T19:00:00Z"}}, now=NOW)


def test_future_event_time_stays_an_event_time():
    """A scheduled event (an expiry, a session open) may be in the future and is not an observation."""
    e = _evidence(kind="event", source_as_of="2026-11-14T21:00:00Z", verdict="OK")
    assert e["clocks"]["source_as_of"] == "2026-11-14T21:00:00Z"
    assert e["kind"] == "event"


def test_unknown_value_never_becomes_zero():
    """A missing value with an OK verdict is a fabrication; it must render UNKNOWN."""
    e = _evidence(verdict="OK", value=None, completeness={"counted": 0, "total": 0, "exclusions": []})
    assert e["verdict"] == "UNKNOWN"
    assert e["value"] is None
    assert e["cause"]["code"] == "NO_VALUE"


def test_partial_coverage_is_named_with_exclusions():
    """Partial coverage names what is missing, never a quiet total."""
    e = _evidence(
        verdict="PARTIAL",
        value={"total_usd": 1255586.0},
        completeness={"counted": 28, "total": 33, "exclusions": [{"reason": "unpriced", "count": 5}]},
    )
    assert e["verdict"] == "PARTIAL"
    assert e["completeness"]["counted"] == 28 and e["completeness"]["total"] == 33
    assert e["completeness"]["exclusions"][0]["count"] == 5


def test_reconciliation_residual_within_tolerance():
    """HQ-07/PR-007: rows and headline reconcile at published precision, or expose the bridge."""
    out = bc.reconcile(
        headline_cents=-345700,
        rows=[("acct-a", -300000), ("acct-b", -45600)],
        tolerance_cents=300,
    )
    assert out["residual_cents"] == 100  # sum(-345600) - headline(-345700)
    assert out["verdict"] == "ARITHMETIC_OK"
    bad = bc.reconcile(headline_cents=-345700, rows=[("acct-a", -300000), ("acct-b", -45600), ("acct-c", -200)], tolerance_cents=50)
    assert bad["verdict"] == "ARITHMETIC_RESIDUAL"
    assert bad["residual_cents"] == -100  # sum(-345800) - headline(-345700)


def test_reconciliation_incomplete_never_fabricates_a_residual():
    """A missing contributor leaves the bridge INCOMPLETE with residual None — no invented number."""
    out = bc.reconcile(headline_cents=-345700, rows=[("acct-a", -300000), ("acct-b", None)], tolerance_cents=300)
    assert out["verdict"] == "INCOMPLETE"
    assert out["residual_cents"] is None


def test_verified_pnl_needs_signed_evidence():
    """Two agreeing candidate numbers never make P&L verified; a signed reconciliation does."""
    unverified = bc.pnl(price_move_cents=-345700, account_change_cents=-345800)
    assert unverified["verified"] is False
    assert unverified["basis"] == "price_move"
    assert "signed" in unverified["reason"]
    # the trap the capture sets: two candidate numbers that AGREE are still not a verified result
    agreeing = bc.pnl(price_move_cents=-345700, account_change_cents=-345700)
    assert agreeing["verified"] is False
    assert agreeing["basis"] == "price_move"
    verified = bc.pnl(
        price_move_cents=-345700,
        account_change_cents=-345700,
        sign_off={"reconciliation_id": "rec_20261114_01", "signed_at": "2026-11-14T22:00:00Z", "by": "operator"},
    )
    assert verified["verified"] is True
    assert verified["reconciliation_id"] == "rec_20261114_01"


def test_absent_broker_source_never_makes_a_plan_authoritative():
    """b1r2 F1: with no broker answer, authority is None / UNKNOWN / NO_AUTHORITY_SOURCE — the plan is a facet."""
    resolved = bc.resolve_authority(
        domain="protection",
        candidates=[{"source": "plan_store", "state": "PLANNED", "value": 63.66}],
    )
    assert resolved["authority"] is None
    assert resolved["state"] == "UNKNOWN"
    assert resolved["value"] is None
    assert resolved["cause"]["code"] == "NO_AUTHORITY_SOURCE"
    assert resolved["plan"] == {"source": "plan_store", "value": 63.66}  # visible, never the claim
    empty = bc.resolve_authority(domain="protection", candidates=[])
    assert empty["authority"] is None and empty["plan"] is None
    assert empty["cause"]["code"] == "NO_AUTHORITY_SOURCE"


def test_validate_accepts_every_envelope_build_produces():
    """b1r2 F2: the safety rules beat a caller cause — build's output always passes validate()."""
    caller = {"code": "CALLER_SUPPLIED", "detail": "this caller cause must not license an OK", "owner": None,
              "next_action": None}
    cases = [
        dict(value=None, cause=caller),                              # caller cause on the fabricated-zero path
        dict(value=None),                                            # the fabricated-zero path itself
        dict(stale_after_hours=None, cause=caller),                  # caller cause on the no-window path
        dict(stale_after_hours=None),                                # no window at all
        dict(stale_after_hours=None, on_demand=True),                # on-demand: no claim without a window
        dict(kind="event", source_as_of="2026-11-14T21:00:00Z", stale_after_hours=None, on_demand=True),
    ]
    for kw in cases:
        e = _evidence(**kw)
        assert bc.validate(e, now=NOW)["schema"] == bc.SCHEMA
        assert e["verdict"] != "OK"
    on_demand = _evidence(stale_after_hours=None, on_demand=True)
    assert on_demand["verdict"] == "UNKNOWN"
    assert on_demand["cause"]["code"] == "ON_DEMAND"


def test_plan_never_promotes_unknown_protection():
    """PR-017/PR-018: a locally stored plan is not broker evidence and cannot clear UNKNOWN."""
    resolved = bc.resolve_authority(
        domain="protection",
        candidates=[
            {"source": "plan_store", "state": "PLANNED", "value": 63.66},
            {"source": "broker_order_receipts", "state": "UNKNOWN", "value": None},
        ],
    )
    assert resolved["authority"] == "broker_order_receipts"
    assert resolved["state"] == "UNKNOWN"
    assert resolved["plan"] == {"source": "plan_store", "value": 63.66}
    # the plan remains visible as a separate facet, never as the protection verdict
    assert resolved["value"] is None


def test_unregistered_domain_cannot_claim_freshness():
    """A domain with no registry row has no stale window: it is UNKNOWN, never OK-by-default."""
    gaps = bc.registry_gaps(
        required=["portfolio", "incidents", "health", "positions_store"],
        registry={"positions_store": {"stale_after_hours": 26}},
    )
    assert gaps == ["portfolio", "incidents", "health"]
    e = _evidence(domain="portfolio", stale_after_hours=None)
    assert e["verdict"] == "UNKNOWN"
    assert e["cause"]["code"] == "NO_FRESHNESS_CONTRACT"


def test_read_envelope_v1_keys_are_preserved():
    """Backward compatibility: the existing BrokerReadEnvelope@v1 shape renders from the contract."""
    e = _evidence()
    v1 = bc.to_read_envelope(e)
    for k in ("schema", "as_of", "age_hours", "source", "stale", "stale_after_hours"):
        assert k in v1
    assert v1["schema"] == "BrokerReadEnvelope@v1"
    assert v1["as_of"] == "2026-11-14T14:41:02Z"
    lifted = bc.from_read_envelope(
        v1, domain="positions_store", scope=SCOPE, versions=VERSIONS, built_at=NOW, now=NOW
    )
    assert lifted["clocks"]["source_as_of"] == v1["as_of"]
    assert lifted["snapshot_id"] == e["snapshot_id"]
