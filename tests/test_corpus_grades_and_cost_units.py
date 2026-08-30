"""Two things I reported wrongly, pinned so the next reader is not misled.

**The grades.** I reported "the catalog exists but not one row carries a grade;
0 of 34 eligible to corpus_hit" — measured by reading
`config/cio_research_source_catalog.json` directly. That was the wrong artifact.
The grade is DERIVED at read time by `cio_corpus_index.catalog_entries()` from
`CATALOG_GRADE = "D"`: no lawful full text -> not reproducible -> D, and grade D
"must not be treated as a Trade AI fact". Zero of the 34 being able to
corpus_hit is the designed and correct outcome, not a defect. The eligible
population is the 11 library facts, of which 4 are grade B.

Reading a config file instead of following the symbol that reads it is the same
class of error as grepping a filename instead of the write call — named in
CLAUDE.md, and this is another instance.

**The cost column.** `llm_consumption_log.estimated_cost_usd` was not USD for
4,069 rows written before the 2026-08-03 guard. Repaired by
`scripts/fix_llm_consumption_cost_units.py`; these tests pin the arithmetic the
repair used so a future rate-card edit cannot silently change history.
"""
from __future__ import annotations

from scripts.lib import cio_corpus_index as corpus


# ── the grade is derived, and must stay single-sourced ────────────────────

def test_the_catalogued_works_derive_grade_d_rather_than_storing_one():
    entries = corpus.catalog_entries()
    assert len(entries) == 34
    assert {e["evidence_grade"] for e in entries} == {"D"}
    assert corpus.CATALOG_GRADE == "D"


def test_no_catalog_row_stores_its_own_grade(  ):
    """If a row ever carries a grade key, there are two sources of truth for the
    same fact and they can disagree. The derivation must stay the only one."""
    import json
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent.joinpath(*corpus.CATALOG_RELPATH)
    raw = json.loads(p.read_text(encoding="utf-8"))
    for s in raw.get("sources") or []:
        for key in ("grade", "evidence_grade", "source_grade"):
            assert key not in s, (
                f"{s.get('source_id')} stores {key!r}; grade is derived from "
                "CATALOG_GRADE and must not also be written into the file")


def test_grade_d_cannot_corpus_hit_and_that_is_the_point():
    assert corpus.CLOSING_GRADES == frozenset({"A", "B"})
    assert "D" in corpus.CONTEXT_ONLY_GRADES
    assert all(e["can_corpus_hit"] is False for e in corpus.catalog_entries())


def test_the_eligible_population_is_the_library_facts_not_the_catalogue():
    """The corrective fact: something IS eligible, just not the 34."""
    facts = corpus.library_facts()
    assert len(facts) == 11
    closing = [f for f in facts if f.get("evidence_grade") in corpus.CLOSING_GRADES]
    assert len(closing) >= 1, "no fact can close a gap — the corpus governs nothing"
    assert all(f.get("evidence_grade") in {"A", "B", "C", "D", "X"} for f in facts)


def test_a_contradicted_fact_is_graded_x_and_never_closes():
    facts = corpus.library_facts()
    assert any(f.get("evidence_grade") == "X" for f in facts), (
        "grade X exists so a refuted claim is recorded, not deleted")
    for f in facts:
        if f.get("evidence_grade") == "X":
            assert f.get("evidence_grade") not in corpus.CLOSING_GRADES


# ── the cost repair's arithmetic ──────────────────────────────────────────

def test_the_repair_uses_the_published_rate_card():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / "scripts" / "fix_llm_consumption_cost_units.py"
    spec = importlib.util.spec_from_file_location("fixcost", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    # Exactly the figures installed in CLAUDE.md / AGENTS.md on 2026-08-30.
    assert m.RATES["flash"] == {"hit": 0.007, "miss": 0.22, "out": 0.66}
    assert m.RATES["pro"] == {"hit": 0.022, "miss": 0.66, "out": 1.98}


def test_the_repair_nulls_unknown_rows_rather_than_zeroing_them():
    """Zero is a claim that the call was free. We do not know that."""
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "fix_llm_consumption_cost_units.py").read_text(encoding="utf-8")
    assert "SET estimated_cost_usd = NULL" in src
    assert "NULL, not zero" in src


def test_the_repair_preserves_every_original_before_touching_it():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "fix_llm_consumption_cost_units.py").read_text(encoding="utf-8")
    assert "legacy_cost_value" in src
    # The preserve step must come before both updates.
    assert src.index("legacy_cost_value") < src.index("SET estimated_cost_usd = ROUND")
    assert src.index("legacy_cost_value") < src.index("SET estimated_cost_usd = NULL")


def test_the_repair_never_touches_rows_that_already_have_a_basis():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "fix_llm_consumption_cost_units.py").read_text(encoding="utf-8")
    assert 'TARGET = "cost_basis IS NULL' in src
