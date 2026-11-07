"""ANCHOR: RELEASES_SCHEDULES_LOCAL_IDENTITY_20261107 — the releases page names the running build from local files.

LQ-20261107-239. The build that serves this host was activated from the integration line, not from main. The page
already read its identity from the CURRENT symlink and the BUILD_SHA pins, but then:
- main was an ancestor of the running build, so ``commits_ahead`` was 0 while ``is_serving`` was False, and the
  operator view read that pair as "the version that is running could not be identified";
- the deploy receipt (written only by the main deploy path) still named yesterday's build and nothing said so;
- the line the build came from and its stamp time were on disk (BUILD_BRANCH, BUILD_STAMPED_AT) but never read.

Pinned here, with synthetic SHAs and temp directories only (no GitHub, no network, no live state):
- the serving section carries ``build_branch`` / ``build_stamped_at`` from the release's own stamp files;
- ``deploy_receipt_matches`` is False when the receipt names another build, None when there is no receipt;
- ``serving_contains_main`` is True when main is an ancestor of the running build, False when it is not, None when
  git could not answer; and the KPI says "already inside the serving build" instead of "0 commits ahead";
- the git runner allows ``merge-base`` and still refuses anything that writes.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import releases_schedules_view as R  # noqa: E402

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)
SHA_RUN = "d" * 40
SHA_MAIN = "e" * 40
SHA_OLD = "f" * 40


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    R.clear_cache()
    yield
    R.clear_cache()


def _releases(tmp_path: Path, *, stamps: bool = True) -> Path:
    base = tmp_path / "releases"
    d = base / "ddddddddd-live-integration-20261107-144752"
    d.mkdir(parents=True)
    for pin in ("BUILD_SHA", "GIT_SHA", "SOURCE_COMMIT"):
        (d / pin).write_text(SHA_RUN + "\n")
    if stamps:
        (d / "BUILD_BRANCH").write_text("live-integration\n")
        (d / "BUILD_STAMPED_AT").write_text("2026-11-07T19:48:57Z\n")
    (base / "CURRENT").symlink_to(d)
    for pin in ("ACTIVE_RELEASE", "EXPECTED_RELEASE"):
        (base / pin).write_text(str(d.resolve()) + "\n")
    return base


def _deploy(tmp_path: Path, deployed_sha: str | None) -> Path:
    dep = tmp_path / "deploy"
    dep.mkdir()
    if deployed_sha:
        (dep / "deploy_receipt.json").write_text(json.dumps(
            {"ok": True, "mode": "promote", "at": "2026-11-06T18:50:00+00:00", "deployed_sha": deployed_sha}))
    return dep


def _git(ancestor_rc: int):
    def run(args):
        if args[0] == "rev-parse":
            return 0, SHA_MAIN + "\n"
        if args[:2] == ["log", "-1"]:
            return 0, "2026-11-06T13:37:35-05:00\x1fa merged change\n"
        if args[0] == "log":
            return 0, ""  # nothing on main that the running build lacks
        if args[:2] == ["merge-base", "--is-ancestor"]:
            assert args[2:] == [SHA_MAIN, SHA_RUN], args
            return ancestor_rc, ""
        raise AssertionError(args)
    return run


def test_serving_names_the_build_from_its_own_stamp_files(tmp_path):
    base = _releases(tmp_path)
    v = R.read_serving(base, _deploy(tmp_path, SHA_OLD), NOW)["value"]
    assert v["release_name"] == "ddddddddd-live-integration-20261107-144752"
    assert v["short_sha"] == "ddddddddd"
    assert v["build_branch"] == "live-integration"
    assert v["build_stamped_at"] == "2026-11-07T19:48:57Z"
    assert v["since_basis"] == "CURRENT symlink mtime"  # the old receipt is not this build's activation


def test_a_receipt_for_another_build_is_flagged_not_trusted(tmp_path):
    base = _releases(tmp_path)
    assert R.read_serving(base, _deploy(tmp_path, SHA_OLD), NOW)["value"]["deploy_receipt_matches"] is False
    other = tmp_path / "b"
    other.mkdir()
    assert R.read_serving(base, _deploy(other, SHA_RUN), NOW)["value"]["deploy_receipt_matches"] is True
    none = tmp_path / "c"
    none.mkdir()
    assert R.read_serving(base, _deploy(none, None), NOW)["value"]["deploy_receipt_matches"] is None


def test_missing_stamp_files_are_null_never_invented(tmp_path):
    v = R.read_serving(_releases(tmp_path, stamps=False), _deploy(tmp_path, None), NOW)["value"]
    assert v["build_branch"] is None and v["build_stamped_at"] is None


@pytest.mark.parametrize("rc,expected", [(0, True), (1, False), (128, None)])
def test_main_inside_the_running_build_is_measured(tmp_path, rc, expected):
    dep = _deploy(tmp_path, None)
    v = R.read_next_release(tmp_path / "canon", dep, SHA_RUN, NOW, git=_git(rc))["value"]
    assert v["is_serving"] is False and v["commits_ahead"] == 0
    assert v["serving_contains_main"] is expected


def test_main_serving_itself_contains_main_without_asking_git(tmp_path):
    def git(args):
        if args[0] == "rev-parse":
            return 0, SHA_RUN + "\n"
        if args[:2] == ["log", "-1"]:
            return 0, "2026-11-06T13:37:35-05:00\x1fx\n"
        raise AssertionError(args)
    v = R.read_next_release(tmp_path / "canon", _deploy(tmp_path, None), SHA_RUN, NOW, git=git)["value"]
    assert v["is_serving"] is True and v["serving_contains_main"] is True


def test_kpi_says_main_is_inside_the_build_not_zero_ahead():
    ok = {"freshness": "OK", "as_of": "x"}
    sections = {"serving": {**ok, "value": {"short_sha": "ddddddddd", "pins_agree": True}},
                "next_release": {**ok, "value": {"short_sha": "eeeeeeeee", "is_serving": False, "commits_ahead": 0,
                                                 "serving_contains_main": True, "ci": {"state": "OK"}}},
                "n8n_today": {**ok, "value": {}}, "release_errors": {**ok, "value": {"rows": []}}}
    nxt = next(k for k in R.kpis(sections) if k["key"] == "next_release")
    assert nxt["detail"].startswith("already inside the serving build") and nxt["tone"] == "neutral"


def test_git_runner_allows_merge_base_and_still_refuses_writes(tmp_path):
    run = R.git_runner(tmp_path)
    for args in (["fetch"], ["push"], ["checkout", "x"], ["update-ref", "x"], []):
        with pytest.raises(ValueError):
            run(args)
    rc, _ = run(["merge-base", "--is-ancestor", SHA_MAIN, SHA_RUN])  # not a repo: a non-zero rc, never a raise
    assert rc != 0
