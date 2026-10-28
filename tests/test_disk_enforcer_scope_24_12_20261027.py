"""disk_hygiene_enforcer.py removes nothing outside AGENTS.md §24.12 (2026-10-27).

§24.12 ("Disk hygiene: the only automated deletion") lets exactly scripts/disk_hygiene.py under
config/disk_hygiene_rules.json (n8n lane `disk-hygiene`, or the operator CLI) and the host /tmp lanes remove
anything, puts backups out of scope, and states as an open gap that scripts/disk_hygiene_enforcer.py "already
removes release trees and backups under --apply" and is "named as the disk_critical remedy in
config/health_agent_policy.json". §0 rule 6: never delete outside the exception.

Pinned here:
  (a) --apply --backups-only removes nothing, reports REFUSED_OUTSIDE_24_12 and exits 77;
  (b) --apply --releases-only removes nothing (release-local files included; the archive helper is never called);
  (c) the dry run is unchanged (same keys, same plan) and apply's plan IS the dry run's plan;
  (d) the health policy's disk_critical remedy no longer invokes the enforcer: report + page through
      never_auto_remediate, no retry, no queue item, a stale queued retry is shed;
  plus the enforcer holds no removal primitive and never shells out, and the two callers that ran its apply
  (disk_pressure_guard, weekly_disk_cleanup_notify) request the plan only and say so.

No host path is read or written: tmp dirs, a patched policy loader, stubbed transports.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENFORCER = ROOT / "scripts" / "disk_hygiene_enforcer.py"
POLICY = ROOT / "config" / "health_agent_policy.json"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

REFUSED = "REFUSED_OUTSIDE_24_12"
#: The top-level keys a dry run printed before 2026-10-27. A dry run must print exactly these.
DRY_RUN_KEYS = {"ts", "disk", "releases_plan", "releases_result", "backups_plan", "backups_result", "dry_run", "ok"}


def _load(path: Path, name: str):
    """Load by explicit path so a same-named module from another tree cannot be asserted against."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def hy():
    return _load(ENFORCER, "_disk_hygiene_enforcer_scope_under_test")


@pytest.fixture
def fixture(tmp_path, hy, monkeypatch):
    """Five releases (CURRENT -> newest, keep_n 2 => 2 planned removals), each with release-local data, and a
    backup pile with one stale and one fresh file. The enforcer's policy loader is pointed at it."""
    rel = tmp_path / "portfolio-server"
    rel.mkdir()
    dirs = []
    for i in range(5):
        d = rel / f"{i:03d}aaaa-main-exact-phase2-2026100{i}-000000"
        (d / "data" / "raw").mkdir(parents=True)
        (d / "data" / "raw" / "x.csv").write_text(f"only-in-{i}")
        (d / "state").mkdir()
        (d / "state" / "s.json").write_text(f"state-{i}")
        t = 1_700_000_000 + i * 100
        os.utime(d, (t, t))
        dirs.append(d)
    (rel / "CURRENT").symlink_to(dirs[-1])
    pile = tmp_path / "backups"
    pile.mkdir()
    old = pile / "trade_ai_backup_old.zip"
    old.write_bytes(b"o" * 4096)
    os.utime(old, (1_600_000_000, 1_600_000_000))
    (pile / "trade_ai_backup_new.zip").write_bytes(b"n" * 4096)
    policy = {
        "releases": {"root": str(rel), "glob": "*-main-exact-*", "keep_n": 2, "protect_symlinks": ["CURRENT"]},
        "stale_backup_piles": [{"path": str(pile), "max_age_days": 45}],
        "disk": {"warn_free_pct": 0, "critical_free_pct": 0, "target_path": str(tmp_path)},
    }
    monkeypatch.setattr(hy, "_load_policy", lambda: policy)
    return {"root": tmp_path, "rel": rel, "dirs": dirs, "pile": pile, "old": old}


def _tree(root: Path) -> dict[str, str]:
    """Every path under root -> sha256 of its bytes ('dir' / 'link:<target>'): a change to anything shows."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        key = p.relative_to(root).as_posix()
        if p.is_symlink():
            out[key] = f"link:{os.readlink(p)}"
        elif p.is_dir():
            out[key] = "dir"
        else:
            out[key] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _main(hy, argv: list[str], capsys) -> tuple[int, dict, str]:
    rc = hy.main(argv)
    cap = capsys.readouterr()
    return rc, json.loads(cap.out), cap.err


# ── (a) --apply --backups-only ────────────────────────────────────────────────────────────────────────


def test_apply_backups_only_removes_nothing_and_reports_the_refusal(hy, fixture, capsys):
    before = _tree(fixture["root"])
    rc, out, err = _main(hy, ["--apply", "--backups-only"], capsys)
    assert rc == hy.EXIT_REFUSED == 77
    assert _tree(fixture["root"]) == before, "a refused apply changed the tree"
    assert fixture["old"].read_bytes() == b"o" * 4096
    assert out["status"] == REFUSED and out["refused"] is True and out["removed_count"] == 0
    assert out["refusal"]["status"] == REFUSED
    assert "disk_hygiene.py" in out["refusal"]["reason"] and "§24.12" in out["refusal"]["reason"]
    assert "operator decision" in out["refusal"]["governed_route"]["backups"]
    br = out["backups_result"]
    assert br["refused"] is True and br["deleted"] == [] and br["bytes_reclaimed_est"] == 0
    assert [i["path"] for i in br["refused_items"]] == [str(fixture["old"])]
    assert all(i["action"] == "refused" for i in br["refused_items"])
    assert "releases_result" not in out
    assert err.startswith("REFUSED: ")


# ── (b) --apply --releases-only ───────────────────────────────────────────────────────────────────────


def test_apply_releases_only_removes_nothing_and_never_archives(hy, fixture, capsys, monkeypatch):
    from lib import retention_archive as ra

    def _boom(*a, **k):
        raise AssertionError("the archive-then-unlink helper must never be reached from the enforcer")

    monkeypatch.setattr(ra, "archive_files_then_unlink", _boom)
    before = _tree(fixture["root"])
    rc, out, _err = _main(hy, ["--apply", "--releases-only"], capsys)
    assert rc == 77
    assert _tree(fixture["root"]) == before
    rr = out["releases_result"]
    assert rr["refused"] is True and rr["status"] == REFUSED and rr["deleted"] == [] and rr["errors"] == []
    planned = out["releases_plan"]["delete_sample"]
    assert len(planned) == 2 and sorted(i["path"] for i in rr["refused_items"]) == sorted(planned)
    for p in planned:
        assert (Path(p) / "data" / "raw" / "x.csv").is_file() and (Path(p) / "state" / "s.json").is_file()
    assert fixture["dirs"][-1].is_dir(), "CURRENT's target"
    assert "backups_result" not in out


def test_full_apply_removes_nothing(hy, fixture, capsys):
    before = _tree(fixture["root"])
    rc, out, _err = _main(hy, ["--apply"], capsys)
    assert rc == 77 and out["status"] == REFUSED
    assert _tree(fixture["root"]) == before
    assert "postgres_remediate" not in out, "the post-apply restart went with the removal"


def test_the_low_level_apply_functions_refuse_for_direct_importers(hy, fixture):
    """A caller importing the module and passing dry_run=False directly gets the refusal too."""
    plan = hy.plan_releases(hy._load_policy()["releases"])
    bplan = hy.plan_stale_backups(hy._load_policy()["stale_backup_piles"])
    before = _tree(fixture["root"])
    assert hy.apply_release_deletes(plan, dry_run=False)["refused"] is True
    assert hy.apply_stale_backup_deletes(bplan, dry_run=False)["refused"] is True
    assert _tree(fixture["root"]) == before


# ── (c) the dry run is unchanged ──────────────────────────────────────────────────────────────────────


def test_dry_run_is_unchanged(hy, fixture, capsys):
    before = _tree(fixture["root"])
    rc, out, err = _main(hy, ["--dry-run"], capsys)
    assert rc == 0 and err == ""
    assert set(out) == DRY_RUN_KEYS, "a dry run grew or lost a top-level key"
    assert out["dry_run"] is True
    rr, br = out["releases_result"], out["backups_result"]
    assert set(rr) == {"dry_run", "deleted", "errors", "bytes_reclaimed_est", "ok"}
    assert set(br) == {"dry_run", "deleted", "errors", "bytes_reclaimed_est", "ok"}
    assert [e["action"] for e in rr["deleted"]] == ["would_delete", "would_delete"]
    assert all(e["bytes"] == 0 and e["release_local"]["files"] == 2 for e in rr["deleted"])
    assert [e["path"] for e in br["deleted"]] == [str(fixture["old"])] and br["bytes_reclaimed_est"] == 4096
    assert _tree(fixture["root"]) == before


def test_apply_prints_exactly_the_dry_run_plan(hy, fixture, capsys):
    _rc, dry, _ = _main(hy, ["--dry-run"], capsys)
    _rc, app, _ = _main(hy, ["--apply"], capsys)
    assert app["releases_plan"] == dry["releases_plan"] and app["backups_plan"] == dry["backups_plan"]
    for key in ("releases_result", "backups_result"):
        assert [{**e, "action": "would_delete"} for e in app[key]["refused_items"]] == dry[key]["deleted"]


def test_status_mode_is_unchanged(hy, fixture, capsys):
    rc, out, _ = _main(hy, ["--status"], capsys)
    assert rc == 0 and set(out) == {"ts", "disk", "releases"} and out["releases"]["count"] == 5


# ── the enforcer holds no removal primitive and never shells out ──────────────────────────────────────


def test_enforcer_source_has_no_removal_primitive_and_no_subprocess():
    src = ENFORCER.read_text(encoding="utf-8")
    for forbidden in (
        "rmtree",
        ".unlink(",
        "os.remove",
        "os.rmdir",
        "archive_files_then_unlink",
        "subprocess",
        "os.system",
        "os.exec",
        "os.spawn",
        "Popen",
    ):
        assert forbidden not in src, f"disk_hygiene_enforcer.py must not contain {forbidden!r}"
    assert "disk_hygiene.py --apply" not in src, "it must never shell out to the lane's apply"


def test_cli_exit_code_is_77_end_to_end(tmp_path):
    """The real entrypoint, as the systemd unit runs it. HOME points at an empty tmp dir, so the policy's '~' paths
    resolve to nothing on this host and there is nothing to remove whatever the code did."""
    env = {**os.environ, "HOME": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, str(ENFORCER), "--apply", "--backups-only"],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(tmp_path),
    )
    assert proc.returncode == 77, proc.stderr[-400:]
    assert json.loads(proc.stdout)["status"] == REFUSED
    assert list(tmp_path.iterdir()) == []


# ── (d) the health policy's disk_critical remedy ──────────────────────────────────────────────────────


@pytest.fixture
def policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def _disk_finding() -> dict:
    return {
        "category": "infra",
        "type": "disk_critical",
        "severity": "critical",
        "message": "Disk /: 9.0GB free (1.9%) — at/below critical floor (15GB / 10% free)",
    }


def test_policy_no_longer_runs_the_enforcer_for_disk_critical(policy):
    assert "disk_critical" not in policy["remediation_map"]
    assert "disk_critical" not in policy["auto_remediate"]["finding_types"]
    assert "disk_critical" in policy["never_auto_remediate"], "report + page: operator action, never auto"
    live = {k: v for k, v in policy["remediation_map"].items() if not k.startswith("_")}
    assert not any("disk_hygiene_enforcer" in json.dumps(v) for v in live.values())
    assert "_disk_critical_note" in policy["remediation_map"], "de-mapped without saying why"
    assert "§24.12" in policy["remediation_map"]["_disk_critical_note"]


def test_policy_keeps_its_other_remedies(policy):
    """NEGATIVE CONTROL: emptying the map would also pass the test above."""
    assert policy["remediation_map"]["postgres_main_down"].endswith("remediate_postgres_main.py --apply")
    assert len([k for k in policy["remediation_map"] if not k.startswith("_")]) > 50


@pytest.fixture
def ha(monkeypatch, tmp_path, policy):
    import health_agent as mod

    monkeypatch.setattr(mod, "_POLICY", policy)  # the file policy, never a DB copy
    monkeypatch.setattr(mod, "QUEUE_FILE", tmp_path / "queue.json")
    monkeypatch.setattr(mod, "REMEDIATION_STATE", tmp_path / "remediation_state.json")
    monkeypatch.setattr(mod, "REMEDIATION_LOG", tmp_path / "remediation.jsonl")
    return mod


def test_health_agent_runs_nothing_for_disk_critical(ha, policy, monkeypatch):
    def _no_spawn(*a, **k):
        raise AssertionError("the health agent spawned a remediation for disk_critical")

    monkeypatch.setattr(ha.subprocess, "Popen", _no_spawn)
    monkeypatch.setattr(ha.subprocess, "run", _no_spawn)
    assert ha._data_source_retry_cmd(policy, "disk_critical", _disk_finding()) is None
    assert ha.run_auto_remediation(policy, [_disk_finding()]) == []


def test_health_agent_does_not_enqueue_a_retry_for_disk_critical(ha, policy):
    assert ha.enqueue_escalations(policy, [_disk_finding()]) == 0
    queued = json.loads(ha.QUEUE_FILE.read_text()) if ha.QUEUE_FILE.exists() else []
    assert not [i for i in queued if "disk_critical" in str(i.get("component"))]


def test_health_agent_reports_disk_critical_as_operator_action(ha, policy):
    f = _disk_finding()
    ha._annotate(f, policy["remediation_map"])
    assert f["action_type"] == "operator" and f["never_auto"] is True and f["actionable"] is True
    assert "Auto-retry" not in f["recommended_action"]


def test_escalation_handler_sheds_a_stale_queued_enforcer_retry(policy):
    """A disk_critical item queued before this change still carries `disk_hygiene_enforcer.py --apply`. The policy,
    not the queue snapshot, decides what is retryable: it must be shed, not re-run."""
    esc = _load(ROOT / "scripts" / "claude_escalation_handler.py", "_escalation_handler_scope_under_test")
    types = {k for k in policy["remediation_map"] if not k.startswith("_")}
    item = {
        "component": "health:infra:disk_critical",
        "fixable": True,
        "source": "health_agent",
        "retry_cmd": ".venv/bin/python scripts/disk_hygiene_enforcer.py --apply",
        "_attempts": 3,
    }
    assert esc.is_review_only(item, types) is True
    # and the handler's allowlist never admitted the enforcer (checked on the patterns themselves, so an env-guard
    # refusal cannot make this pass for the wrong reason)
    import yaml

    allow = yaml.safe_load((ROOT / "config" / "claude_escalation_allowlist.yaml").read_text(encoding="utf-8"))
    assert not [p for p in allow["allowed_script_patterns"] if p in item["retry_cmd"]]


# ── the callers request the plan only ─────────────────────────────────────────────────────────────────


class _Proc:
    def __init__(self, payload: dict, rc: int = 0):
        self.stdout = json.dumps(payload)
        self.stderr = ""
        self.returncode = rc


def _dry_payload() -> dict:
    entry = {"path": "/x/000-main-exact-a", "bytes": 0, "action": "would_delete", "release_local": {"files": 0}}
    return {
        "releases_result": {"dry_run": True, "deleted": [entry], "errors": [], "bytes_reclaimed_est": 0, "ok": True}
    }


def test_pressure_guard_asks_the_enforcer_for_its_plan_only(monkeypatch):
    import disk_pressure_guard as g

    seen: list[list[str]] = []

    def _run(argv, **k):
        seen.append([str(a) for a in argv])
        return _Proc(_dry_payload())

    monkeypatch.setattr(g.subprocess, "run", _run)
    for dry in (True, False):
        res = g.run_enforcer(dry_run=dry)
        assert res["_deleted_count"] == 0, "a would_delete entry is not a deletion"
        assert res["_would_remove_count"] == 1 and res["_reclaimed"] == 0
    assert seen and all("--dry-run" in a and "--apply" not in a for a in seen), seen


def test_pressure_guard_pages_the_governed_route(monkeypatch, tmp_path, capsys):
    import disk_pressure_guard as g
    from lib import alert_condition_state as acs

    sent: list[str] = []
    monkeypatch.setattr(g, "RECEIPT", tmp_path / "receipts.jsonl")
    # Free space rises 1 GiB between the two reads from unrelated host activity: the guard did none of it.
    reads = iter([(91.0, 40 * 1024**3, 468 * 1024**3), (90.8, 41 * 1024**3, 468 * 1024**3)])
    monkeypatch.setattr(g, "disk_used_pct", lambda path="/": next(reads))
    monkeypatch.setattr(g, "run_enforcer", lambda **k: {"_would_remove_count": 3, "_deleted_count": 0})
    monkeypatch.setattr(acs, "observe", lambda *a, **k: {"action": "alert", "notify": True})
    monkeypatch.setattr(g, "notify", lambda text: sent.append(text) or "accepted")
    assert g.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["removal"].startswith("none") and sent
    assert "disk-hygiene lane owns reclaim" in sent[0] and "scripts/disk_hygiene.py --report" in sent[0]
    assert "reclaimed" not in sent[0], "the page must not claim a reclaim the guard no longer attempts"
    # the receipt labels the change as observed, never as this run's reclaim
    assert "reclaimed" not in out and out["free_space_delta_observed_gb"] == 1.0


def test_weekly_apply_runs_plans_only_and_keeps_preclean_dirs(monkeypatch, tmp_path):
    import weekly_disk_cleanup_notify as w

    home = tmp_path / "home"
    stale = home / "backups" / "deploy-tree-preclean-20260101"
    stale.mkdir(parents=True)
    (stale / "f.txt").write_text("keep me")
    os.utime(stale, (1_600_000_000, 1_600_000_000))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(w, "ROOT", tmp_path)
    monkeypatch.setattr(w, "_disk", lambda: {"free_gb": 9.0, "used_pct": 98.0, "free_pct": 2.0, "level": "critical"})
    launched: list[str] = []

    def _run_json(argv, timeout=60):
        launched.append(" ".join(str(a) for a in argv))
        return False, {**_dry_payload(), "ok": False, "backups_result": {"deleted": [], "errors": []}}

    monkeypatch.setattr(w, "_run_json", _run_json)
    summary = w.run(apply=True, notify=False)
    assert launched and all("--dry-run" in a and "--apply" not in a for a in launched), launched
    assert stale.is_dir() and (stale / "f.txt").read_text() == "keep me"
    steps = {s["name"]: s for s in summary["steps"]}
    assert steps["disk_hygiene"]["ok"] is True, "a critical-floor dry-run exit is the enforcer's alarm, not a failure"
    assert steps["disk_hygiene"]["detail"].startswith(REFUSED)
    assert (
        steps["backup_preclean_dirs"]["detail"].startswith(REFUSED)
        and "listed=1" in steps["backup_preclean_dirs"]["detail"]
    )
    assert summary["bytes_reclaimed_est"] == 0 and summary["removal"].startswith("none")
    assert w.REMOVAL_LINE in w.build_telegram(summary)


def test_weekly_dry_run_is_unchanged(monkeypatch, tmp_path):
    import weekly_disk_cleanup_notify as w

    home = tmp_path / "home"
    stale = home / "backups" / "deploy-tree-preclean-20260101"
    stale.mkdir(parents=True)
    os.utime(stale, (1_600_000_000, 1_600_000_000))
    monkeypatch.setenv("HOME", str(home))
    res = w._clean_preclean_dirs(dry_run=True)
    assert set(res) == {"ok", "deleted", "bytes_reclaimed_est", "errors", "max_age_days"}
    assert [d["action"] for d in res["deleted"]] == ["would_delete"] and stale.is_dir()
    assert w.REMOVAL_LINE not in w.build_telegram(
        {
            "ok": True,
            "apply": False,
            "ts": "2026-10-27T00:00:00+00:00",
            "disk_before": {"free_gb": 1, "used_pct": 1, "level": "ok"},
            "disk_after": {"free_gb": 1, "used_pct": 1, "level": "ok"},
            "steps": [],
        }
    )
