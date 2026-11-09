# ANCHOR: LQ1444_REGISTRY_RUNTIME_DUPLICATE_CRON_20261109
"""LQ-20261107-1444 — DUPLICATE_SCHEDULER names a live-list + unwrapped-cron twin.

Integrity slices (2026-11-08) graded registry-runtime-truth DETECTOR_BLIND_SPOT: the 07:20
report listed one DUPLICATE_SCHEDULER (timer twin) and missed event-detector, which was on
TRADEAI_N8N_RELAY_LIVE_LANES while crontab L330 still ran scripts/event_detector.py unwrapped.
Registry kind stayed cron; the timer-only duplicate rule never saw it.

Synthetic fixtures only. No crontab -l, no systemd, no docker, no live state.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import check_registry_runtime_truth as RT  # noqa: E402

LANE = "event-detector"
CRON_UNWRAPPED = (
    "0 7,9,12,16,20 * * 1-5 cd $PROJ && bash scripts/market_day_gate.sh "
    "$PY scripts/event_detector.py >> logs/event_detector.log 2>&1"
)
CRON_CLAIMED = (
    "0 7,9,12,16,20 * * 1-5 cd $PROJ && flock -n /tmp/event_detector.lock "
    "env TRADEAI_EFFECT_CLAIM=event-detector bash scripts/effect_claim_cron.sh event-detector "
    "$PY scripts/event_detector.py >> logs/event_detector.log 2>&1"
)


def _row(*, kind="cron", stage="canary", dispatch="live", state="ACTIVE", match="scripts/event_detector.py"):
    sched = {"kind": kind, "expression": "0 7,9,12,16,20 * * 1-5", "match": match, "stage": stage}
    row = {"lane_id": LANE, "owner": "t", "state": state, "scheduler": sched, "output_signal": {"kind": "none"}}
    if dispatch:
        row["dispatch"] = {"mode": dispatch}
    return row


def _decl(row, *, allow=None, contracts=None):
    allow = allow if allow is not None else {LANE: {"lane_id": LANE, "live_arg": []}}
    contracts = contracts if contracts is not None else {
        LANE: {"id": LANE, "status": "REVIEWED", "stage": "canary", "kind": "lane"}
    }
    return {
        "rows": {row["lane_id"]: row},
        "contracts": contracts,
        "allow": allow,
        "processes": {},
        "grandfathered_draft": [],
    }


def _codes(found):
    return [(c["code"], c["lane_id"]) for c in found]


def test_live_list_plus_unwrapped_cron_is_duplicate_scheduler():
    """The L330 shape: kind stays cron, lane is on the live list, cron line has no effect_claim."""
    found, nm, _ = RT.evaluate(
        _decl(_row()),
        ledger=None,
        live_lanes=[LANE],
        cron_lines=[CRON_UNWRAPPED],
        n8n_active=None,
        systemd={},
    )
    assert ("DUPLICATE_SCHEDULER", LANE) in _codes(found)
    hit = next(c for c in found if c["code"] == "DUPLICATE_SCHEDULER")
    assert "without effect_claim_cron.sh" in hit["detail"]
    assert hit["evidence"]["registry_kind"] == "cron"
    assert hit["evidence"]["lines"] == 1
    assert "DUPLICATE_SCHEDULER" not in nm


def test_effect_claim_cron_twin_is_not_a_duplicate():
    """Canary shared-flock twin is intentional; only an unwrapped line is a finding."""
    found, _, _ = RT.evaluate(
        _decl(_row()),
        ledger=None,
        live_lanes=[LANE],
        cron_lines=[CRON_CLAIMED],
        n8n_active=None,
        systemd={},
    )
    assert ("DUPLICATE_SCHEDULER", LANE) not in _codes(found)


def test_retired_comment_is_not_a_duplicate():
    """active_cron_lines drops # comments; a retired L330 must not fire."""
    text = f"# RETIRED 2026-11-08 n8n-cutover event-detector {CRON_UNWRAPPED}"
    lines = RT.active_cron_lines(text)
    assert lines == []
    found, _, _ = RT.evaluate(
        _decl(_row()),
        ledger=None,
        live_lanes=[LANE],
        cron_lines=lines,
        n8n_active=None,
        systemd={},
    )
    assert ("DUPLICATE_SCHEDULER", LANE) not in _codes(found)


def test_shadow_live_list_row_is_not_this_duplicate():
    found, _, _ = RT.evaluate(
        _decl(_row(stage="shadow", dispatch="dry_run")),
        ledger=None,
        live_lanes=[LANE],
        cron_lines=[CRON_UNWRAPPED],
        n8n_active=None,
        systemd={},
    )
    assert ("DUPLICATE_SCHEDULER", LANE) not in _codes(found)
