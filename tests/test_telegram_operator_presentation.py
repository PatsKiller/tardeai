#!/usr/bin/env python3
"""The operator channel must be readable, tappable, and honestly recorded.

Each test here corresponds to a defect measured on live outbound traffic over
the 7 days to 2026-09-10 (678 messages, `communication_events` where
`direction='OUTBOUND'`):

    97.6%  no command_center_url, 62 bodies naming a destination with no link
    15     visible Markdown escape characters (`siem\\_p1`)
    8      raw HTML tags rendered literally under parse_mode="Markdown"
    11     ledger body differed from the body actually sent

Producer of those numbers:
`trade-ai-audits/cursor-independent-closure-20260910/telegram_outbound_audit.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.notification_url_builder import (  # noqa: E402
    linkify_navigation,
    navigation_destination,
)
from scripts.telegram_transport import (  # noqa: E402
    escape_markdown,
    parse_mode_for,
    unescape_markdown,
)

FQDN_PREFIX = "https://"


# ---------------------------------------------------------------- navigation

def test_navigation_prose_resolves_to_a_route():
    """The exact strings the live producers emit."""
    assert navigation_destination("Check System → SIEM.") == "/v3/system"
    assert navigation_destination("review Command Center → alerts") == "/v3/alerts"
    assert navigation_destination("Review: Paper Journal") == "/v3/journal"
    assert navigation_destination("Open: Command Center → CIO") == "/v3/cio"


def test_body_with_no_destination_is_untouched():
    body = "P&L: $-227.79 | Avg R: -11.95R"
    assert navigation_destination(body) is None
    assert linkify_navigation(body) == body


def test_linkify_appends_an_absolute_link():
    out = linkify_navigation("7 events / 1 group(s) in 14d. Check System → SIEM.")
    assert "Open: " in out
    assert FQDN_PREFIX in out
    assert "/v3/system" in out
    # The prose says WHY to go; it must survive.
    assert "Check System → SIEM." in out


def test_linkify_does_not_double_link_a_body_that_already_has_one():
    body = "Coverage: 91%\n\nhttps://example.invalid/v3/trade-in-view"
    assert linkify_navigation(body) == body


def test_linkified_link_is_absolute_never_a_bare_path():
    """`raw audit: Command Center /v3/` is unopenable from a phone."""
    out = linkify_navigation("raw audit: Command Center /v3/")
    tail = out.rsplit("Open: ", 1)[-1].strip()
    assert tail.startswith(FQDN_PREFIX)
    assert "://" in tail


# -------------------------------------------------------------------- markup

def test_unescape_is_the_inverse_of_escape():
    raw = "siem_p1 cleanup_stale_proposals *bold* [x] `c`"
    assert unescape_markdown(escape_markdown(raw)) == raw


def test_unescape_leaves_an_authored_backslash_alone():
    assert unescape_markdown("path C:\\temp and 50\\50") == "path C:\\temp and 50\\50"


def test_html_body_selects_html_parse_mode():
    assert parse_mode_for("⚠️ <b>Health Agent: DEGRADED — 68/100</b>") == "HTML"


def test_markdown_body_keeps_markdown():
    assert parse_mode_for("⚡ *Watchpool: NVDA*") == "Markdown"


def test_plain_body_keeps_the_default():
    assert parse_mode_for("Closed: 2 | 0W / 2L / 0F") == "Markdown"


def test_mixed_markup_keeps_the_default_and_widens_nothing():
    """0 of 678 live messages mix the two. If one ever does, do not guess."""
    assert parse_mode_for("<b>x</b> and *y*") == "Markdown"


# ------------------------------------------------------- ledger equals wire

def test_wire_text_is_what_the_ledger_records():
    """The ledger stored the pre-rewrite string; the wire got the rewritten one.

    Both now go through one function, so they cannot drift.
    """
    from scripts.telegram_alert import operator_wire_text

    body = "7 events / 1 group(s) in 14d. Check System → SIEM."
    wire = operator_wire_text(body)
    assert wire != body
    assert operator_wire_text(body) == wire  # deterministic
    assert FQDN_PREFIX in wire


def test_wire_text_fails_soft_to_the_original(monkeypatch):
    """A presentation failure must not cost the operator the message.

    Patches ``notification_url_builder`` — the top-level name
    ``telegram_alert`` actually imports. ``scripts.notification_url_builder``
    is a second module object for the same file and patching it here would be
    an invalid mutation: green for a reason unrelated to the guard.
    """
    import notification_url_builder as nub  # the module telegram_alert imports
    from scripts.telegram_alert import operator_wire_text

    def boom(_):
        raise RuntimeError("presentation layer down")

    monkeypatch.setattr(nub, "publicize_message", boom)
    body = "Check System → SIEM."
    assert operator_wire_text(body) == body


def test_wire_text_of_empty_is_empty():
    from scripts.telegram_alert import operator_wire_text

    assert operator_wire_text("") == ""


# ------------------------------------------------- wiring, not just helpers

def test_plaintext_fallback_actually_unescapes_on_the_wire(monkeypatch):
    """Wiring test. The helper being correct proved nothing about the caller.

    First sendMessage fails (the Markdown parse 400 this path exists for);
    the retry must carry unescaped text, because parse_mode is gone.
    """
    from scripts import telegram_transport as tt

    # The interdict is on in CI and returns before any send. Disabling it for
    # this test exercises the fallback; it does not weaken the control, which
    # has its own coverage.
    monkeypatch.setattr(tt, "_interdicted", lambda: False)

    sent: list[dict] = []

    def fake_post(url, payload):
        sent.append(dict(payload))
        if len(sent) == 1:
            return {"ok": False, "status_code": 400, "response": {}}
        return {"ok": True, "status_code": 200,
                "response": {"result": {"message_id": 7}}}

    escaped = tt.escape_markdown("siem_p1 cleanup_stale_proposals")
    out = tt.deliver_text(
        token="t", chat_id="1", text=escaped, parse_mode="Markdown", post=fake_post,
    )
    assert out["ok"] is True
    assert out.get("plain_fallback") is True
    assert len(sent) == 2
    assert "\\_" in sent[0]["text"], "first attempt should carry the escapes"
    assert "\\_" not in sent[1]["text"], "operator must never see backslashes"
    assert "siem_p1" in sent[1]["text"]


def test_ledger_records_the_wire_body_not_the_producer_body(monkeypatch):
    """Wiring test for the ledger/wire divergence.

    Measured 2026-09-10: 11 of 678 stored bodies differed from what was sent.
    """
    import scripts.telegram_alert as ta

    captured: dict = {}

    class _Published:
        delivery_ids: list = []

    def fake_from_plain_message(*, producer, body, subject_key, message_class):
        captured["body"] = body
        captured["subject_key"] = subject_key
        return object()

    monkeypatch.setitem(
        sys.modules, "scripts.lib.comms.adapters",
        type(sys)("scripts.lib.comms.adapters"),
    )
    sys.modules["scripts.lib.comms.adapters"].from_plain_message = fake_from_plain_message
    monkeypatch.setitem(
        sys.modules, "scripts.lib.comms.client",
        type(sys)("scripts.lib.comms.client"),
    )
    sys.modules["scripts.lib.comms.client"].publish_communication = lambda ev: _Published()
    monkeypatch.setitem(
        sys.modules, "scripts.lib.comms.delivery",
        type(sys)("scripts.lib.comms.delivery"),
    )
    sys.modules["scripts.lib.comms.delivery"].settle_delivery = lambda *a, **k: None
    monkeypatch.setattr(ta, "_tag_outbound", lambda *a, **k: None)

    body = "7 events / 1 group(s) in 14d. Check System → SIEM."
    ta._best_effort_comms_publish(body, message_class="operator_alert", delivered=True)

    assert captured, "publish path did not run"
    assert captured["body"] == ta.operator_wire_text(body)
    assert captured["body"] != body
    assert FQDN_PREFIX in captured["body"]
