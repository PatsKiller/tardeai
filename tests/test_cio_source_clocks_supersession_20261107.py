"""A retired lane's schedule is followed, not reported as RETIRED.

LQ-20261107-77: /v3/advisory technicals showed ``next — indicator-cache-refresh:
lane state RETIRED``.  The producer did not stop — the 2026-10-11 C1 manifest flip
absorbed its cron line into ``premarket-data-pipeline`` step ``indicator_cache_refresh``.
The lane row records that with ``superseded_by`` (and the step with ``c1_flip``), so
``next_scheduled_run`` must follow the chain instead of returning null.

The step's own ``cron_schedule`` wins over the host lane's expression: premarket fires
every day, the absorbed step only Mon-Fri.

Frozen on disk (tmp root): no live registry, DB, broker or host state is touched.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_source_clocks as csc  # noqa: E402

T1 = datetime(2026, 11, 7, 14, 35, tzinfo=timezone.utc)  # Sat 09:35 ET


def _root(tmp_path: Path, lanes: list[dict], pipeline: dict | None = None) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    # nosemgrep: tq-py-nonatomic-store-write -- a pytest tmp_path fixture written once, then only read; no live store is touched or truncated
    (tmp_path / "config/lane_registry.json").write_text(json.dumps({"lanes": lanes}), encoding="utf-8")
    if pipeline is not None:
        (tmp_path / "config/pipelines").mkdir(parents=True, exist_ok=True)
        (tmp_path / "config/pipelines/premarket.json").write_text(json.dumps(pipeline), encoding="utf-8")
    return tmp_path


def _retired(**extra) -> dict:
    row = {
        "lane_id": "indicator-cache-refresh",
        "state": "RETIRED",
        "superseded_by": "premarket-data-pipeline",
        "scheduler": {"kind": "cron", "expression": "45 5 * * 1-5"},
    }
    row.update(extra)
    return row


def _successor() -> dict:
    return {
        "lane_id": "premarket-data-pipeline",
        "state": "ACTIVE",
        "scheduler": {"kind": "cron", "expression": "45 5 * * *"},
    }


def test_retired_lane_follows_superseded_by(tmp_path):
    """The page's 'lane state RETIRED' becomes a real next run on the successor."""
    root = _root(tmp_path, [_retired(), _successor()])
    out = csc.next_scheduled_run(["indicator-cache-refresh"], now=T1, root=root, systemd_lookup=None)
    assert out["reason"] is None
    assert out["lane_id"] == "premarket-data-pipeline"
    assert out["next_run_at"] == "2026-11-08T10:45:00+00:00"  # Sun 05:45 ET — lane expression
    assert out["followed_from"] == ["indicator-cache-refresh"]


def test_absorbed_step_schedule_beats_the_host_lane(tmp_path):
    """premarket fires daily; the absorbed indicator step is Mon-Fri — the step wins."""
    retired = _retired(c1_flip={"manifest": "premarket", "stage": "premarket", "step_id": "indicator_cache_refresh"})
    pipeline = {
        "stages": {
            "premarket": {
                "steps": [
                    {"id": "other_step", "cron_schedule": "0 0 * * *"},
                    {"id": "indicator_cache_refresh", "cron_schedule": "45 5 * * 1-5"},
                ]
            }
        }
    }
    root = _root(tmp_path, [retired, _successor()], pipeline)
    out = csc.next_scheduled_run(["indicator-cache-refresh"], now=T1, root=root, systemd_lookup=None)
    # Saturday 09:35 ET -> next weekday 05:45 ET is Monday, not Sunday.
    assert out["next_run_at"] == "2026-11-09T10:45:00+00:00"
    assert out["expression"] == "45 5 * * 1-5"
    assert out["schedule_source"] == "pipeline_step"
    assert out["step_id"] == "indicator_cache_refresh"
    assert out["pipeline"] == "premarket:premarket"


def test_missing_step_falls_back_to_the_successor_lane(tmp_path):
    """A c1_flip naming a step the manifest does not have must not lose the schedule."""
    retired = _retired(c1_flip={"manifest": "premarket", "stage": "premarket", "step_id": "gone"})
    root = _root(tmp_path, [retired, _successor()], {"stages": {"premarket": {"steps": []}}})
    out = csc.next_scheduled_run(["indicator-cache-refresh"], now=T1, root=root, systemd_lookup=None)
    assert out["next_run_at"] == "2026-11-08T10:45:00+00:00"
    assert "schedule_source" not in out


def test_two_hop_chain(tmp_path):
    a = _retired(lane_id="a", superseded_by="b")
    b = {"lane_id": "b", "state": "RETIRED", "superseded_by": "c",
         "scheduler": {"kind": "cron", "expression": "0 3 * * *"}}
    c = {"lane_id": "c", "state": "ACTIVE", "scheduler": {"kind": "cron", "expression": "0 3 * * *"}}
    root = _root(tmp_path, [a, b, c])
    out = csc.next_scheduled_run(["a"], now=T1, root=root, systemd_lookup=None)
    assert out["lane_id"] == "c"
    assert out["followed_from"] == ["a", "b"]
    assert out["next_run_at"] == "2026-11-08T08:00:00+00:00"  # Sun 03:00 ET


def test_retired_with_no_successor_keeps_the_reason(tmp_path):
    """A lane that really stopped still says so — never a fabricated next run."""
    root = _root(tmp_path, [_retired(superseded_by=None)])
    out = csc.next_scheduled_run(["indicator-cache-refresh"], now=T1, root=root, systemd_lookup=None)
    assert out["next_run_at"] is None
    assert out["reason"] == "indicator-cache-refresh: lane state RETIRED"


def test_successor_not_in_registry_keeps_the_reason(tmp_path):
    root = _root(tmp_path, [_retired(superseded_by="missing-lane")])
    out = csc.next_scheduled_run(["indicator-cache-refresh"], now=T1, root=root, systemd_lookup=None)
    assert out["next_run_at"] is None
    assert "RETIRED" in out["reason"]


def test_successor_not_active_keeps_the_reason(tmp_path):
    paused = {"lane_id": "premarket-data-pipeline", "state": "PAUSED",
              "scheduler": {"kind": "cron", "expression": "45 5 * * *"}}
    root = _root(tmp_path, [_retired(), paused])
    out = csc.next_scheduled_run(["indicator-cache-refresh"], now=T1, root=root, systemd_lookup=None)
    assert out["next_run_at"] is None
    assert out["reason"] == "indicator-cache-refresh: lane state RETIRED"


def test_cycle_is_bounded(tmp_path):
    a = _retired(lane_id="a", superseded_by="b")
    b = _retired(lane_id="b", superseded_by="a")
    root = _root(tmp_path, [a, b])
    out = csc.next_scheduled_run(["a"], now=T1, root=root, systemd_lookup=None)
    assert out["next_run_at"] is None and "RETIRED" in out["reason"]


def test_live_registry_technicals_has_a_next_run():
    """The production pin: the declared technicals producer must never read RETIRED."""
    declared = list(csc.SPECS_BY_SOURCE["technicals"].lane_ids)
    assert declared, "the technicals source must declare the lane that runs its producer"
    out = csc.next_scheduled_run(declared, now=T1, systemd_lookup=None)
    assert out["reason"] is None, out
    assert out["lane_id"] and out["next_run_at"]
    if out.get("schedule_source") == "pipeline_step":
        assert out["next_run_at"] != "2026-11-08T10:45:00+00:00"  # a weekend step must not fire Sunday
