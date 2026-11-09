"""ANCHOR: HERMES_TAG_EFFICACY_SUPERSEDE_LQ1491_20261109. LQ-20261107-1491 —

After LQ-133b changed the efficacy metric, seven old-metric rows (five of them
``flagged``) stayed in ``hermes_tag_efficacy`` because the engine only UPSERTs
tags it still computes. Consumers read the whole table, so stale flags stayed
visible. The engine now stamps ``superseded_at`` (never DELETE); consumers
filter ``superseded_at IS NULL``. Hermetic: fake cursor, no DB, no network.
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
            # rowcount = how many stale rows the WHERE would hit
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
        v = self._answer()
        return v if v is not None else (0,)


def _ledger_rows(tags):
    # tag, ledger_n, actioned_hits, directive_hits, outcome_n, wins
    return [(t, 100, 10, 80, 50, 20) for t in tags]


def _cfg():
    return {"efficacy": {"min_samples_per_tag": 15, "min_effect": 0.05, "alpha": 0.05}}


def test_absent_tags_are_listed_when_column_missing():
    """Before the first apply, superseded_at does not exist — every row is active."""
    cur = _Cur([
        ("information_schema.columns", [("tag",), ("flagged",), ("n",)]),
        ("FROM hermes_tag_efficacy",
         [(t, True) for t in STALE_FLAGGED] + [(t, False) for t in STALE_CLEAR]),
    ])
    absent = TE.list_absent_efficacy_tags(cur, CURRENT)
    assert {a["tag"] for a in absent} == set(STALE_FLAGGED + STALE_CLEAR)
    assert {a["tag"] for a in absent if a["flagged"]} == set(STALE_FLAGGED)


def test_already_superseded_rows_are_not_listed_again():
    cur = _Cur([
        ("information_schema.columns",
         [("tag",), ("flagged",), ("superseded_at",), ("superseded_reason",)]),
        ("FROM hermes_tag_efficacy", []),  # WHERE superseded_at IS NULL → empty
    ])
    assert TE.list_absent_efficacy_tags(cur, CURRENT) == []


def test_apply_supersedes_absent_tags_and_clears_flags():
    """Fail-before shape: without the UPDATE, stale flagged tags stay visible.
    Pass-after: apply stamps superseded_at, clears flagged, never DELETE."""
    cur = _Cur([
        ("unnest(hri.strategy_tags) tag, count(*)", _ledger_rows(CURRENT)),
        ("SELECT tag, count(*) trade_n", []),
        ("information_schema.columns",
         [("tag",), ("flagged",), ("superseded_at",), ("n",)]),
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
    # upserts clear a prior supersede when a tag returns
    ins = next(s for s in writes if s.startswith("INSERT INTO hermes_tag_efficacy"))
    compact = ins.replace(" ", "")
    assert "superseded_at=NULL" in compact or "NULL,NULL,NOW()" in compact


def test_dry_run_reports_would_supersede_without_writes():
    cur = _Cur([
        ("unnest(hri.strategy_tags) tag, count(*)", _ledger_rows(CURRENT)),
        ("SELECT tag, count(*) trade_n", []),
        ("information_schema.columns",
         [("tag",), ("flagged",), ("superseded_at",)]),
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
        ("information_schema.columns", [("tag",), ("flagged",), ("superseded_at",)]),
        ("FROM hermes_tag_efficacy", []),
    ])
    TE.tag_efficacy(cur, _cfg(), apply=True, dry_run=False)
    ddl = [s for s, _ in cur.log if s.startswith(("CREATE", "ALTER"))]
    assert len(ddl) == 3
    assert "superseded_at TIMESTAMPTZ" in ddl[2]
    assert "superseded_reason TEXT" in ddl[2]


def test_consumers_filter_superseded_at_is_null():
    """The four known readers must hide superseded rows (predicate in source)."""
    sources = {
        "hermes_outcome_feedback_agent.py": (ROOT / "scripts" / "hermes_outcome_feedback_agent.py").read_text(),
        "hermes_maturity_gates.py": (ROOT / "scripts" / "hermes_maturity_gates.py").read_text(),
        "momentum_scalp_validation_tracker.py": (
            ROOT / "scripts" / "momentum_scalp_validation_tracker.py").read_text(),
    }
    for name, src in sources.items():
        assert "FROM hermes_tag_efficacy" in src, name
        # every hermes_tag_efficacy SELECT carries the hide predicate
        assert src.count("FROM hermes_tag_efficacy") <= src.count("superseded_at IS NULL"), name
    assert TE.ACTIVE_EFFICACY_PREDICATE == "superseded_at IS NULL"


def test_engine_never_issues_delete_on_efficacy():
    src = (ROOT / "scripts" / "hermes_tag_engine.py").read_text()
    assert "DELETE FROM hermes_tag_efficacy" not in src
    assert "superseded_at" in src and "LQ-1491" in src
