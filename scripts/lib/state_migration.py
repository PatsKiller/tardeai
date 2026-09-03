#!/usr/bin/env python3
"""state_migration.py — per-store reconciliation planning for forked state stores.

Eighteen Command Center-critical stores exist twice: once under the producer
checkout root and once under the served persistent root. They are NOT all the
same kind of thing, and applying one merge algorithm to all of them would be the
defect, not the fix. A cache can be rebuilt; a tax lot cannot be guessed.

This module does the discovery and picks a strategy per store. It PLANS only —
it computes what the reconciled content would be and never writes it. The writing
side, its safeguards and its refusals live in ``scripts/migrate_state_stores.py``.

The rule that matters most is the one about financial truth: ``stops``,
``tax_lots``, ``performance_*`` and ``trade_journal`` fail closed when both sides
carry conflicting authoritative facts. Newer is not more correct. Picking a side
because its file was touched later is how a cost basis gets silently rewritten.

AUTHORITY: READ_ONLY_ADVISORY. Reads and hashes files, returns plans. No writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import grp
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "StateMigrationManifest@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
CALCULATION_VERSION = "1.0.0"

# ── reconciliation strategies ────────────────────────────────────────────────
IDENTICAL_BIND = "IDENTICAL_BIND"
AUTHORITATIVE_REPLACE = "AUTHORITATIVE_REPLACE"
APPEND_ONLY_UNION = "APPEND_ONLY_UNION"
VERSIONED_SNAPSHOT_SELECT = "VERSIONED_SNAPSHOT_SELECT"
REBUILD_DERIVED = "REBUILD_DERIVED"
MANUAL_CONFLICT = "MANUAL_CONFLICT"
RETIRE_DUPLICATE = "RETIRE_DUPLICATE"

STRATEGIES = (
    IDENTICAL_BIND,
    AUTHORITATIVE_REPLACE,
    APPEND_ONLY_UNION,
    VERSIONED_SNAPSHOT_SELECT,
    REBUILD_DERIVED,
    MANUAL_CONFLICT,
    RETIRE_DUPLICATE,
)

#: Record kinds. The kind decides which strategies are even eligible.
KIND_DOCUMENT = "replace-snapshot"
KIND_COLLECTION = "indexed-collection"
KIND_APPEND_LOG = "append-only"
KIND_CACHE = "cache"
KIND_DERIVED = "derived-projection"

#: Stores whose contents are financial truth. These may never be resolved by
#: recency, size or any other heuristic when both sides disagree on a fact.
FINANCIAL_STORES = frozenset(
    {"stops.json", "tax_lots.json", "trade_journal.json", "performance_history.json", "performance_attribution.json"}
)

#: Caches and derived projections: safe to rebuild from canonical upstream.
DERIVED_STORES = frozenset(
    {
        "ticker_enrichment_cache.json",
        "ai_analysis_cache.json",
        "finviz_quote_cache.json",
        "technical_snapshot.json",
        "correlation.json",
        "lookthrough_themes.json",
    }
)

#: Fields that are pure bookkeeping. A difference in these alone is not a
#: conflict of fact — it is the same fact observed at two times.
OBSERVATION_FIELDS = frozenset(
    {
        "synced_at",
        "updated_at",
        "generated_at",
        "as_of",
        "last_updated",
        "timestamp",
        "written_at",
        "cached_at",
        "_cached_at",
        "fetched_at",
        "observed_at",
    }
)

#: Timestamp fields consulted, in order, to decide which snapshot is newer.
#: Filesystem mtime is deliberately absent: a file can be touched without its
#: contents being any fresher, and that is exactly how the wrong side gets picked.
SNAPSHOT_TIME_FIELDS = (
    "generated_at",
    "completed_at",
    "captured_at",
    "as_of",
    "last_updated",
    "updated_at",
    "synced_at",
    "written_at",
    "timestamp",
    "cached_at",
)

#: Fields a list-shaped store may use as a stable record identity, in preference
#: order. Without one, a list cannot be unioned and must be refused rather than
#: merged positionally — positional merging silently drops or duplicates rows.
LIST_IDENTITY_FIELDS = ("id", "snapshot_id", "record_id", "date", "as_of", "key", "path")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def serialize(content: Any) -> bytes:
    """The ONE way reconciled content becomes bytes.

    The planned hash and the bytes actually written must come from the same
    function, or the post-write validation compares two different renderings of
    the same object and fails a correct migration. (It did exactly that once,
    which is how this function came to exist.)
    """
    return (json.dumps(content, indent=2, sort_keys=False, default=str) + "\n").encode()


def content_sha256(content: Any) -> str:
    return hashlib.sha256(serialize(content)).hexdigest()


def sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _stat(path: Path) -> dict[str, Any]:
    try:
        st = path.stat()
    except OSError:
        return {"exists": False}
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    return {
        "exists": True,
        "bytes": st.st_size,
        "mode": oct(st.st_mode & 0o777),
        "owner": owner,
        "group": group,
        "inode": st.st_ino,
        "mtime_utc": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
    }


def _load(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text()), None
    except FileNotFoundError:
        return None, "ABSENT"
    except OSError as exc:
        return None, f"UNREADABLE: {type(exc).__name__}"
    except ValueError as exc:
        return None, f"INVALID_JSON: {exc}"


def classify_kind(name: str, doc: Any) -> str:
    """What sort of thing is this store? The kind gates the strategy."""
    if name in DERIVED_STORES:
        return KIND_CACHE if "cache" in name else KIND_DERIVED
    if isinstance(doc, list):
        return KIND_APPEND_LOG
    if isinstance(doc, dict):
        keys = [k for k in doc if not str(k).startswith("_")]
        sample = doc.get(keys[0]) if keys else None
        if len(keys) > 3 and isinstance(sample, (dict, list)):
            return KIND_COLLECTION
    return KIND_DOCUMENT


def list_identity_field(doc: Any) -> str | None:
    """The field that identifies a row in a list-shaped store, if there is one.

    A candidate only counts when it is present on every row AND unique across
    them; otherwise 'merging by identity' would silently drop records.
    """
    if not isinstance(doc, list) or not doc or not all(isinstance(r, dict) for r in doc):
        return None
    for field in LIST_IDENTITY_FIELDS:
        if all(field in r and r[field] is not None for r in doc):
            values = [str(r[field]) for r in doc]
            if len(set(values)) == len(values):
                return field
    return None


def _records(doc: Any) -> dict[str, Any] | None:
    """Identity -> record, for collection-shaped stores. None when not a collection.

    Handles both dict-of-records and list-of-records; a list without a stable
    unique identity field is deliberately NOT treated as a collection, so it can
    never be silently unioned.
    """
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if not str(k).startswith("_")}
    if isinstance(doc, list):
        field = list_identity_field(doc)
        if field is None:
            return None
        return {str(r[field]): r for r in doc}
    return None


def _schema_marker(doc: Any) -> str | None:
    if isinstance(doc, dict):
        for k in ("schema", "schema_version", "contract_version", "version", "calculation_version"):
            v = doc.get(k)
            if isinstance(v, str):
                return v
        meta = doc.get("_agent_metadata")
        if isinstance(meta, dict):
            for k in ("schema", "version"):
                if isinstance(meta.get(k), str):
                    return meta[k]
    return None


def _snapshot_time(doc: Any) -> str | None:
    """The store's own statement of when it was produced. Never the file mtime."""
    if not isinstance(doc, dict):
        return None
    for field in SNAPSHOT_TIME_FIELDS:
        v = doc.get(field)
        if isinstance(v, str) and v.strip():
            return v
    meta = doc.get("_agent_metadata")
    if isinstance(meta, dict):
        for field in SNAPSHOT_TIME_FIELDS:
            v = meta.get(field)
            if isinstance(v, str) and v.strip():
                return v
    return None


def _material_diff(a: Any, b: Any) -> dict[str, Any]:
    """Differences that are NOT merely a re-observation of the same fact.

    Two records that agree on every field except ``synced_at`` describe one fact
    seen twice. Two records that disagree on ``shares`` describe two claims about
    the world, and only one of them can be right.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        out = {}
        for f in sorted(set(a) | set(b)):
            if f in OBSERVATION_FIELDS:
                continue
            if a.get(f) != b.get(f):
                out[f] = {"producer": a.get(f), "served": b.get(f)}
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return {"_length": {"producer": len(a), "served": len(b)}}
        out = {}
        for i, (x, y) in enumerate(zip(a, b)):
            d = _material_diff(x, y)
            if d:
                out[f"[{i}]"] = d
        return out
    return {} if a == b else {"_value": {"producer": a, "served": b}}


def compare_records(p_doc: Any, s_doc: Any) -> dict[str, Any]:
    """Unique and conflicting records on each side."""
    pr, sr = _records(p_doc), _records(s_doc)
    if pr is None or sr is None:
        same = json.dumps(p_doc, sort_keys=True, default=str) == json.dumps(s_doc, sort_keys=True, default=str)
        return {
            "comparable": False,
            "identical": same,
            "producer_only": [],
            "served_only": [],
            "conflicting": [],
            "conflict_detail": {},
            "note": "not a keyed collection; compared whole-document",
        }
    p_only = sorted(set(pr) - set(sr))
    s_only = sorted(set(sr) - set(pr))
    conflicting, detail, restamped = [], {}, []
    for k in sorted(set(pr) & set(sr)):
        # A top-level key that IS an observation field (last_updated, as_of, ...)
        # records when the store was written, not what it claims about the world.
        # Counting it as a conflicting record would make every re-run look like a
        # disagreement of fact.
        if k in OBSERVATION_FIELDS:
            if pr[k] != sr[k]:
                restamped.append(k)
            continue
        d = _material_diff(pr[k], sr[k])
        if d:
            conflicting.append(k)
            detail[k] = d
    return {
        "comparable": True,
        "identical": not (p_only or s_only or conflicting),
        "producer_record_count": len(pr),
        "served_record_count": len(sr),
        "producer_only": p_only,
        "served_only": s_only,
        "conflicting": conflicting,
        "conflict_detail": {k: detail[k] for k in conflicting[:10]},
        "observation_fields_restamped": restamped,
        "both_sides_hold_unique_records": bool(p_only) and bool(s_only),
    }


def select_strategy(name: str, kind: str, cmp_: dict[str, Any], p_doc: Any, s_doc: Any) -> tuple[str, str]:
    """Choose a reconciliation strategy, conservatively. Returns (strategy, why)."""
    financial = name in FINANCIAL_STORES

    if cmp_.get("identical"):
        return IDENTICAL_BIND, "both copies already carry identical content; only the binding differs"

    if kind in (KIND_CACHE, KIND_DERIVED):
        return REBUILD_DERIVED, (
            f"{name} is a {kind}: it is reproducible from canonical upstream inputs, so neither "
            "copy needs to win — regenerating is cheaper and safer than merging"
        )

    if financial and cmp_.get("conflicting"):
        return MANUAL_CONFLICT, (
            f"FAIL CLOSED: {name} is a financial truth store and both copies assert different "
            f"values for {len(cmp_['conflicting'])} record(s) ({', '.join(cmp_['conflicting'][:4])}). "
            "Choosing a side would be choosing a financial fact. An operator must reconcile these "
            "against the broker record."
        )

    if financial and cmp_.get("both_sides_hold_unique_records"):
        return MANUAL_CONFLICT, (
            f"FAIL CLOSED: {name} is a financial truth store and each copy holds records the other "
            "lacks; a union would fabricate a position set neither side ever asserted"
        )

    if cmp_.get("comparable") and not cmp_.get("conflicting"):
        if cmp_.get("producer_only") and not cmp_.get("served_only"):
            return AUTHORITATIVE_REPLACE, (
                "the producer copy is a strict superset with no conflicting record; the served copy "
                "contains no unique truth"
            )
        if cmp_.get("served_only") and not cmp_.get("producer_only"):
            return AUTHORITATIVE_REPLACE, (
                "the served copy is a strict superset with no conflicting record; the producer copy "
                "contains no unique truth"
            )
        if cmp_.get("both_sides_hold_unique_records"):
            return APPEND_ONLY_UNION, (
                "each copy holds records the other lacks and no shared record conflicts, so the "
                "union is well-defined by stable identity"
            )

    if kind == KIND_DOCUMENT:
        pt, st = _snapshot_time(p_doc), _snapshot_time(s_doc)
        if pt or st:
            return VERSIONED_SNAPSHOT_SELECT, (
                f"whole-document snapshot; selection uses the store's own observation time "
                f"(producer={pt!r} served={st!r}), never filesystem mtime"
            )
        return MANUAL_CONFLICT, (
            "whole-document snapshot with no observation metadata on either side: there is no "
            "non-arbitrary way to say which is current"
        )

    if cmp_.get("conflicting"):
        return VERSIONED_SNAPSHOT_SELECT, (
            f"{len(cmp_['conflicting'])} record(s) conflict in a non-financial collection; the "
            "store's own observation time selects per record"
        )
    return MANUAL_CONFLICT, "no strategy fits the observed shape; refusing to guess"


def _pick_newer(p_doc: Any, s_doc: Any) -> tuple[str, str | None, str | None]:
    pt, st = _snapshot_time(p_doc), _snapshot_time(s_doc)
    if pt and st:
        return ("producer" if pt >= st else "served"), pt, st
    if pt:
        return "producer", pt, st
    if st:
        return "served", pt, st
    return "undecidable", pt, st


def plan_content(strategy: str, p_doc: Any, s_doc: Any, cmp_: dict[str, Any]) -> tuple[Any | None, dict[str, Any]]:
    """Compute what the reconciled content WOULD be. Never writes it."""
    note: dict[str, Any] = {}
    if strategy == IDENTICAL_BIND:
        return p_doc, {"action": "no content change; bind the canonical root"}
    if strategy == AUTHORITATIVE_REPLACE:
        side = "producer" if cmp_.get("producer_only") else "served"
        note["authoritative_side"] = side
        note["reason"] = "strict superset with no conflicting record"
        return (p_doc if side == "producer" else s_doc), note
    if strategy == APPEND_ONLY_UNION:
        pr, sr = _records(p_doc) or {}, _records(s_doc) or {}
        merged = dict(sr)
        merged.update(pr)  # shared records are byte-equal here, so order is immaterial
        base = dict(p_doc) if isinstance(p_doc, dict) else {}
        for k in list(base):
            if not str(k).startswith("_"):
                base.pop(k)
        base.update(merged)
        note.update(
            {
                "action": "union by stable identity",
                "records": len(merged),
                "from_producer_only": len(cmp_.get("producer_only") or []),
                "from_served_only": len(cmp_.get("served_only") or []),
            }
        )
        return base, note
    if strategy == VERSIONED_SNAPSHOT_SELECT:
        side, pt, st = _pick_newer(p_doc, s_doc)
        note.update(
            {
                "selected_side": side,
                "producer_observation_time": pt,
                "served_observation_time": st,
                "rule": "the store's own observation metadata, never filesystem mtime",
            }
        )
        if side == "undecidable":
            return None, {**note, "refused": "neither copy states when it was produced"}
        return (p_doc if side == "producer" else s_doc), note
    if strategy == REBUILD_DERIVED:
        return None, {"action": "regenerate from canonical upstream inputs; no copy is promoted"}
    if strategy == MANUAL_CONFLICT:
        return None, {"refused": "operator reconciliation required"}
    if strategy == RETIRE_DUPLICATE:
        return None, {"action": "retire only after producers and consumers have moved"}
    return None, {"refused": f"unknown strategy {strategy!r}"}


def _grep_files(needle: str, *paths: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "grep", "-l", "-F", needle, "--", *(paths or ("scripts/", "tools/", "bin/"))],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except Exception:  # noqa: BLE001
        return []
    return sorted({p for p in out.splitlines() if p.strip()})


WRITE_IDIOMS = (
    "open(",
    ".write_text",
    ".write_bytes",
    "json.dump",
    "atomic_write",
    "write_json",
    "save_json",
    "os.replace",
    "shutil.move",
    ".unlink",
)
WRITE_PROXIMITY_LINES = 8


def _classify_reference(path: Path, needle: str) -> str:
    """WRITER if the store name sits near a write idiom in this file, else MENTION.

    This is a heuristic and is labelled as one. It exists so that an operator-facing
    pause list is not built from every file that merely reads or names a store —
    api_v2.py mentions all 88 stores and writes almost none of them.
    """
    try:
        lines = (ROOT / path).read_text(errors="replace").splitlines()
    except Exception:  # noqa: BLE001
        return "MENTION"
    hits = [i for i, ln in enumerate(lines) if needle in ln]
    for i in hits:
        lo = max(0, i - WRITE_PROXIMITY_LINES)
        hi = min(len(lines), i + WRITE_PROXIMITY_LINES + 1)
        window = "\n".join(lines[lo:hi])
        if any(idiom in window for idiom in WRITE_IDIOMS):
            return "WRITER"
    return "MENTION"


def _split_writers(files: list[str], needle: str) -> tuple[list[str], list[str]]:
    """Split files that name a store into probable writers and mere mentions."""
    writers, mentions = [], []
    for f in files:
        (writers if _classify_reference(Path(f), needle) == "WRITER" else mentions).append(f)
    return writers, mentions


def _token_match(stem: str, haystack: str) -> bool:
    """True only on a whole-token match.

    A substring test made the stem "runner" match "glib-pacrunner.service", which put an
    unrelated system unit on an operator's pause list. Schedules are matched on token
    boundaries so a stem can only match a real invocation of that script.
    """
    # Script stems use "_" and "-" internally, so both count as word characters here.
    # Otherwise the stem "health_agent" matches the different script
    # "health_agent_llm_review.py" and pauses a job that writes something else.
    pattern = r"(?<![A-Za-z0-9_-])" + re.escape(stem) + r"(?![A-Za-z0-9_-])"
    return re.search(pattern, haystack) is not None


def _producer_schedule(writers: list[str]) -> dict[str, Any]:
    """systemd units / cron entries that run any of these writers.

    ADVISORY. Returned as a structured record, never a bare list, so the caller cannot
    mistake a heuristic for a verified inventory. The operator must confirm the pause
    list against the running system before quiescing anything.
    """
    stems = {Path(w).stem for w in writers}
    record: dict[str, Any] = {
        "authority": "ADVISORY_HEURISTIC",
        "match_rule": "whole-token match of a confirmed-writer script stem",
        "requires_operator_confirmation": True,
        "matched_writer_stems": sorted(stems),
        "cron": [],
        "systemd": [],
        "truncated": False,
    }
    if not stems:
        return record

    try:
        cron = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        cron = ""
    for line in cron.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        matched = sorted(s for s in stems if _token_match(s, stripped))
        if matched:
            record["cron"].append({"entry": re.sub(r"\s+", " ", stripped), "matched_stems": matched})

    try:
        units = subprocess.run(
            ["systemctl", "--user", "list-unit-files", "--type=service", "--plain", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
    except Exception:  # noqa: BLE001
        units = ""
    for line in units.splitlines():
        parts = line.split()
        name = parts[0] if parts else ""
        if not name.endswith(".service"):
            continue
        matched = sorted(s for s in stems if _token_match(s.replace("_", "-"), name) or _token_match(s, name))
        if matched:
            record["systemd"].append({"unit": name, "matched_stems": matched})

    return record


def discover_store(name: str, producer_root: Path, served_root: Path) -> dict[str, Any]:
    """Everything a migration needs to know about one store, before any decision."""
    p_path, s_path = producer_root / name, served_root / name
    p_stat, s_stat = _stat(p_path), _stat(s_path)
    p_doc, p_err = _load(p_path)
    s_doc, s_err = _load(s_path)
    p_hash, s_hash = sha256_file(p_path), sha256_file(s_path)

    kind = classify_kind(name, p_doc if p_doc is not None else s_doc)
    cmp_ = compare_records(p_doc, s_doc)
    strategy, why = select_strategy(name, kind, cmp_, p_doc, s_doc)
    planned, plan_note = plan_content(strategy, p_doc, s_doc, cmp_)

    referencing = _grep_files(name)
    writers, mentions = _split_writers(referencing, name)
    consumers = _grep_files(name, "scripts/", "apps/")

    return {
        "store": name,
        "producer_path": str(p_path),
        "served_path": str(s_path),
        "canonical_target": str(s_path),
        "canonical_rule": ("the served persistent root is canonical: it is what the running service reads"),
        "kind": kind,
        "financial_truth_store": name in FINANCIAL_STORES,
        "producer": {
            **p_stat,
            "sha256": p_hash,
            "parse_error": p_err,
            "schema": _schema_marker(p_doc),
            "observation_time": _snapshot_time(p_doc),
            "record_count": len(_records(p_doc) or {})
            if _records(p_doc) is not None
            else (len(p_doc) if isinstance(p_doc, list) else None),
        },
        "served": {
            **s_stat,
            "sha256": s_hash,
            "parse_error": s_err,
            "schema": _schema_marker(s_doc),
            "observation_time": _snapshot_time(s_doc),
            "record_count": len(_records(s_doc) or {})
            if _records(s_doc) is not None
            else (len(s_doc) if isinstance(s_doc, list) else None),
        },
        "comparison": cmp_,
        "strategy": strategy,
        "strategy_reason": why,
        "plan": plan_note,
        # Hashed with serialize(), the SAME function that writes the bytes, so the
        # post-write check compares like with like.
        "planned_content_sha256": (content_sha256(planned) if planned is not None else None),
        "requires_operator": strategy == MANUAL_CONFLICT,
        "producers": writers,
        "producers_rule": (
            "files whose reference to this store sits within "
            f"{WRITE_PROXIMITY_LINES} lines of a write idiom; heuristic, not proof"
        ),
        "mentions_only": mentions,
        "consumers": consumers,
        "producer_schedule": _producer_schedule(writers),
        "rollback_strategy": (
            "restore the timestamped pre-write backup of BOTH sides and re-verify both hashes; "
            "no source or backup is ever deleted"
        ),
        "validation_check": (
            f"post-write sha256 of {s_path} equals planned_content_sha256; JSON reparses; "
            f"record_count >= max(producer, served) for union strategies; schema marker unchanged"
        ),
    }


def build_manifest(stores: list[str], producer_root: Path, served_root: Path) -> dict[str, Any]:
    rows = [discover_store(n, producer_root, served_root) for n in stores]
    by_strategy: dict[str, int] = {}
    for r in rows:
        by_strategy[r["strategy"]] = by_strategy.get(r["strategy"], 0) + 1
    blocked = [r["store"] for r in rows if r["requires_operator"]]
    doc = {
        "schema": SCHEMA,
        "calculation_version": CALCULATION_VERSION,
        "authority": AUTHORITY,
        "generated_at_utc": _now(),
        "producer_root": str(producer_root),
        "served_root": str(served_root),
        "store_count": len(rows),
        "strategy_counts": dict(sorted(by_strategy.items())),
        "requires_operator": blocked,
        "auto_applicable": [r["store"] for r in rows if not r["requires_operator"]],
        "stores": rows,
        "rule": (
            "Financial truth stores fail closed on any conflicting authoritative fact. "
            "Recency never decides a financial value."
        ),
    }
    doc["manifest_sha256"] = manifest_hash(doc)
    return doc


def manifest_hash(doc: dict[str, Any]) -> str:
    """Stable hash over the manifest, excluding volatile fields."""
    body = {k: v for k, v in doc.items() if k not in ("generated_at_utc", "manifest_sha256")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
