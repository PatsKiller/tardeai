#!/usr/bin/env python3
"""Strategy Weekly Review data-integrity fixes (2026-07-05 incident):
(1) no "None (UNVALIDATED)" rows — registry query COALESCEs strategy_id to strategy_type
    and the config-loader upsert always writes strategy_id;
(2) Real column reads the schwab journal (trade_closed) with single-owner family-tag
    attribution — not the NULL-strategy_type agent_recommendation_outcomes join;
(3) zero-conversion rows carry a factual gate note instead of a bare zero;
(4) lifecycle gating uses exact-id real trades only (family-attributed history reported,
    never promoting/demoting)."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv")
    _d.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _d

import strategy_weekly_review as swr  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def _src(name):
    with open(os.path.join(SCRIPTS, name)) as fh:
        return fh.read()


# ── family-tag attribution ───────────────────────────────────────────────────

def test_family_tags_have_single_owner():
    # each journal family tag is owned by exactly one registry strategy — a tag shared by
    # two strategies would double-count the same real trades in both rows
    owners = list(swr.JOURNAL_FAMILY_OWNER.values())
    assert len(set(swr.JOURNAL_FAMILY_OWNER)) == len(swr.JOURNAL_FAMILY_OWNER)
    assert "scalp" in swr.JOURNAL_FAMILY_OWNER and swr.JOURNAL_FAMILY_OWNER["scalp"] == "momentum_scalp"
    assert swr.JOURNAL_FAMILY_OWNER["swing"] == "swing_trade"
    # ambiguous journal tags must NOT be force-fitted to a strategy
    for tag in ("momentum", "position_trim", "other"):
        assert tag not in swr.JOURNAL_FAMILY_OWNER


def test_journal_tags_for():
    assert swr._journal_tags_for("momentum_scalp") == ["momentum_scalp", "scalp"]
    assert swr._journal_tags_for("swing_trade") == ["swing_trade", "swing"]
    assert swr._journal_tags_for("gap_and_go") == ["gap_and_go"]     # owns no family tag
    assert swr._journal_tags_for("SWING_TRADE") == ["swing_trade", "swing"]  # case-insensitive
    assert swr._journal_tags_for(None) == [""]


def test_compute_metrics_on_journal_rows():
    rows = [{"realized_pnl": 100.0}, {"realized_pnl": -50.0}, {"realized_pnl": 30.0}]
    m = swr._compute_metrics(rows)
    assert m["total"] == 3 and m["wins"] == 2 and m["losses"] == 1
    assert abs(m["win_rate"] - 2 / 3) < 1e-3
    assert abs(m["profit_factor"] - 2.6) < 1e-9   # 130 gross profit / 50 gross loss
    assert m["total_pnl"] == 80.0
    z = swr._compute_metrics([])
    assert z["total"] == 0 and z["win_rate"] == 0.0 and z["profit_factor"] == 0.0


# ── honest zero annotations ──────────────────────────────────────────────────

def test_gate_notes():
    zero = swr._compute_metrics([])
    n = swr._gate_note("UNVALIDATED", 7, 0, zero, 0.50)
    assert n == f"gate: 7/{swr.MIN_SIGNALS_FOR_TESTING} signals for TESTING"

    n = swr._gate_note("TESTING", 144, 2, zero, 0.50)
    assert f"2/{swr.MIN_TRADES_FOR_VALIDATED}" in n and "VALIDATED" in n

    good = swr._compute_metrics([{"realized_pnl": 10}] * 20 + [{"realized_pnl": -10}] * 15)
    n = swr._gate_note("TESTING", 144, 35, good, 0.50)
    assert n.startswith("gate:") and "WR" not in n.split("gate:")[0]
    assert "PF" in n  # PF 200/150 = 1.3 < 1.5 blocks

    bad_wr = swr._compute_metrics([{"realized_pnl": 100}] * 4 + [{"realized_pnl": -1}] * 6)
    n = swr._gate_note("TESTING", 144, 35, bad_wr, 0.50)
    assert "WR" in n and "40%" in n

    assert swr._gate_note("VALIDATED", 10, 50, good, 0.50) == "no change"


def test_trading_days_helper_bounded():
    d = swr._trading_days_last_7()
    assert d is None or (isinstance(d, int) and 0 <= d <= 7)


# ── source-level join/gating assertions ─────────────────────────────────────

def test_real_column_reads_schwab_journal():
    src = _src("strategy_weekly_review.py")
    assert "FROM trade_closed" in src
    # the broken join: agent_recommendation_outcomes.strategy_type is NULL on every row
    assert "agent_recommendation_outcomes" not in src.replace(
        "# source (agent_recommendation_outcomes.strategy_type)", "")
    # registry rows can never render as "None (...)"
    assert "COALESCE(NULLIF(BTRIM(strategy_id), ''), strategy_type)" in src


def test_lifecycle_gating_uses_exact_trades_only():
    src = _src("strategy_weekly_review.py")
    assert "combined_total = exact_metrics['total'] + paper_metrics['total']" in src
    # family-attributed rows must not feed promote/demote WR/PF checks
    assert "real_metrics['win_rate'] >= min_wr" not in src
    assert "exact_metrics['win_rate'] >= min_wr" in src


def test_config_loader_always_sets_strategy_id():
    src = _src("strategy_config_loader.py")
    assert "INSERT INTO strategy_registry (strategy_type, strategy_id," in src
    assert "strategy_id=COALESCE(strategy_registry.strategy_id, EXCLUDED.strategy_id)" in src


def test_state_snapshot_target():
    assert str(swr.STATE_FILE).endswith("data/portfolios/state/strategy_weekly_review_latest.json")


def main():
    fails = []
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  [PASS] {name}")
            except AssertionError as e:
                fails.append(name)
                print(f"  [FAIL] {name}: {e}")
    print(f"\n{len(fails)} failures")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
