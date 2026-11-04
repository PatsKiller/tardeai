"""ACCOUNT_SCOPE — the REAL caller (clearing condition for #2603, reviewers cx-openai-4 / cc-deepseek-9).

The earlier change was helper-only: `account_scope.held_for()` was correct, but `gather()` still keyed
evidence by symbol alone, never copied the account the desk row stated, and computed held against a
symbol-wide set. This file drives the actual caller — `cio_entry_state_runner.gather()` with a scripted
cursor — and the actual re-entry surface, `residual_surfaces.reentry_row_status()`, so a regression in the
wiring fails here, not only in a helper unit test.

Cases the reviewers named:
  A. A-only holdings + an explicit B candidate -> B is not held, and does not render the already-owned/add
     decision header.
  B. truly held B, and empty holdings, keep their correct outcomes (HELD / not held).
  C. two rows for the same symbol in different accounts survive, in either input order.
  D. an account-scoped re-entry surface does not become HELD from another account's residual.

Fixtures only: a scripted cursor, JSON files in a temporary state dir. No DB, no network, no broker.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import cio_entry_state_runner as runner  # noqa: E402
from lib import cio_entry_state as ces  # noqa: E402
from lib import residual_surfaces as rs  # noqa: E402


class ScriptedCursor:
    """Answers the runner's queries by what they ask for. No SQL is executed."""

    def __init__(self, *, symbols, plans=None, cards=None, packets=None):
        self.symbols = list(symbols)
        self.plans = plans or {}
        self.cards = cards or {}
        self.packets = packets or {}

    def execute(self, sql, params=None):  # noqa: D401 - small fixture
        self.sql = " ".join(str(sql).split())
        self.params = params

    def fetchall(self):
        q = self.sql
        if "UNION SELECT upper(symbol) FROM paper_trade_proposals" in q:
            return [(s,) for s in self.symbols]
        if "FROM watchlist_entry_plans" in q:
            return [tuple([s, *self.plans[s]]) for s in self.symbols if s in self.plans]
        if "FROM watchlist_strategy_cards" in q:
            return [tuple([s, *self.cards[s]]) for s in self.symbols if s in self.cards]
        if "FROM decision_packets" in q:
            return [(s, self.packets[s]) for s in self.symbols if s in self.packets]
        return []


@pytest.fixture()
def state(tmp_path, monkeypatch):
    """A temp state dir with holdings + desk rows, plus stubs for every non-cursor source."""
    def install(desk_rows, holdings_rows):
        (tmp_path / "ticker_enrichment_cache.json").write_text("{}")
        (tmp_path / "holdings.json").write_text(json.dumps({"holdings": holdings_rows}))
        desk = tmp_path / "desk.json"
        desk.write_text(json.dumps({"rows": desk_rows}))
        monkeypatch.setattr(runner, "STATE_DIR", tmp_path)
        monkeypatch.setattr(runner, "DESK_PATH", desk)

    from lib import entry_alert_context as eac
    from lib import alert_quotes
    monkeypatch.setattr(eac, "cio_review_fields", lambda row: {}, raising=False)
    monkeypatch.setattr(eac, "latest_cio_decisions", lambda cur, syms: {}, raising=False)
    monkeypatch.setattr(eac, "symbol_profiles", lambda cur, syms: {}, raising=False)
    monkeypatch.setattr(eac, "planner_plan_symbols", lambda cur: set(), raising=False)
    monkeypatch.setattr(eac, "single_sender_enabled", lambda: False, raising=False)
    monkeypatch.setattr(alert_quotes, "broker_quotes", lambda cur, syms: {}, raising=False)
    return install


def _row(symbol, account=None, **kw):
    row = {"symbol": symbol, "price": 100.0, "price_age_h": 0.2,
           "entry_low": 95.0, "entry_high": 105.0, "stop": 90.0, "target": 125.0, "atr": 3.0}
    if account:
        row["account"] = account
    row.update(kw)
    return row


def test_A_a_candidate_in_another_account_is_not_held(state):
    # Holdings only in account A; the desk candidate states account B.
    state([_row("SPCX", "schwab_ira")], [{"symbol": "SPCX", "account": "schwab_individual", "shares": 12}])
    ev = runner.gather(ScriptedCursor(symbols=["SPCX"]))

    assert "SPCX|schwab_ira" in ev, f"the stated account was not carried into the evidence key: {list(ev)}"
    e = ev["SPCX|schwab_ira"]
    assert e["account"] == "schwab_ira"
    assert e["held"] is False, "an Individual residual read as held for the IRA candidate"

    result = ces.evaluate(e)
    assert result["held"] is False
    header = ces.render_operator(result, e).splitlines()[0]
    assert "already owned" not in header, f"the add-decision header rendered for a not-held account: {header}"
    assert "add decision required" not in header


def test_B_a_held_account_and_an_empty_store_keep_their_outcomes(state):
    state([_row("SPCX", "schwab_ira")], [{"symbol": "SPCX", "account": "schwab_ira", "shares": 5}])
    ev = runner.gather(ScriptedCursor(symbols=["SPCX"]))
    assert ev["SPCX|schwab_ira"]["held"] is True
    assert ces.evaluate(ev["SPCX|schwab_ira"])["held"] is True

    state([_row("SPCX", "schwab_ira")], [])
    ev = runner.gather(ScriptedCursor(symbols=["SPCX"]))
    assert ev["SPCX|schwab_ira"]["held"] is False


def test_C_two_accounts_for_one_symbol_survive_in_either_order(state):
    holdings = [{"symbol": "SPCX", "account": "schwab_individual", "shares": 12}]
    for order in (("schwab_individual", "schwab_ira"), ("schwab_ira", "schwab_individual")):
        state([_row("SPCX", order[0]), _row("SPCX", order[1])], holdings)
        ev = runner.gather(ScriptedCursor(symbols=["SPCX"]))
        keys = {k for k in ev if str(k).startswith("SPCX")}
        assert keys == {"SPCX|schwab_individual", "SPCX|schwab_ira"}, f"order {order}: {sorted(keys)}"
        assert ev["SPCX|schwab_individual"]["held"] is True
        assert ev["SPCX|schwab_ira"]["held"] is False, "the second row inherited the first account's hold"


def test_D_the_reentry_surface_does_not_borrow_another_accounts_residual(state):
    holdings = {"holdings": [{"symbol": "SPCX", "account": "schwab_individual", "shares": 12}]}
    row = {"symbol": "SPCX", "account": "schwab_ira", "held": True,  # the symbol-wide boolean says held
           "gates": [{"id": "price_fresh", "pass": True}], "price_age_h": 0.2}

    status = rs.reentry_row_status(row, holdings_doc=holdings)
    assert status["status"] == rs.READY, f"an IRA row became {status['status']} from an Individual residual"
    assert status["held"] is False
    assert status["held_accounts"] == ["schwab_individual"]

    held_row = dict(row, account="schwab_individual")
    assert rs.reentry_row_status(held_row, holdings_doc=holdings)["status"] == rs.HELD
    assert rs.reentry_row_status(held_row, holdings_doc={"holdings": []})["status"] == rs.READY


def test_E_the_served_projection_decides_held_from_the_store(monkeypatch):
    """The production projection (what api_v2 serves) must not fall back to the desk's symbol-wide boolean."""
    holdings = {"holdings": [{"symbol": "SPCX", "account": "schwab_individual", "shares": 12}]}
    monkeypatch.setattr(rs, "_holdings_for_scope", lambda: holdings)
    payload = {
        "rows": [{"symbol": "SPCX", "account": "schwab_ira", "held": True,
                  "gates": [{"id": "price_fresh", "pass": True}], "price_age_h": 0.2}],
        "criteria": {"stale_hours": 6.0},
    }
    served = rs.reentry_projection(payload)
    row = served["rows"][0]
    assert row["status"] == rs.READY, f"the served projection rendered {row['status']} for an IRA row"
    assert row["held"] is False
    assert row["held_accounts"] == ["schwab_individual"]


def test_F_the_send_and_sample_paths_find_a_scoped_row_by_symbol(state):
    """cx-openai-4 R2: the alert/save/sample lookups must not KeyError on a SYN|account row."""
    holdings = [{"symbol": "SPCX", "account": "schwab_individual", "shares": 12}]
    for account in ("schwab_ira", "schwab_individual"):   # A-only residual, then a genuinely held account
        state([_row("SPCX", account)], holdings)
        ev = runner.gather(ScriptedCursor(symbols=["SPCX"]))
        assert list(ev) == [f"SPCX|{account}"]
        result = ces.evaluate(ev[f"SPCX|{account}"])

        # The three call sites in main() that only know the result (they used to do evidence["SPCX"]).
        entry = runner.evidence_for(ev, result["symbol"])
        assert entry is ev[f"SPCX|{account}"]
        # And the follow-up path, which only knows the recorded symbol.
        assert runner.evidence_for(ev, "SPCX") is ev[f"SPCX|{account}"]
        assert runner.evidence_for(ev, "NOPE") == {}
