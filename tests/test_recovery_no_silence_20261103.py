"""No-silence invariant: a T1 recovery case can never be suppressed.

Operator P0 2026-11-03 (SPEC_RECOVERY_REENTRY_ENGINE_20261103.md §3.3): Recovery Watch found re-entry
candidates for weeks, sent them with priority="P2", and the router answered P2_DASHBOARD_ONLY and the
publish path LEGACY_SHADOWED. The operator missed SPCX — his largest stop-out — recovering. This test
drives the real notify path and the real router classifier; only the Telegram transport is stubbed.

Hermetic: no DB, no network, no live Telegram, tmp state file only.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import recovery_notify as rn  # noqa: E402
import telegram_alert_router as router  # noqa: E402

COVERS = ["scripts/lib/recovery_notify.py", "scripts/telegram_alert_router.py"]

POLICY = {"materiality": {"t1": {"loss_usd": 10000, "weight_pct": 3.0}}}


def _case(**kw):
    base = {
        "symbol": "SPCX",
        "price": 141.65,
        "exit_price": 137.19,
        "pct_vs_exit": 3.3,
        "realized_loss_usd": -12770,
        "pre_exit_weight_pct": 2.25,
        "state": "RECOVERING",
        "next_trigger": "reclaims 151.62 20-day mean",
        "eligibility": "IRA now; taxable 11-27",
        "plan": "restore 800 shares in two tranches",
    }
    base.update(kw)
    return base


class _Sender:
    def __init__(self):
        self.calls = []

    def __call__(self, message, **kwargs):
        self.calls.append((message, kwargs))
        return True


class _NudgeState:
    def __init__(self, path):
        self.path = path

    def note(self, keys, when):
        return {k: when.isoformat() for k in keys}

    def save(self, rows):
        return None


def _fake_batch(monkeypatch):
    mod = types.ModuleType("lib.telegram_batch")
    mod.NudgeState = _NudgeState
    mod.batch_text = lambda *, header, items, footer=None: header + "\n" + items[0]["title"]
    mod.nudge_decision = lambda *, keys, state, now, priority="P2", floor_minutes=120: {
        "send": True, "keys": list(keys), "priority": priority}
    monkeypatch.setitem(sys.modules, "lib.telegram_batch", mod)
    return mod


# ── materiality comes from config, never from a constant in the code ─────────────────────────────────


def test_declared_tier_wins():
    assert rn.resolve_tier(_case(materiality_tier="T1"))[0] == "T1"
    assert rn.resolve_tier(_case(materiality_tier="T2"))[0] == "T2"


def test_tier_is_derived_from_the_config_thresholds():
    case = _case(realized_loss_usd=-12770, pre_exit_weight_pct=1.0)
    assert rn.resolve_tier(case, policy=POLICY)[0] == "T1"
    # The same case under a HIGHER configured T1 loss floor is T2: the number came from policy.
    higher = {"materiality": {"t1": {"loss_usd": 50000, "weight_pct": 3.0}}}
    assert rn.resolve_tier(case, policy=higher)[0] == "T2"


def test_unknown_materiality_resolves_loud():
    t, why = rn.resolve_tier({"symbol": "SPCX"})
    assert t == "T1" and "unknown" in why
    assert rn.resolve_tier({"symbol": "SPCX"}, policy={})[0] == "T1"


# ── the page itself ───────────────────────────────────────────────────────────────────────────────────


def test_t1_sends_as_p1_through_the_batch_module(monkeypatch):
    _fake_batch(monkeypatch)
    send = _Sender()
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/does-not-matter.json")
    assert out["tier"] == "T1" and out["priority"] == "P1"
    assert out["sent"] is True and out["suppressed"] is False and out["path"] == "batch"
    assert len(send.calls) == 1
    _msg, kwargs = send.calls[0]
    assert kwargs.get("priority") == "P1"
    assert "P2" not in str(kwargs)


def test_t1_without_telegram_batch_falls_back_to_a_direct_p1(monkeypatch):
    # telegram_batch is not on this checkout until its own PR lands; the T1 page must still go out.
    monkeypatch.setitem(sys.modules, "lib.telegram_batch", None)
    send = _Sender()
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert out["path"] == "direct" and out["sent"] is True and out["suppressed"] is False
    _msg, kwargs = send.calls[0]
    assert kwargs.get("priority") == "P1"
    assert kwargs.get("dedupe_minutes") == rn.DEFAULT_REPEAT_FLOOR_MINUTES


def test_t2_is_not_paged():
    send = _Sender()
    out = rn.notify_recovery_case(_case(materiality_tier="T2"), policy=POLICY, sender=send)
    assert out["sent"] is False and out["priority"] is None and send.calls == []


# ── the router can never downgrade a T1 recovery page ────────────────────────────────────────────────


def test_router_never_downgrades_a_t1_recovery_message():
    for case in (_case(), _case(state="RE_ENTRY_READY"), _case(next_trigger=None)):
        level = router.classify_alert(rn.build_message(case))
        assert level not in ("P2_DASHBOARD_ONLY", "P3_LOG_ONLY"), level
        assert level == "P0_INTERRUPT", level


def test_a_json_shaped_plan_cannot_demote_the_page():
    """The marker check precedes the raw-JSON guard.

    The marker starts with '[', so a recovery page whose plan/summary quotes a JSON fragment
    (`{"symbol": ..., "rationale": ...}`) satisfied looks_like_raw_json and was P3_LOG_ONLY when the
    raw-JSON guard ran first — the exact silence this marker exists to stop.
    """
    msg = rn.build_message(_case(plan='{"symbol":"SPCX","rationale":"reclaims the mean"}'))
    assert router.classify_alert(msg) == "P0_INTERRUPT"


def test_the_marker_is_on_the_first_line():
    msg = rn.build_message(_case())
    assert msg.splitlines()[0].startswith(rn.RECOVERY_T1_MARKER)
    assert rn.RECOVERY_T1_MARKER in msg


def test_the_marker_wins_with_an_empty_plan_and_with_tier_words():
    """The marker is an authority signal, not gated by the tier path or by message content."""
    for extra in ({"plan": ""}, {"plan": None}, {"plan": "T3 — small, do not page"}, {"state": "T2"}):
        level = router.classify_alert(rn.build_message(_case(**extra)))
        assert level == "P0_INTERRUPT", (extra, level)


def test_a_transport_that_returns_false_is_recorded_not_treated_as_success(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "lib.telegram_batch", None)   # direct path
    calls = []

    def send(message, **kwargs):
        calls.append((message, kwargs))
        return False

    caplog.set_level("WARNING", logger="scripts.lib.recovery_notify")
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert calls and out["sent"] is False and out["suppressed"] is False and out["priority"] == "P1"
    assert "not accepted by the direct transport" in caplog.text


def test_a_consumed_dedupe_key_is_recorded_as_a_floor_hold(monkeypatch, caplog):
    _fake_batch(monkeypatch)
    monkeypatch.setattr(sys.modules["lib.telegram_batch"], "nudge_decision",
                        lambda **kw: {"send": False, "reason": "nothing due", "keys": []})
    send = _Sender()
    caplog.set_level("WARNING", logger="scripts.lib.recovery_notify")
    out = rn.notify_recovery_case(_case(), policy=POLICY, sender=send, state_path="/tmp/x.json")
    assert out["sent"] is False and out["deduped_by_floor"] is True and send.calls == []
    assert "held by the repeat floor" in caplog.text


def test_a_batch_delivery_that_raises_is_loud_not_empty_success(monkeypatch):
    """If both transports raise, the caller must see the exception — never a quiet result."""
    _fake_batch(monkeypatch)

    def boom(message, **kwargs):
        raise RuntimeError("transport down")

    with pytest.raises(RuntimeError, match="transport down"):
        rn.notify_recovery_case(_case(), policy=POLICY, sender=boom, state_path="/tmp/x.json")


def test_a_p1_intent_is_delivered_even_in_quiet_hours():
    """The transport contract the page relies on: P1 is never held or capped."""
    from datetime import datetime, timezone

    quiet = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)  # 03:00 America/New_York
    route = router.route_intent(rn.build_message(_case()), "P1", dedupe_minutes=0,
                                producer="recovery_notify", now=quiet)
    assert route["decision"] == "DELIVER" and route["deliver"] is True
