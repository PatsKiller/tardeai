"""A dictated ticker, a Flash demotion, and a freeform reply with no price.

2026-09-14 08:23 the operator asked "What is a x t i price right now what has been
the support and resistance is it a good option to get back into". The desk replied
"Price now: DATA_UNAVAILABLE ... Support/resistance: DATA_UNAVAILABLE" while
ticker_prices held AXTI's close (64.76) and the re-entry desk row held its zone,
stop, target, SMAs and resistance. Three defects, pinned here:

1. "a x t i" resolved no symbol (dictation spells tickers letter by letter).
2. Flash re-classified the ask as freeform, which dropped the reentry needs the
   heuristic had matched ("support and resistance", "get back into").
3. The freeform context never carried a named stock's price or levels.

Offline: registry, book and model are pinned; get_cio_snapshot is patched.
"""
from __future__ import annotations

import json
import uuid

import pytest

import scripts.lib.cio_operator_desk_loop as desk  # noqa: E402
import scripts.lib.operator_subject_resolver as osr  # noqa: E402

QUESTION = ("What is a x t i price right now what has been the support and resistance "
            "is it a good option to get back into")


def _guid(sym: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"test-registry:{sym}"))


def _registry(symbols):
    return {
        "entities": {_guid(s): {"subject_guid": _guid(s), "security_guid": _guid(s),
                                "issuer_guid": _guid("issuer:" + s), "identity_status": "CONFIRMED",
                                "aliases": [s], "active": True} for s in symbols},
        "by_symbol": {s: _guid(s) for s in symbols},
        "events": {},
    }


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    reg_path = tmp_path / "identity_registry.json"
    reg_path.write_text(json.dumps(_registry(["AXTI", "SCHG"])), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(reg_path))
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setattr(desk, "_known_symbols", lambda ttl_s=0: frozenset({"SCHG"}))
    yield


# ── 1. spelled tickers ───────────────────────────────────────────────────────


def test_spelled_ticker_binds_when_the_registry_holds_it():
    subs = osr.resolve_subjects(QUESTION, book=[], registry=_registry(["AXTI"]))
    tick = [s for s in subs if s.get("symbol")]
    assert [s["symbol"] for s in tick] == ["AXTI"]
    assert tick[0]["matched"] == "a x t i" and tick[0]["guid"] == _guid("AXTI")


def test_spelled_ticker_binds_when_the_book_holds_it():
    subs = osr.resolve_subjects("where is s c h g trading", book=["SCHG"], registry={})
    assert osr.symbols_of(subs) == ["SCHG"]


@pytest.mark.parametrize("text", ["A.X.T.I price", "a-x-t-i support", "is A X T I a buy"])
def test_other_spellings_bind(text):
    assert osr.symbols_of(osr.resolve_subjects(text, book=[], registry=_registry(["AXTI"]))) == ["AXTI"]


def test_spelled_letters_nothing_holds_are_not_a_symbol():
    subs = osr.resolve_subjects("tell me about q z x w today", book=[], registry=_registry(["AXTI"]))
    assert osr.symbols_of(subs) == []


def test_two_spelled_letters_do_not_bind_and_words_are_untouched():
    reg = _registry(["AX", "ITA", "AGO"])
    assert osr.symbols_of(osr.resolve_subjects("is a x cheap", book=[], registry=reg)) == []
    assert osr.symbols_of(osr.resolve_subjects("is it a good time to go", book=[], registry=reg)) == []


# ── 2. Flash may not demote a price / levels ask ─────────────────────────────


def _flash(monkeypatch, payload):
    import scripts.lib.cio_plan_enrichment as pe
    monkeypatch.setattr(pe, "call_governed_llm",
                        lambda messages, policy, use_pro=False, task_type=None: {"ok": True, "content": json.dumps(payload),
                                                                 "model": "test-flash"})
    monkeypatch.setattr(pe, "load_llm_policy", lambda: {})
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "1")


def test_heuristic_resolves_the_dictated_question_to_a_reentry_levels_ask():
    got = desk.analyze_operator_intent(QUESTION)
    assert got["symbols"] == ["AXTI"]
    assert got["intent"] == "reentry"
    assert {"reentry_ready", "reentry_levels"} <= set(got["needs"])
    assert got["answerable"] is True


def test_flash_freeform_cannot_drop_the_matched_levels_needs(monkeypatch):
    _flash(monkeypatch, {"intent": "freeform", "symbols": ["AXTI"], "needs": []})
    got = desk.analyze_operator_intent(QUESTION)
    assert got["source"] == "deepseek_flash"
    assert got["intent"] == "reentry", "a matched support/resistance ask stays a desk pull"
    assert {"reentry_ready", "reentry_levels"} <= set(got["needs"])


def test_flash_may_still_pick_a_desk_intent_and_keeps_the_levels_need(monkeypatch):
    _flash(monkeypatch, {"intent": "analyst_view", "symbols": ["AXTI"], "needs": ["analyst_view"]})
    got = desk.analyze_operator_intent(QUESTION)
    assert got["intent"] == "analyst_view"
    assert {"analyst_view", "reentry_levels"} <= set(got["needs"])


def test_flash_freeform_on_a_true_explainer_is_unchanged(monkeypatch):
    _flash(monkeypatch, {"intent": "freeform", "symbols": [], "needs": []})
    got = desk.analyze_operator_intent("explain how covered calls work")
    assert got["intent"] == "freeform" and not ({"reentry_ready", "reentry_levels"} & set(got["needs"]))


# ── 3. freeform context carries the named stock's price and levels ───────────


ROW = {"symbol": "AXTI", "price": 64.76, "price_as_of": "2026-09-14T07:15:01-04:00", "rsi": 42.37,
       "sma_20": 72.09, "sma_50": 63.33, "entry_low": 60.0, "entry_high": 63.5, "stop": 53.5,
       "target": 78.0, "rr": 1.18, "catalyst": {"headline": "not a level"},
       "resistance": {"state": "BELOW", "level": 96.025, "as_of": "2026-09-11", "source": "cache"}}


def _patch_house(monkeypatch, *, price=True, levels=True):
    import scripts.lib.data_broker.cio_portfolio as cp
    monkeypatch.setattr(cp, "get_cio_snapshot", lambda max_age_s=60: {"domains": {}})
    monkeypatch.setattr(desk, "subject_price_facts", lambda syms, days=45: (
        {"AXTI": {"close": 64.76, "price_date": "2026-09-14", "change_30d_pct": -6.9,
                  "bars": [["2026-09-11", 64.76], ["2026-09-14", 64.76]]}} if price else {}))
    monkeypatch.setattr(desk, "_subject_levels", lambda syms: (
        ({"AXTI": ROW}, "2026-09-14T12:24:58Z", "/x/reentry_decision_desk_latest.json") if levels else ({}, None, None)))
    monkeypatch.setattr(desk, "subject_research", lambda syms: [])


def test_freeform_context_carries_price_and_levels_for_a_named_stock(monkeypatch):
    _patch_house(monkeypatch)
    ev = desk.gather_freeform_context({"intent": "freeform", "symbols": ["AXTI"], "needs": [], "text": QUESTION})
    facts = ev["available"]["freeform_context"]
    assert facts["price_for_symbols"]["AXTI"]["close"] == 64.76
    assert "bars" not in facts["price_for_symbols"]["AXTI"]
    lv = facts["levels_for_symbols"]["AXTI"]
    assert (lv["entry_low"], lv["entry_high"], lv["stop"], lv["target"]) == (60.0, 63.5, 53.5, 78.0)
    assert lv["resistance"]["level"] == 96.025 and "catalyst" not in lv
    assert {"ticker_prices", "reentry_decision_desk"} <= set(ev["sources"])
    # The model sees them.
    assert "levels_for_symbols" in desk._facts_for_model(facts)


def test_freeform_context_names_the_gap_when_nothing_is_on_file(monkeypatch):
    _patch_house(monkeypatch, price=False, levels=False)
    ev = desk.gather_freeform_context({"intent": "freeform", "symbols": ["AXTI"], "needs": [], "text": QUESTION})
    facts = ev["available"]["freeform_context"]
    assert "price_for_symbols" not in facts and "levels_for_symbols" not in facts
    assert any(g.get("domain") == "quote_price" and g.get("symbol") == "AXTI"
               for g in ev["available"]["soft_gaps"])


def test_freeform_prompt_tells_the_model_to_use_price_and_levels():
    import inspect
    src = inspect.getsource(desk.answer_freeform_with_flash)
    assert "price_for_symbols" in src and "levels_for_symbols" in src
