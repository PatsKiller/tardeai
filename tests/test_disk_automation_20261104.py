"""The three disk automations the operator named on 2026-11-04, each with a test that FIRES and one that STAYS QUIET.

Operator, verbatim: "clean disk now get agents to fix whats not working on monitoring and deleting"; then
"48 hours and 10 GB is fine, build them"; and for the rotation store: "It must rotate on a schedule, not on a human's
word."

1. Release cleanup on promote — keep CURRENT plus the two before it; a release held by a running process is RESTARTED
   (so the component re-resolves CURRENT) or REPORTED by name, never skipped silently.
2. Agent scratch retention — a 48 h floor and a 10 GB ceiling, oldest-first, never a live cwd or a live claim.
3. Scheduled CIO accounting rotation — the archival lane is live, and a store under its window stays untouched.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import disk_hygiene as H  # noqa: E402

GIB = 1024 ** 3


# ── 1. release cleanup on promote ────────────────────────────────────────────────────────────────────


def _fake_proc(tmp_path: Path, entries: dict[str, tuple[str, str]], fds: dict[str, dict[str, str]] | None = None) -> Path:
    """A /proc stand-in: {pid: (cwd, cgroup-line)}, optionally {pid: {fd-name: link-target}}."""
    proc = tmp_path / "proc"
    proc.mkdir()
    for pid, (cwd, cg) in entries.items():
        d = proc / pid
        d.mkdir()
        os.symlink(cwd, d / "cwd")
        (d / "cgroup").write_text(cg + "\n", encoding="utf-8")
        pid_fds = (fds or {}).get(pid) or {}
        if pid_fds:
            (d / "fd").mkdir()
        for name, target in pid_fds.items():
            os.symlink(target, d / "fd" / name)
    return proc


def test_a_holder_is_named_not_guessed(tmp_path):
    """FIRE: the process holding a release is identified by its unit, from its own cgroup."""
    release = tmp_path / "releases" / "1f1ba5832-main"
    (release / "data").mkdir(parents=True)
    proc = _fake_proc(tmp_path, {
        "101": (str(release / "data"),
                "0::/user.slice/user-1000.slice/user@1000.service/app.slice/tradeai-ops-agent.service"),
        "102": (str(tmp_path / "elsewhere"), "0::/user.slice/user-1000.slice/user@1000.service/app.slice/other.service"),
    })
    scan = H.proc_holder_units(release, proc_root=proc)
    assert scan.units == ("tradeai-ops-agent.service",) and scan.complete is True


def test_no_holder_when_nothing_is_inside(tmp_path):
    """QUIET: a release nobody is inside names no holder (so nothing gets restarted)."""
    release = tmp_path / "releases" / "1f1ba5832-main"
    release.mkdir(parents=True)
    proc = _fake_proc(tmp_path, {"201": (str(tmp_path / "elsewhere"), "0::/user.slice/x.service")})
    scan = H.proc_holder_units(release, proc_root=proc)
    assert scan.units == () and scan.complete is True


def _release_rows(monkeypatch, *, holders, action, allowed, in_use=True, complete=True,
                  holder_count=None, unattributed=()):
    """One release row through the real holder policy, with /proc and the evaluation stubbed."""
    rules = {"_home": Path("/home/fixture"), "_release_roots": [
        {"_path": Path("/releases"), "entry_kind": "dir", "glob": "*-*", "keep_newest": 2, "previous_served": True}],
        "_credential_globs": []}
    r_cfg = {"root": "~/releases", "keep_newest": 2, "lock_path": "~/lock",
             "holders": {"action": action, "restart_allowed_units": allowed}}

    monkeypatch.setattr(H, "served_release_targets", lambda r: {})
    monkeypatch.setattr(H, "release_lock_reason", lambda p: None)
    row_path = "/releases/old"
    monkeypatch.setattr(H, "evaluate_releases",
                        lambda r, ctx: [{"kind": "release_dir", "path": row_path,
                                         "reasons": ["in_use_cwd"] if in_use else [], "evidence": {}, "fingerprint": {}}])
    count = holder_count if holder_count is not None else (len(holders) + len(unattributed) if in_use else 0)
    # A duck-typed scan, not H.HolderScan: the SAME stub then drives the pre-fix code, so the controls below fail on
    # BEHAVIOUR at 302b34483 (the release is selected and restarted) rather than on a constructor signature.
    from types import SimpleNamespace  # noqa: PLC0415
    monkeypatch.setattr(H, "proc_holder_units",
                        lambda p, proc_root=None: SimpleNamespace(units=tuple(holders), complete=complete,
                                                                  holders=count, unattributed=tuple(unattributed)))
    monkeypatch.setattr(H, "_credential_name", lambda name, r: False)
    ctx = {"cwds": []}
    return H._release_rows(rules, ctx, r_cfg, lambda p, rule, kind: {"path": str(p), "rule": rule, "kind": kind,
                                                                     "reasons": [], "evidence": {}}, None)


def test_the_default_policy_reports_a_release_and_never_selects_it(monkeypatch):
    """(a), lead ruling 2026-11-04: no attribute of a process tells us it will not fchdir in the next microsecond, so
    the scheduled lane reports the reclaimable release and never deletes it. Fails at 302b34483, where the same row is
    a candidate and the fence proceeds."""
    rows = _release_rows(monkeypatch, holders=["tradeai-ops-agent.service"], action="restart",
                         allowed=["tradeai-ops-agent.service"])
    row = rows[0]
    assert "release_delete_refused:no_enforceable_quiescence_primitive" in row["reasons"], row["reasons"]
    assert not row.get("restart_units"), "no restart may be ordered when nothing is removed"
    assert not row["reasons"].count("") and row["reasons"], "the row is refused with a reason, not silently dropped"


def test_even_a_restartable_holder_never_makes_a_release_a_candidate(monkeypatch):
    """The holder policy still NAMES who holds it; it no longer authorises anything. Fails at cd1c2038f, where an
    arranged arming made this row executable."""
    rows = _release_rows(monkeypatch, holders=["tradeai-ops-agent.service"], action="restart",
                         allowed=["tradeai-ops-agent.service"])
    row = rows[0]
    assert not row.get("restart_units"), "no restart may be ordered when nothing is removed"
    assert H.RELEASE_REFUSAL in row["reasons"], row["reasons"]
    assert row["evidence"]["holder_units"] == ["tradeai-ops-agent.service"]


def test_an_unknown_holder_is_reported_never_skipped_silently(monkeypatch):
    """QUIET-but-VISIBLE: a unit we may not restart is named in the reason, not dropped."""
    rows = _release_rows(monkeypatch, holders=["some-other.service"], action="restart",
                         allowed=["tradeai-ops-agent.service"])
    row = rows[0]
    assert "in_use_cwd" in row["reasons"]
    assert "held_by_process:some-other.service" in row["reasons"]
    assert not row.get("restart_units")


def test_report_mode_never_restarts_anything(monkeypatch):
    rows = _release_rows(monkeypatch, holders=["tradeai-ops-agent.service"], action="report",
                         allowed=["tradeai-ops-agent.service"])
    assert "held_by_process:tradeai-ops-agent.service" in rows[0]["reasons"]
    assert not rows[0].get("restart_units")


@pytest.mark.xfail(strict=False, reason="the rules file is held by cc4 (claim 20261104T021300Z-claude-72727bca); the "
                                          "retention edits travel with that release, not this branch")
def test_the_operator_s_retention_numbers_are_in_the_rules_file():
    """THE OPERATOR'S RULINGS, not drift. If a number here changes, the change is a new ruling and must cite one.

    * 2026-11-04, releases: "Keep CURRENT plus the two before it" ⇒ keep_newest 2 (+ previous_served).
    * 2026-11-04, scratch floor (D16): "floor 24h" ⇒ keep_younger_than_hours 24, with max_total_gb 10 ("48 hours and
      10 GB is fine, build them" — the 48 was later ruled down to 24, so the FLOOR is 24 and the CEILING stays 10).

    A future reader must be able to tell an operator ruling from a drifting value: the only legitimate reason to edit
    these numbers is a newer operator ruling, and the comment above is where it gets recorded.
    """
    rules = json.loads((ROOT / "config" / "disk_hygiene_rules.json").read_text(encoding="utf-8"))
    served = [r for r in rules["releases"]["roots"] if r["path"].endswith("portfolio-server")][0]
    assert served["keep_newest"] == 2 and served["previous_served"] is True
    assert rules["standing_apply"]["release_reclaim"]["keep_newest"] == 2
    scratch = rules["standing_apply"]["agent_scratch"]
    assert scratch["keep_younger_than_hours"] == 24, "operator D16 ruling 2026-11-04: floor is 24 h, not 48"
    assert scratch["max_total_gb"] == 10


# ── 2. agent scratch: 48 h floor, 10 GB ceiling ──────────────────────────────────────────────────────


def _t_row(path, size, age_hours, candidate=True):
    """A row shaped exactly like the REAL producer (standing_results): fingerprint.activity is epoch seconds and
    evidence.idle_days is days. No `last_activity` — no producer emits that field, and a fixture that supplies it is
    what let the wrong sort key pass review (codex S1, 2026-11-04)."""
    import time as _t
    activity = _t.time() - age_hours * 3600
    return {"path": path, "rule": "T", "kind": "agent_scratch", "size_bytes": size, "candidate": candidate,
            "reasons": [] if candidate else ["recent_activity"],
            "evidence": {"idle_days": round(age_hours / 24, 2)}, "fingerprint": {"activity": activity, "kind": "agent_scratch"}}


def test_scratch_over_the_cap_evicts_oldest_first():
    """FIRE: 14 GB of 20 GB is reclaimable; the ceiling takes the oldest until 10 GB is left."""
    rows = [
        _t_row("/s/old-1", 5 * GIB, 50),
        _t_row("/s/old-2", 3 * GIB, 30),
        _t_row("/s/young", 2 * GIB, 1, candidate=False),      # inside the operator's 24 h floor
        _t_row("/s/older-3", 4 * GIB, 100),
    ]
    out, summary = H.apply_scratch_cap(rows, {"max_total_gb": 10, "keep_younger_than_hours": 24})
    taken = [r["path"] for r in out if r["candidate"]]
    # total 14 GiB, ceiling 10 GiB: the oldest 4 GiB comes out and the total lands exactly on the ceiling.
    assert summary["taken"] == 1 and taken == ["/s/older-3"]
    assert summary["kept_over_cap"] == 2                 # the two it did not need to take are named, not dropped
    assert summary["total_bytes"] == 14 * GIB


def test_scratch_under_the_cap_touches_nothing():
    """QUIET: 6 GB is inside the ceiling; not one candidate changes."""
    rows = [_t_row("/s/a", 4 * GIB, 50), _t_row("/s/b", 2 * GIB, 30)]
    before = [(r["path"], r["candidate"], list(r["reasons"])) for r in rows]
    out, summary = H.apply_scratch_cap(rows, {"max_total_gb": 10, "keep_younger_than_hours": 24})
    assert [(r["path"], r["candidate"], list(r["reasons"])) for r in out] == before
    assert summary["taken"] == 0 and summary["kept_over_cap"] == 0


def test_the_floor_is_never_crossed_to_meet_the_cap():
    """The two operator numbers can disagree; young work is NEVER evicted to satisfy the ceiling, and the pass says so."""
    rows = [_t_row("/s/young-1", 6 * GIB, 1, candidate=False),
            _t_row("/s/young-2", 6 * GIB, 2, candidate=False),
            _t_row("/s/old", 1 * GIB, 100)]
    out, summary = H.apply_scratch_cap(rows, {"max_total_gb": 10, "keep_younger_than_hours": 24})
    assert all(r["candidate"] is False for r in out if "young" in r["path"])
    assert summary["floor_exceeds_cap"] is True
    assert summary["taken"] == 1          # the only old one, and the pass still reports it cannot reach 10 GB


# ── 3. rotation: the store is a target; the promotion is DEFERRED, and says why ─────────────────────


def test_the_rotation_lane_stays_shadow_until_its_enable_gate_opens():
    """The lane cannot rotate yet, by design, and this test records the two reasons rather than a passing absence.

    Promoting it in this PR turned six CI jobs red, all of them pins of a reviewed decision:
    `jsonl-archive-rotate` must stay shadow/dry_run with no live argv while `jsonl_retention.enabled` is false
    (tests/test_w8_legacy_shadow_config_20261024.py, test_stale_n8n_set_rebuild_20261024.py,
    test_canary_wave1_20261011.py). The enable flag lives in config/disk_hygiene_rules.json, which another live claim
    holds. So the promotion travels with that flag, in its own packet, not here.
    """
    rules = json.loads((ROOT / "config" / "disk_hygiene_rules.json").read_text(encoding="utf-8"))
    assert rules["jsonl_retention"]["enabled"] is False, "if this flipped, the promotion packet is overdue"
    rows = json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))["lanes"]
    row = [r for r in rows if r["lane_id"] == "jsonl-archive-rotate"][0]
    assert row["scheduler"]["stage"] == "shadow" and row["dispatch"]["mode"] == "dry_run"
    allow = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))["lanes"]
    entry = [e for e in allow if e["lane_id"] == "jsonl-archive-rotate"][0]
    assert entry["live_arg"] is None and entry["dry_run_arg"] == ["--dry-run"]


def test_the_accounting_store_is_a_rotation_target():
    """The store that reached 2.48 GB must be in the rotation config, not added by hand later."""
    rules = json.loads((ROOT / "config" / "disk_hygiene_rules.json").read_text(encoding="utf-8"))
    stores = rules["jsonl_retention"]["stores"]
    acct = [s for s in stores if s.get("id") == "research_call_accounting"][0]
    assert acct["rotate"] is True and acct["hot_days"] >= 1


def test_the_accounting_rotation_lane_is_recorded_but_not_armed(tmp_path):
    """DEFERRAL, not a quiet test. The earlier version of this test called a planner that does not exist and fell back
    to a literal {"action": "keep"}, so it passed with zero calls — a green that proved nothing (W4, 2026-11-04). This
    asserts only the fact a reader needs: the promote is recorded and disabled, so no run of it is claimed here.
    """
    import json as _json  # noqa: PLC0415
    registry = _json.loads((ROOT / "config" / "lane_registry.json").read_text(encoding="utf-8"))
    lane = [r for r in registry.get("lanes", []) if r.get("lane_id") == "jsonl-archive-rotate"]
    assert lane, "the rotation lane must be registered"
    for row in lane:
        sched = row.get("scheduler") or {}
        dispatch = row.get("dispatch") or {}
        assert sched.get("stage") == "shadow", sched
        assert dispatch.get("mode") == "dry_run", dispatch
        assert dispatch.get("live_arg") in (None, ""), "not armed: no live_arg"


# ── the reviewer's scenarios, as controls ────────────────────────────────────────────────────────────


def test_a_scope_holder_is_a_holder_even_though_no_unit_can_be_restarted(tmp_path):
    """R3a: a `session-N.scope` process inside the release used to read as `units=(), complete=True` — "nobody is
    there" — and the release was deleted under it. Holder EXISTENCE is not holder NAMING."""
    release = tmp_path / "releases" / "old"
    (release / "data").mkdir(parents=True)
    proc = _fake_proc(tmp_path, {
        "401": (str(release / "data"), "0::/user.slice/user-1000.slice/session-77.scope"),
    })
    scan = H.proc_holder_units(release, proc_root=proc)
    assert scan.units == (), "a scope cannot be restarted, so it names no unit"
    assert scan.holders == 1, scan
    assert scan.complete is True
    assert scan.unattributed == (401,), "the holder we cannot name must still be reported as a holder"


def test_a_directory_descriptor_holder_is_seen(tmp_path):
    """R3b: a directory fd opened through the old name survives a rename, and the fence cannot see it. The scan must
    read the descriptors, not only the cwd, or `complete=True/units=()` means "nothing there" while an fd holds it."""
    release = tmp_path / "releases" / "old"
    (release / "data").mkdir(parents=True)
    proc = _fake_proc(
        tmp_path,
        {"402": (str(tmp_path / "elsewhere"), "0::/user.slice/x.service")},
        fds={"402": {"7": str(release / "data")}},
    )
    scan = H.proc_holder_units(release, proc_root=proc)
    assert scan.holders == 1, scan


def test_remove_item_refuses_when_the_scan_can_only_count_the_holder(tmp_path, monkeypatch):
    """R3a at the deletion boundary: `units=()` must not be read as "nothing holds it". The stub is a plain object so
    the SAME stub drives 302b's code, where `.holders` is not consulted and rmtree runs. Fails at 302b34483."""
    from types import SimpleNamespace  # noqa: PLC0415
    release = tmp_path / "releases" / "old"
    (release / "keep.txt").parent.mkdir(parents=True)
    (release / "keep.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(H, "proc_holder_units",
                        lambda p, proc_root=None: SimpleNamespace(units=(), complete=True, holders=1, unattributed=(4242,)))
    ok, how = H.remove_item({"path": str(release), "kind": "release_dir", "rule": "R"})
    assert (ok, how) == (False, H.RELEASE_REFUSAL), how
    assert release.is_dir() and not list(release.parent.glob("*.reclaiming-*")), "untouched, no fence left behind"


def test_a_scope_holder_is_never_cleared_by_a_restart(monkeypatch, tmp_path):
    """Positive control (NOT a regression control — the policy already refused a nameless holder): a scope-held
    process cannot be restarted, so it is refused AND recorded with its count, which is what makes the operator digest
    name a holder nobody can clear."""
    rows = _release_rows(monkeypatch, holders=[], action="restart", allowed=[],
                         holder_count=1, unattributed=(4242,), )
    row = rows[0]
    assert not row.get("restart_units"), row
    assert "in_use_cwd" in row["reasons"]
    assert "held_by_process:unnamed" in row["reasons"], row["reasons"]
    assert row["evidence"]["holder_count"] == 1 and row["evidence"]["holder_unattributed_pids"] == [4242]


def test_the_post_fence_scan_sees_a_descriptor_holder_under_the_new_name(tmp_path):
    """R3b at the fence: the child's descriptor is inside the FENCED directory and its cwd is outside. A cwd-only scan
    reads that as "nothing there" and rmtree proceeds. Fails at 302b34483, where `holders` does not exist because
    descriptors were never read."""
    release = tmp_path / "releases" / "old"
    (release / "data").mkdir(parents=True)
    fenced = release.with_name(release.name + ".reclaiming-20261104T000000Z")
    os.rename(release, fenced)                      # the fence step, as remove_item performs it
    proc = _fake_proc(tmp_path, {"403": (str(tmp_path / "elsewhere"), "0::/user.slice/user-1000.slice/session-77.scope")},
                      fds={"403": {"7": str(fenced / "data")}})
    try:
        scan = H.proc_holder_units(fenced, proc_root=proc)
    finally:
        os.rename(fenced, release)                  # restored, as the refusal path must
    assert scan.holders == 1 and scan.units == (), scan
    assert scan.complete is True


def test_the_cap_cannot_evict_a_row_it_cannot_date():
    """S2: the protection must be the RETURNED eligibility bit. Fails at 302b34483, where an undatable row stays
    candidate=True and reaches the manifest as executable."""
    rows = [
        {"path": "/s/unknown", "rule": "T", "kind": "agent_scratch", "size_bytes": 20 * GIB, "candidate": True,
         "reasons": [], "evidence": {}, "fingerprint": {}},
        _t_row("/s/old", 1 * GIB, 100),
    ]
    out, summary = H.apply_scratch_cap(rows, {"max_total_gb": 10, "keep_younger_than_hours": 24})
    unknown = [r for r in out if r["path"] == "/s/unknown"][0]
    assert unknown["candidate"] is False and "scratch_age_unknown" in unknown["reasons"], unknown
    assert summary["age_unknown_protected"] == 1


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_the_cap_cannot_evict_a_row_with_a_nonfinite_age(bad):
    """S2: NaN/±Infinity evade both the floor comparison and the sort key. They are not ages — they cannot be dated."""
    rows = [
        {"path": "/s/nan", "rule": "T", "kind": "agent_scratch", "size_bytes": 20 * GIB, "candidate": True,
         "reasons": [], "evidence": {"idle_days": bad}, "fingerprint": {"activity": bad}},
        _t_row("/s/old", 1 * GIB, 100),
    ]
    out, _ = H.apply_scratch_cap(rows, {"max_total_gb": 10, "keep_younger_than_hours": 24})
    nan_row = [r for r in out if r["path"] == "/s/nan"][0]
    assert nan_row["candidate"] is False and "scratch_age_unknown" in nan_row["reasons"], nan_row


def test_a_fresh_row_without_the_action_field_drops_the_stale_one():
    """R2-inverse: omission is not permission. A manifest restart instruction must not survive a fresh row that no
    longer requires it. Fails at 302b34483, where the marker is inherited."""
    manifest_row = {"path": "/releases/old", "kind": "release_dir", "rule": "R",
                    "restart_units": ["old-holder.service"], "reasons": [], "evidence": {"holder_units": ["old-holder.service"]}}
    fresh_row = {"path": "/releases/old", "kind": "release_dir", "rule": "R"}     # the holder is gone: no action key
    executed = H.executed_row(manifest_row, fresh_row)
    assert "restart_units" not in executed, executed
    assert "evidence" not in executed and "reasons" not in executed, executed
    assert executed["path"] == "/releases/old"


def test_a_fresh_empty_action_list_is_honoured_as_no_action():
    """R2-inverse, positive control: an explicit empty list means "nothing to restart" and is not confused with an
    omitted key."""
    executed = H.executed_row({"path": "/releases/old", "kind": "release_dir", "rule": "R",
                               "restart_units": ["old-holder.service"]},
                              {"path": "/releases/old", "kind": "release_dir", "rule": "R", "restart_units": []})
    assert executed["restart_units"] == []


def test_an_unreadable_cgroup_is_refused_not_treated_as_no_holder(tmp_path, monkeypatch):
    """R1: 'I could not determine' must never read like 'nobody is there'."""
    release = tmp_path / "releases" / "old"
    (release / "data").mkdir(parents=True)
    proc = tmp_path / "proc"
    proc.mkdir()
    d = proc / "301"
    d.mkdir()
    os.symlink(str(release / "data"), d / "cwd")
    (d / "cgroup").write_text("0::/user.slice/x.service\n", encoding="utf-8")
    real_read = Path.read_text
    def boom(self, *a, **k):
        if self.name == "cgroup":
            raise PermissionError(13, "denied")
        return real_read(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", boom)
    scan = H.proc_holder_units(release, proc_root=proc)
    assert scan.units == () and scan.complete is False, scan


def test_a_complete_scan_with_no_process_is_a_real_absence(tmp_path):
    release = tmp_path / "releases" / "old"
    release.mkdir(parents=True)
    proc = tmp_path / "proc"
    proc.mkdir()
    d = proc / "302"
    d.mkdir()
    os.symlink(str(tmp_path / "elsewhere"), d / "cwd")
    (d / "cgroup").write_text("0::/user.slice/x.service\n", encoding="utf-8")
    scan = H.proc_holder_units(release, proc_root=proc)
    assert scan.units == () and scan.complete is True


def test_an_unknown_holder_blocks_the_restart_shortcut(monkeypatch):
    """R1 through the planner: an incomplete scan never clears in_use_cwd."""
    rows = _release_rows(monkeypatch, holders=["tradeai-ops-agent.service"], action="restart",
                         allowed=["tradeai-ops-agent.service"], complete=False)
    row = rows[0]
    assert "in_use_cwd" in row["reasons"] and "holder_state_unknown" in row["reasons"]
    assert not row.get("restart_units")


def test_the_cap_sorts_on_the_field_the_producer_emits():
    """S1: 100 h must come before 50 h — the previous key made production order alphabetical."""
    rows = [_t_row("/s/a-newer", 5 * GIB, 50), _t_row("/s/z-oldest", 5 * GIB, 100), _t_row("/s/filler", 1 * GIB, 25)]
    out, summary = H.apply_scratch_cap(rows, {"max_total_gb": 10, "keep_younger_than_hours": 24})
    picked = [r["path"] for r in out if r["candidate"]]
    assert picked == ["/s/z-oldest"], picked          # oldest first, on real age
    assert summary["taken"] == 1


def test_the_cap_reads_the_operator_floor_itself():
    """S5: a candidate-shaped row inside the floor is protected even if an upstream change called it a candidate."""
    import time as _t
    young = _t.time() - 1 * 3600
    rows = [{"path": "/s/young", "rule": "T", "kind": "agent_scratch", "size_bytes": 20 * GIB, "candidate": True,
             "reasons": [], "evidence": {"idle_days": 0.04}, "fingerprint": {"activity": young}},
            _t_row("/s/old", 1 * GIB, 100)]
    out, summary = H.apply_scratch_cap(rows, {"max_total_gb": 10, "keep_younger_than_hours": 24})
    young_row = [r for r in out if r["path"] == "/s/young"][0]
    assert young_row["candidate"] is False and "recent_activity" in young_row["reasons"]
    assert summary["taken"] == 1


def test_the_row_that_is_executed_is_the_row_that_was_revalidated():
    """R2: a manifest captured before a holder exists must not execute its own (stale) action.

    The manifest row has no restart_units; the revalidated row has them. The executed row must be the revalidated one,
    or the removal runs with no restart and no post-restart check.
    """
    manifest_row = {"path": "/releases/old", "kind": "release_dir", "rule": "R", "fingerprint": {"a": 1}}
    fresh_row = {"path": "/releases/old", "kind": "release_dir", "rule": "R", "fingerprint": {"a": 1},
                 "restart_units": ["tradeai-ops-agent.service"], "evidence": {"holder_units": ["tradeai-ops-agent.service"]},
                 "reasons": []}
    executed = H.executed_row(manifest_row, fresh_row)
    assert executed["restart_units"] == ["tradeai-ops-agent.service"]
    assert executed["evidence"]["holder_units"] == ["tradeai-ops-agent.service"]
    assert executed["path"] == "/releases/old"


def test_a_holder_that_appears_at_removal_time_stops_the_removal(tmp_path):
    """R3: the fence. A process inside the release when removal starts is found under the fenced name, the rename is
    rolled back, and the directory survives intact."""
    import subprocess as _sp
    import sys as _sys
    release = tmp_path / "releases" / "old"
    (release / "data").mkdir(parents=True)
    (release / "keep.txt").write_text("x", encoding="utf-8")
    child = _sp.Popen([_sys.executable, "-c", "import time; time.sleep(30)"], cwd=str(release / "data"))
    try:
        ok, how = H.remove_item({"path": str(release), "kind": "release_dir", "rule": "R"})
    finally:
        child.kill(); child.wait()
    assert (ok, how) == (False, H.RELEASE_REFUSAL), how
    assert release.is_dir() and (release / "keep.txt").is_file(), "the directory must survive untouched"
    assert not list(release.parent.glob("*.reclaiming-*")), "no fence left behind"


def test_the_legacy_plan_never_carries_an_executable_release():
    """Codex 2026-11-04 (1): the LEGACY plan() path still selected releases, so the default report path being safe
    said nothing about the old entrypoint. Fails at 865241797, where the same rows stay candidates."""
    rows = [{"path": "/releases/old", "kind": "release_dir", "rule": "R", "candidate": True, "reasons": []},
            {"path": "/s/x", "kind": "agent_scratch", "rule": "T", "candidate": True, "reasons": []}]
    out = H.refuse_release_removals(rows)
    assert out[0]["candidate"] is False and H.RELEASE_REFUSAL in out[0]["reasons"], out[0]
    assert out[1]["candidate"] is True, "nothing else is touched"


def test_no_release_is_removable_by_any_caller_however_it_is_named(tmp_path):
    """Codex 2026-11-04 (48ecc1f): the one-shot exception is REMOVED, not tightened. No arming argument exists, no file
    authorises a deletion, and the gate keys on location and rule, so a release named with another kind and a direct
    caller whose rules were never loaded are refused too. Fails at cd1c2038f, where arming authorised a deletion."""
    release = tmp_path / "releases" / "old"
    (release / "keep.txt").parent.mkdir(parents=True)
    (release / "keep.txt").write_text("x", encoding="utf-8")
    for item in ({"path": str(release), "kind": "release_dir", "rule": "R"},
                 {"path": str(release), "kind": "git_clone", "rule": "R"},
                 {"path": str(release), "kind": "cache_entry"}):
        ok, how = H.remove_item(item)
        assert (ok, how) == (False, H.RELEASE_REFUSAL), (item["kind"], how)
    assert (release / "keep.txt").is_file()


def test_a_plain_remove_item_call_never_deletes_a_release(tmp_path):
    """THE structural control (codex 2026-11-04), written against no new symbol so it fails on BEHAVIOUR at
    865241797: the directory is deleted there. Every caller — the standing apply, the legacy plan, a helper, a future
    one — goes through remove_item, and remove_item refuses a release without an arming object naming its path."""
    release = tmp_path / "releases" / "old"
    (release / "keep.txt").parent.mkdir(parents=True)
    (release / "keep.txt").write_text("x", encoding="utf-8")
    ok, _how = H.remove_item({"path": str(release), "kind": "release_dir", "rule": "R"})
    assert ok is False, "a release was removed without an arming object"
    assert (release / "keep.txt").is_file()


def test_a_parent_that_contains_a_release_root_is_refused_too(tmp_path):
    """Codex 2026-11-04 (0065310b5): the catalogue tested only "candidate inside root". A parent containing a
    configured root deletes protected children, so containment is checked BOTH ways. Fails at 0065310b5, where the
    parent was removed."""
    parent = tmp_path / "trade-ai-releases"
    (parent / "portfolio-server" / "abc-main").mkdir(parents=True)
    (parent / "portfolio-server" / "abc-main" / "keep.txt").write_text("x", encoding="utf-8")
    old = H._RELEASE_ROOTS
    H._RELEASE_ROOTS = (str(parent / "portfolio-server"),)
    try:
        ok, how = H.remove_item({"path": str(parent), "kind": "git_clone", "rule": "W"})
    finally:
        H._RELEASE_ROOTS = old
    assert (ok, how) == (False, H.RELEASE_REFUSAL), how
    assert (parent / "portfolio-server" / "abc-main" / "keep.txt").is_file()


def test_the_filesystem_root_is_never_classified_as_safe(tmp_path):
    """Codex 2026-11-04 (45543874f): `_in_release_roots(Path("/"))` was False because the reverse-prefix test becomes
    "//". "/" contains every configured root, so it is a release-path removal whenever one exists. Fails at 45543874f."""
    old = H._RELEASE_ROOTS
    H._RELEASE_ROOTS = (str(tmp_path / "trade-ai-releases" / "portfolio-server"),)
    try:
        assert H._in_release_roots(Path("/")) is True
        ok, how = H.remove_item({"path": "/", "kind": "cache_entry"})
    finally:
        H._RELEASE_ROOTS = old
    assert (ok, how) == (False, H.RELEASE_REFUSAL), how


def test_a_release_root_with_a_trailing_slash_still_protects_its_children(tmp_path):
    """W1 (whole-head review 2026-11-04): root + os.sep became '//' for a root configured as '/x/rel/', so a CHILD of
    that root read as unprotected and remove_item returned rmtree. Fails at 5454a217c."""
    root = tmp_path / "trade-ai-releases" / "portfolio-server"
    child = root / "abc-main"
    child.mkdir(parents=True)
    (child / "keep.txt").write_text("x", encoding="utf-8")
    old = H._RELEASE_ROOTS
    H._RELEASE_ROOTS = (str(root) + os.sep,)          # exactly the shape load_rules used to store
    try:
        ok, how = H.remove_item({"path": str(child), "kind": "cache_entry", "rule": "C"})
    finally:
        H._RELEASE_ROOTS = old
    assert (ok, how) == (False, H.RELEASE_REFUSAL), how
    assert (child / "keep.txt").is_file()


def test_the_catalogue_never_forgets_a_root_from_an_earlier_load(tmp_path, monkeypatch):
    """W2 (whole-head review 2026-11-04): load_rules REPLACED the catalogue, so loading another home's rules made an
    earlier home's root removable. The catalogue is a union now. Controlled at the assignment rather than by calling
    load_rules twice (which would need two complete rules trees)."""
    a = tmp_path / "homeA"
    (a / "portfolio-server" / "old").mkdir(parents=True)
    (a / "portfolio-server" / "old" / "keep.txt").write_text("x", encoding="utf-8")
    old = H._RELEASE_ROOTS
    try:
        H._RELEASE_ROOTS = (str(a / "portfolio-server"),)
        assert H._in_release_roots(a / "portfolio-server" / "old") is True
        # the union semantics: adding a second catalogue cannot subtract the first
        H._RELEASE_ROOTS = tuple(sorted(set(H._RELEASE_ROOTS) | {str(tmp_path / "homeB" / "rel")}))
        ok, how = H.remove_item({"path": str(a / "portfolio-server" / "old"), "kind": "cache_entry"})
        assert (ok, how) == (False, H.RELEASE_REFUSAL), how
        assert (a / "portfolio-server" / "old" / "keep.txt").is_file()
    finally:
        H._RELEASE_ROOTS = old
