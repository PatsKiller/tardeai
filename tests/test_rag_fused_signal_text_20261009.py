"""Storage audit 2026-10-09 #1: fused_signal embeddings must carry real signal fields; empty ones are skipped.

Hermetic: rag_indexer is loaded by file path with a stub embedder; the DB is a fake cursor.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


@pytest.fixture
def ri(monkeypatch):
    calls: list[str] = []
    stub = types.ModuleType("rag_retrieval")
    stub.embed_text = lambda text: calls.append(text) or [0.1, 0.2, 0.3]
    monkeypatch.setitem(sys.modules, "rag_retrieval", stub)
    iem = types.ModuleType("intelligence_entity_manager")
    iem.upsert_entity = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "intelligence_entity_manager", iem)
    spec = importlib.util.spec_from_file_location("rag_indexer_under_test", SCRIPTS / "rag_indexer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._embed_calls = calls
    return mod


MEANINGFUL = {
    "symbol": "abnb", "strategy_type": "swing_trade", "direction": None, "severity": "medium",
    "fused_score": 0.519, "confidence": 0.519, "catalyst_score": 1.0, "news_score": 0.32,
    "social_score": 0, "research_score": 0.31, "sentiment_score": 0.63, "research_insights": 5,
    "contradictions": 0, "top_signals": [], "reason_codes": [],
    "created_at": "2026-10-09T12:30:19.591075-04:00",
}
EMPTY = {
    "symbol": "YYYM", "strategy_type": "core_index", "direction": "", "severity": "low",
    "fused_score": 0.075, "confidence": 0.075, "catalyst_score": 0, "news_score": 0, "social_score": 0,
    "research_score": 0, "sentiment_score": 0.5, "research_insights": 0, "contradictions": 0,
    "top_signals": [], "reason_codes": [], "created_at": "2026-10-09T12:30:19-04:00",
}


def test_embed_text_carries_real_fields(ri):
    text, title = ri.build_fused_signal_text(json.dumps(MEANINGFUL))
    for needle in ("ABNB", "swing_trade", "severity medium", "fused score 0.519", "catalyst 1.00",
                   "news 0.32", "research 0.31", "sentiment bullish 0.63", "research insights 5",
                   "2026-10-09 16:00Z"):
        assert needle in text, needle
    assert "social" not in text.split("sources", 1)[1].split("·")[0]   # zero sources are not listed
    assert title.startswith("ABNB signal: medium fused 0.52 (catalyst,news,research)")
    # never the blank template the junk purge matches
    from_db_retention = r"^\S+ signal: *$"
    assert not re.match(from_db_retention, title)


def test_direction_reason_codes_and_top_signals_are_embedded(ri):
    rec = dict(EMPTY, direction="bullish", reason_codes=["EARNINGS_BEAT"], top_signals=[{"type": "insider_buy"}])
    text, title = ri.build_fused_signal_text(rec)
    assert "direction bullish" in text and "EARNINGS_BEAT" in text and "insider_buy" in text
    assert "bullish" in title


def test_distinct_signals_get_distinct_texts(ri):
    a = ri.build_fused_signal_text(MEANINGFUL)[0]
    b = ri.build_fused_signal_text(dict(MEANINGFUL, symbol="ACB", news_score=1.0, catalyst_score=0))[0]
    c = ri.build_fused_signal_text(dict(MEANINGFUL, created_at="2026-10-08T09:00:00+00:00"))[0]
    assert len({a, b, c}) == 3


@pytest.mark.parametrize("rec", [EMPTY, dict(EMPTY, sentiment_score=0.53), dict(EMPTY, symbol=""), "not json", None])
def test_empty_signal_is_not_embedded(ri, rec):
    assert ri.build_fused_signal_text(rec) is None


def test_sql_prefilter_and_builder_replace_the_blank_template(ri):
    cfg = ri.SOURCE_CONFIGS["fused_signal"]
    assert "' signal: '||COALESCE(direction" not in cfg["sql"]
    assert ri.FUSED_MEANINGFUL_SQL in cfg["sql"] and "NOT " + ri.FUSED_MEANINGFUL_SQL in cfg["skip_count_sql"]
    assert cfg["text_builder"] == "fused_signal" and ri.TEXT_BUILDERS["fused_signal"] is ri.build_fused_signal_text


class _Cur:
    def __init__(self, rows, prefilter_skips):
        self.rows, self.prefilter_skips = rows, prefilter_skips
        self.inserts: list[tuple] = []
        self.sql: list[str] = []
        self._one = None

    def execute(self, sql, params=None):
        self.sql.append(sql)
        if sql.lstrip().startswith("SELECT sub.id"):
            self._all = self.rows
        elif sql.startswith("SELECT count(*) FROM fused_signals"):
            self._one = (self.prefilter_skips,)
        elif "INSERT INTO content_embeddings" in sql:
            self.inserts.append(params)

    def fetchall(self):
        return self._all

    def fetchone(self):
        return self._one

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass


def test_index_source_skips_empty_and_counts_it(ri):
    rows = [(1, json.dumps(MEANINGFUL), "", None), (2, json.dumps(EMPTY), "", None)]
    cur = _Cur(rows, prefilter_skips=7)
    stats: dict = {}
    indexed, skipped = ri.index_source("fused_signal", hours_back=4, conn=_Conn(cur), stats=stats)
    assert indexed == 1 and skipped == 1
    assert stats["skipped_empty"] == 1 + 7 and stats["skipped_empty_prefilter"] == 7
    assert len(ri._embed_calls) == 1 and "ABNB fused signal" in ri._embed_calls[0]
    assert len(cur.inserts) == 1
    source_type, source_id, title = cur.inserts[0][:3]
    assert (source_type, source_id) == ("fused_signal", 1) and title.startswith("ABNB signal: medium")
    assert any("INTERVAL '4 hours'" in s for s in cur.sql if s.startswith("SELECT count(*) FROM fused_signals"))


def test_index_source_dry_run_embeds_and_writes_nothing(ri):
    cur = _Cur([(1, json.dumps(MEANINGFUL), "", None)], prefilter_skips=0)
    stats: dict = {}
    indexed, _ = ri.index_source("fused_signal", conn=_Conn(cur), dry_run=True, stats=stats)
    assert indexed == 1 and ri._embed_calls == [] and cur.inserts == []
    assert stats["samples"][0]["title"].startswith("ABNB signal:")


def test_other_sources_unchanged(ri):
    cur = _Cur([(5, "Some headline NVDA", "Some headline", None)], prefilter_skips=0)
    indexed, _ = ri.index_source("news", conn=_Conn(cur))
    assert indexed == 1 and ri._embed_calls == ["Some headline NVDA"]
    assert not any(s.startswith("SELECT count(*) FROM fused_signals") for s in cur.sql)
