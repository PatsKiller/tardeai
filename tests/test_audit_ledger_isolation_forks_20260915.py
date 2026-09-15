"""R-01 (2026-09-15): tests never reach the production ledger; an investigated fork verifies only on exact hashes."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_ledger as al  # noqa: E402


def test_the_suite_runs_with_the_db_mirror_off_and_a_private_ledger_dir():
    assert al._db_mirror_enabled() is False and al._conn() is None
    assert Path(os.environ["TRADEAI_AUDIT_LEDGER_DIR"]) != ROOT / "data" / "runtime" / "audit_ledger"
    assert "persistent-state" not in str(al.LEDGER_PATH.resolve())


def _forked_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(al, "LEDGER_DIR", tmp_path)
    monkeypatch.setattr(al, "LEDGER_PATH", tmp_path / "events.jsonl")
    for i in range(4):
        al.record_event("readiness_evaluated", reason=str(i))
    rows = [json.loads(x) for x in al.LEDGER_PATH.read_text().splitlines()]
    # Branch: row 3 is re-hashed as if it followed row 1 (two copies written from a common ancestor).
    body = {k: v for k, v in rows[3].items() if k != "event_hash"}
    body["prev_event_hash"] = rows[1]["event_hash"]
    body["event_hash"] = al._hash_payload(body)
    rows[3] = body
    al.LEDGER_PATH.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return rows


def _ack(tmp_path, monkeypatch, **fork):
    p = tmp_path / "forks.json"
    p.write_text(json.dumps({"forks": [fork]}))
    monkeypatch.setattr(al, "ACKNOWLEDGED_FORKS_PATH", p)


def test_an_unacknowledged_fork_breaks_the_chain(tmp_path, monkeypatch):
    rows = _forked_ledger(tmp_path, monkeypatch)
    monkeypatch.setattr(al, "ACKNOWLEDGED_FORKS_PATH", tmp_path / "absent.json")
    v = al.verify_chain(10)
    assert v["ok"] is False and v["error"] == "chain_break" and v["event_id"] == rows[3]["event_id"]


def test_an_acknowledged_fork_verifies_and_is_named(tmp_path, monkeypatch):
    rows = _forked_ledger(tmp_path, monkeypatch)
    _ack(tmp_path, monkeypatch, event_id=rows[3]["event_id"], prev_event_hash=rows[1]["event_hash"],
         follows_event_hash=rows[2]["event_hash"])
    v = al.verify_chain(10)
    assert v["ok"] is True and v["verified"] == 4 and v["acknowledged_forks"] == [rows[3]["event_id"]]


def test_an_acknowledgement_with_a_wrong_hash_does_not_excuse_the_break(tmp_path, monkeypatch):
    rows = _forked_ledger(tmp_path, monkeypatch)
    _ack(tmp_path, monkeypatch, event_id=rows[3]["event_id"], prev_event_hash=rows[1]["event_hash"],
         follows_event_hash="0" * 64)
    assert al.verify_chain(10)["ok"] is False


def test_the_production_acknowledgement_names_exactly_one_investigated_fork():
    doc = json.loads((ROOT / "config" / "audit_ledger_acknowledged_forks.json").read_text())
    assert len(doc["forks"]) == 1
    f = doc["forks"][0]
    assert f["line"] == 1558 and f["prev_event_line"] == 1522 and "served-copy split" in f["cause"]
    assert all(len(f[k]) == 64 for k in ("prev_event_hash", "follows_event_hash"))
