"""CC v3 audit re-measure scorecard: every row from synthetic fixtures, no DB, no live paths."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("ccv3_audit_remeasure", ROOT / "scripts/ops/ccv3_audit_remeasure.py")
m = importlib.util.module_from_spec(_spec)
sys.modules.setdefault(_spec.name, m)  # dataclasses resolve the module by name
_spec.loader.exec_module(m)

NOW = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)


class FakeDB:
    """Answers by a substring of the SQL; records every statement so the test can prove it only SELECTs."""

    def __init__(self, answers: dict[str, list[tuple]]):
        self.answers = answers
        self.seen: list[str] = []

    def __call__(self, sql, params):
        self.seen.append(sql)
        for key, rows in self.answers.items():
            if key in sql:
                return rows
        raise AssertionError(f"unexpected SQL: {sql[:80]}")


def _healthy_db() -> FakeDB:
    return FakeDB({
        "alert_notification_deliveries": [(0, 0, 12, 0)],
        "market_regime_snapshots": [(NOW - timedelta(hours=2), "risk_on_trend", "broad")],
        "catalyst_events": [(60.0,), (1800.0,), (-30.0,), (3000.0,)],
        "market_quotes": [("alpaca", 100), ("finviz", 3)],
        "intelligence.embedding": [(42, NOW)],
    })


def _registry(**overrides) -> dict:
    lanes = []
    for lane_id in m.AUDIT_LANES:
        row = {"lane_id": lane_id, "state": "ACTIVE",
               "scheduler": {"kind": "n8n", "stage": "cutover", "cadence": "*/5 * * * *"},
               "dispatch": {"mode": "live"}}
        if lane_id in overrides:
            if overrides[lane_id] is None:
                continue
            row.update(overrides[lane_id])
        lanes.append(row)
    return {"lanes": lanes}


def _state_root(tmp_path: Path, *, modes=("ENFORCE",) * 3, projection_age_s=30, receipt_age_h=1.0) -> Path:
    cio = tmp_path / "data" / "cio"
    rt = tmp_path / "data" / "runtime"
    cio.mkdir(parents=True)
    rt.mkdir(parents=True)
    (cio / "retrieval_receipts.jsonl").write_text("".join(json.dumps({"mode": x}) + "\n" for x in modes))
    if projection_age_s is not None:
        p = rt / "overview_projection.json"
        p.write_text("{}")
        t = NOW.timestamp() - projection_age_s
        os.utime(p, (t, t))
    if receipt_age_h is not None:
        r = rt / "cio-capital-plan-record_last.json"
        r.write_text("{}")
        t = NOW.timestamp() - receipt_age_h * 3600
        os.utime(r, (t, t))
    return tmp_path


def _by(rows, metric):
    return next(r for r in rows if r.metric == metric)


def test_all_items_pass_on_a_healthy_fixture(tmp_path):
    db = _healthy_db()
    rows = m.measure(db, _state_root(tmp_path), _registry(), lambda: "# c\n0 * * * * a\n\n", NOW)
    assert {r.status for r in rows} == {"PASS"}, [(r.metric, r.value, r.detail) for r in rows if r.status != "PASS"]
    items = {r.item for r in rows}
    assert items == {"alert_queue", "retrieval", "regime", "catalyst_lead_time", "overview_projection",
                     "capital_plan_record", "quotes", "memory", "lane_stage", "crontab"}
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in db.seen)


def test_audit_findings_fail(tmp_path):
    db = FakeDB({
        "alert_notification_deliveries": [(655, 655, 0, 16)],
        "market_regime_snapshots": [(NOW - timedelta(hours=30), "high_volatility", "not_measured")],
        "catalyst_events": [(14 * 3600.0,), (20 * 3600.0,), (1800.0,)],
        "market_quotes": [("yfinance", 11228), ("alpaca", 5)],
        "intelligence.embedding": [(0, None)],
    })
    root = _state_root(tmp_path, modes=("SHADOW",) * 5, projection_age_s=None, receipt_age_h=None)
    reg = _registry(**{"overview-projection": None,
                       "alert-delivery-queue-hygiene": {"scheduler": {"kind": "n8n", "stage": "shadow"},
                                                        "dispatch": {"mode": "dry_run"}}})
    rows = m.measure(db, root, reg, lambda: "x\n" * 299, NOW)
    for metric in ("queued_older_than_10m", "completed_total", "suppressed_not_delivered_24h",
                   "shadow_share_last_2000", "snapshot_age_h", "breadth_measured", "share_within_1h",
                   "share_within_6h", "median_h", "file_age_s", "lane_receipt_age_h", "yfinance_rows_last_1h",
                   "intelligence_embedding_rows", "overview-projection", "alert-delivery-queue-hygiene",
                   "active_lines"):
        assert _by(rows, metric).status == "FAIL", metric
    assert _by(rows, "overview-projection").value == "unregistered"
    assert _by(rows, "shadow_share_last_2000").value == 1.0
    assert _by(rows, "yfinance_rows_last_1h").value == 11228
    assert _by(rows, "median_h").value == 14.0
    assert _by(rows, "share_within_1h").value == round(1 / 3, 4)


@pytest.mark.parametrize("row,ok", [
    ({"scheduler": {"kind": "n8n", "stage": "canary"}}, True),
    ({"scheduler": {"kind": "n8n", "stage": "cutover"}}, True),
    ({"scheduler": {"kind": "n8n", "stage": "shadow"}}, False),
    ({"scheduler": {"kind": "n8n", "stage": "cutover"}, "dispatch": {"mode": "dry_run"}}, False),
    ({"scheduler": {"kind": "cron"}, "dispatch": {"mode": "live"}}, True),
    ({"scheduler": {"kind": "cron", "stage": "shadow"}}, False),
    ({"scheduler": {"kind": "systemd"}, "state": "PAUSED"}, False),
    ({"scheduler": {"kind": "none", "stage": "shadow"}}, False),
])
def test_lane_live_rule(row, ok):
    base = {"lane_id": "x", "state": "ACTIVE", "dispatch": {"mode": "live"}}
    base.update(row)
    (r,) = m.lane_stages({"lanes": [base]}, lanes=("x",))
    assert (r.status == "PASS") is ok


def test_one_broken_probe_is_an_error_row_not_a_crash(tmp_path):
    db = _healthy_db()
    del db.answers["intelligence.embedding"]
    rows = m.measure(db, _state_root(tmp_path), _registry(), lambda: "", NOW)
    err = [r for r in rows if r.status == "ERROR"]
    assert [r.item for r in err] == ["memory"]
    assert len(rows) > 10


def test_receipt_tail_reads_only_the_last_n_and_skips_a_cut_first_line(tmp_path):
    p = tmp_path / "r.jsonl"
    lines = [json.dumps({"mode": "SHADOW", "pad": "x" * 50}) for _ in range(500)]
    lines += [json.dumps({"mode": "ENFORCE"}) for _ in range(3)]
    p.write_text("\n".join(lines) + "\n")
    tail = m._tail_lines(p, 3, chunk=64)
    assert [json.loads(t)["mode"] for t in tail] == ["ENFORCE"] * 3


def test_empty_catalyst_window_fails_without_dividing_by_zero():
    rows = m.catalyst_lead_time(lambda sql, p: [])
    assert {r.status for r in rows} == {"FAIL"}


def test_render_counts(tmp_path):
    rows = m.measure(_healthy_db(), _state_root(tmp_path), _registry(), lambda: "", NOW)
    out = m.render(rows, NOW)
    assert out.splitlines()[-1].startswith(f"# PASS {len(rows)}  FAIL 0  ERROR 0")
