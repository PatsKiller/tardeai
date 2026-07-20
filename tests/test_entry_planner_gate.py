#!/usr/bin/env python3
"""Entry-planner candidate selection — the label must not decide who gets analysed.

Priority 2 used to select ONLY buy-side-rated names, which made the
recommendation label a ROUTING decision: a symbol labelled IGNORE could never
receive an entry plan, the card then showed "no entry plan", and that absence
read as more evidence against the symbol. The label produced the gap and the gap
corroborated the label.

These tests assert the loop stays broken open. There were NO planner tests before
2026-07-20, which is how the gate survived unexamined.

Pure: the SQL is inspected as text, so no database, no LLM, no network.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

SRC = (ROOT / "scripts" / "watchlist_entry_planner.py").read_text()

import watchlist_entry_planner as wep  # noqa: E402


def _priority2_sql() -> str:
    """The Priority-2 candidate query, as source text."""
    start = SRC.index("PRIORITY 2")
    end = SRC.index("return rows", start)
    return SRC[start:end]


# ── the gate is gone ──────────────────────────────────────────────────────────

def test_priority2_admits_names_on_evidence_not_only_on_verdict():
    sql = _priority2_sql()
    for signal in ("operator_starred_symbols", "change_pct", "catalyst_events", "scope_tier"):
        assert signal in sql, f"Priority 2 lost the {signal!r} signal — the label is the gate again"


def test_buy_side_conviction_still_qualifies():
    """Widening must not drop the original guarantee (operator 2026-07-01:
    'no info should be missing on strong buy, buy, or wait')."""
    sql = _priority2_sql()
    assert "'BUY','STRONG_BUY','ADD','ADD_ON_PULLBACK'" in sql
    assert "watchlist_research_cards" in sql and "watchlist_final_synthesis" in sql


def test_no_avoid_side_exclusion_anywhere_in_the_planner():
    """The decisive property: nothing may filter candidates OUT by verdict."""
    for word in ("AVOID", "IGNORE", "REBALANCE_TRIM"):
        for m in re.finditer(word, SRC):
            line_start = SRC.rfind("\n", 0, m.start()) + 1
            line = SRC[line_start:SRC.index("\n", m.start())]
            stripped = line.strip()
            assert stripped.startswith("#") or stripped.startswith("--"), (
                f"{word!r} appears in executable planner code, not a comment: {stripped[:110]!r}"
            )


# ── thresholds are policy, not literals ───────────────────────────────────────

def test_interest_thresholds_are_env_configurable():
    """Standing rule: no hardcoded values. These will need tuning as the
    watchlist grows."""
    for name in ("INTEREST_MOVE_PCT", "INTEREST_MOVE_RVOL",
                 "INTEREST_CATALYST_DAYS", "INTEREST_CATALYST_CONF"):
        assert hasattr(wep, name), f"{name} missing"
        assert f'os.getenv("PLANNER_{name}"' in SRC, f"{name} is not env-configurable"


def test_material_move_requires_volume_confirmation():
    """A bare percentage threshold is a volatility test, not a materiality one —
    it admitted 523 names on 2026-07-20, mostly small caps on ordinary days."""
    sql = _priority2_sql()
    move = [ln for ln in sql.splitlines() if "change_pct" in ln and "--" not in ln.split("change_pct")[0]]
    assert move, "material-move signal not found"
    window = sql[sql.index("change_pct"):sql.index("change_pct") + 400]
    assert "rvol" in window.lower(), "material move must be volume-confirmed"


# ── ordering: time-sensitive names must not be crowded out ────────────────────

def test_interest_outranks_conviction_in_the_cap():
    """BETA sat at hermes rank 525 with six catalysts and a big up day and was
    never reached, because the cap filled with higher-ranked names first."""
    sql = _priority2_sql()
    order = sql[sql.index("ORDER BY _interest"):]
    assert order.index("_interest") < order.index("_displayed"), \
        "_interest must sort ABOVE _displayed or time-sensitive names starve"


def test_interest_flag_uses_the_same_threshold_as_the_filter():
    """A sort flag that disagrees with the filter silently reorders the wrong
    rows — the class of drift that produced three different avoid-sets in the UI."""
    sql = _priority2_sql()
    assert sql.count("INTEREST_MOVE_PCT") >= 2 or sql.count(str(wep.INTEREST_MOVE_PCT)) >= 2, \
        "filter and sort flag must share one threshold"


# ── the psycopg2 trap that a compile check cannot catch ───────────────────────

def test_no_literal_percent_in_planner_sql():
    """A '%' inside SQL — including in a comment — is read by psycopg2 as a
    parameter placeholder and raises IndexError at execute. py_compile passes
    happily; only a live run catches it. One was introduced and caught in a dry
    run on 2026-07-20, before the 17:35 cron would have crashed on it."""
    sql = _priority2_sql()
    for i, line in enumerate(sql.splitlines(), 1):
        # Python comments are outside the query string; only SQL text reaches psycopg2.
        if line.strip().startswith("#"):
            continue
        for m in re.finditer(r"%", line):
            after = line[m.end():m.end() + 1]
            assert after == "s", (
                f"literal '%' in planner SQL at relative line {i} — psycopg2 will "
                f"treat it as a placeholder: {line.strip()[:110]!r}"
            )


def test_candidates_signature_is_stable():
    """The dry run that caught the '%' bug called this positionally."""
    import inspect
    params = list(inspect.signature(wep._candidates).parameters)
    assert params[:2] == ["cur", "limit"]
    for p in ("symbols", "scope", "buy_rated_cap"):
        assert p in params
