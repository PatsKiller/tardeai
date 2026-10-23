"""The data dictionary inside the §7A authority registry: one store, one writer, one read path per fact.

WHY (operator, 2026-10-22, verbatim): "The CIO agent is supposed to tie all of this together, and it should
all be in persistent memory. One data store with everything; use the CIO agent and n8n to accomplish this.
This was supposed to be the baseline of the site." and "... we should also have a data dictionary that shows
one source of data."

The read-only inventory of 2026-10-22 measured 16 entities over 131 stores: the per-symbol prospect split over
seven-plus CIO stores, none GUID-keyed in Postgres; two registered authorities for positions; four watchlist
membership lists; stops, scans, catalysts, fused signals, CIO decisions, options and paper proposals and
alerts with no registry domain at all. This module is the dictionary half of the answer
(docs/architecture/CIO_PROSPECT_DATA_FOUNDATION.md is the architecture half).

WHERE IT LIVES
--------------
There is no second registry. Everything is in ``config/data_source_authority.json`` (AGENTS.md §7A):

* ``proposed_domains[]`` — rows an agent proposes, ``status: "proposed"`` and ``approval: null``. They sit
  outside ``domains[]`` on purpose: every consumer of ``domains[]`` (the data broker, the §7A table, the
  ``UNAPPROVED_SOURCE`` gate) keeps reading only what the operator granted. Promotion into ``domains[]``
  is the operator's grant (AGENTS.md §17) and is done with :func:`promote`.
* ``domains[].dictionary`` — the dictionary block an approved row carries after promotion: the measured
  ceilings that CI enforces (writer files, surface reads of each non-authoritative copy).
* ``data_dictionary`` — the field level: the canonical key, the identity aliases, the CIO prospect record's
  fields, and the key facts (positions, cash, marks, stops, basis, catalysts, scores, decisions, options
  ideas, alerts), each pointing at exactly one domain.

WHAT IS CHECKED (by scripts/check_data_source_authority.py, which calls :func:`evaluate`)
-----------------------------------------------------------------------------------------
    DICTIONARY_INVALID          a proposed row or field entry is malformed (always fails: it is our own text)
    DICTIONARY_SECOND_WRITER    more files write a dictionary store than its ceiling
    NON_AUTHORITATIVE_READ      a page/API surface file reads a derived or retiring copy more than its ceiling
For an APPROVED row (``domains[].dictionary``) the last two are findings and fail the build. For a PROPOSED
row they are warnings: printed, reported, never a failure — an unapproved source must not trip a ceiling
nobody granted.

What the scan structurally cannot see: writes or reads spelled any way other than ``INSERT INTO`` /
``UPDATE`` / ``COPY`` / ``FROM`` / ``JOIN`` + the table name, or a file's declared match markers; an ORM;
a path assembled from fragments that never spells the marker; surface files outside
``data_dictionary.surface_files``; anything outside ``scripts/``. The broker execution file set is never
opened (AGENTS.md §0 rule 2): the scan reuses the gate's lane exclusions for broker paths.

AUTHORITY: READ_ONLY_ADVISORY. Stdlib only. Reads repository files; writes nothing (``promote`` returns a
new dict and the caller decides whether to write it).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "DataDictionary@v1"
PROPOSED = "proposed"
COPY_ROLES = ("derived", "retiring", "history", "excluded")
#: Roles a page or API must never read directly: it reads the authoritative store through its projection.
SURFACE_FORBIDDEN_ROLES = ("derived", "retiring")
REQUIRED_PROPOSED_KEYS = (
    "domain", "status", "entity", "title", "class", "store", "cadence", "stale_after_hours", "freshness_sla",
    "refresh_lane", "readers", "derived_copies", "no_coverage", "proposal", "facts",
)
REQUIRED_PROPOSAL_KEYS = ("proposed_by", "proposed_on", "reference", "decision")
REQUIRED_LANE_KEYS = ("runner", "lane", "note")
LANE_RUNNERS = ("n8n", "host", "n8n_shadow_then_live", "event")
REQUIRED_FACT_KEYS = ("fact", "entity", "domain", "store", "field", "meaning")
REQUIRED_RECORD_FIELD_KEYS = ("field", "type", "meaning", "source")
#: Files never opened by the dictionary scan (AGENTS.md §0 rule 2): the broker execution file set.
BROKER_EXCLUDE_PREFIXES = ("scripts/brokers/", "scripts/active_trader/", "scripts/moomoo/")
BROKER_EXCLUDE_FILES = ("scripts/lib/trading_session_grant.py", "scripts/schwab_transport.py",
                        "scripts/schwab_oco_bracket.py", "scripts/schwab_token_manager.py")
_WRITE_MARKER = re.compile(
    r"(write_text\(|write_bytes\(|json\.dump\(|atomic_write\w*\(|os\.replace\(|\.write\(|"
    r"open\([^)]*['\"](?:w|a|wb|ab|w\+|a\+)['\"])")
_WRITE_WINDOW = (3, 8)  # lines before / after a marker mention that count as "this file writes it"


class DictionaryError(ValueError):
    """The dictionary cannot be read at all. Never a pass."""


# ------------------------------------------------------------------------------------------------ helpers


def store_key(store: dict | None) -> str | None:
    """``table:x`` / ``file:y`` — the identity of a store, for one-owner checks."""
    if not isinstance(store, dict):
        return None
    if store.get("table"):
        return f"table:{store['table']}"
    if store.get("file"):
        return f"file:{store['file']}"
    return None


def _markers(store: dict) -> list[str]:
    """What a file store looks like in source: declared ``match`` markers, else its basename."""
    if store.get("match"):
        return [str(m) for m in store["match"]]
    return [Path(str(store["file"])).name]


def proposed_rows(auth: dict) -> list[dict]:
    rows = auth.get("proposed_domains") or []
    if not isinstance(rows, list):
        raise DictionaryError("proposed_domains must be a list")
    return rows


def approved_rows(auth: dict) -> list[dict]:
    """Approved domains that carry a dictionary block (promoted rows)."""
    return [d for d in auth.get("domains") or [] if isinstance(d.get("dictionary"), dict)]


def dictionary_rows(auth: dict) -> list[tuple[dict, bool]]:
    """``[(row, approved)]`` — approved rows first, then proposed ones."""
    return [(r, True) for r in approved_rows(auth)] + [(r, False) for r in proposed_rows(auth)]


def _excluded(rel: str) -> bool:
    return rel in BROKER_EXCLUDE_FILES or rel.startswith(BROKER_EXCLUDE_PREFIXES)


def source_files(root: Path) -> list[Path]:
    """``scripts/**/*.py|.sh`` minus tests, caches and the broker execution file set."""
    out = []
    for p in (root / "scripts").rglob("*"):
        if p.suffix not in (".py", ".sh") or not p.is_file() or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        if "/tests/" in rel or _excluded(rel):
            continue
        out.append(p)
    return sorted(out)


def surface_files(auth: dict, root: Path) -> list[Path]:
    """The page/API surface files named in ``data_dictionary.surface_files`` (globs, repo-relative)."""
    globs = (auth.get("data_dictionary") or {}).get("surface_files") or []
    out: set[Path] = set()
    for g in globs:
        for p in root.glob(g):
            if p.is_file() and not _excluded(p.relative_to(root).as_posix()):
                out.add(p)
    return sorted(out)


def _read(p: Path, cache: dict[Path, str]) -> str:
    if p not in cache:
        try:
            cache[p] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            cache[p] = ""
    return cache[p]


def writes_store(text: str, store: dict) -> bool:
    """True when ``text`` writes ``store``: SQL write verbs for a table, a write marker near a file marker."""
    if store.get("table"):
        t = re.escape(str(store["table"]))
        return bool(re.search(rf"\b(INSERT\s+INTO|UPDATE|COPY)\s+{t}\b", text, re.I))
    if store.get("file"):
        lines = text.splitlines()
        markers = _markers(store)
        before, after = _WRITE_WINDOW
        for i, line in enumerate(lines):
            if any(m in line for m in markers):
                window = "\n".join(lines[max(0, i - before): i + after + 1])
                if _WRITE_MARKER.search(window):
                    return True
    return False


def reads_store(text: str, store: dict) -> bool:
    """True when ``text`` reads ``store`` directly: ``FROM``/``JOIN`` a table, or spells a file marker."""
    if store.get("table"):
        t = re.escape(str(store["table"]))
        return bool(re.search(rf"\b(FROM|JOIN)\s+{t}\b", text, re.I))
    if store.get("file"):
        return any(m in text for m in _markers(store))
    return False


def _may_mention(p: Path, store: dict, cache: dict) -> bool:
    """Exact pre-filter, so the regexes run only on files that can match.

    A table matches only through ``\\b(VERB)\\s+<table>\\b`` under re.I, so a file whose lower-cased text lacks the
    lower-cased table name cannot match; a file store matches only where a marker is spelled (case-sensitive).
    The result is identical to running the regex on every file; it is ~10x faster (measured 2026-10-22: 39 s -> ~4 s
    over 3.5k files), which lets Ops -> Controls show live readiness (scripts/lib/data_domain_readiness.py).
    """
    if store.get("table"):
        key = ("lower", p)
        if key not in cache:
            cache[key] = _read(p, cache).lower()
        return str(store["table"]).lower() in cache[key]
    if store.get("file"):
        text = _read(p, cache)
        return any(m in text for m in _markers(store))
    return False


def writer_files(store: dict, files: Iterable[Path], root: Path, cache: dict[Path, str]) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in files
                  if _may_mention(p, store, cache) and writes_store(_read(p, cache), store))


def reader_files(store: dict, files: Iterable[Path], root: Path, cache: dict[Path, str]) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for p in files
                  if _may_mention(p, store, cache) and reads_store(_read(p, cache), store))


# --------------------------------------------------------------------------------------------- validation


def validate(auth: dict, root: Path | None = None) -> list[dict]:
    """``DICTIONARY_INVALID`` findings. Proposed rows are our own text, so a malformed one always fails."""
    out: list[dict] = []

    def bad(where: str, why: str) -> None:
        out.append({"check": "DICTIONARY_INVALID", "where": where, "why": why})

    approved_names = {d.get("domain") for d in auth.get("domains") or []}
    approved_by_store = {store_key(d.get("store")): d.get("domain") for d in auth.get("domains") or []
                         if store_key(d.get("store"))}
    seen: set[str] = set()
    owners: dict[str, str] = {}
    for row in proposed_rows(auth):
        name = str(row.get("domain") or "?")
        where = f"proposed_domains[{name}]"
        for k in REQUIRED_PROPOSED_KEYS:
            if k not in row or (row[k] in (None, "", []) and k != "derived_copies"):
                bad(where, f"missing {k}")
        if row.get("status") != PROPOSED:
            bad(where, f"status must be {PROPOSED!r} until the operator grants it (AGENTS.md §17)")
        if row.get("approval") not in (None, {}):
            bad(where, "a proposed row carries no approval; the grant is recorded at promotion")
        if name in seen:
            bad(where, "duplicate proposed domain")
        seen.add(name)
        if name in approved_names and not row.get("extends_approved"):
            bad(where, "name collides with an approved domain; set extends_approved: true to extend it")
        if row.get("extends_approved") and name not in approved_names:
            bad(where, "extends_approved names no approved domain")
        for s in row.get("supersedes") or []:
            if s not in approved_names:
                bad(where, f"supersedes unknown approved domain {s!r}")
        key = store_key(row.get("store"))
        if not key:
            bad(where, "store must name exactly one table or file")
        else:
            if key in owners:
                bad(where, f"store {key} is already authoritative in proposed row {owners[key]!r}")
            owners[key] = name
            owner = approved_by_store.get(key)
            if owner and owner != name and owner not in (row.get("supersedes") or []):
                bad(where, f"store {key} is the authoritative store of approved domain {owner!r}; "
                           "supersede it or extend it, never claim it twice")
        w = row.get("writer")
        if w:
            if root is not None and not (root / w).exists():
                bad(where, f"writer {w} does not exist")
        elif row.get("writer_status") != "UNCONSOLIDATED" or not row.get("writer_target"):
            bad(where, "no single writer: declare writer_status UNCONSOLIDATED and a writer_target")
        prop = row.get("proposal") or {}
        for k in REQUIRED_PROPOSAL_KEYS:
            if not str(prop.get(k) or "").strip():
                bad(where, f"proposal.{k} missing")
        lane = row.get("refresh_lane") or {}
        for k in REQUIRED_LANE_KEYS:
            if not str(lane.get(k) or "").strip():
                bad(where, f"refresh_lane.{k} missing")
        if lane.get("runner") and lane["runner"] not in LANE_RUNNERS:
            bad(where, f"refresh_lane.runner must be one of {LANE_RUNNERS}")
        if lane.get("never_list") and lane.get("runner") not in ("host", "event"):
            bad(where, "a lane on the AGENTS.md §23 never-list stays on the host")
        for c in row.get("derived_copies") or []:
            ck = store_key(c.get("store"))
            if not ck:
                bad(where, f"derived copy without a store: {c}")
            elif ck == key:
                bad(where, f"{ck} is both authoritative and a copy")
            owner_of_copy = approved_by_store.get(ck)
            if owner_of_copy and owner_of_copy != name and owner_of_copy not in (row.get("supersedes") or []):
                bad(where, f"copy {ck} is the authoritative store of approved domain {owner_of_copy!r}; "
                           "list it in supersedes (the operator decides the supersession)")
            if c.get("role") not in COPY_ROLES:
                bad(where, f"copy {ck} role must be one of {COPY_ROLES}")
            if not str(c.get("how") or "").strip():
                bad(where, f"copy {ck} must say how it is derived or retired")
            if c.get("role") == "retiring" and "archive" not in str(c.get("how")).lower():
                bad(where, f"retiring copy {ck} must name archive + tripwire (AGENTS.md §0 rule 6)")
    dd = auth.get("data_dictionary")
    if dd is None:
        return out
    if dd.get("schema") != SCHEMA:
        bad("data_dictionary", f"schema must be {SCHEMA!r}")
    all_names = approved_names | seen
    for fact in dd.get("facts") or []:
        where = f"data_dictionary.facts[{fact.get('fact')}]"
        for k in REQUIRED_FACT_KEYS:
            if not str(fact.get(k) or "").strip():
                bad(where, f"missing {k}")
        if fact.get("domain") and fact["domain"] not in all_names:
            bad(where, f"domain {fact['domain']!r} is neither approved nor proposed")
    for rname, rec in (dd.get("records") or {}).items():
        dom = rec.get("domain")
        if dom and dom not in all_names:
            bad(f"data_dictionary.records[{rname}]", f"domain {dom!r} is neither approved nor proposed")
        for f in rec.get("fields") or []:
            where = f"data_dictionary.records[{rname}].{f.get('field')}"
            for k in REQUIRED_RECORD_FIELD_KEYS:
                if not str(f.get(k) or "").strip():
                    bad(where, f"missing {k}")
    return out


# ------------------------------------------------------------------------------------------- enforcement


def _limits(row: dict, approved: bool) -> tuple[int, dict[str, int]]:
    """(writer ceiling, {copy store key: surface-read ceiling}).

    An approved row reads the ceilings recorded in its dictionary block at grant time (they may only fall).
    A proposed row is held to the target — one writer, no surface read of a copy — and, because it is not
    granted, every gap is a warning, never a failure.
    """
    block = (row.get("dictionary") or {}) if approved else {}
    writer_ceiling = int(block.get("writer_ceiling", 1))
    ceilings = block.get("surface_read_ceilings") or {}
    reads = {store_key(c.get("store")): int(ceilings.get(store_key(c.get("store")), 0))
             for c in row.get("derived_copies") or []}
    return writer_ceiling, reads


def measure(auth: dict, root: Path) -> dict[str, dict]:
    """Measured now, per dictionary row: writer files of its store and surface files reading each copy."""
    cache: dict[Path, str] = {}
    files = source_files(root)
    surfaces = surface_files(auth, root)
    out: dict[str, dict] = {}
    for row, _approved in dictionary_rows(auth):
        store = row.get("store") or {}
        m = {"writer_files": writer_files(store, files, root, cache), "surface_reads": {}}
        for c in row.get("derived_copies") or []:
            if c.get("role") not in SURFACE_FORBIDDEN_ROLES:
                continue
            ck = store_key(c.get("store"))
            m["surface_reads"][ck] = reader_files(c["store"], surfaces, root, cache)
        out[row["domain"]] = m
    return out


def evaluate(auth: dict, root: Path) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """(findings, warnings, measurements). Approved rows fail; proposed rows warn only."""
    findings = list(validate(auth, root))
    warnings: list[dict] = []
    measured = measure(auth, root)
    for row, approved in dictionary_rows(auth):
        name = row["domain"]
        m = measured[name]
        writer_ceiling, read_ceilings = _limits(row, approved)
        sink = findings if approved else warnings
        state = "approved" if approved else "proposed (warn only until the operator grants the row)"
        allowed = {row.get("writer")} | set(row.get("writers_allowed") or [])
        extra = [f for f in m["writer_files"] if f not in allowed]
        if len(m["writer_files"]) > writer_ceiling or (approved and writer_ceiling <= 1 and extra):
            sink.append({"check": "DICTIONARY_SECOND_WRITER", "domain": name, "state": state,
                         "store": store_key(row.get("store")), "ceiling": writer_ceiling,
                         "now": len(m["writer_files"]), "files": m["writer_files"],
                         "action": "write through the row's single writer; adding a writer is operator-only "
                                   "(AGENTS.md §7A, §17); the ceiling may only fall"})
        for ck, files in m["surface_reads"].items():
            ceiling = read_ceilings.get(ck, 0)
            if len(files) > ceiling:
                sink.append({"check": "NON_AUTHORITATIVE_READ", "domain": name, "state": state, "copy": ck,
                             "ceiling": ceiling, "now": len(files), "files": files,
                             "action": f"read {store_key(row.get('store'))} through projection "
                                       f"{row.get('projection') or '(to build)'}; a page or API never reads a "
                                       "derived or retiring copy (AGENTS.md §7A rule 3)"})
    return findings, warnings, measured


# ------------------------------------------------------------------------------------------------ promotion


def _count(v: Any) -> int:
    """A measurement is a file list (live scan) or a count (the registry's dated snapshot)."""
    if isinstance(v, (list, tuple, set)):
        return len(v)
    return int(v or 0)


def promote(auth: dict, domain: str, approval: dict, measured: dict | None = None) -> dict:
    """Return a new registry with proposed row ``domain`` granted: moved into ``domains[]`` with the
    operator's ``approval`` and a ``dictionary`` block whose ceilings are the measurements at grant time.

    The grant is the operator's (AGENTS.md §17); this only records it. Ceilings may only fall afterwards.
    Superseded approved domains are marked, never removed (consumers still read them until their readers
    move, batch by batch).
    """
    for k in ("approved_by", "approved_on", "reference", "scope"):
        if not str((approval or {}).get(k) or "").strip():
            raise DictionaryError(f"approval.{k} missing: no grant, no promotion")
    new = copy.deepcopy(auth)
    rows = proposed_rows(new)
    row = next((r for r in rows if r.get("domain") == domain), None)
    if row is None:
        raise DictionaryError(f"no proposed row {domain!r}")
    rows.remove(row)
    m = (measured or {}).get(domain) or row.get("measured") or {}
    reads = m.get("surface_reads") or {}
    dictionary = {
        "schema": SCHEMA,
        "entity": row.get("entity"),
        "writer_ceiling": max(1, _count(m.get("writer_files"))),
        "surface_read_ceilings": {k: _count(v) for k, v in reads.items()},
        "readers": row.get("readers"),
        "refresh_lane": row.get("refresh_lane"),
        "freshness_sla": row.get("freshness_sla"),
        "facts": row.get("facts"),
    }
    granted = {k: v for k, v in row.items() if k not in ("status", "proposal", "measured", "approval",
                                                         "extends_approved")}
    granted["approval"] = dict(approval)
    granted["dictionary"] = dictionary
    granted["proposal"] = row.get("proposal")
    domains = new.setdefault("domains", [])
    if row.get("extends_approved"):
        idx = next(i for i, d in enumerate(domains) if d.get("domain") == domain)
        merged = dict(domains[idx])
        merged.update(granted)
        domains[idx] = merged
    else:
        domains.append(granted)
    for d in domains:
        if d.get("domain") in (row.get("supersedes") or []):
            d["dictionary_superseded_by"] = domain
    return new

