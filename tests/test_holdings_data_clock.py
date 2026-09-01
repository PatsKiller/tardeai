"""holdings.json must carry a real data clock, not just a loader-run date.

Cause (2026-09-01): the Command Center read top-level `as_of` and showed
"PORTFOLIO STALE - as_of 3.4d". `as_of` is written by portfolio_loader as
`= today`: it records when the LOADER RAN. It read 2026-08-29 while the Schwab
rows carried 2026-08-31 and the moomoo/alpaca CASH rows carried 2026-08-03/04 --
older than 28 of 30 rows and newer than the other 2. One number, wrong in both
directions at once, describing nothing in the file.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
pl = pytest.importorskip("portfolio_loader")
pr = pytest.importorskip("portfolio_repricer")


@pytest.mark.parametrize("mod", [pl, pr], ids=["loader", "repricer"])
def test_data_as_of_is_the_oldest_contributing_row(mod):
    rows = [
        {"account": "schwab_taxable", "broker_position_as_of": "2026-08-31"},
        {"account": "schwab_roth", "broker_position_as_of": "2026-08-31"},
        {"account": "moomoo_taxable_live", "broker_position_as_of": "2026-08-03"},
    ]
    out = mod.compute_data_as_of(rows)
    assert out["data_as_of"] == "2026-08-03"
    assert out["data_as_of_account"] == "moomoo_taxable_live"


@pytest.mark.parametrize("mod", [pl, pr], ids=["loader", "repricer"])
def test_one_stale_cash_row_makes_the_block_stale(mod):
    """AGENTS.md 9.1: 'A 27-day-old $500 makes the block 27 days old.'

    28 fresh rows must not be able to hide a stale one -- that is the exact defect
    the banner had.
    """
    rows = [{"account": "schwab_taxable", "broker_position_as_of": "2026-08-31"} for _ in range(28)]
    rows.append({"account": "moomoo_taxable_live", "broker_position_as_of": "2026-08-03"})
    out = mod.compute_data_as_of(rows)
    assert out["data_as_of"] == "2026-08-03", "a fresh majority must not mask a stale row"
    assert out["data_as_of_account"] == "moomoo_taxable_live", "the culprit must be named"


@pytest.mark.parametrize("mod", [pl, pr], ids=["loader", "repricer"])
def test_falls_back_to_row_as_of_when_no_broker_stamp(mod):
    out = mod.compute_data_as_of([{"account": "a", "as_of": "2026-07-01"}])
    assert out["data_as_of"] == "2026-07-01"


@pytest.mark.parametrize("mod", [pl, pr], ids=["loader", "repricer"])
def test_no_rows_or_no_dates_yields_none_not_today(mod):
    """Absence must read as UNKNOWN, never as fresh. A missing clock that
    defaults to now is how a dead feed reports healthy."""
    assert mod.compute_data_as_of([])["data_as_of"] is None
    assert mod.compute_data_as_of([{"account": "a"}])["data_as_of"] is None
    assert mod.compute_data_as_of(None)["data_as_of"] is None


@pytest.mark.parametrize("mod", [pl, pr], ids=["loader", "repricer"])
def test_malformed_rows_do_not_raise(mod):
    out = mod.compute_data_as_of([None, "junk", {"account": "a", "as_of": "2026-08-05"}])
    assert out["data_as_of"] == "2026-08-05"


# ---------------------------------------------------------------------------
# GAP 1 -- the publication point. Writing the clock is not publishing it.
#
# compute_data_as_of was correct and tested above throughout the period the
# banner was wrong, because /api/v2/overview never emitted the field: the
# surface cannot read what the API does not send. #825 added the emission and
# validated it with `tsc` and a TypeScript test, neither of which can see the
# Python payload -- so deleting the two lines from overview() turned nothing
# red. These tests pin the emission itself.
#
# Asserted over the AST, not by grepping the source: a grep cannot tell code
# from a comment quoting it (AGENTS.md 7, detector shape), and the emission is
# accompanied by a comment naming both fields.
# ---------------------------------------------------------------------------
import ast


def _overview_return_dict() -> ast.Dict:
    path = Path(__file__).resolve().parents[1] / "scripts" / "api_v2.py"
    src = path.read_bytes()
    compile(src, str(path), "exec")   # compile(), never a bare ast.parse
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == "overview"]
    assert len(fns) == 1, f"expected exactly one overview(), found {len(fns)}"
    rets = [n for n in ast.walk(fns[0])
            if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    assert len(rets) == 1, f"expected one dict return in overview(), found {len(rets)}"
    return rets[0].value


def _string_keys(d: ast.Dict) -> dict:
    return {k.value: v for k, v in zip(d.keys, d.values)
            if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _reads_holdings_field(node: ast.AST, field: str) -> bool:
    """True for `h.get("<field>")`, with or without a trailing `or None`."""
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return any(_reads_holdings_field(v, field) for v in node.values)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "h"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == field
    )


@pytest.mark.parametrize("field", ["data_as_of", "data_as_of_account"])
def test_overview_publishes_the_data_clock(field):
    top = _string_keys(_overview_return_dict())
    assert field in top, (
        f"/api/v2/overview must emit {field}: the Command Center cannot render a "
        f"freshness the API never sends, which is why this was a two-sided defect"
    )


@pytest.mark.parametrize("field", ["data_as_of", "data_as_of_account"])
def test_overview_data_clock_reads_the_holdings_document(field):
    """Presence is not correctness.

    Emitting the key while reading another clock into it -- `h.get("as_of")`,
    the loader-run date -- reproduces the original defect behind a correct
    field name, and a presence-only assertion cannot see it.
    """
    top = _string_keys(_overview_return_dict())
    assert _reads_holdings_field(top[field], field), (
        f"{field} must be read from the holdings document as h.get({field!r}), "
        f"not recomputed, defaulted, or borrowed from another field"
    )


def test_overview_keeps_the_loader_clock_as_a_separate_field():
    """`as_of` is demoted, not deleted.

    It still means "the loader ran", and a consumer wanting provenance must
    still be able to read it -- but it must not be the same expression as the
    data clock, or the demotion is cosmetic.
    """
    top = _string_keys(_overview_return_dict())
    assert "as_of" in top, "as_of must remain published as loader provenance"
    assert not _reads_holdings_field(top["as_of"], "data_as_of"), (
        "as_of must not be sourced from data_as_of; the two clocks stay distinct"
    )
