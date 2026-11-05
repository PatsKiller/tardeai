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


def test_a_confidence_only_recovery_never_claims_a_reclaim_fired():
    """The SENTENCE was the untested thing, which is why it survived review.

    The two tests above pass because R3 alone (0.10) and R5 alone (0.15) cannot clear `recovering_floor` (0.30) —
    arithmetic, not a guard. Lower the floor and momentum plus a catalyst reach RECOVERING with no reclaim at all.
    The old code answered that with "a reclaim trigger fired above the exit", which was simply false. It now names
    what happened.
    """
    policy = {**R.DEFAULT_POLICY, "recovering_floor": 0.20}
    quiet = snap(close=137.00, rsi=42.0, rsi_prev=36.0, sma20=151.62, macd_up_sessions=0,
                 catalyst_confidence=0.88, catalyst_sessions_ago=1)
    d = R.evaluate(case(), quiet, policy=policy, now=NOW)

    assert d.triggers == {"R1": False, "R2": False, "R3": True, "R4": False, "R5": True}
    assert d.state == R.RECOVERING, "the card still has to show the case"
    assert "reclaim fired" not in d.reason.lower(), f"a confidence-only recovery claimed a reclaim: {d.reason!r}"
    assert d.reason == "confidence 0.25 crossed the floor without a reclaim", d.reason


def test_a_reclaim_names_which_trigger_fired():
    """The other half: when a reclaim DID happen, the sentence says which one, so the two cases are distinguishable."""
    r4_and_momentum = snap(close=100.0, rsi=42.0, rsi_prev=36.0, sma20=95.0, macd_up_sessions=0,
                           catalyst_confidence=0.0)
    d = R.evaluate(case(), r4_and_momentum, now=NOW)
    assert d.triggers["R4"] is True and d.state == R.RECOVERING
    assert d.reason == "a reclaim fired (R4); confidence 0.35", d.reason

    # 141.65 is above both the +1% exit reclaim and the 138.00 stop, so the sentence must name BOTH, not just the first.
    r1 = R.evaluate(case(), snap(close=141.65, rsi=39.1, rsi_prev=36.0, sma20=151.62), now=NOW)
    assert r1.triggers["R1"] is True
    assert "reclaim fired (R1+R2)" in r1.reason, r1.reason


def test_the_run_pass_reports_the_decay_window_on_every_row():
    """`session_decay` was tested and called by nothing — a documented policy that had quietly stopped running."""
    class _Store:
        def list_open(self, limit=200):
            return [case()]

    out = R.run_pass(_Store(), lambda c: snap(close=141.65), now=NOW, dry_run=True, notify=lambda *a, **k: None)
    row = out["decisions"][0]
    assert row["decay"]["decay_sessions"] == 20
    assert row["decay"]["sessions_since_trigger"] is None      # no invented session count
    assert set(row["decay"]) >= {"decayed", "digest_only", "auto_close"}


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
    """Piece A's CAS write boundary: the transition applies only to the row the pass READ."""

    def __init__(self, cases):
        self.cases = [dict(c) for c in cases]
        self.written = []

    def list(self):
        return [dict(c) for c in self.cases]

    def set_state(self, key, state, *, expect):
        for row in self.cases:
            if str(row.get("case_key")) != str(key):
                continue
            if (str(row.get("state")) != expect.get("state")
                    or str(row.get("operator_decision") or "none") != expect.get("operator_decision")):
                return (0, "state_changed")
            row["state"] = state
            self.written.append((key, state))
            return (1, None)
        return (0, "not_found")


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
    """CAS-aware: an unconditional write is what the finding removed, so the fake honours the expectation."""

    def __init__(self, cases):
        self.cases = [dict(c) for c in cases]
        self.written = []

    def list(self):
        return [dict(c) for c in self.cases]

    def set_state(self, key, state, *, expect):
        for row in self.cases:
            if str(row.get("case_key")) != str(key):
                continue
            if (str(row.get("state")) != expect.get("state")
                    or str(row.get("operator_decision") or "none") != expect.get("operator_decision")):
                return (0, "state_changed")
            row["state"] = state
            self.written.append((key, state))
            return (1, None)
        return (0, "not_found")


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
    def set_state(self, key, state, *, expect):
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
    assert out["decisions"][0]["notify"]["reason"].startswith("state write did not apply")


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


# ── CX3-B-F1: a decision taken after list() is a compare-and-set miss ─────────────────────────────────────
_READY_SNAP = {"close": 102.0, "rsi": 35.0, "sma20": 99.0, "fetched_at": NOW.isoformat()}
_DEMO_KEY = "DEMO:DEMO_IRA:2030-01-10"


def _live_cas_store(row):
    class LiveCasStore:
        """A real CAS boundary: the row moves only when it still matches what the pass read."""

        def __init__(self, initial):
            self.row = dict(initial)
            self.writes = []

        def list(self):
            return [dict(self.row)]

        def set_state(self, key, state, *, expect):
            if (str(self.row.get("state")) != expect.get("state")
                    or str(self.row.get("operator_decision") or "none") != expect.get("operator_decision")):
                return (0, "state_changed")
            self.row["state"] = state
            self.writes.append((key, state))
            return (1, None)

    return LiveCasStore(row)


def test_a_decision_taken_after_listing_is_a_cas_miss_and_never_pages(tmp_path):
    """CX3-B-F1: the operator closes the case between list() and the write.

    The stale read concluded RE_ENTRY_READY; the durable boundary must refuse it, change zero rows, keep the
    operator's decision and call no notifier.
    """
    store = _live_cas_store({**_t1_row(), "state": R.WATCHING, "operator_decision": "none"})
    calls = []

    def snapshot_for(case):
        # Deterministic interleaving: the close lands AFTER list() and BEFORE the write.
        store.row["state"] = R.CLOSED
        store.row["operator_decision"] = "closed"
        return dict(_READY_SNAP)

    pending = tmp_path / "pending.json"
    out = R.run_pass(store, snapshot_for, now=NOW, dry_run=False,
                     notify=lambda c: calls.append(c) or {"sent": True}, pending_path=pending)

    assert store.row["state"] == R.CLOSED and store.row["operator_decision"] == "closed"
    assert store.writes == [] and calls == [] and out["notifier_calls"] == 0
    assert out["changed"] == 0
    row = out["decisions"][0]
    assert row["state"] == R.RE_ENTRY_READY            # what the stale read concluded...
    assert row["cas"] == {"status": "cas_miss", "refusal": "state_changed"}   # ...was refused
    assert row["notify"]["sent"] is False

    # The responsibility persisted before the refused write is revalidated on the next pass: CLOSED settles it.
    second = R.run_pass(store, lambda c: dict(_READY_SNAP), now=NOW, dry_run=False,
                        notify=lambda c: calls.append(c) or {"sent": True}, pending_path=pending)
    assert calls == [] and second["notifier_calls"] == 0 and second["pending"] == 0
    assert json.loads(pending.read_text(encoding="utf-8")) == {}


def test_a_store_that_cannot_compare_and_set_is_refused_not_written(tmp_path):
    """An unconditional set_state is the defect, not a fallback: refuse it and page nothing."""
    class UnconditionalStore(RecordingStore):
        def set_state(self, key, state):          # no expectation -> cannot prove the row it read
            self.written.append((key, state))

    store = UnconditionalStore([_t1_row()])
    calls = []
    out = R.run_pass(store, lambda c: dict(_READY_SNAP), now=NOW, dry_run=False,
                     notify=lambda c: calls.append(c) or {"sent": True}, pending_path=tmp_path / "p.json")

    assert store.written == [] and calls == [] and out["notifier_calls"] == 0
    assert out["decisions"][0]["cas"]["status"] == "cas_unsupported"


# ── CX3-B-F2: retry responsibility survives notifier absence and storage failure ─────────────────────────
def test_an_unavailable_notifier_keeps_a_durable_retry_until_it_returns(tmp_path, monkeypatch):
    """CX3-B-F2: an absent notifier must not let a committed transition lose its page."""
    monkeypatch.setattr(R, "_default_notify", lambda: None)
    pending = tmp_path / "pending.json"

    first = R.run_pass(RecordingStore([_t1_row()]), lambda c: dict(_READY_SNAP), now=NOW, dry_run=False,
                       notify=None, pending_path=pending)
    assert first["changed"] == 1 and first["notifier_calls"] == 0
    doc = json.loads(pending.read_text(encoding="utf-8"))
    assert doc[_DEMO_KEY]["state"] == R.RE_ENTRY_READY        # durable BEFORE piece C could be called
    assert first["decisions"][0]["notify_pending"] is True

    sent = []
    second = R.run_pass(RecordingStore([{**_t1_row(), "state": R.RE_ENTRY_READY}]), lambda c: dict(_READY_SNAP),
                        now=NOW, dry_run=False, notify=lambda c: sent.append(c) or {"sent": True},
                        pending_path=pending)
    assert second["changed"] == 0 and second["notifier_calls"] == 1
    assert sent[0]["state"] == R.RE_ENTRY_READY
    assert json.loads(pending.read_text(encoding="utf-8")) == {}


def test_retry_responsibility_is_durable_before_the_notifier_is_called(tmp_path):
    """The pending record exists by the time the send starts, so an interruption after the state commit retries."""
    pending = tmp_path / "pending.json"
    seen = []

    def notify(case):
        seen.append(json.loads(pending.read_text(encoding="utf-8")))
        return {"sent": True}

    out = R.run_pass(RecordingStore([_t1_row()]), lambda c: dict(_READY_SNAP), now=NOW, dry_run=False,
                     notify=notify, pending_path=pending)
    assert out["notifier_calls"] == 1
    assert seen and seen[0][_DEMO_KEY]["state"] == R.RE_ENTRY_READY
    assert json.loads(pending.read_text(encoding="utf-8")) == {}      # confirmed delivery clears it


def test_a_pending_store_failure_leaves_the_transition_visible_and_recovers(tmp_path):
    """CX3-B-F2: no durable responsibility -> no state write, so the transition is still visible next pass."""
    obstruction = tmp_path / "not-a-dir"
    obstruction.write_text("x", encoding="utf-8")
    broken = obstruction / "pending.json"
    store = RecordingStore([_t1_row()])
    calls = []

    first = R.run_pass(store, lambda c: dict(_READY_SNAP), now=NOW, dry_run=False,
                       notify=lambda c: calls.append(c) or {"sent": True}, pending_path=broken)
    assert store.written == [], "a transition whose retry responsibility is not durable must not be written"
    assert first["changed"] == 0 and first["notifier_calls"] == 0 and calls == []
    row = first["decisions"][0]
    assert row["write_error"].startswith("retry responsibility")
    assert row["pending_store_error"]
    assert row.get("notify_pending") is not True

    fixed = tmp_path / "ok" / "pending.json"
    second = R.run_pass(store, lambda c: dict(_READY_SNAP), now=NOW, dry_run=False,
                        notify=lambda c: calls.append(c) or {"sent": True}, pending_path=fixed)
    assert second["changed"] == 1 and second["notifier_calls"] == 1 and len(calls) == 1


# ── CX3-B-F3: retries are revalidated at the dispatch boundary ────────────────────────────────────────────
def _seed_pending(path, *, state=R.RECOVERING):
    path.write_text(json.dumps({_DEMO_KEY: {
        "state": state, "attempts": 1, "first_failed_at": NOW.isoformat(), "last_error": "transport refused"}}),
        encoding="utf-8")


def test_a_pending_retry_for_an_operator_closed_case_never_pages(tmp_path):
    pending = tmp_path / "pending.json"
    _seed_pending(pending)
    calls = []
    out = R.run_pass(RecordingStore([{**_t1_row(), "state": R.CLOSED, "operator_decision": "closed"}]),
                     lambda c: dict(_READY_SNAP), now=NOW, dry_run=False,
                     notify=lambda c: calls.append(c) or {"sent": True}, pending_path=pending)

    assert calls == [] and out["notifier_calls"] == 0
    assert "operator decision holds" in out["decisions"][0]["notify"]["reason"]
    assert json.loads(pending.read_text(encoding="utf-8")) == {}
    assert out["pending"] == 0


def test_a_pending_retry_for_a_snoozed_row_never_pages_when_the_state_column_lags(tmp_path):
    """The operator decision settles the page even if ``state`` still says RECOVERING."""
    pending = tmp_path / "pending.json"
    _seed_pending(pending)
    calls = []
    out = R.run_pass(RecordingStore([{**_t1_row(), "state": R.RECOVERING, "operator_decision": "snoozed"}]),
                     lambda c: dict(_READY_SNAP), now=NOW, dry_run=False,
                     notify=lambda c: calls.append(c) or {"sent": True}, pending_path=pending)

    assert calls == [] and out["notifier_calls"] == 0
    assert "operator decision holds" in out["decisions"][0]["notify"]["reason"]
    assert json.loads(pending.read_text(encoding="utf-8")) == {}


def test_a_stale_pending_retry_keeps_responsibility_then_sends_when_the_quote_is_fresh(tmp_path):
    pending = tmp_path / "pending.json"
    _seed_pending(pending)
    calls = []
    stale = {"close": 102.0, "rsi": 35.0, "sma20": 99.0, "fetched_at": STALE_FETCHED}

    out = R.run_pass(RecordingStore([{**_t1_row(), "state": R.RECOVERING}]), lambda c: stale, now=NOW,
                     dry_run=False, notify=lambda c: calls.append(c) or {"sent": True}, pending_path=pending)
    assert calls == [] and out["notifier_calls"] == 0
    assert "quote not current" in out["decisions"][0]["notify"]["reason"]
    assert out["decisions"][0]["notify_pending"] is True
    assert _DEMO_KEY in json.loads(pending.read_text(encoding="utf-8"))   # honest responsibility retained

    fresh = {"close": 102.0, "rsi": 35.0, "sma20": 130.0, "fetched_at": NOW.isoformat()}
    second = R.run_pass(RecordingStore([{**_t1_row(), "state": R.RECOVERING}]), lambda c: fresh, now=NOW,
                        dry_run=False, notify=lambda c: calls.append(c) or {"sent": True}, pending_path=pending)
    assert second["notifier_calls"] == 1 and calls[0]["state"] == R.RECOVERING
    assert json.loads(pending.read_text(encoding="utf-8")) == {}


def test_a_pending_retry_whose_transition_never_applied_is_settled_without_paging(tmp_path):
    pending = tmp_path / "pending.json"
    _seed_pending(pending, state=R.RE_ENTRY_READY)
    calls = []
    quiet = {"close": 90.0, "rsi": 30.0, "sma20": 130.0, "fetched_at": NOW.isoformat()}

    out = R.run_pass(RecordingStore([_t1_row()]), lambda c: quiet, now=NOW, dry_run=False,
                     notify=lambda c: calls.append(c) or {"sent": True}, pending_path=pending)
    assert calls == [] and out["notifier_calls"] == 0
    assert "not pageable" in out["decisions"][0]["notify"]["reason"]
    assert json.loads(pending.read_text(encoding="utf-8")) == {}


# ── CX3-B-F4: eligibility is one contract; malformed or contradictory is unknown ─────────────────────────
def test_the_string_false_is_not_eligibility():
    d = R.evaluate(case(eligibility_json={"IRA": {"eligible": "false"}}), snap(close=152.0), now=NOW)
    assert d.state != R.RE_ENTRY_READY and d.eligible_accounts == []
    gate = next(a for a in d.annotations if a["gate"] == "eligibility_unknown")
    assert gate["account"] == "IRA" and gate["blocks_ready"] is True
    assert "not a boolean" in gate["detail"]
    assert d.state == R.RECOVERING, "the reclaim stays visible; only readiness is withheld"


@pytest.mark.parametrize("value", [["IRA"], {"nested": True}, 1, 0, "true", 1.5])
def test_container_and_non_boolean_eligibility_is_explicit_unknown(value):
    d = R.evaluate(case(eligibility_json={"IRA": value}), snap(close=152.0), now=NOW)
    assert d.state != R.RE_ENTRY_READY and d.eligible_accounts == []
    gate = next(a for a in d.annotations if a["gate"] == "eligibility_unknown" and a["account"] == "IRA")
    assert gate["blocks_ready"] is True


def test_eligible_true_with_a_future_date_is_contradictory_not_ready():
    d = R.evaluate(case(eligibility_json={"IRA": {"eligible": True, "eligible_from": "2099-01-01"}}),
                   snap(close=152.0), now=NOW)
    assert d.state != R.RE_ENTRY_READY and d.eligible_accounts == []
    gate = next(a for a in d.annotations if a["gate"] == "eligibility_unknown")
    assert "future" in gate["detail"] and gate["blocks_ready"] is True


def test_eligible_false_with_a_past_date_is_contradictory_not_a_valid_hold():
    d = R.evaluate(case(eligibility_json={"IRA": {"eligible": False, "eligible_from": "2026-10-01"}}),
                   snap(close=152.0), now=NOW)
    assert d.state != R.RE_ENTRY_READY and d.eligible_accounts == []
    assert any(a["gate"] == "eligibility_unknown" and "already passed" in (a.get("detail") or "")
               for a in d.annotations)


def test_an_unparseable_eligibility_date_is_unknown_not_open():
    d = R.evaluate(case(eligibility_json={"IRA": {"eligible": True, "eligible_from": "not-a-date"}}),
                   snap(close=152.0), now=NOW)
    assert d.state != R.RE_ENTRY_READY and d.eligible_accounts == []
    assert any(a["gate"] == "eligibility_unknown" for a in d.annotations)


def test_a_valid_date_open_pending_operator_row_still_reads_as_eligible():
    rows = [{"account": "schwab_roth_ira", "eligible": True, "eligible_from": "2026-11-01",
             "pending_operator_decision": True, "reason": "the hold date passed; awaiting the operator"}]
    d = R.evaluate(case(eligibility_json=rows), snap(close=152.0), now=NOW)
    assert d.state == R.RE_ENTRY_READY and d.eligible_accounts == ["schwab_roth_ira"]
    gate = next(a for a in d.annotations if a["account"] == "schwab_roth_ira")
    assert gate["gate"] == "pending_operator_decision"


# ── CX3-B-F5: non-finite/invalid market numbers never fire a trigger ──────────────────────────────────────
@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), True, False, None, "",
                                 0, -1.0, "not-a-number"])
def test_an_invalid_close_never_moves_a_case(bad):
    snapshot = {"close": bad, "sma20": 1.0, "rsi": 90.0, "fetched_at": NOW.isoformat()}
    d = R.evaluate(case(), snapshot, now=NOW)

    assert d.state == R.STOPPED_OUT and d.changed is False
    assert "market input unavailable" in d.reason
    assert d.triggers == {}, "no trigger may be evaluated on an unusable quote"


def test_non_finite_optional_market_fields_cannot_fire_triggers():
    snapshot = {"close": 102.0, "sma20": float("inf"), "rsi": float("nan"), "rsi_prev": float("nan"),
                "stop_level": float("nan"), "macd_up_sessions": float("inf"),
                "catalyst_confidence": 0.99, "catalyst_sessions_ago": float("nan"),
                "fetched_at": NOW.isoformat()}
    d = R.evaluate(_t1_row(), snapshot, now=NOW)

    assert d.triggers == {"R1": True, "R2": False, "R3": False, "R4": False, "R5": False}
    assert d.state == R.RECOVERING, "the one valid reclaim fires; nothing malformed does"


def test_boolean_market_fields_are_not_numbers():
    snapshot = {"close": 102.0, "sma20": True, "rsi": 39.0, "rsi_prev": False, "stop_level": True,
                "macd_up_sessions": True, "catalyst_confidence": True, "catalyst_sessions_ago": True,
                "fetched_at": NOW.isoformat()}
    d = R.evaluate(_t1_row(), snapshot, now=NOW)

    assert d.triggers["R2"] is False and d.triggers["R3"] is False
    assert d.triggers["R4"] is False and d.triggers["R5"] is False
    assert d.state == R.RECOVERING


def test_a_valid_fresh_reclaim_still_reaches_ready():
    """The control: hardening the inputs must not break a genuinely fresh reclaim."""
    d = R.evaluate(_t1_row(), {"close": 102.0, "rsi": 45.0, "rsi_prev": 39.0, "sma20": 99.0,
                               "stop_level": 101.0, "macd_up_sessions": 0, "catalyst_confidence": 0.0,
                               "fetched_at": NOW.isoformat()}, now=NOW)

    assert d.triggers == {"R1": True, "R2": True, "R3": True, "R4": True, "R5": False}
    assert d.state == R.RE_ENTRY_READY
