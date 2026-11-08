"""ANCHOR: RESEARCH_INSIGHT_SYMBOL_EVIDENCE_20261108. LQ-20261107-1081.

A headline acronym that is also a listed ticker is not an insight symbol. The 2026-11-08 run wrote COLA
from a cost-of-living headline and RMD from a required-minimum-distribution headline. A symbol is accepted
only from a cashtag, the company's name, or a source symbol that is held or on the watchlist. A topic-slug
source row produces no insight.

Hermetic: a fake cursor, synthetic rows, no database, no network, no holdings file.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("TRADE_AI_CI", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    name = "lq1081_research_insight_extractor"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "research_insight_extractor.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class _Cur:
    def __init__(self):
        self.sql = ""
        self.insert_params = None

    def execute(self, sql, params=None):
        self.sql = " ".join(sql.split())
        if self.sql.startswith("INSERT INTO research_insights"):
            self.insert_params = params

    def fetchall(self):
        return []

    def fetchone(self):
        if self.sql.startswith("SELECT strategy_type"):
            return None
        if self.sql.startswith("INSERT INTO research_insights"):
            return {"id": 7}
        return None


class _Conn:
    def __init__(self, cur):
        self._cur = cur
        self.commits = 0

    def cursor(self, **_kw):
        return self._cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        pass


def _run(mod, text, symbol, *, known, universe, held=(), names=None):
    cur = _Cur()
    session = {
        "conn": _Conn(cur),
        "cur": cur,
        "known": set(known),
        "universe": set(universe),
        "held_watch": set(held),
        "names_by_symbol": {} if names is None else dict(names),
        "source_ids": {},
    }
    row = mod.extract_insight(
        text, symbol=symbol, source_type="news", source_reference="news:1", session=session,
    )
    return row, cur


def test_a_cost_of_living_headline_does_not_become_cola():
    mod = _load()
    row, cur = _run(
        mod,
        "The 2027 COLA is official and retirees will see a strong raise.",
        symbol=None,
        known={"COLA"},
        universe={"COLA"},
    )
    assert row["symbol"] is None
    assert "COLA" not in (row.get("supporting_entities") or [])
    assert cur.insert_params is None or cur.insert_params[0] is None


def test_a_required_distribution_headline_does_not_become_rmd():
    mod = _load()
    row, _cur = _run(
        mod,
        "He turned 73 and delayed his first RMD to April 1 after a dividend increase.",
        symbol=None,
        known={"RMD"},
        universe={"RMD"},
    )
    assert row["symbol"] is None
    assert "RMD" not in (row.get("supporting_entities") or [])


def test_a_parenthetical_ticker_is_not_evidence():
    mod = _load()
    row, _cur = _run(
        mod,
        "The benefit note (COLA) described a dividend cut and guidance lower for the year.",
        symbol=None,
        known={"COLA"},
        universe={"COLA"},
    )
    assert row["symbol"] is None


def test_a_cashtag_is_the_symbol():
    mod = _load()
    row, cur = _run(
        mod,
        "Traders marked $COLA after a dividend increase and strong growth this quarter.",
        symbol=None,
        known={"COLA"},
        universe={"COLA"},
    )
    assert row["symbol"] == "COLA"
    assert cur.insert_params[0] == "COLA"


def test_a_company_name_is_the_symbol_without_a_bare_ticker():
    mod = _load()
    row, _cur = _run(
        mod,
        "Coca-Cola Consolidated reported a dividend increase and strong growth this quarter.",
        symbol=None,
        known={"COLA"},
        universe={"COLA"},
        names={"COLA": ["Coca-Cola Consolidated"]},
    )
    assert row["symbol"] == "COLA"


def test_a_company_name_still_counts_when_the_bare_word_is_also_present():
    mod = _load()
    row, _cur = _run(
        mod,
        "Coca-Cola Consolidated (the bottler) reported results. The 2027 COLA is a separate benefit.",
        symbol=None,
        known={"COLA"},
        universe={"COLA"},
        names={"COLA": ["Coca-Cola Consolidated"]},
    )
    assert row["symbol"] == "COLA"


def test_a_common_first_word_of_a_truncated_name_is_not_the_company():
    mod = _load()
    row, _cur = _run(
        mod,
        "Rising income and a distribution to retirees followed the official cost-of-living notice.",
        symbol=None,
        known={"IOR", "RDAC", "DSGR"},
        universe={"IOR", "RDAC", "DSGR"},
        names={
            "IOR": ["INCOME OPPORTUNITY R"],
            "RDAC": ["RISING DRAGON ACQUIS"],
            "DSGR": ["DISTRIBUTION SOLUTIO"],
        },
    )
    assert row["symbol"] is None
    assert row.get("supporting_entities") == []


def test_the_full_issuer_phrase_is_the_company_and_the_city_name_is_not():
    mod = _load()
    kept, _cur = _run(
        mod,
        "Columbus Acquisition won shareholder approval and raised its guidance.",
        symbol=None,
        known={"COLA"},
        universe={"COLA"},
        names={"COLA": ["COLUMBUS ACQUISITION"]},
    )
    assert kept["symbol"] == "COLA"
    city, _cur = _run(
        mod,
        "The city of Columbus raised a tax and reported strong growth.",
        symbol=None,
        known={"COLA"},
        universe={"COLA"},
        names={"COLA": ["COLUMBUS ACQUISITION"]},
    )
    assert city["symbol"] is None


def test_a_one_word_issuer_name_still_counts():
    mod = _load()
    row, _cur = _run(
        mod,
        "ResMed reported a strong quarter and an upgrade.",
        symbol=None,
        known={"RMD"},
        universe={"RMD"},
        names={"RMD": ["RESMED INC"]},
    )
    assert row["symbol"] == "RMD"


def test_a_held_source_symbol_is_kept_and_a_bare_acronym_is_not_added():
    mod = _load()
    row, _cur = _run(
        mod,
        "The 2027 COLA is official.",
        symbol="aaoi",
        known={"AAOI", "COLA"},
        universe={"AAOI", "COLA"},
        held={"AAOI"},
    )
    assert row["symbol"] == "AAOI"
    assert "COLA" not in (row.get("supporting_entities") or [])


def test_a_validated_source_symbol_that_is_not_held_or_watched_is_not_kept():
    mod = _load()
    row, _cur = _run(
        mod,
        "AAOI upgrade: strong growth and a contract win for the quarter.",
        symbol="aaoi",
        known={"AAOI"},
        universe={"AAOI"},
    )
    assert row["symbol"] is None
    assert "AAOI" not in (row.get("supporting_entities") or [])


def test_a_topic_slug_is_not_inserted():
    mod = _load()
    row, cur = _run(
        mod,
        "Medicare and IRMAA planning for retirees continues into next year.",
        symbol="d194_closed_end_funds",
        known={"COLA", "IRMAA"},
        universe={"COLA", "IRMAA"},
    )
    assert row.get("skipped") == "topic_slug"
    assert row["symbol"] is None
    assert row.get("supporting_entities") == []
    assert cur.insert_params is None


def test_the_news_batch_skips_a_topic_slug_before_extraction(monkeypatch):
    mod = _load()
    rows = [
        {
            "id": 9,
            "symbol": "k_medicaid_application_planning",
            "title": "Medicare and IRMAA planning for retirees this year",
            "summary": "A benefits note that is long enough to extract.",
            "source_url": None,
        }
    ]

    class _NewsCur(_Cur):
        def fetchall(self):
            if self.sql.startswith("SELECT na.id"):
                return rows
            return []

    conn = _Conn(_NewsCur())
    monkeypatch.setattr(mod, "_open_session", lambda dry_run=False: {"conn": conn, "cur": conn.cursor()})
    seen = []

    def _extract(text, **kw):
        seen.append(kw.get("symbol"))
        return {"id": 1, "active": True, "symbol": "SHOULD_NOT_RUN"}

    monkeypatch.setattr(mod, "extract_insight", _extract)
    skips = {}
    out = mod.extract_from_news(skips=skips)
    assert seen == []
    assert out == []
    assert skips.get("topic_slug") == 1
    assert conn.commits == 0
