"""The memory join, closed at both ends: event lineage and receipt subject.

WHY
---
Measured 2026-09-22 against the live ledger:

  * `causation_id`   0 of 54,928 communication_events
  * `parent_event_id` 0 of 54,928
  * `subject_guid`   0 of 199 agent consumption receipts

None of that was a missing design. Both event columns have existed since the
2026-09-05 ledger migration, and `subject_guid` exists on the receipts table
AND on the AgentConsumptionReceipt dataclass -- it was simply absent from the
INSERT column list, so every receipt discarded it on the way to Postgres.
`correlation_id` and `thread_id` were already 100% populated by the same
`mint_identity()` this change extends.

THE TWO DEFAULTS, AND WHY THEY ARE NOT INVENTED LINEAGE
-------------------------------------------------------
A cron-scheduled alert is caused by a schedule, not by another ledger event.
So for a root event:

  * `causation_id` = its own `event_id`. This is the standard event-sourcing
    encoding for a root message. It is a MARKER, not an ancestor: the exact
    predicate "has an upstream cause" is `causation_id <> event_id`, and
    `is_root_event()` exists so consumers never have to guess. Leaving NULL
    would keep the column unjoinable and indistinguishable from the 54,928
    unwired rows this change exists to fix.

  * `parent_event_id` = NULL. A root event has no parent. Writing its own id
    here would be a false statement AND would make any recursive walk of the
    lineage tree loop forever. The column therefore stays sparse until real
    reply/supersede lineage exists, which is an honest measurement of the
    lineage the system has rather than a column we forced to 100%.

`run_id`, `incident_id` and `wake_id` are NOT event ids and are never
laundered into an event-id column, which is what the `parent_kind` test below
pins.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts.lib.comms.event import CommunicationEvent, is_root_event

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_SRC = ROOT / "scripts" / "lib" / "comms" / "agent_contracts.py"
EVENT_SRC = ROOT / "scripts" / "lib" / "comms" / "event.py"

RECEIPT_TABLE = "communication_agent_consumption_receipts"


def _event(**kw) -> CommunicationEvent:
    base = dict(
        direction="OUTBOUND",
        event_type="alert",
        message_class="ops",
        producer="test_producer",
        subject_key="subj_1",
        retention_class="operational_30d",
    )
    base.update(kw)
    return CommunicationEvent(**base)


def _insert_columns() -> list[str]:
    """Column list of the receipt INSERT, read from source."""
    src = CONTRACTS_SRC.read_text(encoding="utf-8")
    m = re.search(
        r"INSERT INTO " + RECEIPT_TABLE + r"\s*\((?P<cols>.*?)\)\s*VALUES",
        src,
        re.S,
    )
    assert m, "receipt INSERT not found -- did the writer move?"
    return [c.strip() for c in m.group("cols").split(",") if c.strip()]


# --- structural / behavioural: always run, no database ------------------


def test_a_root_event_causation_points_at_itself() -> None:
    """The whole defect in one assertion. NULL here is the 54,928-row bug."""
    ev = _event()
    ev.mint_identity()
    assert ev.causation_id is not None, "causation_id was left NULL -- the defect"
    assert ev.causation_id == ev.event_id
    assert is_root_event(ev)


def test_a_root_event_has_no_parent() -> None:
    """Self-parenting would be a lie AND would loop a recursive lineage walk."""
    ev = _event()
    ev.mint_identity()
    assert ev.parent_event_id is None
    assert ev.parent_event_id != ev.event_id


def test_a_reply_names_the_event_that_caused_it() -> None:
    ev = _event(reply_to_event_id="evt_parent")
    ev.mint_identity()
    assert ev.causation_id == "evt_parent"
    assert ev.parent_event_id == "evt_parent"
    assert not is_root_event(ev)


def test_a_supersede_is_caused_by_what_it_replaces() -> None:
    ev = _event(supersedes_event_id="evt_old")
    ev.mint_identity()
    assert ev.causation_id == "evt_old"
    assert ev.parent_event_id == "evt_old"


def test_a_producer_supplied_cause_is_never_overwritten() -> None:
    ev = _event(causation_id="evt_explicit", reply_to_event_id="evt_parent")
    ev.mint_identity()
    assert ev.causation_id == "evt_explicit"


def test_a_non_event_parent_is_not_laundered_into_an_event_id_column() -> None:
    """parent_id may hold a wake id. wake_id is not an event id."""
    ev = _event(parent_id="wake_123", parent_kind="wake")
    ev.mint_identity()
    assert ev.parent_event_id is None
    assert is_root_event(ev), "a wake is not a ledger event; this is still a root"

    comm = _event(parent_id="evt_pk", parent_kind="comm_event")
    comm.mint_identity()
    assert comm.parent_event_id == "evt_pk"
    assert comm.causation_id == "evt_pk"


def test_lineage_reaches_the_row_that_is_written() -> None:
    """to_row() is what the INSERT binds. Minting alone would prove nothing."""
    ev = _event()
    row = ev.to_row()
    assert row["causation_id"] == ev.event_id
    assert row["parent_event_id"] is None
    assert row["correlation_id"] and row["thread_id"]


def test_mint_identity_actually_calls_the_lineage_default() -> None:
    """Negative control on the wiring itself, not just on one event."""
    src = EVENT_SRC.read_text(encoding="utf-8")
    assert "_default_lineage" in src
    assert src.count("_default_lineage") >= 2, "defined but never called"


def test_the_receipt_insert_names_subject_guid() -> None:
    """0 of 199 receipts carried a subject_guid because of this column list."""
    cols = _insert_columns()
    assert "subject_guid" in cols, "the receipt write drops subject_guid again"
    assert "event_id" in cols and "thread_id" in cols


def test_a_receipt_falls_back_to_the_ledger_subject_guid(monkeypatch) -> None:
    """A caller that supplies none must still land the spine guid."""
    from scripts.lib.comms import agent_contracts

    # Hermetic on purpose: force the in-memory path so this assertion can never
    # write to a real receipts table. A unit test in this repository has
    # written to the production database before.
    monkeypatch.setattr(agent_contracts, "_db_conn", lambda: None)
    emit_consumption_receipt = agent_contracts.emit_consumption_receipt

    receipt = emit_consumption_receipt(
        "cio",
        event_id="evt_guid_fallback_1",
        purpose="unit_test_subject_guid",
        event={
            "event_id": "evt_guid_fallback_1",
            "subject_guid": "guid-from-the-ledger",
            "knowledge_eligibility": "ineligible",
        },
        provenance={"producer": "test"},
    )
    assert receipt.subject_guid == "guid-from-the-ledger"


def test_an_explicit_subject_guid_wins_over_the_fallback(monkeypatch) -> None:
    from scripts.lib.comms import agent_contracts

    monkeypatch.setattr(agent_contracts, "_db_conn", lambda: None)
    emit_consumption_receipt = agent_contracts.emit_consumption_receipt

    receipt = emit_consumption_receipt(
        "cio",
        event_id="evt_guid_explicit_1",
        purpose="unit_test_subject_guid_explicit",
        subject_guid="guid-explicit",
        event={
            "event_id": "evt_guid_explicit_1",
            "subject_guid": "guid-from-the-ledger",
            "knowledge_eligibility": "ineligible",
        },
        provenance={"producer": "test"},
    )
    assert receipt.subject_guid == "guid-explicit"


def test_the_consumer_prefers_the_spine_guid_over_the_conversation_guid() -> None:
    from scripts.lib.agent_comms_consumption import comms_subject_guid, consume_event

    with_spine = consume_event(
        "cio",
        {"event_id": "evt_spine_1", "subject_key": "chat:9", "subject_guid": "guid-spine"},
        apply=False,
        provenance={"producer": "test"},
    )
    assert with_spine["subject_guid"] == "guid-spine"

    without = consume_event(
        "cio",
        {"event_id": "evt_spine_2", "subject_key": "chat:9"},
        apply=False,
        provenance={"producer": "test"},
    )
    assert without["subject_guid"] == comms_subject_guid("chat:9")


def test_the_detector_can_fail() -> None:
    """Positive control: the column-list check must reject a reverted INSERT."""
    reverted = "INSERT INTO " + RECEIPT_TABLE + " (\n  receipt_id, event_id\n) VALUES"
    m = re.search(
        r"INSERT INTO " + RECEIPT_TABLE + r"\s*\((?P<cols>.*?)\)\s*VALUES",
        reverted,
        re.S,
    )
    cols = [c.strip() for c in m.group("cols").split(",") if c.strip()]
    assert "subject_guid" not in cols


# --- database-dependent: skipped when no database is reachable ----------


@pytest.fixture
def live_conn():
    """Skip DB assertions when no database is reachable.

    CI is hermetic. A test that can only pass with a database attached does not
    belong in a hermetic gate, and one that silently passes because it skipped
    everything is worse -- so every assertion above still runs unconditionally.

    READ-ONLY by construction: this fixture never writes. A unit test has
    written to the production database in this repository before.
    """
    try:
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        from db_adapter import _get_conn  # type: ignore

        conn = _get_conn()
    except Exception:
        pytest.skip("no database in this environment; structural tests still run")
    if conn is None:
        pytest.skip("no database in this environment; structural tests still run")
    return conn


def _columns(conn, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
            (table,),
        )
        return {r[0] for r in cur.fetchall()}


def test_every_column_the_receipt_insert_names_exists(live_conn) -> None:
    """A name that is not a real column makes the INSERT raise.

    The writer catches that, rolls back and degrades to the in-memory store, so
    receipts would stop reaching Postgres SILENTLY. That is exactly how a
    column can be present in the dataclass and absent from the database.
    """
    actual = _columns(live_conn, RECEIPT_TABLE)
    if not actual:
        pytest.skip(f"{RECEIPT_TABLE} not present in this database")
    missing = [c for c in _insert_columns() if c not in actual]
    assert missing == [], f"INSERT names columns that do not exist: {missing}"


def test_the_event_lineage_columns_exist_to_be_written(live_conn) -> None:
    actual = _columns(live_conn, "communication_events")
    if not actual:
        pytest.skip("communication_events not present in this database")
    for col in ("causation_id", "parent_event_id", "reply_to_event_id", "subject_guid"):
        assert col in actual, f"communication_events.{col} is missing"
