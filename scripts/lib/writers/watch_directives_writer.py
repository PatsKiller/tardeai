"""watch_directives_writer.py — THE write module for the `watch_directives` store.

One Source of Truth, phase 9 (AGENTS.md §7A rule 1: one writer per store).

Before this module eighteen files each carried their own INSERT/UPDATE against
watch_directives, so the column list, the dedup rule, the status vocabulary and
the JSON coercion of `spec` could drift between them (and did: five different
creation-time dedup rules, two files that never deduped ticker rows at all,
three different TTL defaults). This module owns:

  * the INSERT column list and parameter order  (`write_watch_directives`)
  * the ONE creation-time dedup rule            (`find_existing_directive`)
  * every UPDATE shape the producers use        (`update_watch_directive` and
    the named wrappers), including the two set-based predicate updates
    (TTL expiry, quiet-directive touch) that are legitimately different rows
  * the plausibility rails: kind / status vocabularies, non-empty label,
    spec is a JSON object, ticker spec carries a plausible symbol, ttl_days a
    non-negative integer
  * identity: a ticker directive's symbol is resolved through the registry-first
    path (identity_registry.lookup_symbol -> resolve_guid, then the
    security_identity spine). The table has NO identity column (see the phase-9
    notes: proposed migration), so the GUID travels in the receipt, never
    invented, never written to a column that does not exist.
  * provenance: `created_by` (the only provenance column the table has) is the
    caller's `source` unless the row names one; `source` and `run_id` are
    carried on the receipt. `written_by` / `written_at` columns do not exist —
    proposed migration, not added here.

Rejected rows are never dropped silently: they come back on the receipt with a
reason and are logged at WARNING.

Every function takes a `target` that is EITHER a DB-API cursor (has `.execute`
and `.fetchone`), a connection (has `.cursor()`), OR an executor callable with
the `db_adapter._execute(sql, params=None, fetch=None)` signature — because the
producers use both styles and a write module that forced one would have made
half of them open a second connection inside another's transaction. Tests
inject a fake cursor; nothing here opens a connection or imports psycopg2.

Nothing here sizes, orders, stops, or touches a broker (MBI_BEHAVIOR = 0).
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.append(_p)  # append, never insert(0): a test's injected paths win

log = logging.getLogger("tradeai.writers.watch_directives")

TABLE = "watch_directives"
KINDS = ("ticker", "sector", "trend")
# The 2026-06-08 migration's CHECK lists the first four; 'expired' (hygiene TTL
# fold, Watch Desk v4 C2) and 'proposed' (family-gate cap, Watch Desk v2 B1) are
# written by legacy producers and read by the UI, so they are part of the
# vocabulary this module accepts. See the notes file for the CHECK discrepancy.
STATUSES = ("active", "paused", "archived", "needs_review", "expired", "proposed")
INSERT_COLUMNS = (
    "kind", "label", "spec", "rationale", "created_by", "status", "priority",
    "ttl_days", "trade_ai_enabled", "hermes_enabled",
)
UPDATE_COLUMNS = (
    "label", "spec", "rationale", "status", "priority", "ttl_days",
    "last_confirmed_at", "cold_since", "last_serviced_at",
)
DEFAULT_STATUS = "active"
DEFAULT_PRIORITY = "normal"
_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-/^=]{0,14}$")


class _Now:
    """Sentinel: set a timestamp column to the database's NOW()."""

    def __repr__(self) -> str:  # pragma: no cover - repr only
        return "NOW"


NOW = _Now()

# ── SQL — the only copies of it ─────────────────────────────────────────────
_INSERT_SQL = (
    "INSERT INTO watch_directives\n"
    "     (kind, label, spec, rationale, created_by, status, priority, ttl_days,\n"
    "      trade_ai_enabled, hermes_enabled)\n"
    "   VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)\n"
    "   RETURNING id"
)
# Exact-label lookup. Legacy fakes in tests/test_two_way_curation.py and
# tests/test_drain_contention.py key on the prefix "SELECT id FROM watch_directives"
# with params (kind, label): keep both.
_SELECT_EXACT_SQL = (
    "SELECT id FROM watch_directives WHERE kind = %s AND label = %s "
    "AND status <> 'archived' ORDER BY id LIMIT 1"
)
_SELECT_ACTIVE_BY_KIND_SQL = (
    "SELECT wd.id, wd.label, wd.spec,\n"
    "       (SELECT count(*) FROM watch_directive_hits h WHERE h.directive_id = wd.id) AS hits\n"
    "  FROM watch_directives wd\n"
    " WHERE wd.kind = %s AND wd.status = 'active'\n"
    " ORDER BY wd.id"
)
_EXPIRE_TTL_SQL = (
    "UPDATE watch_directives\n"
    "   SET status='expired', updated_at=now()\n"
    " WHERE status='active' AND ttl_days IS NOT NULL\n"
    "   AND created_at < now() - (ttl_days || ' days')::interval\n"
    " RETURNING id, label"
)
_TOUCH_QUIET_SQL = (
    "UPDATE watch_directives d\n"
    "   SET last_serviced_at = now(), updated_at = now()\n"
    " WHERE d.status = 'active'\n"
    "   AND (d.last_serviced_at IS NULL\n"
    "        OR d.last_serviced_at < now() - (%s || ' hours')::interval)\n"
    "   AND NOT EXISTS (\n"
    "     SELECT 1 FROM hermes_directive_hits_staging h\n"
    "     WHERE h.directive_id = d.id AND NOT h.drained\n"
    "   )"
)


# ── receipt ─────────────────────────────────────────────────────────────────
@dataclass
class WriteReceipt:
    table: str
    source: str
    operation: str
    run_id: Optional[str] = None
    rows_in: int = 0
    rows_written: int = 0
    rows_rejected: List[Dict[str, Any]] = field(default_factory=list)
    ids: List[int] = field(default_factory=list)
    reused: List[Dict[str, Any]] = field(default_factory=list)
    details: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def directive_id(self) -> Optional[int]:
        """First written id, else first reused id, else None."""
        if self.ids:
            return self.ids[0]
        if self.reused:
            return self.reused[0].get("id")
        return None

    @property
    def ok(self) -> bool:
        return not self.rows_rejected

    def reject(self, row: Any, reason: str) -> None:
        self.rows_rejected.append({"row": row, "reason": reason})
        log.warning("watch_directives write rejected (%s, source=%s): %s", self.operation, self.source, reason)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table, "source": self.source, "operation": self.operation,
            "run_id": self.run_id, "rows_in": self.rows_in, "rows_written": self.rows_written,
            "rows_rejected": [{"reason": r["reason"]} for r in self.rows_rejected],
            "ids": list(self.ids), "reused": [dict(r) for r in self.reused],
        }


class RowRejected(ValueError):
    """A row is off its rail; carried on the receipt, never raised to callers."""


# ── target abstraction (cursor | connection | executor) ─────────────────────
class _Target:
    def __init__(self, target: Any):
        self.cur = None
        self.ex: Optional[Callable[..., Any]] = None
        if hasattr(target, "execute") and hasattr(target, "fetchone"):
            self.cur = target
        elif hasattr(target, "cursor") and callable(getattr(target, "cursor")):
            self.cur = target.cursor()
        elif callable(target):
            self.ex = target
        else:
            raise TypeError("target must be a cursor, a connection, or an executor callable")

    def run(self, sql: str, params: Optional[Sequence[Any]] = None, fetch: Optional[str] = None) -> Any:
        if self.cur is not None:
            self.cur.execute(sql, params)
            if fetch == "one":
                return self.cur.fetchone()
            if fetch == "all":
                return self.cur.fetchall()
            return True
        assert self.ex is not None
        return self.ex(sql, params, fetch=fetch)

    def rowcount(self) -> Optional[int]:
        rc = getattr(self.cur, "rowcount", None) if self.cur is not None else None
        return rc if isinstance(rc, int) and rc >= 0 else None


def _id_of(row: Any) -> Optional[int]:
    if row is None or row is True or row is False:
        return None
    if isinstance(row, dict):
        v = row.get("id")
    elif isinstance(row, (list, tuple)):
        v = row[0] if row else None
    else:
        v = row
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _col(row: Any, key: str, idx: int) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[idx]
    except (IndexError, TypeError, KeyError):
        return None


def _spec_dict(spec: Any) -> Dict[str, Any]:
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, (str, bytes)):
        try:
            v = json.loads(spec or "{}")
            return v if isinstance(v, dict) else {}
        except ValueError:
            return {}
    return {}


def norm_label(s: Any) -> str:
    """Same normalisation as scripts/watch_directive_canonical.norm_label (kept identical)."""
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _canonical_family(label: str) -> Optional[str]:
    try:
        from watch_directive_canonical import canonical_family  # scripts/ on path
    except ImportError:  # pragma: no cover - import layout fallback
        from scripts.watch_directive_canonical import canonical_family  # type: ignore
    return canonical_family(label)


# ── identity (rule a/b/c: registry-first, never minted here) ────────────────
def resolve_directive_subject(kind: str, spec: Any) -> Dict[str, Any]:
    """Subject GUID for a ticker directive, via the existing resolvers only.

    registry-first: identity_registry.lookup_symbol(load_cached(), symbol) — the
    GUID the registry minted for the watch item (watchlist_items.status='active'
    is the minting scope) — followed through resolve_guid so a superseded GUID
    lands on its successor. Fallback: security_identity.resolve_identity_spine
    (issuer -> security -> listing -> ticker alias) and subject_guid_of, which is
    the same alias GUID memory_fact.subject_from_security defines. Sector/trend
    directives have no security subject and get None, honestly.

    Never raises: an unreadable registry must not block a write, and it must
    never mint a plausible GUID. The failure is recorded on the result.
    """
    out: Dict[str, Any] = {"subject_guid": None, "identity_source": None, "symbol": None}
    if kind != "ticker":
        return out
    sd = _spec_dict(spec)
    sym = str(sd.get("symbol") or "").strip().upper()
    if not sym:
        out["identity_reason"] = "no_symbol"
        return out
    out["symbol"] = sym
    try:
        from scripts.lib import identity_registry as ir
        doc = ir.load_cached()
        ent = ir.lookup_symbol(doc, sym)
        if ent and ent.get("subject_guid"):
            out["subject_guid"] = ir.resolve_guid(doc, str(ent["subject_guid"]))
            out["identity_source"] = "registry"
            return out
        from scripts.lib.security_identity import resolve_identity_spine
        spine = resolve_identity_spine({
            "symbol": sym,
            "company": sd.get("company"),
            "cik": sd.get("cik"),
        })
        out["subject_guid"] = ir.subject_guid_of(spine, sym)
        out["identity_source"] = "spine"
        out["identity_status"] = spine.get("identity_status")
    except Exception as e:  # noqa: BLE001 - see docstring
        out["identity_lookup_failed"] = f"{type(e).__name__}: {e}"
    return out


# ── the ONE dedup rule ──────────────────────────────────────────────────────
def find_existing_directive(target: Any, kind: str, label: str, spec: Any = None,
                            *, include_family: bool = True) -> Optional[Dict[str, Any]]:
    """The single creation-time dedup rule (consolidates five legacy variants).

    Precedence, first hit wins:
      1. sector/trend: exact (kind, label) among non-archived  match="label"
         (NOT for ticker: a ticker's label is a list name that several symbols
         legitimately share — "White House Quantum Computing" is on GFS, IBM,
         QBTS and RGTI — so for a ticker the symbol is the key, per identity
         rule (c): the ticker alias, not the label, is what round-trips to
         the subject GUID)
      2. same subject among ACTIVE rows of the same kind:
           ticker -> UPPER(spec.symbol) equal                 match="symbol"
           sector -> spec.finviz_sector / gics_sector equal   match="sector"
           trend  -> spec.finviz_industry equal               match="industry"
      3. sector/trend: normalised label equal among active     match="label_normalized"
      4. trend only, include_family: same canonical family    match="family"
         (survivor = most hits, then oldest — the Watch Desk v2 B1 gate rule)

    Returns {"id", "label", "match", ...} or None. Never raises on a missing
    spec; a lookup that returns no rows simply finds nothing.
    """
    t = target if isinstance(target, _Target) else _Target(target)
    kind = str(kind or "").strip().lower()
    label = str(label or "")
    if kind != "ticker":
        exact = t.run(_SELECT_EXACT_SQL, (kind, label), fetch="one")
        eid = _id_of(exact)
        if eid is not None:
            return {"id": eid, "label": label, "match": "label"}

    sd = _spec_dict(spec)
    sym = str(sd.get("symbol") or "").strip().upper() if kind == "ticker" else ""
    sector = (sd.get("finviz_sector") or sd.get("gics_sector")) if kind == "sector" else None
    industry = sd.get("finviz_industry") if kind == "trend" else None
    norm = norm_label(label) if kind != "ticker" else ""
    fam = _canonical_family(label) if (kind == "trend" and include_family) else None

    rows = t.run(_SELECT_ACTIVE_BY_KIND_SQL, (kind,), fetch="all") or []
    if rows is True:
        rows = []
    by_norm: Optional[Dict[str, Any]] = None
    fam_members: List[Dict[str, Any]] = []
    for r in rows:
        rid = _id_of({"id": _col(r, "id", 0)})
        if rid is None:
            continue
        rlabel = str(_col(r, "label", 1) or "")
        rspec = _spec_dict(_col(r, "spec", 2))
        hits = _col(r, "hits", 3) or 0
        if sym and str(rspec.get("symbol") or "").strip().upper() == sym:
            return {"id": rid, "label": rlabel, "match": "symbol"}
        if sector and sector in (rspec.get("finviz_sector"), rspec.get("gics_sector")):
            return {"id": rid, "label": rlabel, "match": "sector"}
        if industry and rspec.get("finviz_industry") == industry:
            return {"id": rid, "label": rlabel, "match": "industry"}
        if norm and by_norm is None and norm_label(rlabel) == norm:
            by_norm = {"id": rid, "label": rlabel, "match": "label_normalized"}
        if fam and _canonical_family(rlabel) == fam:
            fam_members.append({"id": rid, "label": rlabel, "hits": int(hits or 0)})
    if by_norm:
        return by_norm
    if fam_members:
        surv = min(fam_members, key=lambda m: (-m["hits"], m["id"]))
        return {"id": surv["id"], "label": surv["label"], "match": "family", "family": fam,
                "hits": surv["hits"]}
    return None


# ── coercion + rails ────────────────────────────────────────────────────────
def _coerce_insert_row(row: Dict[str, Any], source: str) -> Dict[str, Any]:
    if not isinstance(row, dict):
        raise RowRejected("row_not_a_dict")
    kind = str(row.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise RowRejected(f"kind_invalid:{kind or 'empty'}")
    label = str(row.get("label") or "").strip()
    if not label:
        raise RowRejected("label_empty")
    spec = row.get("spec")
    if isinstance(spec, (str, bytes)):
        try:
            spec = json.loads(spec)
        except ValueError:
            raise RowRejected("spec_not_json")
    if spec is None:
        raise RowRejected("spec_missing")
    if not isinstance(spec, dict):
        raise RowRejected("spec_not_object")
    if kind == "ticker":
        sym = str(spec.get("symbol") or "").strip().upper()
        if not sym:
            raise RowRejected("ticker_spec_symbol_missing")
        if not _SYMBOL_RE.match(sym):
            raise RowRejected(f"symbol_implausible:{sym[:20]}")
    rationale = row.get("rationale")
    rationale = None if rationale is None else str(rationale)
    created_by = str(row.get("created_by") or source or "").strip()
    if not created_by:
        raise RowRejected("created_by_empty")
    status = str(row.get("status") or DEFAULT_STATUS).strip().lower()
    if status not in STATUSES:
        raise RowRejected(f"status_invalid:{status}")
    priority = str(row.get("priority") or DEFAULT_PRIORITY).strip().lower()
    if not priority or len(priority) > 32:
        raise RowRejected("priority_invalid")
    ttl = row.get("ttl_days")
    if ttl is not None:
        try:
            ttl = int(ttl)
        except (TypeError, ValueError):
            raise RowRejected("ttl_days_invalid")
        if ttl < 0:
            raise RowRejected("ttl_days_negative")
    return {
        "kind": kind, "label": label, "spec": spec, "rationale": rationale,
        "created_by": created_by, "status": status, "priority": priority, "ttl_days": ttl,
        "trade_ai_enabled": bool(row.get("trade_ai_enabled", True)),
        "hermes_enabled": bool(row.get("hermes_enabled", True)),
    }


def _validate_update_fields(fields: Dict[str, Any]) -> Optional[str]:
    if "status" in fields and str(fields["status"]).lower() not in STATUSES:
        return f"status_invalid:{fields['status']}"
    if "label" in fields and not str(fields["label"] or "").strip():
        return "label_empty"
    if "priority" in fields and not str(fields["priority"] or "").strip():
        return "priority_invalid"
    if "spec" in fields:
        sp = fields["spec"]
        if isinstance(sp, (str, bytes)):
            try:
                sp = json.loads(sp)
            except ValueError:
                return "spec_not_json"
        if not isinstance(sp, dict):
            return "spec_not_object"
    if "ttl_days" in fields and fields["ttl_days"] is not None:
        try:
            if int(fields["ttl_days"]) < 0:
                return "ttl_days_negative"
        except (TypeError, ValueError):
            return "ttl_days_invalid"
    for col in ("last_confirmed_at", "cold_since", "last_serviced_at"):
        if col in fields and fields[col] is not None and fields[col] is not NOW:
            return f"{col}_must_be_NOW_or_None"
    return None


# ── public writes ───────────────────────────────────────────────────────────
def write_watch_directives(target: Any, rows: Iterable[Dict[str, Any]], *, source: str,
                           run_id: Optional[str] = None, on_duplicate: str = "reuse",
                           resolve_identity: bool = True) -> WriteReceipt:
    """INSERT watch_directives rows. Returns a WriteReceipt; never raises on bad rows.

    row keys: kind (required), label (required), spec (dict or JSON text, required),
    rationale, created_by (default = `source`), status (default active), priority
    (default normal), ttl_days (default NULL = standing), trade_ai_enabled /
    hermes_enabled (default True).

    on_duplicate: "reuse" (default) applies find_existing_directive and records the
    match on receipt.reused instead of inserting; "reuse_exact" applies only the
    exact/subject/normalised-label rules (no family fold); "insert" writes anyway
    (an operator's explicit force=true).
    """
    if on_duplicate not in ("reuse", "reuse_exact", "insert"):
        raise ValueError("on_duplicate must be reuse|reuse_exact|insert")
    t = _Target(target)
    rec = WriteReceipt(table=TABLE, source=str(source), operation="insert", run_id=run_id)
    for i, row in enumerate(list(rows or [])):
        rec.rows_in += 1
        try:
            clean = _coerce_insert_row(row, source)
        except RowRejected as e:
            rec.reject(row, str(e))
            continue
        ident = resolve_directive_subject(clean["kind"], clean["spec"]) if resolve_identity else {}
        if on_duplicate != "insert":
            found = find_existing_directive(t, clean["kind"], clean["label"], clean["spec"],
                                            include_family=(on_duplicate == "reuse"))
            if found:
                rec.reused.append({**found, "row_index": i, **ident})
                continue
        params = (
            clean["kind"], clean["label"], json.dumps(clean["spec"], default=str), clean["rationale"],
            clean["created_by"], clean["status"], clean["priority"], clean["ttl_days"],
            clean["trade_ai_enabled"], clean["hermes_enabled"],
        )
        res = t.run(_INSERT_SQL, params, fetch="one")
        did = _id_of(res)
        if did is None:
            if res is None:
                rec.reject(row, "db_unavailable:executor_returned_None")
            else:
                rec.reject(row, "insert_returned_no_id")
            continue
        rec.ids.append(did)
        rec.rows_written += 1
        rec.details.append({"row_index": i, "id": did, "kind": clean["kind"], "label": clean["label"],
                            "created_by": clean["created_by"], **ident})
    return rec


def update_watch_directive(target: Any, directive_id: Any, *, source: str,
                           run_id: Optional[str] = None, rationale_append: Optional[str] = None,
                           **fields: Any) -> WriteReceipt:
    """UPDATE one directive (int id) or a set of them (list of ids) — always stamps updated_at.

    Settable columns: label, spec, rationale, status, priority, ttl_days,
    last_confirmed_at, cold_since, last_serviced_at. Timestamp columns take the
    `NOW` sentinel or None (NULL). `rationale_append` appends text to the existing
    rationale (COALESCE(rationale,'')||text). Unknown columns raise ValueError —
    that is a programming error, not a data rail.
    """
    unknown = set(fields) - set(UPDATE_COLUMNS)
    if unknown:
        raise ValueError(f"unknown watch_directives column(s): {sorted(unknown)}")
    if not fields and not rationale_append:
        raise ValueError("update_watch_directive: nothing to update")
    ids: List[int]
    if isinstance(directive_id, (list, tuple, set, frozenset)):
        ids = [int(x) for x in directive_id]
    else:
        ids = [int(directive_id)]
    rec = WriteReceipt(table=TABLE, source=str(source), operation="update", run_id=run_id)
    rec.rows_in = len(ids)
    if not ids:
        return rec
    bad = _validate_update_fields(fields)
    if bad:
        for did in ids:
            rec.reject({"id": did, **{k: v for k, v in fields.items() if k != "spec"}}, bad)
        return rec
    sets: List[str] = []
    params: List[Any] = []
    for col in UPDATE_COLUMNS:
        if col not in fields:
            continue
        v = fields[col]
        if v is NOW:
            sets.append(f"{col}=NOW()")
        elif col == "spec":
            sets.append("spec=%s::jsonb")
            params.append(v if isinstance(v, str) else json.dumps(v, default=str))
        elif col == "status":
            sets.append("status=%s")
            params.append(str(v).lower())
        elif col == "ttl_days":
            sets.append("ttl_days=%s")
            params.append(None if v is None else int(v))
        else:
            sets.append(f"{col}=%s")
            params.append(v)
    if rationale_append:
        sets.append("rationale=COALESCE(rationale,'')||%s")
        params.append(str(rationale_append))
    sets.append("updated_at=NOW()")
    if len(ids) == 1:
        where = "id=%s"
        params.append(ids[0])
    else:
        where = "id = ANY(%s)"
        params.append(ids)
    sql = f"UPDATE watch_directives SET {', '.join(sets)} WHERE {where}"
    t_run = _Target(target)
    res = t_run.run(sql, tuple(params), fetch=None)
    if res is None:
        for did in ids:
            rec.reject({"id": did}, "db_unavailable:executor_returned_None")
        return rec
    rc = t_run.rowcount()
    rec.rows_written = rc if rc is not None else len(ids)
    rec.ids = list(ids)
    rec.details.append({"ids": list(ids), "columns": [c for c in UPDATE_COLUMNS if c in fields]
                        + (["rationale_append"] if rationale_append else [])})
    return rec


def touch_watch_directive_serviced(target: Any, directive_id: Any, *, source: str,
                                   run_id: Optional[str] = None) -> WriteReceipt:
    """last_serviced_at=NOW(), updated_at=NOW() — the servicer heartbeat."""
    return update_watch_directive(target, directive_id, source=source, run_id=run_id,
                                  last_serviced_at=NOW)


def set_watch_directive_status(target: Any, directive_id: Any, status: str, *, source: str,
                               run_id: Optional[str] = None, **extra: Any) -> WriteReceipt:
    """Governed status transition (the caller decides legality; this writes it)."""
    return update_watch_directive(target, directive_id, source=source, run_id=run_id,
                                  status=status, **extra)


def expire_watch_directives_past_ttl(target: Any, *, source: str,
                                     run_id: Optional[str] = None) -> WriteReceipt:
    """active + past ttl_days -> status='expired' (never deleted). Returns the rows folded."""
    t = _Target(target)
    rec = WriteReceipt(table=TABLE, source=str(source), operation="expire_ttl", run_id=run_id)
    rows = t.run(_EXPIRE_TTL_SQL, None, fetch="all")
    if rows is None:
        rec.reject({}, "db_unavailable:executor_returned_None")
        return rec
    rows = [] if rows is True else list(rows)
    rec.rows_in = rec.rows_written = len(rows)
    for r in rows:
        rec.ids.append(_id_of({"id": _col(r, "id", 0)}) or 0)
        rec.details.append({"id": _col(r, "id", 0), "label": _col(r, "label", 1)})
    return rec


def touch_quiet_watch_directives_serviced(target: Any, *, source: str, stale_hours: int = 24,
                                          run_id: Optional[str] = None) -> WriteReceipt:
    """Active directives with no undrained hermes staging and no service in `stale_hours`
    -> last_serviced_at=now(), so the stale-monitor count reflects real backlog only."""
    t = _Target(target)
    rec = WriteReceipt(table=TABLE, source=str(source), operation="touch_quiet", run_id=run_id)
    res = t.run(_TOUCH_QUIET_SQL, (str(int(stale_hours)),), fetch=None)
    if res is None:
        rec.reject({}, "db_unavailable:executor_returned_None")
        return rec
    rc = t.rowcount()
    rec.rows_written = rc if rc is not None else 0
    rec.rows_in = rec.rows_written
    return rec


__all__ = [
    "TABLE", "KINDS", "STATUSES", "INSERT_COLUMNS", "UPDATE_COLUMNS", "NOW",
    "WriteReceipt", "RowRejected",
    "write_watch_directives", "update_watch_directive", "touch_watch_directive_serviced",
    "set_watch_directive_status", "expire_watch_directives_past_ttl",
    "touch_quiet_watch_directives_serviced", "find_existing_directive",
    "resolve_directive_subject", "norm_label",
]
