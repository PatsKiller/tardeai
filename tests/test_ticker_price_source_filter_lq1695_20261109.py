"""LQ-20261107-1695 — a reader over ``ticker_prices`` never serves a banned source.

ANCHOR: TICKER_PRICE_SOURCE_FILTER_LQ1695_20261109

The operator price rule (2026-11-07, WORKERS.md "N8N ONBOARDING + PRICE WORK"): "Finviz cache first
(30 min), a fresh Schwab/Alpaca/moomoo quote second, the stored mark only flagged stale. Never
yfinance." LQ-20261107-1679 removed the last yfinance *writers*. Read-only measurement on the live
store 2026-11-09:

    source                rows       newest price_date
    yfinance              687,708    2026-10-30
    market_quotes         527,080    2026-11-09
    finviz                  6,774    2026-11-09
    alpaca                  7,071    2026-11-06
    yfinance_eod                1    2026-11-02

So "no yfinance writes remain" was true and "no yfinance price is served" was not: a query that
did not name a source returned a nine-day-old (or year-old) yfinance close as the current close.
This is the reader half of the rule. ``lib/price_provenance.py`` holds the one predicate; this
file pins the two things a ratchet needs:

  A. a repo-wide SHRINK-ONLY scan over ``scripts/`` — every SQL statement that names
     ``ticker_prices`` (and is not a docstring) must carry ``sql_source_allowed()``, or be listed in
     ``config/ticker_price_reader_baseline.json`` with a kind and a checkable reason. A new
     statement fails; a baseline entry that no longer matches fails (delete it); editing a listed
     statement changes its hash, so a re-baseline is a visible edit;
  B. behaviour on synthetic rows: the real readers (``lesson_outcome_quality.db_lookups`` and
     ``sector_momentum_engine._closes``) go through SQLite — the predicate is plain SQL — and the
     negative control shows the same fixture serving the yfinance close when the predicate is
     neutralised, so the exclusion is caused by the predicate and not by the fixture.

No database, no network, no credential: rows live in an in-memory SQLite table.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import lib.lesson_outcome_quality as lesson_quality  # noqa: E402
import sector_momentum_engine  # noqa: E402
from lib.price_provenance import sql_source_allowed  # noqa: E402

BASELINE_PATH = ROOT / "config" / "ticker_price_reader_baseline.json"

#: A statement is "about" the table only when the table name appears as a table reference — plain
#: mentions in prose, identifiers and file names are not statements.
TABLE_REF = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE)\s+ticker_prices\b", re.I)
SQL_KEYWORD = re.compile(r"\b(SELECT|INSERT\s+INTO|DELETE\s+FROM)\b", re.I)

#: Any one of these in the enclosing statement is a recognised source constraint. ``_SRC_P`` is
#: catalyst_calibration's module constant bound to ``sql_source_allowed("p")``; the other three are
#: pre-existing constraints written before the shared module existed.
ACCEPTED_CONSTRAINTS = (
    "sql_source_allowed",
    "_SRC_P",
    "source NOT ILIKE 'yfinance",
    "source = 'finviz'",
    "source='finviz'",
    "source = ANY(",
    "source=ANY(",
)

#: The sites the ticket names, plus the two files its evidence pass named. Asserted by name so a
#: regression reports the reader, not just a hash.
TICKET_READERS = (
    "scripts/sector_momentum_engine.py",
    "scripts/price_db_sync.py",
    "scripts/materialize_watchlist_strategy_cards.py",
    "scripts/defense_cash_alternatives.py",
)


# ---------------------------------------------------------------------------------------------
# A. static scan
# ---------------------------------------------------------------------------------------------

def _normalise(text: str) -> str:
    return " ".join(text.split())


def _docstring_ids(tree: ast.AST) -> set[int]:
    """Constants that are docstrings. Prose that mentions the table is not a statement."""
    ids: set[int] = set()
    owners = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if isinstance(node, owners) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                ids.add(id(first.value))
    return ids


def _sql_sites(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if "ticker_prices" not in text:
        return []
    tree = ast.parse(text, filename=str(path))
    docstrings = _docstring_ids(tree)
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    sites = []
    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if not TABLE_REF.search(node.value) or not SQL_KEYWORD.search(node.value):
            continue
        statement = node
        while id(statement) in parents and not isinstance(statement, ast.stmt):
            statement = parents[id(statement)]
        segment = _normalise(ast.get_source_segment(text, statement) or "")
        sites.append({
            "file": str(path.relative_to(ROOT)),
            "line": node.lineno,
            "hash": _hash(_normalise(node.value)),
            "filtered": any(marker in segment for marker in ACCEPTED_CONSTRAINTS),
            "sql": _normalise(node.value)[:120],
        })
    return sites


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _all_sites() -> list[dict]:
    sites: list[dict] = []
    for path in sorted((ROOT / "scripts").rglob("*.py")):
        if "/archive/" in path.as_posix():
            continue
        sites.extend(_sql_sites(path))
    return sites


def _baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_the_scan_sees_the_table_at_all() -> None:
    """A scan that finds nothing must fail loudly, not pass vacuously."""
    assert TABLE_REF.search("SELECT x FROM ticker_prices WHERE 1=1")
    assert not TABLE_REF.search("ticker_prices rows were stale")
    candidates = _all_sites()
    assert sum(1 for s in candidates if s["filtered"]) >= 25, "no filtered statement found"
    assert sum(1 for s in candidates if not s["filtered"]) >= 1, "no unfiltered site found"


def test_no_unlisted_statement_reads_ticker_prices_without_a_source_filter() -> None:
    listed = {(e["file"], e["hash"]) for e in _baseline()["entries"]}
    unlisted = [s for s in _all_sites() if not s["filtered"] and (s["file"], s["hash"]) not in listed]
    assert not unlisted, (
        "SQL over ticker_prices without sql_source_allowed(); add the predicate, or record it in "
        f"config/ticker_price_reader_baseline.json with a kind and a reason:\n{unlisted}"
    )


def test_every_baseline_entry_still_describes_a_live_unfiltered_statement() -> None:
    """Shrink-only: an entry that gained the predicate (or vanished) must be deleted, not kept."""
    found = {(s["file"], s["hash"]) for s in _all_sites() if not s["filtered"]}
    stale = [e for e in _baseline()["entries"] if (e["file"], e["hash"]) not in found]
    assert not stale, (
        "baseline entries no longer match a live unfiltered statement — remove them (the baseline "
        f"may only shrink):\n{stale}"
    )


def test_baseline_entries_carry_a_documented_kind_and_a_reason() -> None:
    doc = _baseline()
    kinds = set(doc["kinds"])
    bad = [e for e in doc["entries"] if e.get("kind") not in kinds or len(e.get("reason", "")) < 40]
    assert not bad, bad


def test_the_readers_named_in_the_ticket_carry_the_predicate() -> None:
    for rel in TICKET_READERS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "sql_source_allowed" in text, f"{rel}: no source predicate imported or used"


def test_the_predicate_is_a_fixed_literal_per_alias() -> None:
    with pytest.raises(KeyError):
        sql_source_allowed("not-an-alias")
    for alias in ("source", "tp", "t", "p"):
        assert sql_source_allowed(alias) == sql_source_allowed(alias)
        assert "yfinance" in sql_source_allowed(alias)
        assert "COALESCE" in sql_source_allowed(alias)


# ---------------------------------------------------------------------------------------------
# B. behaviour on synthetic rows (SQLite: the predicate is plain SQL)
# ---------------------------------------------------------------------------------------------

TODAY = date.today()
YF_DATE = (TODAY - timedelta(days=10)).isoformat()   # the stale row that must never be served
FV_DATE = (TODAY - timedelta(days=2)).isoformat()

ROWS = [
    # a symbol with a fresh allowed row AND an older banned one: the allowed row is served
    ("ZZTEST1", YF_DATE, 999.0, "yfinance", YF_DATE),
    ("ZZTEST1", FV_DATE, 5.0, "finviz", FV_DATE),
    # a symbol whose ONLY row is banned: nothing may be served (this is the defect)
    ("ZZTEST2", YF_DATE, 42.0, "yfinance_eod", YF_DATE),
    # a row with no recorded source is unknown, not known-bad: still served
    ("ZZTEST3", YF_DATE, 7.0, None, YF_DATE),
]


def _translate(sql: str, params) -> tuple[str, list]:
    """The two PostgreSQL spellings the readers use, expressed in SQLite."""
    params = list(params)
    while "= ANY(%s)" in sql:
        at = sql.index("= ANY(%s)")
        index = sql[:at].count("%s")
        values = list(params[index])
        sql = sql[:at] + "IN (" + ",".join(["%s"] * len(values)) + ")" + sql[at + len("= ANY(%s)"):]
        params = params[:index] + values + params[index + 1:]
    sql = sql.replace("CURRENT_DATE - %s", "date('now', '-' || %s || ' days')")
    return sql.replace("%s", "?"), params


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ticker_prices (symbol TEXT, price_date TEXT, close_price REAL, "
                 "source TEXT, created_at TEXT)")
    conn.executemany("INSERT INTO ticker_prices VALUES (?,?,?,?,?)", ROWS)
    return conn


class _Cursor:
    """``db_lookups`` / ``_closes`` cursors: execute(sql, params), fetchone/fetchall as tuples."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._result = None

    def execute(self, sql: str, params=()) -> None:
        translated, values = _translate(sql, params)
        self._result = self._conn.execute(translated, values)

    def fetchone(self):
        return self._result.fetchone()

    def fetchall(self):
        return self._result.fetchall()

    def close(self) -> None:  # pragma: no cover - symmetry with psycopg cursors
        pass


def _query(conn: sqlite3.Connection):
    """A ``_db_query``-style callable returning dict rows, as lesson_outcome_quality expects."""

    def query(sql: str, params=(), *, fetch: str = "one"):
        translated, values = _translate(sql, params)
        cursor = conn.execute(translated, values)
        names = [d[0] for d in cursor.description]

        def as_dict(row):
            return dict(zip(names, row))

        if fetch == "one":
            row = cursor.fetchone()
            return as_dict(row) if row else None
        return [as_dict(row) for row in cursor.fetchall()]

    return query


def test_price_on_skips_a_banned_close_and_keeps_an_unknown_source() -> None:
    price_on = lesson_quality.db_lookups(_query(_conn()))[0]
    assert price_on("ZZTEST1", TODAY.isoformat()) == 5.0       # finviz, not the yfinance 999
    assert price_on("ZZTEST2", TODAY.isoformat()) is None      # the only row is banned
    assert price_on("ZZTEST3", TODAY.isoformat()) == 7.0       # NULL source is unknown, not banned


def test_sector_momentum_closes_skip_a_banned_close() -> None:
    closes = sector_momentum_engine._closes(_Cursor(_conn()), ["ZZTEST1", "ZZTEST2"], days=90)
    assert [px for _d, px in closes.get("ZZTEST1", [])] == [5.0]
    assert "ZZTEST2" not in closes or closes["ZZTEST2"] == []


def test_the_same_fixture_serves_the_banned_close_without_the_predicate(monkeypatch) -> None:
    """Negative control: the exclusion comes from the predicate, not from the fixture rows."""
    neutral = lambda alias="source": "1=1"  # noqa: E731
    monkeypatch.setattr(lesson_quality, "sql_source_allowed", neutral)
    monkeypatch.setattr(sector_momentum_engine, "sql_source_allowed", neutral)

    price_on = lesson_quality.db_lookups(_query(_conn()))[0]
    assert price_on("ZZTEST2", TODAY.isoformat()) == 42.0
    closes = sector_momentum_engine._closes(_Cursor(_conn()), ["ZZTEST2"], days=90)
    assert [px for _d, px in closes["ZZTEST2"]] == [42.0]


def test_daily_bars_last_close_statement_is_filtered_before_its_ordering() -> None:
    """``LAST_CLOSE_SQL`` is a module constant built at import; assert its shape in the source."""
    text = (ROOT / "scripts" / "lib" / "data_broker" / "daily_bars.py").read_text(encoding="utf-8")
    start = text.index("LAST_CLOSE_SQL = ")
    segment = text[start:text.index("\n\n", start)]
    assert "sql_source_allowed()" in segment
    assert segment.index("sql_source_allowed()") < segment.index("ORDER BY price_date DESC")


def test_every_banned_source_is_excluded_by_the_predicate_itself() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ticker_prices (source TEXT)")
    conn.executemany("INSERT INTO ticker_prices VALUES (?)",
                     [("yfinance",), ("yfinance_eod",), ("yahoo",), ("yahoo_finance",),
                      ("finviz",), ("alpaca",), (None,)])
    kept = [r[0] for r in conn.execute(
        "SELECT source FROM ticker_prices WHERE " + sql_source_allowed())]
    assert kept == ["finviz", "alpaca", None]
