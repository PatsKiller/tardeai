"""Intent and subject resolution, measured against the operator's REAL questions.

2026-09-13 18:50: "Is now a good time to get back into schg" resolved no symbol
and the desk answered with the whole re-entry book. The base fix matched known
symbols in any case. This suite pins what came after:

- `operator_subject_resolver.resolve_subjects` resolves tickers (book any case,
  registry upper-case), company names through the broker instrument feed, sector
  words and topics -- each symbol with its registry GUID, never a minted one.
- `analyze_operator_intent` fills `symbols` and `subjects` from it on the heuristic
  AND the Flash path; Flash may add a verified symbol, never remove one.
- tests/fixtures/operator_questions_20260913.json holds the operator's real
  questions; every one must route as the fixture says.

Offline: identity registry, instrument feed and book are pinned to temp values.
No model is called (CIO_OPERATOR_INTENT_FLASH=0; the Flash tests patch the call).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "operator_questions_20260913.json").read_text(encoding="utf-8"))
ENV = FIXTURE["environment"]

import scripts.lib.cio_operator_desk_loop as desk  # noqa: E402
import scripts.lib.company_name_index as cni  # noqa: E402
import scripts.lib.operator_subject_resolver as osr  # noqa: E402


def _guid(sym: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"test-registry:{sym}"))


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """Never the production registry, instrument feed, book or model."""
    reg = {
        "entities": {_guid(s): {"subject_guid": _guid(s), "security_guid": _guid(s), "issuer_guid": _guid("issuer:" + s),
                                "identity_status": "CONFIRMED", "aliases": [s], "active": True}
                     for s in ENV["registry_symbols"]},
        "by_symbol": {s: _guid(s) for s in ENV["registry_symbols"]},
        "events": {},
    }
    reg_path = tmp_path / "identity_registry.json"
    reg_path.write_text(json.dumps(reg), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(reg_path))

    inst_path = tmp_path / "schwab_instrument_evidence.json"
    from scripts.lib.schwab_instrument_evidence import SCHEMA as INSTRUMENT_SCHEMA  # load() rejects a doc without it
    inst_path.write_text(json.dumps({"schema": INSTRUMENT_SCHEMA, "instruments": {
        sym: {"description": desc, "identifiers": {"cusip": f"TEST{sym}"}} for sym, desc in ENV["instruments"].items()
    }}), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_SCHWAB_INSTRUMENT_EVIDENCE", str(inst_path))
    cni.refresh()

    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "0")
    monkeypatch.setattr(desk, "_known_symbols", lambda ttl_s=0: frozenset(ENV["book"]))
    yield reg_path
    cni.refresh()


def _subject_matches(expected: dict, got: dict) -> bool:
    return all(got.get(k) == v for k, v in expected.items())


# ── the operator's real questions ────────────────────────────────────────────


@pytest.mark.parametrize("q", FIXTURE["questions"], ids=[q["id"] for q in FIXTURE["questions"]])
def test_real_operator_question_routes_as_expected(q):
    got = desk.analyze_operator_intent(q["text"])
    assert got["intent"] == q["intent"], (q["id"], q["text"], got)
    assert sorted(got["needs"]) == sorted(q["needs"]), (q["id"], q["text"], got)
    assert got["symbols"] == q["symbols"], (q["id"], q["text"], got)
    for exp in q.get("subjects", []):
        assert any(_subject_matches(exp, s) for s in got["subjects"]), (q["id"], exp, got["subjects"])
    if "answerable" in q:
        assert desk.is_answerable(got)[0] is q["answerable"], (q["id"], got)


def test_fixture_is_the_real_corpus_and_carries_no_approval_tokens():
    texts = [q["text"] for q in FIXTURE["questions"]]
    assert len(texts) == len(set(texts)) == 36
    assert not any("gapprove" in t.lower() or "grant-" in t.lower() for t in texts)
    for litmus in (
        "Is now a good time to get back into schg",
        "How does the market normally perform in September and normally during a mid-cycle election term what sectors should I be concentrated on going into the third and fourth quarter",
        "what's the outlook for SpaceX, what are options closing, what are analysts expecting",
    ):
        assert litmus in texts


# ── the three litmus questions, spelled out ──────────────────────────────────


def test_litmus_schg_resolves_with_its_registry_guid():
    got = desk.analyze_operator_intent("Is now a good time to get back into schg")
    (schg,) = [s for s in got["subjects"] if s["symbol"]]
    assert schg == {**schg, "symbol": "SCHG", "kind": "ticker", "matched": "schg", "guid": _guid("SCHG"), "source": "book"}
    assert schg["confidence"] >= 0.9


def test_litmus_spacex_resolves_to_spcx_from_house_held_names():
    """Corrected 2026-09-13: SpaceX is not private in Trade-AI's data. The book holds
    SPCX, the registry has it CONFIRMED, and config/ipo_lockups.json names it
    "SpaceX (Space Exploration Technologies Corp)". The Schwab instrument sweep
    lacked it; house-held names now resolve it."""
    got = desk.analyze_operator_intent("what's the outlook for SpaceX, what are options closing, what are analysts expecting")
    companies = [s for s in got["subjects"] if s["kind"] == "company"]
    assert companies and companies[0]["symbol"] == "SPCX" and companies[0]["matched"] == "SpaceX"
    assert got["symbols"] == ["SPCX"]
    assert desk.is_answerable(got) == (True, "")


def test_the_verdict_travels_with_the_intent_so_a_handler_can_refuse_before_gathering():
    """Agent D replay: the SpaceX ask produced no blocking gap, so the handler never
    reached is_answerable and replied 'Queued a pull' with nothing queued."""
    unknown = desk.analyze_operator_intent("what are analysts expecting for Nonesuch Holdings")
    assert unknown["answerable"] is False
    assert "did not resolve to an instrument" in unknown["unanswerable_reason"]
    assert "private" not in unknown["unanswerable_reason"], "never assert WHY a name failed to resolve"
    schg = desk.analyze_operator_intent("Is now a good time to get back into schg")
    assert schg["answerable"] is True and schg["unanswerable_reason"] is None
    seasonal = desk.analyze_operator_intent(FIXTURE["questions"][17]["text"])
    assert seasonal["answerable"] is True, "a thematic question needs no instrument"


def test_litmus_seasonality_question_names_no_issuer():
    got = desk.analyze_operator_intent(FIXTURE["questions"][17]["text"])
    assert got["symbols"] == [] and all(s["symbol"] is None for s in got["subjects"])
    assert got["intent"] == "freeform"


# ── resolver contract ────────────────────────────────────────────────────────


def test_registry_symbols_bind_only_upper_case_book_symbols_any_case():
    """514 registry symbols are English words; lower-case they are the word."""
    assert osr.symbols_of(osr.resolve_subjects("is it a good time to go back into tech, looks cheap", book=ENV["book"])) == []
    assert osr.symbols_of(osr.resolve_subjects("is nvda cheap here", book=ENV["book"])) == []
    assert osr.symbols_of(osr.resolve_subjects("is NVDA cheap here", book=ENV["book"])) == ["NVDA"]
    assert osr.symbols_of(osr.resolve_subjects("is $nvda cheap here", book=ENV["book"])) == ["NVDA"]
    assert osr.symbols_of(osr.resolve_subjects("what's jepi's yield", book=ENV["book"])) == ["JEPI"]


def test_lower_case_registry_ticker_is_a_named_candidate_never_a_symbol():
    """'is nvda cheap here' must not bind (a guess) nor be refused silently."""
    got = desk.analyze_operator_intent("is nvda cheap here")
    assert got["symbols"] == [] and got["ticker_candidates"] == ["NVDA"], got
    assert got["answerable"] is False and "write it in capitals (NVDA)" in got["unanswerable_reason"]
    assert "text_for_candidates" not in got
    # English words that are registry symbols are not offered as candidates.
    assert "ticker_candidates" not in desk.analyze_operator_intent("look at the price today via the chart")


def test_pseudo_and_word_like_book_symbols_do_not_bind_lower_case():
    assert osr.symbols_of(osr.resolve_subjects("get back into cash and div income", book=ENV["book"])) == []
    assert osr.symbols_of(osr.resolve_subjects("what about DIV", book=ENV["book"])) == ["DIV"]


def test_every_symbol_carries_the_registry_guid_or_none_with_lower_confidence():
    subs = osr.resolve_subjects("compare SCHD with ZQXW", book=ENV["book"])
    by = {s["symbol"]: s for s in subs if s["symbol"]}
    assert by["SCHD"]["guid"] == _guid("SCHD") and by["SCHD"]["identity_status"] == "CONFIRMED"
    assert by["ZQXW"]["guid"] is None and by["ZQXW"]["confidence"] < by["SCHD"]["confidence"]


def test_a_generic_word_never_binds_an_issuer():
    """REFR incident: 'Research' resolved to Research Frontiers."""
    subs = osr.resolve_subjects("Research on Walmart please. Research is thin.", book=ENV["book"])
    assert osr.symbols_of(subs) == ["WMT"]
    assert not any(s["symbol"] == "REFR" for s in subs)


def test_company_names_resolve_through_the_instrument_feed_with_guid():
    subs = osr.resolve_subjects("how is my Norfolk Southern position", book=ENV["book"])
    (nsc,) = [s for s in subs if s["symbol"]]
    assert nsc["kind"] == "company" and nsc["symbol"] == "NSC" and nsc["guid"] == _guid("NSC")
    assert nsc["source"] == "company_name_index"


def test_sector_words_map_to_snapshot_sector_names():
    subs = osr.resolve_subjects("rotate out of staples into energy and tech", book=ENV["book"])
    assert {s["sector"] for s in subs if s["kind"] == "sector"} == {"Consumer Defensive", "Energy", "Technology"}
    assert all(s["symbol"] is None and s["guid"] is None for s in subs if s["kind"] == "sector")


def test_nothing_resolved_is_one_general_topic_not_an_empty_list():
    assert osr.resolve_subjects("please continue", book=ENV["book"]) == [
        {"symbol": None, "guid": None, "kind": "topic", "matched": "please continue", "confidence": 0.2,
         "source": "fallback", "topic": "general"}]


def test_every_subject_has_the_contract_keys_and_a_known_kind():
    for q in FIXTURE["questions"]:
        for s in osr.resolve_subjects(q["text"], book=ENV["book"]):
            assert {"symbol", "guid", "kind", "matched", "confidence"} <= set(s)
            assert s["kind"] in osr.KINDS


def test_resolution_never_writes_the_registry(_isolated):
    before = hashlib.sha256(_isolated.read_bytes()).hexdigest()
    for q in FIXTURE["questions"]:
        desk.analyze_operator_intent(q["text"])
    assert hashlib.sha256(_isolated.read_bytes()).hexdigest() == before


# ── phrasings the regexes missed (each with a control) ───────────────────────


@pytest.mark.parametrize(
    "text,intent,needs,symbols",
    [
        ("should I add to SCHD here", "reentry", ["reentry_ready"], ["SCHD"]),
        ("buy more jepi?", "reentry", ["reentry_ready"], ["JEPI"]),
        ("should I trim NOC", "portfolio", ["portfolio", "risk"], ["NOC"]),
        ("time to take some profits on RTX", "portfolio", ["portfolio", "risk"], ["RTX"]),
        ("time to rotate into energy", "freeform", ["portfolio"], []),
        ("should I be overweight tech", "freeform", ["portfolio"], []),
        ("is NVDA cheap here", "analyst_view", ["analyst_view"], ["NVDA"]),
        ("is schg overvalued", "analyst_view", ["analyst_view"], ["SCHG"]),
        ("what's jepi doing", "freeform", ["reentry_levels"], ["JEPI"]),
        ("WMT price today", "freeform", ["reentry_levels"], ["WMT"]),
        ("any rentry candidates", "reentry", ["reentry_ready"], []),
        ("what are anaylst saying about V", "analyst_view", ["analyst_view"], ["V"]),
        ("analist targets for NOC", "analyst_view", ["analyst_view"], ["NOC"]),
        ("where is suport on SCHD", "freeform", ["reentry_levels"], ["SCHD"]),
    ],
)
def test_new_phrasings(text, intent, needs, symbols):
    got = desk.analyze_operator_intent(text)
    assert (got["intent"], sorted(got["needs"]), got["symbols"]) == (intent, sorted(needs), symbols), got


def test_rotation_and_overweight_carry_the_sector_subject():
    got = desk.analyze_operator_intent("should I be overweight tech")
    assert any(s["kind"] == "sector" and s["sector"] == "Technology" for s in got["subjects"])


@pytest.mark.parametrize(
    "text",
    ["add NOC to my watchlist", "should I add to my watch list", "what's going on", "how is the market doing"],
)
def test_controls_do_not_claim_reentry(text):
    assert "reentry_ready" not in desk.analyze_operator_intent(text)["needs"]


def test_what_is_x_doing_needs_a_resolved_symbol():
    got = desk.analyze_operator_intent("whats crowdstrite doing")
    assert got["symbols"] == [] and "reentry_levels" not in got["needs"]


# ── P0 precedence stays intact ───────────────────────────────────────────────


def test_meta_system_still_wins_over_desk_words():
    got = desk.analyze_operator_intent("alex what llm are you using for schg support levels")
    assert got["intent"] == "meta_system" and "reentry_levels" not in got["needs"]
    assert desk.analyze_operator_intent("are you read only")["intent"] == "meta_system"
    assert desk.analyze_operator_intent("what authority do you have?")["intent"] == "meta_system"


def test_model_portfolio_is_not_a_question_about_the_model():
    got = desk.analyze_operator_intent("what does the model portfolio say about SCHD")
    assert got["intent"] != "meta_system" and "portfolio" in got["needs"]


def test_attention_still_wins_and_carries_subjects():
    got = desk.analyze_operator_intent("why haven't you told me anything today about schg")
    assert got["intent"] == "attention" and got["symbols"] == ["SCHG"]
    assert got["subjects"][0]["guid"] == _guid("SCHG")


# ── Flash may add, never remove, never invent ────────────────────────────────


def _flash(monkeypatch, payload: dict):
    import scripts.lib.cio_plan_enrichment as pe
    calls = []

    def fake(messages, policy, use_pro=False, task_type=None):  # 2026-09-14: callers name their task type
        calls.append(messages)
        return {"ok": True, "content": json.dumps(payload), "model": "test-flash"}

    monkeypatch.setattr(pe, "call_governed_llm", fake)
    monkeypatch.setattr(pe, "load_llm_policy", lambda: {})
    monkeypatch.setenv("CIO_OPERATOR_INTENT_FLASH", "1")
    return calls


def test_flash_cannot_remove_a_resolved_symbol(monkeypatch):
    calls = _flash(monkeypatch, {"intent": "reentry", "symbols": [], "needs": ["reentry_ready"]})
    got = desk.analyze_operator_intent("Is now a good time to get back into schg")
    assert calls, "the patched Flash call must have run"
    assert got["source"] == "deepseek_flash" and got["symbols"] == ["SCHG"]
    assert got["subjects"][0]["guid"] == _guid("SCHG")


def test_flash_may_add_only_a_verified_symbol(monkeypatch):
    _flash(monkeypatch, {"intent": "analyst_view", "symbols": ["SPACEX", "NVDA", "SCHG", "ZQXW"], "needs": ["analyst_view"]})
    got = desk.analyze_operator_intent("what are analysts expecting for SpaceX and schg")
    assert set(got["symbols"]) == {"SCHG", "SPCX", "NVDA"}, "SpaceX resolves by house name; Flash's SPACEX token does not"
    assert got["flash_unverified_symbols"] == ["SPACEX", "ZQXW"]
    added = [s for s in got["subjects"] if s.get("source") == "flash"]
    assert added and added[0]["symbol"] == "NVDA" and added[0]["guid"] == _guid("NVDA")
    assert got["intent"] == "analyst_view"


def test_flash_invented_ticker_is_not_trusted_but_the_house_name_still_resolves(monkeypatch):
    _flash(monkeypatch, {"intent": "research", "symbols": ["SPACEX"], "needs": ["analyst_view"]})
    got = desk.analyze_operator_intent("what's the outlook for SpaceX, what are options closing, what are analysts expecting")
    assert got["symbols"] == ["SPCX"] and "SPACEX" in got.get("flash_unverified_symbols", [])
    assert desk.is_answerable(got)[0] is True


def test_extract_symbols_wrapper_used_by_converse_core_agrees_with_the_analyzer():
    for q in FIXTURE["questions"]:
        assert desk._extract_symbols(q["text"]) == desk.analyze_operator_intent(q["text"])["symbols"], q["id"]
