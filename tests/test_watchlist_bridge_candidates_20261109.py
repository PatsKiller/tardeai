"""LQ-20261107-1658 / INC-261109-xqwzsp: the bridge's candidate statement and its one fallback.

ANCHOR: WATCHLIST_BRIDGE_CANDIDATES_1658_20261109

Synthetic fixtures only (public repo): symbols DEMOA/DEMOB/DEMOC/DEMOD, no live symbol, no live dollar
amount, no database, no network. The statement is exercised through a fake cursor, so the test proves the
PROMISES the incident broke rather than the runtime of any particular Postgres: the analyst source is read
in ONE set-based join (never a correlated scan per watchlist row), the statement runs under a budget, a
statement timeout downgrades the run exactly once and names what is missing, and a missing source never
becomes a rating.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import watchlist_proposal_bridge as b  # noqa: E402

ANCHOR = "WATCHLIST_BRIDGE_CANDIDATES_1658_20261109"
COVERS = ["scripts/watchlist_proposal_bridge.py"]

COLUMNS = [
    "symbol", "wl_status", "hermes_composite_score", "hermes_rank", "trend", "wl_source",
    "card_rec", "synth_rec", "analyst_rec",
    "limit_price", "entry_zone_low", "entry_zone_high", "entry_tag", "entry_urgency",
    "wl_strategy", "card_entry", "card_stop", "card_target", "card_support", "card_resistance", "card_rr",
]


def _row(symbol, card_rec=None, synth_rec=None, analyst_rec=None):
    values = dict.fromkeys(COLUMNS)
    values.update(symbol=symbol, wl_status="active", card_rec=card_rec, synth_rec=synth_rec,
                  analyst_rec=analyst_rec, wl_strategy="momentum_scalp")
    return tuple(values[c] for c in COLUMNS)


ROWS = [
    _row("DEMOA", card_rec="buy"),
    _row("DEMOB", synth_rec="strong_buy"),
    _row("DEMOC", analyst_rec="buy"),           # buy ONLY through the analyst source
    _row("DEMOD"),                              # no rating at all
]


class Canceled(Exception):
    """Stands in for psycopg2.errors.QueryCanceled (SQLSTATE 57014)."""


class Locked(Exception):
    """Stands in for psycopg2.errors.LockNotAvailable (SQLSTATE 55P03)."""


class FakeConn:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


class FakeCursor:
    """Records every statement; answers the two settings reads; raises where the test says."""

    def __init__(self, *, rows=None, fail_on_analyst=False, fail_on_fallback=False,
                 fail_on_analyst_with=None, fail_on_fallback_with=None):
        self.conn = FakeConn()
        self.statements = []
        self.settings = []
        self.rows = ROWS if rows is None else rows
        self.fail_on_analyst = fail_on_analyst
        self.fail_on_fallback = fail_on_fallback
        self.analyst_error = fail_on_analyst_with or Canceled("canceling statement due to statement timeout")
        self.fallback_error = fail_on_fallback_with or RuntimeError("the database is gone")
        self.description = [(c,) for c in COLUMNS]
        self._fallback = False

    # -- connection surface the module uses ------------------------------------------------
    @property
    def connection(self):
        return self.conn

    def execute(self, sql, params=None):
        if sql.startswith("SELECT current_setting"):
            self.statements.append(("setting-read", sql, params))
            return
        if sql.startswith("SELECT set_config"):
            self.statements.append(("setting-write", sql, params))
            self.settings.append(params[0])
            return
        self.statements.append(("candidate", sql, params))
        self._fallback = "analyst_data_history" not in sql
        if self.fail_on_analyst and "analyst_data_history" in sql:
            raise self.analyst_error
        if self.fail_on_fallback and "analyst_data_history" not in sql:
            raise self.fallback_error

    def fetchone(self):
        return ("3min",)

    def fetchall(self):
        # the fallback statement selects NULL::text AS analyst_rec, so the fixture's analyst column is
        # empty on that path — otherwise the fake would "return" a rating the real database would not
        fallback = self._fallback
        if not fallback:
            return list(self.rows)
        analyst = COLUMNS.index("analyst_rec")
        return [r[:analyst] + (None,) + r[analyst + 1:] for r in self.rows]

    # -- helpers ---------------------------------------------------------------------------
    def candidate_statements(self):
        return [s[1] for s in self.statements if s[0] == "candidate"]


# ---------------------------------------------------------------------------------------
# the shape of the statement
# ---------------------------------------------------------------------------------------

def test_the_analyst_source_is_one_set_based_join_not_a_correlated_scan():
    sql = b._candidate_sql()
    assert sql.count("analyst_data_history") == 1, "the analyst table must be read once, not once per row"
    assert "DISTINCT ON (upper(symbol))" in sql
    assert "ORDER BY upper(symbol), as_of DESC NULLS LAST" in sql, "latest row per symbol must keep the old rule"
    assert "WHERE UPPER(symbol) = UPPER(wi.symbol)" not in sql, "the correlated scan is the 145 s defect"
    assert sql.count("ad.symbol_key = upper(wi.symbol)") == 1


def test_the_symbol_filter_keeps_its_regex_quantifier():
    """A template that turns ``{1,5}`` into a set renders ``^[A-Z](1, 5)$`` — which matches nothing.

    That is exactly what an f-string did to this statement while the fix was being written: the read
    returned 0 candidates against live data whose ratings were intact. Both paths keep the literal.
    """
    for sql in (b._candidate_sql(), b._candidate_sql(with_analyst=False)):
        assert "'^[A-Z]{1,5}$'" in sql, "the symbol filter lost its quantifier"
        assert "(1, 5)" not in sql


def test_the_fallback_selects_the_same_columns_and_drops_only_the_analyst_source():
    with_analyst, without = b._candidate_sql(), b._candidate_sql(with_analyst=False)
    def aliases(sql):
        # the joined subquery's own aliases (symbol_key / recommendation_key) are not result columns
        return set(re.findall(r"\bAS (\w+)", sql)) - {"symbol_key", "recommendation_key"}
    assert aliases(with_analyst) == aliases(without), "a fallback with a different shape is a second query to maintain"
    assert "analyst_rec" in aliases(without) and "analyst_rec" in aliases(with_analyst)
    assert "analyst_data_history" not in without
    assert "NULL::text AS analyst_rec" in without, "the absent source must be an explicit null, never a guess"
    assert "DISTINCT ON" not in without


# ---------------------------------------------------------------------------------------
# the budget, the one fallback, and what is never downgraded
# ---------------------------------------------------------------------------------------

def test_the_statement_runs_under_the_budget_and_the_prior_value_is_restored():
    cur = FakeCursor()
    out = b._fetch_buy_candidates(cur)
    assert cur.settings == [f"{b.CANDIDATE_STATEMENT_BUDGET_S}s", "3min"], "set the budget, then restore the DB's own"
    assert out["degraded"] is None and out["elapsed_ms"] >= 0
    assert out["rows"] and all(r["watchlist_rating"] in b.BUY_RATINGS for r in out["rows"])


def test_a_statement_timeout_is_one_named_degradation_not_a_traceback():
    cur = FakeCursor(fail_on_analyst=True)
    out = b._fetch_buy_candidates(cur)
    assert out["degraded"] == b.DEGRADED_ANALYST_HISTORY == "analyst_data_history:statement_timeout"
    assert cur.conn.rollbacks == 1, "an aborted transaction must be cleared before the fallback runs"
    assert len(cur.candidate_statements()) == 2, "exactly one fallback attempt"
    symbols = [r["symbol"] for r in out["rows"]]
    assert symbols == ["DEMOA", "DEMOB"], "card and synthesis still rate; the analyst-only name cannot be rated now"


def test_a_missing_analyst_source_never_becomes_a_rating():
    """DEMOC is BUY only through analyst_data_history; with the source gone it must be dropped, not guessed."""
    healthy = b._fetch_buy_candidates(FakeCursor())["rows"]
    degraded = b._fetch_buy_candidates(FakeCursor(fail_on_analyst=True))["rows"]
    assert "DEMOC" in {r["symbol"] for r in healthy}
    assert "DEMOC" not in {r["symbol"] for r in degraded}
    assert all(r["watchlist_rating"] for r in degraded)


def test_a_lock_timeout_is_not_downgraded():
    """A lock means another writer holds a row; the fallback would meet the same lock."""
    cur = FakeCursor(fail_on_analyst=True, fail_on_analyst_with=Locked("canceling statement due to lock timeout"))
    with pytest.raises(Locked):
        b._fetch_buy_candidates(cur)
    assert len(cur.candidate_statements()) == 1, "a lock timeout must not fire the fallback"


def test_the_fallback_is_bounded_to_one_attempt():
    cur = FakeCursor(fail_on_analyst=True, fail_on_fallback=True)
    with pytest.raises(RuntimeError, match="the database is gone"):
        b._fetch_buy_candidates(cur)
    assert len(cur.candidate_statements()) == 2, "a second failure escalates; it never becomes a retry loop"


# ---------------------------------------------------------------------------------------
# the contract
# ---------------------------------------------------------------------------------------

def _gate():
    return json.loads((ROOT / "config" / "ci_gates" / "watchlist_bridge_candidates_1658_20261109.json").read_text())


def _lane_binding():
    cfg = json.loads((ROOT / "config" / "cron_outage_watchdog.json").read_text())
    return cfg["wrapper_bindings"]["watchlist-proposal-bridge"]


def test_the_budget_lives_in_the_operators_contract_and_the_code_agrees():
    gate = _gate()
    assert gate["schema"] == "CiGate@v1" and ANCHOR in gate["anchor"]
    t = gate["thresholds"]
    assert t["candidate_statement_budget_s"] == b.CANDIDATE_STATEMENT_BUDGET_S
    assert t["candidate_statement_budget_s"] < t["db_role_statement_ceiling_s"], "a budget at the ceiling is no budget"
    assert t["measured_before_ms"] > t["db_role_statement_ceiling_s"] * 9 // 10, "the defect must sit near the ceiling"
    assert t["measured_after_ms"] * 100 < t["candidate_statement_budget_s"] * 1000, "the fix must clear the budget 100x"
    assert "degraded" in " ".join(gate["verdict"]) and "ONE fallback" in " ".join(gate["verdict"])
    assert gate["files"] == ["tests/test_watchlist_bridge_candidates_20261109.py"]


def test_the_budget_is_a_fraction_of_the_lane_slot():
    """The lane fires every 30 min; a statement budget that cannot fit many times in the slot is not a budget."""
    expr = _lane_binding()["expression"]
    assert expr == "*/30 10-15 * * 1-5"
    schedule_minutes = int(expr.split()[0].split("/")[1])
    assert b.CANDIDATE_STATEMENT_BUDGET_S < schedule_minutes * 60 / 10


def test_no_order_vocabulary_in_the_statement():
    sql = b._candidate_sql().lower()
    assert not {"place_order", "order_id", "account_number"} & set(re.findall(r"[a-z_]+", sql))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
