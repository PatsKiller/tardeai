#!/usr/bin/env python3
"""Put an EXISTING id on the existing subject spine, without changing that id.

P1 of the goal-loop plan. Read `docs/architecture/narrative-subject-identity.md`
first: this module adds no schema, mints no subject, and invents no sixth
identity scheme. It is a thin wrapper over `cio_narrative_subjects.build_links`
and writes the same `narrative_subjects` row the detector and the narrative
writer already write, with the same `ON CONFLICT (link_guid) DO NOTHING`.

THE DEFECT THIS ADDRESSES
-------------------------
Measured 2026-09-16: a question has five identities and no join key.

    DataGap.gap_id            uuid5 over  domain|subject|question
    ResearchGap.gap_id        uuid5 over  security_guid|reason|question
    data_gap_registry.id      a bigserial integer
    question_guid (circle)    uuid5 over  chat_id|message_id|text
    question_guid (diligence) uuid5 over  subject_guid|change_guid|text
    cio_goals.goal_id         "goal_" + 12 hex

Nothing could follow one question from the goal that raised it, through the gap
that expressed it, to the pending reply that answered it. The two `tradeai:gap:`
schemes are worse than merely different -- they share a prefix and disagree on
the tuple, so the same gap gets two UUIDs (see `scripts/check_identity_spine.py`).

WHY A LINK AND NOT A MIGRATION
------------------------------
Every one of those ids keeps its value forever. `narrative_subjects` is already
a generic `(source_table, source_id) -> subject_guid` edge table with a
`row_guid` convention for rows whose PK is not a guid. Registering an id is
therefore additive: no column is added, no row is rewritten, no id changes, and
an older reader that knows nothing of these `source_table` values is unaffected.

RULES THIS KEEPS
----------------
* **Never mint a security identity.** The caller supplies a `subject_guid` that
  some registry lookup already resolved. For a non-security subject the minted
  guid must MATCH the one supplied, or the link is refused -- a wrapper that
  silently re-stamped identity would recreate the `sector_move` defect this
  table exists to prevent.
* **Fail-safe, not fail-closed** (contract rule 5). A registration failure
  leaves the producer's own write untouched and returns None. A gap that is
  unlinked is degraded; a gap that was never written because the linker could
  not reach the database is lost.
* **Additive, delete-free.** INSERT ... ON CONFLICT (link_guid) DO NOTHING is
  the only statement this module issues against `narrative_subjects`.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. A link says what a gap, question
or goal is ABOUT. It can never change what any desk DOES.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Iterable, Optional

from scripts.lib.cio_narrative_subjects import (
    CONFIDENCE_CANDIDATE,
    build_links,
)
from scripts.lib.cio_narrative_write import row_guid_for

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

log = logging.getLogger("tradeai.identity_spine")

#: The six existing id schemes P1 puts on the spine, and the `source_table`
#: value each is registered under. These are NEW source_table values on an
#: EXISTING table -- `narrative_subjects.source_table` carries no CHECK
#: constraint, precisely so a lane can join without a migration.
SOURCE_TABLES = (
    "gap_resolver_gaps",        # gap_resolver.DataGap.gap_id       (uuid5)
    "research_gaps",            # research_gap.gap_id                (uuid5)
    "data_gap_registry",        # the bigserial integer id
    "operator_questions",       # research_circle.question_guid      (uuid5)
    "due_diligence_questions",  # due_diligence_questions.question_guid (uuid5)
    "cio_goals",                # cio_goals.goal_id                  ("goal_<hex>")
)

#: The one statement this module issues. Character-for-character the INSERT in
#: `material_change_detector.persist` and `cio_narrative_write.persist_narrative`,
#: because three writers disagreeing about a table's columns is how the
#: `narrative_subjects_confidence_ck` outage happened on 2026-09-11.
_INSERT_SQL = """INSERT INTO narrative_subjects
     (link_guid, row_guid, source_table, source_id, entity_type,
      subject_guid, semantic_subject, relationship, confidence,
      author_agent_id, schema_version)
   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
   ON CONFLICT (link_guid) DO NOTHING"""

_FLAG = "CIO_IDENTITY_SPINE"


def enabled(env: Optional[dict[str, str]] = None) -> bool:
    """Registration is on by default and switchable off without a deploy.

    Fails OPEN deliberately, unlike a budget or a broker flag: the worst case of
    an unwanted link row is a joinable row nobody reads, while the worst case of
    a silently-off linker is the identity gap this phase exists to close
    reappearing with no receipt.
    """
    raw = (env if env is not None else os.environ).get(_FLAG, "1")
    return str(raw).strip().lower() not in ("0", "false", "off", "no")


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def row_guid_of(source_table: str, source_id: Any) -> str:
    """The row's own guid when it HAS one; the spine's uuid5 convention when not.

    `DataGap.gap_id` and both `question_guid`s are already UUIDs -- using them
    directly is what makes the link joinable back to the producer's store
    without a lookup table. `data_gap_registry.id` (a bigserial) and
    `cio_goals.goal_id` ("goal_<hex>") are not, so they take the same
    `row_guid_for(table, pk)` uuid5 the other fourteen narrative surfaces take.
    """
    return str(source_id) if _is_uuid(source_id) else row_guid_for(source_table, source_id)


def build_spine_link(
    *,
    source_table: str,
    source_id: Any,
    subject_guid: str,
    relationship: str = "subject",
    entity_type: str = "SECURITY",
    semantic_subject: Optional[str] = None,
    confidence: str = CONFIDENCE_CANDIDATE,
    author_agent_id: str = "cio",
    row_guid: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """The pure half: the link row, or None with the reason logged.

    Goes through `build_links` rather than assembling a dict, so the link_guid
    convention, the relationship vocabulary and the entity-type rejection are
    the ones already under test -- there is exactly one definition of a
    NarrativeSubjectLink and this is not a second one.

    For a SECURITY the resolved guid is INJECTED (the caller already looked it
    up; this module never touches the registry). For any other subject type
    `build_links` mints deterministically from the name and the result must
    equal the supplied guid, or the link is refused rather than re-stamped.
    """
    table = str(source_table or "").strip()
    sid = "" if source_id is None else str(source_id).strip()
    sguid = str(subject_guid or "").strip()
    if not table or not sid or not sguid:
        log.warning("spine: refused source_table=%r source_id=%r subject_guid=%r",
                    source_table, source_id, subject_guid)
        return None

    et = str(entity_type or "SECURITY").strip().upper()
    name = str(semantic_subject or "").strip() or (sid if et != "SECURITY" else sguid)
    rg = row_guid or row_guid_of(table, sid)

    if et == "SECURITY":
        def _lookup(symbol: str, root: Any = None) -> dict[str, Any]:
            # Identity is an input here, not a question: nothing in this
            # function reads the registry. `resolve_subject` reports
            # CONFIRMED / CANDIDATE from `identity_status`.
            return {"subject_guid": sguid, "identity_status": confidence}
    else:
        _lookup = None  # type: ignore[assignment]

    try:
        links, misses = build_links(
            row_guid=rg,
            source_table=table,
            source_id=sid,
            subjects=[{"entity_type": et, "value": name, "relationship": relationship}],
            author_agent_id=author_agent_id,
            symbol_lookup=_lookup,
        )
    except Exception as exc:  # noqa: BLE001 -- fail-safe: never break the producer
        log.warning("spine: build_links refused %s/%s: %s: %s", table, sid,
                    type(exc).__name__, exc)
        return None

    if not links:
        log.warning("spine: no link for %s/%s (%s)", table, sid, misses)
        return None
    link = links[0]
    if link["subject_guid"] != sguid:
        # A minted guid that disagrees with the resolved one is the sector_move
        # defect in a new costume. Refuse; never overwrite identity.
        log.warning("spine: refused %s/%s -- minted %s != supplied %s",
                    table, sid, link["subject_guid"], sguid)
        return None
    return link


def _connect():
    """A short-lived connection, or None. Mirrors the desk's gap-queue idiom."""
    if os.environ.get("TRADE_AI_CI") == "1":
        return None
    password = os.environ.get("DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD")
    if not password:
        return None
    import psycopg2  # noqa: PLC0415

    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "trade_ai"),
        user=os.environ.get("DB_USER", "trade_ai"),
        password=password,
        connect_timeout=3,
        options="-c statement_timeout=5000",
    )


def _write(cur, link: dict[str, Any]) -> None:
    cur.execute(_INSERT_SQL, (
        link["link_guid"], link["row_guid"], link["source_table"], link["source_id"],
        link["entity_type"], link["subject_guid"], link["semantic_subject"],
        link["relationship"], link["confidence"], link["author_agent_id"],
        link["schema_version"],
    ))


def register_on_spine(
    source_table: str,
    source_id: Any,
    subject_guid: str,
    relationship: str = "subject",
    *,
    cur: Any = None,
    entity_type: str = "SECURITY",
    semantic_subject: Optional[str] = None,
    confidence: str = CONFIDENCE_CANDIDATE,
    author_agent_id: str = "cio",
    row_guid: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Register one existing id on the spine. Returns its link_guid, or None.

    ``cur`` is a DB-API cursor whose transaction the CALLER owns and commits --
    the pattern every write module here uses, and the reason a producer can put
    its row and its link in one transaction. With no cursor this opens its own
    short-lived connection and commits it.

    A returned link_guid means the edge exists (written now, or already there --
    ON CONFLICT DO NOTHING makes those indistinguishable and equally true).
    None means no edge exists and the producer's own write is untouched.
    """
    if not enabled(env):
        return None
    if cur is None and os.environ.get("TRADE_AI_CI") == "1":
        # Offline by contract: a test never reaches a database, and building a
        # link that provably cannot be written is pure cost.
        return None
    link = build_spine_link(
        source_table=source_table, source_id=source_id, subject_guid=subject_guid,
        relationship=relationship, entity_type=entity_type,
        semantic_subject=semantic_subject, confidence=confidence,
        author_agent_id=author_agent_id, row_guid=row_guid,
    )
    if link is None:
        return None

    if cur is not None:
        try:
            _write(cur, link)
            return link["link_guid"]
        except Exception as exc:  # noqa: BLE001 -- fail-safe
            log.warning("spine: write failed on caller cursor for %s/%s: %s: %s",
                        link["source_table"], link["source_id"], type(exc).__name__, exc)
            return None

    conn = None
    try:
        conn = _connect()
        if conn is None:
            return None
        with conn.cursor() as own:
            _write(own, link)
        conn.commit()
        return link["link_guid"]
    except Exception as exc:  # noqa: BLE001 -- fail-safe
        log.warning("spine: write failed for %s/%s: %s: %s",
                    link["source_table"], link["source_id"], type(exc).__name__, exc)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def register_many(rows: Iterable[dict[str, Any]], *, cur: Any = None,
                  env: Optional[dict[str, str]] = None) -> list[str]:
    """Register several ids on one cursor. Returns the link_guids that exist.

    One row is one ``register_on_spine`` kwargs mapping. A row that fails is
    skipped and logged; it never aborts the rest, because a producer batching
    ten gaps must not lose nine links to one unresolved symbol.
    """
    out: list[str] = []
    for row in rows or []:
        try:
            lg = register_on_spine(cur=cur, env=env, **row)
        except Exception as exc:  # noqa: BLE001 -- fail-safe
            log.warning("spine: register_many row refused: %s: %s", type(exc).__name__, exc)
            continue
        if lg:
            out.append(lg)
    return out


def register_symbol_on_spine(
    source_table: str,
    source_id: Any,
    symbol: str,
    relationship: str = "subject",
    *,
    cur: Any = None,
    author_agent_id: str = "cio",
    env: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """Register an id whose subject is known only as a SYMBOL.

    Four of the six producers hold a ticker, not a guid. Resolution goes through
    `cio_subject_guid.lookup_subject` -- read-only, registry-first, and the same
    function every other lane resolves with, so a gap and a material change
    about NVDA land on ONE subject_guid. Memory is not an identity authority and
    nothing here registers a new one: an unknown symbol returns None and the
    producer's own row stays exactly as it was.
    """
    if not enabled(env):
        return None
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    if cur is None and os.environ.get("TRADE_AI_CI") == "1":
        # Before the registry read, not after: loading a 9.5 MB identity
        # registry to build a link nothing can write is the kind of cost a
        # fail-safe path must not impose on every test run.
        return None
    try:
        from scripts.lib.cio_subject_guid import lookup_subject  # noqa: PLC0415

        found = lookup_subject(sym) or {}
    except Exception as exc:  # noqa: BLE001 -- fail-safe
        log.warning("spine: registry lookup failed for %s: %s: %s", sym, type(exc).__name__, exc)
        return None
    sguid = found.get("subject_guid")
    if not sguid:
        # UNRESOLVED or LOOKUP_FAILED. A link with no guid joins to nothing and
        # would misreport coverage -- `cio_subject_guid` draws that distinction
        # precisely so it is not swallowed here.
        return None
    return register_on_spine(
        source_table, source_id, str(sguid), relationship,
        cur=cur, entity_type="SECURITY", semantic_subject=sym,
        confidence=str(found.get("identity_status") or CONFIDENCE_CANDIDATE),
        author_agent_id=author_agent_id, env=env,
    )


def coverage(cur: Any = None) -> Optional[dict[str, int]]:
    """Read-only: rows per source_table. None when there is no database.

    This is the P1 receipt -- `SELECT source_table, count(*) FROM
    narrative_subjects GROUP BY 1` is what proves the ids became joinable, and
    an exit code proves nothing (AGENTS §0 rule 8).
    """
    sql = "SELECT source_table, count(*) FROM narrative_subjects GROUP BY 1 ORDER BY 2 DESC"
    if cur is not None:
        cur.execute(sql)
        return {str(r[0]): int(r[1]) for r in cur.fetchall()}
    conn = None
    try:
        conn = _connect()
        if conn is None:
            return None
        with conn.cursor() as own:
            own.execute(sql)
            return {str(r[0]): int(r[1]) for r in own.fetchall()}
    except Exception as exc:  # noqa: BLE001
        log.warning("spine: coverage unavailable: %s: %s", type(exc).__name__, exc)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


__all__ = [
    "AUTHORITY",
    "MBI",
    "SOURCE_TABLES",
    "build_spine_link",
    "coverage",
    "enabled",
    "register_many",
    "register_on_spine",
    "register_symbol_on_spine",
    "row_guid_of",
]
