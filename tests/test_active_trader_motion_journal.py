#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from active_trader.motion_journal import (  # noqa: E402
    JournalIntegrityError,
    MotionJournal,
)


def test_append_verify_and_filter(tmp_path):
    journal = MotionJournal(tmp_path / "motion.jsonl")
    first = journal.append(
        "candidate_observation",
        {"symbol": "AAPL", "observed_at": 100.0},
        recorded_at=100.0,
    )
    second = journal.append(
        "position_observation",
        {"position_id": "P1", "symbol": "AAPL", "observed_at": 101.0},
        recorded_at=101.0,
    )

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert second["previous_hash"] == first["record_hash"]
    verified = journal.verify()
    assert verified.ok is True
    assert verified.record_count == 2
    assert journal.latest("position_observation")["payload"]["position_id"] == "P1"
    assert [row["payload"]["symbol"] for row in journal.records(kind="candidate_observation")] == ["AAPL"]


def test_tamper_breaks_chain_and_blocks_append(tmp_path):
    path = tmp_path / "motion.jsonl"
    journal = MotionJournal(path)
    journal.append("candidate_observation", {"symbol": "AAPL"}, recorded_at=100.0)

    row = json.loads(path.read_text(encoding="utf-8"))
    row["payload"]["symbol"] = "TSLA"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    assert journal.verify().ok is False
    with pytest.raises(JournalIntegrityError):
        journal.append("candidate_observation", {"symbol": "MSFT"}, recorded_at=101.0)


def test_rejects_unsupported_kind(tmp_path):
    journal = MotionJournal(tmp_path / "motion.jsonl")
    with pytest.raises(ValueError):
        journal.append("broker_order", {"symbol": "AAPL"})
