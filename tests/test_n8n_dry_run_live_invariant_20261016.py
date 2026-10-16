"""2026-10-16 — a lane that runs live on n8n never also gets a parallel dry_run slot.

Measured 2026-10-16 (receipts in data/runtime/n8n_runs/): 824 dry_run vs 302 live receipts for the day, and 0 dry_run
receipts for any lane that had already run live. The dry share is shadow-stage lanes plus registry-live lanes that
are not on TRADEAI_N8N_RELAY_LIVE_LANES (downgraded, reason relay_live_not_enabled). These tests pin the
one-mode-per-lane invariant in scripts/lib/n8n_due.py over a whole trading day, and the read-only report
scripts/report_n8n_dry_run_load.py that buckets the dry load. Hermetic: tmp ledger, fixed clock, no socket.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import report_n8n_dry_run_load as R
from scripts.lib import n8n_due as D
from scripts.lib import n8n_retry_policy as RP
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore

ROOT = Path(__file__).resolve().parents[1]
POLICIES = RP.load_policies(ROOT / "config" / "n8n_retry_policies.json")
DAY_START = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)   # 06:00 America/New_York (EDT)


def _row(lane, cron, *, mode, stage):
    return {"lane_id": lane, "scheduler": {"kind": "cron", "expression": cron, "stage": stage},
            "dispatch": {"mode": mode, "cron": [cron], "class": "monitor", "priority": 5,
                         "retry_policy": "transient-2", "wave": "W1"}}


def _allow(*lanes):
    return {lane: {"lane_id": lane, "command": ["$PY", "scripts/x.py"], "dry_run_arg": ["--dry-run"],
                   "live_arg": ["--apply"]} for lane in lanes}


@pytest.fixture
def store(tmp_path):
    ledger = CoordinationLedger(tmp_path / "ledger.sqlite")
    yield LedgerRunStore(ledger)
    ledger.close()


def _finish(store, run_id, lane, mode, at):
    store.request(run_id=run_id, lane_id=lane, mode=mode, requested_by="t", caller_id="t", now=at.timestamp() - 5)
    store._l._conn.execute("UPDATE runs SET state = 'RUN_DONE', finished_at = ?, exit_code = 0 WHERE run_id = ?",
                           (at.isoformat(), run_id))
    store._l._conn.commit()


@pytest.mark.parametrize("stage", ["canary", "cutover"])
def test_listed_live_lane_gets_only_live_slots_for_a_whole_day(store, monkeypatch, stage):
    """Every 5-minute tick of a trading day, executing what is due: the listed live lane never yields a dry_run key,
    even with dry_run history from its shadow days in the ledger. The shadow lane beside it keeps its dry runs."""
    monkeypatch.setenv(D.LIVE_LANES_ENV, "hb-live shadow-listed")
    rows = [_row("hb-live", "*/5 * * * *", mode="live", stage=stage),
            _row("shadow-listed", "*/5 * * * *", mode="dry_run", stage="shadow"),   # listed but still shadow
            _row("shadow-lane", "*/5 * * * *", mode="dry_run", stage="shadow")]
    allow = _allow("hb-live", "shadow-listed", "shadow-lane")
    _finish(store, "d:hb-live:dry_run:20261015T1500", "hb-live", "dry_run", DAY_START - timedelta(hours=15))
    _finish(store, "d:hb-live:live:20261015T2350", "hb-live", "live", DAY_START - timedelta(hours=6, minutes=10))
    seen: dict[str, set[str]] = {"hb-live": set(), "shadow-listed": set(), "shadow-lane": set()}
    for tick in range(0, 10 * 12):                        # 06:00-16:00 ET every 5 minutes
        now = DAY_START + timedelta(minutes=5 * tick)
        for item in D.compute_due(rows, allow, POLICIES, store, now)["items"]:
            seen[item["lane_id"]].add(item["mode"])
            _finish(store, item["idempotency_key"], item["lane_id"], item["mode"], now)
    assert seen["hb-live"] == {"live"}
    assert seen["shadow-listed"] == {"dry_run"}
    assert seen["shadow-lane"] == {"dry_run"}


def test_unreadable_live_list_never_turns_a_live_slot_into_fewer_live_checks(store, monkeypatch):
    """List missing: the live lane is reported (relay_live_lanes_missing), not silently downgraded or dropped from
    the shadow lanes' dry runs."""
    monkeypatch.delenv(D.LIVE_LANES_ENV, raising=False)
    rows = [_row("hb-live", "0 10 * * *", mode="live", stage="canary"),
            _row("shadow-lane", "0 10 * * *", mode="dry_run", stage="shadow")]
    resp = D.compute_due(rows, _allow("hb-live", "shadow-lane"), POLICIES, store, DAY_START + timedelta(hours=4))
    assert [(i["lane_id"], i["mode"]) for i in resp["items"]] == [("shadow-lane", "dry_run")]
    assert [(e["lane_id"], e["code"]) for e in resp["errors"]] == [("hb-live", "relay_live_lanes_missing")]


# ── the read-only report ──────────────────────────────────────────────────────────────────────────


def test_parse_run_file_accepts_only_slot_receipts():
    assert R.parse_run_file("d:hb:dry_run:20261016T1000.json") == ("d", "hb", "dry_run", "20261016T1000")
    assert R.parse_run_file("e:hb:live:20261016T1000:a2.json") == ("e", "hb", "live", "20261016T1000")
    for bad in ("hb_last.json", "d:hb:dry_run:20261016T1000.txt", "x:hb:live:20261016T1000.json",
                "d:hb:sandbox:20261016T1000.json"):
        assert R.parse_run_file(bad) is None


def test_summarize_buckets_dry_load(tmp_path):
    modes = {"hb-live": ("live", "canary"), "scalp": ("live", "canary"), "feeder": ("dry_run", "shadow")}
    receipts = [
        ("d", "hb-live", "live", "20261015T2350", {"state": "RUN_DONE", "duration_s": 1.0}),
        ("d", "hb-live", "dry_run", "20261015T2350", {"state": "RUN_DONE", "duration_s": 9.0}),  # promotion minute
        ("d", "hb-live", "dry_run", "20261016T0900", {"state": "RUN_DONE", "duration_s": 2.0}),  # waste
        ("d", "hb-live", "live", "20261016T0900", {"state": "RUN_DONE", "duration_s": 3.0}),
        ("d", "scalp", "dry_run", "20261016T0905", {"state": "RUN_DONE", "duration_s": 0.5}),
        ("d", "feeder", "dry_run", "20261016T0905", {"state": "RUN_DONE", "duration_s": 0.25}),
        ("d", "feeder", "dry_run", "20261016T0910", {"state": "RUN_FAILED", "duration_s": None}),
    ]
    out = R.summarize(receipts, modes, "20261016")
    assert out["dry_runs"] == 4 and out["live_runs"] == 1
    assert out["buckets"]["dry_after_live"] == {"dry_runs": 1, "executor_s": 2.0, "lanes": 1}
    assert out["buckets"]["live_not_listed"] == {"dry_runs": 1, "executor_s": 0.5, "lanes": 1}
    assert out["buckets"]["shadow"] == {"dry_runs": 2, "executor_s": 0.2, "lanes": 1}
    assert out["dry_share"] == 0.8
    # a live RUN_FAILED is not "already runs live"
    failed_live = [("d", "scalp", "live", "20261016T0800", {"state": "RUN_FAILED"})] + receipts
    assert R.summarize(failed_live, modes, "20261016")["buckets"]["live_not_listed"]["dry_runs"] == 1


def test_main_reads_a_tmp_state_root_and_writes_nothing(tmp_path, capsys):
    runs = tmp_path / "data" / "runtime" / "n8n_runs"
    runs.mkdir(parents=True)
    (runs / "d:feeder:dry_run:20261016T0905.json").write_text(json.dumps({"state": "RUN_DONE", "duration_s": 1}))
    (runs / "feeder_last.json").write_text("{}")
    reg = tmp_path / "lane_registry.json"
    reg.write_text(json.dumps({"lanes": [_row("feeder", "*/5 * * * *", mode="dry_run", stage="shadow")]}))
    before = sorted(p.name for p in tmp_path.rglob("*"))
    assert R.main(["--day", "20261016", "--state-root", str(tmp_path), "--registry", str(reg)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["buckets"]["shadow"]["dry_runs"] == 1 and out["lanes"][0]["stage"] == "shadow"
    assert sorted(p.name for p in tmp_path.rglob("*")) == before
    assert R.main(["--day", "20261016", "--state-root", str(tmp_path / "nope"), "--registry", str(reg)]) == 2
