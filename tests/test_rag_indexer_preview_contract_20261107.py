"""``rag_indexer --dry-run`` is an offline preview, and the file must say so (2026-11-07).

1c733d98f made the CLI preview offline: it prints one ``DRY-RUN`` line and returns 0 before any DB
connection. It left the pre-stub dry-run machinery in ``main()`` — ``enforce_readonly(conn)``,
``dry_run=args.dry_run``, ``dry_run_report(...)`` and the ``if not args.dry_run`` receipt guard — all of
which became unreachable, and the module docstring kept describing that older, DB-backed rehearsal
("selects the rows and builds the embed texts ... prints the RAG_INDEXER_SUMMARY line (dry_run=true)").
A reader who trusts the docstring believes a preview counts rows; it cannot, because counting needs the
database the preview refuses to open.

This file pins the contract in the direction that fails loudly:

* behaviour — ``main(["--dry-run"])`` opens no connection, calls no indexer, touches no receipt library,
  prints one ``DRY-RUN`` line and no ``RAG_INDEXER_SUMMARY`` line, and leaves the state root empty;
* structure — ``main()`` carries none of the unreachable branches, and its preview return precedes the
  connection attempt, so re-adding one fails here rather than silently never running again;
* the docstring — it calls the preview offline and says it cannot report row counts, rather than
  promising row selection and the summary line;
* the library-level preview is still real and still used: ``index_source(dry_run=True)`` over a fake
  connection counts rows and writes/embeds nothing. That is the capability the CLI preview does not
  take; it is why the parameter stays.

Hermetic: a fake connection, a synthetic state root, no network, no crontab, no live persistent state.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import rag_indexer  # noqa: E402


class _FakeCursor:
    def __init__(self, conn: "_FakeConn"):
        self._conn = conn

    def execute(self, sql, params=()):
        self._conn.statements.append(" ".join(str(sql).split()))

    def fetchall(self):
        return list(self._conn.rows)

    def fetchone(self):
        return (0,)

    def close(self):
        self._conn.closed_cursors += 1


class _FakeConn:
    """Records every statement and commit; ``rows`` is what the indexer's SELECT returns."""

    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements: list[str] = []
        self.commits = 0
        self.closed_cursors = 0

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        pass

    def writes(self):
        return [s for s in self.statements if s.upper().startswith(("INSERT", "UPDATE", "DELETE"))]


# ── the CLI preview ─────────────────────────────────────────────────────────────────────────────


def test_a_cli_preview_touches_no_connection_no_indexer_no_receipt_and_prints_one_line(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))

    def _refuse(*_args, **_kwargs):
        raise AssertionError("the offline preview reached a run-time dependency")

    monkeypatch.setattr(rag_indexer, "_get_conn", _refuse)
    monkeypatch.setattr(rag_indexer, "index_source", _refuse)
    monkeypatch.setattr(rag_indexer, "_receipt_lib", _refuse)

    assert rag_indexer.main(["--dry-run", "--source", "news", "--hours", "4"]) == 0

    out = capsys.readouterr().out
    assert out.count("DRY-RUN") == 1
    assert "would index sources=news hours=4 backfill=False" in out
    # A preview reports no counts: counting needs the DB, and that line is what a real run prints.
    assert "RAG_INDEXER_SUMMARY" not in out
    assert list(tmp_path.rglob("*")) == []


def test_main_carries_no_unreachable_dry_run_branch():
    src = inspect.getsource(rag_indexer.main)
    # The preview returns before the connection is attempted, so nothing after it can be a dry-run path.
    assert src.index("if args.dry_run:") < src.index("_get_conn()")
    for dead in ("enforce_readonly", "dry_run_report", "dry_run=args.dry_run", "if not args.dry_run"):
        assert dead not in src, f"main() still carries the unreachable dry-run branch {dead!r}"


def test_the_docstring_states_the_offline_contract():
    doc = rag_indexer.__doc__ or ""
    assert "OFFLINE PREVIEW" in doc
    assert "cannot report row counts" in doc
    # The claims the code cannot honour: a preview prints no summary line and runs no read-only session.
    assert "dry_run=true" not in doc
    assert "enforce_readonly" not in doc
    # The library preview is named as a library path, not implied to be what --dry-run does.
    assert "main() never reaches it" in doc


# ── the library preview that remains ────────────────────────────────────────────────────────────


def test_index_source_dry_run_counts_rows_without_embedding_or_writing(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    conn = _FakeConn(
        [
            (1, "AAPL shares rise", "AAPL shares rise", "2026-11-07"),
            (2, "MSFT earns", "MSFT earns", "2026-11-07"),
        ]
    )
    monkeypatch.setattr(
        rag_indexer, "embed_text", lambda _t: (_ for _ in ()).throw(AssertionError("a preview embedded"))
    )

    stats: dict = {}
    indexed, _skipped = rag_indexer.index_source("news", conn=conn, dry_run=True, stats=stats)

    assert indexed == 2
    assert stats["selected"] == 2
    assert [s["title"] for s in stats["samples"]] == ["AAPL shares rise", "MSFT earns"]
    assert conn.writes() == []
    assert conn.commits == 0
    assert not list(tmp_path.rglob("*"))
