"""Release Train v2 Phase 5 — shadow for real (ANCHOR RELEASE_TRAIN_SHADOW_P5_20261023; DSN-20261021-release-train-P5-T1).

Measured on the host 2026-10-23 before this change: the claimer ran every minute and answered nothing (no request was
ever written); a forced shadow tick then selected nothing because the migrated queue store is readable and EMPTY (no
submitter exists) and the census was never consulted; the shadow claimer built no candidate (TrainConfig defaults)
and kept no report; the receipt's 20-row needs_action dropped every LIVE_WOULD_REFUSE row once ~50 PRs were open.

This file pins the fix and the Phase 5 injected-failure list (plan "Phases 5-7", enhanced design §10):

* shadow reads the open-PR census (ShadowQueueSource); the live source is unchanged;
* a shadow request integrates the frozen members in an isolated per-slot scratch worktree (policy ``shadow``), writes
  a ShadowTrainReport@v1 named in the receipt, and never pushes, merges, promotes, claims, issues or writes control /
  latch / store / release state;
* shadow rehearses past a 06:00 / 08:00 window rule a live train would skip, and says so; a live train still skips;
* STOP during each phase halts shadow and live at that boundary; a corrupt latch (bad JSON, empty, directory, dangling
  link) fails closed everywhere; stale CI evidence and wrong-SHA evidence never qualify; a request that names a SHA is
  invalid; a PR head that moves is never integrated;
* ``release_window.py train-shadow-tick``: dry run writes nothing; apply appends through the request lane's code and
  waits for the claimer's terminal receipt.

Hermetic: the controller test world under tmp_path (temp git repos, fake GitHub, fake deploy host, temp control
state). No network, DB, systemd, broker, or live server. psycopg2 is stubbed by the imported controller test module.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tests.test_release_train_controller_20261021 import (  # noqa: E402
    CC,
    CHECKS,
    NOW,
    StaticQueue,
    World,
    put,
    receipt,
    request,
    runs_for,
)
from scripts import release_window as RW  # noqa: E402
from scripts.lib import release_control as RC  # noqa: E402
from scripts.lib import release_train_controller as T  # noqa: E402
from scripts.lib import release_train_window as W  # noqa: E402
from scripts.lib import release_train_window_view as WV  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
SHADOW_ON = {"integrate": True, "local_test": False, "past_window_rules": True}


@pytest.fixture(autouse=True)
def _hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state-root"))
    monkeypatch.setenv("TRADEAI_RELEASE_WINDOW_STATE_DIR", str(tmp_path / "rw"))
    (tmp_path / "rw").mkdir(exist_ok=True)


def _snap(w):
    """The state dir before the claimer runs: names and bytes of every file (control state included)."""
    return {p.name: (p.read_bytes() if p.is_file() else None) for p in w.state_dir.iterdir()}


def _claim(w, *, pol=SHADOW_ON, **kw):
    w.before = getattr(w, "before", None) or _snap(w)
    return T.process_requests(w.state, lambda live: w.controller(live=live, **kw), apply=True,
                              now=lambda: w.clock.t, shadow_pol=pol)


def _nothing_written(w):
    """Shadow wrote nothing outside the request spool (and the scratch worktree): every other file in the state dir
    is byte-identical to before the claimer ran, and nothing new appeared (no claims, capabilities, trains, events)."""
    after = {k: v for k, v in _snap(w).items() if k != "train_requests"}
    assert after == {k: v for k, v in w.before.items() if k != "train_requests"}, sorted(after)
    assert not w.state.latch.exists()
    assert w.writer.calls == [] and [c for c in w.host.calls if c[0] in ("deploy", "checkout")] == []
    origin_refs = subprocess.run(["git", "-C", str(w.repo.origin), "for-each-ref", "--format=%(refname)"],
                                 capture_output=True, text=True).stdout.split()
    assert not [r for r in origin_refs if r.startswith("refs/heads/train/")]


# ── the census is the shadow queue ─────────────────────────────────────────────────────────────────────


def _entry(pr, sha="a" * 40, **census):
    return T.QueueEntry(pr=pr, head_sha=sha, census=dict(census))


def test_shadow_queue_reads_the_census_when_the_store_is_readable_and_empty():
    q = T.ShadowQueueSource(StaticQueue([]), StaticQueue([_entry(11), _entry(12)]))
    snap = q.snapshot()
    assert snap.complete and [e.pr for e in snap.entries] == [11, 12]
    assert "store ok, 0 riding" in snap.source
    # the live default is unchanged: a readable empty store stays a real empty
    live = T.FallbackQueueSource(StaticQueue([]), StaticQueue([_entry(11)]))
    assert live.snapshot().entries == []
    assert isinstance(T.default_queue_source(), T.FallbackQueueSource)
    assert isinstance(T.default_queue_source(shadow=True), T.ShadowQueueSource)


def test_shadow_queue_annotates_store_rows_and_never_adds_a_closed_pr():
    store = StaticQueue([_entry(12, queue_state="ready"), _entry(99, queue_state="ready")])
    snap = T.ShadowQueueSource(store, StaticQueue([_entry(11), _entry(12)])).snapshot()
    assert [e.pr for e in snap.entries] == [11, 12]
    assert snap.entries[1].census["store"] == {"queue_state": "ready"}
    assert "1 store rows not open in the census (never ride): [99]" in snap.source


@pytest.mark.parametrize("reason", ["no_receipt:/x", "receipt_stale:2026-10-01", "gh_pr_list_failed:OSError"])
def test_an_incomplete_census_selects_nothing(tmp_path, reason):
    q = T.ShadowQueueSource(StaticQueue([]), StaticQueue([_entry(11)], complete=False, reasons=[reason]))
    assert not q.snapshot().complete
    w = World(tmp_path)
    code, rec = w.controller(live=False, queue=q).run(NOW)
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "QUEUE_INCOMPLETE" and reason in rec["detail"]


def test_build_controller_gives_dry_runs_the_shadow_queue(tmp_path):
    w = World(tmp_path)
    c = T.build_controller(live=False, host=w.host, state=w.state)
    assert isinstance(c.queue, T.ShadowQueueSource) and not c.live


def test_a_head_the_census_saw_fail_never_rides(tmp_path):
    w = World(tmp_path)
    heads = w.repo.heads
    fail = {"status": "FAIL", "failed": ["ci-gate"], "head": heads[11]}
    stale_fail = {"status": "FAIL", "failed": ["ci-gate"], "head": "e" * 40}  # recorded for an older head
    q = StaticQueue([T.QueueEntry(pr=11, head_sha=heads[11], census={"required_checks": fail}),
                     T.QueueEntry(pr=12, head_sha=heads[12], census={"required_checks": stale_fail})])
    code, rec = w.controller(live=False, queue=q).run(NOW)
    assert rec["selection"]["excluded"] == {"11": "CHECKS_FAILING:ci-gate"}
    assert rec["selection"]["members"] == [12]


# ── the policy and the claimer: a real candidate, a durable report, nothing mutated ─────────────────


def test_policy_shadow_block_is_on_in_the_repo_and_fails_closed():
    assert T.shadow_policy() == SHADOW_ON
    pol = json.loads((ROOT / "config/release_train_policy.json").read_text())
    assert pol["armed"] is False and all(x["enabled"] is False for x in pol["windows"])


@pytest.mark.parametrize("body", ["{broken", json.dumps({"schema": "x"}),
                                  json.dumps({"shadow": {"integrate": "true", "past_window_rules": 1}})])
def test_shadow_policy_anything_but_true_is_off(tmp_path, body):
    p = tmp_path / "policy.json"
    p.write_text(body)
    assert T.shadow_policy(p) == {"integrate": False, "local_test": False, "past_window_rules": False}


def test_apply_shadow_policy_sets_a_per_slot_scratch():
    cfg = T.apply_shadow_policy(T.TrainConfig(), "0600", SHADOW_ON)
    assert cfg.dry_run_integrate and not cfg.dry_run_local_test and cfg.shadow_past_window_rules
    assert cfg.scratch_key == "shadow-0600"
    off = T.apply_shadow_policy(T.TrainConfig(), "1800", {})
    assert not off.dry_run_integrate and not off.shadow_past_window_rules


def test_shadow_request_builds_a_real_candidate_and_writes_a_report(tmp_path):
    w = World(tmp_path)
    req = request()
    put(w, req)
    code, out = _claim(w)
    r = receipt(w, req["request_id"])
    assert WV.validate_receipt(r) == [], WV.validate_receipt(r)
    assert (r["state"], r["mode"], r["outcome"]) == ("COMPLETED", "simulate", "NO_OP")
    assert [m["pr"] for m in r["members"]] == [11, 12]
    cand = r["candidate_sha"]
    assert cand and len(cand) == 40
    wt = tmp_path / "scratch" / "shadow-1800" / "wt"
    parents = subprocess.run(["git", "-C", str(wt), "log", "--format=%P", "-1", cand], capture_output=True,
                             text=True).stdout.split()
    assert w.repo.heads[12] in parents  # the merge of #12 onto the candidate built from #11
    rid = req["request_id"]
    assert r["evidence_refs"] == [f"report:train_requests/reports/{rid}.json"]
    rep = json.loads((w.state_dir / "train_requests" / "reports" / f"{rid}.json").read_text())
    assert rep["schema"] == "ShadowTrainReport@v1" and rep["authority"] == "SHADOW_SIMULATE_ONLY"
    assert rep["integration"]["candidate_sha"] == cand and rep["integration"]["simulated"] is False
    assert rep["manifest"]["members"][0]["pr"] == 11 and rep["shadow_config"]["scratch_key"] == "shadow-1800"
    assert rep["reason"] in ("DRY_RUN_COMPLETE", None) or rep["outcome"] == "NO_OP"
    assert "push_train_ref" in r["simulated_effects"] and "merge_batch_pr" in r["simulated_effects"]
    _nothing_written(w)
    # the view reads the report for the Releases page
    cov = {c["slot"]: c for c in WV.shadow_coverage(w.state_dir)}["1800"]
    assert cov["has_report"] and cov["riding"] == 2 and cov["candidate_sha"] == cand and cov["outcome"] == "NO_OP"


def test_a_second_tick_reuses_the_slot_scratch_and_never_rewrites_a_report(tmp_path):
    w = World(tmp_path)
    first = request()
    put(w, first)
    _claim(w)
    second = request(tick="off_window")
    put(w, second)
    _claim(w)
    assert receipt(w, second["request_id"])["state"] == "COMPLETED"
    wts = subprocess.run(["git", "-C", str(w.repo.checkout), "worktree", "list", "--porcelain"], capture_output=True,
                         text=True).stdout
    assert wts.count("shadow-1800") == 1
    spool = T.RequestSpool(w.state_dir)
    assert spool.write_report(first["request_id"], {"schema": "x"}) is None  # written once, never rewritten
    assert spool.report(first["request_id"])["schema"] == "ShadowTrainReport@v1"


def test_without_the_policy_the_claimer_keeps_the_simulated_integration(tmp_path):
    w = World(tmp_path)
    req = request()
    put(w, req)
    _claim(w, pol=None)
    r = receipt(w, req["request_id"])
    assert r["state"] == "COMPLETED" and r["candidate_sha"] is None
    assert not (tmp_path / "scratch").exists()
    rep = json.loads((w.state_dir / "train_requests" / "reports" / f"{req['request_id']}.json").read_text())
    assert rep["integration"] is None and rep["shadow_config"]["integrate"] is False
    assert any("WOULD merge --no-ff #11" in x for x in rep["steps"])


def test_live_would_refuse_rows_survive_a_long_not_riding_list():
    rec = {"selection": {"excluded": {str(n): "held:x" for n in range(100, 140)}},
           "would_refuse": ["control CONTROL_UNARMED", "delegation PAUSED", "window 1800 is disabled"],
           "would_halt": None}
    doc = T._receipt(request(), state="COMPLETED", mode="simulate", now=NOW.timestamp(), acknowledged_at="x",
                     rec=rec, outcome="NO_OP")
    codes = [n["code"] for n in doc["needs_action"]]
    assert len(codes) == 20 and codes[:3] == ["LIVE_WOULD_REFUSE"] * 3 and codes[3:] == ["NOT_RIDING"] * 17


# ── window rules: shadow rehearses past a skip; live never does ─────────────────────────────────────


def test_0600_without_a_drain_shadow_runs_on_and_says_live_would_skip(tmp_path):
    at = datetime(2026, 10, 22, 6, 5, tzinfo=ET)
    w = World(tmp_path, slot="0600", now=at)
    req = request(slot="0600", day="20261022")
    put(w, req)
    _claim(w)
    r = receipt(w, req["request_id"])
    assert r["state"] == "COMPLETED" and [m["pr"] for m in r["members"]] == [11, 12]
    texts = [n["text"] for n in r["needs_action"] if n["code"] == "LIVE_WOULD_REFUSE"]
    assert any("live would skip (WINDOW_SKIPPED_NO_DRAIN" in t for t in texts), texts
    rep = json.loads((w.state_dir / "train_requests" / "reports" / f"{req['request_id']}.json").read_text())
    assert rep["window_rules"]["window_rules_live_would_skip"]["reason"] == "WINDOW_SKIPPED_NO_DRAIN"
    _nothing_written(w)


def test_0800_shadow_records_every_rule_a_live_train_would_skip(tmp_path):
    at = datetime(2026, 10, 22, 8, 1, tzinfo=ET)
    w = World(tmp_path, slot="0800", now=at)  # no macro calendar, no measured durations
    code, rec = w.controller(live=False, shadow_past_window_rules=True).run(at)
    reasons = [x["reason"] for x in rec["window_rules_live_would_skip_all"]]
    assert reasons == ["WINDOW_SKIPPED_MACRO_UNAVAILABLE", "WINDOW_SKIPPED_UNMEASURED"], reasons
    assert rec["selection"]["members"] == [11, 12]  # rehearsed on
    live_code, live_rec, _ = w.run()
    assert live_rec["reason"] == "WINDOW_SKIPPED_MACRO_UNAVAILABLE"  # live: the first skip ends the run


def test_a_live_controller_ignores_the_shadow_flag_and_still_skips(tmp_path):
    at = datetime(2026, 10, 22, 6, 5, tzinfo=ET)
    w = World(tmp_path, slot="0600", now=at)
    code, rec, _ = w.run(shadow_past_window_rules=True)
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "WINDOW_SKIPPED_NO_DRAIN"
    assert w.writer.calls == [] and w.deploys() == []


# ── STOP during each phase ───────────────────────────────────────────────────────────────────────────


def _stop_at(c, w, label):
    real = c._boundary
    seen = []

    def boundary(lbl, **kw):
        seen.append(lbl)
        if lbl == label and not getattr(boundary, "fired", False):
            boundary.fired = True
            RC.ReleaseControl(w.state_dir).request_stop(CC, f"phase 5 drill: STOP at {label}")
        return real(lbl, **kw)

    c._boundary = boundary
    return seen


SHADOW_BOUNDARIES = ("select", "qualify", "merge", "promote")


@pytest.mark.parametrize("label", SHADOW_BOUNDARIES)
def test_stop_during_each_phase_halts_shadow_there(tmp_path, label):
    w = World(tmp_path)
    c = w.controller(live=False, dry_run_integrate=True, scratch_key="shadow-1800")
    seen = _stop_at(c, w, label)
    code, rec = c.run(NOW)
    assert label in seen
    assert rec["outcome"] == "STOPPED" and rec["reason"] == "STOP_REQUESTED", rec["steps"][-3:]
    assert rec["would_halt"]["at"] == label
    steps = "\n".join(rec["steps"])
    after = {"select": "WOULD push", "qualify": "WOULD merge batch PR", "merge": "WOULD merge batch PR",
             "promote": "WOULD re-check STOP + epoch at activation"}[label]
    if label != "merge":
        assert after not in steps
    # simulated halt: the STOP request is the only control write; shadow never acknowledges or settles it
    assert RC.ReleaseControl(w.state_dir).view().mode == RC.STOP_REQUESTED
    assert w.writer.calls == [] and w.deploys() == [] and not (w.state_dir / "capabilities.json").exists()


LIVE_BOUNDARIES = ("select", "wait_checks_batch", "qualify", "merge", "promote", "wait_checks_main", "activation")


@pytest.mark.parametrize("label", LIVE_BOUNDARIES)
def test_stop_during_each_phase_halts_live_there(tmp_path, label):
    w = World(tmp_path)
    c = w.controller(live=True)
    seen = _stop_at(c, w, label)
    code, rec = c.run()
    assert label in seen
    merged_before = label in ("promote", "wait_checks_main", "activation")
    assert rec["outcome"] == ("MERGED_NOT_LIVE" if merged_before else "STOPPED"), (label, rec["outcome"])
    kinds = [x[0] for x in w.writer.calls]
    assert ("merge" in kinds) is merged_before
    assert "promote" not in [d[1] for d in w.deploys()]
    v = RC.ReleaseControl(w.state_dir).view()
    assert v.mode == RC.STOPPED and v.stop["acknowledged_at"] and v.stop["stopped_at"]


# ── a corrupt latch fails closed ─────────────────────────────────────────────────────────────────────


def _corrupt(w, kind):
    latch = w.state.latch
    if kind == "bad_json":
        latch.write_text("{corrupt")
    elif kind == "empty":
        latch.write_text("")
    elif kind == "directory":
        latch.mkdir()
    elif kind == "dangling_link":
        latch.symlink_to(w.state_dir / "does-not-exist.json")


CORRUPT = ("bad_json", "empty", "directory", "dangling_link")


@pytest.mark.parametrize("kind", CORRUPT)
def test_corrupt_latch_refuses_the_shadow_request(tmp_path, kind):
    w = World(tmp_path)
    _corrupt(w, kind)
    assert w.state.read_latch()[0] == "UNREADABLE"
    req = request()
    put(w, req)
    _claim(w)
    r = receipt(w, req["request_id"])
    assert r["state"] == "REFUSED" and r["refusal"]["code"] == "STOP_UNREADABLE", r
    assert r["members"] == [] and r["candidate_sha"] is None
    assert not (tmp_path / "scratch").exists()


@pytest.mark.parametrize("kind", CORRUPT)
def test_corrupt_latch_refuses_live_and_the_request_lane(tmp_path, kind):
    w = World(tmp_path)
    _corrupt(w, kind)
    code, rec, _ = w.run()
    assert rec["reason"] == "REFUSED_STOP_UNREADABLE" and w.writer.calls == []
    d = W.decide({"stop_state": W.host_snapshot(NOW, "1800", W.load_config(), stop_dir=w.state_dir,
                                                delegation_loader=lambda: ("PAUSED", "test"))["stop_state"],
                  "armed": False, "shadow_enabled": True, "delegation_state": "PAUSED", "window_enabled": False},
                 "off_window", shadow_only=True)
    assert d["disposition"] == "no_op" and d["no_op_reason"] == "stop_unreadable"
    # the Command Center's STOP reader agrees (a dangling link used to read ABSENT there and in the request lane)
    from scripts.lib import release_train_view as RTV  # noqa: PLC0415
    assert RTV.read_latch_file(w.state.latch)[0] == "UNREADABLE"
    assert WV.read_latch(w.state_dir) == "UNREADABLE"


# ── stale CI evidence and wrong SHAs ─────────────────────────────────────────────────────────────────


def test_an_old_green_run_superseded_by_a_rerun_in_flight_is_not_green():
    sha = "c" * 40
    runs = runs_for(sha) + [{"id": 900, "name": "ci-gate", "head_sha": sha, "status": "in_progress",
                             "conclusion": None, "app": "github-actions"}]
    verdict, why = T.evidence_verdict(T.check_evidence(runs, sha, now=0))
    assert verdict == "PENDING" and why == ["ci-gate:in_progress"]


def test_green_member_heads_never_qualify_the_candidate(tmp_path):
    w = World(tmp_path)
    w.gh.default_runs = False
    for sha in w.repo.heads.values():  # every PR head green; the integrated candidate has no runs
        w.gh.runs[sha] = runs_for(sha)
    code, rec, _ = w.run()
    assert rec["reason"] == "CI_TIMEOUT_BATCH" and "merge" not in [x[0] for x in w.writer.calls]


def test_evidence_turning_red_after_qualification_stops_the_merge(tmp_path):
    w = World(tmp_path)
    reads = {"n": 0}
    real = w.gh.check_runs

    def runs(sha):
        if w.writer.calls and sha == w.writer.calls[0][2]:
            reads["n"] += 1
            if reads["n"] >= 2:   # the re-read immediately before the merge sees a failed rerun
                return runs_for(sha) + runs_for(sha, "failure", names=("ci-gate",), start_id=500)
        return real(sha)

    w.gh.check_runs = runs
    code, rec, _ = w.run()
    assert rec["outcome"] == "FAILED_PRE_MERGE" and "merge" not in [x[0] for x in w.writer.calls]


@pytest.mark.parametrize("extra", [{"candidate_sha": "a" * 40}, {"head_sha": "b" * 40}, {"pr": 11}])
def test_a_request_that_names_a_sha_or_pr_is_invalid(tmp_path, extra):
    w = World(tmp_path)
    req = request(**extra)
    put(w, req)
    _claim(w)
    r = receipt(w, req["request_id"])
    assert r["state"] == "REFUSED" and r["refusal"]["code"] == "INVALID_REQUEST"
    assert not (w.state_dir / "train_requests" / "reports").exists()


def test_a_pr_head_that_moved_after_select_is_never_integrated(tmp_path):
    w = World(tmp_path)
    w.gh.heads[12] = "f" * 40  # GitHub now reports a different head than the census row
    code, rec = w.controller(live=False, dry_run_integrate=True).run(NOW)
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "PR_HEAD_MOVED_AT_FREEZE"
    assert "integration" not in rec


def test_a_fetched_head_that_differs_from_the_frozen_one_is_ejected(tmp_path):
    w = World(tmp_path)
    q = StaticQueue([T.QueueEntry(pr=11, head_sha="9" * 40), T.QueueEntry(pr=12, head_sha=w.repo.heads[12])])
    w.gh.heads[11] = "9" * 40
    code, rec = w.controller(live=False, dry_run_integrate=True, queue=q).run(NOW)
    assert rec["integration"]["ejected"]["11"].startswith("HEAD_MOVED_OR_UNFETCHABLE")
    assert rec["integration"]["kept"] == [12]


# ── train-shadow-tick: the forced tick ───────────────────────────────────────────────────────────────


def test_shadow_tick_dry_run_writes_nothing(tmp_path):
    state = RW.State(tmp_path / "rw")
    code, out = T.shadow_tick(list(T.SHADOW_TICK_ORDER), apply=False, inject=None, wait_s=0, state=state)
    assert code == T.EXIT_OK, out
    assert [r["slot"] for r in out["windows"]] == ["1800", "0000", "0600", "0800"]
    assert all(r["result"].startswith("WOULD_REQUEST") for r in out["windows"])
    assert not (tmp_path / "rw" / "train_requests").exists()


def test_shadow_tick_apply_appends_and_waits_for_the_claimer(tmp_path):
    w = World(tmp_path)

    def claimer_runs(_s):  # the installed claimer, answering while the tick waits
        T.process_requests(w.state, lambda live: w.controller(live=live), apply=True, now=lambda: w.clock.t,
                           shadow_pol=SHADOW_ON)

    clock = {"t": 0.0}
    code, out = T.shadow_tick(["1800"], apply=True, inject="corrupt-latch", wait_s=60, state=w.state,
                              clock=lambda: clock["t"], sleep=lambda s: (clock.__setitem__("t", clock["t"] + s),
                                                                         claimer_runs(s)))
    row = out["windows"][0]
    assert code == T.EXIT_OK and row["result"] == "ANSWERED", row
    assert row["receipt_state"] == "REFUSED" and row["refusal"]["code"] == "STOP_UNREADABLE"
    assert "corrupt-latch@preconditions=AS_SPECIFIED" in row["line"]
    assert Path(row["report"]).exists()
    assert not w.state.latch.exists()  # the drill is simulated


def test_back_to_back_forced_ticks_get_distinct_requests(tmp_path):
    state = RW.State(tmp_path / "rw")
    ids = []
    for _ in range(3):
        code, out = T.shadow_tick(["1800"], apply=True, inject=None, wait_s=0, state=state)
        ids.append(out["windows"][0]["request_id"])
        assert out["windows"][0]["disposition"] == "requested"
    assert len(set(ids)) == 3
    assert len(os.listdir(tmp_path / "rw" / "train_requests" / "pending")) == 3


def test_shadow_tick_reports_a_missing_claimer(tmp_path):
    state = RW.State(tmp_path / "rw")
    clock = {"t": 0.0}
    code, out = T.shadow_tick(["0000"], apply=True, inject=None, wait_s=30, state=state,
                              clock=lambda: clock["t"], sleep=lambda s: clock.__setitem__("t", clock["t"] + s))
    assert code == 1 and out["windows"][0]["result"].startswith("NO TERMINAL RECEIPT")
    assert len(os.listdir(tmp_path / "rw" / "train_requests" / "pending")) == 1  # left for the claimer


def test_shadow_tick_with_stop_set_requests_nothing(tmp_path):
    state = RW.State(tmp_path / "rw")
    state.write(state.latch, {"latched_at": "x", "reason": "drill"})
    code, out = T.shadow_tick(["1800"], apply=True, inject=None, wait_s=0, state=state)
    assert code == 1 and out["windows"][0]["result"] == "NOT_REQUESTED"
    assert out["windows"][0]["no_op_reason"] == "stop_set"
    assert not (tmp_path / "rw" / "train_requests" / "pending").exists()


def test_cli_exposes_train_shadow_tick_dry_run(capsys, tmp_path):
    assert RW.main(["train-shadow-tick", "--window", "0800"]) == T.EXIT_OK
    out = capsys.readouterr().out
    assert "release train shadow tick (dry_run)" in out and "WOULD_REQUEST" in out
