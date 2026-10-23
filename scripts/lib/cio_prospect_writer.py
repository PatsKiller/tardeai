"""CIO prospect writer — the production caller of ``InstrumentRecordStore.upsert_prospect`` (P1 dual-write).

docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md §11 backlog item 2 / §12 audit (2026-10-23): the store had no
production writer — only tests called ``upsert_prospect``. The CIO's own passes now call this module after they run:

* ``scripts/cio_opportunity_curator.py --apply``  — the whole universe (``scope="full"``);
* ``scripts/cio_entry_state_runner.py --apply`` — only the symbols whose entry state changed (``scope="subset"``).

Each call builds the prospects with ``scripts/lib/cio_prospect_builder.build`` (the one assembler; this module never
re-derives a field), then, per security_guid:

=====================================  =====================================================================
``TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE``  what is written
=====================================  =====================================================================
unset / not ``1`` (the default, OFF)    the existing shadow artifact ``data/cio/cio_prospect_shadow.json``
                                        (full scope only — a subset never overwrites the full shadow) and this
                                        writer's receipt (``data/runtime/cio_prospect_writer_<caller>_last.json``). **Nothing** to ``cio_instrument_records.jsonl``,
                                        nothing to Postgres.
``1`` (ON)                              the above, plus ``InstrumentRecordStore.upsert_prospect`` per changed
                                        prospect: the jsonl row (store of record in P1) and — only when
                                        ``prospect_store_status`` is live (row granted + flag + table present) —
                                        the ``cio_prospect`` row upsert and its ``cio_prospect_events`` rows.
=====================================  =====================================================================

Rules this module keeps:

* **Idempotent.** The record is merged onto the stored prospect for the same ``security_guid``; a merge that
  changes nothing is a ``CognitionNoOp`` and writes nothing. Postgres upserts only when the revision advances
  (``WHERE cio_prospect.revision < EXCLUDED.revision``) and events are ``ON CONFLICT (security_guid, event_key)
  DO NOTHING``.
* **A version only on material change** (the opportunity store's rule). The jsonl is append-only and a full
  prospect is ~4.3 KB (1,685 prospects ≈ 7.3 MB measured 2026-10-23), so a run whose only change is timestamps,
  provenance or a conviction move under ``CONVICTION_TOLERANCE`` writes nothing until the stored record is
  ``TRADEAI_CIO_PROSPECT_REFRESH_HOURS`` old (default 4). Stage, stance, conflicts, triggers, gaps, watchlist,
  lifecycle and component values are always material.
* **Conflicts are recorded, never resolved** (AGENTS.md §0 rule 5). The builder's ``conflicts[]`` pass through
  untouched. A stored prospect for the same GUID under another symbol adds a ``symbol`` conflict to the record.
  A Postgres row whose revision did not advance (the table is ahead of the jsonl) is listed in the receipt with
  both revisions; neither copy is changed to match the other.
* **Fail-soft.** A build error, a DB error, a jsonl error or a refused row never raises into the caller; each is
  logged on stderr and counted in the receipt. After ``PG_CIRCUIT_AFTER`` consecutive Postgres failures the run
  stops calling Postgres (the jsonl writes continue) and says so.
* **MBI_BEHAVIOR = 0.** Any ``BEHAVIOR_FIELDS`` key anywhere in a prospect or in its lifecycle events refuses the
  row (``BehaviorWriteRefused``) — counted, never written, never filtered silently.

Never: a broker call, a model call, a send, a DDL statement, a delete.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from scripts.lib import cio_instrument_record as ir

SCHEMA = "CioProspectWriterRun@v1"
WRITER = "scripts/lib/cio_prospect_writer.py"
FLAG_ENV = ir.PROSPECT_DUAL_WRITE_ENV
SHADOW_REL = "data/cio/cio_prospect_shadow.json"          # same artifact as scripts/cio_prospect_shadow_build.py
RECEIPT_TMPL = "data/runtime/cio_prospect_writer_{caller}_last.json"   # one receipt per calling lane
RECORDS_REL = "data/cio/cio_instrument_records.jsonl"     # InstrumentRecordStore's file under the state root
PG_CIRCUIT_AFTER = 3
CALLERS = ("cio-opportunity-curator", "cio-entry-state", "manual")
# Prospect fields the writer never copies from the builder row: aliases are recomputed by apply_prospect, and
# stage_changed_at is set by apply_prospect only when the stage actually moves (copying the builder's value would
# make every run a change).
_NOT_COPIED = ("aliases", "stage_changed_at")
_CAP = 50
REFRESH_ENV = "TRADEAI_CIO_PROSPECT_REFRESH_HOURS"
REFRESH_HOURS_DEFAULT = 4.0       # a prospect whose only change is its timestamps is rewritten at most this often
CONVICTION_TOLERANCE = 1.0        # points; a smaller move alone is not a material change
# Fields that move on every refresh of an input without the judgment changing; alone they are not a version.
_VOLATILE = ("evidence_at", "expires_at", "provenance", "stage_changed_at", "aliases", "conviction",
             "conviction_components")
SELF_SOURCE = "instrument_records"                         # builder input name of InstrumentRecordStore's own file


def _log(msg: str) -> None:
    print(f"[cio_prospect_writer] {msg}", file=sys.stderr)


def receipt_rel(caller: str) -> str:
    return RECEIPT_TMPL.format(caller="".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in caller))


def dual_write_flag(env: Optional[dict[str, str]] = None) -> bool:
    environ = os.environ if env is None else env
    return str(environ.get(FLAG_ENV) or "").strip() == "1"


def behavior_keys(row: dict[str, Any]) -> list[str]:
    """Every BEHAVIOR_FIELDS key anywhere in the row or its lifecycle events (MBI_BEHAVIOR = 0)."""
    return sorted(k for k in ir._walk_keys(row) if k in ir.BEHAVIOR_FIELDS)


def priors_by_guid(store: ir.InstrumentRecordStore) -> dict[str, dict[str, Any]]:
    """The latest stored prospect per security_guid (one row per GUID, whatever its subject_key)."""
    out: dict[str, dict[str, Any]] = {}
    for rec in store.all():
        if not ir.is_prospect_record(rec):
            continue
        g = str(rec.get("security_guid") or "")
        if not g:
            continue
        cur = out.get(g)
        if cur is None or (int(rec.get("prospect_revision") or 0), str(rec.get("updated_ts") or "")) > \
                (int(cur.get("prospect_revision") or 0), str(cur.get("updated_ts") or "")):
            out[g] = rec
    return out


def merge(row: dict[str, Any], prior: Optional[dict[str, Any]], *, now: datetime,
          refresh_after_h: Optional[float] = None) -> dict[str, Any]:
    """The prospect record for ``row`` (a builder table row), merged onto ``prior``.

    Raises ``BehaviorWriteRefused`` (MBI), ``ProspectInvalid`` or ``CognitionNoOp`` (nothing changed) — the
    caller counts each; none is written. With ``refresh_after_h``, a merge whose only change is volatile
    (timestamps, provenance, conviction within CONVICTION_TOLERANCE) raises ``Immaterial`` until the stored record
    is ``refresh_after_h`` old — the jsonl is append-only, so every version is a row forever.
    """
    bad = behavior_keys(row)
    if bad:
        raise ir.BehaviorWriteRefused(f"MBI_BEHAVIOR=0: a prospect may not carry {bad}")
    sym = str(row.get("symbol") or (row.get("aliases") or {}).get("symbol") or "").upper()
    key = str(row.get("subject_key") or "")
    if not sym or not key:
        raise ir.ProspectInvalid("builder row has no symbol / subject_key")
    kind = ir.parse_subject_key(key)[0]
    if prior is not None:
        base = dict(prior)
        base["subject_key"] = key                      # stage, not kind, is the state; the alias follows the build
        base["kind"] = kind
        if (sym not in [str(s).upper() for s in (prior.get("symbols") or [])]):
            base["symbols"] = [sym]
    else:
        base = ir.new_record(kind, sym)
        for k, v in (row.get("cognition") or {}).items():
            if k in ir.COGNITION_FIELDS and v is not None:
                base[k] = v
    base["subject_guid"] = (row.get("aliases") or {}).get("subject_guid") or row["security_guid"]
    if row.get("thesis_ref"):
        base["thesis_ref"] = row["thesis_ref"]
    block = {k: row.get(k) for k in ir.PROSPECT_FIELDS if k not in _NOT_COPIED and k in row}
    prov = block.get("provenance")
    if isinstance(prov, dict) and isinstance(prov.get("sources"), dict):
        # The builder reads this writer's own store; its file-wide as_of moves on every write, so carrying it would
        # make every run a change to every prospect (a write loop). The record names the exclusion instead.
        block["provenance"] = {**prov, "sources": {k: v for k, v in prov["sources"].items() if k != SELF_SOURCE},
                               "self_source_excluded": SELF_SOURCE}
    conflicts = list(block.get("conflicts") or [])
    prior_syms = [str(s).upper() for s in ((prior or {}).get("symbols") or [])]
    if prior is not None and prior_syms and sym not in prior_syms:
        conflicts.append({
            "field": "symbol", "resolved": False,
            "note": "one security_guid, two symbols — recorded by the writer, never resolved by it",
            "values": [{"value": prior_syms[0], "source": "cio_instrument_records.jsonl (stored prospect)",
                        "at": prior.get("updated_ts")},
                       {"value": sym, "source": "cio_prospect_builder", "at": row.get("evidence_at")}]})
    block["conflicts"] = conflicts
    rec, _ = ir.apply_prospect(base, prospect=block, strict=True)
    if refresh_after_h is not None and prior is not None:
        changed = material_changes(prior, rec)
        if not changed and not refresh_due(prior, hours=refresh_after_h):
            raise Immaterial(f"{key}: only timestamps moved; refresh due after {refresh_after_h} h")
    return rec


class Immaterial(ir.CognitionNoOp):
    """Only timestamps / provenance / sub-tolerance conviction moved and the refresh is not due — not a version."""


def _components(rec: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in (rec.get("conviction_components") or {}).items():
        val = (v or {}).get("value") if isinstance(v, dict) else None
        out[k] = None if val is None else round(float(val), 0)
    return out


_TIME_KEYS = frozenset({"at", "since", "as_of", "evidence_at", "expires_at", "observed_at", "updated_at",
                        "updated_ts", "computed_at", "generated_at"})


def _sans_times(obj: Any) -> Any:
    """The value with every timestamp key removed, at any depth (``watchlist.since``, ``conflicts[].values[].at``,
    ``stage_evidence.at`` ...): when an input re-runs, those move while the judgment does not."""
    if isinstance(obj, dict):
        return {k: _sans_times(v) for k, v in obj.items() if k not in _TIME_KEYS}
    if isinstance(obj, list):
        return [_sans_times(v) for v in obj]
    return obj


def material_changes(prior: Optional[dict[str, Any]], rec: dict[str, Any]) -> list[str]:
    """The prospect fields whose change makes a new version (the opportunity store's material-change rule, applied
    to the prospect): any non-volatile field, the conviction beyond CONVICTION_TOLERANCE, or a component's value."""
    if prior is None or not ir.is_prospect_record(prior):
        return ["mint"]
    out = [k for k in ir.PROSPECT_FIELDS
           if k not in _VOLATILE and _sans_times(prior.get(k)) != _sans_times(rec.get(k))]
    try:
        if abs(float(prior.get("conviction") or 0) - float(rec.get("conviction") or 0)) >= CONVICTION_TOLERANCE:
            out.append("conviction")
    except (TypeError, ValueError):
        out.append("conviction")
    if _components(prior) != _components(rec):
        out.append("conviction_components")
    if prior.get("subject_key") != rec.get("subject_key"):
        out.append("subject_key")
    return out


def refresh_hours(env: Optional[dict[str, str]] = None) -> float:
    environ = os.environ if env is None else env
    try:
        return max(0.0, float(environ.get(REFRESH_ENV) or REFRESH_HOURS_DEFAULT))
    except ValueError:
        return REFRESH_HOURS_DEFAULT


def refresh_due(prior: Optional[dict[str, Any]], *, hours: float, clock: Optional[datetime] = None) -> bool:
    """``updated_ts`` is stamped by the store's wall clock, so the age is measured on the wall clock too."""
    ts = ir._parse_ts((prior or {}).get("updated_ts"))
    wall = clock or datetime.now(timezone.utc)
    return ts is None or (wall - ts).total_seconds() >= hours * 3600.0


class _RunBackend:
    """Wraps the Postgres backend for one run: the table probe runs once; consecutive failures open a circuit."""

    def __init__(self, backend: Any) -> None:
        self._b = backend
        self._present: Optional[bool] = None
        self.failures = 0
        self.open = False

    def table_present(self) -> bool:
        if self._present is None:
            self._present = bool(self._b.table_present())
        return self._present

    def write(self, row: dict[str, Any], event: dict[str, Any], lifecycle: Iterable[dict[str, Any]] = ()) -> dict:
        try:
            out = self._b.write(row, event, lifecycle)
        except Exception:
            self.failures += 1
            if self.failures >= PG_CIRCUIT_AFTER:
                self.open = True
            raise
        self.failures = 0
        return out


def _default_backend() -> Any:
    from scripts.session13_db import get_conn
    return ir.ProspectPgBackend(get_conn)


def _readonly_db_query() -> tuple[Callable[..., list[dict]], Any]:
    from scripts.cio_prospect_shadow_build import _readonly_db_query as q
    return q()


def write_prospects(state_root: Path | str, *, caller: str, apply: bool, scope: str = "full",
                    symbols: Optional[Iterable[str]] = None, env: Optional[dict[str, str]] = None,
                    store: Optional[ir.InstrumentRecordStore] = None, backend: Any = None,
                    backend_factory: Optional[Callable[[], Any]] = None,
                    registry: Optional[dict[str, Any]] = None,
                    db_query: Optional[Callable[..., list[dict]]] = None, with_db: bool = False,
                    build_fn: Optional[Callable[..., dict]] = None, now: Optional[datetime] = None,
                    write_receipt: bool = True) -> dict[str, Any]:
    """Build the prospects and write them as the flag says. Never raises; returns the run report."""
    t0 = time.time()
    now = now or datetime.now(timezone.utc)
    root = Path(state_root)
    flag = dual_write_flag(env)
    rep: dict[str, Any] = {
        "schema": SCHEMA, "writer": WRITER, "caller": caller, "scope": scope, "as_of": now.isoformat(),
        "mode": ("dual_write_flag_on" if flag else "shadow_only") if apply else "dry_run",
        "flag": flag, "apply": apply, "ok": False, "memory_behavior_influence": ir.MBI_BEHAVIOR,
        "counts": {"built": 0, "unchanged": 0, "immaterial": 0, "jsonl_written": 0, "pg_upserted": 0, "pg_not_advanced": 0,
                   "pg_errors": 0, "jsonl_errors": 0, "refused_behavior": 0, "invalid": 0,
                   "builder_conflicts": 0, "writer_conflicts": 0, "events_appended": 0},
        "wrote": [], "pg": None, "conflicts": [], "errors": [],
    }
    c = rep["counts"]
    conn = None
    try:
        if build_fn is None:
            from scripts.lib import cio_prospect_builder as builder
            build_fn = builder.build
        if db_query is None and with_db:
            try:
                db_query, conn = _readonly_db_query()
            except Exception as exc:  # noqa: BLE001 — the build still runs on the file inputs
                rep["errors"].append({"stage": "db_connect", "error": f"{type(exc).__name__}: {exc}"[:200]})
                _log(f"read-only DB unavailable, building from files only: {type(exc).__name__}")
        try:
            kw: dict[str, Any] = {"db_query": db_query, "now": now}
            if symbols is not None:
                kw["symbols"] = sorted({str(s).upper() for s in symbols})
            doc = build_fn(root, **kw)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
        rows = list(doc.get("prospects") or [])
        c["built"] = len(rows)
        c["builder_conflicts"] = sum(len(r.get("conflicts") or []) for r in rows)
        rep["build"] = {k: (doc.get("counts") or {}).get(k) for k in
                        ("universe", "prospects", "identity_unresolved", "duplicate_guid", "errors")}
        for d in (doc.get("duplicate_guid") or [])[:_CAP]:          # recorded, never resolved
            rep["conflicts"].append({"kind": "duplicate_guid", **d})

        if apply and scope == "full":
            from scripts.lib.data_broker.atomic_json import atomic_write_json
            atomic_write_json(root / SHADOW_REL, doc)
            rep["wrote"].append(SHADOW_REL)
        elif scope != "full":
            rep["shadow_skipped"] = "subset build never overwrites the full shadow artifact"

        if not (apply and flag):
            rep["pg"] = {"mode": "off", "reasons": (["dual_write_flag_off"] if not flag else ["dry_run"])}
            rep["ok"] = True
            return rep

        store = store or ir.InstrumentRecordStore(root / RECORDS_REL)
        raw = backend
        if raw is None:
            try:
                raw = (backend_factory or _default_backend)()
            except Exception as exc:  # noqa: BLE001
                raw = None
                rep["errors"].append({"stage": "pg_backend", "error": f"{type(exc).__name__}: {exc}"[:200]})
        run_backend = _RunBackend(raw) if raw is not None else None
        status = ir.prospect_store_status(registry=registry, env=env,
                                          table_probe=(run_backend.table_present if run_backend else None))
        rep["pg"] = {k: status[k] for k in ("live", "mode", "reasons", "row_granted", "flag", "table_present")}
        priors = priors_by_guid(store)
        refresh_h = refresh_hours(env)
        rep["refresh_hours"] = refresh_h
        for row in rows:
            g = str(row.get("security_guid") or "")
            try:
                rec = merge(row, priors.get(g), now=now, refresh_after_h=refresh_h)
            except Immaterial:
                c["immaterial"] += 1
                continue
            except ir.CognitionNoOp:
                c["unchanged"] += 1
                continue
            except ir.BehaviorWriteRefused as exc:
                c["refused_behavior"] += 1
                rep["errors"].append({"security_guid": g, "symbol": row.get("symbol"), "refused": str(exc)[:200]})
                _log(f"refused {row.get('symbol')}: {exc}")
                continue
            except ir.ProspectInvalid as exc:
                c["invalid"] += 1
                rep["errors"].append({"security_guid": g, "symbol": row.get("symbol"), "invalid": str(exc)[:200]})
                continue
            c["writer_conflicts"] += sum(1 for x in rec.get("conflicts") or [] if x.get("field") == "symbol")
            use_pg = run_backend if (run_backend is not None and not run_backend.open and status["live"]) else None
            try:
                res = store.upsert_prospect(rec, backend=use_pg, registry=registry, env=env,
                                            lifecycle_events=row.get("lifecycle_events") or [])
            except Exception as exc:  # noqa: BLE001 — one row never sinks the pass
                c["jsonl_errors"] += 1
                rep["errors"].append({"security_guid": g, "symbol": row.get("symbol"),
                                      "jsonl": f"{type(exc).__name__}: {exc}"[:200]})
                _log(f"jsonl write failed for {row.get('symbol')}: {type(exc).__name__}")
                continue
            c["jsonl_written"] += 1
            priors[g] = res["row"]
            pg = res.get("pg") or {}
            if use_pg is None or not pg.get("live"):
                continue
            if pg.get("ok") is False:
                c["pg_errors"] += 1
                rep["errors"].append({"security_guid": g, "symbol": row.get("symbol"), "pg": pg.get("error")})
                _log(f"postgres write failed for {row.get('symbol')}: {pg.get('error')}")
            elif int(pg.get("upserted") or 0) == 0:
                c["pg_not_advanced"] += 1
                rep["conflicts"].append({"kind": "pg_revision_not_advanced", "security_guid": g,
                                         "symbol": row.get("symbol"), "jsonl_revision": rec.get("prospect_revision"),
                                         "note": "cio_prospect holds this revision or a later one; both copies "
                                                 "kept, neither changed (§0 rule 5)"})
            else:
                c["pg_upserted"] += 1
            c["events_appended"] += int(pg.get("event_appended") or 0)
        if run_backend is not None and run_backend.open:
            rep["pg"]["circuit"] = f"open after {PG_CIRCUIT_AFTER} consecutive failures; later rows jsonl only"
        rep["ok"] = c["pg_errors"] == 0 and c["jsonl_errors"] == 0
        return rep
    except Exception as exc:  # noqa: BLE001 — the writer never breaks the curator or the runner
        rep["errors"].append({"stage": "run", "error": f"{type(exc).__name__}: {exc}"[:300]})
        _log(f"run failed (fail-soft): {type(exc).__name__}: {exc}")
        return rep
    finally:
        rep["conflicts"] = rep["conflicts"][:_CAP]
        rep["errors"] = rep["errors"][:_CAP]
        rep["seconds"] = round(time.time() - t0, 2)
        if apply and write_receipt:
            try:
                from scripts.lib.data_broker.atomic_json import atomic_write_json
                rel = receipt_rel(caller)
                rep["wrote"].append(rel)
                atomic_write_json(root / rel, rep)
            except Exception as exc:  # noqa: BLE001
                _log(f"receipt write failed: {type(exc).__name__}: {exc}")


def summary(rep: dict[str, Any]) -> dict[str, Any]:
    """The slice a caller's own receipt carries."""
    return {k: rep.get(k) for k in ("mode", "scope", "ok", "flag", "counts", "seconds")} | {
        "pg_mode": (rep.get("pg") or {}).get("mode"), "pg_reasons": (rep.get("pg") or {}).get("reasons"),
        "errors": len(rep.get("errors") or []), "receipt": receipt_rel(str(rep.get("caller"))) if rep.get("apply") else None}
