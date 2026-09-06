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


@pytest.fixture(scope="module")
def mod():
    return pytest.importorskip("material_change_detector")


class Cur:
    """Returns canned rows for the price query."""

    def __init__(self, rows):
        self._rows = rows
        self._result = []

    def execute(self, sql, params=None):
        self._result = self._rows if "ticker_prices" in sql else []

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
    found, stats = mod.price_excursions(Cur(rows), {"BHVN": "watchlist"})
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
    found, stats = mod.price_excursions(Cur(rows), {"AOUT": "watchlist"})
    assert len(found) == 1
    assert found[0]["magnitude"] == pytest.approx(14.93, abs=0.01)
    assert stats["fired"] == 1


def test_a_quiet_name_does_not_fire(mod):
    rows = [("AAPL", 66, 1.25, 0.9, "2026-09-04")]
    found, _ = mod.price_excursions(Cur(rows), {"AAPL": "watchlist"})
    assert found == []


# ── the threshold is relative, not absolute ────────────────────────────────

def test_the_same_percent_move_fires_for_one_name_and_not_another(mod):
    """The whole reason for normalising. 8% is noise in one name and an event in
    another, and a fixed percent cannot express that."""
    calm = mod.price_excursions(Cur([("CALM", 60, 0.8, 8.0, "2026-09-04")]),
                                {"CALM": "watchlist"})[0]
    wild = mod.price_excursions(Cur([("WILD", 60, 9.0, 8.0, "2026-09-04")]),
                                {"WILD": "watchlist"})[0]
    assert len(calm) == 1, "8% on a 0.8% baseline is a ten-sigma move and must fire"
    assert wild == [], "8% on a 9% baseline is an ordinary day and must not"


def test_k_is_configurable_without_a_deploy(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'os.getenv("MATERIAL_CHANGE_K"' in src


# ── it reports what it could not see ───────────────────────────────────────

def test_too_little_history_is_counted_not_silently_dropped(mod):
    rows = [("NEWCO", 4, 2.0, 30.0, "2026-09-04")]
    found, stats = mod.price_excursions(Cur(rows), {"NEWCO": "watchlist"})
    assert found == []
    assert stats["not_evaluable"] == 1
    assert stats["evaluated"] == 0


def test_a_zero_baseline_is_not_evaluable_rather_than_infinite(mod):
    """Dividing by a zero baseline yields inf, which beats every threshold and
    would fire on a symbol that has never moved at all."""
    rows = [("FLAT", 60, 0.0, 5.0, "2026-09-04")]
    found, stats = mod.price_excursions(Cur(rows), {"FLAT": "watchlist"})
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
            self._result = [("AAPL",)] if "watchlist_items" in sql else []

    out = mod.universe(C([]))
    assert out == {"AAPL": "watchlist"}
    assert "WARN" in capsys.readouterr().err


def test_a_held_name_is_tracked_even_if_not_on_the_watchlist(mod, monkeypatch, tmp_path):
    h = tmp_path / "holdings.json"
    h.write_text(json.dumps({"holdings": [{"symbol": "schd"}]}), encoding="utf-8")
    monkeypatch.setattr(mod, "HOLDINGS", h)

    class C(Cur):
        def execute(self, sql, params=None):
            self._result = [("AAPL",)] if "watchlist_items" in sql else []

    out = mod.universe(C([]))
    assert out["SCHD"] == "held", "held names must be tracked and normalised to upper"
    assert out["AAPL"] == "watchlist"


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
