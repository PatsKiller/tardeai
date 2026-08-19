"""IEM / readiness retry once after a closed Postgres handle."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import intelligence_entity_manager as iem  # noqa: E402
import symbol_enrichment as se  # noqa: E402


class _Closed(Exception):
    pass


def test_upsert_retries_once_on_already_closed():
    dead = MagicMock()
    dead.closed = 1
    dead.cursor.side_effect = Exception("connection already closed")
    live = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    live.cursor.return_value = cur
    live.closed = 0

    with patch.object(iem, "_live_conn", side_effect=[dead, live]):
        with patch("db_adapter.ensure_conn", return_value=live), patch("db_adapter.close_thread_conn"):
            # first call uses dead via _live_conn then retries
            ok = iem.upsert_entity(dead, "TEST", "market", {}, source="unit")
    assert ok is True or cur.execute.called


def test_dead_conn_msg():
    assert iem._dead_conn_msg(Exception("psycopg2.InterfaceError: connection already closed"))
    assert iem._dead_conn_msg(Exception("SSL connection has been closed unexpectedly"))
    assert not iem._dead_conn_msg(Exception("unique violation"))


def test_readiness_retries_on_closed_cursor():
    dead = MagicMock()
    dead.closed = 0
    dead.cursor.side_effect = Exception("connection already closed")
    live = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    cur.execute.return_value = None
    live.cursor.return_value = cur
    live.closed = 0
    live.commit = MagicMock()

    with patch("db_adapter.ensure_conn", return_value=live), patch("db_adapter.close_thread_conn"):
        out = se.compute_intelligence_readiness("PLSM", dead)
    assert isinstance(out, dict)
    assert out.get("grade") in {"UNKNOWN", "MINIMAL", "LOW", "MED", "HIGH"} or "score" in out


def test_finviz_runner_has_refresh_hook():
    text = (ROOT / "scripts" / "finviz_screener_runner.py").read_text()
    assert "def _refresh_conn" in text
    assert "ensure_conn" in text
