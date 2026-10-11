"""Shadow dry_run fires never take the lane's live lock (2026-10-11, Agent LK, LOCK_STEAL finding).

Defect: the executor wrapped every mode in the lane's own lock, the same ``flock -n`` file the cron line holds. The
dispatcher fires a shadow dry_run in the same minute as the cron slot it shadows, so whichever process reached the
lock first won; when the dry_run won, the real cron run exited 1 silently (2026-10-11 12:50 ET
research-insight-extractor; 8 real runs on 6 lanes in ~17 h — ~/n8n-maturity-verification/LOCK_STEAL_MEASURE.md).

Fix (scripts/n8n_run_executor.py ``lock_path_for``): ``dry_run`` takes ``<lock>.dryrun``; ``live`` (canary/cutover)
keeps the shared lock, which is the intended no-double-run guard. The receipt records the lock used.

Hermetic: tmp locks, a real ``flock`` binary and the real safe_flock.sh with ``/bin/true``-style commands, fake rows.
No live ledger, no crontab, no /tmp lock of a real lane is touched.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import lane_dispatch as LD  # noqa: E402

ALLOWLIST = json.loads((ROOT / "config" / "n8n_run_allowlist.json").read_text(encoding="utf-8"))["lanes"]


def _entry(lock: Path, kind: str = "flock", *, live_arg=(), dry_arg=("--dry-run",)) -> dict:
    return {
        "lane_id": "iso-lane",
        "command": ["/bin/echo", "ran"],
        "dry_run_arg": list(dry_arg),
        "live_arg": list(live_arg) if live_arg is not None else None,
        "lock": str(lock),
        "lock_kind": kind,
        "timeout_s": 30,
        "market_gate": False,
        "output_signal": "data/runtime/iso_lane_last.json",
    }


@pytest.fixture
def code_root(tmp_path, monkeypatch):
    code = tmp_path / "code"
    (code / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "safe_flock.sh", code / "scripts" / "safe_flock.sh")
    monkeypatch.setenv("SAFE_FLOCK_LOG_DIR", str(tmp_path / "flock-logs"))  # never the repo's logs/
    return code


def _run(entry, mode, tmp_path, code_root, stage_rows=X.NO_STAGE_CLAMP, requested=None):
    row = {"run_id": f"t:{mode}", "lane_id": entry["lane_id"], "mode": requested or mode}
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "SAFE_FLOCK_LOG_DIR": str(tmp_path / "flock-logs")}
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    return X.execute(row, entry, env=env, state_root=state, code_root=code_root, stage_rows=stage_rows)


def _held(lock: Path) -> bool:
    with open(lock, "a") as probe:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(probe, fcntl.LOCK_UN)
        return False


# ── pure lock selection ────────────────────────────────────────────────────────────────────────────


def test_lock_path_for_dry_run_is_the_dryrun_sibling_and_live_is_the_shared_lock():
    e = _entry(Path("/tmp/x.lock"))
    assert X.DRY_RUN_LOCK_SUFFIX == ".dryrun"
    assert X.lock_path_for(e, "dry_run") == "/tmp/x.lock.dryrun"
    assert X.lock_path_for(e, "live") == "/tmp/x.lock"


@pytest.mark.parametrize("kind", ["flock", "safe_flock"])
def test_build_argv_wraps_dry_run_in_the_dryrun_lock_and_live_in_the_live_lock(kind):
    e = _entry(Path("/tmp/x.lock"), kind)
    kw = dict(env={}, state_root=Path("/s"), code_root=Path("/c"))
    dry, live = X.build_argv(e, "dry_run", **kw), X.build_argv(e, "live", **kw)
    if kind == "flock":
        assert dry[:5] == ["flock", "-n", "-E", "75", "/tmp/x.lock.dryrun"]
        assert live[:5] == ["flock", "-n", "-E", "75", "/tmp/x.lock"]
    else:
        assert dry[:3] == ["bash", "scripts/safe_flock.sh", "/tmp/x.lock.dryrun"]
        assert live[:3] == ["bash", "scripts/safe_flock.sh", "/tmp/x.lock"]


def test_a_live_lock_named_like_a_dry_run_lock_is_refused():
    assert X.validate_entry(_entry(Path("/tmp/x.lock.dryrun"))) == "bad_lock"


def test_no_dry_run_lock_collides_with_any_live_lock_in_the_repo_allowlist():
    live = {e["lock"] for e in ALLOWLIST}
    dry = {X.lock_path_for(e, "dry_run") for e in ALLOWLIST if e.get("dry_run_arg") is not None}
    assert dry and not (dry & live)
    for e in ALLOWLIST:
        assert X.lock_path_for(e, "live") == e["lock"]
        assert not e["lock"].endswith(X.DRY_RUN_LOCK_SUFFIX), e["lane_id"]
        # safe_flock's pid/meta siblings of the dry lock never land on a live lock either
        d = X.lock_path_for(e, "dry_run")
        assert {d + ".pid", d + ".meta"}.isdisjoint(live)


def test_canary_lock_match_stays_about_the_live_lock():
    row = {"scheduler": {"command_text": "cd $PROJ && flock -n /tmp/x.lock $PY scripts/x.py"}}
    ok, why = LD.r1_canary_lock_matches(row, _entry(Path("/tmp/x.lock")))
    assert ok and why == "canary_on_cron"


# ── real locks ─────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["flock", "safe_flock"])
def test_dry_run_runs_while_the_live_lock_is_held_and_never_touches_it(tmp_path, code_root, kind):
    lock = tmp_path / "locks" / "lane.lock"
    lock.parent.mkdir()
    entry = _entry(lock, kind)
    with open(lock, "w") as held:  # the live cron line's `flock -n` holds it
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        before = lock.stat()
        r = _run(entry, "dry_run", tmp_path, code_root)
        assert _held(lock)  # still the cron line's, unaffected
    assert r["state"] == "RUN_DONE" and r["lock_skipped"] is False and r["exit_code"] == 0
    assert r["lock"] == {"path": f"{lock}.dryrun", "scope": "dryrun", "kind": kind}
    after = lock.stat()
    assert (after.st_ino, after.st_mtime_ns, after.st_size) == (before.st_ino, before.st_mtime_ns, before.st_size)
    assert not Path(f"{lock}.pid").exists()  # safe_flock never wrote a pid file for the live lock


@pytest.mark.parametrize("kind", ["flock", "safe_flock"])
def test_dry_run_with_no_live_lock_file_never_creates_it(tmp_path, code_root, kind):
    lock = tmp_path / "lane.lock"
    r = _run(_entry(lock, kind), "dry_run", tmp_path, code_root)
    assert r["state"] == "RUN_DONE"
    assert not lock.exists() and not Path(f"{lock}.pid").exists()


def test_live_fire_still_contends_on_the_live_lock(tmp_path, code_root):
    lock = tmp_path / "lane.lock"
    entry = _entry(lock, "flock")
    with open(lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = _run(entry, "live", tmp_path, code_root)
    assert r["state"] == "RUN_SKIPPED_LOCK" and r["reason"] == "flock_held"
    assert r["lock"] == {"path": str(lock), "scope": "live", "kind": "flock"}
    r2 = _run(entry, "live", tmp_path, code_root)  # released -> runs
    assert r2["state"] == "RUN_DONE"


def test_a_held_dry_run_lock_skips_the_next_dry_run_but_never_the_live_fire(tmp_path, code_root):
    lock = tmp_path / "lane.lock"
    entry = _entry(lock, "flock")
    with open(f"{lock}.dryrun", "w") as held:  # an earlier dry run still in flight
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert _run(entry, "dry_run", tmp_path, code_root)["state"] == "RUN_SKIPPED_LOCK"
        assert _run(entry, "live", tmp_path, code_root)["state"] == "RUN_DONE"


def test_a_live_request_clamped_to_dry_run_takes_the_dryrun_lock(tmp_path, code_root):
    lock = tmp_path / "lane.lock"
    entry = _entry(lock, "flock")
    rows = [{"lane_id": "iso-lane", "scheduler": {"kind": "cron", "stage": "shadow"}, "dispatch": {"mode": "dry_run"}}]
    with open(lock, "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        r = _run(entry, "live", tmp_path, code_root, stage_rows=rows)
    assert r["requested_mode"] == "live" and r["mode"] == "dry_run" and r["stage_clamp"]["clamped"] is True
    assert r["state"] == "RUN_DONE" and r["lock"]["scope"] == "dryrun" and r["argv"][4] == f"{lock}.dryrun"
