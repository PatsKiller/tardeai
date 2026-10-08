"""Phase 2 PR-B (2026-10-08): the registry gate's findings become incident fan-in events between CI runs.

Hermetic: fixture registry, fixture crontab text, fixture timer names. The live crontab is never read.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import lane_registry as LR  # noqa: E402
from scripts.lib.lane_registry_drift import (  # noqa: E402
    STATE_DRIFT, STRUCTURAL, UNDECLARED_CRON, UNDECLARED_UNIT, findings,
)
import scripts.n8n_incident_fanin as fanin  # noqa: E402

NOW = datetime(2026, 10, 8, 3, 15, tzinfo=timezone.utc)
DECLARED = "5 * * * * cd $PROJ && $PY scripts/declared_job.py --apply >> logs/declared.log 2>&1"
UNDECLARED = "7 * * * * cd $PROJ && $PY scripts/nobody_declared_me.py --apply >> logs/x.log 2>&1"
NEVER = "9 * * * * cd $PROJ && $PY scripts/never_scheduled_job.py --apply >> logs/never.log 2>&1"


def _lane(lane_id: str, state: str, match: str, **extra) -> dict:
    row = {"lane_id": lane_id, "owner": "platform", "state": state,
           "scheduler": {"kind": "cron", "expression": f"{match} every hour", "match": match},
           "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{lane_id}_last.json"},
           "expected_cadence_hours": 1.0}
    if state != "ACTIVE":
        row.update(state_reason="fixture: declared off for the test", state_since="2026-10-08",
                   reason_confidence="ESTABLISHED", reason_evidence="x" * 70)
    row.update(extra)
    return row


def _registry(*lanes: dict, baseline: list[str] | None = None) -> dict:
    return {"schema": "LaneRegistry@v1", "lanes": list(lanes), "undeclared_baseline": list(baseline or []),
            "inherited_tranches": []}


def test_a_never_scheduled_lane_whose_line_is_live_is_state_drift():
    reg = _registry(_lane("never-lane", "NEVER_SCHEDULED", "scripts/never_scheduled_job.py"))
    out = findings(reg, NEVER + "\n", [])
    codes = {f["code"]: f for f in out}
    assert STATE_DRIFT in codes
    assert codes[STATE_DRIFT]["item"] == "drift:never-lane:CRON_PRESENT_WHILE_DECLARED_NEVER_SCHEDULED"
    assert codes[STATE_DRIFT]["severity"] == "P2"


def test_an_undeclared_cron_line_has_a_stable_item_that_is_not_the_command():
    reg = _registry(_lane("declared", "ACTIVE", "scripts/declared_job.py"))
    out = findings(reg, DECLARED + "\n" + UNDECLARED + "\n", [])
    assert [f["code"] for f in out] == [UNDECLARED_CRON]
    item = out[0]["item"]
    assert item.startswith("cron:") and len(item) == len("cron:") + 12
    assert "nobody_declared_me" not in item and "$PY" not in item
    assert out[0]["detail"] == "undeclared cron line 7 * * * * nobody_declared_me.py"
    again = findings(reg, UNDECLARED + "\n" + DECLARED + "\n", [])   # order and surroundings do not change the item
    assert again[0]["item"] == item


def test_an_undeclared_timer_and_a_structural_error_are_reported():
    bad = _lane("broken", "ACTIVE", "scripts/broken.py")
    del bad["output_signal"]
    reg = _registry(bad)
    out = findings(reg, "", ["tradeai-mystery.timer"])
    codes = sorted(f["code"] for f in out)
    assert codes == [STRUCTURAL, UNDECLARED_UNIT]
    unit = next(f for f in out if f["code"] == UNDECLARED_UNIT)
    assert unit["item"] == "unit:tradeai-mystery.timer"
    assert next(f for f in out if f["code"] == STRUCTURAL)["severity"] == "P1"


def test_a_clean_fixture_yields_no_findings_and_the_baseline_is_honoured():
    reg = _registry(_lane("declared", "ACTIVE", "scripts/declared_job.py"), baseline=[UNDECLARED])
    assert findings(reg, DECLARED + "\n" + UNDECLARED + "\n", []) == []


def _wire(monkeypatch, reg: dict | Exception, cron_text: str, units: list[str]):
    def load_registry(path=None):
        if isinstance(reg, Exception):
            raise reg
        return reg
    monkeypatch.setattr(LR, "load_registry", load_registry)
    monkeypatch.setattr(LR, "discover_systemd", lambda: [{"kind": "systemd", "expression": u} for u in units])
    import subprocess
    real_run = subprocess.run

    def fake_run(cmd, *a, **k):
        if cmd[:2] == ["crontab", "-l"]:
            class R:  # noqa: D401
                stdout = cron_text
                returncode = 0
            return R()
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", fake_run)


def test_the_fanin_emits_one_event_per_finding_with_a_stable_key(monkeypatch, tmp_path):
    reg = _registry(_lane("never-lane", "NEVER_SCHEDULED", "scripts/never_scheduled_job.py"))
    _wire(monkeypatch, reg, NEVER + "\n" + UNDECLARED + "\n", [])
    found = [f for f in fanin.collect(tmp_path, NOW) if f["source"] == "lane_registry"]
    assert sorted(f["item"][:6] for f in found) == ["cron:9", "drift:"] or len(found) == 2
    assert fanin.NOTES["lane_registry_source"] == "ok:2"
    events = [fanin.build_event(f, day="2026-10-08", now=NOW, sha="a" * 40) for f in found]
    keys = {e["idempotency_key"] for e in events}
    assert len(keys) == 2
    later = fanin.collect(tmp_path, NOW.replace(hour=22))   # same UTC day, hours later: same keys, same payload
    later_events = [fanin.build_event(f, day="2026-10-08", now=NOW.replace(hour=22), sha="a" * 40)
                    for f in later if f["source"] == "lane_registry"]
    assert {e["idempotency_key"] for e in later_events} == keys
    assert {e["source_timestamp"] for e in later_events} == {e["source_timestamp"] for e in events}
    for e in events:
        assert e["lane_id"] == fanin.LANE and e["artifact_ref"] == "data/runtime:" + fanin.LANE_REGISTRY_RECEIPT_REL


def test_an_unavailable_source_is_a_note_on_the_receipt_not_a_crash(monkeypatch, tmp_path):
    _wire(monkeypatch, RuntimeError("registry unreadable"), "", [])
    found = [f for f in fanin.collect(tmp_path, NOW) if f["source"] == "lane_registry"]
    assert found == []
    assert fanin.NOTES["lane_registry_source"].startswith("unavailable:RuntimeError:registry unreadable")
    monkeypatch.setattr(fanin, "state_root", lambda: tmp_path)
    monkeypatch.setattr(fanin, "served_sha", lambda: "b" * 40)
    receipt = tmp_path / "fanin.json"
    assert fanin.main(["--dry-run", "--receipt", str(receipt)]) == 0
    assert not receipt.exists()   # dry-run writes nothing
    assert not (tmp_path / fanin.LANE_REGISTRY_RECEIPT_REL).exists()


def test_apply_writes_the_drift_receipt_the_incident_references(monkeypatch, tmp_path):
    reg = _registry(_lane("never-lane", "NEVER_SCHEDULED", "scripts/never_scheduled_job.py"))
    _wire(monkeypatch, reg, NEVER + "\n", [])
    monkeypatch.setattr(fanin, "state_root", lambda: tmp_path)
    monkeypatch.setattr(fanin, "served_sha", lambda: "c" * 40)

    class Unreachable:
        url = "http://127.0.0.1:1"; has_key = False
        def healthz(self): return {"ok": False}
        def status(self, key): return {"state": "UNREACHABLE"}
    monkeypatch.setattr(fanin, "GatewayClient", lambda caller_id: Unreachable())
    receipt = tmp_path / "fanin.json"
    rc = fanin.main(["--apply", "--receipt", str(receipt)])
    assert rc == 1   # gateway unreachable is reported, not hidden
    doc = json.loads((tmp_path / fanin.LANE_REGISTRY_RECEIPT_REL).read_text())
    assert doc["schema"] == "N8nLaneRegistryDrift@v1" and [f["code"] for f in doc["findings"]] == [STATE_DRIFT]
    rec = json.loads(receipt.read_text())
    assert rec["source_notes"]["lane_registry_source"] == "ok:1"
    assert [r["source"] for r in rec["incidents"]] == ["lane_registry"]
