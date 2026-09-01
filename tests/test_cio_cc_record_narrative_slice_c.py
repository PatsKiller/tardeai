"""Slice C — the record's narrative reaches the Command Center.

The operator's acceptance sentence is `test_home_payload_carries_cash_letter_
and_held_narrative`: the home payload contains the cash letter AND at least one
non-SCHD held record narrative, with `telegram_sent` false. SCHD is excluded on
purpose — it is the one name the desk has always had prose for, so a payload
that only proves SCHD proves nothing about the spine.

The rest of this file guards the ways the wiring could be wrong while still
looking right:

  * a missing / empty store must still build a payload (fail SOFT — a blank
    page is worse than a stale one);
  * the cash letter must be on /v3/cio even though notify is off;
  * the letter must CITE next_eligible_at, so the reader can see when the desk
    intends to look again;
  * a changed regime must change the letter, so "did this change?" is
    answerable without a diff;
  * "deploy $N into TICKER" is refused by a guard, not by a prompt — and a
    record that trips it loses its prose, not the whole letter;
  * the composer renders prose and never calls a model. `cio_run` stays a
    DETERMINISTIC_PRODUCT.

READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. No sizes, orders or deltas are asserted
here, and nothing in this file contacts a vendor.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import cio_command_center as c  # noqa: E402
from scripts.lib.cio_instrument_record import (  # noqa: E402
    CASH_SLEEVE,
    InstrumentRecordStore,
    cc_narrative,
    new_record,
)
from scripts.lib.cio_record_narrative import (  # noqa: E402
    CASH_OPTION_IDS,
    InstructionInLetter,
    assert_no_instruction,
    build_cash_letter,
)

FIXED = datetime(2026, 8, 28, 20, 0, 0, tzinfo=timezone.utc)
NEXT_LOOK = "2026-09-15T13:30:00+00:00"


# ── fixtures ────────────────────────────────────────────────────────────────

def _plan() -> dict:
    return {
        # Live is_cash row sum (LITMUS_MONEY). Sleeve fossil 630784.82 is prior only.
        "cash_total_usd": 630513.62,
        "cash_investable_usd": 321622.3,
        "cash_posture": "ABOVE_BAND",
        "cash_source": "position_rows",
        "cash_as_of": {"as_of": "2026-08-14", "unstamped": False,
                       "source": "holdings rows where is_cash, oldest stamp wins"},
        "portfolio_value_usd": 1240000.0,
        "portfolio_constraints": [{"kind": "concentration_fire_pct", "value": 12.0}],
        "position_decisions": [
            {"symbol": "SCHD", "cio_stance": "HOLD", "current_value_usd": 200000.0,
             "current_weight_pct": 16.53, "recommended_delta_usd": 0.0,
             "why_now": "Advisory TRIM — SCHD", "risk": "concentration > cap"},
            # REVIEW is a non-size reason to surface a card, which is what this
            # suite wants: a book row on the page with no dollar attached to it.
            {"symbol": "NOC", "cio_stance": "HOLD", "action_label": "REVIEW",
             "current_value_usd": 88000.0, "current_weight_pct": 7.1,
             "recommended_delta_usd": 0.0,
             "why_now": "deferral on record; review the standing question",
             "risk": "within single-name cap"},
        ],
        "seasonality": {
            "month": {"month_name": "September", "hypothesis_bucket": "REPRODUCED",
                      "worst_six_months_window": True},
            "presidential_cycle": {"cycle_label": "midterm"},
            "calendar_effects": ["september_weakness"],
        },
    }


def _sectors() -> dict:
    return {"opportunities": [
        {"sector": "Technology", "state": "LEADING", "current_exposure_pct": 7.4,
         "target_posture_pct": 18.0, "recommendation": "STAGED_DEPLOYMENT",
         "candidates": []},
    ]}


def _queue() -> dict:
    return {"items": [
        {"symbol": "XOM", "source": "advisory", "directive_label": "Advisory TRIM — XOM"},
        {"symbol": "ADBE", "source": "reentry", "state": "NEAR ENTRY",
         "directive_label": "Re-entry NEAR ENTRY — ADBE"},
    ]}


def _store(tmp_path: Path, *, cash_narrative: str = "Cash sleeve held as optionality.",
           with_cash_record: bool = True) -> InstrumentRecordStore:
    """A store with prose on a held name, a watch, a re-entry and a sector."""
    store = InstrumentRecordStore(tmp_path / "records.jsonl")
    if with_cash_record:
        store.upsert(new_record(
            "SLEEVE", "CASH",
            # Fossil on the sleeve — must NOT become cash_letter.cash_usd.
            cash_usd=630784.82,
            cash_written_at="2026-08-29T23:28:23.648735+00:00",
            cash_source="position_rows",
            next_eligible_at=NEXT_LOOK,
            notify_priority="cc",
            cc_narrative=cc_narrative(
                what=cash_narrative,
                thesis_fit="Cash is intentional optionality under the desk thesis.",
                recommendation_option_id="wait_until_month",
                writer="agent:cio_cash_lane"),
        ))
    store.upsert(new_record(
        "HELD", "NOC",
        symbols=["NOC"],
        next_eligible_at=NEXT_LOOK,
        next_research_question="Does the FY27 backlog conversion hold at this margin?",
        cc_narrative=cc_narrative(
            what="NOC: the operator deferred this in July and the deferral still stands.",
            thesis_fit="Core defense sleeve; unchanged.",
            risks=["program concentration"],
            writer="agent:cio_book_lane"),
    ))
    store.upsert(new_record(
        "HELD", "SCHD",
        symbols=["SCHD"],
        cc_narrative=cc_narrative(
            what="SCHD: concentration above cap, reviewed and left alone.",
            writer="agent:cio_book_lane"),
    ))
    store.upsert(new_record(
        "WATCH", "XOM",
        symbols=["XOM"],
        cc_narrative=cc_narrative(
            what="XOM: staged on the watch desk pending a reproduced entry band.",
            writer="agent:cio_watch_lane"),
    ))
    store.upsert(new_record(
        "EXIT", "ADBE",
        symbols=["ADBE"],
        cc_narrative=cc_narrative(
            what="ADBE: exited in May; re-entry waits on the next print.",
            writer="agent:cio_reentry_lane"),
    ))
    store.upsert(new_record(
        "SECTOR", "Technology",
        cc_narrative=cc_narrative(
            what="Technology: exposure sits well under the posture target.",
            writer="agent:cio_sector_lane"),
    ))
    return store


def _home(store, **over):
    args = dict(
        capital_plan=_plan(),
        sector_opportunities=_sectors(),
        opportunity_queue=_queue(),
        operator_product={},
        now=FIXED,
        record_store=store,
    )
    args.update(over)
    return c.build_office_home(**args)


# ── the operator's acceptance test ──────────────────────────────────────────

def test_home_payload_carries_cash_letter_and_held_narrative(tmp_path):
    """Cash letter + at least one non-SCHD held record narrative. No telegram."""
    home = _home(_store(tmp_path))

    letter = home["cash_letter"]
    assert letter["schema"] == "CashSleeveLetter@v1"
    assert letter["subject_key"] == CASH_SLEEVE
    assert letter["from_record"] is True
    # Published dollar follows capital_plan (row sum), not the sleeve fossil.
    assert letter["cash_usd"] == home["capital_plan"]["cash_total_usd"] == 630513.62
    assert letter["prior_cash_usd"] == 630784.82
    assert letter["prior_cash_written_at"] == "2026-08-29T23:28:23.648735+00:00"
    assert letter["as_of"] == "2026-08-14"
    assert "Cash sleeve" in letter["what"]

    nars = home["instrument_narratives"]
    held = {
        k: v for k, v in nars.items()
        if str(v.get("kind", "")).upper() == "HELD" and not k.endswith(":SCHD")
    }
    assert held, f"no non-SCHD held narrative in {sorted(nars)}"
    assert "HELD:NOC" in held
    assert held["HELD:NOC"]["what"].startswith("NOC:")
    assert held["HELD:NOC"]["from_record"] is True

    assert home["telegram_sent"] is False
    assert home["delivery"] == "dashboard"


# ── the letter is required even though notify is off ────────────────────────

def test_cash_letter_present_when_notify_is_off(tmp_path):
    home = _home(_store(tmp_path))
    assert home["telegram_sent"] is False
    assert home["cash_letter"]["what"]
    # Advisory shape is enforced, not requested.
    assert home["cash_letter"]["standalone_sell"] is False
    assert home["cash_letter"]["financial_action"] is False
    assert home["cash_letter"]["option_ids"] == list(CASH_OPTION_IDS)
    assert home["cash_letter"]["authority"] == "READ_ONLY_ADVISORY"
    assert home["cash_letter"]["memory_behavior_influence"] == 0


def test_letter_cites_next_eligible_at(tmp_path):
    """The reader must be able to see when the desk intends to look again."""
    home = _home(_store(tmp_path))
    assert home["cash_letter"]["next_eligible_at"] == NEXT_LOOK
    # The key is cited even when the record has no date, rather than dropped.
    bare = build_cash_letter(None, capital_plan=_plan(), now=FIXED)
    assert "next_eligible_at" in bare
    assert bare["next_eligible_at"] is None


def test_regime_hash_changes_the_letter(tmp_path):
    """'Did this change?' is answerable without diffing prose."""
    store = _store(tmp_path)
    september = _home(store)
    plan_july = _plan()
    plan_july["seasonality"] = {
        "month": {"month_name": "July", "hypothesis_bucket": "NOT_REPRODUCED",
                  "worst_six_months_window": False},
        "presidential_cycle": {"cycle_label": "midterm"},
        "calendar_effects": [],
    }
    july = _home(store, capital_plan=plan_july)

    assert september["cash_letter"]["regime"]["regime_hash"] != \
        july["cash_letter"]["regime"]["regime_hash"]
    assert september["cash_letter"]["month_context"] != july["cash_letter"]["month_context"]
    assert "worst-six-months" in september["cash_letter"]["month_context"]
    assert "worst-six-months" not in july["cash_letter"]["month_context"]
    # Same regime twice is the same letter — the hash is not a nonce.
    assert _home(store)["cash_letter"] == september["cash_letter"]


# ── record preferred, deterministic fallback behind it ──────────────────────

def test_cc_sections_prefer_the_record_narrative(tmp_path):
    """position/book row · watch row · re-entry row · sector row."""
    home = _home(_store(tmp_path))

    book = {r["symbol"]: r for r in home["cio_now"]["decisions"]}
    assert book["NOC"]["narrative_source"] == "record"
    assert book["NOC"]["cc_narrative"]["what"].startswith("NOC:")
    assert book["NOC"]["cc_narrative"]["next_eligible_at"] == NEXT_LOOK

    watch = {r["symbol"]: r for r in home["opportunities"]["watch"]}
    assert watch["XOM"]["narrative_source"] == "record"
    assert "watch desk" in watch["XOM"]["cc_narrative"]["what"]

    reentry = {r["symbol"]: r for r in home["opportunities"]["reentry"]}
    assert reentry["ADBE"]["narrative_source"] == "record"
    assert "re-entry" in reentry["ADBE"]["cc_narrative"]["what"]

    tilts = {r["sector"]: r for r in home["posture"]["sector_tilts"]}
    assert tilts["Technology"]["narrative_source"] == "record"
    assert tilts["Technology"]["cc_narrative"]["what"].startswith("Technology:")

    cov = home["record_narrative_coverage"]
    assert cov["from_record"] >= 5
    assert cov["sections"]["cash"]["from_record"] == 1
    for section in ("book", "watch", "reentry", "sector"):
        assert cov["sections"][section]["from_record"] >= 1, section


def test_fallback_when_no_record(tmp_path):
    """Empty store: every row still speaks, deterministically. Never blank."""
    empty = InstrumentRecordStore(tmp_path / "absent.jsonl")
    home = _home(empty)

    letter = home["cash_letter"]
    assert letter["from_record"] is False
    assert letter["writer"] == "deterministic_fallback"
    assert letter["what"], "the letter must never be blank"
    assert letter["cash_usd"] == 630513.62  # capital_plan row sum (not sleeve)
    assert letter["recommendation_option_id"] == "hold_cash"

    assert home["instrument_narratives"] == {}

    rows = home["cio_now"]["decisions"] + home["opportunities"]["watch"] \
        + home["opportunities"]["reentry"] + home["posture"]["sector_tilts"]
    assert rows
    for row in rows:
        assert row["narrative_source"] == "deterministic"
        assert row["cc_narrative"]["what"].strip()
        assert row["cc_narrative"]["from_record"] is False

    cov = home["record_narrative_coverage"]
    assert cov["from_record"] == 0
    assert cov["store_records"] == 0
    assert cov["from_deterministic_fallback"] == cov["rows"] > 0


def test_missing_store_still_builds_a_payload():
    """No store at all is a degraded page, not a broken one."""
    home = c.build_office_home(
        capital_plan=_plan(), operator_product={}, now=FIXED, record_store=_Broken())
    assert home["cash_letter"]["what"]
    assert home["instrument_narratives"] == {}
    assert home["record_narrative_coverage"]["from_record"] == 0
    assert home["telegram_sent"] is False


class _Broken:
    """A store that raises on every read — the worst realistic case."""

    def load(self, key):                                         # noqa: D102
        raise RuntimeError("store unavailable")

    def all(self):                                               # noqa: D102
        raise RuntimeError("store unavailable")


# ── the instruction guard ───────────────────────────────────────────────────

@pytest.mark.parametrize("text", [
    "deploy $250,000 into NOC",
    "Deploy $250,000 into NOC over three tranches.",
    "buy 50,000 of the sleeve into SCHD",
    "allocate $100,000 to XLB",
])
def test_deploy_dollars_into_ticker_is_refused(text):
    with pytest.raises(InstructionInLetter):
        assert_no_instruction(text)


@pytest.mark.parametrize("text", [
    "Cash sleeve 630784.82 held as optionality.",
    "September is a reproduced weak month; the desk is not adding here.",
    "The operator deferred this in July and the deferral still stands.",
])
def test_advisory_prose_passes_the_guard(text):
    assert_no_instruction(text)  # must not raise


def test_poisoned_cash_record_loses_its_prose_not_the_letter(tmp_path):
    """A guard in code, not a prompt. One bad record must not blank the page."""
    store = _store(tmp_path, cash_narrative="Deploy $250,000 into NOC this week.")
    home = _home(store)
    letter = home["cash_letter"]
    assert letter["from_record"] is False
    assert letter["record_refused"]
    assert "deploy" not in letter["what"].lower()
    assert letter["what"], "the letter survives the refusal"
    assert home["telegram_sent"] is False


def test_poisoned_row_record_falls_back_to_deterministic(tmp_path):
    store = _store(tmp_path)
    store.upsert(new_record(
        "HELD", "NOC", symbols=["NOC"],
        cc_narrative=cc_narrative(what="Deploy $80,000 into NOC on the open.",
                                  writer="agent:compromised"),
    ))
    home = _home(store)
    noc = {r["symbol"]: r for r in home["cio_now"]["decisions"]}["NOC"]
    assert noc["narrative_source"] == "deterministic"
    assert noc["cc_narrative"]["record_refused"] == "instruction_in_narrative"
    assert "deploy" not in noc["cc_narrative"]["what"].lower()


# ── DETERMINISTIC_PRODUCT ───────────────────────────────────────────────────

FORBIDDEN_MODULE_TOKENS = (
    "telegram", "ollama", "anthropic", "openai", "hermes", "llm",
    "requests", "httpx", "urllib.request", "smtplib", "socket",
)


def test_composer_imports_no_delivery_or_llm_module():
    """The narrative blob is an INPUT this composer renders, not a model call.

    Checked two ways: the module's own import statements, and what actually
    lands in `sys.modules` after a full payload is built — a transitive import
    would be just as much of a model call as a direct one.
    """
    src = (ROOT / "scripts" / "lib" / "cio_command_center.py").read_text(encoding="utf-8")
    import_lines = [
        ln.strip() for ln in src.splitlines()
        if ln.strip().startswith(("import ", "from ")) and "#" not in ln.split("import")[0]
    ]
    assert import_lines
    for line in import_lines:
        low = line.lower()
        for token in FORBIDDEN_MODULE_TOKENS:
            assert token not in low, f"composer imports {token!r}: {line}"


def test_building_a_payload_loads_no_delivery_or_llm_module(tmp_path):
    import subprocess
    code = (
        "import sys, json\n"
        "sys.path.insert(0, %r)\n"
        "from scripts.lib.cio_command_center import build_office_home\n"
        "from scripts.lib.cio_instrument_record import InstrumentRecordStore\n"
        "build_office_home(operator_product={}, record_store=InstrumentRecordStore(%r))\n"
        "bad = [m for m in sys.modules if any(t in m.lower() for t in %r)]\n"
        "print(json.dumps(bad))\n"
    ) % (str(ROOT), str(tmp_path / "records.jsonl"),
         tuple(t for t in FORBIDDEN_MODULE_TOKENS if t != "socket"))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, cwd=str(ROOT), timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    import json as _json
    assert _json.loads(out.stdout.strip().splitlines()[-1]) == []


def test_payload_is_deterministic_with_the_same_store(tmp_path):
    store = _store(tmp_path)
    a = _home(store)
    b = _home(InstrumentRecordStore(tmp_path / "records.jsonl"))
    assert a["cash_letter"] == b["cash_letter"]
    assert a["instrument_narratives"] == b["instrument_narratives"]
    assert a["record_narrative_coverage"] == b["record_narrative_coverage"]


def test_no_behavior_fields_leak_into_the_narrative_blob(tmp_path):
    """MBI_BEHAVIOR=0: prose may change what the desk SAYS, never a size."""
    home = _home(_store(tmp_path))
    banned = ("recommended_delta_usd", "size_usd", "shares", "qty", "order",
              "target_weight_pct")
    for key, nar in home["instrument_narratives"].items():
        for field in banned:
            assert field not in nar, f"{key} leaked {field}"
    for field in banned:
        assert field not in home["cash_letter"], f"cash letter leaked {field}"
