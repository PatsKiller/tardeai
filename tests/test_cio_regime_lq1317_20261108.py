"""LQ-20261107-1317 — the CIO brief's deterministic Regime block.

Operator, 2026-11-08 20:23 ET: *"we need a little bit more: is the market right, is the sector right, we also
have the CPI, plus we're coming through the weekend of a crash. I would expect this updated around 6 a.m. with the
futures and around 8 a.m. with pre-market."* This module pins the six sections of ``lib/cio_regime`` and the one
law they share: **a missing input is stated as missing, never filled with a plausible number.** So the cases that
matter most here are the dishonest-looking ones — a futures print with no dated settle, a sector payload that is
absent rather than empty, an unreadable store versus a store with no open episode, and a held name the off-hours
lane never quoted.

It also pins the two wiring facts: the bottom line cites the regime only through clauses the sections can prove,
and an unreachable store degrades the block instead of failing the brief.

Every fixture is synthetic: ZZ-prefixed symbols, invented prices and sector labels, no database, no provider, no
network, no model. The one real dependency is the NYSE calendar, which is a static table on this host.
"""

from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import scripts.cio_overnight_brief as B  # noqa: E402
from lib import cio_regime as R  # noqa: E402
from lib.cio_buys_gate import buys_block  # noqa: E402

#: The Monday the operator's two new slots land on, after the 11-04 → 11-06 selloff: 08:00 ET pre-open.
AS_OF = datetime(2026, 11, 9, 8, 0, tzinfo=R.ET)


# ── fixtures ──────────────────────────────────────────────────────────────────────────────────────


def market_risk_doc() -> dict:
    """The shape of ``data/runtime/market_risk/latest.json`` this block reads — synthetic throughout."""
    return {
        "as_of": "2026-11-06T20:05:00+00:00",
        "tier": "RED",
        "market_tier": "RED",
        "score": 7.4,
        "mode": "shadow",
        "confirming": 4,
        "hysteresis": {"carried_only": True, "days_in_tier": 2},
        "observations": [
            {"category": "breadth", "state": "RISK_ON", "headline": "ZSYN advancing 71% of issues",
             "observed_at": "2026-11-06T20:00:00+00:00"},
            {"category": "trend", "state": "RISK_OFF", "headline": "ZZTAPE below its 50-day",
             "observed_at": "2026-11-06T20:00:00+00:00"},
        ],
        "shock_type": {"class": "SECTOR", "label": "semis selloff", "headline": "semis led the tape down"},
        "sectors": {
            "as_of": "2026-11-06T20:00:00+00:00",
            "sectors_measured": 6,
            "sectors_down": 4,
            "stressed": ["semis", "software"],
            "resilient": ["utilities", "staples"],
            "groups": [
                {"key": "semi", "label": "Semis", "kind": "sector", "rs20": -3.2, "state": "RISK_OFF"},
                {"key": "soft", "label": "Software", "kind": "sector", "rs20": -1.0, "state": "RISK_OFF"},
                {"key": "fin", "label": "Financials", "kind": "sector", "rs20": -0.5, "state": "NEUTRAL"},
                {"key": "indu", "label": "Industrials", "kind": "sector", "rs20": 0.8, "state": "NEUTRAL"},
                {"key": "util", "label": "Utilities", "kind": "sector", "rs20": 2.1, "state": "RISK_ON"},
                {"key": "stap", "label": "Staples", "kind": "sector", "rs20": 4.5, "state": "RISK_ON"},
                # Not a sector: must never be ranked as a leader or a laggard.
                {"key": "mom", "label": "Momentum factor", "kind": "factor", "rs20": 9.9, "state": "RISK_ON"},
            ],
        },
    }


def macro_calendar() -> list[dict]:
    return [
        {"event": "Consumer Price Index", "date": "2026-11-10", "time_et": "08:30"},
        {"event": "Retail Sales", "date": "2026-11-13", "time_et": "08:30"},
    ]


def episode_row() -> dict:
    return {
        "episode_id": "ep-zz-001",
        "kind": "sector_selloff",
        "scope": "semis",
        "state": "OPEN",
        "opened_at": "2026-11-04T20:30:00+00:00",
        "baseline_date": "2026-11-04",
        "affected_sectors": ["semis", "software"],
        "last_eval": {"session": "2026-11-06"},
        "updated_at": "2026-11-06T20:30:00+00:00",
    }


def futures_row(symbol: str, *, price: float, ref_close: float | None, ref_date: str | None,
                change_pct: float | None, bar_end: str = "2026-11-09T11:00:00+00:00") -> dict:
    return {
        "symbol": symbol, "session": "futures_open", "bar_end": bar_end, "price": price,
        "reference_close": ref_close, "reference_date": ref_date, "change_pct": change_pct,
        "reference_basis": "prior_settle" if ref_date else None,
    }


class FakeDb:
    """One reader behind every section. ``fail=True`` makes the store unreadable, as a closed conn would."""

    def __init__(self, *, episodes=None, futures=None, refs=None, premarket=None, fail: bool = False):
        self.episodes = [] if episodes is None else episodes
        self.futures = [] if futures is None else futures
        self.refs = [] if refs is None else refs
        self.premarket = [] if premarket is None else premarket
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, sql: str, params=None):
        if self.fail:
            raise RuntimeError("store unreachable")
        self.calls.append(sql)
        if "market_event_episodes" in sql:
            return list(self.episodes)
        if "reference_close IS NOT NULL" in sql:
            return list(self.refs)
        if "session = ANY" in sql:
            wanted = set((params or [None, []])[1] or [])
            return [r for r in self.premarket if r["symbol"] in wanted]
        if "market_quotes_extended" in sql:
            return list(self.futures)
        raise AssertionError(f"unexpected SQL reached the stub: {sql[:60]}")


def loaded(tmp_path, doc: dict | None = None) -> dict:
    """The mapping the brief actually hands the block: written as the file, read back by its own loader."""
    path = tmp_path / "data" / "runtime" / "market_risk"
    path.mkdir(parents=True, exist_ok=True)
    (path / "latest.json").write_text(json.dumps(doc if doc is not None else market_risk_doc()),
                                      encoding="utf-8")
    return B.load_market_risk(tmp_path)


def premarket_row(symbol: str, *, pct: float, price: float = 100.0,
                  bar_end: str = "2026-11-09T11:30:00+00:00", session: str = "premarket") -> dict:
    return {"symbol": symbol, "session": session, "session_date": "2026-11-09", "bar_end": bar_end,
            "price": price, "reference_close": price / (1 + pct / 100.0), "reference_date": "2026-11-06",
            "change_pct": pct, "reference_basis": "prior_close"}


# ── the honesty law: missing ≠ empty ≠ failed ────────────────────────────────────────────────────


def test_no_reader_at_all_states_each_store_section_missing_and_never_empty():
    doc = R.build(as_of=AS_OF, market_risk=market_risk_doc(), macro=macro_calendar(),
                  held_symbols=["ZRKT"], db_query=None)
    for name in ("event", "futures", "premarket"):
        assert doc[name]["state"] == "missing", name
        assert doc[name]["missing"], name
    # The two file-backed sections still answer: one broken store never hides another read.
    assert doc["market"]["state"] == "ok"
    assert doc["sector"]["state"] == "ok"
    assert any(m.startswith("event: ") for m in doc["missing"])
    assert any(m.startswith("futures: ") for m in doc["missing"])


def test_an_unreadable_store_is_missing_and_a_store_with_no_rows_is_empty():
    unreadable = R.event_block(FakeDb(fail=True), AS_OF)
    assert unreadable["state"] == "missing"
    assert unreadable["missing"] == ["market_event_episodes unreadable (table missing or no reader)"]
    assert unreadable["line"] == "market-event context missing"
    empty = R.event_block(FakeDb(episodes=[]), AS_OF)
    assert empty["state"] == "empty"
    assert empty["missing"] == ["no open market-event episode"]
    assert empty["short"] is None


def test_every_section_carries_its_own_as_of_source_and_missing(tmp_path):
    db = FakeDb(episodes=[episode_row()],
                futures=[futures_row(s, price=5000.0, ref_close=4980.0, ref_date="2026-11-06",
                                     change_pct=0.4) for s in R.FUTURES_ROOTS],
                premarket=[premarket_row("ZRKT", pct=1.5)])
    doc = R.build(as_of=AS_OF, market_risk=loaded(tmp_path), macro=macro_calendar(),
                  held_symbols=["ZRKT"], db_query=db)
    for name in ("market", "sector", "macro", "event", "futures", "premarket"):
        sec = doc[name]
        assert sec["schema"] == "CioRegime@v1#section", name
        assert sec["state"] in ("ok", "empty", "missing"), name
        assert isinstance(sec["missing"], list), name
        assert isinstance(sec["source_ids"], list), name
        assert sec["as_of"] is not None or sec["state"] == "missing", name
    assert doc["schema"] == R.SCHEMA
    assert doc["authority"] == "READ_ONLY_ADVISORY"


# ── market ────────────────────────────────────────────────────────────────────────────────────────


def test_the_market_section_reports_the_tier_the_confirmation_and_that_it_is_a_shadow_carried_read(tmp_path):
    sec = R.market_block(loaded(tmp_path), AS_OF)
    assert sec["state"] == "ok"
    assert sec["tier"] == "RED" and sec["score"] == pytest.approx(7.4)
    assert sec["confirming"] == {"n": 4, "of": 2}
    assert sec["breadth"]["state"] == "RISK_ON"
    assert "67%" not in sec["line"]  # the detail is passed through, not parsed into a number
    assert "SHADOW" in sec["line"] and "carried over the closure" in sec["line"]
    assert sec["as_of"] == "2026-11-06T20:05:00+00:00"


def test_no_market_risk_read_says_so_and_still_produces_a_section():
    sec = R.market_block({}, AS_OF)
    assert sec["state"] == "missing"
    assert sec["tier"] is None
    assert "no market-risk read on file" in sec["missing"]
    assert "not measured" in sec["line"]


def test_a_tier_with_no_breadth_observation_names_the_gap_rather_than_printing_nothing(tmp_path):
    doc = market_risk_doc()
    doc["observations"] = [o for o in doc["observations"] if o["category"] != "breadth"]
    sec = R.market_block(loaded(tmp_path, doc), AS_OF)
    assert sec["state"] == "ok"  # the tier was measured
    assert "breadth not measured" in sec["missing"]
    assert "breadth not measured" in sec["line"]


def test_the_brief_loader_passes_through_the_parts_the_old_reader_dropped(tmp_path):
    """The snapshot is read once and shared, so the brief and the Home card cannot disagree about the tape."""
    path = tmp_path / "data" / "runtime" / "market_risk"
    path.mkdir(parents=True)
    (path / "latest.json").write_text(json.dumps(market_risk_doc()), encoding="utf-8")
    got = B.load_market_risk(tmp_path)
    assert got["confirming"] == {"n": 4, "of": 2}  # 4 of the 2 observations on file
    assert got["mode"] == "shadow"
    assert got["carried_only"] is True
    assert got["breadth"]["state"] == "RISK_ON"
    assert got["sectors"]["stressed"] == ["semis", "software"]
    assert got["market_tier"] == "RED"
    sec = R.market_block(got, AS_OF)
    assert sec["confirming"] == {"n": 4, "of": 2}


# ── sector ───────────────────────────────────────────────────────────────────────────────────────


def test_the_sector_section_names_the_selloff_and_ranks_leaders_and_laggards_by_rs20(tmp_path):
    sec = R.sector_block(loaded(tmp_path), AS_OF)
    assert sec["state"] == "ok"
    assert sec["selloff"] == ["semis", "software"]
    assert [x["label"] for x in sec["leaders"]] == ["Staples", "Utilities", "Industrials"]
    assert [x["label"] for x in sec["laggards"]] == ["Semis", "Software", "Financials"]
    assert sec["shock"]["class"] == "SECTOR"
    # A factor group is not a sector and is never ranked as one.
    assert all(x["group"] != "mom" for x in sec["leaders"] + sec["laggards"])
    assert "selloff in semis, software" in sec["line"]
    assert "2 of 6 sectors holding" in sec["line"]


def test_a_sector_payload_that_is_absent_is_missing_not_an_empty_leader_list(tmp_path):
    doc = market_risk_doc()
    doc.pop("sectors")
    sec = R.sector_block(loaded(tmp_path, doc), AS_OF)
    assert sec["state"] == "missing"
    assert sec["leaders"] == [] and sec["laggards"] == []
    assert sec["missing"] == ["no sector block in the market-risk snapshot"]
    assert sec["line"] == "sector read missing"


def test_a_sector_groups_with_no_rs20_are_not_ranked_at_all(tmp_path):
    doc = market_risk_doc()
    for g in doc["sectors"]["groups"]:
        g.pop("rs20", None)
    sec = R.sector_block(loaded(tmp_path, doc), AS_OF)
    assert sec["leaders"] == [] and sec["laggards"] == []
    assert "no sector rs20 on file" in sec["missing"]
    assert "selloff in semis, software" in sec["line"]


def test_a_sector_that_is_up_over_twenty_days_is_never_called_a_laggard(tmp_path):
    """Live 2026-11-08: the third-weakest sector was +0.2%, and "laggards Energy +0.2" is a false statement."""
    doc = market_risk_doc()
    doc["sectors"]["groups"] = [
        {"key": "a", "label": "Semis", "kind": "sector", "rs20": -3.2, "state": "RISK_OFF"},
        {"key": "b", "label": "Energy", "kind": "sector", "rs20": 0.2, "state": "NEUTRAL"},
        {"key": "c", "label": "Comms", "kind": "sector", "rs20": 0.5, "state": "NEUTRAL"},
        {"key": "d", "label": "Staples", "kind": "sector", "rs20": 4.5, "state": "RISK_ON"},
    ]
    sec = R.sector_block(loaded(tmp_path, doc), AS_OF)
    assert [x["label"] for x in sec["laggards"]] == ["Semis"]
    assert [x["label"] for x in sec["leaders"]] == ["Staples", "Comms", "Energy"]
    assert all(x["rs20"] < 0 for x in sec["laggards"])
    assert all(x["rs20"] > 0 for x in sec["leaders"])
    assert "laggards Semis -3.2" in sec["line"]


def test_a_sector_tape_with_nothing_underwater_states_that_instead_of_padding_the_list(tmp_path):
    doc = market_risk_doc()
    doc["sectors"]["groups"] = [
        {"key": "a", "label": "Semis", "kind": "sector", "rs20": 0.9, "state": "NEUTRAL"},
        {"key": "b", "label": "Energy", "kind": "sector", "rs20": 2.4, "state": "RISK_ON"},
    ]
    sec = R.sector_block(loaded(tmp_path, doc), AS_OF)
    assert sec["laggards"] == []
    assert "no sector underperforming on rs20" in sec["missing"]
    assert "laggards" not in sec["line"]


# ── macro gate ───────────────────────────────────────────────────────────────────────────────────


def test_the_macro_section_reuses_the_lq1311_gate_verbatim():
    sec = R.macro_block(market_risk_doc(), macro_calendar(), AS_OF)
    expected = buys_block("RED", macro_calendar(), AS_OF.astimezone(R.ET))
    assert sec["gate"] == expected["gate"] == "NONE"
    assert sec["line"] == expected["line"]
    assert sec["until"] == expected["until"]
    assert sec["until_short"] == "CPI Tue"
    assert sec["source_ids"] == expected["source_ids"]
    assert sec["events"] == 2


def test_an_empty_macro_window_states_that_and_the_gate_still_answers_from_the_tier():
    sec = R.macro_block(market_risk_doc(), [], AS_OF)
    assert sec["state"] == "missing"
    assert sec["missing"] == ["no macro events in the calendar window"]
    assert sec["gate"] == "NONE"  # RED gates without a named release too
    assert sec["until_short"] is None


# ── event context ───────────────────────────────────────────────────────────────────────────────


def test_the_event_section_names_the_baseline_and_counts_only_completed_sessions_since_it():
    sec = R.event_block(FakeDb(episodes=[episode_row()]), AS_OF)
    assert sec["state"] == "ok"
    assert sec["episode_id"] == "ep-zz-001"
    assert sec["baseline_date"] == "2026-11-04"
    # The baseline is a CLOSE: 11-05 and 11-06 closed after it, and 11-09 has not.
    assert sec["sessions_since_baseline"] == 2
    assert sec["short"] == "after the 11-04 selloff"
    assert sec["affected_sectors"] == ["semis", "software"]
    assert sec["last_session"] == "2026-11-06"


def test_the_newest_open_episode_wins_and_an_episode_without_a_baseline_is_missing():
    newer = dict(episode_row(), episode_id="ep-zz-002", opened_at="2026-11-06T20:30:00+00:00",
                 updated_at="2026-11-06T20:30:00+00:00")
    sec = R.event_block(FakeDb(episodes=[episode_row(), newer]), AS_OF)
    assert sec["episode_id"] == "ep-zz-002"
    undated = dict(episode_row(), baseline_date=None)
    sec = R.event_block(FakeDb(episodes=[undated]), AS_OF)
    assert sec["state"] == "missing"
    assert sec["missing"] == ["episode has no baseline_date"]
    assert sec["sessions_since_baseline"] is None
    assert sec["short"] is None


def test_sessions_between_counts_trading_days_strictly_after_the_baseline_close():
    assert R.sessions_between(datetime(2026, 11, 4).date(), datetime(2026, 11, 9).date()) == 2
    assert R.sessions_between(datetime(2026, 11, 4).date(), datetime(2026, 11, 5).date()) == 0
    assert R.sessions_between(datetime(2026, 11, 6).date(), datetime(2026, 11, 9).date()) == 0


# ── futures ─────────────────────────────────────────────────────────────────────────────────────


def test_futures_percent_counts_only_when_its_reference_is_the_session_before():
    db = FakeDb(futures=[futures_row("/ES", price=5000.0, ref_close=4980.0, ref_date="2026-11-06",
                                     change_pct=0.40)])
    sec = R.futures_block(db, AS_OF)
    es = sec["rows"][0]
    assert sec["prior_session"] == "2026-11-06"
    assert es["change_pct"] == pytest.approx(0.40)
    assert es["reference_stale"] is False
    assert es["change_label"] == "vs prior settle"
    assert es["age_hours"] == pytest.approx(2.0)  # 06:00 ET print read at 08:00 ET
    # The other two roots were not quoted: named, not silently dropped.
    assert "/NQ" in sec["missing"] and "/RTY" in sec["missing"]
    assert sec["short"] == "futures ES +0.40%"


def test_a_settle_older_than_the_prior_session_is_used_only_with_a_label_and_kept_out_of_the_short_line():
    """11-06's futures after-hours prints were never collected, so the newest print moves from the 11-05 settle."""
    db = FakeDb(
        futures=[futures_row("/ES", price=6000.0, ref_close=None, ref_date=None, change_pct=None,
                             bar_end="2026-11-06T21:00:00+00:00")],
        refs=[{"/ES": None, "symbol": "/ES", "reference_close": 5986.8, "reference_date": "2026-11-05"}],
    )
    sec = R.futures_block(db, AS_OF)
    es = sec["rows"][0]
    assert es["reference_stale"] is True
    assert es["reference_date"] == "2026-11-05"
    assert es["change_pct"] == pytest.approx(0.22, abs=0.01)
    assert es["change_label"] == "vs the 11-05 settle"
    assert "vs the 2026-11-05 settle (stale)" in sec["line"]
    # A stale percent is a fact about an old settle; the bottom line does not cite it as this morning's move.
    assert sec["short"] is None


def test_a_futures_print_with_no_dated_settle_reports_the_level_and_says_the_percent_was_not_measured():
    db = FakeDb(futures=[futures_row("/NQ", price=21000.0, ref_close=None, ref_date=None, change_pct=None)])
    sec = R.futures_block(db, AS_OF)
    nq = sec["rows"][0]
    assert nq["price"] == pytest.approx(21000.0)
    assert nq["change_pct"] is None
    assert nq["reference_date"] is None
    assert "(percent not measured)" in sec["line"]
    assert "/NQ percent (no dated settle in the feed)" in sec["missing"]
    assert sec["short"] is None


def test_futures_with_no_print_on_file_still_lists_all_three_roots_as_unquoted():
    sec = R.futures_block(FakeDb(futures=[]), AS_OF)
    assert sec["state"] == "empty"
    assert sec["rows"] == []
    assert sec["line"] == "no futures print on file"
    assert set(sec["missing"]) == set(R.FUTURES_ROOTS)
    assert sec["short"] is None


# ── pre-market ──────────────────────────────────────────────────────────────────────────────────


def test_the_premarket_section_reports_the_held_names_movers_biggest_absolute_move_first():
    db = FakeDb(premarket=[premarket_row("ZRKT", pct=-4.0), premarket_row("ZQT", pct=1.2)])
    sec = R.premarket_block(db, ["ZRKT", "ZQT"], AS_OF)
    assert sec["state"] == "ok"
    assert [r["symbol"] for r in sec["rows"]] == ["ZRKT", "ZQT"]
    assert sec["held"] == 2
    assert "largest ZRKT -4.00%" in sec["line"]
    assert sec["missing"] == []


def test_a_held_name_the_off_hours_lane_never_quoted_is_named_not_omitted():
    db = FakeDb(premarket=[premarket_row("ZRKT", pct=0.5)])
    sec = R.premarket_block(db, ["ZRKT", "ZUNSN"], AS_OF)
    assert sec["missing"] == ["ZUNSN"]
    assert "1 of 2 held names moved" in sec["line"]


def test_a_non_ticker_holding_row_is_counted_not_listed_as_a_name_that_was_never_quoted():
    """A settlement id or a fund code in the holdings document is not a ticker the quote lane will ever print."""
    db = FakeDb(premarket=[premarket_row("ZRKT", pct=0.5)])
    sec = R.premarket_block(db, ["ZRKT", "12507E201", "543354104"], AS_OF)
    assert sec["held"] == 1
    assert sec["not_ticker"] == 2
    assert sec["missing"] == []


def test_no_held_names_at_all_says_so_rather_than_reading_the_store():
    db = FakeDb()
    sec = R.premarket_block(db, [], AS_OF)
    assert sec["state"] == "empty"
    assert sec["missing"] == ["no held names to read"]
    assert db.calls == [], "an empty held list must not cost a query"


# ── the one-line posture fragment ───────────────────────────────────────────────────────────────


def test_the_short_line_is_only_what_the_sections_can_prove():
    assert R.short_line({"short": "after the 11-04 selloff"}, {"short": "futures ES/NQ/RTY +0.30%"}) == (
        "after the 11-04 selloff; futures ES/NQ/RTY +0.30%")
    assert R.short_line({"short": "after the 11-04 selloff"}, {"short": None}) == "after the 11-04 selloff"
    assert R.short_line({}, {}) is None


def test_build_unions_source_ids_without_duplicates_and_prefixes_each_missing_line_with_its_section(tmp_path):
    db = FakeDb(episodes=[episode_row()],
                futures=[futures_row("/ES", price=5000.0, ref_close=4980.0, ref_date="2026-11-06",
                                     change_pct=0.4)],
                premarket=[premarket_row("ZRKT", pct=1.5)])
    doc = R.build(as_of=AS_OF, market_risk=loaded(tmp_path), macro=macro_calendar(),
                  held_symbols=["ZRKT", "ZUNSN"], db_query=db)
    assert len(doc["source_ids"]) == len(set(doc["source_ids"]))
    assert "market_risk" in doc["source_ids"]  # shared by market and the macro gate, listed once
    assert "futures: /NQ" in doc["missing"]
    assert "premarket: ZUNSN" in doc["missing"]
    assert all(": " in m for m in doc["missing"])
    assert doc["short"] == "after the 11-04 selloff; futures ES +0.40%"


# ── the brief's wiring ──────────────────────────────────────────────────────────────────────────


def _verdict(regime=None) -> str:
    return B.synopsis_verdict(
        posture_label="DEFENSIVE — HOLD CASH",
        market={"tier": "RED", "market_wide": False},
        book={},
        stop_advice=[],
        reentry={"stage2": False, "stage3": False},
        buys={"gate": "NONE", "until_short": "CPI Tue"},
        regime=regime,
    )


def test_the_bottom_line_cites_the_selloff_and_the_futures_percent(tmp_path):
    doc = R.build(as_of=AS_OF, market_risk=loaded(tmp_path), macro=macro_calendar(),
                  held_symbols=[], db_query=FakeDb(episodes=[episode_row()],
                                                   futures=[futures_row(s, price=5000.0, ref_close=4980.0,
                                                                        ref_date="2026-11-06", change_pct=0.30)
                                                            for s in R.FUTURES_ROOTS]))
    text = _verdict(doc)
    assert "RED sector tape after the 11-04 selloff" in text
    assert "futures ES/NQ/RTY +0.30%" in text
    assert "no buys before CPI Tue" in text
    assert len(text) <= B.VERDICT_MAX_CHARS


def test_the_bottom_line_never_invents_a_clause_for_a_missing_regime():
    assert "futures" not in _verdict(None)
    assert "selloff" not in _verdict(None)
    # A regime whose stores were all unreadable adds nothing either.
    doc = R.build(as_of=AS_OF, market_risk={}, macro=[], held_symbols=[], db_query=None)
    assert doc["short"] is None
    assert "futures" not in _verdict(doc)


def test_an_unreachable_store_degrades_the_regime_block_instead_of_failing_the_brief(monkeypatch, capsys):
    def no_connect():
        raise RuntimeError("no db")

    monkeypatch.setattr(B, "connect", no_connect)
    out = B.load_regime(as_of=AS_OF, risk_market=market_risk_doc(), calendar={"macro": macro_calendar()},
                        symbols=["ZRKT"], service=None, dry_run=True)
    assert out["schema"] == R.SCHEMA
    assert out["market"]["state"] == "ok"
    assert out["sector"]["state"] == "ok"
    assert out["macro"]["gate"] == "NONE"
    assert out["event"]["state"] == "missing"
    assert out["futures"]["state"] == "missing"
    assert "regime store unavailable read-only" in capsys.readouterr().err


def test_a_read_only_guard_that_cannot_be_armed_means_the_block_does_not_read(monkeypatch, capsys):
    """A dry run with an unprovable read-only session must not read the store on a hope: it states the gap."""
    class _Conn:
        closed = False
        def close(self):  # noqa: D401 -- a stub
            self.closed = True

    conn = _Conn()
    monkeypatch.setattr(B, "connect", lambda: conn)

    def refuse(_conn):
        raise RuntimeError("cannot arm read-only")

    import scripts.lib.lane_last_receipt as L

    monkeypatch.setattr(L, "enforce_readonly", refuse)
    out = B.load_regime(as_of=AS_OF, risk_market={}, calendar={"macro": []}, symbols=[], service=None,
                        dry_run=True)
    assert conn.closed, "the session is closed when the guard fails"
    assert out["event"]["state"] == "missing"
    assert out["event"]["missing"] == ["market_event_episodes unreadable (table missing or no reader)"]
    assert "regime store unavailable read-only" in capsys.readouterr().err


# ── the rail: nothing here decides anything ────────────────────────────────────────────────────


def test_the_module_imports_no_network_no_broker_and_no_model():
    src = (ROOT / "scripts" / "lib" / "cio_regime.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "re", "datetime", "typing", "zoneinfo", "lib"}, imported
    for verb in ("place_order", "submit_order", "cancel_order", "requests", "urllib"):
        assert verb not in src
