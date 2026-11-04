"""Piece B — the recovery state machine (SPEC_RECOVERY_REENTRY_ENGINE_20261103 §3.2).

Operator's words: "SpaceX is back up to 141 … Nothing has notified me to get back in." The machine's job is to
say RECOVERING when a stopped-out position reclaims its exit, and RE_ENTRY_READY only when the reclaim plus
momentum reaches the floor AND at least one account can actually buy — with every gate shown as a dated
annotation rather than a silence. Pure functions: no DB, no store, no order path.
"""
from __future__ import annotations

import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib import recovery_state as R  # noqa: E402

NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)


def case(**over):
    base = {
        "case_key": "SPCX:schwab_taxable:2026-10-30",
        "symbol": "SPCX", "account": "schwab_taxable", "state": "STOPPED_OUT",
        "exit_price": 137.19, "stop_level": 138.00,
        "pre_exit_shares": 1400.0, "residual_shares": 200.0,
        "materiality_tier": "T1", "residual_is_held": None,
        "eligibility_json": {"IRA": {"eligible": True}, "taxable": {"eligible": False, "gate": "house_hold",
                                                                   "until": "2026-11-27"}},
    }
    base.update(over)
    return base


def snap(**over):
    base = {"close": 141.65, "rsi": 39.1, "rsi_prev": 36.0, "sma20": 151.62, "macd_up_sessions": 0,
            "catalyst_confidence": 0.88, "catalyst_sessions_ago": 1, "entry_high": 139.00,
            "fetched_at": NOW.isoformat()}
    base.update(over)
    return base


def test_a_reclaim_of_the_exit_is_recovering_even_below_the_twenty_day_mean():
    """SPCX: +3.3% above the 10-30 exit while SMA20 is still 151.62 — the V-recovery the pullback-only trigger
    could never catch."""
    d = R.evaluate(case(), snap(), now=NOW)

    assert d.state == R.RECOVERING and d.changed is True
    assert d.triggers["R1"] is True and d.triggers["R4"] is False
    assert "reclaims the 20-day mean" in d.next_trigger


def test_the_reclaim_needs_a_full_one_percent():
    d = R.evaluate(case(stop_level=145.0), snap(close=138.0, catalyst_confidence=0.0), now=NOW)
    assert d.state == R.WATCHING and d.triggers["R1"] is False


def test_the_residual_is_displayed_and_never_disqualifies():
    """Operator ruling 2026-11-03: "drop 'held' as a disqualifier. A residual is a FACT TO DISPLAY, not a
    silencer." Piece A carries the note; B renders it and never re-derives a percentage."""
    shown = case(residual_pct_of_pre_exit=14.3,
                 residual_note="200 of 1,400 shares remain after the 2026-10-30 exit (14.3%)")
    d = R.evaluate(shown, snap(close=152.0), now=NOW)

    fact = next(a for a in d.annotations if a["gate"] == "residual")
    assert fact["blocks_ready"] is False
    assert fact["detail"] == "200 of 1,400 shares remain after the 2026-10-30 exit (14.3%)"
    assert "information, not a blocker" in fact["would_change_it"]
    assert d.state == R.RE_ENTRY_READY           # the residual does not stop readiness

    # 200 of 1,000 (20%) is the same fact, not a different verdict: no threshold exists any more.
    twenty = case(residual_pct_of_pre_exit=20.0, residual_note="200 of 1,000 shares remain (20.0%)")
    d2 = R.evaluate(twenty, snap(close=152.0), now=NOW)
    assert d2.state == R.RE_ENTRY_READY
    assert next(a for a in d2.annotations if a["gate"] == "residual")["blocks_ready"] is False


def test_an_open_date_gate_reads_as_pending_your_decision():
    """The engine reports the dated split; it never answers whether to re-enter."""
    d = R.evaluate(case(), snap(close=141.65), now=NOW)
    pending = [a for a in d.annotations if a["gate"] == "pending_operator_decision"]
    assert [a["account"] for a in pending] == ["IRA"]
    assert pending[0]["would_change_it"] == "your decision on the recovery card"


def test_re_entry_ready_needs_the_mean_reclaim_and_an_eligible_account():
    d = R.evaluate(case(), snap(close=152.0), now=NOW)

    assert d.state == R.RE_ENTRY_READY and d.eligible_accounts == ["IRA"]
    gates = {a["gate"]: a for a in d.annotations}
    assert gates["house_hold"]["account"] == "taxable"
    assert gates["house_hold"]["until"] == "2026-11-27"
    assert gates["house_hold"]["blocks_ready"] is False        # IRA is still a route
    assert gates["rsi_below_level"]["blocks_ready"] is False   # information, never a silencer
    assert gates["above_entry_zone"]["blocks_ready"] is False


def test_every_account_blocked_means_no_ready_state_but_the_card_still_says_why():
    all_blocked = {"IRA": {"eligible": False, "gate": "house_hold", "until": "2026-11-27"},
                   "taxable": {"eligible": False, "gate": "wash_sale", "until": "2026-12-02"}}
    d = R.evaluate(case(eligibility_json=all_blocked), snap(close=152.0), now=NOW)

    assert d.state != R.RE_ENTRY_READY
    assert d.eligible_accounts == []
    blockers = {a["account"] for a in d.annotations if a["blocks_ready"]}
    assert blockers == {"IRA", "taxable"}      # every date-closed account is named; nothing else blocks


def test_a_verified_catalyst_alone_never_advances_the_state():
    quiet = snap(close=130.0, rsi=35.0, rsi_prev=34.0, sma20=160.0, catalyst_confidence=0.95)
    d = R.evaluate(case(), quiet, now=NOW)

    assert d.triggers["R5"] is True and d.triggers["R1"] is False
    assert d.state == R.WATCHING, "R5 is an amplifier, never a trigger"


def test_momentum_alone_is_not_enough_either():
    d = R.evaluate(case(), snap(close=130.0, rsi=45.0, rsi_prev=38.0, sma20=160.0, catalyst_confidence=0.0), now=NOW)
    assert d.triggers["R3"] is True and d.state == R.WATCHING


def test_the_rsi_cross_up_through_the_level_is_the_momentum_trigger():
    below = snap(rsi=39.5, rsi_prev=38.0, macd_up_sessions=0)
    above = snap(rsi=41.0, rsi_prev=38.0, macd_up_sessions=0)
    two_up = snap(rsi=39.0, rsi_prev=39.5, macd_up_sessions=2)
    assert R.evaluate(case(), below, now=NOW).triggers["R3"] is False
    assert R.evaluate(case(), above, now=NOW).triggers["R3"] is True
    assert R.evaluate(case(), two_up, now=NOW).triggers["R3"] is True


def test_an_operator_decision_is_never_overridden_by_a_rule():
    for state in (R.CLOSED, R.SNOOZED, R.RE_ENTERED):
        d = R.evaluate(case(state=state), snap(close=152.0), now=NOW)
        assert d.state == state and d.changed is False


def test_no_snapshot_leaves_the_state_alone_and_says_so():
    d = R.evaluate(case(), None, now=NOW)
    assert d.state == "STOPPED_OUT" and d.changed is False and "no market snapshot" in d.reason


def test_decay_moves_the_card_to_the_digest_but_never_closes_a_material_case():
    t1 = R.session_decay(case(sessions_since_trigger=25, materiality_tier="T1"))
    t3 = R.session_decay(case(sessions_since_trigger=25, materiality_tier="T3"))
    fresh = R.session_decay(case(sessions_since_trigger=3, materiality_tier="T1"))
    assert t1["decayed"] is True and t1["auto_close"] is False
    assert t3["decayed"] is True and t3["auto_close"] is True
    assert fresh["decayed"] is False


def test_a_case_filed_over_the_journal_is_never_a_second_reason_to_buy():
    """Idempotence: same inputs, same answer, no hidden clock or global state."""
    a = R.evaluate(case(), snap(), now=NOW).as_dict()
    b = R.evaluate(case(), snap(), now=NOW).as_dict()
    assert a == b


def test_policy_defaults_apply_when_the_reviewed_file_is_absent():
    policy = R.load_policy(ROOT / "config" / "does-not-exist.yaml")
    assert policy["reclaim_exit_pct"] == 0.010
    assert "residual_remaining_fraction" not in policy
    assert policy["policy_source"].startswith("defaults")


# ── the thin caller (piece A owns the store; B applies no writes of its own) ───────────────────────────────
class FakeStore:
    def __init__(self, cases):
        self.cases = cases
        self.written = []

    def list(self):
        return list(self.cases)

    def set_state(self, key, state):
        self.written.append((key, state))


def test_run_pass_returns_decisions_and_writes_only_through_the_store(tmp_path):
    store = FakeStore([case(), case(case_key="OTHER:x", symbol="OTHER", exit_price=10.0, residual_shares=900.0)])
    out = R.run_pass(store, lambda c: snap(), now=NOW, dry_run=False,
                     pending_path=tmp_path / "pending.json")

    assert out["store"] == "ok" and out["considered"] == 2 and out["changed"] == 2
    assert store.written == [(c[0], c[1]) for c in
                             [(r["case_key"], r["state"]) for r in out["decisions"]]]
    states = {r["case_key"]: r["state"] for r in out["decisions"]}
    assert states["SPCX:schwab_taxable:2026-10-30"] == R.RECOVERING


def test_run_pass_never_guesses_without_a_snapshot():
    store = FakeStore([case()])
    out = R.run_pass(store, lambda c: None, dry_run=False)
    assert out["decisions"][0]["state"] == "STOPPED_OUT" and store.written == []


def test_an_absent_store_says_absent_not_empty():
    assert R.run_pass(None, lambda c: snap())["store"] == "absent"


def test_the_reviewed_nested_policy_dialect_maps_onto_the_engine(tmp_path):
    """Piece A's config/recovery_policy.yaml is nested; B reads ITS names, never a fork of them."""
    import yaml
    doc = {"schema": "RecoveryPolicy@v1",
           "triggers": {"r1_reclaim_exit_pct": 2.0, "r3_rsi_cross": 45, "r3_macd_histogram_sessions": 3,
                        "r5_catalyst_min_confidence": 0.9, "decay_sessions": 30},
           "confidence": {"weights": {"r1": 0.4, "r4": 0.3}, "ready_floor": 0.6},
           "residual": {"residual_remaining_fraction": 0.1}}
    path = tmp_path / "recovery_policy.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    policy = R.load_policy(path)
    assert policy["reclaim_exit_pct"] == 0.02 and policy["rsi_level"] == 45   # 2.0 percent -> 0.02 fraction
    assert policy["macd_up_sessions"] == 3 and policy["catalyst_min_confidence"] == 0.9
    assert policy["decay_sessions"] == 30
    assert "residual_remaining_fraction" not in policy   # the held concept is removed, not tuned
    assert policy["weights"]["R1"] == 0.4 and policy["weights"]["R4"] == 0.3
    assert policy["weights"]["R2"] == R.DEFAULT_POLICY["weights"]["R2"]   # unmapped weights keep defaults
    assert policy["ready_floor"] == 0.6


def test_piece_a_eligibility_list_is_rendered_as_annotations():
    elig = [{"account": "schwab_roth_ira", "eligible": True, "eligible_from": None, "reason": "ira eligible now"},
            {"account": "schwab_taxable", "eligible": False, "eligible_from": "2026-11-29",
             "reason": "house hold 30 days after a taxable sale"}]
    d = R.evaluate(case(eligibility_json=elig), snap(close=152.0), now=NOW)

    assert d.eligible_accounts == ["schwab_roth_ira"]
    gate = next(a for a in d.annotations if a["account"] == "schwab_taxable")
    assert gate["until"] == "2026-11-29" and gate["blocks_ready"] is False
    assert "house hold" in gate["would_change_it"]


def test_no_eligibility_rows_is_not_a_pass():
    """Missing data is not permission: without the account split B cannot honestly say "ready"."""
    d = R.evaluate(case(eligibility_json=None), snap(close=152.0), now=NOW)

    assert d.state != R.RE_ENTRY_READY and d.eligible_accounts == []
    gate = next(a for a in d.annotations if a["gate"] == "eligibility_unknown")
    assert "nothing to re-enter until the account split exists" in gate["detail"]
    assert gate["would_change_it"] == "piece A supplies the account eligibility"
    assert gate["blocks_ready"] is True


def test_a_reclaim_still_shows_when_eligibility_is_unknown():
    """The anti-regression pin for the readiness/state split: gates annotate, they never silence.

    No eligibility rows AND a genuine reclaim (+3.3% above the exit) must end in RECOVERING — not WATCHING (a
    silenced state, the original failure in a new place) and not RE_ENTRY_READY (unprovable readiness). The
    operator's complaint was that nothing told him the name was recovering, so an account-split gap must never
    be able to hide a reclaim.
    """
    d = R.evaluate(case(eligibility_json=None), snap(close=141.65), now=NOW)

    assert d.state == R.RECOVERING
    assert d.state not in (R.WATCHING, R.RE_ENTRY_READY)
    assert any(a["gate"] == "eligibility_unknown" and a["blocks_ready"] for a in d.annotations)


def test_all_dates_closed_shows_the_reclaim_but_never_readiness():
    closed = {"IRA": {"eligible": False, "gate": "house_hold", "until": "2026-11-27"},
              "taxable": {"eligible": False, "gate": "wash_sale", "until": "2026-12-02"}}
    assert R.evaluate(case(eligibility_json=closed), snap(close=141.65), now=NOW).state == R.RECOVERING
    assert R.evaluate(case(eligibility_json=closed), snap(close=152.0), now=NOW).state != R.RE_ENTRY_READY


def test_a_pending_decision_row_is_date_open_but_still_reads_as_pending():
    pending = [{"account": "schwab_roth_ira", "eligible": True, "eligible_from": None,
                "pending_operator_decision": True, "reason": "date gate open; the operator has not answered"}]
    d = R.evaluate(case(eligibility_json=pending), snap(close=152.0), now=NOW)

    assert d.state == R.RE_ENTRY_READY and d.eligible_accounts == ["schwab_roth_ira"]
    gate = next(a for a in d.annotations if a["account"] == "schwab_roth_ira")
    assert gate["gate"] == "pending_operator_decision"
    assert gate["would_change_it"] == "your decision on the recovery card"


def test_piece_a_case_shape_is_consumed_without_renaming_fields():
    """A's RecoveryCase.to_dict() carries `exits` (ExitFill dicts with `price`) and `eligibility` as a list."""
    a_case = {"case_key": "SPCX:acct", "symbol": "SPCX", "account": "schwab_taxable",
              "state": "WATCHING", "materiality_tier": "T1",
              "exits": [{"symbol": "SPCX", "price": 137.19, "shares": 200, "realized_pnl": -12770.0,
                         "exit_date": "2026-10-30"}],
              "eligibility": [{"account": "schwab_roth_ira", "eligible": True, "eligible_from": None,
                               "reason": "ira eligible now"}],
              "residual_pct_of_pre_exit": 14.3,
              "residual_note": "200 of 1,400 shares remain after the 2026-10-30 exit (14.3%)"}
    d = R.evaluate(a_case, snap(close=141.65), now=NOW)

    assert R.exit_price(a_case) == 137.19
    assert d.state == R.RECOVERING and d.eligible_accounts == ["schwab_roth_ira"]


# ── A→B integration contract (codex's real-A probes, 2026-11-03) ─────────────────────────────────────────
def test_a_percent_policy_loads_as_a_fraction_not_as_100x(tmp_path):
    """A1: piece A writes ``r1_reclaim_exit_pct: 1.0`` meaning ONE PERCENT (exit*(1+pct/100)).

    B loaded it as the fraction 1.0 = 100%, so R1 needed a doubling of the price. Fed by a REAL A-shaped row and
    A's actual policy shape; R1 is asserted on its own with R2–R5 false so another trigger cannot hide it.
    """
    import yaml
    policy_doc = {"schema": "RecoveryPolicy@v1",
                  "triggers": {"r1_reclaim_exit_pct": 1.0, "r2_reclaim_stop": True, "r3_rsi_cross": 40,
                               "r3_macd_histogram_sessions": 2, "r5_catalyst_min_confidence": 0.8},
                  "confidence": {"weights": {}, "ready_floor": 0.55}}
    path = tmp_path / "recovery_policy.yaml"
    path.write_text(yaml.safe_dump(policy_doc), encoding="utf-8")
    policy = R.load_policy(path)
    assert policy["reclaim_exit_pct"] == 0.01          # 1 percent, not 1.0

    a_row = {"case_key": "DEMO:ira", "symbol": "DEMO", "account": "DEMO_IRA", "state": "WATCHING",
             "materiality_tier": "T1",
             "exits": [{"symbol": "DEMO", "price": 100.0, "shares": 100, "realized_pnl": -5000.0,
                        "exit_date": "2026-10-30"}]}
    flat = {"close": 102.0, "rsi": 35.0, "rsi_prev": 34.0, "sma20": 130.0, "macd_up_sessions": 0,
            "catalyst_confidence": 0.0, "fetched_at": NOW.isoformat()}
    d = R.evaluate(a_row, flat, policy, now=NOW)

    assert d.triggers == {"R1": True, "R2": False, "R3": False, "R4": False, "R5": False}
    assert d.state == R.RECOVERING


def test_the_reference_is_the_final_exit_not_the_max(tmp_path):
    """A2: A compares against ``exits[-1].price`` (the FINAL exit). B took the max, so with exits 120 then 100
    the two sides answered oppositely at any price between them — at 102, A.R1 true and B.R1 false."""
    a_row = {"case_key": "DEMO:ira", "symbol": "DEMO", "account": "DEMO_IRA", "state": "WATCHING",
             "materiality_tier": "T1",
             "exits": [{"symbol": "DEMO", "price": 120.0, "shares": 50, "realized_pnl": -1000.0,
                        "exit_date": "2026-10-01"},
                       {"symbol": "DEMO", "price": 100.0, "shares": 100, "realized_pnl": -5000.0,
                        "exit_date": "2026-10-30"}]}
    assert R.exit_price(a_row) == 100.0                 # final exit, not max 120

    flat = {"close": 102.0, "rsi": 35.0, "rsi_prev": 34.0, "sma20": 130.0, "macd_up_sessions": 0,
            "catalyst_confidence": 0.0, "fetched_at": NOW.isoformat()}
    d = R.evaluate(a_row, flat, now=NOW)                # default policy (0.01 fraction)
    assert d.triggers == {"R1": True, "R2": False, "R3": False, "R4": False, "R5": False}
    assert d.state == R.RECOVERING


def test_the_final_exit_follows_the_rows_own_order_when_dates_are_missing():
    row = {"exits": [{"price": 120.0}, {"price": 100.0}]}
    assert R.exit_price(row) == 100.0                   # A's exits[-1], in A's order


# ── the PRODUCTION handoff: run_pass itself must notify (codex's scheduled-shape probe) ────────────────────
class RecordingStore:
    def __init__(self, cases):
        self.cases = cases
        self.written = []

    def list(self):
        return list(self.cases)

    def set_state(self, key, state):
        self.written.append((key, state))


def _t1_row(exit_price=100.0, residual=1.0, pre_exit=7.0):
    return {"case_key": "DEMO:DEMO_IRA:2030-01-10", "symbol": "DEMO", "account": "DEMO_IRA",
            "state": "WATCHING", "materiality_tier": "T1", "realized_pnl": -5000.0,
            "exits": [{"symbol": "DEMO", "price": exit_price, "shares": pre_exit - residual,
                       "realized_pnl": -5000.0, "exit_date": "2030-01-10"}],
            "eligibility": [{"account": "DEMO_IRA", "eligible": True, "eligible_from": None}],
            "residual_pct_of_pre_exit": 14.3, "residual_note": "1 of 7 shares remain after the 2030-01-10 exit"}


def test_the_scheduled_pass_pages_a_t1_recovering_transition(tmp_path):
    """The failure codex found: run_pass wrote a T1 RECOVERING case and made ZERO notifier calls."""
    store = RecordingStore([_t1_row()])
    calls = []
    out = R.run_pass(store, lambda c: {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()},
                     now=NOW, dry_run=False, notify=lambda case: calls.append(case) or {"sent": True},
                     pending_path=tmp_path / "pending.json")

    assert out["store"] == "ok" and out["changed"] == 1 and out["notifier_calls"] == 1
    assert store.written == [("DEMO:DEMO_IRA:2030-01-10", R.RECOVERING)]
    assert calls and calls[0]["state"] == R.RECOVERING
    assert calls[0]["exit_price"] == 100.0 and calls[0]["price"] == 102.0
    assert out["decisions"][0]["notify"] == {"sent": True}


def test_the_scheduled_pass_does_not_page_a_case_that_did_not_transition(tmp_path):
    store = RecordingStore([{**_t1_row(), "state": "WATCHING"}])
    calls = []
    out = R.run_pass(store, lambda c: {"close": 90.0, "rsi": 30.0, "sma20": 130.0, "fetched_at": NOW.isoformat()},
                     now=NOW, dry_run=False, notify=lambda case: calls.append(case) or {"sent": True},
                     pending_path=tmp_path / "pending.json")
    assert out["changed"] == 0 and out["notifier_calls"] == 0 and calls == []


def test_a_dry_run_never_pages_or_writes(tmp_path):
    store = RecordingStore([_t1_row()])
    calls = []
    out = R.run_pass(store, lambda c: {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()},
                     now=NOW, dry_run=True, notify=lambda case: calls.append(case) or {"sent": True},
                     pending_path=tmp_path / "pending.json")
    assert out["notifier_calls"] == 0 and calls == [] and store.written == []
    assert out["decisions"][0]["notify"]["reason"] == "dry_run"


def test_a_notifier_fault_is_recorded_and_never_aborts_the_pass(tmp_path):
    store = RecordingStore([_t1_row(), {**_t1_row(), "case_key": "OTHER:x", "symbol": "OTHER"}])
    def boom(case):
        raise RuntimeError("transport down")
    out = R.run_pass(store, lambda c: {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()},
                     now=NOW, dry_run=False, notify=boom,
                     pending_path=tmp_path / "pending.json")
    assert out["notifier_calls"] == 2 and len(store.written) == 2
    assert out["decisions"][0]["notify"]["error"].startswith("RuntimeError")


# ── failure paths: durability order (codex's fade15f6a BLOCK) ──────────────────────────────────────────────
class FailingWriteStore(RecordingStore):
    def set_state(self, key, state):
        raise OSError("disk full")


def test_a_failed_state_write_never_pages(tmp_path):
    """Step 2 of the sequence: a page must not fire for a case that was never recorded."""
    store = FailingWriteStore([_t1_row()])
    calls = []
    out = R.run_pass(store, lambda c: {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()}, now=NOW,
                     dry_run=False, notify=lambda case: calls.append(case) or {"sent": True},
                     pending_path=tmp_path / "pending.json")
    assert calls == [] and out["notifier_calls"] == 0
    assert out["decisions"][0]["write_error"].startswith("OSError")
    assert out["decisions"][0]["notify"]["reason"].startswith("state write failed")


def test_a_failed_send_stays_pending_and_is_retried_after_the_state_is_already_advanced(tmp_path):
    """Step 3/4: delivery failed -> a durable marker survives the pass; the next pass retries it even
    though the state no longer changes (this is the case codex proved was lost)."""
    pending = tmp_path / "pending.json"
    store = RecordingStore([_t1_row()])
    snap = lambda c: {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()}
    first = R.run_pass(store, snap, now=NOW, dry_run=False,
                       notify=lambda case: {"sent": False, "reason": "transport refused"}, pending_path=pending)
    assert first["notifier_calls"] == 1 and first["pending"] == 1
    assert json.loads(pending.read_text())["DEMO:DEMO_IRA:2030-01-10"]["attempts"] == 1

    # The store now reports RECOVERING: no transition, so `changed` is 0 — the retry must still happen.
    delivered = []
    second = R.run_pass(RecordingStore([{**_t1_row(), "state": R.RECOVERING}]), snap, now=NOW, dry_run=False,
                        notify=lambda case: delivered.append(case) or {"sent": True}, pending_path=pending)
    assert second["changed"] == 0 and second["notifier_calls"] == 1 and delivered[0]["state"] == R.RECOVERING
    assert second["pending"] == 0 and json.loads(pending.read_text()) == {}


def test_a_deduped_retry_clears_the_pending_marker(tmp_path):
    pending = tmp_path / "pending.json"
    store = RecordingStore([_t1_row()])
    snap = lambda c: {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()}
    R.run_pass(store, snap, now=NOW, dry_run=False,
               notify=lambda case: {"sent": False}, pending_path=pending)
    cleared = R.run_pass(RecordingStore([{**_t1_row(), "state": R.RECOVERING}]), snap, now=NOW, dry_run=False,
                         notify=lambda case: {"sent": False, "deduped_by_floor": True, "reason": "repeat floor"},
                         pending_path=pending)
    assert cleared["pending"] == 0


def test_a_non_pageable_tier_does_not_create_pending_work(tmp_path):
    pending = tmp_path / "pending.json"
    store = RecordingStore([_t1_row()])
    snap = lambda c: {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()}
    out = R.run_pass(store, snap, now=NOW, dry_run=False,
                     notify=lambda case: {"sent": False, "reason": "not T1 (declared); Home card / digest"},
                     pending_path=pending)
    assert out["pending"] == 0


def test_a_case_that_stays_recovering_without_pending_is_not_rehanded(tmp_path):
    """The lead contract: notify on a transition or a pending retry, not on every pass that observes the state."""
    store = RecordingStore([{**_t1_row(), "state": R.RECOVERING}])
    calls = []
    out = R.run_pass(store, lambda c: {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()}, now=NOW, dry_run=False,
                     notify=lambda case: calls.append(case) or {"sent": True}, pending_path=tmp_path / "p.json")
    assert out["changed"] == 0 and out["notifier_calls"] == 0 and calls == []


# ── quote freshness: a stale price must not move a case (codex's scheduled stale-quote BLOCK) ──────────────
STALE_FETCHED = (NOW - timedelta(days=8)).isoformat()


def _run_with_snapshot(tmp_path, snapshot, *, monkeypatch=None):
    store = RecordingStore([_t1_row()])
    calls = []
    out = R.run_pass(store, lambda c: snapshot, now=NOW, dry_run=False,
                     notify=lambda case: calls.append(case) or {"sent": True},
                     pending_path=tmp_path / "pending.json")
    return out, calls, store


def test_an_eight_day_old_quote_does_not_move_a_case(tmp_path):
    """The freshness guard already exists (derive_freshness); the snapshot used to drop fetched_at, so a stale
    price reached the triggers. At the scheduled entry point: stale -> no transition, no page."""
    out, calls, store = _run_with_snapshot(
        tmp_path, {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": STALE_FETCHED})

    assert out["changed"] == 0 and out["notifier_calls"] == 0 and calls == [] and store.written == []
    assert out["decisions"][0]["state"] == R.WATCHING
    assert "quote not current" in (out["decisions"][0]["reason"] or "")


def test_a_fresh_quote_does_move_a_case(tmp_path):
    """The control: the same price, dated now, transitions and pages exactly once."""
    out, calls, store = _run_with_snapshot(
        tmp_path, {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()})

    assert out["changed"] == 1 and out["notifier_calls"] == 1
    assert store.written == [("DEMO:DEMO_IRA:2030-01-10", R.RECOVERING)]


def test_a_snapshot_with_no_fetch_time_cannot_move_a_case(tmp_path):
    """Drop the field again and the reply is the same: unknown provenance is not freshness."""
    out, calls, store = _run_with_snapshot(tmp_path, {"close": 102.0, "rsi": 35.0, "sma20": 130.0})

    assert out["changed"] == 0 and out["notifier_calls"] == 0 and store.written == []
    assert "DATA_UNAVAILABLE" in (out["decisions"][0]["reason"] or "")


def test_the_stale_guard_is_what_stops_it_not_the_price(tmp_path, monkeypatch):
    """Non-vacuity: with freshness bypassed, the SAME stale snapshot advances — so the passing stale test above
    measures the guard, not a price that happened to be below the threshold."""
    monkeypatch.setattr(R, "snapshot_freshness", lambda snapshot, now=None: ("CURRENT", "regular"))
    out, calls, store = _run_with_snapshot(
        tmp_path, {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": STALE_FETCHED})

    assert out["changed"] == 1 and out["notifier_calls"] == 1
    assert store.written == [("DEMO:DEMO_IRA:2030-01-10", R.RECOVERING)]
