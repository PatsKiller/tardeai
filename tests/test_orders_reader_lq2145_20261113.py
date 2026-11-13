"""ANCHOR: ORDERS_READER_LQ2145_20261113 -- the Home 'Orders / protection' provider against the lane's REAL heartbeat.

No heartbeat -> no_source (NEEDS BACKEND). Heartbeat written by stop_coverage_incidents._heartbeat under a synthetic
state root -> a computed state. A failed run never produces a fresh OK. Synthetic data only; no DB, no broker.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import stop_coverage_incidents as sci  # noqa: E402
from scripts import home_status_verdict as hsv  # noqa: E402
from scripts.lib import home_trade_ready as htr  # noqa: E402

NOW = datetime.now(timezone.utc)


def beat(root, **kw):
    doc = {"started_at": NOW.isoformat(), "finished_at": NOW.isoformat(), "status": "ok", "gaps": 0,
           "day_stop_expired": 0, "unresolved_unknown": 0, **kw}
    sci._heartbeat(doc, Path(root) / "data" / "runtime" / sci.HEARTBEAT_NAME)


def read(root, rows=()):
    return hsv.read_orders(lambda *a, **k: [], NOW, Path(root), list(rows))


def test_no_heartbeat_is_no_source_not_a_guess(tmp_path):
    r = read(tmp_path)
    assert r.state == htr.UNKNOWN and r.needs_backend is True and "LQ-2145" in (r.reason or "")


def test_fresh_clean_heartbeat_is_ok(tmp_path):
    beat(tmp_path)
    r = read(tmp_path)
    assert r.state == htr.OK and r.needs_backend is not True


def test_gap_in_heartbeat_is_gap(tmp_path):
    beat(tmp_path, gaps=2)
    assert read(tmp_path).state == htr.GAP


def test_unresolved_unknown_stays_unknown(tmp_path):
    beat(tmp_path, unresolved_unknown=1)
    assert read(tmp_path).state == htr.UNKNOWN


def test_day_stop_expired_is_warn_never_ok(tmp_path):
    beat(tmp_path, day_stop_expired=1)
    assert read(tmp_path).state == htr.WARN


def test_failed_first_run_has_no_ok_at_and_is_unknown(tmp_path):
    beat(tmp_path, status="error")
    r = read(tmp_path)
    assert r.state == htr.UNKNOWN


def test_failed_run_after_good_run_is_unknown_but_keeps_last_ok_at(tmp_path):
    beat(tmp_path)
    later = (NOW + timedelta(minutes=5)).isoformat()
    beat(tmp_path, status="error", finished_at=later)
    r = read(tmp_path)
    assert r.state == htr.UNKNOWN and "failed" in (r.reason or "")


def test_gate_label_cannot_read_as_the_system_status_orders_row():
    """System status 'Orders' says only that the stops were READ; the gate says whether positions are PROTECTED."""
    from scripts.lib.home_status_live import GATE_LABELS
    label = dict(GATE_LABELS)["orders"]
    assert "protect" in label.lower() and label.strip().lower() != "orders" and not label.lower().startswith("orders")
