"""The plausibility contracts must be well-formed and their SQL must be correct.

These are pure checks -- no database. They guard the two ways this monitor could
quietly stop protecting anything: a contract file that drifts out of shape, and a
predicate that silently matches nothing.

The monitor exists because `analyst_consensus_history.recom_score` held ten-year
return percentages on a column declared 1-5 for five months, and the derived
labels were anti-correlated with reality. The scale lived only in a docstring, so
nothing could check it. These tests keep the declaration honest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import data_plausibility_monitor as dpm  # noqa: E402

CONTRACTS = json.loads((ROOT / "config" / "data_plausibility_contracts.json").read_text())["contracts"]

VALID_RULES = {"range", "min", "max", "finite", "single_scale", "required_fields"}
# Rules that are a property of the population, not of any one row: they have no
# per-row predicate. single_scale since 09-13 a.m.; required_fields since 09-13
# p.m. (analyst_data_history: 18,772 `{}` payloads that looked fresh).
POPULATION_RULES = {"single_scale", "required_fields"}
VALID_SEVERITIES = {"BLOCK", "WARN"}


def test_contracts_file_is_non_empty():
    assert CONTRACTS, "no contracts declared: the monitor would check nothing"


@pytest.mark.parametrize("c", CONTRACTS, ids=lambda c: f"{c['table']}.{c['column']}")
def test_contract_is_well_formed(c):
    assert c["rule"] in VALID_RULES, f"unknown rule {c['rule']!r}"
    assert c["severity"] in VALID_SEVERITIES
    assert c.get("_why"), (
        "every contract states why this scale is the right one. A bound nobody "
        "can justify is how a wrong contract outlives a real defect."
    )
    if c["rule"] == "range":
        assert c["min"] < c["max"]
    if c["rule"] == "required_fields":
        assert c.get("window_column"), "required_fields is measured inside a window; name the timestamp column"
        assert 0 <= float(c.get("max_empty_pct", -1)) < 100, "max_empty_pct is a share of rows, 0..100"
        assert int(c.get("window_days", 0)) > 0


def test_every_contract_has_a_distinct_target():
    seen = [(c["table"], c["column"]) for c in CONTRACTS]
    assert len(seen) == len(set(seen)), f"duplicate contract targets: {seen}"


def test_the_recom_score_contract_is_the_one_that_would_have_caught_it():
    c = next(c for c in CONTRACTS if c["table"] == "analyst_consensus_history" and c["column"] == "recom_score")
    assert (c["min"], c["max"]) == (1.0, 5.0)
    assert c["severity"] == "BLOCK"


# ── predicate correctness ────────────────────────────────────────────────────


def test_range_predicate_excludes_nulls_and_catches_both_tails():
    sql = dpm._violation_predicate({"column": "recom_score", "rule": "range", "min": 1.0, "max": 5.0})
    assert "IS NOT NULL" in sql, (
        "NULL must never count as a violation: absent data and wrong data are "
        "different problems, and conflating them is how 'no rating' became "
        "'Strong Buy'."
    )
    assert "BETWEEN 1.0 AND 5.0" in sql
    assert sql.strip().startswith('"recom_score"')


def test_min_predicate_catches_a_negative_stop_price():
    sql = dpm._violation_predicate({"column": "stop_price", "rule": "min", "min": 0.0})
    assert '"stop_price" < 0.0' in sql


def test_finite_predicate_matches_nan_by_text_not_by_comparison():
    """NaN != NaN in SQL, so a range check silently passes it through."""
    sql = dpm._violation_predicate({"column": "ytd_return_pct", "rule": "finite"})
    assert "::text IN" in sql
    for token in ("'NaN'", "'nan'", "'Infinity'", "'-Infinity'"):
        assert token in sql


def test_single_scale_has_no_per_row_predicate():
    """It is a property of the population, not of any one row."""
    assert dpm._violation_predicate({"column": "confidence", "rule": "single_scale"}) == ""


def test_unknown_rule_raises_rather_than_matching_nothing():
    with pytest.raises(ValueError):
        dpm._violation_predicate({"column": "x", "rule": "not_a_rule"})


def test_column_names_are_quoted_so_a_reserved_word_cannot_break_the_sql():
    for c in CONTRACTS:
        if c["rule"] in POPULATION_RULES:
            # no per-row predicate; the population query quotes the column itself
            if c["rule"] == "required_fields":
                assert f'"{c["column"]}"' in dpm._required_fields_sql(c)
            continue
        assert f'"{c["column"]}"' in dpm._violation_predicate(c)


def test_the_module_imports_without_a_database_driver():
    """No top-level `import psycopg2`, or CI cannot even collect these tests.

    The rules here are pure and testable without a database. A module-level
    driver import made every test in this file uncollectable on any runner
    without psycopg2 -- the file errored at import and cio-hardening went red
    without running a single assertion, while passing locally because the venv
    has the driver.
    """
    import ast

    src = (ROOT / "scripts" / "data_plausibility_monitor.py").read_text()
    top_level = []
    for node in ast.parse(src).body:
        if isinstance(node, ast.Import):
            top_level += [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.append(node.module.split(".")[0])

    for driver in ("psycopg2", "psycopg", "sqlalchemy"):
        assert driver not in top_level, (
            f"{driver} is imported at module level; import it inside the function "
            "that connects, so the pure rules stay testable without a database."
        )
