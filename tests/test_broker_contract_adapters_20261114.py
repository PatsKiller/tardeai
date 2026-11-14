"""SPRINT 8H-2 b2 — adapters that lift an existing payload into the shared envelope (cc-deepseek-2).

The rule these tests enforce: an adapter **lifts and labels**, it never recomputes an authoritative
metric. The payload already carries its measures (``scripts/lib/portfolio_measures.py``), its
coverage, its stored reconciliation and its truth block; the adapter's job is to put them under one
``snapshot_id`` and seven distinct clocks so Portfolio, Risk, Home and any CSV cite the same value.

The fixtures are shaped from the keys ``cio_truth.holdings_payload`` actually publishes
(``measures``, ``reconciliation``, ``source_coverage``, ``truth``, ``position_counts``) — synthetic
numbers only (the repo is public).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib import broker_contract as bc  # noqa: E402
from lib import broker_contract_adapters as ad  # noqa: E402

NOW = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
SCOPE = {"accounts": ["acct-a"], "session_id": "2026-11-14-regular", "cutoff": "2026-11-14T14:30:00Z"}
VERSIONS = {"positions_store": "2026-11-14T14:41:02Z", "quote_price": "2026-11-14T14:58:10Z", "portfolio_market_day": "2026-11-14T14:30:00Z"}


def _payload(*, status="MEASURED", verified_status="UNKNOWN", verified_source=None, reconciliation=None):
    verified = {"measure": "verified_daily_pnl", "status": verified_status, "value": None, "as_of": None, "source": None}
    if verified_status == "VERIFIED":
        verified.update(value=-123.45, as_of="2026-11-13T20:00:00Z", source=verified_source)
    return {
        # one sample row; the count contract below is synthetic and internally consistent (11 + 3 = 14)
        "holdings": [{"account_id": "acct-a", "symbol": "AAA", "price": 10.0, "qty": 100}],
        "count": 11,
        "position_count": 11,
        "total_value": 1000000.0,
        "total_cash": 250000.0,
        "today_change": -123.45,
        "today_change_status": status,
        "positions_as_of": "2026-11-14T14:41:02Z",
        "valuation_as_of": "2026-11-14T14:45:00Z",
        "quote_as_of": "2026-11-14T14:58:10Z",
        # the count contract's own shape (scripts/lib/position_count_authority.py): the headline, every
        # held position, and the named difference between them. Synthetic numbers.
        "position_counts": {"position_count": 11, "held_count": 14, "below_100": 3, "unpriced": 0,
                            "counted": 11, "min_position_usd": 100, "source": "positions_current",
                            "summary": "11 positions at or above $100 · 3 held under $100"},
        "measures": {
            "materialized_at": "2026-11-14T14:45:00Z",
            "measures": {
                "account_value": {"measure": "account_value", "value": 1000000.0, "status": status,
                                  "as_of": "2026-11-14T14:45:00Z", "rows": 30},
                "price_move_estimate": {"measure": "price_move_estimate", "value": -123.45, "status": status,
                                        "coverage": {"measured_rows": 28, "unknown_rows": 5, "row_count": 33,
                                                     "unknown": ["ZZZ"]},
                                        "gap": {"reason": "some rows unmeasured"}},
                "account_value_change_1d": {"measure": "account_value_change_1d", "value": -234.56,
                                            "status": "MEASURED",
                                            "start": {"equity_usd": 1000234.56, "as_of": "2026-11-13T20:00:00Z"}},
                "verified_daily_pnl": verified,
            },
            # source_coverage is a dict of NAMED sources ({observed, source, reason, rows}) — the
            # producer's shape (scripts/lib/portfolio_measures.py), never a counted/total pair.
            "reconciliation": reconciliation,
            "source_coverage": {
                "prior_close_book": {"observed": True, "source": "positions_store", "rows": 33, "reason": None},
                "income": {"observed": False, "source": None, "rows": None,
                           "reason": "no income source is bound"},
            },
        },
        "reconciliation": reconciliation,
        "reconciliation_status": ((reconciliation or {}).get("total") or {}).get("status"),
        "measures_materialized_at": "2026-11-14T14:45:00Z",
        "source_coverage": {"income": {"observed": False, "source": None, "rows": None,
                                       "reason": "no income source is bound"}},
        "truth": {"source": "broker_positions_store", "as_of": "2026-11-14T14:41:02Z", "stale": False, "gap": None},
    }


def test_measured_book_is_ok_with_snapshot_id_and_clocks():
    """A fully measured book is OK, and its envelope carries one snapshot id over the input versions."""
    e = ad.portfolio_evidence(_payload(), versions=VERSIONS, scope=SCOPE, stale_after_hours=26, now=NOW)
    assert e["verdict"] == "OK"
    assert e["snapshot_id"] == bc.snapshot_id(VERSIONS, SCOPE)
    assert e["clocks"]["source_as_of"] == "2026-11-14T14:41:02Z"  # the source clock, not the valuation clock
    for k in bc.CLOCK_FIELDS:
        assert k in e["clocks"]


def test_partial_book_names_its_exclusions():
    """A PARTIAL book must say what is missing; a bare percentage is not coverage."""
    e = ad.portfolio_evidence(_payload(status="PARTIAL"), versions=VERSIONS, scope=SCOPE, stale_after_hours=26, now=NOW)
    assert e["verdict"] == "PARTIAL"
    assert e["completeness"]["counted"] == 28
    assert e["completeness"]["total"] == 33
    assert e["completeness"]["exclusions"]  # the gap is named, not dropped


def test_unknown_measures_never_render_ok():
    """No measures block ⇒ UNKNOWN with a named cause, never OK and never a zero."""
    p = _payload()
    p.pop("measures")
    e = ad.portfolio_evidence(p, versions=VERSIONS, scope=SCOPE, stale_after_hours=26, now=NOW)
    assert e["verdict"] == "UNKNOWN"
    assert e["value"] is None
    assert e["cause"]["code"] in ("NO_VALUE", "MEASURES_ABSENT")


def test_price_move_and_account_change_stay_distinct_measures():
    """HQ-07: the price move and the account change are two typed measures, never merged into one number."""
    e = ad.portfolio_evidence(_payload(), versions=VERSIONS, scope=SCOPE, stale_after_hours=26, now=NOW)
    blocks = e["value"]
    assert blocks["price_move"]["cents"] == -12345
    assert blocks["account_change_1d"]["cents"] == -23456
    assert blocks["price_move"]["measure"] != blocks["account_change_1d"]["measure"]


def test_verified_pnl_requires_a_signed_reconciliation():
    """A VERIFIED status with no stored record identity is not verification; the adapter never upgrades it."""
    e = ad.portfolio_evidence(_payload(verified_status="VERIFIED"), versions=VERSIONS, scope=SCOPE,
                              stale_after_hours=26, now=NOW)
    assert e["value"]["verified_pnl"]["verified"] is False  # value, but no stored source/as_of
    ok = ad.portfolio_evidence(_payload(verified_status="VERIFIED", verified_source="operator"),
                               versions=VERSIONS, scope=SCOPE, stale_after_hours=26, now=NOW)
    assert ok["value"]["verified_pnl"]["verified"] is True
    assert ok["value"]["verified_pnl"]["reconciliation_id"] == "stored:operator@2026-11-13T20:00:00Z"


def test_stored_reconciliation_is_lifted_not_recomputed():
    """The stored bridge passes through unchanged; the adapter adds no residual of its own."""
    stored = {"total": {"status": "SIGNED", "residual_cents": 0},
              "accounts": [{"account": "acct-a", "cents": -12000}, {"account": "acct-b", "cents": -6410}]}
    e = ad.portfolio_evidence(_payload(reconciliation=stored), versions=VERSIONS, scope=SCOPE,
                              stale_after_hours=26, now=NOW)
    assert e["value"]["reconciliation"] == stored
    assert e["value"]["reconciliation"]["total"]["residual_cents"] == 0


def test_positions_evidence_lifts_counts_without_reclassifying():
    """The count contract is the payload's; the adapter never re-derives the $100 rule (review F-B2-2).

    Four separate facts, each asserted: the headline count, the contract lifted verbatim, the
    completeness census the envelope publishes, and the named exclusion for the held-under-floor rows.
    """
    e = ad.positions_evidence(_payload(), versions=VERSIONS, scope=SCOPE, stale_after_hours=26, now=NOW)
    assert e["value"]["position_count"] == 11                      # the headline, as published
    assert e["value"]["position_counts"] == _payload()["position_counts"]  # the whole contract, verbatim
    assert e["completeness"]["counted"] == 11                       # what the headline counts
    assert e["completeness"]["total"] == 14                         # every held position
    assert e["completeness"]["exclusions"] == [
        {"reason": "held under $100: listed, not counted", "count": 3}]
    assert e["verdict"] == "OK"


def test_stale_window_reads_an_explicit_registry(tmp_path):
    """``registry_path=`` makes the parser testable off the live config (cc-deepseek-8 observation 1.2)."""
    good = tmp_path / "auth.json"
    good.write_text(json.dumps({"domains": [{"domain": "demo_store", "stale_after_hours": 7}]}), encoding="utf-8")
    assert ad.stale_window("demo_store", registry_path=good) == 7.0
    assert ad.stale_window("no_such_domain", registry_path=good) is None
    assert ad.stale_window("demo_store", registry_path=tmp_path / "missing.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert ad.stale_window("demo_store", registry_path=broken) is None   # unreadable ⇒ UNKNOWN, never a guess


def test_unobserved_source_is_a_named_exclusion():
    """An input source the producer could not read is named in exclusions — never a silent gap."""
    e = ad.portfolio_evidence(_payload(), versions=VERSIONS, scope=SCOPE, stale_after_hours=26, now=NOW)
    named = [x for x in e["completeness"]["exclusions"] if x.get("source") == "income"]
    assert named and "no income source is bound" in named[0]["reason"]


#: Domains a page serves that still have NO registry row. An approved `domains[]` row requires an
#: OPERATOR grant (`approved_by == "operator"` plus a reference naming a PR — asserted by
#: tests/test_data_source_authority_20260913.py:185-203), which no sprint ruling can supply. So the
#: five rows ship as a proposal for the operator's grant, and this list is the gate: the moment a
#: row lands it must be deleted here, and a NEW served domain without a row turns this test red.
PENDING_REGISTRY_GRANT = {"portfolio_summary", "incidents", "protection", "gates", "lane_health"}


def test_every_domain_a_page_serves_has_a_stale_window_or_is_a_named_pending_grant():
    """Lead ruling: a served domain must have a declared window — or be a named, pending operator grant."""
    registry = {d["domain"]: d for d in json.loads(
        (ROOT / "config" / "data_source_authority.json").read_text(encoding="utf-8"))["domains"]}
    gaps = set(bc.registry_gaps(required=list(ad.SERVED_DOMAINS), registry=registry))
    assert gaps <= PENDING_REGISTRY_GRANT, f"served domain with no window and no pending grant: {gaps - PENDING_REGISTRY_GRANT}"
    for name in ad.SERVED_DOMAINS:
        if name in PENDING_REGISTRY_GRANT:
            assert ad.stale_window(name) is None or registry[name].get("stale_after_hours") is not None
            continue
        assert registry[name].get("stale_after_hours") is not None, name
        assert ad.stale_window(name) == float(registry[name]["stale_after_hours"])
    assert ad.stale_window("positions_store") is not None  # the one my adapters already rely on
    assert ad.stale_window("no_such_domain") is None


def test_a_failed_producer_renders_failed_not_ok():
    """Failure state: a producer that reports FAILED keeps its value visible and never renders OK."""
    e = ad.portfolio_evidence(_payload(status="FAILED"), versions=VERSIONS, scope=SCOPE, stale_after_hours=26, now=NOW)
    assert e["verdict"] == "FAILED"
    assert e["value"]["account_value"]["status"] == "FAILED"


def test_an_undeclared_window_is_unknown_not_ok():
    """No explicit stale window and no registry row ⇒ UNKNOWN/NO_FRESHNESS_CONTRACT (never OK by default)."""
    e = ad.portfolio_evidence(_payload(), versions=VERSIONS, scope=SCOPE, stale_after_hours=None, now=NOW)
    assert e["verdict"] == "UNKNOWN"
    assert e["cause"]["code"] == "NO_FRESHNESS_CONTRACT"


def test_stale_source_makes_every_block_stale():
    """A stale positions read makes the whole envelope STALE even when measures were just materialized."""
    p = _payload()
    p["truth"]["as_of"] = "2026-11-11T14:41:02Z"
    p["positions_as_of"] = "2026-11-11T14:41:02Z"
    e = ad.portfolio_evidence(p, versions=VERSIONS, scope=SCOPE, stale_after_hours=26, now=NOW)
    assert e["clocks"]["source_as_of"] == "2026-11-11T14:41:02Z"
    assert e["verdict"] == "STALE"
