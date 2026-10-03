"""Stale CIO plans expire append-only; the plan store no longer loses updates.

Operator-approved 2026-10-03: 1,010 open plans, 973 past their own revisit date,
kept the CIO Desk "Decisions" card DEGRADED. Measuring that also showed the
projection had drifted from the event log (52 cancelled plans still read draft,
7 created plans missing) because every writer rewrote the whole projection from
its own in-memory copy.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_command_center import _plan_is_open  # noqa: E402
from scripts.lib.cio_plans import CIOPlanStore  # noqa: E402

T0 = datetime.now(timezone.utc)
NOW = T0 + timedelta(days=60)


def _sweeper():
    spec = importlib.util.spec_from_file_location("expire_stale_cio_plans", ROOT / "scripts" / "expire_stale_cio_plans.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _store(tmp_path: Path) -> CIOPlanStore:
    return CIOPlanStore(tmp_path / "plans.jsonl", tmp_path / "plans_projection.json")


def _plan(store: CIOPlanStore, symbol: str, *, revisit_days: float, status: str = "draft") -> str:
    p = store.create_plan(
        situation_type="S3_REENTRY_CANDIDATE", symbols=[symbol], title=f"re-entry {symbol}",
        options=[{"id": "wait", "label": "Wait"}], recommendation="wait",
        evidence_refs=[{"domain": "reentry"}], revisit_at=(T0 + timedelta(days=revisit_days)).isoformat(),
        owner_agent="steph", status=status,
    )
    return p["plan_id"]


def _touch(store: CIOPlanStore, plan_id: str, at: datetime) -> None:
    store._append_event("PLAN_UPDATED", plan_id, {"summary": "touched", "updated_ts": at.isoformat()}, "test")


def _seed(tmp_path: Path) -> tuple[CIOPlanStore, dict[str, str]]:
    store = _store(tmp_path)
    ids = {
        "stale_draft": _plan(store, "AAA", revisit_days=1),
        "stale_proposed": _plan(store, "BBB", revisit_days=1, status="proposed"),
        "accepted": _plan(store, "CCC", revisit_days=1, status="accepted"),
        "recently_updated": _plan(store, "DDD", revisit_days=1),
        "revisit_not_overdue": _plan(store, "EEE", revisit_days=50),
    }
    _touch(store, ids["recently_updated"], NOW - timedelta(days=5))
    return store, ids


def _run(store: CIOPlanStore, tmp_path: Path, *, apply: bool = True) -> dict:
    return _sweeper().run(apply=apply, grace_days=14, limit=None, store=store, now=NOW,
                          receipts=tmp_path / "receipts.jsonl")


def test_expires_only_eligible_plans_with_the_reason(tmp_path):
    store, ids = _seed(tmp_path)
    result = _run(store, tmp_path)
    assert result["expired"] == 2
    for key in ("stale_draft", "stale_proposed"):
        plan = store.get_plan(ids[key])
        assert plan["status"] == "expired"
        assert "passed by 59d" in plan["status_reason"]
    for key in ("accepted", "recently_updated", "revisit_not_overdue"):
        assert store.get_plan(ids[key])["status"] != "expired"
    receipt = json.loads((tmp_path / "receipts.jsonl").read_text().strip())
    assert receipt["expired"] == 2 and sorted(receipt["expired_plan_ids"]) == sorted([ids["stale_draft"], ids["stale_proposed"]])


def test_dry_run_writes_nothing(tmp_path):
    store, ids = _seed(tmp_path)
    before = (tmp_path / "plans.jsonl").read_bytes()
    result = _run(store, tmp_path, apply=False)
    assert result["would_expire"] == 2 and "expired" not in result
    assert (tmp_path / "plans.jsonl").read_bytes() == before
    assert not (tmp_path / "receipts.jsonl").exists()


def test_rerun_is_idempotent(tmp_path):
    store, _ = _seed(tmp_path)
    _run(store, tmp_path)
    again = _run(store, tmp_path)
    assert again["would_expire"] == 0 and again.get("expired") is None


def test_expired_plans_are_closed_everywhere(tmp_path):
    store, ids = _seed(tmp_path)
    open_before = len(store.list_open_plans(limit=100))
    _run(store, tmp_path)
    open_ids = {p["plan_id"] for p in store.list_open_plans(limit=100)}
    assert ids["stale_draft"] not in open_ids and len(open_ids) == open_before - 2
    assert _plan_is_open({"status": "expired"}) is False
    assert _plan_is_open({"status": "superseded"}) is False
    assert _plan_is_open({"status": "draft"}) is True


def test_rebuilt_projection_keeps_expired(tmp_path):
    store, ids = _seed(tmp_path)
    _run(store, tmp_path)
    (tmp_path / "plans_projection.json").unlink()
    rebuilt = _store(tmp_path)
    assert rebuilt.get_plan(ids["stale_draft"])["status"] == "expired"


def test_a_concurrent_writer_no_longer_undoes_another(tmp_path):
    store, ids = _seed(tmp_path)
    stale_view = _store(tmp_path)              # loaded before the sweep
    _run(store, tmp_path)
    # The stale instance writes; before the fix it rewrote the projection from its
    # own copy, putting the expired plans back to draft.
    stale_view.update_plan(ids["accepted"], summary="operator note")
    fresh = _store(tmp_path)
    assert fresh.get_plan(ids["stale_draft"])["status"] == "expired"
    assert fresh.get_plan(ids["accepted"])["summary"] == "operator note"


def test_a_plan_accepted_after_the_snapshot_is_not_expired(tmp_path):
    store, ids = _seed(tmp_path)
    other = _store(tmp_path)
    other.update_plan(ids["stale_draft"], status="accepted")   # lands after `store` loaded
    _run(store, tmp_path)
    assert _store(tmp_path).get_plan(ids["stale_draft"])["status"] == "accepted"


def test_a_projection_without_an_offset_reads_as_is_and_the_first_write_migrates_it(tmp_path):
    store, ids = _seed(tmp_path)
    proj = tmp_path / "plans_projection.json"
    data = json.loads(proj.read_text())
    data.pop("event_offset")
    data["plans"][ids["stale_draft"]]["status"] = "cancelled"   # drifted legacy projection
    proj.write_text(json.dumps(data))
    before = proj.read_bytes()
    legacy = _store(tmp_path)
    assert legacy.get_plan(ids["stale_draft"])["status"] == "cancelled"   # read-only load
    assert proj.read_bytes() == before
    assert legacy.refresh_from_log() is True                              # sweeper's view
    assert legacy.get_plan(ids["stale_draft"])["status"] == "draft"
    assert proj.read_bytes() == before
    _store(tmp_path).update_plan(ids["accepted"], summary="first write")  # migrates
    migrated = json.loads(proj.read_text())
    assert isinstance(migrated["event_offset"], int)
    assert migrated["plans"][ids["stale_draft"]]["status"] == "draft"


def test_hygiene_job_runs_the_sweep_only_when_asked(tmp_path, monkeypatch, capsys):
    store, ids = _seed(tmp_path)
    spec = importlib.util.spec_from_file_location("cio_draft_plan_hygiene", ROOT / "scripts" / "cio_draft_plan_hygiene.py")
    hygiene = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hygiene)
    import scripts.lib.cio_plans as plans_mod

    monkeypatch.setattr(plans_mod, "CIOPlanStore", lambda *a, **k: store)
    before = (tmp_path / "plans.jsonl").read_bytes()
    assert hygiene.main([]) == 0
    assert "stale_expiry" not in capsys.readouterr().out          # off by default
    assert hygiene.main(["--expire-stale"]) == 0                  # dry run
    assert "stale_expiry would_expire=" in capsys.readouterr().out
    assert (tmp_path / "plans.jsonl").read_bytes() == before
