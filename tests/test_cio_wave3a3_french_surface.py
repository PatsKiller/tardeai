"""Wave 3A.3 — operator surfaces grade off real market data.

The rule this file exists to hold: a determinism fixture may be synthetic; an
operator-visible number may not.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_corpus_index as corpus
from scripts.lib.cio_library_paths import (
    OPERATOR_MONTHLY, is_synthetic_path, operator_monthly_series_path,
    us_equity_monthly_path,
)
from scripts.lib.cio_regime_facts import MIN_SAMPLE_N, build_regime_facts
from scripts.lib.cio_research_gate import decide

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------- the resolver rule

def test_operator_resolver_is_not_synthetic_and_not_in_tests():
    p = operator_monthly_series_path()
    assert "synthetic" not in p.name.lower()
    assert "tests" not in p.parts
    assert not is_synthetic_path(p)


def test_seasonality_surface_reads_the_operator_series():
    from scripts.lib.cio_seasonality_analytics import DEFAULT_FIXTURE

    assert DEFAULT_FIXTURE == OPERATOR_MONTHLY
    assert "synthetic" not in DEFAULT_FIXTURE.name.lower()


def test_the_synthetic_fixture_still_exists_for_determinism():
    """Operator decision 4: keep it, do not revert it, do not surface it."""
    assert us_equity_monthly_path().exists()
    assert is_synthetic_path(us_equity_monthly_path())


def test_no_operator_module_resolves_the_synthetic_series():
    """research_governance is exempt: it is R1-frozen and not an operator surface."""
    exempt = {"scripts/lib/cio_library_paths.py",
              "scripts/lib/cio_calendar_facts.py",
              "scripts/lib/research_governance/almanac.py",
              "scripts/lib/research_governance/pr_scope_guard.py"}
    offenders = []
    for path in (REPO / "scripts").rglob("*.py"):
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        if rel in exempt:
            continue
        txt = path.read_text(encoding="utf-8", errors="replace")
        # strip comments and docstrings: modules legitimately *explain* the
        # two-resolver rule, and naming the synthetic path is not using it.
        code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", txt))
        if "us_equity_monthly_synthetic" in code or "us_equity_monthly_path()" in code:
            offenders.append(rel)
    assert not offenders, offenders


def test_the_operator_series_is_real_market_history():
    rows = list(csv.DictReader(OPERATOR_MONTHLY.open(encoding="utf-8")))
    assert len(rows) == 1200
    oct87 = next(r for r in rows
                 if int(r["year"]) == 1987 and int(r["month"]) == 10)
    assert float(oct87["return_pct"]) < -15.0
    assert min(float(r["return_pct"]) for r in rows) < -20.0


def test_the_normalized_series_is_reproducible_from_source():
    """The committed file must equal what the generator produces."""
    import subprocess

    r = subprocess.run(
        [".venv/bin/python", "scripts/build_french_monthly_normalized.py", "--check"],
        cwd=REPO, capture_output=True, text=True)
    assert "MATCH" in r.stdout, r.stdout + r.stderr


# ------------------------------------------------ the re-grade actually bit

def test_august_weakness_no_longer_reproduces():
    """The claim the synthetic file was propping up.

    On real 1926- data August averages positive with a ~63% win rate, so the
    almanac's weak-August claim is contradicted rather than reproduced. Grade
    X exists for exactly this and must not be quietly softened to B.
    """
    from scripts.lib.cio_seasonality_analytics import august_general

    rec = august_general()
    assert rec["mean"] > 0, "August is positive on the real series"
    assert rec["evidence_grade"] == "X"


def test_september_weakness_survives_on_real_data():
    from scripts.lib.cio_seasonality_analytics import september_general

    rec = september_general()
    assert rec["mean"] < 0
    assert rec["evidence_grade"] in {"A", "B"}


def test_october_is_now_a_reproduced_weak_month():
    """Real history has crashes; the synthetic series had none."""
    from scripts.lib.cio_seasonality_analytics import reproduced_weak_months

    assert 10 in reproduced_weak_months()


def test_a_contradicted_grade_cannot_close_a_gap():
    assert "X" not in corpus.CLOSING_GRADES


# ------------------------------------------------------------ regime facts

def test_regime_facts_are_context_only_and_cannot_sell():
    facts = build_regime_facts()
    assert facts
    for f in facts:
        assert f["dimension_scope"] == "context"
        assert f["standalone_sell"] is False
        assert f["creates_trim"] is False
        assert f["sample_n"] is not None
        assert f["as_of"]


def test_regime_facts_carry_no_imperative():
    from scripts.lib.execution_language import find_imperative

    for f in build_regime_facts():
        blob = " ".join(str(f.get(k) or "") for k in
                        ("title", "notes", "application_law"))
        assert not find_imperative(blob), (f["fact_id"], blob)


def test_small_samples_are_graded_d():
    from scripts.lib.cio_regime_facts import _grade

    assert _grade(MIN_SAMPLE_N - 1) == "D"
    assert _grade(MIN_SAMPLE_N) == "C"
    assert _grade(30) == "B"


def test_no_regime_fact_encodes_a_threshold_action():
    for f in build_regime_facts():
        blob = str(f).lower()
        for banned in ("then sell", "-> sell", "therefore sell", "emit sell"):
            assert banned not in blob


# ------------------------------------------------------------- rails hold

def test_midterm_row_still_does_not_close_a_schd_plan():
    r = decide({"material": True, "kind": "held_core_thesis", "symbol": "SCHD",
                "corpus": corpus.consult("bear_case", now=NOW)}, now=NOW)
    assert r["decision"] != "corpus_hit"


def test_registry_still_one_index_no_second_ttl():
    import inspect

    r = corpus.registry()
    assert r["counts"]["regime_facts"] == 7
    assert r["freshness_law"].startswith("research_source_index")
    src = inspect.getsource(
        __import__("scripts.lib.cio_regime_facts", fromlist=["x"]))
    assert "TTL_HOURS" not in src


def test_fed_documents_stay_url_only_with_event_refresh():
    """Operator decision 3: do not commit them into the release."""
    from scripts.lib.cio_library_seed import seed_rows

    by_id = {r["source_id"]: r for r in seed_rows()}
    for sid in ("fomc_statements_minutes_sep", "fed_beige_book",
                "frbsf_wp_2025_30_usmpd"):
        assert by_id[sid]["path_or_MISSING"] == "MISSING"
        assert by_id[sid]["refresh"] == "event"


def test_copyright_books_still_c_with_url():
    from scripts.lib.cio_library_seed import seed_rows

    by_id = {r["source_id"]: r for r in seed_rows()}
    for sid in ("natenberg_option_volatility", "hull_options_futures"):
        assert by_id[sid]["evidence_grade"] == "C"
        assert by_id[sid]["official_url"]
