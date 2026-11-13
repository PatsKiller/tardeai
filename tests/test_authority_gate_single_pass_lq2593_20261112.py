"""LQ-20261107-2593 -- check_data_source_authority took 120 s of CPU (numbers-truth-audit RUN_TIMEOUT 124).

count_writers re-read and re-regexed every source file once per declared table. Synthetic files only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
gate = pytest.importorskip("check_data_source_authority")

TABLES = ["orders", "order_items", "pos", "pos.hist", "Quotes", "a.b.c", "a"]
SOURCES = {
    "w1.py": "cur.execute('INSERT INTO orders (a) VALUES (1)')",
    "w2.py": "UPDATE order_items SET x=1; update ORDERS set y=2",
    "w3.py": "COPY pos.hist FROM stdin",
    "w4.py": "INSERT   INTO\n  quotes(a)",
    "w5.py": "UPDATE orders_archive SET z=1",          # word boundary: not 'orders'
    "w6.py": "UPDATE a.b.c SET q=1",                  # satisfies a, a.b.c
    "w7.py": "SELECT * FROM orders",                  # a read, not a write
    "w8.py": "INSERT INTO pos.hist x; UPDATE pos SET y",
    "w9.py": "",
}


def _old(auth, files):
    out = {}
    for d in auth["domains"]:
        table = (d.get("store") or {}).get("table")
        if not table:
            continue
        pat = re.compile(rf"\b(INSERT\s+INTO|UPDATE|COPY)\s+{re.escape(table)}\b", re.I)
        out[table] = sum(1 for p in files if pat.search(p.read_text()))
    return out


@pytest.fixture
def tree(tmp_path):
    files = []
    for n, t in SOURCES.items():
        p = tmp_path / n
        p.write_text(t)
        files.append(p)
    auth = {"domains": [{"domain": t, "store": {"table": t}} for t in TABLES] + [{"domain": "nostore"}]}
    return auth, files


def test_count_writers_equals_the_per_table_reference(tree):
    auth, files = tree
    assert gate.count_writers(auth, files) == _old(auth, files)


def test_each_file_is_read_once_not_once_per_table(tree, monkeypatch):
    auth, files = tree
    reads = []
    gate._TEXT_CACHE = {}
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: reads.append(self.name) or real(self, *a, **k))
    try:
        gate.count_writers(auth, files)
    finally:
        gate._TEXT_CACHE = None
    assert sorted(reads) == sorted(p.name for p in files)


def test_a_file_shared_with_the_reader_check_is_not_reread(tree, monkeypatch):
    auth, files = tree
    gate._TEXT_CACHE = {}
    try:
        gate.count_writers(auth, files)
        monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(AssertionError("reread")))
        assert gate._text(files[0]) is not None
    finally:
        gate._TEXT_CACHE = None


@pytest.mark.parametrize("text,tables,want", [
    ("SELECT * FROM positions_store p", ["positions_store"], True),
    ("select 1 from positions_store_x", ["positions_store"], False),   # \b after the table
    ("JOIN   a_t ON", ["x", "a_t"], True),
    ("FROM other", ["x", "a_t"], False),
    ("FROM a", [], False),
    ("select * from positions_store", ["positions_store"], True),      # G1: lower case
    ("join Positions_Store x", ["positions_store"], True),
])
def test_reads_table_matches_any_of_the_tables(text, tables, want):
    assert gate._reads_table(text, tables) is want


def test_a_rewritten_file_is_reread_in_the_same_process(tmp_path):
    """C1: a long-lived caller (portfolio_server) must not be served the first call's text."""
    f = tmp_path / "w.py"
    f.write_text("INSERT INTO zz_tbl VALUES (1)")
    auth = {"domains": [{"store": {"table": "zz_tbl"}}]}
    assert gate.count_writers(auth, [f]) == {"zz_tbl": 1}
    f.write_text("print('no longer writes')")
    assert gate.count_writers(auth, [f]) == {"zz_tbl": 0}
    assert not gate._TEXT_CACHE


def test_main_leaves_no_cache_behind_even_when_it_raises(monkeypatch):
    seen = {}

    def boom():
        seen["open"] = isinstance(gate._TEXT_CACHE, dict)
        raise RuntimeError("x")

    monkeypatch.setattr(gate, "_main", boom)
    with pytest.raises(RuntimeError):
        gate.main()
    assert seen["open"] is True and gate._TEXT_CACHE is None


def test_main_clears_the_cache_after_a_normal_return(monkeypatch):
    monkeypatch.setattr(gate, "_main", lambda: 0)
    assert gate.main() == 0 and gate._TEXT_CACHE is None


def test_an_unreadable_file_is_none_and_skipped(tmp_path):
    assert gate._text(tmp_path / "missing.py") is None
    assert gate.count_writers({"domains": [{"store": {"table": "t"}}]}, [tmp_path / "missing.py"]) == {"t": 0}
