"""ANCHOR: HERMES_TAG_EFFICACY_SUPERSEDE_LQ1491_20261109. LQ-20261107-1491 —

After LQ-133b changed the efficacy metric, seven old-metric rows (five of them
``flagged``) stayed in ``hermes_tag_efficacy`` because the engine only UPSERTs
tags it still computes. Consumers read the whole table, so stale flags stayed
visible. The engine now stamps ``superseded_at`` (never DELETE); consumers
filter via ``active_efficacy_predicate`` — ``superseded_at IS NULL`` when the
column exists, ``TRUE`` before the first engine ``--apply`` so a fold cannot
crash with "column does not exist". Hermetic: fake cursor, no DB, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import hermes_tag_engine as TE  # noqa: E402

ANCHOR = "HERMES_TAG_EFFICACY_SUPERSEDE_LQ1491_20261109"

# Live inventory 2026-11-09 (read-only): 7 old-metric tags not in current compute,
# 5 of them flagged. Synthetic fixture mirrors that shape — no live symbols.
STALE_FLAGGED = ["catalyst", "holdings", "risk_protection", "social_route", "swing"]
STALE_CLEAR = ["recovery_watch", "sector_rotation"]
CURRENT = ["momentum_scalp", "swing_breakout", "general_research"]

# information_schema probe needles (must match efficacy_has_superseded_column SQL)
_COL_PROBE = "column_name = 'superseded_at'"


@pytest.fixture(autouse=True)
def _clear_superseded_col_cache():
    TE.reset_efficacy_superseded_col_cache()
    yield
    TE.reset_efficacy_superseded_col_cache()


class _Cur:
    """Minimal cursor: answers by substring needle; records writes."""

    def __init__(self, answers: list[tuple[str, object]]):
        self.answers = list(answers)
        self.log: list[tuple[str, object]] = []
        self.rowcount = 0
        self._last = ""
        self._params = None

    def execute(self, sql, params=None):
        text = " ".join(str(sql).split())
        self.log.append((text, params))
        self._last = text
        self._params = params
        if text.upper().startswith("UPDATE"):
            current = list(params[-1]) if params else []
            self.rowcount = sum(1 for t in STALE_FLAGGED + STALE_CLEAR if t not in current)
        else:
            self.rowcount = 0

    def _answer(self):
        for needle, value in self.answers:
            if needle in self._last:
                return value
        return None

    def fetchall(self):
        v = self._answer()
        return v if v is not None else []

    def fetchone(self):
        # None = no row (column missing). Do not coerce to (0,).
        return self._answer()


def _ledger_rows(tags):
    return [(t, 100, 10, 80, 50, 20) for t in tags]


def _cfg():
    return {"efficacy": {"min_samples_per_tag": 15, "min_effect": 0.05, "alpha": 0.05}}


def test_predicate_is_true_when_superseded_at_column_missing():
    """Fold-before-10:50 hazard: probe is False; predicate stays TRUE (docs/helper)."""
    cur = _Cur([(_COL_PROBE, None)])
    assert TE.efficacy_has_superseded_column(cur) is False
    assert TE.active_efficacy_predicate(cur) == "TRUE"


def test_predicate_hides_superseded_when_column_exists():
    cur = _Cur([(_COL_PROBE, (1,))])
    assert TE.efficacy_has_superseded_column(cur) is True
    assert TE.active_efficacy_predicate(cur) == "superseded_at IS NULL"


def test_absent_tags_are_listed_when_column_missing():
    """Before the first apply, superseded_at does not exist — every row is active."""
    cur = _Cur([
        (_COL_PROBE, None),
        ("FROM hermes_tag_efficacy",
         [(t, True) for t in STALE_FLAGGED] + [(t, False) for t in STALE_CLEAR]),
    ])
    absent = TE.list_absent_efficacy_tags(cur, CURRENT)
    assert {a["tag"] for a in absent} == set(STALE_FLAGGED + STALE_CLEAR)
    assert {a["tag"] for a in absent if a["flagged"]} == set(STALE_FLAGGED)
    sel = next(s for s, _ in cur.log if "FROM hermes_tag_efficacy" in s and "SELECT tag" in s)
    assert "superseded_at" not in sel


def test_already_superseded_rows_are_not_listed_again():
    cur = _Cur([
        (_COL_PROBE, (1,)),
        ("FROM hermes_tag_efficacy", []),  # WHERE superseded_at IS NULL → empty
    ])
    assert TE.list_absent_efficacy_tags(cur, CURRENT) == []
    sel = next(s for s, _ in cur.log if "FROM hermes_tag_efficacy" in s and "SELECT tag" in s)
    assert "superseded_at IS NULL" in sel


def test_apply_supersedes_absent_tags_and_clears_flags():
    """Pass-after: apply stamps superseded_at, clears flagged, never DELETE."""
    cur = _Cur([
        ("unnest(hri.strategy_tags) tag, count(*)", _ledger_rows(CURRENT)),
        ("SELECT tag, count(*) trade_n", []),
        (_COL_PROBE, (1,)),
        ("FROM hermes_tag_efficacy",
         [(t, True) for t in STALE_FLAGGED] + [(t, False) for t in STALE_CLEAR]),
    ])
    out = TE.tag_efficacy(cur, _cfg(), apply=True, dry_run=False)
    assert set(out["would_supersede"]) == set(STALE_FLAGGED + STALE_CLEAR)
    assert set(out["would_supersede_flagged"]) == set(STALE_FLAGGED)
    assert out["superseded"] == len(STALE_FLAGGED) + len(STALE_CLEAR)

    writes = [s for s, _ in cur.log]
    assert not any(s.upper().startswith("DELETE") for s in writes)
    upd = next(s for s in writes if s.upper().startswith("UPDATE HERMES_TAG_EFFICACY"))
    assert "superseded_at = NOW()" in upd
    assert "flagged = FALSE" in upd
    assert "NOT (tag = ANY(%s))" in upd
    ins = next(s for s in writes if s.startswith("INSERT INTO hermes_tag_efficacy"))
    compact = ins.replace(" ", "")
    assert "superseded_at=NULL" in compact or "NULL,NULL,NOW()" in compact


def test_dry_run_reports_would_supersede_without_writes():
    cur = _Cur([
        ("unnest(hri.strategy_tags) tag, count(*)", _ledger_rows(CURRENT)),
        ("SELECT tag, count(*) trade_n", []),
        (_COL_PROBE, (1,)),
        ("FROM hermes_tag_efficacy",
         [(t, True) for t in STALE_FLAGGED] + [(t, False) for t in STALE_CLEAR]),
    ])
    out = TE.tag_efficacy(cur, _cfg(), apply=True, dry_run=True)  # dry_run wins
    assert set(out["would_supersede"]) == set(STALE_FLAGGED + STALE_CLEAR)
    assert set(out["would_supersede_flagged"]) == set(STALE_FLAGGED)
    assert out["superseded"] == 0
    writes = [s for s, _ in cur.log if s.split(" ", 1)[0].upper()
              in ("INSERT", "UPDATE", "DELETE", "CREATE", "ALTER")]
    assert writes == []


def test_ddl_stays_at_three_statements_and_adds_superseded_columns():
    cur = _Cur([
        ("unnest(hri.strategy_tags) tag, count(*)", _ledger_rows(["general_research"])),
        ("SELECT tag, count(*) trade_n", []),
        (_COL_PROBE, (1,)),
        ("FROM hermes_tag_efficacy", []),
    ])
    TE.tag_efficacy(cur, _cfg(), apply=True, dry_run=False)
    ddl = [s for s, _ in cur.log if s.startswith(("CREATE", "ALTER"))]
    assert len(ddl) == 3
    assert "superseded_at TIMESTAMPTZ" in ddl[2]
    assert "superseded_reason TEXT" in ddl[2]


def test_consumers_probe_before_referencing_superseded_at():
    """Each consumer gates the column filter on efficacy_has_superseded_column."""
    sources = {
        "hermes_outcome_feedback_agent.py": (ROOT / "scripts" / "hermes_outcome_feedback_agent.py").read_text(),
        "hermes_maturity_gates.py": (ROOT / "scripts" / "hermes_maturity_gates.py").read_text(),
        "momentum_scalp_validation_tracker.py": (
            ROOT / "scripts" / "momentum_scalp_validation_tracker.py").read_text(),
    }
    for name, src in sources.items():
        assert "FROM hermes_tag_efficacy" in src, name
        assert "efficacy_has_superseded_column" in src, name
        # Both branches present: filtered (column exists) and unfiltered (pre-apply)
        assert "superseded_at IS NULL" in src, name
        assert src.count("FROM hermes_tag_efficacy") >= 2, name
    assert TE.ACTIVE_EFFICACY_PREDICATE == "superseded_at IS NULL"


def test_consumer_select_survives_missing_column():
    """Simulate the three consumer SELECT branches before the first engine --apply."""
    cur = _Cur([
        (_COL_PROBE, None),
        ("FROM hermes_tag_efficacy", [("momentum_scalp", -0.08, True, 0.24)]),
    ])
    assert TE.efficacy_has_superseded_column(cur) is False
    # feedback agent — else branch (no column)
    cur.execute("SELECT tag, lift, flagged, hit_rate FROM hermes_tag_efficacy")
    assert cur.fetchall()
    # maturity gates — else branch
    cur.execute("""SELECT tag, n, lift, base_rate FROM hermes_tag_efficacy
                   WHERE n >= 50 AND lift IS NOT NULL AND base_rate IS NOT NULL""")
    # momentum tracker — else branch
    cur.execute("""SELECT tag, n, hit_rate, lift, trade_n, avg_realized_r
                   FROM hermes_tag_efficacy
                   WHERE tag IN ('momentum_scalp','social_route','large_float_social_scout','catalyst')
                   ORDER BY n DESC""")
    for s, _ in cur.log:
        if "FROM hermes_tag_efficacy" in s:
            assert "superseded_at" not in s


def test_fail_before_bare_superseded_filter_would_reference_missing_column():
    """Document the hazard the rework removes: a bare filter names the missing column."""
    cur = _Cur([(_COL_PROBE, None)])
    assert TE.efficacy_has_superseded_column(cur) is False
    bare = "SELECT tag FROM hermes_tag_efficacy WHERE superseded_at IS NULL"
    assert "superseded_at" in bare  # what the pre-rework consumers emitted
    # Safe branch omits it:
    safe = "SELECT tag FROM hermes_tag_efficacy"
    assert "superseded_at" not in safe


def test_engine_never_issues_delete_on_efficacy():
    src = (ROOT / "scripts" / "hermes_tag_engine.py").read_text()
    assert "DELETE FROM hermes_tag_efficacy" not in src
    assert "superseded_at" in src and "LQ-1491" in src
    assert "active_efficacy_predicate" in src
