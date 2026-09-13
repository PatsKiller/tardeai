"""A boundary must not report READY about a domain it has no evidence for.

CL-63. Before feeding the boundary real evidence, this had to be fixed, because
the obvious implementation of "feed it" is actively harmful.

`evaluate()` read `snapshot.category_scores.get(health_cat, 100)` -- a category
absent from the snapshot scored a perfect 100. Measured 2026-09-12 against the
live health_agent_status.json: that producer emits data_quality /
execution_health / infra / intelligence_quality / pipeline_freshness /
retirement_planning / risk_protection, and this boundary maps market_data /
broker / database / backup / agent_jobs / indicators / shadow_batch / llm / api /
file_integrity / watchlist. The vocabularies do not overlap at all, so every
category defaulted to 100 and EVERY domain evaluated READY -- while the same
snapshot reported status=unhealthy, overall_score=64, and 9 critical findings.

Absence of evidence was being read as evidence of health. That is strictly worse
than the UNKNOWN it would have replaced, because UNKNOWN is honest.
"""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib.cio_health_boundary import CIOHealthBoundary, HealthSnapshot


def _snap(category_scores=None, findings=None):
    return HealthSnapshot(
        health_snapshot_id="snap-coverage",
        observed_at=datetime.now(timezone.utc).isoformat(),
        overall_score=64,
        overall_status="unhealthy",
        category_scores=category_scores or {},
        findings=findings or [],
    )


def test_foreign_vocabulary_is_unknown_not_ready():
    """NEGATIVE CONTROL: returned READY before the fix."""
    d = CIOHealthBoundary(
        _snap(category_scores={"data_quality": 60, "execution_health": 60})
    ).evaluate("cio_run", ["portfolio", "risk"])
    assert d.state == "UNKNOWN", "no mapped category covers these domains"
    assert "HEALTH_EVIDENCE_UNAVAILABLE" in d.reason_codes


def test_unhealthy_snapshot_never_reads_as_ready():
    """The specific lie: overall_status=unhealthy presenting as READY."""
    d = CIOHealthBoundary(
        _snap(
            category_scores={"data_quality": 60},
            findings=[{"category": "data_quality", "severity": "critical"}],
        )
    ).evaluate("cio_run", ["portfolio"])
    assert d.state != "READY"


def test_evidenced_category_still_reports_ready():
    """Back-compat: real evidence must still be able to clear a domain."""
    d = CIOHealthBoundary(
        _snap(category_scores={"database": 95})
    ).evaluate("cio_run", ["income"])
    assert d.state == "READY"
    assert "HEALTH_EVIDENCE_UNAVAILABLE" not in d.reason_codes


def test_findings_alone_count_as_evidence():
    """A category can be evidenced by a finding even with no score."""
    d = CIOHealthBoundary(
        _snap(findings=[{"category": "database", "severity": 1}])
    ).evaluate("cio_run", ["income"])
    assert d.state == "READY"


def test_partial_coverage_marks_only_the_uncovered_domain():
    b = CIOHealthBoundary(_snap(category_scores={"watchlist": 95}))
    assert b.evaluate("cio_run", ["watch"]).state == "READY"
    assert b.evaluate("cio_run", ["tax"]).state == "UNKNOWN"


def test_blocked_outranks_unknown():
    """A domain positively known unusable is more actionable than an
    unassessed one, so BLOCKED must win."""
    d = CIOHealthBoundary(
        _snap(
            category_scores={"broker": 10},
            findings=[{"category": "broker", "severity": 5}],
        )
    ).evaluate("cio_run", ["broker_reconciliation", "tax"])
    assert d.state == "BLOCKED"


def test_unknown_outranks_degraded():
    """Missing evidence must not present as a merely-degraded bill."""
    d = CIOHealthBoundary(
        _snap(
            category_scores={"watchlist": 60},
            findings=[{"category": "watchlist", "severity": 2}],
        )
    ).evaluate("cio_run", ["watch", "tax"])
    assert d.state == "UNKNOWN"
