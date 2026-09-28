"""Options order gates (operator work order 2026-09-27, PR 3).

An options ORDER could be created from an 'approved' queue row alone: the submit-mode risk
evaluator skipped quote/chain age, market session and buying power whenever they were
ABSENT (and the engine never stamped them); a missing liquidity dict passed; an approval
survived a changed long leg (spread ids named only the short strike) and an archived
thesis (abandoned ideas were dropped BEFORE the queue sync); approvals never expired; and
/api/v2/options/preflight re-ran no desk gate before building an intent.

Everything here is desk layer. Hermetic: no psycopg2, no network, no LLM; the queue row,
the thesis store and the brokers.* modules are in-memory fakes / MagicMocks, and the
api_v2 test asserts the broker stubs are NEVER called.

    .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_options_order_gates_20260927.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import options_desk_enterprise as ent  # noqa: E402
from lib.options_thesis import OptionsThesisStore  # noqa: E402

# Monday 2026-09-28 15:00Z = 11:00 ET -> REGULAR session (lib.canonical_observation.market_session).
NOW = datetime(2026, 9, 28, 15, 0, tzinfo=timezone.utc)
GUID = "optstrat-dell-put-spread-1"
PID = "opt_credit_spread_DELL_rollover_522p5000_l497p5000_20261120_d20260928"
CFG = ent.load_desk_config()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _leg(role, strike, *, quote_age_s=30, oi=400, spread_pct=5.0):
    mid = 30.0
    half = mid * spread_pct / 200.0
    return {"role": role, "strike": strike, "bid": round(mid - half, 2), "ask": round(mid + half, 2), "mid": mid,
            "open_interest": oi, "volume": 150, "spread_pct": spread_pct, "two_sided": True,
            "quote_time": _iso(NOW - timedelta(seconds=quote_age_s)) if quote_age_s is not None else None}


def _proposal(**over):
    """A valid DELL put credit spread as the desk holds it (everything the gate needs present)."""
    legs = [_leg("short put", 522.5), _leg("long put", 497.5)]
    p = {
        "id": PID, "symbol": "DELL", "underlying": "DELL", "strategy": "credit_spread", "account": "rollover",
        "option_type": "put", "short_strike": 522.5, "long_strike": 497.5, "strike": 522.5,
        "expiration": "2026-11-20", "dte": 53, "contracts": 1, "occ_symbol": "DELL  261120P00522500",
        "premium": 6.35, "premium_total": 635.0, "net_credit": 6.35, "max_profit": 635.0, "max_loss": 1865.0,
        "underlying_price": 563.0, "option_strategy_guid": GUID, "data_source": "schwab_chain",
        "legs_liquidity": legs,
        "chain_fetched_at": _iso(NOW - timedelta(seconds=60)),
        "market_session": "REGULAR",
        "thesis_blocks": [],
        "cio_decision": {"outcome": "APPROVE", "decision_guid": "dec-1"},
        # The desk never reads buying power (broker read). The positive control supplies it
        # as a granted layer would; the buying-power test removes it.
        "buying_power": 50_000,
        "enterprise": {
            "tier": "A", "live_eligible": True, "blocks": [],
            "earnings": {"in_blackout": False, "symbol": "DELL"},
            "liquidity": {"pass": True, "issues": [],
                          "legs": [{"pass": True, "issues": [], "role": "short put", "strike": 522.5},
                                   {"pass": True, "issues": [], "role": "long put", "strike": 497.5}]},
        },
    }
    p.update(over)
    return p


def _store(tmp_path, *, record=True, decision="APPROVE", validated_age_min=5, abandoned=False):
    s = OptionsThesisStore(tmp_path / "options_thesis.jsonl")
    if record:
        s._append({"event_type": "OPTIONS_THESIS_VERSION", "position_guid": GUID, "version": 1,
                   "pin": f"opt_{GUID}@v1", "thesis_gate_state": "CURRENT",
                   "investment_thesis": {"stance": "BULLISH", "pin": "thesis_DELL@v3"},
                   "missing_required": [],
                   "cio_approval_record": ({"outcome": decision, "decision_guid": "dec-1"} if decision else None),
                   "recorded_at": _iso(NOW - timedelta(hours=2))})
    if decision:
        s.append_event(GUID, "OPTIONS_THESIS_DECISION", outcome=decision, decision_guid="dec-1",
                       recorded_at=_iso(NOW - timedelta(hours=1)))
    if validated_age_min is not None:
        s._append({"event_type": "OPTIONS_VALIDATED", "position_guid": GUID, "status": "VALIDATED",
                   "validated_at": _iso(NOW - timedelta(minutes=validated_age_min)),
                   "recorded_at": _iso(NOW - timedelta(minutes=validated_age_min))})
    if abandoned:
        s.append_event(GUID, "OPTIONS_THESIS_ABANDONED", reason="48h research window passed",
                       recorded_at=_iso(NOW - timedelta(minutes=30)))
    return s


def _row(proposal, *, status="approved", approved_age_min=10, live_eligible=True, pin=True):
    """The approval-queue row as _fetch_queue_row returns it (in-memory; no DB)."""
    meta = {}
    if pin:
        meta["approval"] = dict(ent.approval_pin(proposal), approved_at=_iso(NOW - timedelta(minutes=approved_age_min)),
                                reviewer="operator")
    return {"status": status, "live_eligible": live_eligible, "blocks_json": [], "proposal_json": dict(proposal),
            "reviewed_at": _iso(NOW - timedelta(minutes=approved_age_min)), "meta": meta, "expires_at": None}


def _gate(proposal, store, row=None, now=NOW):
    return ent.preflight_desk_gate(PID, proposal, store=store, now=now, row=row if row is not None else _row(proposal),
                                   cfg=CFG)


def _codes(res):
    return [r["code"] for r in res["refusals"]]


# ---------------------------------------------------------------------------------------
# positive control: everything valid -> ok, and no broker anything is involved at all
# ---------------------------------------------------------------------------------------

def test_positive_control_everything_valid_gate_ok(tmp_path):
    res = _gate(_proposal(), _store(tmp_path))
    assert res["refusals"] == [], res["refusals"]
    assert res["ok"] is True and res["gate"] == "desk_preflight"
    # freshness recomputed as of NOW from the stored timestamps, not the scan
    assert res["market_session"] == "REGULAR"
    assert res["quote_age_seconds"] == 30.0 and res["chain_age_seconds"] == 60.0


# ---------------------------------------------------------------------------------------
# 1. stale quote: past the threshold AND absent both refuse
# ---------------------------------------------------------------------------------------

def test_stale_quote_past_threshold_is_blocked(tmp_path):
    p = _proposal(legs_liquidity=[_leg("short put", 522.5, quote_age_s=30), _leg("long put", 497.5, quote_age_s=600)])
    res = _gate(p, _store(tmp_path))
    assert "quote_stale" in _codes(res)          # the OLDEST leg quote is the spread's quote age
    assert res["quote_age_seconds"] == 600.0
    assert res["ok"] is False


def test_absent_quote_time_fails_closed_in_submit_mode(tmp_path):
    p = _proposal(legs_liquidity=[_leg("short put", 522.5, quote_age_s=None), _leg("long put", 497.5, quote_age_s=None)])
    p.pop("quote_time", None)
    res = _gate(p, _store(tmp_path))
    assert "quote_age_unknown" in _codes(res) and res["ok"] is False
    # directly on the evaluator: absent -> unknown in submit mode, silent in live mode (desk render)
    bare = {"symbol": "DELL", "strategy": "covered_call", "contracts": 1, "occ_symbol": "X",
            "enterprise": {"earnings": {"in_blackout": False}, "liquidity": {"pass": True}}}
    submit = {b["code"] for b in ent.evaluate_hard_risk_blocks(dict(bare), mode="submit", cfg=CFG)}
    assert {"quote_age_unknown", "chain_age_unknown", "market_session_unknown", "buying_power_unknown"} <= submit
    live = {b["code"] for b in ent.evaluate_hard_risk_blocks(dict(bare), mode="live", cfg=CFG)}
    assert not (live & {"quote_age_unknown", "chain_age_unknown", "market_session_unknown", "buying_power_unknown"})
    assert ent.evaluate_hard_risk_blocks(dict(bare), mode="advisory", cfg=CFG) == []


def test_stale_chain_and_closed_session_labels_block(tmp_path):
    p = _proposal(chain_fetched_at=_iso(NOW - timedelta(seconds=900)))
    assert "option_chain_stale" in _codes(_gate(p, _store(tmp_path)))
    # a weekend clock refuses even though the stored card says REGULAR
    sat = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
    res = _gate(_proposal(), _store(tmp_path), now=sat)
    assert res["market_session"] == "WEEKEND" and "market_closed" in _codes(res)
    # missing liquidity verdict is a refusal, not a pass
    p2 = _proposal(enterprise={"earnings": {"in_blackout": False}})
    assert "liquidity_unknown" in _codes(_gate(p2, _store(tmp_path)))


# ---------------------------------------------------------------------------------------
# 2. thesis missing / CIO decision not APPROVE
# ---------------------------------------------------------------------------------------

def test_missing_thesis_record_blocks(tmp_path):
    res = _gate(_proposal(), _store(tmp_path, record=False, decision=None))
    codes = _codes(res)
    assert "thesis_missing" in codes and "cio_decision_not_approve" in codes and res["ok"] is False


def test_cio_decision_not_approve_blocks(tmp_path):
    res = _gate(_proposal(cio_decision={"outcome": "MORE_RESEARCH"}), _store(tmp_path, decision="MORE_RESEARCH"))
    codes = _codes(res)
    assert "awaiting_cio_decision" in codes and res["ok"] is False
    # an engine-stamped thesis block is honoured even when the stored record looks clean
    res2 = _gate(_proposal(thesis_blocks=[{"code": "thesis_required", "reason": "symbol thesis insufficient data"}]),
                 _store(tmp_path))
    assert "thesis_required" in _codes(res2)


def test_stale_validation_blocks(tmp_path):
    res = _gate(_proposal(), _store(tmp_path, validated_age_min=45))   # fresh_minutes default 30
    assert "validation_stale" in _codes(res)
    assert _gate(_proposal(), _store(tmp_path, validated_age_min=None))["ok"] is False


# ---------------------------------------------------------------------------------------
# 3. failed liquidity on EITHER leg
# ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad_leg", [0, 1])
def test_failed_liquidity_on_either_leg_blocks(tmp_path, bad_leg):
    p = _proposal()
    legs = p["enterprise"]["liquidity"]["legs"]
    legs[bad_leg] = {**legs[bad_leg], "pass": False, "issues": ["OI 0 < 50", "spread 122.0% > 12.0%"]}
    # the top-level verdict still says pass -- the gate must look at every leg itself
    res = _gate(p, _store(tmp_path))
    fails = [r for r in res["refusals"] if r["code"] == "liquidity_failed"]
    assert fails and fails[0]["detail"]["leg"] == legs[bad_leg]["role"]
    assert res["ok"] is False


def test_one_sided_leg_quote_blocks(tmp_path):
    p = _proposal()
    p["legs_liquidity"][1] = {**p["legs_liquidity"][1], "bid": 0.0, "two_sided": False}
    assert "leg_quote_not_two_sided" in _codes(_gate(p, _store(tmp_path)))


# ---------------------------------------------------------------------------------------
# 4. buying power: absent -> blocked; present-but-low -> blocked; enough -> not this code
# ---------------------------------------------------------------------------------------

def test_buying_power_absent_low_enough(tmp_path):
    p = _proposal()
    p.pop("buying_power")
    codes = _codes(_gate(p, _store(tmp_path)))
    assert "buying_power_unknown" in codes and "min_buying_power" not in codes

    codes = _codes(_gate(_proposal(buying_power=100), _store(tmp_path)))
    assert "min_buying_power" in codes and "buying_power_unknown" not in codes

    codes = _codes(_gate(_proposal(buying_power=50_000), _store(tmp_path)))
    assert "min_buying_power" not in codes and "buying_power_unknown" not in codes


# ---------------------------------------------------------------------------------------
# 5. archived proposal with a stale 'approved' row
# ---------------------------------------------------------------------------------------

def test_archived_thesis_with_stale_approved_row_blocks(tmp_path):
    store = _store(tmp_path, abandoned=True)
    assert store.lifecycle(GUID)["stage"] == "ARCHIVED_ABANDONED"
    res = _gate(_proposal(), store)          # the row still says approved
    assert "thesis_abandoned" in _codes(res) and res["ok"] is False


class _FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchall(self):
        return [("opt_old_id_d20260927",), (PID,)]


class _FakeConn:
    def __init__(self):
        self.cur = _FakeCursor()
        self.commits = 0

    def cursor(self):
        return self.cur

    def commit(self):
        self.commits += 1


def test_archive_approval_rows_flips_approved_rows_to_blocked(monkeypatch):
    conn = _FakeConn()
    monkeypatch.setattr(ent, "_conn", lambda: conn)
    out = ent.archive_approval_rows([_proposal(thesis_abandoned="48h research window passed")])
    assert out["ok"] and set(out["archived"]) == {PID, "opt_old_id_d20260927"} and conn.commits == 1
    sql, params = conn.cur.executed[0]
    assert "SET status='blocked'" in sql and "status IN ('pending','approved','blocked')" in sql
    # matched by proposal_id AND by strategy GUID, so yesterday's row for the same idea goes too
    assert "proposal_json->>'option_strategy_guid'" in sql and params[3] == PID and params[5] == GUID
    assert "THESIS_ABANDONED" in params[0]


def test_check_preflight_approval_refuses_every_status_but_approved():
    for status in ("pending", "blocked", "rejected", "executed", "READY_FOR_ALPACA_PAPER"):
        ok, why = ent.check_preflight_approval(PID, row=_row(_proposal(), status=status))
        assert ok is False and why
    ok, _ = ent.check_preflight_approval(PID, row=_row(_proposal(), status="approved"))
    assert ok is True


# ---------------------------------------------------------------------------------------
# 6. changed long leg with the same proposal_id -> legs_changed
# ---------------------------------------------------------------------------------------

def test_changed_long_leg_same_proposal_id_is_legs_changed(tmp_path):
    approved = _proposal()
    row = _row(approved)                        # pinned at approve time to 522.5 / 497.5
    current = _proposal(long_strike=492.5)       # the desk re-picked the long leg, same id
    res = _gate(current, _store(tmp_path), row=row)
    chg = [r for r in res["refusals"] if r["code"] == "legs_changed"]
    assert chg and chg[0]["detail"]["approved"]["long_strike"] == "497.5000"
    assert chg[0]["detail"]["current"]["long_strike"] == "492.5000"
    # a re-serialised but identical proposal (string strikes, extra keys) hashes the same
    same = dict(approved, long_strike="497.5", short_strike="522.50", reasoning="new text")
    assert ent.approval_pin(same)["approved_hash"] == ent.approval_pin(approved)["approved_hash"]
    # and a legacy approval with no pin cannot ride through either: since 2026-09-27 it is
    # pinned to the proposal_json it stored, so the changed leg is caught as legs_changed
    assert "legs_changed" in _codes(_gate(current, _store(tmp_path), row=_row(approved, pin=False)))


def test_engine_spread_id_names_the_long_leg():
    import options_engine as oe
    a = oe._proposal_id("credit_spread", "DELL", "rollover", 522.5, "2026-11-20", long_strike=497.5)
    b = oe._proposal_id("credit_spread", "DELL", "rollover", 522.5, "2026-11-20", long_strike=492.5)
    assert a != b and "_l497p5000" in a and "_l492p5000" in b
    # single-leg ids are unchanged
    assert "_l" not in oe._proposal_id("covered_call", "DELL", "rollover", 600, "2026-11-20")


# ---------------------------------------------------------------------------------------
# 7. approval past TTL -> approval_expired
# ---------------------------------------------------------------------------------------

def test_approval_past_ttl_is_expired(tmp_path):
    assert float(CFG["approval_ttl_minutes"]) == 240.0
    res = _gate(_proposal(), _store(tmp_path), row=_row(_proposal(), approved_age_min=300))
    exp = [r for r in res["refusals"] if r["code"] == "approval_expired"]
    assert exp and exp[0]["detail"]["ttl_minutes"] == 240.0 and res["ok"] is False
    assert "approval_expired" not in _codes(_gate(_proposal(), _store(tmp_path), row=_row(_proposal(), approved_age_min=239)))


# ---------------------------------------------------------------------------------------
# 8. the api_v2 handler refuses at the desk gate and never reaches a broker module
# ---------------------------------------------------------------------------------------

def test_api_v2_preflight_blocks_at_desk_gate_before_any_broker_call(monkeypatch, tmp_path):
    brokers = MagicMock(name="brokers")
    oop = MagicMock(name="brokers.options_order_pilot")
    guard = MagicMock(name="brokers.execution_guard")
    approval = MagicMock(name="brokers.approval_service")
    for name, mod in (("brokers", brokers), ("brokers.options_order_pilot", oop),
                      ("brokers.execution_guard", guard), ("brokers.approval_service", approval)):
        monkeypatch.setitem(sys.modules, name, mod)
    brokers.options_order_pilot, brokers.execution_guard, brokers.approval_service = oop, guard, approval

    import api_v2
    import options_engine as oe

    proposal = _proposal()
    # desk state: approved row, but the thesis store has no fresh validation -> gate refuses
    monkeypatch.setattr(ent, "_fetch_queue_row", lambda pid: _row(proposal) if pid == PID else None)
    monkeypatch.setattr(ent, "_thesis_store", lambda: _store(tmp_path, validated_age_min=None))
    monkeypatch.setattr(oe, "_load_json", lambda path: {"proposals": [proposal]})
    monkeypatch.setattr(oe, "generate_proposals", lambda force=False: pytest.fail("engine regenerate must not run"))
    monkeypatch.setattr(api_v2, "_db_query", lambda *a, **k: pytest.fail("no DB read on the gate path"))

    status, res = api_v2.handle("/api/v2/options/preflight", "POST", body={"proposal_id": PID, "account_key": "rollover"})

    assert status == 200 and res["ok"] is False
    assert res["mode"] == "blocked" and res["gate"] == "desk_preflight"
    codes = [r["code"] for r in res["refusals"]]
    assert "validation_stale" in codes
    assert oop.build_intent.call_count == 0
    assert guard.authorize.call_count == 0
    assert oop.request_2fa.call_count == 0
    assert oop.build_order_spec.call_count == 0
    assert approval.confirm.call_count == 0


def test_api_v2_preflight_refuses_unapproved_row_before_gate(monkeypatch):
    for name in ("brokers", "brokers.options_order_pilot", "brokers.execution_guard"):
        monkeypatch.setitem(sys.modules, name, MagicMock(name=name))
    import api_v2
    monkeypatch.setattr(ent, "_fetch_queue_row", lambda pid: _row(_proposal(), status="pending"))
    status, res = api_v2.handle("/api/v2/options/preflight", "POST", body={"proposal_id": PID})
    assert status == 200 and res["mode"] == "blocked" and res["gate"] == "desk_approval"
    assert sys.modules["brokers.options_order_pilot"].build_intent.call_count == 0


# ---------------------------------------------------------------------------------------
# stamping: the engine-side freshness stamp leaves an unknown ABSENT, never zero
# ---------------------------------------------------------------------------------------

def test_stamp_freshness_absent_stays_absent_and_ages_from_now():
    p = {"symbol": "DELL", "quote_time": _iso(NOW - timedelta(seconds=90))}
    ent.stamp_freshness(p, now=NOW, session="REGULAR")
    assert p["quote_age_seconds"] == 90.0 and "chain_age_seconds" not in p and p["market_session"] == "REGULAR"
    ent.stamp_freshness(p, now=NOW, chain_fetched_at=_iso(NOW - timedelta(seconds=10)))
    assert p["chain_age_seconds"] == 10.0
    # epoch-millis quote times (Schwab quoteTimeInLong) are understood too
    q = {"quote_time": int((NOW - timedelta(seconds=45)).timestamp() * 1000)}
    ent.stamp_freshness(q, now=NOW)
    assert q["quote_age_seconds"] == 45.0
    # buying_power is never invented
    assert "buying_power" not in p and "buying_power" not in q
