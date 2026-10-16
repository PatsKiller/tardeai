"""Self-heal Claude Code fixer (operator 2026-10-16: "connect into Claude Code to fix it in iterations").

Pins the design in docs/ops/self_heal_claude_fixer.md:
1. lifecycle: only legal transitions; a PR (or a deploy) is not a heal;
2. intake: code_error escalations only, one active job per signature, cooldown, broker/held lanes refused;
3. the diff guard refuses protected paths, test deletion/skip/assert removal, non-append CI edits;
4. the claude argv is dontAsk with an allowlist and the child env carries no credential;
5. the iteration loop (mocked claude CLI, real git in tmp repos): red-first on base, previous output fed back,
   stop on no progress, hard refusal, success -> commit -> push + PR only when the policy gate allows;
6. lifecycle advance: merged + released -> fix_deployed; output fresh -> output_recovered; escalation gone ->
   incident_resolved;
7. the dry run on today's daily-incubator-refresh incident calls no model and writes no state.

Hermetic: TRADE_AI_CI=1, tmp_path repos/state, fake claude and gh binaries. Never calls a real model.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import self_heal_fix_evaluator as E  # noqa: E402
from lib import self_heal_fixer as F  # noqa: E402
import self_heal_fixer as S  # noqa: E402

CFG = json.loads((ROOT / "config" / "self_heal_fixer.json").read_text())
FIXTURE = ROOT / "tests" / "fixtures" / "self_heal_fixer" / "daily_incubator_refresh_20261016.json"
NOW = datetime(2026, 10, 16, 18, 0, tzinfo=timezone.utc)
AGENTS_TEXT = (ROOT / "AGENTS.md").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _ci(monkeypatch):
    monkeypatch.setenv("TRADE_AI_CI", "1")


def _cfg(**over):
    c = json.loads(json.dumps(CFG))
    for k, v in over.items():
        c[k].update(v)
    return c


# ---------------------------------------------------------------- 1. lifecycle


def test_lifecycle_only_legal_edges_and_pr_is_not_a_heal():
    job = {"state": F.FIX_REQUESTED}
    F.transition(job, F.FIX_ATTEMPTING, NOW, iteration=1)
    F.transition(job, F.FIX_PR_OPENED, NOW, pr_number=7)
    assert not F.is_healed(job)
    with pytest.raises(F.TransitionError):
        F.transition(job, F.INCIDENT_RESOLVED, NOW)  # a PR cannot jump to resolved
    F.transition(job, F.FIX_DEPLOYED, NOW)
    assert not F.is_healed(job)  # deployed code alone is not a heal
    F.transition(job, F.OUTPUT_RECOVERED, NOW)
    assert F.is_healed(job)
    F.transition(job, F.INCIDENT_RESOLVED, NOW)
    assert [h["state"] for h in job["history"]] == [F.FIX_ATTEMPTING, F.FIX_PR_OPENED, F.FIX_DEPLOYED,
                                                    F.OUTPUT_RECOVERED, F.INCIDENT_RESOLVED]
    with pytest.raises(F.TransitionError):
        F.transition(job, F.FIX_ATTEMPTING, NOW)  # terminal


# ---------------------------------------------------------------- 2. intake


def _inc(lane="daily-incubator-refresh", **kw):
    return {"key": f"{lane}|k", "lane": lane, "route": "fix_pr_release",
            "stderr_tail": "Traceback\npsycopg2.InterfaceError: connection already closed\n", **kw}


def _producer_defect(lane="daily-incubator-refresh", stderr="psycopg2.InterfaceError: connection already closed",
                     run="d:x:live:1", episode=1):
    """The PRODUCER's own record (scripts/n8n_failure_diagnosis.code_defect_hook, PR #1828) — not a hand copy."""
    import n8n_failure_diagnosis as D
    from lib import n8n_self_heal as H
    res = {"lane": lane, "signature": H.signature(lane, "RUN_FAILED", stderr), "episode": episode,
           "failure_kind": H.failure_kind(stderr), "failure_class": H.classify_failure(stderr), "siem_id": 7,
           "incident_key": f"siem:{lane}", "event_type": "RUN_FAILED"}
    return D.code_defect_hook(res, {"run": run})


def test_consumer_reads_the_producers_n8n_code_defect_contract():
    d = _producer_defect()
    assert d["schema"] == F.CODE_DEFECT_SCHEMA and d["consumer"] == F.CODE_DEFECT_CONSUMER
    other = dict(d, defect_id="cd-other", consumer="someone_else")
    wrong = dict(d, defect_id="cd-wrong", schema="N8nCodeDefect@v0")
    records = [{"at": "2", "code_defect": d}, {"at": "1", "code_defect": other}, {"at": "1", "code_defect": wrong},
               {"at": "0", "outcome": "diagnosed"}]
    diag = {"escalations": {"daily-incubator-refresh|" + d["signature"]: {"fix_path": d, "at": "2"}}}
    got = F.code_defects(records, diag, CFG)
    assert [g["defect_id"] for g in got] == [d["defect_id"]]  # deduped by defect_id; other consumers ignored
    inc = got[0]
    assert inc["failed_run_id"] == "d:x:live:1" and inc["signature"] == d["signature"]
    assert inc["key"] == f"daily-incubator-refresh|{d['signature']}"  # the diagnoser's escalation_key
    ep2 = _producer_defect(episode=2)
    assert F.code_defects([{"code_defect": ep2}], None, CFG)[0]["key"].endswith("|ep2")
    assert F.code_defects([], None, CFG) == []


def test_one_job_per_defect_id_ever():
    state = {"jobs": {}}
    inc = F.code_defects([{"code_defect": _producer_defect()}], None, CFG)[0]
    job, why = F.admit(state, inc, now=NOW, cfg=CFG)
    assert why == "admitted" and job["defect_id"] == inc["defect_id"] and job["failed_run_id"] == "d:x:live:1"
    job["state"], job["updated_at"] = F.FIX_FAILED, NOW.isoformat()
    again, why2 = F.admit(state, inc, now=NOW + timedelta(days=30), cfg=CFG)
    assert again is None and why2.startswith(f"consumed:{job['job_id']}")


def test_one_active_job_per_signature_then_cooldown():
    state = {"jobs": {}}
    job, why = F.admit(state, _inc(), now=NOW, cfg=CFG)
    assert why == "admitted" and job["state"] == F.FIX_REQUESTED
    again, why2 = F.admit(state, _inc(), now=NOW, cfg=CFG)
    assert again is None and why2.startswith("deduped:active:")
    # a different exception on the same lane is a different signature -> its own job
    other, why3 = F.admit(state, _inc(stderr_tail="KeyError: 'x'"), now=NOW, cfg=CFG)
    assert why3 == "admitted" and other["signature"] != job["signature"]
    job["state"], job["updated_at"] = F.FIX_FAILED, NOW.isoformat()
    cool, why4 = F.admit(state, _inc(), now=NOW + timedelta(hours=1), cfg=CFG)
    assert cool is None and why4.startswith("cooldown:")
    later, why5 = F.admit(state, _inc(), now=NOW + timedelta(hours=73), cfg=CFG)
    assert why5 == "admitted" and later["job_id"].endswith("-2")


@pytest.mark.parametrize("lane,script,held", [
    ("schwab-positions-sync", "scripts/schwab_sync.py", None),
    ("stop-guard", "scripts/x.py", None),
    ("benign", "scripts/order_router.py", None),
    ("coder-dispatch", "scripts/coder_dispatch.py", {"coder-dispatch": "operator_hold_20261016"}),
])
def test_broker_class_and_held_lanes_are_refused_at_intake(lane, script, held):
    state = {"jobs": {}}
    job, why = F.admit(state, _inc(lane=lane, script=script), now=NOW, cfg=CFG, held=held)
    assert job["state"] == F.FIX_REFUSED and why.startswith("lane_refused:")


# ---------------------------------------------------------------- 3. diff guard


def _guard(name_status, numstat, unified, ci="GATES = [\n    (\"a\", [\"tests/test_a.py\"]),\n]\n"):
    return F.guard_diff(name_status=name_status, numstat=numstat, unified=unified, base_ci_text=ci, cfg=CFG)


def _codes(refusals):
    return {r["code"] for r in refusals}


GOOD_U = ("diff --git a/scripts/lane.py b/scripts/lane.py\n--- a/scripts/lane.py\n+++ b/scripts/lane.py\n"
          "@@ -3 +3 @@\n-    conn.rollback()\n+    _safe_rollback(conn)\n"
          "diff --git a/tests/test_self_heal_lane.py b/tests/test_self_heal_lane.py\n--- /dev/null\n"
          "+++ b/tests/test_self_heal_lane.py\n@@ -0,0 +1,2 @@\n+def test_x():\n+    assert True\n")


def test_guard_accepts_a_minimal_fix_with_a_regression_test():
    r = _guard("M\tscripts/lane.py\nA\ttests/test_self_heal_lane.py\n",
               "1\t1\tscripts/lane.py\n2\t0\ttests/test_self_heal_lane.py\n", GOOD_U)
    assert r == []


@pytest.mark.parametrize("path", ["AGENTS.md", ".cursor/hooks/guard_ledger.py", ".githooks/pre-push",
                                  "config/memory_chokepoint_baseline.json", "config/n8n_run_allowlist.json",
                                  "scripts/check_provider_chokepoint.py", "config/crontab_backup.txt",
                                  "config/systemd/tradeai-x.service", "scripts/schwab_client.py",
                                  "scripts/lib/order_router.py", ".env", "config/lane_registry.json",
                                  "scripts/self_heal_fixer.py", ".github/workflows/ci.yml",
                                  "sql/migrations/2026_x.sql", "tests/conftest.py"])
def test_guard_refuses_protected_paths_hard(path):
    r = _guard(f"M\t{path}\nA\ttests/test_self_heal_lane.py\n", f"1\t1\t{path}\n1\t0\ttests/test_self_heal_lane.py\n",
               "")
    assert any(x["hard"] and x["code"] == "protected_path" and x["path"] == path for x in r)


def test_guard_refuses_test_deletion_skip_and_assert_removal():
    assert "test_deleted" in _codes(_guard("D\ttests/test_a.py\n", "0\t9\ttests/test_a.py\n", ""))
    skip_u = ("diff --git a/tests/test_a.py b/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1 +1,2 @@\n"
              "+@pytest.mark.skip(reason='flaky')\n")
    assert "test_weakened:skip_or_xfail" in _codes(_guard("M\ttests/test_a.py\n", "1\t0\ttests/test_a.py\n", skip_u))
    rm_u = ("diff --git a/tests/test_a.py b/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -4,2 +4 @@\n"
            "-    assert x == 1\n-    assert y == 2\n+    assert x\n")
    assert "test_weakened:asserts_removed" in _codes(_guard("M\ttests/test_a.py\n", "1\t2\ttests/test_a.py\n", rm_u))
    gone_u = ("diff --git a/tests/test_a.py b/tests/test_a.py\n+++ b/tests/test_a.py\n@@ -1,2 +0,0 @@\n"
              "-def test_one():\n-    pass\n")
    assert "test_weakened:test_removed" in _codes(_guard("M\ttests/test_a.py\n", "0\t2\ttests/test_a.py\n", gone_u))


def test_ci_registration_is_append_only_inside_gates():
    ci = "import os\nGATES = [\n    (\"a\", [\"tests/test_a.py\"]),\n]\nPASS = 1\n"
    ok_u = ("diff --git a/scripts/run_cio_hardening_ci.py b/scripts/run_cio_hardening_ci.py\n"
            "+++ b/scripts/run_cio_hardening_ci.py\n@@ -3,0 +4,2 @@\n"
            "+    # self-heal regression for lane x\n+    (\"self_heal_x\", [\"tests/test_self_heal_x.py\"]),\n")
    ns = "M\tscripts/run_cio_hardening_ci.py\nA\ttests/test_self_heal_x.py\n"
    st = "2\t0\tscripts/run_cio_hardening_ci.py\n3\t0\ttests/test_self_heal_x.py\n"
    assert _guard(ns, st, ok_u, ci) == []
    code_u = ok_u.replace('+    ("self_heal_x", ["tests/test_self_heal_x.py"]),', "+PASS_CODES = frozenset({0, 1, 5})")
    assert "append_only:non_registration_line" in _codes(_guard(ns, st, code_u, ci))
    rm_u = ok_u + "@@ -3 +0,0 @@\n-    (\"a\", [\"tests/test_a.py\"]),\n"
    assert "append_only:lines_removed" in _codes(_guard(ns, st, rm_u, ci))
    out_u = ok_u.replace("@@ -3,0 +4,2 @@", "@@ -5,0 +6,2 @@")
    assert "append_only:outside_gates_list" in _codes(_guard(ns, st, out_u, ci))


def test_soft_refusals_go_back_as_feedback():
    r = _guard("M\tscripts/lane.py\n", "1\t1\tscripts/lane.py\n", "")
    assert _codes(r) == {"no_regression_test"} and not r[0]["hard"]
    assert _codes(_guard("", "", "")) == {"empty_diff"}


# ---------------------------------------------------------------- 4. claude argv + env + parsing


def test_claude_argv_is_dontask_with_an_allowlist_and_denies_push():
    argv = F.claude_argv(CFG, budget_usd=2.5, pytest_cmd="/tmp/w/shf-x-bin/pytest")
    assert argv[:2] == [CFG["claude"]["bin"], "-p"]
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    allowed = argv[argv.index("--allowedTools") + 1]
    denied = argv[argv.index("--disallowedTools") + 1]
    assert "Bash(git push:*)" in denied and "Bash(gh:*)" in denied and "WebFetch" in denied
    assert "Read(**/.env)" in denied
    assert "Bash(/tmp/w/shf-x-bin/pytest:*)" in allowed and "-m pytest" not in allowed
    assert argv[argv.index("--setting-sources") + 1] == "project"  # the user's interactive allow rules stay out
    assert "Bash(bash:*)" in denied and "Bash(python3:*)" in denied
    assert "Bash(*)" not in allowed and "Bash," not in allowed + ","  # never a bare Bash allow
    assert argv[argv.index("--max-budget-usd") + 1] == "2.50"
    assert "bypassPermissions" not in argv


def test_child_env_carries_no_credentials():
    env = F.child_env({"HOME": "/h", "PATH": "/bin", "DB_PASSWORD": "x", "ANTHROPIC_API_KEY": "k",
                       "SCHWAB_APP_SECRET": "s", "TRADEAI_REMOTE_PUSH_AUTHORIZED": "1"}, CFG, scratch_state="/tmp/s")
    assert set(env) == {"HOME", "PATH", "TRADE_AI_CI", "TRADEAI_STATE_ROOT", "PYTHONDONTWRITEBYTECODE"}
    assert env["TRADE_AI_CI"] == "1"


def test_parse_claude_result_reads_cost_and_final_json_line():
    out = json.dumps({"type": "result", "is_error": False, "total_cost_usd": 1.25, "num_turns": 9,
                      "result": "done\n{\"root_cause\": \"rollback on closed conn\", \"confidence\": 0.8}"})
    r = F.parse_claude_result(out)
    assert r["ok"] and r["cost_usd"] == 1.25 and r["summary"]["root_cause"] == "rollback on closed conn"
    assert F.parse_claude_result("garbage")["is_error"]


def test_redact_strips_credentials_but_keeps_tracebacks():
    s = F.redact("DB_PASSWORD=hunter2 postgres://u:pw@h/db File \"/x/94ee3770a-main-exact-phase2-20261015-234752/a.py\"")
    assert "hunter2" not in s and "u:pw" not in s and "94ee3770a-main-exact-phase2" in s


def test_rails_are_section_0_verbatim_from_agents():
    rails = F.extract_rails(AGENTS_TEXT)
    assert "MBI_BEHAVIOR = 0" in rails and "Never route around a permission denial" in rails
    assert "# 1 · Identity" not in rails
    with pytest.raises(ValueError):
        F.extract_rails("# AGENTS\nno rails here\n")


def test_sandbox_prefix_denies_network_and_hides_credentials():
    kinds = {"/h/.claude": "dir", "/h/.pgpass": "file", "/r/.env": "file"}
    argv = F.sandbox_prefix(CFG, home="/h", repo_root="/r", writable=["/tmp/wt/a", "/tmp/wt/a-state"],
                            existing=kinds.get)
    assert argv[0] == CFG["sandbox"]["bwrap"] and "--unshare-net" in argv
    assert argv[argv.index("--ro-bind") + 1:argv.index("--ro-bind") + 3] == ["/", "/"]
    assert ["--tmpfs", "/run"] == argv[argv.index("/run") - 1:argv.index("/run") + 1]
    assert ["--tmpfs", "/h/.claude"] == argv[argv.index("/h/.claude") - 1:argv.index("/h/.claude") + 1]
    assert ["/dev/null", "/r/.env"] == argv[argv.index("/r/.env") - 1:argv.index("/r/.env") + 1]
    assert "/h/.ssh" not in argv  # absent paths are skipped
    assert argv[-6:] == ["--bind", "/tmp/wt/a", "/tmp/wt/a", "--bind", "/tmp/wt/a-state", "/tmp/wt/a-state"]
    assert F.sandbox_prefix(_cfg(sandbox={"enabled": False}), home="/h", repo_root="/r", writable=[],
                            existing=kinds.get) == []


def _bwrap_works() -> bool:
    bw = CFG["sandbox"]["bwrap"]
    if not os.access(bw, os.X_OK):
        return False
    try:
        return subprocess.run([bw, "--ro-bind", "/", "/", "--unshare-net", "true"], capture_output=True,
                              timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def test_failing_set_and_no_progress():
    out = "FAILED tests/test_a.py::test_x - boom\nERROR tests/test_b.py::test_y\n"
    assert F.failing_set(out) == ["ERROR tests/test_b.py::test_y", "tests/test_a.py::test_x"]
    h = [{"failing": ["a"], "passed": False}, {"failing": ["a"], "passed": False}]
    assert F.no_progress(h, 2)
    assert not F.no_progress([{"failing": ["a"]}, {"failing": ["b"]}], 2)
    assert not F.no_progress([{"failing": []}, {"failing": []}], 2)


# ---------------------------------------------------------------- gates


def test_arming_needs_named_grant_and_daily_cap():
    assert not F.arming_verdict(None, cfg=CFG, jobs_today=0)["armed"]
    assert not F.arming_verdict({"reason": "PR #1830 sha abc1234"}, cfg=CFG, jobs_today=0)["armed"]
    ok = F.arming_verdict({"reason": "self-heal-fixer 2026-10-17", "grant_id": "f" * 32}, cfg=CFG, jobs_today=0)
    assert ok["armed"]
    capped = F.arming_verdict({"reason": "self-heal-fixer"}, cfg=CFG, jobs_today=CFG["arming"]["daily_job_cap"])
    assert not capped["armed"] and "cap" in capped["why"]


def test_policy_gate_blocks_push_until_amendment_active():
    assert not F.policy_verdict(AGENTS_TEXT, CFG)["push_allowed"]  # main today: 24.5 binds
    marker = CFG["policy_gate"]["amendment_heading_marker"]
    assert not F.policy_verdict(f"{marker} (13.0.0, PROPOSED)\n", CFG)["push_allowed"]
    assert F.policy_verdict(f"{marker} (13.0.0, ACTIVE; amends 24.5)\n", CFG)["push_allowed"]


# ---------------------------------------------------------------- evaluator, selector, repair memory


def test_evaluator_ignores_backend_claims():
    claims_pass = {"backend_result": {"summary": {"root_cause": "fixed", "confidence": 1.0}, "ok": True},
                   "tests_run": ["tests/test_x.py"], "red_first": True, "targeted_rc": 1, "ci_rc": None,
                   "refusals": []}
    v = E.local_verdict(claims_pass)
    assert not v["accepted"] and v["failed"] == ["ci_pr_profile_green", "green_with_fix"]
    good = dict(claims_pass, targeted_rc=0, ci_rc=0, backend_result={"ok": False, "summary": None})
    assert E.local_verdict(good)["accepted"]  # a backend saying it failed does not matter either
    assert not E.local_verdict(dict(good, red_first=False))["accepted"]  # never reproduced = not a fix
    assert not E.local_verdict(dict(good, refusals=[{"code": "x"}]))["accepted"]


@pytest.mark.parametrize("rollup,verdict", [
    ([{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}], "pass"),
    ([{"__typename": "CheckRun", "name": "ci", "status": "COMPLETED", "conclusion": "FAILURE"}], "fail"),
    ([{"__typename": "CheckRun", "name": "ci", "status": "IN_PROGRESS", "conclusion": ""}], "pending"),
    ([{"__typename": "StatusContext", "context": "ci", "state": "SUCCESS"}], "pass"),
    ([], "pending"),
])
def test_pr_head_ci_verdict(rollup, verdict):
    assert E.pr_head_verdict({"headRefOid": "abc123def4567", "statusCheckRollup": rollup},
                             expected_head="abc123def4567")["verdict"] == verdict


def test_pr_head_moved_is_not_acceptance():
    pr = {"headRefOid": "f" * 40, "statusCheckRollup": [{"name": "ci", "status": "COMPLETED", "conclusion": "SUCCESS"}]}
    v = E.pr_head_verdict(pr, expected_head="a" * 40)
    assert v["verdict"] == "head_moved"
    assert not E.final_acceptance({"accepted": True}, v)["accepted"]
    ok = E.pr_head_verdict(pr, expected_head="f" * 40)
    assert E.final_acceptance({"accepted": True}, ok)["accepted"]
    assert not E.final_acceptance({"accepted": False}, ok)["accepted"]


def test_selector_is_static_and_refuses_unqualified_backends():
    assert F.select_backend(CFG) == ("claude_code", "static")
    assert F.select_backend(_cfg(selector={"backend": "codex_cli"}))[0] is None  # not qualified yet
    assert "shadow" in F.select_backend(_cfg(selector={"mode": "adaptive"}))[1]
    q = _cfg(selector={"backend": "codex_cli"})
    q["backends"]["codex_cli"].update(enabled=True, qualified=True)
    assert F.select_backend(q) == ("codex_cli", "static")
    argv = F.backend_argv(q, "codex_cli", budget_usd=1, pytest_cmd="/w/pytest")
    assert argv[0] == CFG["backends"]["codex_cli"]["bin"] and argv[-1] == "-"


def test_shadow_router_records_but_never_selects():
    rows = [{"event": "iteration", "backend": "claude_code", "failure_kind": "code_error:KeyError",
             "accepted_local": False}] * 3 + \
           [{"event": "iteration", "backend": "codex_cli", "failure_kind": "code_error:KeyError",
             "accepted_local": True}] * 2
    r = F.shadow_route(rows, failure_kind="code_error:KeyError", backends=["claude_code", "codex_cli"],
                       chosen="claude_code")
    assert r["mode"] == "shadow" and r["used"] is False and r["recommended"] == "codex_cli" and not r["agrees"]
    assert r["basis"] == "same_failure_kind" and r["scores"]["claude_code"]["attempts"] == 3


# ---------------------------------------------------------------- 5. the loop against a tmp repo + mocked claude

FAKE_CLAUDE = r'''#!{py}
import json, os, sys, pathlib
prompt = sys.stdin.read()
here = pathlib.Path(__file__).resolve().parent
scen = (here / "scenario").read_text().strip()
calls = here / "calls.jsonl"
with calls.open("a") as fh:
    fh.write(json.dumps({{"cwd": os.getcwd(), "argv": sys.argv[1:], "prev": "Previous iteration" in prompt,
                         "env": sorted(os.environ)}}) + "\n")
n = sum(1 for _ in calls.open())
cwd = pathlib.Path.cwd()
TEST = "def test_ratio_handles_zero():\n    from scripts.buggy import ratio\n    assert ratio(1, 0) == 0.0\n"
REG = '    # self-heal regression for buggy\n    ("self_heal_buggy", ["tests/test_self_heal_buggy.py"]),\n'
def register():
    p = cwd / "scripts" / "run_cio_hardening_ci.py"
    s = p.read_text()
    p.write_text(s.replace("\n]\n", "\n" + REG + "]\n", 1))
def fix():
    p = cwd / "scripts" / "buggy.py"
    p.write_text("def ratio(a, b):\n    return a / b if b else 0.0\n")
if scen == "fix":
    (cwd / "tests" / "test_self_heal_buggy.py").write_text(TEST); fix(); register()
elif scen == "two_step":
    if n == 1:
        (cwd / "tests" / "test_self_heal_buggy.py").write_text(TEST); register()
    else:
        fix()
elif scen == "protected":
    (cwd / "AGENTS.md").write_text("weakened\n")
    (cwd / "tests" / "test_self_heal_buggy.py").write_text(TEST); fix(); register()
elif scen == "skip":
    p = cwd / "tests" / "test_a.py"
    p.write_text("import pytest\n@pytest.mark.skip(reason='x')\n" + p.read_text())
    (cwd / "tests" / "test_self_heal_buggy.py").write_text(TEST); register()
elif scen == "noprogress":
    (cwd / "tests" / "test_self_heal_buggy.py").write_text(TEST); register()
if (here / "text_output").exists():
    print("plain text backend: changed scripts/buggy.py")
else:
    print(json.dumps({{"type": "result", "is_error": False, "total_cost_usd": 0.5, "num_turns": 3,
                      "result": 'ok\n{{"root_cause": "division by zero", "fix": "guard b == 0", "confidence": 0.9}}'}}))
'''

FAKE_GH = r'''#!/bin/sh
echo "$@" >> "$(dirname "$0")/gh_calls.txt"
echo "https://github.com/PatsKiller/tardeai/pull/4242"
'''

CI_STUB = 'GATES = [\n    ("a", ["tests/test_a.py"]),\n]\nprint("ci ok")\n'


def _sh(*cmd, cwd=None):
    return subprocess.run(list(cmd), cwd=cwd, check=True, capture_output=True, text=True).stdout


def _exe(path: Path, text: str):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def sandbox(tmp_path):
    origin = tmp_path / "origin.git"
    _sh("git", "init", "-q", "--bare", "-b", "main", str(origin))
    repo = tmp_path / "repo"
    _sh("git", "clone", "-q", str(origin), str(repo))
    for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
        _sh("git", "-C", str(repo), "config", k, v)
    (repo / "scripts").mkdir()
    (repo / "tests").mkdir()
    (repo / "scripts" / "__init__.py").write_text("")
    (repo / "scripts" / "buggy.py").write_text("def ratio(a, b):\n    return a / b\n")
    (repo / "scripts" / "run_cio_hardening_ci.py").write_text(CI_STUB)
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert 1 + 1 == 2\n")
    (repo / "conftest.py").write_text("import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent))\n")
    (repo / "AGENTS.md").write_text("# AGENTS\n\n" + F.extract_rails(AGENTS_TEXT) + "\n---\n\n# 1 · Identity\n")
    _sh("git", "-C", str(repo), "add", "-A")
    _sh("git", "-C", str(repo), "commit", "-qm", "base")
    _sh("git", "-C", str(repo), "push", "-q", "origin", "main")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _exe(bindir / "claude", FAKE_CLAUDE.format(py=sys.executable))
    _exe(bindir / "gh", FAKE_GH)
    state = tmp_path / "state"
    cfg = _cfg(repo={"repo_root": str(repo), "worktree_root": str(tmp_path / "wt"), "python": sys.executable},
               claude={"bin": str(bindir / "claude"), "env_names": ["HOME", "PATH"]},
               sandbox={"enabled": False},
               iteration={"ci_argv": ["{python}", "scripts/run_cio_hardening_ci.py"], "test_timeout_s": 120,
                          "ci_timeout_s": 120},
               lifecycle={"release_current_sha_file": str(tmp_path / "GIT_SHA")})
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(cfg))
    incident = tmp_path / "incident.json"
    defect = _producer_defect(lane="buggy-lane", stderr="ZeroDivisionError: division by zero", run="r1")
    incident.write_text(json.dumps({"code_defect": defect,
                                    "receipt": {"run_id": "r1", "argv": ["$PY", "scripts/buggy.py"],
                                                "stderr_tail": "Traceback\nZeroDivisionError: division by zero\n"},
                                    "registry_row": {"lane_id": "buggy-lane", "output_signal": {
                                        "kind": "json_key", "path": "data/runtime/buggy-lane_last.json",
                                        "key": "ok_at"}}}))
    env = {"HOME": os.environ.get("HOME", str(tmp_path)), "PATH": f"{bindir}:{os.environ['PATH']}",
           "TRADEAI_STATE_ROOT": str(state), "TRADE_AI_CI": "1"}
    return {"repo": repo, "origin": origin, "bin": bindir, "state": state, "cfg": cfg_path, "incident": incident,
            "env": env, "tmp": tmp_path}


def _run_cycle(sb, scenario, *, agents_marker=False, grant="self-heal-fixer test"):
    (sb["bin"] / "scenario").write_text(scenario)
    if agents_marker:
        marker = CFG["policy_gate"]["amendment_heading_marker"]
        p = sb["repo"] / "AGENTS.md"
        p.write_text(p.read_text() + f"\n{marker} (13.0.0, ACTIVE)\n")
        _sh("git", "-C", str(sb["repo"]), "commit", "-qam", "amend")
        _sh("git", "-C", str(sb["repo"]), "push", "-q", "origin", "main")
    rc = S.main(["--cycle", "--apply", "--config", str(sb["cfg"]), "--incident", str(sb["incident"])],
                now=lambda: NOW, environ=sb["env"],
                grant_reader=lambda tier: {"reason": grant, "grant_id": "a" * 32} if grant else None,
                gh=lambda cmd: {"rc": 1, "out": "", "err": "", "seconds": 0})
    assert rc == 0
    st = json.loads((sb["state"] / CFG["state"]["state_rel"]).read_text())
    (job,) = st["jobs"].values()
    calls = [json.loads(x) for x in (sb["bin"] / "calls.jsonl").read_text().splitlines()] \
        if (sb["bin"] / "calls.jsonl").exists() else []
    return job, calls


def test_success_without_amendment_stops_at_fix_ready_local(sandbox):
    job, calls = _run_cycle(sandbox, "fix")
    assert job["state"] == F.FIX_READY_LOCAL and job["reason"] == "push_not_allowed"
    it = job["iterations"][0]
    assert it["passed"] and it["red_first"] is True and it["ci_rc"] == 0
    assert it["tests_run"] == ["tests/test_self_heal_buggy.py"] and it["diffstat"]["files"] == 3
    assert len(calls) == 1 and calls[0]["cwd"] != str(sandbox["repo"])  # ran in the isolated worktree
    assert "DB_PASSWORD" not in calls[0]["env"] and "TRADE_AI_CI" in calls[0]["env"]
    # committed on a local branch; nothing pushed, no PR
    log = _sh("git", "-C", str(sandbox["repo"]), "log", "--format=%s", job["branch"])
    assert "self-heal fix for ZeroDivisionError" in log.splitlines()[0]
    assert job["branch"] not in _sh("git", "-C", str(sandbox["origin"]), "branch", "--list")
    assert not (sandbox["bin"] / "gh_calls.txt").exists()
    ev = sandbox["state"] / CFG["state"]["evidence_rel"] / job["job_id"]
    assert (ev / "pr_body.md").exists() and (ev / "fix.patch").exists() and (ev / "prompt_iter1.md").exists()
    assert not list((sandbox["tmp"] / "wt").glob("shf-*"))  # worktrees cleaned
    rcpt = json.loads((sandbox["state"] / CFG["state"]["receipt_rel"]).read_text())
    assert rcpt["ok_at"] and rcpt["arming"]["armed"]


def test_repair_memory_is_durable_per_signature(sandbox):
    job, _ = _run_cycle(sandbox, "two_step")
    rows = [json.loads(x) for x in (sandbox["state"] / CFG["state"]["repair_memory_rel"]).read_text().splitlines()]
    assert [r["event"] for r in rows] == ["consumed", "iteration", "iteration", "attempt_outcome"]
    assert {r["signature"] for r in rows} == {job["signature"]} and {r["defect_id"] for r in rows} == {job["defect_id"]}
    it1, it2 = rows[1], rows[2]
    assert it1["backend"] == it2["backend"] == "claude_code" and it1["selector"] == "static"
    assert it1["accepted_local"] is False and it2["accepted_local"] is True
    assert it1["diff_sha256"] != it2["diff_sha256"] and Path(it2["patch"]).exists()
    assert rows[3]["shadow_route"]["used"] is False and rows[3]["state"] == F.FIX_READY_LOCAL
    # a second cycle appends; nothing is rewritten
    S.main(["--cycle", "--apply", "--config", str(sandbox["cfg"]), "--incident", str(sandbox["incident"])],
           now=lambda: NOW, environ=sandbox["env"], grant_reader=lambda t: None,
           gh=lambda cmd: {"rc": 1, "out": "", "err": "", "seconds": 0})
    again = (sandbox["state"] / CFG["state"]["repair_memory_rel"]).read_text().splitlines()
    assert again[:4] == [json.dumps(r, sort_keys=True, default=str) for r in rows]


def test_a_second_backend_kind_passes_the_same_acceptance_scenario(sandbox):
    """Backend qualification shape: the same scenario, judged by the same evaluator, through the generic
    cli_stdin contract (plain-text output, no cost JSON) instead of the Claude CLI."""
    cfg = json.loads(sandbox["cfg"].read_text())
    cfg["backends"]["candidate"] = {"kind": "cli_stdin", "bin": str(sandbox["bin"] / "claude"),
                                    "argv_template": ["{bin}"], "enabled": True, "qualified": True}
    cfg["selector"]["backend"] = "candidate"
    sandbox["cfg"].write_text(json.dumps(cfg))
    (sandbox["bin"] / "text_output").write_text("1")
    job, calls = _run_cycle(sandbox, "fix")
    assert job["backend"] == "candidate" and job["state"] == F.FIX_READY_LOCAL
    assert job["iterations"][0]["acceptance"]["accepted"] and calls[0]["argv"] == []
    assert job["shadow_route"]["chosen_static"] == "candidate"


def test_success_with_amendment_pushes_one_branch_and_opens_labelled_pr(sandbox):
    job, _ = _run_cycle(sandbox, "fix", agents_marker=True)
    assert job["state"] == F.FIX_PR_OPENED and job["pr_number"] == 4242
    assert job["branch"] in _sh("git", "-C", str(sandbox["origin"]), "branch", "--list")
    gh = (sandbox["bin"] / "gh_calls.txt").read_text()
    assert "pr create" in gh and "--label self-heal-fix" in gh and "--base main" in gh
    assert "merge" not in gh  # never merges
    assert not F.is_healed(job)


def test_previous_output_is_fed_back_and_two_step_fix_passes(sandbox):
    job, calls = _run_cycle(sandbox, "two_step")
    assert [c["prev"] for c in calls] == [False, True]
    assert [i["passed"] for i in job["iterations"]] == [False, True]
    assert any("test_ratio_handles_zero" in f for f in job["iterations"][0]["failing"])
    assert job["state"] == F.FIX_READY_LOCAL and job["cost_usd"] == 1.0


def test_same_failing_set_twice_stops_early_and_escalates_p1_once(sandbox):
    job, calls = _run_cycle(sandbox, "noprogress")
    assert job["state"] == F.FIX_FAILED and job["reason"] == "no_progress"
    assert len(calls) == 2 < CFG["iteration"]["max_iterations"]
    esc = [json.loads(x) for x in (sandbox["state"] / CFG["state"]["escalations_rel"]).read_text().splitlines()]
    assert len(esc) == 1 and esc[0]["priority"] == "P1" and len(esc[0]["tried"]) == 2
    assert job["branch"] not in _sh("git", "-C", str(sandbox["repo"]), "branch", "--list")


@pytest.mark.parametrize("scenario,code", [("protected", "guard:protected_path"),
                                           ("skip", "guard:test_weakened:skip_or_xfail")])
def test_authority_breach_refuses_the_job(sandbox, scenario, code):
    job, calls = _run_cycle(sandbox, scenario, agents_marker=True)
    assert job["state"] == F.FIX_REFUSED and job["reason"] == "guard_refused"
    assert code in job["iterations"][0]["failing"] and len(calls) == 1
    assert not (sandbox["bin"] / "gh_calls.txt").exists()
    assert job["branch"] not in _sh("git", "-C", str(sandbox["origin"]), "branch", "--list")


@pytest.mark.skipif(not _bwrap_works(), reason="bubblewrap unavailable on this runner (host-only proof)")
def test_sandboxed_loop_runs_tests_without_network(sandbox):
    cfg = json.loads(sandbox["cfg"].read_text())
    cfg["sandbox"]["enabled"] = True
    sandbox["cfg"].write_text(json.dumps(cfg))
    # the regression test also proves the sandbox: no route to a localhost port from inside it
    probe = ("    import socket\n    s = socket.socket(); s.settimeout(1)\n"
             "    assert s.connect_ex(('127.0.0.1', 5432)) != 0\n")
    fake = (sandbox["bin"] / "claude").read_text().replace(
        'TEST = "def test_ratio_handles_zero():\\n',
        'TEST = "def test_ratio_handles_zero():\\n' + probe.replace("\n", "\\n"))
    assert "connect_ex" in fake
    (sandbox["bin"] / "claude").write_text(fake)
    job, calls = _run_cycle(sandbox, "fix")
    assert job["state"] == F.FIX_READY_LOCAL, job["iterations"]
    assert job["iterations"][0]["red_first"] is True
    assert "--setting-sources" in calls[0]["argv"]


def test_not_armed_runs_no_model(sandbox):
    job, calls = _run_cycle(sandbox, "fix", grant=None)
    assert job["state"] == F.FIX_REQUESTED and calls == []


# ---------------------------------------------------------------- 6. lifecycle advance


def test_advance_merged_released_recovered_resolved(sandbox, monkeypatch):
    repo = sandbox["repo"]
    head = _sh("git", "-C", str(repo), "rev-parse", "HEAD").strip()
    (sandbox["tmp"] / "GIT_SHA").write_text(head + "\n")
    cfg = json.loads(sandbox["cfg"].read_text())
    monkeypatch.setattr(S, "registry_row", lambda lane: {"output_signal": {
        "kind": "json_key", "path": "data/runtime/buggy-lane_last.json", "key": "ok_at"}})
    job = {"job_id": "j", "lane": "buggy-lane", "state": F.FIX_PR_OPENED, "pr_number": 9, "escalation_key": "k",
           "history": []}
    job["head_sha"] = head
    job["iterations"] = [{"passed": True, "acceptance": {"accepted": True}}]
    gh = lambda cmd: {"rc": 0, "out": json.dumps({"state": "MERGED", "mergeCommit": {"oid": head},
                                                  "mergedAt": "2026-10-16T17:00:00Z", "headRefOid": head,
                                                  "statusCheckRollup": [{"name": "cio-hardening", "status": "COMPLETED",
                                                                         "conclusion": "SUCCESS"}]})}
    root = sandbox["state"]
    assert S.advance(job, cfg=cfg, now=NOW, diag_state=None, root=root, gh=gh, repo=repo) == F.FIX_DEPLOYED
    assert job["acceptance"]["accepted"] and job["acceptance"]["pr_head_ci"] == "pass"  # independent evaluator
    assert S.advance(job, cfg=cfg, now=NOW, diag_state=None, root=root, gh=gh, repo=repo) is None  # no fresh output
    out = root / "data/runtime/buggy-lane_last.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"ok_at": (NOW + timedelta(hours=1)).isoformat()}))
    later = NOW + timedelta(hours=2)
    assert S.advance(job, cfg=cfg, now=later, diag_state=None, root=root, gh=gh, repo=repo) == F.OUTPUT_RECOVERED
    diag_open = {"escalations": {"k": {"heal_state": "recovery_requested"}}}
    assert S.advance(job, cfg=cfg, now=later, diag_state=diag_open, root=root, gh=gh, repo=repo) is None
    assert S.advance(job, cfg=cfg, now=later, diag_state={"escalations": {}}, root=root, gh=gh,
                     repo=repo) == F.INCIDENT_RESOLVED


def test_advance_unreleased_merge_stays_pr_opened(sandbox):
    cfg = json.loads(sandbox["cfg"].read_text())
    (sandbox["tmp"] / "GIT_SHA").write_text("0" * 40)
    job = {"job_id": "j", "lane": "l", "state": F.FIX_PR_OPENED, "pr_number": 9, "history": []}
    gh = lambda cmd: {"rc": 0, "out": json.dumps({"state": "MERGED", "mergeCommit": {"oid": "f" * 40}})}
    assert S.advance(job, cfg=cfg, now=NOW, diag_state=None, root=sandbox["state"], gh=gh,
                     repo=sandbox["repo"]) is None
    assert job["state"] == F.FIX_PR_OPENED and job["merged_sha"] == "f" * 40


# ---------------------------------------------------------------- 7. dry run on today's incident


def test_dry_run_on_daily_incubator_refresh_calls_no_model_and_writes_no_state(sandbox, tmp_path):
    marker = tmp_path / "claude_was_called"
    fake = tmp_path / "claude_marker"
    _exe(fake, f"#!/bin/sh\ntouch {marker}\n")
    cfg = json.loads(sandbox["cfg"].read_text())
    cfg["claude"]["bin"] = str(fake)
    cfg_path = tmp_path / "cfg_dry.json"
    cfg_path.write_text(json.dumps(cfg))
    out = tmp_path / "out"
    state = tmp_path / "state_dry"
    rc = S.main(["--cycle", "--config", str(cfg_path), "--incident", str(FIXTURE), "--out", str(out)],
                now=lambda: NOW, environ={"TRADEAI_STATE_ROOT": str(state), "HOME": "/h", "PATH": "/bin"},
                grant_reader=lambda tier: None)
    assert rc == 0 and not marker.exists() and not state.exists()
    assert not (sandbox["tmp"] / "wt").exists()  # no worktree in a dry run
    plan = json.loads((out / "plan.json").read_text())
    assert plan["backend_call"].startswith("STUBBED") and plan["would_push"] is False
    assert plan["backend"] == "claude_code" and plan["job"]["defect_id"].startswith("cd-daily-incubator-refresh-")
    assert plan["job"]["shadow_route"]["used"] is False
    assert plan["job"]["lane"] == "daily-incubator-refresh" and plan["job"]["state"] == F.FIX_REQUESTED
    ev = json.loads((out / "evidence.json").read_text())
    assert ev["final_exception"]["type"] == "psycopg2.InterfaceError"
    assert ev["script"] == "scripts/daily_incubator_refresh.py"
    assert ev["failing_run"]["run_id"] == "d:daily-incubator-refresh:live:20261016T0815"
    prompt = (out / "prompt_iter1.md").read_text()
    assert "MBI_BEHAVIOR = 0" in prompt and "connection already closed" in prompt
    assert "REQUIRES it to fail there" in prompt
    rcpt = json.loads((out / "receipt.json").read_text())
    assert rcpt["mode"] == "dry_run" and not rcpt["arming"]["armed"]


# ---------------------------------------------------------------- registry / allowlist rows


def test_lane_is_registered_paused_on_host_cron_and_never_n8n_runnable():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    (row,) = [r for r in reg["lanes"] if r["lane_id"] == "self-heal-fixer"]
    assert row["state"] == "PAUSED" and row["scheduler"]["kind"] == "cron"
    assert row["recommendation"] == "KEEP_ON_CRON"
    assert "scripts/self_heal_fixer.py --cycle --apply" in row["scheduler"]["install_line"]
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text())
    assert "self-heal-fixer" not in {r["lane_id"] for r in allow["lanes"]}
    assert "24.5" in allow["blocked_reasons"]["self-heal-fixer"]
