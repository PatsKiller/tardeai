"""A price the market has moved past may not be spoken as a current price.

The operator asked "how is S for entry on cyber" on 2026-09-22 and the desk replied
"$19.84 close Sep 04" -- stated flatly, no age, on a question about entering today.
Both halves of that are defects and both are pinned here.

SELECTION. Measured 2026-09-22 ~13:30 EDT: market_quotes held 4,975 distinct symbols
refreshed within 0.2h (BAX/MU/PLTR all 0.2h) and S's newest row was 431.1h old across 3
rows total. The refresher was healthy; S was excluded from its universe. watchlist_items
held two rows for S -- status='removed' (05-31) and status='researched' (updated 09-18) --
and the predicate matched neither. The duplicate row is a red herring: the universe is a
UNION of rows, so 'removed' cannot suppress 'researched'; the 'researched' row simply never
qualified. ticker_prices is downstream (4,752 of 4,813 rows on 2026-09-22 carry
source='market_quotes'), so the same exclusion emptied the store the desk actually read.

STALENESS. Fixing selection does not fix this: 6,899 'removed' symbols stay out of the
universe by design, and the operator can still ask about any of them. So the marker is the
part that must hold regardless -- and it must hold in BOTH directions. Half these tests
pin that a stale close is marked; the other half pin that Friday's close is NOT called
stale on a Saturday, because a marker that cries wolf is one someone turns off.

AUTHORITY: READ_ONLY_ADVISORY. No broker, no network, no database.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import external_market_data_ingest as ingest  # noqa: E402
from scripts.lib.cio_operator_desk_loop import (  # noqa: E402
    _subject_required_tokens,
    _subject_takeaway,
    format_subject_brief,
    price_age_note,
)

ET = ZoneInfo("America/New_York")

# The real calendar around the incident: 09-18 Fri, 09-19/20 weekend, 09-21 Mon, 09-22 Tue.
# Confirmed against ticker_prices coverage by date (4,693 symbols 09-18, none 09-19/20,
# 4,866 09-21, 4,813 09-22).
ASKED_AT = datetime(2026, 9, 22, 13, 30, tzinfo=ET)  # when the operator asked
S_CLOSE = "2026-09-04"                                # what the desk quoted


# ── half 1: the refresh universe ─────────────────────────────────────────────


class _FakeCursor:
    """Runs the real UNIVERSE_SQL against sqlite and shapes rows like RealDictCursor."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._rows: list[tuple] = []

    def execute(self, sql: str, params=None) -> None:
        self._rows = self._conn.execute(sql, params or []).fetchall()

    def fetchall(self) -> list[dict]:
        return [{"symbol": r[0]} for r in self._rows]


class _FakeConn:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def cursor(self, **_kw):
        return _FakeCursor(self._conn)

    def close(self) -> None:
        pass


def _universe_db() -> sqlite3.Connection:
    """The live shape of the three tables, including S's duplicate watchlist rows."""
    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE ticker_strategy_classifications (symbol TEXT, active BOOLEAN);
        CREATE TABLE paper_trades (symbol TEXT, status TEXT);
        CREATE TABLE watchlist_items (symbol TEXT, in_directive_watch BOOLEAN, status TEXT);

        -- S as it actually sits in the database: classified but INACTIVE, no open trade,
        -- and two watchlist rows, neither in directive-watch.
        INSERT INTO ticker_strategy_classifications VALUES ('S', 0), ('MU', 1);
        INSERT INTO paper_trades VALUES ('TMHC', 'open');
        INSERT INTO watchlist_items VALUES
            ('S',    0, 'removed'),      -- 2026-05-31
            ('S',    0, 'researched'),   -- 2026-09-18, the row that must now qualify
            ('DROP', 0, 'removed'),      -- deliberately dropped: must STAY out
            ('ACTV', 0, 'active'),
            ('SPCX', 1, 'removed');      -- directive-watch outranks status, as before
        """
    )
    return db


def _selected(monkeypatch) -> list[str]:
    db = _universe_db()
    monkeypatch.setattr(ingest, "_get_conn", lambda: _FakeConn(db))
    return ingest._get_symbols()


def test_researched_symbol_is_in_the_refresh_universe(monkeypatch):
    """NEGATIVE CONTROL: the exact live exclusion. RED if 'researched' leaves the predicate."""
    assert "S" in _selected(monkeypatch)


def test_removed_symbol_is_still_excluded(monkeypatch):
    """The other direction. RED if someone 'fixes' this by quoting every watchlist row.

    6,899 symbols carry status='removed' -- names the operator dropped. Refreshing them is
    a provider bill for nothing, and the staleness marker is what protects an answer about
    one of them.
    """
    assert "DROP" not in _selected(monkeypatch)


def test_directive_watch_still_outranks_status(monkeypatch):
    """SPCX is 'removed' but directive-watched: the pre-existing rule must survive."""
    assert "SPCX" in _selected(monkeypatch)


def test_duplicate_watchlist_rows_do_not_suppress_or_duplicate(monkeypatch):
    """S has two rows. A UNION of rows means the dead one cannot mask the live one."""
    assert _selected(monkeypatch).count("S") == 1


def test_single_letter_symbol_survives_the_length_filter(monkeypatch):
    """'S' is one character; the `len(s) <= 5` / no-dash filter must not eat it."""
    picked = _selected(monkeypatch)
    assert "S" in picked and "MU" in picked and "TMHC" in picked


# ── half 2: the staleness marker ─────────────────────────────────────────────


def test_the_quoted_close_is_marked_stale():
    """NEGATIVE CONTROL: the exact price the operator was given, at the time he asked."""
    note = price_age_note(S_CLOSE, now=ASKED_AT)
    assert note["stale"] is True
    assert note["age_days"] == 18
    assert "STALE" in note["note"]
    assert "18 days old" in note["note"]
    assert "NOT a current price" in note["note"]


def test_last_completed_session_close_is_not_stale():
    """Monday's close, asked on Tuesday mid-session: the freshest close that can exist."""
    assert price_age_note("2026-09-21", now=ASKED_AT)["stale"] is False


def test_friday_close_is_not_stale_on_saturday():
    """A marker that fires every weekend gets turned off. Market time, not wall clock."""
    assert price_age_note("2026-09-18", now=datetime(2026, 9, 19, 11, 0, tzinfo=ET))["stale"] is False


def test_friday_close_is_not_stale_monday_premarket():
    """Nothing has traded yet on Monday, so Friday's close is still authoritative."""
    assert price_age_note("2026-09-18", now=datetime(2026, 9, 21, 8, 30, tzinfo=ET))["stale"] is False


def test_friday_close_goes_stale_once_monday_has_closed():
    """The point that stops this being a way of making old data look young."""
    note = price_age_note("2026-09-18", now=ASKED_AT)
    assert note["stale"] is True
    assert note["age_days"] == 4


def test_unparseable_price_date_never_raises():
    assert price_age_note(None)["stale"] is False
    assert price_age_note("not-a-date")["stale"] is False


# ── half 2b: the marker reaches what the operator reads ──────────────────────


def _stale_avail() -> dict:
    note = price_age_note(S_CLOSE, now=ASKED_AT)
    return {
        "subject_price": {
            "S": {
                "close": 19.84, "price_date": S_CLOSE, "change_30d_pct": None,
                "price_stale": note["stale"], "price_age_days": note["age_days"],
                "price_stale_note": note["note"],
            }
        },
    }


def test_rendered_brief_never_states_the_price_bare():
    """NEGATIVE CONTROL: the reply the operator actually got. RED if the render is reverted."""
    text = format_subject_brief(["S"], _stale_avail())
    assert "$19.84" in text
    assert "STALE" in text
    assert "18 days old" in text
    # the defect verbatim: the close and its date, with nothing between them and the reader
    assert "Price $19.84 (close Sep 04)\n" not in text
    assert not text.rstrip().endswith("Price $19.84 (close Sep 04)")


def test_fresh_price_renders_clean():
    """No marker noise on a current close -- the brief must stay readable."""
    fresh = {"subject_price": {"MU": {"close": 100.0, "price_date": "2026-09-21",
                                      "price_stale": False, "price_stale_note": ""}}}
    text = format_subject_brief(["MU"], fresh)
    assert "$100.00" in text
    assert "STALE" not in text


def test_required_tokens_force_the_marker_through_the_flash_rewrite():
    """The Flash summary is rejected unless it keeps the marker, so the brief is sent instead."""
    req = _subject_required_tokens(["S"], _stale_avail())
    assert "$19.84" in req
    assert "STALE" in req
    assert "18 days old" in req


def test_takeaway_says_the_levels_are_measured_off_a_stale_close():
    """'17.9% below resistance' off an 18-day-old print reads as a live setup."""
    price = _stale_avail()["subject_price"]["S"]
    row = {"resistance": {"level": 23.0}, "stop": 18.0}
    take = _subject_takeaway("S", price, row, None, [])
    assert "STALE" in take
    assert take.index("STALE") < take.index("resistance")


def test_takeaway_stays_quiet_when_the_close_is_current():
    price = {"close": 100.0, "price_date": "2026-09-21", "price_stale": False}
    take = _subject_takeaway("MU", price, {"resistance": {"level": 110.0}, "stop": 90.0}, None, [])
    assert "STALE" not in take
