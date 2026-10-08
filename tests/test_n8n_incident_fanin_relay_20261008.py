"""Incident fan-in `relay` source (observability gaps PR, 2026-10-08).

The run relay's last file ($TRADEAI_STATE_ROOT/data/runtime/n8n_relay/n8n_run_relay_last.json, shape
{"last": row, "counts": {...}}) carries cumulative counters. auth_failures rising by >= 3 since the
previous fan-in receipt opens `relay:auth_failures` (P2); a relay last file older than 2x the shortest
n8n cadence while the executor is running ACTIVE n8n lanes AND the relay unit is in
config/expected_services.json opens `relay:down` (P1). The next file with no new failures clears the
P2 (the existing recovery path closes it). TRADEAI_FANIN_RELAY=0 opts out. Fixture files under tmp_path
only; the live state root is never read.

COVERS = ["scripts/n8n_incident_fanin.py"]
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402

NOW = datetime(2026, 10, 8, 13, 0, tzinfo=timezone.utc)


def _relay_last(root: Path, *, auth_failures: int, at: datetime, state="REFUSED", reason="relay_bad_bearer") -> Path:
    p = root / fanin.RELAY_LAST_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": at.isoformat(), "state": state, "reason": reason, "lane_id": "n8n-lab-watchdog"}
    p.write_text(
        json.dumps(
            {
                "last": row,
                "counts": {
                    "requested": 4,
                    "refused": auth_failures,
                    "auth_failures": auth_failures,
                    "gateway_unreachable": 0,
                },
            }
        )
    )
    return p


def _wire(monkeypatch, tmp_path, *, cadence=1.0, executor_age_h=0.5, unit_expected=True, n8n_lanes=True):
    reg = {
        "schema": "LaneRegistry@v1",
        "lanes": [
            {
                "lane_id": "n8n-lab-watchdog",
                "state": "ACTIVE",
                "expected_cadence_hours": cadence,
                "scheduler": {"kind": "n8n" if n8n_lanes else "cron", "expression": "wf-1"},
            },
        ],
    }
    monkeypatch.setattr(LR, "load_registry", lambda path=None: reg)
    monkeypatch.setenv("TRADEAI_FANIN_LANE_REGISTRY", "0")
    monkeypatch.setenv("TRADEAI_FANIN_RUNS", "0")
    monkeypatch.delenv("TRADEAI_FANIN_RELAY", raising=False)
    monkeypatch.setattr(fanin, "_outbox_findings", lambda now: [])
    monkeypatch.setattr(fanin, "PREV_RECEIPT", None)
    es = tmp_path / "expected_services.json"
    units = [{"unit": "tradeai-n8n-run-executor.service"}] + ([{"unit": fanin.RELAY_UNIT}] if unit_expected else [])
    es.write_text(json.dumps({"schema": "ExpectedServices@v1", "units": units}))
    monkeypatch.setattr(fanin, "EXPECTED_SERVICES_PATH", es)
    if executor_age_h is not None:
        p = tmp_path / "data/runtime/n8n_runs/n8n_run_executor_last.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps({"schema": "RunReceipt@v1", "finished_at": (NOW - timedelta(hours=executor_age_h)).isoformat()})
        )


def _relay(found):
    return [f for f in found if f["source"] == "relay"]


def test_without_a_relay_last_file_there_is_no_finding_and_the_receipt_says_so(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    assert _relay(fanin.collect(tmp_path, NOW)) == [] and fanin.NOTES["relay_source"] == "ok:no_relay_last"
    assert fanin.RELAY_COUNTS == {}


def test_auth_failures_rising_by_three_since_the_previous_receipt_opens_a_p2(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    _relay_last(tmp_path, auth_failures=5, at=NOW - timedelta(minutes=3))
    # first run: no baseline → nothing, but the counts are parked for the receipt
    assert _relay(fanin.collect(tmp_path, NOW)) == []
    assert fanin.RELAY_COUNTS["auth_failures"] == 5 and fanin.NOTES["relay_source"].startswith(
        "ok:0:auth_failures=5:prev=None"
    )
    prev = {"relay_counts": {"auth_failures": 2, "as_of": (NOW - timedelta(minutes=15)).isoformat()}}
    (f,) = _relay(fanin.collect(tmp_path, NOW, prev))
    assert (f["item"], f["severity"], f["artifact_rel"], f["store"]) == (
        "relay:auth_failures",
        "P2",
        fanin.RELAY_LAST_REL,
        "data/runtime",
    )
    assert f["detail"].startswith(
        "auth_failures 2->5 (+3) since fan-in 2026-10-08T12:45:00+00:00; last REFUSED/relay_bad_bearer"
    )
    assert f["detected_at"] == (NOW - timedelta(minutes=3)).isoformat()
    day = NOW.strftime("%Y-%m-%d")
    ev = fanin.build_event(f, day=day, now=NOW, sha="a" * 40)
    assert (
        ev["subject_key"] == "sev=P2;src=relay;item=relay:auth_failures"
        and ev["artifact_ref"] == f"data/runtime:{fanin.RELAY_LAST_REL}"
    )


def test_fewer_than_three_new_failures_or_a_counter_reset_is_not_a_finding_and_it_clears(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    _relay_last(tmp_path, auth_failures=4, at=NOW - timedelta(minutes=3))
    assert _relay(fanin.collect(tmp_path, NOW, {"relay_counts": {"auth_failures": 2}})) == []  # +2 < step
    assert _relay(fanin.collect(tmp_path, NOW, {"relay_counts": {"auth_failures": 10}})) == []  # relay restarted
    # clears: the next file with no new failures (same counter) against the receipt that recorded the spike
    assert _relay(fanin.collect(tmp_path, NOW, {"relay_counts": {"auth_failures": 4}})) == []
    assert fanin.NOTES["relay_source"].startswith("ok:0:auth_failures=4:prev=4")


def test_a_stale_relay_file_while_the_executor_runs_n8n_lanes_and_the_unit_is_expected_is_a_p1(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, cadence=1.0, executor_age_h=0.5)
    _relay_last(tmp_path, auth_failures=0, at=NOW - timedelta(hours=2.5), state="REQUESTED", reason=None)
    (f,) = _relay(fanin.collect(tmp_path, NOW))
    assert (f["item"], f["severity"]) == ("relay:down", "P1")
    assert "age_h=2.5 > 2.0x shortest n8n cadence 1.0h" in f["detail"] and fanin.RELAY_UNIT in f["detail"]
    assert f["detected_at"] == "2026-10-08T00:00:00+00:00"  # stable per UTC day = stable idempotency payload
    assert fanin.NOTES["relay_source"].endswith("executor_running=yes")


def test_relay_down_needs_all_three_conditions(monkeypatch, tmp_path):
    # unit not expected (not installed by grant yet): expected_services owns that story, not the fan-in
    _wire(monkeypatch, tmp_path, unit_expected=False)
    _relay_last(tmp_path, auth_failures=0, at=NOW - timedelta(hours=2.5))
    assert _relay(fanin.collect(tmp_path, NOW)) == []
    # executor itself stalled: the runs source's P1, not a second one here
    _wire(monkeypatch, tmp_path, executor_age_h=5.0)
    assert _relay(fanin.collect(tmp_path, NOW)) == [] and fanin.NOTES["relay_source"].endswith("executor_running=no")
    # no executor receipt at all
    _wire(monkeypatch, tmp_path, executor_age_h=None)
    assert _relay(fanin.collect(tmp_path, NOW)) == []
    # no ACTIVE n8n lanes → nothing for the relay to be down for
    _wire(monkeypatch, tmp_path, n8n_lanes=False)
    assert _relay(fanin.collect(tmp_path, NOW)) == []
    # fresh relay file: fine
    _wire(monkeypatch, tmp_path)
    _relay_last(tmp_path, auth_failures=0, at=NOW - timedelta(minutes=30))
    assert _relay(fanin.collect(tmp_path, NOW)) == []


def test_the_env_opt_out_and_a_broken_file_are_notes_not_crashes(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path)
    _relay_last(tmp_path, auth_failures=9, at=NOW)
    monkeypatch.setenv("TRADEAI_FANIN_RELAY", "0")
    assert _relay(fanin.collect(tmp_path, NOW, {"relay_counts": {"auth_failures": 0}})) == []
    assert fanin.NOTES["relay_source"] == "unavailable:RuntimeError:disabled_by_env" and fanin.RELAY_COUNTS == {}
    monkeypatch.delenv("TRADEAI_FANIN_RELAY")
    (tmp_path / fanin.RELAY_LAST_REL).write_text('{"last": "not a row", "counts": {"auth_failures": "x"}}')
    assert _relay(fanin.collect(tmp_path, NOW)) == [] and fanin.NOTES["relay_source"].startswith("unavailable:")


def test_apply_writes_the_relay_counts_onto_the_receipt_and_keeps_the_baseline_when_the_source_is_off(
    monkeypatch, tmp_path
):
    _wire(monkeypatch, tmp_path)
    _relay_last(tmp_path, auth_failures=7, at=NOW - timedelta(minutes=1))
    monkeypatch.setattr(fanin, "state_root", lambda: tmp_path)
    monkeypatch.setattr(fanin, "served_sha", lambda: "b" * 40)

    class Client:
        url, has_key = "http://127.0.0.1:0", False

        def __init__(self, caller_id):
            pass

        def healthz(self):
            return {"ok": True}

        def status(self, k):
            return {"state": "REFUSED", "reason": "unknown_event"}

        def accept_event(self, ev):
            return {"state": "REFUSED", "reason": "unknown_lane"}

        def transition(self, op, k, **kw):
            return {"state": "CONSUMED", "reason": None}

    monkeypatch.setattr(fanin, "GatewayClient", Client)
    receipt = tmp_path / "data/runtime/n8n_incident_fanin_last.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps({"incidents": [], "relay_counts": {"auth_failures": 1, "as_of": "2026-10-08T12:00:00+00:00"}})
    )
    fanin.main(["--apply", "--receipt", str(receipt)])
    doc = json.loads(receipt.read_text())
    assert doc["relay_counts"]["auth_failures"] == 7 and doc["source_notes"]["relay_source"].startswith(
        "ok:1:auth_failures=7:prev=1"
    )
    assert [(r["source"], r["item"], r["severity"]) for r in doc["incidents"]] == [
        ("relay", "relay:auth_failures", "P2")
    ]
    # the source switched off: the baseline on the receipt survives, so the next run cannot see a false +delta
    monkeypatch.setenv("TRADEAI_FANIN_RELAY", "0")
    fanin.main(["--apply", "--receipt", str(receipt)])
    doc = json.loads(receipt.read_text())
    assert doc["relay_counts"]["auth_failures"] == 7 and doc["incidents"] == []
