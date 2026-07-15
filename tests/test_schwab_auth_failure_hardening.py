#!/usr/bin/env python3
"""Schwab auth-failure hardening — immediate degrade, staggered crons, transport wiring."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TRANSPORT_SRC = (ROOT / "scripts" / "schwab_transport.py").read_text()
INGEST_SRC = (ROOT / "scripts" / "schwab_transaction_ingest.py").read_text()
SYNC_SRC = (ROOT / "scripts" / "schwab_position_sync.py").read_text()
TOKEN_SRC = (ROOT / "scripts" / "schwab_token_manager.py").read_text()


def test_record_auth_failure_exists_with_alert_gate():
    assert "def record_auth_failure(" in TOKEN_SRC
    assert "auth_failure_alert" in TOKEN_SRC
    assert "interval '4 hours'" in TOKEN_SRC


def test_transport_read_records_auth_failure():
    block = TRANSPORT_SRC[TRANSPORT_SRC.index("def _read"):TRANSPORT_SRC.index("def get_account")]
    assert "record_auth_failure" in block
    assert "is_auth_failure(err)" in block


def test_position_sync_records_auth_failure():
    assert "record_auth_failure" in SYNC_SRC
    assert "schwab_position_sync" in SYNC_SRC


def test_ingest_records_auth_failure_on_exception():
    assert "schwab_transaction_ingest:get_transactions" in INGEST_SRC
    assert "is_auth_failure(err)" in INGEST_SRC


def test_record_auth_failure_marks_degraded_and_alerts_once():
    import schwab_token_manager as stm

    class _Cur:
        def __init__(self):
            self._select = False
        def execute(self, *a, **k):
            self._sql = a[0] if a else ""
            self._select = "auth_failure_alert" in self._sql
        def fetchone(self):
            return None if self._select else None

    class _Conn:
        def cursor(self):
            return _Cur()
        def commit(self):
            pass

    with mock.patch.object(stm, "canonical_token_key", return_value="schwab_taxable"), \
         mock.patch.object(stm, "mark_degraded") as md, \
         mock.patch.object(stm, "_conn", return_value=_Conn()), \
         mock.patch.object(stm, "_telegram") as tg, \
         mock.patch.object(stm, "_audit"):
        stm.record_auth_failure("invalid_grant: token revoked", source="test")
    md.assert_called_once()
    tg.assert_called_once()