"""Identity carriage helpers — stamp registry GUIDs on durable writes.

Lookup only (never mint). SECURITY rows must carry a registry UUID, not a
ticker, smoke-guid, or subject_key. Used by InstrumentRecord, theses, spine,
Hermes enforce, and watchlist durable writers (CADI identity 4/5).
"""
from __future__ import annotations

import re
from typing import Any

# UUIDv4/v5 hex form (registry uses UUIDv5).
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_FORBIDDEN_GUIDS = frozenset({
    "smoke-guid",
    "missing_registry",
    "guid-nflx",
    "none",
    "null",
    "undefined",
})


def is_registry_guid(value: Any) -> bool:
    if value is None:
        return False
    s = str(value).strip()
    if not s or s.lower() in _FORBIDDEN_GUIDS:
        return False
    if ":" in s:  # subject_key / tradeai:entity:* / HELD:SYM
        return False
    return bool(_UUID_RE.match(s))


def resolve_security_identity(symbol: str, *, root: Any = None) -> dict[str, Any]:
    """Registry envelope for a ticker; empty guids on miss. Never raises."""
    sym = str(symbol or "").strip().upper()
    out: dict[str, Any] = {
        "symbol": sym or None,
        "subject_guid": None,
        "issuer_guid": None,
        "security_guid": None,
        "identity_status": "UNRESOLVED",
        "identity_lookup": "NOT_APPLICABLE" if not sym else "UNRESOLVED",
    }
    if not sym or sym in {"CASH", "PORTFOLIO", "MMKT", "BOOK"}:
        return out
    try:
        from scripts.lib.cio_subject_guid import lookup_identity_envelope
        env = lookup_identity_envelope(sym, root=root)
    except Exception as exc:  # noqa: BLE001
        out["identity_lookup"] = "LOOKUP_FAILED"
        out["identity_lookup_reason"] = type(exc).__name__
        return out
    out["subject_guid"] = env.get("subject_guid") if is_registry_guid(env.get("subject_guid")) else None
    out["issuer_guid"] = env.get("issuer_guid") if is_registry_guid(env.get("issuer_guid")) else None
    out["security_guid"] = env.get("security_guid") if is_registry_guid(env.get("security_guid")) else None
    out["identity_status"] = env.get("identity_status") or out["identity_status"]
    out["identity_lookup"] = env.get("identity_lookup") or out["identity_lookup"]
    out["identity_lookup_reason"] = env.get("identity_lookup_reason")
    return out


def stamp_security_fields(
    row: dict[str, Any],
    *,
    symbol: str | None = None,
    root: Any = None,
    require_resolved: bool = False,
) -> dict[str, Any]:
    """Copy row and stamp subject_guid/issuer_guid from registry when resolvable.

    If require_resolved and symbol resolves nowhere, sets
    ``identity_stamp_miss=True`` (caller decides whether to refuse).
    """
    out = dict(row or {})
    sym = str(symbol or out.get("symbol") or "").strip().upper()
    if not sym and out.get("symbols"):
        syms = out.get("symbols") or []
        if isinstance(syms, list) and syms:
            sym = str(syms[0] or "").strip().upper()
    if not sym:
        return out
    # Keep a good existing registry GUID; never keep smoke/ticker-as-guid.
    existing = out.get("subject_guid")
    if is_registry_guid(existing) and not out.get("issuer_guid"):
        # Enrich issuer if missing
        env = resolve_security_identity(sym, root=root)
        if env.get("issuer_guid"):
            out["issuer_guid"] = env["issuer_guid"]
        out.setdefault("identity_status", env.get("identity_status"))
        return out
    if is_registry_guid(existing):
        return out
    env = resolve_security_identity(sym, root=root)
    if env.get("subject_guid"):
        out["subject_guid"] = env["subject_guid"]
        if env.get("issuer_guid"):
            out["issuer_guid"] = env["issuer_guid"]
        if env.get("security_guid"):
            out["security_guid"] = env["security_guid"]
        out["identity_status"] = env.get("identity_status")
        out["identity_lookup"] = env.get("identity_lookup")
        out.pop("identity_stamp_miss", None)
    else:
        # Drop non-registry junk
        if existing is not None and not is_registry_guid(existing):
            out["subject_guid"] = None
        if require_resolved:
            out["identity_stamp_miss"] = True
            out["identity_lookup"] = env.get("identity_lookup")
            out["identity_lookup_reason"] = env.get("identity_lookup_reason")
    out.setdefault("symbol", sym)
    return out


def linked_subject_guids(symbols: list[Any] | None, *, root: Any = None) -> list[str]:
    guids: list[str] = []
    seen: set[str] = set()
    for raw in symbols or []:
        sym = str(raw or "").strip().upper()
        if not sym:
            continue
        env = resolve_security_identity(sym, root=root)
        g = env.get("subject_guid")
        if g and g not in seen:
            seen.add(g)
            guids.append(g)
    return guids
