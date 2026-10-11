"""Notification intents, wave 3 (2026-10-11).

The next 40 files under BELOW_CAP in sender-measure/snd2/REMAINING_SND2.md. Each send declares
a priority: operator-action is P1 with dedupe off, time-critical is P1, reports and
operator-attention findings are P2, FYI is P3.

claude_escalation_handler.py is not in this wave's list. Importing it used to load the live
release .env. This file never imports it. The env-load fix is tests/test_claude_escalation_env_20261011.py.

Nothing here reaches Telegram. The static check does not import the producers.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_notification_intents as CNI  # noqa: E402

# file -> priorities its send calls may declare
MIGRATED_WAVE3 = {
    "scripts/paper_performance_governance.py": {"P1"},
    "scripts/system_health_alerts.py": {"P1", "P2", "P3"},
    "scripts/watchlist_entry_planner.py": {"P2"},
    "scripts/overnight_batch.py": {"P2", "P3"},
    "scripts/aegis_overnight.py": {"P2"},
    "scripts/agent_watchlist_engine.py": {"P2", "P3"},
    "scripts/crawl_v3_dashboard.py": {"P2"},
    "scripts/data_plausibility_monitor.py": {"P1"},
    "scripts/pro_analyst_monitor.py": {"P2"},
    "scripts/youtube_cookie_health_check.py": {"P1", "P2"},
    "scripts/audit_enrichment_coverage.py": {"P2"},
    "scripts/audit_position_basis.py": {"P2"},
    "scripts/auto_research.py": {"P3"},
    "scripts/continuous_runner.py": {"P1"},
    "scripts/generate_max_hold_exit_proposals.py": {"P1"},
    "scripts/incubator_llm_screener.py": {"P2"},
    "scripts/intel_auto_discovery.py": {"P3"},
    "scripts/iterate_research_topics.py": {"P3"},
    "scripts/portfolio_level_qa.py": {"P1"},
    "scripts/recovery_watch_daily.py": {"P1", "P2"},
    "scripts/technicals_gap_backfill.py": {"P2"},
    "scripts/telegram_smart_alerts.py": {"P1", "P2", "P3"},
    "scripts/youtube_transcript_ingest.py": {"P1"},
    "scripts/defense_weekly_paid_review.py": {"P2"},
    "scripts/generate_weekly_docx.py": {"P2"},
    "scripts/rotation_rebalance_digest.py": {"P2"},
    "scripts/strategy_weekly_review.py": {"P2"},
    "scripts/warrior_weekly_audit_cron.py": {"P2"},
    "scripts/watch_directive_hygiene.py": {"P1"},
    "scripts/watchlist_hygiene.py": {"P3"},
    "scripts/youtube_channel_discovery.py": {"P2"},
    "scripts/alert_dispatcher.py": {"P1", "P2"},
    "scripts/alex_retirement_advisor.py": {"P2"},
    "scripts/api_v2.py": {"P2", "P3"},
    "scripts/cio_event_brief.py": {"P2"},
    "scripts/cloud_consensus_verdict.py": {"P2"},
    "scripts/credential_monitor.py": {"P1", "P3"},
    "scripts/defense_engine_gap_checker.py": {"P2"},
    "scripts/finviz_ingestion.py": {"P1", "P2"},
    "scripts/full_system_backup.py": {"P1", "P3"},
}

OPERATOR_ACTION_DEDUPE_OFF = {
    "scripts/paper_performance_governance.py",
    "scripts/generate_max_hold_exit_proposals.py",
    "scripts/youtube_transcript_ingest.py",
    "scripts/watch_directive_hygiene.py",
    "scripts/recovery_watch_daily.py",
    "scripts/credential_monitor.py",
    "scripts/finviz_ingestion.py",
}

_BROKER_PREFIXES = ("scripts/brokers/", "scripts/active_trader/", "scripts/moomoo/")
_NAME_BAN = ("order", "stop", "execut", "broker", "alpaca", "schwab")


def test_wave3_is_forty_non_broker_senders():
    assert len(MIGRATED_WAVE3) == 40
    for rel in MIGRATED_WAVE3:
        assert not rel.startswith(_BROKER_PREFIXES), rel
        assert not any(w in Path(rel).name for w in _NAME_BAN), rel


def _declared_priorities(tree: ast.AST) -> set[str]:
    exprs = [k.value for n in ast.walk(tree) if isinstance(n, ast.Call) for k in n.keywords if k.arg == "priority"]
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            pos = a.posonlyargs + a.args
            for arg, default in zip(pos[len(pos) - len(a.defaults):], a.defaults):
                if arg.arg == "priority":
                    exprs.append(default)
            for arg, default in zip(a.kwonlyargs, a.kw_defaults):
                if arg.arg == "priority" and default is not None:
                    exprs.append(default)
    return {c.value for e in exprs for c in ast.walk(e)
            if isinstance(c, ast.Constant) and isinstance(c.value, str) and c.value in ("P1", "P2", "P3")}


def test_wave3_does_not_import_claude_escalation_handler():
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name != "claude_escalation_handler" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "claude_escalation_handler"


@pytest.mark.parametrize("rel,allowed", sorted(MIGRATED_WAVE3.items()))
def test_migrated_sender_declares_every_send(rel, allowed):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    calls = CNI.notifier_calls(tree)
    assert calls, f"{rel}: no notifier call found"
    undeclared = [(ln, fn) for ln, fn, declared, _ in calls if not declared]
    assert not undeclared, f"{rel}: undeclared notifier sends {undeclared}"
    assert not [ln for ln, _, _, bypass in calls if bypass], f"{rel} bypasses the router"
    used = _declared_priorities(tree)
    assert used and used <= allowed, (rel, used, allowed)
    if rel in OPERATOR_ACTION_DEDUPE_OFF:
        assert "dedupe_minutes=0" in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_oauth_lane_stale_over_two_hours_in_session_is_p1():
    """Operator ruling 2026-10-11: ordinary stale stays P2; >2h during the session is P1."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import oauth_lane_keepalive as lane

    session = int(datetime(2026, 10, 12, 10, 0, tzinfo=ZoneInfo("America/New_York")).timestamp())
    night = int(datetime(2026, 10, 12, 23, 0, tzinfo=ZoneInfo("America/New_York")).timestamp())
    fresh = {"grok": {"ok": False, "last_ok": session - 3600}}
    stale = {"grok": {"ok": False, "last_ok": session - 2 * 60 * 60 - 1}}
    assert lane._priority_for_alerts(fresh, session) == "P2"
    assert lane._priority_for_alerts(stale, session) == "P1"
    assert lane._priority_for_alerts(stale, night) == "P2"
    assert lane._priority_for_alerts({"grok": {"ok": True, "last_ok": session}}, session) == "P2"


def test_intent_baseline_is_below_99_and_excludes_wave3():
    measured = CNI.measure()
    base = CNI._load_baseline()
    assert CNI.compare(measured, base) == []
    total = sum(base.values())
    assert total == json.loads(CNI.BASELINE.read_text())["total"]
    assert total < 99, total
    for rel in MIGRATED_WAVE3:
        assert rel not in base, rel
