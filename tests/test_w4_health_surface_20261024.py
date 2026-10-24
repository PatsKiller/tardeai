"""One Health population and verified remediation evidence; pinned files only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

from scripts.lib import health_surface as H

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)


def test_kill_switch_mirror_counted_once_with_diagnostic_retained():
    original = {"status": "unhealthy", "overall_score": 60, "findings": [
        {"category": "execution_health", "type": "kill_switch_active", "severity": "critical", "message": "Kill switch global: operator hold"},
        {"category": "execution_health", "type": "execution_state_conflict", "severity": "warning", "message": "kill_switch_active"},
        {"category": "data_quality", "type": "source_stale", "severity": "warning", "message": "Source overdue"},
    ]}
    before = deepcopy(original)
    result = H.normalize_snapshot(original)
    assert result["counts"] == {"critical": 1, "warning": 1, "info": 0, "total": 2, "actionable": 0}
    assert result["headline"] == "UNHEALTHY 60/100 — 1 critical, 1 warning"
    assert result["findings"][0]["related_evidence"][0]["type"] == "execution_state_conflict"
    assert original == before


def test_distinct_controls_and_accounts_are_not_deduplicated():
    findings = [{"type": "kill_switch_active", "severity": "critical", "message": f"Kill switch {level}: hold"}
                for level in ["global", "live_submit"]]
    findings += [{"type": "missing_data", "symbol": "FIX", "account": a, "message": "Missing", "severity": "warning"} for a in ["One", "Two"]]
    assert H.normalize_snapshot({"findings": findings})["counts"]["total"] == 4


def write(path, rows):
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))


def test_previews_and_exit_zero_without_recheck_are_not_fixes(tmp_path):
    agent, inspector = tmp_path / 'agent.jsonl', tmp_path / 'inspector.jsonl'
    common = {"at": NOW.isoformat(), "type": "fixture", "exit_code": 0}
    write(agent, [
        {**common, "ok": True, "verified_by_recheck": True, "mode": "dry_run"},
        {**common, "ok": True, "verified_by_recheck": True, "cmd": "python fixture.py --dry-run"},
        {**common, "ok": True},
        {**common, "ok": True, "verified_by_recheck": True},
    ])
    write(inspector, [{"timestamp": NOW.isoformat(), "verified": True, "mode": "shadow"},
                      {"timestamp": NOW.isoformat(), "verified": True, "exit_code": 1},
                      {"timestamp": NOW.isoformat(), "verified": True, "mode": "live", "exit_code": 0}])
    result = H.get_remediation(paths=(agent, [inspector, inspector]), now=NOW)
    assert result["stats"]["total_events_24h"] == 7
    assert result["stats"]["preview_events_24h"] == 3
    assert result["stats"]["verified_fixes_24h"] == 2
    assert result["stats"]["total_fixes_24h"] == 2
    assert result["stats"]["success_rate"] == '50%'
    assert sum(r["evidence_state"] == "Unverified" for r in result["remediations"]) == 1


def test_missing_histories_are_unavailable_counts_not_zero(tmp_path):
    result = H.get_remediation(paths=(tmp_path/'absent', [tmp_path/'also-absent']), now=NOW)
    assert result["coverage"]["status"] == 'UNAVAILABLE'
    assert result["stats"]["total_fixes_24h"] is None
    assert result["stats"]["total_events_24h"] is None


def test_future_and_old_events_do_not_enter_today_counts(tmp_path):
    path = tmp_path/'agent'
    write(path, [{"at": at.isoformat(), "ok": True, "verified_by_recheck": True} for at in [NOW-timedelta(days=2), NOW+timedelta(minutes=1), NOW]])
    result = H.get_remediation(paths=(path, []), now=NOW)
    assert result["stats"]["total_fixes_24h"] == 1


def test_truncated_window_is_visible_and_duplicate_read_paths_do_not_duplicate(tmp_path):
    path = tmp_path/'agent'
    write(path, [{"at": NOW.isoformat(), "ok": True, "verified_by_recheck": True}] * 30)
    result = H.get_remediation(paths=(path, [path]), now=NOW, max_bytes=512)
    assert result["coverage"]["status"] == 'PARTIAL'
    assert result["stats"]["stats_truncated"]
    assert 0 < result["stats"]["total_fixes_24h"] < 30
