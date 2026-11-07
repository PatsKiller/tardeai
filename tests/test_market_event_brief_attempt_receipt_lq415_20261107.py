"""LQ-20261107-415: every live market-event-brief exit writes the per-attempt LaneRunReceipt@v2 that the executor grades.

The allowlist opts the lane into output enforcement (``output_receipt: "v2"``), so the executor reads ONLY
``data/runtime/lane_attempts/market-event-brief/<run_id>.json``. Before this fix the brief printed a LANE_OUTPUT line
and wrote nothing the executor reads, so every live fire (a delivered Sunday brief included) graded RUN_FAILED
``output_unverifiable``. Real executor validator, real health contract and allowlist entry, stubbed channels, synthetic
fixture; nothing is sent and operator_contact.json is never read.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
import market_event_brief as meb  # noqa: E402
from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib import lane_last_receipt as LR  # noqa: E402
from scripts.lib import n8n_output_verdict as V  # noqa: E402

LANE = meb.LANE_ID
SLOT = "2026-11-08T20:00"
CODE = "b" * 40
FIX = json.loads((ROOT / "tests/fixtures/market_event_brief_sample.json").read_text())
RULE = {c["id"]: c for c in json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]}[LANE]["expected_output"]
ENTRY = {e["lane_id"]: e for e in json.loads((ROOT / "config/n8n_run_allowlist.json").read_text())["lanes"]}[LANE]


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A live attempt: executor env set, state root in tmp, channels stubbed (they record, never send)."""
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    monkeypatch.setenv("TRADEAI_RUN_ATTEMPT", "1")
    monkeypatch.setenv("TRADEAI_RUN_MODE", "live")
    monkeypatch.setenv("TRADEAI_CODE_SHA", CODE)
    sent = {"email": [], "tg": [], "txt": [], "ok": True}
    monkeypatch.setattr(meb, "_default_email", lambda s, b: sent["email"].append(s) or sent["ok"])
    monkeypatch.setattr(meb, "_default_telegram", lambda t: sent["tg"].append(t) or sent["ok"])
    monkeypatch.setattr(meb, "_default_text", lambda ev: sent["txt"].append(ev["event_id"]) or {"sent": True})
    counter = {"n": 0}

    def fire(argv, payload=FIX, slot=SLOT):
        counter["n"] += 1
        run_id = f"d:{LANE}:live:20261108T2000:t{counter['n']}"
        monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
        fx = tmp_path / f"payload{counter['n']}.json"
        fx.write_text(json.dumps(payload))
        args = ["--input", str(fx)] + (["--slot", slot] if slot else []) + argv
        started = datetime.now(timezone.utc) - timedelta(seconds=1)
        rc = meb.main(args)
        finished = datetime.now(timezone.utc) + timedelta(seconds=1)
        doc = X.read_attempt_receipt(tmp_path, LANE, run_id)
        exec_receipt = {"run_id": run_id, "lane_id": LANE, "mode": "live", "state": "RUN_DONE" if rc == 0 else "RUN_FAILED",
                        "reason": None if rc == 0 else "exit_nonzero", "attempt": 1, "code_sha": CODE,
                        "started_at": started.isoformat(), "finished_at": finished.isoformat()}
        verdict = V.evaluate(RULE, doc, run_id=run_id, lane_id=LANE, mode="live", attempt=1,
                             started_at=started.isoformat(), finished_at=finished.isoformat(), code_sha=CODE)
        graded = X.apply_output_verdict(dict(exec_receipt), {LANE: RULE}, lane_id=LANE, mode="live", state_root=tmp_path, entry=ENTRY)
        return rc, doc, verdict, graded

    fire.sent = sent
    fire.root = tmp_path
    return fire


def test_lane_is_enforced_so_the_attempt_receipt_is_required():
    assert ENTRY.get("output_receipt") == X.OUTPUT_RECEIPT_ENFORCED
    assert V.validate_expected_output(RULE) == []


def test_delivered_sunday_brief_grades_produced_and_keeps_ok_at(lane):
    rc, doc, verdict, graded = lane(["--deliver"])
    assert rc == 0 and len(lane.sent["email"]) == 1 and len(lane.sent["tg"]) == 1
    assert doc and doc["schema"] == "LaneRunReceipt@v2" and doc["produced_count"] == 1
    assert verdict["verdict"] == "produced", verdict
    assert graded["state"] == "RUN_DONE" and graded["output_verdict"]["verdict"] == "produced", graded
    last = json.loads((lane.root / meb.RECEIPT_REL).read_text())
    assert last["ok_at"] and last["summary"]["slot"] == SLOT          # lane_registry output_signal json_key ok_at
    assert last["summary"]["channels"] == {"email": True, "telegram": True}


def test_repeat_fire_is_slot_already_delivered_and_allowed(lane):
    lane(["--deliver"])
    rc, doc, verdict, graded = lane(["--deliver"])
    assert rc == 0 and len(lane.sent["email"]) == 1                  # nothing sent the second time
    assert doc["produced_count"] == 0 and doc["empty_reason"] == "slot_already_delivered"
    assert verdict["verdict"] == "empty_allowed", verdict
    assert graded["state"] == "RUN_DONE", graded


def test_no_slot_due_is_allowed(lane, monkeypatch):
    monkeypatch.setattr(meb, "slot_for", lambda now, policy: None)
    rc, doc, verdict, graded = lane(["--deliver"], slot=None)
    assert rc == 0 and doc["empty_reason"] == "no_slot_due" and doc["attempted_count"] == 0
    assert verdict["verdict"] == "empty_allowed" and graded["state"] == "RUN_DONE", (verdict, graded)


@pytest.mark.parametrize("reason,mutate", [
    ("no_episode", lambda p: p.update(episode={})),
    ("episode_not_active", lambda p: p["episode"].update(state="WATCHING")),
])
def test_idle_episode_reasons_are_allowed(lane, reason, mutate):
    payload = copy.deepcopy(FIX)
    mutate(payload)
    rc, doc, verdict, graded = lane(["--deliver"], payload=payload)
    assert rc == 0 and doc["empty_reason"] == reason
    assert verdict["verdict"] == "empty_allowed" and graded["state"] == "RUN_DONE", (verdict, graded)
    assert not lane.sent["email"]


def test_no_channel_confirmed_fails(lane):
    lane.sent["ok"] = False
    rc, doc, verdict, _ = lane(["--deliver"])
    assert rc == 1 and doc["status"] == "failed"
    assert doc["skipped_reasons"] == {"no_channel_confirmed": 1}
    assert verdict["verdict"] == "empty_violation", verdict
    assert not (lane.root / meb.STATE_REL).exists()                  # the slot stays open for a retry


def test_payload_unavailable_fails(lane, tmp_path, monkeypatch):
    run_id = f"d:{LANE}:live:20261108T2000:pu"
    monkeypatch.setenv("TRADEAI_RUN_ID", run_id)
    rc = meb.main(["--deliver", "--slot", SLOT, "--input", str(tmp_path / "missing.json")])
    doc = X.read_attempt_receipt(tmp_path, LANE, run_id)
    assert rc == 1 and doc["status"] == "failed" and doc["skipped_reasons"] == {"payload_unavailable": 1}
    assert V.evaluate(RULE, doc, run_id=run_id, lane_id=LANE, mode="live")["verdict"] == "empty_violation"


def test_dry_run_writes_no_receipt(lane):
    rc, doc, verdict, _ = lane(["--dry-run"])
    assert rc == 0 and doc is None
    assert not (lane.root / meb.RECEIPT_REL).exists()
    assert not (lane.root / "data/runtime/lane_attempts").exists()
    assert not lane.sent["email"] and not lane.sent["txt"]
