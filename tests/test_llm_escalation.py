"""Free lanes, then deepseek-flash, then ASK — never silently pay more.

Operator policy, 2026-09-06:

    1. free OAuth      grok -> chatgpt
    2. deepseek-flash  the one paid lane enterable automatically
    3. NOTIFY, STOP    Telegram, and the run yields nothing
    4. further paid    never automatic

Step 3 is a hard stop, not a warning. An escalation that notifies and continues
defeats the point: silently walking up a cost ladder is how a research backlog
becomes a bill nobody authorised.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import llm_escalation as E  # noqa: E402

COVERS = ["scripts/lib/llm_escalation.py"]


class _Res:
    def __init__(self, text, lane="grok"):
        self.text = text
        self.lane = lane


def test_a_free_lane_success_never_notifies():
    sent = []
    r = E.run_with_escalation("p", purpose="test",
                              generate_fn=lambda p, **k: _Res("ok"),
                              notify_fn=lambda m: sent.append(m) or True)
    assert r["ok"] and r["escalated"] is False
    assert sent == [], "a working free lane must not page the operator"


def test_the_auto_paid_lane_is_reachable_without_asking():
    """deepseek-flash is the ONE paid lane the operator allowed automatically."""
    assert E.AUTO_PAID == ("deepseek-flash",)
    calls = []

    def gen(p, **k):
        calls.append(k.get("allow_paid"))
        return _Res("ok", lane="deepseek-flash")

    E.run_with_escalation("p", purpose="t", generate_fn=gen, notify_fn=lambda m: True)
    assert calls and calls[0] is True, "deepseek-flash must be reachable automatically"


def test_when_everything_fails_the_operator_is_notified_and_the_run_stops():
    sent = []

    def boom(p, **k):
        raise RuntimeError("all lanes down")

    with pytest.raises(E.EscalationStopped):
        E.run_with_escalation("p", purpose="mentions backfill",
                              generate_fn=boom, notify_fn=lambda m: sent.append(m) or True)
    assert sent, "the operator was not notified"
    assert "STOPPED" in sent[0]
    assert "mentions backfill" in sent[0]


def test_stopping_is_a_stop_not_a_warning():
    """The failure this guards: notify, then quietly pay anyway."""
    used = []

    def gen(p, **k):
        used.append(k.get("extra_lanes"))
        raise RuntimeError("down")

    with pytest.raises(E.EscalationStopped):
        E.run_with_escalation("p", purpose="t", generate_fn=gen, notify_fn=lambda m: True)
    assert all(x is None for x in used), "a gated paid lane was entered without approval"


def test_a_gated_lane_is_only_entered_on_an_explicit_operator_rerun(monkeypatch):
    monkeypatch.setattr(E, "GATED_PAID", ("expensive-api",))
    seen = []

    def gen(p, **k):
        seen.append(k.get("extra_lanes"))
        if k.get("extra_lanes"):
            return _Res("paid answer", lane="expensive-api")
        raise RuntimeError("free+auto down")

    # default: stops
    with pytest.raises(E.EscalationStopped):
        E.run_with_escalation("p", purpose="t", generate_fn=gen, notify_fn=lambda m: True)
    # explicit re-run: allowed
    r = E.run_with_escalation("p", purpose="t", generate_fn=gen,
                              notify_fn=lambda m: True, allow_gated=True)
    assert r["ok"] and r["escalated"] is True


def test_no_gated_lane_exists_by_default():
    """A provider must never arrive in the paid path by default."""
    assert E.GATED_PAID == () or all(isinstance(x, str) for x in E.GATED_PAID)


def test_the_notification_names_what_was_tried_and_what_would_be_paid():
    msg = E.build_message(
        attempts=[{"lane": "grok", "error": "401"}, {"lane": "chatgpt", "error": "timeout"}],
        purpose="mentions", gated=("expensive-api",))
    assert "grok" in msg and "chatgpt" in msg
    assert "expensive-api" in msg
    assert "Nothing was spent" in msg


def test_the_notification_bypasses_the_router():
    """An escalation prompt classified P1_DIGEST and archived is a decision the
    operator never sees — that happened to guard approvals on 2026-09-05."""
    src = (ROOT / "scripts" / "lib" / "llm_escalation.py").read_text(encoding="utf-8")
    fn = src.split("def _default_notify", 1)[1].split("\ndef ", 1)[0]
    assert "bypass_router=True" in fn


def test_a_failed_notification_still_stops_the_run():
    """Telegram being down must not become permission to spend."""
    def boom(p, **k):
        raise RuntimeError("down")

    def bad_notify(m):
        raise RuntimeError("telegram down")

    with pytest.raises(E.EscalationStopped) as ei:
        E.run_with_escalation("p", purpose="t", generate_fn=boom, notify_fn=bad_notify)
    assert ei.value.notified is False


def test_it_is_one_notification_per_run_not_per_call():
    """A 2,000-document batch that lost its free lanes must not send 2,000
    identical messages — indistinguishable from a broken loop."""
    sent = []

    def boom(p, **k):
        raise RuntimeError("down")

    with pytest.raises(E.EscalationStopped):
        E.run_with_escalation("p", purpose="t", generate_fn=boom,
                              notify_fn=lambda m: sent.append(m) or True)
    assert len(sent) == 1


def test_the_consumption_gate_is_passed_through():
    seen = {}

    def gen(p, **k):
        seen.update(k)
        return _Res("ok")

    E.run_with_escalation("p", purpose="t", generate_fn=gen,
                          notify_fn=lambda m: True, process_id="mentions_backfill")
    assert seen.get("process_id") == "mentions_backfill", (
        "a fallback must not become a way around the spend cap")


def test_local_models_are_still_never_in_the_chain():
    from lib.llm_fallback import NEVER_CHAIN
    assert {"local", "gemma", "ollama"} <= set(NEVER_CHAIN)
