"""Dry financial-advisory replay tests — read-only, no action, vintage-protected."""
from __future__ import annotations

from financial_senses.dry_replay import run_dry_replay


def test_replay_runs_all_cases():
    report = run_dry_replay()
    assert report["summary"]["cases"] == 6


def test_replay_suggests_no_actions():
    report = run_dry_replay()
    assert report["summary"]["suggested_actions"] == 0
    for c in report["cases"]:
        assert c["suggested_action"] is False


def test_replay_mutates_nothing():
    report = run_dry_replay()
    assert report["summary"]["production_mutations"] == 0
    assert report["summary"]["telegram_sends"] == 0


def test_replay_critic_is_shadow_only():
    report = run_dry_replay()
    for c in report["cases"]:
        assert c["critic"]["shadow_only"] is True
        assert c["critic"]["behavior_influence"] is False


def test_replay_vintage_does_not_leak():
    report = run_dry_replay()
    filing_case = next(c for c in report["cases"] if c["case"] == "company with recent SEC filing")
    mv = filing_case["macro_vintage"]
    # As-of 2024-12-31, the latest observation was 2024-06-01 = 5.5.
    assert mv["observation_date"] == "2024-06-01"
    assert mv["decision_time_value"] == 5.5
    # Same observation date has not been revised; the 2025 observation (5.9)
    # is a different economic date and must NOT leak in as a "revision".
    assert mv["latest_revised_value"] == 5.5
    assert mv["revision_delta"] == 0.0


def test_replay_stress_coverage_invariant():
    report = run_dry_replay()
    schd = next(c for c in report["cases"] if c["case"] == "SCHD concentration challenge")
    stress = schd["stress"]
    # unmodeled_value + modeled value must reconcile; coverage <= 100
    assert stress["coverage_pct"] <= 100.0
    assert stress["unmodeled_value"] >= 0.0


def test_replay_evidence_graph_supported_claim():
    report = run_dry_replay()
    filing_case = next(c for c in report["cases"] if c["case"] == "company with recent SEC filing")
    g = filing_case["evidence_graph"]
    assert "c1" not in g["unsupported_claims"]
