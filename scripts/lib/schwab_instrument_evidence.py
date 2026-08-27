"""SchwabInstrumentEvidence@v1 — durable identifiers fetched from the broker.

The identity registry can only confirm an entity it has a durable identifier
for. Holdings and e-confirms cover what we have *traded*; the active watch
universe — the names decisions are being formed about — has no CUSIP anywhere in
the system, which is why 361 of 400 entities sit at UNRESOLVED_WITH_REASON.

Schwab's `/marketdata/v1/instruments` returns a CUSIP for a symbol we have never
held, which is exactly the gap. Alpaca does not: its `/v2/assets` payload has no
`cusip` field at all (verified against all 14,281 active US equities), so it
cannot close this and is not used here.

This module owns the evidence store only. Fetching lives in
`scripts/sweep_schwab_instruments.py`; minting stays in the registry. Keeping
them apart means a sweep can be re-run, inspected, or thrown away without ever
touching identity.

Nothing here invents an identifier. A symbol the broker does not resolve is
recorded as a miss with the reason, so the next sweep can tell "we asked and
there is nothing" apart from "we never asked".

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "SchwabInstrumentEvidence@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
EVIDENCE_RELATIVE = Path("data") / "runtime" / "schwab_instrument_evidence.json"

# Durable identifier keys the broker payload may carry. `cusip` is the one Schwab
# actually returns today; the others are here so a later payload that carries
# them is not silently dropped the way the CUSIP was.
BROKER_ID_KEYS = ("cusip", "isin", "figi")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def evidence_path(root: Path | str | None = None) -> Path:
    env = os.environ.get("TRADEAI_SCHWAB_INSTRUMENT_EVIDENCE")
    if env:
        return Path(env)
    if root:
        return Path(root) / EVIDENCE_RELATIVE
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root()) / EVIDENCE_RELATIVE
    except Exception:
        return Path.home() / "trade-ai-releases" / "persistent-state" / EVIDENCE_RELATIVE


def empty_evidence() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "instruments": {},
        "misses": {},
        "updated_at": _now(),
    }


def load(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else evidence_path()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_evidence()
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return empty_evidence()
    doc.setdefault("instruments", {})
    doc.setdefault("misses", {})
    return doc


def save(doc: dict[str, Any], path: Path | str | None = None) -> Path:
    p = Path(path) if path else evidence_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at"] = _now()
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)
    return p


def record_instrument(doc: dict[str, Any], symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Record what the broker returned for one symbol. Absent stays absent.

    A payload with no durable identifier is a miss, not an instrument: recording
    it under `instruments` would let a description-only row look like evidence.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return doc

    identifiers = {}
    for key in BROKER_ID_KEYS:
        val = str(payload.get(key) or "").strip().upper()
        if val:
            identifiers[key] = val

    if not identifiers:
        return record_miss(doc, sym, "no_durable_identifier_in_payload")

    entry: dict[str, Any] = {"identifiers": identifiers, "observed_at": _now()}
    for src, dest in (("description", "description"), ("exchange", "exchange"),
                      ("assetType", "asset_type")):
        val = str(payload.get(src) or "").strip()
        if val:
            entry[dest] = val

    doc.setdefault("instruments", {})[sym] = entry
    doc.setdefault("misses", {}).pop(sym, None)
    return doc


def record_miss(doc: dict[str, Any], symbol: str, reason: str) -> dict[str, Any]:
    """A symbol the broker could not resolve. Recorded so we know we asked."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return doc
    doc.setdefault("misses", {})[sym] = {"reason": str(reason), "observed_at": _now()}
    return doc


def identifier_rows(doc: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Rows in the shape `identity_registry.register()` accepts."""
    src = doc if doc is not None else load()
    rows = []
    for sym, entry in sorted((src.get("instruments") or {}).items()):
        ids = entry.get("identifiers") or {}
        if not ids:
            continue
        row: dict[str, Any] = {"symbol": sym, "identifiers": dict(ids),
                               "source": "schwab_instruments"}
        # The broker description is the issuer name; it fills `issuer_guid` for
        # entities that reached CONFIRMED on a CUSIP alone.
        if entry.get("description"):
            row["company"] = entry["description"]
        if entry.get("exchange"):
            row["exchange"] = entry["exchange"]
        rows.append(row)
    return rows
