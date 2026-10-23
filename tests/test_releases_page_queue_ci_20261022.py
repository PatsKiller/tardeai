"""Releases page: main-HEAD exact-SHA CI from a cached receipt, and a loud census alert (2026-10-22).

Operator, on System -> Releases & schedules (served f7c1e96cb): "I don't see anything queued up." The queue panel
read "queue store 0 queued · PR census UNAVAILABLE · no_receipt" with 30 open PRs, and "Releasing next 0f5bf2453 ·
main CI UNAVAILABLE". Covered here:

* scripts/main_ci_watch.py — exact-SHA push/main CI of main HEAD (SUCCESS | FAILURE | PENDING), GET-only gh, one
  receipt; its required workflows equal the promote gate's (release_grant_preflight.REQUIRED_PUSH_WORKFLOWS).
* scripts/lib/releases_schedules_view.py — next_release.ci from that receipt with its age; FAILURE rows in
  release_errors; census_attempt / census_alert so a missing census says why, the last attempt and the next fire.
* scripts/pr_hygiene_audit.py — the executor runs from portfolio-server/CURRENT, which is not a clone (since
  release ee38621b1): resolve_repo falls back to the canonical checkout, and a no-slug real run writes a failed
  receipt instead of nothing.

Hermetic (AGENTS.md §24.6): TRADEAI_STATE_ROOT under tmp_path, fake gh JSON, tmp SQLite ledger and registry; no
network, no live state, no send.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import main_ci_watch as MCW  # noqa: E402
import pr_hygiene_audit as PHA  # noqa: E402
from lib import releases_schedules_view as R  # noqa: E402

NOW = datetime(2026, 10, 23, 2, 0, tzinfo=timezone.utc)  # 22:00 ET 10-22
HEAD = "0f5bf24537bed1bc0e9c4e76f2efbb607311bf3f"
OTHER = "f7c1e96cbcab399082de186e6367fa834df48e1c"
GOV, CIO, RR = MCW.REQUIRED_WORKFLOWS


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)
    monkeypatch.delenv("TRADEAI_PR_HYGIENE_REPO", raising=False)
    monkeypatch.delenv("TRADEAI_PR_HYGIENE_SLUG", raising=False)
    R.clear_cache()
    yield
    R.clear_cache()


def _run(
    path, *, sha=HEAD, status="completed", conclusion="success", rid=1, num=10, attempt=1, event="push", branch="main"
):
    return {
        "id": rid,
        "run_number": num,
        "run_attempt": attempt,
        "path": path,
        "name": Path(path).stem,
        "head_sha": sha,
        "event": event,
        "head_branch": branch,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://example.invalid/runs/{rid}",
        "updated_at": "2026-10-23T01:50:00Z",
        "workflow_id": 7,
    }


# ── main_ci_watch: pure evaluation ────────────────────────────────────────────────────────────────────────────


def test_required_workflows_equal_the_promote_gate():
    import release_grant_preflight as RGP

    assert set(MCW.REQUIRED_WORKFLOWS) == set(RGP.REQUIRED_PUSH_WORKFLOWS)


def test_all_success_is_success():
    s = MCW.evaluate(HEAD, [_run(GOV, rid=1), _run(CIO, rid=2), _run(RR, rid=3)])
    assert s["state"] == "SUCCESS" and s["counts"]["SUCCESS"] == 3 and s["head_sha"] == HEAD
    assert s["schema"] == "MainCiWatch@v1"


def test_in_progress_or_not_started_is_pending():
    s = MCW.evaluate(HEAD, [_run(GOV, rid=1), _run(CIO, rid=2, status="in_progress", conclusion=None)])
    assert s["state"] == "PENDING"
    by = {w["path"]: w["state"] for w in s["workflows"]}
    assert by == {GOV: "SUCCESS", CIO: "PENDING", RR: "MISSING"}


def test_any_failure_is_failure_even_with_pending():
    s = MCW.evaluate(HEAD, [_run(GOV, rid=1, conclusion="failure"), _run(CIO, rid=2, status="queued", conclusion=None)])
    assert s["state"] == "FAILURE"


def test_later_attempt_supersedes_and_other_shas_and_events_are_ignored():
    runs = [
        _run(GOV, rid=1, conclusion="failure"),
        _run(GOV, rid=1, attempt=2),  # rerun went green
        _run(CIO, rid=2),
        _run(RR, rid=3),
        _run(RR, rid=9, sha=OTHER, conclusion="failure"),
        _run(RR, rid=10, event="pull_request", conclusion="failure"),
        _run(RR, rid=11, branch="feature", conclusion="failure"),
    ]
    assert MCW.evaluate(HEAD, runs)["state"] == "SUCCESS"


# ── main_ci_watch: main() with a fake gh ──────────────────────────────────────────────────────────────────────


class _FakeGh:
    calls: list = []
    fail = False

    def __init__(self, slug, run=None):
        self.slug = slug

    def json(self, *args):
        PHA._assert_read_only_gh(args)  # the same guard the real Gh applies
        _FakeGh.calls.append(list(args))
        if _FakeGh.fail:
            raise PHA.AuditError("gh api exit 1: offline")
        if args[1].endswith("/commits/main"):
            return {"sha": HEAD}
        return {
            "workflow_runs": [
                _run(GOV, rid=1),
                _run(CIO, rid=2, status="in_progress", conclusion=None),
                _run(RR, rid=3),
            ]
        }


@pytest.fixture
def fake_gh(monkeypatch):
    _FakeGh.calls, _FakeGh.fail = [], False
    monkeypatch.setattr(PHA, "Gh", _FakeGh)
    return _FakeGh


def _receipt(tmp_path, lane="main-ci-watch"):
    return tmp_path / "state" / "data" / "runtime" / f"{lane}_last.json"


def test_real_run_writes_one_receipt(tmp_path, fake_gh, capsys):
    assert MCW.main(["--slug", "o/r"]) == 0
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] == "ok" and doc["summary"]["state"] == "PENDING" and doc["summary"]["head_sha"] == HEAD
    assert doc["summary"]["slug"] == "o/r"
    assert [c[:2] for c in fake_gh.calls] == [["api", "repos/o/r/commits/main"], ["api", "--paginate"]]
    assert sorted(p.name for p in (tmp_path / "state" / "data" / "runtime").iterdir()) == ["main-ci-watch_last.json"]


def test_dry_run_writes_nothing(tmp_path, fake_gh, capsys):
    assert MCW.main(["--slug", "o/r", "--dry-run"]) == 0
    assert not (tmp_path / "state").exists()
    assert "DRY-RUN" in capsys.readouterr().out


def test_github_unreadable_writes_failed_receipt_exit_1(tmp_path, fake_gh):
    fake_gh.fail = True
    assert MCW.main(["--slug", "o/r"]) == 1
    doc = json.loads(_receipt(tmp_path).read_text())
    assert doc["status"] != "ok" and doc["error"].startswith("AuditError")  # lane_last_receipt scrubs the text


def test_bad_sha_is_usage(fake_gh):
    assert MCW.main(["--slug", "o/r", "--sha", "abc"]) == 2


def test_main_ci_watch_reach_is_read_only():
    src = (ROOT / "scripts" / "main_ci_watch.py").read_text()
    for bad in (
        "send_telegram",
        "smtplib",
        "requests.post",
        "place_order",
        "brokers",
        "psycopg",
        "open(",
        "subprocess.run",
        "-X",
        "--method",
    ):
        assert bad not in src, bad


# ── pr_hygiene_audit: the executor's cwd is not a clone ───────────────────────────────────────────────────────


def _clone(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_resolve_repo_falls_back_to_the_canonical_checkout(tmp_path, monkeypatch):
    release = tmp_path / "release"  # portfolio-server/CURRENT: no .git since release ee38621b1
    (release / "scripts").mkdir(parents=True)
    canonical = _clone(tmp_path / "canonical")
    monkeypatch.setattr(PHA, "_SCRIPTS", release / "scripts")
    monkeypatch.setattr(PHA, "CANONICAL_CLONE", canonical)
    assert PHA.resolve_repo(None) == canonical
    monkeypatch.setattr(PHA, "CANONICAL_CLONE", tmp_path / "absent")
    assert PHA.resolve_repo(None) is None


def test_explicit_repo_that_is_not_a_clone_is_never_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(PHA, "CANONICAL_CLONE", _clone(tmp_path / "canonical"))
    assert PHA.resolve_repo(str(tmp_path / "nope")) is None
    monkeypatch.setenv("TRADEAI_PR_HYGIENE_REPO", str(tmp_path / "nope"))
    assert PHA.resolve_repo(None) is None


def test_no_slug_real_run_writes_a_failed_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(PHA, "resolve_repo", lambda explicit: None)
    assert PHA.main([]) == 2
    doc = json.loads(_receipt(tmp_path, "pr-hygiene-audit").read_text())
    assert doc["status"] != "ok" and doc["error"].startswith("no_github_slug")


def test_no_slug_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(PHA, "resolve_repo", lambda explicit: None)
    assert PHA.main(["--dry-run"]) == 2
    assert not (tmp_path / "state").exists()


# ── releases_schedules_view: main-HEAD CI ─────────────────────────────────────────────────────────────────────


def _write_watch(tmp_path, *, sha=HEAD, state="PENDING", status="ok", age_min=12, failed=()):
    p = _receipt(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    wf = [
        {
            "path": w,
            "name": Path(w).stem,
            "state": ("FAILURE" if w in failed else "SUCCESS" if failed else state),
            "conclusion": "failure" if w in failed else None,
            "url": "https://example.invalid/r",
            "updated_at": "2026-10-23T01:40:00Z",
        }
        for w in MCW.REQUIRED_WORKFLOWS
    ]
    p.write_text(
        json.dumps(
            {
                "status": status,
                "error": None if status == "ok" else "AuditError: offline",
                "finished_at": (NOW - timedelta(minutes=age_min)).isoformat(),
                "summary": {
                    "schema": "MainCiWatch@v1",
                    "head_sha": sha,
                    "state": state,
                    "checked_at": (NOW - timedelta(minutes=age_min)).isoformat(),
                    "workflows": wf,
                    "counts": {state: 3},
                },
            }
        )
    )
    return p


def _git(head=HEAD):
    def run(args):
        if args[0] == "rev-parse":
            return 0, head + "\n"
        if args[:2] == ["log", "-1"]:
            return 0, "2026-10-22T21:40:00-04:00\x1fMerge pull request #1963 from x/y\n"
        return 0, "Merge pull request #1963 from x/y\n"

    return run


def test_next_release_ci_from_the_watch_receipt_with_age(tmp_path):
    p = _write_watch(tmp_path, state="PENDING", age_min=12)
    f = R.read_next_release(tmp_path / "canonical", tmp_path / "deploy", OTHER, NOW, git=_git(), main_ci_receipt=p)
    ci = f["value"]["ci"]
    assert ci["state"] == "PENDING" and ci["age_s"] == 720 and ci["source"] == "receipt:main-ci-watch"
    assert ci["stale"] is False and len(ci["workflows"]) == 3


def test_watch_receipt_for_another_sha_is_unavailable_with_both_shas(tmp_path):
    p = _write_watch(tmp_path, sha=OTHER, state="SUCCESS")
    ci = R.read_next_release(tmp_path / "c", tmp_path / "d", OTHER, NOW, git=_git(), main_ci_receipt=p)["value"]["ci"]
    assert ci["state"] == "UNAVAILABLE" and "f7c1e96cb" in ci["reason"] and "0f5bf2453" in ci["reason"]


def test_failed_watch_run_and_missing_receipt_say_why(tmp_path):
    p = _write_watch(tmp_path, status="failed")
    ci = R.read_next_release(tmp_path / "c", tmp_path / "d", OTHER, NOW, git=_git(), main_ci_receipt=p)["value"]["ci"]
    assert ci["state"] == "UNAVAILABLE" and "last run failed" in ci["reason"]
    ci = R.read_next_release(
        tmp_path / "c", tmp_path / "d", OTHER, NOW, git=_git(), main_ci_receipt=tmp_path / "none.json"
    )["value"]["ci"]
    assert ci["state"] == "UNAVAILABLE" and "has not run" in ci["reason"]


def test_old_pending_receipt_is_flagged_stale(tmp_path):
    p = _write_watch(tmp_path, state="PENDING", age_min=300)
    ci = R.read_next_release(tmp_path / "c", tmp_path / "d", OTHER, NOW, git=_git(), main_ci_receipt=p)["value"]["ci"]
    assert ci["stale"] is True and "re-run" in ci["reason"]


def test_failure_workflows_become_release_errors(tmp_path):
    p = _write_watch(tmp_path, state="FAILURE", failed=(RR,))
    f = R.read_release_errors(tmp_path / "deploy", tmp_path / "rw", NOW, main_ci_receipt=p)
    rows = [r for r in f["value"]["rows"] if r["source"] == "receipt:main-ci-watch"]
    assert len(rows) == 1 and rows[0]["kind"] == "main CI failure" and "release-readiness" in rows[0]["detail"]


# ── releases_schedules_view: a missing census is loud ─────────────────────────────────────────────────────────


def _ledger(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE runs (run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT, "
        "started_at TEXT, finished_at TEXT, exit_code INTEGER, receipt_json TEXT)"
    )
    c.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)", rows)
    c.commit()
    c.close()
    return path


def _registry(path: Path):
    path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "lane_id": "pr-hygiene-audit",
                        "scheduler": {"stage": "canary"},
                        "dispatch": {"mode": "live", "cron": ["30 6 * * *"], "tz": "America/New_York"},
                    }
                ]
            }
        )
    )
    return path


def test_census_attempt_reads_last_attempt_and_next_fire(tmp_path):
    led = _ledger(
        tmp_path / "l.sqlite",
        [
            (
                "d:pr-hygiene-audit:dry_run:20261022T0630",
                "pr-hygiene-audit",
                "dry_run",
                "RUN_DONE",
                "2026-10-22T10:30:04+00:00",
                None,
                "2026-10-22T10:31:04+00:00",
                0,
                "{}",
            ),
            ("x", "other-lane", "live", "RUN_DONE", "2026-10-22T20:00:00+00:00", None, None, 0, "{}"),
        ],
    )
    a = R.census_attempt(led, _registry(tmp_path / "reg.json"), NOW)
    assert a["last_attempt"]["mode"] == "dry_run" and a["last_live_attempt"] is None
    assert a["dispatch_mode"] == "live" and a["stage"] == "canary"
    assert a["next_fire_at"] == "2026-10-23T10:30:00+00:00"
    msg = R.census_alert({"freshness": "UNAVAILABLE", "reason": "no_receipt"}, a)
    assert msg.startswith("PR census MISSING") and "never written a receipt" in msg
    assert "10/22 06:30 ET dry_run RUN_DONE (a dry run writes no receipt)" in msg
    assert "next fire 10/23 06:30 ET (live)" in msg and "Open PRs are UNKNOWN" in msg


def test_census_attempt_without_ledger_or_rows(tmp_path):
    a = R.census_attempt(tmp_path / "missing.sqlite", None, NOW)
    assert a["last_attempt"] is None and "ledger unreadable" in a["last_attempt_reason"]
    a = R.census_attempt(_ledger(tmp_path / "l.sqlite", []), None, NOW)
    assert a["last_attempt_reason"] == "no run of this lane in the coordination ledger"
    assert R.census_alert({"freshness": "OK"}, a) is None


def test_read_queue_carries_the_alert_and_never_reads_as_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(
        R.RTV,
        "build_queue",
        lambda db, q: {
            "freshness": "OK",
            "reason": None,
            "as_of": NOW.isoformat(),
            "total": 0,
            "rows": [],
            "census": {"value": None, "as_of": None, "freshness": "UNAVAILABLE", "reason": "no_receipt"},
        },
    )
    monkeypatch.setattr(R.RTV, "_receipt_titles", lambda p: {})
    led = _ledger(
        tmp_path / "l.sqlite",
        [("r", "pr-hygiene-audit", "dry_run", "RUN_DONE", "2026-10-22T10:30:04+00:00", None, None, 0, "{}")],
    )
    f = R.read_queue(None, NOW, ledger=led, registry=_registry(tmp_path / "reg.json"))
    assert f["freshness"] == "STALE" and f["reason"].startswith("PR census MISSING")
    census = f["value"]["census"]
    assert census["alert"] and census["open_prs"] is None and census["attempt"]["last_attempt"]["mode"] == "dry_run"
    assert f["value"]["store"]["total"] == 0  # a measured zero for the store, never the open-PR count


def test_default_paths_name_the_watch_receipt(tmp_path):
    assert R.default_paths()["main_ci_receipt"] == _receipt(tmp_path)
