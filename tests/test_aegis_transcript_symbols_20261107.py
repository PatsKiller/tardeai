"""LQ-20261107-143 (old LQ-143): aegis-transcript-discovery attaches a transcript only when it NAMES the symbol.

Before 2026-11-07 the lane matched with ``ILIKE '%SYM%'`` and wrote every substring hit with a fixed 0.55
confidence, so the live store carried AXON on a Palantir video, NOC on a Medicare video, and DRS on a
Portuguese B3 video (the "DRS" inside "cdrs"/"BDRs"). These tests pin the replacement: the exact-symbol
matcher decides, ``publish_date`` becomes ``published_at``, a (symbol, title) already filed is skipped, and
the confidence follows HOW the text named the symbol.

Synthetic rows only; ``_db_query`` is stubbed, so no database is read.
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))

import aegis_transcript_discovery as atd  # noqa: E402


def _row(title="", summary="", transcript_text="", strategy_tags=None, publish_date=None, video_id="vid00000001"):
    return {"video_id": video_id, "title": title, "channel_name": "Desk",
            "url": "https://www.youtube.com/watch?v=" + video_id, "summary": summary,
            "transcript_text": transcript_text, "quality_score": 70,
            "strategy_tags": strategy_tags, "publish_date": publish_date, "ingested_at": None}


def _fake_db(rows, *, filed=(), calls=None):
    """_db_query double: the already-filed lookup answers ``filed``; every other query answers ``rows``."""
    def query(sql, params=None, **kwargs):
        if calls is not None:
            calls.append((sql, params))
        if "transcript_intel_history" in sql:
            return [{"symbol": s, "title": t} for s, t in filed]
        return list(rows)
    return query


# ── the failing check: a substring is not a mention ───────────────────────────────────────────


def test_substring_hits_are_not_attached(monkeypatch):
    """"cdrs"/"BDRs" contain DRS; neither video names DRS."""
    rows = [_row(title="How to read CDRs", transcript_text="the cdrs market is complex"),
            _row(title="BDRs are having a year", video_id="vid00000002")]
    stats: dict = {}
    monkeypatch.setattr(atd, "_db_query", _fake_db(rows))
    assert atd.fetch_db_youtube_transcripts(["DRS"], stats=stats) == []
    assert stats["candidates"] == 2
    assert stats["rejected_not_mentioned"] == 2


def test_single_letter_ticker_is_not_matched_inside_prose(monkeypatch):
    """The 11-07 audit's T case: "don't" is not the ticker T, and a bare T needs a cashtag."""
    rows = [_row(title="Why you don't want to sell", summary="I don't know")]
    monkeypatch.setattr(atd, "_db_query", _fake_db(rows))
    assert atd.fetch_db_youtube_transcripts(["T"]) == []


def test_a_row_that_names_the_symbol_is_attached_with_its_evidence(monkeypatch):
    rows = [_row(title="DRS wins a $1.2bn Army contract", summary="Leonardo DRS guidance raised",
                 transcript_text="DRS expects margin expansion", publish_date=None)]
    monkeypatch.setattr(atd, "_db_query", _fake_db(rows))
    records = atd.fetch_db_youtube_transcripts(["DRS"])
    assert len(records) == 1
    assert records[0]["symbol"] == "DRS"
    assert records[0]["matched_by"] == "ticker"
    assert records[0]["confidence"] == pytest.approx(0.65)


def test_a_cashtag_outranks_a_bare_ticker(monkeypatch):
    rows = [_row(title="$DRS is the pick of the week", transcript_text="we bought $DRS")]
    monkeypatch.setattr(atd, "_db_query", _fake_db(rows))
    records = atd.fetch_db_youtube_transcripts(["DRS"])
    assert records[0]["matched_by"] == "cashtag"
    assert records[0]["confidence"] > atd._mention_confidence("ticker")


# ── published_at, dedupe, statistics ─────────────────────────────────────────────────────────


def test_published_at_comes_from_publish_date(monkeypatch):
    import datetime

    rows = [_row(title="SCHD outlook", publish_date=datetime.date(2026, 11, 4))]
    monkeypatch.setattr(atd, "_db_query", _fake_db(rows))
    records = atd.fetch_db_youtube_transcripts(["SCHD"])
    assert records[0]["published_at"] == "2026-11-04"


def test_a_title_already_filed_for_that_symbol_is_skipped(monkeypatch):
    rows = [_row(title="SCHD outlook", summary="SCHD dividends"), _row(title="SCHD payout", video_id="vid00000002")]
    stats: dict = {}
    monkeypatch.setattr(atd, "_db_query", _fake_db(rows, filed={("SCHD", "SCHD outlook")}))
    records = atd.fetch_db_youtube_transcripts(["SCHD"], stats=stats)
    assert [r["title"] for r in records] == ["SCHD payout"]
    assert stats["skipped_duplicate"] == 1


def test_statistics_separate_rejected_from_matched(monkeypatch):
    rows = [_row(title="How to read CDRs"), _row(title="DRS wins a contract", video_id="vid00000002")]
    stats: dict = {}
    monkeypatch.setattr(atd, "_db_query", _fake_db(rows))
    atd.fetch_db_youtube_transcripts(["DRS"], stats=stats)
    assert stats["candidates"] == 2
    assert stats["rejected_not_mentioned"] == 1
    assert stats["rejected_reasons"] == {"no_mention": 1}
    assert stats["matched_by"] == {"ticker": 1}


def test_the_sql_prefilter_is_a_whole_word_not_an_ilike(monkeypatch):
    calls: list = []
    monkeypatch.setattr(atd, "_db_query", _fake_db([], calls=calls))
    atd.fetch_db_youtube_transcripts(["DRS"])
    sql = next(s for s, _ in calls if "youtube_transcripts" in s)
    assert "ILIKE" not in sql.upper()
    assert "~ %s" in sql
    params = next(p for s, p in calls if "youtube_transcripts" in s)
    assert "%DRS%" not in params
    assert r"(^|[^[:alnum:]_])\$?DRS([^[:alnum:]_]|$)" in params


def test_a_fund_identifier_is_not_searched_for_in_text(monkeypatch):
    """FID-/SP500- codes cannot appear as a ticker in prose; the old lane still ILIKE'd them."""
    calls: list = []
    monkeypatch.setattr(atd, "_db_query", _fake_db([], calls=calls))
    assert atd.fetch_db_youtube_transcripts(["FID-1234"]) == []
    assert not [s for s, _ in calls if "youtube_transcripts" in s]
