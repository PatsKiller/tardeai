"""Data-domain approval readiness: is each data-dictionary row ready for the operator's grant? Read-only.

WHY (operator, 2026-10-22, on Ops → Controls → "Data approvals"): the tab listed 17 domains, all "proposed",
with no other information — "This is not a dashboard." This module answers, per domain: which store and which
single writer it declares, who reads it, what the live checks find, how fresh the store is, whether it is
approved — and, for a proposed row, whether granting it now would hold, or exactly what is missing.

WHAT "READY" MEANS — nothing here is invented; every criterion is a check that already exists
-------------------------------------------------------------------------------------------------
A grant (AGENTS.md §17, §26.2, §26.6) is applied by a reviewed PR that calls ``data_dictionary.promote`` with the
operator's approval record; from then on ``scripts/check_data_source_authority.py`` treats the row as binding and
FAILS the build on what it only warned about before. So the honest readiness test is: promote the row in memory,
with the ceilings measured now (exactly what ``promote`` records), and run the real gate functions on it.

    row_valid             data_dictionary.validate()            DICTIONARY_INVALID on the proposed row
    writer_declared       check_data_source_authority.check_domains() on the promoted row
                                                                WRITER_MISSING · WRITER_UNDECLARED
    projection_registered check_domains() on the promoted row   PROJECTION_MISSING (the declared projection is not
                                                                in scripts/lib/data_broker/catalog.py)
    ceilings_hold         data_dictionary.evaluate() on the promoted registry
                                                                DICTIONARY_SECOND_WRITER · NON_AUTHORITATIVE_READ
    readers_granted       check_data_source_authority.check_readers() on the promoted registry (gated stores only)
                                                                UNAPPROVED_READER · READER_GRANT_INVALID
    writer_claim_true     AGENTS.md §26.2: "one writer (or a declared UNCONSOLIDATED ceiling that only falls)". A row
                          that names a single ``writer`` while the scan measures other files writing its store
                          states something false; it must declare UNCONSOLIDATED (the same ``extra`` set
                          data_dictionary.evaluate computes for an approved single-writer row)

Verdicts: ``APPROVED`` (the row is in ``domains[]`` with a dictionary block) · ``READY_TO_APPROVE`` (every
criterion holds) · ``NOT_READY`` (each failing criterion is listed with the gate's own finding). The operator's
approval record itself is the grant, never a readiness gap. Freshness, live warnings and readers are shown as
evidence; they are not criteria (no code makes them one).

WHAT IS NOT DONE HERE: no row is approved or promoted, nothing is written, no broker or provider is called. The
freshness probe is ``stat`` on a file store under ``served_from.root`` and, for a table, ``to_regclass`` + the
planner's row estimate + ``max(<column>)`` only for a timestamp column the registry declares in
``data_dictionary.facts`` (a field ending ``_at`` or named ``as_of``), each query under a 2 s statement timeout in
a read-only transaction. What the scan structurally cannot see is what ``data_dictionary`` cannot see (its
docstring).

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.append(_p)

from scripts.lib import data_dictionary as DD  # noqa: E402

SCHEMA = "DataDomainReadiness@v1"
APPROVED = "APPROVED"
READY = "READY_TO_APPROVE"
NOT_READY = "NOT_READY"
NOTES_REL = Path("config") / "data_domain_approval_notes.json"
AUTHORITY_REL = Path("config") / "data_source_authority.json"
#: Bounds: file lists in the view are cut to this many (the count is always whole).
MAX_FILES = 12
CACHE_TTL_S = 60
TABLE_TIMEOUT_MS = 2000

#: The readiness criteria, in display order. ``source`` is where the check already lives.
CRITERIA: tuple[dict, ...] = (
    {
        "id": "row_valid",
        "label": "Row is well-formed",
        "checks": ("DICTIONARY_INVALID",),
        "source": "scripts/lib/data_dictionary.py validate()",
    },
    {
        "id": "writer_declared",
        "label": "Writer exists, or UNCONSOLIDATED with a target",
        "checks": ("WRITER_MISSING", "WRITER_UNDECLARED"),
        "source": "scripts/check_data_source_authority.py check_domains() on the promoted row",
    },
    {
        "id": "projection_registered",
        "label": "Declared read projection is in the data-broker catalog",
        "checks": ("PROJECTION_MISSING",),
        "source": "scripts/check_data_source_authority.py check_domains() on the promoted row",
    },
    {
        "id": "ceilings_hold",
        "label": "Ceilings measured now pass once binding",
        "checks": ("DICTIONARY_SECOND_WRITER", "NON_AUTHORITATIVE_READ"),
        "source": "scripts/lib/data_dictionary.py promote() + evaluate()",
    },
    {
        "id": "readers_granted",
        "label": "Every reader of a gated store is an approved batch",
        "checks": ("UNAPPROVED_READER", "READER_GRANT_INVALID"),
        "source": "scripts/check_data_source_authority.py check_readers() on the promoted registry",
    },
    {
        "id": "writer_claim_true",
        "label": "A named single writer is the only file writing the store",
        "checks": ("WRITER_CLAIM_FALSE",),
        "source": "AGENTS.md §26.2; the `extra` set in data_dictionary.evaluate()",
    },
)
_CHECK_TO_CRITERION = {c: crit["id"] for crit in CRITERIA for c in crit["checks"]}
#: Placeholder used ONLY for the in-memory promotion simulation. Never written, never returned as a grant.
_SIM_APPROVAL = {
    "approved_by": "SIMULATION (not a grant)",
    "approved_on": "1970-01-01",
    "reference": "data_domain_readiness in-memory promotion; nothing is written",
    "scope": "readiness check only",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def _cut(files: list[str]) -> dict:
    files = sorted(files)
    return {"count": len(files), "files": files[:MAX_FILES], "truncated": len(files) > MAX_FILES}


def load_notes(root: Path) -> dict:
    """Operator-decision annotations not (yet) in the registry, e.g. an approval given but not yet promoted."""
    try:
        doc = json.loads((root / NOTES_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc.get("domains") or {}


# ── the gates (real functions, called — never shelled out) ─────────────────────────────────────────────────────────


def _checker():
    from scripts import check_data_source_authority as C  # imported lazily: it is heavy and path-sensitive

    return C


def _domain_of(f: dict) -> Optional[str]:
    return f.get("domain") or f.get("name") or None


def simulate_promotion(auth: dict, measured: dict) -> dict:
    """Every proposed row promoted in memory with the ceilings measured now (what ``promote`` records).

    Promoting all rows at once is equivalent to promoting each alone: validate() then sees no proposed rows, and
    evaluate(), check_domains() and check_readers() are per row."""
    sim = copy.deepcopy(auth)
    for row in list(DD.proposed_rows(auth)):
        name = row.get("domain")
        try:
            sim = DD.promote(sim, name, _SIM_APPROVAL, measured)
        except Exception:  # noqa: BLE001 — a row promote() refuses stays proposed; validate() names why
            continue
    return sim


def run_gates(auth: dict, root: Path, files: Optional[list[Path]] = None) -> dict:
    """Run the live checks and the promotion simulation. Returns plain data for :func:`assess`."""
    C = _checker()
    t0 = time.monotonic()
    live_findings, live_warnings, measured = DD.evaluate(auth, root)
    files = files if files is not None else C._files()
    live_readers = C.check_readers(auth, files)
    sim = simulate_promotion(auth, measured)
    sim_findings, _w, _m = DD.evaluate(sim, root)
    sim_findings = [f for f in sim_findings if f.get("check") != "DICTIONARY_INVALID"] + [
        f for f in DD.validate(auth, root)
    ]
    sim_findings += C.check_domains(sim)
    sim_findings += C.check_readers(sim, files)
    # who reads each store today (FROM/JOIN a table, or spells a file marker), scripts/ minus tests and broker set
    cache: dict = {}
    src = DD.source_files(root)
    store_readers = {}
    for row, _approved in DD.dictionary_rows(auth):
        store_readers[row["domain"]] = DD.reader_files(row.get("store") or {}, src, root, cache)
    return {
        "live_findings": live_findings,
        "live_warnings": live_warnings,
        "live_readers": live_readers,
        "measured": measured,
        "sim_findings": sim_findings,
        "store_readers": store_readers,
        "duration_s": round(time.monotonic() - t0, 2),
    }


# ── freshness ──────────────────────────────────────────────────────────────────────────────────────────────────────


def declared_time_columns(auth: dict, domain: str, store: dict) -> list[str]:
    """Timestamp columns the registry declares for this domain's store in data_dictionary.facts."""
    table = store.get("table")
    out: list[str] = []
    for f in (auth.get("data_dictionary") or {}).get("facts") or []:
        if f.get("domain") != domain or (table and f.get("store") != table):
            continue
        for tok in re.split(r"[,\s]+", str(f.get("field") or "")):
            if (
                tok
                and re.fullmatch(r"[a-z_][a-z0-9_]*", tok)
                and (tok.endswith("_at") or tok == "as_of")
                and tok not in out
            ):
                out.append(tok)
    return out


def file_freshness(served_root: Path, rel: str, now: datetime) -> dict:
    if "<" in rel:
        return {"state": "NO_SIGNAL", "detail": f"{rel} is a dated family, not one file"}
    p = served_root / rel
    try:
        st = p.stat()
    except OSError:
        return {"state": "MISSING", "detail": f"{p} absent"}
    at = datetime.fromtimestamp(st.st_mtime, timezone.utc)
    return {
        "state": "MEASURED",
        "signal": "file mtime",
        "newest_at": _iso(at),
        "age_h": round((now - at).total_seconds() / 3600, 2),
        "size_bytes": st.st_size,
    }


def pg_table_probe(conn_factory: Callable[[], Any]) -> Callable[[str, list[str]], dict]:
    """A read-only, time-bounded table probe: existence, planner row estimate, max(declared time column)."""

    def probe(table: str, columns: list[str]) -> dict:
        conn = conn_factory()
        try:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = {int(TABLE_TIMEOUT_MS)}")
                cur.execute(
                    "SELECT to_regclass(%s) IS NOT NULL, "
                    "(SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(%s))",
                    (table, table),
                )
                present, est = cur.fetchone()
                if not present:
                    return {"state": "MISSING", "detail": f"table {table} does not exist"}
                out: dict = {
                    "state": "NO_SIGNAL",
                    "rows_estimate": int(est) if est is not None and est >= 0 else None,
                    "detail": "no timestamp column declared in data_dictionary.facts",
                }
                cur.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = %s "
                    "AND data_type LIKE 'timestamp%%' ORDER BY ordinal_position",
                    (table,),
                )
                have = [r[0] for r in cur.fetchall()]
                out["timestamp_columns"] = have[:8]
                if columns:
                    col = next((c for c in columns if c in have), None)
                    if col is None:
                        out["detail"] = (
                            f"registry declares {', '.join(columns)} but {table} has no such timestamp "
                            f"column (it has: {', '.join(have[:6]) or 'none'})"
                        )
                        out["declared_signal_mismatch"] = True
                        return out
                    # identifiers come from the registry and are validated to [a-z0-9_] above
                    cur.execute(f'SELECT max("{col}") FROM "{table}"')
                    newest = cur.fetchone()[0]
                    out.update(
                        {
                            "state": "MEASURED" if newest else "EMPTY",
                            "signal": f"max({col})",
                            "newest_at_raw": newest,
                            "detail": None,
                        }
                    )
                return out
        finally:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass

    return probe


def measure_freshness(
    auth: dict,
    now: datetime,
    table_probe: Optional[Callable[[str, list[str]], dict]],
    served_root: Optional[Path] = None,
) -> dict[str, dict]:
    served_root = served_root or Path((auth.get("served_from") or {}).get("root") or "/nonexistent")
    out: dict[str, dict] = {}
    for row, _approved in DD.dictionary_rows(auth):
        name = row.get("domain")
        store = row.get("store") or {}
        sla_h = row.get("stale_after_hours")
        try:
            if store.get("file"):
                fr = file_freshness(served_root, str(store["file"]), now)
            elif store.get("table") and re.fullmatch(r"[a-z_][a-z0-9_.]*", str(store["table"])):
                if table_probe is None:
                    fr = {"state": "UNAVAILABLE", "detail": "no database probe in this context"}
                else:
                    fr = dict(table_probe(str(store["table"]), declared_time_columns(auth, name, store)))
                    raw = fr.pop("newest_at_raw", None)
                    if isinstance(raw, datetime):
                        raw = raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
                        fr["newest_at"] = _iso(raw)
                        fr["age_h"] = round((now - raw).total_seconds() / 3600, 2)
            else:
                fr = {"state": "NO_SIGNAL", "detail": "store names no table or file"}
        except Exception as exc:  # noqa: BLE001 — unreadable is UNAVAILABLE, never fresh
            fr = {"state": "UNAVAILABLE", "detail": f"{type(exc).__name__}: {str(exc)[:120]}"}
        fr["stale_after_hours"] = sla_h
        if fr.get("state") == "MEASURED" and isinstance(sla_h, (int, float)) and fr.get("age_h") is not None:
            fr["stale"] = fr["age_h"] > float(sla_h)
        else:
            fr["stale"] = None
        out[name] = fr
    return out


# ── assessment (pure) ──────────────────────────────────────────────────────────────────────────────────────────────


def _brief(f: dict) -> dict:
    keep = (
        "check",
        "store",
        "copy",
        "ceiling",
        "now",
        "file",
        "why",
        "where",
        "writer",
        "projection",
        "entry",
        "missing",
    )
    b = {k: f[k] for k in keep if k in f}
    if isinstance(f.get("files"), list):
        b["files"] = _cut(f["files"])
    return b


def _gap_text(f: dict) -> str:
    c = f.get("check")
    if c == "DICTIONARY_INVALID":
        return f"row malformed: {f.get('why')}"
    if c == "WRITER_MISSING":
        return f"declared writer {f.get('writer')} does not exist"
    if c == "WRITER_UNDECLARED":
        return "no writer and no UNCONSOLIDATED writer_target declared"
    if c == "PROJECTION_MISSING":
        return f"declared projection {f.get('projection')!r} is not in the data-broker catalog"
    if c == "DICTIONARY_SECOND_WRITER":
        return (
            f"once binding, {f.get('now')} file(s) write {f.get('store')} against a ceiling of "
            f"{f.get('ceiling')}: {', '.join((f.get('files') or [])[:4])}"
        )
    if c == "NON_AUTHORITATIVE_READ":
        return (
            f"once binding, {f.get('now')} surface file(s) read copy {f.get('copy')} above ceiling {f.get('ceiling')}"
        )
    if c == "UNAPPROVED_READER":
        return f"{f.get('file')} reads the gated store without an approved reader batch"
    if c == "READER_GRANT_INVALID":
        return f"approved_readers entry {f.get('entry')} invalid: {f.get('why') or f.get('missing')}"
    if c == "WRITER_CLAIM_FALSE":
        return (
            f"row names single writer {f.get('writer')} but {len(f.get('files') or [])} other file(s) write "
            f"{f.get('store')}: {', '.join((f.get('files') or [])[:4])} — declare UNCONSOLIDATED with a ceiling, "
            "or move those writes behind the writer"
        )
    return f"{c}: {json.dumps({k: v for k, v in f.items() if k != 'check'})[:160]}"


def writer_claim_findings(row: dict, measured_files: list[str]) -> list[dict]:
    w = row.get("writer")
    if not w or row.get("writer_status") == "UNCONSOLIDATED":
        return []
    allowed = {w} | set(row.get("writers_allowed") or [])
    extra = [f for f in measured_files if f not in allowed]
    if not extra:
        return []
    return [
        {
            "check": "WRITER_CLAIM_FALSE",
            "domain": row.get("domain"),
            "writer": w,
            "store": DD.store_key(row.get("store")),
            "files": extra,
        }
    ]


#: Runtime code that reads a row's grant (searched 2026-10-22: the only caller outside the gates and renderers).
RUNTIME_GRANT_READERS = {
    "cio_prospect": "scripts/lib/cio_instrument_record.py prospect_store_status(): the Postgres dual-write runs only "
    "when this row is granted AND TRADEAI_CIO_PROSPECT_PG_DUAL_WRITE=1 AND the table exists",
}


def approval_effects(row: dict, measured: Optional[dict]) -> list[str]:
    """What granting this row actually changes — and what it does not (AGENTS.md §26.2, §26.6)."""
    name = row.get("domain")
    store = DD.store_key(row.get("store"))
    out = [
        "The row moves from proposed_domains[] into domains[] with the operator's approval record "
        "(data_dictionary.promote, in a reviewed PR)."
    ]
    if measured is not None:
        wf = measured.get("writer_files") or []
        reads = {k: len(v) for k, v in (measured.get("surface_reads") or {}).items()}
        out.append(
            f"CI starts FAILING instead of warning: a writer ceiling of {max(1, len(wf))} file(s) on {store} "
            f"(measured now; it may only fall)"
            + (f" and surface-read ceilings {reads} on its derived/retiring copies" if reads else "")
            + "."
        )
    else:
        out.append(
            "CI starts FAILING instead of warning on a second writer or a page reading a derived/retiring "
            "copy above the ceilings measured at the grant."
        )
    if row.get("extends_approved"):
        out.append(f"{name} is already a granted §7A domain; the grant adds its dictionary block and ceilings.")
    for sup in row.get("supersedes") or []:
        out.append(f"Approved domain {sup} is marked superseded by {name} (marked, never removed).")
    if name in RUNTIME_GRANT_READERS:
        out.append(f"Runtime: {RUNTIME_GRANT_READERS[name]}.")
    out.append(
        "It creates no table, moves no reader, schedules nothing and changes no page by itself (§26.6): each "
        "migration and reader batch is its own operator decision."
    )
    return out


def assess(auth: dict, gates: Optional[dict], freshness: Optional[dict] = None, notes: Optional[dict] = None) -> dict:
    """Per-domain view + verdict. ``gates`` None (scan not run yet) yields rows with ``verdict`` None."""
    notes = notes or {}
    freshness = freshness or {}
    approved_by_name = {d.get("domain"): d for d in auth.get("domains") or []}
    rows_out: list[dict] = []
    for row, approved in DD.dictionary_rows(auth):
        name = row.get("domain")
        base = approved_by_name.get(name) if not approved else row
        store = row.get("store") or {}
        approved_readers = (base or {}).get("approved_readers") or []
        gate = (base or {}).get("reader_gate") or None
        out: dict[str, Any] = {
            "domain": name,
            "title": row.get("title"),
            "entity": row.get("entity"),
            "status": "approved" if approved else (row.get("status") or "proposed"),
            "class": row.get("class"),
            "store": DD.store_key(store),
            "store_detail": row.get("store_detail"),
            "writer": row.get("writer"),
            "writer_status": row.get("writer_status") or ("SINGLE" if row.get("writer") else None),
            "writer_target": row.get("writer_target"),
            "writer_target_status": row.get("writer_target_status"),
            "writer_note": row.get("_writer_note"),
            "projection": row.get("projection"),
            "projection_status": row.get("projection_status"),
            "refresh_lane": row.get("refresh_lane"),
            "cadence": row.get("cadence"),
            "freshness_sla": row.get("freshness_sla"),
            "stale_after_hours": row.get("stale_after_hours"),
            "readers_declared": row.get("readers") or [],
            "approved_reader_batches": [
                {
                    "batch": r.get("batch"),
                    "reader": r.get("reader"),
                    "files": r.get("files"),
                    "surfaces": r.get("surfaces"),
                    "facts": r.get("facts"),
                    "approved_on": (r.get("approval") or {}).get("approved_on"),
                }
                for r in approved_readers
            ],
            "reader_gate": {
                "tables": gate.get("tables"),
                "unbatched": sorted((gate.get("measured_unbatched_readers") or {}).keys()),
            }
            if gate
            else None,
            "derived_copies": [
                {"store": DD.store_key(c.get("store")), "role": c.get("role"), "how": c.get("how")}
                for c in row.get("derived_copies") or []
            ],
            "supersedes": row.get("supersedes") or [],
            "extends_approved": bool(row.get("extends_approved")),
            "base_domain_approval": (base or {}).get("approval") if row.get("extends_approved") else None,
            "decision": (row.get("proposal") or {}).get("decision"),
            "proposal": {k: (row.get("proposal") or {}).get(k) for k in ("proposed_by", "proposed_on", "decision")},
            "approval": row.get("approval") if approved else None,
            "recorded_measurement": row.get("measured"),
            "operator_note": notes.get(name),
            "freshness": freshness.get(name),
            "verdict": None,
            "missing": [],
            "criteria": [],
            "live": None,
            "approval_effects": approval_effects(row, None) if not approved else [],
        }
        if gates is not None:
            m = (gates.get("measured") or {}).get(name) or {}
            wf = list(m.get("writer_files") or [])
            live = [
                f
                for f in (gates.get("live_findings") or [])
                + (gates.get("live_warnings") or [])
                + (gates.get("live_readers") or [])
                if _domain_of(f) == name
                or (f.get("check") == "DICTIONARY_INVALID" and f"[{name}]" in str(f.get("where")))
            ]
            out["live"] = {
                "writer_files": _cut(wf),
                "surface_reads": {k: _cut(v) for k, v in (m.get("surface_reads") or {}).items()},
                "store_readers": _cut(list((gates.get("store_readers") or {}).get(name) or [])),
                "findings": [_brief(f) for f in live],
                "warn_count": sum(1 for f in live if f in (gates.get("live_warnings") or [])),
            }
            gaps = [
                f
                for f in gates.get("sim_findings") or []
                if _domain_of(f) == name
                or (f.get("check") == "DICTIONARY_INVALID" and f"[{name}]" in str(f.get("where")))
            ]
            gaps += writer_claim_findings(row, wf)
            by_crit: dict[str, list[dict]] = {}
            for f in gaps:
                by_crit.setdefault(_CHECK_TO_CRITERION.get(f.get("check"), "row_valid"), []).append(f)
            out["criteria"] = [
                {
                    "id": c["id"],
                    "label": c["label"],
                    "source": c["source"],
                    "ok": c["id"] not in by_crit,
                    "gaps": [_gap_text(f) for f in by_crit.get(c["id"], [])],
                }
                for c in CRITERIA
            ]
            out["missing"] = [g for c in out["criteria"] for g in c["gaps"]]
            out["approval_effects"] = approval_effects(row, m) if not approved else []
            if approved:
                out["verdict"] = APPROVED
            else:
                out["verdict"] = NOT_READY if out["missing"] else READY
        rows_out.append(out)
    # approved §7A domains that a proposed row extends are listed once, under the proposed row
    summary = {
        "approved": sum(1 for r in rows_out if r["verdict"] == APPROVED),
        "ready": sum(1 for r in rows_out if r["verdict"] == READY),
        "not_ready": sum(1 for r in rows_out if r["verdict"] == NOT_READY),
        "unchecked": sum(1 for r in rows_out if r["verdict"] is None),
        "findings": sum(len((r.get("live") or {}).get("findings") or []) for r in rows_out),
        "operator_approved_pending_pr": sorted(
            r["domain"]
            for r in rows_out
            if (r.get("operator_note") or {}).get("approval_given") and r["verdict"] != APPROVED
        ),
    }
    return {
        "schema": SCHEMA,
        "rows": rows_out,
        "summary": summary,
        "criteria": [{"id": c["id"], "label": c["label"], "source": c["source"]} for c in CRITERIA],
    }


# ── the cached, bounded view the API serves ────────────────────────────────────────────────────────────────────────


class ReadinessCache:
    """Single-flight background refresh. A request never waits on the scan: it gets the last result (with its age)
    and, when that is older than the TTL, starts one refresh. Until the first scan finishes, rows carry the registry
    facts only and ``verdict`` None."""

    def __init__(
        self,
        root: Path,
        *,
        ttl_s: int = CACHE_TTL_S,
        table_probe_factory: Optional[Callable[[], Optional[Callable]]] = None,
        clock: Callable[[], datetime] = _utc_now,
        background: bool = True,
    ):
        self.root = Path(root)
        self.ttl_s = ttl_s
        self.table_probe_factory = table_probe_factory
        self.clock = clock
        self.background = background
        self._lock = threading.Lock()
        self._result: Optional[dict] = None  # {"gates", "freshness", "at", "duration_s"} or {"error", "at"}
        self._mono: Optional[float] = None
        self._running = False

    def _auth(self) -> dict:
        return json.loads((self.root / AUTHORITY_REL).read_text(encoding="utf-8"))

    def _scan(self) -> None:
        try:
            auth = self._auth()
            gates = run_gates(auth, self.root)
            probe = self.table_probe_factory() if self.table_probe_factory else None
            try:
                fresh = measure_freshness(auth, self.clock(), probe)
            finally:
                closer = getattr(probe, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:  # noqa: BLE001
                        pass
            res = {"gates": gates, "freshness": fresh, "at": _iso(self.clock()), "duration_s": gates["duration_s"]}
        except Exception as exc:  # noqa: BLE001 — a failed scan is shown as FAILED, never as ready
            res = {"error": f"{type(exc).__name__}: {str(exc)[:200]}", "at": _iso(self.clock())}
        with self._lock:
            if "error" not in res or self._result is None or "error" in self._result:
                self._result = res
            else:  # keep the last good scan, but say the refresh failed
                self._result = dict(self._result, refresh_error=res["error"])
            self._mono = time.monotonic()
            self._running = False

    def _maybe_refresh(self) -> None:
        with self._lock:
            due = self._mono is None or (time.monotonic() - self._mono) > self.ttl_s
            if not due or self._running:
                return
            self._running = True
        if self.background:
            threading.Thread(target=self._scan, name="data-domain-readiness", daemon=True).start()
        else:
            self._scan()

    def view(self) -> dict:
        self._maybe_refresh()
        auth = self._auth()
        with self._lock:
            res = self._result
            running = self._running
            age = None if self._mono is None else int(time.monotonic() - self._mono)
        notes = load_notes(self.root)
        if res and "gates" in res:
            out = assess(auth, res["gates"], res.get("freshness"), notes)
            scan = {
                "state": "DONE",
                "as_of": res["at"],
                "age_s": age,
                "duration_s": res.get("duration_s"),
                "refreshing": running,
                "refresh_error": res.get("refresh_error"),
            }
        else:
            out = assess(auth, None, None, notes)
            scan = {
                "state": "FAILED" if res and "error" in res else "RUNNING",
                "as_of": (res or {}).get("at"),
                "age_s": age,
                "error": (res or {}).get("error"),
                "refreshing": running,
            }
        out["scan"] = scan
        out["ttl_s"] = self.ttl_s
        return out


_CACHES: dict[str, ReadinessCache] = {}
_CACHES_LOCK = threading.Lock()


def _default_probe_factory() -> Optional[Callable]:
    try:
        from scripts import db_adapter  # type: ignore
    except Exception:  # noqa: BLE001
        try:
            import db_adapter  # type: ignore
        except Exception:  # noqa: BLE001
            return None
    if os.environ.get("TRADEAI_DATA_READINESS_NO_DB") == "1":
        return None
    probe = pg_table_probe(db_adapter.ensure_conn)
    probe.close = getattr(db_adapter, "close_thread_conn", None)  # type: ignore[attr-defined]
    return probe


def cached_view(root: Path, **kw) -> dict:
    key = str(Path(root).resolve())
    with _CACHES_LOCK:
        c = _CACHES.get(key)
        if c is None:
            kw.setdefault("table_probe_factory", _default_probe_factory)
            c = _CACHES[key] = ReadinessCache(Path(root), **kw)
    return c.view()


def main(argv: Optional[list[str]] = None) -> int:
    """``python scripts/lib/data_domain_readiness.py [--json] [--no-db]`` — one synchronous scan, printed."""
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-db", action="store_true", help="skip the table freshness probe")
    a = ap.parse_args(argv)
    c = ReadinessCache(_ROOT, background=False, table_probe_factory=None if a.no_db else _default_probe_factory)
    v = c.view()
    if a.json:
        print(json.dumps(v, indent=2, default=str))
        return 0
    s = v["summary"]
    print(
        f"Data-domain readiness ({v['scan']['state']}, {v['scan'].get('duration_s')}s): approved={s['approved']} "
        f"ready={s['ready']} not_ready={s['not_ready']} findings={s['findings']}"
    )
    for r in v["rows"]:
        fr = r.get("freshness") or {}
        print(
            f"  {r['domain']:<22} {str(r['verdict']):<17} store={r['store']} writer={r['writer'] or r['writer_status']} "
            f"fresh={fr.get('state')}{'/STALE' if fr.get('stale') else ''}"
        )
        for g in r["missing"]:
            print(f"      - {g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
