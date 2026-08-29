"""S0 operator loop — mint, attach, turn ids, rehydrate, thesis honesty.

The symptom was "the desk only knows SCHD". The cause: free-text operator
questions minted an `S0_OPERATOR_CONVERSE` plan with **empty `symbols`** — the
live book still shows one for "alex what can i reenter n…" with `symbols: []`.
No symbol means no `registry[symbol]` load, no thesis, no prior artifact. SCHD
looked special only because it already carried an operator defer.

`extract_symbols` was already written, in `cio_telegram_converse`, and was never
wired into the channel-agnostic mint path.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_notification_policy as policy
from scripts.lib.cio_s0_operator_loop import (
    ACK, DEFER, DESK_PIN_ONLY, QUESTION, REFUSE_CASH, REFUSE_DUST,
    REFUSE_NONE, REFUSE_TEST, REJECT, RESEARCH_REQUIRED, SITUATION_TYPE,
    classify_intent, extract_operator_symbols, gate_input_from, last_turn_for,
    mint_eligibility, newest_open_plan_for, operator_last_line, persist_turn,
    rehydrate, route_turn, thesis_coverage, turn_id_for,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
SCHD_S6 = {"plan_id": "plan_schd_s6",
           "situation_type": "S6_CONCENTRATION_OR_DISPOSITION",
           "symbols": ["SCHD"], "status": "proposed", "created_ts": "2026-08-01"}


# ------------------------------------------------------- the named tests

def test_what_about_rtx_mints_one_s0_with_the_symbol():
    """The headline case. Previously minted a plan with symbols: []."""
    r = route_turn("what about RTX", plans=[SCHD_S6], now=NOW)
    assert r["action"] == "mint"
    assert r["symbol"] == "RTX"
    assert r["mint_situation_type"] == SITUATION_TYPE
    assert r["intent"] == QUESTION
    assert r["turn_id"].startswith("turn_")


def test_a_second_turn_on_the_same_symbol_reuses_the_plan(tmp_path):
    """Same plan_id, new operator_turn_id."""
    first = route_turn("what about SCHD", plans=[SCHD_S6], now=NOW)
    second = route_turn("SCHD still worth holding?", plans=[SCHD_S6], now=NOW)
    assert first["plan_id"] == second["plan_id"] == "plan_schd_s6"
    assert first["turn_id"] != second["turn_id"]


def test_schd_defer_attaches_and_does_not_open_a_second_s6():
    r = route_turn("SCHD defer, wait for price buffer", plans=[SCHD_S6], now=NOW)
    assert r["action"] == "attach"
    assert r["plan_id"] == "plan_schd_s6"
    assert r["intent"] == DEFER
    assert r.get("mint_situation_type") is None


def test_dust_and_test_refuse_mint():
    assert mint_eligibility("TEST1") == REFUSE_TEST
    assert mint_eligibility("SOAKX") == REFUSE_TEST
    assert mint_eligibility("CASH") == REFUSE_CASH
    assert mint_eligibility("SRNE", dust={"SRNE"}) == REFUSE_DUST
    assert mint_eligibility("RTX") is None


def test_a_dust_symbol_is_refused_not_minted():
    r = route_turn("what about SRNE", plans=[], dust={"SRNE"}, now=NOW)
    assert r["action"] == "refuse"
    assert r["reason"] == REFUSE_DUST


def test_free_text_with_no_symbol_refuses():
    r = route_turn("what should i do today", plans=[], now=NOW)
    assert r["action"] == "refuse"
    assert r["reason"] == REFUSE_NONE
    assert r["plan_id"] is None


def test_no_telegram_anywhere_in_the_module():
    import re

    src = (Path(__file__).resolve().parents[1]
           / "scripts/lib/cio_s0_operator_loop.py").read_text(encoding="utf-8")
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", src))
    for bad in ("send_cio_message", "api.telegram.org", "RealTelegramAdapter",
                "requests.post", "urlopen"):
        assert bad not in code, bad


# ----------------------------------------------------------------- routing

def test_attach_beats_refuse_for_an_existing_plan():
    """An ack on a dust name still means something if a plan is open."""
    dusty = dict(SCHD_S6, symbols=["SRNE"], plan_id="plan_srne")
    r = route_turn("ack SRNE", plans=[dusty], dust={"SRNE"}, now=NOW)
    assert r["action"] == "attach"
    assert r["plan_id"] == "plan_srne"


def test_explicit_plan_id_wins():
    r = route_turn("ack", plans=[SCHD_S6], plan_id="plan_schd_s6", now=NOW)
    assert r["action"] == "attach"
    assert r["reason"] == "explicit_plan_id"


def test_closed_plans_are_not_attach_targets():
    closed = dict(SCHD_S6, status="cancelled")
    r = route_turn("what about SCHD", plans=[closed], now=NOW)
    assert r["action"] == "mint"


def test_newest_open_plan_wins():
    old = dict(SCHD_S6, plan_id="old", created_ts="2026-01-01")
    new = dict(SCHD_S6, plan_id="new", created_ts="2026-08-20")
    assert newest_open_plan_for("SCHD", [old, new])["plan_id"] == "new"


@pytest.mark.parametrize("text,intent", [
    ("ack that", ACK), ("defer for now", DEFER), ("reject this", REJECT),
    ("what about V", QUESTION),
])
def test_intent_classification(text, intent):
    assert classify_intent(text) == intent


def test_reject_outranks_defer_and_ack():
    assert classify_intent("ok but reject, wait") == REJECT


def test_turn_id_is_stable_for_the_same_turn():
    a = turn_id_for("RTX", "what about RTX", NOW.isoformat())
    b = turn_id_for("RTX", "what about RTX", NOW.isoformat())
    assert a == b


def test_symbol_extraction_reuses_the_existing_extractor():
    assert "RTX" in extract_operator_symbols("thoughts on RTX please")
    assert extract_operator_symbols("what should i do") == []


# --------------------------------------------------------------- turn store

def test_turns_persist_and_the_next_wake_sees_the_last_one(tmp_path):
    for txt in ("what about RTX", "RTX defer until earnings"):
        persist_turn(tmp_path, route_turn(txt, plans=[], now=NOW))
    last = last_turn_for("RTX", tmp_path)
    assert last["intent"] == DEFER
    assert operator_last_line("RTX", tmp_path).startswith("operator last: defer")


def test_turn_store_keeps_a_hash_not_the_words(tmp_path):
    """A product surface must not be able to leak the operator's message."""
    persist_turn(tmp_path, route_turn("RTX secret internal note", plans=[],
                                      now=NOW))
    blob = (tmp_path / "data/cio/cio_operator_turns.jsonl").read_text(
        encoding="utf-8")
    assert "secret internal note" not in blob
    assert "text_hash" in blob


def test_no_turn_for_an_unknown_symbol(tmp_path):
    assert last_turn_for("NOPE", tmp_path) is None
    assert operator_last_line("NOPE", tmp_path) is None


# ---------------------------------------------------------------- rehydrate

def test_rehydrate_returns_a_bundle_even_with_no_stores(tmp_path):
    b = rehydrate("RTX", root=tmp_path, plans=[])
    assert b["symbol"] == "RTX"
    assert b["open_plans"] == []
    assert b["research"]["prior_outcome"] is None
    assert b["desk_pin_only"] is True


def test_rehydrate_finds_open_plans_and_kinds(tmp_path):
    b = rehydrate("SCHD", root=tmp_path, plans=[SCHD_S6])
    assert b["open_plans"] == ["plan_schd_s6"]
    assert b["open_plan_kinds"] == ["S6_CONCENTRATION_OR_DISPOSITION"]


def test_rehydrate_carries_the_operator_turn(tmp_path):
    persist_turn(tmp_path, route_turn("SCHD defer", plans=[SCHD_S6], now=NOW))
    b = rehydrate("SCHD", root=tmp_path, plans=[SCHD_S6])
    assert b["last_turn_intent"] == DEFER
    assert b["operator_last"].startswith("operator last: defer")


def test_gate_input_carries_prior_outcome_so_the_ladder_applies():
    """Without this the gate pays for a first pass on a tainted subject."""
    b = {"symbol": "RTX", "open_plans": ["p1"],
         "research": {"prior_outcome": "execution_language",
                      "prior_artifact_ids": ["r1"], "research_id": "r1"}}
    gi = gate_input_from(b)
    assert gi["prior_outcome"] == "execution_language"
    from scripts.lib.cio_research_gate import decide

    assert decide(gi, now=NOW)["decision"] == "skip"


# ------------------------------------------------------- thesis honesty

def test_coverage_reports_the_gap_without_minting():
    c = thesis_coverage(held_non_dust=["SCHD", "V", "XLI"],
                        thesis_symbols={"SCHD"})
    assert c["held_non_dust_n"] == 3
    assert c["with_thesis_n"] == 1
    assert c["missing"] == ["V", "XLI"]
    assert c["auto_minted"] is False
    assert all(r["state"] == RESEARCH_REQUIRED
               for r in c["rows"] if r["symbol"] != "SCHD")


def test_coverage_does_not_stamp_a_desk_thesis_on_everything():
    c = thesis_coverage(held_non_dust=["A", "B", "C"], thesis_symbols=set())
    assert c["with_thesis_n"] == 0
    assert c["missing_n"] == 3


# ------------------------------------------------------------ product

def test_s0_is_suppressed_by_the_notification_policy():
    """Notifying the operator about their own message is noise by definition."""
    r = policy.decide({"plan_id": "p", "situation_type": SITUATION_TYPE,
                       "material": True}, now=NOW)
    assert r["decision"] == policy.SUPPRESSED
    assert r["reason"] == "s0_operator_turn_default_suppressed"
    assert r["would_send"] is False


def test_s0_rows_are_visible_on_the_command_center_block():
    from scripts.lib.cio_command_center import build_notification_block

    b = build_notification_block([
        {"plan_id": "s0a", "situation_type": SITUATION_TYPE,
         "symbols": ["RTX"], "status": "draft", "material": True,
         "title": "Operator converse: what about RTX"},
        SCHD_S6,
    ], now=NOW)
    assert b["s0_open_n"] == 1
    assert b["s0_operator_turns"][0]["symbols"] == ["RTX"]
    assert b["would_send_any"] is False
