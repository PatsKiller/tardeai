"""Stage 2: the alert that would have arrived on Friday.

Stage 1 detects; this speaks. A detector nobody reads is the same as no detector.

Three properties, each paid for by something that went wrong:

ANNOUNCED EXACTLY ONCE
    change_guid is UUID and psycopg2 sends a Python list of strings as text[],
    which Postgres will not compare to uuid. The first live run SENT the alert and
    then failed on the UPDATE, leaving the rows unmarked — so the next run announced
    the same three changes again. Duplicate alerts are how an operator learns to
    ignore them.

HELD IS NOT DROPPED
    Outside market hours a change stays pending and is announced at the next open.
    Dropping it would mean a Friday-evening move is never mentioned, which is the
    exact failure this feature exists to fix.

A SUPPRESSED SEND MUST NOT CONSUME THE CHANGE
    send_telegram returns True when the platform ACCEPTED an event, which is not
    proof anyone saw it — on 2026-09-05 two adjacent ledger rows both read
    LEGACY_DELIVERED and one had been suppressed by the router. So a change is
    marked notified only on an accepted send.

No database, no network, no Telegram.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

SCRIPT = ROOT / "scripts" / "notify_material_change.py"
ET = ZoneInfo("America/New_York")

#: The alarm site this file drives end to end.
COVERS = ["scripts/notify_material_change.py:254"]


@pytest.fixture(scope="module")
def mod():
    return pytest.importorskip("notify_material_change")


def _row(**kw):
    base = {"change_guid": "g-1", "symbol": "AOUT", "kind": "price_excursion",
            "magnitude": 14.93, "baseline": 3.0438, "observed_value": 45.4363,
            "observed_at": "2026-09-04 00:00:00", "universe_reason": "watchlist",
            "subject_guid": "s-1"}
    base.update(kw)
    return base


# ── announced exactly once ──────────────────────────────────────────────────

def test_the_update_casts_to_uuid(mod):
    """The bug that duplicated the first live alert."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "ANY(%s::uuid[])" in src
    assert "WHERE change_guid = ANY(%s)\"\"\"" not in src


def test_only_unnotified_changes_are_selected(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert "notified_at IS NULL" in src


def test_a_suppressed_send_leaves_the_change_pending(mod):
    """Marking a suppressed alert as notified consumes it silently, which is how
    the operator stops hearing about the thing the alert exists for."""
    src = SCRIPT.read_text(encoding="utf-8")
    body = src.split("accepted = bool(send_telegram", 1)[1]
    marked = body.split("if accepted:", 1)[1].split("else:", 1)[0]
    assert "notified_at = now()" in marked, "the mark must be inside the accepted branch"
    unaccepted = body.split("else:", 1)[1]
    assert "notified_at" not in unaccepted


# ── held is not dropped ─────────────────────────────────────────────────────

@pytest.mark.parametrize("when,expected", [
    (datetime(2026, 9, 4, 10, 0, tzinfo=ET), True),    # Friday mid-morning
    (datetime(2026, 9, 4, 9, 29, tzinfo=ET), False),   # one minute before the open
    (datetime(2026, 9, 4, 16, 1, tzinfo=ET), False),   # one minute after the close
    (datetime(2026, 9, 5, 12, 0, tzinfo=ET), False),   # Saturday
    (datetime(2026, 9, 6, 12, 0, tzinfo=ET), False),   # Sunday
])
def test_the_market_window(mod, when, expected):
    assert mod.in_window(when) is expected


def test_outside_the_window_the_change_is_held_not_dropped(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    held = src.split("if not open_now:", 1)[1].split("if not args.apply:", 1)[0]
    assert "HELD_OUTSIDE_WINDOW" in held
    assert "notified_at" not in held, "a held change must stay pending"


def test_the_window_can_be_disabled(mod, monkeypatch):
    monkeypatch.setattr(mod, "NOTIFY_WINDOW", "always")
    assert mod.in_window(datetime(2026, 9, 6, 3, 0, tzinfo=ET)) is True


def test_stale_changes_are_not_announced(mod):
    """After a weekend or an outage the backlog would otherwise arrive as a wall."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "MAX_AGE_HOURS" in src
    assert "observed_at > now()" in src


def test_one_thrashing_name_cannot_dominate(mod):
    assert mod.MAX_PER_RUN > 0
    assert "LIMIT %s" in SCRIPT.read_text(encoding="utf-8")


# ── what the operator actually reads ────────────────────────────────────────

def test_the_move_is_expressed_relative_to_the_name_itself(mod):
    """'AOUT +45%' is a number. '14.9x its normal daily move' is intelligence."""
    msg = mod.render([_row()], {"s-1": {"articles": 64, "catalysts": 70,
                                        "last_research": None}})
    assert "14.9x its normal daily move" in msg
    assert "usual 3.0%" in msg


def test_the_alert_says_what_we_already_hold(mod):
    msg = mod.render([_row()], {"s-1": {"articles": 64, "catalysts": 70,
                                        "last_research": None}})
    assert "64 articles" in msg and "70 catalysts" in msg
    assert "no prior research" in msg


def test_absence_is_stated_as_a_fact_about_the_corpus(mod):
    """Not about the world. We can only ever say what WE hold."""
    msg = mod.render([_row(subject_guid=None)], {})
    assert "nothing linked in the corpus yet" in msg


def test_it_never_advises(mod):
    msg = mod.render([_row()], {})
    assert "Advisory only" in msg
    for banned in ("buy", "sell", "trim", "add to", "target price"):
        assert banned not in msg.lower()


def test_it_is_advisory_only_and_free(mod):
    assert mod.AUTHORITY == "READ_ONLY_ADVISORY"
    src = SCRIPT.read_text(encoding="utf-8")
    assert '"model_calls": 0' in src
    for banned in ("place_order(", "submit_order(", "position_size("):
        assert banned not in src


# ── honest counting ────────────────────────────────────────────────────────

def test_a_dry_run_reports_unmeasured_not_zero(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    dry = src.split("if not args.apply:", 1)[1].split("return 0", 1)[0]
    assert "rows_produced" not in dry, "a dry run must leave rows_produced as None"


def test_nothing_pending_is_a_measured_zero(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    assert 'result["rows_produced"] = 0 if args.apply else None' in src


# ── the alarm actually fires ────────────────────────────────────────────────
#
# Required by the alarm-coverage gate, and independently worth having: this file
# was written after the first live send was ACCEPTED, suppressed into the 8pm
# digest, and marked notified anyway. Routing verdicts alone would not have caught
# that — only driving the send and observing what reaches the transport does.

def _drive(mod, monkeypatch, *, rows, route="WILL_SEND", accepted=True):
    """Run main() with no database, no router and no Telegram."""
    sent: list[str] = []
    updates: list[tuple] = []

    class C:
        def __init__(self):
            self._rows = []

        def execute(self, sql, params=None):
            if "material_changes" in sql and "UPDATE" in sql:
                updates.append((sql, params)); self._rows = []
            elif "SELECT change_guid" in sql:
                self._rows = rows
            else:
                self._rows = [(0,)]

        def fetchall(self):
            return self._rows

        def fetchone(self):
            return (0,)

        @property
        def rowcount(self):
            return len(rows)

    class Conn:
        def cursor(self): return C()
        def commit(self): pass
        def close(self): pass

    monkeypatch.setattr(mod, "_db", lambda: Conn())
    monkeypatch.setattr(mod, "route_check", lambda m: route)
    monkeypatch.setattr(mod, "context", lambda cur, sg: {})
    fake = type(sys)("telegram_alert")
    fake.send_telegram = lambda msg, **kw: (sent.append(msg), accepted)[1]
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(sys, "argv", ["x", "--apply", "--ignore-window"])
    mod.main()
    return sent, updates


def test_the_alarm_reaches_the_transport(mod, monkeypatch):
    """The firing test: inject a pending change, observe the message sent."""
    row = ("g-1", "AOUT", "price_excursion", 14.93, 3.0438, 45.4363,
           "2026-09-04 00:00:00", "watchlist", None)
    sent, updates = _drive(mod, monkeypatch, rows=[row])
    assert len(sent) == 1, "the alarm did not reach send_telegram"
    assert "AOUT" in sent[0] and "14.9x its normal daily move" in sent[0]
    assert updates, "a sent alarm must mark the change notified"


def test_a_suppressing_router_neither_sends_nor_consumes(mod, monkeypatch):
    """The incident, reproduced. ACCEPTED-but-suppressed must not consume."""
    row = ("g-1", "AOUT", "price_excursion", 14.93, 3.0438, 45.4363,
           "2026-09-04 00:00:00", "watchlist", None)
    sent, updates = _drive(mod, monkeypatch, rows=[row], route="WOULD_SUPPRESS")
    assert sent == [], "it sent into a known suppression"
    assert updates == [], "it consumed a change the operator never received"


def test_an_unaccepted_send_does_not_consume(mod, monkeypatch):
    row = ("g-1", "AOUT", "price_excursion", 14.93, 3.0438, 45.4363,
           "2026-09-04 00:00:00", "watchlist", None)
    sent, updates = _drive(mod, monkeypatch, rows=[row], accepted=False)
    assert len(sent) == 1
    assert updates == [], "a rejected send must leave the change pending"


def test_the_body_pages_rather_than_digests(mod):
    """It classifies P0_INTERRUPT. Routed to DIGEST it arrived hours later, which
    for a 45% move is the same as not arriving."""
    from telegram_alert_router import classify_alert

    msg = mod.render([_row()], {"s-1": {"articles": 64, "catalysts": 70,
                                        "last_research": None}})
    assert classify_alert(msg) == "P0_INTERRUPT"
