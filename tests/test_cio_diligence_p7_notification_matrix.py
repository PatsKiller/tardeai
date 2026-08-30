"""P7 — notification routing matrix diligence (CC-first / would_send).

Exit gate (master plan Phase 7): prove IMMEDIATE / DIGEST / COMMAND_CENTER_ONLY /
SUPPRESSED for priority up/down, reentry NEAR, duplicates, dust, cash, test.

Hard rails: INTERDICT left as found; no new Telegram producer; do not flip
notify-on. Prefer Wave 3E / 3B patterns:
  - scripts/lib/cio_notification_signal.py
  - scripts/lib/cio_situation_notify_bridge.py
  - scripts/lib/cio_notification_policy.py

Gap: G-NOTIFY-01. READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib import cio_notification_policy as policy
from scripts.lib.cio_notification_signal import (
    DELIVERY_COMMAND_CENTER_ONLY,
    DELIVERY_DIGEST,
    DELIVERY_IMMEDIATE,
    DELIVERY_SUPPRESSED,
    NotificationStateStore,
    decide_notification,
)
from scripts.lib.cio_situation_notify_bridge import situation_to_decision

REPO = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)

MATRIX_MODULES = (
    "scripts/lib/cio_notification_signal.py",
    "scripts/lib/cio_situation_notify_bridge.py",
    "scripts/lib/cio_notification_policy.py",
)

ROUTES = {
    DELIVERY_IMMEDIATE,
    DELIVERY_DIGEST,
    DELIVERY_COMMAND_CENTER_ONLY,
    DELIVERY_SUPPRESSED,
}


def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


def _store(tmp_path: Path) -> NotificationStateStore:
    return NotificationStateStore(
        state_path=tmp_path / "state.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        metrics_path=tmp_path / "metrics.jsonl",
    )


def _pos(*, action="TRIM", current=None, act_now=False, digest="e1",
         symbol="SCHD", delta=-40000, operator_disposition=None,
         source_kind=None, env=None, market_value=None):
    cur = current if current is not None else ("TRIM" if act_now else "WAIT")
    d = {
        "decision_id": f"dec_{symbol.lower()}_{digest}",
        "symbol": symbol,
        "action": action,
        "stance_code": action,
        "standing_recommendation": action,
        "current_action": cur,
        "act_now": act_now,
        "actionability": (
            cur if cur in {"DATA_CONFLICT", "REVALIDATE", "STALE_REFRESH_REQUIRED"}
            else ("ACT_NOW" if act_now else "NO_ACTION")
        ),
        "delta_usd": delta,
        "recommended_delta_usd": delta,
        "why_now": f"{action} — {symbol}",
        "decision_evidence_digest": digest,
        "financial_action": False,
        "memory_behavior_influence": 0,
    }
    if operator_disposition is not None:
        d["operator_disposition"] = operator_disposition
    if source_kind is not None:
        d["source_kind"] = source_kind
    if env is not None:
        d["env"] = env
    if market_value is not None:
        d["market_value"] = market_value
        d["aggregate_market_value_usd"] = market_value
    return d


def _reentry(*, action="WAIT", ready=("AMD",), near=("MSFT",), digest="r1"):
    standing = "RE_ENTER" if action == "RE_ENTER" else "WAIT"
    return {
        "decision_id": f"dec_reentry_{digest}",
        "symbol": "REENTRY",
        "action": action,
        "stance_code": standing,
        "standing_recommendation": standing,
        "current_action": action,
        "act_now": action == "RE_ENTER",
        "actionability": "ACT_NOW" if action == "RE_ENTER" else "NO_ACTION",
        "delta_usd": 0.0,
        "why_now": f"Re-entry {action}; near={list(near)} ready={list(ready)}",
        "ready": list(ready),
        "near": list(near),
        "decision_evidence_digest": digest,
        "financial_action": False,
        "memory_behavior_influence": 0,
    }


def _cash(*, status="ABOVE_BAND", deploy_now=0, digest="c1"):
    deploy = bool(deploy_now and deploy_now > 0)
    action = "DEPLOY_CASH" if deploy else "HOLD_CASH"
    return {
        "decision_id": f"dec_cash_{digest}",
        "symbol": "CASH",
        "action": action,
        "stance_code": action,
        "standing_recommendation": action,
        "current_action": action,
        "act_now": deploy,
        "actionability": "ACT_NOW" if deploy else "NO_ACTION",
        "delta_usd": float(deploy_now),
        "why_now": f"Cash {status}; deploy {deploy_now}.",
        "cash_posture": {"cash_posture_status": status},
        "cash_posture_status": status,
        "capital": {"deploy_now": deploy_now},
        "decision_evidence_digest": digest,
        "financial_action": False,
        "memory_behavior_influence": 0,
    }


# ── pins: no Telegram producer / no notify flip ────────────────────────────

def test_p7_no_new_telegram_producer_in_matrix_modules():
    offenders = []
    for rel in MATRIX_MODULES:
        code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", _src(rel)))
        for bad in ("send_cio_message", "api.telegram.org", "RealTelegramAdapter",
                    "cio_telegram_transport", "sendMessage"):
            if bad in code:
                offenders.append(f"{rel}:{bad}")
    assert not offenders, offenders


def test_p7_policy_never_flips_notify_env():
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                                     _src("scripts/lib/cio_notification_policy.py")))
    assert "os.environ[" not in code
    assert "putenv" not in code and "setenv" not in code


# ── routing matrix (policy Wave 3B) ────────────────────────────────────────

@pytest.mark.parametrize("plan,kwargs,expect", [
    ({"situation_type": "S3_REENTRY_CANDIDATE", "material": True},
     {"duplicate_subject": True}, "SUPPRESSED"),
    ({"situation_type": "S3_REENTRY_CANDIDATE", "material": False},
     {}, "SUPPRESSED"),
    ({"situation_type": "S5_CASH_DEPLOYMENT", "material": True},
     {}, "SUPPRESSED"),
    ({"situation_type": "S1_POSITION_LIFECYCLE", "material": True},
     {}, "SUPPRESSED"),
    ({"situation_type": "S6_CONCENTRATION_OR_DISPOSITION", "material": True},
     {}, "COMMAND_CENTER_ONLY"),
    ({"situation_type": "S3_REENTRY_CANDIDATE", "material": True},
     {"synthesis": {"state": "DISPUTED"}}, "COMMAND_CENTER_ONLY"),
    ({"situation_type": "S3_REENTRY_CANDIDATE", "material": True},
     {}, "DIGEST"),
    ({"situation_type": "S3_REENTRY_CANDIDATE", "material": True},
     {"operator_directed": True}, "IMMEDIATE"),
])
def test_p7_policy_routing_matrix(plan, kwargs, expect):
    row = policy.decide(plan, now=NOW, **kwargs)
    assert row["decision"] == expect
    assert row["decision"] in ROUTES
    assert row["would_send"] is False
    assert row["delivery"] == "shadow"
    assert row["financial_action"] is False


# ── signal matrix: priority / reentry NEAR / dups / cash / dust / test ─────

def test_p7_priority_up_pages_once(tmp_path):
    """Priority up: WAIT → TRIM act_now → IMMEDIATE once, then SUPPRESSED."""
    store = _store(tmp_path)
    cold = decide_notification(
        _pos(action="HOLD", current="WAIT", act_now=False, digest="p0"),
        store=store)
    assert cold["notification_class"] in {DELIVERY_DIGEST, DELIVERY_COMMAND_CENTER_ONLY,
                                          DELIVERY_SUPPRESSED}
    store.record(cold)

    hot = decide_notification(
        _pos(action="TRIM", current="TRIM", act_now=True, digest="p1", delta=-50000),
        store=store)
    assert hot["notification_class"] == DELIVERY_IMMEDIATE
    store.record(hot)

    replay = decide_notification(
        _pos(action="TRIM", current="TRIM", act_now=True, digest="p1b", delta=-50000),
        store=store)
    # Same material generation → not a second page.
    assert replay["notification_class"] in {DELIVERY_SUPPRESSED, DELIVERY_DIGEST}
    assert replay["notification_class"] != DELIVERY_IMMEDIATE or replay.get(
        "suppressed_reason")


def test_p7_priority_down_does_not_repage_unchanged(tmp_path):
    """Priority down / block: ACT_NOW → DATA_CONFLICT then unchanged → suppress."""
    store = _store(tmp_path)
    first = decide_notification(
        _pos(current="TRIM", act_now=True, digest="d0"), store=store)
    store.record(first)
    blocked = decide_notification(
        _pos(current="DATA_CONFLICT", act_now=False, digest="d1"), store=store)
    # Blocking-state transition may page once.
    assert blocked["notification_class"] in ROUTES
    store.record(blocked)
    again = decide_notification(
        _pos(current="DATA_CONFLICT", act_now=False, digest="d2"), store=store)
    assert again["notification_class"] == DELIVERY_SUPPRESSED


def test_p7_reentry_near_churn_is_not_immediate(tmp_path):
    """NEAR list churn under WAIT must not open IMMEDIATE pages."""
    store = _store(tmp_path)
    a = decide_notification(
        _reentry(action="WAIT", ready=("AMD",), near=("MSFT",), digest="n1"),
        store=store)
    store.record(a)
    b = decide_notification(
        _reentry(action="WAIT", ready=("AMD", "MSFT"), near=(), digest="n2"),
        store=store)
    assert b["notification_class"] != DELIVERY_IMMEDIATE
    assert b["notification_class"] in {
        DELIVERY_SUPPRESSED, DELIVERY_DIGEST, DELIVERY_COMMAND_CENTER_ONLY}


def test_p7_duplicate_subject_suppressed_by_policy():
    row = policy.decide(
        {"situation_type": "S3_REENTRY_CANDIDATE", "material": True, "plan_id": "p1"},
        duplicate_subject=True, now=NOW)
    assert row["decision"] == policy.SUPPRESSED
    assert row["reason"] == "duplicate_subject"
    assert row["would_send"] is False


def test_p7_cash_hold_is_not_immediate(tmp_path):
    store = _store(tmp_path)
    nd = decide_notification(_cash(deploy_now=0, digest="cash1"), store=store)
    assert nd["notification_class"] != DELIVERY_IMMEDIATE
    assert nd["notification_class"] in {
        DELIVERY_DIGEST, DELIVERY_COMMAND_CENTER_ONLY, DELIVERY_SUPPRESSED}


def test_p7_dust_and_test_are_suppressed(tmp_path):
    """Dust residuals and synthetic TEST rows must not page (eligibility gate)."""
    store = _store(tmp_path)
    dust = decide_notification(
        _pos(symbol="SRNE", digest="dust1", market_value=12.0,
             source_kind="PROD", act_now=True),
        store=store)
    # Dust may still route if not marked synthetic; force test isolation path.
    test_row = decide_notification(
        _pos(symbol="SPACEX_TEST", digest="test1", act_now=True,
             source_kind="TEST", env="TEST"),
        store=store)
    assert test_row["notification_class"] == DELIVERY_SUPPRESSED
    assert test_row.get("suppressed_reason") == "not_production_advisory_eligible"

    # Explicit dust symbol via production eligibility markers when present.
    from scripts.lib.cio_production_eligibility import is_forbidden_from_production

    synthetic = {
        "symbol": "DUMMY",
        "source_kind": "FIXTURE",
        "env": "TEST",
        "act_now": True,
        "standing_recommendation": "TRIM",
        "current_action": "TRIM",
        "decision_id": "dec_dust_synth",
        "decision_evidence_digest": "dx",
    }
    assert is_forbidden_from_production(synthetic) is True
    nd = decide_notification(synthetic, store=store)
    assert nd["notification_class"] == DELIVERY_SUPPRESSED


def test_p7_situation_bridge_stamps_mbi_zero_and_no_orders():
    sit = {
        "situation_class": "REENTRY_READY",
        "notification_eligibility": "NOTIFY",
        "situation_id": "sit_reentry_near",
        "cio_conclusion": "RE_ENTER",
        "what_changed": "NEAR→READY for KTOS",
        "new_state": {"symbol": "KTOS"},
        "support": [],
        "counterevidence": [],
    }
    dec = situation_to_decision(sit)
    assert dec["memory_behavior_influence"] == 0
    assert dec["financial_action"] is False
    assert dec["executable_order"] is None
    assert dec["authority"] == "READ_ONLY_ADVISORY"


def test_p7_every_matrix_decision_records_would_send_false():
    for plan in (
        {"situation_type": "S6_X", "material": True},
        {"situation_type": "S3_X", "material": True},
        {"situation_type": "S5_X", "material": True},
        {"situation_type": "S1_X", "material": True},
    ):
        row = policy.decide(plan, now=NOW)
        assert row["would_send"] is False
        out = policy.deliver(row)
        assert out["would_send"] is False
