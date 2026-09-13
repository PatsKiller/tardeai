"""WriteReceipt -- what a store's write module hands back to its producer.

A rejected row is never silently dropped: it is returned here with its reason
and logged by the writer, so a producer that ignores the receipt still leaves a
trace and a producer that reads it can quarantine or alert.

Identity travels on the receipt, not in the table, for the two Phase 9 price
stores: neither ``market_quotes`` nor ``ticker_prices`` has an identity column
(see docs/implementation/sot/phase9_quotes_prices_notes.md). The resolver is the
existing registry-first path -- ``cio_subject_guid.lookup_subject`` (lookup, no
mint) falling back to ``identity_registry.subject_guid_of(resolve_identity_spine)``
which is security > issuer > ticker alias exactly as ``register()`` keys it.
Nothing here computes a UUID of its own.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

SCHEMA = "WriteReceipt@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

# identity_lookup verdicts. RESOLVED comes from the minted registry; DERIVED_ALIAS
# from the spine when the registry has no entity (the same GUID register() would
# assign, so a later mint does not fork the key); the other two are about the
# lookup, not the symbol -- cio_subject_guid's distinction, kept.
RESOLVED = "RESOLVED"
DERIVED_ALIAS = "DERIVED_ALIAS"
LOOKUP_FAILED = "LOOKUP_FAILED"
NOT_APPLICABLE = "NOT_APPLICABLE"

_SPINE_KEYS = ("symbol", "cik", "company", "exchange", "identifiers",
               "security_guid", "issuer_guid", "classification", "share_class")

log = logging.getLogger("tradeai.writers")


@dataclass
class WriteReceipt:
    table: str
    source: str
    written_by: str
    run_id: str | None = None
    conflict_rule: str = ""
    rows_in: int = 0
    rows_accepted: int = 0          # passed the rails; a statement was issued for them
    rows_written: int = 0           # sum of cursor.rowcount (0 on DO NOTHING conflicts)
    rows_rejected: list[dict[str, Any]] = field(default_factory=list)
    identity: dict[str, str | None] = field(default_factory=dict)   # symbol -> subject_guid
    identity_lookup: dict[str, str] = field(default_factory=dict)   # symbol -> verdict
    statements: int = 0
    schema: str = SCHEMA
    authority: str = AUTHORITY

    def reject(self, row: Any, reason: str) -> None:
        self.rows_rejected.append({"row": _plain(row), "reason": reason})
        log.warning("[%s] rejected row (%s): %s", self.table, reason, _plain(row))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authority": self.authority,
            "table": self.table,
            "source": self.source,
            "written_by": self.written_by,
            "run_id": self.run_id,
            "conflict_rule": self.conflict_rule,
            "rows_in": self.rows_in,
            "rows_accepted": self.rows_accepted,
            "rows_written": self.rows_written,
            "rows_rejected": list(self.rows_rejected),
            "identity": dict(self.identity),
            "identity_lookup": dict(self.identity_lookup),
            "statements": self.statements,
        }


def _plain(row: Any) -> Any:
    if isinstance(row, dict):
        return {str(k): (v if isinstance(v, (int, float, str, bool)) or v is None else str(v))
                for k, v in row.items()}
    return str(row)


def cursor_of(conn_or_cursor: Any):
    """Accept a psycopg2 connection or cursor (or a test fake of either)."""
    if hasattr(conn_or_cursor, "execute"):
        return conn_or_cursor
    if hasattr(conn_or_cursor, "cursor"):
        return conn_or_cursor.cursor()
    raise TypeError(f"expected a connection or cursor, got {type(conn_or_cursor).__name__}")


def rowcount_of(cur: Any) -> int:
    rc = getattr(cur, "rowcount", None)
    try:
        return int(rc) if rc is not None and int(rc) >= 0 else 0
    except (TypeError, ValueError):
        return 0


def resolve_subject_identity(row: dict[str, Any]) -> tuple[str | None, str]:
    """(subject_guid, verdict) for one row, through the existing resolvers only.

    Registry first (``lookup_subject``: the minted, supersede-chained registry,
    read via ``TRADEAI_IDENTITY_REGISTRY`` when set). If the registry has no
    entity, ``subject_guid_of(resolve_identity_spine(row), symbol)`` gives the
    GUID ``register()`` would mint for the same row -- issuer-derived when the
    row carries cik/company, otherwise the ticker alias defined once in
    ``memory_fact.subject_from_security``. Never NULL for a non-empty symbol
    unless the resolver itself could not run, and that is reported as
    LOOKUP_FAILED rather than as an absent identity.
    """
    sym = str((row or {}).get("symbol") or "").strip().upper()
    if not sym:
        return None, NOT_APPLICABLE
    try:
        from scripts.lib.cio_subject_guid import lookup_subject, NOT_APPLICABLE as _NA, RESOLVED as _RES
        hit = lookup_subject(sym)
        if hit.get("identity_lookup") == _NA:
            return None, NOT_APPLICABLE
        if hit.get("identity_lookup") == _RES and hit.get("subject_guid"):
            return str(hit["subject_guid"]), RESOLVED
        from scripts.lib.identity_registry import subject_guid_of
        from scripts.lib.security_identity import resolve_identity_spine
        spine = resolve_identity_spine({k: v for k, v in row.items() if k in _SPINE_KEYS})
        guid = subject_guid_of(spine, sym)
        return (str(guid), DERIVED_ALIAS) if guid else (None, LOOKUP_FAILED)
    except Exception as exc:  # the lookup failed; that is not "no identity"
        log.warning("[identity] lookup failed for %s: %s", sym, type(exc).__name__)
        return None, LOOKUP_FAILED


def attach_identity(receipt: WriteReceipt, rows: list[dict[str, Any]]) -> None:
    """Resolve each distinct symbol once and record it on the receipt."""
    for row in rows:
        sym = str((row or {}).get("symbol") or "").strip().upper()
        if not sym or sym in receipt.identity_lookup:
            continue
        guid, verdict = resolve_subject_identity(row)
        receipt.identity[sym] = guid
        receipt.identity_lookup[sym] = verdict
