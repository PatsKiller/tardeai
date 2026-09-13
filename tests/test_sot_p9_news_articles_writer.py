"""Phase 9 — one write module for news_articles.

Sixteen files carried their own INSERT/UPDATE against news_articles on
2026-09-13 (config/data_source_authority_baseline.json: writers.news_articles = 16).
After this phase the gate's regex finds exactly one: scripts/lib/writers/
news_articles_writer.py. These tests are pure — a fake cursor records SQL and
params, the identity registry is a temp file (autouse), nothing touches a database.

For every legacy writer there is a golden test: the input the legacy hunk fed is
fed to the module, and the emitted statement is checked column-by-column and
value-by-value against what the legacy SQL wrote. Rails, dedupe, identity and
the writer-count reduction are pinned separately.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_data_source_authority as gate  # noqa: E402
from lib import identity_registry as REG  # noqa: E402
from lib import research_identity as RI  # noqa: E402
from lib import security_identity as SI  # noqa: E402
from lib.writers import news_articles_writer as W  # noqa: E402

AUTH = json.loads((ROOT / "config" / "data_source_authority.json").read_text())
BASELINE = json.loads((ROOT / "config" / "data_source_authority_baseline.json").read_text())
IDENTITY = ["subject_guid", "issuer_guid", "identity_status", "identity_tagged_at"]

#: The sixteen files the baseline counted (gate regex, 2026-09-13, before this phase).
LEGACY_WRITERS = [
    "scripts/news_ingestion.py", "scripts/symbol_enrichment.py", "scripts/premarket_watcher.py",
    "scripts/finviz_proactive_research.py", "scripts/hermes_news_bridge.py",
    "scripts/telegram_command_handler.py", "scripts/external_market_data_ingest.py",
    "scripts/topic_ingestion.py", "scripts/sentiment_processor.py", "scripts/topic_curator.py",
    "scripts/_news_strategy_classifier.py", "scripts/iris_taxonomy_agent.py", "scripts/api_v2.py",
    "scripts/inference_layers.py", "scripts/run_deep_overnight_llm_queue.py", "scripts/region_tag_news.py",
]


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """No test here may read the production identity registry (rule d)."""
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "identity_registry.json"))
    monkeypatch.setattr(W, "_IDENTITY_COLUMNS_PRESENT", None)
    yield


def _seed(rows):
    """Mint into the TEMP registry only (env pinned above)."""
    REG.register_all(rows, apply=True)
    return REG.load()


class FakeCursor:
    """Records every statement; answers the probe, the dedupe SELECT and RETURNING id."""

    def __init__(self, *, identity_cols=True, existing=None, dict_rows=False):
        self.calls: list[tuple[str, list | None]] = []
        self.identity_cols = identity_cols
        self.existing = list(existing or [])
        self.dict_rows = dict_rows
        self.rowcount = -1
        self._pending: list = []
        self._next_id = 101

    def _row(self, *vals, keys=("id",)):
        return dict(zip(keys, vals)) if self.dict_rows else tuple(vals)

    def execute(self, sql, params=None):
        params = list(params) if params is not None else None
        self.calls.append((sql, params))
        s = " ".join(sql.split())
        if "information_schema.columns" in s:
            self._pending = [self._row(c, keys=("column_name",)) for c in IDENTITY] if self.identity_cols else []
        elif s.startswith("SELECT id FROM news_articles"):
            self._pending = [self._row(1)] if self._dup(s, params) else []
        elif s.startswith("INSERT INTO news_articles"):
            cols, vals = parse_insert(sql, params)
            self.existing.append(dict(zip(cols, vals)))
            self._pending = [self._row(self._next_id)]
            self._next_id += 1
            self.rowcount = 1
        elif s.startswith("UPDATE news_articles"):
            self._pending = []
            self.rowcount = 7
        else:
            self._pending = []

    def _dup(self, s, params):
        p = list(params or [])
        sym = None if "symbol IS NULL" in s else p.pop(0)
        url = p.pop(0) if "source_url = %s" in s else None
        title = p.pop(0) if "title = %s" in s else None
        for r in self.existing:
            if r.get("symbol") != sym:
                continue
            if (url and r.get("source_url") == url) or (title and r.get("title") == title):
                return True
        return False

    def fetchone(self):
        return self._pending[0] if self._pending else None

    def fetchall(self):
        return list(self._pending)


_INSERT = re.compile(r"INSERT INTO news_articles \((.*?)\) VALUES \((.*?)\) ON CONFLICT DO NOTHING RETURNING id", re.S)


def parse_insert(sql, params):
    """(columns, values) with NOW() rendered as W.SQL_NOW so a golden test can compare."""
    m = _INSERT.search(sql)
    assert m, sql
    cols = [c.strip() for c in m.group(1).split(",")]
    slots = [p.strip() for p in m.group(2).split(",")]
    it = iter(params)
    vals = [W.SQL_NOW if p == "NOW()" else next(it) for p in slots]
    assert len(cols) == len(vals)
    return cols, vals


def inserts(cur):
    return [parse_insert(sql, p) for sql, p in cur.calls if sql.lstrip().startswith("INSERT INTO news_articles")]


def updates(cur):
    return [(" ".join(sql.split()), p) for sql, p in cur.calls if sql.lstrip().startswith("UPDATE news_articles")]


def strip_identity(cols, vals):
    keep = [i for i, c in enumerate(cols) if c not in IDENTITY]
    return [cols[i] for i in keep], [vals[i] for i in keep]


# ── golden: the eight INSERT writers ─────────────────────────────────────────


def test_golden_news_ingestion_row_shape_and_identity():
    doc = _seed([{"symbol": "NOC", "company": "Northrop Grumman", "cik": "1133421"}])
    cur = FakeCursor()
    a = {"title": "Northrop wins award", "summary": "B-21 lot", "source": "yahoo_rss",
         "source_url": "https://finance.yahoo.com/n/1", "published_at": "2026-09-13T10:00:00+00:00"}
    tags = {"strategy_tags": ["defense"], "agent_tags": ["Aegis"]}
    rc = W.write_news_articles(cur, [{
        "symbol": "NOC", "strategy_type": "traded", "title": a["title"][:500], "summary": a["summary"][:1000],
        "source": a["source"], "source_url": a["source_url"][:500], "published_at": a["published_at"],
        "relevance_score": 0.62, "strategy_tags": json.dumps(tags["strategy_tags"]),
        "agent_tags": json.dumps(tags["agent_tags"]),
    }], source="yahoo_rss")
    assert rc.rows_in == rc.rows_written == 1 and rc.rows_rejected == rc.rows_duplicate == 0
    (cols, vals), = inserts(cur)
    base_cols, base_vals = strip_identity(cols, vals)
    # Legacy: INSERT (symbol, strategy_type, title, summary, source, source_url, published_at,
    #                 relevance_score, strategy_tags, agent_tags)
    assert base_cols == ["symbol", "strategy_type", "title", "summary", "source", "source_url",
                         "published_at", "relevance_score", "strategy_tags", "agent_tags"]
    assert base_vals == ["NOC", "traded", "Northrop wins award", "B-21 lot", "yahoo_rss",
                         "https://finance.yahoo.com/n/1", "2026-09-13T10:00:00+00:00", 0.62,
                         '["defense"]', '["Aegis"]']
    # Identity: the registry's GUID, never NULL where the resolver has one (rule a).
    ident = dict(zip(cols, vals))
    expected = RI.resolve(doc, "NOC")
    assert ident["subject_guid"] == expected["subject_guid"]
    assert ident["issuer_guid"] == expected["issuer_guid"] == SI.issuer_guid(cik="1133421")
    assert ident["identity_status"] == expected["identity_status"] == "CANDIDATE"
    assert ident["identity_tagged_at"] is W.SQL_NOW
    assert rc.identity_resolved == 1 and rc.ids == [101]


def test_golden_symbol_enrichment_sec_edgar():
    cur = FakeCursor()
    url = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=ACME&type=8-K"
    rc = W.write_news_articles(cur, [{"symbol": "ACME", "title": "ACME 8-K filed"[:300], "source": "sec_edgar_filing",
                                      "source_url": url[:500], "relevance_score": 85, "published_at": W.SQL_NOW}],
                               source="sec_edgar_filing")
    assert rc.rows_written == 1
    (cols, vals), = inserts(cur)
    # Legacy: INSERT (symbol, title, source, source_url, relevance_score, published_at) VALUES (..., NOW()).
    # Same columns, same values; the module owns column ORDER (published_at before relevance_score).
    base_cols, base_vals = strip_identity(cols, vals)
    assert set(base_cols) == {"symbol", "title", "source", "source_url", "relevance_score", "published_at"}
    assert dict(zip(base_cols, base_vals)) == {"symbol": "ACME", "title": "ACME 8-K filed", "source": "sec_edgar_filing",
                                               "source_url": url, "relevance_score": 85, "published_at": W.SQL_NOW}
    sql = cur.calls[-1][0]
    assert sql.count("NOW()") == 1 and "published_at" in sql
    # ACME is not in the (temp) registry: identity stays NULL — nothing invented (rule a/c).
    assert not set(cols) & set(IDENTITY) and rc.identity_unresolved == 1


def test_golden_premarket_watcher_yahoo_premarket():
    cur = FakeCursor()
    rc = W.write_news_articles(cur, [{"symbol": "XYZ", "title": "XYZ pre-market mover", "source": "yahoo_premarket",
                                      "source_url": "https://y/x", "relevance_score": 65, "published_at": W.SQL_NOW}],
                               source="yahoo_premarket")
    (cols, vals), = inserts(cur)
    assert dict(zip(*strip_identity(cols, vals))) == {"symbol": "XYZ", "title": "XYZ pre-market mover",
                                                      "source": "yahoo_premarket", "source_url": "https://y/x",
                                                      "relevance_score": 65, "published_at": W.SQL_NOW}
    assert rc.source == "yahoo_premarket"


def test_golden_finviz_proactive_research():
    cur = FakeCursor()
    pub = datetime.fromtimestamp(1757757600, tz=timezone.utc)
    rc = W.write_news_articles(cur, [{
        "symbol": "LMT", "strategy_type": "LMT", "title": "Lockheed lands contract", "summary": "",
        "source": "finviz_news", "source_url": "https://finviz.com/n/9", "published_at": pub,
        "relevance_score": 0.5, "strategy_tags": json.dumps([]), "agent_tags": json.dumps([]),
    }], source="finviz_news")
    (cols, vals), = inserts(cur)
    # Legacy: VALUES (%s,%s,%s,%s,'finviz_news',%s,%s,%s,%s,%s) with strategy_type = sym, summary = ""
    assert strip_identity(cols, vals) == (
        ["symbol", "strategy_type", "title", "summary", "source", "source_url", "published_at",
         "relevance_score", "strategy_tags", "agent_tags"],
        ["LMT", "LMT", "Lockheed lands contract", "", "finviz_news", "https://finviz.com/n/9", pub, 0.5, "[]", "[]"])
    assert rc.rows_written == 1


def test_golden_hermes_news_bridge_returns_id_and_keeps_payload():
    cur = FakeCursor()
    payload = {"hermes_research_id": 42, "research_type": "momentum_catalyst", "bridged_by": "hermes_news_bridge.py",
               "hermes_confidence": 0.81, "quality_score": 70, "validation_status": "validated"}
    created = datetime(2026, 9, 12, 8, 0, tzinfo=timezone.utc)
    rc = W.write_news_articles(cur, [{
        "symbol": "RTX", "strategy_type": "defense", "title": "RTX raises guidance", "summary": None,
        "source": "hermes", "source_url": "https://h/1", "published_at": created,
        "relevance_score": 0.733, "raw_payload": json.dumps(payload),
    }], source="hermes")
    (cols, vals), = inserts(cur)
    # Legacy: (symbol, strategy_type, title, summary, source, source_url, published_at, relevance_score,
    #          raw_payload, created_at=now()) RETURNING id — created_at DEFAULT NOW() carries the last one.
    assert strip_identity(cols, vals) == (
        ["symbol", "strategy_type", "title", "summary", "source", "source_url", "published_at", "relevance_score", "raw_payload"],
        ["RTX", "defense", "RTX raises guidance", None, "hermes", "https://h/1", created, 0.733, json.dumps(payload)])
    assert rc.ids == [101]
    assert json.loads(dict(zip(cols, vals))["raw_payload"])["hermes_research_id"] == 42


def test_golden_telegram_manual_add():
    cur = FakeCursor()
    rc = W.write_news_articles(cur, [{
        "symbol": "manual_add", "strategy_type": "manual_add", "title": "An article", "summary": "body text",
        "source": "telegram_article", "source_url": "https://site/a", "published_at": W.SQL_NOW,
        "relevance_score": 0.5, "strategy_tags": "[]", "agent_tags": "[]",
    }], source="telegram_article")
    (cols, vals), = inserts(cur)
    assert strip_identity(cols, vals)[1] == ["manual_add", "manual_add", "An article", "body text", "telegram_article",
                                             "https://site/a", W.SQL_NOW, 0.5, "[]", "[]"]
    # 'manual_add' is not a security and not registered: identity left NULL, not invented.
    assert not set(cols) & set(IDENTITY) and rc.rows_written == 1


def test_golden_external_alpha_vantage_sentiment_row():
    cur = FakeCursor()
    rc = W.write_news_articles(cur, [{
        "symbol": "NVDA", "title": "Nvidia beats", "summary": "s", "source": "av:Benzinga",
        "source_url": "https://bz/1", "published_at": date(2026, 9, 12), "relevance_score": round(0.45 * 100),
        "sentiment": "bullish", "sentiment_score": round(0.3141, 3),
        "strategy_tags": json.dumps(["av_sentiment_bullish"]),
    }], source="av:Benzinga")
    (cols, vals), = inserts(cur)
    # Legacy: (symbol, title, summary, source, source_url, published_at, relevance_score, sentiment,
    #          sentiment_score, strategy_tags::jsonb) ON CONFLICT DO NOTHING
    assert strip_identity(cols, vals) == (
        ["symbol", "title", "summary", "source", "source_url", "published_at", "relevance_score",
         "sentiment", "sentiment_score", "strategy_tags"],
        ["NVDA", "Nvidia beats", "s", "av:Benzinga", "https://bz/1", date(2026, 9, 12), 45, "bullish", 0.314,
         '["av_sentiment_bullish"]'])
    assert "ON CONFLICT DO NOTHING" in cur.calls[-1][0]
    assert rc.rows_written == 1  # the 0-100 relevance scale this lane writes is inside the rail


def test_golden_topic_ingestion_topic_identity():
    from backfill_subject_identity import topic_guid
    cur = FakeCursor()
    rc = W.write_news_articles(cur, [{
        "symbol": "d107_energy_transition", "strategy_type": "d107_energy_transition", "title": "Grid storage boom",
        "summary": "summary", "source": "topic_google_news_rss", "source_url": "https://g/1",
        "published_at": None, "relevance_score": 0.5,
        "strategy_tags": json.dumps(["energy"]), "agent_tags": json.dumps(["Maya"]),
    }], source="topic_google_news_rss", subject_kind="topic")
    (cols, vals), = inserts(cur)
    row = dict(zip(cols, vals))
    assert strip_identity(cols, vals)[1] == ["d107_energy_transition", "d107_energy_transition", "Grid storage boom",
                                             "summary", "topic_google_news_rss", "https://g/1", None, 0.5,
                                             '["energy"]', '["Maya"]']
    # Same deterministic GUID backfill_subject_identity stamps on topic rows; symbol case untouched.
    assert row["subject_guid"] == topic_guid("d107_energy_transition")
    assert row["identity_status"] == "CONFIRMED" and row["issuer_guid"] is None
    assert rc.identity_resolved == 1


# ── golden: the eight UPDATE writers ─────────────────────────────────────────


def test_golden_sentiment_processor():
    cur = FakeCursor()
    assert W.set_sentiment(cur, 5, "positive", 0.25) == 7
    assert updates(cur) == [("UPDATE news_articles SET sentiment = %s, sentiment_score = %s WHERE id = %s",
                             ["positive", 0.25, 5])]


def test_golden_topic_curator_auto_approve_and_rating():
    cur = FakeCursor()
    W.approve_pending_by_relevance(cur, source_prefix="topic_", min_relevance=0.4, reason="auto: relevance >= 0.4")
    W.set_rag_status(cur, 9, "low_quality", "thin")
    ((sql1, p1), (sql2, p2)) = updates(cur)
    assert sql1 == ("UPDATE news_articles SET rag_status='approved', rag_reason=%s "
                    "WHERE rag_status='pending' AND source LIKE %s AND relevance_score >= %s")
    assert p1 == ["auto: relevance >= 0.4", "topic_%", 0.4]
    assert (sql2, p2) == ("UPDATE news_articles SET rag_status=%s, rag_reason=%s WHERE id=%s", ["low_quality", "thin", 9])


def test_golden_strategy_classifier():
    cur = FakeCursor()
    W.set_strategy_classification(cur, 3, "retirement_income", "high")
    assert updates(cur) == [("UPDATE news_articles SET strategy_type = %s, retirement_relevance = %s WHERE id = %s",
                             ["retirement_income", "high", 3])]


def test_golden_iris_archive_and_duplicate_flagging():
    cur = FakeCursor()
    W.archive_article(cur, 11, "stale > 60d")
    n = W.flag_title_duplicates(cur, days=90)
    (sql1, p1), (sql2, p2) = updates(cur)
    assert (sql1, p1) == ("UPDATE news_articles SET hygiene_status='archived', demoted_at=NOW(), demoted_reason=%s WHERE id=%s",
                          ["stale > 60d", 11])
    assert "PARTITION BY LEFT(LOWER(TRIM(title)), 60)" in sql2
    assert "ORDER BY relevance_score DESC NULLS LAST, created_at ASC" in sql2
    assert "AND NOT COALESCE(is_duplicate, FALSE)" in sql2 and "make_interval(days => %s)" in sql2
    assert p2 == [90] and n == 7


def test_golden_api_v2_admin_reassign():
    cur = FakeCursor()
    W.reassign_strategy_type(cur, "defense_thesis", "investment_general")
    assert updates(cur) == [("UPDATE news_articles SET strategy_type=%s WHERE strategy_type=%s",
                             ["investment_general", "defense_thesis"])]


def test_golden_region_tagging_both_callers():
    cur = FakeCursor()
    hits = ["china", "taiwan", "export", "chips", "tsmc", "asia", "tariff", "yuan", "ninth"]
    W.set_region(cur, 21, "asia", hits[:8])          # region_tag_news: json.dumps(hits[:8])
    W.set_region(cur, 22, "europe", ["ecb"])         # inference_layers: json.dumps(kws)
    (s1, p1), (s2, p2) = updates(cur)
    assert s1 == s2 == "UPDATE news_articles SET region=%s, geo_keywords=%s, region_tagged_at=now() WHERE id=%s"
    assert p1 == ["asia", json.dumps(hits[:8]), 21] and p2 == ["europe", '["ecb"]', 22]


def test_golden_deep_curation_with_and_without_rag_promotion():
    cur = FakeCursor()
    W.set_deep_curation(cur, 31, "APPROVE_BOOST", 1.25, rag_status="approved")
    W.set_deep_curation(cur, 32, "LOW_QUALITY", 0.4, rag_status=None)
    (s1, p1), (s2, p2) = updates(cur)
    assert s1 == ("UPDATE news_articles SET deep_curation_verdict=%s, deep_curation_at=NOW(), "
                  "deep_curation_weight=%s, rag_status=%s WHERE id=%s")
    assert p1 == ["APPROVE_BOOST", 1.25, "approved", 31]
    assert s2 == "UPDATE news_articles SET deep_curation_verdict=%s, deep_curation_at=NOW(), deep_curation_weight=%s WHERE id=%s"
    assert p2 == ["LOW_QUALITY", 0.4, 32]


# ── rails: rejected rows are returned, not written ───────────────────────────


@pytest.mark.parametrize("source", ["finnhub", "newsapi", "polygon", "fmp", "search:polygon", "FINNHUB"])
def test_retired_provider_row_is_rejected_not_written(source):
    assert source.split(":")[-1].lower() in AUTH["providers"] and AUTH["providers"][source.split(":")[-1].lower()]["status"] == "retired"
    cur = FakeCursor()
    rc = W.write_news_articles(cur, [{"symbol": "AAPL", "title": "t", "source": source, "source_url": "https://x/1"}])
    assert rc.rows_rejected == 1 and rc.rows_written == 0 and inserts(cur) == []
    assert rc.rejected[0]["reason"].startswith("RETIRED_PROVIDER:")
    assert rc.rejected[0]["symbol"] == "AAPL"


@pytest.mark.parametrize("source", ["search:brave", "search:searxng", "finviz_news", "yahoo_rss", "hermes",
                                    "topic_google_news_rss", "av:Benzinga", "telegram_article", "sec_edgar_filing"])
def test_live_source_labels_are_preserved_verbatim(source):
    cur = FakeCursor()
    rc = W.write_news_articles(cur, [{"symbol": "AAPL", "title": "t", "source": source, "source_url": "https://x/1"}])
    assert rc.rows_written == 1
    (cols, vals), = inserts(cur)
    assert dict(zip(cols, vals))["source"] == source


@pytest.mark.parametrize("row,reason", [
    ({"symbol": "A", "title": "", "source": "yahoo_rss"}, "EMPTY_TITLE"),
    ({"symbol": "A", "title": "x", "source": ""}, "EMPTY_SOURCE"),
    ({"symbol": "A", "title": "x", "source": "yahoo_rss", "relevance_score": 250}, "RELEVANCE_OUT_OF_RANGE:250"),
    ({"symbol": "A", "title": "x", "source": "yahoo_rss", "relevance_score": -0.1}, "RELEVANCE_OUT_OF_RANGE:-0.1"),
    ({"symbol": "A", "title": "x", "source": "yahoo_rss", "relevance_score": float("nan")}, "RELEVANCE_OUT_OF_RANGE:nan"),
    ({"symbol": "A", "title": "x", "source": "av:x", "sentiment_score": 1.5}, "SENTIMENT_OUT_OF_RANGE:1.5"),
    ({"symbol": "A", "title": "x", "source": "yahoo_rss", "published_at": 12345}, "BAD_PUBLISHED_AT:int"),
])
def test_off_rail_row_is_returned_with_reason(row, reason):
    cur = FakeCursor()
    rc = W.write_news_articles(cur, [row])
    assert rc.rows_written == 0 and rc.rows_rejected == 1 and inserts(cur) == []
    assert rc.rejected[0]["reason"] == reason


def test_mixed_batch_receipt_adds_up_and_keeps_good_rows(caplog):
    cur = FakeCursor(existing=[{"symbol": "MSFT", "source_url": "https://m/1", "title": "old"}])
    with caplog.at_level("WARNING"):
        rc = W.write_news_articles(cur, [
            {"symbol": "MSFT", "title": "new headline", "source": "yahoo_rss", "source_url": "https://m/2"},
            {"symbol": "MSFT", "title": "another", "source": "yahoo_rss", "source_url": "https://m/1"},   # dup by url
            {"symbol": "MSFT", "title": "bad", "source": "finnhub"},                                     # retired
        ], source="yahoo_rss")
    assert (rc.rows_in, rc.rows_written, rc.rows_duplicate, rc.rows_rejected) == (3, 1, 1, 1)
    assert rc.rows_in == rc.rows_written + rc.rows_duplicate + rc.rows_rejected
    assert "RETIRED_PROVIDER:finnhub" in caplog.text
    assert rc.schema == "NewsArticlesWriteReceipt@v1" and rc.table == "news_articles"


def test_update_rails_raise_loudly():
    cur = FakeCursor()
    with pytest.raises(W.NewsArticleRejected):
        W.set_sentiment(cur, 1, "positive", 3.0)
    with pytest.raises(W.NewsArticleRejected):
        W.set_rag_status(cur, 1, "maybe", "")
    with pytest.raises(W.NewsArticleRejected):
        W.set_deep_curation(cur, 1, "APPROVE_BOOST", 1.0, rag_status="great")
    with pytest.raises(W.NewsArticleRejected):
        W.flag_title_duplicates(cur, days=0)
    assert updates(cur) == []


def test_title_summary_url_truncation_is_the_modules_rule():
    cur = FakeCursor()
    W.write_news_articles(cur, [{"symbol": "A", "title": "t" * 900, "summary": "s" * 2000, "source": "yahoo_rss",
                                 "source_url": "https://x/" + "u" * 900}])
    (cols, vals), = inserts(cur)
    row = dict(zip(cols, vals))
    assert len(row["title"]) == 500 and len(row["summary"]) == 1000 and len(row["source_url"]) == 500


# ── dedupe: ONE rule ─────────────────────────────────────────────────────────


def test_dedupe_same_symbol_same_url_is_duplicate():
    cur = FakeCursor(existing=[{"symbol": "NOC", "source_url": "https://n/1", "title": "A"}])
    rc = W.write_news_articles(cur, [{"symbol": "NOC", "title": "B", "source": "yahoo_rss", "source_url": "https://n/1"}])
    assert rc.rows_duplicate == 1 and rc.rows_written == 0 and inserts(cur) == []


def test_dedupe_same_symbol_same_title_is_duplicate():
    cur = FakeCursor(existing=[{"symbol": "NOC", "source_url": "https://n/1", "title": "Same headline"}])
    rc = W.write_news_articles(cur, [{"symbol": "NOC", "title": "Same headline", "source": "hermes", "source_url": None}])
    assert rc.rows_duplicate == 1 and inserts(cur) == []
    sql = cur.calls[-1][0]
    assert "source_url" not in sql and "title = %s" in sql  # no url on the new row -> title clause only


def test_dedupe_is_per_symbol_a_shared_headline_reaches_every_ticker():
    """finviz: 'CVX,NOC,LMT' saves once per universe ticker it mentions."""
    cur = FakeCursor(existing=[{"symbol": "CVX", "source_url": "https://f/1", "title": "Oil and defense"}])
    rc = W.write_news_articles(cur, [{"symbol": s, "title": "Oil and defense", "source": "finviz_news", "source_url": "https://f/1"}
                                     for s in ("CVX", "NOC", "LMT")])
    assert (rc.rows_written, rc.rows_duplicate) == (2, 1)
    assert [dict(zip(c, v))["symbol"] for c, v in inserts(cur)] == ["NOC", "LMT"]


def test_second_identical_write_in_the_same_batch_is_a_duplicate():
    cur = FakeCursor()
    row = {"symbol": "AAPL", "title": "t", "source": "yahoo_rss", "source_url": "https://a/1"}
    rc = W.write_news_articles(cur, [row, dict(row)])
    assert (rc.rows_written, rc.rows_duplicate) == (1, 1)


def test_is_duplicate_is_the_public_precheck_producers_call():
    cur = FakeCursor(existing=[{"symbol": "manual_add", "source_url": "https://u/1", "title": "x"}])
    assert W.is_duplicate(cur, "manual_add", "https://u/1") is True
    assert W.is_duplicate(cur, "manual_add", "https://u/2") is False
    assert W.is_duplicate(cur, "manual_add") is False  # nothing to match on -> not a duplicate


# ── identity: rules (a)–(e) ───────────────────────────────────────────────────


def test_symbol_only_row_round_trips_to_the_registry_guid(tmp_path):
    """Rule (c): ticker is an alias; the GUID is whatever the registry resolves today."""
    doc = _seed([{"symbol": "SCHD", "company": "Schwab US Dividend Equity ETF"}])
    ent = REG.lookup_symbol(doc, "SCHD")
    expected = REG.subject_guid_of(ent, "SCHD")
    got = W.resolve_identity("schd ")
    assert got["subject_guid"] == expected == RI.resolve(doc, "SCHD")["subject_guid"]
    assert got["resolved_via"] == "registry" and got["issuer_guid"] == ent["issuer_guid"]
    # and the same GUID lands in the INSERT
    cur = FakeCursor()
    W.write_news_articles(cur, [{"symbol": "SCHD", "title": "t", "source": "yahoo_rss", "source_url": "https://s/1"}])
    (cols, vals), = inserts(cur)
    assert dict(zip(cols, vals))["subject_guid"] == expected


def test_registry_upgrade_chain_is_followed_never_rewritten():
    """Rule (b): registry-first through resolve_guid; a superseded id still resolves forward."""
    doc = _seed([{"symbol": "V", "company": "Visa Inc"}])
    weak = REG.lookup_symbol(doc, "V")["subject_guid"]
    doc = _seed([{"symbol": "V", "company": "Visa Inc", "cik": "1403161", "identifiers": {"cusip": "92826C839"}}])
    strong = REG.lookup_symbol(doc, "V")["subject_guid"]
    assert weak != strong
    assert doc["entities"][weak]["superseded_by"] == strong          # old id retained, points forward
    assert REG.resolve_guid(doc, weak) == strong
    got = W.resolve_identity("V", registry=doc)
    assert got["subject_guid"] == strong and got["identity_status"] == "CONFIRMED"


def test_row_with_cik_or_company_for_an_unregistered_symbol_uses_the_spine():
    got = W.resolve_identity("NEWCO", cik="0000012345", company="Newco Holdings")
    spine = SI.resolve_identity_spine({"symbol": "NEWCO", "cik": "0000012345", "company": "Newco Holdings"})
    assert got["resolved_via"] == "spine"
    assert got["issuer_guid"] == spine["issuer_guid"] == SI.issuer_guid(cik="0000012345")
    assert got["subject_guid"] == REG.subject_guid_of(spine, "NEWCO") == spine["security_guid"]
    assert got["identity_status"] == "CANDIDATE"
    # ... and it is exactly what identity_registry.register would have minted for that row.
    doc = _seed([{"symbol": "NEWCO", "cik": "0000012345", "company": "Newco Holdings"}])
    assert REG.lookup_symbol(doc, "NEWCO")["subject_guid"] == got["subject_guid"]


def test_unregistered_symbol_only_row_writes_no_identity_and_invents_none():
    got = W.resolve_identity("ZZZQ")
    assert got == {"subject_guid": None, "issuer_guid": None, "identity_status": None,
                   "resolved_via": None, "lookup_failed": False}
    cur = FakeCursor()
    rc = W.write_news_articles(cur, [{"symbol": "ZZZQ", "title": "t", "source": "yahoo_rss", "source_url": "https://z/1"}])
    (cols, _), = inserts(cur)
    assert not set(cols) & set(IDENTITY) and rc.identity_unresolved == 1 and rc.rows_written == 1


@pytest.mark.parametrize("sym", ["CASH", "PORTFOLIO", "MMKT", "", None])
def test_non_entity_symbols_get_no_identity(sym):
    assert W.resolve_identity(sym)["subject_guid"] is None


def test_identity_columns_absent_means_no_identity_columns_written():
    _seed([{"symbol": "NOC", "cik": "1133421"}])
    cur = FakeCursor(identity_cols=False)
    rc = W.write_news_articles(cur, [{"symbol": "NOC", "title": "t", "source": "yahoo_rss", "source_url": "https://n/1"}])
    (cols, _), = inserts(cur)
    assert not set(cols) & set(IDENTITY) and rc.identity_columns_present is False


def test_identity_probe_is_the_information_schema_and_is_cached():
    _seed([{"symbol": "NOC", "cik": "1133421"}])
    cur = FakeCursor(dict_rows=True)  # RealDictCursor-shaped rows must work too
    W.write_news_articles(cur, [{"symbol": "NOC", "title": "a", "source": "yahoo_rss", "source_url": "https://n/1"}])
    W.write_news_articles(cur, [{"symbol": "NOC", "title": "b", "source": "yahoo_rss", "source_url": "https://n/2"}])
    probes = [c for c in cur.calls if "information_schema.columns" in c[0]]
    assert len(probes) == 1 and probes[0][1] == ["news_articles", IDENTITY]
    assert all("subject_guid" in cols for cols, _ in inserts(cur))


def test_registry_read_failure_is_reported_not_stamped(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("registry unreadable")
    monkeypatch.setattr(REG, "lookup_symbol", boom)
    got = W.resolve_identity("NOC", registry={})
    assert got["lookup_failed"] is True and got["subject_guid"] is None


# ── the reduction: 16 -> 1, and the module is the one ────────────────────────


def test_negative_control_baseline_was_plural_and_now_exactly_one_writer():
    assert BASELINE["writers"]["news_articles"] > 1          # 16 on 2026-09-13
    writers = gate.count_writers(AUTH, gate._files())
    assert writers["news_articles"] == 1, writers


def test_the_one_writer_is_the_module_and_no_legacy_file_carries_sql():
    pat = re.compile(r"\b(INSERT\s+INTO|UPDATE|COPY)\s+news_articles\b", re.I)
    hits = sorted(str(p.relative_to(ROOT)) for p in gate._files() if pat.search(p.read_text(encoding="utf-8", errors="replace")))
    assert hits == ["scripts/lib/writers/news_articles_writer.py"]
    for rel in LEGACY_WRITERS:
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        assert not pat.search(text), rel
        if rel != "scripts/lib/writers/news_articles_writer.py":
            assert "news_articles_writer" in text, f"{rel} must call the write module"


def test_news_ingestion_is_the_registry_target_and_re_exports_the_module():
    domain = next(d for d in AUTH["domains"] if d["store"]["table"] == "news_articles")
    assert domain["writer"] == "scripts/lib/writers/news_articles_writer.py"
    assert domain["writer_facade"] == "scripts/news_ingestion.py"
    import news_ingestion as ni
    assert ni.write_news_articles is W.write_news_articles
    assert ni.set_region is W.set_region and ni.SQL_NOW is W.SQL_NOW


def test_gate_regex_still_sees_the_module_when_table_is_literal():
    """count_writers scans source text — the module must spell the table out, not interpolate it."""
    src = (ROOT / "scripts/lib/writers/news_articles_writer.py").read_text()
    assert "INSERT INTO news_articles (" in src and "UPDATE news_articles SET" in src
    assert "{TABLE}" not in src
