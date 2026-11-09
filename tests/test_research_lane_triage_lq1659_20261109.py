"""LQ-20261107-1659 — the three research-lane alarms triaged on /v3/health.

Each test pins one verdict from the triage, so a future edit cannot quietly restore the
behaviour the evidence contradicted:

* drive-sync ``DEGRADED_STALE_SOURCE`` must mean the synced pin does not CONTAIN origin/main.
  The live release is normally AHEAD of main between promotes, so comparing for equality fired
  on every normal deploy;
* the overnight-deep alarm must carry its provider lane's own verdict — the lane writes no row
  when the provider refuses, so the RAW store can only say "silence" while the cause is on disk;
* a coverage stall must not be charged to thesis minting while the research leg is measurably
  down — then a flat thesis count is the absence of research, and deepseek's own lane alarms.

Fixtures are synthetic; no live identifier, address or value is asserted here.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import research_lane_health as hl

ROOT = Path(__file__).resolve().parents[1]

# Lazy on purpose: the fail-before run keeps these tests and reverts ONLY the sources, so a
# module-level import of a symbol that does not exist yet would abort collection and hide which
# pin each test actually tests.
def _source_status_for(pin, main_sha, *, repo, run=None):
    from scripts.lib.drive_sync_health import source_status_for
    return source_status_for(pin, main_sha, repo=repo, run=run)


def _collect_coverage_stall(**kw):
    from scripts.lib.research_lane_health import collect_coverage_stall
    return collect_coverage_stall(**kw)


def _oauth_lane_verdict(**kw):
    from scripts.lib.research_lane_health import oauth_lane_verdict
    return oauth_lane_verdict(**kw)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=test@example.invalid",
         "-c", "user.name=test", *args],
        check=True, capture_output=True, text=True,
    )
    return out.stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name + "\n", encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _repo_with_ahead_release(tmp_path: Path) -> tuple[Path, str, str]:
    """main = A; release = A + B (the live topology: the released pin is AHEAD of main)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    main_sha = _commit(repo, "a.txt")
    _git(repo, "checkout", "-q", "-b", "release")
    release_sha = _commit(repo, "b.txt")
    return repo, main_sha, release_sha


def test_a_release_ahead_of_main_is_not_a_stale_source(tmp_path):
    """The normal deployment: pin contains main. Equality called this degraded; it is not."""
    repo, main_sha, release_sha = _repo_with_ahead_release(tmp_path)
    assert _source_status_for(release_sha, main_sha, repo=repo) == "ok"
    assert _source_status_for(release_sha, release_sha, repo=repo) == "ok"


def test_a_release_that_does_not_contain_main_is_a_stale_source(tmp_path):
    """The risk the alarm names: main published docs the synced pin does not have."""
    repo, main_sha, release_sha = _repo_with_ahead_release(tmp_path)
    assert _source_status_for(main_sha, release_sha, repo=repo) == "DEGRADED_STALE_SOURCE"


def test_a_diverged_pin_is_a_stale_source(tmp_path):
    repo, main_sha, release_sha = _repo_with_ahead_release(tmp_path)
    _git(repo, "checkout", "-q", "main")
    other_sha = _commit(repo, "c.txt")
    assert _source_status_for(other_sha, release_sha, repo=repo) == "DEGRADED_STALE_SOURCE"


def test_an_unreadable_repository_is_not_evidence_of_staleness(tmp_path):
    """git says 128 for 'cannot run'; only 1 ('not an ancestor') is a verdict."""
    assert _source_status_for("aaa", "bbb", repo=tmp_path, run=lambda cmd: 128) == "ok"
    assert _source_status_for("aaa", "bbb", repo=tmp_path, run=lambda cmd: 1) == "DEGRADED_STALE_SOURCE"
    assert _source_status_for(None, "bbb", repo=tmp_path) == "ok"
    assert _source_status_for("aaa", None, repo=tmp_path) == "ok"


def test_the_writer_no_longer_decides_staleness_itself():
    """The decision lives in ONE place now; the writer calls it instead of comparing."""
    src = (ROOT / "scripts" / "sync-docs-to-drive.sh").read_text(encoding="utf-8")
    assert "source_status_for(" in src
    assert "DEGRADED_STALE_SOURCE" not in src


def test_the_overnight_alarm_carries_its_providers_verdict(tmp_path):
    """The provider's own prober says WHY; the alarm used to say only 'zero non-error 24h'."""
    path = tmp_path / "oauth_lane_status.json"
    path.write_text(json.dumps({
        "chatgpt": {"lane": "chatgpt", "ok": False, "kind": "rate_limited",
                    "detail": "429 Client Error: Too Many Requests for url: http://127.0.0.1:9/v1",
                    "consec_fail": 7, "last_ok": 1, "quota_exhausted": True},
    }), encoding="utf-8")
    verdict = _oauth_lane_verdict(path=path)
    assert verdict is not None and verdict["ok"] is False
    hint = hl.fix_hint({
        "lane": "overnight-deep",
        "firing": ["zero_non_error_24h"],
        "provider_verdict": {"lane": "chatgpt", "kind": verdict["kind"], "detail": verdict["detail"],
                             "consec_fail": verdict["consec_fail"], "quota_exhausted": True},
    })
    assert "rate_limited" in hint and "429" in hint
    assert "not the scheduler" in hint


def test_the_overnight_hint_without_a_verdict_names_the_real_mechanics(tmp_path):
    """No verdict: the hint must still be true — the lane writes no row, so targets repeat."""
    assert _oauth_lane_verdict(path=tmp_path / "absent.json") is None
    hint = hl.fix_hint({"lane": "overnight-deep", "firing": ["zero_non_error_24h"]})
    assert "ChatGPT" in hint
    assert "gemma" not in hint          # the 2026-08 retarget is long done
    assert "journal" in hint            # where the per-target reason actually is


def test_a_coverage_stall_is_not_charged_to_the_thesis_pipeline_while_research_is_down():
    row = _collect_coverage_stall(
        deepseek_ok_24h=33, thesis_substantive=6, thesis_coverage=22, thesis_held=23,
        research_leg={"attempts_24h": 183, "error_rate_24h": 84.2, "non_error_24h": 29},
        persist=False,
    )
    assert row["ok"] is True
    assert row["firing"] == []
    assert "research_lane_unhealthy" in row["held_by"]
    hint = hl.fix_hint(row)
    assert "deepseek lane carries that alarm" in hint


def test_a_healthy_leg_with_a_flat_thesis_still_fires():
    """The alarm is kept for the condition it describes; only a broken premise holds it."""
    row = _collect_coverage_stall(
        deepseek_ok_24h=33, thesis_substantive=6, thesis_coverage=22, thesis_held=23,
        research_leg={"attempts_24h": 60, "error_rate_24h": 2.0, "non_error_24h": 58},
        persist=False,
    )
    assert row["ok"] is False
    assert any("research_up_thesis_flat" in x for x in row["firing"])
    assert row["held_by"] is None


def test_no_research_leg_keeps_the_previous_callers_behaviour():
    row = _collect_coverage_stall(
        deepseek_ok_24h=33, thesis_substantive=6, thesis_coverage=22, thesis_held=23,
        persist=False,
    )
    assert row["ok"] is False
    assert row["held_by"] is None
