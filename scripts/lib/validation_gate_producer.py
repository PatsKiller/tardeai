"""Validation-gate declaration producer (LQ-20261107-2966; closes REVIEW-2963 (c): nothing produced declarations).

Pure logic. ``build_decls`` turns the catalog ``config/validation_gate_declarations.json`` into
``ValidationGateDecl@v1`` documents, each validated by ``validation_gates.parse_decl`` against the named-query file.
Rules enforced here, not just documented:

* only machine-evaluable evidence: ``manual_evidence`` and any ``close`` block are refused (a producer must never
  pre-pass or close a gate);
* ``lane_fresh`` reads ``data/runtime/<lane_id>_last.json``; the other kinds name a query that exists in the query file;
* a gate already declared (file in ``ingested/`` or ``inbox/``) is never rewritten: if the catalog now says something
  different about its check, ``blocks_trading`` or kind, that is DRIFT and is reported and skipped, so the producer
  itself cannot loosen a gate. (The sync's freeze refuses it a second time.)

Authority: writes declaration files under <state>/data/coordination/validation_gates/inbox only. No DB, no broker.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from lib import validation_gates as VG

CATALOG_SCHEMA = "ValidationGateCatalog@v1"
DECLARED_BY = "validation-gate-producer"
_ENTRY_KEYS = {"gate_id", "title", "category", "blocks", "lq_id", "owner", "due_in_h", "check_kind", "check_spec",
               "evidence", "blocks_trading", "fix_ref"}
_FROZEN_VIEW = ("check_kind", "check_spec", "blocks_trading")


class CatalogError(ValueError):
    pass


def gates_dir(root: Path) -> Path:
    return root / "data" / "coordination" / "validation_gates"


def build_decls(catalog: Mapping[str, Any], *, queries: Mapping[str, Any], now: datetime) -> list[dict]:
    """Validated declaration documents (without the ``sha256`` key parse_decl adds). Raises CatalogError."""
    if not isinstance(catalog, Mapping) or catalog.get("schema") != CATALOG_SCHEMA:
        raise CatalogError(f"schema must be {CATALOG_SCHEMA}")
    out, seen = [], set()
    for entry in catalog.get("gates") or []:
        gid = entry.get("gate_id") if isinstance(entry, Mapping) else None
        if set(entry) - _ENTRY_KEYS:
            raise CatalogError(f"{gid}: unknown keys {sorted(set(entry) - _ENTRY_KEYS)}")
        if gid in seen:
            raise CatalogError(f"duplicate gate_id {gid}")
        seen.add(gid)
        kind = entry.get("check_kind")
        if kind == "manual_evidence":
            raise CatalogError(f"{gid}: a producer may not declare manual_evidence gates (no self-certification)")
        if not str(entry.get("evidence") or "").strip():
            raise CatalogError(f"{gid}: 'evidence' must say what real signal the check reads")
        due_in = entry.get("due_in_h")
        if isinstance(due_in, bool) or not isinstance(due_in, (int, float)) or due_in <= 0:
            raise CatalogError(f"{gid}: due_in_h must be a number > 0")
        doc = {"schema": VG.DECL_SCHEMA, "gate_id": gid, "title": entry.get("title"), "category": entry.get("category"),
               "blocks": entry.get("blocks"), "owner": entry.get("owner"), "declared_by": DECLARED_BY,
               "opened_at": now.astimezone(timezone.utc).isoformat(),
               "due_at": (now + timedelta(hours=float(due_in))).astimezone(timezone.utc).isoformat(),
               "check_kind": kind, "check_spec": entry.get("check_spec") or {}}
        for k in ("lq_id", "blocks_trading", "fix_ref"):
            if entry.get(k) is not None:
                doc[k] = entry[k]
        try:
            VG.parse_decl(doc, queries=queries)
        except VG.DeclError as exc:
            raise CatalogError(f"{gid}: {exc}") from exc
        out.append(doc)
    if not out:
        raise CatalogError("catalog declares no gates")
    return out


def _load(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _view(doc: Mapping[str, Any]) -> dict:
    d = {k: doc.get(k) for k in _FROZEN_VIEW}
    d["blocks_trading"] = doc.get("blocks_trading")  # absent == null == not declared
    return d


def plan(decls: list[dict], *, root: Path) -> list[dict]:
    """One row per gate: action write | unchanged | drift. Never touches the disk."""
    base = gates_dir(root)
    rows = []
    for d in decls:
        existing = None
        where = None
        for sub in ("inbox", "ingested"):
            f = base / sub / f"{d['gate_id']}.json"
            if f.is_file():
                existing, where = _load(f), sub
                break
        if where is None:
            rows.append({"gate_id": d["gate_id"], "action": "write", "check_kind": d["check_kind"]})
        elif existing is not None and _view(existing) == _view(d):
            rows.append({"gate_id": d["gate_id"], "action": "unchanged", "where": where})
        else:
            rows.append({"gate_id": d["gate_id"], "action": "drift", "where": where,
                         "reason": "the catalog now differs from the declared check / blocks_trading; a declared "
                                   "gate cannot change, declare a new gate_id"})
    return rows


def write_pending(decls: list[dict], rows: list[dict], *, root: Path) -> list[Path]:
    """Write the 'write' rows atomically into inbox/. Returns the paths written."""
    inbox = gates_dir(root) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    by_id = {d["gate_id"]: d for d in decls}
    written = []
    for r in rows:
        if r["action"] != "write":
            continue
        target = inbox / f"{r['gate_id']}.json"
        tmp = inbox / f".{r['gate_id']}.json.tmp"
        tmp.write_text(json.dumps(by_id[r["gate_id"]], indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(target)
        written.append(target)
    return written
