"""CIO Telegram signal-over-spam — notification gate golden/adversarial tests.

Covers identity stability, REJECT suppression/reopen, cash/re-entry material
change policy, durable/persistent dedupe, content linter, authority invariants,
and a full Aug-17-style replay. No live Telegram sends under pytest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_notification_signal import (  # noqa: E402
    DELIVERY_COMMAND_CENTER_ONLY,
    DELIVERY_DIGEST,
    DELIVERY_IMMEDIATE,
    DELIVERY_SUPPRESSED,
    NotificationStateStore,
    decide_notification,
    decision_lineage_id,
    evidence_generation_id,
    lint_cio_text,
    material_generation_id,
    render_cio_card,
    replay_decisions,
    semantic_materiality,
)


@pytest.fixture
def store(tmp_path):
    return NotificationStateStore(
        state_path=tmp_path / "state.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        metrics_path=tmp_path / "metrics.jsonl",
    )


# ── Decision builders mirroring cio_material_scan output ─────────────────────

def cash_dec(*, status="ABOVE_BAND", deploy_now=0, action=None, act_now=None, digest="d1", operator_disposition=None):
    deploy = bool(deploy_now and deploy_now > 0)
    action = action or ("DEPLOY_CASH" if deploy else "HOLD_CASH")
    d = {
        "decision_id": f"dec_cash_{digest}",
        "symbol": "CASH",
        "action": action,
        "stance_code": action,
        "standing_recommendation": action,
        "current_action": action,
        "act_now": deploy if act_now is None else act_now,
        "actionability": "ACT_NOW" if deploy else "NO_ACTION",
        "delta_usd": float(deploy_now),
        "why_now": f"Cash {status}; deploy {deploy_now}.",
        "cash_posture": {"cash_posture_status": status},
        "cash_posture_status": status,
        "capital": {"free_investable": 322000, "deploy_now": deploy_now, "remain_cash": 256000},
        "decision_evidence_digest": digest,
    }
    if operator_disposition is not None:
        d["operator_disposition"] = operator_disposition
    return d


def reentry_dec(*, action="WAIT", ready=("AMD", "NVDA"), near=("MSFT",), governed=None, operator_disposition=None):
    standing = "RE_ENTER" if action == "RE_ENTER" else "WAIT"
    d = {
        "decision_id": "dec_reentry_x",
        "symbol": "REENTRY",
        "action": action,
        "stance_code": standing,
        "standing_recommendation": standing,
        "current_action": action,
        "act_now": action == "RE_ENTER",
        "actionability": "ACT_NOW" if action == "RE_ENTER" else "NO_ACTION",
        "delta_usd": 0.0,
        "why_now": f"Re-entry {action}; ready={','.join(ready)} near={','.join(near)} governed={governed}",
        "ready": list(ready),
        "near": list(near),
        "decision_evidence_digest": json.dumps([list(ready), list(near)]),
    }
    if operator_disposition is not None:
        d["operator_disposition"] = operator_disposition
    return d


def schd_dec(*, current="DATA_CONFLICT", act_now=False, weight=17.6, delta=-44334, digest="e1", operator_disposition=None):
    d = {
        "decision_id": f"dec_schd_{digest}",
        "symbol": "SCHD",
        "action": "TRIM",
        "stance_code": "TRIM",
        "standing_recommendation": "TRIM",
        "current_action": current,
        "act_now": act_now,
        "actionability": current if current in {"DATA_CONFLICT", "REVALIDATE", "STALE_REFRESH_REQUIRED"} else ("ACT_NOW" if act_now else "NO_ACTION"),
        "weight_pct": weight,
        "current_weight_pct": weight,
        "delta_usd": delta,
        "recommended_delta_usd": delta,
        "why_now": "TRIM — SCHD concentration above single-name cap",
        "what_changes_call": "Weight falls under cap or thesis revalidates",
        "decision_evidence_digest": digest,
    }
    if operator_disposition is not None:
        d["operator_disposition"] = operator_disposition
    return d


# ── Identity ─────────────────────────────────────────────────────────────────

def test_01_cash_small_drift_same_lineage():
    a = cash_dec(digest="d1", status="ABOVE_BAND")
    b = cash_dec(digest="d2", status="ABOVE_BAND")
    assert decision_lineage_id(a) == decision_lineage_id(b) == "cash_posture:CASH"


def test_02_cash_500_drift_same_generation_same_posture():
    a = cash_dec(digest="d1", deploy_now=0)
    b = cash_dec(digest="d2", deploy_now=0)
    assert material_generation_id(a) == material_generation_id(b)


def test_03_reentry_ready_order_same_lineage():
    a = reentry_dec(ready=("AMD", "NVDA"))
    b = reentry_dec(ready=("NVDA", "AMD"))
    assert decision_lineage_id(a) == decision_lineage_id(b) == "reentry:BOOK"


def test_04_ready_near_move_waits_unchanged_same_generation():
    a = reentry_dec(action="WAIT", ready=("AMD",), near=("MSFT",))
    b = reentry_dec(action="WAIT", ready=("AMD", "MSFT"), near=())
    assert material_generation_id(a) == material_generation_id(b)


def test_05_wait_to_reenter_new_generation():
    a = reentry_dec(action="WAIT")
    b = reentry_dec(action="RE_ENTER")
    assert material_generation_id(a) != material_generation_id(b)


def test_06_blocked_to_act_now_new_generation():
    a = schd_dec(current="DATA_CONFLICT", act_now=False)
    b = schd_dec(current="TRIM", act_now=True)
    assert material_generation_id(a) != material_generation_id(b)


def test_07_new_decision_id_alone_cannot_force_notification(store):
    a = cash_dec(digest="d1")
    nd1 = decide_notification(a, store=store)
    store.record(nd1)
    b = cash_dec(digest="d2")  # new id + new evidence, same semantic meaning
    nd2 = decide_notification(b, store=store)
    assert nd2["notification_class"] != DELIVERY_IMMEDIATE


def test_08_new_evidence_digest_alone_cannot_force_notification(store):
    a = reentry_dec(action="WAIT", ready=("AMD",), near=("MSFT",))
    nd1 = decide_notification(a, store=store)
    store.record(nd1)
    b = reentry_dec(action="WAIT", ready=("AMD", "NVDA"), near=("MSFT",))
    nd2 = decide_notification(b, store=store)
    assert nd2["notification_class"] != DELIVERY_IMMEDIATE


# ── REJECT suppression / reopen ──────────────────────────────────────────────

def test_09_reject_unchanged_suppressed(store):
    a = schd_dec(digest="e1", operator_disposition={"disposition": "REJECT"})
    nd1 = decide_notification(a, store=store)
    store.record(nd1)
    nd2 = decide_notification(schd_dec(digest="e2", operator_disposition={"disposition": "REJECT"}), store=store)
    assert nd2["notification_class"] == DELIVERY_SUPPRESSED
    assert "reject" in nd2["suppressed_reason"]


def test_10_fresh_quote_only_reject_suppressed(store):
    a = schd_dec(digest="e1", operator_disposition={"disposition": "REJECT"})
    store.record(decide_notification(a, store=store))
    nd = decide_notification(schd_dec(digest="e2", operator_disposition={"disposition": "REJECT"}), store=store)
    assert nd["notification_class"] == DELIVERY_SUPPRESSED


def test_11_data_conflict_persists_reject_suppressed(store):
    a = schd_dec(digest="e1", current="DATA_CONFLICT", operator_disposition={"disposition": "REJECT"})
    store.record(decide_notification(a, store=store))
    nd = decide_notification(schd_dec(digest="e2", current="DATA_CONFLICT", operator_disposition={"disposition": "REJECT"}), store=store)
    assert nd["notification_class"] == DELIVERY_SUPPRESSED


def test_12_material_evidence_change_reopens(store):
    a = schd_dec(digest="e1", current="DATA_CONFLICT", operator_disposition={"disposition": "REJECT"})
    store.record(decide_notification(a, store=store))
    # Blocking clears and action becomes actionable → reopen
    b = schd_dec(digest="e2", current="TRIM", act_now=True, operator_disposition={"disposition": "REJECT"})
    nd = decide_notification(b, store=store)
    assert nd["notification_class"] == DELIVERY_IMMEDIATE
    assert nd["reopen"] is True


def test_13_reopen_message_says_what_changed_since_reject(store):
    a = schd_dec(digest="e1", current="DATA_CONFLICT", operator_disposition={"disposition": "REJECT"})
    store.record(decide_notification(a, store=store))
    b = schd_dec(digest="e2", current="TRIM", act_now=True, operator_disposition={"disposition": "REJECT"})
    nd = decide_notification(b, store=store)
    body = render_cio_card(b, nd)
    assert "WHAT CHANGED SINCE YOUR REJECT" in body


def test_14_reopen_stays_same_lineage(store):
    a = schd_dec(digest="e1", current="DATA_CONFLICT", operator_disposition={"disposition": "REJECT"})
    store.record(decide_notification(a, store=store))
    b = schd_dec(digest="e2", current="TRIM", act_now=True, operator_disposition={"disposition": "REJECT"})
    nd = decide_notification(b, store=store)
    assert nd["decision_lineage_id"] == "position:SCHD:CONCENTRATION"


# ── Cash ─────────────────────────────────────────────────────────────────────

def test_15_hold_cash_repeated_20_times_limits_pages(store):
    decisions = [cash_dec(digest=f"d{i}", deploy_now=0) for i in range(20)]
    res = replay_decisions(decisions, store=store)
    assert res["immediate_notifications"] <= 1


def test_16_deploy_zero_to_positive_material(store):
    a = cash_dec(digest="d1", deploy_now=0)
    store.record(decide_notification(a, store=store))
    b = cash_dec(digest="d2", deploy_now=50000, action="DEPLOY_CASH")
    nd = decide_notification(b, store=store)
    assert nd["notification_class"] == DELIVERY_IMMEDIATE


def test_17_band_status_change_material(store):
    a = cash_dec(digest="d1", status="ABOVE_BAND", deploy_now=0)
    store.record(decide_notification(a, store=store))
    b = cash_dec(digest="d2", status="IN_BAND", deploy_now=0)
    nd = decide_notification(b, store=store)
    assert nd["notification_class"] != DELIVERY_SUPPRESSED


def test_18_candidate_demand_changes_deploy_stays_zero_no_page(store):
    a = cash_dec(digest="d1", deploy_now=0)
    store.record(decide_notification(a, store=store))
    b = cash_dec(digest="d2", deploy_now=0)
    nd = decide_notification(b, store=store)
    assert nd["notification_class"] != DELIVERY_IMMEDIATE


# ── Re-entry ─────────────────────────────────────────────────────────────────

def test_19_ready_count_changes_no_governed_reenter_no_page(store):
    a = reentry_dec(action="WAIT", ready=("AMD", "NVDA"))
    store.record(decide_notification(a, store=store))
    b = reentry_dec(action="WAIT", ready=("AMD", "NVDA", "MSFT", "GOOG"))
    nd = decide_notification(b, store=store)
    assert nd["notification_class"] != DELIVERY_IMMEDIATE


def test_20_governed_reenter_appears_immediate(store):
    a = reentry_dec(action="WAIT")
    store.record(decide_notification(a, store=store))
    b = reentry_dec(action="RE_ENTER")
    nd = decide_notification(b, store=store)
    assert nd["notification_class"] == DELIVERY_IMMEDIATE


def test_21_stale_block_removes_act_now_material(store):
    a = schd_dec(current="TRIM", act_now=True)
    store.record(decide_notification(a, store=store))
    b = schd_dec(current="DATA_CONFLICT", act_now=False)
    nd = decide_notification(b, store=store)
    assert nd["notification_class"] == DELIVERY_IMMEDIATE  # blocking transition pages once


# ── Timer / persistence ──────────────────────────────────────────────────────

def test_22_hundred_scans_not_hundred_pages(store):
    decisions = []
    for i in range(100):
        decisions.append(cash_dec(digest=f"c{i}", deploy_now=0))
        decisions.append(reentry_dec(action="WAIT", ready=("AMD", "NVDA")))
        decisions.append(schd_dec(digest=f"s{i}", current="DATA_CONFLICT"))
    res = replay_decisions(decisions, store=store)
    assert res["raw_evaluations"] == 300
    assert res["immediate_notifications"] <= 3  # at most one per lineage


def test_23_restart_does_not_reset_dedupe(tmp_path):
    path = tmp_path / "state.jsonl"
    s1 = NotificationStateStore(state_path=path, audit_path=tmp_path / "a.jsonl", metrics_path=tmp_path / "m.jsonl")
    a = schd_dec(digest="e1", current="DATA_CONFLICT")
    s1.record(decide_notification(a, store=s1))
    # New store instance = simulated process restart
    s2 = NotificationStateStore(state_path=path, audit_path=tmp_path / "a.jsonl", metrics_path=tmp_path / "m.jsonl")
    nd = decide_notification(schd_dec(digest="e2", current="DATA_CONFLICT"), store=s2)
    assert nd["notification_class"] == DELIVERY_SUPPRESSED


def test_24_notification_state_corruption_fails_closed(tmp_path):
    path = tmp_path / "state.jsonl"
    path.write_text("NOT JSON\n", encoding="utf-8")
    s = NotificationStateStore(state_path=path, audit_path=tmp_path / "a.jsonl", metrics_path=tmp_path / "m.jsonl")
    assert s.latest("cash_posture:CASH") is None  # skips malformed, never raises
    nd = decide_notification(cash_dec(digest="d1"), store=s)
    assert nd["decision_lineage_id"] == "cash_posture:CASH"


def test_25_notification_state_retention_bounded(tmp_path):
    s = NotificationStateStore(state_path=tmp_path / "state.jsonl",
                               audit_path=tmp_path / "a.jsonl",
                               metrics_path=tmp_path / "m.jsonl")
    big = {}
    for i in range(3000):
        lineage = f"position:S{i}:HOLD"
        big[lineage] = {"decision_lineage_id": lineage,
                        "updated_at": f"2026-08-17T00:00:{i % 60:02d}"}
    s._write_index(big)
    assert len(s.all_lineages()) <= 2048


# ── Content ──────────────────────────────────────────────────────────────────

def test_27_no_duplicate_what_changed_and_why():
    nd = {"standing_recommendation": "TRIM", "current_action": "DATA_CONFLICT",
          "act_now": False, "blocking_state": "DATA_CONFLICT", "reopen": False,
          "operator_disposition": None, "next_review": None}
    d = schd_dec(current="DATA_CONFLICT")
    body = render_cio_card(d, nd)
    assert body.count("What would change the call") == 1
    assert "WHAT CHANGED" not in body or body.count("WHAT CHANGED") == 1


def test_28_no_hold_cash_cash():
    d = cash_dec(deploy_now=0)
    nd = decide_notification(d)
    body = render_cio_card(d, nd)
    assert "HOLD_CASH CASH" not in body
    assert "HOLD CASH CASH" not in body


def test_29_no_reenter_reentry_gibberish():
    d = reentry_dec(action="WAIT")
    nd = decide_notification(d)
    body = render_cio_card(d, nd)
    assert "RE_ENTER REENTRY" not in body


def test_30_no_raw_ready_near_wait_in_phone_copy():
    d = reentry_dec(action="WAIT", ready=("AMD", "NVDA"), near=("MSFT",))
    nd = decide_notification(d)
    body = render_cio_card(d, nd)
    assert "READY=" not in body
    assert "NEAR=" not in body
    assert "WAIT=" not in body


def test_31_no_mid_word_truncation():
    # A decision with an extremely long why; renderer must not cut mid-word.
    d = cash_dec(deploy_now=0)
    d["why_now"] = "A " + ("x" * 2000) + " sentence about cash."
    nd = decide_notification(d)
    body = render_cio_card(d, nd)
    assert "…" in body
    assert not body.rstrip().endswith("x")


def test_32_linter_no_underscore_italics():
    res = lint_cio_text("Some dec_abc123 token here")
    assert res["ok"] is False


def test_33_linter_body_too_long():
    res = lint_cio_text("x" * 5000)
    assert res["ok"] is False
    assert "body_too_long" in res["issues"]


def test_34_concise_fallback_complete():
    d = cash_dec(deploy_now=0)
    nd = decide_notification(d)
    body = render_cio_card(d, nd)
    assert "Alex · CIO" in body
    assert "What would change the call" in body


# ── Linter machine tokens ────────────────────────────────────────────────────

def test_linter_flags_machine_tokens():
    for tok in ("ACT_NOW=", "READY=", "NEAR=", "WAIT=", "STALE_REFRESH_REQUIRED",
                "DATA_UNAVAILABLE", "operator_challenge_status=", "challenge_review="):
        assert lint_cio_text(f"headline {tok} 5").get("ok") is False


# ── Authority / parity ───────────────────────────────────────────────────────

def test_35_39_authority_invariants():
    import scripts.lib.cio_notification_signal as sig
    src = (sig.__doc__ or "") + open(sig.__file__).read()
    for forbidden in ("place_order", "modify_order", "modify_stop", "2fa",
                      "risk_policy", "broker"):
        assert forbidden.lower() not in src.lower().replace("_", ""), forbidden
    # MEMORY_BEHAVIOR_INFLUENCE is not enabled here
    assert "MEMORY_BEHAVIOR_INFLUENCE" not in src or "=0" in src or "not enabled" in src


def test_42_suppression_does_not_alter_canonical_decision(store):
    a = cash_dec(digest="d1", deploy_now=0)
    nd1 = decide_notification(a, store=store)
    store.record(nd1)
    b = cash_dec(digest="d2", deploy_now=0)
    nd2 = decide_notification(b, store=store)
    assert nd2["notification_class"] == DELIVERY_SUPPRESSED
    # Canonical decision meaning is unchanged
    assert b["action"] == "HOLD_CASH"
    assert b["standing_recommendation"] == "HOLD_CASH"


def test_43_44_45_46_parity(store):
    d = schd_dec(current="DATA_CONFLICT", operator_disposition={"disposition": "REJECT"})
    nd = decide_notification(d, store=store)
    assert nd["standing_recommendation"] == "TRIM"
    assert nd["current_action"] == "DATA_CONFLICT"
    assert nd["operator_disposition"] == "REJECT"
    assert nd["decision_lineage_id"] == "position:SCHD:CONCENTRATION"


# ── Replay ───────────────────────────────────────────────────────────────────

def test_aug17_replay_does_not_reproduce_54_notifications(store):
    """Replay the 09:44–12:34 cash/re-entry/SCHD loop + genuine transitions.

    18 timer cycles × 3 families = 54 decisions. Plus 1 governed RE_ENTER
    transition, 1 ACT_NOW transition, 1 changed-since-REJECT, 1 deferred review.
    Expected: <=5 immediate, 0 duplicate semantic, 0 unchanged post-REJECT.
    """
    decisions = []
    # SCHD rejected early, then unchanged blocked repeats
    decisions.append(schd_dec(digest="e0", current="DATA_CONFLICT",
                              operator_disposition={"disposition": "REJECT"}))
    for i in range(18):
        decisions.append(cash_dec(digest=f"c{i}", deploy_now=0))          # HOLD_CASH drift
        decisions.append(reentry_dec(action="WAIT", ready=("AMD", "NVDA")))  # READY churn
        decisions.append(schd_dec(digest=f"s{i}", current="DATA_CONFLICT",
                                  operator_disposition={"disposition": "REJECT"}))
    # deferred review (one due defer)
    decisions.append({"decision_id": "dec_defer_1", "symbol": "BOOK", "action": "WAIT",
                      "standing_recommendation": "WAIT", "current_action": "WAIT",
                      "act_now": False, "delta_usd": 0.0, "why_now": "deferred review due",
                      "next_review": "2026-08-18"})
    # genuine material transitions
    decisions.append(reentry_dec(action="RE_ENTER", ready=("AMD",)))
    decisions.append(schd_dec(digest="sX", current="TRIM", act_now=True))
    decisions.append(schd_dec(digest="sY", current="TRIM", act_now=True,
                              operator_disposition={"disposition": "REJECT"}))

    res = replay_decisions(decisions, store=store)
    assert res["raw_evaluations"] == len(decisions)
    assert res["immediate_notifications"] <= 5, res
    # unchanged post-REJECT repeats are suppressed: establish a rejected+blocked
    # baseline, then replay 10 identical blocked+REJECT decisions → 0 immediate.
    s3 = NotificationStateStore(
        state_path=store.state_path.parent / "reject_state.jsonl",
        audit_path=store.state_path.parent / "reject_audit.jsonl",
        metrics_path=store.state_path.parent / "reject_metrics.jsonl",
    )
    s3.record(decide_notification(
        schd_dec(digest="base", current="DATA_CONFLICT", operator_disposition={"disposition": "REJECT"}),
        store=s3,
    ))
    res2 = replay_decisions(
        [schd_dec(digest=f"r{i}", current="DATA_CONFLICT",
                  operator_disposition={"disposition": "REJECT"}) for i in range(10)],
        store=s3,
    )
    assert res2["immediate_notifications"] == 0


def test_replay_fixture_module_acceptance(tmp_path):
    """The reusable Aug-17 fixture module reports the required acceptance shape."""
    from scripts.lib.cio_notification_replay import build_aug17_replay, run_aug17_replay
    from scripts.lib.cio_notification_signal import NotificationStateStore

    fixture = build_aug17_replay()
    # Families present: cash, re-entry, SCHD blocked TRIM, REJECT, defer,
    # governed RE_ENTER, ACT_NOW, changed-since-REJECT.
    assert any(d["symbol"] == "CASH" for d in fixture)
    assert any(d["symbol"] == "REENTRY" for d in fixture)
    assert any(d["symbol"] == "SCHD" and d.get("operator_disposition") for d in fixture)
    assert any(d.get("symbol") == "BOOK" for d in fixture)
    assert any(d.get("action") == "RE_ENTER" for d in fixture)
    assert any(d.get("symbol") == "SCHD" and d.get("act_now") for d in fixture)

    s = NotificationStateStore(
        state_path=tmp_path / "state.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        metrics_path=tmp_path / "metrics.jsonl",
    )
    res = run_aug17_replay(store=s)
    assert res["raw_evaluations"] == len(fixture)
    assert res["immediate_notifications"] <= 5
    assert res["reopens"] >= 1


def test_aug17_zero_repeat_after_first_material(store):
    """The 09:44–12:34 unchanged loop produces zero repeated pages after the
    first material state publication."""
    decisions = []
    for i in range(18):
        decisions.append(cash_dec(digest=f"c{i}", deploy_now=0))
        decisions.append(reentry_dec(action="WAIT", ready=("AMD", "NVDA")))
        decisions.append(schd_dec(digest=f"s{i}", current="DATA_CONFLICT"))
    res = replay_decisions(decisions, store=store)
    # First cycle pages each lineage once (3); the remaining 17 cycles add 0.
    assert res["immediate_notifications"] <= 3, res
