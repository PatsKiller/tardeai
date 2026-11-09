"""ANCHOR: LQ1466_RESEARCH_INSIGHT_ACRONYM_STOPLIST_20261109. LQ-20261107-1466.

A source symbol that is held or watched is still refused when it is on the acronym stoplist.
The list is config/research_insight_acronym_stoplist.json, measured from active research_insights
rows (COLA, IRMAA, NAV, QCD, RMD, SSDI). A cashtag or the issuer's full name still accepts it.
A held source symbol that is not on the list is unchanged. Synthetic fixtures only: no database.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("TRADE_AI_CI", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

_MEASURED = ["COLA", "IRMAA", "NAV", "QCD", "RMD", "SSDI"]
_REAL_SHORT = {"DSL", "FN", "GIC", "CR", "ALL", "KO", "AAOI"}
_COLA_TEXT = "The 2027 COLA is official and retirees will see a strong raise."


def _load():
    name = "lq1466_research_insight_extractor"
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

    def cursor(self, **_kw):
        return self._cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _run(mod, text, symbol, *, known, universe, held=(), names=None, stoplist=None):
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
    if stoplist is not None:
        session["acronym_stoplist"] = set(stoplist)
    row = mod.extract_insight(
        text, symbol=symbol, source_type="news", source_reference="news:1", session=session,
    )
    return row, cur


def test_the_stoplist_file_is_the_measured_acronyms_only():
    doc = json.loads((ROOT / "config" / "research_insight_acronym_stoplist.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "ResearchInsightAcronymStoplist@v1"
    assert doc["symbols"] == _MEASURED
    assert _REAL_SHORT.isdisjoint(doc["symbols"])


def test_the_loader_reads_the_config_file_and_has_no_python_list():
    mod = _load()
    assert mod.load_acronym_stoplist() == set(_MEASURED)
    source = (ROOT / "scripts" / "research_insight_extractor.py").read_text(encoding="utf-8")
    assert "_MEASURED" not in source
    assert '{"COLA"' not in source
    assert "'COLA'" not in source and '"COLA"' not in source


def test_a_held_stoplisted_source_symbol_is_not_the_cost_of_living_acronym():
    mod = _load()
    row, cur = _run(
        mod, _COLA_TEXT, symbol="COLA", known={"COLA"}, universe={"COLA"}, held={"COLA"}, stoplist={"COLA"},
    )
    assert row["symbol"] is None
    assert "COLA" not in (row.get("supporting_entities") or [])
    assert cur.insert_params is None or cur.insert_params[0] is None


def test_the_config_file_blocks_a_held_source_symbol_without_an_injected_list():
    mod = _load()
    row, _cur = _run(mod, _COLA_TEXT, symbol="COLA", known={"COLA"}, universe={"COLA"}, held={"COLA"})
    assert row["symbol"] is None
    assert "COLA" not in (row.get("supporting_entities") or [])


def test_a_cashtag_still_names_a_stoplisted_symbol():
    mod = _load()
    row, cur = _run(
        mod,
        "Traders marked $COLA after a dividend increase and strong growth this quarter.",
        symbol=None,
        known={"COLA"},
        universe={"COLA"},
        stoplist=set(_MEASURED),
    )
    assert row["symbol"] == "COLA"
    assert cur.insert_params[0] == "COLA"


def test_the_full_issuer_name_still_names_a_stoplisted_symbol():
    mod = _load()
    row, _cur = _run(
        mod,
        "Coca-Cola Consolidated reported a dividend increase and strong growth this quarter.",
        symbol="COLA",
        known={"COLA"},
        universe={"COLA"},
        held={"COLA"},
        names={"COLA": ["Coca-Cola Consolidated"]},
        stoplist={"COLA"},
    )
    assert row["symbol"] == "COLA"


def test_a_cola_source_symbol_on_a_ko_headline_is_not_cola():
    mod = _load()
    row, _cur = _run(
        mod,
        "Coca-Cola delivers strong growth and an upgrade, but the stock discussed is KO.",
        symbol="COLA",
        known={"COLA", "KO"},
        universe={"COLA", "KO"},
        held={"COLA"},
        names={"COLA": ["Coca-Cola Consolidated"], "KO": ["Coca-Cola"]},
        stoplist={"COLA"},
    )
    assert row["symbol"] != "COLA"
    assert "COLA" not in (row.get("supporting_entities") or [])


def test_a_held_source_symbol_that_is_not_stoplisted_is_kept():
    mod = _load()
    row, _cur = _run(
        mod,
        "The 2027 COLA is official.",
        symbol="aaoi",
        known={"AAOI", "COLA"},
        universe={"AAOI", "COLA"},
        held={"AAOI"},
        stoplist=set(_MEASURED),
    )
    assert row["symbol"] == "AAOI"
    assert "COLA" not in (row.get("supporting_entities") or [])


def test_an_empty_injected_stoplist_does_not_drop_a_held_source_symbol():
    mod = _load()
    row, _cur = _run(
        mod,
        "AAOI upgrade: strong growth and a contract win for the quarter.",
        symbol="COLA",
        known={"COLA"},
        universe={"COLA"},
        held={"COLA"},
        stoplist=set(),
    )
    assert row["symbol"] == "COLA"
