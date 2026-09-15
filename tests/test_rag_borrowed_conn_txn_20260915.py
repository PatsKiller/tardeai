"""R-09 (2026-09-15): RAG reads on a borrowed connection must not leave it idle in a transaction."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _stub(name, **attrs):
    if name not in sys.modules:
        try:
            __import__(name)
        except Exception:
            sys.modules[name] = types.SimpleNamespace(**attrs)


_stub("numpy")

import rag_retrieval as rag  # noqa: E402


@pytest.fixture(autouse=True)
def _psycopg2_extras(monkeypatch):
    """get_rag_context imports psycopg2.extras at call time; give it one regardless of other stubs."""
    extras = types.SimpleNamespace(RealDictCursor=object)
    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(extras=extras))
    monkeypatch.setitem(sys.modules, "psycopg2.extras", extras)


class _Cur:
    def execute(self, *a, **k):
        pass

    def fetchall(self):
        return []

    def close(self):
        pass


class _Conn:
    def __init__(self, status):
        self.status, self.rollbacks = status, 0

    def cursor(self, **kw):
        return _Cur()

    def get_transaction_status(self):
        return self.status

    def rollback(self):
        self.rollbacks += 1


def test_an_idle_borrowed_connection_is_returned_idle(monkeypatch):
    monkeypatch.setattr(rag, "embed_text", lambda t: [0.1, 0.2])
    monkeypatch.setattr(rag, "_keyword_fallback", lambda *a, **k: [])
    conn = _Conn(0)
    assert rag.get_rag_context("ACHV", conn=conn) == []
    assert conn.rollbacks == 1


def test_a_caller_transaction_in_progress_is_never_rolled_back(monkeypatch):
    monkeypatch.setattr(rag, "embed_text", lambda t: [0.1, 0.2])
    monkeypatch.setattr(rag, "_keyword_fallback", lambda *a, **k: [])
    conn = _Conn(2)  # TRANSACTION_STATUS_INTRANS: the caller has uncommitted work
    rag.get_rag_context("ACHV", conn=conn)
    assert conn.rollbacks == 0
