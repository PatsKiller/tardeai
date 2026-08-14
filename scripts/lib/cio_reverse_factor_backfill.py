"""Reverse-factor `n` backfill — Phase 5 §8 (one-shot reliability-gate sample sizes).

The reliability gate is only as good as the `<factor>_n` writers produce. Existing
`watchlist_items` rows predate the `n` persistence, so they carry `<factor>_n = NULL`
and the scorer damps every reverse factor to zero. This module recomputes the three
sample sizes from their canonical source tables and folds them back through the
single two_way_curation writers (audit-trailed, advisory-only, idempotent).

Factors and canonical sources:
  thesis_outcome_n  <- hermes_outcome_ledger  subject_type='trade'        (realized)
  hermes_research_n <- hermes_outcome_ledger  subject_type='research_row' (proxy)
  options_edge_n    <- options_paper_outcomes (closed=realized) /
                       options_approval_queue + options_iv_history (proxy)

SAFETY INVARIANTS:
  * every write goes through the two_way_curation writers (write_realized_outcome /
    write_hermes_research / fold_options_to_underlying) — no direct DML here, so the
    overwrite-vs-COALESCE semantics and audit trail stay single-sourced.
  * every step takes an injectable `executor`, so it is dry-testable in memory with
    no live DB / broker / LLM.
  * advisory only — no execution, no strategy-status flip, no broker/order/2FA.
  * idempotent — re-running recomputes the same `n` from the same source rows.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from scripts.lib.two_way_curation import (
    hermes_research_score_from_action,
    outcome_verdict_to_ledger,
    write_hermes_research,
    write_realized_outcome,
)

Executor = Callable[..., Any]

# The three sample-size columns the scorer reliability-gates (hermes_watchlist_scorer.py).
REVERSE_FACTOR_N_COLS = ("thesis_outcome_n", "options_edge_n", "hermes_research_n")

# Graded trade outcomes -> thesis_outcome (realized). Latest graded verdict wins;
# n = count of graded outcomes backing that symbol.
THESIS_OUTCOME_SQL = """
SELECT UPPER(l.symbol) AS symbol, l.verdict, l.graded_at
FROM hermes_outcome_ledger l
WHERE l.subject_type = 'trade' AND l.verdict IN ('hit','miss','neutral')
  AND l.symbol IS NOT NULL
ORDER BY l.symbol, l.graded_at NULLS LAST
"""

# Graded research rows -> hermes_research (proxy). Latest action wins; n = count.
HERMES_RESEARCH_SQL = """
SELECT UPPER(l.symbol) AS symbol, l.actioned, l.graded_at
FROM hermes_outcome_ledger l
WHERE l.subject_type = 'research_row' AND l.actioned IS NOT NULL
  AND l.symbol IS NOT NULL
ORDER BY l.symbol, l.graded_at NULLS LAST
"""

# Candidate underlyings with any options evidence, restricted to live watch rows.
# Mirror of lib.options_pipeline.validation.backfill_options_edge_universe.
OPTIONS_CANDIDATE_SQL = """
SELECT symbol FROM (
  SELECT DISTINCT UPPER(symbol) AS symbol FROM options_paper_outcomes WHERE symbol IS NOT NULL
  UNION
  SELECT DISTINCT UPPER(symbol) FROM options_approval_queue
    WHERE symbol IS NOT NULL AND edge_score IS NOT NULL
  UNION
  SELECT DISTINCT UPPER(symbol) FROM options_iv_history WHERE symbol IS NOT NULL
) u
WHERE symbol IN (SELECT UPPER(symbol) FROM watchlist_items WHERE status IN ('active','researched'))
ORDER BY 1
"""


def _as_symbol(v: Any) -> Optional[str]:
    s = str(v or "").strip().upper()
    return s or None


def _rows_as(sym_key: str, val_key: str):
    """Return a normalizer that pulls (symbol, value) from dict rows or tuples."""
    def norm(row: Any):
        if isinstance(row, dict):
            return _as_symbol(row.get(sym_key)), row.get(val_key)
        return _as_symbol(row[0]), row[1]
    return norm


def derive_thesis_outcomes(rows: List[Any]) -> Dict[str, Dict[str, Any]]:
    """Aggregate graded trade-outcome rows into per-symbol write directives.

    rows: iterable of (symbol, verdict) in graded_at order. Latest graded verdict
    wins (matches hermes_outcome_grader.writeback_trade_outcomes); ``n`` is the
    count of graded outcomes backing that symbol.
    """
    norm = _rows_as("symbol", "verdict")
    by_sym: Dict[str, List[str]] = {}
    for r in rows or []:
        symbol, verdict = norm(r)
        if not symbol:
            continue
        v = str(verdict or "").strip().lower()
        if not v:
            continue
        by_sym.setdefault(symbol, []).append(v)

    out: Dict[str, Dict[str, Any]] = {}
    for symbol, verdicts in by_sym.items():
        realized, thesis = outcome_verdict_to_ledger(verdicts[-1])
        if realized is None and thesis is None:
            continue  # ungradeable/unknown latest verdict — nothing to write
        out[symbol] = {
            "realized_outcome": realized,
            "thesis_win": thesis,
            "n": len(verdicts),
        }
    return out


def derive_hermes_research(rows: List[Any]) -> Dict[str, Dict[str, Any]]:
    """Aggregate graded research-row outcomes into per-symbol write directives.

    rows: iterable of (symbol, actioned) in graded_at order. Latest action wins;
    ``n`` is the count of graded research rows backing that symbol.
    """
    norm = _rows_as("symbol", "actioned")
    by_sym: Dict[str, List[str]] = {}
    for r in rows or []:
        symbol, action = norm(r)
        if not symbol or action is None:
            continue
        by_sym.setdefault(symbol, []).append(str(action).strip().lower())

    out: Dict[str, Dict[str, Any]] = {}
    for symbol, actions in by_sym.items():
        score = hermes_research_score_from_action(actions[-1])
        if score is None:
            continue
        out[symbol] = {
            "score": score,
            "actioned": actions[-1],
            "n": len(actions),
        }
    return out


def _default_executor() -> Executor:
    from db_adapter import _execute
    return _execute


def backfill(
    executor: Optional[Executor] = None,
    *,
    dry_run: bool = False,
    limit: Optional[int] = None,
    include_options: bool = True,
) -> Dict[str, Any]:
    """Recompute + fold all three reverse-factor sample sizes.

    Returns a summary dict. With ``dry_run=True`` nothing is written; the summary
    reports exactly what *would* be folded so an operator can inspect before apply.
    """
    ex = executor or _default_executor()
    summary: Dict[str, Any] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "thesis_outcome": {"candidates": 0, "written": 0},
        "hermes_research": {"candidates": 0, "written": 0},
        "options_edge": {"candidates": 0, "written": 0, "skipped": 0, "errors": 0},
    }

    # 1) thesis_outcome — graded realized/paper trade outcomes
    thesis = derive_thesis_outcomes(ex(THESIS_OUTCOME_SQL, fetch="all") or [])
    summary["thesis_outcome"]["candidates"] = len(thesis)
    if not dry_run:
        for symbol, d in thesis.items():
            res = write_realized_outcome(
                symbol, d["realized_outcome"], d["thesis_win"],
                executor=ex, n=d["n"],
            )
            if res.get("ok"):
                summary["thesis_outcome"]["written"] += 1

    # 2) hermes_research — graded research rows
    hermes = derive_hermes_research(ex(HERMES_RESEARCH_SQL, fetch="all") or [])
    summary["hermes_research"]["candidates"] = len(hermes)
    if not dry_run:
        for symbol, d in hermes.items():
            res = write_hermes_research(
                symbol, d["score"],
                detail={"actioned": d["actioned"], "source": "reverse_factor_backfill"},
                executor=ex, n=d["n"],
            )
            if res.get("ok"):
                summary["hermes_research"]["written"] += 1

    # 3) options_edge — closed outcomes (realized) / queue + IV (proxy)
    if include_options:
        candidates = ex(OPTIONS_CANDIDATE_SQL, fetch="all") or []
        summary["options_edge"]["candidates"] = len(candidates)
        if not dry_run and candidates:
            from scripts.lib.options_pipeline.validation import backfill_options_edge_universe
            opts = backfill_options_edge_universe(executor=ex, limit=limit or 500)
            summary["options_edge"]["written"] = opts.get("folded", 0)
            summary["options_edge"]["skipped"] = opts.get("skipped", 0)
            summary["options_edge"]["errors"] = opts.get("errors", 0)

    summary["ok"] = True
    return summary
