#!/usr/bin/env python3
"""Recovery engine piece A — policy, residual rule, materiality, eligibility, store, and the SPCX replay gate.

The replay is the operator's acceptance test (spec §4.1): feed the five SPCX exits and the closes through 11-03 and the
engine must open one T1 case on 10-30, mark it RECOVERING on the 11-02 close, and raise exactly one P1 — the thing that
never happened in real life.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.recovery_engine import cases as rc  # noqa: E402
from lib.recovery_engine import policy as rp  # noqa: E402

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 11, 3)


@pytest.fixture()
def policy() -> rp.Policy:
    return rp.load_policy(ROOT / "config/recovery_policy.yaml")


@pytest.fixture()
def store(policy):
    conn = sqlite3.connect(":memory:")
    yield rc.CaseStore(conn, policy)
    conn.close()


# ── Policy ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_policy_loads_and_reads_the_operator_owned_values(policy):
    assert policy.residual.get("display_only") is True
    assert policy.eligibility.get("answered") is False
    assert policy.materiality["t1_loss_usd"] == 10000
    assert policy.eligibility["taxable_hold_days"] == 30
    assert policy.notification["t1_never_suppressed"] is True


def test_a_missing_policy_file_refuses_instead_of_defaulting(tmp_path):
    with pytest.raises(rp.PolicyError):
        rp.load_policy(tmp_path / "absent.yaml")


def test_a_policy_that_leaves_t1_suppressible_is_refused(tmp_path):
    text = (ROOT / "config/recovery_policy.yaml").read_text().replace("t1_never_suppressed: true",
                                                                     "t1_never_suppressed: false")
    bad = tmp_path / "recovery_policy.yaml"
    bad.write_text(text)
    with pytest.raises(rp.PolicyError) as caught:
        rp.load_policy(bad)
    assert "t1_never_suppressed" in str(caught.value)


def test_an_inverted_materiality_ladder_is_refused(tmp_path):
    text = (ROOT / "config/recovery_policy.yaml").read_text().replace("t2_loss_usd: 2000", "t2_loss_usd: 20000")
    bad = tmp_path / "recovery_policy.yaml"
    bad.write_text(text)
    with pytest.raises(rp.PolicyError):
        rp.load_policy(bad)


# ── Rule 1: the residual is displayed, never a silencer (operator ruling 2026-11-03) ─────────────────────
def test_a_residual_is_reported_as_a_percentage_not_a_verdict(policy):
    pct, note = rp.residual_display(1400, 200, "2026-10-30")
    assert pct == 14.3
    assert note == "200 of 1,400 shares remain after the 2026-10-30 exit (14.3%)"
    assert "held" not in note.lower()


def test_a_large_residual_is_reported_the_same_way(policy):
    pct, note = rp.residual_display(1400, 1000, "2026-10-30")
    assert pct == 71.4 and "1,000 of 1,400" in note
    assert "held" not in note.lower()


def test_an_unknown_pre_exit_size_is_stated_not_guessed(policy):
    pct, note = rp.residual_display(None, 200)
    assert pct is None and "pre-exit size unknown" in note


def test_a_closed_position_reports_no_shares_left(policy):
    assert rp.residual_display(1400, 0) == (0.0, "no shares remain")


# ── Rule 2: materiality ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("loss,weight,tier", [
    (-12770, 2.25, "T1"),
    (-10000, 0.1, "T1"),      # on the loss threshold
    (0, 3.0, "T1"),           # on the weight threshold
    (-3048, 0.5, "T2"),
    (-672, 0.2, "T3"),
])
def test_materiality_tiers(policy, loss, weight, tier):
    assert rp.materiality_tier(loss, weight, policy) == tier


# ── Rule 3: per-account eligibility ───────────────────────────────────────────────────────────────────────
def test_a_taxable_exit_carries_the_house_hold_and_an_ira_is_eligible_now(policy):
    taxable = rp.eligibility_for("schwab_taxable", date(2026, 10, 30), policy, today=TODAY)
    assert taxable.eligible is False and taxable.eligible_from == "2026-11-29"
    assert taxable.pending_operator_decision is True
    assert "house hold 30 days" in taxable.reason
    ira = rp.eligibility_for("schwab_roth_ira", date(2026, 10, 30), policy, today=TODAY)
    assert ira.eligible is True and ira.pending_operator_decision is True
    assert ira.line() == "schwab_roth_ira: now"


# ── The case row ──────────────────────────────────────────────────────────────────────────────────────────
def _spcx_fills():
    # realized = shares x (exit - avg cost), from the spec's table
    return [
        rc.ExitFill("SPCX", "schwab_taxable", date(2026, 10, 14), 200, 151.53, -6196, stop_price=152.0),
        rc.ExitFill("SPCX", "schwab_taxable", date(2026, 10, 14), 600, 151.50, -8171, stop_price=152.0),
        rc.ExitFill("SPCX", "schwab_taxable", date(2026, 10, 26), 700, 147.07, -3048, stop_price=148.0),
        rc.ExitFill("SPCX", "schwab_taxable", date(2026, 10, 28), 200, 146.14, -672, stop_price=147.0),
        rc.ExitFill("SPCX", "schwab_taxable", date(2026, 10, 30), 1200, 137.19, -12770, stop_price=137.0),
    ]


def test_the_case_row_carries_the_facts_the_card_needs(store):
    case = rc.consume_fills(store, _spcx_fills(), residual_shares=200, pre_exit_weight_pct=2.25,
                            today=TODAY, now=NOW)
    assert case.symbol == "SPCX" and case.account == "schwab_taxable"
    assert case.realized_pnl == pytest.approx(-30857)
    assert case.pre_exit_shares == pytest.approx(1400)          # 1,200 sold at the final exit + 200 residual
    assert case.residual_shares == pytest.approx(200)
    assert case.residual_pct_of_pre_exit == 14.3 and "held" not in case.residual_note.lower()
    assert case.materiality_tier == "T1"
    assert case.state == "WATCHING"
    assert case.eligibility_line() == "schwab_taxable: 2026-11-29 (house hold 30 days after a taxable sale)"
    assert case.exits[-1]["date"] == "2026-10-30"
    assert store.get(case.case_key).case_key == case.case_key


def test_consuming_the_same_cluster_twice_does_not_open_a_second_case(store):
    first = rc.consume_fills(store, _spcx_fills(), residual_shares=200, pre_exit_weight_pct=2.25, today=TODAY, now=NOW)
    second = rc.consume_fills(store, _spcx_fills(), residual_shares=200, pre_exit_weight_pct=2.25, today=TODAY, now=NOW)
    assert first.case_key == second.case_key
    assert len(store.list()) == 1


def test_a_large_residual_still_opens_the_case(store):
    """The ruling: a residual never suppresses the case. 1,300 of 1,400 remaining is displayed, not disqualifying."""
    case = rc.consume_fills(store, _spcx_fills(), residual_shares=1300, pre_exit_shares=1400,
                            pre_exit_weight_pct=2.25, today=TODAY, now=NOW)
    assert case.residual_pct_of_pre_exit == 92.9
    assert case.state == "WATCHING" and case.materiality_tier == "T1"
    assert "held" not in case.residual_note.lower()


# ── The replay gate (spec §4.1) ──────────────────────────────────────────────────────────────────────────
def test_the_spcx_replay_opens_t1_on_10_30_and_raises_exactly_one_p1(store):
    # 10-31 is a Saturday: closes are trading days only (11-02, 11-03).
    closes = [
        (date(2026, 11, 2), 141.65),      # +3.3% over the 137.19 exit -> R1 -> one P1 that day
        (date(2026, 11, 3), 141.65),
    ]
    result = rc.replay_spcx(store, fills=_spcx_fills(), closes=closes, sma20=151.62, residual_shares=200,
                            pre_exit_weight_pct=2.25, today=TODAY, now=NOW)
    case, events = result["case"], result["events"]
    assert case["materiality_tier"] == "T1"
    assert case["exits"][-1]["date"] == "2026-10-30"
    assert case["state"] == "RECOVERING" and case["state_since"]
    assert len(events) == 1
    event = events[0]
    assert event["priority"] == "P1" and event["suppressed"] is None
    assert "+3.3% above your 2026-10-30 exit" in event["text"]
    assert "next: reclaims 151.62 20-day mean" in event["text"]
    assert event["eligibility"].startswith("schwab_taxable: 2026-11-29")
    stored = store.get(case["case_key"])
    assert stored.last_p1_at is not None


def test_the_replay_raises_no_p1_before_the_reclaim(store):
    closes = [(date(2026, 11, 2), 137.50), (date(2026, 11, 3), 138.00)]
    result = rc.replay_spcx(store, fills=_spcx_fills(), closes=closes, sma20=151.62, residual_shares=200,
                            pre_exit_weight_pct=2.25, today=TODAY, now=NOW)
    assert result["events"] == []
    assert result["case"]["state"] == "WATCHING"


def test_a_t2_case_recovers_without_a_p1(store):
    # Same shape, but the loss is small enough for T2: a recovery still opens, and it is not a page.
    small = [rc.ExitFill("PFLT", "schwab_taxable", date(2026, 10, 30), 500, 15.0, -600, stop_price=15.2)]
    case = rc.consume_fills(store, small, residual_shares=1.15, today=TODAY, now=NOW)
    assert case.materiality_tier == "T3"
    assert case.residual_pct_of_pre_exit == 0.2    # 1.15 of 501.15 shares, displayed not judged


def test_pflt_residual_is_displayed_not_judged(store):
    """The spec's second named name: a 1.15-share residual is shown as a fact and opens its case."""
    fills = [rc.ExitFill("PFLT", "schwab_taxable", date(2026, 10, 20), 500, 14.9, -500)]
    case = rc.consume_fills(store, fills, residual_shares=1.15, today=TODAY, now=NOW)
    assert case.residual_pct_of_pre_exit == 0.2 and "1.15 of 501.15" in case.residual_note


# ── The fills consumer against the live store shapes ───────────────────────────────────────────────────────
def _live_shaped_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE stopped_out_watch (stopped_out_at TEXT, exit_price REAL, realized_pnl REAL, stop_price REAL,
                                        broker TEXT, symbol TEXT, account TEXT, is_active INTEGER);
        CREATE TABLE trade_transactions (trade_date TEXT, action TEXT, symbol TEXT, quantity REAL, price REAL,
                                         account TEXT);
        CREATE TABLE stop_last_known (broker TEXT, account TEXT, symbol TEXT, stop_price REAL, captured_at TEXT);
        CREATE TABLE positions_current (account_key TEXT, symbol TEXT, qty REAL);
    """)
    conn.executemany("INSERT INTO stopped_out_watch VALUES (?,?,?,?,?,?,?,?)", [
        ("2026-10-30", 137.19, -12770, 137.0, "schwab", "SPCX", "schwab_taxable", 1),
    ])
    conn.executemany("INSERT INTO trade_transactions VALUES (?,?,?,?,?,?)", [
        ("2026-10-30", "SELL", "SPCX", 1200, 137.19, "schwab_taxable"),
    ])
    conn.execute("INSERT INTO stop_last_known VALUES ('schwab','schwab_taxable','SPCX',137.0,'2026-10-30')")
    conn.execute("INSERT INTO positions_current VALUES ('schwab_taxable','SPCX',200)")
    conn.commit()
    return conn


def test_the_consumer_reads_the_live_shapes_and_opens_spcx(store):
    from lib.recovery_engine import fills_consumer as fc
    conn = _live_shaped_db()
    read = fc.read_confirmed_exits(conn, "SPCX", "schwab_taxable")
    assert read.residual_shares == pytest.approx(200)
    assert read.fills[-1].realized_pnl == pytest.approx(-12770)
    assert read.fills[-1].shares == pytest.approx(1200)       # from trade_transactions, not invented
    assert read.fills[-1].stop_price == pytest.approx(137.0)  # from the watch row
    case = fc.consume_symbol(store, conn, "SPCX", "schwab_taxable", today=TODAY, now=NOW)
    assert case.materiality_tier == "T1" and case.residual_pct_of_pre_exit == 14.3
    conn.close()


def test_the_consumer_is_idempotent_over_a_run(store):
    from lib.recovery_engine import fills_consumer as fc
    conn = _live_shaped_db()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    second = fc.run(store, conn, today=TODAY, now=NOW)
    assert first["cases"] and second["cases"]
    assert len(store.list()) == 1
    conn.close()


def test_a_missing_store_is_a_stated_gap_not_an_invented_fill(store):
    from lib.recovery_engine import fills_consumer as fc
    empty = sqlite3.connect(":memory:")
    read = fc.read_confirmed_exits(empty, "SPCX", "schwab_taxable")
    assert read.fills == [] and read.gaps
    assert fc.consume_symbol(store, empty, "SPCX", "schwab_taxable", today=TODAY, now=NOW) is None
    empty.close()


def test_the_case_carries_no_sizing_decision(store):
    """Sizing is the operator's (MBI_BEHAVIOR = 0): the row may carry a proposal field, never a computed size."""
    case = rc.consume_fills(store, _spcx_fills(), residual_shares=200, pre_exit_weight_pct=2.25, today=TODAY, now=NOW)
    row = case.to_dict()
    assert row.get("plan") is None
    for forbidden in ("size_to_restore", "order_qty", "shares_to_buy", "stop_price_target"):
        assert forbidden not in row
