"""Notification intents replace bypass_router=True (operator 2026-10-10, AGENTS.md §24.1 PROPOSED).

Thirty scheduled senders passed ``bypass_router=True`` (~/n8n-maturity-verification/SENDER_JOBS_MEASURED.md):
straight to the phone, no dedupe, no route receipt. Each now declares a priority and goes through
``telegram_alert_router.route_intent``:

  P1  delivered now; never capped, never quiet-held; exact-content dedupe with a declared window; receipted.
  P2  as P1, but held during the operator's quiet window (incident notifier's 22:00-07:00 ET) and archived
      for the advice digest. A hold that cannot be archived is delivered instead -- never dropped.

Every send here is captured at the transport (``alarm_capture``); nothing reaches Telegram. The gate at the
bottom fails if ``bypass_router=True`` reappears outside the allowlist, and is shrink-only.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import telegram_alert as TA  # noqa: E402
import telegram_alert_router as TR  # noqa: E402


@pytest.fixture
def intents(alarm_capture, monkeypatch, tmp_path):
    """Transport stubbed (alarm_capture), durable state redirected to tmp, legacy runtime mode, no gateway."""
    monkeypatch.setenv(TR.INTENT_RECEIPTS_ENV, str(tmp_path / "intent_receipts.jsonl"))
    monkeypatch.setenv("CIO_OUTBOUND_DEDUPE_PATH", str(tmp_path / "dedupe.jsonl"))
    monkeypatch.setattr(TR, "_intent_sent", {})
    monkeypatch.setattr(TR, "_durable_recently_sent", lambda key, ttl: False)
    monkeypatch.setattr(TR, "durable_mark_sent", lambda key, meta=None: None)
    import alert_runtime_mode
    monkeypatch.setattr(alert_runtime_mode, "get_mode", lambda **k: alert_runtime_mode.MODE_OFF)
    monkeypatch.setattr(TA, "_comms_gateway_owns", lambda mc: False)
    monkeypatch.setattr(TA, "_best_effort_comms_publish", lambda *a, **k: None)
    archived: list[dict] = []
    import report_capture
    monkeypatch.setattr(report_capture, "archive_message",
                        lambda message, suppressed=False, reason="", report_type=None:
                        archived.append({"message": message, "report_type": report_type}) or report_type)
    routes: list[dict] = []
    real_route = TR.route_intent

    def _spy(message, priority, **kw):
        r = real_route(message, priority, **kw)
        routes.append(r)
        return r

    monkeypatch.setattr(TR, "route_intent", _spy)
    monkeypatch.setattr(TR, "intent_in_quiet_hours", lambda now=None: False)
    alarm_capture.archived = archived
    alarm_capture.routes = routes
    alarm_capture.receipts = lambda: [json.loads(line) for line in
                                      (tmp_path / "intent_receipts.jsonl").read_text().splitlines() if line]
    return alarm_capture


# ── the router: priority decides, never the text classifier ─────────────────────────────────────────────

def test_p1_delivers_without_consulting_the_text_classifier(intents, monkeypatch):
    monkeypatch.setattr(TR, "should_send_telegram", lambda *a, **k: pytest.fail("classifier consulted"))
    monkeypatch.setattr(TR, "_record_budget_send", lambda: pytest.fail("P1 counted against the budget"))
    assert TA.send_telegram("momentum scalp setup ARMP probe", priority="P1", producer="t") is True
    intents.assert_fired(contains="ARMP probe")
    assert intents.routes[0]["priority"] == "P1" and intents.routes[0]["decision"] == "DELIVER"
    rec = intents.receipts()
    assert rec[-1]["schema"] == "NotificationIntentRoute@v1" and rec[-1]["delivered"] is True
    assert rec[-1]["producer"] == "t" and rec[-1]["dedupe_key"].startswith("intent:")


def test_p1_is_never_quiet_held(intents, monkeypatch):
    monkeypatch.setattr(TR, "intent_in_quiet_hours", lambda now=None: True)
    assert TA.send_telegram("💾 Disk 97.0% used probe", priority="P1") is True
    intents.assert_fired(contains="Disk 97.0%")
    assert not intents.archived


def test_p2_is_held_in_quiet_hours_and_archived_for_the_digest(intents, monkeypatch):
    monkeypatch.setattr(TR, "intent_in_quiet_hours", lambda now=None: True)
    accepted = TA.send_telegram("🧹 Weekly disk cleanup probe", priority="P2", producer="weekly_disk_cleanup")
    assert accepted is True, "a held intent is accepted (archived for the digest), not failed"
    assert not intents.fired
    assert intents.archived == [{"message": "🧹 Weekly disk cleanup probe",
                                 "report_type": TR.HELD_P2_REPORT_TYPE}]
    assert intents.receipts()[-1]["decision"] == "HELD_QUIET_HOURS"
    assert intents.receipts()[-1]["archived_report_type"] == TR.HELD_P2_REPORT_TYPE


def test_p2_hold_that_cannot_be_archived_is_delivered_not_dropped(intents, monkeypatch):
    monkeypatch.setattr(TR, "intent_in_quiet_hours", lambda now=None: True)
    import report_capture
    monkeypatch.setattr(report_capture, "archive_message", lambda *a, **k: None)
    assert TA.send_telegram("System digest probe", priority="P2") is True
    intents.assert_fired(contains="System digest probe")
    assert intents.receipts()[-1]["decision"] == "HOLD_UNPERSISTED_DELIVERED"


def test_p2_outside_quiet_hours_delivers_now(intents):
    assert TA.send_telegram("Morning brief probe", priority="P2") is True
    intents.assert_fired(contains="Morning brief probe")


def test_identical_p1_inside_the_window_is_deduped_but_accepted(intents):
    assert TA.send_telegram("STOP HEALTH — supervisor L4 probe", priority="P1") is True
    assert TA.send_telegram("STOP HEALTH — supervisor L4 probe", priority="P1") is True
    assert len(intents.transport) == 1
    assert intents.receipts()[-1]["decision"] == "DEDUPED"
    # a different body is never deduped
    assert TA.send_telegram("STOP HEALTH — supervisor L4 probe (2h)", priority="P1") is True
    assert len(intents.transport) == 2


def test_dedupe_off_for_a_ledger_scheduled_producer(intents):
    for _ in range(2):
        TA.send_telegram("Approval reminder probe", priority="P1", dedupe_minutes=0)
    assert len(intents.transport) == 2


def test_keyboard_branch_carries_the_intent(intents):
    kb = {"inline_keyboard": [[{"text": "CC", "url": "https://example.test"}]]}
    assert TA.send_telegram("GO ARMP keyboard probe", priority="P1", reply_markup=kb) is True
    intents.assert_fired(contains="keyboard probe")
    assert intents.routes and intents.routes[0]["priority"] == "P1"
    # deduped on the keyboard branch: accepted, not reported as a failure
    assert TA.send_telegram("GO ARMP keyboard probe", priority="P1", reply_markup=kb) is True
    assert len(intents.transport) == 1


def test_send_with_id_returns_the_provider_id_for_an_intent(intents):
    r = TA.send_telegram_with_id("Stop decision brief probe", priority="P1")
    assert r["accepted"] is True and r["message_id"]


def test_document_intent_reaches_the_transport_and_holds_in_quiet_hours(intents, monkeypatch, tmp_path):
    doc = tmp_path / "report.pdf"
    doc.write_bytes(b"%PDF-1.4 probe")
    assert TA.send_telegram_document(str(doc), caption="Portfolio Report probe (PDF)", priority="P2") is True
    assert intents.documents and intents.documents[0]["document"] == str(doc)
    monkeypatch.setattr(TR, "intent_in_quiet_hours", lambda now=None: True)
    assert TA.send_telegram_document(str(doc), caption="Portfolio Report probe 2 (PDF)", priority="P2") is True
    assert len(intents.documents) == 1
    assert intents.archived and str(doc) in intents.archived[-1]["message"]


def test_invalid_priority_is_refused():
    with pytest.raises(ValueError):
        TR.route_intent("x", "P0")


def test_non_intent_calls_keep_their_exact_shape(monkeypatch):
    """A non-intent send passes no intent kwargs, so fakes with fixed signatures keep working."""
    seen = {}

    def fake_publish(message, *, bypass_router=False, resolving=False):
        seen.update(bypass_router=bypass_router)
        return {"accepted": True, "delivered": True, "route_mode": "LEGACY"}

    monkeypatch.setattr(TA, "_enabled", lambda: True)
    monkeypatch.setattr(TA, "_comms_gateway_owns", lambda mc: False)
    monkeypatch.setattr(TA, "_best_effort_comms_publish", lambda *a, **k: None)
    monkeypatch.setattr(TA, "publish_operator_message", fake_publish)
    assert TA.send_telegram("plain probe") is True and seen == {"bypass_router": False}


def test_quiet_window_matches_the_incident_notifier(monkeypatch):
    """One quiet window: the router reads the incident notifier's env vars and defaults."""
    for var in ("TRADEAI_INCIDENT_NOTIFIER_QUIET_START", "TRADEAI_INCIDENT_NOTIFIER_QUIET_END",
                "TRADEAI_INCIDENT_NOTIFIER_TZ"):
        monkeypatch.delenv(var, raising=False)
    from scripts import incident_notifier as inn
    cfg = inn.config_from_env({})
    for base in (datetime(2026, 7, 15, tzinfo=timezone.utc), datetime(2026, 12, 15, tzinfo=timezone.utc)):
        for minute in range(0, 24 * 60, 7):
            now = base + timedelta(minutes=minute)
            assert TR.intent_in_quiet_hours(now) == inn.in_quiet_hours(now, cfg), now


# ── per-module: each migrated sender reaches the router with its declared priority ──────────────────────

def _route_priorities(intents):
    return [(r["priority"], r["producer"]) for r in intents.routes]


def test_disk_pressure_guard_is_p1(intents):
    import disk_pressure_guard
    assert disk_pressure_guard.notify("💾 Disk probe") == "accepted"
    assert _route_priorities(intents) == [("P1", "disk_pressure_guard")]
    intents.assert_fired(contains="Disk probe")


def test_approval_reminder_is_p1_with_dedupe_off(intents):
    import approval_package_reminder
    approval_package_reminder.send_reminder_text("Approval package reminder probe")
    assert _route_priorities(intents) == [("P1", "approval_package_reminder")]
    assert intents.routes[0]["window_minutes"] == 0
    intents.assert_fired(contains="reminder probe")


def test_options_intent_matcher_is_p1(intents):
    import options_intent_matcher
    assert options_intent_matcher.telegram_send("Options intent probe") is True
    assert _route_priorities(intents) == [("P1", "options_intent_matcher")]


def test_stop_decision_brief_is_p1(intents):
    import stop_decision_brief
    mid = stop_decision_brief.send_stop_brief_telegram({"telegram_msg": "STOP BRIEF probe"})
    assert mid and _route_priorities(intents) == [("P1", "stop_decision_brief")]


def test_alpaca_live_read_sync_broker_health_is_p1(intents):
    import alpaca_live_read_sync
    alpaca_live_read_sync._telegram("⚠️ Alpaca live read sync FAILED ×3 probe")
    assert _route_priorities(intents) == [("P1", "alpaca_live_read_sync")]


def test_sm_render_alert_is_p1_and_reads_no_env_file(intents, monkeypatch, tmp_path):
    from scripts.secrets import render_env
    monkeypatch.setattr(render_env, "RENDER_PATH", tmp_path / "absent-render")
    monkeypatch.setattr(render_env, "DISK_ENV", tmp_path / "absent-disk")
    render_env._telegram("⚠️ SM env cache STALE probe")
    assert _route_priorities(intents) == [("P1", "sm_render_env")]


def test_morning_brief_is_p2(intents):
    import send_morning_brief
    send_morning_brief.send_telegram("Morning brief intent probe")
    assert _route_priorities(intents) == [("P2", "send_morning_brief")]
    intents.assert_fired(contains="intent probe")


def test_advice_digest_is_p2(intents):
    import send_advice_digest
    ids = send_advice_digest.deliver(["📋 advice digest intent probe"])
    assert ids and ids[0]
    assert _route_priorities(intents) == [("P2", "send_advice_digest")]


def test_defense_weekly_review_is_p2(intents):
    import defense_weekly_paid_review
    defense_weekly_paid_review._telegram(TA.send_telegram, "[weekly-oversight] probe")
    assert _route_priorities(intents) == [("P2", "defense_weekly_paid_review")]


def test_portfolio_report_document_is_p2(intents, tmp_path):
    import portfolio_alerts
    doc = tmp_path / "Portfolio_Report.pdf"
    doc.write_bytes(b"%PDF-1.4 probe")
    assert portfolio_alerts._send_telegram_document(doc, "Portfolio Report probe (PDF)", ROOT) is True
    assert _route_priorities(intents) == [("P2", "portfolio_alerts")]
    assert intents.documents


# ── the migration contract and the gate ──────────────────────────────────────────────────────────────────

# Each migrated sender file -> the priority every one of its send calls declares.
MIGRATED = {
    "scripts/send_morning_brief.py": "P2",
    "scripts/eod_open_trade_alert.py": "P2",
    "scripts/watch_alerts_eval.py": "P1",
    "scripts/alert_daily_digest.py": "P2",
    "scripts/system_rollup_snapshot.py": "P2",
    "scripts/defense_weekly_paid_review.py": "P2",
    "scripts/oversight_weekly_digest.py": "P2",
    "scripts/alpaca_live_read_sync.py": "P1",
    "scripts/screener_go_alerts.py": "P1",
    "scripts/llm_spend_report.py": "P2",
    "scripts/approval_package_reminder.py": "P1",
    "scripts/options_intent_matcher.py": "P1",
    "scripts/positions_proof_daily.py": "P2",
    "scripts/send_advice_digest.py": "P2",
    "scripts/disk_pressure_guard.py": "P1",
    "scripts/portfolio_alerts.py": "P2",
    "scripts/stop_decision_brief.py": "P1",
    "scripts/secrets/render_env.py": "P1",
    "scripts/supervisor_breach_detector.py": "P1",
    "scripts/weekly_disk_cleanup_notify.py": "P2",
}

# Remaining bypass_router call sites (keyword not literally False, plus send_telegram_document calls that
# rely on its bypass_router=True default) -- file -> count. SHRINK-ONLY: a new file or a higher count fails;
# a lower count also fails until this entry is lowered, so a migration is recorded where the next agent reads.
BYPASS_ALLOWLIST = {
    # Broker execution file set (config/agents_guard_hook_rules.json broker.execution_code_edit, or an
    # order/stop/execution module). Migrating these needs an operator `execution-engineering` grant.
    "scripts/alpaca_stop_manager.py": 2,          # P1: host-lock BLOCKED (live endpoint refused)
    "scripts/defense_execution.py": 1,            # P1: OPERATIONAL execution plumbing
    "scripts/moomoo/opend_health.py": 1,          # P1: broker data plane DOWN
    "scripts/active_trader/momentum_alerts.py": 1,
    # The transport and pass-throughs: they carry a caller's flag, they do not choose it.
    "scripts/telegram_alert.py": 5,
    "scripts/send_operator_alert.py": 1,
    "scripts/lib/advisory/notification_broker.py": 1,
    "scripts/lib/hermes_outcome_bus/alert_notifications.py": 1,
    # Outside the 30 measured scheduled senders: not yet migrated (cron inventory rows).
    "scripts/advisory_telegram_brief.py": 1,
    "scripts/ci_outage_emergency_release.py": 1,
    "scripts/guard_request_approval.py": 1,
    "scripts/hermes_backlog_drain.py": 1,
    "scripts/interlock_parity_monitor.py": 1,
    "scripts/lib/aec_narrator.py": 1,
    "scripts/lib/cio_operator_renderers.py": 2,
    "scripts/lib/llm_escalation.py": 1,
    "scripts/lib/scalp_advisory_alert.py": 1,
    "scripts/morning_digest.py": 1,
    "scripts/open_trade_monitor.py": 2,
    "scripts/p1_digest_sender.py": 1,
    "scripts/portfolio_monthly_report.py": 2,
    "scripts/portfolio_monthly_synthesis.py": 1,
    "scripts/portfolio_report_ms.py": 1,
    "scripts/portfolio_weekly_report.py": 2,
    "scripts/schwab_auto_reauth.py": 1,
    "scripts/secrets/rotation_daemon.py": 1,
    "scripts/secrets_admin.py": 1,
    "scripts/send_closed_trade_digest.py": 1,
    "scripts/session18_signal_flow_health.py": 1,
    "scripts/telegram_command_handler.py": 1,
    "scripts/verify_fib_proposals.py": 1,
    "scripts/verify_hermes_daily.py": 1,
    "scripts/weekly_summary_local.py": 1,
}

_SEND_NAMES = {"send_telegram", "send_telegram_with_id", "send_telegram_document", "_send", "sender_with_id"}


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _bypass_sites(tree: ast.AST) -> int:
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        kws = {k.arg: k.value for k in node.keywords}
        if "bypass_router" in kws:
            v = kws["bypass_router"]
            if not (isinstance(v, ast.Constant) and v.value is False):
                n += 1
        elif _call_name(node) == "send_telegram_document" and "priority" not in kws:
            n += 1   # its default is bypass_router=True
    return n


def _measure() -> dict[str, int]:
    out = {}
    for p in sorted((ROOT / "scripts").glob("**/*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        n = _bypass_sites(tree)
        if n:
            out[str(p.relative_to(ROOT))] = n
    return out


def test_no_bypass_router_outside_the_allowlist():
    measured = _measure()
    new = {f: n for f, n in measured.items() if n > BYPASS_ALLOWLIST.get(f, 0)}
    assert not new, (f"bypass_router reappeared outside the allowlist: {new}. Send a notification intent "
                     f"instead: send_telegram(text, priority='P1'|'P2') (AGENTS.md §24.1).")
    stale = {f: (BYPASS_ALLOWLIST[f], measured.get(f, 0)) for f in BYPASS_ALLOWLIST
             if measured.get(f, 0) < BYPASS_ALLOWLIST[f]}
    assert not stale, f"allowlist is shrink-only: lower these entries to the measured count {stale}"


def test_gate_detects_a_reintroduced_bypass():
    """Mutation check: the detector the gate relies on must see each bypass spelling."""
    for src in ("send_telegram(m, bypass_router=True)", "send_telegram(m, bypass_router=flag)",
                "send_telegram_document(p, caption='c')"):
        assert _bypass_sites(ast.parse(src)) == 1, src
    for src in ("send_telegram(m, priority='P1')", "send_telegram(m, bypass_router=False)",
                "send_telegram_document(p, caption='c', priority='P2')"):
        assert _bypass_sites(ast.parse(src)) == 0, src


@pytest.mark.parametrize("rel,priority", sorted(MIGRATED.items()))
def test_migrated_sender_declares_its_priority_and_never_bypasses(rel, priority):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    assert _bypass_sites(tree) == 0, f"{rel} still bypasses the router"
    declared = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _call_name(node) in _SEND_NAMES:
            for k in node.keywords:
                if k.arg == "priority":
                    declared.append(k.value.value if isinstance(k.value, ast.Constant) else None)
    assert declared and set(declared) == {priority}, (rel, declared)
