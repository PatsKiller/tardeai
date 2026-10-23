"""Release Train v2, Phase 3: the train controller (scripts/lib/release_train_controller.py via release_window.py).

Pipeline select -> freeze -> integrate -> local test -> qualify -> merge -> promote -> verify -> outcome, and the
enhanced design §10 adversarial list as far as it applies to the controller: competing trains, a manual/emergency
collision, main or CURRENT moving at each boundary, wrong / missing / revoked capability, forged / stale / wrong-SHA
CI evidence, missing / skipped / neutral mandatory checks, a candidate that edits its own verifier, STOP before
merge and during promotion, corrupt control state, restart with an ambiguous effect, DST, a stale macro calendar,
redeploying a failed artifact, dependency ejection and bisect attribution.

Hermetic: a temporary git repository (bare "origin" with refs/pull/N/head), a fake GitHub reader and writer, a fake
deploy host, a temp delegation, HMAC key and armed control state under tmp_path, a fixed clock. GitHub and
cio_phase2_exact_main_deploy.sh are never called; no network, DB, systemd or broker. psycopg2 is stubbed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # pragma: no cover - depends on the environment
    import psycopg2  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    _pg = types.ModuleType("psycopg2")

    def _no_connect(*_a, **_k):
        raise RuntimeError("psycopg2 stub: these tests never touch a database")

    _pg.connect = _no_connect
    sys.modules.setdefault("psycopg2", _pg)

from scripts import release_window as RW  # noqa: E402
from scripts.lib import release_capability as CAP  # noqa: E402
from scripts.lib import release_control as RC  # noqa: E402
from scripts.lib import release_delegation as RD  # noqa: E402
from scripts.lib import release_train_contracts as TC  # noqa: E402
from scripts.lib import release_train_controller as T  # noqa: E402
from scripts.lib import macro_calendar as MC  # noqa: E402

#: Alarm coverage (tests/test_alarm_coverage.py): release_window.Host.notify's send_telegram site (ops branch
#: 58bf60cf3) is fired by test_failed_window_alert_reaches_the_transport.
COVERS = ["scripts/release_window.py"]

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 10, 21, 18, 5, tzinfo=ET)
CHECKS = ("cio-hardening", "agent-governance", "release-readiness", "ci-gate")
HOST_ACTOR = RC.Actor("host_cli", "uid:test")
CC = RC.Actor("cc", "operator@tailnet")


@pytest.fixture(autouse=True)
def _hermetic_git(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def git(cwd, *args):
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=str(cwd), capture_output=True, text=True
    )
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


# ── the world ─────────────────────────────────────────────────────────────────────────────────────


class Clock:
    def __init__(self, t: datetime = NOW) -> None:
        self.t = t.timestamp()

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.t, timezone.utc)


class Repo:
    """origin.git (bare) with main and refs/pull/N/head; checkout = a clone (the release checkout)."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.origin = tmp / "origin.git"
        git(tmp, "init", "-q", "--bare", "--initial-branch=main", str(self.origin))
        self.seed = tmp / "seed"
        git(tmp, "init", "-q", "-b", "main", str(self.seed))
        (self.seed / "app.txt").write_text("line1\nline2\n")
        (self.seed / "docs").mkdir()
        (self.seed / "docs" / "base.md").write_text("# base\n")
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", "base")
        git(self.seed, "remote", "add", "origin", str(self.origin))
        git(self.seed, "push", "-q", "origin", "main")
        self.base = git(self.seed, "rev-parse", "HEAD")
        self.checkout = tmp / "checkout"
        git(tmp, "clone", "-q", str(self.origin), str(self.checkout))
        self.heads: dict[int, str] = {}

    def pr(self, n: int, files: dict, *, parent: str | None = None) -> str:
        git(self.seed, "checkout", "-q", "--detach", parent or self.base)
        for rel, text in files.items():
            p = self.seed / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-q", "-m", f"pr {n}")
        sha = git(self.seed, "rev-parse", "HEAD")
        git(self.seed, "push", "-q", "origin", f"{sha}:refs/pull/{n}/head")
        self.heads[n] = sha
        return sha


def runs_for(sha, conclusion="success", names=CHECKS, app="github-actions", status="completed", start_id=100):
    return [
        {"id": start_id + i, "name": n, "head_sha": sha, "status": status, "conclusion": conclusion, "app": app}
        for i, n in enumerate(names)
    ]


class FakeGitHub:
    repository = "PatsKiller/tardeai"

    def __init__(self, repo: Repo) -> None:
        self.repo = repo
        self.main = repo.base
        self.heads = dict(repo.heads)
        self.runs: dict[str, list] = {}
        self.default_runs = True
        self.parents: dict[str, list] = {}
        self.contains_map: dict[tuple, bool] = {}
        self.refs: dict[str, str] = {}
        self.on_main_read = None
        self.reads = 0

    def main_head(self):
        self.reads += 1
        if self.on_main_read:
            self.on_main_read(self)
        return self.main

    def pr_head(self, pr):
        return self.heads.get(pr)

    def check_runs(self, sha):
        if sha in self.runs:
            return list(self.runs[sha])
        return runs_for(sha) if self.default_runs else []

    def commit_parents(self, sha):
        return self.parents.get(sha)

    def contains(self, a, b):
        return self.contains_map.get((a, b), a == b)

    def ref_sha(self, ref):
        return self.refs.get(ref)


class FakeWriter:
    simulated = False

    def __init__(self, gh: FakeGitHub) -> None:
        self.gh = gh
        self.calls: list[tuple] = []
        self.hooks: dict[str, object] = {}
        self.merge_raises = None
        self.main_after_merge = None

    def push_train_ref(self, train_id, sha):
        self.calls.append(("push", train_id, sha))
        assert train_id.startswith("rt-")
        self.gh.refs[f"heads/train/{train_id}"] = sha
        if "push" in self.hooks:
            self.hooks["push"]()
        return {"ref": f"refs/heads/train/{train_id}", "sha": sha}

    def open_or_update_batch_pr(self, train_id, sha, title, body):
        self.calls.append(("open_pr", train_id, sha))
        self.gh.heads[9001] = sha
        if "open_pr" in self.hooks:
            self.hooks["open_pr"]()
        return 9001

    def merge_batch_pr(self, pr, expected_head_sha, message):
        self.calls.append(("merge", pr, expected_head_sha))
        if self.merge_raises:
            raise self.merge_raises
        m = hashlib.sha1(("merge" + expected_head_sha).encode()).hexdigest()
        self.gh.parents[m] = [self.gh.main, expected_head_sha]
        self.merged = m
        self.gh.main = self.main_after_merge or m
        if "merge" in self.hooks:
            self.hooks["merge"]()
        return m


class FakeHost:
    """release_window.Host stand-in: deploy prepare/promote/rollback and every verification read."""

    def __init__(self, tmp: Path, repo: Repo, clock: Clock) -> None:
        self.clock = clock
        self.checkout = repo.checkout
        self.deploy = tmp / "deploy.sh"
        self.python = sys.executable
        self.releases = tmp / "releases"
        self.prev = self.releases / "prev"
        self.prev.mkdir(parents=True)
        (self.prev / "BUILD_SHA").write_text("f" * 40 + "\n")
        self.cur = Path(os.path.realpath(self.prev))
        self.calls: list[tuple] = []
        self.health_when_new = 200
        self.promote_rc = 0
        self.rollback_rc = 0
        self.hooks: dict[str, object] = {}
        self.notified: list = []
        # CANONICAL_SOURCE (the dev tree the deploy runs its verifier from). None = fast-forwarded to the train's
        # merge commit (World wires main_ref to the fake writer's merge); a test pins a stale HEAD by setting a SHA.
        self.canonical_sha: str | None = None
        self.main_ref = lambda: ""

    def canonical_head(self):
        self.calls.append(("canonical_head",))
        return self.canonical_sha if self.canonical_sha is not None else self.main_ref()

    def now(self):
        return self.clock.now()

    def sleep(self, s):
        self.clock.t += s

    def current_release(self):
        return self.cur

    def build_sha(self, release):
        try:
            return (Path(release) / "BUILD_SHA").read_text().strip()
        except OSError:
            return ""

    def checkout_clean(self):
        return True

    def checkout_sha(self, sha):
        self.calls.append(("checkout", sha))
        self.sha = sha
        return 0, ""

    def run_deploy(self, args, env):
        self.calls.append(("deploy", *args, env.get("TRADEAI_RELEASE_CAMPAIGN"), env.get("TRADEAI_RELEASE_PR")))
        if args[0] == "prepare":
            d = self.releases / f"{self.sha[:9]}-new-{len(self.calls)}"
            d.mkdir(parents=True)
            (d / "BUILD_SHA").write_text(self.sha + "\n")
            return 0, f"log\nPREPARE OK: {d}\n{d}\n"
        if args[0] == "promote":
            if "promote" in self.hooks:
                self.hooks["promote"]()
            self.cur = Path(os.path.realpath(args[1]))
            return self.promote_rc, "PROMOTE OK"
        if args[0] == "rollback":
            self.cur = Path(os.path.realpath(args[1]))
            return self.rollback_rc, "ROLLBACK OK"
        raise AssertionError(args)

    def units_active(self, units):
        return {u: True for u in units}

    def http_status(self, url):
        return 200 if self.cur == Path(os.path.realpath(self.prev)) else self.health_when_new

    def http_get(self, url):
        if url.endswith("/api/v2/system/platform-health"):
            return 200, '{"status": "OK", "overall": "OK"}'
        if url.endswith("/api/v2/needs-action"):
            return 200, '{"counts": {}, "total": 0}'
        return 200, "<!doctype html>"

    def served_copy(self, release):
        return 0, ""

    def notify(self, message, priority):
        self.notified.append((priority, message))
        return {"accepted": True, "priority": priority}


class StaticQueue:
    name = "test-queue"

    def __init__(self, entries, complete=True, reasons=()):
        self.entries, self.complete, self.reasons = entries, complete, list(reasons)

    def snapshot(self):
        return T.QueueSnapshot(
            self.name, "2026-10-21T21:00:00+00:00", self.complete, list(self.entries), list(self.reasons)
        )


class AllowClassifier:
    version = "test-allow/1"
    policy_version = "test-policy/1"

    def classify(self, entry, change):
        return "eligible", ["test"]


FAIL_CMD = [sys.executable, "-c", "import os,sys; sys.exit(1 if os.path.exists('FAIL_MARKER') else 0)"]


def delegation_body(slot="1800"):
    d = json.loads(RD.EXAMPLE_PATH.read_text(encoding="utf-8"))
    d["status"] = "ACTIVE"
    d["delegation_id"] = "rtd-test-0001"
    d["operator"]["approved_at"] = "2026-10-21T17:00:00-04:00"
    for s in d["windows"]["slots"]:
        s["enabled"] = s["window_id"] == slot
    d["limits"]["max_attempts_per_capability"] = 2
    return d


class World:
    def __init__(self, tmp: Path, *, prs=None, slot="1800", now=NOW, attempts=6, arm=True) -> None:
        self.tmp = tmp
        self.repo = Repo(tmp)
        for n, files, *rest in prs if prs is not None else [(11, {"docs/a.md": "a\n"}), (12, {"docs/b.md": "b\n"})]:
            self.repo.pr(n, files)
        self.deps = {n: tuple(rest[0]) for n, _f, *rest in (prs or []) if rest}
        self.clock = Clock(now)
        self.state_dir = tmp / "state"
        self.state_dir.mkdir()
        self.state = RW.State(self.state_dir)
        self.key = tmp / "hostcfg" / "capability.key"
        self.key.parent.mkdir()
        self.key.write_bytes(os.urandom(48).hex().encode())
        os.chmod(self.key, 0o600)
        self.deleg = tmp / "hostcfg" / "delegation.json"
        self.deleg.write_text(json.dumps(delegation_body(slot)))
        self.ctl = RC.ReleaseControl(self.state_dir, clock=lambda: self.clock.t)
        if arm:
            self.ctl.arm(
                HOST_ACTOR,
                RC.HostCliProof("/dev/pts/9", os.getuid(), self.ctl.expected_phrase("arm")),
                policy_digest=RD.load(self.deleg).digest,
                reason="arm for test",
            )
        self.gh = FakeGitHub(self.repo)
        self.writer = FakeWriter(self.gh)
        self.host = FakeHost(tmp, self.repo, self.clock)
        self.host.main_ref = lambda: getattr(self.writer, "merged", "")
        self.events_path = self.state_dir / "train_events.jsonl"
        self.attempts = attempts
        self.calendar = MC.ReleaseTrainCalendar(tmp / "hostcfg" / "macro_calendar.json")

    def entries(self, numbers=None):
        return [
            T.QueueEntry(pr=n, head_sha=s, depends_on=self.deps.get(n, ()))
            for n, s in sorted(self.repo.heads.items())
            if numbers is None or n in numbers
        ]

    def controller(self, *, live=True, queue=None, classifier=None, env=None, **cfg) -> T.TrainController:
        config = T.TrainConfig(
            scratch_root=self.tmp / "scratch",
            regenerators=(("noop", [sys.executable, "-c", "pass"]),),
            test_attempts=self.attempts,
            poll_s=60,
            qualify_timeout_s=600,
            main_ci_timeout_s=600,
            **cfg,
        )
        tester = T.LocalTester(command=FAIL_CMD, base_env={"PATH": os.environ["PATH"]})
        return T.TrainController(
            host=self.host,
            state=self.state,
            github=self.gh,
            queue=queue or StaticQueue(self.entries()),
            classifier=classifier or AllowClassifier(),
            live=live,
            writer=self.writer if live else None,
            tester=tester,
            events=T.JsonlEventSink(self.events_path) if live else None,
            delegation_path=self.deleg,
            key_path=self.key,
            config=config,
            env=env if env is not None else {"PATH": os.environ["PATH"]},
            calendar=self.calendar,
        )

    def run(self, **kw):
        c = self.controller(**kw)
        code, rec = c.run()
        assert rec["event_errors"] == [], rec["event_errors"]
        return code, rec, c

    def events(self):
        if not self.events_path.exists():
            return []
        return [json.loads(x) for x in self.events_path.read_text().splitlines()]

    def ledger(self):
        return json.loads((self.state_dir / "capabilities.json").read_text())

    def deploys(self):
        return [c for c in self.host.calls if c[0] == "deploy"]


# ── happy path ────────────────────────────────────────────────────────────────────────────────────


def test_live_happy_path_releases_and_records_every_contract(tmp_path):
    w = World(tmp_path)
    code, rec, c = w.run()
    assert code == T.EXIT_OK and rec["outcome"] == T.RELEASED_VERIFIED, rec["steps"]
    # merged in dependency/PR order in the scratch worktree, then published to train/<id> only
    kinds = [x[0] for x in w.writer.calls]
    assert kinds == ["push", "open_pr", "merge"]
    assert w.writer.calls[0][1] == rec["train_id"] and T.TC.TRAIN_ID_RE.match(rec["train_id"])
    # promote through the deploy script, under the train campaign and the batch PR
    assert [d[1] for d in w.deploys()] == ["prepare", "promote"]
    assert w.deploys()[0][2] == f"release-train-{rec['train_id']}" and w.deploys()[0][3] == "9001"
    assert all(v["ok"] for v in rec["verification"].values())
    # every event row is a valid TrainEvent@v1; the outcome is a valid TrainOutcome@v1
    evs = w.events()
    assert evs and all(
        TC.validate_as(TC.TRAIN_EVENT, {k: v for k, v in e.items() if k not in ("seq", "recorded_at", "store")}) == []
        for e in evs
    )
    outcome = [e for e in evs if e["event_type"] == "outcome_recorded"][-1]
    assert outcome["payload"]["outcome"] == "RELEASED_VERIFIED" and outcome["state_after"] == "released"
    assert TC.validate_as(TC.TRAIN_OUTCOME, outcome["payload"]) == []
    frozen = [e for e in evs if e["event_type"] == "frozen"][0]
    assert TC.validate_as(TC.TRAIN_CANDIDATE, frozen["payload"]["train_candidate"]) == []
    assert {e["pr_number"] for e in evs if e["event_type"] == "released"} == {11, 12}
    assert [e["seq"] for e in evs] == list(range(1, len(evs) + 1))
    # capabilities: every intent SUCCEEDED, nothing uncertain
    ledger = w.ledger()
    assert {i["status"] for i in ledger["intents"].values()} == {"SUCCEEDED"}
    assert {i["action"] for i in ledger["intents"].values()} == {
        "push_train_ref",
        "open_batch_pr",
        "merge_batch_pr",
        "prepare_release",
        "promote_release",
    }
    # intents were journaled before effects
    jrn = [json.loads(x) for x in (w.state_dir / "train_intents.jsonl").read_text().splitlines()]
    order = [(r["kind"], r.get("action") or r.get("intent")) for r in jrn]
    assert order[0][0] == "intent" and order[1][0] == "effect"
    st = json.loads((w.state_dir / "trains" / rec["train_id"] / "state.json").read_text())
    assert st["outcome"]["outcome"] == "RELEASED_VERIFIED" and st["phase"] == "terminal"
    assert RC.ReleaseControl(w.state_dir).view().current_train_id is None
    assert (w.state_dir / "train_measurements.jsonl").exists()


def test_dry_run_writes_nothing_and_prints_every_step(tmp_path):
    w = World(tmp_path)
    before = sorted(p.name for p in w.state_dir.iterdir())
    c = w.controller(live=False)
    code, rec = c.run(NOW)
    assert code == T.EXIT_OK and rec["outcome"] == "DRY_RUN_COMPLETE", rec["steps"]
    assert sorted(p.name for p in w.state_dir.iterdir()) == before  # no claim, ledger, events, state
    text = "\n".join(rec["steps"])
    for needle in (
        "WOULD claim window",
        "WOULD merge --no-ff #11",
        "WOULD push",
        "WOULD open/update batch PR",
        "WOULD merge batch PR",
        "prepare",
        "WOULD re-check STOP + epoch at activation",
        "WOULD on failure: rollback",
    ):
        assert needle in text
    assert w.writer.calls == [] and w.host.calls == []
    assert all(
        TC.validate_as(TC.TRAIN_EVENT, {k: v for k, v in e.items() if k not in ("seq", "store")}) == []
        for e in rec["events"]
    )


def test_dry_run_of_an_unarmed_host_lists_what_live_would_refuse(tmp_path):
    w = World(tmp_path, arm=False)
    w.deleg.unlink()
    code, rec = w.controller(live=False).run(NOW)
    assert any("CONTROL_UNARMED" in x for x in rec["would_refuse"])
    assert any("delegation MISSING" in x for x in rec["would_refuse"])


def test_cli_live_is_refused_while_build_only(capsys):
    assert RW.main(["train-run", "--live"]) == T.EXIT_REFUSED
    assert "REFUSED_BUILD_ONLY" in capsys.readouterr().out


def test_real_github_writer_refuses_until_d2_and_policy_are_active():
    with pytest.raises(T.WriterNotArmed):
        T.GhCliWriter(RW.Host(), T.GhCliReader(RW.Host()))


def test_backward_compatible_manual_commands_unchanged(tmp_path, monkeypatch, capsys):
    real = RW.State
    monkeypatch.setattr(RW, "State", lambda: real(tmp_path / "rwstate"))
    assert RW.main(["status"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["latch_state"] == "ABSENT" and body["windows_et"] == ["1200", "1730"]


# ── windows, DST, calendar, rules ─────────────────────────────────────────────────────────────────


def test_window_identity_is_dst_safe():
    slots = [{"window_id": "1800", "duration_min": 90, "enabled": True}]
    w1, _ = T.window_at(datetime(2026, 10, 31, 18, 1, tzinfo=ET), slots, lead_min=90, grace_min=15)
    w2, _ = T.window_at(datetime(2026, 11, 1, 18, 1, tzinfo=ET), slots, lead_min=90, grace_min=15)
    assert w1.window_id == "2026-10-31T18:00-04:00" and w2.window_id == "2026-11-01T18:00-05:00"


def test_repeated_local_hour_cannot_activate_twice_and_missing_hour_is_skipped():
    slots = [{"window_id": "0130", "duration_min": 120, "enabled": True}]
    first = datetime(2026, 11, 1, 5, 35, tzinfo=timezone.utc)  # 01:35 EDT (first 01:35)
    second = datetime(2026, 11, 1, 6, 35, tzinfo=timezone.utc)  # 01:35 EST (repeated)
    w, phase = T.window_at(first, slots, lead_min=0, grace_min=15)
    assert w is not None and w.window_id == "2026-11-01T01:30-04:00" and phase == "open"
    w2, why = T.window_at(second, slots, lead_min=0, grace_min=15)
    assert w2 is None and why == "off_window"  # past the grace of the only 01:30
    assert T.local_start(date(2026, 3, 8), "0230") is None  # spring-forward gap: no such time


def test_repeated_hour_claim_key_is_per_day_and_slot(tmp_path):
    w = World(tmp_path)
    first = w.controller()
    code, rec = first.run()
    w.clock.t = NOW.timestamp() + 300  # same window, still inside the grace
    code2, rec2 = w.controller().run()
    assert rec2["reason"] == "REFUSED_WINDOW_ALREADY_CLAIMED" and code2 == T.EXIT_REFUSED


def test_no_catch_up_after_the_grace(tmp_path):
    w = World(tmp_path, now=datetime(2026, 10, 21, 18, 30, tzinfo=ET))
    code, rec, _ = w.run()
    assert rec["reason"] == "REFUSED_OFF_WINDOW" and w.writer.calls == []


def test_0600_needs_a_proven_drain(tmp_path):
    w = World(tmp_path, slot="0600", now=datetime(2026, 10, 22, 6, 2, tzinfo=ET))
    code, rec, _ = w.run()
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "WINDOW_SKIPPED_NO_DRAIN"
    out = [e for e in w.events() if e["event_type"] == "outcome_recorded"]
    assert out and out[0]["payload"]["outcome"] == "NO_OP" and out[0]["payload"]["members"] == []


def _cal(fetched, valid_through="2026-12-31", skip_days=()):
    """A MacroCalendar@v1 body (scripts/lib/macro_calendar.py), the one calendar the controller reads."""
    dates = {
        d: {
            "has_0830": True,
            "skip_0800": True,
            "events": [{"event": "CPI", "time_et": "08:30", "source": "fred", "release_id": 10, "skips_0800": True}],
        }
        for d in skip_days
    }
    return {
        "schema": "MacroCalendar@v1",
        "fetched_at": fetched,
        "covers_from": "2026-10-01",
        "valid_through": valid_through,
        "dates": dates,
    }


@pytest.mark.parametrize(
    "calendar,reason",
    [
        (None, "WINDOW_SKIPPED_MACRO_UNAVAILABLE"),
        (_cal("2026-10-01T08:00:00-04:00"), "WINDOW_SKIPPED_MACRO_STALE"),
        (_cal("2026-10-18T07:00:00-04:00"), "WINDOW_SKIPPED_MACRO_STALE"),  # 97 h: over 72 h (was fine at 168 h)
        (_cal("2026-10-21T08:00:00-04:00", valid_through="2026-10-21"), "WINDOW_SKIPPED_MACRO_STALE"),
        (_cal("2026-10-21T08:00:00-04:00", skip_days=("2026-10-22",)), "WINDOW_SKIPPED_MACRO_MACRO_DAY"),
        (_cal("2026-10-21T08:00:00-04:00"), "WINDOW_SKIPPED_UNMEASURED"),
    ],
)
def test_0800_macro_calendar_and_measured_latest_start(tmp_path, calendar, reason):
    w = World(tmp_path, slot="0800", now=datetime(2026, 10, 22, 8, 1, tzinfo=ET))
    if calendar is not None:
        (tmp_path / "hostcfg" / "macro_calendar.json").write_text(json.dumps(calendar))
    code, rec, _ = w.run()
    assert rec["outcome"] == "NO_OP" and rec["reason"] == reason, rec


def test_0800_latest_start_is_09_minus_measured_promote_verify_rollback_minus_buffer(tmp_path):
    m = T.Measurements(tmp_path / "m.jsonl")
    m.append({"promote_s": 300, "verify_s": 120, "rollback_s": 90})
    m.append({"promote_s": 240, "verify_s": 60, "rollback_s": 180})
    # Phase 7 (2026-10-22): three samples of each are required; the worst of each is used
    m.append({"promote_s": 200, "verify_s": 100, "rollback_s": 150})
    w = T.TrainWindow("0800", "last", datetime(2026, 10, 22, 8, 0, tzinfo=ET), 30, True, None, True)
    latest, why = T.latest_activation_start(w, m, buffer_min=10)
    assert latest == datetime(2026, 10, 22, 9, 0, tzinfo=ET) - timedelta(seconds=300 + 120 + 180, minutes=10)
    w2 = T.TrainWindow("0800", "last", w.start, 30, True, "08:10", True)
    assert T.latest_activation_start(w2, m, buffer_min=10)[0] == datetime(2026, 10, 22, 8, 10, tzinfo=ET)


def test_missing_calendar_fails_closed_and_the_controller_has_one_calendar_source(tmp_path, monkeypatch):
    v, why = MC.ReleaseTrainCalendar(tmp_path / "absent.json").verdict(date(2026, 10, 22), NOW)
    assert v == "UNAVAILABLE" and "calendar missing" in why and MC.LANE_ID in why
    assert not hasattr(T, "MacroCalendar") and not hasattr(T, "MACRO_CALENDAR_PATH")
    src = (ROOT / "scripts/lib/release_train_controller.py").read_text(encoding="utf-8")
    assert "168.0" not in src and '"macro_calendar.json"' not in src
    # the default: <state root>/data/runtime/macro_calendar.json, 72 h
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "ps"))
    c = T.TrainController(
        host=types.SimpleNamespace(checkout=tmp_path, python=sys.executable, now=lambda: NOW),
        state=RW.State(tmp_path / "s"),
        github=None,
        queue=None,
        classifier=None,
    )
    assert isinstance(c.calendar, MC.ReleaseTrainCalendar) and c.calendar.max_age_h == 72.0
    assert MC.default_path() == tmp_path / "ps" / "data" / "runtime" / "macro_calendar.json"


# ── competing trains and manual / emergency collisions ───────────────────────────────────────────


def test_competing_train_is_refused_while_one_holds_the_train_lock(tmp_path):
    w = World(tmp_path)
    lock = RC._Flock(w.state_dir / "train.lock", 0.0).acquire()
    try:
        code, rec, _ = w.run()
    finally:
        lock.release()
    assert rec["reason"] == "REFUSED_TRAIN_BUSY" and w.writer.calls == []


def test_manual_release_holding_the_global_lock_blocks_the_first_mutation_and_consumes_nothing(tmp_path):
    w = World(tmp_path)
    assert RC.GlobalReleaseLock(w.state_dir).path == w.state_dir / ".lock"  # release_window run's own lock
    lock = RC.GlobalReleaseLock(w.state_dir).acquire()
    try:
        code, rec, _ = w.run()
    finally:
        lock.release()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and "LOCK_BUSY" in rec["reason"]
    assert w.writer.calls == [] and w.deploys() == []
    # refused at issuance under the busy lock: no capability, no reservation, nothing consumed
    assert not (w.state_dir / "capabilities.json").exists()


@pytest.mark.parametrize(
    "name,value",
    [
        ("TRADEAI_EMERGENCY_RELEASE_SHA", "a" * 40),
        ("TRADEAI_RELEASE_TRAIN_SHA", "b" * 40),
        ("TRADEAI_CONFORMANCE_GATE_OVERRIDE", "x"),
    ],
)
def test_emergency_or_bypass_env_refuses_before_anything(tmp_path, name, value):
    w = World(tmp_path)
    code, rec, _ = w.run(env={"PATH": os.environ["PATH"], name: value})
    assert rec["reason"] == "REFUSED_BYPASS_ENV" and not (w.state_dir / "claims").exists()


def test_a_second_claimed_train_is_refused_by_control(tmp_path):
    w = World(tmp_path)
    w.ctl.claim_train(RC.Actor("controller", "other"), "rt-20261021-1800-other1")
    code, rec, _ = w.run()
    assert rec["reason"] == "REFUSED_TRAIN_ALREADY_CLAIMED"


# ── main / CURRENT / heads moving at each boundary ────────────────────────────────────────────────


def test_main_moves_between_select_and_freeze(tmp_path):
    w = World(tmp_path)

    def move(gh):
        if gh.reads == 2:
            gh.main = "9" * 40

    w.gh.on_main_read = move
    code, rec, _ = w.run()
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "MAIN_MOVED_AT_FREEZE"


def test_main_moves_before_publishing_the_train_ref(tmp_path):
    w = World(tmp_path)
    w.writer.hooks["push"] = None
    orig = w.gh.main_head

    def moved():
        if any(e["event_type"] == "integrating" for e in w.events()):
            w.gh.main = "9" * 40
        return orig()

    w.gh.main_head = moved
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and "WRONG_SHA" in rec["reason"], rec["reason"]
    assert w.writer.calls == []


def test_main_moves_before_the_merge(tmp_path):
    w = World(tmp_path)
    w.writer.hooks["open_pr"] = lambda: setattr(w.gh, "main", "9" * 40)
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and "WRONG_SHA" in rec["reason"]
    assert [c[0] for c in w.writer.calls] == ["push", "open_pr"]


def test_member_head_moves_before_the_merge(tmp_path):
    w = World(tmp_path)
    w.writer.hooks["open_pr"] = lambda: w.gh.heads.__setitem__(11, "7" * 40)
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and "PR_HEADS_CHANGED" in rec["reason"]


def test_main_moves_during_the_merge_latches_and_never_promotes(tmp_path):
    w = World(tmp_path)
    w.writer.main_after_merge = None

    def racing():
        m = w.writer.calls[-1]
        merged = hashlib.sha1(("merge" + m[2]).encode()).hexdigest()
        w.gh.parents[merged] = ["8" * 40, m[2]]  # someone else's commit got in first

    w.writer.hooks["merge"] = racing
    code, rec, _ = w.run()
    assert rec["outcome"] == "MERGED_NOT_LIVE" and rec["reason"] == "MAIN_MOVED_AT_MERGE"
    assert w.deploys() == [] and w.state.read_latch()[0] == "SET"


def test_main_moves_after_merge_before_promote(tmp_path):
    w = World(tmp_path)
    orig = w.host.checkout_sha

    def moved(sha):
        return orig(sha)

    w.writer.hooks["merge"] = lambda: None
    real_runs = w.gh.check_runs

    def runs(sha):
        if sha in w.gh.parents:  # main CI read on the merge commit
            w.gh.main = "6" * 40
        return real_runs(sha)

    w.gh.check_runs = runs
    code, rec, _ = w.run()
    assert rec["outcome"] == "MERGED_NOT_LIVE" and "WRONG_SHA" in rec["reason"], rec["reason"]
    assert [d[1] for d in w.deploys()] == []


def test_current_moves_before_activation(tmp_path):
    w = World(tmp_path)
    other = tmp_path / "releases" / "manual"
    other.mkdir()
    orig = w.host.run_deploy

    def deploy(args, env):
        out = orig(args, env)
        if args[0] == "prepare":
            w.host.cur = Path(os.path.realpath(other))  # a manual release landed meanwhile
        return out

    w.host.run_deploy = deploy
    code, rec, _ = w.run()
    assert rec["outcome"] == "MERGED_NOT_LIVE" and rec["reason"] == "CURRENT_MOVED"
    assert [d[1] for d in w.deploys()] == ["prepare"]


# ── capabilities ──────────────────────────────────────────────────────────────────────────────────


def test_missing_capability_key_refuses_the_first_mutation(tmp_path):
    w = World(tmp_path)
    w.key.rename(w.key.with_suffix(".archived"))
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and rec["reason"] == "CAPABILITY_KEY_MISSING"
    assert w.writer.calls == []


def test_wrong_capability_signature_is_refused(tmp_path, monkeypatch):
    w = World(tmp_path)
    c = w.controller()
    real = c.authority.issue_merge

    def forged(*a, **k):
        tok = real(*a, **k)
        p, b, _sig = tok.split(".")
        return f"{p}.{b}.{'0' * 64}"

    monkeypatch.setattr(c.authority, "issue_merge", forged)
    code, rec = c.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and rec["reason"] == "CAPABILITY_SIGNATURE_INVALID"
    assert [x[0] for x in w.writer.calls] == ["push", "open_pr"]


def test_revoked_delegation_mid_train_stops_before_merge(tmp_path):
    w = World(tmp_path)

    def revoke():
        d = json.loads(w.deleg.read_text())
        d["revocation_epoch"] = 2
        w.deleg.write_text(json.dumps(d))

    w.writer.hooks["open_pr"] = revoke
    code, rec, _ = w.run()
    assert rec["outcome"] in ("STOPPED", "FAILED_PRE_MERGE") and "POLICY" in rec["reason"], rec["reason"]
    assert "merge" not in [x[0] for x in w.writer.calls]


def test_revoked_control_refuses_a_live_run(tmp_path):
    w = World(tmp_path)
    w.ctl.revoke(
        HOST_ACTOR,
        RC.HostCliProof("/dev/pts/9", os.getuid(), w.ctl.expected_phrase("revoke")),
        reason="revoke for test",
    )
    code, rec, _ = w.run()
    assert rec["reason"] == "REFUSED_REVOKED" and w.writer.calls == []


def test_replayed_capability_is_refused(tmp_path):
    w = World(tmp_path)
    c = w.controller()
    tokens = []
    real = c.authority.issue_build

    def keep(*a, **k):
        tokens.append(real(*a, **k))
        return tokens[-1]

    c.authority.issue_build = keep
    code, rec = c.run()
    assert rec["outcome"] == "RELEASED_VERIFIED"
    w.ctl.claim_train(RC.Actor("controller", "replay"), rec["train_id"])
    with pytest.raises(CAP.CapabilityRefused) as e:
        c.authority.reserve(tokens[0], "push_train_ref", observed={})
    assert e.value.code in ("REPLAY", "CAPABILITY_EXPIRED", "BUDGET_EXHAUSTED")


def test_capability_promote_binds_batch_evidence_and_main_evidence(tmp_path):
    from tests.test_release_train_authority_20261021 import World as AW  # reuse the authority fixtures

    aw = AW(tmp_path)
    base, cand, merged = "a" * 40, "c" * 40, "e" * 40
    heads = [{"pr": 1901, "head_sha": "1" * 40}, {"pr": 1902, "head_sha": "2" * 40}]
    main_ev = {
        "sha": merged,
        "checks": [{"name": n, "head_sha": merged, "status": "completed", "conclusion": "success"} for n in CHECKS[:3]],
    }
    batch_ev = {
        "sha": cand,
        "checks": [{"name": n, "head_sha": cand, "status": "completed", "conclusion": "success"} for n in CHECKS],
    }
    kw = dict(
        expected_base_sha=base,
        pr_heads=heads,
        candidate_sha=merged,
        artifact_digest="sha256:" + "d" * 64,
        evidence=main_ev,
        rollback_target={"kind": "release", "sha": base, "release": "/r/prev"},
        services=["portfolio-server.service"],
        actions=["promote_release"],
    )
    with pytest.raises(CAP.CapabilityRefused) as e:  # ci-gate never runs on main
        aw.auth.issue_promote("train-20261021-1800", **kw)
    assert e.value.code == "EVIDENCE_NOT_QUALIFYING"
    tok = aw.auth.issue_promote("train-20261021-1800", batch_candidate_sha=cand, batch_evidence=batch_ev, **kw)
    body = CAP.decode(tok, CAP.load_key(aw.key))
    assert body["batch_candidate_sha"] == cand and body["batch_evidence_digest"].startswith("sha256:")
    bad = {**batch_ev, "checks": batch_ev["checks"][:3]}
    with pytest.raises(CAP.CapabilityRefused):
        aw.auth.issue_promote("train-20261021-1800", batch_candidate_sha=cand, batch_evidence=bad, **kw)


def test_capability_accepts_store_train_ids():
    assert CAP.TRAIN_RE.match("rt-20261021-1800-a1b2c3") and CAP.TRAIN_RE.match("train-20261021-1800")
    assert not CAP.TRAIN_RE.match("rt-20261021-1800") and not CAP.TRAIN_RE.match("rt-2026-1800-abcd")


# ── CI evidence ───────────────────────────────────────────────────────────────────────────────────


def test_evidence_counts_only_trusted_latest_runs_on_the_exact_sha():
    sha = "c" * 40
    runs = runs_for(sha) + [
        {
            "id": 1,
            "name": "ci-gate",
            "head_sha": "d" * 40,
            "status": "completed",
            "conclusion": "success",
            "app": "github-actions",
        },
        {
            "id": 999,
            "name": "ci-gate",
            "head_sha": sha,
            "status": "completed",
            "conclusion": "success",
            "app": "forger",
        },
    ]
    ev = T.check_evidence(runs, sha, now=0)
    assert T.evidence_verdict(ev)[0] == "GREEN"
    assert {i["why"] for i in ev["ignored"]} == {"other_sha", "untrusted_app"}
    forged_only = T.check_evidence([r for r in runs if r["name"] != "ci-gate"] + runs[-1:], sha, now=0)
    assert T.evidence_verdict(forged_only)[0] == "PENDING"


@pytest.mark.parametrize("conclusion", ["neutral", "skipped", "cancelled", "stale", "timed_out", "failure", None])
def test_any_non_success_mandatory_check_is_red(conclusion):
    sha = "c" * 40
    runs = runs_for(sha, names=CHECKS[:3]) + [
        {
            "id": 200,
            "name": "ci-gate",
            "head_sha": sha,
            "status": "completed",
            "conclusion": conclusion,
            "app": "github-actions",
        }
    ]
    assert T.evidence_verdict(T.check_evidence(runs, sha, now=0))[0] == "RED"


def test_a_rerun_supersedes_an_older_run():
    sha = "c" * 40
    runs = runs_for(sha) + [
        {
            "id": 500,
            "name": "ci-gate",
            "head_sha": sha,
            "status": "in_progress",
            "conclusion": None,
            "app": "github-actions",
        }
    ]
    assert T.evidence_verdict(T.check_evidence(runs, sha, now=0))[0] == "PENDING"


def test_forged_ci_evidence_never_qualifies_the_batch(tmp_path):
    w = World(tmp_path)
    w.gh.default_runs = False
    w.writer.hooks["push"] = lambda: w.gh.runs.__setitem__(
        w.writer.calls[0][2], runs_for(w.writer.calls[0][2], app="evil-app")
    )
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and rec["reason"] == "CI_TIMEOUT_BATCH"
    assert "merge" not in [x[0] for x in w.writer.calls]


def test_wrong_sha_ci_evidence_never_qualifies_the_batch(tmp_path):
    w = World(tmp_path)
    w.gh.default_runs = False
    w.writer.hooks["push"] = lambda: w.gh.runs.__setitem__(w.writer.calls[0][2], runs_for("d" * 40))
    code, rec, _ = w.run()
    assert rec["reason"] == "CI_TIMEOUT_BATCH"


@pytest.mark.parametrize("conclusion", ["neutral", "skipped"])
def test_skipped_or_neutral_mandatory_check_fails_the_batch(tmp_path, conclusion):
    w = World(tmp_path)

    def bad():
        sha = w.writer.calls[0][2]
        w.gh.runs[sha] = runs_for(sha, names=CHECKS[:3]) + runs_for(sha, conclusion, names=("ci-gate",), start_id=9)

    w.writer.hooks["push"] = bad
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and rec["reason"] == "CI_RED_BATCH"


def test_missing_mandatory_check_times_out(tmp_path):
    w = World(tmp_path)
    w.writer.hooks["push"] = lambda: w.gh.runs.__setitem__(
        w.writer.calls[0][2], runs_for(w.writer.calls[0][2], names=CHECKS[:3])
    )
    code, rec, _ = w.run()
    assert rec["reason"] == "CI_TIMEOUT_BATCH" and "ci-gate:missing" in rec["detail"]


def test_stale_evidence_is_re_read_immediately_before_the_merge(tmp_path):
    w = World(tmp_path)
    seen = {"n": 0}
    real = w.gh.check_runs

    def runs(sha):
        if sha == (w.writer.calls[0][2] if w.writer.calls else None):
            seen["n"] += 1
            if seen["n"] >= 2:  # a rerun started after qualification
                return runs_for(sha, names=CHECKS[:3]) + [
                    {
                        "id": 900,
                        "name": "ci-gate",
                        "head_sha": sha,
                        "status": "queued",
                        "conclusion": None,
                        "app": "github-actions",
                    }
                ]
        return real(sha)

    w.gh.check_runs = runs
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and rec["reason"] == "CI_TIMEOUT_BATCH_RECHECK"
    assert "merge" not in [x[0] for x in w.writer.calls]


# ── self-modification ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "scripts/release_window.py",
        "scripts/lib/release_capability.py",
        "scripts/lib/release_control.py",
        "scripts/cio_phase2_exact_main_deploy.sh",
        ".github/workflows/cio-production-hardening-ci.yml",
        "scripts/lib/release_train_controller.py",
        "AGENTS.md",
    ],
)
def test_a_pr_that_edits_the_verifier_never_rides(tmp_path, path):
    w = World(tmp_path, prs=[(11, {"docs/a.md": "a\n"}), (12, {path: "tampered\n"})])
    code, rec, _ = w.run()
    assert rec["outcome"] == "RELEASED_VERIFIED"
    assert rec["selection"]["excluded"]["12"] == "BLOCKED_SELF_MODIFICATION"
    assert rec["selection"]["members"] == [11]


def test_protected_surface_list_covers_the_named_verifiers():
    for p in (
        "scripts/release_window.py",
        "scripts/lib/release_capability.py",
        "scripts/lib/release_control.py",
        "scripts/cio_phase2_exact_main_deploy.sh",
        ".github/workflows/x.yml",
        ".githooks/pre-push",
        ".cursor/hooks/guard_ledger.py",
        "bin/guard",
    ):
        assert T.is_protected(p), p
    assert not T.is_protected("docs/ops/x.md") and not T.is_protected("scripts/api_v2.py")


def test_final_candidate_diff_is_checked_even_if_selection_missed_it(tmp_path, monkeypatch):
    w = World(tmp_path, prs=[(11, {".github/workflows/sneaky.yml": "x\n"})])
    c = w.controller()
    c.changeset = lambda e, base: {"paths": [{"path": "docs/innocent.md", "status": "M"}]}
    code, rec = c.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE"
    assert rec["reason"] in ("ALL_EJECTED", "CANDIDATE_TOUCHES_VERIFIER")
    assert w.writer.calls == []


# ── integration: conflicts, dependents, bisect ────────────────────────────────────────────────────


def test_conflict_ejects_the_pr_and_its_dependents(tmp_path):
    w = World(
        tmp_path,
        prs=[(21, {"app.txt": "A\nline2\n"}), (22, {"app.txt": "B\nline2\n"}), (23, {"docs/d.md": "d\n"}, (22,))],
    )
    code, rec, _ = w.run()
    assert rec["outcome"] == "RELEASED_VERIFIED"
    ej = rec["integration"]["ejected"]
    assert ej["22"].startswith("MERGE_CONFLICT") and ej["23"].startswith("DEPENDENCY_EJECTED")
    blocked = {e["pr_number"]: e["payload"] for e in w.events() if e["event_type"] == "blocked"}
    assert set(blocked) == {22, 23}
    assert w.writer.calls[0][0] == "push"


def test_bisect_attributes_the_failing_pr_and_releases_the_rest(tmp_path):
    w = World(tmp_path, prs=[(11, {"docs/a.md": "a\n"}), (12, {"FAIL_MARKER": "x\n"}), (13, {"docs/c.md": "c\n"})])
    code, rec, _ = w.run()
    assert rec["outcome"] == "RELEASED_VERIFIED", rec["steps"]
    labels = [a["label"] for a in rec["local_test"]["attempts"]]
    assert labels[0] == "full" and "without-culprit" in labels
    out = [e for e in w.events() if e["event_type"] == "outcome_recorded"][-1]["payload"]
    assert out["failure_attribution"]["attributed"] == [12]
    ev = [e for e in w.events() if e["event_type"] == "evidence_recorded" and e["payload"]["kind"] == "local_test"]
    assert {e["payload"]["conclusion"] for e in ev} == {"success", "failure"}


def test_budget_exhaustion_marks_uncertain_prs_pending_not_ejected(tmp_path):
    w = World(
        tmp_path, prs=[(11, {"docs/a.md": "a\n"}), (12, {"FAIL_MARKER": "x\n"}), (13, {"docs/c.md": "c\n"})], attempts=2
    )
    code, rec, _ = w.run()
    assert rec["outcome"] == "RELEASED_VERIFIED", rec["steps"]
    pend = {
        e["pr_number"]
        for e in w.events()
        if e["event_type"] == "ready" and e["payload"].get("step") == "pending_investigation"
    }
    assert pend == {12, 13}
    assert not any(e["event_type"] == "blocked" and e["pr_number"] in (12, 13) for e in w.events())
    assert [e["pr_number"] for e in w.events() if e["event_type"] == "released"] == [11]


def test_base_red_blames_nobody(tmp_path):
    w = World(tmp_path, prs=[(11, {"docs/a.md": "a\n"})])
    (w.repo.seed / "FAIL_MARKER").write_text("x")
    git(w.repo.seed, "checkout", "-q", "main")
    (w.repo.seed / "FAIL_MARKER").write_text("x")
    git(w.repo.seed, "add", "-A")
    git(w.repo.seed, "commit", "-q", "-m", "red base")
    git(w.repo.seed, "push", "-q", "origin", "main")
    new_base = git(w.repo.seed, "rev-parse", "HEAD")
    git(w.repo.checkout, "fetch", "-q", "origin")
    w.gh.main = new_base
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and rec["reason"] == "BASE_RED"
    assert not any(e["event_type"] == "blocked" for e in w.events())


# ── STOP ──────────────────────────────────────────────────────────────────────────────────────────


def test_stop_before_merge(tmp_path):
    w = World(tmp_path)
    w.writer.hooks["open_pr"] = lambda: RC.ReleaseControl(w.state_dir).request_stop(CC, "operator stop test")
    code, rec, _ = w.run()
    assert rec["outcome"] == "STOPPED" and rec["reason"] == "STOP_REQUESTED"
    assert "merge" not in [x[0] for x in w.writer.calls] and w.deploys() == []
    v = RC.ReleaseControl(w.state_dir).view()
    assert v.mode == RC.STOPPED and v.stop["acknowledged_at"] and v.stop["stopped_at"]


def test_stop_after_merge_before_activation_never_promotes(tmp_path):
    w = World(tmp_path)
    w.writer.hooks["merge"] = lambda: RC.ReleaseControl(w.state_dir).request_stop(CC, "operator stop test")
    code, rec, _ = w.run()
    assert rec["outcome"] == "MERGED_NOT_LIVE" and "STOP" in rec["reason"]
    assert [d[1] for d in w.deploys()] == []


def test_stop_during_promotion_finishes_verification_then_settles(tmp_path):
    w = World(tmp_path)
    w.host.hooks["promote"] = lambda: RC.ReleaseControl(w.state_dir).request_stop(CC, "operator stop test")
    code, rec, _ = w.run()
    assert rec["outcome"] == "RELEASED_VERIFIED"  # an activation that started is settled
    v = RC.ReleaseControl(w.state_dir).view()
    assert v.mode == RC.STOPPED and v.stop["acknowledged_at"]


def test_stop_latch_written_by_release_window_refuses(tmp_path):
    w = World(tmp_path)
    w.state.write(w.state.latch, {"latched_at": "x", "outcome": "ROLLED_BACK"})
    code, rec, _ = w.run()
    assert rec["reason"] == "REFUSED_STOP_LATCHED"


# ── corrupt state ─────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "target,body,reason",
    [
        ("control.json", "{not json", "REFUSED_CONTROL_CORRUPT"),
        (
            "control.json",
            '{"schema": "ReleaseControl@v1", "mode": "WHATEVER", "epoch": 1, "version": 1}',
            "REFUSED_CONTROL_CORRUPT",
        ),
        ("STOP.json", "garbage", "REFUSED_STOP_UNREADABLE"),
    ],
)
def test_corrupt_control_state_fails_closed(tmp_path, target, body, reason):
    w = World(tmp_path)
    (w.state_dir / target).write_text(body)
    code, rec, _ = w.run()
    assert rec["reason"] == reason and w.writer.calls == []


def test_corrupt_capability_ledger_fails_closed(tmp_path):
    w = World(tmp_path)
    (w.state_dir / "capabilities.json").write_text("{broken")
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and "STATE_CORRUPT" in rec["reason"]
    assert w.writer.calls == []


# ── restart with an ambiguous effect ──────────────────────────────────────────────────────────────


def _uncertain_merge(tmp_path):
    w = World(tmp_path)
    w.writer.merge_raises = TimeoutError("socket timed out after the request was sent")
    code, rec, _ = w.run()
    assert code == T.EXIT_UNCERTAIN and rec["outcome"] == "UNCERTAIN"
    return w, rec


def test_uncertain_merge_blocks_everything_until_reconciled(tmp_path):
    w, rec = _uncertain_merge(tmp_path)
    assert any(i["status"] == "UNCERTAIN" for i in w.ledger()["intents"].values())
    w.clock.t += 86400  # the next day's window
    code, rec2, _ = w.run()
    assert rec2["reason"] == "REFUSED_RECONCILE_FIRST"


def test_reconcile_effect_absent_closes_the_train_and_refunds(tmp_path):
    w, rec = _uncertain_merge(tmp_path)
    c = w.controller()
    code, out = T.Reconciler(c).run()
    assert code == T.EXIT_OK
    d = out["trains"][0]
    assert d["disposition"] == "RESOLVED" and d["intents"][0]["disposition"] == "EFFECT_ABSENT"
    assert not any(i["status"] in ("UNCERTAIN", "RESERVED") for i in w.ledger()["intents"].values())
    st = json.loads((w.state_dir / "trains" / rec["train_id"] / "state.json").read_text())
    assert st["outcome"]["outcome"] == "FAILED_PRE_MERGE"
    assert TC.validate_as(TC.TRAIN_OUTCOME, st["outcome"]) == []
    assert w.controller().pending_trains() == []


def test_reconcile_effect_applied_is_merged_not_live(tmp_path):
    w, rec = _uncertain_merge(tmp_path)
    cand = w.writer.calls[-1][2]
    w.gh.main = "5" * 40
    w.gh.contains_map[(cand, w.gh.main)] = True
    code, out = T.Reconciler(w.controller()).run()
    assert out["trains"][0]["outcome"] == "MERGED_NOT_LIVE"
    assert any(i["status"] == "RECONCILED_APPLIED" for i in w.ledger()["intents"].values())


def test_reconcile_ambiguous_latches_stop_and_keeps_the_train_open(tmp_path):
    w, rec = _uncertain_merge(tmp_path)
    w.gh.main = "4" * 40  # main moved; candidate not in it
    code, out = T.Reconciler(w.controller()).run()
    assert code == T.EXIT_UNCERTAIN and out["trains"][0]["disposition"] == "AMBIGUOUS"
    assert w.state.read_latch()[0] == "SET"
    assert w.controller().pending_trains() == [rec["train_id"]]


def test_reconcile_dry_run_writes_nothing(tmp_path):
    w, rec = _uncertain_merge(tmp_path)
    before = (w.state_dir / "capabilities.json").read_text()
    code, out = T.Reconciler(w.controller(live=False)).run()
    assert out["mode"] == "dry_run" and out["trains"][0]["intents"][0]["disposition"] == "EFFECT_ABSENT"
    assert (w.state_dir / "capabilities.json").read_text() == before


def test_unreadable_train_state_is_ambiguous(tmp_path):
    w, rec = _uncertain_merge(tmp_path)
    (w.state_dir / "trains" / rec["train_id"] / "state.json").write_text("{")
    code, out = T.Reconciler(w.controller()).run()
    assert code == T.EXIT_UNCERTAIN


# ── failed artifact ───────────────────────────────────────────────────────────────────────────────


def test_failed_verification_rolls_back_latches_quarantines_and_blocks_redeploy(tmp_path):
    w = World(tmp_path)
    w.host.health_when_new = 503
    code, rec, _ = w.run()
    assert rec["outcome"] == "ROLLED_BACK" and code == T.EXIT_ROLLED_BACK
    assert w.host.cur == Path(os.path.realpath(w.host.prev))
    assert [d[1] for d in w.deploys()] == ["prepare", "promote", "rollback"]
    assert w.state.read_latch()[0] == "SET"
    q = [json.loads(x) for x in (w.state_dir / "quarantine.jsonl").read_text().splitlines()]
    merged = rec["merge"]["main_sha"]
    assert q[0]["sha"] == merged and q[0]["artifact_digest"].startswith("sha256:")
    out = [e for e in w.events() if e["event_type"] == "outcome_recorded"][-1]["payload"]
    assert out["outcome"] == "ROLLED_BACK" and out["rollback_target"]
    assert w.host.notified and w.host.notified[0][0] == "P1"
    # the operator reviews and archives the latch; main still contains the failed merge
    w.state.latch.rename(w.state_dir / "STOP.reviewed.archived")
    w.gh.contains_map[(merged, w.gh.main)] = True
    w.clock.t += 86400
    code2, rec2, _ = w.run()
    assert rec2["reason"] == "REFUSED_QUARANTINED_LINEAGE"
    code3, body = T.resolve_quarantine(w.state, merged, "reverted on main by #9100", "main 1234abc", live=True)
    assert body["outcome"] == "RESOLVED"
    assert w.controller().quarantined() == []


def test_quarantined_artifact_is_never_promoted_again(tmp_path):
    w = World(tmp_path)
    c = w.controller()
    cand_merge = {}
    real = w.writer.merge_batch_pr

    def merge(pr, sha, msg):
        m = real(pr, sha, msg)
        cand_merge["m"] = m
        T.RC._append_jsonl(w.state_dir / "quarantine.jsonl", {"kind": "quarantine", "sha": m})
        return m

    w.writer.merge_batch_pr = merge
    code, rec = c.run()
    assert rec["outcome"] == "MERGED_NOT_LIVE" and rec["reason"] == "QUARANTINED_ARTIFACT"
    assert w.deploys() == []


# ── event store ───────────────────────────────────────────────────────────────────────────────────


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.conn.sql.append((sql, params))
        self.last = sql

    def fetchone(self):
        if "to_regclass" in self.last:
            return (self.conn.migrated, self.conn.migrated)
        if "INSERT INTO release_queue_events" in self.last:
            self.conn.seq += 1
            return (self.conn.seq,)
        return None

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, migrated):
        self.migrated, self.sql, self.seq = migrated, [], 0

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass


def test_store_sink_appends_through_append_event_when_migrated(tmp_path):
    conn = FakeConn(True)
    sink = T.StoreEventSink(lambda: conn, T.JsonlEventSink(tmp_path / "ev.jsonl"))
    (tmp_path / "w").mkdir()
    w = World(tmp_path / "w")
    c = w.controller()
    c.events = sink
    code, rec = c.run()
    assert rec["outcome"] == "RELEASED_VERIFIED" and rec["event_store"]["state"] == "OK"
    assert sum("INSERT INTO release_queue_events" in s for s, _ in conn.sql) > 10
    assert not (tmp_path / "ev.jsonl").exists()
    assert rec["event_store"]["projection_rows"] == 0


@pytest.mark.parametrize("factory", [lambda: FakeConn(False), lambda: (_ for _ in ()).throw(OSError("db down"))])
def test_store_sink_falls_back_to_jsonl_when_not_migrated_or_down(tmp_path, factory):
    sink = T.StoreEventSink(factory, T.JsonlEventSink(tmp_path / "ev.jsonl"))
    (tmp_path / "w").mkdir()
    w = World(tmp_path / "w")
    c = w.controller()
    c.events = sink
    code, rec = c.run()
    assert rec["event_store"]["state"] in ("NOT_MIGRATED", "DB_UNAVAILABLE")
    rows = [json.loads(x) for x in (tmp_path / "ev.jsonl").read_text().splitlines()]
    assert rows and rows[-1]["event_type"] == "outcome_recorded"


def test_jsonl_sink_refuses_an_invalid_event(tmp_path):
    with pytest.raises(T.InvalidTrainEvent):
        T.JsonlEventSink(tmp_path / "e.jsonl").append({"schema": "TrainEvent@v1", "event_type": "nonsense"})
    assert not (tmp_path / "e.jsonl").exists()


# ── queue sources and classifier ──────────────────────────────────────────────────────────────────


def test_real_phase1_classifier_is_used_and_blocks_its_own_controller():
    c = T.load_classifier(closure=False)
    assert isinstance(c, T.PolicyClassifier) and c.policy_version
    e = T.QueueEntry(pr=1, head_sha="a" * 40)
    risk, why = c.classify(e, {"paths": [{"path": "scripts/release_window.py", "status": "M"}]})
    assert risk in ("blocked", "needs_operator", "held")
    assert c.classify(e, None)[0] == "held"


def test_classifier_unavailable_holds_everything(monkeypatch):
    import scripts.lib as SL

    monkeypatch.setitem(sys.modules, "scripts.lib.release_train_classify", None)
    monkeypatch.delattr(SL, "release_train_classify", raising=False)
    c = T.load_classifier()
    assert isinstance(c, T.HoldAllClassifier)
    assert c.classify(T.QueueEntry(pr=1, head_sha="a" * 40), {"paths": [{"path": "docs/x.md"}]})[0] == "held"


def test_held_prs_never_ride(tmp_path):
    w = World(tmp_path)
    code, rec, _ = w.run(classifier=T.HoldAllClassifier("stub"))
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "NOTHING_ELIGIBLE" and w.writer.calls == []
    held = [e for e in w.events() if e["event_type"] == "held"]
    assert {e["pr_number"] for e in held} == {11, 12}


def test_incomplete_queue_selects_nothing(tmp_path):
    w = World(tmp_path)
    code, rec, _ = w.run(queue=StaticQueue(w.entries(), complete=False, reasons=["receipt_stale:x"]))
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "QUEUE_INCOMPLETE"


def test_fallback_queue_uses_receipt_source_only_when_store_absent():
    class Store:
        name = "phase1"

        def __init__(self, snap):
            self.snap = snap

        def snapshot(self):
            return self.snap

    fb = StaticQueue([T.QueueEntry(pr=5, head_sha="a" * 40)])
    absent = T.FallbackQueueSource(Store(T.QueueSnapshot("phase1", None, False, [], ["store:not_migrated"])), fb)
    assert [e.pr for e in absent.snapshot().entries] == [5]
    empty = T.FallbackQueueSource(Store(T.QueueSnapshot("phase1", "t", True, [], [])), fb)
    assert empty.snapshot().entries == []


def test_phase1_store_queue_source_reads_riding_rows(monkeypatch):
    rows = [
        {"pr_number": 7, "head_sha": "a" * 40, "state": "ready", "depends_on": [6], "risk_class": "eligible"},
        {"pr_number": 8, "head_sha": "b" * 40, "state": "held", "depends_on": [], "risk_class": "held"},
    ]
    monkeypatch.setattr(T.Q, "read_queue", lambda dbq, limit: {"store_state": "OK", "as_of": "t", "rows": rows})
    snap = T.Phase1StoreQueueSource(lambda: FakeConn(True)).snapshot()
    assert snap.complete and [e.pr for e in snap.entries] == [7] and snap.entries[0].depends_on == (6,)
    monkeypatch.setattr(T.Q, "read_queue", lambda dbq, limit: {"store_state": "NOT_MIGRATED", "reason": "not_migrated"})
    assert T.Phase1StoreQueueSource(lambda: FakeConn(False)).snapshot().reasons == ["store:not_migrated"]


def test_hygiene_receipt_source_fails_closed_and_parses_dependencies(tmp_path):
    receipt = tmp_path / "r.json"
    clock = lambda: NOW.timestamp()  # noqa: E731

    def runner(argv, **kw):
        out = json.dumps(
            [
                {
                    "number": 30,
                    "headRefOid": "a" * 40,
                    "baseRefName": "main",
                    "headRefName": "feat/a",
                    "title": "a",
                    "isDraft": False,
                    "labels": [],
                    "body": "Depends-on: #29, #28",
                    "files": [{"path": "docs/a.md"}],
                },
                {
                    "number": 31,
                    "headRefOid": "b" * 40,
                    "baseRefName": "feat/a",
                    "headRefName": "feat/b",
                    "title": "b",
                    "isDraft": False,
                    "labels": [],
                    "body": "",
                    "files": [],
                },
            ]
        )
        return types.SimpleNamespace(stdout=out, returncode=0)

    src = T.HygieneReceiptGhQueueSource(receipt=receipt, runner=runner, clock=clock)
    snap = src.snapshot()
    assert not snap.complete and snap.reasons[0].startswith("no_receipt")
    receipt.write_text(json.dumps({"summary": {"as_of": "2026-10-19T10:00:00+00:00", "prs": []}}))
    assert any(r.startswith("receipt_stale") for r in src.snapshot().reasons)
    receipt.write_text(
        json.dumps({"summary": {"as_of": "2026-10-21T21:00:00+00:00", "prs": [{"number": 30, "holds": []}]}})
    )
    snap = src.snapshot()
    assert snap.complete
    by = {e.pr: e for e in snap.entries}
    assert by[30].depends_on == (29, 28) and by[31].depends_on == (30,)


def test_dependency_order_and_missing_dependency():
    es = [
        T.QueueEntry(pr=3, head_sha="a" * 40, depends_on=(2,)),
        T.QueueEntry(pr=2, head_sha="b" * 40),
        T.QueueEntry(pr=4, head_sha="c" * 40, depends_on=(99,)),
        T.QueueEntry(pr=5, head_sha="d" * 40, depends_on=(6,)),
        T.QueueEntry(pr=6, head_sha="e" * 40, depends_on=(5,)),
    ]
    ordered, excl = T.order_members(es)
    assert [e.pr for e in ordered] == [2, 3]
    assert excl[4].startswith("DEPENDENCY_NOT_IN_TRAIN") and excl[5] == excl[6] == "DEPENDENCY_CYCLE"


# ── test worker isolation ─────────────────────────────────────────────────────────────────────────


def test_worker_env_is_built_from_an_allowlist(tmp_path):
    base = {
        "PATH": "/usr/bin",
        "DB_PASSWORD": "x",
        "GH_TOKEN": "x",
        "PGHOST": "db",
        "HOME": "/home/real",
        "TELEGRAM_BOT_TOKEN": "x",
        "OPENAI_API_KEY": "x",
        "LANG": "C.UTF-8",
    }
    env = T.worker_env(base, home=tmp_path / "h", tmp=tmp_path / "t")
    assert set(env) == {"PATH", "LANG", "HOME", "TMPDIR", *T.WORKER_ENV_FIXED}
    assert env["HOME"] == str(tmp_path / "h") and env["ENABLE_TELEGRAM"] == "0"


def test_local_test_worker_sees_no_credentials(tmp_path):
    seen = {}

    def runner(argv, *, cwd, env, timeout, preexec):
        seen.update(env)
        return 0, ""

    t = T.LocalTester(
        command=["true"], base_env={"PATH": "/usr/bin", "DB_PASSWORD": "s", "GITHUB_TOKEN": "s"}, runner=runner
    )
    assert t.run(tmp_path, "a" * 40, timeout=5, scratch=tmp_path, now=lambda: 0.0).ok
    assert "DB_PASSWORD" not in seen and "GITHUB_TOKEN" not in seen and seen["HOME"].startswith(str(tmp_path))


# ── n8n window requests (RELEASE_TRAIN_N8N_CONTRACT.md C1-C11) ──────────────────────────────────


def request(slot="1800", day="20261021", tick="on_window", shadow=True, **over):
    start = datetime(int(day[:4]), int(day[4:6]), int(day[6:]), int(slot[:2]), int(slot[2:]), tzinfo=ET)
    rid = f"rtw-{day}-{slot}-" + ("win" if tick == "on_window" else "f0a1b2c")
    body = {
        "schema": "TrainWindowRequest@v1",
        "request_id": rid,
        "window_slot": slot,
        "window_id": start.isoformat(timespec="minutes"),
        "window_start": start.isoformat(),
        "tick": tick,
        "shadow": shadow,
        "shadow_reason": "train_not_armed" if shadow else None,
        "requested_at": (start - timedelta(minutes=90)).isoformat(),
        "expires_at": (start + timedelta(minutes=15)).isoformat(),
        "requested_by": {
            "lane_id": f"release-train-request-{slot}",
            "run_id": "rtw:x:live:1",
            "attempt": 1,
            "run_mode": "live",
            "code_sha": None,
        },
        "readiness": {
            "stop_state": "ABSENT",
            "armed": False,
            "shadow_enabled": True,
            "delegation_state": "PAUSED",
            "window_enabled": False,
            "policy_version": None,
        },
        "authority": "REQUEST_ONLY",
        "note": "not authority",
    }
    body.update(over)
    return body


def put(w, body, name=None):
    d = w.state_dir / "train_requests" / "pending"
    d.mkdir(parents=True, exist_ok=True)
    p = d / (name or f"{body['request_id']}.json")
    p.write_text(json.dumps(body))
    return p


def claim(w, *, apply=True, status=None):
    def factory(live):
        return w.controller(live=live)

    return T.process_requests(w.state, factory, apply=apply, now=lambda: w.clock.t, live_status=status)


def receipt(w, rid):
    return json.loads((w.state_dir / "train_requests" / "receipts" / f"{rid}.json").read_text())


def test_shadow_request_is_simulate_only_and_completes(tmp_path):
    w = World(tmp_path, now=datetime(2026, 10, 21, 16, 35, tzinfo=ET))  # the W-90 request tick
    req = request()
    put(w, req)
    code, out = claim(w)
    r = receipt(w, req["request_id"])
    assert r["state"] == "COMPLETED" and r["mode"] == "simulate" and r["shadow"] is True
    assert r["outcome"] == "NO_OP" and "push_train_ref" in r["simulated_effects"]
    assert r["acknowledged_at"] and r["refusal"] is None and r["train_id"].startswith("rt-20261021-1800-")
    assert [m["pr"] for m in r["members"]] == [11, 12]
    assert not (w.state_dir / "claims").exists() and not (w.state_dir / "capabilities.json").exists()
    assert w.writer.calls == [] and w.host.calls == []
    assert (w.state_dir / "train_requests" / "claimed" / f"{req['request_id']}.json").exists()
    assert not (w.state_dir / "train_requests" / "pending" / f"{req['request_id']}.json").exists()


def test_off_window_shadow_request_is_evaluated_at_its_window(tmp_path):
    w = World(tmp_path, now=datetime(2026, 10, 21, 11, 0, tzinfo=ET))
    req = request(
        tick="off_window",
        requested_at=(datetime(2026, 10, 21, 10, 59, tzinfo=ET)).isoformat(),
        expires_at=(datetime(2026, 10, 21, 12, 0, tzinfo=ET)).isoformat(),
    )
    put(w, req)
    claim(w)
    r = receipt(w, req["request_id"])
    assert r["state"] == "COMPLETED" and r["mode"] == "simulate" and r["window_id"] == "2026-10-21T18:00-04:00"


def test_live_request_is_refused_while_build_only(tmp_path):
    w = World(tmp_path)
    req = request(shadow=False, shadow_reason=None)
    put(w, req)
    claim(w)
    r = receipt(w, req["request_id"])
    assert r["state"] == "REFUSED" and r["refusal"]["code"] == "CONTROLLER_BUILD_ONLY" and r["mode"] == "live"
    assert w.writer.calls == []


def test_live_request_when_active_re_validates_on_the_host(tmp_path):
    w = World(tmp_path)
    w.state.write(w.state.latch, {"latched_at": "x"})  # host STOP beats the request's view
    req = request(shadow=False, shadow_reason=None)
    put(w, req)
    claim(w, status="ACTIVE")
    r = receipt(w, req["request_id"])
    assert r["state"] == "REFUSED" and r["refusal"]["code"] == "STOP_SET"


@pytest.mark.parametrize(
    "mutate,needle",
    [
        (lambda b: b.update(candidate_sha="a" * 40), "unknown key"),
        (lambda b: b.update(train_id="rt-20261021-1800-abcd"), "unknown key"),
        (lambda b: b.update(window_slot="1200"), "window_slot"),
        (lambda b: b.update(authority="GRANT"), "authority"),
        (lambda b: b.update(tick="off_window"), "suffix"),
        (lambda b: b.update(window_id="2026-10-22T18:00-04:00"), "disagree"),
        (lambda b: b["requested_by"].update(lane_id="release-train-request-0000"), "lane_id"),
        (lambda b: b.pop("expires_at"), "missing"),
    ],
)
def test_invalid_requests_are_claimed_and_refused(tmp_path, mutate, needle):
    w = World(tmp_path)
    req = request()
    mutate(req)
    put(w, req, name="rtw-20261021-1800-win.json")
    claim(w)
    r = receipt(w, "rtw-20261021-1800-win")
    assert r["state"] == "REFUSED" and r["refusal"]["code"] == "INVALID_REQUEST" and needle in r["refusal"]["detail"]
    assert w.host.calls == [] and w.writer.calls == []


def test_off_window_request_claiming_live_is_invalid(tmp_path):
    w = World(tmp_path)
    req = request(tick="off_window", shadow=False)
    put(w, req)
    claim(w)
    assert receipt(w, req["request_id"])["refusal"]["code"] == "INVALID_REQUEST"


def test_wrong_file_name_and_garbage_are_refused(tmp_path):
    w = World(tmp_path)
    put(w, request(), name="rtw-20261021-1800-f000000.json")
    (w.state_dir / "train_requests" / "pending" / "junk.json").write_text("{nope")
    code, out = claim(w)
    assert receipt(w, "rtw-20261021-1800-f000000")["refusal"]["code"] == "INVALID_REQUEST"
    assert receipt(w, "junk")["refusal"]["code"] == "INVALID_REQUEST"


def test_expired_request_never_starts_a_train(tmp_path):
    w = World(tmp_path, now=datetime(2026, 10, 21, 18, 20, tzinfo=ET))
    req = request()
    put(w, req)
    claim(w)
    r = receipt(w, req["request_id"])
    assert r["state"] == "EXPIRED" and r["refusal"]["code"] == "EXPIRED" and w.host.calls == []


def test_duplicate_window_request_is_refused_and_terminal_receipts_are_never_rewritten(tmp_path):
    w = World(tmp_path, now=datetime(2026, 10, 21, 16, 35, tzinfo=ET))
    req = request()
    put(w, req)
    claim(w)
    first = receipt(w, req["request_id"])
    put(w, request(note="replayed"))
    code, out = claim(w)
    assert out["requests"][0]["result"].startswith(("REFUSED DUPLICATE_WINDOW", "NOT_CLAIMED"))
    assert receipt(w, req["request_id"]) == first


def test_claim_without_apply_lists_and_writes_nothing(tmp_path):
    w = World(tmp_path)
    req = request()
    p = put(w, req)
    code, out = claim(w, apply=False)
    assert out["mode"] == "dry_run" and "simulate" in out["requests"][0]["would"]
    assert p.exists() and not (w.state_dir / "train_requests" / "receipts").exists()


def test_requests_are_answered_in_requested_at_order(tmp_path):
    w = World(tmp_path, now=datetime(2026, 10, 21, 16, 35, tzinfo=ET))
    late = request(
        slot="0000", day="20261022", requested_at="2026-10-21T22:30:00-04:00", expires_at="2026-10-22T00:15:00-04:00"
    )
    early = request()
    put(w, late)
    put(w, early)
    code, out = claim(w)
    assert [r["request_id"] for r in out["requests"]] == [early["request_id"], late["request_id"]]


def test_a_busy_claimer_does_nothing(tmp_path):
    w = World(tmp_path)
    put(w, request())
    lock = RC._Flock(w.state_dir / "train_requests" / ".claimer.lock", 0.0).acquire()
    try:
        code, out = claim(w)
    finally:
        lock.release()
    assert out["outcome"] == "CLAIMER_BUSY"
    assert (w.state_dir / "train_requests" / "pending" / "rtw-20261021-1800-win.json").exists()


# ── alarm firing (release_window.Host.notify -> telegram_alert.send_telegram) ─────────────────────


def test_failed_window_alert_reaches_the_transport(tmp_path, monkeypatch):
    sent = []
    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = lambda msg, **kw: sent.append((msg, kw)) or True
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    runner = RW.Runner(RW.Host(checkout=tmp_path, releases=tmp_path, canonical=tmp_path), RW.State(tmp_path / "s"))
    w = RW.window_for(NOW, "1730")
    rec = {
        "outcome": "ROLLED_BACK",
        "candidate": {"sha": "c" * 40, "selected_by": "head_green"},
        "current": {"build_sha": "b" * 40},
        "finished_at": "2026-10-21T22:00:00Z",
        "stop_latched": {"x": 1},
    }
    runner._alert(w, rec)
    assert rec["notification"] == {"accepted": True, "priority": "P1"}
    assert len(sent) == 1 and "ROLLED_BACK" in sent[0][0]
    assert sent[0][1]["priority"] == "P1" and sent[0][1]["dedupe_minutes"] == 0
    assert rec["needs_action_item"]["severity"] == "P1"


# ── CANONICAL_SOURCE HEAD (2026-10-21, release-1 promote failure) ─────────────────────────────────


def test_stale_canonical_source_halts_before_any_prepare_or_capability(tmp_path):
    """The deploy script runs its release verifier from CANONICAL_SOURCE; a dev tree not at the merge commit is an
    older verifier. The controller refuses before issuing a prepare capability or calling the deploy script."""
    w = World(tmp_path)
    w.host.canonical_sha = "5" * 40  # dev tree left on an older main
    code, rec, _ = w.run()
    assert rec["outcome"] == "MERGED_NOT_LIVE" and rec["reason"] == "CANONICAL_SOURCE_HEAD_MISMATCH", rec["reason"]
    assert w.deploys() == []  # no prepare, no promote
    assert ("canonical_head",) in w.host.calls
    actions = {i["action"] for i in w.ledger()["intents"].values()}
    assert "prepare_release" not in actions and "promote_release" not in actions


def test_unreadable_canonical_source_halts_too(tmp_path):
    w = World(tmp_path)
    w.host.canonical_sha = ""  # Host.canonical_head: "" when unreadable
    code, rec, _ = w.run()
    assert rec["reason"] == "CANONICAL_SOURCE_HEAD_MISMATCH" and w.deploys() == []


def test_dry_run_names_the_canonical_source_check(tmp_path):
    w = World(tmp_path)
    code, rec = w.controller(live=False).run(NOW)
    assert any("CANONICAL_SOURCE HEAD" in s for s in rec["steps"])


def test_release_window_host_reads_canonical_head_from_git(tmp_path):
    repo = tmp_path / "canonical"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "c"], check=True, env=env)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert RW.Host(checkout=tmp_path, releases=tmp_path, canonical=repo).canonical_head() == head
    assert RW.Host(checkout=tmp_path, releases=tmp_path, canonical=tmp_path / "absent").canonical_head() == ""
