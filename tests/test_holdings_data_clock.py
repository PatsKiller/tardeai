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
