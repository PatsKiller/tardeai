"""RAW-store lane health — must NOT use last_real NOT LIKE '[%'."""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib.research_lane_health import (
    consecutive_error_streak,
    evaluate_lane,
    is_error_recommendation,
    non_error_count,
)


def test_bracket_prefix_is_error():
    assert is_error_recommendation("[ERROR] No module named 'lib.llm_lane'")
    assert is_error_recommendation("[AUTH_PENDING] not logged in")
    assert is_error_recommendation("")
    assert is_error_recommendation(None)
    assert not is_error_recommendation("Hold SCHD; thesis intact.")


def test_streak_counts_newest_errors_until_success():
    rows = [
        {"recommendation": "[ERROR] boom", "created_at": "t3"},
        {"recommendation": "[ERROR] boom", "created_at": "t2"},
        {"recommendation": "Hold", "created_at": "t1"},
    ]
    assert consecutive_error_streak(rows) == 2
    assert consecutive_error_streak([{"recommendation": "Hold"}]) == 0


def test_dead_deepseek_pattern_fires_streak_and_silence():
    """The 8-day outage: every raw row is `[ERROR]…`. last_real would hide this."""
    now = datetime(2026, 8, 21, 18, 0, tzinfo=timezone.utc)
    dead = [{"recommendation": "[ERROR] No module named 'lib.llm_lane'", "created_at": now}] * 8
    row = evaluate_lane(
        "deepseek",
        newest_first=dead,
        last_24h=dead,
        silence=True,
        streak_n=5,
        now=now,
    )
    assert row["ok"] is False
    assert "error_streak:8>=5" in row["firing"]
    assert any(x.startswith("zero_non_error_") for x in row["firing"])
    assert non_error_count(dead) == 0


def test_last_real_filter_would_hide_dead_lane():
    """Document the bug: filtering NOT LIKE '[%' on a 100% error lane yields []."""
    dead = [{"recommendation": "[ERROR] No module named 'lib.llm_lane'"}] * 5
    last_real = [r for r in dead if not str(r["recommendation"]).startswith("[")]
    assert last_real == []  # looks like "no new research"
    assert consecutive_error_streak(dead) == 5  # raw store sees the outage


def test_manual_claude_silence_does_not_fire():
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    row = evaluate_lane(
        "claude",
        newest_first=[{"recommendation": "Hold", "created_at": now}],
        last_24h=[],
        silence=False,
        streak_n=5,
        now=now,
    )
    assert row["ok"] is True


def test_chatgpt_24h_zero_ok_fires():
    now = datetime(2026, 8, 21, tzinfo=timezone.utc)
    rows = [{"recommendation": "[AUTH_PENDING] x", "created_at": now}] * 3
    row = evaluate_lane(
        "chatgpt",
        newest_first=rows,
        last_24h=rows,
        silence=True,
        streak_n=5,
        now=now,
    )
    assert row["ok"] is False
    assert any("zero_non_error" in x for x in row["firing"])


def test_coverage_stall_fires_when_research_up_thesis_flat(tmp_path):
    from scripts.lib.research_lane_health import collect_coverage_stall

    row = collect_coverage_stall(
        deepseek_ok_24h=545,
        thesis_current=3,
        thesis_held=22,
        snap_path=tmp_path / "stall.json",
        persist=True,
    )
    assert row["lane"] == "coverage-stall"
    assert row["ok"] is False
    assert any("research_up_thesis_flat" in x for x in row["firing"])


def test_coverage_stall_quiet_when_thesis_meets_sla(tmp_path):
    from scripts.lib.research_lane_health import collect_coverage_stall

    row = collect_coverage_stall(
        deepseek_ok_24h=545,
        thesis_current=20,
        thesis_held=22,
        snap_path=tmp_path / "stall.json",
        persist=False,
    )
    assert row["ok"] is True


def test_coverage_stall_fires_when_covered_but_thin(tmp_path):
    """22/22 coverage with 5 PASS must not quiet the stall — that is the fake green."""
    from scripts.lib.research_lane_health import collect_coverage_stall

    row = collect_coverage_stall(
        deepseek_ok_24h=545,
        thesis_current=5,
        thesis_substantive=5,
        thesis_coverage=22,
        thesis_held=22,
        snap_path=tmp_path / "stall.json",
        persist=False,
    )
    assert row["ok"] is False
    assert any("thesis_substantive=5/22" in x for x in row["firing"])
    assert row["thesis_coverage"] == 22


def test_pin_hybrid_fires():
    from scripts.lib.current_pin_integrity import evaluate_pin

    ok = evaluate_pin(source_commit="abc", diff_paths=[], extra_paths=[])
    assert ok["ok"] is True
    bad = evaluate_pin(
        source_commit="a7f30d89",
        diff_paths=["docs/CHANGELOG.md", "docs/ops/RESEARCH_LANE_HEALTH.md"],
        extra_paths=["docs/ops/overlay.md"],
    )
    assert bad["ok"] is False
    assert any(x.startswith("tree_diff:") for x in bad["firing"])
    assert any(x.startswith("unpinned_extra:") for x in bad["firing"])


def test_drive_sync_raw_404_shape_fires():
    """Hourly cron '0 uploaded, 1979 unchanged' with 404s must not look healthy."""
    from datetime import datetime, timezone
    from scripts.lib.drive_sync_health import evaluate_drive_sync

    now = datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc)
    silent = evaluate_drive_sync(
        {
            "status": "done",
            "finished_utc": "2026-08-21T22:31:54Z",
            "uploaded": 0,
            "skipped": 1979,
            "failed": 40,
            "exit_code": 0,
        },
        now=now,
    )
    assert silent["ok"] is False
    assert any("zero_uploaded_with_failures" in x for x in silent["firing"])

    missing = evaluate_drive_sync(None, now=now)
    assert missing["ok"] is False
    assert "missing_result_file" in missing["firing"]

    stale_src = evaluate_drive_sync(
        {
            "status": "done",
            "finished_utc": "2026-08-21T22:31:54Z",
            "uploaded": 26,
            "skipped": 2069,
            "failed": 0,
            "exit_code": 0,
            "source_status": "DEGRADED_STALE_SOURCE",
        },
        now=now,
    )
    assert stale_src["ok"] is False
    assert "DEGRADED_STALE_SOURCE" in stale_src["firing"]

    healthy = evaluate_drive_sync(
        {
            "status": "done",
            "finished_utc": "2026-08-21T22:31:54Z",
            "uploaded": 5,
            "skipped": 10,
            "failed": 0,
            "exit_code": 0,
        },
        now=now,
    )
    assert healthy["ok"] is True


def test_researcher_imports_llm_lane_not_lib():
    import inspect
    from scripts.hermes_external_researcher import _import_llm_generate, call_governed_deepseek
    src = inspect.getsource(call_governed_deepseek)
    assert "lib.llm_lane" not in src
    src2 = inspect.getsource(_import_llm_generate)
    assert "from llm_lane import generate" in src2
    assert "from lib.llm_lane" not in src2
