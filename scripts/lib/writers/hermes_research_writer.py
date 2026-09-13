"""hermes_research_intelligence — the one write module (One Source of Truth, Phase 9).

WHY
---
On 2026-09-13 thirty-two files carried their own ``INSERT INTO`` / ``UPDATE
hermes_research_intelligence`` SQL. Plural producers are by design — eight lanes
legitimately stage research — but plural *write paths* are not: every file chose
its own column list, its own coercions (``'{"a","b"}'`` text literals next to
``ARRAY[...]`` next to Python lists), its own defaults, and none of them set the
identity columns the registry declares required (``subject_guid``). The Finviz
incident (a 1–5 rating column holding ten-year performance for five months) was
exactly this class of defect. From here on the SQL for this table lives in this
module and nowhere else; ``check_data_source_authority.py`` counts the files that
write the table and fails when the count rises.

WHAT IT OWNS
------------
* the column allowlist (DDL 2026-05-30 + every additive ALTER since),
* coercion: JSONB from dict/list/str, TEXT[] from list or ``{...}`` literal,
  booleans rendered as SQL literals, NOW()/CURRENT_DATE sentinels,
* plausibility rails that mirror the table's CHECK constraints
  (``confidence_score`` in [0, 1], ``thesis_type`` and ``status`` enums,
  NOT NULL ``research_type``/``topic``/``summary``),
* identity: ``subject_guid``/``issuer_guid``/``identity_status``/
  ``identity_tagged_at`` populated registry-first (``identity_registry`` →
  ``security_identity`` spine), never minted locally, never a ticker,
* provenance: ``source`` (origin, CHECK 'hermes' in the DDL), ``hermes_agent_name``
  (producer), ``model_used`` — the columns the table actually has. There is no
  ``run_id``/``written_by``/``written_at`` column; the receipt carries them and
  the notes file proposes the migration.

Rejected rows are never silently dropped: they come back on the receipt with a
reason and are logged.

AUTHORITY: READ_ONLY_ADVISORY. Research rows only. No prices, no positions, no
orders, no broker. MBI = 0.
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "HermesResearchWriteReceipt@v1"
TABLE = "hermes_research_intelligence"
WRITTEN_BY = "scripts/lib/writers/hermes_research_writer.py"

#: The two statement heads, spelled out as literals on purpose: the authority gate
#: (check_data_source_authority.count_writers) counts files whose SOURCE matches
#: ``(INSERT INTO|UPDATE|COPY) hermes_research_intelligence``. This file must be
#: that one file, and it must be counted for the SQL it emits — not for a docstring.
INSERT_HEAD = "INSERT INTO hermes_research_intelligence"
UPDATE_HEAD = "UPDATE hermes_research_intelligence"

_ROOT = Path(__file__).resolve().parents[3]
log = logging.getLogger("hermes_research_writer")

# ── column contract ──────────────────────────────────────────────────────────

#: Canonical INSERT order. Every column the table has, from the 2026-05-30 DDL
#: plus each additive ALTER (content_tags 08-04, provenance columns, identity
#: tags, trade_instances, health-learning columns). Order is stable so a
#: recorded INSERT is diffable; JSON payloads deliberately last.
COLUMNS: tuple[str, ...] = (
    "created_at", "updated_at",
    "source", "hermes_agent_name", "research_type", "symbol",
    "related_trade_id", "related_proposal_id", "trade_instance_id",
    "topic", "summary", "thesis", "thesis_type",
    "confidence_score", "quality_score", "freshness_date",
    "model_used", "prompt_hash", "context_type_used", "status",
    "promoted_to_table", "promoted_to_id", "reviewed_by", "reviewed_at",
    "tags", "strategy_tags", "agent_tags", "content_tags",
    "pattern_signature", "category_lifecycle", "category_content", "category_sector",
    "threshold_adjusted", "new_pattern_discovered", "learning_cycle",
    "remediation_success", "remediation_duration_ms",
    "trigger_source", "trigger_id", "budget_tier", "budget_decision", "lane_used",
    "research_expires_at", "downstream_outcome", "taxonomy_tagged_at",
    "subject_guid", "issuer_guid", "gics_sector", "identity_status", "identity_tagged_at",
    "evidence_json", "source_urls_json",
)
INSERTABLE = frozenset(COLUMNS)
UPDATABLE = frozenset(c for c in COLUMNS if c != "created_at")

JSONB_COLUMNS = frozenset({"evidence_json", "source_urls_json"})
ARRAY_COLUMNS = frozenset({"tags", "strategy_tags", "agent_tags", "content_tags"})
BOOL_COLUMNS = frozenset({"threshold_adjusted", "new_pattern_discovered", "remediation_success"})
FLOAT_COLUMNS = frozenset({"confidence_score", "quality_score"})
INT_COLUMNS = frozenset({"related_trade_id", "related_proposal_id", "trade_instance_id",
                         "promoted_to_id", "learning_cycle", "remediation_duration_ms"})
IDENTITY_COLUMNS: tuple[str, ...] = ("subject_guid", "issuer_guid", "identity_status", "identity_tagged_at")

#: Keys a producer may pass as identity *hints*. They are consumed by the
#: resolver and never written — they are not columns.
IDENTITY_HINT_KEYS = frozenset({"cik", "company", "identifiers", "exchange",
                                "security_guid", "listing_guid", "classification", "share_class"})

#: CHECK constraints from the DDL, mirrored as rails so a bad value is rejected
#: here with a reason instead of surfacing as a constraint error (or, worse, not
#: surfacing at all because a writer swallowed the exception).
REQUIRED_TEXT = ("research_type", "topic", "summary")
THESIS_TYPES = frozenset({"bullish", "bearish", "neutral", "mixed"})
STATUSES = frozenset({"staged", "reviewed", "promoted", "rejected", "archived"})
NON_ENTITY_SYMBOLS = frozenset({"CASH", "PORTFOLIO", "MMKT"})


class SqlExpr:
    """A SQL expression rendered verbatim into VALUES/SET (no parameter)."""

    __slots__ = ("text",)

    def __init__(self, text: str):
        self.text = text

    def __repr__(self) -> str:  # pragma: no cover
        return f"SqlExpr({self.text!r})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SqlExpr) and other.text == self.text

    def __hash__(self) -> int:
        return hash(self.text)


SQL_NOW = SqlExpr("NOW()")
SQL_CURRENT_DATE = SqlExpr("CURRENT_DATE")


class ResearchWriteError(ValueError):
    """Raised for a misuse that must never reach the database (e.g. UPDATE with no WHERE)."""


@dataclass
class WriteReceipt:
    schema: str = SCHEMA
    table: str = TABLE
    op: str = "insert"
    source: str = "hermes"
    producer: str | None = None
    run_id: str | None = None
    written_by: str = WRITTEN_BY
    rows_in: int = 0
    rows_written: int = 0
    rows_rejected: list[dict[str, Any]] = field(default_factory=list)
    ids: list[Any] = field(default_factory=list)
    identity: dict[str, Any] = field(default_factory=dict)
    dropped_columns: list[str] = field(default_factory=list)
    sql: list[str] = field(default_factory=list)
    authority: str = AUTHORITY
    financial_action: bool = False

    @property
    def rejected(self) -> int:
        return len(self.rows_rejected)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "table": self.table, "op": self.op, "source": self.source,
            "producer": self.producer, "run_id": self.run_id, "written_by": self.written_by,
            "rows_in": self.rows_in, "rows_written": self.rows_written,
            "rows_rejected": list(self.rows_rejected), "ids": list(self.ids),
            "identity": dict(self.identity), "dropped_columns": list(self.dropped_columns),
            "authority": self.authority, "financial_action": self.financial_action,
        }


# ── execution shim ───────────────────────────────────────────────────────────


def _run(target: Any, sql: str, params: Sequence[Any], *, want_row: bool = False,
         want_rows: bool = False) -> tuple[Any, int]:
    """Execute against a DB-API cursor OR a db_adapter-style ``fn(sql, params, fetch=)``.

    Returns (fetched, rowcount). rowcount is -1 when the target cannot report it.
    """
    if hasattr(target, "execute"):
        target.execute(sql, tuple(params))
        fetched = None
        if want_row:
            fetched = target.fetchone()
        elif want_rows:
            fetched = target.fetchall()
        rc = getattr(target, "rowcount", None)
        return fetched, (int(rc) if isinstance(rc, int) else -1)
    if callable(target):
        fetch = "one" if want_row else ("all" if want_rows else None)
        fetched = target(sql, tuple(params), fetch=fetch)
        return (fetched if fetch else None), -1
    raise ResearchWriteError("target must be a cursor with .execute or a callable(sql, params, fetch=)")


def _first(fetched: Any) -> Any:
    """The first column of a fetched row, whether tuple or dict (RealDictCursor)."""
    if fetched is None:
        return None
    if isinstance(fetched, Mapping):
        return next(iter(fetched.values()), None)
    try:
        return fetched[0]
    except (TypeError, IndexError, KeyError):
        return None


# ── identity ─────────────────────────────────────────────────────────────────


def _identity_modules():
    """identity_registry + security_identity, importable from any producer's sys.path."""
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from scripts.lib import identity_registry, security_identity  # noqa: PLC0415
    return identity_registry, security_identity


def resolve_subject_identity(row: Mapping[str, Any], *, registry: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Registry-first identity for one research row. Lookup, then spine. Never mints.

    Order (rule b of the Phase 9 brief):
      1. an explicit ``subject_guid`` on the row is kept, upgraded along the
         registry's supersede chain (``identity_registry.resolve_guid``);
      2. ``symbol`` → ``identity_registry.lookup_symbol`` → ``subject_guid_of``
         (security > issuer > alias, exactly what ``backfill_research_identity``
         writes, so a write-time GUID equals the backfill's GUID);
      3. a registry miss with ``cik``/``company``/``identifiers`` on the row →
         ``security_identity.resolve_identity_spine`` → issuer-derived security GUID
         (CANDIDATE) or identifier-derived (CONFIRMED). Deterministic, no mint;
      4. otherwise NULL with a reason. A bare ticker is an alias, not an identity,
         and the registry's alias GUID is minted by the registry — not here.
    """
    out: dict[str, Any] = {"subject_guid": None, "issuer_guid": None, "identity_status": None,
                           "identity_lookup": None, "identity_reason": None}
    sym = str(row.get("symbol") or "").strip().upper()
    explicit = row.get("subject_guid")
    try:
        R, S = _identity_modules()
    except Exception as exc:  # registry code unavailable: say so, do not guess
        out["identity_lookup"] = "LOOKUP_FAILED"
        out["identity_reason"] = f"identity_modules_unavailable:{type(exc).__name__}"
        if explicit:
            out["subject_guid"] = str(explicit)
            out["issuer_guid"] = row.get("issuer_guid")
            out["identity_status"] = row.get("identity_status")
        return out

    doc: Mapping[str, Any]
    if registry is not None:
        doc = registry
    else:
        try:
            doc = R.load_cached()
        except Exception as exc:
            doc = {}
            out["identity_lookup"] = "LOOKUP_FAILED"
            out["identity_reason"] = f"registry_unreadable:{type(exc).__name__}"

    if explicit:
        out["subject_guid"] = R.resolve_guid(doc, str(explicit)) or str(explicit)
        out["issuer_guid"] = row.get("issuer_guid")
        out["identity_status"] = row.get("identity_status")
        out["identity_lookup"] = "EXPLICIT"
        return out

    if sym and sym not in NON_ENTITY_SYMBOLS and doc:
        ent = R.lookup_symbol(doc, sym)
        if ent:
            guid = R.subject_guid_of(ent, sym)
            if guid:
                out.update({"subject_guid": guid, "issuer_guid": ent.get("issuer_guid"),
                            "identity_status": ent.get("identity_status") or "UNRESOLVED",
                            "identity_lookup": "REGISTRY"})
                return out

    hints = {k: row.get(k) for k in ("cik", "company", "identifiers", "exchange",
                                     "security_guid", "listing_guid", "classification", "share_class")
             if row.get(k) not in (None, "", {})}
    if hints:
        spine = S.resolve_identity_spine({"symbol": sym, **hints})
        guid = spine.get("security_guid") or spine.get("issuer_guid")
        if guid:
            out.update({"subject_guid": guid, "issuer_guid": spine.get("issuer_guid"),
                        "identity_status": spine.get("identity_status"),
                        "identity_lookup": "SPINE"})
            return out

    if not sym:
        out["identity_lookup"] = out["identity_lookup"] or "NOT_APPLICABLE"
        out["identity_reason"] = out["identity_reason"] or "no_symbol_on_row"
    elif sym in NON_ENTITY_SYMBOLS:
        out["identity_lookup"] = "NOT_APPLICABLE"
        out["identity_reason"] = "cash_or_non_entity_symbol"
    else:
        out["identity_lookup"] = out["identity_lookup"] or "UNRESOLVED"
        out["identity_reason"] = out["identity_reason"] or "registry_answered_no_entity"
    return out


_IDENTITY_COLS_PRESENT: bool | None = None


def identity_columns_available(target: Any, *, refresh: bool = False) -> bool:
    """Does the live table carry the identity columns from sql/research_identity_tags.sql?

    Probed once per process through information_schema (a read). A probe that
    cannot run answers False for this call and is not cached, so a transient
    failure does not disable identity for the life of a long-running process.
    """
    global _IDENTITY_COLS_PRESENT
    if _IDENTITY_COLS_PRESENT is not None and not refresh:
        return _IDENTITY_COLS_PRESENT
    sql = ("SELECT column_name FROM information_schema.columns "
           "WHERE table_name = %s AND column_name = ANY(%s)")
    try:
        fetched, _ = _run(target, sql, (TABLE, list(IDENTITY_COLUMNS)), want_rows=True)
        names = {str(_first(r)) for r in (fetched or [])}
    except Exception as exc:
        log.debug("identity column probe failed: %s", exc)
        return False
    _IDENTITY_COLS_PRESENT = set(IDENTITY_COLUMNS) <= names
    return _IDENTITY_COLS_PRESENT


# ── coercion + rails ─────────────────────────────────────────────────────────


def _coerce(col: str, val: Any) -> tuple[str, Any]:
    """(placeholder_sql, param) for one column value. param None ⇒ literal only."""
    if isinstance(val, SqlExpr):
        return val.text, None
    if val is None:
        return "%s", None  # explicit NULL (UPDATE paths; INSERT drops None keys earlier)
    if col in JSONB_COLUMNS:
        if isinstance(val, (dict, list)):
            return "%s::jsonb", json.dumps(val, default=str)
        return "%s::jsonb", str(val)
    if col in ARRAY_COLUMNS:
        if isinstance(val, (list, tuple, set)):
            return "%s::text[]", [str(x) for x in val]
        return "%s::text[]", str(val)  # a '{"a","b"}' text literal, as legacy writers passed
    if col in BOOL_COLUMNS:
        return ("true" if bool(val) else "false"), None
    if col in FLOAT_COLUMNS:
        return "%s", float(val)
    if col in INT_COLUMNS:
        return "%s", int(val)
    if col == "symbol":
        s = str(val).strip()
        return "%s", (s or None)
    return "%s", val


def _validate_row(row: Mapping[str, Any]) -> str | None:
    """A reason string when the row is off its rails, else None."""
    for col in REQUIRED_TEXT:
        v = row.get(col)
        if v is None or (isinstance(v, str) and not v.strip()):
            return f"{col}_required"
    cs = row.get("confidence_score")
    if cs is not None and not isinstance(cs, SqlExpr):
        try:
            f = float(cs)
        except (TypeError, ValueError):
            return "confidence_score_not_numeric"
        if not (0.0 <= f <= 1.0):
            return f"confidence_score_out_of_range:{f}"
    tt = row.get("thesis_type")
    if tt is not None and str(tt) not in THESIS_TYPES:
        return f"thesis_type_not_allowed:{tt}"
    st = row.get("status")
    if st is not None and str(st) not in STATUSES:
        return f"status_not_allowed:{st}"
    for col in JSONB_COLUMNS:
        v = row.get(col)
        if isinstance(v, str):
            try:
                json.loads(v)
            except ValueError:
                return f"{col}_invalid_json"
    for col in FLOAT_COLUMNS | INT_COLUMNS:
        v = row.get(col)
        if v is None or isinstance(v, SqlExpr) or col == "confidence_score":
            continue
        try:
            float(v) if col in FLOAT_COLUMNS else int(v)
        except (TypeError, ValueError):
            return f"{col}_not_numeric"
    return None


def _summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (str(row.get(k))[:80] if row.get(k) is not None else None)
            for k in ("hermes_agent_name", "research_type", "symbol", "topic")}


# ── INSERT ───────────────────────────────────────────────────────────────────


def write_research_rows(
    target: Any,
    rows: Iterable[Mapping[str, Any]],
    *,
    producer: str | None = None,
    source: str = "hermes",
    run_id: str | None = None,
    identity_columns: bool | None = None,
    drop_unknown: bool = False,
    registry: Mapping[str, Any] | None = None,
) -> WriteReceipt:
    """Stage research rows. One INSERT per row, ``RETURNING id``.

    ``target`` is a DB-API cursor or a ``fn(sql, params, fetch=)`` executor
    (db_adapter._execute shape). Commit is the caller's, as it always was.

    ``producer`` fills ``hermes_agent_name`` when the row does not carry one and
    is recorded on the receipt. ``source`` fills the ``source`` column when the
    row does not carry one (the DDL CHECKs it to 'hermes'). ``run_id`` has no
    column today — it rides on the receipt only.

    Defaults applied only when the row omits the column: ``created_at = NOW()``,
    ``freshness_date = CURRENT_DATE``, ``status = 'staged'``. ``None`` values are
    omitted so the table's own defaults apply (NULL / '[]' / '{}').

    ``identity_columns``: None probes information_schema once; True/False forces.
    Identity is resolved registry-first (see ``resolve_subject_identity``); an
    unresolved row gets NULL identity columns exactly as the backfill leaves them,
    so ``backfill_research_identity.py`` still picks it up later.
    """
    receipt = WriteReceipt(op="insert", source=source, producer=producer, run_id=run_id,
                           identity={"resolved": 0, "unresolved": 0, "explicit": 0,
                                     "columns_present": None, "lookups": {}})
    rows = list(rows)
    receipt.rows_in = len(rows)
    if not rows:
        return receipt

    if identity_columns is None:
        identity_columns = identity_columns_available(target)
    receipt.identity["columns_present"] = bool(identity_columns)

    for idx, raw in enumerate(rows):
        row: dict[str, Any] = {k: v for k, v in dict(raw).items() if v is not None}
        hints = {k: row.pop(k) for k in list(row) if k in IDENTITY_HINT_KEYS}
        unknown = sorted(k for k in row if k not in INSERTABLE)
        if unknown:
            if not drop_unknown:
                receipt.rows_rejected.append({"index": idx, "reason": f"unknown_columns:{','.join(unknown)}",
                                              "row": _summary(row)})
                log.warning("%s rejected row %d: unknown columns %s", TABLE, idx, unknown)
                continue
            for k in unknown:
                row.pop(k)
                if k not in receipt.dropped_columns:
                    receipt.dropped_columns.append(k)

        row.setdefault("source", source)
        if producer and not row.get("hermes_agent_name"):
            row["hermes_agent_name"] = producer
        row.setdefault("status", "staged")
        row.setdefault("created_at", SQL_NOW)
        row.setdefault("freshness_date", SQL_CURRENT_DATE)

        reason = _validate_row(row)
        if reason:
            receipt.rows_rejected.append({"index": idx, "reason": reason, "row": _summary(row)})
            log.warning("%s rejected row %d: %s", TABLE, idx, reason)
            continue

        if identity_columns:
            ident = resolve_subject_identity({**row, **hints}, registry=registry)
            lk = ident.get("identity_lookup") or "UNRESOLVED"
            receipt.identity["lookups"][lk] = receipt.identity["lookups"].get(lk, 0) + 1
            if ident.get("subject_guid"):
                receipt.identity["explicit" if lk == "EXPLICIT" else "resolved"] += 1
                row["subject_guid"] = ident["subject_guid"]
                if ident.get("issuer_guid"):
                    row["issuer_guid"] = ident["issuer_guid"]
                if ident.get("identity_status"):
                    row["identity_status"] = ident["identity_status"]
                row.setdefault("identity_tagged_at", SQL_NOW)
            else:
                receipt.identity["unresolved"] += 1
                for c in IDENTITY_COLUMNS:
                    row.pop(c, None)
        else:
            for c in IDENTITY_COLUMNS:
                row.pop(c, None)

        cols = [c for c in COLUMNS if c in row]
        placeholders: list[str] = []
        params: list[Any] = []
        for c in cols:
            ph, p = _coerce(c, row[c])
            placeholders.append(ph)
            if p is not None or ph == "%s":
                params.append(p)
        sql = (f"{INSERT_HEAD}\n    ({', '.join(cols)})\n"
               f"    VALUES ({', '.join(placeholders)})\n    RETURNING id")
        receipt.sql.append(sql)
        fetched, _ = _run(target, sql, params, want_row=True)
        receipt.rows_written += 1
        receipt.ids.append(_first(fetched))
    return receipt


# ── UPDATE ───────────────────────────────────────────────────────────────────


def update_research_rows(
    target: Any,
    *,
    where: str,
    where_params: Sequence[Any] = (),
    set_fields: Mapping[str, Any] | None = None,
    set_raw: Mapping[str, str | tuple[str, Sequence[Any]]] | None = None,
    from_clause: str | None = None,
    alias: str | None = None,
    touch_updated_at: bool = False,
    source: str = "hermes",
    producer: str | None = None,
    run_id: str | None = None,
) -> WriteReceipt:
    """The one UPDATE emitter for the table.

    ``set_fields`` are coerced like INSERT values (allowlisted columns only).
    ``set_raw`` maps a column to a SQL expression — ``"CASE ... END"``,
    ``("COALESCE(pattern_signature, %s)", [sig])`` — for the shapes that cannot
    be a plain value; the column is still allowlisted. ``where`` is mandatory: an
    UPDATE without a predicate never reaches the database. ``from_clause`` and
    ``alias`` support the two join-backfills (``UPDATE t AS h SET ... FROM ...``).
    """
    if not isinstance(where, str) or not where.strip():
        raise ResearchWriteError("update_research_rows: WHERE is required (refusing a whole-table UPDATE)")
    set_fields = dict(set_fields or {})
    set_raw = dict(set_raw or {})
    if not set_fields and not set_raw and not touch_updated_at:
        raise ResearchWriteError("update_research_rows: nothing to SET")
    bad = sorted(k for k in set(set_fields) | set(set_raw) if k not in UPDATABLE)
    if bad:
        raise ResearchWriteError(f"update_research_rows: columns not updatable: {bad}")
    st = set_fields.get("status")
    if st is not None and not isinstance(st, SqlExpr) and str(st) not in STATUSES:
        raise ResearchWriteError(f"update_research_rows: status_not_allowed:{st}")
    tt = set_fields.get("thesis_type")
    if tt is not None and str(tt) not in THESIS_TYPES:
        raise ResearchWriteError(f"update_research_rows: thesis_type_not_allowed:{tt}")
    cs = set_fields.get("confidence_score")
    if cs is not None and not isinstance(cs, SqlExpr) and not (0.0 <= float(cs) <= 1.0):
        raise ResearchWriteError(f"update_research_rows: confidence_score_out_of_range:{cs}")

    sets: list[str] = []
    params: list[Any] = []
    for c in COLUMNS:
        if c in set_fields:
            ph, p = _coerce(c, set_fields[c])
            sets.append(f"{c} = {ph}")
            if p is not None or ph == "%s":
                params.append(p)
    for c, expr in set_raw.items():
        if isinstance(expr, tuple):
            text, ps = expr
            sets.append(f"{c} = {text}")
            params.extend(ps)
        else:
            sets.append(f"{c} = {expr}")
    if touch_updated_at and "updated_at" not in set_fields and "updated_at" not in set_raw:
        sets.append("updated_at = NOW()")

    head = UPDATE_HEAD + (f" AS {alias}" if alias else "")
    sql = f"{head}\n    SET {', '.join(sets)}"
    if from_clause:
        sql += f"\n    FROM {from_clause}"
    sql += f"\n    WHERE {where}"
    params.extend(where_params)

    receipt = WriteReceipt(op="update", source=source, producer=producer, run_id=run_id, rows_in=1)
    receipt.sql.append(sql)
    _, rc = _run(target, sql, params)
    receipt.rows_written = rc
    return receipt


# ── named UPDATE shapes (each is one legacy writer's exact semantics) ─────────


def set_status(target: Any, *, ids: Sequence[Any], status: str, only_from: Sequence[str] | None = None,
               touch_updated_at: bool = False, **prov: Any) -> WriteReceipt:
    """status := X for ids (coordinator promote, critique/refresh archive)."""
    where = "id = ANY(%s)"
    params: list[Any] = [list(ids)]
    if only_from:
        where += " AND status = ANY(%s)"
        params.append(list(only_from))
    return update_research_rows(target, set_fields={"status": status}, where=where, where_params=params,
                                touch_updated_at=touch_updated_at, **prov)


def archive_rows_where(target: Any, *, where: str, where_params: Sequence[Any] = (), add_tag: str | None = None,
                       extra_set: Mapping[str, Any] | None = None, touch_updated_at: bool = False,
                       **prov: Any) -> WriteReceipt:
    """status := 'archived' for a predicate, optionally appending one tag.

    freshness (stale_freshness), retention (auto_archived), outcome_learning (no tag).
    """
    set_fields: dict[str, Any] = {"status": "archived", **dict(extra_set or {})}
    set_raw: dict[str, Any] = {}
    if add_tag:
        set_raw["tags"] = ("array_append(COALESCE(tags, ARRAY[]::text[]), %s)", [add_tag])
    return update_research_rows(target, set_fields=set_fields, set_raw=set_raw, where=where,
                                where_params=where_params, touch_updated_at=touch_updated_at, **prov)


def archive_with_tags_union(target: Any, *, where: str, where_params: Sequence[Any] = (), tags: Sequence[str],
                            extra_set: Mapping[str, Any] | None = None, touch_updated_at: bool = True,
                            **prov: Any) -> WriteReceipt:
    """status := 'archived', tags := DISTINCT(tags ∪ given) — repair_health_threshold_tuning_noise."""
    set_raw = {"tags": ("(SELECT ARRAY(SELECT DISTINCT x FROM unnest("
                        "COALESCE(tags, ARRAY[]::text[]) || %s::text[]) AS x))", [list(tags)])}
    return update_research_rows(target, set_fields={"status": "archived", **dict(extra_set or {})}, set_raw=set_raw,
                                where=where, where_params=where_params, touch_updated_at=touch_updated_at, **prov)


def transition_if_status(target: Any, *, ids: Sequence[Any], from_status: str, to_status: str,
                         add_tag_if_absent: str | None = None, **prov: Any) -> WriteReceipt:
    """status := to WHEN status = from ELSE unchanged; tag appended only if absent (backlog drain)."""
    set_raw: dict[str, Any] = {
        "status": ("CASE WHEN status = %s THEN %s ELSE status END", [from_status, to_status]),
    }
    if add_tag_if_absent:
        set_raw["tags"] = ("CASE WHEN %s = ANY(tags) THEN tags ELSE array_append(tags, %s) END",
                           [add_tag_if_absent, add_tag_if_absent])
    return update_research_rows(target, set_raw=set_raw, where="id = ANY(%s)", where_params=[list(ids)], **prov)


def fill_if_null(target: Any, *, ids: Sequence[Any], fields: Mapping[str, Any], touch_updated_at: bool = True,
                 **prov: Any) -> WriteReceipt:
    """col := COALESCE(col, value) for each field — never overwrites (health remediation, trade links)."""
    set_raw: dict[str, Any] = {}
    for c, v in fields.items():
        ph, p = _coerce(c, v)
        set_raw[c] = (f"COALESCE({c}, {ph})", [p] if (p is not None or ph == "%s") else [])
    return update_research_rows(target, set_raw=set_raw, where="id = ANY(%s)", where_params=[list(ids)],
                                touch_updated_at=touch_updated_at, **prov)


def record_remediation_outcome(target: Any, *, finding_id: Any, success: Any, duration_ms: Any,
                               pattern_signature: Any, **prov: Any) -> WriteReceipt:
    """remediation_success/duration := given; pattern_signature kept if already set (health inspector)."""
    return update_research_rows(
        target,
        set_fields={"remediation_success": success, "remediation_duration_ms": duration_ms},
        set_raw={"pattern_signature": ("COALESCE(pattern_signature, %s)", [pattern_signature])},
        where="id = ANY(%s)", where_params=[[finding_id]], **prov)


def set_fields_by_id(target: Any, *, ids: Sequence[Any], fields: Mapping[str, Any], touch_updated_at: bool = False,
                     extra_where: str | None = None, extra_params: Sequence[Any] = (), **prov: Any) -> WriteReceipt:
    """Plain column assignment for ids (strategy_tags, content_tags, categories, evidence_json, synthesis)."""
    where = "id = ANY(%s)"
    params: list[Any] = [list(ids)]
    if extra_where:
        where += f" AND {extra_where}"
        params.extend(extra_params)
    return update_research_rows(target, set_fields=fields, where=where, where_params=params,
                                touch_updated_at=touch_updated_at, **prov)


def patch_evidence_json_path(target: Any, *, ids: Sequence[Any], path: Sequence[str], value: Any,
                             **prov: Any) -> WriteReceipt:
    """evidence_json := jsonb_set(COALESCE(evidence_json,'{}'), path, value) (reground reset)."""
    set_raw = {"evidence_json": ("jsonb_set(COALESCE(evidence_json, '{}'::jsonb), %s::text[], %s::jsonb)",
                                 [list(path), json.dumps(value, default=str)])}
    return update_research_rows(target, set_raw=set_raw, where="id = ANY(%s)", where_params=[list(ids)], **prov)


def blend_quality_score(target: Any, *, research_type: str, blend_existing: float, neutral: float,
                        blend_outcome_prior: float, prior: float, **prov: Any) -> WriteReceipt:
    """quality_score := ROUND((be*COALESCE(q, neutral) + bo*prior), 3) per research_type (tag engine)."""
    set_raw = {"quality_score": ("ROUND((%s * COALESCE(quality_score, %s) + %s * %s)::numeric, 3)",
                                 [float(blend_existing), float(neutral), float(blend_outcome_prior), float(prior)])}
    return update_research_rows(target, set_raw=set_raw, where="COALESCE(research_type, 'unknown') = %s",
                                where_params=[research_type], **prov)


def stamp_learning_cycle(target: Any, *, cycle_number: int, within: str = "1 hour", **prov: Any) -> WriteReceipt:
    """learning_cycle := n for rows this cycle wrote (learning_cycle = 0, created in the window)."""
    return update_research_rows(target, set_fields={"learning_cycle": int(cycle_number)},
                                where=f"learning_cycle = 0 AND created_at > NOW() - INTERVAL '{within}'", **prov)


def link_from_join(target: Any, *, set_raw: Mapping[str, str], from_clause: str, where: str,
                   where_params: Sequence[Any] = (), alias: str = "hri", **prov: Any) -> WriteReceipt:
    """UPDATE t AS alias SET col = other.col FROM ... WHERE ... (trade_instances, outcome ledger)."""
    return update_research_rows(target, set_raw=dict(set_raw), from_clause=from_clause, where=where,
                                where_params=where_params, alias=alias, **prov)


def rollback_sql_for_status(row_id: Any, status: str) -> str:
    """The reversal statement the coordinator files in hermes_promotion_audit.rollback_sql."""
    if str(status) not in STATUSES:
        raise ResearchWriteError(f"rollback_sql_for_status: status_not_allowed:{status}")
    return f"{UPDATE_HEAD} SET status='{status}' WHERE id={int(row_id)};"


__all__ = [
    "AUTHORITY", "MBI", "SCHEMA", "TABLE", "COLUMNS", "IDENTITY_COLUMNS", "STATUSES", "THESIS_TYPES",
    "SqlExpr", "SQL_NOW", "SQL_CURRENT_DATE", "WriteReceipt", "ResearchWriteError",
    "resolve_subject_identity", "identity_columns_available",
    "write_research_rows", "update_research_rows",
    "set_status", "archive_rows_where", "archive_with_tags_union", "transition_if_status", "fill_if_null",
    "record_remediation_outcome", "set_fields_by_id", "patch_evidence_json_path", "blend_quality_score", "stamp_learning_cycle",
    "link_from_join", "rollback_sql_for_status",
]
