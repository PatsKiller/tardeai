"""Reverse-factor `n` backfill — dry tests (Phase 5 §8).

Deterministic, no live DB / broker / LLM. Proves the backfill:
  * derives thesis_outcome + hermes_research `n` from their canonical source rows,
  * folds them through the single two_way_curation writers with the correct `n`,
  * is dry-runnable (counts without writing) and idempotent,
  * wires the options-edge universe fold.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib.cio_reverse_factor_backfill import (  # noqa: E402
    backfill,
    derive_hermes_research,
    derive_thesis_outcomes,
)


def _rows(seq):
    """Return RealDictCursor-shaped dict rows from (symbol, value) tuples."""
    return [{"symbol": s, "value": v} for s, v in seq]


class FakeExecutor:
    """Simulates db_adapter._execute for the backfill's read + write paths."""

    def __init__(self, thesis=None, hermes=None, options=None):
        self.thesis = thesis or []
        self.hermes = hermes or []
        self.options = options or []
        self.writes = []          # (sql_upper, params) for UPDATE/INSERT
        self.watchlist_rows = {}  # symbol -> {col: value}

    def __call__(self, sql, params=None, fetch=None):
        sql_u = sql.upper()

        if "FROM HERMES_OUTCOME_LEDGER" in sql_u and "SUBJECT_TYPE = 'TRADE'" in sql_u:
            return [dict(r) for r in self.thesis] if fetch == "all" else None
        if "FROM HERMES_OUTCOME_LEDGER" in sql_u and "SUBJECT_TYPE = 'RESEARCH_ROW'" in sql_u:
            return [dict(r) for r in self.hermes] if fetch == "all" else None
        if "OPTIONS_PAPER_OUTCOMES" in sql_u and "OPTIONS_APPROVAL_QUEUE" in sql_u and "OPTIONS_IV_HISTORY" in sql_u:
            return [{"symbol": s} for s in self.options] if fetch == "all" else None

        if "UPDATE WATCHLIST_ITEMS" in sql_u:
            self.writes.append((sql_u, params))
            return True
        if "INSERT INTO CURATION_LOOP_AUDIT" in sql_u:
            self.writes.append((sql_u, params))
            return True

        return None


# ── pure derivation ──────────────────────────────────────────────────────────

def test_derive_thesis_outcomes_latest_wins_and_counts_n():
    rows = [
        {"symbol": "NVDA", "verdict": "miss"},
        {"symbol": "NVDA", "verdict": "hit"},
        {"symbol": "XOM", "verdict": "neutral"},
    ]
    out = derive_thesis_outcomes(rows)
    assert out["NVDA"] == {"realized_outcome": "win", "thesis_win": True, "n": 2}
    assert out["XOM"] == {"realized_outcome": "scratch", "thesis_win": None, "n": 1}


def test_derive_thesis_outcomes_supports_tuple_rows():
    rows = [("AAPL", "hit"), ("AAPL", "hit")]
    out = derive_thesis_outcomes(rows)
    assert out["AAPL"]["n"] == 2
    assert out["AAPL"]["realized_outcome"] == "win"


def test_derive_thesis_outcomes_skips_blank_symbol_and_verdict():
    rows = [
        {"symbol": "", "verdict": "hit"},
        {"symbol": "NVDA", "verdict": None},
        {"symbol": "MSFT", "verdict": "ungradeable"},
    ]
    out = derive_thesis_outcomes(rows)
    # blank symbol skipped; None verdict skipped; ungradeable latest -> no writeback
    assert out == {}


def test_derive_hermes_research_latest_action_and_n():
    rows = [
        {"symbol": "NVDA", "actioned": "proposal"},
        {"symbol": "NVDA", "actioned": "trade"},
        {"symbol": "XOM", "actioned": "none"},
    ]
    out = derive_hermes_research(rows)
    assert out["NVDA"] == {"score": 90.0, "actioned": "trade", "n": 2}
    assert out["XOM"]["score"] == 15.0
    assert out["XOM"]["n"] == 1


def test_derive_hermes_research_skips_ungraded():
    rows = [
        {"symbol": "NVDA", "actioned": None},
        {"symbol": "XOM", "actioned": "mystery_action"},
    ]
    out = derive_hermes_research(rows)
    assert "NVDA" not in out  # None action -> no sample
    assert "XOM" not in out  # unknown action -> hermes_research_score_from_action is None


# ── orchestrator ─────────────────────────────────────────────────────────────

def test_backfill_dry_run_counts_without_writing():
    ex = FakeExecutor(
        thesis=[{"symbol": "NVDA", "verdict": "hit"}, {"symbol": "NVDA", "verdict": "miss"}],
        hermes=[{"symbol": "NVDA", "actioned": "trade"}],
        options=["NVDA", "XOM"],
    )
    summary = backfill(ex, dry_run=True)
    assert summary["dry_run"] is True
    assert summary["thesis_outcome"]["candidates"] == 1
    assert summary["thesis_outcome"]["written"] == 0
    assert summary["hermes_research"]["candidates"] == 1
    assert summary["hermes_research"]["written"] == 0
    assert summary["options_edge"]["candidates"] == 2
    assert ex.writes == []  # nothing written on dry-run


def test_backfill_apply_writes_thesis_and_hermes_n():
    ex = FakeExecutor(
        thesis=[{"symbol": "NVDA", "verdict": "hit"}, {"symbol": "NVDA", "verdict": "hit"}],
        hermes=[{"symbol": "NVDA", "actioned": "trade"}, {"symbol": "NVDA", "actioned": "trade"}],
    )
    summary = backfill(ex, dry_run=False, include_options=False)
    assert summary["thesis_outcome"]["written"] == 1
    assert summary["hermes_research"]["written"] == 1

    # thesis_outcome write carries n=2 (thesis_outcome_n)
    thesis_updates = [w for w in ex.writes if "THESIS_OUTCOME_N" in w[0]]
    assert thesis_updates, "expected a write_realized_outcome UPDATE"
    params = thesis_updates[0][1]
    # write_realized_outcome params: (realized_outcome, n, thesis_win, thesis_win, symbol)
    assert params[0] == "win"
    assert params[1] == 2
    assert params[4] == "NVDA"

    # hermes_research write carries n=2 (hermes_research_n)
    hermes_updates = [w for w in ex.writes if "HERMES_RESEARCH_N" in w[0]]
    assert hermes_updates, "expected a write_hermes_research UPDATE"
    hparams = hermes_updates[0][1]
    assert hparams[0] == 90.0
    assert hparams[1] == 2
    assert hparams[3] == "NVDA"


def test_backfill_apply_wires_options_fold(monkeypatch):
    ex = FakeExecutor(options=["NVDA", "XOM"])
    calls = {}

    def _fake_universe(*, executor=None, limit=500):
        calls["executor"] = executor
        calls["limit"] = limit
        return {"ok": True, "candidates": 2, "folded": 1, "skipped": 1, "errors": 0}

    monkeypatch.setattr(
        "scripts.lib.options_pipeline.validation.backfill_options_edge_universe",
        _fake_universe,
    )
    summary = backfill(ex, dry_run=False, include_options=True, limit=7)
    assert calls["executor"] is ex
    assert calls["limit"] == 7
    assert summary["options_edge"]["written"] == 1
    assert summary["options_edge"]["skipped"] == 1


def test_backfill_idempotent_derivation():
    rows = [{"symbol": "NVDA", "verdict": "hit"}, {"symbol": "NVDA", "verdict": "miss"}]
    a = derive_thesis_outcomes(rows)
    b = derive_thesis_outcomes(rows)
    assert a == b == {"NVDA": {"realized_outcome": "loss", "thesis_win": False, "n": 2}}
