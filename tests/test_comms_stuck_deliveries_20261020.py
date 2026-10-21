"""Communications delivery-health strip: 205 RESERVED rows that nothing would ever settle (2026-10-20).

Measured 2026-10-20 on the live ledger (GET /api/v2/communications/deliveries/summary: unsettled 205, oldest
2026-10-12 13:30 ET). Every one of the 205 was a reservation that ``publish_communication`` minted for an event
that no sender owned:

* 150 INBOUND ``telegram_inbound`` events (the operator's own callbacks/commands). ``build_inbound_event`` leaves
  ``CommunicationEvent.channels`` at its dataclass default ``["telegram"]``, so the operator's message got an
  OUTBOUND delivery reservation.
* 55 OUTBOUND "shadow ledger" events (``send_watchpool_maturity_alerts`` 49, and one each from six other lanes).
  These producers send through ``send_telegram`` -- which records and settles its OWN event -- and then publish a
  second ``CommunicationEvent`` with no channels named. The default reserved a Telegram delivery for the copy, and
  the caller discards the result, so nobody ever holds the delivery id to settle it. Every one has a send_telegram
  twin delivery that did settle (3 SENT with a provider id, 52 SUPPRESSED).

The fix: a reservation is minted only for an event that asked for a channel -- never for an INBOUND event and never
for a channel the dataclass assumed -- and ``reap_stale_reservations`` settles a stale un-owned reservation to a
terminal status without any provider I/O (CANCELLED for inbound, EXPIRED for an outbound reservation nobody
claimed, UNKNOWN for a stale SENDING). Hermetic: in-memory ledger, the DB connection is never opened.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def mem(monkeypatch):
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)
    # settle_delivery's best-effort PG stamp must not reach a real database from a test (AGENTS.md §24.6).
    monkeypatch.setattr("scripts.lib.comms.delivery._persist_event_settlement_pg", lambda *a, **k: None)
    from scripts.lib.comms.client import reset_memory_store
    from scripts.lib.comms.delivery import reset_memory_deliveries

    reset_memory_store()
    reset_memory_deliveries()
    yield
    reset_memory_store()
    reset_memory_deliveries()


def _rows():
    from scripts.lib.comms.delivery import memory_delivery_snapshot

    return list(memory_delivery_snapshot().values())


# ── the two shapes that produced the 205 ─────────────────────────────────────

def test_inbound_operator_callback_reserves_no_outbound_delivery(mem):
    """150 of 205: build_inbound_event -> publish_communication reserved a Telegram delivery for the operator's own tap."""
    from scripts.lib.comms.client import publish_communication
    from scripts.lib.comms.inbound import build_inbound_event

    update = {"update_id": 900001,
              "callback_query": {"id": "cbq1", "data": "approve:123",
                                 "message": {"message_id": 77, "chat": {"id": 5551}}}}
    result = publish_communication(build_inbound_event(update))
    assert result.ok, result.errors
    assert result.delivery_ids == []
    assert _rows() == [], "an INBOUND event got an outbound delivery reservation that nothing will ever settle"


def test_inbound_event_with_explicit_channels_still_reserves_nothing(mem):
    """Belt and braces: direction alone decides. An operator message is never an outbound delivery."""
    from scripts.lib.comms.client import publish_communication
    from scripts.lib.comms.event import CommunicationEvent

    ev = CommunicationEvent(direction="INBOUND", event_type="telegram_command", message_class="operator_command",
                            producer="telegram_inbound", subject_key="telegram:inbound:1:2",
                            retention_class="operational", sanitized_body="/status", channels=["telegram"])
    result = publish_communication(ev)
    assert result.ok, result.errors
    assert _rows() == []


def test_shadow_ledger_copy_with_assumed_channel_reserves_nothing(mem):
    """55 of 205: the post-send_telegram ledger copy names no channel; the default must not become a reservation."""
    from scripts.lib.comms.client import POLICY_DEFAULT_OUTBOUND_TELEGRAM, publish_communication
    from scripts.lib.comms.event import CommunicationEvent

    # Exactly the send_watchpool_maturity_alerts.py shape (no channels=).
    result = publish_communication(CommunicationEvent(
        direction="OUTBOUND", event_type="alert", message_class="ops",
        producer="send_watchpool_maturity_alerts", subject_key="symbol:DAIC",
        retention_class="operational", severity="info", entity_refs={"symbol": "DAIC"},
        sanitized_body="Watchpool: DAIC", short_summary="Watchpool: DAIC"))
    assert result.ok, f"the ledger record itself must still be written: {result.errors}"
    assert result.delivery_ids == []
    assert _rows() == [], "a channel nobody asked for became a RESERVED row nobody settles"
    assert result.destination_policy_id == POLICY_DEFAULT_OUTBOUND_TELEGRAM, (
        "the row must say the channel was ASSUMED, not chosen by event.channels")


def test_an_explicit_channel_still_reserves(mem):
    """Negative control: the real send paths (from_plain_message, channel_adapters, agent gateway) name the channel."""
    from scripts.lib.comms.adapters import from_plain_message
    from scripts.lib.comms.client import POLICY_EVENT_CHANNELS, publish_communication

    result = publish_communication(from_plain_message(producer="telegram_alert.send_telegram", body="hello",
                                                      subject_key="telegram:ops:hello", message_class="ops"))
    assert result.ok, result.errors
    assert len(result.delivery_ids) == 1
    rows = _rows()
    assert len(rows) == 1 and rows[0]["status"] == "RESERVED"
    assert rows[0]["destination_policy_id"] == POLICY_EVENT_CHANNELS


def test_assigning_default_list_explicitly_counts_as_explicit(mem):
    """A caller that writes channels=["telegram"] asked for Telegram, even though it equals the default value."""
    from scripts.lib.comms.event import CommunicationEvent, channels_were_assumed

    assumed = CommunicationEvent(direction="OUTBOUND", event_type="a", message_class="ops", producer="p",
                                 subject_key="s", retention_class="r")
    chosen = CommunicationEvent(direction="OUTBOUND", event_type="a", message_class="ops", producer="p",
                                subject_key="s", retention_class="r", channels=["telegram"])
    assert channels_were_assumed(assumed) is True
    assert channels_were_assumed(chosen) is False
    assert assumed.channels == ["telegram"] == chosen.channels, "the value (and every reader of it) is unchanged"


# ── the reaper for what is already stuck, and for anything that slips through ──

def _reserve(event_id: str, *, age_s: float, channel: str = "telegram"):
    from scripts.lib.comms import delivery as dl

    d = dl.reserve_delivery(event_id=event_id, channel=channel)
    with dl._lock:
        dl._MEM[d.delivery_id]["reserved_at"] = datetime.now(timezone.utc) - timedelta(seconds=age_s)
    return d.delivery_id


def test_reaper_settles_stale_unowned_reservations_without_sending(mem, monkeypatch):
    from scripts.lib.comms import delivery as dl

    sent = []
    monkeypatch.setattr("scripts.lib.comms.channel_adapters._provider_send",
                        lambda *a, **k: sent.append(a) or {"ok": True}, raising=False)
    old_in = _reserve("evt_inbound_old", age_s=8 * 86400)
    old_out = _reserve("evt_outbound_old", age_s=3 * 3600)
    fresh = _reserve("evt_outbound_fresh", age_s=60)
    directions = {"evt_inbound_old": "INBOUND", "evt_outbound_old": "OUTBOUND", "evt_outbound_fresh": "OUTBOUND"}

    plan = dl.reap_stale_reservations(max_age_s=3600, apply=False, direction_of=directions.get)
    assert plan["mode"] == "DRY-RUN"
    assert {p["delivery_id"]: p["to_status"] for p in plan["planned"]} == {old_in: "CANCELLED", old_out: "EXPIRED"}
    assert {r["status"] for r in _rows()} == {"RESERVED"}, "a dry run changed a row"

    out = dl.reap_stale_reservations(max_age_s=3600, apply=True, direction_of=directions.get)
    assert out["settled"] == 2 and out["errors"] == []
    by_id = {r["delivery_id"]: r for r in _rows()}
    assert by_id[old_in]["status"] == "CANCELLED"
    assert by_id[old_in]["error_taxonomy"] == "inbound_event_no_outbound_delivery"
    assert by_id[old_out]["status"] == "EXPIRED"
    assert by_id[old_out]["error_taxonomy"] == "reservation_unclaimed_stale"
    assert by_id[old_out]["completed_at"] is not None
    assert by_id[old_out]["provider_message_id"] is None, "the reaper must never invent delivery evidence"
    assert by_id[fresh]["status"] == "RESERVED", "a reservation inside the bound belongs to a send in progress"
    assert sent == [], "the reaper performed provider I/O"

    again = dl.reap_stale_reservations(max_age_s=3600, apply=True, direction_of=directions.get)
    assert again["settled"] == 0, "not idempotent"


def test_reaper_is_bounded(mem):
    from scripts.lib.comms import delivery as dl

    for i in range(5):
        _reserve(f"evt_{i}", age_s=7200)
    out = dl.reap_stale_reservations(max_age_s=3600, apply=True, limit=2, direction_of=lambda _e: "OUTBOUND")
    assert out["settled"] == 2
    assert sum(1 for r in _rows() if r["status"] == "RESERVED") == 3


def test_reaper_refuses_a_bound_shorter_than_a_send():
    from scripts.lib.comms import delivery as dl

    with pytest.raises(ValueError):
        dl.reap_stale_reservations(max_age_s=60, apply=False)


def test_comms_lifecycle_reaper_step_is_opt_in():
    """The reaper is a comms-lifecycle step, but NOT in the hourly cron run's defaults: that would change a frozen
    cron job (operator freeze 2026-10-09) before its inventory approval. Run with --steps reservations."""
    src = (ROOT / "scripts" / "comms_lifecycle.py").read_text(encoding="utf-8")
    assert 'default="classify,expire,purge"' in src
    assert '"reservations" in steps' in src
    assert "reap_stale_reservations" in src


def test_settled_rows_leave_the_unsettled_count():
    """The summary endpoint counts RESERVED/SENDING as unsettled; every reaper status is outside that set."""
    from scripts.communications_portal import UNSETTLED_STATUSES
    from scripts.lib.comms import delivery as dl

    for st in dl.REAPER_STATUSES.values():
        assert st not in UNSETTLED_STATUSES
        assert st in dl.DELIVERY_STATUSES


def test_summary_counts_reaped_unclaimed_copies_apart_from_failed(monkeypatch):
    """After the 21:17 reaper run (2026-10-20) the strip read "failed 6": the six EXPIRED rows were unclaimed
    shadow-ledger copies whose own deliveries had settled. They are reaped_unclaimed, not failed. A real EXPIRED
    (any other or NULL error_taxonomy) still counts as failed -- checked against a real SQL engine below."""
    import sqlite3

    import communications_portal as CP
    from scripts.lib.comms import delivery as dl

    assert CP.REAPED_UNCLAIMED_TAXONOMY == dl.REAPER_TAXONOMY["reserved"]
    assert dl.REAPER_STATUSES["reserved"] == "EXPIRED"

    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE communication_deliveries (status TEXT, error_taxonomy TEXT, reserved_at TEXT)")
    db.executemany("INSERT INTO communication_deliveries VALUES (?, ?, '2026-10-20T10:00:00+00:00')", [
        ("EXPIRED", "reservation_unclaimed_stale")] * 6 + [
        ("EXPIRED", None), ("EXPIRED", "provider_ttl"), ("FAILED", "reservation_unclaimed_stale"),
        ("SENT", None), ("RESERVED", None)])

    class _Cur:
        description = None

        def execute(self, sql, params=None):
            sql = sql.replace("now()", "'2026-10-20T12:00:00+00:00'")  # deterministic timezone-aware SQL clock
            self._c = db.execute(sql)
            self.description = self._c.description

        def fetchone(self):
            row = list(self._c.fetchone())
            for index, column in enumerate(self.description):
                name = column[0]
                if name in {"oldest_unsettled_at", "as_of", "window_start"} and row[index] is not None:
                    row[index] = datetime.fromisoformat(row[index])
            return tuple(row)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

        def rollback(self):
            pass

    monkeypatch.setattr(CP, "_deliveries_db_conn", lambda: _Conn())
    s = CP.delivery_summary()
    assert s["status"] == "OK", s
    assert s["reaped_unclaimed"] == 6
    assert s["failed"] == 3, "a NULL-taxonomy EXPIRED, a provider EXPIRED and a FAILED are real failures"
    assert s["unsettled"] == 1 and s["total"] == 11
