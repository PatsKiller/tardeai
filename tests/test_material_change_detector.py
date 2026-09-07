"""Stage 1: notice when a tracked name stops behaving like itself.

On 2026-09-05 three watchlist names were up 15-40% and nothing told the operator.
Every research job here is schedule-triggered, and a sweep treats every name
identically on every pass — so it structurally cannot notice that THIS name is
behaving unlike ITSELF.

Verified against live data on 2026-09-06: AOUT went 9.97 -> 14.50, +45.4% against a
3.04% average daily move — 14.93x. `watchlist_items.change_pct` independently
reported 45.4363 from a different source.

Three properties this suite holds:

FREE AND DETERMINISTIC
    No model on any row. Detection must stay cheap so the expensive judgement step
    downstream only runs on things that actually moved.

CORRUPT DATA IS SKIPPED, NEVER ALARMED ON
    ticker_prices carries literal NaN in a numeric column. A NaN compares False to
    every threshold, so `if ratio < K: continue` LETS IT THROUGH and it fires. The
    first run of this detector duly reported BHVN at magnitude NaN. Wrong in the
    dangerous direction: corrupt data manufacturing an alert.

WHAT IT COULD NOT SEE IS PART OF THE OUTPUT
    A symbol with too little history is NOT_EVALUABLE, counted and reported. A
    detector that silently skips what it cannot measure inherits the exact defect
    stage 0 existed to end.

No database and no network: the cursor is a fake.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCRIPT = ROOT / "scripts" / "material_change_detector.py"


def W(symbol: str, tier: str = "watchlist") -> dict:
    """universe() returns {symbol: {reasons, precedence, tier}} since precedence
    landed. Built here so a shape change breaks one helper, not fifteen tests."""
    import material_change_detector as M

    return {symbol: {"reasons": [tier], "precedence": M.PRECEDENCE[tier],
                     "tier": tier}}


@pytest.fixture(scope="module")
def mod():
    return pytest.importorskip("material_change_detector")


class Cur:
    """Serves both sources: ticker_prices, and the corroborating watchlist_items.

    `independent` defaults to agreeing with whatever the price query reports, so a
    test that is not ABOUT corroboration does not have to restate it. Tests that are
    about it pass explicit values.
    """

    def __init__(self, rows, independent=None):
        self._rows = rows
        self._independent = independent
        self._result = []

    def execute(self, sql, params=None):
        if "SAVEPOINT" in sql.upper() or "ROLLBACK" in sql.upper():
            self._result = []
        elif "to_regclass" in sql:
            self._result = [(None,)]          # optional sources absent
        elif "ticker_prices" in sql:
            self._result = self._rows
        elif "watchlist_items" in sql:
            if self._independent is not None:
                self._result = [(k.upper(), v) for k, v in self._independent.items()]
            else:
                # Agree with the price source by default.
                self._result = [(r[0].upper(), r[3]) for r in self._rows
                                if r[3] is not None]
        else:
            self._result = []

    def fetchall(self):
        return self._result


# ── free and deterministic ──────────────────────────────────────────────────

def test_no_model_is_called(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    for banned in ("llm", "chat_json", "deepseek", "openai", "anthropic",
                   "run_with_escalation", "cio_governed"):
        assert banned not in src.lower(), f"stage 1 reaches a model via {banned!r}"
    assert '"model_calls": 0' in src


def test_the_same_change_mints_the_same_id(mod):
    """A detector that re-emits the same finding forever is one nobody reads."""
    a = mod.change_guid("AOUT", "price_excursion", "2026-09-04")
    assert a == mod.change_guid("AOUT", "price_excursion", "2026-09-04")
    assert a != mod.change_guid("AOUT", "price_excursion", "2026-09-05")
    assert a != mod.change_guid("BALY", "price_excursion", "2026-09-04")


def test_the_insert_dedupes_on_that_id(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert "ON CONFLICT (change_guid) DO NOTHING" in src
    assert "change_guid       UUID UNIQUE NOT NULL" in src


# ── corrupt data must never fire ────────────────────────────────────────────

def test_a_nan_move_does_not_fire(mod):
    """The bug this file was written after.

    NaN < 3.0 is False, so the early-continue does not trigger and the change is
    emitted with magnitude NaN. Corrupt data must never manufacture an alert.
    """
    rows = [("BHVN", 40, float("nan"), float("nan"), "2026-08-28")]
    found, stats = mod.price_excursions(Cur(rows), W("BHVN"))
    assert found == [], "a NaN magnitude was emitted as a real change"
    assert stats["not_evaluable"] == 1
    assert stats["fired"] == 0


def test_the_query_excludes_nan_at_the_source(mod):
    """And it cannot be written as close_price = close_price: Postgres NUMERIC NaN
    compares EQUAL to itself, unlike float."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "close_price <> 'NaN'::numeric" in src
    # Checked against the EXECUTABLE sql only. The comment inside that same
    # string deliberately quotes the wrong form to explain why it is wrong, so
    # both a file-wide search and a naive block scope flag the explanation as
    # the defect. Strip -- comments first.
    sql = src.split("WITH d AS (", 1)[1].split('"""', 1)[0]
    code = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    assert "close_price = close_price" not in code
    assert "close_price <> 'NaN'::numeric" in code, "the guard is only in a comment"


def test_a_real_move_still_fires(mod):
    """The negative control for the NaN guard: do not fix corruption by breaking
    detection."""
    rows = [("AOUT", 66, 3.0438, 45.4363, "2026-09-04")]
    found, stats = mod.price_excursions(Cur(rows), W("AOUT"))
    assert len(found) == 1
    assert found[0]["magnitude"] == pytest.approx(14.93, abs=0.01)
    assert stats["fired"] == 1


def test_a_quiet_name_does_not_fire(mod):
    rows = [("AAPL", 66, 1.25, 0.9, "2026-09-04")]
    found, _ = mod.price_excursions(Cur(rows), W("AAPL"))
    assert found == []


# ── the threshold is relative, not absolute ────────────────────────────────

def test_the_same_percent_move_fires_for_one_name_and_not_another(mod):
    """The whole reason for normalising. 8% is noise in one name and an event in
    another, and a fixed percent cannot express that."""
    calm = mod.price_excursions(Cur([("CALM", 60, 0.8, 8.0, "2026-09-04")]),
                                W("CALM"))[0]
    wild = mod.price_excursions(Cur([("WILD", 60, 9.0, 8.0, "2026-09-04")]),
                                W("WILD"))[0]
    assert len(calm) == 1, "8% on a 0.8% baseline is a ten-sigma move and must fire"
    assert wild == [], "8% on a 9% baseline is an ordinary day and must not"


def test_k_is_configurable_without_a_deploy(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'os.getenv("MATERIAL_CHANGE_K"' in src


# ── it reports what it could not see ───────────────────────────────────────

def test_too_little_history_is_counted_not_silently_dropped(mod):
    rows = [("NEWCO", 4, 2.0, 30.0, "2026-09-04")]
    found, stats = mod.price_excursions(Cur(rows), W("NEWCO"))
    assert found == []
    assert stats["not_evaluable"] == 1
    assert stats["evaluated"] == 0


def test_a_zero_baseline_is_not_evaluable_rather_than_infinite(mod):
    """Dividing by a zero baseline yields inf, which beats every threshold and
    would fire on a symbol that has never moved at all."""
    rows = [("FLAT", 60, 0.0, 5.0, "2026-09-04")]
    found, stats = mod.price_excursions(Cur(rows), W("FLAT"))
    assert found == []
    assert stats["not_evaluable"] == 1


def test_not_evaluable_reaches_the_result(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"not_evaluable"' in src.split("RESULT:", 1)[1]


def test_a_dry_run_reports_unmeasured_not_zero(mod):
    """rows_produced=0 means 'measured, wrote nothing'. A dry run measured nothing."""
    assert mod.persist(Cur([]), [{"symbol": "X"}], apply=False) == 0
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"rows_produced": written if args.apply else None' in src


# ── universe ───────────────────────────────────────────────────────────────

def test_unreadable_holdings_degrade_rather_than_crash(mod, monkeypatch, tmp_path, capsys):
    """A broken holdings file must not take the whole detector down — but it must
    say the universe was narrowed, or the run looks complete when it is not."""
    bad = tmp_path / "holdings.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(mod, "HOLDINGS", bad)

    class C(Cur):
        def execute(self, sql, params=None):
            u = sql.upper()
            if "SAVEPOINT" in u or "ROLLBACK" in u:
                self._result = []
            elif "to_regclass" in sql:
                self._result = [(None,)]   # optional sources absent
            elif "watchlist_items" in sql and "source_tier" in sql:
                self._result = []          # the PREFERRED query — AAPL is not core/S0
            elif "watchlist_items" in sql:
                self._result = [("AAPL",)]
            else:
                self._result = []

    out = mod.universe(C([]))
    assert out == W("AAPL")
    assert "WARN" in capsys.readouterr().err


def test_a_held_name_is_tracked_even_if_not_on_the_watchlist(mod, monkeypatch, tmp_path):
    h = tmp_path / "holdings.json"
    h.write_text(json.dumps({"holdings": [{"symbol": "schd"}]}), encoding="utf-8")
    monkeypatch.setattr(mod, "HOLDINGS", h)

    class C(Cur):
        def execute(self, sql, params=None):
            u = sql.upper()
            if "SAVEPOINT" in u or "ROLLBACK" in u:
                self._result = []
            elif "to_regclass" in sql:
                self._result = [(None,)]   # optional sources absent
            elif "watchlist_items" in sql and "source_tier" in sql:
                self._result = []          # the PREFERRED query — AAPL is not core/S0
            elif "watchlist_items" in sql:
                self._result = [("AAPL",)]
            else:
                self._result = []

    out = mod.universe(C([]))
    assert out["SCHD"]["tier"] == "held", "held names must be tracked, upper-cased"
    assert out["AAPL"]["tier"] == "watchlist"
    assert out["SCHD"]["precedence"] > out["AAPL"]["precedence"], (
        "money at risk must outrank money considered")


# ── authority ──────────────────────────────────────────────────────────────

def test_it_is_advisory_only(mod):
    """Checks for CALLS, not for the word.

    The first version asserted "broker" was absent from the source, which the
    module docstring fails on the sentence promising it never writes to one. A
    guard that forbids naming the hazard makes the code less clear, not safer.
    """
    assert mod.AUTHORITY == "READ_ONLY_ADVISORY"
    src = SCRIPT.read_text(encoding="utf-8")
    for banned in ("place_order(", "submit_order(", "cancel_order(",
                   "position_size(", "import broker", "from broker"):
        assert banned not in src, f"stage 1 reaches execution via {banned!r}"


# ── a move needs a second source before it is called a change ───────────────
#
# Measured 2026-09-06, the first live run of this detector. portfolio_repricer had
# written closes into ticker_prices that were not market moves at all:
#
#     NOC   528.37 -> 119.32  (-77%)   watchlist_items.change_pct says  -2.44%
#     SCHG   35.83 ->   8.15  (-77%)                                    +0.28%
#     JEPI   57.42 ->  22.41  (-61%)                                    -0.08%
#     BND    71.92 ->  55.64  (-23%)                                    -0.57%
#     AOUT                     +45.4%                                  +45.44%  <- real
#
# Six of eight excursions were corrupt data, faithfully reported. The one real move
# agreed with the independent source to four decimal places; every corrupt one
# disagreed by an order of magnitude. Corroboration costs nothing and separates them
# perfectly.

def test_a_corroborated_move_fires(mod):
    ok, why = mod.agrees(45.4363, 45.4363)
    assert ok and why == "corroborated"


def test_sources_that_disagree_by_an_order_of_magnitude_do_not_fire(mod):
    """The exact six."""
    for observed, independent in ((22.64, 0.57), (60.97, 0.08), (77.20, 0.44),
                                  (77.42, 2.44), (50.80, 0.82), (77.25, 0.28)):
        ok, why = mod.agrees(observed, independent)
        assert not ok, f"{observed} vs {independent} was accepted"
        assert why.startswith("disagree")


def test_no_second_source_is_not_corroboration(mod):
    """Firing on a single source is how six corrupt rows became six alerts."""
    ok, why = mod.agrees(45.0, None)
    assert not ok and why == "no_independent_source"


def test_tolerance_is_a_ratio_not_a_percentage_point_gap(mod):
    """2pp is nothing on a 45% move and everything on a 0.5% one, so a fixed
    percentage-point tolerance cannot be right for both."""
    assert mod.agrees(45.0, 43.0)[0] is True
    assert mod.agrees(3.0, 1.0)[0] is False


def test_two_quiet_sources_are_not_a_disagreement(mod):
    """Below the floor both are saying 'nothing happened' and the ratio between them
    is meaningless — 0.02 vs 0.01 is not a 2x conflict."""
    ok, why = mod.agrees(0.02, 0.01)
    assert not ok and why == "both_below_floor"


def test_uncorroborated_candidates_are_counted_not_hidden(mod):
    """What was rejected, and why, must reach the result. A detector that quietly
    drops candidates cannot be audited."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"uncorroborated"' in src
    assert "uncorroborated_detail" in src


def test_the_independent_value_is_recorded_on_the_change(mod):
    """So a later reader can see what the second source said, not just that it agreed."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"independent_pct"' in src


def test_corroboration_is_free(mod):
    """One extra query, no model."""
    src = SCRIPT.read_text(encoding="utf-8")
    fn = src.split("def corroborate(", 1)[1].split("\ndef ", 1)[0]
    assert "watchlist_items" in fn
    for banned in ("llm", "model", "chat"):
        assert banned not in fn.lower()


def test_the_end_to_end_path_rejects_a_corrupt_move(mod):
    """The whole chain: a big ratio that a second source does not confirm must not
    become a change, and must be counted as uncorroborated rather than vanishing."""
    rows = [("NOC", 60, 1.9803, 77.42, "2026-09-04")]
    found, stats = mod.price_excursions(Cur(rows, independent={"NOC": 2.44}),
                                        W("NOC", "held"))
    assert found == [], "a corrupt move became an operator alert"
    assert stats["uncorroborated"] == 1
    assert stats["fired"] == 0
    assert any("NOC" in d for d in stats["uncorroborated_detail"])


def test_the_end_to_end_path_accepts_the_real_one(mod):
    """AOUT, whose two sources agreed to four decimal places."""
    rows = [("AOUT", 66, 3.0438, 45.4363, "2026-09-04")]
    found, stats = mod.price_excursions(Cur(rows, independent={"AOUT": 45.4363}),
                                        W("AOUT"))
    assert len(found) == 1
    assert stats["fired"] == 1 and stats["uncorroborated"] == 0
    assert found[0]["evidence"]["independent_pct"] == 45.4363


# ── precedence: what gets looked at first when the queue exceeds the budget ──
#
# Operator instruction 2026-09-06. Curation and routing are both capped per run, so
# this is not cosmetic ordering — it decides what actually gets researched when more
# moved than we can afford to look at.

def test_money_at_risk_outranks_money_considered(mod):
    """A held name that moves is a position behaving unlike itself; a watchlist name
    that moves is an idea behaving unlike itself. Both matter, in that order."""
    assert mod.PRECEDENCE["held"] > mod.PRECEDENCE["watchlist"]
    assert mod.PRECEDENCE["operator"] > mod.PRECEDENCE["held"]
    assert mod.PRECEDENCE["reentry"] > mod.PRECEDENCE["preferred"]
    assert mod.PRECEDENCE["preferred"] > mod.PRECEDENCE["watchlist"]
    assert mod.PRECEDENCE["watchlist"] > mod.PRECEDENCE["other"]


def test_a_symbol_takes_its_highest_tier(mod):
    """A name can qualify several ways at once — held AND on the watchlist. The
    strongest claim wins, or a held name would be ranked as a mere idea."""
    score, tier = mod.precedence_for({"watchlist", "held"})
    assert tier == "held" and score == mod.PRECEDENCE["held"]
    assert mod.precedence_for({"watchlist", "operator", "held"})[1] == "operator"
    assert mod.precedence_for(set())[1] == "other"


def test_changes_are_ordered_by_precedence_before_magnitude(mod):
    """A 3x move on a holding outranks a 14x move on an idea."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'changes.sort(key=lambda x: (-(x.get("precedence") or 0), -(x["magnitude"] or 0)))' in src


def test_precedence_is_stored_not_just_computed(mod):
    """It has to survive to the consumer, or the ordering is lost the moment the
    detector exits."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "precedence        INTEGER" in src
    assert "ADD COLUMN IF NOT EXISTS precedence" in src, (
        "CREATE TABLE IF NOT EXISTS does not add columns to an existing table")


def test_an_optional_source_failure_is_isolated_by_a_savepoint(mod):
    """In Postgres a failed statement aborts the WHOLE transaction, so a bare
    try/except around an optional probe does not make it optional — it hides the
    failure and poisons every later statement. A missing column on an optional table
    took down the price query twenty lines away."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "SAVEPOINT opt_src" in src
    assert "ROLLBACK TO SAVEPOINT opt_src" in src


def test_a_missing_optional_source_is_reported_not_silent(mod):
    """The run continues with a narrower universe — and says so, because a silently
    narrower universe looks identical to a quiet market."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "not applied" in src and "WARN optional source" in src
