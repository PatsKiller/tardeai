#!/usr/bin/env python3
"""Regression tests for the Telegram-normalization remediation blockers.

One test class per blocker so a failure names the requirement it protects.
Pure/injected throughout: no database, no Telegram, no broker, no secrets.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import alert_runtime_mode as rt                                    # noqa: E402
from alert_routing_resolver import (                               # noqa: E402
    INV_APPROVALS_ALLOWLIST,
    INV_APPROVALS_NEEDS_AUTH,
    INV_NO_SECRETS_IN_PREFS,
    INV_PAPER_NOT_APPROVALS,
    INV_PROTECTION_ALWAYS_VISIBLE,
    resolve_route,
    sanitize_preference,
)
from operator_alert_policy_v2 import (                             # noqa: E402
    APPROVALS_ONLY,
    CRITICAL_OPERATIONS,
    ROUTE_COMMAND_CENTER,
    ROUTE_DIGEST,
    ROUTE_IMMEDIATE,
    ROUTE_LOG,
    AlertEvent,
)


def ev(alert_type: str, **kw) -> AlertEvent:
    base = dict(
        alert_type=alert_type,
        source_system="test",
        source_producer="pytest",
        entity_id=kw.pop("entity_id", "e1"),
    )
    base.update(kw)
    return AlertEvent(**base)


@pytest.fixture(autouse=True)
def _clean_mode(monkeypatch):
    monkeypatch.delenv(rt.ENV_VAR, raising=False)
    rt.reset_cache()
    yield
    rt.reset_cache()


# ── Blocker 1: explicit runtime modes, default OFF, fail closed ───────────────
class TestRuntimeModes:
    def test_default_is_off(self, monkeypatch):
        monkeypatch.delenv(rt.ENV_VAR, raising=False)
        rt.reset_cache()
        assert rt.get_mode(refresh=True) == rt.MODE_OFF

    @pytest.mark.parametrize("value,expected", [
        ("ACTIVE", rt.MODE_ACTIVE), ("SHADOW", rt.MODE_SHADOW),
        ("off", rt.MODE_OFF), ("  active ", rt.MODE_ACTIVE),
    ])
    def test_env_override(self, monkeypatch, value, expected):
        monkeypatch.setenv(rt.ENV_VAR, value)
        rt.reset_cache()
        assert rt.get_mode(refresh=True) == expected

    def test_invalid_value_fails_closed_to_off(self, monkeypatch):
        monkeypatch.setenv(rt.ENV_VAR, "ENABLED")
        rt.reset_cache()
        mode, why = rt.resolve_mode(refresh=True)
        assert mode == rt.MODE_OFF and "invalid" in why

    def test_unreadable_config_fails_closed(self, monkeypatch):
        monkeypatch.delenv(rt.ENV_VAR, raising=False)
        monkeypatch.setattr(rt, "POLICY_PATH", ROOT / "does" / "not" / "exist.yaml")
        rt.reset_cache()
        mode, why = rt.resolve_mode(refresh=True)
        assert mode == rt.MODE_OFF and why == "policy_file_missing"

    def test_yaml_bool_off_is_not_an_invalid_value(self, monkeypatch, tmp_path):
        """Bare `runtime_mode: OFF` becomes False under YAML 1.1 — must map to OFF."""
        p = tmp_path / "policy.yaml"
        p.write_text("telegram_normalization:\n  runtime_mode: OFF\n", encoding="utf-8")
        monkeypatch.delenv(rt.ENV_VAR, raising=False)
        monkeypatch.setattr(rt, "POLICY_PATH", p)
        rt.reset_cache()
        mode, why = rt.resolve_mode(refresh=True)
        assert mode == rt.MODE_OFF and "yaml_bool" in why

    def test_legacy_true_cannot_reach_active(self, monkeypatch, tmp_path):
        p = tmp_path / "policy.yaml"
        p.write_text("telegram_normalization:\n  runtime_enabled: true\n", encoding="utf-8")
        monkeypatch.delenv(rt.ENV_VAR, raising=False)
        monkeypatch.setattr(rt, "POLICY_PATH", p)
        rt.reset_cache()
        assert rt.get_mode(refresh=True) == rt.MODE_SHADOW


# ── Blocker 2: migration absence must not silently disable alerts ─────────────
class TestMigrationSafety:
    def test_active_without_tables_raises_not_false(self, monkeypatch):
        monkeypatch.setenv(rt.ENV_VAR, "ACTIVE")
        rt.reset_cache()
        monkeypatch.setattr(rt, "missing_tables", lambda conn=None, **k: ["alert_notification_events"])
        with pytest.raises(rt.MigrationUnavailable) as exc:
            rt.require_active_capability()
        assert "alert_notification_events" in str(exc.value)

    def test_off_and_shadow_never_raise_on_missing_tables(self, monkeypatch):
        monkeypatch.setattr(rt, "missing_tables", lambda conn=None, **k: list(rt.REQUIRED_TABLES))
        for mode in ("OFF", "SHADOW"):
            monkeypatch.setenv(rt.ENV_VAR, mode)
            rt.reset_cache()
            rt.require_active_capability()          # must not raise

    def test_shadow_does_not_persist_without_migration(self, monkeypatch):
        monkeypatch.setenv(rt.ENV_VAR, "SHADOW")
        rt.reset_cache()
        monkeypatch.setattr(rt, "missing_tables", lambda conn=None, **k: ["alert_digest_queue"])
        assert rt.can_persist_shadow() is False

    def test_off_mode_delivers_legacy_without_touching_new_tables(self, monkeypatch):
        """The regression that silently dropped every alert."""
        import telegram_alert as ta
        monkeypatch.setenv(rt.ENV_VAR, "OFF")
        rt.reset_cache()
        sent: list[str] = []
        monkeypatch.setattr(ta, "_raw_send_telegram", lambda m, chat_ids=None: sent.append(m) or True)
        monkeypatch.setattr(ta, "_token", lambda: "t")
        monkeypatch.setattr(ta, "_chat_ids", lambda: ["1"])

        def _explode(*a, **k):
            raise AssertionError("OFF mode must not touch the normalized outbox")
        monkeypatch.setitem(sys.modules, "alert_outbox", type(sys)("alert_outbox"))
        sys.modules["alert_outbox"].publish_legacy_message = _explode

        res = ta.publish_operator_message("ORPHANED STOP AAPL unprotected", bypass_router=True)
        assert res["accepted"] is True and res["delivered"] is True
        assert len(sent) == 1


# ── Blocker 3: DB preferences authoritative, invariants immutable ─────────────
class TestPreferenceAuthority:
    def test_preference_changes_routing(self):
        e = ev("scanner_candidate")
        default = resolve_route(e, mode="ACTIVE")
        assert default.route_mode == ROUTE_COMMAND_CENTER
        louder = resolve_route(
            e, mode="ACTIVE",
            preferences={"general_telegram": "IMMEDIATE", "command_center": True, "row_version": 3})
        assert louder.route_mode == ROUTE_IMMEDIATE
        assert louder.logical_destination == CRITICAL_OPERATIONS
        assert louder.applied_preference and louder.preference_row_version == 3

    def test_preference_can_quiet_to_digest(self):
        r = resolve_route(ev("stop_warning"), mode="ACTIVE",
                          preferences={"general_telegram": "DIGEST", "digest_bucket": "RISK"})
        assert r.route_mode == ROUTE_DIGEST and r.digest_bucket == "RISK"

    def test_invariant_paper_cannot_reach_approvals(self):
        r = resolve_route(ev("paper_proposal", operator_action_required=True,
                             authorization_or_order_id="auth-1"),
                          mode="ACTIVE", preferences={"approval_telegram": "IMMEDIATE"})
        assert r.logical_destination != APPROVALS_ONLY
        assert INV_PAPER_NOT_APPROVALS in r.invariant_violations

    def test_invariant_approvals_requires_allowlisted_type(self):
        # broker_auth_blocking is critical but NOT approval-allowlisted, and not a
        # paper/candidate type — so it isolates the allowlist invariant. (Using
        # job_telemetry here would trip the paper invariant first, which is correct
        # behaviour but a different rule.)
        r = resolve_route(ev("broker_auth_blocking", operator_action_required=True,
                             authorization_or_order_id="auth-1"),
                          mode="ACTIVE", preferences={"approval_telegram": "IMMEDIATE"})
        assert INV_APPROVALS_ALLOWLIST in r.invariant_violations
        assert r.logical_destination != APPROVALS_ONLY

    def test_invariant_approvals_requires_live_authorization(self):
        r = resolve_route(ev("live_order_2fa_required", operator_action_required=False),
                          mode="ACTIVE", preferences={"approval_telegram": "IMMEDIATE"})
        assert INV_APPROVALS_NEEDS_AUTH in r.invariant_violations
        assert r.logical_destination != APPROVALS_ONLY

    def test_allowlisted_with_authorization_does_reach_approvals(self):
        r = resolve_route(ev("live_order_2fa_required", operator_action_required=True,
                             authorization_or_order_id="intent-9"),
                          mode="ACTIVE", preferences={"approval_telegram": "IMMEDIATE"})
        assert r.logical_destination == APPROVALS_ONLY and not r.invariant_violations

    @pytest.mark.parametrize("atype", ["orphaned_stop", "position_unprotected", "protection_failure"])
    def test_invariant_protection_cannot_be_silenced_everywhere(self, atype):
        r = resolve_route(ev(atype, severity="critical", operator_action_required=True),
                          mode="ACTIVE",
                          preferences={"general_telegram": "OFF", "approval_telegram": "OFF",
                                       "command_center": False})
        assert r.route_mode != ROUTE_LOG
        assert INV_PROTECTION_ALWAYS_VISIBLE in r.invariant_violations

    def test_secrets_are_stripped_from_preferences(self):
        clean, violations = sanitize_preference(
            {"general_telegram": "IMMEDIATE", "chat_id": "-100123", "bot_token": "x"})
        assert "chat_id" not in clean and "bot_token" not in clean
        assert INV_NO_SECRETS_IN_PREFS in violations
        r = resolve_route(ev("orphaned_stop"), mode="ACTIVE",
                          preferences={"general_telegram": "IMMEDIATE", "chat_id": "-100123"})
        assert INV_NO_SECRETS_IN_PREFS in r.invariant_violations

    def test_mode_gates_delivery_not_routing(self):
        e = ev("orphaned_stop", severity="critical", operator_action_required=True)
        for mode, allowed in (("OFF", False), ("SHADOW", False), ("ACTIVE", True)):
            r = resolve_route(e, mode=mode)
            assert r.route_mode == ROUTE_IMMEDIATE      # routing is evaluated in all modes
            assert r.delivery_allowed is allowed        # delivery only in ACTIVE


# ── Blocker 7: synthetic events must never become deliverable ─────────────────
class TestSyntheticNotDeliverable:
    def test_delivery_prohibited_blocks_immediate(self):
        e = ev("orphaned_stop", severity="critical", operator_action_required=True,
               payload={"delivery_prohibited": True, "synthetic": True, "environment": "test"})
        r = resolve_route(e, mode="ACTIVE")
        assert r.delivery_allowed is False
        assert r.route_mode != ROUTE_IMMEDIATE
        assert r.suppression_reason == "synthetic_delivery_prohibited"

    def test_synthetic_cannot_be_re_enabled_by_preference(self):
        e = ev("orphaned_stop", payload={"delivery_prohibited": True})
        r = resolve_route(e, mode="ACTIVE", preferences={"general_telegram": "IMMEDIATE"})
        assert r.delivery_allowed is False


# ── Blocker 5: recurring-event dedupe, deterministic with injected timestamps ─
from datetime import datetime, timedelta, timezone                 # noqa: E402
from alert_dedupe import (                                         # noqa: E402
    NOTIFY_ESCALATION_DEADLINE,
    NOTIFY_FIRST_OCCURRENCE,
    NOTIFY_RECURRED_AFTER_RESOLUTION,
    NOTIFY_RESOLUTION,
    NOTIFY_SEVERITY_INCREASED,
    NOTIFY_STATE_VERSION,
    NOTIFY_WINDOW_ELAPSED,
    SUPPRESS_WITHIN_WINDOW,
    PriorState,
    should_notify,
)

T0 = datetime(2026, 7, 28, 14, 0, 0, tzinfo=timezone.utc)


def _prior(**kw):
    base = dict(last_notified_at=T0, last_seen_at=T0, severity="warning",
                operator_action_required=False, state_version="1",
                occurrence_count=1, notified_count=1)
    base.update(kw)
    return PriorState(**base)


class TestRecurringDedupe:
    def test_first_occurrence_notifies(self):
        d = should_notify(None, now=T0)
        assert d.notify and d.reason == NOTIFY_FIRST_OCCURRENCE and d.occurrence_seq == 1

    def test_duplicate_inside_window_suppressed(self):
        d = should_notify(_prior(), now=T0 + timedelta(minutes=5), severity="warning",
                          dedupe_window_seconds=900)
        assert not d.notify and d.reason == SUPPRESS_WITHIN_WINDOW
        assert d.suppressed_until == T0 + timedelta(seconds=900)

    def test_new_occurrence_after_window_notifies(self):
        """The lifetime-suppression bug: a later recurrence must notify again."""
        d = should_notify(_prior(), now=T0 + timedelta(hours=3), severity="warning",
                          dedupe_window_seconds=900)
        assert d.notify and d.reason == NOTIFY_WINDOW_ELAPSED and d.occurrence_seq == 2

    def test_severity_increase_breaks_window(self):
        d = should_notify(_prior(severity="warning"), now=T0 + timedelta(minutes=1),
                          severity="critical", dedupe_window_seconds=900)
        assert d.notify and d.reason == NOTIFY_SEVERITY_INCREASED

    def test_severity_decrease_does_not_notify(self):
        d = should_notify(_prior(severity="critical"), now=T0 + timedelta(minutes=1),
                          severity="info", dedupe_window_seconds=900)
        assert not d.notify

    def test_transition_to_action_required_breaks_window(self):
        d = should_notify(_prior(operator_action_required=False), now=T0 + timedelta(minutes=1),
                          severity="warning", operator_action_required=True,
                          dedupe_window_seconds=900)
        assert d.notify

    def test_state_version_change_breaks_window(self):
        d = should_notify(_prior(state_version="1"), now=T0 + timedelta(minutes=1),
                          severity="warning", state_version="2", dedupe_window_seconds=900)
        assert d.notify and d.reason == NOTIFY_STATE_VERSION

    def test_recurrence_after_resolution_notifies_inside_window(self):
        d = should_notify(_prior(resolved_at=T0 + timedelta(minutes=2)),
                          now=T0 + timedelta(minutes=3), severity="warning",
                          dedupe_window_seconds=86400)
        assert d.notify and d.reason == NOTIFY_RECURRED_AFTER_RESOLUTION

    def test_escalation_deadline_reraises_unacknowledged(self):
        d = should_notify(_prior(acknowledged_at=None), now=T0 + timedelta(minutes=40),
                          severity="warning", dedupe_window_seconds=86400,
                          escalate_after_seconds=1800)
        assert d.notify and d.reason == NOTIFY_ESCALATION_DEADLINE and d.is_escalation

    def test_acknowledged_alert_does_not_escalate(self):
        d = should_notify(_prior(acknowledged_at=T0 + timedelta(minutes=5)),
                          now=T0 + timedelta(minutes=40), severity="warning",
                          dedupe_window_seconds=86400, escalate_after_seconds=1800)
        assert not d.notify

    def test_resolution_is_reported_once(self):
        d = should_notify(_prior(), now=T0 + timedelta(hours=1), resolving=True)
        assert d.notify and d.reason == NOTIFY_RESOLUTION and d.is_resolution

    def test_resolution_not_reported_if_never_notified(self):
        d = should_notify(_prior(notified_count=0), now=T0 + timedelta(hours=1), resolving=True)
        assert not d.notify

    def test_occurrence_sequence_is_monotonic(self):
        seqs = [should_notify(_prior(occurrence_count=n), now=T0 + timedelta(hours=1)).occurrence_seq
                for n in (1, 2, 7)]
        assert seqs == [2, 3, 8]


# ── Blocker 12: shell bodies must never be interpolated into Python source ────
class TestShellBodySafety:
    """The old path was send_telegram(\"\"\"${MSG}\"\"\") inside a heredoc.

    These bodies each terminated that literal; the last one executed arbitrary code.
    They now travel over stdin as bytes and must arrive byte-identical.
    """

    HOSTILE = [
        ('double_quotes', 'he said "stop" now'),
        ('triple_quotes', 'body with """ triple quote'),
        ('dollar_brace', 'cost ${MSG} and $HOME and $(whoami)'),
        ('backticks', 'run `id` please'),
        ('backslashes', r'path C:\temp\new \\ end'),
        ('unicode', 'café — ✓ 日本語 · émoji 🚨'),
        ('multiline', 'line1\nline2 "quoted"\nline3 ${REPORT}'),
        ('python_injection', '"""); import os; os.system("touch /tmp/pwned_alert"); ("""'),
    ]

    @pytest.mark.parametrize("name,body", HOSTILE, ids=[n for n, _ in HOSTILE])
    def test_body_survives_stdin_unmodified(self, name, body, monkeypatch, capsys):
        import io
        import send_operator_alert as soa

        seen: list[str] = []
        stub = type(sys)("telegram_alert")
        stub.publish_operator_message = lambda b, **kw: (
            seen.append(b) or {"accepted": True, "delivered": False, "reason": "stub"})
        monkeypatch.setitem(sys.modules, "telegram_alert", stub)
        monkeypatch.setattr(sys, "argv", ["send_operator_alert.py", "--quiet"])
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(body.encode("utf-8"))))

        rc = soa.main()
        assert rc == 0, f"{name} was not accepted"
        assert seen == [body], f"{name} was mutated in transit"
        assert not Path("/tmp/pwned_alert").exists(), "injection executed"

    def test_empty_body_is_rejected_not_published(self, monkeypatch):
        import io
        import send_operator_alert as soa
        stub = type(sys)("telegram_alert")
        called: list[str] = []
        stub.publish_operator_message = lambda b, **kw: called.append(b)
        monkeypatch.setitem(sys.modules, "telegram_alert", stub)
        monkeypatch.setattr(sys, "argv", ["send_operator_alert.py", "--quiet"])
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"   \n  ")))
        assert soa.main() == 2 and called == []

    def test_shell_scripts_no_longer_interpolate_bodies(self):
        """Static guard: the heredoc pattern must not come back."""
        import re
        for rel in ("scripts/cron_wrapper.sh", "scripts/morning_eval_check.sh"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            assert not re.search(r'send_telegram\(\s*"""\$\{', text), f"{rel} still interpolates"
            assert "send_operator_alert.py" in text, f"{rel} does not use the safe sender"
            # absolute project path + venv, so cron's cwd cannot break imports
            assert '"$PROJ/' in text or '"$PY"' in text, f"{rel} lacks absolute paths"
