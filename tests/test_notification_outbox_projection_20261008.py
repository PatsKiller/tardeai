"""Roadmap Phase 2 PR-A (2026-10-08): read-only projection of send state and its incident fan-in source.
Hermetic: stubbed DB rows, no connection, no sends, no token store."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import notification_outbox_projection as P  # noqa: E402

NOW = datetime(2026, 10, 8, 1, 0, tzinfo=timezone.utc)


def _rows(comm, tg):
    def q(sql, params):
        assert "now() - make_interval" in sql and params[0] == 24
        return comm if sql.startswith("SELECT outbox_id") else tg
    return q


def test_projection_counts_per_outbox_and_state_and_filters_items_only():
    comm = [
        (1, "evt-a", "telegram", "sent", 1, None, NOW - timedelta(minutes=5), NOW),
        (2, "evt-b", "telegram", "suppressed", 0, "dedupe:same_subject", NOW - timedelta(minutes=9), NOW),
        (3, "evt-c", "email", "withdrawn", 1, "operator_withdrew", NOW - timedelta(minutes=40), NOW),
    ]
    tg = [(7, NOW - timedelta(minutes=2), "morning_brief", "Brief", 1200, True, "operator"),
          (8, NOW - timedelta(minutes=3), "alert", "Alert", 5000, False, "operator")]
    m = P.project_outbox(_rows(comm, tg), hours=24, now=NOW)
    assert m["schema"] == "NotificationOutboxProjection@v1" and m["status"] == "OK" and m["total"] == 5
    assert m["counts"] == {"communication_outbox": {"sent": 1, "suppressed": 1, "withdrawn": 1},
                           "telegram_outbox": {"sent": 1, "failed": 1}}
    assert m["items"][0]["id"] == "7" and m["items"][0]["age_min"] == 2.0
    only = P.project_outbox(_rows(comm, tg), hours=24, now=NOW, state="suppressed")
    assert only["count"] == 1 and only["items"][0]["reason"] == "dedupe:same_subject" and only["total"] == 5


def test_anomalies_name_withdrawn_stuck_pending_and_silent_senders():
    comm = [(i, f"evt-{i}", "telegram", "suppressed", 0, "dedupe", NOW - timedelta(minutes=i), NOW) for i in range(1, 21)]
    comm += [(90, "evt-w", "email", "withdrawn", 1, "operator_withdrew", NOW - timedelta(minutes=12), NOW),
             (91, "evt-p", "telegram", "queued", 0, None, NOW - timedelta(minutes=45), NOW),
             (92, "evt-q", "telegram", "queued", 0, None, NOW - timedelta(minutes=5), NOW),
             (93, "evt-r", "telegram", "recorded", 0, None, NOW - timedelta(hours=30), NOW)]   # terminal, never "stuck"
    m = P.project_outbox(_rows(comm, []), hours=24, now=NOW)
    found = P.anomalies(m)
    assert sorted(f["item"] for f in found) == ["silent_senders", "stuck_pending:communication_outbox:91",
                                                 "withdrawn:communication_outbox:90"]
    assert all(f["severity"] == "P2" for f in found)
    # one send in the window and the senders are not silent; suppression alone is never a finding
    comm.append((94, "evt-s", "telegram", "sent", 1, None, NOW - timedelta(minutes=1), NOW))
    items = [f["item"] for f in P.anomalies(P.project_outbox(_rows(comm, []), hours=24, now=NOW))]
    assert "silent_senders" not in items and len(items) == 2


def test_quiet_window_has_no_anomalies():
    comm = [(1, "evt-a", "telegram", "sent", 1, None, NOW - timedelta(minutes=5), NOW)]
    assert P.anomalies(P.project_outbox(_rows(comm, []), hours=24, now=NOW)) == []


def test_live_loader_without_a_database_is_unavailable_not_an_exception(monkeypatch):
    monkeypatch.delenv("DB_PASSWORD", raising=False)
    monkeypatch.delenv("TRADEAI_OUTBOX_PROJECTION", raising=False)
    quiet = P.load_outbox(hours=24, now=NOW)
    assert quiet["status"] == "UNAVAILABLE" and quiet["note"].startswith("no_db_env")

    def boom(timeout_s=3.0):
        raise RuntimeError("no_db_connection")
    monkeypatch.setenv("DB_PASSWORD", "unit-test-not-a-secret")
    monkeypatch.setattr(P, "db_query_with_timeout", boom)
    m = P.load_outbox(hours=24, now=NOW)
    assert m["status"] == "UNAVAILABLE" and m["items"] == [] and "no_db_connection" in m["note"]
    monkeypatch.setenv("TRADEAI_OUTBOX_PROJECTION", "0")
    assert P.load_outbox(hours=24, now=NOW)["status"] == "DISABLED"


def test_fanin_source_is_fail_soft_and_records_its_status(monkeypatch):
    monkeypatch.setattr(P, "load_outbox", lambda **kw: {"status": "UNAVAILABLE", "note": "RuntimeError: no_db_connection", "total": 0, "items": []})
    assert fanin._outbox_findings(NOW) == []
    assert fanin.OUTBOX_SOURCE_STATUS["status"] == "UNAVAILABLE"
    comm = [(90, "evt-w", "email", "withdrawn", 1, "operator_withdrew", NOW - timedelta(minutes=12), NOW)]
    monkeypatch.setattr(P, "load_outbox", lambda **kw: P.project_outbox(_rows(comm, []), hours=24, now=NOW))
    found = fanin._outbox_findings(NOW)
    assert [f["item"] for f in found] == ["withdrawn:communication_outbox:90"]
    assert found[0]["store"] == "data/runtime" and found[0]["artifact_rel"].endswith("n8n_incident_fanin_last.json")
    ev = fanin.build_event(found[0], day="2026-10-08", now=NOW, sha="a" * 40)
    assert ev["lane_id"] == fanin.LANE and ev["idempotency_key"] == fanin.idem_key(found[0], "2026-10-08")
    assert ev["subject_key"].startswith("sev=P2;src=outbox;item=withdrawn:")


def test_fanin_source_block_sits_before_the_lab_backup_block_and_receipt_carries_status():
    src = (ROOT / "scripts" / "n8n_incident_fanin.py").read_text(encoding="utf-8")
    assert src.index("out.extend(_outbox_findings(now))") < src.index('doc = _load(root / "backups" / "n8n" / "n8n_lab_backup_last.json")')
    assert '"outbox_source": OUTBOX_SOURCE_STATUS' in src


def test_api_route_calls_the_projection_read_only():
    src = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    i = src.index('base_path == "/api/v2/coordination/outbox"')
    block = src[i:i + 600]
    assert "notification_outbox_projection import load_outbox" in block
    assert "INSERT" not in block and "UPDATE" not in block and "send_telegram" not in block
