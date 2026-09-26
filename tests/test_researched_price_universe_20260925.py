"""A researched name must stay in the price-refresh universe (split out of PR #1189).

2026-09-22: the operator asked "how is S for entry" and the desk quoted S's 2026-09-04 close.
market_quotes was healthy (4,975 symbols refreshed within 0.2h) but S was outside the refresh
universe: its watchlist rows were status='removed' (05-31) and status='researched' (09-18), and
the predicate matched neither. The universe is a UNION of rows, so 'removed' cannot suppress
'researched'; 'researched' simply never qualified. These tests pin both directions: researched
names are refreshed, deliberately removed names are not.

AUTHORITY: READ_ONLY_ADVISORY. No broker, no network, no database (sqlite shim).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import external_market_data_ingest as ingest  # noqa: E402


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
