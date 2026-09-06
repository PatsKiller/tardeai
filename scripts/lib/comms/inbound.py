"""Inbound half of the Communications Gateway (Wave C).

Builds INBOUND CommunicationEvent@v2 rows from raw Telegram ``getUpdates``
payloads, maintains a durable ``update_id`` checkpoint whose offset advances
only after the event is persisted, and quarantines unresolved callback queries.

Why this module exists (the defect it fixes)
--------------------------------------------
The live poller advanced its offset *before* processing each update::

    for update in results:
        _save_offset(update["update_id"])   # durable write at the TOP
        handle_callback_query(update["callback_query"])  # or command

A crash between the offset write and the persist permanently dropped that
update — Telegram never re-delivers an update whose ``update_id`` is at or
below the supplied ``offset``, and the poller's own offset file claimed it was
done. The fix is a two-phase API:

- ``claim_update(update_id)`` — read-only gate. Returns whether the update is
  already processed. Performs **no durable write**, so a crash here loses
  nothing.
- ``commit_checkpoint(update_id)`` — the *only* durable offset write, called
  after the CommunicationEvent is persisted. Monotonic and idempotent.

Replay-denial is therefore a consequence of the checkpoint, not a separate
side effect: ``is_update_already_processed(u)`` is ``u <= committed_offset``.

Never calls providers. Never mints a new ``@v1`` type — reuses
``CommunicationEvent@v2``.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.comms.event import CommunicationEvent
from scripts.lib.comms.vocabulary import normalize_message_class

RETENTION_CLASS = "inbound_7d"
DEFAULT_MESSAGE_CLASS = "operator_command"
DEFAULT_PRODUCER = "telegram_inbound"

_CHECKPOINT_TABLE = "communication_inbound_checkpoint"
_QUARANTINE_TABLE = "communication_inbound_quarantine"

_lock = threading.Lock()


class InboundGateError(ValueError):
    """Fail-closed: malformed update, missing update_id, or missing quarantine reason."""


@dataclass
class ClaimResult:
    """Result of claiming an update for processing. No durable side effect."""

    update_id: int
    already_processed: bool
    checkpoint_offset: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "update_id": self.update_id,
            "already_processed": self.already_processed,
            "checkpoint_offset": self.checkpoint_offset,
        }


# ── build_inbound_event ────────────────────────────────────────────────────────


def build_inbound_event(update: dict[str, Any]) -> CommunicationEvent:
    """Build an INBOUND CommunicationEvent from a raw Telegram getUpdates item.

    Accepts ``callback_query`` and ``message``-shaped updates. Deterministic:
    the same update always yields the same ``subject_key``, so the ledger
    idempotency key (derived from it) collides on replay.
    """
    if not isinstance(update, dict):
        raise InboundGateError(f"update must be a dict, got {type(update).__name__}")

    update_id = _coerce_update_id(update.get("update_id"))
    cb = update.get("callback_query")
    msg = update.get("message")

    if cb is None and msg is None:
        raise InboundGateError("update has neither callback_query nor message")

    if cb is not None:
        event_type = "callback_query"
        callback_query_id = cb.get("id")
        inner = cb.get("message") or {}
        chat_id = _as_str(inner.get("chat", {}).get("id"))
        message_id = inner.get("message_id")
        reply_to_message_id = (inner.get("reply_to_message") or {}).get("message_id")
        body = cb.get("data")
    else:
        event_type = "telegram_command"
        callback_query_id = None
        chat_id = _as_str(msg.get("chat", {}).get("id"))
        message_id = msg.get("message_id")
        reply_to_message_id = (msg.get("reply_to_message") or {}).get("message_id")
        body = msg.get("text")

    message_class = normalize_message_class(
        update.get("message_class") or DEFAULT_MESSAGE_CLASS
    )
    producer = str(update.get("producer") or DEFAULT_PRODUCER)

    subject_key = f"telegram:inbound:{chat_id}:{message_id}"

    provider_coordinates = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_to_message_id": reply_to_message_id,
        "callback_query_id": callback_query_id,
        "update_id": update_id,
        "bot_id": _bot_id(update),
    }

    event = CommunicationEvent(
        direction="INBOUND",
        event_type=event_type,
        message_class=message_class,
        producer=producer,
        subject_key=subject_key,
        retention_class=RETENTION_CLASS,
        provider_coordinates=provider_coordinates,
        sanitized_body=body if isinstance(body, str) else None,
        payload={"text": body if event_type == "telegram_command" else None,
                 "data": body if event_type == "callback_query" else None},
        intended_action="record",
        source_system="telegram",
        observed_at=datetime.now(timezone.utc),
    )
    event.mint_identity()
    return event


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _bot_id(update: dict[str, Any]) -> str | None:
    # The bot identity is supplied by the (approved) inbound poller, which knows
    # its own bot id. This library module must NOT read TELEGRAM_BOT_TOKEN — the
    # telegram chokepoint ratchet treats a token read outside the approved
    # transport/inbound set as a delivery bypass (token_for_delivery).
    explicit = update.get("bot_id")
    if explicit is not None:
        return str(explicit)
    return None


def _coerce_update_id(update_id: Any) -> int:
    if update_id is None:
        raise InboundGateError("update_id required")
    try:
        uid = int(update_id)
    except (TypeError, ValueError):
        raise InboundGateError(f"invalid update_id: {update_id!r}") from None
    if uid < 0:
        raise InboundGateError(f"invalid update_id: {uid}")
    return uid


# ── durable checkpoint ─────────────────────────────────────────────────────────


def _state_dir() -> Path:
    env = os.environ.get("COMMS_INBOUND_STATE_DIR")
    if env:
        return Path(env)
    # <root>/scripts/lib/comms/inbound.py -> parents[3] == <root>
    return Path(__file__).resolve().parents[3] / "data" / "portfolios" / "state"


def _checkpoint_file() -> Path:
    return _state_dir() / "communication_inbound_checkpoint.json"


def _quarantine_file() -> Path:
    return _state_dir() / "communication_inbound_quarantine.json"


def _db_conn():
    """Best-effort connection; None when unavailable or inbound tables missing."""
    try:
        from db_adapter import _get_conn  # scripts/ on path in many entrypoints
    except Exception:
        try:
            from scripts.db_adapter import _get_conn  # type: ignore
        except Exception:
            return None
    try:
        conn = _get_conn()
    except Exception:
        return None
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.tables
                 WHERE table_name IN (%s, %s)
                """,
                (_CHECKPOINT_TABLE, _QUARANTINE_TABLE),
            )
            n = cur.fetchone()[0]
        if int(n) < 2:
            return None
    except Exception:
        return None
    return conn


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, default=str))
    os.replace(tmp, path)


def _read_checkpoint_file() -> dict[str, Any]:
    state = _read_json(_checkpoint_file(), {"committed_update_id": 0})
    return state if isinstance(state, dict) else {"committed_update_id": 0}


def _read_quarantine_file() -> list[dict[str, Any]]:
    rows = _read_json(_quarantine_file(), [])
    return [r for r in rows if isinstance(r, dict)]


def get_checkpoint_offset() -> int:
    """Return the highest update_id whose inbound event has been persisted."""
    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT committed_update_id FROM {_CHECKPOINT_TABLE} WHERE id = 1"
                )
                row = cur.fetchone()
            conn.commit()
            if row:
                return int(row[0])
            # No checkpoint row yet. Returning 0 here is the MAXIMALLY UNSAFE
            # default on this path: the poller then requests offset = 0 + 1,
            # Telegram replays its whole retained backlog, and claim_update
            # denies none of it because `u <= 0` is false for every update.
            # Among that backlog are approve/reject callbacks.
            #
            # Measured 2026-09-05: the DB checkpoint held 0 rows while the
            # legacy poller's own file recorded 113864091. The cutover created
            # the tables and never seeded them, so replay-denial has been
            # inoperative since — not failing, just never able to say no.
            #
            # For replay denial a HIGHER offset is the safe direction: it denies
            # more. So an uninitialised checkpoint takes the highest value any
            # source knows about rather than assuming nothing has happened.
            return _seed_offset()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    with _lock:
        return max(int(_read_checkpoint_file().get("committed_update_id") or 0),
                   _legacy_offset())


def _legacy_offset() -> int:
    """The pre-gateway poller's durable offset, or 0 when it cannot be read.

    This is a READ of a file the legacy path still owns. Nothing here writes it:
    the two offsets converge because commit_checkpoint advances the DB one, not
    because this module edits the old file.
    """
    try:
        raw = (_state_dir() / ".telegram_callback_offset").read_text(encoding="utf-8")
        return int(raw.strip() or 0)
    except Exception:
        return 0


def _seed_offset() -> int:
    """Highest offset any source knows, for an uninitialised checkpoint."""
    with _lock:
        file_cp = int(_read_checkpoint_file().get("committed_update_id") or 0)
    return max(0, file_cp, _legacy_offset())


def claim_update(update_id: int) -> ClaimResult:
    """Gate an update for processing. Read-only — never advances the offset.

    Returns ``already_processed=True`` only when the update has been *committed*
    (``update_id <= committed_offset``). A crash before
    ``commit_checkpoint`` leaves ``already_processed=False`` on the next poll,
    so the update is re-delivered rather than lost.
    """
    uid = _coerce_update_id(update_id)
    offset = get_checkpoint_offset()
    return ClaimResult(update_id=uid, already_processed=uid <= offset, checkpoint_offset=offset)


def commit_checkpoint(update_id: int) -> int:
    """Advance the durable committed offset to at least ``update_id``.

    The only durable offset write. Call only after the CommunicationEvent has
    been persisted. Monotonic and idempotent.
    """
    uid = _coerce_update_id(update_id)
    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_CHECKPOINT_TABLE} (id, committed_update_id, updated_at)
                    VALUES (1, %s, now())
                    ON CONFLICT (id) DO UPDATE SET
                        committed_update_id = GREATEST(
                            {_CHECKPOINT_TABLE}.committed_update_id,
                            EXCLUDED.committed_update_id
                        ),
                        updated_at = now()
                    RETURNING committed_update_id
                    """,
                    (uid,),
                )
                new_offset = int(cur.fetchone()[0])
            conn.commit()
            return new_offset
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    with _lock:
        state = _read_checkpoint_file()
        new_offset = max(int(state.get("committed_update_id") or 0), uid)
        state["committed_update_id"] = new_offset
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json_atomic(_checkpoint_file(), state)
    return new_offset


def is_update_already_processed(update_id: int) -> bool:
    """Replay-denial helper (negative control for tests).

    ``False`` before ``commit_checkpoint``, ``True`` after. Usable as a
    positive/negative control: inject a known id, confirm the detector flips.
    """
    return claim_update(update_id).already_processed


# ── callback quarantine ────────────────────────────────────────────────────────

_QUARANTINE_COLS = (
    "quarantine_id",
    "update_id",
    "reason",
    "callback_query_id",
    "provider_coordinates",
    "quarantined_at",
    "resolved",
    "resolved_at",
    "resolution_note",
)


def _row_to_quarantine(mapped: dict[str, Any]) -> dict[str, Any]:
    coords = mapped.get("provider_coordinates") or {}
    if isinstance(coords, str):
        try:
            coords = json.loads(coords)
        except Exception:
            coords = {}
    qa = mapped.get("quarantined_at")
    ra = mapped.get("resolved_at")
    return {
        "quarantine_id": mapped.get("quarantine_id"),
        "update_id": int(mapped.get("update_id") or 0),
        "reason": mapped.get("reason") or "",
        "callback_query_id": mapped.get("callback_query_id"),
        "provider_coordinates": dict(coords or {}),
        "quarantined_at": qa.isoformat() if hasattr(qa, "isoformat") else (qa or ""),
        "resolved": bool(mapped.get("resolved")),
        "resolved_at": ra.isoformat() if hasattr(ra, "isoformat") else (ra or None),
        "resolution_note": mapped.get("resolution_note"),
    }


def quarantine_callback(
    reason: str,
    provider_coordinates: dict[str, Any] | None,
    update_id: int,
    callback_query_id: str | None = None,
) -> dict[str, Any]:
    """Record an unresolved callback query for operator review.

    Idempotent on ``update_id``: a replayed quarantine of the same update is a
    no-op (returns the existing row). Never answered or dropped silently.
    """
    if not reason or not str(reason).strip():
        raise InboundGateError("quarantine reason required")
    uid = _coerce_update_id(update_id)
    coords = dict(provider_coordinates or {})
    cq_id = callback_query_id if callback_query_id is not None else coords.get("callback_query_id")
    reason_text = str(reason).strip()

    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {_QUARANTINE_TABLE} (
                        update_id, reason, callback_query_id, provider_coordinates
                    ) VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (update_id) DO NOTHING
                    RETURNING quarantine_id, update_id, reason, callback_query_id,
                              provider_coordinates, quarantined_at, resolved,
                              resolved_at, resolution_note
                    """,
                    (uid, reason_text, cq_id, json.dumps(coords)),
                )
                got = cur.fetchone()
            conn.commit()
            if got is None:
                # Already quarantined — return the existing row.
                with conn.cursor() as cur:
                    cur.execute(
                        f"SELECT quarantine_id, update_id, reason, callback_query_id, "
                        f"provider_coordinates, quarantined_at, resolved, resolved_at, "
                        f"resolution_note FROM {_QUARANTINE_TABLE} WHERE update_id = %s",
                        (uid,),
                    )
                    row = cur.fetchone()
                conn.commit()
                if row:
                    return _row_to_quarantine(dict(zip(_QUARANTINE_COLS, row)))
                return _new_quarantine_row(uid, reason_text, cq_id, coords)
            return _row_to_quarantine(dict(zip(_QUARANTINE_COLS, got)))
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass

    with _lock:
        rows = _read_quarantine_file()
        for existing in rows:
            if int(existing.get("update_id") or -1) == uid:
                return dict(existing)
        row = _new_quarantine_row(uid, reason_text, cq_id, coords)
        rows.append(row)
        _write_json_atomic(_quarantine_file(), rows)
    return dict(row)


def _new_quarantine_row(
    uid: int, reason: str, cq_id: str | None, coords: dict[str, Any]
) -> dict[str, Any]:
    return {
        "quarantine_id": None,
        "update_id": uid,
        "reason": reason,
        "callback_query_id": cq_id,
        "provider_coordinates": dict(coords),
        "quarantined_at": datetime.now(timezone.utc).isoformat(),
        "resolved": False,
        "resolved_at": None,
        "resolution_note": None,
    }


def list_quarantined(resolved: bool | None = None) -> list[dict[str, Any]]:
    """Return quarantined callback rows (newest first), optionally filtered."""
    conn = _db_conn()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                base = (
                    f"SELECT quarantine_id, update_id, reason, callback_query_id, "
                    f"provider_coordinates, quarantined_at, resolved, resolved_at, "
                    f"resolution_note FROM {_QUARANTINE_TABLE}"
                )
                if resolved is None:
                    cur.execute(base + " ORDER BY quarantined_at DESC")
                else:
                    cur.execute(
                        base + " WHERE resolved = %s ORDER BY quarantined_at DESC",
                        (resolved,),
                    )
                rows = [_row_to_quarantine(dict(zip(_QUARANTINE_COLS, r))) for r in cur.fetchall()]
            conn.commit()
            return rows
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    with _lock:
        rows = [dict(r) for r in _read_quarantine_file()]
    if resolved is not None:
        rows = [r for r in rows if bool(r.get("resolved")) == bool(resolved)]
    rows.sort(key=lambda r: r.get("quarantined_at") or "", reverse=True)
    return rows


def reset_inbound_state() -> None:
    """Test helper: clear file-backed checkpoint + quarantine to defaults.

    Only touches the configured ``COMMS_INBOUND_STATE_DIR`` (tmp_path in tests).
    Never called by the poller.
    """
    with _lock:
        _write_json_atomic(_checkpoint_file(), {"committed_update_id": 0})
        _write_json_atomic(_quarantine_file(), [])
