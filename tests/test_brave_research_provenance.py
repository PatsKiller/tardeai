#!/usr/bin/env python3
"""Provenance and eligibility controls for Brave discovery evidence.

Covers the source prompt's Phase 9 "Provenance and circulation" items that
apply at the search boundary: a complete source observation survives to the
rendered contract, a snippet is never decision-eligible, denials are not
absence, and identical evidence replays as NO_NEW_INFO.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.lib import brave_research_router as R  # noqa: E402
from scripts.lib.research_observation.brave_adapter import (  # noqa: E402
    evidence_gap_signature,
    wrap_brave_outcome,
)
from scripts.lib.research_observation.consumer_gate import gate_for_consumer  # noqa: E402
from scripts.lib.research_observation.contract import (  # noqa: E402
    required_provenance_fields,
)
from scripts.lib.research_observation.eligibility import (  # noqa: E402
    EligibilityDecision,
    evaluate_eligibility,
)
from scripts.lib.research_observation.statuses import (  # noqa: E402
    FreshnessStatus,
    QualityStatus,
)

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)


def _outcome(status=R.Status.OK, results=None, query="q"):
    return R.Outcome(
        status=status,
        results=results
        if results is not None
        else [
            R.Result(
                title="T", url="https://www.sec.gov/x", description="d", source_domain="sec.gov", is_primary_source=True
            ),
        ],
        query=query,
        fingerprint=R.fingerprint(query),
        purpose=R.Purpose.EVIDENCE_GAP.value,
        caller="test",
        as_of=NOW.isoformat(),
        provider_billed=True,
    )


def _wrap(o, **kw):
    return wrap_brave_outcome(o, run_id="run-1", trace_id="trace-1", now=NOW, **kw)


# ── 1. Complete provenance survives ─────────────────────────────────────────


def test_every_required_provenance_field_is_populated():
    obs = _wrap(_outcome())
    for field in required_provenance_fields():
        assert hasattr(obs, field), f"envelope is missing {field}"
        assert getattr(obs, field) is not None, f"{field} is None"


def test_the_source_observation_survives_into_the_payload():
    obs = _wrap(_outcome(), symbol_or_entity="AAPL")
    assert obs.symbol_or_entity == "AAPL"
    p = obs.payload_ref
    assert p["results"][0]["url"] == "https://www.sec.gov/x"
    assert p["results"][0]["attribution"] == "SEARCH_DISCOVERY"
    assert p["results"][0]["is_primary_source"] is True
    assert p["router_status"] == "OK"
    assert obs.raw_evidence_ref.startswith("brave:")


# ── 2. A snippet is never decision-eligible ─────────────────────────────────


def test_a_successful_snippet_is_display_only_never_eligible():
    """Even a 200 with a primary-source hit is not decision-grade evidence."""
    obs = _wrap(_outcome())
    assert obs.freshness_status is FreshnessStatus.FRESH
    assert obs.quality_status is QualityStatus.UNVERIFIED

    display = evaluate_eligibility(obs, consumer_kind="display", now=NOW)
    assert display.decision is EligibilityDecision.DISPLAY_ONLY
    assert obs.degraded_label

    proposal = evaluate_eligibility(obs, consumer_kind="proposal", now=NOW)
    assert proposal.decision is EligibilityDecision.INELIGIBLE
    assert any("QUALITY_FAILURE" in r for r in proposal.reasons)


def test_proposal_consumer_gate_rejects_search_discovery():
    obs = _wrap(_outcome())
    gate = gate_for_consumer(obs, consumer_id="proposal-engine", consumer_kind="proposal", now=NOW)
    assert gate.accepted is False


def test_display_consumer_gets_it_with_a_label_not_a_blank():
    obs = _wrap(_outcome())
    gate = gate_for_consumer(obs, consumer_id="command-center", consumer_kind="display", now=NOW)
    assert gate.accepted is True
    assert "SEARCH_DISCOVERY" in obs.degraded_label
    assert "not a filing" in obs.degraded_label


def test_discovering_a_primary_source_is_not_ingesting_it():
    """A sec.gov hit is a pointer worth acquiring, not an acquired filing."""
    obs = _wrap(_outcome())
    assert obs.payload_ref["results"][0]["is_primary_source"] is True
    assert obs.quality_status is QualityStatus.UNVERIFIED
    assert evaluate_eligibility(obs, consumer_kind="proposal", now=NOW).decision is EligibilityDecision.INELIGIBLE


# ── 3. Denial is not absence; error is not emptiness ────────────────────────


def test_a_budget_denial_is_ineligible_not_no_data():
    obs = _wrap(_outcome(status=R.Status.DENIED_BUDGET, results=[]))
    assert obs.freshness_status is FreshnessStatus.INELIGIBLE
    assert obs.freshness_status is not FreshnessStatus.NO_DATA
    assert obs.durable_output_present is False


def test_a_transport_error_is_error_not_gap():
    obs = _wrap(_outcome(status=R.Status.TRANSPORT_ERROR, results=[]))
    assert obs.freshness_status is FreshnessStatus.ERROR


def test_an_empty_served_result_is_a_gap_never_fresh():
    obs = _wrap(_outcome(status=R.Status.EMPTY, results=[]))
    assert obs.freshness_status is FreshnessStatus.GAP
    assert obs.freshness_status is not FreshnessStatus.FRESH


def test_denial_and_error_never_claim_durable_output():
    """LOG_ONLY_SUCCESS_WITHOUT_DURABLE_OUTPUT is the join rule this protects."""
    for st in (R.Status.DENIED_BUDGET, R.Status.TIMEOUT, R.Status.RATE_LIMITED, R.Status.UNAUTHORIZED, R.Status.EMPTY):
        obs = _wrap(_outcome(status=st, results=[]))
        assert obs.durable_output_present is False, f"{st} claimed durable output"


def test_no_degraded_status_is_ever_relabelled_fresh():
    for st in (
        R.Status.DENIED_BUDGET,
        R.Status.DENIED_WEEKEND,
        R.Status.TIMEOUT,
        R.Status.MALFORMED,
        R.Status.EMPTY,
        R.Status.BUDGET_UNAVAILABLE,
    ):
        obs = _wrap(_outcome(status=st, results=[]))
        assert obs.freshness_status is not FreshnessStatus.FRESH, f"{st} was relabelled FRESH"


# ── 4. Replayed evidence is recognisable ────────────────────────────────────


def test_identical_evidence_produces_an_identical_signature():
    a = evidence_gap_signature("AAPL earnings guidance", "AAPL")
    b = evidence_gap_signature("  aapl   EARNINGS   guidance ", "aapl")
    assert a == b, "trivial formatting changed the evidence identity"


def test_a_different_question_produces_a_different_signature():
    assert evidence_gap_signature("AAPL earnings", "AAPL") != evidence_gap_signature("AAPL litigation", "AAPL")


def test_identical_outcomes_hash_identically():
    """Replay suppression depends on the source hash being stable."""
    one = _wrap(_outcome())
    two = _wrap(_outcome())
    assert one.source_hash == two.source_hash


def test_different_results_change_the_source_hash():
    other = _outcome()
    other.results = [R.Result(title="Different", url="https://other.com/x", description="d", source_domain="other.com")]
    assert _wrap(_outcome()).source_hash != _wrap(other).source_hash


# ── 5. Stale evidence is blocked ────────────────────────────────────────────


def test_stale_evidence_is_not_eligible():
    obs = _wrap(_outcome())
    later = NOW + timedelta(days=3)
    result = evaluate_eligibility(obs, consumer_kind="proposal", now=later)
    assert result.decision is EligibilityDecision.INELIGIBLE


# ── 6. Search discovery is never native social sentiment ────────────────────


def test_a_social_page_hit_is_discovery_not_native_sentiment():
    o = _outcome(
        results=[
            R.Result(
                title="r/stocks thread",
                url="https://reddit.com/r/stocks/1",
                description="chatter",
                source_domain="reddit.com",
            ),
        ]
    )
    o.purpose = R.Purpose.SOCIAL_LEAD_DISCOVERY.value
    obs = _wrap(o)
    r = obs.payload_ref["results"][0]
    assert r["attribution"] == "SEARCH_DISCOVERY"
    assert obs.quality_status is QualityStatus.UNVERIFIED
    assert obs.source_identity == "brave_search_discovery"
    # It must not be presentable as a native Reddit observation.
    assert obs.provider == "brave"
    assert obs.provider != "reddit"
