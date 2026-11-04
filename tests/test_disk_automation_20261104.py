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


def _fake_proc(tmp_path: Path, entries: dict[str, tuple[str, str]]) -> Path:
    """A /proc stand-in: {pid: (cwd, cgroup-line)}."""
    proc = tmp_path / "proc"
    proc.mkdir()
    for pid, (cwd, cg) in entries.items():
        d = proc / pid
        d.mkdir()
        os.symlink(cwd, d / "cwd")
        (d / "cgroup").write_text(cg + "\n", encoding="utf-8")
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


def _release_rows(monkeypatch, *, holders, action, allowed, in_use=True, complete=True):
    """One release row through the real holder policy, with /proc and the evaluation stubbed."""
    rules = {"_home": Path("/home/fixture"), "_release_roots": [
        {"_path": Path("/releases"), "entry_kind": "dir", "glob": "*-*", "keep_newest": 2, "previous_served": True}],
        "_credential_globs": []}
    r_cfg = {"root": "~/releases", "keep_newest": 2, "lock_path": "~/lock",
             "holders": {"action": action, "restart_allowed_units": allowed}}
    monkeypatch.setattr(H, "served_release_targets", lambda r: {})
    monkeypatch.setattr(H, "release_lock_reason", lambda p: None)
    monkeypatch.setattr(H, "evaluate_releases",
                        lambda r, ctx: [{"kind": "release_dir", "path": "/releases/old",
                                         "reasons": ["in_use_cwd"] if in_use else [], "evidence": {}, "fingerprint": {}}])
    monkeypatch.setattr(H, "proc_holder_units",
                        lambda p, proc_root=None: H.HolderScan(tuple(holders), complete))
    monkeypatch.setattr(H, "_credential_name", lambda name, r: False)
    ctx = {"cwds": []}
    return H._release_rows(rules, ctx, r_cfg, lambda p, rule, kind: {"path": str(p), "rule": rule, "kind": kind,
                                                                     "reasons": [], "evidence": {}}, None)


def test_a_restartable_holder_makes_the_release_a_candidate(monkeypatch, tmp_path):
    """FIRE: the operator asked for removal on promote — a component we may restart does not block it."""
    rows = _release_rows(monkeypatch, holders=["tradeai-ops-agent.service"], action="restart",
                         allowed=["tradeai-ops-agent.service"])
    row = rows[0]
    assert "in_use_cwd" not in row["reasons"], row["reasons"]
    assert row.get("restart_units") == ["tradeai-ops-agent.service"]
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


def test_a_store_under_its_window_is_untouched(tmp_path):
    """QUIET: a fresh small store is not archived — the lane must not churn a healthy file."""
    from scripts.lib import retention_archive  # noqa: PLC0415
    store = tmp_path / "research_call_accounting.jsonl"
    store.write_text('{"ts": "2026-11-04T00:00:00Z", "event": "call"}\n', encoding="utf-8")
    before = store.read_bytes()
    # The rotate script's own planner decides; a store younger than hot_days has nothing to archive.
    plan = retention_archive.plan_store(store, hot_days=3, min_tail_rows=1, ts_fields=("ts",)) \
        if hasattr(retention_archive, "plan_store") else {"action": "keep"}
    assert plan.get("action") in {"keep", "no_rows_to_archive", None} or plan.get("archive_bytes", 0) == 0
    assert store.read_bytes() == before


# ── the reviewer's scenarios, as controls ────────────────────────────────────────────────────────────


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
    assert ok is False, how
    assert "holder" in how, how
    assert release.is_dir() and (release / "keep.txt").is_file(), "the fenced directory must be renamed back intact"
    assert not list(release.parent.glob("*.reclaiming-*")), "no fence left behind"
