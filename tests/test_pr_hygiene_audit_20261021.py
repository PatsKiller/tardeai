"""PR hygiene audit (operator process plan 2026-10-21): scripts/pr_hygiene_audit.py, scripts/pr_overlap_check.py,
the needs-action source ``pr_hygiene`` and the n8n SHADOW lane ``pr-hygiene-audit``.

A 59-PR backlog built up unnoticed and caused a duplicate fix (#1906 re-did #1836). Pins, all hermetic: canned gh
JSON (no network), tmp git repos (a bare "origin" and a clone under tmp_path), tmp state roots and a tmp
coordination ledger. Nothing here calls GitHub, the live ledger, n8n or a sender.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # CI runners have no driver; a minimal stand-in only when the real one is absent (never shadows it)
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - depends on the runner
    _pg = types.ModuleType("psycopg2")
    _pg.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("psycopg2 stand-in: no DB in tests"))
    _pg.Error = Exception
    sys.modules["psycopg2"] = _pg

import pr_hygiene_audit as PHA  # noqa: E402
import pr_overlap_check as POC  # noqa: E402
from scripts.lib import needs_action as NA  # noqa: E402

COVERS = ["scripts/pr_hygiene_audit.py", "scripts/pr_overlap_check.py", "scripts/lib/needs_action.py",
          "config/lane_registry.json", "config/n8n_run_allowlist.json", "config/n8n_health_contracts.json",
          "config/host_comms_intent_routes.json"]

NOW = datetime(2026, 10, 21, 18, 0, tzinfo=timezone.utc)
SLUG = "example-owner/example-repo"
LANE = "pr-hygiene-audit"
RECEIPT = "data/runtime/pr-hygiene-audit_last.json"


# ── fakes ──────────────────────────────────────────────────────────────────────────────────────────────────────


class _R:
    def __init__(self, out="", rc=0, err=""):
        self.stdout, self.returncode, self.stderr = out, rc, err


class FakeGh:
    """Routes canned JSON by argv; records every call; an unknown argv fails like gh would."""

    def __init__(self, routes, fail=()):
        self.routes, self.fail, self.calls = routes, set(fail), []

    def __call__(self, argv):
        self.calls.append(list(argv))
        key = " ".join(argv)
        for prefix in self.fail:
            if key.startswith(prefix):
                return _R("", 1, "HTTP 502")
        for prefix, payload in self.routes.items():
            if key.startswith(prefix):
                return _R(json.dumps(payload(argv) if callable(payload) else payload))
        return _R("", 1, f"no fake for {key}")


def _pr(n, *, head, sha, title="t", body="", base="main", updated=NOW - timedelta(hours=1), checks=None, **kw):
    return {"number": n, "title": title, "body": body, "isDraft": kw.get("draft", False),
            "createdAt": (NOW - timedelta(days=10)).isoformat(), "updatedAt": updated.isoformat(),
            "headRefName": head, "headRefOid": sha, "baseRefName": base, "mergeable": kw.get("mergeable", "UNKNOWN"),
            "url": f"https://github.com/{SLUG}/pull/{n}", "isCrossRepository": False,
            "labels": [{"name": x} for x in kw.get("labels", [])], "author": {"login": "someone"},
            "statusCheckRollup": checks if checks is not None else [
                {"__typename": "CheckRun", "name": c, "status": "COMPLETED", "conclusion": "SUCCESS"}
                for c in ("cio-hardening", "agent-governance", "release-readiness")]}


def _patch(*hunks):
    return "\n".join(hunks)


# ── read-only enforcement ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("argv", [
    ["pr", "merge", "1"], ["pr", "close", "1"], ["pr", "comment", "1", "-b", "x"], ["pr", "edit", "1"],
    ["pr", "ready", "1"], ["api", "-X", "POST", "repos/a/b/issues/1/comments"], ["api", "--method=PATCH", "x"],
    ["api", "repos/a/b/issues/1/comments", "-f", "body=x"], ["api", "graphql", "-F", "query=mutation{}"],
    ["api", "graphql"], ["repo", "delete"], ["issue", "comment", "1"], ["release", "create", "v1"],
])
def test_gh_mutations_are_refused_before_running(argv):
    with pytest.raises(PHA.ReadOnlyViolation):
        PHA._assert_read_only_gh(argv)
    fake = FakeGh({})
    with pytest.raises(PHA.ReadOnlyViolation):
        PHA.Gh(SLUG, run=fake).json(*argv)
    assert fake.calls == []


@pytest.mark.parametrize("argv", [["push", "origin", "x"], ["branch", "-D", "x"], ["checkout", "x"],
                                  ["reset", "--hard"], ["worktree", "remove", "x"], ["remote", "add", "x", "y"],
                                  ["fetch", "origin"], ["update-ref", "-d", "refs/heads/x"], ["gc"]])
def test_git_mutations_are_refused(argv):
    with pytest.raises(PHA.ReadOnlyViolation):
        PHA._assert_read_only_git(argv)


def test_fetch_needs_the_flag_and_never_prunes():
    PHA._assert_read_only_git(["fetch", "--quiet", "origin"], allow_fetch=True)
    with pytest.raises(PHA.ReadOnlyViolation):
        PHA._assert_read_only_git(["fetch", "--prune", "origin"], allow_fetch=True)


# ── pure parts ─────────────────────────────────────────────────────────────────────────────────────────────────


def test_hold_markers():
    assert PHA.hold_markers("DO-NOT-MERGE: x", "") == ["DO-NOT-MERGE"]
    assert PHA.hold_markers("x", "Status: PROPOSED (awaiting)") == ["PROPOSED"]
    assert PHA.hold_markers("x", "", ["do-not-merge"]) == ["DO-NOT-MERGE"]
    assert PHA.hold_markers("we proposed a fix", "do not merge yet") == ["DO-NOT-MERGE"]
    assert PHA.hold_markers("we proposed a fix", "") == []


def test_required_checks_status_on_the_head():
    req = ["cio-hardening", "agent-governance"]
    ok = [{"name": "cio-hardening", "state": "SUCCESS"}, {"name": "agent-governance", "state": "SKIPPED"}]
    assert PHA.required_checks_status(ok, req)["status"] == "PASS"
    bad = [{"name": "cio-hardening", "state": "FAILURE"}, {"name": "agent-governance", "state": "SUCCESS"}]
    assert PHA.required_checks_status(bad, req) == {"status": "FAIL", "missing": [], "failed": ["cio-hardening"],
                                                    "pending": []}
    assert PHA.required_checks_status(ok[:1], req)["missing"] == ["agent-governance"]
    assert PHA.required_checks_status([{"name": "cio-hardening", "state": "PENDING"}, ok[1]], req)["status"] == "PENDING"
    assert PHA.required_checks_status(None, req)["status"] == "UNKNOWN"


def test_patch_hunks_spans_and_bodies():
    hs = PHA.parse_patch_hunks(_patch("@@ -10,3 +10,4 @@ def foo(x):", " a", "-b", "+B", "+C", " d",
                                      "@@ -0,0 +1,2 @@", "+new", "+file"))
    assert hs[0]["func"] == "def foo(x):" and hs[0]["span"] == (11, 12) and hs[0]["deletes"]
    assert hs[1]["span"] == (1, 1) and not hs[1]["deletes"]
    assert hs[0]["body"] != hs[1]["body"]


def _files(**by_path):
    return {path: PHA.parse_patch_hunks(p) for path, p in by_path.items()}


def test_duplicate_same_function_or_overlapping_hunks():
    a = _files(**{"scripts/lib/cc_auth.py": _patch("@@ -100,2 +100,3 @@ def evaluate_request(cfg):", " x", "+guard_a", " y")})
    b = _files(**{"scripts/lib/cc_auth.py": _patch("@@ -130,2 +130,3 @@ def evaluate_request(cfg):", " x", "+guard_b", " y")})
    c = _files(**{"scripts/lib/cc_auth.py": _patch("@@ -400,2 +400,3 @@ def other():", " x", "+z", " y")})
    d = _files(**{"config/x.json": _patch("@@ -5,3 +5,3 @@", " a", "-b", "+B", " c")})
    e = _files(**{"config/x.json": _patch("@@ -5,3 +5,3 @@", " a", "-b", "+b2", " c")})
    dups = PHA.detect_duplicates({1: a, 2: b, 3: c, 4: d, 5: e})
    assert [x["prs"] for x in dups] == [[1, 2], [4, 5]]
    assert dups[0]["files"][0]["functions"] == ["def evaluate_request(cfg):"] and dups[0]["confidence"] == "medium"
    assert dups[1]["confidence"] == "high"  # both modify the same existing line


def test_duplicate_ignores_ledgers_and_shared_identical_hunks():
    ledger = _patch("@@ -35,2 +35,3 @@ GATES = [", " x", "+gate", " y")
    a = _files(**{"scripts/run_cio_hardening_ci.py": ledger, "docs/INDEX.md": ledger})
    b = _files(**{"scripts/run_cio_hardening_ci.py": ledger.replace("+gate", "+other"), "docs/INDEX.md": ledger})
    assert PHA.detect_duplicates({1: a, 2: b}) == []
    shared = _patch("@@ -10,2 +10,3 @@ def f():", " x", "+same line", " y")
    assert PHA.detect_duplicates({1: _files(**{"a.py": shared}), 2: _files(**{"a.py": shared})}) == []


def test_superseded_detector():
    assert PHA.detect_superseded(contained_in_main=True, files=["a"], main_changed=set(), conflict=False)["confidence"] == "high"
    s = PHA.detect_superseded(contained_in_main=False, files=["a.py", "docs/INDEX.md"], main_changed={"a.py"}, conflict=False)
    assert s["reason"] == "all_files_changed_on_main_since_last_update" and s["confidence"] == "low"
    assert PHA.detect_superseded(contained_in_main=False, files=["a.py"], main_changed={"a.py"}, conflict=True)["confidence"] == "medium"
    assert PHA.detect_superseded(contained_in_main=False, files=["a.py", "b.py"], main_changed={"a.py"}, conflict=True) is None
    assert PHA.detect_superseded(contained_in_main=False, files=["docs/INDEX.md"], main_changed={"docs/INDEX.md"}, conflict=False) is None
    assert PHA.detect_superseded(contained_in_main=None, files=["a.py"], main_changed=None, conflict=None) is None


def test_stale_hold_detector():
    pr = {"holds": ["PROPOSED"], "updated_at": (NOW - timedelta(days=4)).isoformat()}
    assert PHA.detect_stale_hold(pr, NOW)["idle_days"] == 4.0
    assert PHA.detect_stale_hold({**pr, "updated_at": (NOW - timedelta(days=2)).isoformat()}, NOW) is None
    assert PHA.detect_stale_hold({**pr, "holds": []}, NOW) is None


def test_stacked_detector_and_declared_parent():
    pr = {"number": 9, "base": "feat/a", "title": "x"}
    assert PHA.detect_stacked(pr, {"merged_pr": 7, "exists": False})["reasons"] == ["base PR #7 merged"]
    assert PHA.detect_stacked(pr, {"exists": False})["reasons"] == ["base branch gone"]
    assert PHA.detect_stacked(pr, {"exists": True, "base_moved": True})["reasons"] == ["base moved since the PR was cut"]
    assert PHA.detect_stacked(pr, {"exists": True, "base_moved": False}) is None
    assert PHA.declared_parent({"number": 9, "title": "batch 2 (stacked on #8)", "body": ""}) == 8
    assert PHA.declared_parent({"number": 9, "title": "x", "body": "Stacked on PR #5."}) == 5
    assert PHA.declared_parent({"number": 9, "title": "x", "body": ""}) is None


def test_fingerprint_ignores_unpushed_and_order():
    f = [{"key": "CONFLICT:#2", "kind": "CONFLICT"}, {"key": "UNPUSHED:x", "kind": "UNPUSHED"},
         {"key": "STALE_HOLD:#1", "kind": "STALE_HOLD"}]
    fp, keys = PHA.fingerprint(f)
    assert keys == ["CONFLICT:#2", "STALE_HOLD:#1"] and fp == PHA.fingerprint(list(reversed(f)))[0]


# ── tmp git repos: merge-tree, behind, superseded, stacked, unpushed ──────────────────────────────────────────


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=True)
    return r.stdout.strip()


def _commit(repo, path, text, msg):
    p = Path(repo) / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    """origin (bare) + clone. Branches: conflict, clean, merged (already in main), stack-base/stack-top, wip (local)."""
    origin, clone = tmp_path / "origin.git", tmp_path / "clone"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    _git(clone, "checkout", "-q", "-b", "main")
    _commit(clone, "a.py", "line1\nline2\nline3\n", "base")
    _commit(clone, "b.py", "b1\n", "b")
    _git(clone, "push", "-q", "origin", "main")
    shas = {}
    _git(clone, "checkout", "-q", "-b", "conflict", "main")
    shas["conflict"] = _commit(clone, "a.py", "line1\nCONFLICT\nline3\n", "conflict edit")
    _git(clone, "checkout", "-q", "-b", "clean", "main")
    shas["clean"] = _commit(clone, "c.py", "new\n", "clean add")
    _git(clone, "checkout", "-q", "-b", "merged", "main")
    shas["merged"] = _commit(clone, "d.py", "d\n", "merged work")
    _git(clone, "checkout", "-q", "-b", "stack-base", "main")
    shas["stack-base"] = _commit(clone, "e.py", "e\n", "stack base")
    _git(clone, "checkout", "-q", "-b", "stack-top", "stack-base")
    shas["stack-top"] = _commit(clone, "f.py", "f\n", "stack top")
    _git(clone, "checkout", "-q", "main")
    _git(clone, "merge", "-q", "--no-ff", "merged", "-m", "merge merged")
    _commit(clone, "a.py", "line1\nMAIN\nline3\n", "main moves a.py")
    _commit(clone, "b.py", "b2\n", "main moves b.py")
    for b in ("main", "conflict", "clean", "merged", "stack-base", "stack-top"):
        _git(clone, "push", "-q", "origin", b)
    # stack-base moves after stack-top was cut
    _git(clone, "checkout", "-q", "stack-base")
    _commit(clone, "e.py", "e2\n", "stack base moved")
    _git(clone, "push", "-q", "origin", "stack-base")
    # local-only work: 2 commits on no remote
    _git(clone, "checkout", "-q", "-b", "wip", "main")
    _commit(clone, "w.py", "1\n", "wip one")
    _commit(clone, "w.py", "2\n", "wip two: last subject")
    _git(clone, "checkout", "-q", "main")
    _git(clone, "fetch", "-q", "origin")
    return clone, shas


def _after_commits():
    return datetime.now(timezone.utc) + timedelta(hours=1)


def _gh_for(shas, *, old=NOW - timedelta(days=5)):
    prs = [
        # updated after the tmp repo's (wall-clock) commits, so the files-changed heuristic does not fire for 1 and 2
        _pr(1, head="conflict", sha=shas["conflict"], title="fix conflict", updated=_after_commits()),
        _pr(2, head="clean", sha=shas["clean"], title="add c", updated=_after_commits()),
        _pr(3, head="merged", sha=shas["merged"], title="already merged work", updated=old),
        _pr(4, head="stack-top", sha=shas["stack-top"], base="stack-base", title="top of stack", updated=old,
            body="PROPOSED"),
    ]
    files = {
        1: [{"filename": "a.py", "patch": "@@ -1,3 +1,3 @@\n line1\n-line2\n+CONFLICT\n line3"}],
        2: [{"filename": "c.py", "patch": "@@ -0,0 +1 @@\n+new"}],
        3: [{"filename": "d.py", "patch": "@@ -0,0 +1 @@\n+d"}],
        4: [{"filename": "f.py", "patch": "@@ -0,0 +1 @@\n+f"}],
    }
    routes = {"pr list --repo example-owner/example-repo --state open": prs,
              "pr list --repo example-owner/example-repo --state merged --head": [],
              "pr list --repo example-owner/example-repo --state all": [
                  {"number": 1, "headRefName": "conflict", "state": "OPEN"}],
              f"api repos/{SLUG}/branches/main/protection/required_status_checks": {"contexts": ["cio-hardening"]}}
    for n, rows in files.items():
        routes[f"api --paginate repos/{SLUG}/pulls/{n}/files"] = rows
    return FakeGh(routes)


def test_audit_end_to_end_on_tmp_repos(repo):
    clone, shas = repo
    fake = _gh_for(shas)
    rep = PHA.audit(PHA.Gh(SLUG, run=fake), PHA.Git(clone), now=NOW)
    by = {p["number"]: p for p in rep["prs"]}
    kinds = {(f["kind"], f["pr"]) for f in rep["findings"]}
    assert rep["mergeability"] == "git_merge_tree" and rep["required_checks"]["source"] == "branch_protection"
    assert by[1]["conflict"] is True and ("CONFLICT", 1) in kinds
    assert by[2]["conflict"] is False and by[2]["behind_main"] == 4 and not any(k[1] == 2 for k in kinds)
    assert by[3]["contained_in_main"] is True
    sup = next(f for f in rep["findings"] if f["kind"] == "SUPERSEDED")
    assert sup["pr"] == 3 and sup["confidence"] == "high"
    st = next(f for f in rep["findings"] if f["kind"] == "STACKED")
    assert st["pr"] == 4 and "base moved since the PR was cut" in st["detail"]["reasons"]
    assert ("STALE_HOLD", 4) in kinds
    assert by[1]["required_checks"] == {"status": "PASS", "missing": [], "failed": [], "pending": [],
                                        "head": shas["conflict"]}
    # local work: wip has 2 commits on no remote; branch + count + subject only
    un = [f for f in rep["findings"] if f["kind"] == "UNPUSHED"]
    assert [(u["detail"]["branch"], u["detail"]["commits"], u["detail"]["last_subject"]) for u in un] == [
        ("wip", 2, "wip two: last subject")]
    assert set(un[0]["detail"]) == {"branch", "commits", "last_subject", "last_commit_at", "worktree", "pr", "pr_state"}
    assert rep["counts"] == {"CONFLICT": 1, "SUPERSEDED": 1, "DUPLICATE": 0, "STACKED": 1, "STALE_HOLD": 1,
                             "UNPUSHED": 1}
    # read-only: only list/view/GET calls were made
    assert all(c[0] in ("pr", "api") and (c[0] != "pr" or c[1] in ("list", "view")) for c in fake.calls)


def test_superseded_by_files_changed_on_main(repo):
    clone, shas = repo
    fake = _gh_for(shas)
    # PR 1 last updated BEFORE main moved a.py -> every file it touches changed on main since: low/medium heuristic
    rows = fake.routes["pr list --repo example-owner/example-repo --state open"]
    rows[0]["updatedAt"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    rep = PHA.audit(PHA.Gh(SLUG, run=fake), PHA.Git(clone), now=datetime.now(timezone.utc))
    sup = next(f for f in rep["findings"] if f["kind"] == "SUPERSEDED" and f["pr"] == 1)
    assert sup["detail"]["reason"] == "all_files_changed_on_main_since_last_update"
    assert sup["confidence"] == "medium"  # it also conflicts


def test_settled_local_branches_are_counted_not_findings(repo):
    clone, shas = repo
    fake = _gh_for(shas)
    fake.routes["pr list --repo example-owner/example-repo --state all"] = [
        {"number": 77, "headRefName": "wip", "state": "MERGED"}]
    rep = PHA.audit(PHA.Gh(SLUG, run=fake), PHA.Git(clone), now=NOW)
    assert not [f for f in rep["findings"] if f["kind"] == "UNPUSHED"]
    assert rep["local_unpushed"]["settled_local"] == {"MERGED": 1}


def test_rest_fallback_and_no_clone():
    prs_rest = [{"number": 5, "title": "DO-NOT-MERGE x", "body": "", "draft": True,
                 "created_at": (NOW - timedelta(days=9)).isoformat(), "updated_at": (NOW - timedelta(days=8)).isoformat(),
                 "head": {"ref": "h", "sha": "abc", "repo": {"full_name": SLUG}},
                 "base": {"ref": "main", "repo": {"full_name": SLUG}}, "html_url": "u5", "labels": [], "user": {"login": "x"}}]
    fake = FakeGh({f"api --paginate repos/{SLUG}/pulls?state=open": prs_rest,
                   f"api repos/{SLUG}/commits/abc/check-runs": {"check_runs": [
                       {"name": "cio-hardening", "status": "completed", "conclusion": "failure"}]},
                   f"api --paginate repos/{SLUG}/pulls/5/files": [],
                   f"api repos/{SLUG}/compare/main...abc": {"behind_by": 4, "status": "diverged"}},
                  fail=["pr list", f"api repos/{SLUG}/branches"])
    rep = PHA.audit(PHA.Gh(SLUG, run=fake), PHA.Git(None), now=NOW)
    p = rep["prs"][0]
    assert rep["source"] == "rest_api" and rep["required_checks"]["source"] == "fallback_constant"
    assert p["draft"] and p["holds"] == ["DO-NOT-MERGE"] and p["behind_main"] == 4
    assert p["required_checks"]["status"] == "FAIL" and rep["mergeability"] == "github_mergeable"
    assert rep["local_unpushed"]["measured"] is False
    assert {f["kind"] for f in rep["findings"]} == {"STALE_HOLD"}


def test_github_unreadable_raises():
    fake = FakeGh({}, fail=["pr list", "api"])
    with pytest.raises(PHA.AuditError):
        PHA.audit(PHA.Gh(SLUG, run=fake), PHA.Git(None), now=NOW)


# ── receipt, dry run, alert-on-change, weekly digest ───────────────────────────────────────────────────────────


def _report(keys=("CONFLICT:#1",), open_prs=3):
    findings = [{"key": k, "kind": k.split(":")[0], "severity": PHA.SEVERITY[k.split(":")[0]], "pr": 1, "prs": [1],
                 "title": f"{k} title", "url": "https://example.invalid/pull/1", "confidence": None, "detail": {}}
                for k in keys]
    fp, ak = PHA.fingerprint(findings)
    counts = {k: sum(1 for f in findings if f["kind"] == k) for k in PHA.SEVERITY}
    return {"schema": PHA.SCHEMA, "as_of": NOW.isoformat(), "repo": SLUG, "source": "gh_pr_list",
            "mergeability": "git_merge_tree", "required_checks": {"contexts": [], "source": "fallback_constant"},
            "open_prs": open_prs, "drafts": 0, "held": 0, "required_checks_failing": 0, "counts": counts,
            "fingerprint": fp, "alert_keys": ak, "errors": {}, "findings": findings, "prs": [],
            "local_unpushed": {"measured": False, "branches": []}, "stack_families": []}


def test_plan_alerts_only_on_a_gained_finding_and_weekly_digest():
    r1 = _report()
    first = PHA.plan_alerts(r1, {}, NOW)
    assert [p["kind"] for p in first] == ["pr_hygiene_findings", "pr_hygiene_weekly_digest"]
    state = {"fingerprint": r1["fingerprint"], "alert_keys": r1["alert_keys"], "digest_week": first[1]["week"]}
    assert PHA.plan_alerts(r1, state, NOW) == []                                    # unchanged: silent
    assert PHA.plan_alerts(_report(keys=()), state, NOW) == []                      # shrank: silent
    gained = PHA.plan_alerts(_report(keys=("CONFLICT:#1", "SUPERSEDED:#2")), state, NOW)
    assert [p["kind"] for p in gained] == ["pr_hygiene_findings"] and "SUPERSEDED:#2" in gained[0]["summary"]
    assert [p["kind"] for p in PHA.plan_alerts(r1, state, NOW + timedelta(days=7))] == ["pr_hygiene_weekly_digest"]


def test_emit_alerts_advances_state_only_when_queued(tmp_path):
    calls = []

    def ok(**kw):
        calls.append(kw)
        return {"intent_id": f"i{len(calls)}"}

    def refused(**kw):
        raise ValueError("ledger_absent")

    st = tmp_path / "state.json"
    out = PHA.emit_alerts(_report(), state_path=st, queue=refused, now=NOW)
    assert set(out["refused"]) == {"pr_hygiene_findings", "pr_hygiene_weekly_digest"}
    assert "fingerprint" not in json.loads(st.read_text())                          # retried next run
    out = PHA.emit_alerts(_report(), state_path=st, queue=ok, now=NOW)
    assert [q["kind"] for q in out["queued"]] == ["pr_hygiene_findings", "pr_hygiene_weekly_digest"]
    assert PHA.emit_alerts(_report(), state_path=st, queue=ok, now=NOW)["queued"] == []  # dedupe
    assert len(calls) == 2


def test_main_live_writes_receipt_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    queued = []
    monkeypatch.setattr(PHA, "audit", lambda gh, git, **kw: _report())
    monkeypatch.setattr(PHA, "queue_host_intent", lambda **kw: queued.append(kw) or {"intent_id": "x"})
    receipt = tmp_path / RECEIPT
    assert PHA.main(["--report", "--slug", SLUG, "--repo", str(tmp_path / "no-clone")]) == 0
    assert PHA.main(["--dry-run", "--slug", SLUG, "--repo", str(tmp_path / "no-clone")]) == 0
    assert not receipt.exists() and queued == [] and not list((tmp_path).rglob("*.json"))
    assert PHA.main(["--slug", SLUG, "--repo", str(tmp_path / "no-clone")]) == 0
    doc = json.loads(receipt.read_text())
    assert doc["lane_id"] == LANE and doc["status"] == "ok" and doc["ok_at"]
    assert doc["output_fields"] == "LaneRunReceipt@v2" and doc["produced_count"] == 3
    assert doc["summary"]["findings"][0]["key"] == "CONFLICT:#1" and doc["summary"]["counts"]["CONFLICT"] == 1
    assert [q["kind"] for q in queued] == ["pr_hygiene_findings", "pr_hygiene_weekly_digest"]
    assert (tmp_path / "data" / "runtime" / PHA.ALERT_STATE_NAME).exists()


def test_main_github_unreadable_exits_1_with_failed_receipt(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))

    def boom(gh, git, **kw):
        raise PHA.AuditError("gh pr exit 1")

    monkeypatch.setattr(PHA, "audit", boom)
    assert PHA.main(["--slug", SLUG, "--repo", str(tmp_path / "x")]) == 1
    doc = json.loads((tmp_path / RECEIPT).read_text())
    assert doc["status"] == "failed" and doc["ok_at"] is None and doc["skipped_reasons"] == {"dependency_unavailable": 1}


def test_queue_host_intent_into_a_tmp_ledger(tmp_path):
    ledger = tmp_path / "ledger.sqlite"
    with pytest.raises(ValueError, match="ledger_absent"):
        PHA.queue_host_intent(kind=PHA.ALERT_KIND, subject="s", summary="b", execution_id="e", ledger_path=ledger)
    sqlite3.connect(str(ledger)).close()
    out = PHA.queue_host_intent(kind=PHA.ALERT_KIND, subject="PR hygiene: 1 new", summary="New: CONFLICT:#1",
                                execution_id="e1", ledger_path=ledger, now=NOW.timestamp())
    assert out.get("intent_id")
    rows = sqlite3.connect(str(ledger)).execute("SELECT domain, kind, tier, caller_id FROM comms_intents").fetchall()
    assert rows == [("agents", "pr_hygiene_findings", "DIGEST", "host:pr_hygiene_audit")]
    with pytest.raises(ValueError, match="intent_unrouted"):
        PHA.queue_host_intent(kind="not_a_route", subject="s", summary="b", execution_id="e", ledger_path=ledger)


def test_host_routes_are_owned_digest_routes_and_ledger_path_matches_gateway():
    # lib.* spelling only (the script's): importing the gateway here would load n8n_fabric_store under scripts.lib.*
    # too and trip the dual-import guard in later tests, so the gateway's path function is read in a subprocess.
    from lib.n8n_fabric_store import load_host_intent_routes, load_intent_routes, merged_intent_routes
    hosts = load_host_intent_routes()
    merged_intent_routes(load_intent_routes(), hosts)
    for kind in (PHA.ALERT_KIND, PHA.DIGEST_KIND):
        r = hosts["routes"][(PHA.ALERT_DOMAIN, kind)]
        assert r["producer"] == PHA.ALERT_PRODUCER and r["tier"] == "DIGEST"
    envs = [{}, {"TRADEAI_STATE_ROOT": "/x"}, {"TRADEAI_N8N_COORDINATION_LEDGER": "/y/l.sqlite"}]
    code = ("import json, sys; sys.path[:0] = [sys.argv[1], sys.argv[1] + '/scripts'];"
            "from scripts.n8n_coordination_gateway import default_ledger_path as d;"
            "print(json.dumps([str(d(e)) for e in json.loads(sys.argv[2])]))")
    out = subprocess.run([sys.executable, "-c", code, str(ROOT), json.dumps(envs)], capture_output=True, text=True,
                         check=True, env={**os.environ, "HOME": os.environ.get("HOME", "/nonexistent")})
    assert json.loads(out.stdout.strip().splitlines()[-1]) == [str(PHA._ledger_path(e)) for e in envs]


# ── needs-action source ────────────────────────────────────────────────────────────────────────────────────────


def _receipt(findings, ok_at=NOW - timedelta(hours=2), status="ok"):
    return {"schema": "LaneRunReceipt@v1", "lane_id": LANE, "status": status,
            "ok_at": ok_at.isoformat() if ok_at else None, "finished_at": NOW.isoformat(),
            "summary": {"as_of": NOW.isoformat(), "findings": findings}}


def _f(kind, n, **kw):
    return {"key": f"{kind}:#{n}", "kind": kind, "severity": PHA.SEVERITY[kind], "pr": n, "prs": [n],
            "title": f"#{n} {kind.lower()}", "url": f"https://example.invalid/pull/{n}", "confidence": kw.get("c"),
            "detail": kw.get("detail", {})}


def test_needs_action_rule_maps_findings_to_items_with_links():
    items = NA.rule_pr_hygiene(_receipt([_f("CONFLICT", 1), _f("SUPERSEDED", 2, c="high"), _f("DUPLICATE", 3),
                                         _f("STALE_HOLD", 4), _f("STACKED", 5),
                                         {"key": "UNPUSHED:wip", "kind": "UNPUSHED", "detail": {"branch": "wip"}}]), NOW)
    sev = {i["evidence"].get("kind"): i["severity"] for i in items if i["evidence"].get("kind")}
    assert sev == {"CONFLICT": "P2", "SUPERSEDED": "P2", "DUPLICATE": "P2", "STALE_HOLD": "P3", "STACKED": "P3"}
    assert all(i["evidence"]["url"].startswith("https://") for i in items if i["evidence"].get("kind"))
    assert any(i["severity"] == "P3" and "1 local branch" in i["title"] and "wip" in i["why"] for i in items)
    assert all(i["source"] == "pr_hygiene" for i in items)


def test_needs_action_rule_no_receipt_stale_failed_and_cap():
    assert [i["severity"] for i in NA.rule_pr_hygiene({"status": "NO_RECEIPT", "path": "x"}, NOW)] == ["P3"]
    stale = NA.rule_pr_hygiene(_receipt([], ok_at=NOW - timedelta(hours=40)), NOW)
    assert [i["severity"] for i in stale] == ["P2"] and "stale" in stale[0]["title"]
    failed = NA.rule_pr_hygiene(_receipt([], ok_at=NOW - timedelta(hours=1), status="failed"), NOW)
    assert [i["title"] for i in failed] == ["PR hygiene audit failed"]
    many = NA.rule_pr_hygiene(_receipt([_f("CONFLICT", n) for n in range(20)]), NOW)
    assert len(many) == NA.PR_HYGIENE_ITEMS_MAX + 1 and "8 more" in many[-1]["title"]
    with pytest.raises(NA.SourceUnavailable):
        NA.rule_pr_hygiene({**_receipt([]), "lane_id": "other"}, NOW)


def test_needs_action_probe_and_aggregate(tmp_path):
    p = tmp_path / "r.json"
    assert NA.probe_pr_hygiene(p)["status"] == "NO_RECEIPT"
    p.write_text("{not json")
    with pytest.raises(NA.SourceUnavailable):
        NA.probe_pr_hygiene(p)
    p.write_text(json.dumps(_receipt([_f("CONFLICT", 1)])))
    out = NA.aggregate({"pr_hygiene": lambda: NA.probe_pr_hygiene(p)}, now=NOW)
    assert out["sources"]["pr_hygiene"]["status"] == "OK" and out["counts"]["P2"] == 1
    assert "pr_hygiene" in NA.RULES


def test_api_v2_wires_the_source():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert '"pr_hygiene": _na.probe_pr_hygiene' in src


# ── the n8n lane: registry, allowlist, DRAFT contract, closure ─────────────────────────────────────────────────


def _row():
    return next(r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]
                if r["lane_id"] == LANE)


def test_registry_row_is_n8n_native_shadow_daily_0630():
    row = _row()
    sch, d = row["scheduler"], row["dispatch"]
    assert (sch["kind"], sch["expression"], sch["stage"]) == ("n8n", "dispatcher", "shadow")
    assert d["mode"] == "dry_run" and d["cron"] == ["30 6 * * *"] and d["tz"] == "America/New_York"
    assert d["class"] == "monitor" and row["owner"] == "platform"
    assert (row["output_signal"]["path"], row["output_signal"]["key"]) == (RECEIPT, "ok_at")
    from scripts.lib.lane_dispatch import dispatch_eligible
    ok = dispatch_eligible(row)
    assert ok[0] if isinstance(ok, tuple) else ok


def test_allowlist_entry_is_shadow_and_names_no_secret():
    a = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    e = next(x for x in a["lanes"] if x["lane_id"] == LANE)
    assert e["command"] == ["$PY", "scripts/pr_hygiene_audit.py"]
    assert e["dry_run_arg"] == ["--dry-run"] and e["live_arg"] is None
    assert e["lock_kind"] == "flock" and not e["lock"].endswith(".dryrun") and e["output_signal"] == RECEIPT
    assert not any(any(t in n for t in ("TOKEN", "SECRET", "PASSWORD", "KEY", "SCHWAB", "ALPACA", "SNAPTRADE",
                                        "MOOMOO", "IBKR")) for n in e["env_names"])
    assert LANE not in json.dumps(a.get("never"))


def test_health_contract_is_shadow_reviewed_by_the_operator():
    c = json.loads((ROOT / "config" / "n8n_health_contracts.json").read_text())
    k = next(x for x in c["contracts"] if x["id"] == LANE)
    # Operator reviewed the contract 2026-10-21 ("yes approve pr-hygiene-audit too"); an agent may not.
    assert k["status"] == "REVIEWED" and k["owner"] == "platform" and k["stage"] == "shadow"
    assert k["review"]["status"] == "REVIEWED" and k["review"]["reviewed_by"].startswith("operator ")
    assert k["evidence"]["receipt"] == RECEIPT and k["expected_output"]["empty_allowed_reasons"] == ["no_new_input"]


def test_lane_closure_reaches_no_sender_broker_or_order():
    import audit_lane_transitive_capabilities as cap
    res = cap.Resolver()
    order, _ = res.closure(ROOT / "scripts" / "pr_hygiene_audit.py")
    rels = {res.info(m).path for m in order}
    assert not rels & {"scripts/db_adapter.py", "scripts/telegram_alert.py", "scripts/lib/host_comms_intents.py",
                       "scripts/n8n_coordination_gateway.py"}, rels
    caps = set().union(*(res.info(m).caps for m in order))
    assert not caps & {"direct_sender", "broker_module", "order_placement", "chokepoint_send"}, caps


# ── pr_overlap_check ───────────────────────────────────────────────────────────────────────────────────────────


def _overlap_gh():
    prs = [_pr(10, head="fix/reauth-stepup", sha="s10", title="fix(cc-auth): exempt reauth from step-up"),
           _pr(11, head="feat/other", sha="s11", title="unrelated", body="nothing")]
    return FakeGh({"pr list --repo example-owner/example-repo --state open": prs,
                   f"api --paginate repos/{SLUG}/pulls/10/files": [
                       {"filename": "scripts/lib/cc_auth.py", "patch": "@@ -1 +1,2 @@\n x\n+STEP_UP_EXEMPT = ()"}],
                   f"api --paginate repos/{SLUG}/pulls/11/files": [
                       {"filename": "docs/ops/X.md", "patch": "@@ -1 +1,2 @@\n x\n+mentions totp here"}]})


def test_overlap_check_files_dirs_and_keywords():
    gh = PHA.Gh(SLUG, run=_overlap_gh())
    hits = POC.check(gh, ["scripts/lib/cc_auth.py"], [])
    assert [h["number"] for h in hits] == [10] and hits[0]["files"] == ["scripts/lib/cc_auth.py"]
    assert [h["number"] for h in POC.check(gh, ["docs/ops/"], [])] == [11]
    kw = {h["number"]: h["keywords"] for h in POC.check(gh, [], ["step-up", "TOTP"])}
    assert kw[10][0]["where"] == "title" and kw[11][0]["where"].startswith("diff docs/ops/X.md")
    assert POC.check(gh, ["nope.py"], ["nothing-matches-this"]) == []
    assert all(c[0] in ("pr", "api") for c in gh._run.calls)


def test_overlap_check_cli_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(PHA, "Gh", _GhStub)
    assert POC.main(["--slug", SLUG, "--files", "scripts/lib/cc_auth.py"]) == 0
    assert "#10" in capsys.readouterr().out
    assert POC.main(["--slug", SLUG, "--files", "scripts/lib/cc_auth.py", "--fail-on-overlap"]) == 3
    assert POC.main(["--slug", SLUG, "--keywords", "zzz-none", "--fail-on-overlap"]) == 0
    with pytest.raises(SystemExit):
        POC.main(["--slug", SLUG])


class _GhStub(PHA.Gh):
    def __init__(self, slug):
        super().__init__(slug, run=_overlap_gh())
