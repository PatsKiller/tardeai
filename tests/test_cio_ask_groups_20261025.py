"""My questions grouping (Screen 5): group_by security|sector|theme|date|none, overrides, related-from-memory, API.

COVERS = ["scripts/lib/cio_ask_groups.py", "scripts/lib/cio_ask_api.py", "scripts/lib/cio_ask_store.py"]

Synthetic ledger only (tmp_path); no host store, no live server, no model call.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import cio_ask_api as api  # noqa: E402
from scripts.lib import cio_ask_groups as G  # noqa: E402
from scripts.lib.cio_ask_store import AskEventStore  # noqa: E402

TSLA = "11111111-1111-4111-8111-111111111111"
AXTI = "22222222-2222-4222-8222-222222222222"
RTX = "33333333-3333-4333-8333-333333333333"
FACTS = {
    TSLA: {"company": {"value": "Tesla, Inc."}, "sector": {"value": "Consumer Discretionary"}, "industry": {"value": "Autos"}},
    AXTI: {"company": {"value": "AXT Inc"}, "sector": {"value": "Information Technology"}, "industry": {"value": "Semiconductors"}},
    RTX: {"company": {"value": None}, "sector": {"value": None}},
}
THEMES = {"available": True, "reason": None, "source": "config/thesis.json",
          "by_symbol": {"RTX": [{"key": "ai_wwiii_defense", "label": "AI World War III defense thesis"}]}}


def _ent(sym, guid):
    return {"name": sym, "kind": "security", "symbol": sym, "security_guid": guid, "resolution": "CONFIRMED"}


def ledger(tmp_path):
    st = AskEventStore(tmp_path / "cio_ask_events.jsonl")
    rows = [  # thread, ask, question, channel, asked_at (UTC), entities, recall refs
        ("thr_aaaaaaaaaaaaaaaa", "ask_aaaaaaaaaaaaaaa1", "100 or 1,000 TSLA?", "cc", "2026-10-20T14:00:00+00:00", [_ent("TSLA", TSLA)], []),
        ("thr_aaaaaaaaaaaaaaaa", "ask_aaaaaaaaaaaaaaa2", "and the follow-up on TSLA", "telegram", "2026-10-21T02:30:00+00:00", [_ent("TSLA", TSLA)],
         [{"key": TSLA, "items": [{"ref": "ask_aaaaaaaaaaaaaaa1:v1", "at": "2026-10-20T14:01:00+00:00", "source": "cio_ask_events"},
                                  {"ref": "ask_ffffffffffffffff", "at": "2026-09-01T00:00:00+00:00", "source": "security_research_spine"}]}]),
        ("thr_bbbbbbbbbbbbbbbb", "ask_bbbbbbbbbbbbbbb1", "AXTI after the print?", "cc", "2026-10-22T15:00:00+00:00", [_ent("AXTI", AXTI)], []),
        ("thr_cccccccccccccccc", "ask_ccccccccccccccc1", "RTX into the budget?", "telegram", "2026-10-23T13:00:00+00:00", [_ent("RTX", RTX)], []),
        ("thr_dddddddddddddddd", "ask_ddddddddddddddd1", "what is the market doing", "cc", "2026-10-23T18:00:00+00:00", [], []),
    ]
    for tid, aid, q, ch, at, ents, recall in rows:
        st.append("ask.asked", {"thread_id": tid, "ask_id": aid, "question": q, "channel": ch, "asked_at": at,
                                "turn_kind": "ask" if aid.endswith("1") else "follow_up"}, event_id=f"a:{aid}")
        for e in ents:
            st.append("ask.entity_resolved", {"thread_id": tid, "ask_id": aid, "entity": e}, event_id=f"e:{aid}:{e['symbol']}")
        st.append("ask.answer_version", {"thread_id": tid, "ask_id": aid, "answer": {
            "version": 1, "status": "quick", "depth": "quick", "summary": f"answer to {q}", "produced_at": at.replace(":00+", ":30+"),
            "recall": recall}}, event_id=f"v:{aid}")
    return st


def grouped(st, gb, **kw):
    return G.group_questions(st.threads(), group_by=gb, events=st.events(),
                             facts_for=lambda e: FACTS.get(e.get("security_guid"), {}),
                             stance_for=lambda syms: {"TSLA": {"stance": "HOLD", "conviction": 61, "as_of": "2026-10-22T20:00:00+00:00",
                                                               "source": "cio_prospect"}},
                             themes=THEMES, **kw)


def test_security_groups_use_guid_and_c1_facts_with_counts_and_memory(tmp_path):
    out = grouped(ledger(tmp_path), "security")
    by = {g["label"]: g for g in out["groups"]}
    tsla = by["TSLA"]
    assert tsla["key"] == f"security:{TSLA}" and tsla["sub"] == "Tesla, Inc. · Consumer Discretionary · Autos"
    assert tsla["counts"] == {"questions": 2, "threads": 1, "names": 1}
    assert tsla["memory"]["stance"] == "HOLD" and tsla["memory"]["conviction"] == 61
    assert tsla["memory"]["last_answer_at"] == "2026-10-21T02:30:30+00:00"
    assert by["RTX"]["sub"] is None  # no C1 facts on file: shown as missing, never guessed
    assert by["AXTI"]["memory"]["stance"] is None and by["AXTI"]["memory"]["stance_missing_reason"]
    assert out["groups"][-1]["label"] == G.NO_SECURITY  # catch-all last
    assert out["counts"] == {"groups": 4, "questions": 5, "threads": 4}


def test_sector_unknown_is_unclassified_never_inferred(tmp_path):
    out = grouped(ledger(tmp_path), "sector")
    labels = [g["label"] for g in out["groups"]]
    assert "Information Technology" in labels and "Consumer Discretionary" in labels
    unc = next(g for g in out["groups"] if g["label"] == G.UNCLASSIFIED)
    assert [q["ask_id"] for q in unc["questions"]] == ["ask_ccccccccccccccc1"]
    assert all(g["memory"]["stance"] is None for g in out["groups"])


def test_theme_from_thesis_catalog_and_unavailable_catalog_is_reported(tmp_path):
    out = grouped(ledger(tmp_path), "theme")
    th = next(g for g in out["groups"] if g["key"] == "theme:ai_wwiii_defense")
    assert th["label"] == "AI World War III defense thesis" and th["counts"]["questions"] == 1
    assert next(g for g in out["groups"] if g["key"] == "theme:none")["counts"]["questions"] == 3
    real = G.load_themes()
    assert real["available"] is True and "RTX" in real["by_symbol"]  # config/thesis.json is a real catalog
    bad = tmp_path / "thesis.json"; bad.write_text(json.dumps({"targets": {"x": 1}}))
    none = G.load_themes(bad)
    assert none["available"] is False and "no thesis" in none["reason"]
    out2 = G.group_questions({}, group_by="security", themes=none)
    assert out2["groups"] == []  # empty ledger: empty state, never sample groups
    theme = next(x for x in out2["group_bys"] if x["id"] == "theme")
    assert theme["available"] is False and theme["reason"] == none["reason"]


def test_date_groups_by_et_day_newest_first(tmp_path):
    out = grouped(ledger(tmp_path), "date")
    keys = [g["key"] for g in out["groups"]]
    assert keys == sorted(keys, reverse=True)
    # 2026-10-21T02:30Z is the evening of 2026-10-20 in New York
    oct20 = next(g for g in out["groups"] if g["key"] == "2026-10-20")
    assert {q["ask_id"] for q in oct20["questions"]} == {"ask_aaaaaaaaaaaaaaa1", "ask_aaaaaaaaaaaaaaa2"}


def test_none_search_and_channel_filters(tmp_path):
    st = ledger(tmp_path)
    assert grouped(st, "none")["groups"][0]["counts"]["questions"] == 5
    assert grouped(st, "security", q="axti")["counts"]["questions"] == 1
    tg = grouped(st, "security", channel="telegram")
    assert {q["channel"] for g in tg["groups"] for q in g["questions"]} == {"telegram"}
    assert grouped(st, "security", q="no such thing")["groups"] == []
    with pytest.raises(ValueError):
        grouped(st, "bogus")


def test_override_is_an_appended_event_newest_wins_and_ungroup(tmp_path):
    st = ledger(tmp_path)
    st.append("ask.group_override", {"thread_id": "thr_bbbbbbbbbbbbbbbb", "ask_id": "ask_bbbbbbbbbbbbbbb1",
                                     "group_by": "security", "group_key": f"security:{TSLA}"}, event_id="o1")
    out = grouped(st, "security")
    tsla = next(g for g in out["groups"] if g["key"] == f"security:{TSLA}")
    assert "ask_bbbbbbbbbbbbbbb1" in [q["ask_id"] for q in tsla["questions"]]
    assert not any(g["label"] == "AXTI" for g in out["groups"])
    st.append("ask.group_override", {"thread_id": "thr_bbbbbbbbbbbbbbbb", "ask_id": "ask_bbbbbbbbbbbbbbb1",
                                     "group_by": "security", "group_key": None}, event_id="o2")
    out = grouped(st, "security")
    assert next(g for g in out["groups"] if g["key"] == "ungrouped")["questions"][0]["ask_id"] == "ask_bbbbbbbbbbbbbbb1"
    assert grouped(st, "sector")["groups"]  # an override applies only to its own grouping
    raw = [json.loads(x) for x in (tmp_path / "cio_ask_events.jsonl").read_text().splitlines()]
    assert sum(1 for e in raw if e["kind"] == "ask.asked") == 5  # history untouched


def test_related_from_memory_resolves_only_persisted_recall_refs(tmp_path):
    st = ledger(tmp_path)
    th = st.threads()
    rel = G.related_from_memory(th["thr_aaaaaaaaaaaaaaaa"], th)
    rows = rel["ask_aaaaaaaaaaaaaaa2"]
    assert rows[0]["ask_id"] == "ask_aaaaaaaaaaaaaaa1" and rows[0]["question"] == "100 or 1,000 TSLA?"
    assert rows[1]["missing_reason"] == "recalled ask is not on the ask ledger"
    assert rel["ask_aaaaaaaaaaaaaaa1"] == []  # recalled nothing → related nothing (no similarity guess)


class _Deps:
    def __init__(self, store):
        self.store = store
        self.facts_for = lambda e: FACTS.get(e.get("security_guid"), {})
        self.stance_for = lambda syms: {}


def _ctx(deps, csrf=(True, "")):
    return api.Ctx(principal=lambda: "tailnet:john@jwwhiting.com", listener=lambda: "serve_proxy",
                   csrf=lambda m, p: csrf, allowed_logins=frozenset({"john@jwwhiting.com"}), deps=deps)


def test_api_grouped_list_thread_related_and_regroup(tmp_path, monkeypatch):
    from scripts.lib import cio_ask_core as core
    st = ledger(tmp_path)
    deps = _Deps(st)
    monkeypatch.setattr(core, "_deps", lambda d: d)
    s, body = api.handle("/api/v2/cio/asks", "GET", query={"group_by": "sector"}, ctx=_ctx(deps))
    assert s == 200 and body["data"]["grouped"]["group_by"] == "sector" and body["data"]["threads"]
    s, body = api.handle("/api/v2/cio/asks", "GET", query={"group_by": "planet"}, ctx=_ctx(deps))
    assert s == 400 and body["error"] == "BAD_GROUPING"
    s, body = api.handle("/api/v2/cio/asks", "GET", ctx=_ctx(deps))
    assert s == 200 and "grouped" not in body["data"]  # old callers unchanged
    s, body = api.handle("/api/v2/cio/asks/thr_aaaaaaaaaaaaaaaa", "GET", ctx=_ctx(deps))
    assert body["data"]["related_from_memory"]["ask_aaaaaaaaaaaaaaa2"][0]["ask_id"] == "ask_aaaaaaaaaaaaaaa1"
    url = "/api/v2/cio/asks/thr_bbbbbbbbbbbbbbbb/regroup"
    s, body = api.handle(url, "POST", {"ask_id": "ask_bbbbbbbbbbbbbbb1", "group_by": "security", "group_key": None},
                         ctx=_ctx(deps, csrf=(False, "cross-site")))
    assert s == 403
    s, body = api.handle(url, "POST", {"ask_id": "ask_aaaaaaaaaaaaaaa1", "group_by": "security", "group_key": None}, ctx=_ctx(deps))
    assert s == 400 and body["error"] == "ASK_NOT_IN_THREAD"
    s, body = api.handle(url, "POST", {"ask_id": "ask_bbbbbbbbbbbbbbb1", "group_by": "none", "group_key": None}, ctx=_ctx(deps))
    assert s == 400
    s, body = api.handle(url, "POST", {"ask_id": "ask_bbbbbbbbbbbbbbb1", "group_by": "security", "group_key": None}, ctx=_ctx(deps))
    assert s == 200 and body["data"]["override"]["kind"] == "ask.group_override"
    s, body = api.handle("/api/v2/cio/asks", "GET", query={"group_by": "security"}, ctx=_ctx(deps))
    assert any(g["key"] == "ungrouped" for g in body["data"]["grouped"]["groups"])


# ── committed browser fixture (builder output on the synthetic ledger above) ───────────────────────────────────────

FIXTURE = ROOT / "apps/command-center-v3/e2e/fixtures/myQuestionsGroups.fixture.json"


def compose_fixture(tmp_path) -> dict:
    from scripts.lib import cio_ask_core as core
    from scripts.lib import cio_ask_store as store_mod
    import itertools
    tick = itertools.count()
    saved_now = store_mod.utc_now_iso
    store_mod.utc_now_iso = lambda: f"2026-10-24T11:{next(tick) % 60:02d}:00+00:00"  # deterministic ledger clock
    try:
        st = ledger(tmp_path)
    finally:
        store_mod.utc_now_iso = saved_now
    deps = _Deps(st)
    deps.stance_for = lambda syms: {s: {"missing_reason": "CIO prospect store not live (shadow)"} for s in syms}
    saved = core._deps
    core._deps = lambda d: d
    try:
        ctx = _ctx(deps)
        grouped = {}
        for gb in G.GROUP_BYS:
            grouped[gb] = api.handle("/api/v2/cio/asks", "GET", query={"group_by": gb}, ctx=ctx)[1]
        grouped["telegram"] = api.handle("/api/v2/cio/asks", "GET", query={"group_by": "security", "channel": "telegram"}, ctx=ctx)[1]
        threads = {tid: api.handle(f"/api/v2/cio/asks/{tid}", "GET", ctx=ctx)[1] for tid in st.threads()}
        empty = AskEventStore(tmp_path / "empty.jsonl")
        edeps = _Deps(empty)
        empty_body = api.handle("/api/v2/cio/asks", "GET", query={"group_by": "security"}, ctx=_ctx(edeps))[1]
    finally:
        core._deps = saved

    def scrub(o):  # the response clock is the only non-deterministic field
        if isinstance(o, dict):
            return {k: ("2026-10-24T12:00:00+00:00" if k == "as_of" else scrub(v)) for k, v in o.items()}
        if isinstance(o, list):
            return [scrub(v) for v in o]
        return o
    return scrub({"_comment": "SYNTHETIC ask ledger run through cio_ask_api + cio_ask_groups; regenerate with "
                              "MY_QUESTIONS_WRITE_FIXTURE=1 pytest tests/test_cio_ask_groups_20261025.py. Not production data.",
                  "clock": "2026-10-24T12:00:00+00:00", "grouped": grouped, "threads": threads, "empty": empty_body})


def test_my_questions_browser_fixture_is_current_builder_output(tmp_path):
    import os
    doc = compose_fixture(tmp_path)
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    if os.environ.get("MY_QUESTIONS_WRITE_FIXTURE") == "1":
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.read_text(encoding="utf-8") == text, "regenerate with MY_QUESTIONS_WRITE_FIXTURE=1"
    assert doc["empty"]["data"]["grouped"]["groups"] == []
