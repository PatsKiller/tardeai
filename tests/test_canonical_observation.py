#!/usr/bin/env python3
"""The canonical observation contract, and the two defects it closes.

Audit cc-truth-v1-20260902T202759Z proved a stacked pair: producers wrote
`_freshness.json` / `performance_history.json` / `portfolio_news.json` under
$PROJ while the served API read persistent-state (separate inodes), AND
`portfolio_orchestrator.py` wrote `"status": "fresh"` as a literal. Fixing
either alone LOOKS like it worked, so both are pinned here.

No test in this file touches the network, a broker, a scheduler, Drive, a
database or any production path. Every filesystem write goes to tmp_path.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import canonical_observation as co  # noqa: E402

NOW = datetime(2026, 9, 2, 21, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── freshness fails closed ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("observed", "why"),
    [
        (None, "missing"),
        ("", "empty string"),
        ("not-a-timestamp", "unparsable"),
        ("2026-13-45T99:00:00", "impossible date"),
        (12345, "wrong type"),
        ([], "wrong type"),
    ],
)
def test_missing_or_malformed_never_reports_fresh(observed, why):
    verdict = co.compute_freshness(observed, max_age_hours=36.0, now=NOW)
    assert verdict["status"] == co.UNKNOWN, why
    assert verdict["status"] != co.FRESH


def test_old_timestamp_is_stale_not_fresh():
    # The measured case: served _freshness.json was ~177.3h old and said fresh.
    old = _iso(NOW - timedelta(hours=177.3))
    verdict = co.compute_freshness(old, max_age_hours=36.0, now=NOW)
    assert verdict["status"] == co.STALE
    assert verdict["age_hours"] == pytest.approx(177.3, abs=0.01)


def test_future_skew_is_unknown_not_fresh():
    future = _iso(NOW + timedelta(hours=6))
    verdict = co.compute_freshness(future, max_age_hours=36.0, now=NOW)
    assert verdict["status"] == co.UNKNOWN
    assert verdict["reason"] == "not_fresh:future_skew"


def test_clock_regression_is_unknown_not_fresh():
    """A backwards jump must not be readable as a very fresh observation."""
    stamp = _iso(NOW + timedelta(seconds=1))  # within tolerance -> fine
    assert co.compute_freshness(stamp, max_age_hours=36.0, now=NOW)["status"] == co.FRESH
    regressed = _iso(NOW + timedelta(hours=1))  # beyond tolerance -> refused
    assert co.compute_freshness(regressed, max_age_hours=36.0, now=NOW)["status"] == co.UNKNOWN


def test_no_agreed_threshold_is_unknown_not_fresh():
    verdict = co.compute_freshness(_iso(NOW), max_age_hours=None, now=NOW)
    assert verdict["status"] == co.UNKNOWN
    assert verdict["reason"] == "not_fresh:no_agreed_threshold"


def test_a_real_recent_timestamp_is_the_only_route_to_fresh():
    verdict = co.compute_freshness(_iso(NOW - timedelta(hours=2)), max_age_hours=36.0, now=NOW)
    assert verdict["status"] == co.FRESH


def test_boundary_is_inclusive_and_one_second_past_is_stale():
    exact = _iso(NOW - timedelta(hours=36))
    assert co.compute_freshness(exact, max_age_hours=36.0, now=NOW)["status"] == co.FRESH
    past = _iso(NOW - timedelta(hours=36, seconds=1))
    assert co.compute_freshness(past, max_age_hours=36.0, now=NOW)["status"] == co.STALE


def test_date_only_is_marked_so_midnight_is_not_mistaken_for_an_instant():
    """`data_as_of` is emitted date-only; midnight vs 16:45 is a 16.75h swing."""
    verdict = co.compute_freshness("2026-09-02", max_age_hours=36.0, now=NOW)
    assert verdict["precision"] == "date_only"


def test_mixed_repo_formats_all_parse():
    for raw in (
        "2026-09-02T16:45:02+00:00",
        "2026-09-02 16:45:02 ET",
        "2026-09-02 16:45:02",
        "2026-09-02",
        "2026-09-02T16:45:02Z",
    ):
        parsed, reason = co.parse_timestamp(raw)
        assert parsed is not None, (raw, reason)


# ── the literal "fresh" is gone ──────────────────────────────────────────────


def test_orchestrator_status_is_measured_not_constant():
    fresh_status, _ = co.orchestrator_freshness_status(_iso(NOW), now=NOW)
    stale_status, _ = co.orchestrator_freshness_status(_iso(NOW - timedelta(days=8)), now=NOW)
    missing_status, _ = co.orchestrator_freshness_status(None, now=NOW)
    assert fresh_status == "fresh"
    assert stale_status == "stale"
    assert missing_status == "unknown"
    # If these three ever collapse to one value the literal is back.
    assert len({fresh_status, stale_status, missing_status}) == 3


def test_orchestrator_no_longer_writes_a_literal_status(_ast_orchestrator):
    """AST, not grep: a grep cannot tell code from a comment quoting it."""
    import ast

    for node in ast.walk(_ast_orchestrator):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "status"
                    and isinstance(value, ast.Constant)
                    and value.value == "fresh"
                ):
                    pytest.fail("portfolio_orchestrator.py still assigns the literal status='fresh'")


# ── the divergent-root mutation ──────────────────────────────────────────────


@pytest.fixture()
def _two_roots(tmp_path, monkeypatch):
    """A served root and a checkout root, on separate inodes — the proven shape."""
    persistent = tmp_path / "persistent-state"
    checkout = tmp_path / "checkout"
    (persistent / "data" / "portfolios" / "state").mkdir(parents=True)
    (checkout / "data" / "portfolios" / "state").mkdir(parents=True)
    monkeypatch.setenv("TRADEAI_PERSISTENT_STATE_ROOT", str(persistent))
    return persistent, checkout


def test_write_reaches_both_roots_from_one_object(_two_roots):
    persistent, checkout = _two_roots
    payload = {"completed_at": _iso(NOW), "run_id": "20260902-210000"}
    result = co.write_state_json("_freshness.json", payload, checkout_root=checkout)

    assert result["errors"] == []
    assert result["target_count"] == 2, "the served copy is the one that was being stranded"
    served = persistent / "data" / "portfolios" / "state" / "_freshness.json"
    local = checkout / "data" / "portfolios" / "state" / "_freshness.json"
    assert served.exists() and local.exists()
    assert json.loads(served.read_text()) == json.loads(local.read_text())
    assert served.stat().st_ino != local.stat().st_ino, "separate inodes, as measured"


def test_the_api_reads_the_newly_written_canonical_observation(_two_roots):
    """Divergent-root mutation: mutate the served copy, prove the reader follows.

    This is the test that would have caught the original defect. Before the
    fix, a write went only to the checkout and the reader kept serving the
    August copy.
    """
    persistent, checkout = _two_roots
    state = persistent / "data" / "portfolios" / "state"
    # Plant a deliberately DIVERGENT pair: served is ancient, checkout is new.
    (state / "_freshness.json").write_text(
        json.dumps({"completed_at": _iso(NOW - timedelta(days=7)), "status": "fresh"})
    )
    (checkout / "data" / "portfolios" / "state" / "_freshness.json").write_text(
        json.dumps({"completed_at": _iso(NOW), "status": "fresh"})
    )

    _, env = co.observe_state_file("_freshness.json", checkout_root=checkout, now=NOW)
    assert env.source_identity == str(state / "_freshness.json"), "reader must resolve the served root"
    assert env.status == co.STALE, "the served copy is 7 days old and must not read as fresh"
    assert env.diagnostics["literal_status_field_contradicted"] == "fresh"

    # Now write through the canonical path from one object and re-read.
    co.write_state_json("_freshness.json", {"completed_at": _iso(NOW), "status": "fresh"}, checkout_root=checkout)
    _, env2 = co.observe_state_file("_freshness.json", checkout_root=checkout, now=NOW)
    assert env2.status == co.FRESH, "after the canonical write the reader sees the new observation"
    assert env2.source_hash != env.source_hash


def test_missing_file_is_unknown_and_flagged_missing(_two_roots):
    _persistent, checkout = _two_roots
    payload, env = co.observe_state_file("_freshness.json", checkout_root=checkout, now=NOW)
    assert payload == {}
    assert env.status == co.UNKNOWN
    assert env.quality == co.QUALITY_MISSING
    assert env.fallback == co.FALLBACK_MISSING


def test_unparsable_file_is_unknown_not_fresh(_two_roots):
    persistent, checkout = _two_roots
    (persistent / "data" / "portfolios" / "state" / "_freshness.json").write_text("{not json")
    payload, env = co.observe_state_file("_freshness.json", checkout_root=checkout, now=NOW)
    assert payload == {}
    assert env.status == co.UNKNOWN
    assert env.quality == co.QUALITY_UNPARSABLE


def test_stamp_that_claims_fresh_inside_a_stranded_file_is_degraded(_two_roots):
    """The two defects are mutually concealing; the envelope reports both."""
    import os

    persistent, checkout = _two_roots
    path = persistent / "data" / "portfolios" / "state" / "_freshness.json"
    path.write_text(json.dumps({"completed_at": _iso(NOW), "status": "fresh"}))
    ancient = (NOW - timedelta(days=8)).timestamp()
    os.utime(path, (ancient, ancient))

    _, env = co.observe_state_file("_freshness.json", checkout_root=checkout, now=NOW)
    assert env.status == co.FRESH, "the producer stamp itself is recent"
    assert env.quality == co.QUALITY_DEGRADED, "but the file it lives in has not moved"
    assert env.diagnostics["stamp_mtime_disagreement"] is True


# ── one envelope: value and metadata together ────────────────────────────────


def test_envelope_carries_every_required_contract_field(_two_roots):
    persistent, checkout = _two_roots
    (persistent / "data" / "portfolios" / "state" / "holdings.json").write_text(
        json.dumps({"last_repriced": _iso(NOW), "as_of": "2026-09-02", "holdings": []})
    )
    _, env = co.observe_state_file(
        "holdings.json",
        checkout_root=checkout,
        observed_at_field="last_repriced",
        account_scope="alpaca_taxable_live",
        now=NOW,
    )
    d = env.to_dict()
    for required in (
        "source_identity",
        "account_scope",
        "provider_timestamp",
        "observed_at",
        "received_at",
        "normalized_at",
        "business_date",
        "market_session",
        "timezone_label",
        "freshness",
        "quality",
        "entitlement",
        "sequence",
        "source_hash",
        "calculation_version",
        "contract_version",
        "fallback",
        "trace_id",
    ):
        assert required in d, required
    assert d["account_scope"] == "alpaca_taxable_live"
    assert d["contract_version"] == co.CONTRACT_VERSION


def test_envelope_serialization_round_trips(_two_roots):
    persistent, checkout = _two_roots
    (persistent / "data" / "portfolios" / "state" / "holdings.json").write_text(
        json.dumps({"last_repriced": _iso(NOW)})
    )
    _, env = co.observe_state_file("holdings.json", checkout_root=checkout, now=NOW)
    assert json.loads(json.dumps(env.to_dict())) == env.to_dict()


def test_one_trace_id_binds_a_whole_observation_set(_two_roots):
    _persistent, checkout = _two_roots
    trace = co.new_trace_id()
    _, a = co.observe_state_file("holdings.json", checkout_root=checkout, trace_id=trace, now=NOW)
    _, b = co.observe_state_file("_freshness.json", checkout_root=checkout, trace_id=trace, now=NOW)
    assert a.trace_id == b.trace_id == trace


def test_surface_is_as_fresh_as_its_oldest_dataset():
    def env(status):
        e = co.ObservationEnvelope(dataset="d", source_identity="/x")
        e.freshness = {"status": status}
        return e

    assert co.worst_status({"a": env(co.FRESH), "b": env(co.FRESH)}) == co.FRESH
    assert co.worst_status({"a": env(co.FRESH), "b": env(co.STALE)}) == co.STALE
    assert co.worst_status({"a": env(co.STALE), "b": env(co.UNKNOWN)}) == co.UNKNOWN
    assert co.worst_status({}) == co.UNKNOWN


# ── position-count contract ──────────────────────────────────────────────────


def test_disagreeing_counts_are_named_not_silently_contradictory():
    """The measured case: overview 14, risk 15, both unlabeled."""
    contract = co.position_count_contract({"overview.non_cash_over_100": 14, "risk.risk_included": 15})
    assert contract["agree"] is False
    assert contract["distinct_values"] == [14, 15]
    assert set(contract["scopes"]) == {"overview.non_cash_over_100", "risk.risk_included"}


def test_agreeing_counts_report_agreement():
    contract = co.position_count_contract({"overview.non_cash_over_100": 15, "risk.risk_included": 15})
    assert contract["agree"] is True
    assert contract["distinct_values"] == [15]


# ── diagnostics carry no secrets ─────────────────────────────────────────────


def test_diagnostics_expose_path_age_version_and_fallback_only(_two_roots):
    persistent, checkout = _two_roots
    (persistent / "data" / "portfolios" / "state" / "_freshness.json").write_text(
        json.dumps({"completed_at": _iso(NOW - timedelta(days=8)), "status": "fresh"})
    )
    _, env = co.observe_state_file("_freshness.json", checkout_root=checkout, now=NOW)
    diag = co.envelope_diagnostics({"freshness": env})
    blob = json.dumps(diag).lower()

    assert diag["datasets"]["freshness"]["status"] == co.STALE
    assert diag["any_not_fresh"] is True
    assert diag["datasets"]["freshness"]["age_hours"] is not None
    assert diag["calculation_version"] == co.CALCULATION_VERSION
    for forbidden in ("password", "token", "secret", "api_key", "authorization", "totp", "bearer"):
        assert forbidden not in blob


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def _ast_orchestrator():
    import ast

    return ast.parse((ROOT / "scripts" / "portfolio_orchestrator.py").read_bytes())
