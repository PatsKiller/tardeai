"""Remaining audit phases that are safe to land (2026-09-27).

The heartbeat backfill used to append CIO_ACTION_CREATED rows with no
stream_id and no event_hash. That writer is retired. New rows go through
CIOActionLedger.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    path = ROOT / "scripts" / "backfill_cio_actions.py"
    spec = importlib.util.spec_from_file_location("backfill_cio_actions", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_backfill_does_not_append_when_asked_to_write(tmp_path, monkeypatch):
    mod = _load()
    ledger = tmp_path / "cio_action_ledger.jsonl"
    ledger.write_text('{"event_type":"CIO_ACTION_LEDGER_GENESIS"}\n', encoding="utf-8")
    monkeypatch.setattr(mod, "ACTION_LEDGER", ledger)
    monkeypatch.setattr(mod, "SNAPSHOT_DIR", tmp_path)
    summary = mod.run_backfill(dry_run=False)
    assert summary["retired"] is True
    assert summary["actions_created"] == 0
    assert ledger.read_text(encoding="utf-8").count("\n") == 1


def test_backfill_dry_run_still_does_not_append(tmp_path, monkeypatch):
    mod = _load()
    ledger = tmp_path / "cio_action_ledger.jsonl"
    ledger.write_text("", encoding="utf-8")
    snap = tmp_path / "cio_heartbeat_snapshots.jsonl"
    snap.write_text(
        '{"snapshot_id":"abc","collected_at":"2026-08-01T00:00:00+00:00","domains":{}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ACTION_LEDGER", ledger)
    monkeypatch.setattr(mod, "SNAPSHOT_DIR", tmp_path)
    summary = mod.run_backfill(dry_run=True)
    assert summary.get("retired") is not True
    assert ledger.read_text(encoding="utf-8") == ""
