"""Iris taxonomy agent and proposal curator defects, measured 2026-10-09.

1. `--freshness` auto-remediation shell-ran the API's `.venv/bin/python scripts/...` string with cwd = the
   release, which ships no .venv: every run logged "Failed (exit 127)" and the job still exited 0.
2. The weekly scan re-created the same pending proposal every run: 4,058 pending retire_channel rows were
   32 channels (141 copies each), so the "5,741 pending" review queue was ~110 distinct items.
3. The weekly scan had no dry run, so it could not take an n8n shadow stage (AGENTS §23.12).

Fakes only: no database, no LLM, no subprocess is launched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import iris_proposal_curator as curator  # noqa: E402
import iris_taxonomy_agent as iris  # noqa: E402


class FakeCursor:
    def __init__(self, rows=None, rowcount=-1):
        self.sql: list[tuple[str, tuple]] = []
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def execute(self, sql, params=()):
        self.sql.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        out, self._rows = self._rows, []
        return out


class FakeConn:
    def __init__(self, cur):
        self.cur = cur
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def _writes(cur):
    return [s for s, _ in cur.sql if s.split()[0].upper() in ("INSERT", "UPDATE", "DELETE", "WITH")
            and ("INSERT" in s.upper() or "UPDATE" in s.upper() or "DELETE" in s.upper())]


# ── 1. freshness remediation ────────────────────────────────────────────────

def test_remediation_argv_maps_release_relative_venv_to_resolved_interpreter(monkeypatch):
    monkeypatch.setattr(iris, "venv_python", lambda root=None: "/opt/py/bin/python")
    argv = iris._remediation_argv(".venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 5")
    assert argv == ["/opt/py/bin/python", str(iris.PROJECT_ROOT / "scripts/process_watchlist_agent_jobs.py"),
                    "--limit", "5"]


@pytest.mark.parametrize("cmd", [
    "rm -rf /",
    ".venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 5; rm -rf /",
    ".venv/bin/python scripts/process_watchlist_agent_jobs.py $(whoami)",
    ".venv/bin/python scripts/../../etc/evil.py",
    ".venv/bin/python scripts/does_not_exist_anywhere.py",
    "python3 -c 'import os'",
    "",
    None,
])
def test_remediation_argv_refuses_anything_but_an_existing_repo_script(cmd):
    assert iris._remediation_argv(cmd) is None


def _freshness_env(monkeypatch, *, rc=0, api_error=False):
    calls = {"run": [], "log_run": []}

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return json.dumps(self.body).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(url, timeout=10):
        if api_error:
            raise OSError("connection refused")
        if "data-product-health" in url:
            return Resp({"data": {"products": [{
                "product": "agent_jobs_completed", "status": "stale", "age_hours": 4, "max_stale_hours": 2,
                "remediation": ".venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 5"}]}})
        return Resp({"summary": {"critical": 0, "never_run": 0}})

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(iris, "_get_conn", lambda: FakeConn(FakeCursor([(0,), (0,)])))
    monkeypatch.setattr(iris, "log_run", lambda *a, **k: calls["log_run"].append((a, k)))

    class Done:
        returncode = rc
        stderr = "" if rc == 0 else "boom"

    def fake_run(argv, **kw):
        calls["run"].append((argv, kw))
        return Done()

    import subprocess
    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_freshness_runs_remediation_as_argv_without_a_shell(monkeypatch):
    calls = _freshness_env(monkeypatch, rc=0)
    res = iris.run_freshness_validation()
    assert len(calls["run"]) == 1
    argv, kw = calls["run"][0]
    assert isinstance(argv, list) and argv[1].endswith("scripts/process_watchlist_agent_jobs.py")
    assert not kw.get("shell")
    assert res["remediation_failed"] == 0
    assert iris.freshness_exit_code(res) == 0


def test_failed_remediation_makes_the_job_exit_nonzero(monkeypatch):
    _freshness_env(monkeypatch, rc=127)
    res = iris.run_freshness_validation()
    assert res["remediation_failed"] == 1
    assert iris.freshness_exit_code(res) == 1


def test_check_error_makes_the_job_exit_nonzero(monkeypatch):
    _freshness_env(monkeypatch, api_error=True)
    res = iris.run_freshness_validation()
    assert "error" in res
    assert iris.freshness_exit_code(res) == 1


def test_freshness_dry_run_reaches_no_remediation_and_no_run_log(monkeypatch):
    calls = _freshness_env(monkeypatch, rc=0)
    res = iris.run_freshness_validation(dry_run=True)
    assert calls["run"] == [] and calls["log_run"] == []
    assert res["stale_products"] == 1 and res["remediation_failed"] == 0


def test_main_propagates_the_freshness_exit_code(monkeypatch):
    monkeypatch.setattr(iris, "run_freshness_validation", lambda dry_run=False: {"error": "x"})
    assert iris.main(["--freshness"]) == 1
    monkeypatch.setattr(iris, "run_freshness_validation", lambda dry_run=False: {"issues": 3, "remediation_failed": 0})
    assert iris.main(["--freshness"]) == 0


# ── 2. proposal de-duplication ──────────────────────────────────────────────

def test_create_proposal_reuses_an_identical_pending_proposal(monkeypatch):
    cur = FakeCursor([(4242,)])  # the duplicate lookup finds #4242
    monkeypatch.setattr(iris, "_get_conn", lambda: FakeConn(cur))
    pid, created = iris.create_or_reuse_proposal("retire_channel", "FedLife", {"active": True}, {"active": False},
                                                  "Low relevance", 0.6)
    assert (pid, created) == (4242, False)
    assert not any("INSERT" in s for s, _ in cur.sql)
    lookup, params = cur.sql[0]
    assert "status='pending'" in lookup.replace(" = ", "=") and params[:2] == ("retire_channel", "FedLife")


def test_create_proposal_inserts_when_no_pending_duplicate(monkeypatch):
    cur = FakeCursor([None, (77,)])  # lookup misses, INSERT ... RETURNING id gives 77
    monkeypatch.setattr(iris, "_get_conn", lambda: FakeConn(cur))
    assert iris.create_or_reuse_proposal("add_channel", "X", {}, {"category": "c"}, "gap", 0.5) == (77, True)
    assert any("INSERT INTO iris_taxonomy_proposals" in s for s, _ in cur.sql)
    assert iris.create_proposal is not None  # legacy name kept for callers


# ── 3. weekly scan dry run ──────────────────────────────────────────────────

def _scan_env(monkeypatch):
    calls = {"llm": 0, "log_run": 0}
    monkeypatch.setattr(iris, "analyze_coverage", lambda: {
        "overall_score": 71, "categories": {"macro": {"status": "low", "current_count": 1, "ideal_count": 5,
                                                      "coverage_score": 20, "channels": ["A"]}}})
    monkeypatch.setattr(iris, "detect_gaps", lambda cov: [{"severity": "critical", "category": "macro",
                                                           "description": "macro gap"}])
    monkeypatch.setattr(iris, "audit_channels", lambda: [
        {"issue": "uncategorized", "channel": "U", "detail": "none"},
        {"issue": "low_relevance", "channel": "FedLife", "detail": "0 relevant"}])

    def llm(*a, **k):
        calls["llm"] += 1
        return "{}"

    monkeypatch.setattr(iris, "llm_generate", llm)
    monkeypatch.setattr(iris, "log_run", lambda *a, **k: calls.__setitem__("log_run", calls["log_run"] + 1))
    return calls


def test_weekly_scan_dry_run_calls_no_llm_and_writes_nothing(monkeypatch):
    calls = _scan_env(monkeypatch)
    cur = FakeCursor([None])  # read-only duplicate lookup for the retire proposal
    monkeypatch.setattr(iris, "_get_conn", lambda: FakeConn(cur))
    res = iris.run_weekly_scan(dry_run=True)
    assert calls == {"llm": 0, "log_run": 0}
    assert not _writes(cur)
    assert res["proposals_created"] == 0 and res["would_create"] >= 1


def test_weekly_scan_counts_only_new_proposals(monkeypatch):
    _scan_env(monkeypatch)
    made = []
    monkeypatch.setattr(iris, "create_or_reuse_proposal",
                        lambda ptype, target, *a, **k: (made.append(target) or 1, target != "FedLife"))
    monkeypatch.setattr(iris, "suggest_channels_for_gap", lambda cat, existing: [])
    monkeypatch.setattr(iris, "classify_channel_llm", lambda ch: {"category": "macro", "confidence": 0.9})
    res = iris.run_weekly_scan()
    assert "FedLife" in made
    assert res["proposals_created"] == 1  # U is new, FedLife was a pending duplicate


# ── 4. curator supersedes the duplicate backlog ─────────────────────────────

def test_curator_supersede_dry_run_counts_without_writing():
    cur = FakeCursor([(4026,)])
    assert curator.supersede_duplicates(cur, apply=False) == 4026
    assert len(cur.sql) == 1 and cur.sql[0][0].startswith("WITH")
    assert "UPDATE" not in cur.sql[0][0]


def test_curator_supersede_apply_keeps_the_newest_and_flags_the_rest():
    cur = FakeCursor([(4026,)], rowcount=4026)
    assert curator.supersede_duplicates(cur, apply=True) == 4026
    update = cur.sql[1][0]
    assert "SET status='superseded'" in update.replace(" = ", "=")
    assert "PARTITION BY proposal_type, target, proposed_state" in update
    assert "ORDER BY created_at DESC, id DESC" in update
    assert "status='pending'" in update.replace(" = ", "=")
    assert "DELETE" not in update.upper()
