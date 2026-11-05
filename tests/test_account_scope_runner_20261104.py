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


# ── F1/F2 of the #2603 BLOCK (cc-deepseek-3, cc-deepseek-6): the persisted row must survive two accounts ──────────
from datetime import datetime, timezone  # noqa: E402

_WED = datetime(2026, 11, 5, 5, 56, 31, tzinfo=timezone.utc)


def test_G_one_symbol_in_two_accounts_gets_two_decision_ids():
    """cc-deepseek-6's P1: the decision id carried no account, so two rows collided on the primary key."""
    a = runner.decision_id({"symbol": "SPCX", "account": "schwab_ira"}, now=_WED)
    b = runner.decision_id({"symbol": "SPCX", "account": "schwab_individual"}, now=_WED)
    assert a != b, f"both accounts produced {a} — the second INSERT would violate cio_decisions_pkey"
    assert a.startswith("cio-entry-") and b.startswith("cio-entry-"), "the prefix consumers exclude by must survive"
    # the same row twice is the same decision: the id is stable within one account
    assert runner.decision_id({"symbol": "SPCX", "account": "schwab_ira"}, now=_WED) == a


def test_H_the_prospect_writer_is_handed_symbols_not_evidence_keys():
    """cc-deepseek-3's F2: `prior` is keyed by bare symbol, so a scoped key never matched and "SPCX|acct" was passed."""
    results = {
        "SPCX|schwab_ira": {"symbol": "SPCX", "state": "BUY_READY"},
        "SPCX|schwab_individual": {"symbol": "SPCX", "state": "BUY_READY"},
        "V|schwab_ira": {"symbol": "V", "state": "ENTRY_NEAR"},
    }
    prior = {"SPCX|schwab_ira": "BUY_READY", "SPCX|schwab_individual": "BUY_READY", "V|schwab_ira": "ENTRY_NEAR"}
    changed = runner.changed_symbols(results, prior=prior)
    assert changed == [], f"unchanged rows were reported changed: {changed}"
    prior = {"SPCX|schwab_ira": "ENTRY_NEAR", "SPCX|schwab_individual": "BUY_READY", "V|schwab_ira": "ENTRY_NEAR"}
    changed = runner.changed_symbols(results, prior=prior)
    assert changed == ["SPCX"], f"expected the bare changed symbol once, got {changed}"
    assert all("|" not in s for s in changed), "an evidence key reached the prospect writer"


# ── The f65cfebac BLOCK (cx-openai-3 CX3-S-F1..F4, cx-openai-2 F1..F3) ──────────────────────────────


class _FakeConn:
    """A connection whose SQL never executes; main() only needs execute/commit/rollback."""

    def cursor(self):
        class _Cursor:
            def execute(self, sql, params=None):  # noqa: D401 - fixture
                self.sql, self.params = sql, params

            def fetchall(self):
                return []
        return _Cursor()

    def commit(self):
        pass

    def rollback(self):
        pass


def _evidence(account):
    return {"symbol": "SPCX", "account": account, "price": 100.0, "quote_age_h": 0.2,
            "entry_low": 95.0, "entry_high": 105.0, "stop": 90.0, "target": 140.0, "atr": 3.0,
            "held": False, "plan_source": "reentry_desk"}


def test_I_a_symbol_wide_held_flag_does_not_hold_another_account(state):
    """CX3-S-F1 / CX2-F1: an inherited held=True on a named B row must not survive A-only holdings."""
    state([_row("SPCX", "schwab_ira", held=True)],
          [{"symbol": "SPCX", "account": "schwab_individual", "shares": 12}])
    ev = runner.gather(ScriptedCursor(symbols=["SPCX"]))
    e = ev["SPCX|schwab_ira"]
    assert e["held"] is False, "the inherited symbol-wide flag defeated the scoped lookup"
    assert e["held_evidence"] == "CONFIRMED"
    result = ces.evaluate(e)
    assert result["held"] is False
    header = ces.render_operator(result, e).splitlines()[0]
    assert "already owned" not in header and "add decision required" not in header, header

    # truly held in this account: the positive control
    state([_row("SPCX", "schwab_ira", held=False)],
          [{"symbol": "SPCX", "account": "schwab_ira", "shares": 5}])
    ev = runner.gather(ScriptedCursor(symbols=["SPCX"]))
    assert ev["SPCX|schwab_ira"]["held"] is True
    assert ev["SPCX|schwab_ira"]["held_evidence"] == "CONFIRMED"

    # unscoped control: held somewhere, and the reader is told where
    state([_row("SPCX", held=False)],
          [{"symbol": "SPCX", "account": "schwab_individual", "shares": 12}])
    ev = runner.gather(ScriptedCursor(symbols=["SPCX"]))
    assert ev["SPCX"]["held"] is True
    assert ev["SPCX"]["held_accounts"] == ["schwab_individual"]


def test_J_alert_history_and_prior_state_are_account_scoped():
    """CX3-S-F2 / CX2-F3: account A's delivered alert must not suppress account B's."""
    day = _WED.date()
    a = {"symbol": "SPCX", "account": "schwab_ira", "state": "BUY_READY"}
    b = {"symbol": "SPCX", "account": "schwab_individual", "state": "BUY_READY"}
    assert ces.transition_key(a, day=day) != ces.transition_key(b, day=day)
    legacy = f"cio_entry:SPCX:BUY_READY:{day.isoformat()}"
    assert ces.transition_key({"symbol": "SPCX", "state": "BUY_READY"}, day=day) == legacy

    done = {ces.transition_key(a, day=day)}
    assert runner.alert_worthy([b], {}, done, set()) == [b], "A's delivered alert suppressed B"
    assert runner.alert_worthy([b], {}, {ces.transition_key(b, day=day)}, set()) == [], "a repeat of B must be suppressed"

    class _Rows:
        def execute(self, sql, params=None):
            self.sql = sql

        def fetchall(self):
            return [("SPCX", "schwab_ira", "BUY_READY"), ("SPCX", "", "NOT_YET")]

    assert runner.last_states(_Rows()) == {"SPCX|schwab_ira": "BUY_READY", "SPCX": "NOT_YET"}

    # an ENTRY_NEAR row is not suppressed by another account's BUY_READY prior state
    near = {"symbol": "SPCX", "account": "schwab_individual", "state": "ENTRY_NEAR"}
    assert runner.alert_worthy([near], {"SPCX|schwab_ira": "BUY_READY"}, set(), {"SPCX"}) == [near]


def test_K_two_accounts_keep_their_own_review_and_packet(tmp_path, monkeypatch):
    """CX3-S-F3 / CX2-F2: reviews and durable packets are keyed by scoped identity."""
    monkeypatch.setattr(runner, "PACKET_DIR", tmp_path / "packets")
    from lib import cio_options_fluency
    monkeypatch.setattr(
        cio_options_fluency, "build_buy_ready_packet",
        lambda result, ev: {"symbol": result["symbol"], "account": result.get("account"),
                            "state": result.get("state")})
    runner.save_packet({"symbol": "SPCX", "account": "schwab_ira", "state": "BUY_READY"}, {})
    runner.save_packet({"symbol": "SPCX", "account": "schwab_individual", "state": "BUY_READY"}, {})
    files = sorted(p.name for p in (tmp_path / "packets").glob("*.json"))
    assert files == ["SPCX|schwab_individual.json", "SPCX|schwab_ira.json"], files
    saved = json.loads((tmp_path / "packets" / "SPCX|schwab_ira.json").read_text())
    assert saved["account"] == "schwab_ira", "the account did not survive into the durable packet"

    # main --apply: each account's review is recorded against that account
    seen: list[tuple] = []
    monkeypatch.setattr(runner, "_conn", lambda: _FakeConn())
    monkeypatch.setattr(runner, "gather", lambda cur: {
        "SPCX|schwab_ira": _evidence("schwab_ira"),
        "SPCX|schwab_individual": _evidence("schwab_individual"),
    })
    monkeypatch.setattr(runner, "last_states", lambda cur: {})
    monkeypatch.setattr(runner, "alerted_today", lambda cur, keys: set())
    monkeypatch.setattr(runner, "starred_symbols", lambda cur: set())
    monkeypatch.setattr(
        runner, "prepare_packet_inputs",
        lambda r, ev, apply: {"status": "OK", "symbol": r["symbol"],
                              "account": r.get("account"), "marker": r.get("account")})
    monkeypatch.setattr(runner, "record_review",
                        lambda cur, review, result: seen.append((review["marker"], result.get("account"))))
    monkeypatch.setattr(runner, "send_alerts", lambda r, ev: {})
    monkeypatch.setattr(runner, "save_packet", lambda r, ev: None)
    monkeypatch.setattr(runner, "follow_up_pending_reviews", lambda cur, ev: [])
    monkeypatch.setattr(runner, "write_cio_prospects", lambda changed: {})
    monkeypatch.setattr(runner, "RECEIPT", tmp_path / "receipt.json")
    monkeypatch.setattr(sys, "argv", ["cio_entry_state_runner", "--apply"])

    assert runner.main() == 0
    assert sorted(seen) == [("schwab_individual", "schwab_individual"),
                            ("schwab_ira", "schwab_ira")], seen


def test_L_follow_up_rows_keep_both_accounts(tmp_path, monkeypatch):
    """CX3-S-F3: the pending-review queue is keyed by scoped identity, not symbol."""
    pending = tmp_path / "pending.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"symbol": "SPCX", "account": "schwab_ira", "state": "BUY_READY", "queued_at": now,
         "result": {"symbol": "SPCX", "account": "schwab_ira", "state": "BUY_READY"}, "status": "PENDING"},
        {"symbol": "SPCX", "account": "schwab_individual", "state": "BUY_READY", "queued_at": now,
         "result": {"symbol": "SPCX", "account": "schwab_individual", "state": "BUY_READY"}, "status": "PENDING"},
    ]
    pending.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    monkeypatch.setattr(runner, "REVIEW_PENDING", pending)
    seen: list[tuple] = []

    def _prep(result, ev, apply):
        seen.append((ev.get("account"), result.get("account")))
        return {"status": "PENDING"}

    monkeypatch.setattr(runner, "prepare_packet_inputs", _prep)
    evidence = {"SPCX|schwab_ira": {"symbol": "SPCX", "account": "schwab_ira"},
                "SPCX|schwab_individual": {"symbol": "SPCX", "account": "schwab_individual"}}
    out = runner.follow_up_pending_reviews(object(), evidence)
    assert sorted(seen) == [("schwab_individual", "schwab_individual"),
                            ("schwab_ira", "schwab_ira")], seen
    assert len(out) == 2
    assert len(pending.read_text().splitlines()) == 2, "one account's follow-up overwrote the other"


def test_M_unknown_holdings_evidence_is_not_an_absent_position():
    """CX3-S-F4: malformed/unknown evidence stays explicit, never READY/held=False."""
    row = {"symbol": "SPCX", "account": "schwab_ira", "held": True,
           "gates": [{"id": "fresh", "pass": True}], "price_age_h": 0.1}
    # No holdings source supplied: the row's own fact stands (legacy path).
    assert rs.reentry_row_status(row)["status"] == rs.HELD

    for doc in ({}, {"holdings": None}):
        status = rs.reentry_row_status(row, holdings_doc=doc)
        assert status["status"] == rs.UNKNOWN_STATUS, (doc, status)
        assert status["held_evidence"] == "UNKNOWN"

    # A holding for the symbol with no account cannot be attributed to this account.
    status = rs.reentry_row_status(row, holdings_doc={"holdings": [{"symbol": "SPCX", "shares": 3}]})
    assert status["status"] == rs.UNKNOWN_STATUS, status
    assert status["held_evidence"] == "SCOPE_UNKNOWN"

    # Confirmed-empty stays an affirmative, positive control.
    status = rs.reentry_row_status(dict(row, held=False), holdings_doc={"holdings": []})
    assert status["status"] == rs.READY, status
    assert status["held_evidence"] == "CONFIRMED"


def test_N_the_served_projection_marks_an_unreadable_store_unknown(monkeypatch):
    """CX3-S-F4: the served projection must not turn an unreadable holdings store into READY."""
    monkeypatch.setattr(rs, "_holdings_for_scope", lambda: {})
    payload = {"rows": [{"symbol": "SPCX", "account": "schwab_ira", "held": True,
                         "gates": [{"id": "fresh", "pass": True}], "price_age_h": 0.1}],
               "criteria": {"stale_hours": 6.0}}
    served = rs.reentry_projection(payload)
    row = served["rows"][0]
    assert row["status"] == rs.UNKNOWN_STATUS, row
    assert row["held_evidence"] == "UNKNOWN"


# ── codex-cloud BLOCK at fbe0582bf (P1 aliases, P2 unknown ownership, P2 packet scope, P2 re-key) ──────


def _plan_evidence(**kw):
    ev = {"symbol": "SPCX", "account": "schwab_ira", "price": 100.0, "quote_age_h": 0.2,
          "entry_low": 95.0, "entry_high": 105.0, "stop": 90.0, "target": 140.0,
          "held": False, "held_evidence": "SCOPE_UNKNOWN", "plan_source": "reentry_desk"}
    ev.update(kw)
    return ev


def test_O_unknown_ownership_blocks_the_entry_call():
    """codex-cloud P2 (account_scope:122): an unknown holding account must not become 'New position'.

    The state was BUY_READY, so the Telegram card rendered a green new-position review for a symbol
    that may already be owned. Unknown ownership cannot back an entry call.
    """
    result = ces.evaluate(_plan_evidence())
    assert result["state"] == "BLOCKED", f"unknown ownership still produced {result['state']}"
    assert "ownership" in (result["first_hard_block"] or "").lower(), result
    assert "BUY READY" not in ces.render_operator(result, _plan_evidence())

    # An unreadable holdings source is unknown too.
    assert ces.evaluate(_plan_evidence(held_evidence="UNKNOWN"))["state"] == "BLOCKED"

    # Positive control: a confirmed-absent position is still an ordinary new-position call.
    assert ces.evaluate(_plan_evidence(held_evidence="CONFIRMED"))["state"] == "BUY_READY"

    # A row whose own inherited fact says held is not blocked by the ownership guard.
    assert ces.evaluate(_plan_evidence(held=True, held_evidence="SCOPE_UNKNOWN"))["state"] == "BUY_READY"


def test_P_the_telegram_card_never_reads_unknown_ownership_as_a_new_position(monkeypatch):
    """codex-cloud P2: the formatter honoured only the boolean, so unknown rendered as 'New position'."""
    from lib import telegram_cards
    from lib.telegram_rich import cio_entry_alert
    base = {"symbol": "SPCX", "state": "BUY_READY", "held": False, "held_evidence": "SCOPE_UNKNOWN",
            "price": 100.0, "entry_low": 95.0, "entry_high": 105.0, "stop": 90.0, "target": 140.0,
            "rr": 2.33, "rr_at_ideal_entry": 2.33, "rr_at_current_price": 2.33, "cio_review_id": "rv-1"}
    msg = cio_entry_alert(dict(base))
    text = msg.render()["text"]
    assert "New position" not in text, text
    assert "OWNERSHIP UNVERIFIED" in text, text
    assert "Position status unavailable" in text, text
    assert msg.marker != "🟢", f"unknown ownership rendered as a green ready: {msg.marker}"

    # Confirmed absence keeps the affirmative new-position reading.
    ok = cio_entry_alert({**base, "held_evidence": "CONFIRMED"})
    assert "HIGH CONVICTION ENTRY" in ok.render()["text"]

    # The fallback (non-card) layout names the position too; it must not say New position.
    import importlib
    for mod in (telegram_cards, importlib.import_module("scripts.lib.telegram_cards")):
        monkeypatch.setattr(mod, "enabled", lambda *a, **kw: False)
    fallback = cio_entry_alert(dict(base)).render()["text"]
    assert "New position" not in fallback and "Position status unavailable" in fallback, fallback
    confirmed = cio_entry_alert({**base, "held_evidence": "CONFIRMED"}).render()["text"]
    assert "New position" in confirmed, confirmed


def _book_paths(tmp_path):
    holdings = {"holdings": [
        {"symbol": "SPCX", "account": "schwab_individual", "shares": 12, "market_value": 1200.0},
        {"symbol": "CASH", "account": "schwab_ira", "is_cash": True, "market_value": 500.0},
    ]}
    paths = {}
    for name, obj in (("holdings", holdings), ("correlation", {}),
                      ("options_monitor", {}), ("ips", {"constraints": {}})):
        f = tmp_path / f"{name}.json"
        f.write_text(json.dumps(obj))
        paths[name] = f
    return paths


def test_Q_portfolio_facts_are_scoped_to_the_candidate_account(tmp_path):
    """codex-cloud P2 (cio_options_fluency:1003): an IRA packet must not inherit an Individual hold."""
    from lib import buy_ready_portfolio_facts as bpf
    paths = _book_paths(tmp_path)

    ira = bpf.build_portfolio_facts("SPCX", account="schwab_ira", paths=paths)
    assert ira["held"] is False, "an Individual holding was counted as an IRA position"
    assert not ira["held_units_total"], ira
    assert ira["held_by_account"], "the reader lost where the symbol actually is"

    ind = bpf.build_portfolio_facts("SPCX", account="schwab_individual", paths=paths)
    assert ind["held"] is True and ind["held_units_total"] == 12.0
    # The declared alias is the same account.
    assert bpf.build_portfolio_facts("SPCX", account="schwab_taxable", paths=paths)["held"] is True


def test_Q2_the_packet_uses_scoped_ownership_for_a_named_account(tmp_path, monkeypatch):
    """codex-cloud P2: the packet's ownership_context/decision_action must follow the account."""
    from lib import cio_options_fluency
    from lib import buy_ready_portfolio_facts as bpf
    port = bpf.build_portfolio_facts("SPCX", account="schwab_ira", paths=_book_paths(tmp_path))
    result = {"symbol": "SPCX", "account": "schwab_ira", "state": "BUY_READY", "price": 100.0,
              "entry_low": 95.0, "entry_high": 105.0, "stop": 90.0, "target": 140.0, "held": False}
    packet = cio_options_fluency.build_buy_ready_packet(
        result, {"held": False, "portfolio_facts": port},
        desk={"by_symbol": {}}, goals=[], enrichment={})
    assert packet["ownership_context"]["held"] is False, packet["ownership_context"]
    assert packet["decision_action"] == "REVIEW_NEW_POSITION", packet["decision_action"]

    # A symbol-wide facts blob attached by an older caller cannot decide a named account either.
    symbol_wide = {"status": "OK", "held": True, "held_units_total": 12.0, "name_market_value": 1200.0}
    monkeypatch.setattr(cio_options_fluency, "_load_portfolio_facts",
                        lambda sym, account=None: {"status": "OK", "held": False, "account": account})
    packet = cio_options_fluency.build_buy_ready_packet(
        result, {"held": False, "portfolio_facts": symbol_wide},
        desk={"by_symbol": {}}, goals=[], enrichment={})
    assert packet["ownership_context"]["held"] is False, packet["ownership_context"]
    assert packet["decision_action"] == "REVIEW_NEW_POSITION", packet["decision_action"]


def test_R_prepare_packet_inputs_scopes_portfolio_facts_to_the_row(monkeypatch):
    """codex-cloud P2: the runner's own build must pass the candidate account."""
    from lib import buy_ready_portfolio_facts as bpf
    from lib import buy_ready_options_alternatives as boa
    from lib import buy_ready_cio_review as bcr
    calls = {}

    def fake_facts(sym, *, account=None, **kw):
        calls["sym"], calls["account"] = sym, account
        return {"status": "OK", "held": False, "account": account}

    monkeypatch.setattr(bpf, "build_portfolio_facts", fake_facts)
    monkeypatch.setattr(boa, "live_alternatives", lambda plan, **kw: {"status": "OPTIONS_ALT_NONE"})
    monkeypatch.setattr(bcr, "review_packet", lambda packet, review_mode=None: {"status": "OK"})
    ev = {}
    runner.prepare_packet_inputs(
        {"symbol": "SPCX", "account": "schwab_ira", "state": "BUY_READY"}, ev, apply=False)
    assert calls == {"sym": "SPCX", "account": "schwab_ira"}, calls


def test_S_a_packet_supplied_account_rekeys_the_evidence_row(state):
    """codex-cloud P2 (runner:232): an inherited account must move the row to its scoped key.

    Left under the bare symbol, evidence_for(symbol, account) returned {} for pending-review retries
    and changed_symbols compared a bare key against scoped prior states, re-reporting every run.
    """
    state([_row("SPCX")], [{"symbol": "SPCX", "account": "schwab_ira", "shares": 5}])
    cur = ScriptedCursor(symbols=["SPCX"], packets={"SPCX": {"account": "schwab_ira"}})
    ev = runner.gather(cur)
    assert "SPCX" not in ev, f"the row stayed under the bare symbol: {list(ev)}"
    assert "SPCX|schwab_ira" in ev, list(ev)
    e = ev["SPCX|schwab_ira"]
    assert e["account"] == "schwab_ira"
    assert runner.evidence_for(ev, "SPCX", "schwab_ira") is e
    assert runner.changed_symbols({"SPCX|schwab_ira": {**e, "state": "BUY_READY"}},
                                  {"SPCX|schwab_ira": "BUY_READY"}) == []


def test_T_a_packet_account_joining_a_scoped_desk_row_keeps_one_row(state):
    """The re-key must not overwrite a row that already names the same account."""
    state([_row("SPCX"), _row("SPCX", "schwab_ira")], [])
    cur = ScriptedCursor(symbols=["SPCX"], packets={"SPCX": {"account": "schwab_ira"}})
    ev = runner.gather(cur)
    assert sorted(k for k in ev if k.startswith("SPCX")) == ["SPCX|schwab_ira"], list(ev)
    assert ev["SPCX|schwab_ira"]["account"] == "schwab_ira"
