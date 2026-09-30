"""Terminal settlement for SUPPRESSED / EXPIRED / CANCELLED deliveries, outbox status advance,
and CIO desk send receipts with Telegram message ids (2026-09-30).

Measured (read-only) 2026-09-30: 7,158 of 7,366 UNSETTLED events in 7 days were SUPPRESSED
deliveries; every communication_outbox row was still 'recorded'; cio_telegram_receipts.jsonl had
not been written since 2026-08-30, so the 09-28 10:20 AXTI alert had no message id on record."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.comms import delivery as dl  # noqa: E402


class _Cur:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        if self.conn.fail_check_once and "communication_events" in sql and params and params[2] in ("SUPPRESSED", "WITHDRAWN"):
            self.conn.fail_check_once = False
            raise Exception('new row for relation "communication_events" violates check constraint '
                            '"communication_events_settlement_state_ck"')
        self.conn.statements.append((" ".join(sql.split()), params))


class _Conn:
    def __init__(self, fail_check_once=False):
        self.statements = []
        self.fail_check_once = fail_check_once
        self.committed = 0
        self.rolled_back = 0

    def cursor(self):
        return _Cur(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        pass


def test_settlement_mapping_is_total_for_terminal_statuses():
    assert dl.settlement_state_for("SENT", "m1") == "SETTLED"
    assert dl.settlement_state_for("SENT", None) is None           # no provider id -> not settled
    assert dl.settlement_state_for("FAILED", None) == "FAILED"
    assert dl.settlement_state_for("LEGACY_DELIVERED", None) == "UNKNOWN_LEGACY"
    assert dl.settlement_state_for("SUPPRESSED", None) == "SUPPRESSED"
    assert dl.settlement_state_for("EXPIRED", None) == "WITHDRAWN"
    assert dl.settlement_state_for("CANCELLED", None) == "WITHDRAWN"
    assert dl.settlement_state_for("RESERVED", None) is None and dl.settlement_state_for("SENDING", None) is None
    terminal = {s for s, nxt in dl._TRANSITIONS.items() if not (nxt - {"UNKNOWN"})} | {"SENT", "LEGACY_DELIVERED"}
    unmapped = {s for s in terminal if dl.settlement_state_for(s, "m1") is None and s != "UNKNOWN"}
    assert not unmapped, unmapped


def test_suppressed_settles_and_the_outbox_row_advances(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr("db_adapter._get_conn", lambda: conn)
    dl._persist_event_settlement_pg("evt-9", status="SUPPRESSED", provider_message_id=None, settled_at=None,
                                    delivery_owner="legacy", channel="telegram")
    ev = [p for s, p in conn.statements if "UPDATE communication_events" in s][0]
    ob = [p for s, p in conn.statements if "UPDATE communication_outbox" in s][0]
    assert ev[2] == "SUPPRESSED" and ev[1] is not None and ev[3] == "legacy"
    assert ob[0] == "suppressed" and ob[2] == "evt-9" and ob[3] == "telegram"
    assert conn.committed == 1


def test_pre_migration_database_keeps_the_other_stamps(monkeypatch):
    conn = _Conn(fail_check_once=True)
    monkeypatch.setattr("db_adapter._get_conn", lambda: conn)
    dl._persist_event_settlement_pg("evt-7", status="SUPPRESSED", provider_message_id=None, settled_at=None,
                                    delivery_owner="legacy", channel="telegram")
    ev = [p for s, p in conn.statements if "UPDATE communication_events" in s]
    assert conn.rolled_back == 1 and len(ev) == 1 and ev[0][2] is None and ev[0][3] == "legacy"
    assert [p for s, p in conn.statements if "UPDATE communication_outbox" in s]
    assert conn.committed == 1


def test_sent_with_id_settles_and_counts_an_attempt(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr("db_adapter._get_conn", lambda: conn)
    dl._persist_event_settlement_pg("evt-1", status="SENT", provider_message_id="tg-42", settled_at=None, channel="telegram")
    ev = [p for s, p in conn.statements if "UPDATE communication_events" in s][0]
    ob = [(s, p) for s, p in conn.statements if "UPDATE communication_outbox" in s][0]
    assert ev[0] == "tg-42" and ev[2] == "SETTLED"
    assert ob[1][0] == "sent" and "attempt_count + CASE" in ob[0]


def test_migration_extends_the_check_and_down_restores_it():
    up = (ROOT / "migrations" / "2026_09_30_comms_settlement_terminal_states.sql").read_text(encoding="utf-8")
    down = (ROOT / "migrations" / "2026_09_30_comms_settlement_terminal_states.down.sql").read_text(encoding="utf-8")
    assert "'SUPPRESSED','WITHDRAWN'" in up and "NOT VALID" in up
    assert "'UNKNOWN_LEGACY'))" in down and "SET provider_settlement_state = 'UNSETTLED'" in down
    from scripts.lib import campaign_interfaces as ci
    assert {"SUPPRESSED", "WITHDRAWN"} <= ci.PROVIDER_SETTLEMENT_STATES


def test_cio_send_writes_a_receipt_with_message_refs(monkeypatch, tmp_path):
    from scripts.lib import cio_telegram_transport as tt
    receipts = tmp_path / "cio_telegram_receipts.jsonl"
    monkeypatch.setenv("CIO_TELEGRAM_RECEIPT_PATH", str(receipts))
    monkeypatch.setattr("scripts.lib.cio_production_eligibility.guard_test_cio_write", lambda p: Path(p))
    tt._append_send_receipt({"delivered": True, "dedupe_key": "cio_entry:AXTI:ENTRY_NEAR:2026-09-28",
                             "message_ids": [4321], "message_refs": [{"chat_ref": tt._chat_ref(780672608), "message_id": 4321}],
                             "reason": "sent"}, kind="cio_advisory", decision_id=None)
    tt._append_send_receipt({"delivered": False, "dedupe_key": "k2", "reason": "send_failed", "errors": ["chat=x:status=400"]},
                            kind="cio_advisory", decision_id=None)
    rows = [json.loads(line) for line in receipts.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["ok"] is True and rows[0]["message_ids"] == [4321] and rows[0]["dedupe_key"].startswith("cio_entry:AXTI")
    assert rows[0]["message_refs"][0]["chat_ref"] == tt._chat_ref(780672608) and "780672608" not in json.dumps(rows[0])
    assert rows[1]["ok"] is False and rows[1]["status"] == "failed" and rows[1]["delivered_at"] is None


def test_receipt_failure_never_changes_the_send(monkeypatch):
    from scripts.lib import cio_telegram_transport as tt
    monkeypatch.setenv("CIO_TELEGRAM_RECEIPT_PATH", "/proc/definitely/not/writable.jsonl")
    monkeypatch.setattr("scripts.lib.cio_production_eligibility.guard_test_cio_write", lambda p: Path(p))
    tt._append_send_receipt({"delivered": True, "message_ids": [1]}, kind="k", decision_id=None)   # no raise


def test_entry_state_runner_keeps_message_refs():
    import ast
    src = (ROOT / "scripts" / "cio_entry_state_runner.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "send_alerts")
    body = ast.get_source_segment(src, fn)
    assert 'out["cio_desk_message_refs"] = r.get("message_refs")' in body and 'out["cio_desk_dedupe_key"]' in body
