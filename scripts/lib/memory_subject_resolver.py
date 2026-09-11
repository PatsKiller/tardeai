"""Canonical identity + subject resolution for L2 memory grounding.

Compatibility accepts memory_id / fact_id / id and subject_guid / UUID-shaped
subject only through explicit deterministic normalization. Conflicting identity
fields fail closed. Human-readable subject titles are NEVER treated as GUIDs.

Symbol→subject resolution goes through cio_subject_guid.lookup_subject with a
positive control. LOOKUP_FAILED / import failure is a hard negative — never a
published zero.

Authority: cognition only. Never mints identities.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping

SCHEMA_VERSION = "MemorySubjectResolver@v1"
SYMBOL_RESOLVE_FLAG = "WAKE_MEMORY_SYMBOL_RESOLVE"

# UUID shape (accepts any UUID version / variant the store may carry).
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# Positive-control symbol that MUST resolve. Mirrors the live detector control.
POSITIVE_CONTROL_SYMBOL = "NVDA"


class ResolverFailure(RuntimeError):
    """Hard negative: registry/import/function failure. Do not publish a zero."""


@dataclass(frozen=True)
class IdentityResolution:
    memory_id: str | None
    error: str | None  # missing_id | conflicting_ids | None


@dataclass(frozen=True)
class SubjectFieldResolution:
    subject_guid: str | None
    source_subject_or_symbol: str | None
    error: str | None  # conflicting_subjects | None


def symbol_resolve_enabled(env: Mapping[str, str] | None = None) -> bool:
    e = env if env is not None else os.environ
    return str(e.get(SYMBOL_RESOLVE_FLAG, "1")).strip().lower() in {"1", "true", "yes", "on"}


def looks_like_guid(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if not _UUID_RE.match(text):
        return False
    try:
        uuid.UUID(text)
    except (ValueError, AttributeError):
        return False
    return True


def normalize_memory_id(row: Mapping[str, Any]) -> IdentityResolution:
    """Accept fact_id / id / memory_id when unambiguous; reject conflicts."""
    present: list[str] = []
    for key in ("fact_id", "id", "memory_id"):
        raw = row.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            present.append(text)
    if not present:
        return IdentityResolution(None, "missing_id")
    unique = set(present)
    if len(unique) > 1:
        return IdentityResolution(None, "conflicting_ids")
    return IdentityResolution(next(iter(unique)), None)


def normalize_subject_fields(row: Mapping[str, Any]) -> SubjectFieldResolution:
    """Normalize subject_guid vs subject.

    - subject_guid (non-empty) is authoritative when present.
    - subject is accepted as a GUID alias ONLY when UUID-shaped.
    - A human-readable subject title becomes source_subject_or_symbol, never a GUID.
    - If both yield GUID values and they disagree → conflicting_subjects.
    """
    guid_raw = row.get("subject_guid")
    sub_raw = row.get("subject")

    guid: str | None = None
    if guid_raw is not None and str(guid_raw).strip() != "":
        guid = str(guid_raw).strip()

    title: str | None = None
    subject_as_guid: str | None = None
    if sub_raw is not None and str(sub_raw).strip() != "":
        text = str(sub_raw).strip()
        if looks_like_guid(text):
            subject_as_guid = text
        else:
            title = text

    if guid and subject_as_guid and guid != subject_as_guid:
        return SubjectFieldResolution(None, title, "conflicting_subjects")

    resolved = guid or subject_as_guid
    source = title
    if not source:
        # Prefer first symbol as human source hint when no title.
        symbols = symbols_of(row)
        source = symbols[0] if symbols else None
    return SubjectFieldResolution(resolved, source, None)


def symbols_of(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("symbols")
    if raw is None and row.get("symbol") is not None:
        raw = [row.get("symbol")]
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip().upper()
        if text and text not in out:
            out.append(text)
    return out


def _default_lookup(symbol: str) -> dict[str, Any]:
    """Canonical deterministic resolver. Import failures raise ResolverFailure."""
    try:
        from scripts.lib.cio_subject_guid import LOOKUP_FAILED, lookup_subject
    except Exception as exc:  # import failure is a hard negative
        raise ResolverFailure(f"cio_subject_guid import failed: {type(exc).__name__}: {exc}") from exc
    try:
        got = lookup_subject(symbol)
    except Exception as exc:
        raise ResolverFailure(f"lookup_subject failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(got, dict):
        raise ResolverFailure("lookup_subject returned non-dict")
    if got.get("identity_lookup_failed") or got.get("identity_lookup") == LOOKUP_FAILED:
        raise ResolverFailure(f"lookup_subject LOOKUP_FAILED for {symbol!r}: {got.get('identity_lookup_reason')}")
    return got


def assert_positive_control(
    lookup: Callable[[str], dict[str, Any]] | None = None,
    *,
    symbol: str = POSITIVE_CONTROL_SYMBOL,
) -> str:
    """Refuse to publish a zero if the positive control does not resolve."""
    fn = lookup or _default_lookup
    got = fn(symbol)
    guid = got.get("subject_guid") if isinstance(got, dict) else None
    if not guid:
        raise ResolverFailure(f"positive control {symbol!r} did not resolve; refusing to publish zero")
    return str(guid)


def resolve_symbol_guid(
    symbol: str,
    *,
    lookup: Callable[[str], dict[str, Any]] | None = None,
    require_positive_control: bool = False,
) -> str | None:
    """Resolve one symbol. LOOKUP_FAILED raises; UNRESOLVED returns None."""
    fn = lookup or _default_lookup
    if require_positive_control:
        assert_positive_control(fn)
    got = fn(symbol)
    guid = got.get("subject_guid") if isinstance(got, dict) else None
    return str(guid) if guid else None


# Disposition taxonomy (fail-closed; never loads globally on miss).
# match / match_resolved → eligible for this subject
# cross → wrong_subject (zero eligibility)
# unmatched → unresolved_subject (no global recall)
# ambiguous → mixed/conflicting identity (fail closed)
# conflicting_subjects → row-level subject field conflict


def row_subject_disposition(
    row: Mapping[str, Any],
    subject_guid: str,
    *,
    env: Mapping[str, str] | None = None,
    lookup: Callable[[str], dict[str, Any]] | None = None,
) -> str:
    """Classify row relevance for a wake subject.

    Missing subject never falls back to global recall.
    Mixed / ambiguous identity fails closed.
    """
    fields = normalize_subject_fields(row)
    if fields.error == "conflicting_subjects":
        return "conflicting_subjects"

    if fields.subject_guid:
        return "match" if str(fields.subject_guid) == str(subject_guid) else "cross"

    if not symbol_resolve_enabled(env):
        return "unmatched"

    symbols = symbols_of(row)
    if not symbols:
        return "unmatched"

    resolved: set[str] = set()
    for sym in symbols:
        g = resolve_symbol_guid(sym, lookup=lookup)
        if g:
            resolved.add(g)
    if not resolved:
        return "unmatched"
    if len(resolved) > 1:
        return "ambiguous"
    return "match_resolved" if next(iter(resolved)) == str(subject_guid) else "cross"
