"""Flash-first vs OAuth lane policy (no live providers)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import agent_job_provider_policy as pol  # noqa: E402


def test_auto_queue_holdings_do_not_preempt_flash(monkeypatch):
    monkeypatch.delenv("AGENT_JOB_OAUTH_LANE", raising=False)
    monkeypatch.delenv("AGENT_JOB_MANUAL_OAUTH_FIRST", raising=False)
    lane = pol.classify_job_lane(
        submitted_from="overnight_batch",
        request_type="full_analysis",
        priority=1,
    )
    assert lane == pol.LANE_AUTO_QUEUE
    assert pol.requested_provider_policy(lane) == pol.POLICY_FLASH_FIRST_AUTO_QUEUE
    assert pol.oauth_may_preempt_flash(lane) is False
    assert pol.first_provider_attempt(lane) == "deepseek-v4-flash"


def test_command_center_scheduled_is_auto_not_oauth(monkeypatch):
    monkeypatch.delenv("AGENT_JOB_MANUAL_OAUTH_FIRST", raising=False)
    lane = pol.classify_job_lane(
        submitted_from="command_center",
        request_type="full_analysis",
        priority=1,
    )
    assert lane == pol.LANE_AUTO_QUEUE
    assert pol.oauth_may_preempt_flash(lane) is False


def test_explicit_challenge_preempts_flash():
    lane = pol.classify_job_lane(request_type="oauth_challenge")
    assert lane == pol.LANE_CHALLENGE
    assert pol.oauth_may_preempt_flash(lane) is True
    assert pol.first_provider_attempt(lane) == "grok-oauth"


def test_manual_requeue_default_is_still_flash_first(monkeypatch):
    monkeypatch.delenv("AGENT_JOB_MANUAL_OAUTH_FIRST", raising=False)
    lane = pol.classify_job_lane(submitted_from="watchlist_requeue", request_type="full_analysis")
    assert lane == pol.LANE_MANUAL_OPERATOR
    assert pol.requested_provider_policy(lane) == pol.POLICY_FLASH_FIRST_AUTO_QUEUE
    assert pol.oauth_may_preempt_flash(lane) is False


def test_hard_policy_failure_blocks_oauth_fallback():
    assert pol.is_hard_policy_failure("COST_CONFIGURATION_INVALID: missing cap")
    assert pol.oauth_soft_fallback_permitted(pol.LANE_AUTO_QUEUE, "COST_CONFIGURATION_INVALID") is False
    assert pol.oauth_soft_fallback_permitted(pol.LANE_AUTO_QUEUE, "FLASH_NETWORK_FAILURE") is True


def test_prefer_maria_oauth_auto_queue_false(monkeypatch):
    monkeypatch.delenv("AGENT_JOB_OAUTH_LANE", raising=False)
    sys.path.insert(0, str(ROOT / "scripts"))
    import process_watchlist_agent_jobs as pwaj
    pwaj._CURRENT_AGENT = "maria"
    pwaj._CURRENT_JOB_SYMBOL = "SCHG"
    pwaj._CURRENT_JOB_SUBMITTED_FROM = "research_scheduler"
    pwaj._CURRENT_JOB_REQUEST_TYPE = "scheduled_research"
    pwaj._CURRENT_JOB_PRIORITY = 5
    pwaj._MARIA_OAUTH_RUN_CALLS = 0
    pwaj._PORTFOLIO_SYMS_RUN = frozenset({"SCHG"})
    pwaj._WAIT_SETUP_SYMS_RUN = frozenset()
    assert pwaj._prefer_maria_oauth() is False
