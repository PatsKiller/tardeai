"""Wave 3A.2 — library seed, calendar reproduction, and the grade law.

The three tests the brief names explicitly are at the bottom: a midterm fact
must not close a SCHD plan, a VIX regime must not emit a sell, and a tariff
event must override SKIP_FRESH without attaching execution language.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_corpus_index as corpus
from scripts.lib.cio_calendar_facts import (
    MIN_SAMPLE_N, build_calendar_facts, divergence_report, load_french,
    load_synthetic,
)
from scripts.lib.cio_library_seed import fred_series_rows, seed_rows
from scripts.lib.cio_research_gate import decide

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)
REPO = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------- grade law

def test_only_a_and_b_may_close():
    assert corpus.CLOSING_GRADES == frozenset({"A", "B"})
    assert "C" not in corpus.CLOSING_GRADES
    assert "D" not in corpus.CLOSING_GRADES
    assert "X" not in corpus.CLOSING_GRADES


def test_entity_dimensions_are_never_corpus_closed():
    for dim in ("bear_case", "what_is_priced_in", "structural_drivers"):
        assert dim in corpus.ENTITY_ONLY_DIMENSIONS
        assert corpus.consult(dim)["closes"] is False


def test_every_registry_row_carries_the_required_fields():
    required = {"source_id", "family", "title", "authors", "year",
                "isbn_or_doi", "official_url", "path_or_MISSING",
                "content_hash", "as_of", "evidence_grade", "application_law",
                "dimension_scope", "refresh", "notes"}
    for row in seed_rows() + fred_series_rows():
        assert required <= set(row), (row["source_id"], required - set(row))


def test_no_seed_row_is_entity_scoped():
    """Nothing seeded may claim authority over a name-level question."""
    for row in seed_rows() + fred_series_rows():
        assert row["dimension_scope"] == "context", row["source_id"]


def test_grades_are_from_the_legal_set():
    for row in seed_rows() + fred_series_rows():
        assert row["evidence_grade"] in {"A", "B", "C", "D", "X"}


def test_copyright_books_stay_citation_only():
    by_id = {r["source_id"]: r for r in seed_rows()}
    for sid in ("natenberg_option_volatility", "hull_options_futures",
                "gatheral_volatility_surface"):
        row = by_id[sid]
        assert row["evidence_grade"] == "C"
        assert row["path_or_MISSING"] == "MISSING"


def test_ingested_files_carry_a_hash():
    on_disk = [r for r in seed_rows() + fred_series_rows()
               if r["status"] == "FOUND_ON_DISK"]
    assert len(on_disk) == 8, "French FF3 + 7 FRED series"
    for row in on_disk:
        assert row["content_hash"], row["source_id"]
        assert row["evidence_grade"] == "A"


# ------------------------------------------------- reproduction on real data

def test_the_grading_series_is_real_market_history():
    """The whole point of 3A.2: grade B must mean something.

    1987-10 is the cheapest discriminator. The synthetic file reads +3.27%
    there; real history fell about 21.5%.
    """
    pts = load_french()
    assert len(pts) > 1000
    oct87 = next(p for p in pts if p.year == 1987 and p.month == 10)
    assert oct87.ret_pct < -15.0, "grading series is not real market history"
    assert min(p.ret_pct for p in pts) < -20.0


def test_reproduced_facts_name_the_real_series():
    for f in build_calendar_facts():
        if f["reproduced"]:
            assert f["reproduced_on"] == "ken_french_monthly_1926"


def test_unreproducible_effects_stay_context_only():
    """Daily-resolution effects cannot be graded from monthly data."""
    by_id = {f["fact_id"]: f for f in build_calendar_facts()}
    for fid in ("turn_of_month", "pre_holiday", "santa_claus_rally"):
        assert by_id[fid]["reproduced"] is False
        assert by_id[fid]["evidence_grade"] == "C"


def test_small_sample_cannot_earn_b():
    from scripts.lib.cio_calendar_facts import _grade

    assert _grade({"n": MIN_SAMPLE_N - 1}, reproduced=True) == "D"
    assert _grade({"n": MIN_SAMPLE_N}, reproduced=True) == "B"
    assert _grade({"n": 9999}, reproduced=False) == "C"


def test_no_calendar_fact_claims_grade_a():
    """A additionally needs out-of-sample support; B is the in-sample ceiling."""
    assert all(f["evidence_grade"] != "A" for f in build_calendar_facts())


def test_every_calendar_fact_is_context_and_cannot_sell():
    for f in build_calendar_facts():
        assert f["dimension_scope"] == "context"
        assert f["standalone_sell"] is False
        assert f["creates_trim"] is False
        assert f["max_influence_pct"] == 10.0


def test_worst_six_months_is_positive_on_real_data():
    """Recorded because it contradicts the folk version of the claim.

    "Sell in May" reads as though May-Oct is negative. On 1926- real data the
    window averages positive; the effect is a *differential* against Nov-Apr,
    which is why this is calendar_context and never an instruction.
    """
    by_id = {f["fact_id"]: f for f in build_calendar_facts()}
    wsm = by_id["worst_six_months_may_oct"]["result"]
    bsm = by_id["best_six_months"]["result"]
    assert wsm["mean"] > 0, "May-Oct is not negative on real data"
    assert bsm["mean"] > wsm["mean"], "the differential is the actual claim"


def test_synthetic_series_diverges_from_real():
    """Evidence for the pending re-grade decision."""
    div = divergence_report()
    assert div, "no comparison produced"
    assert max(d["abs_delta"] for d in div) > 1.0, (
        "expected material divergence between synthetic and real")


def test_no_calendar_fact_contains_an_instruction():
    """'Sell in May' must never be stored as a verb."""
    from scripts.lib.execution_language import find_imperative

    for f in build_calendar_facts():
        blob = " ".join(str(f.get(k) or "") for k in
                        ("title", "notes", "application_law"))
        assert not find_imperative(blob), (f["fact_id"], blob)


# ------------------------------------------------ the three named gate tests

def test_midterm_fact_does_not_close_a_schd_plan():
    """A month-of-year effect may not answer a ticker thesis."""
    r = decide({"material": True, "kind": "held_core_thesis", "symbol": "SCHD",
                "corpus": corpus.consult("bear_case", now=NOW)}, now=NOW)
    assert r["decision"] != "corpus_hit"
    assert corpus.consult("bear_case", now=NOW)["closes"] is False


def test_vix_regime_does_not_emit_a_sell():
    from scripts.lib.execution_language import find_imperative

    rows = [r for r in seed_rows() if "vix" in r["source_id"].lower()]
    rows += [r for r in fred_series_rows() if "vixcls" in r["source_id"]]
    assert rows
    for row in rows:
        assert row["dimension_scope"] == "context"
        assert not find_imperative(
            " ".join(str(row.get(k) or "") for k in
                     ("title", "notes", "application_law")))
        assert "sell" not in str(row.get("application_law")).lower() or \
               "never a standalone sell" in str(row["application_law"])


def test_tariff_event_overrides_skip_fresh_without_execution_language(monkeypatch):
    """An event beats a warm cache; it still mints nothing."""
    import scripts.lib.research_source_index as rsi

    monkeypatch.setattr(rsi, "decide", lambda *a, **k: "SKIP_UNCHANGED")
    r = decide({"material": True, "kind": "held_core_thesis", "symbol": "SCHD",
                "source_id": "tariff_src", "content_hash": "h",
                "event_fired": True}, now=NOW)
    assert r["decision"] != "reuse", "a fired tariff event must override SKIP_FRESH"
    assert r["financial_action"] is False
    assert r["authority"] == "READ_ONLY_ADVISORY"


def test_a_tariff_event_carrying_execution_language_still_fails_closed():
    r = decide({"material": True, "kind": "held_core_thesis",
                "event_fired": True,
                "prior_text": "Tariff announced — sell half the position now."},
               now=NOW)
    assert r["decision"] == "skip"
    assert r["reason"] == "execution_language_fail_closed"


# ----------------------------------------------------------------- one index

def test_registry_is_still_one_index():
    r = corpus.registry()
    # 3A.3 added FF5, momentum, the normalised French series, Shiller and
    # Damodaran to the seed.
    assert r["counts"]["seed"] == 39
    assert r["counts"]["calendar_facts"] == 12
    # 3A.3 ingested FF5, momentum and the normalised French series.
    assert r["counts"]["seed_on_disk"] == 11
    assert r["freshness_law"].startswith("research_source_index")


def test_no_second_freshness_table_was_added():
    import inspect

    for mod in ("cio_library_seed", "cio_calendar_facts"):
        src = inspect.getsource(__import__(f"scripts.lib.{mod}", fromlist=["x"]))
        assert "TTL_HOURS" not in src, f"{mod} must not keep its own TTLs"
