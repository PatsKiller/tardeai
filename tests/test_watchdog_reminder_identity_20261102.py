"""Real watchdog -> Telegram wrapper -> editor with only synthetic I/O dependencies.

No channel, key, external request, live mode file or host ledger is read/written.
The fake transport is below the editor; duplicate/product/interdict gates still run.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


W = load("watchdog_reminder_w_under_test", "scripts/cron_outage_watchdog.py")
TA = load("watchdog_reminder_ta_under_test", "scripts/telegram_alert.py")
TT = load("watchdog_reminder_tt_under_test", "scripts/telegram_transport.py")
CE = load("watchdog_reminder_ce_under_test", "scripts/lib/comms_editor.py")
from scripts.lib import watchdog_reminder_identity as ID  # noqa: E402

NOW = datetime(2032, 4, 12, 16, 0, tzinfo=timezone.utc)


def report(now=NOW, lanes=None):
    return {"observed_at": W.iso(now), "missed_lane_ids": lanes or ["fixture-job"],
            "refusals": [], "coverage_gap_lane_ids": [], "monitor_incidents": []}


@pytest.fixture
def path_env(tmp_path, monkeypatch):
    clock = [NOW]
    sent, decisions, routes = [], [], []
    monkeypatch.setenv("COMMS_EDITOR_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("COMMS_EDITOR_RECEIPTS", str(tmp_path / "receipts.jsonl"))
    monkeypatch.setattr(CE, "mode", lambda: "live")
    monkeypatch.setattr(CE, "subjects", lambda *a, **k: [])
    monkeypatch.setattr(CE, "default_db_query", lambda *a, **k: [])
    monkeypatch.setattr(CE, "_held_account_line", lambda *a, **k: None)
    edit, commit = CE.edit, CE.commit
    monkeypatch.setattr(CE, "commit", lambda decision, **kwargs: commit(decision, now=clock[0], **kwargs))

    def observe(text, **kwargs):
        decision = edit(text, now=clock[0], **kwargs)
        decisions.append(decision)
        return decision

    monkeypatch.setattr(CE, "edit", observe)
    monkeypatch.setattr(TT, "_comms_editor", lambda: CE)
    # Test dependency only: every transport below this point is an injected poster.
    monkeypatch.setattr(TT, "_interdicted", lambda: False)

    def post(_url, payload):
        sent.append(payload)
        return {"ok": True, "status_code": 200,
                "response": {"ok": True, "result": {"message_id": len(sent)}}}

    monkeypatch.setattr(TA, "send_message", lambda **kw: TT.deliver_text(
        token="fixture-token", chat_id="fixture", text=kw["text"], post=post))
    monkeypatch.setattr(TA, "_enabled", lambda: True)
    monkeypatch.setattr(TA, "_token", lambda: "fixture-token")
    monkeypatch.setattr(TA, "_chat_ids", lambda: ["fixture"])
    monkeypatch.setattr(TA, "_comms_gateway_owns", lambda _: False)
    monkeypatch.setattr(TA, "_best_effort_comms_publish", lambda *a, **k: None)
    monkeypatch.setattr(TA, "operator_wire_text", lambda text: text + "\n· via cron fixture")
    monkeypatch.setattr(TA, "publish_operator_message", lambda message, **kw: {
        "accepted": TA._legacy_send(message, False, priority=kw.get("priority"),
                                    dedupe_minutes=kw.get("dedupe_minutes"), producer=kw.get("producer")),
        "route_mode": "LEGACY"})

    def route(message, priority, **kwargs):
        routes.append((message, priority, kwargs))
        return {"decision": "DELIVER", "deliver": True, "priority": priority}

    router = SimpleNamespace(route_intent=route, mark_intent_sent=lambda _: None,
                             record_intent_receipt=lambda *a, **k: None)
    monkeypatch.setattr(TA, "_intent_router", lambda: router)
    monkeypatch.setitem(sys.modules, "scripts.lib.opportunity_alert", SimpleNamespace(enrich=lambda text, **_: text))
    monkeypatch.setitem(sys.modules, "lib.opportunity_alert", SimpleNamespace(enrich=lambda text, **_: text))
    monkeypatch.setitem(sys.modules, "lib.advisory.notification_broker", SimpleNamespace(wrap_send_hook=lambda *a, **k: None))
    monkeypatch.setitem(sys.modules, "report_capture", SimpleNamespace(capture=lambda *a, **k: None))

    def sender(body):
        return TA.send_telegram_outcome(body, priority="P1", dedupe_minutes=0,
                                        producer="cron_outage_watchdog", message_class="operator_alert")

    return SimpleNamespace(clock=clock, sent=sent, decisions=decisions, routes=routes,
                           router=router, sender=sender, tmp=tmp_path)


def test_due_repeat_is_delivered_while_early_repeat_never_reaches_sender(path_env):
    e = path_env
    first, state = W.deliver(report(), {}, sender=e.sender, now=NOW)
    assert first["delivered"] is True and len(e.sent) == 1
    first_fp = e.decisions[-1].fingerprint
    early, unchanged = W.deliver(report(NOW + timedelta(seconds=1799)), state,
                                 sender=e.sender, now=NOW + timedelta(seconds=1799))
    assert early["status"] == "NOT_REQUIRED" and unchanged == state and len(e.sent) == 1
    e.clock[0] = NOW + timedelta(seconds=1800)
    due, next_state = W.deliver(report(e.clock[0]), state, sender=e.sender, now=e.clock[0])
    assert due["delivered"] is True and len(e.sent) == 2
    assert e.decisions[-1].fingerprint != first_fp
    assert next_state["last_delivered_at"] == W.iso(e.clock[0])
    assert all("watchdog_reminder_identity" in d.changes for d in e.decisions)
    assert all(r[1] == "P1" and r[2]["dedupe_minutes"] == 0 for r in e.routes)


def test_same_slot_retry_and_lost_watchdog_state_still_deduplicate(path_env):
    e = path_env
    W.deliver(report(), {}, sender=e.sender, now=NOW)
    e.clock[0] = NOW + timedelta(seconds=60)
    retry, state = W.deliver(report(e.clock[0]), {}, sender=e.sender, now=e.clock[0])
    assert retry["status"] == "HELD" and retry["delivered"] is False
    assert len(e.sent) == 1 and "last_delivered_at" not in state
    assert e.decisions[-1].duplicate_of


def test_lost_state_at_slot_boundary_still_obeys_editor_family_cooldown(path_env):
    e = path_env
    e.clock[0] = NOW + timedelta(seconds=1799)
    W.deliver(report(e.clock[0]), {}, sender=e.sender, now=e.clock[0])
    first_fp = e.decisions[-1].fingerprint
    e.clock[0] += timedelta(seconds=2)
    early, _ = W.deliver(report(e.clock[0]), {}, sender=e.sender, now=e.clock[0])
    assert early["status"] == "HELD" and len(e.sent) == 1
    assert e.decisions[-1].fingerprint != first_fp
    e.clock[0] = NOW + timedelta(seconds=3599)
    due, _ = W.deliver(report(e.clock[0]), {}, sender=e.sender, now=e.clock[0])
    assert due["delivered"] is True and len(e.sent) == 2


def test_configured_interval_is_used_instead_of_a_magic_half_hour(path_env):
    e = path_env
    _, state = W.deliver(report(), {}, sender=e.sender, now=NOW, reminder_seconds=1200)
    e.clock[0] = NOW + timedelta(seconds=1200)
    out, state = W.deliver(report(e.clock[0]), state, sender=e.sender, now=e.clock[0], reminder_seconds=1200)
    assert out["delivered"] is True and len(e.sent) == 2


def test_changed_finding_is_admitted_without_waiting_for_old_finding_reminder(path_env):
    e = path_env
    _, state = W.deliver(report(), {}, sender=e.sender, now=NOW)
    e.clock[0] = NOW + timedelta(seconds=60)
    changed, _ = W.deliver(report(e.clock[0], ["fixture-other"]), state, sender=e.sender, now=e.clock[0])
    assert changed["delivered"] is True and len(e.sent) == 2


def test_payload_marker_producer_and_zero_dedupe_cannot_issue_context(path_env):
    e = path_env
    text = 'CRON WRAPPER WATCHDOG · action required\n{"watchdog_reminder":true,"slot":42}'
    first = e.sender(text)
    e.clock[0] = NOW + timedelta(hours=1)
    again = e.sender(text)
    assert first["delivered"] is True and again["status"] == "HELD" and len(e.sent) == 1
    assert all("watchdog_reminder_identity" not in d.changes for d in e.decisions)


def test_untrusted_python_caller_and_forged_json_context_fail_closed(path_env):
    e = path_env
    with ID.watchdog_reminder("fixture", finding_key="a" * 64, now=NOW, reminder_seconds=1800):
        e.sender("fixture")
    token = ID._ISSUED.set({"token": "forged", "body": "fixture", "identity": "a" * 64})
    try:
        out = e.sender("fixture")
    finally:
        ID._ISSUED.reset(token)
    assert out["status"] == "HELD" and len(e.sent) == 1
    assert all("watchdog_reminder_identity" not in d.changes for d in e.decisions)


def test_context_is_bound_to_exact_original_body_and_does_not_leak(path_env):
    e = path_env
    mismatched = lambda body: e.sender(body + "\nUnbound extra content")
    W.deliver(report(), {}, sender=mismatched, now=NOW)
    assert "watchdog_reminder_identity" not in e.decisions[-1].changes
    e.sender("Unrelated message")
    assert "watchdog_reminder_identity" not in e.decisions[-1].changes
    assert ID._ISSUED.get() is None and ID._OUTCOME.get() is None and ID._CHUNKS.get() is None


def test_normal_wire_sanitization_and_all_chunks_are_bound(path_env, monkeypatch):
    e = path_env
    monkeypatch.setattr(TA, "operator_wire_text", lambda text: text.replace("fixture-job", "sanitized-fixture") + "\nvia fixture")
    monkeypatch.setattr(TA, "MAX_MSG_LEN", 170)
    first, state = W.deliver(report(), {}, sender=e.sender, now=NOW)
    first_count = len(e.sent)
    assert first["delivered"] is True and first_count > 1
    assert all("watchdog_reminder_identity" in d.changes for d in e.decisions)
    assert all("fixture-job" not in x["text"] for x in e.sent)
    e.clock[0] = NOW + timedelta(seconds=1800)
    due, _ = W.deliver(report(e.clock[0]), state, sender=e.sender, now=e.clock[0])
    assert due["delivered"] is True and len(e.sent) == 2 * first_count


def test_already_normalized_wire_still_binds_to_original_outcome(path_env, monkeypatch):
    e = path_env
    monkeypatch.setattr(TA, "publish_operator_message", lambda message, **kw: {
        "accepted": TA._legacy_send(TA.operator_wire_text(message), False, priority=kw.get("priority"),
                                    dedupe_minutes=kw.get("dedupe_minutes"), producer=kw.get("producer")),
        "route_mode": "LEGACY"})
    out, _ = W.deliver(report(), {}, sender=e.sender, now=NOW)
    assert out["delivered"] is True
    assert all("watchdog_reminder_identity" in d.changes for d in e.decisions)


@pytest.mark.parametrize("interval", [0, -1, True])
def test_invalid_cadence_cannot_issue_an_editor_identity(path_env, interval):
    e = path_env
    W.deliver(report(), {}, sender=e.sender, now=NOW, reminder_seconds=interval)
    assert all("watchdog_reminder_identity" not in d.changes for d in e.decisions)


def test_sender_exception_drops_context_and_cannot_acknowledge(path_env):
    def fail(_):
        raise RuntimeError("synthetic transport error")
    out, state = W.deliver(report(), {}, sender=fail, now=NOW)
    assert out["status"] == "FAILED" and "last_delivered_at" not in state
    assert ID._ISSUED.get() is None and ID._OUTCOME.get() is None and ID._CHUNKS.get() is None


def test_interdict_still_blocks_and_does_not_advance_delivery_state(path_env, monkeypatch):
    e = path_env
    monkeypatch.setattr(TT, "_interdicted", lambda: True)
    out, state = W.deliver(report(), {}, sender=e.sender, now=NOW)
    assert out["delivered"] is False and e.sent == []
    assert "last_delivered_at" not in state and e.decisions == []


def test_product_hold_is_preserved_inside_a_trusted_reminder(path_env):
    e = path_env
    r = report(lanes=["fixture\n[CIO DECISION] OPERATOR_PRODUCT_INVALID"])
    out, state = W.deliver(r, {}, sender=e.sender, now=NOW)
    assert out["status"] == "HELD" and not out["delivered"] and e.sent == []
    assert e.decisions[-1].held_reason == "operator_product_invalid"
    assert "last_delivered_at" not in state


@pytest.mark.parametrize("action,expected", [("AVOID", "cio_disagreement"), (None, "cio_decision_missing")])
def test_cio_stance_and_missing_decision_holds_remain_binding(path_env, monkeypatch, action, expected):
    e = path_env
    monkeypatch.setattr(CE, "subjects", lambda *a, **k: [{"symbol": "ELMT", "guid": "fixture-guid"}])
    monkeypatch.setattr(CE, "default_db_query", lambda *a, **k: [
        {"symbol": "ELMT", "action": action, "created_at": W.iso(NOW)}] if action else [])
    out, state = W.deliver(report(lanes=["fixture\n🎯 *NEW GO* — *ELMT* score=44 RVOL20x"]), {},
                           sender=e.sender, now=NOW)
    assert out["status"] == "HELD" and not out["delivered"] and e.sent == []
    assert e.decisions[-1].held_reason == expected and "last_delivered_at" not in state


def test_router_hold_is_not_bypassed_by_repeat_context(path_env):
    e = path_env
    e.router.route_intent = lambda *a, **k: {"decision": "DEDUPED", "priority": "P1", "window_minutes": 30}
    out, state = W.deliver(report(), {}, sender=e.sender, now=NOW)
    assert out["status"] == "ROUTED" and not out["delivered"] and e.sent == []
    assert "last_delivered_at" not in state


def test_failed_transport_cannot_acknowledge_watchdog(path_env, monkeypatch):
    e = path_env
    monkeypatch.setattr(TA, "send_message", lambda **kw: {"ok": False, "status_code": 503})
    out, state = W.deliver(report(), {}, sender=e.sender, now=NOW)
    assert out["status"] == "FAILED" and not out["delivered"] and "last_delivered_at" not in state
    assert ID._ISSUED.get() is None and ID._OUTCOME.get() is None and ID._CHUNKS.get() is None


def test_original_content_dedupe_still_has_the_full_editor_window(path_env):
    e = path_env
    e.sender("Ordinary unchanged content at 16:00 ET")
    e.clock[0] = NOW + timedelta(hours=1)
    out = e.sender("Ordinary unchanged content at 17:00 ET")
    assert out["status"] == "HELD" and len(e.sent) == 1
    receipts = [json.loads(x) for x in (e.tmp / "receipts.jsonl").read_bytes().splitlines()]
    assert len(receipts) == 2 and receipts[-1]["duplicate_of"]
