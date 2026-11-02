"""One merge rule: every check on the exact head is green, not just the required ones.

Regression: PR #2465 merged 2026-11-01 with `secret-scan` red on four heads, because the merge
gate read only the branch's *required* checks (cio-hardening, agent-governance, release-readiness,
ci-gate) and `secret-scan` was not among them. Main went red and the deploy was blocked.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import pr_all_checks_green as G  # noqa: E402


def _run(name: str, conclusion: str | None, *, status: str = "completed", started: str = "2026-11-01T10:00:00Z"):
    return {"name": name, "conclusion": conclusion, "status": status, "started_at": started}


def test_every_check_green_passes():
    res = G.evaluate([_run("cio-hardening", "success"), _run("secret-scan", "success")])
    assert res["ok"] is True
    assert res["failing"] == []


def test_a_red_non_required_check_blocks():
    """The regression: `secret-scan` is green nowhere near 'required', and it must still block."""
    res = G.evaluate([_run("cio-hardening", "success"), _run("secret-scan", "failure")])
    assert res["ok"] is False
    assert res["failing"] == ["secret-scan: failure"]
    assert "secret-scan" in G.describe(res)


def test_neutral_and_skipped_do_not_block_but_are_reported():
    res = G.evaluate(
        [
            _run("cio-hardening", "success"),
            _run("docs-only", "neutral"),
            _run("sharded-suite", "skipped"),
        ]
    )
    assert res["ok"] is True
    assert res["skipped"] == ["sharded-suite"]
    assert res["passing"] == ["cio-hardening", "docs-only"]


def test_pending_check_blocks():
    res = G.evaluate([_run("cio-hardening", "success"), _run("secret-scan", None, status="in_progress")])
    assert res["ok"] is False
    assert "in_progress" in res["failing"][0]


def test_latest_run_per_name_wins():
    superseded = [
        _run("secret-scan", "failure", started="2026-11-01T09:00:00Z"),
        _run("secret-scan", "success", started="2026-11-01T11:00:00Z"),
    ]
    assert G.evaluate(superseded)["ok"] is True
    regressed = [
        _run("secret-scan", "success", started="2026-11-01T09:00:00Z"),
        _run("secret-scan", "failure", started="2026-11-01T11:00:00Z"),
    ]
    assert G.evaluate(regressed)["ok"] is False


def test_no_check_runs_is_not_green():
    res = G.evaluate([])
    assert res["ok"] is False
    assert res["reason"] == "no check runs on the head"
    # A caller that explicitly tolerates it (e.g. a repo with no checks) can say so.
    assert G.evaluate([], allow_empty=True)["ok"] is True


def test_all_checks_green_fetches_the_exact_head():
    seen: list[str] = []

    def gh_json(path: str):
        seen.append(path)
        return {"check_runs": [_run("cio-hardening", "success"), _run("secret-scan", "failure")]}

    res = G.all_checks_green(gh_json, "owner/repo", "abc1234")
    assert seen == ["repos/owner/repo/commits/abc1234/check-runs?per_page=100&page=1"]
    assert res["ok"] is False and res["failing"] == ["secret-scan: failure"]


def test_describe_is_plain_english_and_bounded():
    res = G.evaluate([_run(f"check-{i}", "failure") for i in range(40)])
    text = G.describe(res)
    assert text.startswith("not green:")
    assert "check-0: failure" in text
    assert len(text) <= G.DESCRIBE_LIMIT


def test_a_later_skip_never_hides_an_earlier_failure():
    """A skipped run must not replace a non-skipped one: that is how a red check disappears."""
    runs = [
        _run("secret-scan", "failure", started="2026-11-01T09:00:00Z"),
        _run("secret-scan", "skipped", started="2026-11-01T11:00:00Z"),
    ]
    res = G.evaluate(runs)
    assert res["ok"] is False
    assert res["failing"] == ["secret-scan: failure"]


def test_a_missing_status_is_pending_not_completed():
    """GitHub omits `status` on some runs; treating that as completed would grade an unfinished check."""
    res = G.evaluate([{"name": "secret-scan", "conclusion": None}])
    assert res["ok"] is False
    assert "queued" in res["failing"][0] or "pending" in res["failing"][0]


def test_every_bad_conclusion_blocks():
    for conclusion in ("cancelled", "timed_out", "action_required", "stale", "startup_failure"):
        res = G.evaluate([_run("cio-hardening", "success"), _run("other", conclusion)])
        assert res["ok"] is False, conclusion
        assert res["failing"] == [f"other: {conclusion}"]


def test_paginates_when_the_head_carries_more_than_one_page():
    pages = {1: [_run(f"check-{i}", "success") for i in range(100)], 2: [_run("late", "failure")]}

    def gh_json(path: str):
        page = 2 if "page=2" in path else 1
        rows = pages[page]
        return {"total_count": 101, "check_runs": rows}

    res = G.all_checks_green(gh_json, "owner/repo", "abc1234")
    assert res["ok"] is False
    assert res["failing"] == ["late: failure"]


def test_fails_closed_when_it_cannot_read_every_run():
    def gh_json(path: str):
        # Claims three runs, returns one, and never yields a second page.
        return {"total_count": 3, "check_runs": [_run("cio-hardening", "success")]}

    res = G.all_checks_green(gh_json, "owner/repo", "abc1234")
    assert res["ok"] is False
    assert "could not read" in (res["reason"] or "")
