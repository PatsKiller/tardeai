"""Main-red self-heal (plan item 4, 2026-11-02).

The lane watches the newest origin/main run of a required workflow. When it is red it
re-runs the failed jobs ONCE (``gh run rerun <id> --failed``), and:

* a green re-run records the failure as a suspected flake (the plan's case C: one flaky
  test blocked the deploy poller until a human re-ran it);
* a second red records an escalation: one P1 page and one Claude Code fixer request.

AGENTS.md wins over the plan. §24.5 forbids a scheduled job from writing to a remote, so
the fix task stays a LOCAL request file. The earlier §28.14 reading ("never a test failure")
is superseded by the operator STANDING ORDER of 2026-11-03: every failed CI run gets ONE
automatic re-run per failing head per check group; a passing re-run is FLAKY and opens the
fix task, a second failure is REAL and is never re-run a third time. Every remote write is
behind a config gate.

Hermetic: every gh call, the Telegram sender and the issue writer are injected fakes;
state, receipts and fixer requests live under tmp_path. Nothing reaches GitHub.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import main_red_autoheal as mra

#: The firing test below drives main()'s own send import path, so this file's alarm site is covered.
COVERS = ["scripts/main_red_autoheal.py"]

REPO_ROOT = Path(__file__).resolve().parents[1]

CONFIG = {
    "schema": "MainRedAutohealConfig@v1",
    "repo": "example-org/example-repo",
    "branch": "main",
    "required_workflows": ["cio-production-hardening-ci", "agent-governance"],
    "run_list_limit": 40,
    "max_reruns": 1,
    "rerun_classes": {"infrastructure": True, "test_failure": False, "unknown": False},
    "infra_log_markers": ["The runner has received a shutdown signal", "No space left on device"],
    "flaky_issue": {"enabled": False, "label": "flaky-test"},
    "fixer": {"enabled": True, "requests_rel": "fixer_requests"},
    "page": {"enabled": True, "severity": "P1"},
    "log_tail_chars": 4000,
    "page_cooldown_hours": 6,
}


def run_json(run_id="991", workflow="cio-production-hardening-ci", conclusion="failure",
             head_sha="a" * 40, event="push", created_at="2026-11-02T03:00:00Z",
             status="completed", url="https://example.com/run/991"):
    # No `attempt` key: real `gh run list` has none, and this host's gh also rejects
    # `gh run view --json attempt`. The attempt comes from the REST field via `gh api`.
    return {
        "databaseId": run_id, "workflowName": workflow, "conclusion": conclusion,
        "status": status, "headSha": head_sha, "event": event, "createdAt": created_at,
        "url": url,
    }


class FakeGh:
    """Stand-in for the gh CLI: records every argv and serves scripted output."""

    def __init__(self, runs, views=None, logs=None):
        self.runs = runs
        self.views = views or {}
        self.logs = logs or {}
        self.rerun_rc = 0
        self.attempts: dict[str, int] = {}
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if argv[:2] == ["run", "list"]:
            return 0, json.dumps(self.runs)
        if argv[:2] == ["run", "view"]:
            run_id = str(argv[2])
            if "--log-failed" in argv:
                return 0, self.logs.get(run_id, "")
            return 0, json.dumps(self.views.get(run_id, {"conclusion": "failure", "status": "completed"}))
        if argv[:2] == ["run", "rerun"]:
            return self.rerun_rc, ""
        if argv[:1] == ["api"] and "--jq" in argv:
            run_id = str(argv[1]).rsplit("/", 1)[-1]
            return 0, str(self.attempts.get(run_id, 1))
        return 1, f"unexpected gh argv: {argv}"

    @property
    def reruns(self):
        return [c for c in self.calls if c[:2] == ["run", "rerun"]]

    @property
    def writes(self):
        return [c for c in self.calls if c[:2] == ["run", "rerun"]]


class FakeTelegram:
    def __init__(self):
        self.sent: list[dict] = []

    def __call__(self, text, *, priority="P1"):
        self.sent.append({"text": text, "priority": priority})
        return True


def cycle(tmp_path, gh, *, cfg=None, dry_run=False, telegram=None, issue_writer=None):
    return mra.run_cycle(
        cfg or dict(CONFIG), state_dir=tmp_path / "state", gh=gh, dry_run=dry_run,
        telegram=telegram, issue_writer=issue_writer, now="2026-11-02T03:05:00Z",
    )


# ------------------------------------------------------------------ rerun paths
def test_infrastructure_failure_is_rerun_exactly_once(tmp_path):
    gh = FakeGh([run_json()], logs={"991": "Runner lost connection.\nThe runner has received a shutdown signal"})
    receipt = cycle(tmp_path, gh)

    assert [c[2] for c in gh.reruns] == ["991"]
    assert receipt["actions"][0]["action"] == "rerun"
    assert receipt["actions"][0]["failure_class"] == "infrastructure"


def test_green_rerun_records_a_suspected_flake(tmp_path):
    gh = FakeGh([run_json()], logs={"991": "The runner has received a shutdown signal"},
                views={"991": {"conclusion": "success", "status": "completed"}})
    cycle(tmp_path, gh)                      # cycle 1 detects red and re-runs
    receipt = cycle(tmp_path, gh)            # cycle 2 observes the re-run's result

    assert receipt["actions"][0]["action"] == "flake_recorded"
    assert receipt["actions"][0]["suspected_flake"] is True
    assert len(gh.reruns) == 1               # never re-runs twice


def test_second_failure_pages_once_and_writes_one_fixer_request(tmp_path):
    gh = FakeGh([run_json()], logs={"991": "FAILED tests/test_x.py::test_y - StopIteration"},
                views={"991": {"conclusion": "failure", "status": "completed"}})
    telegram = FakeTelegram()
    cfg = dict(CONFIG, rerun_classes={"infrastructure": True, "test_failure": True, "unknown": False})

    cycle(tmp_path, gh, cfg=cfg, telegram=telegram)          # re-run requested
    receipt = cycle(tmp_path, gh, cfg=cfg, telegram=telegram)  # still red -> escalate
    cycle(tmp_path, gh, cfg=cfg, telegram=telegram)          # idempotent

    assert len(gh.reruns) == 1
    assert len(telegram.sent) == 1
    assert "tests/test_x.py::test_y" in telegram.sent[0]["text"]
    requests = sorted((tmp_path / "state" / "fixer_requests").glob("*.json"))
    assert len(requests) == 1
    body = json.loads(requests[0].read_text())
    assert body["code_defect"]["schema"] == "N8nCodeDefect@v1"
    assert body["main_red_autoheal"]["failing_test_ids"] == ["tests/test_x.py::test_y"]
    assert body["main_red_autoheal"]["run_url"] == "https://example.com/run/991"
    assert receipt["actions"][0]["action"] == "page_and_dispatch"


def test_already_rerun_run_is_never_rerun_again(tmp_path):
    gh = FakeGh([run_json()], logs={"991": "The runner has received a shutdown signal"})
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "state.json").write_text(json.dumps({
        "schema": "MainRedAutohealState@v1",
        "runs": {"991:1": {"attempts": 1, "head_sha": "a" * 40, "escalated": False,
                         "flake_recorded": False, "last_action": "rerun_requested"}},
    }))

    receipt = cycle(tmp_path, gh)

    assert gh.reruns == []
    assert receipt["actions"][0]["action"] == "page_and_dispatch"


# ------------------------------------------------------------------ AGENTS 24.5/28.14 gates
def test_a_test_failure_is_not_rerun_by_default(tmp_path):
    gh = FakeGh([run_json()], logs={"991": "FAILED tests/test_flaky.py::test_it - AssertionError"})
    telegram = FakeTelegram()

    receipt = cycle(tmp_path, gh, telegram=telegram)

    assert gh.reruns == []                    # §28.14: never a test failure
    assert receipt["actions"][0]["failure_class"] == "test_failure"
    assert receipt["actions"][0]["action"] == "page_and_dispatch"
    assert len(telegram.sent) == 1


def test_dry_run_never_writes_remotely_or_mutates_state(tmp_path):
    gh = FakeGh([run_json()], logs={"991": "The runner has received a shutdown signal"})

    receipt = cycle(tmp_path, gh, dry_run=True)

    assert gh.writes == []
    assert not (tmp_path / "state" / "state.json").exists()
    assert receipt["actions"][0]["action"] == "would_rerun"


# ------------------------------------------------------------------ selection
def test_pull_request_runs_are_ignored(tmp_path):
    gh = FakeGh([run_json(event="pull_request")], logs={"991": "The runner has received a shutdown signal"})

    receipt = cycle(tmp_path, gh)

    assert gh.reruns == []
    assert receipt["actions"] == []
    assert receipt["skipped"][0]["reason"] == "no_required_main_run_red"


def test_stale_commit_run_is_ignored(tmp_path):
    old, new = "b" * 40, "a" * 40
    gh = FakeGh([
        run_json(run_id="2", workflow="agent-governance", head_sha=new, conclusion="success",
                 created_at="2026-11-02T03:00:00Z"),
        run_json(run_id="1", workflow="cio-production-hardening-ci", head_sha=old, conclusion="failure",
                 created_at="2026-11-02T02:00:00Z"),
    ], logs={"1": "The runner has received a shutdown signal"})

    receipt = cycle(tmp_path, gh)

    assert gh.reruns == []
    assert receipt["actions"] == []
    assert any(s["reason"] == "stale_commit" for s in receipt["skipped"])


# ------------------------------------------------------------------ shipped config
def test_shipped_config_is_valid_and_gates_remote_writes():
    cfg = json.loads((REPO_ROOT / "config" / "main_red_autoheal.json").read_text())

    assert cfg["schema"] == "MainRedAutohealConfig@v1"
    assert cfg["max_reruns"] == 1
    # Operator STANDING ORDER 2026-11-03: failed CI gets ONE automatic re-run by agents (test failures
    # included), pass = FLAKY + a local fix task, fail again = REAL and never re-run a third time.
    assert cfg["rerun_classes"]["test_failure"] is True
    assert "ONE automatic re-run" in cfg["_why"] and "never re-run a third time" in cfg["_why"]
    assert cfg["flaky_issue"]["enabled"] is False  # still no GitHub write from a scheduled job (§24.5)
    assert "24.5" in cfg["_why"] and "28.14" in cfg["_why"]
    assert cfg["required_workflows"]


# ------------------------------------------------------------------ decision invariants
def test_decide_only_ever_names_one_of_the_four_actions():
    """Every reachable row of the decision table lands in the closed action set."""
    seen = set()
    for attempts in (0, 1, 2, 3):
        for max_reruns in (0, 1, 2):
            for escalated in (False, True):
                for flake in (False, True):
                    for outcome in (None, "success", "failure", "in_progress", "bogus"):
                        for failure_class in ("infrastructure", "test_failure", "unknown", "weird"):
                            for allowed in (False, True):
                                decision = mra.decide(
                                    attempts=attempts, max_reruns=max_reruns, escalated=escalated,
                                    flake_recorded=flake, prior_rerun_outcome=outcome,
                                    failure_class=failure_class, rerun_allowed=allowed)
                                assert decision in mra.DECISIONS
                                seen.add(decision)
    assert seen == {"noop", "rerun", "flake_recorded", "page_and_dispatch"}


def test_decide_maps_the_cases_the_lane_depends_on():
    def d(**kw):
        base = dict(attempts=0, max_reruns=1, escalated=False, flake_recorded=False,
                    prior_rerun_outcome=None, failure_class="infrastructure", rerun_allowed=True)
        return mra.decide(**{**base, **kw})

    assert d() == "rerun"
    assert d(rerun_allowed=False, failure_class="test_failure") == "page_and_dispatch"
    assert d(attempts=1, prior_rerun_outcome="success") == "flake_recorded"
    assert d(attempts=1, prior_rerun_outcome="failure") == "page_and_dispatch"
    assert d(attempts=1, prior_rerun_outcome="in_progress") == "noop"
    assert d(attempts=1, max_reruns=1, prior_rerun_outcome=None) == "noop"  # outcome unreadable yet: wait
    assert d(escalated=True) == "noop"
    assert d(flake_recorded=True) == "noop"


# ------------------------------------------------------------------ the real default path
def test_default_config_path_resolves_the_shipped_config():
    path = mra.default_config_path()
    assert path.is_file(), f"the lane's default config path does not exist: {path}"
    cfg = json.loads(path.read_text())
    assert cfg["schema"] == mra.CONFIG_SCHEMA
    assert path.name == "main_red_autoheal.json"


def test_main_loads_the_default_config_end_to_end(tmp_path, monkeypatch, capsys):
    """The ROOT parent-count bug is caught here: main() must find config/ from its default path."""
    green = [run_json(conclusion="success")]
    monkeypatch.setattr(mra, "_gh_runner", lambda argv: (0, json.dumps(green)))
    rc = mra.main(["--state-dir", str(tmp_path / "state"), "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "MainRedAutohealReceipt@v1" in out
    assert "refusing" not in out


def test_default_state_dir_follows_tradeai_state_root(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    assert mra.default_state_dir() == tmp_path / "data" / "runtime" / "main_red_autoheal"


# ------------------------------------------------------------------ the fixer consumes it
def test_the_request_is_consumable_by_self_heal_fixer_dry_run(tmp_path):
    """Proves the incident format: the existing fixer admits a job from our request (it stays disarmed)."""
    gh = FakeGh([run_json()], logs={"991": "FAILED tests/test_x.py::test_y - StopIteration"})
    cfg = dict(CONFIG, rerun_classes={"infrastructure": True, "test_failure": False, "unknown": False})
    cycle(tmp_path, gh, cfg=cfg, telegram=FakeTelegram())
    request = tmp_path / "state" / "fixer_requests" / "991-1.json"
    assert request.is_file()

    out_dir = tmp_path / "fixer-out"
    out_dir.mkdir()
    env = dict(os.environ, TRADE_AI_CI="1", TRADEAI_STATE_ROOT=str(tmp_path / "fixer-state"),
               TMPDIR=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "self_heal_fixer.py"),
         "--cycle", "--incident", str(request), "--out", str(out_dir)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, env=env, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    result = json.loads(proc.stdout)
    assert result["admitted"], result
    job = result["admitted"][0]
    assert job["lane"] == "cio-production-hardening-ci"
    assert job["state"] == "fix_requested"
    assert job["defect_id"] == "cd-main-red-991-ep1"


# ------------------------------------------------------------------ the alarm fires through main()
def test_main_apply_pages_through_its_own_send_import(tmp_path, monkeypatch):
    """Fires the alarm through main()'s real import path, not an injected callable.

    This is what the COVERS entry above claims: the only send_telegram site in the module is
    executed and observed delivering the page.
    """
    sent: list[tuple[str, dict]] = []

    def _send(text, **kwargs):
        sent.append((text, kwargs))
        return True

    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = _send
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)

    gh = FakeGh([run_json()], logs={"991": "FAILED tests/test_x.py::test_y - StopIteration"})
    monkeypatch.setattr(mra, "_gh_runner", gh)

    # Operator standing order 2026-11-03: the first cycle re-runs the failed jobs once (test failures
    # included) instead of paging; the page happens only when the re-run fails again (REAL).
    rc = mra.main(["--apply", "--state-dir", str(tmp_path / "state"), "--json"])

    assert rc == 0
    assert [c[2] for c in gh.reruns] == ["991"] and sent == []
    gh.attempts["991"] = 2  # the re-run attempt is the red one
    rc = mra.main(["--apply", "--state-dir", str(tmp_path / "state"), "--json"])

    assert rc == 0
    assert len(sent) == 1, sent
    assert "main is red" in sent[0][0]
    assert sent[0][1].get("priority") == "P1"


# ---------------------------------------------------------------- real-log classification
TAB = "\t"


def real_line(text, ts="2026-11-02T13:35:42.7538000Z", job="shard 5", step="Shard 5 of 8"):
    """A line in `gh run view --log-failed`'s real shape: job<TAB>step<TAB><timestamp> <text>."""
    return f"{job}{TAB}{step}{TAB}{ts} {text}"


def test_a_tab_prefixed_failed_line_yields_the_test_id():
    log = "\n".join([
        real_line("E   AssertionError: assert 56.29 == 62.09"),
        real_line("FAILED tests/test_price_unit_integrity_20260914.py::test_prev_close_is_the_prior_bar - AssertionError"),
    ])
    assert mra.extract_test_ids(log) == ["tests/test_price_unit_integrity_20260914.py::test_prev_close_is_the_prior_bar"]
    assert mra.classify_failure("failure", log, ["connection reset by peer"])[0] == "test_failure"


def test_a_failed_test_plus_an_infra_marker_is_still_a_test_failure():
    log = "\n".join([
        real_line("FAILED tests/test_demo.py::test_alpha - AssertionError"),
        real_line("503 Service Unavailable from the quote API"),
        real_line("connection reset by peer"),
    ])
    failure_class, ids = mra.classify_failure("failure", log, ["Service Unavailable", "connection reset by peer"])
    assert failure_class == "test_failure" and ids


def test_an_assertion_without_ids_is_still_a_test_failure():
    log = real_line("E   AssertionError: assert [] == [1]")
    assert mra.classify_failure("failure", log, ["Service Unavailable"])[0] == "test_failure"


def test_an_unknown_failure_pages_and_never_reruns(tmp_path):
    gh = FakeGh([run_json()], logs={"991": "some opaque failure with no signature"})
    telegram = FakeTelegram()
    receipt = cycle(tmp_path, gh, telegram=telegram)
    assert receipt["actions"][0]["failure_class"] == "unknown"
    assert receipt["actions"][0]["action"] == "page_and_dispatch"
    assert gh.reruns == []


def test_a_failed_rerun_call_still_counts_the_attempt(tmp_path):
    gh = FakeGh([run_json()], logs={"991": "The runner has received a shutdown signal"})
    gh.rerun_rc = 1
    cycle(tmp_path, gh)
    cycle(tmp_path, gh)
    assert len(gh.reruns) == 1  # never retried on the next cycle


def test_the_page_is_deduped_by_commit_and_check(tmp_path):
    gh = FakeGh([run_json(run_id="1")], logs={"1": "opaque failure"})
    telegram = FakeTelegram()
    cfg = dict(CONFIG, page_events=[])
    cycle(tmp_path, gh, telegram=telegram)                       # first run: page
    gh.runs = [run_json(run_id="2")]                             # a second run on the same commit
    gh.logs = {"2": "opaque failure"}
    cycle(tmp_path, gh, telegram=telegram)
    assert len(telegram.sent) == 1  # cooldown by (head sha, workflow), not run id


def test_secret_scan_is_watched_and_codeql_is_gone():
    cfg = json.loads((REPO_ROOT / "config" / "main_red_autoheal.json").read_text())
    assert "secret-scan" in cfg["required_workflows"]
    assert "CodeQL" not in cfg["required_workflows"]  # removed 2026-11-02


# ---------------------------------------------------------------- review round 2
def test_a_failed_line_early_in_a_long_log_is_found(tmp_path):
    """Classification reads the whole log; the tail is only the fixer's evidence text."""
    log = "\n".join([real_line("FAILED tests/test_early.py::test_it - AssertionError")]
                     + [real_line("noise line " + str(i)) for i in range(3000)]
                     + [real_line("No space left on device")])
    assert len(log) > 20000
    gh = FakeGh([run_json()], logs={"991": log})
    receipt = cycle(tmp_path, gh)
    assert receipt["actions"][0]["failure_class"] == "test_failure"
    assert receipt["actions"][0]["action"] == "page_and_dispatch"
    assert receipt["actions"][0]["failing_test_ids"] == ["tests/test_early.py::test_it"]
    request = json.loads((tmp_path / "state" / "fixer_requests" / "991-1.json").read_text())
    assert len(request["receipt"]["stderr_tail"]) <= CONFIG["log_tail_chars"]


def test_a_different_failure_on_a_rerun_attempt_is_handled(tmp_path):
    cfg = dict(CONFIG, rerun_classes={"infrastructure": True, "test_failure": True, "unknown": False})
    gh = FakeGh([run_json()], logs={"991": "FAILED tests/test_a.py::test_one - AssertionError"})
    cycle(tmp_path, gh, cfg=cfg)                       # attempt 1: re-run requested
    gh.runs = [run_json()]
    gh.attempts = {"991": 2}
    gh.logs = {"991": "FAILED tests/test_b.py::test_two - AssertionError"}
    receipt = cycle(tmp_path, gh, cfg=cfg)              # attempt 2 fails with a DIFFERENT test
    assert receipt["actions"][0]["action"] == "page_and_dispatch"
    assert receipt["actions"][0]["failing_test_ids"] == ["tests/test_b.py::test_two"]
    assert (tmp_path / "state" / "fixer_requests" / "991-2.json").is_file()
    # a THIRD manual attempt, failing differently again, must still be handled — not "already handled".
    # With the attempt always read as 1 this returns noop, because attempt 2 escalated the shared record.
    gh.attempts = {"991": 3}
    gh.logs = {"991": "FAILED tests/test_c.py::test_three - AssertionError"}
    third = cycle(tmp_path, gh, cfg=cfg)
    assert third["actions"][0]["action"] == "page_and_dispatch"
    assert third["actions"][0]["failing_test_ids"] == ["tests/test_c.py::test_three"]


def test_the_twin_hardening_workflows_page_once_per_commit(tmp_path):
    telegram = FakeTelegram()
    gh = FakeGh([run_json(run_id="1", workflow="cio-production-hardening-ci")], logs={"1": "opaque"})
    cycle(tmp_path, gh, telegram=telegram)
    gh.runs = [run_json(run_id="2", workflow="cio-full-suite-sharded")]
    gh.logs = {"2": "opaque"}
    cycle(tmp_path, gh, telegram=telegram)
    assert len(telegram.sent) == 1


def test_the_page_ledger_is_pruned_to_the_cooldown(tmp_path):
    cfg = dict(CONFIG, page={"enabled": True, "severity": "P1", "page_cooldown_hours": 1})
    gh = FakeGh([run_json(run_id="1")], logs={"1": "opaque"})
    cycle(tmp_path, gh, cfg=cfg, telegram=FakeTelegram())
    pages = json.loads((tmp_path / "state" / "pages.json").read_text())
    assert len(pages) == 1
    key = next(iter(pages))
    # an entry older than the window is dropped on the next mark
    import datetime as dt
    old = (dt.datetime.fromisoformat("2026-11-02T03:05:00+00:00") - dt.timedelta(hours=5)).isoformat()
    pages[key] = old
    (tmp_path / "state" / "pages.json").write_text(json.dumps(pages))
    gh.runs = [run_json(run_id="3", head_sha="b" * 40)]
    gh.logs = {"3": "opaque"}
    cycle(tmp_path, gh, cfg=cfg, telegram=FakeTelegram())
    assert key not in json.loads((tmp_path / "state" / "pages.json").read_text())


def test_the_attempt_comes_from_the_rest_field(tmp_path):
    gh = FakeGh([run_json()])
    gh.attempts = {"991": 3}
    assert mra._run_attempt(CONFIG, gh, "991", {}) == 3
    assert ["api"] == gh.calls[-1][:1]


def test_a_green_rerun_on_a_new_attempt_records_the_flake(tmp_path):
    """A re-run that turns green is attempt 2; the flake belongs to the attempt that re-ran it."""
    gh = FakeGh([run_json()], logs={"991": "The runner has received a shutdown signal"})
    cycle(tmp_path, gh)                                 # attempt 1: red -> re-run
    gh.runs = [run_json(conclusion="success")]
    gh.attempts = {"991": 2}                           # the re-run is a new attempt, now green
    receipt = cycle(tmp_path, gh)
    assert receipt["actions"][0]["action"] == "flake_recorded"
    assert receipt["actions"][0]["suspected_flake"] is True
    assert len(gh.reruns) == 1


# --------------------------------------------- operator standing order 2026-11-03
# "One re-run per failing head per check so red is never retried into green."
GROUPED = {**CONFIG,
           "required_workflows": ["cio-production-hardening-ci", "cio-full-suite-sharded"],
           "rerun_classes": {"infrastructure": True, "test_failure": True, "unknown": False},
           "page_groups": {"cio-production-hardening-ci": "cio-hardening-suite",
                           "cio-full-suite-sharded": "cio-hardening-suite"}}


def test_one_rerun_per_failing_head_and_check_group(tmp_path):
    """Both workflows of one check group go red on the SAME head: the head is re-run once, not twice.

    The ledger is keyed (head SHA, check group), so the second workflow is held even though its own run
    record has never been seen — otherwise a single bad commit would burn one CI re-run per workflow.
    """
    gh = FakeGh([run_json("991", "cio-production-hardening-ci"),
                 run_json("992", "cio-full-suite-sharded")],
                logs={"991": "FAILED tests/test_x.py::test_y - StopIteration",
                      "992": "FAILED tests/test_x.py::test_y - StopIteration"})
    receipt = cycle(tmp_path, gh, cfg=dict(GROUPED))

    assert len(gh.reruns) == 1, gh.reruns
    actions = sorted((a["action"] for a in receipt["actions"]))
    assert actions == ["noop", "rerun"]
    held = next(a for a in receipt["actions"] if a["action"] == "noop")
    assert held["reason"] == "one re-run already requested for this head/check"


def test_passing_rerun_opens_a_fix_task_naming_the_flaky_test(tmp_path):
    """"Pass on re-run = FLAKY, record the test name and run ids, OPEN A FIX TASK ... and carry on." """
    gh = FakeGh([run_json()], logs={"991": "FAILED tests/test_x.py::test_y - StopIteration"},
                views={"991": {"conclusion": "failure", "status": "completed"}})
    cycle(tmp_path, gh, cfg=dict(GROUPED))            # cycle 1: one automatic re-run
    gh.views["991"] = {"conclusion": "success", "status": "completed"}
    receipt = cycle(tmp_path, gh, cfg=dict(GROUPED))  # cycle 2: the re-run passed -> flake

    action = receipt["actions"][0]
    assert action["action"] == "flake_recorded" and action["suspected_flake"] is True
    doc = json.loads(Path(action["fixer_request"]).read_text())
    assert doc["main_red_autoheal"]["why"].startswith("suspected flake")
    assert "tests/test_x.py::test_y" in doc["main_red_autoheal"]["failing_test_ids"]
    assert doc["main_red_autoheal"]["run_id"] == "991"
