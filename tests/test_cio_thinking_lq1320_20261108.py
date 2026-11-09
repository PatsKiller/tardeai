"""LQ-20261107-1320 — the CIO's reasoning pass: a complete packet in, a validated plan out.

The operator's case: ANET, a founder's Form 144 plan sale of 260,000 shares (~$44.4M), a stop at
$164.27 that already locks most of Friday's gain, and the instruction to reason about both
directions and to keep the name on a re-entry watch if it stops out. The failure this replaces is
the old 12,000-character truncation: the model saw a packet cut mid-way and could not name a
cause its research answer stated.

Every fixture here is synthetic (ZZ-prefixed symbols, invented but internally consistent
numbers); the spine is a tmp path, never the live one; no database, no network, no model call.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import cio_thinking as T  # noqa: E402

AS_OF = "2026-11-08T15:35:00-05:00"
TEST_GUID = "11111111-2222-4333-8444-555555555555"
STOP_SOURCE = "stop_last_known:ZZANET:acct_a"


def item(symbol="ZZANET", **over):
    base = {
        "symbol": symbol,
        "price": 170.8,
        "move_pct": 7.31,
        "shares": 900,
        "market_value": 153720.0,
        "accounts": ["acct_a"],
        "quote_source": "finviz_elite",
        "quote_time": "2026-11-08T15:30:00-05:00",
        "holdings_as_of": "2026-11-08T14:00:00-05:00",
        "stops": {
            "working": [{"account": "acct_a", "stop_price": 164.27, "qty": 900,
                         "captured_at": "2026-11-08T14:05:00-05:00", "status": "working"}],
            "coverage": 1.0, "cushion": 3.9,
        },
        "news": [{"id": 41, "title": "ZZANET: A. Founder plans to sell 260,000 ZZ shares, about $44.4M",
                  "source": "Quantisnow", "published_at": "2026-11-06T21:00:00-05:00"}],
        "filings": [{"id": 77, "form": "Form 144", "filer": "A. Founder", "shares": 260000,
                     "value": 44400000, "filed": "2026-11-06"}],
        "events": [{"event_id": "evt:abc", "kind": "insider_plan_sale", "who": "A. Founder",
                    "what": "A. Founder plans to sell 260,000 shares",
                    "why": "Form 144 notice of intent to sell",
                    "size": {"shares": 260000.0, "value_usd": 44400000.0},
                    "is_10b5_1": None,
                    "source_ids": ["news:41", "sec:77"]}],
        "research": {"status": "answered", "lane": "grok",
                     "text": "A. Founder filed a Form 144 for 260,000 shares, about $44.4M, "
                             "under a pre-arranged 10b5-1 plan.",
                     "sources": ["Wire 2026-11-06: headline"]},
        "memory": {"events": []},
        "bars": [{"date": f"2026-11-{d:02d}", "close": 100.0 + d} for d in range(3, 8)],
    }
    base.update(over)
    return base


def plan(level=164.27, source=STOP_SOURCE, condition="keep the working stop"):
    return {"level": level, "source_id": source, "condition": condition}


# ── (a) completeness: every held name, nothing cut ─────────────────────────────────────────


def test_packet_carries_every_held_name_with_events_research_stops_and_quotes():
    symbols = ["ZZANET", "ZZRKT", "ZZQUIET"]
    packet = T.build_packet([item(s) for s in symbols], as_of=AS_OF)
    assert {b["symbol"] for b in packet["names"]} == set(symbols)
    for block in packet["names"]:
        assert block["held"] is True
        assert block["price"]["value"] == 170.8
        assert block["stops"][0]["price"]["value"] == 164.27
        assert block["research"]["text"]
        assert block["news"] and block["news"][0]["source_id"].startswith("news:")
    assert packet["stats"]["names"] == 3


def test_packet_is_not_truncated_at_the_old_12000_character_cut():
    items = [item(f"ZZ{i:02d}") for i in range(8)]
    for i, it in enumerate(items):
        it["research"]["text"] = (f"Research sentence {i} about the sale. " * 200)
    packet = T.build_packet(items, as_of=AS_OF)
    assert packet["stats"]["chars"] > 12_000          # the old cut would have hidden half of it
    body = T.build_request(packet)["messages"][0]["content"][0]["text"]
    for it in items:
        assert it["research"]["text"] in body          # every held name, in full
    assert packet["dropped"] == []


def test_every_packet_value_carries_a_source_id_and_an_as_of():
    packet = T.build_packet([item("ZZANET")], as_of=AS_OF, regime={"record_id": "reg:1", "as_of": AS_OF,
                                                                   "regime": "risk_on"})
    assert packet["facts"]
    for f in packet["facts"]:
        assert f.get("source_id") and f.get("as_of"), f
        assert f.get("value") is not None or f.get("text")
    assert all(b["numbers"] for b in packet["names"])


def test_over_budget_drops_optional_depth_and_never_a_held_name_s_facts():
    items = [item("ZZAAA"), item("ZZBBB")]
    for it in items:
        it["bars"] = [{"date": f"2026-11-0{d}", "close": 100.0 + d} for d in range(1, 8)]
        it["news"] = [{"id": 100 * len(it["symbol"]) + i, "title": "headline " * 12,
                       "source": "Wire", "published_at": "2026-11-08T10:00:00-05:00"}
                      for i in range(6)]
    packet = T.build_packet(items, as_of=AS_OF, max_chars=14_000)
    assert {b["symbol"] for b in packet["names"]} == {"ZZAAA", "ZZBBB"}
    assert packet["dropped"] and any(d["section"] in {"bars", "news", "filings"} for d in packet["dropped"])
    for block in packet["names"]:
        assert block["events"] and block["research"]["text"] and block["stops"]
    assert packet["stats"]["chars"] <= 14_000


def test_a_non_held_name_is_dropped_before_a_held_name_loses_anything():
    held_only = T.build_packet([item("ZZHELD")], as_of=AS_OF)
    budget = held_only["stats"]["chars"] + 150
    optional = item("ZZWATCH", research={"status": "answered", "lane": "grok",
                                         "text": "watched name context. " * 400})
    packet = T.build_packet([item("ZZHELD")], as_of=AS_OF, optional_items=[optional], max_chars=budget)
    assert [b["symbol"] for b in packet["names"]] == ["ZZHELD"]
    assert any(d["section"] == "name" and d["symbol"] == "ZZWATCH" for d in packet["dropped"])
    assert packet["names"][0]["events"] and packet["names"][0]["research"]["text"]


# ── (c) the validator: no invented number, no stale input, no unknown source ────────────────


def _packet():
    return T.build_packet([item("ZZANET")], as_of=AS_OF)


def test_validator_rejects_an_invented_number():
    thinking = {"names": {"ZZANET": {
        "what_happened": "A. Founder plans to sell 260,000 shares, about $44.4M.",
        "why_it_matters": "The sale is 12.5% of the float and about $5,000,000,000 in notional.",
        "protect": plan(),
    }}}
    out = T.validate(thinking, _packet())
    assert out["ok"] is False
    codes = {p["code"] for p in out["problems"]}
    assert "invented_number" in codes
    assert {p["number"] for p in out["problems"] if p["code"] == "invented_number"} == {"12.5", "5000000000"}


def test_validator_accepts_the_source_s_own_shorthand_and_labels():
    thinking = {"names": {"ZZANET": {
        "what_happened": "A. Founder filed Form 144 on 2026-11-06 for 260,000 shares, about $44.4M, "
                         "under a 10b5-1 plan.",
        "protect": plan(),
    }}}
    out = T.validate(thinking, _packet())
    assert out["ok"] is True, out["problems"]


def test_validator_rejects_a_level_cited_to_the_wrong_source():
    out = T.validate({"names": {"ZZANET": {"protect": plan(source="stop_last_known:ZZANET:other")}}}, _packet())
    assert out["ok"] is False
    assert "unknown_source" in {p["code"] for p in out["problems"]}


def test_validator_rejects_a_stale_input_past_its_freshness_limit():
    stale_item = item("ZZANET", quote_time="2026-11-01T15:30:00-05:00")
    packet = T.build_packet([stale_item], as_of=AS_OF)
    out = T.validate({"names": {"ZZANET": {"what_happened": "A sale.", "protect": plan()}}}, packet)
    assert out["ok"] is False
    stale = [p for p in out["problems"] if p["code"] == "stale_input"]
    assert stale and "stale:quote" in stale[0]["detail"]


def test_validator_rejects_a_name_that_is_not_in_the_packet():
    out = T.validate({"names": {"ZZGHOST": {"what_happened": "A sale."}}}, _packet())
    assert [p["code"] for p in out["problems"]] == ["unknown_name"]


def test_the_deterministic_fallback_passes_the_same_validator():
    block = _packet()["names"][0]
    fallback = T.deterministic_thinking(block)
    packet = _packet()
    out = T.validate({"names": {"ZZANET": fallback}}, packet)
    assert out["ok"] is True, out["problems"]
    assert fallback["model"] == "fallback"
    known = set(packet["numbers"]) | T._date_numbers(packet)
    assert set(T.numbers_in(fallback["text"])) <= known


def test_validated_thinking_contains_no_number_that_is_not_a_packet_fact():
    packet = _packet()
    thinking = {"names": {"ZZANET": {
        "what_happened": "A. Founder plans to sell 260,000 shares, about $44.4M, on a Form 144.",
        "both_ways": "The stop sits at $164.27 while the last print is $170.80.",
        "protect": plan(),
        "reentry": plan(level=170.8, source="quote:ZZANET:finviz_elite", condition="reclaim after the sale prints"),
    }}}
    assert T.validate(thinking, packet)["ok"] is True
    known = set(packet["numbers"]) | T._date_numbers(packet)
    text = json.dumps(thinking)
    printed = {k for k in T.numbers_in(text, allowed_forms=T._form_vocabulary(packet))}
    assert printed <= known, printed - known


# ── (b) delta replay: T0's plan, carried in CIO memory, against T1's packet ─────────────────


def test_t0_plan_is_read_back_from_memory_and_replayed_against_t1(tmp_path):
    spine = tmp_path / "spine.jsonl"
    t0 = T.build_packet([item("ZZANET")], as_of="2026-11-08T15:35:00-05:00")
    t0_thinking = {"names": {"ZZANET": {
        "what_happened": "A. Founder plans to sell 260,000 shares, about $44.4M.",
        "protect": plan(),
        "reentry": plan(level=175.0, source="quote:ZZANET:finviz_elite",
                        condition="reclaim after the sale window prints"),
    }}}
    stored = T.remember("ZZANET", t0_thinking, path=spine, subject_guid=TEST_GUID)
    assert stored["stored"] is True
    recalled = T.recall("ZZANET", path=spine)
    assert recalled and recalled[0]["names"]["ZZANET"]["protect"]["level"] == 164.27

    # T1: the price has fallen through the stop.
    t1 = T.build_packet([item("ZZANET", price=163.0, move_pct=-4.5)],
                        as_of="2026-11-09T15:35:00-05:00",
                        prior_packet=t0, prior_thinking=recalled[0])
    plans = t1["delta"]["plans"]["ZZANET"]
    assert plans["prior_protect"]["value"] == 164.27
    assert plans["prior_protect"]["source_id"] == STOP_SOURCE
    assert plans["state"] == "protect_reached"
    assert plans["evidence"]["level"]["value"] == 164.27
    assert plans["say"].startswith("The price reached T0's protect level")
    changes = {(c["field"], c.get("from"), c.get("value")) for c in t1["delta"]["changes"]}
    assert ("price", 170.8, 163.0) in changes
    assert ("move_pct", 7.31, -4.5) in changes


def test_a_reentry_level_reached_is_reported_not_silently_replanned(tmp_path):
    spine = tmp_path / "spine.jsonl"
    t0 = T.build_packet([item("ZZANET")], as_of="2026-11-08T15:35:00-05:00")
    T.remember("ZZANET", {"names": {"ZZANET": {
        "protect": plan(),
        "reentry": plan(level=175.0, source=STOP_SOURCE, condition="reclaim after CPI"),
    }}}, path=spine, subject_guid=TEST_GUID)
    t1 = T.build_packet([item("ZZANET", price=176.0)], as_of="2026-11-09T15:35:00-05:00",
                        prior_packet=t0, prior_thinking=T.recall("ZZANET", path=spine)[0])
    assert t1["delta"]["plans"]["ZZANET"]["state"] == "reentry_reached"


# ── memory round trip ─────────────────────────────────────────────────────────────────────


def test_thinking_is_persisted_per_symbol_and_read_back(tmp_path):
    spine = tmp_path / "spine.jsonl"
    rec = {"names": {"ZZANET": {"protect": plan()}}}
    out = T.remember("ZZANET", rec, path=spine, subject_guid=TEST_GUID)
    assert out["stored"] is True and out["record_id"].startswith("think:")
    got = T.recall("ZZANET", path=spine)
    assert len(got) == 1
    assert got[0]["symbol"] == "ZZANET"
    assert got[0]["record_id"] == out["record_id"]


def test_memory_never_raises_when_the_spine_is_unwritable(tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    out = T.remember("ZZANET", {"names": {}}, path=blocker / "spine.jsonl", subject_guid=TEST_GUID)
    assert out["stored"] is False and out.get("reason")


# ── the two records read each other (amendment 20:47) ─────────────────────────────────────


def test_outlook_and_cio_verdict_carry_their_record_ids_and_disagreement_is_surfaced():
    outlook = {"record_id": "out:2026-11-08", "as_of": AS_OF, "regime": "risk_on",
               "score": 0.42, "confidence": "medium",
               "caveat": "MRE: a single-model estimate, not a forecast"}
    verdict = {"record_id": "cio:2026-11-08", "as_of": AS_OF, "regime": "risk_off",
               "verdict": "trim"}
    packet = T.build_packet([item("ZZANET")], as_of=AS_OF, outlook=outlook, cio_verdict=verdict)
    assert packet["record"]["outlook"]["record_id"] == "out:2026-11-08"
    assert packet["record"]["outlook"]["caveat"].startswith("MRE")
    assert packet["record"]["cio_verdict"]["record_id"] == "cio:2026-11-08"
    found = packet["record"]["disagreement"]
    assert found and found[0]["field"] == "regime"
    assert {found[0]["left"]["record_id"], found[0]["right"]["record_id"]} == {
        "out:2026-11-08", "cio:2026-11-08"}
    assert any("disagree" not in json.dumps(found) for f in found)  # the values are kept, not summed away


def test_agreeing_records_produce_no_disagreement():
    same = {"record_id": "out:1", "as_of": AS_OF, "regime": "neutral"}
    packet = T.build_packet([item("ZZANET")], as_of=AS_OF, outlook=same,
                            cio_verdict=dict(same, record_id="cio:1"))
    assert packet["record"]["disagreement"] == []


# ── the dry run: the exact request, and no call ─────────────────────────────────────────────


def test_dry_run_prints_the_packet_and_the_request_and_sends_nothing(tmp_path, capsys):
    doc = {
        "as_of": AS_OF,
        "run_id": "run:test",
        "source_timestamps": {"quotes": "2026-11-08T15:30:00-05:00",
                              "positions": "2026-11-08T14:00:00-05:00"},
        "holdings": [item("ZZANET")],
        "synopsis": "test book",
        "gaps": [],
    }
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(doc))
    rc = T.main(["--doc", str(path), "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["would_send"] is False
    assert out["names"][0]["symbol"] == "ZZANET" and out["names"][0]["events"] == 1
    assert out["request"]["model"] == "claude-opus-5-5"
    assert out["request"]["effort"] == "medium"
    assert out["request"]["sha256"] and out["request"]["chars"] > out["packet"]["chars"]
    assert out["packet"]["chars"] > 0
