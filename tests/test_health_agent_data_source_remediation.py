"""Unit tests for source-aware `data_source_stale` auto-remediation.

Root cause: the generic `data_source_stale` finding was mapped to
`external_market_data_ingest.py --quotes` for EVERY source. That script only
refreshes quote data (yahoo_finance/finviz/alpaca), so a stale non-quote source
(finnhub news, sec_edgar, youtube_api, …) was retried against the wrong producer
forever — a no-op loop that could never clear the finding. `_data_source_retry_cmd`
now resolves a source-specific producer and skips auto-retry for non-quote sources
without one.
"""
from __future__ import annotations

import json
from pathlib import Path

from health_agent import _data_source_retry_cmd

ROOT = Path(__file__).resolve().parent.parent
POLICY = json.loads((ROOT / "config" / "health_agent_policy.json").read_text())


def _cmd(ftype: str, source: str):
    return _data_source_retry_cmd(POLICY, ftype, {"type": ftype, "source": source})


def test_quote_source_keeps_generic_quote_ingest():
    assert _cmd("data_source_stale", "yahoo_finance") == (
        ".venv/bin/python scripts/external_market_data_ingest.py --quotes"
    )
    assert _cmd("data_source_stale", "finviz") == (
        ".venv/bin/python scripts/external_market_data_ingest.py --quotes"
    )


def test_mapped_non_quote_source_uses_its_own_producer():
    assert _cmd("data_source_stale", "sec_edgar") == (
        ".venv/bin/python scripts/sec_data_ingest.py --all"
    )
    assert _cmd("data_source_stale", "youtube_api") == (
        ".venv/bin/python scripts/youtube_transcript_ingest.py --all-channels"
    )


def test_finnhub_skips_auto_retry():
    # A 401 routes to data_source_auth_failed (operator action); a non-401 stall is the
    # orchestrator/enrichment lane covered by pipeline_failures. Neither should be
    # auto-retried by the quote ingest.
    assert _cmd("data_source_stale", "finnhub") is None


def test_unknown_non_quote_source_skips_auto_retry():
    # Better to escalate than to loop a producer that can never clear the finding.
    assert _cmd("data_source_stale", "fred") is None


def test_non_data_source_findings_unchanged():
    assert _cmd("news_stale", "news") == ".venv/bin/python scripts/news_ingestion.py --priority"


def test_auth_failed_not_in_map():
    assert _cmd("data_source_auth_failed", "finnhub") is None
