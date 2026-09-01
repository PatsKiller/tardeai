"""The P1 digest sender — the tier's missing delivery.

A P1_DIGEST verdict archives a message to telegram_outbox and returns False.
Those rows are readable in the v3 Reports portal but nothing pushed them, so
"digest" meant "archived to a pull surface nobody was watching". 4,387 rows since
2026-07-02 against 1,707 delivered.

COVERS is not claimed for this file: it has no send_telegram call site of its own
outside deliver(), which these tests do exercise, so it is listed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/p1_digest_sender.py"]

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _rows(n=3, start_id=100):
    return [(start_id + i, NOW - timedelta(hours=1), "siem_p1",
             f"🚨 SIEM P1: pipeline {i}", "body") for i in range(n)]


@pytest.fixture
def sender(tmp_path, monkeypatch):
    monkeypatch.setenv("P1_DIGEST_STATE", str(tmp_path / "wm.json"))
    for m in list(sys.modules):
        if m == "p1_digest_sender":
            del sys.modules[m]
    import p1_digest_sender as P
    monkeypatch.setattr(P, "STATE", tmp_path / "wm.json", raising=True)
    return P


# ── rendering ────────────────────────────────────────────────────────────────
def test_digest_aggregates_by_cause_with_counts(sender):
    text = sender.render({"rows": _rows(13), "since_hours": 24, "watermark": 0})
    assert "×13" in text, text
    assert "13 suppressed messages" in text


def test_nothing_suppressed_renders_nothing(sender):
    assert sender.render({"rows": [], "since_hours": 24, "watermark": 0}) == ""


def test_many_kinds_are_folded_with_a_stated_remainder(sender):
    rows = [(i, NOW, f"kind_{i}", f"t{i}", "b") for i in range(40)]
    text = sender.render({"rows": rows, "since_hours": 24, "watermark": 0})
    assert "more kinds" in text, "a truncated list must say how many it folded"


# ── the safety property: the watermark ───────────────────────────────────────
def test_watermark_advances_only_after_a_confirmed_send(sender, monkeypatch):
    monkeypatch.setattr(sender, "collect",
                        lambda since_hours=24, query=None: {"rows": _rows(3), "since_hours": 24, "watermark": 0})
    monkeypatch.setattr(sender, "deliver", lambda text: True)
    monkeypatch.setattr(sys, "argv", ["p1", "--send"])
    assert sender.main() == 0
    assert json.loads(sender.STATE.read_text())["last_id"] == 102


def test_a_failed_delivery_does_not_advance_the_watermark(sender, monkeypatch):
    """Advancing first would silently drop the batch — the failure mode at issue."""
    monkeypatch.setattr(sender, "collect",
                        lambda since_hours=24, query=None: {"rows": _rows(3), "since_hours": 24, "watermark": 0})
    monkeypatch.setattr(sender, "deliver", lambda text: False)
    monkeypatch.setattr(sys, "argv", ["p1", "--send"])
    assert sender.main() == 1
    assert not sender.STATE.exists(), "watermark written despite a failed delivery"


def test_dry_run_sends_nothing_and_does_not_advance(sender, monkeypatch, alarm_capture):
    monkeypatch.setattr(sender, "collect",
                        lambda since_hours=24, query=None: {"rows": _rows(3), "since_hours": 24, "watermark": 0})
    monkeypatch.setattr(sys, "argv", ["p1"])
    assert sender.main() == 0
    assert not alarm_capture.fired
    assert not sender.STATE.exists()


# ── delivery must not be swallowed by the mechanism it drains ────────────────
def test_delivery_reaches_the_transport(sender, alarm_capture):
    assert sender.deliver("📋 P1 digest — probe") is True
    alarm_capture.assert_fired(contains="P1 digest")


def test_delivery_survives_a_router_that_refuses_everything(sender, alarm_capture, monkeypatch):
    """A digest OF suppressed messages, if routed, is suppressed in turn.

    That is not hypothetical: it is the same classification that swallowed its
    contents. This asserts the bypass is load-bearing.
    """
    try:
        import telegram_alert_router as TR
        monkeypatch.setattr(TR, "should_send_telegram", lambda *a, **k: False, raising=True)
    except Exception:
        pytest.skip("router unavailable")
    sender.deliver("📋 P1 digest — must survive the router")
    alarm_capture.assert_fired(contains="must survive")


# ── the backlog hazard ───────────────────────────────────────────────────────
def test_collect_is_bounded_by_time_not_only_by_watermark(sender):
    """A first run with watermark 0 must not page 4,387 rows.

    The query is bounded by BOTH id and sent_at, so a fresh state file yields the
    recent window rather than the entire archive.
    """
    seen = {}

    def fake_query(sql, params=None):
        seen["sql"] = sql
        seen["params"] = params
        return []

    sender.collect(since_hours=6, query=fake_query)
    assert "sent_at >" in seen["sql"], seen["sql"]
    assert "id > " in seen["sql"], seen["sql"]
    assert len(seen["params"]) == 2


# ── embedded foreign markup must not break the digest ────────────────────────
FAILING_BODIES = [
    (1, NOW, "health_agent", "⚠️ <b>Health Agent: DEGRADED — 70/100</b>", "b"),
    (2, NOW, "trade_ai_live", "⚡ *Trade AI v12.1d [0900]* | 2026-08-31", "b"),
]


def test_foreign_html_is_stripped_from_embedded_titles(sender):
    """The first live send 400'd on these exact bodies."""
    text = sender.render({"rows": FAILING_BODIES, "since_hours": 24, "watermark": 0})
    assert "<b>" not in text and "</b>" not in text, text


def test_embedded_titles_are_escaped_by_the_shared_escaper(sender):
    """A title is DATA. Unescaped, it is markup, and Telegram rejects the message.

    Asserted by DELEGATION, not by re-deriving the escaper's rules here. An earlier
    version of this test required every `[`, `]`, `*` and `_` to be backslashed and
    failed on correct output, because Markdown V1 escapes an opening bracket and
    leaves the closing one alone. A test that re-implements the thing it checks will
    disagree with it, and the test is usually the one that is wrong.
    """
    from telegram_transport import escape_markdown

    raw = "⚡ *Trade AI v12.1d [0900]* | 2026-08-31"
    assert sender._safe(raw) == escape_markdown(raw), "not delegating to the shared escaper"
    assert sender._safe("<b>x</b>") == escape_markdown("x"), "HTML must be stripped first"

    text = sender.render({"rows": FAILING_BODIES, "since_hours": 24, "watermark": 0})
    assert "\\*" in text, "the literal asterisk from the title is not escaped"


def test_the_escaper_is_the_shared_one_not_a_new_convention(sender):
    src = (ROOT / "scripts" / "p1_digest_sender.py").read_text(encoding="utf-8")
    assert "from telegram_transport import escape_markdown" in src, (
        "use the shared escaper; a 127th private convention is the defect it replaced"
    )


# ── the watermark must not be keyed to a checkout ────────────────────────────
def test_default_watermark_is_not_tree_relative():
    """A per-tree watermark is not a cache. It is a duplicate delivery.

    This shipped tree-relative and re-sent 33 already-delivered messages: the job
    ran once from the deploy worktree (watermark -> 6159) and once from the hub,
    which had none of its own and so started at 0. Same class as the release-local
    logs/ and the two holdings copies.
    """
    import importlib, os, sys
    os.environ.pop("P1_DIGEST_STATE", None)
    sys.modules.pop("p1_digest_sender", None)
    import p1_digest_sender as P
    importlib.reload(P)
    d = P._default_state_path()
    assert "r20-r24" not in str(d) and "trade-ai-v12-rebuild" not in str(d), (
        f"watermark defaults inside a checkout: {d}"
    )


def test_empty_env_override_does_not_resolve_to_cwd():
    """Path("") is Path("."), which is TRUTHY.

    `Path(os.environ.get(...)) or _default()` silently put the watermark in the
    current directory — so every run from a different cwd started from zero.
    """
    import importlib, os, sys
    os.environ["P1_DIGEST_STATE"] = ""
    sys.modules.pop("p1_digest_sender", None)
    import p1_digest_sender as P
    importlib.reload(P)
    try:
        assert P.STATE != pathlib_Path("."), "empty override resolved to the cwd"
        assert str(P.STATE) not in (".", ""), f"bad state path: {P.STATE}"
    finally:
        os.environ.pop("P1_DIGEST_STATE", None)


from pathlib import Path as pathlib_Path  # noqa: E402
