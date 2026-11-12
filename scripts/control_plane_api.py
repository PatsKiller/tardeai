"""Read-only Command Center control-plane projections (R21).

This module deliberately contains no business decisions or mutation methods.  It
projects inexpensive metadata from canonical stores and returns an explicit
evidence/data-quality envelope for UI consumers.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_CLASS = "CURRENT_SMOKE"
READ_ONLY_ADVISORY = "READ_ONLY_ADVISORY"

# One registry map for every collection endpoint, including computed system/stores.
# Fallbacks are fixture/legacy filenames that MUST live in this map — no endpoint
# may open a bare path that is not listed here.
CONTROL_PLANE_DOMAINS: dict[str, dict[str, Any]] = {
    "system": {
        "kind": "computed",
        "store_ids": (),
        "fallbacks": (),
        "wrap_dict": False,
    },
    "agents": {
        "kind": "collection",
        "store_ids": ("cio.agent_traces",),
        "fallbacks": ("data/runtime/agent_registry.json",),
        "wrap_dict": False,
        "extract": "agent_traces",
    },
    "workflows": {
        "kind": "collection",
        "store_ids": ("cio.workflow_lineage",),
        "fallbacks": ("data/cio/cio_workflow_lineage.jsonl", "data/runtime/workflow_traces.json"),
        "wrap_dict": False,
        # LQ-20261107-223: one torn line (two interleaved appends) in 267,583 failed the whole list.
        # This append-only history skips a few unparseable complete lines and says how many.
        "skip_corrupt_lines": True,
    },
    "research": {
        "kind": "collection",
        "store_ids": ("research.hermes_requests", "research.raw", "research.current"),
        "fallbacks": ("data/runtime/research_attention.json",),
        "wrap_dict": False,
    },
    "stores": {
        "kind": "computed",
        "store_ids": (),
        "fallbacks": (
            "data/runtime/canonical_store_registry.json",
            "data/runtime/store_registry.json",
        ),
        "wrap_dict": False,
        "populated_markers": ("data/cio", "data/portfolios", "data/reconciliation"),
    },
    "identity": {
        "kind": "collection",
        "store_ids": ("identity.registry",),
        "fallbacks": ("data/runtime/identity_registry.json", "data/identity/identity_registry.json"),
        "wrap_dict": False,
    },
    "notifications": {
        "kind": "collection",
        "store_ids": ("notifications.audit", "notifications.outbox"),
        "fallbacks": ("data/runtime/notification_receipts.json",),
        "wrap_dict": False,
    },
    "learning": {
        "kind": "collection",
        "store_ids": ("cio.outcomes", "cio.feedback"),
        "fallbacks": ("data/runtime/learning_evidence.json",),
        "wrap_dict": False,
    },
    "maturity": {
        # Computed live truth (Lane T / campaign m2-canary). Historical
        # data/runtime/maturity_score_latest.json remains on disk as SUPERSEDED
        # evidence and is no longer the served collection body.
        "kind": "computed",
        "store_ids": ("runtime.maturity",),
        "fallbacks": ("data/runtime/maturity.json", "data/runtime/maturity_score_latest.json"),
        "wrap_dict": True,
    },
    "audit": {
        "kind": "collection",
        "store_ids": ("runtime.audit_claims",),
        "fallbacks": ("data/runtime/audit_capability_claims.json",),
        "wrap_dict": True,
    },
}

ROUTES = tuple(f"/api/v3/control-plane/{name}" for name in CONTROL_PLANE_DOMAINS)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha() -> str | None:
    for name in ("SOURCE_COMMIT", "BUILD_SHA", "GIT_SHA"):
        value = os.environ.get(name)
        if value:
            return value
    for path in (PROJECT_ROOT / "SOURCE_COMMIT", PROJECT_ROOT / "BUILD_SHA"):
        try:
            value = path.read_text().strip()
            if value:
                return value
        except OSError:
            pass
    return None


def _envelope(data: Any, *, quality: str = "AVAILABLE", evidence: str = EVIDENCE_CLASS) -> dict[str, Any]:
    return {
        "ok": quality not in {"BROKEN", "INVALID_SCHEMA"},
        "as_of": _now(),
        "source_sha": _sha(),
        "freshness": "CURRENT_SMOKE",
        "data_quality": quality,
        "evidence_class": evidence,
        "data": data,
    }


def _read_json(path: Path) -> tuple[Any | None, str]:
    try:
        with path.open() as handle:
            return json.load(handle), "AVAILABLE"
    except FileNotFoundError:
        return None, "UNAVAILABLE"
    except (OSError, ValueError):
        return None, "INVALID_SCHEMA"


_JSONL_COMPACT_EVERY = 5000


# LQ-20261107-177 / T-20261107-9bf308: a compacting JSONL read resumes where it stopped.
#
# The agents projection re-parsed the whole 138 MB, append-only ``agent_run_traces.jsonl`` on every GET
# (5-17 s) to keep one row per agent. ``compact`` is idempotent and already runs mid-stream, so starting
# from the compacted rows of the bytes read last time and parsing only what was appended is the same
# computation as one long stream. A tail read was rejected: it drops agents that have not woken lately.
#
# The cache is keyed by (path, keep, compact). It is trusted only while the file is the same inode, is
# no shorter than the offset reached, and still holds the same bytes at its head and just before that
# offset; anything else (rotation, truncation, an in-place rewrite) is a full read. A torn final line is
# parsed transiently, exactly as the full read would, and never cached. An unreadable or corrupt file is
# never cached. Callers get deep copies, so nothing they do reaches the cache.
_JSONL_CACHE_MAX = 16
_JSONL_FINGERPRINT_BYTES = 4096
_jsonl_cache: dict[tuple[str, int, int, bool], dict[str, Any]] = {}
#: A tolerant read gives up (INVALID_SCHEMA) beyond this many corrupt lines, or one per thousand if more.
_JSONL_CORRUPT_FLOOR = 10
_jsonl_cache_lock = threading.Lock()


def _jsonl_cache_clear() -> None:
    with _jsonl_cache_lock:
        _jsonl_cache.clear()


def _jsonl_fingerprint(handle: Any, offset: int) -> str:
    """Hash of the file's first bytes and of the bytes just before ``offset``."""
    digest = hashlib.blake2b(digest_size=16)
    handle.seek(0)
    digest.update(handle.read(min(offset, _JSONL_FINGERPRINT_BYTES)))
    start = max(0, offset - _JSONL_FINGERPRINT_BYTES)
    handle.seek(start)
    digest.update(handle.read(offset - start))
    return digest.hexdigest()


def _corrupt_limit(lines: int) -> int:
    return max(_JSONL_CORRUPT_FLOOR, lines // 1000)


def _jsonl_skipped(path: Path, *, keep: Any, compact: Any, tolerant: bool) -> int:
    """Corrupt lines the last tolerant read of ``path`` skipped (0 when none, or not cached)."""
    with _jsonl_cache_lock:
        entry = _jsonl_cache.get((str(path), id(keep), id(compact), tolerant)) or {}
        return int(entry.get("skipped") or 0)


def _read_jsonl_resumable(
    path: Path, *, keep: Any, compact: Any, tolerant: bool = False
) -> tuple[list[dict[str, Any]] | None, str]:
    """Resumable compacting read. ``tolerant`` skips (and counts) unparseable complete lines up to
    ``_corrupt_limit``; a strict read answers INVALID_SCHEMA for any one, as before."""
    key = (str(path), id(keep), id(compact), tolerant)
    with _jsonl_cache_lock:
        try:
            with path.open("rb") as handle:
                st = os.fstat(handle.fileno())
                entry = _jsonl_cache.get(key)
                if (
                    entry is None
                    or entry["dev_ino"] != (st.st_dev, st.st_ino)
                    or st.st_size < entry["offset"]
                    or _jsonl_fingerprint(handle, entry["offset"]) != entry["fingerprint"]
                ):
                    entry = {"dev_ino": (st.st_dev, st.st_ino), "offset": 0, "rows": [], "lines": 0, "skipped": 0}
                if st.st_size == entry["offset"] and "fingerprint" in entry:
                    return copy.deepcopy(entry["rows"]), "AVAILABLE"
                rows = copy.deepcopy(entry["rows"])
                compact_at = max(_JSONL_COMPACT_EVERY, 2 * len(rows))
                offset = entry["offset"]
                lines = int(entry.get("lines") or 0)
                skipped = int(entry.get("skipped") or 0)
                tail: dict[str, Any] | None = None
                handle.seek(offset)
                for raw in handle:
                    complete = raw.endswith(b"\n")
                    try:
                        line = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        if not tolerant:
                            raise
                        line = "\ufffd"  # counted as a corrupt line below
                    if line.strip():
                        try:
                            value = json.loads(line)
                        except ValueError:
                            value = None
                        if not isinstance(value, dict):
                            if not tolerant:
                                _jsonl_cache.pop(key, None)
                                return None, "INVALID_SCHEMA"
                            if not complete:
                                break  # a writer mid-append: neither counted nor cached; read again next time
                            lines += 1
                            skipped += 1
                            offset += len(raw)
                            continue
                        if complete:
                            lines += 1
                        if keep is None or keep(value):
                            if not complete:
                                tail = value  # a final line with no newline yet: answer with it, never cache it
                                break
                            rows.append(value)
                            if len(rows) >= compact_at:
                                rows = compact(rows)
                                compact_at = max(_JSONL_COMPACT_EVERY, 2 * len(rows))
                    if complete:
                        offset += len(raw)
                rows = compact(rows)
                _jsonl_cache.pop(key, None)
                if skipped > _corrupt_limit(lines):
                    return None, "INVALID_SCHEMA"
                if len(_jsonl_cache) >= _JSONL_CACHE_MAX:
                    _jsonl_cache.pop(next(iter(_jsonl_cache)))
                _jsonl_cache[key] = {
                    "dev_ino": (st.st_dev, st.st_ino),
                    "offset": offset,
                    "fingerprint": _jsonl_fingerprint(handle, offset),
                    "rows": copy.deepcopy(rows),
                    "lines": lines,
                    "skipped": skipped,
                }
                if tail is not None:
                    rows = compact([*rows, tail])
                return rows, "AVAILABLE"
        except FileNotFoundError:
            _jsonl_cache.pop(key, None)
            return None, "UNAVAILABLE"
        except UnicodeDecodeError:
            _jsonl_cache.pop(key, None)
            return None, "INVALID_SCHEMA"
        except OSError:
            _jsonl_cache.pop(key, None)
            return None, "UNAVAILABLE"


def _read_jsonl(
    path: Path, *, keep: Any = None, compact: Any = None, tolerant: bool = False
) -> tuple[list[dict[str, Any]] | None, str]:
    """Read an append-only projection without failing the whole endpoint on one bad row.

    Streams line by line. The previous ``read_text().splitlines()`` held the whole
    file twice (bytes-as-str plus the split list) before a single row was parsed;
    on the 150 MB workflow lineage that put ~800 MB on the API process for one
    GET, pushed the service past MemoryHigh and froze it until the watchdog
    SIGKILLed it (n8nmat reliability, 2026-10-09).

    ``keep(row) -> bool`` drops rows a caller will discard anyway, so they are
    never retained. ``compact(rows) -> rows`` is an idempotent reducer applied
    every ``_JSONL_COMPACT_EVERY`` retained rows (and once at the end), so a
    projection that collapses many rows into few never holds the whole file.
    Every line is still parsed: one corrupt row keeps the file INVALID_SCHEMA
    exactly as before.

    With a ``compact`` reducer the read resumes from the offset it reached last
    time (``_read_jsonl_resumable``); without one it is a plain streaming read.
    """
    if compact is not None:
        return _read_jsonl_resumable(path, keep=keep, compact=compact, tolerant=tolerant)
    try:
        rows: list[dict[str, Any]] = []
        compact_at = _JSONL_COMPACT_EVERY
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    return None, "INVALID_SCHEMA"
                if not isinstance(value, dict):
                    return None, "INVALID_SCHEMA"
                if keep is not None and not keep(value):
                    continue
                rows.append(value)
                if compact is not None and len(rows) >= compact_at:
                    rows = compact(rows)
                    # Never re-compact on every row when the reduced set is itself large.
                    compact_at = max(_JSONL_COMPACT_EVERY, 2 * len(rows))
        if compact is not None:
            rows = compact(rows)
        return rows, "AVAILABLE"
    except FileNotFoundError:
        return None, "UNAVAILABLE"
    except UnicodeDecodeError:
        return None, "INVALID_SCHEMA"
    except OSError:
        return None, "UNAVAILABLE"


def _read_jsonl_stream_tolerant(
    path: Path, *, keep: Any, skipped_out: dict[str, int] | None = None
) -> tuple[list[dict[str, Any]] | None, str]:
    """Plain streaming read of an append-only lineage that skips (and counts) corrupt complete lines.

    LQ-20261107-2407: the workflow DETAIL read was strict, so one torn line (two interleaved appends, 2026-11-03)
    made every workflow answer INVALID_SCHEMA while the LIST, which tolerates it, stayed AVAILABLE. Same policy
    as ``_read_jsonl_resumable(tolerant=True)``: an unparseable, non-dict or undecodable complete line is
    skipped and counted; a final line with no newline yet is a writer mid-append (neither counted nor kept);
    more than ``_corrupt_limit`` corrupt lines is INVALID_SCHEMA. Rows ``keep`` rejects are never retained.
    ``skipped_out["skipped"]`` receives the count."""
    rows: list[dict[str, Any]] = []
    lines = skipped = 0
    try:
        with path.open("rb") as handle:
            for raw in handle:
                complete = raw.endswith(b"\n")
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    line = "\ufffd"
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    value = None
                if not isinstance(value, dict):
                    if not complete:
                        break
                    lines += 1
                    skipped += 1
                    continue
                if complete:
                    lines += 1
                if keep is None or keep(value):
                    rows.append(value)
    except FileNotFoundError:
        return None, "UNAVAILABLE"
    except OSError:
        return None, "UNAVAILABLE"
    if skipped > _corrupt_limit(lines):
        return None, "INVALID_SCHEMA"
    if skipped_out is not None:
        skipped_out["skipped"] = skipped
    return rows, "AVAILABLE"


def _read_jsonl_head(path: Path, retain: int) -> tuple[list[dict[str, Any]] | None, int, str]:
    """(first ``retain`` rows, total rows, quality) of a plain JSONL source, holding at most ``retain`` rows.

    LQ-20261107-2215: a list page shows ``limit`` rows from ``offset`` plus the total. Building the whole
    row list for that (twice: the parse, then ``_extract_rows``' copy) put ~285 MB on the API process
    for the 97 MB research request log. Every line is still parsed, so one corrupt row is still
    INVALID_SCHEMA exactly as ``_read_jsonl`` answers it; only rows past the page are not retained.
    """
    head: list[dict[str, Any]] = []
    total = 0
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    return None, 0, "INVALID_SCHEMA"
                if not isinstance(value, dict):
                    return None, 0, "INVALID_SCHEMA"
                total += 1
                if len(head) < retain:
                    head.append(value)
        return head, total, "AVAILABLE"
    except FileNotFoundError:
        return None, 0, "UNAVAILABLE"
    except UnicodeDecodeError:
        return None, 0, "INVALID_SCHEMA"
    except OSError:
        return None, 0, "UNAVAILABLE"


def _workflow_list_keep(row: dict[str, Any]) -> bool:
    """The workflow LIST never shows raw node/edge rows (see _project_workflow_collection).

    Dropping them while streaming gives the same projection: envelopes win when
    present, otherwise the untyped leftovers, otherwise the rows unchanged.
    """
    return row.get("record_type") not in {"node", "edge"}


def _state_root() -> Path:
    """Resolve the runtime state root; deployment may override the code directory."""
    for key in ("TRADEAI_STATE_ROOT", "TRADEAI_ROOT", "TRADEAI_PERSISTENT_STATE_ROOT"):
        value = os.environ.get(key)
        if value:
            return Path(value)
    return PROJECT_ROOT


def _canonical_paths(store_ids: tuple[str, ...], fallbacks: tuple[str, ...] = ()) -> tuple[Path, ...]:
    """Resolve logical stores through CanonicalStoreRegistry, retaining test fallbacks."""
    root = _state_root()
    paths: list[Path] = []
    try:
        from scripts.lib.canonical_store_registry import resolve_store
        for store_id in store_ids:
            loc = resolve_store(store_id, root=root)
            spec = loc.get("spec") or {}
            primary = loc.get("primary_path")
            if primary:
                paths.append(Path(primary))
            found = loc.get("path")
            if found:
                paths.append(Path(found))
            for alias in spec.get("aliases") or []:
                paths.append(root / alias)
    except Exception:
        pass
    paths.extend(root / p for p in fallbacks)
    # An explicitly pinned state root is honoured, not widened back to the repo.
    #
    # This used to also append PROJECT_ROOT/<fallback> whenever root differed,
    # "to preserve the historical PROJECT_ROOT fixture behavior when
    # monkeypatched". The effect was that TRADEAI_STATE_ROOT could not actually
    # isolate anything: a caller pinning an empty root still read files out of
    # the checkout. test_whole_site_truth::test_an_empty_state_root_is_never_
    # reported_live passed only because those repo paths happened not to exist,
    # so creating a single file --
    #     data/cio/cio_workflow_lineage.jsonl
    # -- made /v3/control-plane/workflows answer LIVE against an empty root and
    # failed the gate. Reproduced exactly that way on 2026-09-13, which is what
    # a fresh CI clone was doing once a test suite wrote into data/cio.
    #
    # Production is unaffected: none of TRADEAI_STATE_ROOT, TRADEAI_ROOT or
    # TRADEAI_PERSISTENT_STATE_ROOT is set on the host, so _state_root() returns
    # PROJECT_ROOT and this branch never fired there. It only ever changed
    # behaviour for callers that pinned a root on purpose -- which is precisely
    # the case where the pin should be obeyed.
    return tuple(dict.fromkeys(paths))


def _domain_paths(domain: str) -> tuple[Path, ...]:
    spec = CONTROL_PLANE_DOMAINS[domain]
    return _canonical_paths(tuple(spec.get("store_ids") or ()), tuple(spec.get("fallbacks") or ()))


def _bounded(query: dict[str, Any]) -> tuple[int, int]:
    def integer(key: str, default: int) -> int:
        value = query.get(key, default)
        if isinstance(value, list):
            value = value[0] if value else default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return max(1, min(200, integer("limit", 50))), max(0, integer("offset", 0))


def _paged(rows: list[dict[str, Any]], query: dict[str, Any]) -> dict[str, Any]:
    limit, offset = _bounded(query)
    return {"items": rows[offset : offset + limit], "pagination": {"limit": limit, "offset": offset, "total": len(rows)}}


def _empty_page(query: dict[str, Any]) -> dict[str, Any]:
    limit, offset = _bounded(query)
    return {"items": [], "pagination": {"limit": limit, "offset": offset, "total": 0}}


#: The 21 keys the Agent Office detail panel reads (``AgentOfficePage.tsx``, ``AgentDetailPanel``).
#: A row that cannot fill them all states how many it fills instead of presenting four as the whole.
AGENT_CONTRACT_FIELDS = (
    "agent_id", "role", "runtime_state", "trigger_classes", "last_wake", "wake_reason",
    "current_task", "entity_refs", "queue_depth", "last_success", "last_failure", "last_artifact",
    "research_route", "model_route", "latency", "cost", "next_eligible_wake", "evidence_class",
    "status", "data_quality", "source_sha",
)

#: Explicit status vocabularies. A trace status outside both sets is neither a success nor a
#: failure, and is recorded as neither -- an unrecognised word must not become a green tick.
_TRACE_SUCCESS_STATUSES = frozenset({"completed", "complete", "ok", "success", "succeeded", "done"})
_TRACE_FAILURE_STATUSES = frozenset({
    "failed", "failure", "error", "errored", "aborted", "timeout", "timed_out", "crashed", "exception",
})


def _coalesce(*values: Any) -> Any:
    """The first value that is actually present; a null stays null when nothing fills it."""
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _later(a: Any, b: Any) -> Any:
    """The later of two ISO timestamps; the present one when the other is absent."""
    sa, sb = str(a or ""), str(b or "")
    if not sb:
        return a
    if not sa:
        return b
    return a if sa >= sb else b


def _iso_seconds(start: Any, end: Any) -> float | None:
    """Seconds between two ISO timestamps, or None when either is absent or unparseable."""
    def parse(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    first, last = parse(start), parse(end)
    if first is None or last is None:
        return None
    # Six decimals: a sub-millisecond wake must not round to a plausible 0.0.
    return round((last - first).total_seconds(), 6)


def _trace_latency(row: dict[str, Any]) -> Any:
    """started_at → ended_at for a live trace row; a compacted projection carries its own latency."""
    latency = _iso_seconds(row.get("started_at"), row.get("ended_at"))
    return latency if latency is not None else row.get("latency")


def _agent_contract_markers(row: dict[str, Any]) -> dict[str, Any]:
    """State how much of the 21-key contract a row fills; `data_quality` follows the count.

    ``data_quality`` was a hard-coded AVAILABLE default, so a trace row carrying four of the
    twenty-one keys was served exactly like a complete one. The marker is recomputed on every row
    this module builds; a quality some other producer set (anything but this function's own
    AVAILABLE/PARTIAL) is left alone.
    """
    total = len(AGENT_CONTRACT_FIELDS)
    missing = [key for key in AGENT_CONTRACT_FIELDS if key != "data_quality" and row.get(key) in (None, "")]
    prior = row.get("data_quality")
    if prior in (None, "", "AVAILABLE", "PARTIAL"):
        row["data_quality"] = "AVAILABLE" if not missing else "PARTIAL"
    row["contract_fields_present"] = f"{total - len(missing)}/{total}"
    row["contract_fields_missing"] = missing
    return row


def _agents_from_traces(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per agent, read from the agent's own trace rows.

    The trace store is the only source behind the agents collection, and the source row carries
    ``trigger``, ``decision.current_action``, ``trace_id``, ``status`` and a start/end pair. Those
    fill ``wake_reason``, ``current_task``, ``last_artifact``, ``status`` and ``latency`` with what
    the row says; everything the row does not carry stays null. Before 2026-11-07 this kept four
    keys and the detail panel rendered the other seventeen as null under an AVAILABLE envelope.

    Idempotent: ``_read_jsonl`` compacts with this function every few thousand rows, so a row this
    function produced is a legal input. That is why its own keys are read as fallbacks, and why
    ``last_success``/``last_failure`` are the max over the agent's rows rather than the latest row's.
    """
    by_agent: dict[str, dict[str, Any]] = {}
    for row in rows:
        agent_id = str(row.get("agent") or row.get("agent_id") or "")
        if not agent_id:
            continue
        decision = row.get("decision") if isinstance(row.get("decision"), dict) else {}
        status = _coalesce(row.get("status"), row.get("runtime_state"))
        last_wake = _coalesce(row.get("ended_at"), row.get("started_at"), row.get("last_wake"))
        stamp = _coalesce(row.get("ended_at"), last_wake)
        success = row.get("last_success")
        failure = row.get("last_failure")
        verdict = str(status or "").lower()
        if verdict in _TRACE_SUCCESS_STATUSES:
            success = _later(success, stamp)
        elif verdict in _TRACE_FAILURE_STATUSES:
            failure = _later(failure, stamp)
        candidate = {
            "agent_id": agent_id,
            "role": _coalesce(row.get("role")),
            "last_wake": last_wake,
            "runtime_state": status,
            "wake_reason": _coalesce(row.get("trigger"), row.get("wake_reason")),
            "current_task": _coalesce(decision.get("current_action"), row.get("current_task")),
            "last_artifact": _coalesce(row.get("trace_id"), row.get("last_artifact")),
            "latency": _trace_latency(row),
            "last_success": success,
            "last_failure": failure,
            "status": status,
            # Every row reaching this projection came out of the trace store: a live runtime row,
            # not a fixture and not a declaration.
            "evidence_class": _coalesce(row.get("evidence_class"), "CURRENT_SMOKE"),
            "source_sha": _coalesce(row.get("source_sha"), _sha()),
        }
        existing = by_agent.get(agent_id)
        if existing is not None:
            # Successes and failures accumulate across the agent's whole history, not just the
            # newest row: a failure keeps showing after the next wake succeeds.
            candidate["last_success"] = _later(existing.get("last_success"), candidate["last_success"])
            candidate["last_failure"] = _later(existing.get("last_failure"), candidate["last_failure"])
        if existing is None or str(last_wake or "") >= str(existing.get("last_wake") or ""):
            by_agent[agent_id] = candidate
    return [_agent_contract_markers(row) for row in by_agent.values()]


def _is_agent_trace_source(path: Path) -> bool:
    return path.name == "agent_run_traces.jsonl" or (
        path.suffix.lower() == ".jsonl" and "agent_run_trace" in path.name
    )


def _project_workflow_collection(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer latest envelope per workflow; ignore raw node/edge rows on the list."""
    if not rows:
        return rows
    types = {str(r.get("record_type") or "") for r in rows}
    if not (types & {"envelope", "node", "edge"}):
        return rows
    envelopes: dict[str, dict[str, Any]] = {}
    leftovers: list[dict[str, Any]] = []
    for row in rows:
        rt = row.get("record_type")
        if rt == "envelope":
            wf = str(row.get("workflow_id") or "")
            if wf:
                envelopes[wf] = row
            continue
        if rt in {"node", "edge"}:
            continue
        leftovers.append(row)
    if envelopes:
        return list(envelopes.values())
    return leftovers


def _jsonl_compactor(domain: str, path: Path) -> Any:
    """Idempotent reducer for a JSONL source whose projection collapses rows, else None."""
    if domain == "agents" and _is_agent_trace_source(path):
        return _agents_from_traces
    if domain == "workflows":
        return _project_workflow_collection
    return None


# ── LQ-20261107-223: shape each store into the row contract its page renders ─────────────────────────────────────
#
# The pages render fixed columns; a row missing them showed the literal "undefined". Each projection keeps every
# source field and only adds the contract keys it can derive. A value it cannot derive is None (shown "absent"),
# never invented: no score, no evidence class, no security id minted from a ticker.

_LEARNING_KIND_BY_SCHEMA = {"OutcomeObservation@v1": "outcome", "DecisionDisposition": "decision"}
_LEARNING_KEYS = ("item_id", "kind", "status", "score", "evidence_class", "proof_refs", "limiting_factor", "next_proof")
_OFFICE_AUDIT_FRESH_S = 7 * 86400


def _identity_rows(registry: dict[str, Any]) -> list[dict[str, Any]]:
    """``IdentityRegistry@v1`` entities as identity rows. ``entity_id`` is the registered key, never a ticker."""
    as_of = registry.get("updated_at")
    rows = []
    for key, ent in (registry.get("entities") or {}).items():
        if not isinstance(ent, dict):
            continue
        row = dict(ent)
        row.update(
            {
                "entity_id": ent.get("subject_guid") or str(key),
                "issuer": ent.get("issuer_guid"),
                "security": ent.get("security_guid"),
                "listing": ent.get("listing_guid"),
                "aliases": ent.get("aliases") or [],
                "identifiers": ent.get("identifiers") or {},
                "state": ent.get("identity_status"),
                "unresolved_reason": ent.get("unresolved_reason"),
                "source": "identity.registry",
                "as_of": ent.get("last_seen") or as_of,
            }
        )
        rows.append(row)
    return rows


def _learning_row(row: dict[str, Any]) -> dict[str, Any]:
    if all(k in row for k in _LEARNING_KEYS):
        return row
    out = dict(row)
    kind = row.get("kind") or _LEARNING_KIND_BY_SCHEMA.get(str(row.get("schema") or ""))
    realized = row.get("realized_state") if isinstance(row.get("realized_state"), dict) else {}
    linked = realized.get("linked")
    status = row.get("status")
    if status is None and isinstance(linked, bool):
        status = "LINKED" if linked else "UNLINKED"
    out.setdefault("item_id", row.get("outcome_id") or row.get("disposition_id") or row.get("decision_id"))
    out["kind"] = kind
    out["status"] = status
    out.setdefault("score", None)
    out.setdefault("evidence_class", None)
    refs = row.get("proof_refs", row.get("source_refs"))
    out["proof_refs"] = list(refs) if isinstance(refs, list) else []
    out.setdefault("limiting_factor", "outcome not linked to its decision" if linked is False else None)
    out.setdefault("next_proof", None)
    return out


def _office_audit_claims(audit: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    """A CIO office browser-audit run (scripts/cc_v3_cio_office_audit.py) as one claim per audited viewport."""
    try:
        evidence_ref = str(path.relative_to(_state_root()))
    except ValueError:
        evidence_ref = path.name
    audited_at = audit.get("audited_at")
    fresh = False
    try:
        ts = datetime.fromisoformat(str(audited_at).replace("Z", "+00:00"))
        fresh = (datetime.now(timezone.utc) - ts).total_seconds() <= _OFFICE_AUDIT_FRESH_S
    except (TypeError, ValueError):
        pass
    target = audit.get("target") or "/v3/cio"
    claims = []
    for res in audit.get("results") or []:
        if not isinstance(res, dict):
            continue
        viewport, width = res.get("viewport"), res.get("width")
        issues = [str(i) for i in res.get("issues") or []]
        failed = [str(s.get("section")) for s in res.get("sections") or [] if isinstance(s, dict) and not s.get("ok")]
        ok = bool(res.get("ok")) and not failed
        limits = [f"audited_at {audited_at}" + ("" if fresh else " (older than 7 days)")]
        if failed:
            limits.append("failed sections: " + ", ".join(failed))
        if issues:
            limits.append("issues: " + "; ".join(issues[:5]))
        claims.append(
            {
                "claim_id": f"office-audit:{viewport}:{width}",
                "claim": f"{target} renders every audited section at {viewport} {width}px",
                "status": "PASSED" if ok else "FAILED",
                "implementation_ref": "scripts/cc_v3_cio_office_audit.py",
                "test_ref": "tests/test_cc_v3_cio_office_audit.py",
                "evidence_ref": evidence_ref,
                "evidence_class": "CURRENT_SMOKE" if fresh else None,
                "limitations": "; ".join(limits),
                "reproduction_command": "python scripts/cc_v3_cio_office_audit.py",
                "section": "runtime",
                "audited_at": audited_at,
            }
        )
    return claims


def _extract_rows(value: Any, *, domain: str, path: Path) -> list[dict[str, Any]] | None:
    rows = _extract_rows_raw(value, domain=domain, path=path)
    if rows is not None and domain == "learning":
        return [_learning_row(r) for r in rows]
    return rows


def _extract_rows_raw(value: Any, *, domain: str, path: Path) -> list[dict[str, Any]] | None:
    """Return usable rows, or None to skip this path (do not AVAILABLE-empty-steal)."""
    spec = CONTROL_PLANE_DOMAINS.get(domain) or {}
    wrap_dict = bool(spec.get("wrap_dict"))

    if isinstance(value, list):
        rows = [dict(row) for row in value if isinstance(row, dict)]
        if domain == "agents" and _is_agent_trace_source(path):
            return _agents_from_traces(rows)
        if domain == "workflows":
            return _project_workflow_collection(rows)
        return rows

    if not isinstance(value, dict):
        return None

    if domain == "identity" and isinstance(value.get("entities"), dict):
        return _identity_rows(value)
    if domain == "audit" and isinstance(value.get("results"), list) and "audited_at" in value:
        return _office_audit_claims(value, path)

    for key in ("items", "rows", "data"):
        nested = value.get(key)
        if isinstance(nested, list):
            return [dict(row) for row in nested if isinstance(row, dict)]

    by_research = value.get("by_research_id")
    if isinstance(by_research, dict):
        rows = []
        for key, row in by_research.items():
            if isinstance(row, dict):
                item = dict(row)
                item.setdefault("research_id", key)
                rows.append(item)
            else:
                rows.append({"research_id": str(key), "value": row})
        return rows

    if wrap_dict:
        return [dict(value)]

    # Dict without items/rows/data/by_research_id and not a wrap-dict domain.
    return None


def _select_rows(
    paths: tuple[Path, ...], *, domain: str, meta: dict[str, Any] | None = None, retain: int | None = None,
    row_keep: Any = None, tolerant_stream: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """First-AVAILABLE over registry-ordered candidates.

    ``row_keep(row) -> bool`` (LQ-20261107-2241) is a streaming filter for a ``.jsonl`` candidate read with
    ``domain=""``: rows it rejects are never retained, so a caller that wants one workflow does not hold the
    whole lineage. Every line is still parsed, so a corrupt line is still INVALID_SCHEMA. ``meta["streamed"]``
    is set True when the filter was applied; a ``.json`` candidate is returned whole and unfiltered.
    ``tolerant_stream`` (LQ-20261107-2407) makes that filtered read skip and count corrupt complete lines
    (``meta["skipped_corrupt_lines"]``) instead of answering INVALID_SCHEMA for the first one.

    missing → continue
    invalid JSON → try next unless it is the only existing unreadable primary
    usable rows (including empty list) → AVAILABLE
    unusable shape → skip to next path (do not AVAILABLE empty)
    """
    seen_invalid = False
    seen_valid = False
    from scripts.lib.maturity_score_latest_reader import (
        is_archived_maturity_score_path,
        stamp_maturity_score_payload,
    )

    for path in paths:
        # Archive copy is not current. Do not open it.
        if is_archived_maturity_score_path(path):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() == ".jsonl":
            keep = _workflow_list_keep if domain == "workflows" else None
            if row_keep is not None and domain == "":
                keep = row_keep
                if meta is not None:
                    meta["streamed"] = True
            compact = _jsonl_compactor(domain, path)
            tolerant = bool(CONTROL_PLANE_DOMAINS.get(domain, {}).get("skip_corrupt_lines")) and compact is not None
            if retain is not None and compact is None and keep is None and meta is not None:
                # A page read of a plain JSONL source: hold the page, count the rest (LQ-20261107-2215).
                # _extract_rows maps a list 1:1 per dict row for every domain that reaches here (the
                # reshaping domains, agents traces and workflows, always have a compactor), so the
                # first ``retain`` rows of the file are the first ``retain`` rows of the projection.
                value, total, quality = _read_jsonl_head(path, retain)
                if quality == "AVAILABLE":
                    meta["total"] = total
            elif tolerant_stream and meta is not None and meta.get("streamed"):
                skipped_box: dict[str, int] = {}
                value, quality = _read_jsonl_stream_tolerant(path, keep=keep, skipped_out=skipped_box)
                if quality == "AVAILABLE":
                    meta["skipped_corrupt_lines"] = skipped_box.get("skipped", 0)
            else:
                value, quality = _read_jsonl(path, keep=keep, compact=compact, tolerant=tolerant)
            if tolerant and quality == "AVAILABLE" and meta is not None:
                meta["skipped_corrupt_lines"] = _jsonl_skipped(path, keep=keep, compact=compact, tolerant=True)
        else:
            value, quality = _read_json(path)
        if quality == "INVALID_SCHEMA":
            seen_invalid = True
            continue
        if quality != "AVAILABLE":
            continue
        seen_valid = True
        if path.name == "maturity_score_latest.json":
            if not isinstance(value, dict):
                return [], "STALE"
            stamped = stamp_maturity_score_payload(value)
            out_quality = "STALE" if stamped.get("freshness") == "STALE" else "AVAILABLE"
            return [dict(stamped)], out_quality
        rows = _extract_rows(value, domain=domain, path=path)
        if rows is None:
            continue
        return rows, "AVAILABLE"
    if seen_invalid and not seen_valid:
        return [], "INVALID_SCHEMA"
    return [], "UNAVAILABLE"


def _count_workflow_projection(path: Path) -> tuple[int, str]:
    """(rows the workflow LIST projection would hold, quality) for a lineage ``.jsonl``, holding no rows.

    LQ-20261107-2355: ``control-plane-surface-authority`` probes every domain only to read ``data_quality`` and
    a page's ``item_count``; for the 216 MB lineage that built the whole projection (plus a deep copy for the
    resumable cache) in a throwaway child: ~290 MB maxrss. This mirrors ``_read_jsonl_resumable`` line for line
    (tolerant skip of corrupt complete lines, a torn final line neither counted nor skipped, the same
    ``_corrupt_limit``) and ``_project_workflow_collection`` (the latest envelope per ``workflow_id`` wins; with
    no such envelope, the untyped leftovers; node/edge rows never count), keeping only the workflow ids.
    Any answer other than AVAILABLE is reported as such and the caller falls back to the full read.
    """
    ids: set[str] = set()
    leftovers = 0
    lines = skipped = 0
    try:
        with path.open("rb") as handle:
            for raw in handle:
                complete = raw.endswith(b"\n")
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    line = "\ufffd"
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    value = None
                if not isinstance(value, dict):
                    if not complete:
                        break
                    lines += 1
                    skipped += 1
                    continue
                if complete:
                    lines += 1
                rt = value.get("record_type")
                if rt in {"node", "edge"}:
                    continue
                if rt == "envelope":
                    wf = str(value.get("workflow_id") or "")
                    if wf:
                        ids.add(wf)
                    continue
                leftovers += 1
                if not complete:
                    break
    except FileNotFoundError:
        return 0, "UNAVAILABLE"
    except OSError:
        return 0, "UNAVAILABLE"
    if skipped > _corrupt_limit(lines):
        return 0, "INVALID_SCHEMA"
    return (len(ids) if ids else leftovers), "AVAILABLE"


def _count_agent_projection(path: Path) -> tuple[int, str]:
    """(rows the agents LIST projection would hold, quality) for an agent-trace ``.jsonl``, holding no rows.

    LQ-20261107-2367: after the workflows probe stopped reading rows, the agents domain was the largest holder in the
    ``control-plane-surface-authority`` child (a 140 MB trace file streamed through ``_agents_from_traces``: ~70 MB
    transient peak for a one-row answer). The projection keeps one row per non-empty
    ``str(row.get("agent") or row.get("agent_id") or "")`` and the compactor is idempotent (its own rows carry
    ``agent_id``), so the row count is the number of distinct ids over every dict row, torn final line included
    (``_read_jsonl_resumable`` answers with it, uncached). Mirrors the STRICT read the agents domain uses: any
    non-dict line or undecodable byte answers "INVALID_SCHEMA" here and the caller falls back to the full read.
    """
    ids: set[str] = set()
    try:
        with path.open("rb") as handle:
            for raw in handle:
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    return 0, "INVALID_SCHEMA"
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    return 0, "INVALID_SCHEMA"
                if not isinstance(value, dict):
                    return 0, "INVALID_SCHEMA"
                agent_id = str(value.get("agent") or value.get("agent_id") or "")
                if agent_id:
                    ids.add(agent_id)
    except (FileNotFoundError, OSError):
        return 0, "UNAVAILABLE"
    return len(ids), "AVAILABLE"


def probe_domain_envelope(domain: str, query: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]] | None:
    """The envelope ``handle("/api/v3/control-plane/<domain>")`` would answer, built without the rows, or None.

    Only the workflow lineage and the agent traces (LQ-20261107-2367) have a cheap equivalent; every other domain, and any doubt (the first usable
    candidate is not a plain ``.jsonl``, anything but AVAILABLE), returns None and the caller reads in full.
    The page is ``item_count`` placeholders long and carries the same envelope fields, so a caller that
    reads only the envelope and ``len(data["items"])`` cannot tell the difference.
    """
    if domain not in ("workflows", "agents"):
        return None
    from scripts.lib.maturity_score_latest_reader import is_archived_maturity_score_path

    for path in _domain_paths(domain):
        if is_archived_maturity_score_path(path) or not path.is_file():
            continue
        if path.suffix.lower() != ".jsonl":
            return None
        if domain == "agents":
            if not _is_agent_trace_source(path):
                return None
            n, quality = _count_agent_projection(path)
        else:
            n, quality = _count_workflow_projection(path)
        if quality != "AVAILABLE":
            return None
        limit, offset = _bounded(query or {})
        page = {"items": [None] * max(0, min(limit, n - offset)), "pagination": {"limit": limit, "offset": offset, "total": n}}
        return 200, _envelope(page, quality="AVAILABLE")
    return None


# ── LQ-20261107-2407: the workflow LIST holds an offset index, not the rows ──────────────────────────────────────
#
# The list kept every workflow's latest envelope (34,791 dicts: 139 MB traced, ~230 MB RSS after the call) and
# deep-copied them all per request (+64 MB) to show 50. This keeps ``workflow_id -> (offset, length)`` of that
# workflow's latest envelope line (about 5 MB) and parses only the page's lines from the file. The index is built
# and resumed exactly like ``_read_jsonl_resumable``: same inode, no shorter than the offset reached, same
# bytes at the head and before the offset, else a full re-scan; a torn final line is read for the answer and never
# cached; corrupt complete lines are skipped and counted with the same ``_corrupt_limit``. Order is the order
# ``_project_workflow_collection`` gives: first appearance of a workflow, its latest envelope.
_wf_index_cache: dict[str, dict[str, Any]] = {}
_wf_index_lock = threading.Lock()


def _wf_index_clear() -> None:
    with _wf_index_lock:
        _wf_index_cache.clear()


def _wf_index_update(path: Path) -> dict[str, Any] | None:
    """The (possibly resumed) index entry for ``path`` or None to make the caller use the full read.

    Caller holds ``_wf_index_lock``. The returned entry carries ``index`` (wf -> (offset, length)), ``skipped``,
    ``lines``, ``envelopes`` (bool) and, transiently, ``tail`` = (wf, offset, length) for a valid final envelope
    line that has no newline yet."""
    key = str(path)
    try:
        with path.open("rb") as handle:
            st = os.fstat(handle.fileno())
            entry = _wf_index_cache.get(key)
            if (
                entry is None
                or entry["dev_ino"] != (st.st_dev, st.st_ino)
                or st.st_size < entry["offset"]
                or _jsonl_fingerprint(handle, entry["offset"]) != entry["fingerprint"]
            ):
                entry = {"dev_ino": (st.st_dev, st.st_ino), "offset": 0, "index": {}, "lines": 0, "skipped": 0,
                         "envelopes": False}
            offset = entry["offset"]
            if st.st_size == offset and "fingerprint" in entry:
                return {**entry, "tail": None}
            index = entry["index"]
            lines, skipped, envelopes = int(entry["lines"]), int(entry["skipped"]), bool(entry["envelopes"])
            tail = None
            handle.seek(offset)
            for raw in handle:
                complete = raw.endswith(b"\n")
                try:
                    line = raw.decode("utf-8")
                except UnicodeDecodeError:
                    line = "\ufffd"
                if line.strip():
                    try:
                        value = json.loads(line)
                    except ValueError:
                        value = None
                    if not isinstance(value, dict):
                        if not complete:
                            break
                        lines += 1
                        skipped += 1
                        offset += len(raw)
                        continue
                    if complete:
                        lines += 1
                    rt = value.get("record_type")
                    if rt == "envelope":
                        envelopes = True
                        wf = str(value.get("workflow_id") or "")
                        if wf:
                            if not complete:
                                tail = (wf, offset, len(raw))
                                break
                            index[wf] = (offset, len(raw))
                    elif not complete:
                        break
                if complete:
                    offset += len(raw)
            if skipped > _corrupt_limit(lines):
                _wf_index_cache.pop(key, None)
                return None
            entry = {
                "dev_ino": (st.st_dev, st.st_ino), "offset": offset, "index": index, "lines": lines,
                "skipped": skipped, "envelopes": envelopes, "fingerprint": _jsonl_fingerprint(handle, offset),
            }
            _wf_index_cache[key] = entry
            return {**entry, "tail": tail}
    except (OSError, ValueError):
        _wf_index_cache.pop(key, None)
        return None


def _workflow_page_from_index(paths: tuple[Path, ...], query: dict[str, Any]) -> tuple[dict[str, Any], str] | None:
    """The workflow LIST page built from the offset index, or None to use the full read (any doubt)."""
    from scripts.lib.maturity_score_latest_reader import is_archived_maturity_score_path

    path = next((p for p in paths if not is_archived_maturity_score_path(p) and p.is_file()), None)
    if path is None or path.suffix.lower() != ".jsonl":
        return None
    limit, offset = _bounded(query)
    with _wf_index_lock:
        entry = _wf_index_update(path)
        if entry is None or not (entry["index"] or entry["tail"]):
            return None  # no workflow-id envelope (untyped / leftover-only store) or unreadable: the full read decides
        index, tail = entry["index"], entry["tail"]
        keys = list(index)
        if tail is not None and tail[0] not in index:
            keys.append(tail[0])
        total = len(keys)
        window = [(wf, tail[1:] if tail is not None and wf == tail[0] else index[wf]) for wf in keys[offset: offset + limit]]
        skipped = int(entry["skipped"])
    items: list[dict[str, Any]] = []
    try:
        with path.open("rb") as handle:
            for wf, (start, length) in window:
                handle.seek(start)
                value = json.loads(handle.read(length).decode("utf-8"))
                if not isinstance(value, dict) or value.get("record_type") != "envelope" or str(value.get("workflow_id") or "") != wf:
                    return None  # the file moved under the index: do not guess
                items.append(value)
    except (OSError, ValueError):
        return None
    page: dict[str, Any] = {"items": items, "pagination": {"limit": limit, "offset": offset, "total": total}}
    if skipped:
        page["skipped_corrupt_lines"] = skipped
    return page, "AVAILABLE"


def _rows_from_json(paths: tuple[Path, ...], query: dict[str, Any], *, domain: str) -> tuple[dict[str, Any], str]:
    if domain == "workflows":
        indexed = _workflow_page_from_index(paths, query)
        if indexed is not None:
            return indexed
    meta: dict[str, Any] = {}
    limit, offset = _bounded(query)
    rows, quality = _select_rows(paths, domain=domain, meta=meta, retain=offset + limit)
    # STALE is a stamped score payload, not an empty store. AVAILABLE stays the
    # only quality that means current.
    if quality not in {"AVAILABLE", "STALE"}:
        return _empty_page(query), quality
    page = _paged(rows, query)
    if meta.get("total") is not None:
        page["pagination"]["total"] = meta["total"]
    if meta.get("skipped_corrupt_lines"):
        page["skipped_corrupt_lines"] = meta["skipped_corrupt_lines"]
    return page, quality


def _load_rows(paths: tuple[Path, ...], *, domain: str = "") -> tuple[list[dict[str, Any]], str]:
    """Load bounded projection inputs without replaying or mutating domain state."""
    return _select_rows(paths, domain=domain)


def _collection(domain: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    return _rows_from_json(_domain_paths(domain), query, domain=domain)


def _agent_detail(agent_id: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    rows, quality = _load_rows(_domain_paths("agents"), domain="agents")
    match = next((row for row in rows if str(row.get("agent_id") or row.get("id")) == agent_id), None)
    if match is None:
        if quality == "UNAVAILABLE":
            return {"status": "UNAVAILABLE_BACKEND", "agent_id": agent_id}, quality
        return {"status": "UNKNOWN_AGENT", "agent_id": agent_id}, "NO_RELEVANT_EVENTS"
    detail = {
        "agent_id": agent_id,
        "role": match.get("role"),
        "runtime_state": match.get("runtime_state", "REGISTERED_NO_RUNTIME"),
        # Absent is absent: an empty list here would read as "this agent declares none", which the
        # source never said. The completeness marker below counts a null as missing and a [] as
        # present, so the default must not manufacture one.
        "trigger_classes": match.get("trigger_classes"),
        "last_wake": match.get("last_wake"), "wake_reason": match.get("wake_reason"),
        "current_task": match.get("current_task"), "entity_refs": match.get("entity_refs"),
        "queue_depth": match.get("queue_depth"), "last_success": match.get("last_success"),
        "last_failure": match.get("last_failure"), "last_artifact": match.get("last_artifact"),
        "recent_artifacts": _paged([a for a in match.get("recent_artifacts", []) if isinstance(a, dict)], query),
        "research_route": match.get("research_route"), "model_route": match.get("model_route"),
        "process_route": match.get("process_route"), "latency": match.get("latency"),
        "cost": match.get("cost"), "next_eligible_wake": match.get("next_eligible_wake"),
        "evidence_class": match.get("evidence_class", "CURRENT_SMOKE"),
        "source_sha": _coalesce(match.get("source_sha"), _sha()), "as_of": match.get("as_of") or _now(),
        # No AVAILABLE default: the marker fills it from how much of the contract this row carries.
        "data_quality": match.get("data_quality"),
    }
    return _agent_contract_markers(detail), quality


NODE_TYPES = {
    "event": "SOURCE_EVENT", "source_event": "SOURCE_EVENT", "material_event": "SOURCE_EVENT",
    "entity": "ENTITY",
    "materiality": "MATERIALITY", "graph": "GRAPH_IMPACT", "graph_impact": "GRAPH_IMPACT",
    "research_gap": "RESEARCH_GAP", "research": "RESEARCH", "free_first": "FREE_FIRST",
    "specialist": "SPECIALIST_DISPATCH", "specialist_dispatch": "SPECIALIST_DISPATCH",
    "artifact": "SPECIALIST_ARTIFACT", "specialist_artifact": "SPECIALIST_ARTIFACT",
    "council": "COUNCIL", "cio": "CIO_PRODUCT", "cio_product": "CIO_PRODUCT",
    "notification": "NOTIFICATION", "checkpoint": "CHECKPOINT", "outcome": "OUTCOME",
    "lesson": "LESSON", "learning": "LEARNING", "hypothesis": "HYPOTHESIS",
}

WORKFLOW_ID_ALIASES = (
    "workflow_id", "event_id", "decision_id", "generation_id", "artifact_id",
    "notification_id", "checkpoint_id", "outcome_id", "research_id", "council_id",
    "entity_guid", "research_request_id", "research_artifact_id",
    "specialist_artifact_id", "cio_generation_id",
)

PARTIAL_CERTAINTY = {
    "UNRESOLVED_LINK", "LEGACY_REFERENCE", "MISSING_PARENT", "UNAVAILABLE_STORE", "QUARANTINED_RECORD",
}


def _identifiers(row: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    nested = row.get("identifiers")
    if isinstance(nested, dict):
        for key, value in nested.items():
            if value is not None and str(value):
                out[str(key)] = str(value)
    for key in WORKFLOW_ID_ALIASES:
        value = row.get(key)
        if value is not None and str(value):
            out[key] = str(value)
    return out


def _row_matches_workflow(row: dict[str, Any], workflow_id: str) -> bool:
    ids = _identifiers(row)
    return any(value == workflow_id for value in ids.values())


def _load_checkpoint_row(checkpoint_id: str) -> dict[str, Any] | None:
    if not checkpoint_id:
        return None
    rows, _quality = _load_rows(
        _canonical_paths(("cio.checkpoints",), ("data/cio/outcome_checkpoints.jsonl",)),
        domain="learning",
    )
    for row in rows:
        if str(row.get("checkpoint_id") or "") == str(checkpoint_id):
            return dict(row)
    return None


_ENVELOPE_ID_KEYS = (
    "workflow_id",
    "research_request_id",
    "research_artifact_id",
    "specialist_artifact_id",
    "cio_generation_id",
    "notification_id",
    "checkpoint_id",
    "event_id",
    "generation_id",
)
_TYPED_RECORDS = {"node", "edge", "envelope"}


def _fold_record_identifiers(identifiers: dict[str, str], record: dict[str, Any]) -> None:
    """How one envelope or node record contributes to its workflow's ``identifiers`` (shared by the grouping
    and by the streaming pre-pass, so the two cannot drift)."""
    rt = record.get("record_type")
    if rt == "envelope":
        for key in _ENVELOPE_ID_KEYS:
            if record.get(key):
                identifiers[key] = str(record[key])
    elif rt == "node":
        node_id = record.get("node_id")
        if node_id:
            identifiers.setdefault(str(record.get("node_type", "")).lower() + "_id", str(node_id))


def _workflow_rows_for(workflow_id: str, info: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], str]:
    """The lineage rows that can answer ``workflow_id``, without holding the whole lineage (LQ-20261107-2241).

    The detail used to load every row (``_select_rows(domain="")``): +763.9 MB for one GET on the 216 MB
    lineage (FINDING-LQ-2215). Two streaming passes now: pass 1 retains nothing but a small identifier
    summary per workflow (which workflows answer to ``workflow_id``); pass 2 retains only those workflows'
    rows, in file order. The result is exactly the rows the old code would have selected from, so
    ``_workflow_detail`` is unchanged. A ``.json`` store (not streamable) is returned whole as before.

    ``info`` (optional out-parameter) receives ``store_typed``: whether ANY row of the whole store is typed. The
    detail must decide typed-vs-legacy from the whole store, not from the retained subset: a workflow whose rows
    are all untyped, inside a typed store, is grouped by the old code (REVIEW-LQ-20261107-2261 F2).
    """
    paths = _domain_paths("workflows")
    summary: dict[str, dict[str, Any]] = {}
    seen = {"typed": False, "wf": False}

    def _survey(row: dict[str, Any]) -> bool:
        if row.get("record_type") in _TYPED_RECORDS:
            seen["typed"] = True
        wf = str(row.get("workflow_id") or "")
        if wf:
            seen["wf"] = True
            entry = summary.setdefault(wf, {"ids": {}, "checkpoint_id": None})
            _fold_record_identifiers(entry["ids"], row)
            if row.get("record_type") == "envelope":
                entry["checkpoint_id"] = row.get("checkpoint_id")
        return False

    def _select_pass2(keep: Any) -> tuple[list[dict[str, Any]], str]:
        meta2: dict[str, Any] = {}
        out = _select_rows(paths, domain="", meta=meta2, row_keep=keep, tolerant_stream=True)
        if info is not None:
            info["skipped_corrupt_lines"] = int(meta2.get("skipped_corrupt_lines") or 0)
        return out

    meta: dict[str, Any] = {}
    rows, quality = _select_rows(paths, domain="", meta=meta, row_keep=_survey, tolerant_stream=True)
    if info is not None:
        info["store_typed"] = bool(seen["typed"])
        info["skipped_corrupt_lines"] = int(meta.get("skipped_corrupt_lines") or 0)
    if not meta.get("streamed"):
        if info is not None:
            info.pop("store_typed", None)  # not surveyed: the caller derives it from the whole rows
        return rows, quality  # a .json store, or nothing readable: the old whole-store answer
    if seen["typed"] and seen["wf"]:
        matched = {
            wf for wf, e in summary.items()
            if _row_matches_workflow({"workflow_id": wf, "identifiers": e["ids"], "checkpoint_id": e["checkpoint_id"]}, workflow_id)
        }
        summary.clear()
        return _select_pass2(lambda r: str(r.get("workflow_id") or "") in matched)
    summary.clear()
    return _select_pass2(lambda r: _row_matches_workflow(r, workflow_id))


def _workflow_detail(workflow_id: str, query: dict[str, Any]) -> tuple[dict[str, Any], str]:
    # domain="" skips list projection so node/edge/envelope records remain.
    info: dict[str, Any] = {}
    rows, quality = _workflow_rows_for(workflow_id, info)
    skipped = int(info.get("skipped_corrupt_lines") or 0)
    grouped: dict[str, dict[str, Any]] = {}
    store_typed = info.get("store_typed")
    if store_typed is None:
        store_typed = any(r.get("record_type") in _TYPED_RECORDS for r in rows)
    if store_typed:
        for record in rows:
            wf = str(record.get("workflow_id") or "")
            if not wf:
                continue
            trace = grouped.setdefault(
                wf,
                {
                    "workflow_id": wf,
                    "identifiers": {},
                    "nodes": [],
                    "edges": [],
                    "evidence_class": record.get("evidence_class", "OPERATOR_REQUESTED_LIVE"),
                    "source_sha": record.get("source_sha", _sha()),
                },
            )
            rt = record.get("record_type")
            _fold_record_identifiers(trace["identifiers"], record)
            if rt == "envelope":
                trace["envelope"] = record
                trace["checkpoint_id"] = record.get("checkpoint_id")
                continue
            if rt == "node":
                trace["nodes"].append(record)
            elif rt == "edge":
                trace["edges"].append(record)
        rows = list(grouped.values()) or rows
    matches = [r for r in rows if _row_matches_workflow(r, workflow_id)]
    if not matches:
        status = "UNAVAILABLE" if quality == "UNAVAILABLE" else "NO_RELEVANT_EVENTS"
        absent: dict[str, Any] = {"workflow_id": workflow_id, "status": status, "nodes": [], "edges": [], "identifiers": {}}
        if skipped and quality == "AVAILABLE":
            # Not finding it is not proof it is absent: a skipped line may have been its record.
            absent["meta"] = {"skipped_corrupt_lines": skipped}
            return absent, "DEGRADED"
        return absent, quality
    row = matches[0]
    identifiers = _identifiers(row)
    raw_nodes = row.get("nodes", [])
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, n in enumerate(raw_nodes if isinstance(raw_nodes, list) else []):
        if not isinstance(n, dict):
            continue
        nid = str(n.get("node_id") or n.get("id") or f"{workflow_id}:node:{idx}")
        if nid in seen:
            continue
        seen.add(nid)
        raw_type = str(n.get("node_type") or n.get("kind") or "")
        nodes.append({
            "node_id": nid,
            "node_type": NODE_TYPES.get(raw_type.lower(), n.get("node_type") or n.get("kind") or "UNKNOWN"),
            "entity_refs": n.get("entity_refs", []),
            "timestamp": n.get("timestamp") or n.get("ts"),
            "status": n.get("status", "UNKNOWN"),
            "evidence_class": n.get("evidence_class", row.get("evidence_class", "HISTORICAL_REPLAY")),
            "source_ref": n.get("source_ref"),
            "source_sha": n.get("source_sha", row.get("source_sha", _sha())),
            "data_quality": n.get("data_quality", "AVAILABLE"),
            "summary": n.get("summary"),
            "lineage_status": n.get("lineage_status") or n.get("status"),
        })
    raw_edges = row.get("edges", [])
    edges = []
    for e in raw_edges if isinstance(raw_edges, list) else []:
        if not isinstance(e, dict):
            continue
        frm, to = str(e.get("from") or e.get("source") or ""), str(e.get("to") or e.get("target") or "")
        if not frm or not to:
            continue
        provided = str(e.get("certainty") or "")
        if provided in PARTIAL_CERTAINTY:
            certainty = provided
        elif provided:
            certainty = provided
        else:
            certainty = "SUPPORTED" if frm in seen and to in seen else "UNRESOLVED_LINK"
        if (frm not in seen or to not in seen) and provided not in PARTIAL_CERTAINTY:
            certainty = "UNRESOLVED_LINK"
        edges.append({
            "from": frm, "to": to,
            "relationship": e.get("relationship", "RELATED"),
            "evidence": e.get("evidence"),
            "certainty": certainty,
            "status": e.get("status", "AVAILABLE"),
        })
    missing = [edge for edge in edges if edge["certainty"] in PARTIAL_CERTAINTY or edge["from"] not in seen or edge["to"] not in seen]
    cutoff = query.get("as_of") or query.get("until")
    if cutoff:
        nodes = [n for n in nodes if not n.get("timestamp") or str(n["timestamp"]) <= str(cutoff)]
        allowed = {n["node_id"] for n in nodes}
        edges = [e for e in edges if e["from"] in allowed and e["to"] in allowed]
        missing = [edge for edge in edges if edge["certainty"] in PARTIAL_CERTAINTY or edge["from"] not in allowed or edge["to"] not in allowed]
    dq = "AVAILABLE" if not missing else "PARTIAL"
    row_quality = str(row.get("data_quality") or quality)
    if row_quality in {"STALE", "DEGRADED", "UNAVAILABLE", "INVALID_SCHEMA", "BROKEN"}:
        dq = row_quality
    canonical_id = str(identifiers.get("workflow_id") or row.get("workflow_id") or workflow_id)
    checkpoint_id = str(identifiers.get("checkpoint_id") or row.get("checkpoint_id") or "")
    checkpoint = _load_checkpoint_row(checkpoint_id) if checkpoint_id else None
    if skipped and quality == "AVAILABLE" and dq in {"AVAILABLE", "PARTIAL"}:
        dq = "DEGRADED"  # LQ-20261107-2407: lines were skipped, so this answer may be missing records
    detail_out = {
        "workflow_id": canonical_id,
        "resolved_from": workflow_id if canonical_id != workflow_id else None,
        "status": "AVAILABLE",
        "evidence_class": row.get("evidence_class", "HISTORICAL_REPLAY"),
        "source_sha": row.get("source_sha", _sha()),
        "identifiers": identifiers,
        "checkpoint": checkpoint,
        "envelope": row.get("envelope"),
        "nodes": nodes,
        "edges": edges,
        "unresolved_links": missing,
        "pagination": {"nodes": _bounded(query)[0], "edges": _bounded(query)[0]},
    }
    if skipped:
        detail_out["meta"] = {"skipped_corrupt_lines": skipped}
    return detail_out, dq if quality == "AVAILABLE" else quality


def _invoke_status(fn: Any) -> Any:
    attempts = (
        lambda: fn(),
        lambda: fn(root=_state_root()),
        lambda: fn(_state_root()),
    )
    for attempt in attempts:
        try:
            return attempt()
        except TypeError:
            continue
        except Exception:
            return None
    return None


def _hermes_from_runtime_status() -> dict[str, Any] | None:
    """Lane C classifier when present; None means fail-soft to current health."""
    try:
        hrs = importlib.import_module("scripts.lib.hermes_runtime_status")
    except Exception:
        return None
    snapshot = None
    for name in ("classify", "status", "build", "runtime_status", "snapshot"):
        fn = getattr(hrs, name, None)
        if not callable(fn):
            continue
        snapshot = _invoke_status(fn)
        if snapshot is not None:
            break
    if snapshot is None:
        return None
    if isinstance(snapshot, str):
        return {"mode": "EVENT_DRIVEN_QUEUE", "state": snapshot}
    if isinstance(snapshot, dict):
        hermes = dict(snapshot)
        if "state" not in hermes:
            for key in ("status", "taxonomy", "class", "runtime_state"):
                if hermes.get(key):
                    hermes["state"] = hermes[key]
                    break
        hermes.setdefault("mode", "EVENT_DRIVEN_QUEUE")
        hermes.setdefault("state", "UNKNOWN")
        return hermes
    return None


def _hermes_projection() -> dict[str, Any]:
    pending = 0
    queue: dict[str, Any] = {}
    error = None
    try:
        from scripts.lib.hermes_queue_health import build as build_hermes_health
        queue = build_hermes_health() or {}
        pending = int(queue.get("pending") or 0)
    except Exception as exc:
        error = type(exc).__name__
    try:
        from scripts.lib.hermes_runtime_status import classify
        hermes = classify(
            architecture="oneshot",
            pending=pending,
            worker_running=False,
            error=error,
        )
    except Exception:
        hermes = _hermes_from_runtime_status() or {"mode": "ON_DEMAND", "state": "UNKNOWN"}
    if queue:
        hermes = dict(hermes)
        hermes["queue"] = queue
    return hermes


def _system() -> dict[str, Any]:
    hermes = _hermes_projection()
    return {
        "authority": READ_ONLY_ADVISORY,
        "memory_behavior_influence": 0,
        # LQ-20261107-223: what this process knows first-hand. It answered this GET, so it is SERVING (never
        # LIVE: that is a governance claim this projection cannot make); the state root is present or not.
        "runtime": {
            "source_sha": _sha(),
            "state": "SERVING",
            "state_basis": "this process answered GET /api/v3/control-plane/system",
            "state_root": str(_state_root()),
            "persistent_state": "PRESENT" if (_state_root() / "data").is_dir() else "MISSING",
        },
        "services": [], "timers": [], "workers": [{"agent_id": "hermes", "runtime_state": hermes.get("state", "UNKNOWN"), "mode": hermes.get("mode", "EVENT_DRIVEN_QUEUE")}], "queues": [hermes],
        "research": {"state": "UNKNOWN"}, "notifications": {"state": "UNKNOWN"},
    }


_RUNTIME_EVIDENCE_CLASSES = frozenset({
    "attempted", "consumed", "delivered", "settled", "organic", "behavior_changing",
})


def _maturity_truth(query: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    """Live campaign maturity truth — never the stale June-2026 score body."""
    query = query or {}
    try:
        from scripts.lib.campaign_maturity_truth import build_maturity_truth

        payload = build_maturity_truth(root=_state_root())
    except Exception as exc:
        return {
            "schema": "CampaignMaturityTruth@v1",
            "ok": False,
            "generated_at": _now(),
            "served_sha": _sha(),
            "evidence_timestamp": _now(),
            "source_store": "scripts.lib.campaign_maturity_truth",
            "staleness_hours": None,
            "overall_is_not_a_certification": True,
            "computes_maturity": False,
            "items": [],
            "error": f"{type(exc).__name__}: {exc}",
        }, "BROKEN"
    # Preserve list/pagination shape the Maturity page expects (data.items).
    items = list(payload.get("items") or [])
    page = _paged(items, query)
    page.update({
        "schema": payload.get("schema"),
        "ok": payload.get("ok", True),
        "generated_at": payload.get("generated_at"),
        "served_sha": payload.get("served_sha") or _sha(),
        "evidence_timestamp": payload.get("evidence_timestamp"),
        "source_store": payload.get("source_store"),
        "staleness_hours": payload.get("staleness_hours", 0.0),
        "overall_is_not_a_certification": True,
        "computes_maturity": False,
        "limiting_dimension": payload.get("limiting_dimension"),
        "historical_body_superseded": payload.get("historical_body_superseded"),
        "db_probe": payload.get("db_probe"),
        "note": payload.get("note"),
    })
    # A computed surface must not report AVAILABLE merely because it can always
    # produce a shaped body. build_maturity_truth() emits explicit zeroes even
    # with an empty state root, and reporting that as AVAILABLE made the route
    # render LIVE_GOVERNED with nothing behind it -- the exact "says LIVE while
    # nothing answered" defect this domain exists to prevent, reintroduced by
    # the fix for stale-data-served-as-live. Explicit zeroes are honest content
    # but they are not live evidence: with no evidence at all, answer EMPTY.
    if not _maturity_has_evidence(payload):
        return page, "EMPTY"
    return page, "AVAILABLE"


#: `source_store` labels that name a host- or database-scoped fact, not a file in a state root.
_HOST_SCOPED_STORE_PREFIXES = (
    "user crontab", "crontab", "systemd", "postgresql:", "postgres:", "/run/user/", "/etc/", "/proc/", "/sys/",
)
_STORE_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:")


def _store_is_about_root(store: object, root: Path) -> bool:
    """Whether a ``source_store`` label names something under the root being reported.

    The builder labels its stores three ways: an absolute path, a bare path relative to the served
    tree (``data/persistent_wake/state/wakes.jsonl``), and a host/DB scope (``postgresql:...``,
    ``user crontab``, ``systemd drop-in ...``). Only the first two can be evidence about this root.

    Before 2026-11-07 the test was ``startswith(root)``, which no relative label can satisfy, so
    every qualifying item was skipped and the surface answered EMPTY at every root -- including the
    live one with 4029 recorded wakes. The absolute branch now compares path components instead of
    string prefixes, so ``/state2`` is not "under" ``/state``.
    """
    label = str(store or "").strip()
    if not label:
        return False
    lowered = label.lower()
    if _STORE_SCHEME.match(lowered) or lowered.startswith(_HOST_SCOPED_STORE_PREFIXES):
        return False
    path = Path(label)
    if not path.is_absolute():
        # The builder reads a relative label as ``root / label`` -- it IS this root's store.
        # On the live host ``data/persistent_wake`` is a symlink out of the release tree, so
        # resolving it would call the root's own store "outside the root". A label that tries
        # to climb out with ``..`` is not one the builder emits.
        return ".." not in path.parts
    # Absolute: compare path components, not string prefixes, so /state2 is not under /state.
    try:
        Path(os.path.normpath(path)).relative_to(Path(os.path.normpath(root)))
    except (OSError, ValueError):
        return False
    return True


def _maturity_has_evidence(payload: dict[str, Any]) -> bool:
    """True iff the computed truth rests on at least one real observation about this root.

    Counts evidence, not shape. Deliberately does NOT trust
    ``evidence_timestamp``: the builder stamps that with generation time on every
    call, so it is populated even when every dimension is an explicit zero. The
    only honest signal is a dimension with a non-zero count and an evidence_class
    that is not 'absent'.
    """
    root = _state_root()
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        # Config presence is not an answer. 'configured' and 'scheduled' come
        # from systemd drop-ins and the user crontab -- host facts that are true
        # regardless of whether this state root holds anything.
        if str(item.get("evidence_class") or "absent") not in _RUNTIME_EVIDENCE_CLASSES:
            continue
        # ...and the observation must belong to the root being reported on. On an
        # empty root the builder still returns comms_provider_settled=3 from
        # postgresql:communication_deliveries, which would render the surface LIVE
        # for a state root containing nothing. Out-of-root evidence is real, but
        # it is not evidence about THIS root.
        if not _store_is_about_root(item.get("source_store"), root):
            continue
        try:
            if int(item.get("count") or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _registered_store_present(root: Path) -> bool:
    """True when a canonical store file exists — not merely a data/cio directory."""
    try:
        from scripts.lib.canonical_store_registry import STORES
    except Exception:
        markers = tuple(CONTROL_PLANE_DOMAINS["stores"].get("populated_markers") or ())
        return any((root / p).exists() for p in markers)
    for store_spec in STORES.values():
        rel = store_spec.get("path")
        if rel and (root / rel).exists():
            return True
        for alias in store_spec.get("aliases") or []:
            if (root / alias).exists():
                return True
    return False


def _stores(query: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    query = query or {}
    spec = CONTROL_PLANE_DOMAINS["stores"]
    candidates = _canonical_paths(tuple(spec.get("store_ids") or ()), tuple(spec.get("fallbacks") or ()))
    data, quality = _rows_from_json(candidates, query, domain="stores")
    if quality == "AVAILABLE":
        return data, quality
    # Registry is code-canonical; expose bounded metadata when a generated
    # registry projection has not yet been emitted, but only for a populated
    # state root. Empty test roots remain explicitly UNAVAILABLE.
    root = _state_root()
    if _registered_store_present(root):
        try:
            from scripts.lib.canonical_store_registry import registry, resolve_store
            rows = []
            for store_id, store_spec in registry()["stores"].items():
                loc = resolve_store(store_id, root=root)
                rows.append({
                    "store_id": store_id,
                    "path": str(loc.get("path") or loc.get("primary_path")),
                    "exists": bool(loc.get("exists")),
                    "schema": store_spec.get("schema"),
                    "writer": store_spec.get("writer"),
                    "ownership_class": store_spec.get("ownership_class"),
                    "status": "AVAILABLE" if loc.get("exists") else "UNAVAILABLE_PRODUCER_NOT_RUN",
                })
            return _paged(rows, query), "AVAILABLE"
        except Exception:
            pass
    return data, quality


def handle(path: str, *, method: str = "GET", query: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]] | None:
    """Dispatch one control-plane request; returns ``None`` for non-R21 paths."""
    if not path.startswith("/api/v3/control-plane"):
        return None
    if method.upper() != "GET":
        return 405, _envelope({"error": "control-plane is read-only"}, quality="UNAVAILABLE")
    query = query or {}
    base = path.rstrip("/")
    prefix = "/api/v3/control-plane/"
    if base == "/api/v3/control-plane" or not base.startswith(prefix):
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    rest = base[len(prefix):]
    if not rest:
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    parts = rest.split("/")
    domain = parts[0]
    if domain not in CONTROL_PLANE_DOMAINS:
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    spec = CONTROL_PLANE_DOMAINS[domain]
    if len(parts) > 2:
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    if len(parts) == 2:
        item_id = parts[1]
        if domain == "agents":
            detail, quality = _agent_detail(item_id, query)
            return 200, _envelope(detail, quality=quality)
        if domain == "workflows":
            detail, quality = _workflow_detail(item_id, query)
            return 200, _envelope(detail, quality=quality)
        return 404, _envelope({"error": "unknown control-plane route"}, quality="NO_RELEVANT_EVENTS")
    if spec.get("kind") == "computed" and domain == "system":
        system = _system()
        # An empty state root is not a live system (test_an_empty_state_root_is_never_reported_live).
        present = system["runtime"]["persistent_state"] == "PRESENT"
        return 200, _envelope(system, quality="AVAILABLE" if present else "UNAVAILABLE")
    if spec.get("kind") == "computed" and domain == "stores":
        data, quality = _stores(query)
        return 200, _envelope(data, quality=quality)
    if spec.get("kind") == "computed" and domain == "maturity":
        data, quality = _maturity_truth(query)
        # Freshness is live evidence, not CURRENT_SMOKE fixture class.
        env = _envelope(data, quality=quality, evidence="LIVE_RUNTIME")
        env["freshness"] = "LIVE_RUNTIME"
        return 200, env
    data, quality = _collection(domain, query)
    return 200, _envelope(data, quality=quality)


def handle_query_string(path: str, *, method: str = "GET", query_string: str = "") -> tuple[int, dict[str, Any]] | None:
    query = {k: (v[0] if len(v) == 1 else v) for k, v in parse_qs(query_string).items()}
    return handle(path, method=method, query=query)
