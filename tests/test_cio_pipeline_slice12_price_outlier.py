"""Slice 12: quarantine price outliers on ingest. Do not scrub history."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from price_db_sync import is_price_outlier, quarantine_outlier  # noqa: E402


def test_policy_multiple_is_outlier():
    ok, reason = is_price_outlier(0.05, 179.80)
    assert ok is True
    assert "x the prior close" in reason
    ok2, _ = is_price_outlier(180.0, 179.80)
    assert ok2 is False


def test_quarantine_logs_and_does_not_scrub(tmp_path: Path):
    dest = tmp_path / "price_outlier_quarantine.jsonl"
    rec = quarantine_outlier(
        symbol="NVDA",
        price=0.05,
        prior_close=179.80,
        reason="0.05 is 0.00x the prior close 179.8 (bounds 0.1x-10.0x)",
        source="test",
        price_date="2026-05-05",
        path=dest,
    )
    assert rec["history_scrubbed"] is False
    assert rec["action"] == "rejected_not_written"
    assert dest.is_file()
    text = dest.read_text(encoding="utf-8")
    assert "NVDA" in text
    assert "history_scrubbed" in text
    # no history table touched — quarantine is append-only jsonl
    assert list(tmp_path.iterdir()) == [dest]
