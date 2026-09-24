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
COVERS = ["scripts/notify_material_change.py:350"]


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
    the operator stops hearing about the thing the alert exists for.

    Re-anchored 2026-09-24: the stamp lives in `_mark`, and every call to it must
    sit under an `if accepted:` guard (pages and digest alike). Checked on the AST
    so the next refactor cannot silently un-anchor it.
    """
    import ast

    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    guarded = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == "accepted":
            for b in n.body:
                guarded.update(id(x) for x in ast.walk(b))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_mark"]
    assert len(calls) >= 2, "pages and the digest both consume through _mark"
    assert all(id(c) in guarded for c in calls), "notified_at stamped outside an `if accepted:` guard"
    stamps = [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and "notified_at = now()" in n.value]
    assert len(stamps) == 1, "exactly one place may stamp notified_at: _mark"


# ── held is not dropped ─────────────────────────────────────────────────────

@pytest.mark.parametrize("when,expected", [
    (datetime(2026, 9, 4, 10, 0, tzinfo=ET), True),    # Friday mid-morning
    (datetime(2026, 9, 4, 9, 29, tzinfo=ET), False),   # one minute before the open
    (datetime(2026, 9, 4, 16, 1, tzinfo=ET), False),   # one minute after the close
    (datetime(2026, 9, 5, 12, 0, tzinfo=ET), False),   # Saturday
    (datetime(2026, 9, 6, 12, 0, tzinfo=ET), False),   # Sunday
])
def test_the_market_window_when_explicitly_enabled(mod, monkeypatch, when, expected):
    monkeypatch.setattr(mod, "NOTIFY_WINDOW", "market")
    assert mod.in_window(when) is expected


def test_outside_the_window_the_change_is_held_not_dropped(mod):
    src = SCRIPT.read_text(encoding="utf-8")
    held = src.split("if not open_now:", 1)[1].split("if not args.apply:", 1)[0]
    assert "HELD_OUTSIDE_WINDOW" in held
    assert "notified_at" not in held, "a held change must stay pending"


def test_alerts_are_not_gated_by_the_clock_by_default(mod):
    """Operator decision 2026-09-07. The market-hours default held 36 consecutive
    runs while AOUT burst at 07:13 and SPCX at 16:41 — the operator saw nothing and
    reasonably concluded the layer was dark. News does not wait for the bell."""
    assert mod.NOTIFY_WINDOW == "always"
    assert mod.in_window(datetime(2026, 9, 6, 3, 0, tzinfo=ET)) is True   # Sunday 3am
    assert mod.in_window(datetime(2026, 9, 7, 7, 13, tzinfo=ET)) is True  # pre-market


def test_the_market_window_still_works_when_asked_for(mod, monkeypatch):
    """The gating is not deleted, just no longer the default."""
    monkeypatch.setattr(mod, "NOTIFY_WINDOW", "market")
    assert mod.in_window(datetime(2026, 9, 6, 12, 0, tzinfo=ET)) is False  # Saturday
    assert mod.in_window(datetime(2026, 9, 4, 10, 0, tzinfo=ET)) is True


def test_stale_changes_are_not_announced(mod):
    """After a weekend or an outage the backlog would otherwise arrive as a wall.
    Age runs from when the detector RECORDED the change: price rows carry a
    date-only observed_at (midnight), which silently shortened their window."""
    src = SCRIPT.read_text(encoding="utf-8")
    assert "MAX_AGE_HOURS" in src
    assert "COALESCE(created_at, observed_at) > now()" in src


def test_pending_orders_by_precedence_first(mod):
    """precedence was never selected, so held names waited behind bigger watchlist moves."""
    src = SCRIPT.read_text(encoding="utf-8")
    sql = src.split("def pending(", 1)[1].split("\ndef ", 1)[0]
    assert "precedence" in sql.split("FROM material_changes")[0]
    assert "ORDER BY precedence DESC NULLS LAST, magnitude DESC NULLS LAST" in sql


def test_one_thrashing_name_cannot_dominate(mod):
    assert mod.MAX_PER_RUN > 0
    assert "LIMIT %s" in SCRIPT.read_text(encoding="utf-8")


# ── what the operator actually reads ────────────────────────────────────────

#: A held name on a fresh quote: the case that pages (operator decision 2026-09-24).
HELD = {"price": 12.4, "quote_age_h": 0.1, "holding": {"shares": 100.0, "accounts": ["Taxable"]}}


def test_the_move_is_expressed_relative_to_the_name_itself(mod):
    """'AOUT +45%' is a number. '14.9× its normal daily move' is intelligence."""
    msg = mod.render([_row()], {"g-1": HELD})
    assert "14.9× its normal daily move" in msg
    assert "45.4% move" in msg


def test_the_alert_says_WHAT_HAPPENED_not_how_many_rows_we_hold(mod):
    """The first version reported "we hold 212 articles, 209 catalysts" — internal
    plumbing on the operator's phone. The operator's verdict was "what am I supposed
    to do with these"."""
    msg = mod.render([_row()], {"g-1": {**HELD,
        "narrative": ["Shares jumped 14.6% after better-than-expected Q2 sales."],
        "questions": ["What were the margin percentages?"], "last_research": None}})
    assert "Shares jumped 14.6%" in msg
    assert "articles" not in msg and "catalysts" not in msg, "plumbing leaked again"


def test_the_first_line_says_held_or_not_and_what_happened(mod):
    """2026-09-24 review: the phone preview showed 'ROL · Strategy: dividend growth…'.
    The first line now carries the state, the name, and whether you own it."""
    held = mod.render([_row()], {"g-1": HELD}).splitlines()[0]
    assert held == "⚡ BIG MOVE — AOUT (held, 100 sh)", held
    ready = {"price": 12.4, "quote_age_h": 0.1, "entry_state": {"state": "BUY_READY", "entry_low": 12.0,
                                                                "entry_high": 12.6}}
    watch = mod.render([_row()], {"g-1": ready}).splitlines()[0]
    assert watch == "🟢 BUY READY — AOUT (watchlist, not held)", watch


def test_an_unheld_move_that_is_not_buy_ready_does_not_page(mod):
    """A fresh watchlist move with no stance of note is a digest line, not a page."""
    msg = mod.render([_row()], {"g-1": {"price": 12.4, "quote_age_h": 0.1, "strategy": "x",
                                        "strategy_inactive": False}})
    assert msg == ""


def test_research_status_is_never_claimed_without_evidence(mod):
    """'never researched — questions are being generated now' was printed as fact with
    nothing behind it. The notice no longer claims a research state it cannot see."""
    msg = mod.render([_row()], {"g-1": {**HELD, "last_research": None}})
    assert "questions are being generated" not in msg


def test_the_headline_is_used_when_curation_has_not_run(mod):
    """Better a real headline than a magnitude nobody can act on."""
    msg = mod.render([_row()], {"g-1": {**HELD, "headline": "Acme cuts full-year guidance"}})
    assert "Acme cuts full-year guidance" in msg


def test_it_never_advises(mod):
    msg = mod.render([_row()], {"g-1": HELD})
    assert "Advisory only" in msg and "Material change" in msg
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
    dry = src.split("    if not args.apply:\n", 1)[1].split("result[\"outcome\"]", 1)[0]
    assert 'result["rows_produced"] = None' in dry, "a dry run must leave rows_produced as None"
    assert "= 0" not in dry


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
            if "material_changes" in sql and "notified_at = now()" in sql:
                # Only a notified_at stamp CONSUMES a change; a notify_outcome note does not.
                updates.append((sql, params)); self._rows = []
            elif "material_changes" in sql and "UPDATE" in sql:
                self._rows = []
            elif "SELECT change_guid" in sql:
                self._rows = rows
            elif "subject_state_narratives" in sql or "due_diligence_questions" in sql:
                self._rows = []
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
    # A held name on a fresh quote: the case that pages (operator decision 2026-09-24).
    monkeypatch.setattr(mod, "context", lambda cur, change: dict(HELD))
    fake = type(sys)("telegram_alert")
    fake.send_telegram = lambda msg, **kw: (sent.append(msg), accepted)[1]
    monkeypatch.setitem(sys.modules, "telegram_alert", fake)
    monkeypatch.setattr(sys, "argv", ["x", "--apply", "--ignore-window"])
    mod.main()
    return sent, updates


def test_the_alarm_reaches_the_transport(mod, monkeypatch):
    """The firing test: inject a pending change, observe the message sent."""
    row = ("g-1", "AOUT", "price_excursion", 14.93, 3.0438, 45.4363,
           "2026-09-04 00:00:00", "held", None, None, 80, None)
    sent, updates = _drive(mod, monkeypatch, rows=[row])
    assert len(sent) == 1, "the alarm did not reach send_telegram"
    assert "BIG MOVE — AOUT (held, 100 sh)" in sent[0] and "14.9× its normal daily move" in sent[0]
    assert updates, "a sent alarm must mark the change notified"


def test_a_suppressing_router_neither_sends_nor_consumes(mod, monkeypatch):
    """The incident, reproduced. ACCEPTED-but-suppressed must not consume."""
    row = ("g-1", "AOUT", "price_excursion", 14.93, 3.0438, 45.4363,
           "2026-09-04 00:00:00", "held", None, None, 80, None)
    sent, updates = _drive(mod, monkeypatch, rows=[row], route="WOULD_SUPPRESS")
    assert sent == [], "it sent into a known suppression"
    assert updates == [], "it consumed a change the operator never received"


def test_an_unaccepted_send_does_not_consume(mod, monkeypatch):
    row = ("g-1", "AOUT", "price_excursion", 14.93, 3.0438, 45.4363,
           "2026-09-04 00:00:00", "held", None, None, 80, None)
    sent, updates = _drive(mod, monkeypatch, rows=[row], accepted=False)
    assert len(sent) == 1
    assert updates == [], "a rejected send must leave the change pending"


def test_the_body_pages_rather_than_digests(mod):
    """It classifies P0_INTERRUPT. Routed to DIGEST it arrived hours later, which
    for a 45% move is the same as not arriving."""
    from telegram_alert_router import classify_alert

    assert classify_alert(mod.render([_row()], {"g-1": HELD})) == "P0_INTERRUPT"


def test_a_thesis_phrase_cannot_reroute_a_page(mod):
    """2026-09-22..24: one name's thesis "RCL paper proposal for …" matched a
    dashboard-only rule and held an eight-name notice for 179 runs. The notice
    marker is matched before any content rule."""
    from telegram_alert_router import classify_alert, should_send_telegram

    msg = mod.render([_row()], {"g-1": {**HELD, "narrative": [
        "RCL paper proposal for dividend_growth_compounder was approved by the desk and is on watch."]}})
    assert classify_alert(msg) == "P0_INTERRUPT" and should_send_telegram(msg)


# ── one line per symbol ─────────────────────────────────────────────────────

def test_a_name_appears_once_however_many_signals_produced_it(mod):
    """The 2026-09-07 queue listed AOUT twice and SPCX twice. A name repeated in one
    alert is not more informative — it is harder to read and it crowds out the others."""
    rows = [_row(symbol="AOUT", magnitude=7.7, kind="news_burst"),
            _row(symbol="AOUT", magnitude=6.5, kind="news_burst"),
            _row(symbol="SPCX", magnitude=4.0, kind="catalyst_new")]
    out = mod.dedupe_by_symbol(rows)
    assert [c["symbol"] for c in out] == ["AOUT", "SPCX"]
    assert out[0]["magnitude"] == 7.7, "the strongest signal must survive, not the last"
    assert out[0]["also"] == 1


def test_collapsing_rows_keeps_one_line_per_name(mod):
    rows = [_row(symbol="AOUT", magnitude=7.7), _row(symbol="AOUT", magnitude=6.5)]
    out = mod.dedupe_by_symbol(rows)
    assert len(out) == 1 and out[0]["magnitude"] == 7.7


def test_precedence_orders_the_alert_not_magnitude_alone(mod):
    """A held name at 2x outranks a watchlist name at 9x — money at risk first."""
    rows = [_row(symbol="IDEA", magnitude=9.0, precedence=40),
            _row(symbol="HELD", magnitude=2.0, precedence=80)]
    out = mod.dedupe_by_symbol(rows)
    assert [c["symbol"] for c in out] == ["HELD", "IDEA"]
