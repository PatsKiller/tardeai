"""Waves C4, D2, D3, E4 and G1.

C4  The interdict lived only in `send_message`, which delegates to `deliver_text`
    -- exported and callable directly, so any caller reaching it bypassed the
    interdict entirely. A control named for stopping delivery did not cover every
    path that delivers.

D2  The morning brief -- the one message read daily -- said "Open: Command Center
    → CIO" with NO LINK, while the canonical builder's docstring says all links
    MUST go through it. The renderer never imported it.

D3  "Five identical failures per batch" was never five failures: the query's
    LIMIT 5 with no aggregation emitted one alert per row, each rendering the same
    stringified exit code.

E4  Ten consecutive runs reported success with rows_produced=0 while a Finviz
    outage aged 64h -> 97h, and nothing read it. Fixing the second stage error
    removed the ALARM, not the outage.

G1  The freshness gate asked whether TODAY is Saturday, not whether the WINDOW
    contained hours the writer runs. At Monday 00:00 the 30h window is pure
    weekend, and it paged against a weekday-only writer.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("", "scripts"):
    p = str(ROOT / sub) if sub else str(ROOT)
    if p not in sys.path:
        sys.path.insert(0, p)


# ── C4 ────────────────────────────────────────────────────────────────────────

def test_deliver_text_is_interdictable_directly(monkeypatch):
    """The regression: the low-level sender must honour the interdict itself."""
    import telegram_transport as T
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "1")

    def must_not_run(*a, **k):
        raise AssertionError("network reached while interdicted")

    r = T.deliver_text(token="t", chat_id="c", text="probe", post=must_not_run)
    assert r.get("interdicted") is True
    assert r["response"]["description"] == "INTERDICTED_TEST_OR_FLAG"


def test_send_message_still_interdicted(monkeypatch):
    import telegram_transport as T
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("CIO_TELEGRAM_INTERDICT", "1")
    assert T.send_message(token="t", chat_id="c", text="probe").get("interdicted") is True


def test_the_guard_can_be_off(monkeypatch):
    """Guard the guard: prove the interdict is doing the work, not a hard stop."""
    import telegram_transport as T
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CIO_TELEGRAM_INTERDICT", raising=False)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        raise RuntimeError("stopped before any real network call")

    try:
        T.deliver_text(token="t", chat_id="c", text="probe", post=fake_post)
    except Exception:
        pass
    assert calls, "with the interdict off, the sender must reach its post callable"


# ── G1 ────────────────────────────────────────────────────────────────────────

def test_a_window_containing_weekday_hours_is_checked():
    import system_freshness_monitor as M
    assert M._window_covers_a_weekday(24 * 7) is True


def test_a_pure_weekend_window_is_skipped(monkeypatch):
    """The Monday-00:00 case that produced the false page.

    Today is Monday, so the old gate (`today.weekday() >= 5`) said "not a
    weekend" and ran the check -- against a 30h window that was entirely Sat/Sun.
    """
    import system_freshness_monitor as M

    class MondayMidnight(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 31, 0, 0, 0)      # a Monday, 00:00

    monkeypatch.setattr(M, "datetime", MondayMidnight)
    assert M._window_covers_a_weekday(30) is False, \
        "a 30h window from Monday 00:00 is pure weekend and must not be checked"


def test_the_old_gate_would_have_run_that_check():
    """Guard the guard: prove the old predicate really did fire on that Monday."""
    monday_midnight = datetime(2026, 8, 31, 0, 0, 0)
    assert monday_midnight.weekday() == 0
    assert not (monday_midnight.weekday() >= 5), \
        "the old gate did not consider this a weekend -- which is why it paged"


# ── D2 ────────────────────────────────────────────────────────────────────────

def test_the_morning_brief_renderer_uses_the_canonical_builder():
    src = (ROOT / "scripts" / "lib" / "cio_operator_renderers.py").read_text(encoding="utf-8")
    assert "build_dashboard_url" in src, "the brief must link through the canonical builder"


def test_the_canonical_builder_produces_a_cio_link():
    from scripts.notification_url_builder import build_dashboard_url
    url = build_dashboard_url("/v3/cio")
    assert url.startswith("http") and url.endswith("/v3/cio")


# ── D3 / E4 ───────────────────────────────────────────────────────────────────

def test_pipeline_failures_are_aggregated_by_cause():
    src = (ROOT / "scripts" / "alert_dispatcher_unified.py").read_text(encoding="utf-8")
    assert "GROUP BY pipeline_key" in src, "failures must aggregate, not emit one alert per row"
    assert "COUNT(*)" in src


def test_a_success_producing_nothing_raises_an_alert():
    src = (ROOT / "scripts" / "alert_dispatcher_unified.py").read_text(encoding="utf-8")
    assert "pipeline_zero_rows" in src, "a success with rows_produced=0 must alert"
    assert "rows_produced" in src
