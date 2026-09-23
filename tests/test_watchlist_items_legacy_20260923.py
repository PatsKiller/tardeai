"""Legacy (symbol, source_type) watchlist_items helpers against the CURRENT schema.

watchlist_items has no source_type/thesis/target_intent/added_date columns, so
load/save/remove_watchlist_item raised a SQL error on every call (~3,183 logged) and
the orchestrator's AI-candidate step wrote nothing. Operator decision 2026-09-23: fix the
read, retire the writers loudly, keep the producer dead.

Hermetic: db_adapter._execute is monkeypatched; no database is touched.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import db_adapter  # noqa: E402

# Columns of public.watchlist_items that the read relies on (measured 2026-09-23).
REAL_COLUMNS = {"symbol", "source", "status", "origin_detail", "source_payload", "first_seen_at", "updated_at"}
DEAD_COLUMNS = {"source_type", "thesis", "target_intent", "added_date", "added_by", "confidence", "notes", "data"}


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake_execute(sql, params=None, fetch=None):
        seen.append((sql, params))
        return [{"symbol": "S", "source_type": "ai_discovered", "status": "active", "thesis": "directive:Watchlist"}]

    monkeypatch.setattr(db_adapter, "USE_DB", True)
    monkeypatch.setattr(db_adapter, "_execute", fake_execute)
    return seen


def _referenced_columns(sql: str) -> set[str]:
    """Bare column identifiers the query reads (aliases after AS and JSON keys excluded)."""
    sql = re.sub(r"'[^']*'|%s", "", sql)  # drop string literals (JSON keys) and placeholders
    sql = re.sub(r"\bAS\s+\w+", "", sql, flags=re.I)  # drop aliases
    words = set(re.findall(r"\b[a-z_]+\b", sql))
    keywords = {"select", "from", "where", "and", "order", "by", "desc", "nulls", "last", "watchlist_items"}
    return words - keywords


def test_load_reads_only_real_columns(calls):
    db_adapter.load_watchlist_items(source_type="ai_discovered", status="active")
    (sql, params) = calls[0]
    cols = _referenced_columns(sql)
    assert cols <= REAL_COLUMNS, f"unknown columns: {cols - REAL_COLUMNS}"
    assert not (cols & DEAD_COLUMNS)
    assert params == ["active", "ai_discovered"]


def test_load_without_source_filters_status_only(calls):
    db_adapter.load_watchlist_items(status="active")
    assert calls[0][1] == ["active"]


def test_load_keeps_legacy_source_type_key(calls):
    (row,) = db_adapter.load_watchlist_items(source_type="ai_discovered")
    assert row["source_type"] == "ai_discovered"
    assert row["symbol"] == "S"


def test_load_returns_empty_without_db(monkeypatch):
    monkeypatch.setattr(db_adapter, "USE_DB", False)
    assert db_adapter.load_watchlist_items(source_type="ai_generated") == []


@pytest.mark.parametrize(
    "call",
    [
        lambda: db_adapter.save_watchlist_item({"symbol": "S", "source_type": "ai_generated"}),
        lambda: db_adapter.remove_watchlist_item("S", "ai_generated"),
    ],
)
def test_legacy_writers_are_retired_loudly_and_never_write(calls, capsys, call):
    call()
    assert calls == [], "a retired writer must not issue SQL"
    out = capsys.readouterr().out
    assert "RETIRED watchlist_items legacy writer" in out
    assert "symbol=S" in out
