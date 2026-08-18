#!/usr/bin/env python3
"""Journal STALE-badge semantics — staleness must key off pipeline rebuild freshness
(last_ingested_at), NOT the most recent closed trade (last_close_date).

A quiet market with no recent closes is not "stale data"; the badge was firing on
MAX(close_date) and labeling trading inactivity as a broken ingest. This test pins the
decoupled contract across the API, the v3 header, and the health agent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

API_SRC = (ROOT / "scripts" / "api_v2.py").read_text()
STRIP_SRC = (ROOT / "apps" / "command-center-v3" / "src" / "components" / "MetricStrip.tsx").read_text()
HEALTH_SRC = (ROOT / "scripts" / "health_agent.py").read_text()


def test_overview_journal_exposes_rebuild_freshness():
    # The journal dict returned by /api/v2/overview carries a rebuild timestamp + ledger freshness,
    # separate from the last-close date.
    assert '"last_ingested_at": j_last_ingested' in API_SRC
    assert '"ledger_last_trade_time": j_ledger_last_trade' in API_SRC
    assert '"last_close_date": j_last_close' in API_SRC


def test_overview_freshness_query_uses_rebuild_not_close():
    # Rebuild freshness = MAX(created_at) over schwab trade_closed rows (DELETE-then-INSERT sets
    # created_at=NOW() every --apply). Must NOT be MAX(close_date).
    assert "MAX(created_at) AS last_ingested_at FROM trade_closed WHERE account LIKE 'schwab%'" in API_SRC
    assert "MAX(trade_time) AS last_trade_time FROM trade_transactions WHERE import_source='schwab_api'" in API_SRC


def test_metricstrip_staleness_uses_ingested_not_close():
    # The header no longer derives staleness from the last-close date.
    assert "journalStaleDays" not in STRIP_SRC
    assert "journalLastIngested = overview?.journal?.last_ingested_at" in STRIP_SRC
    # 72h threshold spans weekends; staleness = pipeline not refreshed, not inactivity.
    assert "journalIngestedHours != null && journalIngestedHours > 72" in STRIP_SRC


def test_metricstrip_last_close_is_neutral_info():
    # last_close_date remains as neutral informational text ("last close <date>"), not a stale trigger.
    assert "last close ${journalLastClose}" in STRIP_SRC
    assert "journal rebuilt" in STRIP_SRC


def test_health_agent_trade_closed_stale_uses_rebuild():
    block = HEALTH_SRC[HEALTH_SRC.index("trade_closed output freshness"):]
    block = block[: block.index("journal_annotation_low")] if "journal_annotation_low" in block else block
    assert "MAX(created_at)::timestamp FROM trade_closed WHERE account LIKE 'schwab%'" in HEALTH_SRC
    assert "MAX(close_date)::timestamp FROM trade_closed" not in HEALTH_SRC
    assert "schwab_journal_builder may be broken" in HEALTH_SRC
