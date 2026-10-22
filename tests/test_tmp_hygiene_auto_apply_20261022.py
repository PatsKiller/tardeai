"""/tmp hygiene that actually deletes (operator 2026-10-22: "It needs to be able to delete it. Just looking at it
won't do anything.").

/tmp (tmpfs, 1,048,576 inodes) hit 99% inodes on 2026-10-22 while the n8n lane tmp-hygiene ran --plan only. Pins:
  * the new rules of scripts/tmp_hygiene.py: B (pytest --basetemp trees, layout markers, live pid), E (named
    ephemeral entries: type, size, markers, allowed content), G (top-level /tmp git trees: registered clean
    worktree removed with `git worktree remove`, dirty / unpushed / unregistered kept), and the future-dated
    fixture mtimes being ignored (no_real_mtime when nothing else is left);
  * the selection guards on every new rule: cwd inside, open fd inside, recent activity, never-touch globs
    (systemd-private-*, .X11-unix, tmux-*, ssh-*, snap-private-tmp, n8n-campaign-*, momentum-*, tradeai-*);
  * scripts/tmp_hygiene_auto.py: kill switch, standing approval, n8n executor refusal, /tmp-only root, dry run
    writes nothing, apply removes ONLY the selected items and writes the deletions ledger (path, bytes, files,
    age, rule), the run report and the LaneRunReceipt; the pressure trigger and the P2 / P1 inode alerts;
  * the committed config (approval provenance quoted verbatim), the systemd units, the registry rows;
  * the pipeline runner no longer leaks step locks or results temp files into /tmp.

Hermetic: a tmp dir stands in for /tmp, a fake /proc, fake statvfs, tmp git repos (GIT_CONFIG_GLOBAL=/dev/null),
tmp state roots, an injected notifier. No real /tmp entry is touched, nothing is sent.
"""

from __future__ import annotations

import json
import os
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

from scripts import disk_hygiene as DH  # noqa: E402
from scripts import tmp_hygiene as TH  # noqa: E402
from scripts import tmp_hygiene_auto as TA  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402
from tests.pipeline_runner_fixtures import runner_env, sandbox_runner  # noqa: E402

CONFIG = ROOT / "config"
UNITS = ROOT / "linux_launchers" / "systemd"
UID = os.getuid()
#: plans run 30 days after the fixtures are built
NOW = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(days=30)
QUOTE = "It needs to be able to delete it. Just looking at it won't do anything."


def _load(name: str) -> dict:
    return json.loads((CONFIG / name).read_text(encoding="utf-8"))


def sh(*args: str, cwd: Path | None = None) -> str:
    p = subprocess.run(list(args), cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return p.stdout


def at(p: Path, when: datetime) -> None:
    os.utime(p, (when.timestamp(), when.timestamp()), follow_symlinks=False)


@pytest.fixture(autouse=True)
def no_send(monkeypatch):
    calls: list = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("a Telegram chokepoint was called")

    fake = types.ModuleType("telegram_alert")
    fake.send_telegram = boom
    for name in ("telegram_alert", "scripts.telegram_alert"):
        monkeypatch.setitem(sys.modules, name, fake)
    yield
    assert calls == []


class World:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.root = tmp / "fake_tmp"
        self.root.mkdir()
        self.home = tmp / "home"
        self.home.mkdir()
        self.proc = tmp / "proc"
        self.proc.mkdir()
        self.state = tmp / "state"
        self.alert_state = tmp / "alert_state.json"
        self.rules_path = tmp / "rules.json"
        doc = _load("disk_hygiene_rules.json")
        doc["home"] = str(self.home)
        doc["git"]["roots"] = []
        doc["releases"]["roots"] = []
        doc["references"] = {"crontab_cmd": ["true"], "systemd_unit_dirs": [], "proc_root": str(self.proc)}
        doc["tmp"]["root"] = str(self.root)
        doc["tmp"]["claude_scratch"]["transcripts_dir"] = str(self.home / ".claude" / "projects")
        self.rules = doc
        self.write_rules()
        self.sent: list[tuple[str, str]] = []

    def write_rules(self) -> None:
        self.rules_path.write_text(json.dumps(self.rules, indent=1))

    def loaded(self) -> tuple[dict, dict]:
        rules = DH.load_rules(self.rules_path, home=self.home)
        return rules, TH.tmp_rules(rules)

    # fixtures ------------------------------------------------------------------------------------------------------
    def basetemp(self, parent: str = "cbd", pid: str = "2698529", n: int = 3) -> Path:
        d = self.root / parent / pid
        for i in range(n):
            (d / f"test_thing{i}").mkdir(parents=True)
            (d / f"test_thing{i}" / "f.json").write_text("{}")
        (d / "cio_traces0").mkdir()
        os.symlink(str(d / "cio_traces0"), d / "cio_tracescurrent")
        return d

    def lock(self, name: str = "pipeline_step_par_7318cc2b_y.lock") -> Path:
        p = self.root / name
        p.write_text("")
        return p

    def hermetic(self, name: str = "tradeai_hermetic_env_qj4xkq3p") -> Path:
        d = self.root / name
        (d / "home").mkdir(parents=True)
        (d / "env").write_text("")
        (d / "state_root").mkdir()
        (d / "home" / ".gitconfig").write_text("[user]\n\tname = hermetic-test\n")
        return d

    def fd(self, pid: int, n: int, target: Path) -> None:
        (self.proc / str(pid) / "fd").mkdir(parents=True, exist_ok=True)
        os.symlink(str(target), self.proc / str(pid) / "fd" / str(n))

    def cwd(self, pid: int, target: Path) -> None:
        (self.proc / str(pid)).mkdir(parents=True, exist_ok=True)
        os.symlink(str(target), self.proc / str(pid) / "cwd")

    # runs ----------------------------------------------------------------------------------------------------------
    def plan(self, now: datetime = NOW) -> dict:
        rules, t = self.loaded()
        return TH.plan(rules, t, now)

    def result(self, m: dict, path: Path) -> dict:
        for r in m["items"] + m["excluded"]:
            if r["path"] == str(path):
                return r
        for e in m["untouched"]["entries"]:
            if e["path"] == str(path):
                return {"path": e["path"], "reasons": [e["reason"]], "candidate": False, "untouched": True}
        raise KeyError(path)

    def reasons(self, m: dict, path: Path) -> set[str]:
        return {r.split(":", 1)[0] for r in self.result(m, path)["reasons"]}

    def auto(self, *, now: datetime = NOW, pressure_only: bool = False, dry_run: bool = False,
             allow_test_root: bool = True) -> int:
        rules, t = self.loaded()

        def notify(text: str, priority: str) -> str:
            self.sent.append((priority, text))
            return "accepted"

        return TA.run(rules=rules, t=t, now=now, state_root=self.state, pressure_only=pressure_only, dry_run=dry_run,
                      allow_test_root=allow_test_root, notify=notify, alert_state_path=self.alert_state)

    @property
    def mdir(self) -> Path:
        return self.state / "data" / "runtime" / "disk_hygiene"

    def report(self) -> dict:
        return json.loads((self.mdir / "tmp_hygiene_auto_apply_latest.json").read_text())

    def ledger_rows(self, now: datetime = NOW) -> list[dict]:
        p = self.mdir / f"tmp_hygiene_deletions_{now.strftime('%Y%m')}.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.fixture
def w(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k, v in (("GIT_AUTHOR_NAME", "t"), ("GIT_AUTHOR_EMAIL", "t@e"), ("GIT_COMMITTER_NAME", "t"),
                 ("GIT_COMMITTER_EMAIL", "t@e")):
        monkeypatch.setenv(k, v)
    for k in (DH.GRANT_ENV, DH.RUN_ID_ENV, "TRADEAI_STATE_ROOT", "TRADEAI_ALERT_STATE_PATH"):
        monkeypatch.delenv(k, raising=False)
    world = World(tmp_path)
    # a quiet filesystem by default: 40% inodes used
    monkeypatch.setattr(TH, "statvfs_inodes", lambda root: {"inodes_total": 1000, "inodes_used": 400,
                                                             "inodes_used_pct": 40.0})
    return world


def inode_pct(monkeypatch, *values: float) -> None:
    seq = list(values)

    def fake(root):
        v = seq.pop(0) if len(seq) > 1 else seq[0]
        return {"inodes_total": 1000, "inodes_used": int(v * 10), "inodes_used_pct": v}

    monkeypatch.setattr(TH, "statvfs_inodes", fake)


# ── 1. rule B: pytest --basetemp trees ────────────────────────────────────────────────────────────────────────────


def test_an_idle_basetemp_pid_dir_is_a_candidate_even_with_future_dated_fixture_files(w):
    d = w.basetemp()
    future = NOW + timedelta(days=29)
    at(d / "test_thing0" / "f.json", future)  # a fixture's future mtime is not activity
    m = w.plan()
    r = w.result(m, d)
    assert r["candidate"] is True and r["kind"] == TH.KIND_BASETEMP and r["rule"] == "B"
    assert r["evidence"]["future_mtime_entries"] == 1 and r["evidence"]["idle_days"] > 1
    assert r["file_count"] == 1 + 3 * 2 + 2  # pid dir, 3 test dirs + files, cio_traces0 + its current symlink


def test_basetemp_layout_markers_live_pid_cwd_fd_and_recent_activity_keep_it(w):
    odd = w.basetemp(pid="111")
    (odd / "notes.txt").write_text("not pytest")
    alive = w.basetemp(pid="222")
    (w.proc / "222").mkdir()
    (w.proc / "222" / "cmdline").write_bytes(b"python\0-m\0pytest\0")
    cwd = w.basetemp(pid="333")
    w.cwd(9001, cwd / "test_thing1")
    fd = w.basetemp(pid="444")
    w.fd(9002, 3, fd / "test_thing0" / "f.json")
    recent = w.basetemp(pid="555")
    at(recent / "test_thing2" / "f.json", NOW)
    m = w.plan()
    assert w.reasons(m, odd) == {"not_pytest_layout"}
    assert w.reasons(m, alive) == {"pid_alive"}
    assert w.reasons(m, cwd) == {"in_use_cwd"}
    assert w.reasons(m, fd) == {"open_fd"}
    assert w.reasons(m, recent) == {"recent_activity"}


def test_a_parent_with_anything_but_pid_dirs_is_not_a_basetemp_and_never_scanned(w):
    w.basetemp(parent="mixed", pid="123")
    (w.root / "mixed" / "README").write_text("x")
    (w.root / "empty-dir").mkdir()
    m = w.plan()
    assert w.reasons(m, w.root / "mixed") == {"no_tmp_rule"}
    assert w.reasons(m, w.root / "empty-dir") == {"no_tmp_rule"}
    assert m["items"] == []


def test_only_future_mtimes_is_never_idle(w):
    d = w.basetemp(n=1)
    future = NOW + timedelta(days=84)
    for p in sorted(d.rglob("*"), reverse=True):
        at(p, future)
    at(d, future)
    m = w.plan()
    assert "no_real_mtime" in w.reasons(m, d) and not w.result(m, d)["candidate"]


# ── 2. rule E: named ephemeral entries ────────────────────────────────────────────────────────────────────────────


def test_named_rules_select_idle_test_leaks_and_respect_size_markers_and_content(w):
    lock = w.lock()
    stage = w.lock("pipeline_par_a9068f51-s.lock")
    results = w.lock("pipeline_corrupt-s_results.e9uboB")
    (results).write_text("{}\n")
    big = w.lock("pipeline_step_worker_0a1b2c3d_lost.lock")
    big.write_text("not a lock")
    herm = w.hermetic()
    herm_odd = w.hermetic("tradeai_hermetic_env_zzzzzzzz")
    (herm_odd / "precious.db").write_text("x")
    herm_nomark = w.root / "tradeai_hermetic_env_nnnnnnnn"
    (herm_nomark / "home").mkdir(parents=True)
    unit = w.root / "n8nmat-unit-cxnpofav"
    unit.mkdir()
    (unit / "executor.service").write_text("[Unit]\n")
    live_lock = w.lock("pipeline_step_premarket_fetch.lock")  # a REAL pipeline's lock: no rule matches
    m = w.plan()
    for p, rid in ((lock, "pipeline_test_step_lock"), (stage, "pipeline_test_stage_lock"),
                   (results, "pipeline_results_tmp"), (herm, "hermetic_env"), (unit, "n8nmat_unit")):
        r = w.result(m, p)
        assert r["candidate"] is True and r["rule"] == f"E:{rid}" and r["rule_id"] == rid, (p, r["reasons"])
        assert r["creator"]
    assert w.reasons(m, big) == {"unexpected_size"}
    assert w.reasons(m, herm_odd) == {"unexpected_content"}
    assert w.reasons(m, herm_nomark) == {"marker_missing"}
    assert w.reasons(m, live_lock) == {"no_tmp_rule"}


def test_named_entries_in_use_or_recent_are_kept(w):
    held = w.lock("pipeline_step_par_11111111_a0.lock")
    w.fd(7001, 4, held)
    cwd = w.hermetic("tradeai_hermetic_env_cwdcwdcw")
    w.cwd(7002, cwd / "home")
    fresh = w.lock("pipeline_step_par_22222222_a1.lock")
    at(fresh, NOW - timedelta(hours=3))
    m = w.plan()
    assert w.reasons(m, held) == {"open_fd"}
    assert w.reasons(m, cwd) == {"in_use_cwd"}
    assert w.reasons(m, fresh) == {"recent_activity"}


def test_never_touch_globs_win_over_every_rule(w):
    names = ["systemd-private-abc-chronyd.service-x", ".X11-unix", "tmux-1000", "ssh-XXXXabc", "snap-private-tmp",
             "n8n-campaign-20261018", "momentum-native-abc", "tradeai-reassess-rxarvbxn"]
    for n in names:
        # each shaped like a basetemp, so only the glob keeps it out
        (w.root / n / "4242" / "test_x0").mkdir(parents=True)
    m = w.plan()
    for n in names:
        r = w.result(m, w.root / n)
        assert r.get("untouched") and r["reasons"][0].startswith("never_touch_glob"), n
    assert m["items"] == []
    # tradeai-* (hyphen) is a never-touch glob; it does not match the hermetic env's underscore name
    import fnmatch

    assert not fnmatch.fnmatch("tradeai_hermetic_env_qj4xkq3p", "tradeai-*")


# ── 3. rule G: top-level git trees ────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def repo(w):
    bare = w.tmp / "origin.git"
    sh("git", "init", "-q", "--bare", "-b", "main", str(bare))
    main = w.tmp / "mainrepo"
    sh("git", "init", "-q", "-b", "main", str(main))
    (main / "a.txt").write_text("a")
    sh("git", "add", "a.txt", cwd=main)
    sh("git", "commit", "-q", "-m", "a", cwd=main)
    sh("git", "remote", "add", "origin", str(bare), cwd=main)
    sh("git", "push", "-q", "origin", "main", cwd=main)
    return main


def _age_tree(p: Path, when: datetime) -> None:
    for x in sorted(p.rglob("*"), reverse=True):
        at(x, when)
    at(p, when)


def test_a_clean_idle_review_worktree_is_removed_with_git_worktree_remove(w, repo, monkeypatch):
    wt = w.root / "ready-three-preview"
    sh("git", "worktree", "add", "-q", "-b", "review-x", str(wt), cwd=repo)
    _age_tree(wt, NOW - timedelta(days=3))
    dirty = w.root / "pr1887-requalify-8fd"
    sh("git", "worktree", "add", "-q", "-b", "review-y", str(dirty), cwd=repo)
    (dirty / "untracked.txt").write_text("work in progress")
    _age_tree(dirty, NOW - timedelta(days=3))
    m = w.plan()
    r = w.result(m, wt)
    assert r["candidate"] is True and r["kind"] == TH.KIND_GIT and r["git_trees"][0]["registered"] is True
    assert "git_tree_dirty" in w.reasons(m, dirty)
    assert w.auto() == 0
    assert not wt.exists() and dirty.exists() and (dirty / "untracked.txt").exists()
    assert "review-x" in sh("git", "branch", "--list", "review-x", cwd=repo)  # the branch stays in the main repo
    assert str(wt) not in sh("git", "worktree", "list", cwd=repo)
    row = [x for x in w.ledger_rows() if x["path"] == str(wt)][0]
    assert row["rule"] == "G" and row["how"].startswith("git worktree remove")


def test_clones_with_unpushed_work_or_linked_worktrees_and_unregistered_worktrees_are_kept(w, repo):
    clone = w.root / "ready-three-pr1887"
    sh("git", "clone", "-q", str(w.tmp / "origin.git"), str(clone))
    (clone / "b.txt").write_text("b")
    sh("git", "add", "b.txt", cwd=clone)
    sh("git", "commit", "-q", "-m", "local only", cwd=clone)
    _age_tree(clone, NOW - timedelta(days=5))
    host = w.root / "candidate-release-blockers"
    sh("git", "clone", "-q", str(w.tmp / "origin.git"), str(host))
    linked = w.tmp / "elsewhere-wt"
    sh("git", "worktree", "add", "-q", "-b", "side", str(linked), cwd=host)
    _age_tree(host, NOW - timedelta(days=5))
    orphan = w.root / "stale-pid-test-update"
    sh("git", "worktree", "add", "-q", "-b", "orphan", str(orphan), cwd=repo)
    sh("rm", "-rf", str(repo / ".git" / "worktrees" / "stale-pid-test-update"))
    _age_tree(orphan, NOW - timedelta(days=5))
    m = w.plan()
    assert "git_unpushed_commits" in w.reasons(m, clone)
    assert "clone_has_linked_worktrees" in w.reasons(m, host)
    assert w.reasons(m, orphan) == {"git_worktree_unregistered"}


# ── 4. tmp_hygiene_auto: authority, scope, dry run, apply ─────────────────────────────────────────────────────────


def _mixed(w: World) -> tuple[list[Path], list[Path]]:
    """(selected, kept) fixtures in one fake /tmp."""
    sel = [w.basetemp(), w.lock(), w.hermetic()]
    kept_lock = w.lock("pipeline_step_par_33333333_b0.lock")
    w.fd(8001, 3, kept_lock)
    camp = w.root / "n8n-campaign-x"
    (camp / "1234" / "test_a0").mkdir(parents=True)
    loose = w.root / "some-random-dir"
    loose.mkdir()
    recent = w.lock("pipeline_step_par_44444444_x.lock")
    at(recent, NOW)
    return sel, [kept_lock, camp, loose, recent]


def test_auto_apply_removes_only_the_selected_items_and_writes_ledger_report_and_receipt(w):
    sel, kept = _mixed(w)
    assert w.auto() == 0
    for p in sel:
        assert not os.path.lexists(p), p
    for p in kept:
        assert os.path.lexists(p), p
    rows = w.ledger_rows()
    assert {r["path"] for r in rows} == {str(p) for p in sel}
    for r in rows:
        assert r["schema"] == "TmpHygieneDeletion@v1" and r["approval"] == "operator-20261022-tmp-hygiene-delete"
        assert set(r) >= {"path", "bytes", "files", "age_days", "rule", "how"} and r["age_days"] > 1
        assert r["files"] >= 1
    rep = w.report()
    assert rep["removed_count"] == 3 and rep["authority"]["quote"] == QUOTE and rep["trigger"] == "hourly"
    assert Path(rep["manifest"]).exists() and json.loads(Path(rep["manifest"]).read_text())["authority"]
    rec = json.loads((w.state / "data/runtime/tmp-hygiene-apply_last.json").read_text())
    assert rec["status"] == "ok" and rec["summary"]["removed_count"] == 3 and rec["produced_count"] == 1
    assert w.sent == []  # 40% inodes: no alert


def test_auto_dry_run_writes_and_deletes_nothing(w, capsys):
    sel, kept = _mixed(w)
    assert w.auto(dry_run=True) == 0
    out = capsys.readouterr().out
    assert '"would_remove": 3' in out and "CANDIDATES 3" in out
    assert all(os.path.lexists(p) for p in sel + kept) and not w.state.exists()


def test_kill_switch_approval_executor_and_root_refusals(w, monkeypatch):
    sel, _ = _mixed(w)
    w.rules["tmp"]["auto_apply"]["enabled"] = False
    w.write_rules()
    assert w.auto() == 0 and all(p.exists() or p.is_symlink() for p in sel) and not w.state.exists()
    w.rules["tmp"]["auto_apply"]["enabled"] = True
    w.rules["tmp"]["auto_apply"]["standing_approval"]["quote"] = ""
    w.write_rules()
    with pytest.raises(TA.Refused, match="standing_approval_incomplete"):
        w.auto()
    w.rules = json.loads(w.rules_path.read_text())
    w.rules["tmp"]["auto_apply"]["standing_approval"]["quote"] = QUOTE
    w.write_rules()
    monkeypatch.setenv(DH.RUN_ID_ENV, "d:tmp-hygiene:live:x")
    with pytest.raises(TA.Refused, match="n8n_executor_never_applies"):
        w.auto()
    monkeypatch.delenv(DH.RUN_ID_ENV)
    with pytest.raises(TA.Refused, match="tmp_root_must_be"):
        w.auto(allow_test_root=False)
    assert all(os.path.lexists(p) for p in sel)
    # the CLI maps a refusal to exit 1
    monkeypatch.setenv(DH.RUN_ID_ENV, "d:x")
    assert TA.main(["--rules", str(w.rules_path), "--state-root", str(w.state), "--home", str(w.home),
                    "--now", NOW.isoformat(), "--allow-test-root"]) == 1


def test_apply_revalidates_an_item_that_changed_after_the_plan(w, monkeypatch):
    lock = w.lock()
    real_apply = TH.apply

    def touch_then_apply(*a, **k):
        at(lock, NOW)  # activity between the plan and the delete
        return real_apply(*a, **k)

    monkeypatch.setattr(TH, "apply", touch_then_apply)
    assert w.auto() == 0
    assert lock.exists()
    assert w.report()["skipped"][0]["why"].startswith("rule_now_fails")


# ── 5. pressure trigger and alerts ────────────────────────────────────────────────────────────────────────────────


def test_pressure_mode_acts_only_above_the_trigger_and_not_twice_within_the_interval(w, monkeypatch):
    lock = w.lock()
    inode_pct(monkeypatch, 60.0)
    assert w.auto(pressure_only=True) == 0 and lock.exists()
    rec = json.loads((w.state / "data/runtime/tmp-hygiene-pressure_last.json").read_text())
    assert rec["summary"]["acted"] is False and rec["summary"]["why"] == "below_trigger"
    inode_pct(monkeypatch, 86.0, 80.0)
    assert w.auto(pressure_only=True) == 0 and not lock.exists()
    assert w.report()["trigger"] == "pressure"
    assert json.loads((w.state / "data/runtime/tmp-hygiene-pressure_last.json").read_text())["summary"]["acted"]
    lock2 = w.lock("pipeline_step_par_55555555_x.lock")
    inode_pct(monkeypatch, 88.0)
    assert w.auto(pressure_only=True, now=NOW + timedelta(minutes=5)) == 0 and lock2.exists()
    rec = json.loads((w.state / "data/runtime/tmp-hygiene-pressure_last.json").read_text())
    assert rec["summary"]["why"] == "auto_run_recent"
    assert w.auto(pressure_only=True, now=NOW + timedelta(minutes=20)) == 0 and not lock2.exists()


def test_inode_alerts_p2_at_90_p1_at_97_once_per_band_and_recovery(w, monkeypatch):
    w.lock()
    inode_pct(monkeypatch, 99.0, 97.5)
    assert w.auto() == 0
    assert [p for p, _ in w.sent] == ["P1"] and "97.5% used" in w.sent[0][1] and "removed 1 items" in w.sent[0][1]
    inode_pct(monkeypatch, 97.6)
    w.auto(now=NOW + timedelta(hours=1))
    assert len(w.sent) == 1  # same band, inside the re-alert window: silent
    inode_pct(monkeypatch, 92.0)
    w.auto(now=NOW + timedelta(hours=2))
    assert [p for p, _ in w.sent] == ["P1", "P2"]
    inode_pct(monkeypatch, 50.0)
    w.auto(now=NOW + timedelta(hours=3))
    assert w.sent[-1][0] == "P2" and "recovered" in w.sent[-1][1] and len(w.sent) == 3


def test_threshold_order_is_enforced(w):
    w.rules["tmp"]["auto_apply"]["alert_p2_pct"] = 80.0  # below the 85% trigger
    w.write_rules()
    with pytest.raises(DH.RulesError):
        w.auto()


# ── 6. committed config, units, registry ──────────────────────────────────────────────────────────────────────────


def test_committed_rules_record_the_operator_approval_and_the_new_rules():
    t = _load("disk_hygiene_rules.json")["tmp"]
    aa = t["auto_apply"]
    ap = aa["standing_approval"]
    assert aa["enabled"] is True and ap["quote"] == QUOTE and ap["date"] == "2026-10-22"
    assert (aa["pressure_trigger_pct"], aa["alert_p2_pct"], aa["alert_p1_pct"]) == (85.0, 90.0, 97.0)
    for g in ("systemd-private-*", ".X11-unix", "tmux-*", "ssh-*", "snap-private-tmp", "n8n-campaign-*", "momentum-*",
              "tradeai-*"):
        assert g in t["never_touch_globs"], g
    assert t["root"] == "/tmp" and TH.REQUIRED_TMP_ROOT == "/tmp"
    assert t["pytest_basetemp"]["idle_days"] >= 1 and t["git_trees"]["idle_days"] >= 1
    for r in t["named"]["rules"]:
        assert r["idle_days"] >= 1 and r["creator"] and r["regex"].startswith("^") and r["regex"].endswith("$")
    rules = DH.load_rules(CONFIG / "disk_hygiene_rules.json")
    tr = TH.tmp_rules(rules, uid=1000, user="johnclaw")
    assert {r["id"] for r in tr["_named"]} >= {"pipeline_test_step_lock", "pipeline_test_stage_lock",
                                              "pipeline_results_tmp", "hermetic_env", "n8nmat_unit"}
    assert TA.auto_cfg(tr)["enabled"] is True and TA.approval_id(tr["auto_apply"])


def test_units_run_the_auto_script_and_the_n8n_allowlist_never_does():
    svc = (UNITS / "tradeai-tmp-hygiene-apply.service").read_text()
    psvc = (UNITS / "tradeai-tmp-hygiene-pressure.service").read_text()
    assert "scripts/tmp_hygiene_auto.py" in svc and "--pressure-only" not in svc
    assert "scripts/tmp_hygiene_auto.py --pressure-only" in psvc
    assert "OnCalendar=*-*-* *:20:00" in (UNITS / "tradeai-tmp-hygiene-apply.timer").read_text()
    assert "*:00/5" in (UNITS / "tradeai-tmp-hygiene-pressure.timer").read_text()
    allow = json.dumps(_load("n8n_run_allowlist.json")["lanes"])
    assert "tmp_hygiene_auto" not in allow
    e = {x["lane_id"]: x for x in _load("n8n_run_allowlist.json")["lanes"]}["tmp-hygiene"]
    assert e["live_arg"] == ["--plan"]


def test_registry_rows_are_valid_host_lanes_staged_until_the_operator_installs_them():
    rows = {r["lane_id"]: r for r in _load("lane_registry.json")["lanes"]}
    for lane, unit in (("tmp-hygiene-apply", "tradeai-tmp-hygiene-apply.timer"),
                       ("tmp-hygiene-pressure", "tradeai-tmp-hygiene-pressure.timer")):
        r = rows[lane]
        assert LR.validate_row(r) == [], lane
        assert r["scheduler"]["kind"] == "systemd" and r["scheduler"]["expression"] == unit
        assert r["state"] == "NEVER_SCHEDULED" and QUOTE in r["state_reason"]
        assert r["output_signal"]["path"] == f"data/runtime/{lane}_last.json"
    assert rows["tmp-hygiene-apply"]["expected_cadence_hours"] == 1.0


def test_auto_script_is_host_only():
    src = (ROOT / "scripts" / "tmp_hygiene.py").read_text()
    assert "telegram_alert" not in src and "send_telegram" not in src  # the n8n lane's module stays sender-free


# ── 7. the pipeline runner cleans up after itself ─────────────────────────────────────────────────────────────────

RUNNER = ROOT / "scripts" / "pipelines" / "run_after_close_pipeline.sh"
sys.path.insert(0, str(ROOT / "scripts" / "pipelines"))
import pipeline_manifest as pm  # noqa: E402


def _runner(tmp: Path, name: str, args: tuple[str, ...], env_extra: dict | None = None):
    env = runner_env(tmp)
    env.update(env_extra or {})
    man = tmp / f"{name}.json"
    man.write_text(json.dumps({"schema": pm.MANIFEST_SCHEMA, "pipeline": name, "stages": {"s": {"steps": [
        {"id": "only", "cron_line": 1, "timeout": "5s", "command": "true"}]}}}))
    runner = sandbox_runner(tmp, RUNNER)
    return subprocess.run(["bash", str(runner), "--manifest", str(man), "--project-root", str(tmp), "--stage", "s",
                           *args], cwd=str(tmp), env=env, capture_output=True, text=True, timeout=120), env


def test_runner_step_lock_lives_in_pipeline_lock_dir_not_tmp(tmp_path):
    name = f"leak_{os.urandom(4).hex()}"
    r, env = _runner(tmp_path, name, ("--apply",))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (Path(env["PIPELINE_LOCK_DIR"]) / f"pipeline_step_{name}_only.lock").exists()
    assert not os.path.lexists(f"/tmp/pipeline_step_{name}_only.lock")
    assert list(Path(env["TMPDIR"]).iterdir()) == []  # the results temp file is gone


def test_runner_removes_its_results_temp_file_on_an_early_return(tmp_path):
    (tmp_path / ".env").write_text("ALPACA_MODE=live\n")  # safety refusal: returns before any step
    r, env = _runner(tmp_path, "safety_early", ("--dry-run",))
    assert r.returncode == 2 and "SAFETY-FAIL" in r.stdout + r.stderr
    assert list(Path(env["TMPDIR"]).iterdir()) == []
    lockdir = Path(env["PIPELINE_LOCK_DIR"])
    held = lockdir / "pipeline_held-s.lock"
    import fcntl

    with open(held, "w") as fh:  # lock busy: another early return
        fcntl.flock(fh, fcntl.LOCK_EX)
        (tmp_path / ".env").write_text("")
        r, env = _runner(tmp_path, "held", ("--apply",))
        assert r.returncode == 0 and "already running" in r.stdout + r.stderr
    assert list(Path(env["TMPDIR"]).iterdir()) == []
