"""Pinned standing hygiene tests: fake removers only, no host census/PR/service calls.
COVERS = ["scripts/disk_hygiene.py", "scripts/disk_usage_monitor.py", "scripts/lib/disk_hygiene_retention.py", "docs/ops/packets/disk-standing-apply-20261024/activate_reviewed.py"]
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import disk_hygiene as DH
from scripts import disk_usage_monitor as DM
from scripts.lib import disk_hygiene_retention as SR

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
COLLECT = DH.collect_standing_evidence


def evidence(*, offline=False):
    vals = {"cron": "# authorized fixture capture\n", "units": [], "processes": [], "pointers": [], "prs": [],
            "coordination": {"references": [], "live_claims": [], "live_worklogs": []}}
    return {"schema": SR.SCHEMA, "offline": offline, "sources": {
        k: {"complete": True, "captured_at": NOW.isoformat(), "data": v, "sha256": SR.digest(v)} for k, v in vals.items()}}


def set_source(doc, key, data):
    doc["sources"][key].update(data=data, sha256=SR.digest(data))


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    cfg = json.loads((ROOT / "config/disk_hygiene_rules.json").read_text())
    cfg["standing_apply"] = {"enabled": True, "rules": ["A", "S", "W"], "manifest_max_age_hours": 2,
                             "max_bytes_per_run": SR.MAX_BYTES, "max_gb_per_run": 40, "byte_unit": "GiB",
                             "approved_by": "SYNTHETIC_TEST_ONLY", "archive": {"path": "~/db_backups/archive"},
                             "approval": {"status": "APPROVED", "approved_by": "SYNTHETIC_TEST_ONLY", "approved_at": NOW.isoformat()}}
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(cfg))
    rules = DH.load_rules(rules_path, home=home)
    monkeypatch.setattr(DH, "collect_standing_evidence", lambda *_a, **_kw: evidence())
    monkeypatch.setattr(DH, "reference_texts", lambda *_: pytest.fail("live scheduler census forbidden"))
    monkeypatch.setattr(DH, "process_cwds", lambda *_: pytest.fail("live process census forbidden"))
    monkeypatch.setattr(DH, "discover_git_dirs", lambda *_: [])
    monkeypatch.setattr(DH, "du_bytes", lambda p, *_: p.stat().st_size)
    monkeypatch.setattr(DH, "disk_usage_sample", lambda *_: {"used_pct": 70, "measured_at": NOW.isoformat(), "filesystem_path": str(home)})
    monkeypatch.setattr(DH, "remove_item", lambda *_: pytest.fail("no real cleanup is allowed in these tests"))
    return home, rules, rules_path, cfg


def old(path, days=10):
    stamp = (NOW - timedelta(days=days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def dumps(home):
    archive = home / "db_backups" / "archive"
    archive.mkdir(parents=True)
    for i in range(3, 50):
        p = archive / f"trade_ai_fixture_{i:02}.sql.gz"
        p.write_bytes(b"fixture")
        old(p, i)
    return archive


def planned(world, monkeypatch):
    home, rules, _, _ = world
    dumps(home)
    doc = evidence()
    manifest = DH.standing_plan(rules, NOW, doc)
    path = home / "manifest.json"
    path.write_text(json.dumps(manifest))
    calls = []
    monkeypatch.setattr(DH, "remove_item", lambda item: (calls.append(dict(item)) is None, "SIMULATED_ONLY"))
    return path, manifest, doc, calls


def do_apply(path, rules, doc, **kw):
    return DH.apply(path, rules, NOW, grant=None, run_id="fixture-run", standing=True, evidence=doc,
                    manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), progress_sink=kw.pop("progress_sink", lambda _r: None), **kw)


def test_evidence_requires_each_complete_fresh_hashed_source(world):
    doc = evidence()
    assert SR.evidence_context(doc, NOW)["snapshot"]["prs"] == []
    for key in SR.SOURCES:
        bad = evidence()
        bad["sources"][key]["complete"] = False
        with pytest.raises(ValueError, match="evidence_incomplete"):
            SR.evidence_context(bad, NOW)
        bad = evidence()
        bad["sources"][key]["captured_at"] = (NOW - timedelta(hours=2, seconds=1)).isoformat()
        with pytest.raises(ValueError, match="evidence_stale"):
            SR.evidence_context(bad, NOW)
    doc["sources"]["cron"]["data"] += "changed"
    with pytest.raises(ValueError, match="digest"):
        SR.evidence_context(doc, NOW)


@pytest.mark.parametrize("stamp", ["2026-10-24T12:00:00", "2026-10-24T12:00:01+00:00", "not-time"])
def test_future_naive_or_invalid_evidence_cannot_prove_no_refs(stamp):
    doc = evidence()
    doc["sources"]["prs"]["captured_at"] = stamp
    with pytest.raises(ValueError, match="evidence_stale"):
        SR.evidence_context(doc, NOW)


def test_offline_capture_is_preview_only(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    doc["offline"] = True
    assert DH.standing_plan(world[1], NOW, doc)["offline"]
    assert do_apply(path, world[1], doc)["refused"] == "offline_evidence_cannot_apply"
    assert calls == []


def test_archive_retains_seven_daily_and_four_sunday_points_and_never_live_or_hold(world):
    home, rules, _, _ = world
    archive = dumps(home)
    hold = archive / "hold"
    hold.mkdir()
    (hold / "trade_ai_held.sql.gz").write_bytes(b"held")
    live = home / "db_backups" / "trade_ai_live.sql.gz"
    live.write_bytes(b"live")
    young = archive / "trade_ai_young.sql.gz"
    young.write_bytes(b"partial")
    manifest = DH.standing_plan(rules, NOW, evidence())
    excluded = {Path(r["path"]).name: r for r in manifest["excluded"]}
    kept = [r for r in manifest["excluded"] if "daily_or_sunday_recovery_point" in r["reasons"]]
    days = {datetime.fromtimestamp(r["evidence"]["mtime"], timezone.utc).astimezone(SR.ZoneInfo("America/New_York")).date() for r in kept}
    assert len([d for d in days if d.weekday() == 6]) >= 4
    assert len(days) == 10  # 7 daily + 4 Sunday, with one overlapping date
    assert not any(r["path"] == str(live) or "/hold/" in r["path"] for r in manifest["items"])
    assert "not_completed_dump" in excluded["hold"]["reasons"]
    assert "young_or_incomplete_dump" in excluded[young.name]["reasons"]
    assert DH.never_touch_reason(live, rules).startswith("never_touch")


def test_archive_exception_cannot_escape_to_symlink_other_root_or_directory(world):
    home, rules, _, _ = world
    archive = dumps(home)
    direct = next(archive.iterdir())
    assert DH.standing_hard_reason(direct, "archived_dump", rules) is None
    assert DH.standing_hard_reason(archive, "archived_dump", rules) == "archive_exception_scope"
    link = archive / "trade_ai_symlink.sql.gz"
    link.symlink_to(direct)
    assert DH.standing_hard_reason(link, "archived_dump", rules) == "archive_exception_scope"
    rules["standing_apply"]["archive"]["path"] = "~/elsewhere"
    assert DH.standing_hard_reason(direct, "archived_dump", rules) == "archive_exception_scope"


def test_rtc_historical_coordination_reference_and_deep_activity_hold(world):
    home, rules, _, _ = world
    scratch = home / ".cache" / "rtc"
    scratch.mkdir(parents=True)
    paths = []
    for name in ("unused", "referenced", "recent"):
        p = scratch / name
        (p / "nested").mkdir(parents=True)
        f = p / "nested" / "evidence.txt"
        f.write_text("fixture")
        for child in (f, f.parent, p):
            old(child)
        paths.append(p)
    fresh = paths[2] / "nested" / "evidence.txt"
    os.utime(fresh, (NOW.timestamp(), NOW.timestamp()))
    doc = evidence()
    set_source(doc, "coordination", {"references": [{"historical_progress": str(paths[1] / "body.md")}], "live_claims": [], "live_worklogs": []})
    result = DH.standing_plan(rules, NOW, doc)
    assert {r["path"] for r in result["items"]} == {str(paths[0])}
    assert any("referenced" in " ".join(r["reasons"]) for r in result["excluded"] if r["path"] == str(paths[1]))
    assert any("scratch_not_older" in " ".join(r["reasons"]) for r in result["excluded"] if r["path"] == str(paths[2]))


def test_recursive_activity_limit_fails_closed(tmp_path):
    (tmp_path / "nested").mkdir()
    assert SR.activity(tmp_path, max_entries=1)[1] == "activity_scan_limit"


def fake_worktree(world, monkeypatch, *, branch="refs/heads/work/fixture", merged=None, reasons=()):
    home, rules, _, _ = world
    tree = home / "wt-fixture"
    tree.mkdir()
    gitdir = home / "metadata"
    gitdir.mkdir()
    old(tree)
    old(gitdir)
    monkeypatch.setattr(DH, "discover_git_dirs", lambda *_: [tree])
    monkeypatch.setattr(DH, "git_layout", lambda *_: {"kind": "git_worktree", "gitdir": gitdir, "main_repo": home / "canonical"})
    monkeypatch.setattr(DH, "evaluate_git", lambda *_: {"main_repo": str(home / "canonical"), "evidence": {"merged": merged}, "reasons": list(reasons), "fingerprint": {"head": "a" * 40}})
    monkeypatch.setattr(DH, "_git", lambda _, *args, **kw: ((0, branch) if branch else (1, "")) if args[0] == "symbolic-ref" else (0, "a" * 40))
    return tree, rules


def test_named_branch_preserves_unmerged_unpushed_commits_but_detached_requires_ancestor(world, monkeypatch):
    tree, rules = fake_worktree(world, monkeypatch, reasons=("not_merged", "unpushed_commits", "recent_activity"))
    rows = DH.standing_results(rules, SR.evidence_context(evidence(), NOW))
    assert rows[0]["candidate"] and rows[0]["evidence"]["branch_preserved"]
    monkeypatch.setattr(DH, "_git", lambda *a, **kw: (1, ""))
    assert "detached_not_ancestor" in DH.standing_results(rules, SR.evidence_context(evidence(), NOW))[0]["reasons"]
    assert tree.exists()


@pytest.mark.parametrize("guard", ["dirty", "untracked", "ignored_credential_like", "worktree_locked", "status_failed"])
def test_old_worktree_guards_survive_new_named_branch_rule(world, monkeypatch, guard):
    _, rules = fake_worktree(world, monkeypatch, reasons=(guard,))
    item = DH.standing_results(rules, SR.evidence_context(evidence(), NOW))[0]
    assert not item["candidate"] and guard in item["reasons"]


@pytest.mark.parametrize("source", ["live_claims", "live_worklogs", "prs", "processes"])
def test_worktree_live_claim_worklog_pr_or_process_reference_holds(world, monkeypatch, source):
    tree, rules = fake_worktree(world, monkeypatch)
    doc = evidence()
    if source in ("live_claims", "live_worklogs"):
        set_source(doc, "coordination", {"references": [], "live_claims": [], "live_worklogs": [], source: [{"worktree": str(tree)}]})
    else:
        set_source(doc, source, [{"worktree": str(tree), "cwd": str(tree)}])
    assert not DH.standing_results(rules, SR.evidence_context(doc, NOW))[0]["candidate"]


def test_apply_simulated_only_binds_rules_manifest_and_all_three_rule_totals(world, monkeypatch):
    path, manifest, doc, calls = planned(world, monkeypatch)
    report = do_apply(path, world[1], doc)
    assert report["refused"] is None and calls
    assert report["per_rule"]["A"]["applied_bytes"] == sum(r["size_bytes"] for r in manifest["items"])
    assert set(report["per_rule"]) == {"A", "S", "W"}
    assert "planned/applied" in report["operator_digest"]
    assert all(Path(r["path"]).exists() for r in calls)  # no real unlink/remove/rmtree happened


def test_standing_disabled_or_pending_refuses_before_remover(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    rules = world[1]
    rules["standing_apply"]["enabled"] = False
    assert do_apply(path, rules, doc)["refused"] == "standing_apply_disabled"
    rules["standing_apply"]["approval"]["status"] = "PENDING"
    assert do_apply(path, rules, doc)["refused"] == "standing_approval_pending"
    assert not calls


@pytest.mark.parametrize("change,reason", [("rules", "manifest_rules_sha_mismatch"), ("scope", "manifest_scope"), ("age", "manifest_stale"), ("future", "manifest_stale"), ("naive", "manifest_generated_at")])
def test_bad_manifest_binding_time_or_scope_refuses(world, monkeypatch, change, reason):
    path, manifest, doc, calls = planned(world, monkeypatch)
    if change == "rules": manifest["rules_sha256"] = "bad"
    if change == "scope": manifest["scope"] = "not-standing"
    if change == "age": manifest["generated_at"] = (NOW - timedelta(hours=2, seconds=1)).isoformat()
    if change == "future": manifest["generated_at"] = (NOW + timedelta(seconds=1)).isoformat()
    if change == "naive": manifest["generated_at"] = NOW.replace(tzinfo=None).isoformat()
    path.write_text(json.dumps(manifest))
    assert do_apply(path, world[1], doc)["refused"] == reason
    assert not calls


def test_changed_rules_file_after_plan_and_between_items_stops(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    rules_path = world[2]
    def simulated_remove(item):
        calls.append(item)
        rules_path.write_text(rules_path.read_text() + " ")
        return True, "SIMULATED_ONLY"
    monkeypatch.setattr(DH, "remove_item", simulated_remove)
    report = do_apply(path, world[1], doc)
    assert report["refused"] == "rules_changed_during_apply" and len(calls) == 1
    assert do_apply(path, world[1], doc)["refused"] == "rules_changed_before_apply"


def test_cap_unknown_size_and_unlisted_rule_never_reach_remover(world, monkeypatch):
    path, manifest, doc, calls = planned(world, monkeypatch)
    for item in manifest["items"]: item["size_bytes"] = None
    manifest["items"][0].update(size_bytes=1, rule="UNLISTED")
    path.write_text(json.dumps(manifest))
    report = do_apply(path, world[1], doc)
    assert not calls
    assert {r["why"] for r in report["skipped"]} == {"size_unknown", "standing_rule_not_listed"}
    for item in manifest["items"]: item.update(size_bytes=1, rule="A")
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(DH, "du_bytes", lambda *_: SR.MAX_BYTES + 1)
    report = do_apply(path, world[1], doc)
    assert not calls and {r["why"] for r in report["skipped"]} == {"byte_cap_remeasured"}


def test_manual_grant_still_required_and_executor_old_path_still_refused(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    assert DH.apply(path, world[1], NOW, grant=None, run_id=None)["refused"] == DH.GRANT_ENV + "_missing"
    assert DH.apply(path, world[1], NOW, grant="fixture", run_id="fixture-run")["refused"] == "n8n_executor_never_applies"
    assert not calls


def test_held_alert_counts_distinct_runs_not_repeated_polls():
    old_run = {"manifest_sha256": "old", "run_id": "old-run", "held_bytes": 11 * 1024**3}
    run = {"manifest_sha256": "new", "run_id": "new-run", "held_bytes": 12 * 1024**3}
    assert SR.monitor_decision(run, old_run, 80)["alert"] == "held_above_10gb_two_runs"
    assert SR.monitor_decision(run, run, 80)["alert"] is None
    assert SR.monitor_decision(run, old_run, 85.01)["alert"] == "disk_above_85"
    assert SR.monitor_decision({**run, "held_bytes": 10 * 1024**3}, old_run, 85)["alert"] is None


def test_monitor_reads_digest_without_cleanup_or_direct_sender(world, tmp_path):
    home, rules, _, _ = world
    state_root = tmp_path / "state"
    path = DH.manifest_dir(rules, state_root) / "disk_hygiene_standing_apply_latest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"manifest_sha256": "new", "run_id": "new-run", "finished_at": NOW.isoformat(), "held_bytes": 12 * 1024**3, "operator_digest": "fixture digest"}))
    result = DM.standing_hygiene_status(rules, state_root, {"manifest_sha256": "old", "run_id": "old-run", "held_bytes": 11 * 1024**3}, NOW, 70)
    assert result["alert"] == "held_above_10gb_two_runs" and result["digest"] == "fixture digest"
    assert DM.standing_hygiene_status(rules, state_root, {"manifest_sha256": "new", "run_id": "new-run"}, NOW, 70)["status"] == "already_observed"


def collector_fixture(world):
    home, rules, _, _ = world
    base = home / "trade-ai-releases" / "persistent-state" / "data" / "coordination"
    for folder in ("claims", "worklogs", "handoffs"):
        (base / folder).mkdir(parents=True)
    (base / "handoffs" / "PROGRESS_LOG.md").write_text(str(home / ".cache" / "rtc" / "held" / "body.md"))
    (base / "claims" / "fixture.json").write_text(json.dumps({"schema": "AgentClaim@v1", "claim_id": "fixture", "status": "active", "worktree": str(home / "claimed")}))
    (base / "worklogs" / "fixture.worklog.md").write_text(str(home / "claimed"))
    proc = home / "proc"
    (proc / "123" / "fd").mkdir(parents=True)
    (proc / "123" / "cwd").symlink_to(home / "running")
    (proc / "123" / "fd" / "5").symlink_to(home / "open-file")
    units = home / "units"
    units.mkdir()
    (units / "fixture.service").write_text("WorkingDirectory=" + str(home / "unit-tree"))
    pointers = home / "pointers"
    pointers.mkdir()
    (pointers / "CURRENT").symlink_to(home / "served")
    rules.update(_proc_root=proc, _unit_dirs=[units], _pointer_dir=pointers)
    rules["releases"]["pointer_symlinks"] = ["CURRENT"]
    rules["releases"]["pointer_files"] = []
    return rules


class FixtureGithub:
    repo = "fixture/repo"
    def __init__(self, rows=None, warning=None):
        self.paths = []
        self.rows = rows or []
        self.warning = warning
    def get(self, path):
        self.paths.append(path)
        return self.rows, self.warning


def test_real_collector_seams_refresh_all_sources_without_host_calls(world):
    rules = collector_fixture(world)
    reader = FixtureGithub([{"state": "open", "number": 42, "head": {"ref": "work/preserve"}}])
    def runner(cmd, **kwargs):
        assert cmd == ["crontab", "-l"]
        return type("Result", (), {"returncode": 0, "stdout": "# fixture cron"})()
    snapshot = COLLECT(rules, NOW, runner=runner, github=reader)
    ctx = SR.evidence_context(snapshot, NOW, applying=True)
    assert set(snapshot["sources"]) == set(SR.SOURCES)
    assert ctx["snapshot"]["processes"][0]["fds"] == [str(world[0] / "open-file")]
    assert ctx["snapshot"]["coordination"]["live_claims"][0]["worktree"] == str(world[0] / "claimed")
    assert ctx["snapshot"]["coordination"]["references"]
    assert ctx["snapshot"]["prs"] == [{"number": 42, "branch": "work/preserve", "state": "open"}]
    assert reader.paths == ["repos/fixture/repo/pulls?state=open&per_page=100&page=1"]


def test_collector_refusal_or_unavailable_pr_never_proves_absence(world):
    rules = collector_fixture(world)
    reader = FixtureGithub(warning="fixture unavailable (not a real request)")
    def refused(cmd, **kwargs):
        return type("Result", (), {"returncode": 1, "stdout": ""})()
    snapshot = COLLECT(rules, NOW, runner=refused, github=reader)
    assert not snapshot["sources"]["cron"]["complete"]
    assert not snapshot["sources"]["prs"]["complete"]
    assert "unavailable" in snapshot["sources"]["prs"]["reason"]
    with pytest.raises(ValueError, match="evidence_incomplete"):
        SR.evidence_context(snapshot, NOW, applying=True)
    assert len(reader.paths) == 1  # no retry, alternative auth or fallback to stale PR state


def test_collect_paginates_open_prs_and_refuses_incomplete_page_cap(world):
    rules = collector_fixture(world)
    reader = FixtureGithub([{"state": "open", "number": n, "head": {"ref": f"work/{n}"}} for n in range(100)])
    result = COLLECT(rules, NOW, runner=lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(), github=reader)
    assert not result["sources"]["prs"]["complete"] and len(reader.paths) == 20


def test_explicit_manifest_hash_mismatch_refuses_before_remover(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    report = DH.apply(path, world[1], NOW, grant=None, run_id="fixture", standing=True, evidence=doc, manifest_sha256="bad")
    assert report["refused"] == "manifest_sha_mismatch" and not calls


def test_default_committed_configuration_remains_unconfigured_and_disabled():
    rules = DH.load_rules()
    assert rules["standing_apply"]["enabled"] is False
    assert rules["standing_apply"]["approval"]["status"] == "PENDING_OPERATOR_REVIEW"
    for filename, key in (("lane_registry.json", "lane_id"), ("n8n_run_allowlist.json", "lane_id"), ("n8n_health_contracts.json", "id")):
        doc = json.loads((ROOT / "config" / filename).read_text())
        collection = doc["contracts"] if key == "id" else doc["lanes"]
        row = next(r for r in collection if r.get(key) == "disk-hygiene")
        if filename == "lane_registry.json": assert row["dispatch"]["cron"] == ["0 4 * * 0"]
        if filename == "n8n_run_allowlist.json": assert row["live_arg"] == ["--plan"]
        if filename == "n8n_health_contracts.json": assert row["status"] == "REVIEWED" and "Deletes nothing" in row["purpose"]["text"]
        assert doc["pending_changes"]["disk-hygiene-standing-apply-20261024"]



def monitor_world(world, tmp_path, monkeypatch):
    rules = world[1]
    rules["monitor"].update(mounts=[str(world[0])], consumer_categories=[])
    rules["monitor"].pop("inodes", None)
    rules["standing_apply"]["monitor"] = {"digest_kind": "fixture_digest", "alert_kind": "fixture_alert"}
    state_root = tmp_path / "state"
    pct, queued, fail = [84.0], {}, [False]
    monkeypatch.setattr(DM, "measure", lambda mount: {"mount": mount, "used_pct": pct[0], "size_bytes": 100, "avail_bytes": 16})
    monkeypatch.setattr(DM, "latest_manifest", lambda *_: None)
    monkeypatch.setattr(DM, "top_consumers", lambda *_: [])
    monkeypatch.setattr(DM.R, "write_lane_receipt", lambda *a, **kw: state_root / "receipt.json")
    def queue(**kwargs):
        if fail[0]:
            raise DM.HostIntentError("fixture_queue_failed")
        key = (kwargs["kind"], kwargs["subject"])
        duplicate = key in queued
        queued.setdefault(key, kwargs)
        return {"intent_id": str(len(queued)), "duplicate": duplicate}
    monkeypatch.setattr(DM, "queue_host_intent", queue)
    def report(run, held, *, refused=None):
        p = DH.manifest_dir(rules, state_root) / f"disk_hygiene_standing_apply_{run}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"run_id": run, "manifest_sha256": run + "-sha", "held_bytes": held,
                                 "finished_at": NOW.isoformat(), "operator_digest": "fixture " + run, "refused": refused}))
    def run(minutes=0):
        return DM.run(rules=rules, state_root=state_root, ledger=tmp_path / "ledger", apply=True,
                      now=NOW + timedelta(minutes=minutes), wall_start=NOW)
    def state():
        return json.loads((DM.R.runtime_dir(state_root) / rules["monitor"]["state_name"]).read_text())
    return report, run, state, pct, queued, fail


def test_integrated_monitor_two_runs_replay_and_same_run_new_manifest(world, tmp_path, monkeypatch):
    report, run, state, pct, queued, fail = monitor_world(world, tmp_path, monkeypatch)
    report("run-A", 11 * 1024**3)
    assert run() == 0
    report("run-B", 12 * 1024**3)
    assert run(15) == 0
    assert state()["standing_hygiene"]["seen_run_ids"] == ["run-A", "run-B"]
    assert any(k[0] == "fixture_alert" and "run-B" in k[1] for k in queued)
    assert any(k[0] == "fixture_digest" and "run-A" in k[1] for k in queued)
    before = len(queued)
    report("run-A", 13 * 1024**3)  # same durable run with a regenerated manifest is not a third run
    assert run(30) == 0 and len(queued) == before
    assert state()["standing_hygiene"]["run_id"] == "run-B"


def test_integrated_monitor_same_receipt_crossing_85_is_alerted_once(world, tmp_path, monkeypatch):
    report, run, state, pct, queued, fail = monitor_world(world, tmp_path, monkeypatch)
    report("run-A", 0)
    assert run() == 0
    pct[0] = 86
    assert run(15) == 0
    pressure = [k for k in queued if k[0] == "fixture_alert" and "pressure boundary" in k[1]]
    assert len(pressure) == 1 and state()["standing_pressure_active"]
    assert run(30) == 0 and len([k for k in queued if "pressure boundary" in k[1]]) == 1


def test_integrated_monitor_queue_failure_keeps_run_retryable(world, tmp_path, monkeypatch):
    report, run, state, pct, queued, fail = monitor_world(world, tmp_path, monkeypatch)
    report("run-A", 20 * 1024**3)
    fail[0] = True
    assert run() == 1
    assert state()["standing_hygiene"] == {}
    fail[0] = False
    assert run(15) == 0
    assert state()["standing_hygiene"]["run_id"] == "run-A"


def test_integrated_monitor_state_write_failure_reuses_same_intent_identity(world, tmp_path, monkeypatch):
    from scripts.lib import atomic_json_store
    report, run, state, pct, queued, fail = monitor_world(world, tmp_path, monkeypatch)
    report("run-A", 0)
    original = atomic_json_store.atomic_write_json
    def denied(*a, **kw):
        raise OSError("fixture state failure")
    monkeypatch.setattr(atomic_json_store, "atomic_write_json", denied)
    assert run() == 1
    digest_keys = [k for k in queued if k[0] == "fixture_digest"]
    assert len(digest_keys) == 1
    monkeypatch.setattr(atomic_json_store, "atomic_write_json", original)
    assert run(15) == 0
    assert [k for k in queued if k[0] == "fixture_digest"] == digest_keys


def test_unmeasured_refusal_has_digest_and_cannot_create_two_run_held_proof(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    world[1]["standing_apply"]["enabled"] = False
    result = do_apply(path, world[1], doc)
    assert result["run_id"] == "fixture-run" and result["finished_at"]
    assert result["held_bytes"] is None and "NOT_MEASURED" in result["operator_digest"]
    assert not calls
    assert SR.monitor_decision(result, {"run_id": "older", "held_bytes": 20 * 1024**3}, 70)["alert"] is None


def test_new_claim_appearing_after_plan_holds_before_simulated_remove(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    refreshed = evidence()
    set_source(refreshed, "coordination", {"references": [], "live_claims": [{"worktree": r["path"]} for r in json.loads(path.read_text())["items"]], "live_worklogs": []})
    monkeypatch.setattr(DH, "collect_standing_evidence", lambda *_: refreshed)
    result = do_apply(path, world[1], doc)
    assert not calls and all(r["why"] == "standing_revalidation_failed" for r in result["skipped"])


def test_native_disabled_apply_still_writes_failed_receipt_without_collection(world, tmp_path, monkeypatch):
    home, rules, rules_path, cfg = world
    cfg["standing_apply"]["enabled"] = False
    rules_path.write_text(json.dumps(cfg))
    monkeypatch.setenv(DH.RUN_ID_ENV, "fixture-native-disabled")
    monkeypatch.setattr(DH, "collect_standing_evidence", lambda *_: pytest.fail("disabled native run must not collect"))
    receipts = []
    monkeypatch.setattr(DH.R, "write_lane_receipt", lambda *a, **kw: receipts.append((a, kw)) or tmp_path / "receipt")
    state_root = tmp_path / "state"
    assert DH.main(["--standing", "--apply", "--rules", str(rules_path), "--home", str(home), "--state-root", str(state_root), "--now", NOW.isoformat()]) == 1
    report = json.loads((DH.manifest_dir(rules, state_root) / "disk_hygiene_standing_apply_latest.json").read_text())
    assert report["refused"] == "standing_apply_disabled" and report["held_bytes"] is None
    assert receipts[0][0] == ("disk-hygiene",) and receipts[0][1]["ok"] is False
    assert receipts[0][1]["output"]["produced_count"] == 0


def test_simulated_removal_failure_is_failed_not_zero_removal_success(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    monkeypatch.setattr(DH, "remove_item", lambda *_: (False, "error:PermissionError"))
    result = do_apply(path, world[1], doc)
    assert result["refused"] == "removal_failed" and result["held_bytes"] == result["planned_bytes"] > 0
    assert not result["removed"] and result["skipped"][0]["why"] == "error:PermissionError"


def test_protected_backup_bytes_do_not_count_as_unapplied_eligible_work(world, monkeypatch):
    path, manifest, doc, calls = planned(world, monkeypatch)
    manifest["protected_excluded_bytes"] = 300 * 1024**3
    path.write_text(json.dumps(manifest))
    result = do_apply(path, world[1], doc)
    assert result["held_bytes"] == 0 and result["protected_excluded_bytes"] == 300 * 1024**3
    assert SR.monitor_decision(result, {"run_id": "prior", "held_bytes": 12 * 1024**3}, 70)["alert"] is None


def test_post_apply_usage_and_later_monitor_usage_have_distinct_timebasis(world, tmp_path):
    home, rules, _, _ = world
    state_root = tmp_path / "state"
    p = DH.manifest_dir(rules, state_root) / "disk_hygiene_standing_apply_run.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"run_id": "run-after", "manifest_sha256": "sha", "held_bytes": 0,
                             "finished_at": NOW.isoformat(), "operator_digest": "fixture",
                             "post_apply_usage": {"used_pct": 86, "measured_at": NOW.isoformat()}}))
    result = DM.standing_hygiene_status(rules, state_root, {}, NOW + timedelta(minutes=15), 70)
    assert result["alert"] == "post_apply_disk_above_85"


def test_durable_progress_intent_precedes_every_simulated_removal(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    events = []
    def progress(report):
        events.append(("journal", json.loads(json.dumps(report))))
    def remover(item):
        assert events[-1][0] == "journal"
        assert events[-1][1]["pending_removal"]["path"] == item["path"]
        events.append(("simulated_remove", item["path"]))
        return True, "SIMULATED_ONLY"
    monkeypatch.setattr(DH, "remove_item", remover)
    result = do_apply(path, world[1], doc, progress_sink=progress)
    assert result["refused"] is None
    assert len([e for e in events if e[0] == "journal"]) == 2 * len(result["removed"])


def test_progress_write_failure_prevents_removal_and_never_claims_success(world, monkeypatch):
    path, _, doc, calls = planned(world, monkeypatch)
    def fail(_):
        raise OSError("fixture journal failure")
    result = do_apply(path, world[1], doc, progress_sink=fail)
    assert result["refused"] == "progress_write_failed_before_removal" and not calls
    assert result["pending_removal"]["status"] == "PENDING_NOT_PROVEN_REMOVED"


def activation_module():
    import importlib.util
    path = ROOT / 'docs/ops/packets/disk-standing-apply-20261024/activate_reviewed.py'
    spec = importlib.util.spec_from_file_location('disk_activation_fixture',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def activation_fixture(tmp_path):
    mod = activation_module()
    packet = ROOT / 'docs/ops/packets/disk-standing-apply-20261024'
    pins = json.loads((packet/'activation-input-sha256.json').read_text())
    config = tmp_path/'config'
    config.mkdir()
    for name in pins:
        (config/name).write_bytes((ROOT/'config'/name).read_bytes())
    review = json.loads((packet/'review.required.json').read_text())
    review.update(decision='APPROVE_DISK_STANDING_APPLY',approved_by='SYNTHETIC_OPERATOR_FIXTURE_ONLY',approved_at=NOW.isoformat())
    return mod,packet,config,review


def test_activation_packet_is_default_read_only_and_requires_real_review_shape(tmp_path):
    mod,packet,config,review = activation_fixture(tmp_path)
    before={p.name:p.read_bytes() for p in config.iterdir()}
    pending=dict(review,decision='PENDING_OPERATOR_REVIEW')
    with pytest.raises(ValueError,match='operator_review_pending'):
        mod.promotion(config,packet,pending)
    assert before == {p.name:p.read_bytes() for p in config.iterdir()}
    rendered,digest = mod.promotion(config,packet,review)
    assert before == {p.name:p.read_bytes() for p in config.iterdir()}  # pure preview, even with synthetic approval
    assert len(digest)==64
    rules=json.loads(rendered['disk_hygiene_rules.json'])
    assert rules['standing_apply']['enabled'] and rules['standing_apply']['approval']['approved_by']=='SYNTHETIC_OPERATOR_FIXTURE_ONLY'


def test_exact_promotion_changes_cadence_contract_argv_and_enable_together(tmp_path):
    from scripts.lib.n8n_health_contracts import validate_contract
    mod,packet,config,review=activation_fixture(tmp_path)
    rendered,_=mod.promotion(config,packet,review)
    reg=json.loads(rendered['lane_registry.json']);allow=json.loads(rendered['n8n_run_allowlist.json']);contracts=json.loads(rendered['n8n_health_contracts.json'])
    row=next(x for x in reg['lanes'] if x['lane_id']=='disk-hygiene')
    assert row['dispatch']['cron']==['0 4 * * 1,3,5,0'] and row['dispatch']['tz']=='America/New_York'
    assert row['expected_cadence_hours']==48 and row['dispatch']['retry_policy']=='none'
    entry=next(x for x in allow['lanes'] if x['lane_id']=='disk-hygiene')
    assert entry['live_arg']==['--standing','--apply']
    contract=next(x for x in contracts['contracts'] if x['id']=='disk-hygiene')
    assert not validate_contract(contract)
    assert contract['status']=='REVIEWED' and contract['reviewed_by']==review['approved_by']
    assert contract['previous_plan_review']['purpose']['text'].startswith('Weekly')
    # Every other operative object is preserved, including data from the shared base.
    for name,key,idkey in [('lane_registry.json','lanes','lane_id'),('n8n_run_allowlist.json','lanes','lane_id'),('n8n_health_contracts.json','contracts','id')]:
        before=json.loads((config/name).read_text())
        after=json.loads(rendered[name])
        assert [r for r in before[key] if r.get(idkey)!='disk-hygiene']==[r for r in after[key] if r.get(idkey)!='disk-hygiene']


def test_activation_refuses_changed_base_and_wrong_reviewed_draft(tmp_path):
    mod,packet,config,review=activation_fixture(tmp_path)
    with pytest.raises(ValueError,match='review_contract_hash_mismatch'):
        mod.promotion(config,packet,dict(review,draft_contract_sha256='bad'))
    p=config/'lane_registry.json'
    p.write_text(p.read_text()+' ')
    with pytest.raises(ValueError,match='source_config_changed'):
        mod.promotion(config,packet,review)


def test_rule_subset_is_order_independent_and_omitted_worktree_stays_plan_only(world, monkeypatch):
    tree,rules = fake_worktree(world,monkeypatch)
    rules['standing_apply']['rules']=['S','A']
    rows=DH.standing_results(rules,SR.evidence_context(evidence(),NOW))
    assert not rows[0]['candidate']
    assert rows[0]['reasons']==['rule_plan_only_not_authorized:W']
    rules['standing_apply']['rules']=['W']
    assert DH.standing_results(rules,SR.evidence_context(evidence(),NOW))[0]['candidate']
    assert tree.exists()


def test_unknown_rule_authority_fails_closed_but_valid_empty_subset_loads(world):
    home,rules,path,cfg=world
    cfg['standing_apply']['rules']=[]
    path.write_text(json.dumps(cfg))
    assert DH.load_rules(path,home=home)['standing_apply']['rules']==[]
    cfg['standing_apply']['rules']=['A','UNKNOWN']
    path.write_text(json.dumps(cfg))
    with pytest.raises(DH.RulesError,match='standing_rules_shape'):
        DH.load_rules(path,home=home)


def test_forged_manifest_rule_kind_or_path_cannot_escape_allowlist(world,monkeypatch):
    path,manifest,doc,calls=planned(world,monkeypatch)
    valid=manifest['items'][0]
    outside=world[0]/'outside.sql.gz'
    outside.write_bytes(b'not an archived dump')
    manifest['items']=[dict(valid,path=str(outside)),dict(valid,rule='A',kind='rtc_scratch')]
    path.write_text(json.dumps(manifest))
    result=do_apply(path,world[1],doc)
    assert not calls
    assert {r['why'] for r in result['skipped']}=={'standing_revalidation_failed','standing_rule_not_listed'}


def test_forged_manifest_cannot_authorize_an_omitted_rule(world,monkeypatch):
    home,rules,rules_path,cfg=world
    cfg['standing_apply']['rules']=['S']
    rules_path.write_text(json.dumps(cfg))
    narrowed=DH.load_rules(rules_path,home=home)
    path,manifest,doc,calls=planned(world,monkeypatch)
    # Forge an A item into a correctly bound S-only manifest; membership is checked again at apply.
    manifest['rules_sha256']=narrowed['_sha256']
    path.write_text(json.dumps(manifest))
    result=do_apply(path,narrowed,doc)
    assert not calls and {r['why'] for r in result['skipped']}=={'standing_rule_not_listed'}


def test_named_gb_cap_fields_and_approval_identity_are_enforced(world,monkeypatch):
    path,_,doc,calls=planned(world,monkeypatch)
    world[1]['standing_apply']['approved_by']='DIFFERENT'
    assert do_apply(path,world[1],doc)['refused']=='standing_approval_pending'
    home,rules,p,cfg=world
    cfg['standing_apply']['max_gb_per_run']=41
    p.write_text(json.dumps(cfg))
    with pytest.raises(DH.RulesError,match='standing_cap_units'):
        DH.load_rules(p,home=home)
    assert not calls


@pytest.mark.parametrize('standing',[False,True])
def test_two_hour_manifest_limit_applies_to_manual_grant_and_standing(world,monkeypatch,standing):
    path,_,doc,calls=planned(world,monkeypatch)
    monkeypatch.setattr(DH,'build_context',lambda rules,now:{'now':now,'cwds':set(),'refs':[]})
    # Freeze elapsed processing only for the exact-boundary proof; real code also checks elapsed time per item.
    monkeypatch.setattr(DH.time,'monotonic',lambda:1000.0)
    kwargs={'grant':None if standing else 'fixture-manual-grant','run_id':'fixture' if standing else None,
            'standing':standing,'evidence':doc,'manifest_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'progress_sink':lambda _:None}
    at=DH.apply(path,world[1],NOW+timedelta(hours=2),**kwargs)
    assert at['refused'] is None
    after=DH.apply(path,world[1],NOW+timedelta(hours=2,microseconds=1),**kwargs)
    assert after['refused']=='manifest_stale'


def test_activation_cli_preview_and_unbound_write_leave_fixture_configs_unchanged(tmp_path):
    mod,packet,config,review=activation_fixture(tmp_path)
    review_path=tmp_path/'synthetic-review.json'
    review_path.write_text(json.dumps(review))
    args=['--config-dir',str(config),'--review-file',str(review_path)]
    before={p.name:p.read_bytes() for p in config.iterdir()}
    assert mod.main(args)==0
    assert mod.main([*args,'--write','--plan-sha256','wrong'])==1
    assert before=={p.name:p.read_bytes() for p in config.iterdir()}


def test_activation_cli_exact_source_write_is_contained_in_owned_fixture(tmp_path):
    mod,packet,config,review=activation_fixture(tmp_path)
    review_path=tmp_path/'synthetic-review.json'
    review_path.write_text(json.dumps(review))
    encoded,digest=mod.promotion(config,packet,review)
    args=['--config-dir',str(config),'--review-file',str(review_path),'--write','--plan-sha256',digest]
    assert mod.main(args)==0
    assert {p.name:p.read_bytes() for p in config.iterdir()}==encoded
    assert mod.main(args)==1  # stale/replayed source write cannot pass the old pins
    assert json.loads((ROOT/'config/disk_hygiene_rules.json').read_text())['standing_apply']['enabled'] is False


def test_old_review_cannot_authorize_changed_source_with_regenerated_pins(tmp_path):
    mod,packet,config,review=activation_fixture(tmp_path)
    owned_packet=tmp_path/'owned-packet'
    owned_packet.mkdir()
    for name in ('activation-input-sha256.json','standing-contract.draft.json'):
        (owned_packet/name).write_bytes((packet/name).read_bytes())
    source=config/'disk_hygiene_rules.json'
    source.write_text(source.read_text()+' ')
    pins_path=owned_packet/'activation-input-sha256.json'
    pins=json.loads(pins_path.read_text())
    pins[source.name]=hashlib.sha256(source.read_bytes()).hexdigest()
    pins_path.write_text(json.dumps(pins,indent=2)+'\n')
    with pytest.raises(ValueError,match='review_source_pins_mismatch'):
        mod.promotion(config,owned_packet,review)
    reviewed_new_pins=dict(review,source_config_pins_sha256=hashlib.sha256(pins_path.read_bytes()).hexdigest())
    with pytest.raises(ValueError,match='review_rules_sha_mismatch'):
        mod.promotion(config,owned_packet,reviewed_new_pins)
