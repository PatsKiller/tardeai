"""Wave 3E — notification decisions rendered as a Command Center block.

Operator scope, verbatim: **CC block only, INTERDICT stays on, no Telegram
producer.** That makes this pure rendering: it displays decisions
`NotificationPolicy@v1` already computed, constructs no message, selects no
adapter and reaches no channel.

These tests exist to keep it that way. A "render-only" surface is one refactor
away from a producer, and the refactor always looks reasonable at the time.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib.cio_command_center import build_notification_block

REPO = Path(__file__).resolve().parents[1]
CC = REPO / "scripts" / "lib" / "cio_command_center.py"
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def _plan(pid, stype, material=True, symbols=None, status="draft"):
    return {"plan_id": pid, "situation_type": stype, "material": material,
            "symbols": symbols or [], "status": status}


def _book():
    return [
        _plan("p_s6a", "S6_CONCENTRATION_OR_DISPOSITION", symbols=["SCHD"]),
        _plan("p_s6b", "S6_CONCENTRATION_OR_DISPOSITION", symbols=["DIV"]),
        _plan("p_s1", "S1_POSITION_LIFECYCLE", symbols=["V"]),
        _plan("p_s5", "S5_CASH_DEPLOYMENT"),
        _plan("p_cold", "S3_REENTRY_CANDIDATE", material=False, symbols=["XLI"]),
        _plan("p_closed", "S6_CONCENTRATION_OR_DISPOSITION", symbols=["BND"],
              status="cancelled"),
    ]


# ------------------------------------------------------------------ scope

def test_block_declares_no_producer_and_no_send():
    b = build_notification_block(_book(), now=NOW)
    assert b["producer"] is None
    assert b["channel"] == "command_center"
    assert b["telegram_sent"] is False
    assert b["would_send_any"] is False
    assert all(i["would_send"] is False for i in b["items"])


def test_interdict_and_notify_flags_are_reported_not_changed():
    b = build_notification_block(_book(), now=NOW)
    assert b["interdicted"] is True
    assert b["notify_enabled"] is False


def test_module_gained_no_delivery_import():
    """Render-only is one refactor away from a producer. Hold the line."""
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                                     CC.read_text(encoding="utf-8", errors="replace")))
    for bad in ("cio_notification_delivery", "send_cio_message",
                "api.telegram.org", "RealTelegramAdapter",
                "cio_telegram_transport", "FakeDeliveryAdapter"):
        assert bad not in code, bad


def test_block_never_flips_an_env_var():
    code = re.sub(r"#.*", "", re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "",
                                     CC.read_text(encoding="utf-8", errors="replace")))
    assert "os.environ[" not in code
    assert "putenv" not in code


def test_block_carries_no_imperative():
    from scripts.lib.execution_language import find_imperative

    b = build_notification_block(_book(), now=NOW)
    assert not find_imperative(str(b))


# ------------------------------------------------------------- rendering

def test_only_open_plans_are_considered():
    b = build_notification_block(_book(), now=NOW)
    assert b["considered"] == 5, "the cancelled plan must not be considered"


def test_s6_surfaces_and_nothing_is_immediate():
    b = build_notification_block(_book(), now=NOW)
    assert b["surfaced_n"] == 2
    assert b["immediate_n"] == 0
    assert {i["situation_type"] for i in b["items"]} == {
        "S6_CONCENTRATION_OR_DISPOSITION"}


def test_suppressed_reasons_are_shown_not_just_counted():
    """4 surfaced is only credible next to what was considered and dropped."""
    b = build_notification_block(_book(), now=NOW)
    assert b["suppressed_n"] == 3
    reasons = b["suppressed_by_reason"]
    assert reasons["s1_observational_default_suppressed"] == 1
    assert reasons["s5_cash_deployment_default_suppressed"] == 1
    assert reasons["not_material"] == 1


def test_counts_reconcile():
    b = build_notification_block(_book(), now=NOW)
    assert (b["surfaced_n"] + b["digest_n"] + b["immediate_n"]
            + b["suppressed_n"]) == b["considered"]


def test_items_are_capped():
    many = [_plan(f"p{i}", "S6_CONCENTRATION_OR_DISPOSITION", symbols=[f"S{i}"])
            for i in range(25)]
    b = build_notification_block(many, cap=10, now=NOW)
    assert len(b["items"]) == 10
    assert b["surfaced_n"] == 25, "cap trims display, never the count"


def test_empty_book_is_available_not_broken():
    b = build_notification_block([], now=NOW)
    assert b["available"] is True
    assert b["considered"] == 0
    assert b["items"] == []


def test_none_book_does_not_raise():
    assert build_notification_block(None, now=NOW)["considered"] == 0


def test_policy_unavailable_degrades_visibly(monkeypatch):
    """A missing policy must say so, not render an empty quiet block.

    Blocks the module in sys.modules rather than patching __import__: the
    policy is already imported by the time this runs, so an __import__ hook
    never fires and the test would pass vacuously.
    """
    import sys as _sys

    import scripts.lib as _pkg

    # `from scripts.lib import cio_notification_policy` resolves via the
    # package ATTRIBUTE once the package is loaded, so blocking sys.modules
    # alone is not enough — the import succeeds and the test passes vacuously.
    monkeypatch.setitem(_sys.modules, "scripts.lib.cio_notification_policy", None)
    monkeypatch.delattr(_pkg, "cio_notification_policy", raising=False)
    b = build_notification_block(_book(), now=NOW)
    assert b["available"] is False
    assert b["reason"] == "policy_unavailable"
    assert b["telegram_sent"] is False
    assert b["would_send_any"] is False


# ------------------------------------------------------------ mounted

def test_block_is_mounted_on_office_home():
    code = CC.read_text(encoding="utf-8", errors="replace")
    assert 'home["notifications"] = build_notification_block(plans)' in code


def test_office_home_still_reports_telegram_sent_false():
    code = CC.read_text(encoding="utf-8", errors="replace")
    assert 'home["telegram_sent"] = False' in code
