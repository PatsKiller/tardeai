"""Phase 2: alert delivery must be provable, and must STAY wired.

WHAT WENT WRONG, AND WHY THESE TESTS ARE SHAPED LIKE THIS
---------------------------------------------------------
#1179 landed `attach_telegram_message_id()` and `send_telegram_with_id()`. Both
were correct, both were tested, and NOTHING CALLED EITHER ONE. A merged, tested,
documented function that no call site reaches moves no number. Measured
2026-09-22, after #1179 was already on main:

    alert_events carrying a telegram_message_id : 62 of 8,003   (0.78%)
    communication_events UNSETTLED              : 51,193 of 52,930
    communication_deliveries.destination_policy_id NOT NULL : 0 of 52,929
    communication_outbox.destination_policy_id     NOT NULL : 0 of 52,929

So this suite does not assert that the helpers exist — the suite next door
(test_alert_delivery_id_attach_20260921.py) already does, and that is precisely
the assertion that stayed green while the production numbers did not move. These
tests assert the WIRING: that call sites bind the id, that the legacy settle path
forwards the id it already holds, and that the outbox records which policy chose
the channel.

THREE CLAIMS, THREE INDEPENDENT FAILURE MODES
---------------------------------------------
1. The "DB first, Telegram second" call sites must BIND the id that
   `save_alert_event` returns and stamp it after the send. Reverting
   `alert_event_id = save_alert_event(...)` back to `save_alert_event(...)`
   restores the 0.78% silently — no exception, no log line, nothing red. That
   revert is exactly what `test_a_reverted_call_site_is_detected` proves this
   file catches.

2. The legacy settle path must pass `provider_message_id` when it has one.
   `_persist_event_settlement_pg` reaches SETTLED only for
   SENT/DELIVERED/ACKNOWLEDGED *carrying a provider id*, and maps
   LEGACY_DELIVERED to UNKNOWN_LEGACY unconditionally. That mapping is why
   51,193 rows sat UNSETTLED while the 79 that settled all came from the gateway
   path, which passes the id. Critically, the fix must NOT relabel an idless
   send as SENT: no id still means UNKNOWN_LEGACY, and that is asserted.

3. The reservation/outbox must record WHICH policy chose the channel, so a row
   that targeted Telegram because nobody asked for anything else is
   distinguishable from one that was explicitly routed there.

NO DATABASE IN CI
-----------------
Structural and behavioural assertions here run unconditionally and touch no
database. The genuinely DB-dependent claims (the columns exist at all) live
behind `db_cursor`, which SKIPS when Postgres is unreachable rather than passing
vacuously, and only ever reads `information_schema`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import telegram_alert  # noqa: E402


# ───────────────────────────────────────────────────────────────────────────
# CLAIM 1 — the call sites bind the id instead of discarding it
# ───────────────────────────────────────────────────────────────────────────

# file -> regex proving the alert_events id is BOUND rather than thrown away.
# Each entry is a real call site wired in this change. The value is deliberately
# the *binding*, not the mere presence of a name: `save_alert_event(...)` as a
# bare statement is the pre-Phase-2 shape and must not match.
WIRED_CALL_SITES: dict[str, str] = {
    "scripts/portfolio_live_monitor.py": r"alert_event_id\s*=\s*save_alert_event\(",
    "scripts/stop_decision_brief.py": r"alert_event_id\s*=\s*save_alert_event\(",
    "scripts/stop_over_consensus_monitor.py": r"alert_event_id\s*=\s*save_alert_event\(",
    "scripts/stop_drift_alert.py": r"alert_event_id\s*=\s*save_alert_event\(",
    "scripts/portfolio_alerts.py": r"alert_event_ids\.append\(save_alert_event\(",
    # _siem() is this module's writer wrapper; it must hand the id back so the
    # batched card can be stamped onto every row it carried.
    "scripts/stop_health_check.py": r"return save_alert_event\(",
}


def _source(rel: str) -> str:
    p = ROOT / rel
    assert p.is_file(), f"{rel} vanished — update this test, do not delete the claim"
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", sorted(WIRED_CALL_SITES))
def test_call_site_binds_the_alert_event_id(rel: str):
    """The id must be captured. Discarding it is the 0.78% defect itself."""
    src = _source(rel)
    pattern = WIRED_CALL_SITES[rel]
    assert re.search(pattern, src), (
        f"{rel} no longer binds the id save_alert_event returns "
        f"(expected /{pattern}/). A bare save_alert_event(...) call throws the "
        f"row id away and nothing can ever be stamped onto it."
    )


@pytest.mark.parametrize("rel", sorted(WIRED_CALL_SITES))
def test_call_site_actually_stamps_the_id(rel: str):
    """Binding the id and never using it would be the same defect, one step later."""
    src = _source(rel)
    assert "attach_telegram_message_id" in src, (
        f"{rel} binds the alert_events id but never calls attach_telegram_message_id — the row is still unlinked."
    )


def test_a_reverted_call_site_is_detected():
    """Positive control: the detector must FAIL on the pre-Phase-2 shape.

    A test that cannot fail is not a test. This runs the real predicate over a
    synthetic source in exactly the shape every one of these call sites had
    before this change, and asserts it does NOT match.
    """
    reverted = (
        "from alert_event_writer import save_alert_event\n"
        "save_alert_event(alert_type='strategic_alert', raw_text=msg)\n"
        "send_telegram(msg)\n"
    )
    for pattern in WIRED_CALL_SITES.values():
        assert not re.search(pattern, reverted), (
            f"/{pattern}/ matches the REVERTED shape, so it would stay green "
            f"through the very regression it exists to catch"
        )
    assert "attach_telegram_message_id" not in reverted


def test_the_wired_set_is_not_silently_emptied():
    """Deleting entries from WIRED_CALL_SITES would make every test above vacuous."""
    assert len(WIRED_CALL_SITES) >= 6, (
        "the wired call-site set shrank — if a site was legitimately removed, "
        "say so here; do not let the parametrize list quietly become empty"
    )


def test_send_telegram_bool_contract_is_still_untouched():
    """The wiring must not have been bought by changing send_telegram's return.

    >=36 files read it in boolean context and the module claims 182 call sites
    across 150 files. The id is reached via send_telegram_with_id()/
    last_message_id() instead — that is the whole reason attach_* is separate.
    """
    src = _source("scripts/telegram_alert.py")
    assert re.search(r"def send_telegram\([^)]*\)\s*->\s*bool:", src, re.S), (
        "send_telegram no longer returns bool — that is a 150-file blast radius"
    )
    assert "def send_telegram_with_id" in src
    assert "def last_message_id" in src


# ───────────────────────────────────────────────────────────────────────────
# CLAIM 2 — the legacy settle path forwards the provider id it already holds
# ───────────────────────────────────────────────────────────────────────────


@pytest.fixture
def settled(monkeypatch):
    """Capture what the ledger is told, without a database.

    Mirrors tests/test_comms_ledger_says_what_happened.py, which stubs the comms
    client and settle path so this never reaches the live Postgres that
    tests/conftest.py warns about.
    """
    calls: list[dict] = []

    class _Pub:
        event_id = "evt-1"
        delivery_ids = ["dlv-1"]

    import scripts.lib.comms.adapters as adapters
    import scripts.lib.comms.client as client
    import scripts.lib.comms.delivery as delivery

    monkeypatch.setattr(adapters, "from_plain_message", lambda **kw: {"stub": True}, raising=False)
    monkeypatch.setattr(client, "publish_communication", lambda *a, **k: _Pub(), raising=False)
    monkeypatch.setattr(
        delivery,
        "settle_delivery",
        lambda did, *, status, provider_message_id=None, provider_coordinates=None, **k: calls.append(
            {
                "id": did,
                "status": status,
                "provider_message_id": provider_message_id,
                "coords": provider_coordinates or {},
            }
        ),
        raising=False,
    )
    return calls


def _with_ids(monkeypatch, ids: list[str]):
    """Pretend the send that just happened minted these provider ids."""
    monkeypatch.setattr(telegram_alert, "last_message_ids", lambda: list(ids))


def test_a_delivered_send_with_an_id_settles_sent_and_carries_it(settled, monkeypatch):
    """The whole point: the id the send already had must reach settle_delivery.

    LEGACY_DELIVERED could never become SETTLED. SENT + a real id is the only
    input that can, and it is the same shape the 79 working gateway rows have.
    """
    _with_ids(monkeypatch, ["9001"])
    telegram_alert._best_effort_comms_publish("m", message_class="ops", delivered=True)

    assert settled, "the ledger was never told anything at all"
    assert settled[0]["status"] == "SENT"
    assert settled[0]["provider_message_id"] == "9001"


def test_one_id_per_chat_is_joined_like_the_gateway_does(settled, monkeypatch):
    """channel_adapters records ",".join(mids); both paths must read back alike."""
    _with_ids(monkeypatch, ["9001", "9002"])
    telegram_alert._best_effort_comms_publish("m", message_class="ops", delivered=True)
    assert settled[0]["provider_message_id"] == "9001,9002"


def test_no_id_still_settles_unknown_legacy_and_never_claims_sent(settled, monkeypatch):
    """The guard rail on the fix.

    Relabelling an idless legacy send as SENT would manufacture a SETTLED-looking
    row with nothing behind it — the same class of lie as the 2026-09-05
    LEGACY_DELIVERED incident, just in the other direction. No id means the
    honest answer is still LEGACY_DELIVERED, which maps to UNKNOWN_LEGACY.
    """
    _with_ids(monkeypatch, [])
    telegram_alert._best_effort_comms_publish("m", message_class="ops", delivered=True)

    assert settled[0]["status"] == "LEGACY_DELIVERED"
    assert settled[0]["provider_message_id"] is None


def test_a_suppressed_send_is_never_upgraded_by_a_stale_id(settled, monkeypatch):
    """delivered=False must stay SUPPRESSED even if an id is lying around."""
    _with_ids(monkeypatch, ["9001"])
    telegram_alert._best_effort_comms_publish("m", message_class="ops", delivered=False)
    assert settled[0]["status"] == "SUPPRESSED"


def test_an_unobserved_send_stays_unknown(settled, monkeypatch):
    _with_ids(monkeypatch, ["9001"])
    telegram_alert._best_effort_comms_publish("m", message_class="ops")
    assert settled[0]["status"] == "UNKNOWN"


def test_the_id_cache_is_cleared_before_every_send_path():
    """Why the reset matters more than it looks.

    Only `_raw_send_telegram_result` clears `_LAST_MESSAGE_IDS`, and several
    branches never reach it: a gateway-owned class, a digested or suppressed
    alert, an early return, and `send_telegram_document` (which sends via
    `send_document` and mints no id at all). Without a clear at the top, the id
    of an EARLIER message would still be standing and would be stapled to this
    one — a wrong link is worse than a missing one, because it reads as fact.
    """
    src = _source("scripts/telegram_alert.py")
    for fn in ("def send_telegram(", "def send_telegram_document("):
        start = src.index(fn)
        body = src[start : start + 2000]
        assert "reset_last_message_ids()" in body, (
            f"{fn.strip('def (')} does not clear the previous send's id first — "
            f"a stale id can be attributed to this message"
        )


def test_settlement_state_mapping_is_what_makes_this_work(monkeypatch):
    """Ground truth for the claim above, asserted against the real mapping.

    This is the function that turned every legacy row into UNKNOWN_LEGACY. If
    someone 'simplifies' it, the wiring above becomes pointless and this fails.
    """
    from scripts.lib.comms.delivery import _persist_event_settlement_pg

    class _Cur:
        def __init__(self):
            self.statements = []

        def execute(self, sql, params=None):
            self.statements.append({"sql": sql, "params": params})

        def close(self):
            pass

    class _Conn:
        def __init__(self):
            self.cur = _Cur()

        def cursor(self):
            return self.cur

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    def _run(status, pmid):
        conn = _Conn()
        monkeypatch.setattr("db_adapter._get_conn", lambda: conn)
        _persist_event_settlement_pg(
            "evt-x",
            status=status,
            provider_message_id=pmid,
            settled_at=None,
            delivery_owner="legacy",
        )
        return conn.cur.statements[0]["params"][2]  # the settlement state

    assert _run("SENT", "9001") == "SETTLED", "SENT + id is the only road to SETTLED"
    assert _run("LEGACY_DELIVERED", "9001") == "UNKNOWN_LEGACY", (
        "LEGACY_DELIVERED is mapped unconditionally — which is exactly why the "
        "legacy path had to start sending SENT to ever settle"
    )
    assert _run("SENT", None) is None, "no id must not fabricate a settlement"


# ───────────────────────────────────────────────────────────────────────────
# CLAIM 3 — the outbox records which policy chose the channel
# ───────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mem(monkeypatch):
    """In-memory comms ledger. Forces the memory branch even where localhost
    Postgres answers, so this neither asserts the wrong store nor writes into
    the production database (see tests/test_comms_delivery_ledger.py:34-46)."""
    monkeypatch.delenv("COMMS_GATEWAY_MODE", raising=False)
    monkeypatch.setattr("scripts.lib.comms.client._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.delivery._db_conn", lambda: None)
    monkeypatch.setattr("scripts.lib.comms.subject_memory._db_conn", lambda: None)

    from scripts.lib.comms.client import reset_memory_store
    from scripts.lib.comms.delivery import reset_memory_deliveries

    reset_memory_store()
    reset_memory_deliveries()
    yield
    reset_memory_store()
    reset_memory_deliveries()


def _publish(**kw):
    from scripts.lib.comms.client import publish_communication
    from scripts.lib.comms.event import CommunicationEvent

    ev = CommunicationEvent(
        direction=kw.pop("direction", "OUTBOUND"),
        event_type="health",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key="system:watchdog",
        retention_class="ops_7d",
        sanitized_body="watchdog ok",
        **kw,
    )
    return publish_communication(ev)


def test_an_assumed_telegram_route_says_it_was_assumed():
    """Nobody asked for Telegram here; the default picked it. That must be visible.

    Asserted directly against the policy function rather than through
    publish_communication, because `required_missing` rejects an OUTBOUND event
    that names no channel anywhere (`missing:delivery_channels`) before any
    delivery is reserved — so this branch is reachable only by a caller that
    supplies channels some other way. It still needs its own id: "nobody chose
    this, the default did" is precisely the routing reason worth reading back,
    and an unasserted branch is one that drifts.
    """
    from scripts.lib.comms.client import (
        POLICY_DEFAULT_OUTBOUND_TELEGRAM,
        _destination_policy_for,
    )
    from scripts.lib.comms.event import CommunicationEvent

    ev = CommunicationEvent(
        direction="OUTBOUND",
        event_type="health",
        message_class="operator_alert",
        producer="ops.watchdog",
        subject_key="system:watchdog",
        retention_class="ops_7d",
        sanitized_body="watchdog ok",
        channels=[],
    )
    channels, policy = _destination_policy_for(ev)
    assert channels == ["telegram"], "the default outbound channel changed"
    assert policy == POLICY_DEFAULT_OUTBOUND_TELEGRAM


def test_an_explicitly_routed_event_says_so(mem):
    from scripts.lib.comms.client import POLICY_EVENT_CHANNELS
    from scripts.lib.comms.delivery import memory_delivery_snapshot

    result = _publish(channels=["telegram"])
    assert result.destination_policy_id == POLICY_EVENT_CHANNELS
    rows = list(memory_delivery_snapshot().values())
    assert rows[0]["destination_policy_id"] == POLICY_EVENT_CHANNELS


def test_a_delivery_policy_route_is_distinguishable(mem):
    """Three different reasons must not collapse into one label."""
    from scripts.lib.comms.client import (
        POLICY_DELIVERY_POLICY_CHANNELS,
        POLICY_DEFAULT_OUTBOUND_TELEGRAM,
        POLICY_EVENT_CHANNELS,
    )

    from scripts.lib.comms.delivery import memory_delivery_snapshot

    result = _publish(channels=[], delivery_policy={"channels": ["telegram"]})
    assert result.ok is True
    assert result.destination_policy_id == POLICY_DELIVERY_POLICY_CHANNELS
    rows = list(memory_delivery_snapshot().values())
    assert rows, "publish reserved no delivery at all"
    assert rows[0]["destination_policy_id"] == POLICY_DELIVERY_POLICY_CHANNELS, (
        "the reservation did not record which policy chose the channel — this is "
        "the column that was NULL on all 52,929 rows"
    )
    assert (
        len(
            {
                POLICY_EVENT_CHANNELS,
                POLICY_DELIVERY_POLICY_CHANNELS,
                POLICY_DEFAULT_OUTBOUND_TELEGRAM,
            }
        )
        == 3
    ), "two policies share an id, so the column cannot tell them apart"


def test_the_policy_id_comes_from_the_caller_not_from_thin_air(mem):
    """Negative control for claim 3.

    A reservation made WITHOUT a policy must carry None. If this returned a
    value, the tests above would be asserting an invented default rather than
    the routing decision actually threaded through publish_communication.
    """
    from scripts.lib.comms.delivery import attach_delivery_reservation

    stub = attach_delivery_reservation("evt_no_policy", "telegram")
    assert stub.destination_policy_id is None


def test_the_outbox_insert_records_the_policy_column():
    """The deliveries row and the outbox row were BOTH NULL; fixing one is half."""
    src = _source("scripts/lib/comms/client.py")
    insert = src[src.index("INSERT INTO communication_outbox") :][:400]
    assert "destination_policy_id" in insert, "communication_outbox is still inserted without destination_policy_id"


# ───────────────────────────────────────────────────────────────────────────
# DB-dependent claims — skipped, never silently passed, when Postgres is absent
# ───────────────────────────────────────────────────────────────────────────


@pytest.fixture
def db_cursor():
    """Read-only cursor on the real database, or SKIP.

    There is no Postgres in CI, so the claims that genuinely need one are gated
    here and SKIP rather than passing vacuously — a weaker claim, stated as
    such, instead of one dressed up as end-to-end. Reads information_schema
    only; it never writes.
    """
    try:
        from db_adapter import _get_conn

        conn = _get_conn()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"database unreachable ({type(exc).__name__}) — column checks skipped")
    if conn is None:  # pragma: no cover - environment dependent
        pytest.skip("database unreachable — column checks skipped")
    cur = conn.cursor()
    try:
        yield cur
    finally:
        for closer in (cur, conn):
            try:
                closer.close()
            except Exception:
                pass


@pytest.mark.parametrize(
    "table,column",
    [
        ("alert_events", "telegram_message_id"),
        ("alert_events", "telegram_sent_at"),
        ("communication_deliveries", "destination_policy_id"),
        ("communication_outbox", "destination_policy_id"),
    ],
)
def test_the_columns_this_wiring_writes_actually_exist(db_cursor, table, column):
    """Wiring that writes a column the schema lacks would fail silently at runtime.

    Every write above is inside a best-effort try/except (alerting must never be
    broken by bookkeeping), so a missing column would be swallowed and the
    numbers would simply never move — which is the failure this whole phase is
    about.
    """
    db_cursor.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
        (table, column),
    )
    assert db_cursor.fetchone() is not None, f"{table}.{column} does not exist"
