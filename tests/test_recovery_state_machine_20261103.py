"""Piece B — the recovery state machine (SPEC_RECOVERY_REENTRY_ENGINE_20261103 §3.2).

Operator's words: "SpaceX is back up to 141 … Nothing has notified me to get back in." The machine's job is to
say RECOVERING when a stopped-out position reclaims its exit, and RE_ENTRY_READY only when the reclaim plus
momentum reaches the floor AND at least one account can actually buy — with every gate shown as a dated
annotation rather than a silence. Pure functions: no DB, no store, no order path.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
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
            "catalyst_confidence": 0.88, "catalyst_sessions_ago": 1, "entry_high": 139.00}
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


def test_a_residual_is_not_held_when_it_is_a_small_fraction():
    """200 of ~1,400 shares (14.3%): the old path declared SPCX held and killed every re-entry. Not held."""
    assert R.residual_is_held(case(), R.DEFAULT_POLICY) is False
    held = case(residual_shares=600.0)  # 43% of pre-exit: genuinely held
    assert R.residual_is_held(held, R.DEFAULT_POLICY) is True
    d = R.evaluate(held, snap(close=152.0), now=NOW)
    assert d.state != R.RE_ENTRY_READY
    assert any(a["gate"] == "residual_held" and a["blocks_ready"] for a in d.annotations)


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
    assert {"IRA", "taxable"} <= blockers      # every blocked account is named; the residual gate rides too


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
    assert policy["residual_remaining_fraction"] == 0.15
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


def test_run_pass_returns_decisions_and_writes_only_through_the_store():
    store = FakeStore([case(), case(case_key="OTHER:x", symbol="OTHER", exit_price=10.0, residual_shares=900.0)])
    out = R.run_pass(store, lambda c: snap(), dry_run=False)

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
           "triggers": {"r1_reclaim_exit_pct": 0.02, "r3_rsi_cross": 45, "r3_macd_histogram_sessions": 3,
                        "r5_catalyst_min_confidence": 0.9, "decay_sessions": 30},
           "confidence": {"weights": {"r1": 0.4, "r4": 0.3}, "ready_floor": 0.6},
           "residual": {"residual_remaining_fraction": 0.1}}
    path = tmp_path / "recovery_policy.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")

    policy = R.load_policy(path)
    assert policy["reclaim_exit_pct"] == 0.02 and policy["rsi_level"] == 45
    assert policy["macd_up_sessions"] == 3 and policy["catalyst_min_confidence"] == 0.9
    assert policy["decay_sessions"] == 30 and policy["residual_remaining_fraction"] == 0.1
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
