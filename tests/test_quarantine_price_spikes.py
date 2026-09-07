"""Impossible prices must go — but "impossible" needs evidence, not a shape.

A previous one-sided detector "ate good data". This file exists to keep that from
recurring, and it very nearly did: the first version of this script reported
CONTRADICTED=82 / SUSPECT=1 and would have deleted 82 rows on a comparison that was
meaningless. Keyed correctly the numbers invert to CONTRADICTED=0 / SUSPECT=89.

THREE THINGS A BIG JUMP CAN BE
    split       NXTT 0.0616 -> 6.42 on 2026-08-12, then 5.88-7.95 all week. The level
                SHIFTED and stayed. Real. Deleting it destroys history.
    real spike  AKAN 5.33 -> 10.52 -> back. An ordinary micro-cap pump. Also real, and
                it has exactly the same SHAPE as corruption.
    corrupt     NOC 528.37 -> 119.32 in one day while watchlist_items.change_pct,
                written by a different pipeline THAT DAY, said -2.44%.

Only the third is decidable, and only because a second source disagreed on the SAME
DATE. Measured: ticker_prices holds exactly one source per symbol+date — zero pairs
have more than one — so shape is all that is left for everything else, and shape is a
hypothesis.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCRIPT = ROOT / "scripts" / "quarantine_price_spikes.py"


@pytest.fixture(scope="module")
def mod():
    return pytest.importorskip("quarantine_price_spikes")


# ── a split is not corruption ───────────────────────────────────────────────

def test_a_persistent_level_shift_is_kept(mod):
    """NXTT: 0.0616 -> 6.42, and it STAYS at 6.15 the next day."""
    v, _ = mod.verdict(close=6.42, prev=0.0616, nxt=6.15, independent=None)
    assert v == "SPLIT_LIKE"


def test_a_reverting_spike_without_a_second_source_is_only_SUSPECT(mod):
    """The whole point. AKAN 5.33 -> 10.52 -> back is a real micro-cap move and has
    the same shape as corruption. Reported, never deleted."""
    v, _ = mod.verdict(close=10.52, prev=5.33, nxt=6.34, independent=None)
    assert v == "SUSPECT"


def test_only_a_contradicting_second_source_convicts(mod):
    """NOC: the series says -77%, the other pipeline says -2.44% that same day."""
    v, _ = mod.verdict(close=119.32, prev=528.37, nxt=525.0, independent=2.44)
    assert v == "CONTRADICTED"


def test_a_second_source_that_AGREES_exonerates(mod):
    """A real 60% move confirmed by another pipeline is not corruption."""
    v, _ = mod.verdict(close=8.0, prev=5.0, nxt=5.2, independent=60.0)
    assert v == "SPLIT_LIKE"


def test_a_row_with_no_following_close_is_undecidable(mod):
    """It may be the newest bar of a real move. Re-examined tomorrow."""
    v, back = mod.verdict(close=99.0, prev=10.0, nxt=None, independent=None)
    assert v == "UNDECIDABLE" and back is None


# ── the bug that would have deleted 82 real rows ────────────────────────────

def test_corroboration_is_keyed_on_symbol_AND_date(mod):
    """watchlist_items.change_pct is a point-in-time SNAPSHOT, not a series. Keying on
    symbol alone compares a July price move against a September percentage — two
    unrelated numbers that share a ticker. That returned CONTRADICTED=82; keyed
    correctly it is 0."""
    class C:
        def execute(self, sql, params=None):
            assert "last_enriched_at" in sql, "the as-of date is not being read"
            self._r = [("NOC", dt.date(2026, 9, 4), 2.44)]
        def fetchall(self): return self._r

    out = mod.independent_moves(C(), ["NOC"])
    assert out == {("NOC", dt.date(2026, 9, 4)): 2.44}
    assert "NOC" not in out, "keyed on symbol alone — the defect is back"


def test_a_snapshot_only_corroborates_its_own_day(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert "independent.get((str(sym).upper(), pdate))" in src


# ── nothing is destroyed without a copy ─────────────────────────────────────

def test_the_row_is_archived_before_it_is_deleted(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    insert_at = src.index("INSERT INTO ticker_prices_quarantine")
    delete_at = src.index("DELETE FROM ticker_prices WHERE id")
    assert insert_at < delete_at, "it deletes before archiving"


def test_only_contradicted_rows_are_deleted(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    body = src.split("if args.apply and corrupt:", 1)[1]
    assert "suspect" not in body.split("conn.commit()", 1)[0], (
        "suspect rows reach the delete path")


def test_suspect_rows_are_reported_not_hidden(mod):
    """89 rows we cannot convict must still be visible — that is the whole value."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "are NOT deleted" in src
    assert '"SUSPECT"' in src


def test_a_dry_run_reports_unmeasured_not_zero(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"rows_produced": written if args.apply else None' in src


def test_the_scan_is_single_pass(mod):
    """An iterative scrub re-baselines on its own output and walks down a real trend.
    One SELECT, one verdict per row, no loop over passes."""
    import ast

    src = SCRIPT.read_text(encoding="utf-8")
    assert src.count("cur.execute(CANDIDATES") == 1
    # AST, not text: the module docstring contains the word "while" in prose
    # ("...-77% while the other pipeline said -2.44%"), and a substring search calls
    # that a loop.
    tree = ast.parse(src)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.While)], (
        "a while-loop means the scan can re-baseline on its own output")


def test_it_is_free_and_advisory(mod):
    assert mod.AUTHORITY == "READ_ONLY_ADVISORY"
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"model_calls": 0' in src
    for banned in ("llm", "deepseek", "openai"):
        assert banned not in src.lower()
