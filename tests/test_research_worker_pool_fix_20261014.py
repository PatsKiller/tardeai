"""hermes-research-worker-pool: an all-cadence-skip hour is idle, not pool_incomplete (2026-10-14).

COVERS = ["scripts/hermes_research_worker_pool.py"]

The cron line (L693, `5 * * * *`) fires hourly, but every lane cadence in config/hermes_research_worker_lanes.yaml is
>= 240 min. Most hours every runnable lane skips on `cadence`, so completed == 0 and the CLI wrote a FAILED lane receipt
(error pool_incomplete, ok_at null) with exit 0: 8 of 12 cron runs on 2026-10-14 (logs/hermes_worker_pool.log,
08:05Z, 10:05Z-12:05Z, 14:05Z-16:05Z: lanes {'cadence': 6, 'no_runner': 3}). The receipt said "failing" while the pool
was healthy and simply had nothing due. A lock / pause skip or a lane error stays unhealthy.
Hermetic: run_pool and the dependency loader are stubbed; TRADEAI_STATE_ROOT = tmp.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_research_worker_pool as cli  # noqa: E402


def _lane(name, skipped=None, error=None, scanned=0, upserted=0):
    r = {"lane": name, "scanned": scanned, "upserted": upserted}
    if skipped:
        r["skipped"] = skipped
    if error:
        r["error"] = error
    return r


@pytest.fixture
def run(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))

    def _go(lanes, error=None):
        report = {"lanes": {r["lane"]: r for r in lanes}}
        if error:
            report["error"] = error
        fake = types.SimpleNamespace(run_pool=lambda *a, **k: report)
        monkeypatch.setattr(cli, "_load_dependencies", lambda: setattr(cli, "worker_pool", fake))
        rc = cli.main(["--run", "--json"])
        rec = json.loads((tmp_path / "data" / "runtime" / f"{cli.LANE_ID}_last.json").read_text())
        return rc, rec

    return _go


NO_RUNNER = [_lane(x, skipped="no_runner") for x in ("tax_retirement", "system_ops", "custom_domain")]


def test_all_cadence_skip_hour_is_idle_ok(run, capsys):
    """The 2026-10-14 08:05Z shape: 6 cadence + 3 no_runner, no error."""
    lanes = [_lane(x, skipped="cadence") for x in
             ("holdings", "watchlist", "white_space", "strategy", "private_proxy", "legal_domain")] + NO_RUNNER
    rc, rec = run(lanes)
    assert rc == 0
    assert rec["status"] == "ok" and rec["ok_at"] and rec.get("error") is None
    assert rec["summary"]["completed_lanes"] == 0 and rec["summary"]["idle_nothing_due"] is True


def test_a_completed_lane_is_ok(run):
    lanes = [_lane("holdings", scanned=3, upserted=3)] + [_lane("strategy", skipped="cadence")] + NO_RUNNER
    rc, rec = run(lanes)
    assert rc == 0 and rec["status"] == "ok" and rec["summary"]["idle_nothing_due"] is False


@pytest.mark.parametrize("skip", ["locked", "paused"])
def test_lock_or_pause_skip_stays_incomplete(run, skip):
    lanes = [_lane("holdings", skipped=skip), _lane("watchlist", skipped="cadence")] + NO_RUNNER
    rc, rec = run(lanes)
    assert rc == 0 and rec["status"] != "ok" and rec["error"] == "pool_incomplete" and rec["ok_at"] is None


def test_no_runner_only_stays_incomplete(run):
    rc, rec = run(NO_RUNNER)
    assert rec["status"] != "ok" and rec["error"] == "pool_incomplete"


def test_a_lane_error_stays_incomplete(run):
    lanes = [_lane("holdings", error="boom"), _lane("watchlist", skipped="cadence")] + NO_RUNNER
    rc, rec = run(lanes)
    assert rec["status"] != "ok" and rec["summary"]["failed_lanes"] == 1


def test_pool_error_is_rc1_and_failed(run):
    rc, rec = run([_lane("holdings", skipped="cadence")], error="config")
    assert rc == 1 and rec["status"] != "ok"
