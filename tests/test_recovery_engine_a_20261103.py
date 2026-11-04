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
    assert note == ("200 of 1,400 shares remain after the 2026-10-30 exit "
                    "(14.3%; pre_exit_shares from the fill ledger)")
    assert "held" not in note.lower()


def test_a_large_residual_is_reported_the_same_way(policy):
    pct, note = rp.residual_display(1400, 1000, "2026-10-30")
    assert pct == 71.4 and "1,000 of 1,400" in note and "pre_exit_shares from the fill ledger" in note
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


def test_the_same_symbol_in_two_accounts_is_two_cases(store):
    """The identity C keys its per-case-per-day page on must not merge two accounts (lead ruling, 2026-11-03).

    Both rows come out of the real `consume_fills` path over identical exits; no id is hand-authored.
    """
    taxable = rc.consume_fills(store, _spcx_fills(), residual_shares=200, pre_exit_weight_pct=2.25,
                               today=TODAY, now=NOW)
    ira_fills = [rc.ExitFill(f.symbol, "schwab_roth_ira", f.exit_date, f.shares, f.price, f.realized_pnl,
                             stop_price=f.stop_price) for f in _spcx_fills()]
    ira = rc.consume_fills(store, ira_fills, residual_shares=200, pre_exit_weight_pct=2.25, today=TODAY, now=NOW)
    assert taxable.case_key != ira.case_key
    assert "schwab_taxable" in taxable.case_key and "schwab_roth_ira" in ira.case_key
    assert sorted(c.account for c in store.list()) == ["schwab_roth_ira", "schwab_taxable"]


def test_a_later_exit_cluster_opens_its_own_case_for_the_same_account(store):
    """A second, separated exit is a different case: the cluster dates are part of the identity, not just the symbol."""
    first = rc.consume_fills(store, _spcx_fills(), residual_shares=200, pre_exit_weight_pct=2.25, today=TODAY, now=NOW)
    later = rc.consume_fills(store, [rc.ExitFill("SPCX", "schwab_taxable", date(2026, 11, 2), 300, 139.97, -500,
                                                 stop_price=140.0)],
                             residual_shares=200, pre_exit_weight_pct=0.5, today=TODAY, now=NOW)
    assert first.case_key != later.case_key
    assert first.cluster_key == "2026-10-14..2026-10-30" and later.cluster_key == "2026-11-02..2026-11-02"
    assert len(store.list()) == 2


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
                                        broker TEXT, symbol TEXT, account TEXT, is_active INTEGER, id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE trade_transactions (trade_date TEXT, action TEXT, symbol TEXT, quantity REAL, price REAL,
                                         account TEXT, dedupe_key TEXT, provider_uid TEXT);
        CREATE TABLE stop_last_known (broker TEXT, account TEXT, symbol TEXT, stop_price REAL, captured_at TEXT);
        CREATE TABLE positions_current (account_key TEXT, symbol TEXT, qty REAL);
    """)
    conn.executemany("INSERT INTO stopped_out_watch (stopped_out_at, exit_price, realized_pnl, stop_price, broker, symbol, account, is_active) VALUES (?,?,?,?,?,?,?,?)", [
        ("2026-10-30", 137.19, -12770, 137.0, "schwab", "SPCX", "schwab_taxable", 1),
    ])
    conn.executemany("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account) VALUES (?,?,?,?,?,?)", [
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


# ── Residuals that must each open a case, named (operator ruling: the old 0.15 cliff is gone) ────────────────
@pytest.mark.parametrize("residual,pre_exit,pct_in_name", [
    (1.0, 500.0, 0.2),        # 0.2% — a fragment
    (200.0, 1400.0, 14.3),    # 14.3% — SPCX, closest to the old cliff; the case must open
    (1300.0, 1400.0, 92.9),   # 92.9% — almost everything survived; still opens
])
def test_every_residual_opens_a_case_named_by_its_percentage(store, residual, pre_exit, pct_in_name):
    case = rc.consume_fills(store, _spcx_fills(), residual_shares=residual, pre_exit_shares=pre_exit,
                            pre_exit_weight_pct=2.25, today=TODAY, now=NOW)
    assert case.residual_pct_of_pre_exit == pytest.approx(pct_in_name, abs=0.1)
    # F1: this fixture supplies the denominator, and the note says so. Calling it fill-ledger provenance here was
    # precisely the gap cx-openai-2 found — a caller's estimate and a fill-derived size rendered identically.
    assert case.pre_exit_source.startswith("pre_exit_shares supplied by the caller")
    assert "supplied by the caller" in case.residual_note
    assert case.state == "WATCHING" and case.case_key.startswith("SPCX::schwab_taxable::")


# ── cx-openai-2's two findings ──────────────────────────────────────────────────────────────────────────────
def test_an_unreadable_positions_store_is_unknown_not_zero(tmp_path, store):
    """The false-zero class: an unreadable store must never read as 'no shares remain'."""
    from lib.recovery_engine import fills_consumer as fc
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE stopped_out_watch (stopped_out_at TEXT, exit_price REAL, realized_pnl REAL, stop_price REAL,
                                        broker TEXT, symbol TEXT, account TEXT, is_active INTEGER, id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE trade_transactions (trade_date TEXT, action TEXT, symbol TEXT, quantity REAL, price REAL,
                                         account TEXT, dedupe_key TEXT, provider_uid TEXT);
        CREATE TABLE stop_last_known (broker TEXT, account TEXT, symbol TEXT, stop_price REAL, captured_at TEXT);
        CREATE TABLE positions_current (account_key TEXT, symbol TEXT, qty REAL);
    """)
    conn.execute("INSERT INTO stopped_out_watch (stopped_out_at, exit_price, realized_pnl, stop_price, broker,"
                 " symbol, account, is_active) VALUES ('2026-10-30', 137.19, -12770, 137.0, 'schwab', 'SPCX',"
                 " 'schwab_taxable', 1)")
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account) VALUES ('2026-10-30','SELL','SPCX',1200,137.19,'schwab_taxable')")
    conn.commit()
    conn.execute("DROP TABLE positions_current")          # the store is unavailable
    conn.commit()
    read = fc.read_confirmed_exits(conn, "SPCX", "schwab_taxable")
    assert read.residual_shares is None                    # unknown, NOT 0.0
    assert any("residual is unknown" in gap for gap in read.gaps)
    case = fc.consume_symbol(store, conn, "SPCX", "schwab_taxable", today=TODAY, now=NOW)
    assert case.residual_shares is None
    assert case.residual_pct_of_pre_exit is None
    assert "unknown" in case.residual_note and "zero" not in case.residual_note.lower()
    conn.close()


def test_the_store_executes_through_a_cursor(store):
    """A DB-API connection has no execute(), and psycopg2's Cursor.execute returns None (cx-openai-2 F2).

    The old `return cur.execute(...)` looked fine against SQLite, whose execute returns a cursor, and raised
    "'NoneType' object has no attribute 'fetchall'" against Postgres. This fake reproduces the Postgres return value.
    """
    class CursorOnly:
        def __init__(self, conn):
            self.conn, self._cur = conn, None
        def execute(self, sql, params=()):
            self._cur = self.conn._real.execute(sql.replace("%s", "?"), params)
            return None                      # what psycopg2 does; returning the cursor hides the defect
        def fetchall(self):
            return self._cur.fetchall()
    class Conn:
        def __init__(self, real):
            self._real = real
        def cursor(self): return CursorOnly(self)
        def commit(self): self._real.commit()
    real = sqlite3.connect(":memory:")
    wrapped = Conn(real)
    wrapped_store = rc.CaseStore(wrapped, store.policy)
    case = rc.consume_fills(wrapped_store, _spcx_fills(), residual_shares=200, pre_exit_weight_pct=2.25,
                            today=TODAY, now=NOW)
    assert case.symbol == "SPCX" and wrapped_store.get(case.case_key) is not None
    real.close()


# ── cx-openai-2's whole-head BLOCK at ad53aa9ee (F1-F11) ────────────────────────────────────────────────────
def _source_db() -> sqlite3.Connection:
    """The five stores the reader touches, empty, with the heartbeat clock the residual's age comes from."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE stopped_out_watch (stopped_out_at TEXT, exit_price REAL, realized_pnl REAL, stop_price REAL,
                                        broker TEXT, symbol TEXT, account TEXT, is_active INTEGER, id INTEGER PRIMARY KEY AUTOINCREMENT);
        CREATE TABLE trade_transactions (trade_date TEXT, action TEXT, symbol TEXT, quantity REAL, price REAL,
                                         account TEXT, dedupe_key TEXT, provider_uid TEXT);
        CREATE TABLE stop_last_known (broker TEXT, account TEXT, symbol TEXT, stop_price REAL, captured_at TEXT);
        CREATE TABLE positions_current (account_key TEXT, symbol TEXT, qty REAL);
        CREATE TABLE positions_sync_runs (run_id INTEGER PRIMARY KEY, finished_at TEXT, status TEXT, promoted INTEGER);
    """)
    return conn


def _watch(conn, day, price, pnl, symbol="SPCX", account="schwab_taxable", stop=137.0):
    conn.execute("INSERT INTO stopped_out_watch (stopped_out_at, exit_price, realized_pnl, stop_price, broker, symbol, account, is_active) VALUES (?,?,?,?,?,?,?,1)",
                 (day, price, pnl, stop, "schwab", symbol, account))


def _tx(conn, day, qty, symbol="SPCX", account="schwab_taxable"):
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account) VALUES (?,?,?,?,?,?)",
                 (day, "SELL", symbol, qty, 137.19, account))


def _positions(conn, qty, symbol="SPCX", account="schwab_taxable"):
    conn.execute("INSERT INTO positions_current VALUES (?,?,?)", (account, symbol, qty))


def test_f1_the_denominator_says_where_it_came_from(store):
    """F1: a caller estimate and a fill-derived size must not render identically."""
    derived = rc.consume_fills(store, _spcx_fills(), residual_shares=200, today=TODAY, now=NOW)
    assert derived.pre_exit_shares == pytest.approx(1400)
    assert derived.pre_exit_source.startswith("pre_exit_shares from the fill ledger")
    assert "from the fill ledger" in derived.residual_note
    same_number = rc.consume_fills(store, _spcx_fills(), residual_shares=200, pre_exit_shares=1400,
                                   today=TODAY, now=NOW)
    assert same_number.pre_exit_source.startswith("pre_exit_shares supplied by the caller")
    assert "supplied by the caller" in same_number.residual_note
    assert same_number.pre_exit_source != derived.pre_exit_source


def test_f3_decoded_json_values_read_back_on_postgres_semantics(store):
    """F3: psycopg2 hands back decoded list/dict; json.loads on those raised TypeError and every read failed."""
    row = ("SPCX::x::d..d", "SPCX", "schwab_taxable", "schwab", "d..d", [{"date": "2026-10-30", "price": 137.19}],
           "2026-10-30", "2026-10-30", -12770.0, 1400.0, 200.0, 2.25, "T1", 14.3, "note", "src", None, [],
           "WATCHING", "2026-11-03T00:00:00+00:00",
           [{"account": "schwab_taxable", "eligible": False, "eligible_from": "2026-11-29", "reason": "hold",
             "pending_operator_decision": True}],
           {"proposal": "wait"}, None, None, "none", "a note", "2026-11-01T00:00:00+00:00",
           "2026-11-03T00:00:00+00:00", "2026-11-03T00:00:00+00:00", "broker-fills")
    case = store._row_to_case(row)
    assert case.exits[0]["price"] == 137.19 and case.plan == {"proposal": "wait"}
    assert case.eligibility[0].account == "schwab_taxable"


def test_f4_a_null_realized_pnl_is_unknown_not_a_quiet_t3(store):
    conn = _source_db()
    _watch(conn, "2026-10-30", 137.19, None)          # the P&L is missing on the only source that carries it
    _tx(conn, "2026-10-30", 1200)
    _positions(conn, 200)
    from lib.recovery_engine import fills_consumer as fc
    read = fc.read_confirmed_exits(conn, "SPCX", "schwab_taxable")
    assert read.fills and read.fills[0].realized_pnl is None
    case = fc.consume_symbol(store, conn, "SPCX", "schwab_taxable", today=TODAY, now=NOW)
    assert case.materiality_tier == "UNKNOWN"          # page-worthy, never the quiet rung
    assert any("realized P&L is unknown" in gap for gap in case.gaps)
    conn.close()


def test_f4_a_nan_pnl_is_unknown_too(store):
    conn = _source_db()
    _watch(conn, "2026-10-30", 137.19, "NaN")
    _tx(conn, "2026-10-30", 1200)
    _positions(conn, 200)
    from lib.recovery_engine import fills_consumer as fc
    case = fc.consume_symbol(store, conn, "SPCX", "schwab_taxable", today=TODAY, now=NOW)
    assert case.materiality_tier == "UNKNOWN"
    conn.close()


def test_f4_two_exits_on_one_day_are_not_each_given_the_whole_days_shares(store):
    conn = _source_db()
    _watch(conn, "2026-10-30", 137.19, -1000)
    _watch(conn, "2026-10-30", 136.90, -2000)
    _tx(conn, "2026-10-30", 6000)
    _tx(conn, "2026-10-30", 6000)
    _positions(conn, 200)
    from lib.recovery_engine import fills_consumer as fc
    read = fc.read_confirmed_exits(conn, "SPCX", "schwab_taxable")
    assert [f.shares for f in read.fills] == [None, None]
    assert any("cannot be attributed" in gap for gap in read.gaps)
    assert not any(f.shares == 12000 for f in read.fills)
    conn.close()


def test_r3_a_later_confirmed_fill_joins_the_universe_instead_of_being_dropped(store):
    """cx-openai-4 R3: a fill with no stop-out row used to vanish, so the case understated the exits."""
    conn = _source_db()
    _watch(conn, "2026-10-30", 137.19, -12770)
    _tx(conn, "2026-10-30", 1200)
    _tx(conn, "2026-11-02", 300)                       # a fill with no stop-out row: it is still a confirmed exit
    _positions(conn, 200)
    from lib.recovery_engine import fills_consumer as fc
    read = fc.read_confirmed_exits(conn, "SPCX", "schwab_taxable")
    assert [f.exit_date for f in read.fills] == [date(2026, 10, 30), date(2026, 11, 2)]
    assert read.fills[1].shares == pytest.approx(300) and read.fills[1].price == pytest.approx(137.19)
    assert read.fills[1].realized_pnl is None          # unknown, not a zero
    assert any("no stopped_out_watch row" in gap for gap in read.gaps)
    case = fc.consume_symbol(store, conn, "SPCX", "schwab_taxable", today=TODAY, now=NOW)
    assert case.pre_exit_shares == pytest.approx(500)   # 300 sold at the final exit + 200 residual
    assert case.materiality_tier == "UNKNOWN"           # the 11-02 exit's loss is unknown, so the total is
    conn.close()


def test_r3_contradictory_exit_prices_are_flagged_not_silently_overruled(store):
    conn = _source_db()
    _watch(conn, "2026-10-30", 50.0, -1000)
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account) VALUES ('2026-10-30','SELL','SPCX',100,200.0,'schwab_taxable')")
    _positions(conn, 0)
    from lib.recovery_engine import fills_consumer as fc
    read = fc.read_confirmed_exits(conn, "SPCX", "schwab_taxable")
    assert any("conflicting exit prices" in gap and "50" in gap and "200" in gap for gap in read.gaps)
    assert read.fills[0].price == pytest.approx(50.0)  # the stop-out row's price is kept, and the conflict is visible
    conn.close()


def test_f5_a_plan_carrying_an_execution_value_is_refused(store):
    case = rc.consume_fills(store, _spcx_fills(), residual_shares=200, today=TODAY, now=NOW)
    for bad in ({"shares": 17}, {"stop": 8}, {"order": "BUY"}, {"nested": {"qty": 3}}):
        case.plan = bad
        with pytest.raises(ValueError, match="execution value"):
            store.upsert(case)
    case.plan = {"proposal": "Wait for the operator; the card shows the reclaim level"}
    assert store.upsert(case).plan["proposal"].startswith("Wait")


def test_f7_a_refresh_keeps_the_plan_and_the_operator_note(store):
    case = rc.consume_fills(store, _spcx_fills(), residual_shares=200, today=TODAY, now=NOW)
    case.plan = {"proposal": "Wait for operator"}
    store.upsert(case)
    store.set_decision(case.case_key, "snoozed", note="Synthetic operator annotation")
    again = rc.consume_fills(store, _spcx_fills(), residual_shares=200, today=TODAY, now=NOW)
    assert again.plan == {"proposal": "Wait for operator"}
    assert again.operator_note == "Synthetic operator annotation"
    stored = store.get(case.case_key)
    assert stored.plan == {"proposal": "Wait for operator"}
    assert stored.operator_note == "Synthetic operator annotation"
    assert stored.operator_decision == "snoozed"


def test_f8_the_row_exposes_pending_and_answered(store):
    case = rc.consume_fills(store, _spcx_fills(), residual_shares=200, today=TODAY, now=NOW)
    doc = case.to_dict()
    assert doc["pending_operator_decision"] is True
    assert doc["eligibility"][0]["answered"] is False


def test_f9_a_failed_enumeration_is_not_an_empty_work_list(store):
    conn = sqlite3.connect(":memory:")                 # no stores at all
    from lib.recovery_engine import fills_consumer as fc
    out = fc.run(store, conn, today=TODAY, now=NOW)
    assert out["opened"] == [] and out["cases"] == []
    assert out["complete"] is False
    assert any("work list is incomplete" in gap for gap in out["gaps"])
    conn.close()


def test_f10_one_damaged_case_does_not_block_the_others(store):
    conn = _source_db()
    _watch(conn, "2026-10-30", "damaged", -1000, symbol="AAAA")
    _tx(conn, "2026-10-30", 100, symbol="AAAA")
    _watch(conn, "2026-10-30", 40.0, -500, symbol="EXMPL", account="schwab_roth_ira")
    _tx(conn, "2026-10-30", 50, symbol="EXMPL", account="schwab_roth_ira")
    _positions(conn, 0, symbol="EXMPL", account="schwab_roth_ira")
    from lib.recovery_engine import fills_consumer as fc
    out = fc.run(store, conn, today=TODAY, now=NOW)
    assert any(key.startswith("EXMPL::") for key in out["opened"]), out
    assert any("AAAA" in gap and "excluded" in gap for gap in out["gaps"])
    # AAAA's damaged watch price is excluded, but its confirmed fill still carries a price, so the exit is not lost;
    # its realized P&L is unknown and the case says so rather than guessing T3.
    aaaa = [c for c in out["cases"] if c["symbol"] == "AAAA"]
    assert aaaa and aaaa[0]["materiality_tier"] == "UNKNOWN"
    assert any("realized P&L is unknown" in gap for gap in aaaa[0]["gaps"])
    conn.close()


def test_f11_the_caller_s_boundary_is_honoured(store):
    conn = _source_db()
    _watch(conn, "2026-10-30", 137.19, -12770)
    _tx(conn, "2026-10-30", 1200)
    _watch(conn, "2030-01-01", 900.0, -400, symbol="FUTR")   # after the replay date: invisible at as_of
    _tx(conn, "2030-01-01", 400, symbol="FUTR")
    _positions(conn, 200)
    conn.execute("INSERT INTO positions_sync_runs VALUES (1, '2026-11-02T21:00:00+00:00', 'complete', 1)")
    from lib.recovery_engine import fills_consumer as fc
    read = fc.read_confirmed_exits(conn, "SPCX", "schwab_taxable", as_of=date(2026, 11, 3))
    assert [f.exit_date for f in read.fills] == [date(2026, 10, 30)]
    assert all("2030" not in gap for gap in read.gaps)
    # and the work list honours `since` the same way: from mid-November only the future-dated symbol is listed
    pairs, _, enumerated_ok = fc.symbols_with_confirmed_exits(conn, since=date(2026, 11, 15))
    assert enumerated_ok is True
    assert pairs == [("FUTR", "schwab_taxable")]
    conn.close()


def test_f11_a_positions_snapshot_older_than_the_exit_is_not_todays_residual(store):
    conn = _source_db()
    _watch(conn, "2026-10-30", 137.19, -12770)
    _tx(conn, "2026-10-30", 1200)
    _positions(conn, 14000)                            # a stale snapshot from before the exit
    conn.execute("INSERT INTO positions_sync_runs VALUES (1, '2026-10-20T21:00:00+00:00', 'complete', 1)")
    from lib.recovery_engine import fills_consumer as fc
    case = fc.consume_symbol(store, conn, "SPCX", "schwab_taxable", today=TODAY, now=NOW)
    assert case.residual_shares is None
    assert case.residual_pct_of_pre_exit is None
    assert any("before the 2026-10-30 exit" in gap for gap in case.gaps)
    conn.close()


def test_r5_a_later_exit_does_not_replay_an_existing_closed_case(store):
    """cx-openai-4 R5: the same historical exit used to live in the old CLOSED case AND in the new one."""
    conn = _source_db()
    _watch(conn, "2030-01-02", 100.0, -500)
    _tx(conn, "2030-01-02", 100)
    _positions(conn, 0)
    from lib.recovery_engine import fills_consumer as fc
    first = fc.run(store, conn, today=TODAY, now=NOW)
    assert len(first["opened"]) == 1
    closed_key = first["opened"][0]
    store.set_state(closed_key, "CLOSED")
    _watch(conn, "2030-01-10", 90.0, -300)
    _tx(conn, "2030-01-10", 50)
    second = fc.run(store, conn, today=TODAY, now=NOW)
    cases = {c.case_key: c for c in store.list()}
    assert len(cases) == 2, cases
    new_key = next(k for k in cases if k != closed_key)
    assert second["opened"] == [new_key]
    assert cases[closed_key].state == "CLOSED"
    assert cases[new_key].state == "WATCHING"
    # each historical exit belongs to exactly one case — no overlap
    owned = [(k, e["date"]) for k, c in cases.items() for e in c.exits]
    dates = sorted(d for _, d in owned)
    assert dates == ["2030-01-02", "2030-01-10"], owned
    assert closed_key.endswith("2030-01-02..2030-01-02")
    assert new_key.endswith("2030-01-10..2030-01-10")
    conn.close()


def test_r5_an_open_case_extends_without_changing_its_id(store):
    conn = _source_db()
    _watch(conn, "2030-01-02", 100.0, -500)
    _tx(conn, "2030-01-02", 100)
    _positions(conn, 0)
    from lib.recovery_engine import fills_consumer as fc
    first = fc.run(store, conn, today=TODAY, now=NOW)
    key = first["opened"][0]
    store.set_decision(key, "snoozed", note="keep me")
    _watch(conn, "2030-01-10", 90.0, -300)
    _tx(conn, "2030-01-10", 50)
    second = fc.run(store, conn, today=TODAY, now=NOW)
    assert second["opened"] == [] and second["refreshed"] == [key]
    case = store.get(key)
    assert [e["date"] for e in case.exits] == ["2030-01-02", "2030-01-10"]
    assert case.operator_decision == "snoozed" and case.operator_note == "keep me"
    assert len(store.list()) == 1
    conn.close()


# ── cx-openai-2's F12/F13 at 6b844aace ──────────────────────────────────────────────────────────────────────
def test_f12_a_third_unchanged_pass_does_not_refill_a_case_with_an_older_cluster(store):
    """F12: the newest case was refreshed from ALL older history, so a repeat pass re-absorbed a CLOSED cluster."""
    conn = _source_db()
    _watch(conn, "2026-10-30", 100.0, -15000)
    _tx(conn, "2026-10-30", 100)
    _positions(conn, 0)
    from lib.recovery_engine import fills_consumer as fc
    first = fc.run(store, conn, today=TODAY, now=NOW)
    closed_key = first["opened"][0]
    store.set_state(closed_key, "CLOSED")
    _watch(conn, "2026-11-02", 90.0, -500)
    _tx(conn, "2026-11-02", 50)
    second = fc.run(store, conn, today=TODAY, now=NOW)          # allocates the 11-02 case
    third = fc.run(store, conn, today=TODAY, now=NOW)           # identical pass, no source change
    assert second["complete"] is True and third["complete"] is True
    cases = {c.case_key: c for c in store.list()}
    assert len(cases) == 2, cases
    new_key = next(k for k in cases if k != closed_key)
    assert [e["date"] for e in cases[new_key].exits] == ["2026-11-02"], cases[new_key].exits
    assert cases[new_key].realized_pnl == pytest.approx(-500) and cases[new_key].materiality_tier == "T3"
    assert [e["date"] for e in cases[closed_key].exits] == ["2026-10-30"]
    assert cases[closed_key].realized_pnl == pytest.approx(-15000)
    owned = [(k, e["date"]) for k, c in cases.items() for e in c.exits]
    assert sorted(d for _, d in owned) == ["2026-10-30", "2026-11-02"], owned


def test_f13_a_confirmed_exit_that_cannot_be_priced_makes_the_pass_incomplete(store):
    """F13: a confirmed exit excluded for want of a price reported complete=true."""
    conn = _source_db()
    _watch(conn, "2026-10-30", "damaged", -1000)
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account) VALUES ('2026-10-30','SELL','SPCX',100,'bad','schwab_taxable')")
    _positions(conn, 0)
    from lib.recovery_engine import fills_consumer as fc
    out = fc.run(store, conn, today=TODAY, now=NOW)
    assert out["opened"] == [] and out["cases"] == []
    assert out["complete"] is False, out
    assert out["failed"] and "no case could be built" in out["failed"][0]
    assert any("no usable fill price" in gap for gap in out["gaps"])
    conn.close()


def test_f14_two_distinct_same_day_exits_survive_an_unchanged_refresh(store):
    """codex F14: a date is not a fill identity — two exits on one day must stay two exits with their own numbers."""
    conn = _source_db()
    _watch(conn, "2026-10-27", 80.0, -6000)
    _watch(conn, "2026-10-27", 82.0, -200)
    _tx(conn, "2026-10-27", 100)
    _positions(conn, 0)
    from lib.recovery_engine import fills_consumer as fc
    first = fc.run(store, conn, today=TODAY, now=NOW)
    key = first["opened"][0]
    before = store.get(key)
    assert sorted(e["price"] for e in before.exits) == [80.0, 82.0]
    assert before.realized_pnl == pytest.approx(-6200)
    assert before.materiality_tier == "T2"
    second = fc.run(store, conn, today=TODAY, now=NOW)          # unchanged source, identical pass
    after = store.get(key)
    assert second["complete"] is True and second["refreshed"] == [key]
    assert sorted(e["price"] for e in after.exits) == [80.0, 82.0]
    assert sorted(e["realized_pnl"] for e in after.exits) == [-6000.0, -200.0]
    assert after.realized_pnl == pytest.approx(-6200) and after.materiality_tier == "T2"
    conn.close()


def test_f14_an_unknown_sibling_stays_unknown_on_refresh(store):
    """The worst outcome in this engine: an UNKNOWN converted into a confident number."""
    conn = _source_db()
    _watch(conn, "2026-10-27", 80.0, None)
    _watch(conn, "2026-10-27", 82.0, -200)
    _tx(conn, "2026-10-27", 100)
    _positions(conn, 0)
    from lib.recovery_engine import fills_consumer as fc
    first = fc.run(store, conn, today=TODAY, now=NOW)
    key = first["opened"][0]
    assert store.get(key).realized_pnl is None and store.get(key).materiality_tier == "UNKNOWN"
    fc.run(store, conn, today=TODAY, now=NOW)
    after = store.get(key)
    assert after.realized_pnl is None, "an unknown loss resolved to a number"
    assert after.materiality_tier == "UNKNOWN"
    assert sorted(e["realized_pnl"] for e in after.exits if e["realized_pnl"] is not None) == [-200.0]
    conn.close()


def test_f15_a_late_same_day_exit_is_persisted_not_dropped(store):
    """codex F15: a second confirmed same-day exit was read and silently discarded while the pass said complete."""
    conn = _source_db()
    _watch(conn, "2026-10-27", 82.0, -200)
    _tx(conn, "2026-10-27", 10)
    _positions(conn, 0)
    from lib.recovery_engine import fills_consumer as fc
    first = fc.run(store, conn, today=TODAY, now=NOW)
    key = first["opened"][0]
    assert store.get(key).realized_pnl == pytest.approx(-200) and store.get(key).materiality_tier == "T3"
    _watch(conn, "2026-10-27", 80.0, -12000)      # the late arrival, same day, distinct exit
    _tx(conn, "2026-10-27", 20)
    second = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(key)
    assert sorted(e["realized_pnl"] for e in case.exits) == [-12000.0, -200.0]
    assert case.realized_pnl == pytest.approx(-12200) and case.materiality_tier == "T1"
    assert second["complete"] is True and second["failed"] == []
    conn.close()


def test_f15_a_pass_that_cannot_persist_a_late_fill_reports_incomplete(store, monkeypatch):
    """The one outcome that must be impossible: complete=True while a read fill was dropped."""
    conn = _source_db()
    _watch(conn, "2026-10-27", 82.0, -200)
    _watch(conn, "2026-10-27", 80.0, -12000)
    _tx(conn, "2026-10-27", 20)
    _positions(conn, 0)
    from lib.recovery_engine import fills_consumer as fc

    def refuse(*a, **k):
        raise OSError("store refused the write")

    monkeypatch.setattr(store, "upsert", refuse)
    out = fc.run(store, conn, today=TODAY, now=NOW)
    assert out["complete"] is False and out["failed"], out
    conn.close()


# ── codex F16: the source identity, not a mutable attribute ──────────────────────────────────────────────────
def test_f16_a_price_correction_refreshes_the_exit_instead_of_minting_a_second(store):
    """codex's own counterexample. Persist one exit priced 80, then correct the SOURCE row to 82 with no INSERT and
    run again. Matching on price appended 82 as a second exit: -200 became -400 while the case still reported
    complete=True, gaps=[]. Identity makes a correction a refresh of the SAME member."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _watch(conn, "2026-10-30", 80.0, -200.0)
    _tx(conn, "2026-10-30", 100)
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    assert len(first["opened"]) == 1, first
    case = store.get(first["opened"][0])
    assert len(case.exits) == 1 and case.exits[0]["price"] == 80.0, case.exits
    # The id is persisted, not just used: the next run must be able to recognise this exit after its price changes.
    assert case.exits[0]["source_id"] == "stopped_out_watch:1", case.exits[0]
    # The operator corrects the source row in place: same row, new price, no new row.
    conn.execute("UPDATE stopped_out_watch SET exit_price = 82.0 WHERE id = 1")
    conn.commit()
    second = fc.run(store, conn, today=TODAY, now=NOW)
    assert second["opened"] == [], second
    after = store.get(case.case_key)
    assert len(after.exits) == 1, f"a corrected price must refresh, never duplicate: {after.exits}"
    assert after.exits[0]["price"] == 82.0, after.exits
    assert after.realized_pnl == pytest.approx(-200.0), after.realized_pnl
    conn.close()


def test_f16_two_distinct_ids_at_the_same_price_stay_two_exits(store):
    """The other half: equality is not identity. Two rows with different ids and the SAME day, price, quantity and
    P&L are two economic exits and must not be collapsed into one."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _watch(conn, "2026-10-30", 80.0, -100.0)
    _watch(conn, "2026-10-30", 80.0, -100.0)   # a second row: different id, identical everything else
    _tx(conn, "2026-10-30", 100)
    _positions(conn, 0)
    conn.commit()
    out = fc.run(store, conn, today=TODAY, now=NOW)
    assert len(out["opened"]) == 1, out
    case = store.get(out["opened"][0])
    assert len(case.exits) == 2, f"two established identities must stay two exits: {case.exits}"
    assert len({e["source_id"] for e in case.exits}) == 2, case.exits
    conn.close()


def test_f16_the_unknown_pnl_sibling_becomes_known_when_the_same_identity_is_corrected(store):
    """ACCEPTANCE CONDITION. An exit persisted with an UNKNOWN P&L, later corrected on the SAME identity to a known
    -12,000, must become known (T1) — not stay UNKNOWN because an old unknown exit survives beside the new one."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _watch(conn, "2026-10-30", 80.0, None)          # realized P&L unknown at first
    _tx(conn, "2026-10-30", 100)
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(first["opened"][0])
    assert case.realized_pnl is None, case.realized_pnl          # genuinely unknown, not zero
    # The broker's own correction lands on the SAME row, which is the normal path (ON CONFLICT (dedupe_key) DO UPDATE).
    conn.execute("UPDATE stopped_out_watch SET realized_pnl = -12000 WHERE id = 1")
    conn.commit()
    second = fc.run(store, conn, today=TODAY, now=NOW)
    assert second["opened"] == [], second
    after = store.get(case.case_key)
    assert len(after.exits) == 1, f"a correction must not leave a stale sibling: {after.exits}"
    assert after.realized_pnl == pytest.approx(-12000.0), after.realized_pnl
    assert after.materiality_tier == "T1", after.materiality_tier
    conn.close()


def test_f16_an_identity_that_cannot_be_established_makes_the_pass_incomplete(store):
    """ACCEPTANCE CONDITION. When identity cannot be established the pass must not call itself complete: both
    observations are retained and the gap says the link is unresolved."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    # A sale with NO dedupe_key: the source gives this row no identity at all.
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account) "
                 "VALUES ('2026-10-30','SELL','SPCX',100,80.0,'schwab_taxable')")
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(first["opened"][0])
    assert len(case.exits) == 1 and case.exits[0]["source_id"] is None, case.exits
    # Re-reading the same unidentified state: pairing by price is all that is left, and it proves nothing.
    second = fc.run(store, conn, today=TODAY, now=NOW)
    after = store.get(case.case_key)
    assert len(after.exits) == 1, f"an unresolved pair must not duplicate the observation: {after.exits}"
    assert second["complete"] is False, f"an unestablished identity must not report a complete pass: {second}"
    assert any("provisional" in g or "unresolved" in g for g in second["gaps"]), second["gaps"]
    conn.close()


def test_f16_a_date_correction_on_the_same_id_updates_the_member_not_a_second_one(store):
    """codex's class BLOCK at b982142ee. The SAME source id with its DATE corrected (10-27 -> 10-28) used to become
    two persisted members both carrying that id: -200 became -400 with complete=True, gaps=[]. Membership is now
    resolved by identity before any date is consulted, so a date correction updates the member it belongs to."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _watch(conn, "2026-10-27", 80.0, -200.0)     # id 1; no trade row, so only the watch source speaks
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(first["opened"][0])
    assert len(case.exits) == 1 and case.exits[0]["date"] == "2026-10-27", case.exits
    # The broker corrects the DATE on the same row: no INSERT, same id.
    conn.execute("UPDATE stopped_out_watch SET stopped_out_at = '2026-10-28' WHERE id = 1")
    conn.commit()
    second = fc.run(store, conn, today=TODAY, now=NOW)
    assert second["opened"] == [], second
    after = store.get(case.case_key)
    assert len(after.exits) == 1, f"a corrected date must update the member, never mint a second: {after.exits}"
    assert after.exits[0]["date"] == "2026-10-28", after.exits
    assert after.exits[0]["source_id"] == "stopped_out_watch:1", after.exits
    assert after.realized_pnl == pytest.approx(-200.0), after.realized_pnl
    conn.close()


def test_f16_cross_source_same_event_is_unresolved_not_two_confident_members(store):
    """codex I7 class BLOCK. A tx-only event persists as one member; later the watch lane records an observation for
    the same exit. There is NO declared crosswalk between trade_transactions and stopped_out_watch, so the honest
    answer is an explicit unresolved record with both observations retained — never two confident members and never a
    quiet complete pass."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account, dedupe_key) "
                 "VALUES ('2026-10-30','SELL','SPCX',100,80.0,'schwab_taxable','k1')")
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(first["opened"][0])
    assert len(case.exits) == 1 and case.exits[0]["source"] == "trade_transactions", case.exits
    # The watch lane now records the same exit that the transaction already described.
    _watch(conn, "2026-10-30", 80.0, -200.0)
    conn.commit()
    second = fc.run(store, conn, today=TODAY, now=NOW)
    after = store.get(case.case_key)
    assert len(after.exits) == 2, f"both observations must be retained: {after.exits}"
    assert second["complete"] is False, f"an undeclared cross-source link must not report a complete pass: {second}"
    assert any("crosswalk" in g for g in second["gaps"]), second["gaps"]
    conn.close()


def test_i12_creation_without_a_source_identity_is_reported_not_silent(store):
    """codex I12 at ce917: the FIRST creation of a case from an observation with no source identity reported
    complete=True with no identity diagnostic. The P&L and stop gaps were already honest; the identity gap was not.
    Unknown identity must be stated, never a quiet gap-free sum."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    # A sale whose dedupe_key is NULL: the source gives this observation no identity at all.
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account) "
                 "VALUES ('2026-10-30','SELL','SPCX',100,80.0,'schwab_taxable')")
    _positions(conn, 0)
    conn.commit()
    out = fc.run(store, conn, today=TODAY, now=NOW)
    assert out["opened"], out
    assert out["complete"] is False, f"an unidentifiable creation must not report a complete pass: {out}"
    assert any("identity" in g for g in out["gaps"]), out["gaps"]
    conn.close()


def test_i12_an_existing_case_the_read_did_not_cover_is_not_silently_unchecked(store):
    """codex I12 at ce917: a case that exists but receives no observation took an early return that bypassed coverage
    accounting, so 'empty' silently meant 'unchecked'. A missing source observation is not evidence of deletion — it
    is unconfirmed, and the pass must say so."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _watch(conn, "2026-10-27", 80.0, -200.0)      # id 1 -> the case's only member
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(first["opened"][0])
    assert len(case.exits) == 1, case.exits
    # That observation is gone from the source, and the symbol is still enumerated by a later transaction.
    conn.execute("DELETE FROM stopped_out_watch")
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account, dedupe_key) "
                 "VALUES ('2026-10-30','SELL','SPCX',50,81.0,'schwab_taxable','k2')")
    conn.commit()
    second = fc.run(store, conn, today=TODAY, now=NOW)
    assert second["complete"] is False, f"an uncovered existing case must not pass as checked: {second}"
    conn.close()


def test_i12_a_legacy_member_and_an_identified_read_of_the_same_exit_are_unresolved(store):
    """codex I12 legacy -> identified. A member PERSISTED before identity existed (no source_id) plus an identified read
    of the same exit became TWO members and -400 instead of -200, reporting complete=True. There is no evidence linking
    them, so the pair is UNRESOLVED: both observations retained, the pass incomplete, no link guessed by date or price."""
    import dataclasses
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _watch(conn, "2026-10-30", 80.0, -200.0)
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(first["opened"][0])
    assert len(case.exits) == 1 and case.exits[0]["source_id"] == "stopped_out_watch:1", case.exits
    # Rewrite the stored case as a store written BEFORE identity existed: same facts, no id.
    legacy = [{k: v for k, v in e.items() if k != "source_id"} for e in case.exits]
    store.upsert(dataclasses.replace(case, exits=legacy))
    assert store.get(case.case_key).exits[0].get("source_id") is None
    # An IDENTIFIED read of the same exit now arrives.
    second = fc.run(store, conn, today=TODAY, now=NOW)
    after = store.get(case.case_key)
    assert len(after.exits) == 2, f"both observations must be retained: {after.exits}"
    assert second["complete"] is False, f"an unproven legacy link must not pass as complete: {second}"
    assert any("persisted before source identity existed" in g for g in second["gaps"]), second["gaps"]
    conn.close()


def test_i1_a_quantity_correction_on_the_same_trade_row_is_unresolved_not_two_members(store):
    """codex I1 provider-key BLOCK. dedupe_key is date|action|symbol|quantity|account|uid, so a quantity correction
    necessarily produces a NEW key: one trade row corrected 5.000 -> 7.000 became TWO persisted members (5 and 7)
    with complete=True. The composite is not an identity, and no provider uid is exposed as a field to use instead —
    so the honest result is both observations retained and the pass reported incomplete, with no delimiter guess."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account, dedupe_key) "
                 "VALUES ('2026-10-30','SELL','SPCX',5.0,80.0,'schwab_taxable','2026-10-30|SELL|SPCX|5.000|schwab_taxable|uid1')")
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(first["opened"][0])
    assert len(case.exits) == 1 and case.exits[0]["source"] == "trade_transactions", case.exits
    # The provider corrects the quantity in place; the composite key changes with it.
    conn.execute("UPDATE trade_transactions SET quantity = 7.0, "
                 "dedupe_key = '2026-10-30|SELL|SPCX|7.000|schwab_taxable|uid1'")
    conn.commit()
    second = fc.run(store, conn, today=TODAY, now=NOW)
    after = store.get(case.case_key)
    # With no provider identity reachable for this source, the observation stays unidentified: it is reconciled to the
    # stored member ONLY by the labelled date+price fallback, so there is no duplicate — and the pass must say so
    # rather than call itself complete, because the link is not established (codex I1 / contract I12).
    assert len(after.exits) == 1, f"a non-identity source must not duplicate the observation: {after.exits}"
    assert second["complete"] is False, f"a provisional link must not pass as complete: {second}"
    assert any(("provisional" in g or "identity" in g or "composite" in g) for g in second["gaps"]), second["gaps"]
    conn.close()


def test_i12_an_ambiguous_identity_stays_unresolved_across_three_passes(store):
    """codex narrow BLOCK, the shape that forgets. A tx-only member exists; a watch observation of the same exit then
    arrives and the pass correctly reports the undeclared cross-source ambiguity. On the NEXT pass nothing new happens
    to detect — the observations already pair — and the head reported complete=True with gaps=[]. The property is STAY
    UNRESOLVED UNTIL RESOLVED: every later identical pass must say the same thing."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account, dedupe_key) "
                 "VALUES ('2026-10-30','SELL','SPCX',100,80.0,'schwab_taxable','k1')")
    _positions(conn, 0)
    conn.commit()
    fc.run(store, conn, today=TODAY, now=NOW)          # pass 1: tx-only member
    _watch(conn, "2026-10-30", 80.0, -200.0)           # the watch lane now sees the same exit
    conn.commit()
    seen = []
    for _ in range(3):                                  # passes 2, 3, 4 must all say unresolved
        out = fc.run(store, conn, today=TODAY, now=NOW)
        seen.append(out["complete"])
    assert seen == [False, False, False], f"the ambiguity was forgotten on a later pass: {seen}"
    case = store.get(out["cases"][0]["case_key"])
    assert any("IDENTITY-UNRESOLVED" in g for g in case.gaps), f"no durable record on the row: {case.gaps}"
    conn.close()


def test_i12_an_existing_case_keeps_reporting_unresolved_when_closed_and_reentered(store):
    """The same durable ambiguity must survive the case changing state: open, closed, re-entered."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account, dedupe_key) "
                 "VALUES ('2026-10-30','SELL','SPCX',100,80.0,'schwab_taxable','k1')")
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    key = first["cases"][0]["case_key"]
    _watch(conn, "2026-10-30", 80.0, -200.0)
    conn.commit()
    assert fc.run(store, conn, today=TODAY, now=NOW)["complete"] is False
    for state in ("CLOSED", "RE_ENTERED", "CLOSED"):
        store.set_state(key, state)
        out = fc.run(store, conn, today=TODAY, now=NOW)
        assert out["complete"] is False, f"a {state} case forgot its unresolved identity: {out}"
    conn.close()


@pytest.mark.parametrize("state", [None, "CLOSED", "RE_ENTERED"])
def test_f1_a_later_unidentified_arrival_is_reported_in_every_case_state(store, state):
    """codex F1 at eac2895b2: an identified exit first, then a LATER transaction-only exit with no identity and no
    watch row, arriving through the unassigned path (extend an open case, or open a new one). The arrival pass reported
    complete=true with no identity diagnostic, across OPEN, CLOSED and RE_ENTERED; the same final source delivered all
    at once reported false. Batching must not change completeness."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _watch(conn, "2026-10-27", 80.0, -200.0)
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    key = first["cases"][0]["case_key"]
    assert first["complete"] is True, first["gaps"]
    if state:
        store.set_state(key, state)
    # the later exit: transaction-only, no watch row, and this source exposes no identity for its rows
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account) "
                 "VALUES ('2026-11-02','SELL','SPCX',50,81.0,'schwab_taxable')")
    conn.commit()
    second = fc.run(store, conn, today=TODAY, now=NOW)
    assert second["complete"] is False, (
        f"{state or 'OPEN'}: a later unidentified arrival passed as complete: {second['gaps']}")
    assert any("identity" in g for g in second["gaps"]), second["gaps"]
    # and it stays that way on an unchanged third pass
    third = fc.run(store, conn, today=TODAY, now=NOW)
    assert third["complete"] is False, third["gaps"]
    conn.close()


# ── the broker reference becomes an identity (operator 2026-11-04) ───────────────────────────────────────────
def _tx_uid(conn, day, qty, price, uid, symbol="SPCX", account="schwab_taxable"):
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account, provider_uid) "
                 "VALUES (?,?,?,?,?,?,?)", (day, "SELL", symbol, qty, price, account, uid))


def test_a_provider_uid_resolves_a_price_correction_to_one_member(store):
    """With a real broker reference the correction is an IDENTITY match: one member, and the pass is complete because
    the identity is established — not an unresolved provisional pairing."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _tx_uid(conn, "2026-10-30", 100, 80.0, "uid-1")
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(first["opened"][0])
    assert case.exits[0]["source_id"] == "trade_transactions:uid-1", case.exits
    assert first["complete"] is True, first["gaps"]
    conn.execute("UPDATE trade_transactions SET price = 82.0 WHERE provider_uid = 'uid-1'")
    conn.commit()
    second = fc.run(store, conn, today=TODAY, now=NOW)
    after = store.get(case.case_key)
    assert len(after.exits) == 1, f"an identified correction must never mint a member: {after.exits}"
    assert after.exits[0]["price"] == 82.0, after.exits
    assert second["complete"] is True, second["gaps"]
    conn.close()


def test_a_provider_uid_resolves_a_share_and_a_date_correction(store):
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _tx_uid(conn, "2026-10-30", 100, 80.0, "uid-2")
    _positions(conn, 0)
    conn.commit()
    first = fc.run(store, conn, today=TODAY, now=NOW)
    key = first["opened"][0]
    conn.execute("UPDATE trade_transactions SET quantity = 120 WHERE provider_uid = 'uid-2'")
    conn.commit()
    fc.run(store, conn, today=TODAY, now=NOW)
    conn.execute("UPDATE trade_transactions SET trade_date = '2026-11-02' WHERE provider_uid = 'uid-2'")
    conn.commit()
    third = fc.run(store, conn, today=TODAY, now=NOW)
    after = store.get(key)
    assert len(after.exits) == 1, f"share and date corrections are the same member: {after.exits}"
    assert after.exits[0]["shares"] == 120, after.exits
    assert after.exits[0]["date"] == "2026-11-02", after.exits
    assert third["complete"] is True, third["gaps"]
    conn.close()


def test_a_transaction_with_no_provider_uid_is_unresolved_and_never_guessed(store):
    """NULL provider_uid is a fact, not a missing value: no date/price/arrival/composite fallback, ever."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    conn.execute("INSERT INTO trade_transactions (trade_date, action, symbol, quantity, price, account) "
                 "VALUES ('2026-10-30','SELL','SPCX',100,80.0,'schwab_taxable')")
    _positions(conn, 0)
    conn.commit()
    out = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(out["opened"][0])
    assert case.exits[0]["source_id"] is None, case.exits
    assert out["complete"] is False, out
    assert any("identity" in g for g in out["gaps"]), out["gaps"]
    conn.close()


def test_two_different_provider_uids_stay_two_even_when_every_detail_matches(store):
    """The over-correction control: identity, not equality, decides."""
    from lib.recovery_engine import fills_consumer as fc
    conn = _source_db()
    _tx_uid(conn, "2026-10-30", 100, 80.0, "uid-a")
    _tx_uid(conn, "2026-10-30", 100, 80.0, "uid-b")
    _positions(conn, 0)
    conn.commit()
    out = fc.run(store, conn, today=TODAY, now=NOW)
    case = store.get(out["opened"][0])
    assert len(case.exits) == 2, f"two established identities must stay two: {case.exits}"
    assert len({e["source_id"] for e in case.exits}) == 2, case.exits
    conn.close()
