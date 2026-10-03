"""Operator-facing CIO evidence composition.

This module only reads existing canonical stores.  It deliberately preserves
the difference between a producer event, a consumption receipt, and a UI
projection; an absent receipt is UNKNOWN, never REJECTED or USED.

Receipt rules (2026-10-02 review):

* research USED requires a positive receipt from an explicit allowlist
  (``True``, ``"USED"``, ``"USED_IN_JUDGMENT"``, a non-empty list of consuming
  decision ids, or a canonical ``intelligence_lineages`` ``ADVISORY_USED``
  receipt naming the result id).  Any other string -- ``"NOT_USED"``, ``"no"``,
  ``"0"`` -- proves nothing.
* research RETRIEVED requires a retrieval fact (``retrieved_at``,
  ``result_id``, ``fetched``...).  The store a row came from is not a fact.
* cognition AVAILABLE requires a row with a parseable, non-future clock.
* learning PROVEN requires evidence ids that resolve to SETTLED outcome rows.
* capability LIVE requires producer rows matching the capability's own
  predicate plus an explicit consumer reference.
"""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOOperatorEvidence@v1"
RESEARCH_SCHEMA = "CIOResearchProvenance@v1"
STATES = ("LIVE", "PARTIAL", "UNWIRED", "DARK", "UNKNOWN")
REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWN_DARK_CLASSIFICATION_PATH = REPO_ROOT / "config" / "cio_known_dark_classification.json"
# Clocks this far beyond the composition clock are treated as invalid.
_FUTURE_SKEW = timedelta(minutes=5)


def _root() -> Path:
    return Path(os.getenv("TRADEAI_CIO_DIR") or REPO_ROOT / "data" / "cio")


def _runtime_root(root: Path) -> Path:
    return Path(os.getenv("TRADEAI_RUNTIME_DIR") or root.parent / "runtime")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_matches_decision(row: dict[str, Any], decision_id: str) -> bool:
    """Match an exact decision id without using a symbol or neighboring row."""
    did = str(decision_id or "").strip()
    if not did:
        return True
    values: list[str] = []
    for key in (
        "decision_id", "judgment_decision_id", "cio_case_id", "workflow_id",
        "decision_ids", "decision_refs", "decisions", "consumed_by_decision_ids",
    ):
        value = row.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if item not in (None, ""))
    contributions = row.get("contributions")
    if isinstance(contributions, list):
        for contribution in contributions:
            if isinstance(contribution, dict) and _row_matches_decision(contribution, did):
                return True
    return did in values


def _parse_rows(lines: Iterable[str], *, predicate: Any = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and (predicate is None or predicate(row)):
            out.append(row)
    return out


# Composition reads only a bounded window from the end of each store.  Every
# consumer below keeps the most recent rows (100-250); fully parsing the
# 60-120 MB stores on each request cost ~23 s and ~1.6 GB RSS per call.
_COMPOSITION_TAIL_BYTES = int(os.getenv("CIO_EVIDENCE_TAIL_BYTES") or 1024 * 1024)
# Outcome ledgers are small (KB-MB) and are the denominator of every rate, so
# they are read whole up to this bound; above it the scope says RECENT_WINDOW.
_OUTCOME_SCAN_BYTES = int(os.getenv("CIO_EVIDENCE_OUTCOME_BYTES") or 32 * 1024 * 1024)
# A producer store this small may be scanned to resolve consumer references.
_RESOLVE_SCAN_BYTES = int(os.getenv("CIO_EVIDENCE_RESOLVE_BYTES") or 16 * 1024 * 1024)
_MAX_RESOLVE_NEEDLES = 200


def _tail_lines(path: Path, max_bytes: int) -> list[str]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            handle.readline()  # discard the partial first line
        return handle.read().decode("utf-8", errors="replace").splitlines()


def _rows(path: Path, *, decision_id: str | None = None, max_bytes: int | None = None) -> list[dict[str, Any]]:
    """Rows for one exact decision (whole store), or the store's recent window.

    Exact lookups stream the whole file but only parse lines that contain the
    decision id, so older rows for the same decision are never dropped and a
    miss does not parse 100+ MB of JSON.
    """
    if not path.is_file():
        return []
    did = str(decision_id or "").strip()
    if did:
        predicate = lambda row: _row_matches_decision(row, did)  # noqa: E731
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return _parse_rows((line for line in handle if did in line), predicate=predicate)
    return _parse_rows(_tail_lines(path, max_bytes or _COMPOSITION_TAIL_BYTES))


def _rows_containing(path: Path, needles: set[str]) -> list[dict[str, Any]]:
    """Whole-store rows whose raw line contains any needle (exact ids)."""
    if not needles or not path.is_file():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        if len(needles) <= 8:
            return _parse_rows(line for line in handle if any(n in line for n in needles))
        # Many needles: match whole JSON string values (ids are exact values),
        # one C-level findall per line instead of len(needles) substring scans.
        wanted = set(needles)
        return _parse_rows(line for line in handle if not wanted.isdisjoint(_QUOTED.findall(line)))


_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _stamp(row: dict[str, Any] | None) -> str | None:
    if not isinstance(row, dict):
        return None
    for key in (
        "source_as_of", "as_of", "updated_ts", "updated_at", "recorded_at", "created_ts",
        "created_at", "completed_ts", "observed_at", "occurred_at", "at", "ts", "timestamp", "deferred_at",
    ):
        value = row.get(key)
        if value not in (None, "", []):
            return str(value)
    return None


def _parse_ts(value: Any) -> datetime | None:
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _clock(row: dict[str, Any], ceiling: datetime | None) -> tuple[str | None, str]:
    """(stamp, verdict) where verdict is PARSEABLE / UNPARSEABLE / FUTURE / ABSENT."""
    raw = _stamp(row)
    if raw is None:
        return None, "ABSENT"
    parsed = _parse_ts(raw)
    if parsed is None:
        return raw, "UNPARSEABLE"
    if ceiling is not None and parsed > ceiling + _FUTURE_SKEW:
        return raw, "FUTURE"
    return raw, "PARSEABLE"


def _latest_stamp(rows: Iterable[dict[str, Any]], *, not_after: datetime | None = None) -> str | None:
    """Latest parseable row clock.  Mixed formats compare as instants, not
    strings, and clocks in the future (beyond a 5-minute skew) are ignored."""
    ceiling = (not_after or datetime.now(timezone.utc)) + _FUTURE_SKEW
    best: tuple[datetime, str] | None = None
    for row in rows:
        raw = _stamp(row)
        parsed = _parse_ts(raw) if raw else None
        if parsed is None or parsed > ceiling:
            continue
        if best is None or parsed > best[0]:
            best = (parsed, str(raw))
    return best[1] if best else None


def _source_version(path: Path) -> str | None:
    """Cheap store version (size + mtime).  Hashing every store per request
    re-read ~600 MB; a content hash is not needed to tell versions apart."""
    if not path.is_file():
        return None
    st = path.stat()
    return f"bytes={st.st_size};mtime_ns={st.st_mtime_ns}"


def _source_meta(
    path: Path, rows: list[dict[str, Any]], *, exact: bool = False,
    scope: str | None = None, ceiling: datetime | None = None,
) -> dict[str, Any]:
    return {
        "source_ref": str(path),
        "source_sha": None,
        "source_version": _source_version(path),
        "source_as_of": _latest_stamp(rows, not_after=ceiling),
        "row_count": len(rows),
        "row_scope": "EXACT_DECISION_SCAN" if exact else (scope or "RECENT_WINDOW"),
        "evidence_class": "DURABLE_RUNTIME_ARTIFACT" if path.is_file() else "UNAVAILABLE",
    }


def _freshness(source_as_of: str | None) -> str:
    """Name freshness only when a source clock actually exists."""
    return "OBSERVED" if source_as_of else "UNKNOWN"


def _age_seconds(source_as_of: str | None, composition_as_of: str) -> int | None:
    if not source_as_of:
        return None
    source = _parse_ts(source_as_of)
    composed = _parse_ts(composition_as_of)
    if source is None or composed is None:
        return None
    return max(0, int((composed - source).total_seconds()))


def _row_refs(row: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        value = row.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if item not in (None, "") and not isinstance(item, dict))
    return sorted({value for value in values if value.strip()})


def _evidence_ids(row: dict[str, Any]) -> list[str]:
    return _row_refs(
        row,
        "outcome_ids", "supporting_outcome_ids", "source_outcome_ids",
        "evidence_refs", "evidence_ids", "outcome_id", "outcome_ref",
    )


# ── research receipts ──────────────────────────────────────────────────────

_USE_TOKENS = frozenset({"USED", "USED_IN_JUDGMENT"})
_NEGATIVE_TOKENS = frozenset({
    "", "0", "NO", "NONE", "NULL", "FALSE", "N/A", "NA", "UNKNOWN", "NOT_USED",
    "UNUSED", "REJECTED", "DISMISSED", "IGNORED", "PENDING",
})
_USE_FLAG_KEYS = ("used_in_judgment", "used_in_decision", "advisory_use")
_USE_LIST_KEYS = ("consumed_by", "consumed_by_decision_ids")
_REJECTION_KEYS = ("rejection_reason", "reason_rejected", "rejected_reason", "rejected_because", "rejection_reasons")
_REJECTED_STATES = frozenset({"REJECTED", "DISMISSED", "NOT_USED", "RESEARCH_REJECTED"})


def _positive_use_flag(value: Any) -> bool:
    if value is True:
        return True
    return isinstance(value, str) and value.strip().upper() in _USE_TOKENS


def _consuming_decision_ids(value: Any) -> list[str]:
    """A non-empty list of consuming decision ids; anything else proves nothing."""
    if not isinstance(value, (list, tuple)) or not value:
        return []
    ids = [str(item).strip() for item in value if isinstance(item, str)]
    if len(ids) != len(value) or any(item.upper() in _NEGATIVE_TOKENS for item in ids):
        return []
    return ids


def _explicit_used(row: dict[str, Any]) -> str | None:
    """Name the positive use receipt on the row, or None.  Allowlist only."""
    status = str(row.get("status") or row.get("state") or "").strip().upper()
    if status in _USE_TOKENS:
        return f"status:{status}"
    for key in _USE_FLAG_KEYS:
        if _positive_use_flag(row.get(key)):
            return key
    for key in _USE_LIST_KEYS:
        if _consuming_decision_ids(row.get(key)):
            return key
    return None


def _rejection_reason(row: dict[str, Any]) -> Any:
    for key in _REJECTION_KEYS:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return None


def _explicit_rejected(row: dict[str, Any]) -> bool:
    # A generic request/producer ``reason`` is not a rejection receipt.  A
    # research artifact is rejected only when the canonical row carries an
    # explicit rejection field (which is itself the reason).
    return _rejection_reason(row) is not None


def _retrieval_fact(row: dict[str, Any]) -> str | None:
    for key in ("retrieved_at", "retrieved_ts", "fetched_at", "result_id", "retrieval_receipt_id"):
        if row.get(key) not in (None, "", []):
            return key
    for key in ("fetched", "retrieved"):
        if row.get(key) is True:
            return key
    return None


def _artifact_status(row: dict[str, Any]) -> tuple[str, str | None]:
    used = _explicit_used(row)
    if used:
        return "USED_IN_JUDGMENT", used
    if _explicit_rejected(row):
        return "REJECTED", next(k for k in _REJECTION_KEYS if row.get(k) not in (None, "", []))
    retrieved = _retrieval_fact(row)
    if retrieved:
        return "RETRIEVED", retrieved
    return "UNKNOWN", None


def _research_rows(path: Path, rows: Iterable[dict[str, Any]] | None = None) -> Iterable[dict[str, Any]]:
    """Yield artifact-shaped rows from existing research products.

    SecurityResearchSpine is a canonical projection whose contributions carry
    artifact ids; the spine envelope itself is not a new artifact and must not
    produce a synthetic ``UNKNOWN`` record.
    """
    for row in rows if rows is not None else _rows(path):
        if path.name == "security_research_spine.jsonl":
            contributions = row.get("contributions")
            if isinstance(contributions, list) and contributions:
                for contribution in contributions:
                    if not isinstance(contribution, dict):
                        continue
                    if not (contribution.get("artifact_id") or contribution.get("research_id")):
                        continue
                    # Envelope fields describe the spine, not the contribution:
                    # only identity fields are inherited.
                    yield {
                        **contribution,
                        "symbol": contribution.get("symbol") or row.get("symbol"),
                        "subject_guid": contribution.get("subject_guid") or row.get("subject_guid"),
                    }
                continue
            if not (row.get("artifact_id") or row.get("research_id") or row.get("result_id")):
                continue
        yield row


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value
    return None


def _research_artifact(row: dict[str, Any], *, source_name: str) -> dict[str, Any] | None:
    artifact_id = row.get("result_id") or row.get("research_id") or row.get("artifact_id") or row.get("id")
    if not artifact_id:
        return None
    status, basis = _artifact_status(row)
    entities = row.get("symbols") or row.get("affected_entities")
    if isinstance(entities, str):
        entities = [entities]
    if not isinstance(entities, list):
        entities = [row.get("symbol")] if row.get("symbol") else []
    decision_ids: list[Any] = []
    for key in ("decision_ids", "decision_refs", "decisions", "consumed_by_decision_ids"):
        value = row.get(key)
        decision_ids.extend([value] if isinstance(value, str) else (value if isinstance(value, list) else []))
    direct_decision_id = row.get("decision_id") or row.get("cio_case_id") or row.get("judgment_decision_id")
    if direct_decision_id:
        decision_ids.append(direct_decision_id)
    thesis_refs = row.get("thesis_refs") or row.get("thesis_ids") or row.get("refs") or []
    if isinstance(thesis_refs, str):
        thesis_refs = [thesis_refs]
    thesis_refs = [str(ref) for ref in thesis_refs if isinstance(ref, (str, int)) and str(ref).strip()]
    decision_ids = sorted({str(value) for value in decision_ids if isinstance(value, (str, int)) and str(value).strip()})
    affected_entities = sorted({str(value) for value in entities if value not in (None, "")})
    source_urls = row.get("source_urls")
    publisher = _first(row, "publisher")
    if publisher is None and isinstance(row.get("source"), str):
        publisher = row.get("source")
    retrieved_at = _first(row, "retrieved_at", "retrieved_ts", "fetched_at")
    if retrieved_at is None and source_name == "hermes_research_results.jsonl":
        # A Hermes result row is the retrieval: its completion clock is when
        # the result was obtained.  Other stores carry no such clock.
        retrieved_at = _first(row, "completed_ts")
    return {
        "artifact_id": str(artifact_id),
        "research_id": row.get("research_id"),
        "result_id": row.get("result_id"),
        "status": status,
        "status_basis": basis,
        "source_store": source_name,
        "source_type": _first(row, "source_type", "research_type"),
        "source": publisher,
        "publisher": publisher,
        "provider": row.get("provider"),
        "source_url": _first(row, "url", "source_url") or (source_urls[0] if isinstance(source_urls, list) and source_urls and isinstance(source_urls[0], str) else None),
        "source_ref": _first(row, "source_ref", "source_store") or source_name,
        "publication_date": _first(row, "publication_date", "published_at"),
        "retrieved_at": retrieved_at,
        "source_as_of": _first(row, "source_as_of", "evidence_as_of", "as_of"),
        "symbol": row.get("symbol") or (affected_entities[0] if len(affected_entities) == 1 else None),
        "affected_entities": affected_entities,
        "subject_guid": row.get("subject_guid") or row.get("issuer_guid"),
        "research_run_id": _first(row, "research_run_id", "run_id", "research_run"),
        "agent_model": _first(row, "agent_model", "model", "model_used"),
        "relevance": _first(row, "relevance", "relevance_score"),
        "support_or_challenge": _first(row, "support_or_challenge", "stance", "thesis_stance"),
        "reason_used_or_rejected": _first(row, "use_reason", "reason_used", *_REJECTION_KEYS),
        "decision_id": direct_decision_id,
        "decision_ids": decision_ids,
        "decision_link_basis": row.get("decision_link_basis"),
        "trace_id": _first(row, "trace_id", "trace"),
        "lineage_id": row.get("lineage_id"),
        "use_receipt_ref": None,
        "thesis_refs": thesis_refs,
        # Identifiers only: relationships remain resolved from existing stores.
        "related_decisions": decision_ids,
        "related_securities": affected_entities,
        "evidence_class": row.get("evidence_class"),
    }


_STATUS_RANK = {"UNKNOWN": 0, "RETRIEVED": 1, "REJECTED": 2, "USED_IN_JUDGMENT": 3}


def _merge_research_artifact(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return dict(candidate)
    merged = dict(existing)
    if _STATUS_RANK.get(str(candidate.get("status")), 0) > _STATUS_RANK.get(str(existing.get("status")), 0):
        merged["status"] = candidate["status"]
        merged["status_basis"] = candidate.get("status_basis")
    for key, value in candidate.items():
        if value in (None, "", []) or key in {"status", "status_basis"}:
            continue
        if key in {"affected_entities", "decision_ids", "thesis_refs", "related_decisions", "related_securities"}:
            prior = existing.get(key) if isinstance(existing.get(key), list) else []
            incoming = value if isinstance(value, list) else [value]
            merged[key] = sorted({str(item) for item in [*prior, *incoming] if item not in (None, "")})
        elif merged.get(key) in (None, ""):
            merged[key] = value
    if not merged.get("decision_id") and merged.get("decision_ids"):
        merged["decision_id"] = merged["decision_ids"][0]
    return merged


def _lineage_use_receipts(root: Path, *, artifact_ids: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """result id -> canonical ADVISORY_USED receipt from intelligence_lineages.

    ``intelligence_lineage`` advances a lineage to ADVISORY_USED only from an
    explicit product-reassessment use receipt, never from symbol presence.
    """
    path = root / "intelligence_lineages.jsonl"
    rows = _rows_containing(path, artifact_ids) if artifact_ids is not None else _rows(path)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("status") or "").upper() != "ADVISORY_USED":
            continue
        result_ids = _row_refs(row, "research_result_ids")
        # The live-forward use event is written per result; a row listing
        # several results cannot say which one was used, so it proves none.
        if len(result_ids) != 1:
            continue
        for rid in result_ids:
            out[rid] = {
                "lineage_id": row.get("lineage_id"),
                "decision_id": row.get("decision_id"),
                "at": _stamp(row),
                "source_ref": path.name,
            }
    return out


def _group_research(artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "artifacts": artifacts,
        "retrieved": [a for a in artifacts if a["status"] == "RETRIEVED"],
        "used_in_judgment": [a for a in artifacts if a["status"] == "USED_IN_JUDGMENT"],
        "rejected": [a for a in artifacts if a["status"] == "REJECTED"],
        "unknown": [a for a in artifacts if a["status"] == "UNKNOWN"],
        "counts": {
            "retrieved": sum(a["status"] == "RETRIEVED" for a in artifacts),
            "used_in_judgment": sum(a["status"] == "USED_IN_JUDGMENT" for a in artifacts),
            "rejected": sum(a["status"] == "REJECTED" for a in artifacts),
            "unknown": sum(a["status"] == "UNKNOWN" for a in artifacts),
        },
    }


_FOLLOWUP_EVENT = "OPTIONS_THESIS_FOLLOWUP_REQUESTED"
_FOLLOWUP_BASIS = "options_theses:OPTIONS_THESIS_FOLLOWUP_REQUESTED.for_decision"


def _followup_research_ids(root: Path, decision_id: str) -> set[str]:
    """Research the producer requested for this exact decision.

    When an options CIO review returns MORE_RESEARCH, the thesis lifecycle
    records the follow-up with both the research_id and ``for_decision`` at the
    moment it asks. That written link is the join; nothing is matched by symbol
    or time.
    """
    path = root / "options_theses.jsonl"
    if not decision_id or not path.is_file():
        return set()
    ids: set[str] = set()
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if decision_id not in line or _FOLLOWUP_EVENT not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (isinstance(row, dict) and row.get("event_type") == _FOLLOWUP_EVENT
                    and str(row.get("for_decision") or "") == decision_id and row.get("research_id")):
                ids.add(str(row["research_id"]))
    return ids


def _research_provenance(root: Path, *, decision_id: str | None = None) -> dict[str, Any]:
    paths = [
        root / "hermes_research_results.jsonl",
        root / "web_evidence_provenance.jsonl",
        root / "security_research_spine.jsonl",
    ]
    by_artifact: dict[str, dict[str, Any]] = {}
    sources: list[dict[str, Any]] = []
    for path in paths:
        # Exact decision lookups read only rows that reference the decision;
        # the global view reads each store's recent window.
        rows = _rows(path, decision_id=decision_id)
        sources.append({"source": path.name, **_source_meta(path, rows, exact=bool(decision_id))})
        if decision_id:
            # A shared artifact keeps every decision that referenced it: pull
            # all rows of the artifacts this decision touched (second pass,
            # still prefiltered by artifact id).
            ids = {a["artifact_id"] for r in _research_rows(path, rows)
                   if (a := _research_artifact(r, source_name=path.name))}
            rows = _rows_containing(path, ids)
            if path.name == "hermes_research_results.jsonl":
                requested = _followup_research_ids(root, str(decision_id).strip())
                rows = rows + [
                    {**row, "decision_ids": [*(row.get("decision_ids") or []), str(decision_id).strip()],
                     "decision_link_basis": _FOLLOWUP_BASIS}
                    for row in _rows_containing(path, requested)
                    if str(row.get("research_id") or (row.get("payload") or {}).get("research_id") or "") in requested
                ]
        for row in list(_research_rows(path, rows))[-250:]:
            artifact = _research_artifact(row, source_name=path.name)
            if not artifact:
                continue
            artifact_id = artifact["artifact_id"]
            by_artifact[artifact_id] = _merge_research_artifact(by_artifact.get(artifact_id, {}), artifact)
    did = str(decision_id or "").strip()
    receipts = _lineage_use_receipts(root, artifact_ids=set(by_artifact) if did else None)
    for artifact_id, artifact in by_artifact.items():
        receipt = receipts.get(artifact_id) or receipts.get(str(artifact.get("result_id") or ""))
        if not receipt or artifact["status"] == "USED_IN_JUDGMENT":
            continue
        # For one decision, a use receipt counts only when it names that decision.
        if did and receipt.get("decision_id") != did:
            continue
        artifact["status"] = "USED_IN_JUDGMENT"
        artifact["status_basis"] = "intelligence_lineages:ADVISORY_USED"
        artifact["use_receipt_ref"] = receipt
        if receipt.get("decision_id"):
            artifact["decision_ids"] = sorted({*artifact.get("decision_ids", []), str(receipt["decision_id"])})
            artifact["related_decisions"] = artifact["decision_ids"]
            artifact["decision_id"] = artifact.get("decision_id") or str(receipt["decision_id"])
    artifacts = list(by_artifact.values())
    if did:
        # Never hand a decision the global artifact list: keep only artifacts
        # that carry this exact decision id.
        artifacts = [
            a for a in artifacts
            if a.get("decision_id") == did or did in (a.get("decision_ids") or [])
        ]
    artifacts.sort(key=lambda item: (str(item.get("retrieved_at") or ""), item["artifact_id"]), reverse=True)
    return {
        "schema": RESEARCH_SCHEMA,
        "decision_id": did or None,
        "sources": sources,
        **_group_research(artifacts),
        "status_rules": {
            "USED_IN_JUDGMENT": "positive receipt only: True, USED, USED_IN_JUDGMENT, a list of consuming decision ids, or an intelligence_lineages ADVISORY_USED receipt",
            "REJECTED": "explicit rejection field carrying the reason",
            "RETRIEVED": "retrieval fact present (retrieved_at/result_id/fetched); use not proven",
            "UNKNOWN": "no retrieval, use or rejection receipt",
        },
        "source_as_of": max((s["source_as_of"] for s in sources if s["source_as_of"]), default=None),
    }


def build_research_provenance(
    root: Path | None = None,
    *,
    decision_id: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Build the additive research projection, optionally for one exact decision.

    Filtering is by decision id only.  A shared symbol is not a join key because
    historical decisions for that symbol must remain independently resolvable.
    """
    block = _research_provenance(root or _root(), decision_id=decision_id)
    did = str(decision_id or "").strip()
    if did:
        block["decision_id"] = did
    block["authority"] = AUTHORITY
    block["financial_action"] = False
    block["mutation"] = False
    block["composition_as_of"] = now or _now()
    block["freshness"] = _freshness(block.get("source_as_of"))
    block["producer"] = "scripts.lib.cio_operator_evidence"
    return block


# ── institutional cognition ────────────────────────────────────────────────

OFFICE_TRUTH_CATEGORIES = ["price", "holdings", "cash", "orders", "broker_state", "risk_limits"]
# Fields that would carry office truth.  Cognition items never copy them.
_OFFICE_TRUTH_FIELDS = frozenset({
    "price", "prices", "last_price", "quote", "quotes", "mark", "holdings", "positions",
    "position", "quantity", "shares", "cash", "cash_balance", "buying_power", "orders",
    "order", "open_orders", "broker_state", "account_value", "market_value", "risk_limits",
    "risk_limit", "stop_price", "limit_price",
})
_REJECT_WORDS = frozenset({"REJECT", "REJECTED", "DISMISS", "DISMISSED", "DECLINE", "DECLINED", "NO"})
_DEFER_WORDS = frozenset({"DEFER", "DEFERRED", "SNOOZE", "SNOOZED", "WAIT", "LATER", "REOPENED"})


def _operator_decision(row: dict[str, Any], kind: str) -> str | None:
    if kind == "defer_lineage":
        if row.get("quarantined") or str(row.get("classification") or "").upper().startswith("SYNTHETIC"):
            return None
        return "DEFER"
    raw = str(row.get("intent") or row.get("disposition") or row.get("decision") or "").strip().upper()
    if raw in _REJECT_WORDS:
        return "REJECT"
    if raw in _DEFER_WORDS:
        return "DEFER"
    return None


def _cognition_flags(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    influence = row.get("influence") if isinstance(row.get("influence"), dict) else {}
    flags = [str(f).upper() for f in (influence.get("flags") or []) if isinstance(f, str)]
    retrieval_basis = None
    if kind == "memory_retrieval":
        if str(row.get("retrieval_status") or "").upper() == "OK" and row.get("memory_ids"):
            retrieval_basis = "retrieval_status:OK+memory_ids"
    elif kind == "memory_context":
        if influence.get("consulted") is True:
            retrieval_basis = "influence.consulted"
        elif row.get("memory_ids") or row.get("has_context") is True:
            retrieval_basis = "memory_ids" if row.get("memory_ids") else "has_context"
    elif kind == "research_lineage":
        if row.get("research_result_ids") or row.get("result_id"):
            retrieval_basis = "research_result_ids"
    elif kind == "context_use_receipt":
        if row.get("memory_ids"):
            retrieval_basis = "ContextUseReceipt.memory_ids"
    if row.get("retrieval_receipt_id") and not retrieval_basis:
        retrieval_basis = "retrieval_receipt_id"
    used = _explicit_used(row)
    if not used and kind == "research_lineage" and str(row.get("status") or "").upper() == "ADVISORY_USED":
        used = "intelligence_lineages:ADVISORY_USED"
    influence_receipt = row.get("influence_receipt_id")
    changed = bool(
        row.get("changed_question") is True or row.get("changed_view") is True
        or row.get("question_changed") is True or row.get("view_changed") is True
        or influence.get("changed_decision") is True or influence_receipt
    )
    contradictory = bool(
        row.get("contradictory") is True or row.get("counter") is True
        or row.get("contradiction_receipt_id") or row.get("contradiction_updates")
        or row.get("contradictory_evidence") or "CONTESTED" in flags
    )
    influence_basis = used or (str(influence_receipt) if influence_receipt else None) or (
        "influence.changed_decision" if influence.get("changed_decision") is True else None)
    return {
        "retrieval_basis": retrieval_basis,
        "used_basis": used,
        "changed": changed,
        "contradictory": contradictory,
        "influence_basis": influence_basis,
    }


def _cognition(root: Path, *, decision_id: str | None = None, composition_as_of: str | None = None) -> dict[str, Any]:
    paths = {
        "memory_retrieval": root / "aif_memory_retrievals.jsonl",
        "memory_context": root / "memory_contexts.jsonl",
        "research_lineage": root / "intelligence_lineages.jsonl",
        "context_use_receipt": root / "context_use_receipts.jsonl",
        "operator_feedback": root / "operator_ticker_feedback.jsonl",
    }
    # Prior operator rejection/defer advice: retrievable cognition, never truth.
    operator_paths = {
        "operator_feedback": root / "operator_ticker_feedback.jsonl",
        "decision_disposition": root / "decision_dispositions.jsonl",
        "plan_disposition": root / "cio_operator_learning.jsonl",
        "defer_lineage": root / "cio_defer_lineage.jsonl",
    }
    ceiling = _parse_ts(composition_as_of) if composition_as_of else datetime.now(timezone.utc)
    items: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    cache: dict[Path, list[dict[str, Any]]] = {}

    def rows_for(path: Path) -> list[dict[str, Any]]:
        if path not in cache:
            cache[path] = _rows(path, decision_id=decision_id)
            sources.append({"source": path.name, **_source_meta(path, cache[path], exact=bool(decision_id), ceiling=ceiling)})
        return cache[path]

    def base_item(kind: str, path: Path, row: dict[str, Any]) -> dict[str, Any]:
        stamp, verdict = _clock(row, ceiling)
        withheld = sorted(k for k in row if k in _OFFICE_TRUTH_FIELDS)
        symbols = row.get("symbols")
        return {
            "kind": kind,
            "decision_id": row.get("decision_id") or row.get("judgment_decision_id"),
            "availability": "AVAILABLE" if verdict == "PARSEABLE" else "UNKNOWN",
            "availability_reason": {
                "PARSEABLE": "row present in cognition store with a parseable clock",
                "ABSENT": "row has no clock; availability cannot be dated",
                "UNPARSEABLE": "row clock is not parseable",
                "FUTURE": "row clock is in the future; ignored as a clock",
            }[verdict],
            "symbol": row.get("symbol") or (symbols[0] if isinstance(symbols, list) and symbols else None),
            "source_ref": str(path),
            "source_as_of": stamp if verdict == "PARSEABLE" else None,
            "evidence_class": row.get("evidence_class") or "INSTITUTIONAL_COGNITION",
            "authority": "NON_AUTHORITATIVE_CONTEXT",
            "office_truth_fields_withheld": withheld,
        }

    for kind, path in paths.items():
        if kind == "operator_feedback":
            continue  # projected below as prior_operator_decision
        for row in rows_for(path)[-100:]:
            flags = _cognition_flags(kind, row)
            item = base_item(kind, path, row)
            state = "USED" if flags["used_basis"] else (
                "RETRIEVED" if flags["retrieval_basis"] else item["availability"])
            item.update({
                "id": row.get("context_id") or row.get("retrieval_receipt_id") or row.get("memory_id")
                or row.get("lineage_id") or row.get("run_id") or row.get("feedback_id"),
                "state": state,
                "retrieved": bool(flags["retrieval_basis"]),
                "retrieval_basis": flags["retrieval_basis"],
                "used": bool(flags["used_basis"]),
                "used_basis": flags["used_basis"],
                "changed_question_or_view": flags["changed"],
                "contradictory": flags["contradictory"],
                "summary": row.get("summary") or row.get("query") or row.get("purpose") or row.get("task") or row.get("event"),
                "influence": "PROVEN" if flags["influence_basis"] else "NOT_PROVEN",
                "influence_basis": flags["influence_basis"],
            })
            items.append(item)

    for kind, path in operator_paths.items():
        op_rows = rows_for(path)
        if kind == "defer_lineage":
            # Append log: the latest row per lineage carries quarantine state.
            latest: dict[str, dict[str, Any]] = {}
            for row in op_rows:
                latest[str(row.get("lineage_id") or row.get("decision_id") or len(latest))] = row
            op_rows = list(latest.values())
        for row in op_rows[-100:]:
            decision = _operator_decision(row, kind)
            if decision is None:
                continue
            item = base_item("prior_operator_decision", path, row)
            item.update({
                "id": row.get("feedback_id") or row.get("decision_id") or row.get("plan_id") or row.get("lineage_id"),
                "operator_decision": decision,
                "operator_decision_source": kind,
                "advice": row.get("free_text") or row.get("note") or row.get("reason"),
                "plan_id": row.get("plan_id"),
                "state": item["availability"],
                "retrieved": False,
                "retrieval_basis": None,
                "used": False,
                "used_basis": None,
                "changed_question_or_view": False,
                "contradictory": False,
                "summary": f"operator {decision.lower()}: {row.get('free_text') or row.get('note') or row.get('reason') or 'no advice text recorded'}",
                "influence": "NOT_PROVEN",
                "influence_basis": None,
            })
            items.append(item)

    source_as_of = max((s["source_as_of"] for s in sources if s["source_as_of"]), default=None)
    counts = {
        "available": sum(i["availability"] == "AVAILABLE" for i in items),
        "retrieved": sum(bool(i["retrieved"]) for i in items),
        "used": sum(bool(i["used"]) for i in items),
        "changed": sum(bool(i["changed_question_or_view"]) for i in items),
        "contradictory": sum(bool(i["contradictory"]) for i in items),
        "unknown_availability": sum(i["availability"] != "AVAILABLE" for i in items),
        "prior_operator_decisions": sum(i["kind"] == "prior_operator_decision" for i in items),
        "influence_proven": sum(i["influence"] == "PROVEN" for i in items),
    }
    return {
        "office_truth_boundary": list(OFFICE_TRUTH_CATEGORIES),
        "office_truth": {
            "authority": "OFFICE_TRUTH",
            "categories": list(OFFICE_TRUTH_CATEGORIES),
            "sourced_from_memory": False,
            "replaceable_by_cognition": False,
            "values_in_this_block": False,
            "reason": "prices, holdings, cash, broker state, orders and risk limits come only from the "
                      "office-truth stores; cognition rows never supply or override them, and any such "
                      "field on a cognition row is withheld (office_truth_fields_withheld)",
        },
        "institutional_cognition": {
            "authority": "NON_AUTHORITATIVE_CONTEXT",
            "kinds": [*[k for k in paths if k != "operator_feedback"], "prior_operator_decision"],
            "item_count": len(items),
            "may_inform": "advisory context and research questions only",
        },
        "items": items,
        "contradictory_items": [i for i in items if i["contradictory"]][:50],
        "prior_operator_decisions": [i for i in items if i["kind"] == "prior_operator_decision"][:100],
        "counts": counts,
        "sources": sources,
        "source_as_of": source_as_of,
        "freshness": _freshness(source_as_of),
        "memory_behavior_influence": 0,
        "authority": "NON_AUTHORITATIVE_CONTEXT",
    }


# ── learning ───────────────────────────────────────────────────────────────

_SETTLED_STATES = frozenset({"OUTCOME_EVALUATED", "SETTLED", "SETTLED_OUTCOME", "CONFIRMED", "REFUTED", "EXPIRED", "SUCCESSFUL", "UNSUCCESSFUL"})
_SUCCESS_STATES = frozenset({"SUCCESS", "SUCCESSFUL", "POSITIVE", "CONFIRMED", "WIN", "SUPPORTED"})
_FAILURE_STATES = frozenset({"FAILURE", "FAILED", "UNSUCCESSFUL", "NEGATIVE", "REFUTED", "LOSS", "CONTRADICTED"})
CALIBRATION_METHOD = (
    "success_rate = successful / sample_size over UNIQUE settled outcome ids that carry a directional "
    "verdict, grouped by (population, horizon); same rule as settle_agent_commitments.SettlementLedger.calibration"
)


def _direction(change_pct: float | None, recommendation: str) -> str | None:
    """Producer rule (outcome_to_lesson._direction); imported lazily, never re-invented."""
    try:
        from scripts.lib.outcome_to_lesson import _direction as producer_direction
    except Exception:  # noqa: BLE001
        return None
    return producer_direction(change_pct, recommendation)


def _outcome_view(row: dict[str, Any], *, store: str) -> dict[str, Any] | None:
    oid = row.get("outcome_id") or row.get("id")
    if not oid:
        return None
    status = str(row.get("status") or row.get("outcome") or row.get("lifecycle_state") or "").upper()
    settled = False
    verdict: str | None = None
    population = row.get("population")
    horizon = row.get("horizon")
    if store == "outcome_observations.jsonl":
        realized = row.get("realized_state") if isinstance(row.get("realized_state"), dict) else {}
        change = None
        for key in ("change_pct", "return_pct", "pct_change"):
            if realized.get(key) is not None:
                try:
                    change = float(realized[key])
                except (TypeError, ValueError):
                    change = None
                break
        settled = change is not None and realized.get("price_at_horizon") is not None
        if settled:
            original = row.get("original_decision_state") if isinstance(row.get("original_decision_state"), dict) else {}
            direction = _direction(change, str(original.get("recommendation") or ""))
            verdict = {"CONFIRMED": "SUCCESSFUL", "CONTRADICTED": "UNSUCCESSFUL"}.get(str(direction))
        population = population or "checkpoint"
        status = "SETTLED" if settled else (status or "PENDING")
    else:
        settled = status in _SETTLED_STATES or isinstance(row.get("correct"), bool)
        if settled:
            if isinstance(row.get("correct"), bool):
                verdict = "SUCCESSFUL" if row["correct"] else "UNSUCCESSFUL"
            else:
                result = str(row.get("result") or row.get("outcome") or row.get("lifecycle_state") or row.get("status") or "").upper()
                verdict = "SUCCESSFUL" if result in _SUCCESS_STATES else "UNSUCCESSFUL" if result in _FAILURE_STATES else None
        population = population or "advisory"
    return {
        "outcome_id": str(oid),
        "decision_id": row.get("decision_id"),
        "status": status or None,
        "settled": settled,
        "verdict": verdict,
        "population": population,
        "horizon": horizon,
        "store": store,
        "source_as_of": _stamp(row),
    }


def _runtime_advisory_view(row: dict[str, Any]) -> dict[str, Any] | None:
    """data/runtime/advisory_outcomes.jsonl rows, under the belief writer's id."""
    sid = row.get("source_row_id")
    if not sid or not isinstance(row.get("correct"), bool):
        return None
    try:
        horizon = f"{int(row.get('horizon_d') or 0)}d"
    except (TypeError, ValueError):
        return None
    return {
        "outcome_id": f"adv:{sid}:{horizon}",
        "decision_id": row.get("decision_id"),
        "status": "SETTLED",
        "settled": True,
        "verdict": "SUCCESSFUL" if row["correct"] else "UNSUCCESSFUL",
        "population": "advisory",
        "horizon": horizon,
        "store": "runtime/advisory_outcomes.jsonl",
        "source_as_of": _stamp(row) or row.get("scored_at"),
    }


def _resolve_state(ids: list[str], index: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    settled = [i for i in ids if (index.get(i) or {}).get("settled")]
    pending = [i for i in ids if i in index and not index[i]["settled"]]
    unresolved = [i for i in ids if i not in index]
    detail = {"resolved_outcome_ids": settled, "pending_outcome_ids": pending, "unresolved_evidence_ids": unresolved}
    if ids and len(settled) == len(ids):
        return "PROVEN", detail
    if pending and not unresolved:
        return "PENDING_OUTCOME", detail
    return "INSUFFICIENT_EVIDENCE", detail


def _learning_row(row: dict[str, Any], *, origin: str, index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evidence_ids = _evidence_ids(row)
    raw_status = str(row.get("promotion_stage") or row.get("status") or "UNKNOWN").upper()
    state, detail = _resolve_state(evidence_ids, index)
    reason = (
        "every evidence id resolves to a settled outcome row" if state == "PROVEN"
        else "evidence ids resolve only to unsettled outcome rows" if state == "PENDING_OUTCOME"
        else "no evidence id resolves to a settled outcome row" if not detail["resolved_outcome_ids"]
        else f"{len(detail['unresolved_evidence_ids'])} evidence id(s) do not resolve to an outcome row"
    )
    return {
        **row,
        "evidence_ids": evidence_ids,
        "evidence_state": state,
        "evidence_reason": reason,
        **detail,
        "origin": origin,
        "outcome_ids": _row_refs(row, "outcome_ids", "supporting_outcome_ids", "outcome_id"),
        "status": raw_status,
        "producer_status": raw_status,
    }


def _learning(root: Path, *, decision_id: str | None = None, composition_as_of: str | None = None) -> dict[str, Any]:
    paths = {
        "outcomes": root / "advisory_outcomes_v1.jsonl",
        "observations": root / "outcome_observations.jsonl",
        "checkpoints": root / "outcome_checkpoints.jsonl",
        "lessons": root / "lesson_candidates.jsonl",
        "experiments": root / "shadow_experiments.jsonl",
        "hypotheses": root / "hypotheses.jsonl",
        "hypothesis_candidates": root / "hypothesis_candidates.jsonl",
        "operator_learning": root / "cio_operator_learning.jsonl",
        "instrument_records": root / "cio_instrument_records.jsonl",
    }
    runtime_outcomes = _runtime_root(root) / "advisory_outcomes.jsonl"
    ceiling = _parse_ts(composition_as_of) if composition_as_of else None
    outcome_kinds = ("outcomes", "observations")
    rows_by_kind: dict[str, list[dict[str, Any]]] = {}
    scopes: dict[str, str] = {}
    for kind, path in paths.items():
        if kind in outcome_kinds and not decision_id:
            rows_by_kind[kind] = _rows(path, max_bytes=_OUTCOME_SCAN_BYTES)
            scopes[kind] = "FULL_STORE" if path.is_file() and path.stat().st_size <= _OUTCOME_SCAN_BYTES else "RECENT_WINDOW"
        else:
            rows_by_kind[kind] = _rows(path, decision_id=decision_id)
    sources = [
        {"source": path.name, **_source_meta(path, rows_by_kind[kind], exact=bool(decision_id), scope=scopes.get(kind), ceiling=ceiling)}
        for kind, path in paths.items()
    ]

    views: list[dict[str, Any]] = []
    for kind in outcome_kinds:
        for row in rows_by_kind[kind]:
            view = _outcome_view(row, store=paths[kind].name)
            if view:
                views.append(view)
    index: dict[str, dict[str, Any]] = {}
    for view in views:
        prior = index.get(view["outcome_id"])
        # An outcome id is settled once any row for it is settled.
        if prior is None or (view["settled"] and not prior["settled"]):
            index[view["outcome_id"]] = view

    lessons_raw = rows_by_kind["lessons"] + [r for r in rows_by_kind["operator_learning"] if r.get("lesson_id") or r.get("statement")]
    hypotheses_raw = rows_by_kind["hypotheses"] + rows_by_kind["hypothesis_candidates"]
    records: dict[str, dict[str, Any]] = {}
    for record in rows_by_kind["instrument_records"]:
        key = str(record.get("subject_key") or record.get("subject_guid") or id(record))
        records[key] = record  # append log: last row per subject wins
    belief_rows: dict[str, dict[str, Any]] = {}
    for record in records.values():
        for belief in record.get("beliefs") or []:
            if isinstance(belief, dict):
                belief_rows[str(belief.get("belief_id") or belief.get("belief_key") or len(belief_rows))] = belief

    # Resolve every referenced outcome id against the real outcome rows.
    referenced = set()
    for row in [*lessons_raw[-100:], *hypotheses_raw[-100:]]:
        referenced.update(_evidence_ids(row))
    for belief in belief_rows.values():
        referenced.update(_row_refs(belief, "outcome_ids", "outcome_id"))
    missing = {i for i in referenced if i not in index}
    adv_missing = {i for i in missing if i.startswith("adv:")}
    if adv_missing and runtime_outcomes.is_file():
        # belief writer id shape: adv:<source_row_id>:<horizon_d>d (source_row_id may hold ':')
        sids = {i[len("adv:"):].rsplit(":", 1)[0] for i in adv_missing}
        for row in _rows_containing(runtime_outcomes, set(list(sids)[:_MAX_RESOLVE_NEEDLES])):
            view = _runtime_advisory_view(row)
            if view and view["outcome_id"] in adv_missing:
                index[view["outcome_id"]] = view
    other_missing = {i for i in missing if not i.startswith("adv:") and i not in index}
    if other_missing and len(other_missing) <= _MAX_RESOLVE_NEEDLES:
        for kind in outcome_kinds:
            for row in _rows_containing(paths[kind], other_missing):
                view = _outcome_view(row, store=paths[kind].name)
                if view and view["outcome_id"] in other_missing and view["outcome_id"] not in index:
                    index[view["outcome_id"]] = view

    settled_views = [v for v in index.values() if v["settled"]]
    pending_views = [v for v in index.values() if not v["settled"]]
    window_views = [v for v in index.values() if v["store"] in {paths[k].name for k in outcome_kinds}]
    verdict_ids = {v["outcome_id"] for v in window_views if v["settled"] and v["verdict"]}
    success_ids = {v["outcome_id"] for v in window_views if v["settled"] and v["verdict"] == "SUCCESSFUL"}
    any_outcome_store = any(paths[k].is_file() for k in outcome_kinds)
    sample_size = len(verdict_ids) if any_outcome_store else None
    successful_count = len(success_ids) if any_outcome_store else None
    success_rate = round(successful_count / sample_size, 6) if sample_size else None

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for view in window_views:
        if view["settled"] and view["verdict"]:
            groups[(str(view["population"]), str(view["horizon"]))].append(view)
    calibration_groups = [
        {
            "population": pop,
            "horizon": hz,
            "sample_size": len({v["outcome_id"] for v in rows}),
            "successful": len({v["outcome_id"] for v in rows if v["verdict"] == "SUCCESSFUL"}),
            "success_rate": round(len({v["outcome_id"] for v in rows if v["verdict"] == "SUCCESSFUL"}) / len({v["outcome_id"] for v in rows}), 6),
            "outcome_ids_sample": sorted({v["outcome_id"] for v in rows})[-20:],
        }
        for (pop, hz), rows in sorted(groups.items())
    ]
    calibration = {"method": CALIBRATION_METHOD, "groups": calibration_groups} if calibration_groups else None
    calibration_reason = None if calibration else "no settled outcome with a directional verdict; calibration not computed"

    def lesson_origin(row: dict[str, Any]) -> str:
        if str(row.get("lesson_provenance") or row.get("origin") or "").upper() == "RESEARCH_DERIVED":
            return "RESEARCH_DERIVED"
        return "OUTCOME_DERIVED" if _evidence_ids(row) else "UNKNOWN"

    lessons = [_learning_row(row, origin=lesson_origin(row), index=index) for row in lessons_raw[-100:]]
    hypotheses = [_learning_row(row, origin=str(row.get("origin") or "UNKNOWN").upper(), index=index) for row in hypotheses_raw[-100:]]
    experiments = rows_by_kind["experiments"][-100:]

    beliefs: list[dict[str, Any]] = []
    for belief in belief_rows.values():
        outcome_ids = _row_refs(belief, "outcome_ids", "outcome_id")
        state, detail = _resolve_state(outcome_ids, index)
        method = belief.get("calibration_schema") or belief.get("calibration_method")
        beliefs.append({
            **belief,
            "belief_id": belief.get("belief_id") or belief.get("belief_key"),
            "outcome_ids": outcome_ids,
            "sample_size": belief.get("sample_size") if belief.get("sample_size") is not None else len(outcome_ids),
            "evidence_state": state,
            **detail,
            "lesson_ids": _row_refs(belief, "lesson_ids"),
            "hypothesis_ids": _row_refs(belief, "hypothesis_ids"),
            "calibration": ({
                "method": method,
                "computed_by": belief.get("written_by"),
                "sample_size": belief.get("sample_size"),
                "successful": belief.get("successful"),
                "success_rate": belief.get("success_rate"),
            } if state == "PROVEN" and method else None),
            "calibration_reason": None if state == "PROVEN" and method else (
                "producer stated no calibration method" if not method else f"outcome evidence {state}"),
            "state": str(belief.get("status") or belief.get("state") or "UNKNOWN").upper(),
        })
    known_beliefs = {b.get("belief_id") for b in beliefs}
    beliefs.extend({
        "belief_id": row.get("belief_id"),
        "outcome_ids": row["outcome_ids"],
        "sample_size": row.get("sample_size"),
        "success_rate": row.get("success_rate") if row["evidence_state"] == "PROVEN" else None,
        "state": row.get("status") or "UNKNOWN",
        "evidence_state": row["evidence_state"],
        "resolved_outcome_ids": row["resolved_outcome_ids"],
        "lesson_ids": [row.get("lesson_id")] if row.get("lesson_id") else [],
        "hypothesis_ids": [],
        "calibration": None,
        "calibration_reason": "lesson-carried belief; no calibration method stated",
    } for row in lessons if row.get("belief_id") and row.get("belief_id") not in known_beliefs)

    # REVIEW_READY: the producer says so AND the evidence resolves to settled outcomes.
    review_ready = [row for row in [*lessons, *hypotheses]
                    if row.get("producer_status") == "REVIEW_READY" and row.get("evidence_state") == "PROVEN"]
    producer_review_ready_unproven = sum(
        1 for row in [*lessons, *hypotheses]
        if row.get("producer_status") == "REVIEW_READY" and row.get("evidence_state") != "PROVEN")
    maturity_state = "REVIEW_READY" if review_ready else "INSUFFICIENT_EVIDENCE" if not sample_size or sample_size < 5 else "OBSERVATION_ONLY"

    link_graph = _link_graph(
        outcome_views=[*settled_views[-100:], *pending_views[-100:]],
        index=index, beliefs=beliefs, lessons=lessons, hypotheses=hypotheses,
    )
    horizons = sorted({str(v["horizon"]) for v in settled_views if v.get("horizon")})
    source_as_of = max((s["source_as_of"] for s in sources if s["source_as_of"]), default=None)

    def public(view: dict[str, Any]) -> dict[str, Any]:
        return {k: view[k] for k in ("outcome_id", "decision_id", "status", "verdict", "population", "horizon", "store", "source_as_of")}

    return {
        "settled_outcomes": [public(v) for v in settled_views[-100:]],
        "pending_outcomes": [public(v) for v in pending_views[-100:]],
        "settled_count": len({v["outcome_id"] for v in window_views if v["settled"]}) if any_outcome_store else None,
        "settled_without_verdict_count": len({v["outcome_id"] for v in window_views if v["settled"] and not v["verdict"]}) if any_outcome_store else None,
        "beliefs": beliefs[-100:],
        "lessons": lessons,
        "research_derived_lessons": [row for row in lessons if row.get("origin") == "RESEARCH_DERIVED"],
        "outcome_derived_lessons": [row for row in lessons if row.get("origin") == "OUTCOME_DERIVED"],
        "hypotheses": hypotheses,
        "experiments": experiments,
        "checkpoint_count": len(rows_by_kind["checkpoints"]),
        "sample_size": sample_size,
        "successful_count": successful_count,
        "success_rate": success_rate,
        "sample_rule": "unique settled outcome ids with a directional verdict (numerator and denominator)",
        "horizon": horizons[0] if len(horizons) == 1 else None,
        "horizons": horizons,
        "calibration": calibration,
        "calibration_reason": calibration_reason,
        "maturity_state": maturity_state,
        "review_ready": review_ready,
        "producer_review_ready_unproven": producer_review_ready_unproven,
        "evidence_state_counts": {
            state: sum(row.get("evidence_state") == state for row in [*lessons, *hypotheses, *beliefs])
            for state in ("PROVEN", "PENDING_OUTCOME", "INSUFFICIENT_EVIDENCE")
        },
        "link_graph": link_graph,
        "sources": sources,
        "source_as_of": source_as_of,
        "freshness": _freshness(source_as_of),
        "memory_behavior_influence": 0,
        "self_promotion": False,
    }


def _link_graph(
    *, outcome_views: list[dict[str, Any]], index: dict[str, dict[str, Any]],
    beliefs: list[dict[str, Any]], lessons: list[dict[str, Any]], hypotheses: list[dict[str, Any]],
) -> dict[str, Any]:
    """Edges only from real refs carried by producer rows; ``resolved`` says
    whether the target id exists in the outcome rows that were read."""
    edges: list[dict[str, Any]] = []
    decision_to_outcomes: dict[str, set[str]] = defaultdict(set)
    outcome_to_beliefs: dict[str, set[str]] = defaultdict(set)
    belief_to_learning: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"lesson_ids": set(), "hypothesis_ids": set()})
    lesson_to_sources: dict[str, dict[str, set[str]]] = defaultdict(lambda: {"outcome_ids": set(), "decision_ids": set()})

    def edge(from_type: str, from_id: str, relation: str, to_type: str, to_id: str, resolved: bool, via: str) -> None:
        edges.append({"from_type": from_type, "from_id": from_id, "relation": relation,
                      "to_type": to_type, "to_id": to_id, "resolved": resolved, "via": via})

    referenced_outcomes = {v["outcome_id"] for v in outcome_views}
    for belief in beliefs:
        referenced_outcomes.update(belief.get("outcome_ids") or [])
    for row in [*lessons, *hypotheses]:
        referenced_outcomes.update(row.get("evidence_ids") or [])
    for oid in sorted(referenced_outcomes):
        view = index.get(oid)
        if view and view.get("decision_id"):
            did = str(view["decision_id"])
            decision_to_outcomes[did].add(oid)
            edge("decision", did, "HAS_OUTCOME", "outcome", oid, True, f"{view['store']}.decision_id")
    for belief in beliefs:
        bid = str(belief.get("belief_id") or "")
        if not bid:
            continue
        for oid in belief.get("outcome_ids") or []:
            outcome_to_beliefs[oid].add(bid)
            edge("outcome", oid, "SUPPORTS_BELIEF", "belief", bid, oid in index, "belief.outcome_ids")
        for lid in belief.get("lesson_ids") or []:
            belief_to_learning[bid]["lesson_ids"].add(lid)
            edge("belief", bid, "CITES_LESSON", "lesson", lid, True, "belief.lesson_ids")
        for hid in belief.get("hypothesis_ids") or []:
            belief_to_learning[bid]["hypothesis_ids"].add(hid)
            edge("belief", bid, "CITES_HYPOTHESIS", "hypothesis", hid, True, "belief.hypothesis_ids")
    for kind, rows in (("lesson", lessons), ("hypothesis", hypotheses)):
        for row in rows:
            lid = str(row.get("lesson_id") or row.get("hypothesis_id") or row.get("id") or "")
            if not lid:
                continue
            for oid in row.get("evidence_ids") or []:
                lesson_to_sources[lid]["outcome_ids"].add(oid)
                edge(kind, lid, "DERIVED_FROM_OUTCOME", "outcome", oid, oid in index, f"{kind}.evidence_ids")
                view = index.get(oid)
                if view and view.get("decision_id"):
                    lesson_to_sources[lid]["decision_ids"].add(str(view["decision_id"]))
                    edge(kind, lid, "DERIVED_FROM_DECISION", "decision", str(view["decision_id"]), True, "outcome.decision_id")
            for did in _row_refs(row, "decision_id", "source_decision_ids", "decision_ids"):
                lesson_to_sources[lid]["decision_ids"].add(did)
                edge(kind, lid, "DERIVED_FROM_DECISION", "decision", did, False, f"{kind}.decision_id")

    def listed(mapping: dict[str, set[str]]) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in sorted(mapping.items())[:200]}

    relation_counts: dict[str, int] = defaultdict(int)
    for item in edges:
        relation_counts[item["relation"]] += 1
    return {
        "decision_to_outcomes": listed(decision_to_outcomes),
        "outcome_to_beliefs": listed(outcome_to_beliefs),
        "belief_to_lessons_hypotheses": {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in sorted(belief_to_learning.items())[:200]},
        "lesson_to_sources": {k: {kk: sorted(vv) for kk, vv in v.items()} for k, v in sorted(lesson_to_sources.items())[:200]},
        "edges": edges[:1000],
        "edge_count": len(edges),
        "relation_counts": dict(relation_counts),
        "unresolved_edge_count": sum(not e["resolved"] for e in edges),
        "rule": "edges come only from ids carried by producer rows; nothing is joined by symbol",
    }


# ── capability coverage ────────────────────────────────────────────────────

def _ids_from(row: dict[str, Any], keys: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for scope in (row, row.get("payload") if isinstance(row.get("payload"), dict) else {}):
        for key in keys:
            value = scope.get(key)
            if isinstance(value, str) and value.strip():
                out.add(value.strip())
            elif isinstance(value, list):
                out.update(str(v).strip() for v in value if isinstance(v, (str, int)) and str(v).strip())
    return out


def _belief_entries(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [b for b in (row.get("beliefs") or []) if isinstance(b, dict) and b.get("written_by") == "cio_belief_writer"]


def _spine_research(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in (row.get("contributions") or []) if isinstance(c, dict)
            and str(c.get("silo") or "").lower() == "hermes" and c.get("kind") == "research_result" and c.get("artifact_id")]


def _wl_node(node_type: str) -> Callable[[dict[str, Any]], bool]:
    return lambda r: r.get("record_type") == "node" and r.get("node_type") == node_type


_DISAGREEMENT_NODE_TYPES = {"SPECIALIST_DISAGREEMENT", "DISAGREEMENT"}
_DISAGREEMENT_RELATIONS = {"DISAGREES_WITH", "CONTRADICTS", "DISSENTS_FROM"}

# (capability, producer module, producer store, predicate, predicate description,
#  discriminated, producer-id extractor, consumers [(store, ref keys)], stale_after_seconds)
_DAY = 86_400
_CAPABILITY_SPECS: list[dict[str, Any]] = [
    {"capability": "InstrumentRecord", "producer": "scripts.lib.cio_instrument_record", "store": "cio_instrument_records.jsonl",
     "predicate": lambda r: r.get("schema") == "InstrumentRecord@v1", "predicate_desc": "schema == InstrumentRecord@v1",
     "ids": lambda r: _ids_from(r, ("subject_key",)), "consumers": [("cio_wake_jobs.jsonl", ("subject_key",)), ("context_use_receipts.jsonl", ("subject_key",))],
     "stale_after_seconds": _DAY},
    {"capability": "identity resolution", "producer": "scripts.lib.identity_registry", "store": "security_research_spine.jsonl",
     "predicate": lambda r: bool(r.get("subject_guid")), "predicate_desc": "spine row carrying a resolved subject_guid",
     "discriminated": False,
     "indistinguishable_reason": "identity resolution writes no record of its own here; a resolved subject_guid on a spine row cannot be separated from spine publication",
     "ids": lambda r: _ids_from(r, ("subject_guid",)), "consumers": [("cio_workflow_lineage.jsonl", ("subject_guid",)), ("context_use_receipts.jsonl", ("security_guid",))],
     "stale_after_seconds": _DAY},
    {"capability": "office truth", "producer": "scripts.lib.cio_event_bus", "store": "cio_events.jsonl",
     "predicate": lambda r: bool(r.get("event_type")), "predicate_desc": "cio event with event_type",
     "ids": lambda r: _ids_from(r, ("event_id",)), "consumers": [("cio_workflow_lineage.jsonl", ("event_id",))],
     "stale_after_seconds": 3_600},
    {"capability": "persistent cognition", "producer": "scripts.lib.agent_durable_memory", "store": "memory_contexts.jsonl",
     "predicate": lambda r: bool(r.get("context_id")), "predicate_desc": "memory context row with context_id",
     "ids": lambda r: _ids_from(r, ("context_id",)), "consumers": [("hermes_research_results.jsonl", ("context_id",)), ("context_use_receipts.jsonl", ("context_id",))],
     "stale_after_seconds": _DAY},
    {"capability": "memory retrieval", "producer": "scripts.lib.agent_durable_memory", "store": "aif_memory_retrievals.jsonl",
     "predicate": lambda r: bool(r.get("retrieval_status")), "predicate_desc": "retrieval row with retrieval_status",
     "ids": lambda r: _ids_from(r, ("memory_ids",)), "consumers": [("context_use_receipts.jsonl", ("memory_ids",))],
     "stale_after_seconds": _DAY},
    {"capability": "Hermes research", "producer": "scripts.lib.cio_hermes_research", "store": "hermes_research_requests.jsonl",
     "predicate": lambda r: bool(r.get("research_id")), "predicate_desc": "request row with research_id",
     "ids": lambda r: _ids_from(r, ("research_id",)), "consumers": [("hermes_research_results.jsonl", ("research_id",)), ("intelligence_lineages.jsonl", ("research_request_ids",))],
     "stale_after_seconds": 6 * 3_600},
    {"capability": "external research", "producer": "scripts.lib.cross_asset.security_research_spine", "store": "security_research_spine.jsonl",
     "predicate": lambda r: bool(_spine_research(r)), "predicate_desc": "spine contribution silo=hermes kind=research_result",
     "ids": lambda r: {str(c["artifact_id"]) for c in _spine_research(r)}, "consumers": [("intelligence_lineages.jsonl", ("research_result_ids",)), ("cio_workflow_lineage.jsonl", ("research_artifact_id",))],
     "stale_after_seconds": _DAY},
    {"capability": "specialist artifacts", "producer": "scripts.lib.cio_specialist_artifact", "store": "cio_specialist_artifacts.jsonl",
     "predicate": None, "predicate_desc": "any row (dedicated store)",
     "ids": lambda r: _ids_from(r, ("artifact_id",)), "consumers": [("cio_workflow_lineage.jsonl", ("specialist_artifact_id",))],
     "stale_after_seconds": 7 * _DAY},
    {"capability": "specialist disagreement", "producer": "scripts.lib.cio_specialist_artifact", "store": "cio_workflow_lineage.jsonl",
     "predicate": lambda r: r.get("node_type") in _DISAGREEMENT_NODE_TYPES or r.get("relationship") in _DISAGREEMENT_RELATIONS
     or r.get("schema") == "SpecialistDisagreementMemory@v1",
     "predicate_desc": "node_type SPECIALIST_DISAGREEMENT / relationship DISAGREES_WITH|CONTRADICTS / SpecialistDisagreementMemory@v1",
     "ids": lambda r: _ids_from(r, ("node_id", "from")), "consumers": [("intelligence_lineages.jsonl", ("disagreement_ids",))],
     "stale_after_seconds": 7 * _DAY},
    {"capability": "CIO synthesis", "producer": "scripts.lib.cio_committee", "store": "cio_workflow_lineage.jsonl",
     "predicate": _wl_node("CIO_PRODUCT"), "predicate_desc": "workflow lineage node_type == CIO_PRODUCT",
     "ids": lambda r: _ids_from(r, ("node_id",)), "consumers": [("cio_plans.jsonl", ("product_id", "node_id")), ("cio_production_cases.jsonl", ("product_id", "node_id"))],
     "stale_after_seconds": _DAY},
    {"capability": "judgment", "producer": "scripts.lib.cio_run", "store": "cio_workflow_lineage.jsonl",
     "predicate": _wl_node("CIO_GENERATION"), "predicate_desc": "workflow lineage node_type == CIO_GENERATION",
     "ids": lambda r: _ids_from(r, ("node_id", "cio_generation_id")), "consumers": [("cio_action_ledger.jsonl", ("cio_generation_id", "generation_id"))],
     "stale_after_seconds": _DAY},
    {"capability": "commitment", "producer": "scripts.lib.cio_action_ledger", "store": "cio_action_ledger.jsonl",
     "predicate": lambda r: str(r.get("event_type") or "").startswith("CIO_ACTION"), "predicate_desc": "event_type CIO_ACTION_*",
     "ids": lambda r: _ids_from(r, ("stream_id", "cio_action_id", "action_id")), "consumers": [("operator_notification_outbox.jsonl", ("cio_action_id", "action_id"))],
     "stale_after_seconds": _DAY},
    {"capability": "notification policy", "producer": "scripts.lib.cio_notification_signal", "store": "cio_notification_audit.jsonl",
     "predicate": lambda r: bool(r.get("notification_id")), "predicate_desc": "audit row with notification_id",
     "ids": lambda r: _ids_from(r, ("notification_id",)), "consumers": [("operator_notification_outbox.jsonl", ("notification_id",))],
     "stale_after_seconds": _DAY},
    {"capability": "delivery/outbox", "producer": "scripts.lib.cio_delivery_mode", "store": "operator_notification_outbox.jsonl",
     "predicate": lambda r: bool(r.get("event_type")), "predicate_desc": "outbox event with event_type",
     "ids": lambda r: _ids_from(r, ("stream_id", "notification_id")), "consumers": [("cio_telegram_receipts.jsonl", ("notification_id", "stream_id"))],
     "stale_after_seconds": _DAY},
    {"capability": "operator feedback", "producer": "scripts.lib.cio_operator_ticker_feedback", "store": "operator_ticker_feedback.jsonl",
     "predicate": None, "predicate_desc": "any row (dedicated store)",
     "ids": lambda r: _ids_from(r, ("feedback_id",)), "consumers": [("cio_workflow_lineage.jsonl", ("feedback_id",)), ("cio_operator_learning.jsonl", ("feedback_id",))],
     "stale_after_seconds": 30 * _DAY},
    {"capability": "outcome checkpoint", "producer": "scripts.lib.r17_checkpoint_binding", "store": "outcome_checkpoints.jsonl",
     "predicate": lambda r: bool(r.get("checkpoint_id")), "predicate_desc": "checkpoint row with checkpoint_id",
     "ids": lambda r: _ids_from(r, ("checkpoint_id",)), "consumers": [("outcome_observations.jsonl", ("checkpoint_id",)), ("cio_workflow_lineage.jsonl", ("checkpoint_id",))],
     "stale_after_seconds": _DAY},
    {"capability": "outcome settlement", "producer": "scripts.lib.cio_institutional_learning", "store": "outcome_observations.jsonl",
     "predicate": lambda r: bool(r.get("outcome_id")), "predicate_desc": "OutcomeObservation row with outcome_id",
     "ids": lambda r: _ids_from(r, ("outcome_id",)),
     "consumers": [("lesson_candidates.jsonl", ("supporting_outcome_ids",)), ("cio_instrument_records.jsonl", ("beliefs.outcome_ids",))],
     "stale_after_seconds": 3 * _DAY},
    {"capability": "belief writer", "producer": "scripts.lib.cio_belief_writer", "store": "cio_instrument_records.jsonl",
     "predicate": lambda r: bool(_belief_entries(r)), "predicate_desc": "InstrumentRecord beliefs[] written_by == cio_belief_writer",
     "ids": lambda r: {str(b.get("belief_proposal_id") or b.get("belief_key")) for b in _belief_entries(r)},
     "consumers": [("context_use_receipts.jsonl", ("belief_ids", "belief_proposal_id"))],
     "stale_after_seconds": 2 * _DAY},
    {"capability": "lesson", "producer": "scripts.lib.memory_consolidator", "store": "lesson_candidates.jsonl",
     "predicate": lambda r: bool(r.get("lesson_id")), "predicate_desc": "row with lesson_id",
     "ids": lambda r: _ids_from(r, ("lesson_id",)),
     "consumers": [("lesson_promotions.jsonl", ("lesson_id",)), ("cio_instrument_records.jsonl", ("beliefs.lesson_ids",))],
     "stale_after_seconds": 7 * _DAY},
    {"capability": "hypothesis", "producer": "scripts.lib.r17_checkpoint_binding", "store": "hypothesis_candidates.jsonl",
     "predicate": None, "predicate_desc": "any row (dedicated store)",
     "ids": lambda r: _ids_from(r, ("hypothesis_id", "id")), "consumers": [("shadow_experiments.jsonl", ("hypothesis_id",))],
     "stale_after_seconds": 7 * _DAY},
    {"capability": "graph propagation", "producer": "scripts.lib.ticker_knowledge_graph", "store": "ticker_research_graph.jsonl",
     "predicate": lambda r: bool(r.get("artifact_id") or r.get("research_artifact_guid")), "predicate_desc": "TickerResearchArtifact row",
     "ids": lambda r: _ids_from(r, ("artifact_id", "research_artifact_guid")), "consumers": [("cio_workflow_lineage.jsonl", ("research_artifact_id",)), ("intelligence_lineages.jsonl", ("research_artifact_ids",))],
     "stale_after_seconds": _DAY},
    {"capability": "canon retrieval", "producer": "scripts.lib.cio_canon", "store": "canon_retrievals.jsonl",
     "predicate": None, "predicate_desc": "any row (dedicated store)",
     "ids": lambda r: _ids_from(r, ("retrieval_id",)), "consumers": [("cio_workflow_lineage.jsonl", ("canon_retrieval_id",))],
     "stale_after_seconds": 7 * _DAY},
    {"capability": "historical analogue retrieval", "producer": "scripts.lib.cio_analogue_retrieval", "store": "historical_analogues.jsonl",
     "predicate": None, "predicate_desc": "any row (dedicated store)",
     "ids": lambda r: _ids_from(r, ("analogue_id",)), "consumers": [("cio_workflow_lineage.jsonl", ("analogue_id",))],
     "stale_after_seconds": 7 * _DAY},
]
# Generic edge fields: a consumer row naming the producer store here is an explicit reference.
_SOURCE_REF_KEYS = ("source_ref", "source_refs", "producer", "producer_id", "input_ref", "input_refs", "source_store")


def _consumer_refs(row: dict[str, Any], keys: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    plain = tuple(k for k in keys if "." not in k)
    out |= _ids_from(row, plain)
    for key in keys:
        if "." in key:
            outer, inner = key.split(".", 1)
            for entry in row.get(outer) or []:
                if isinstance(entry, dict):
                    out |= _ids_from(entry, (inner,))
    return out


def _known_dark_classification() -> dict[str, Any]:
    try:
        doc = json.loads(KNOWN_DARK_CLASSIFICATION_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"source_ref": str(KNOWN_DARK_CLASSIFICATION_PATH), "items": [], "counts": {},
                "status": "UNAVAILABLE", "reason": f"classification file unreadable: {type(exc).__name__}"}
    items = [i for i in doc.get("items") or [] if isinstance(i, dict)]
    baseline: set[str] | None
    try:
        from scripts.check_dark_contracts import KNOWN_DARK  # static dict, no I/O at import
        baseline = set(KNOWN_DARK)
    except Exception:  # noqa: BLE001
        baseline = None
    classified = {str(i.get("module")) for i in items}
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[str(item.get("classification"))] += 1
    return {
        "schema": doc.get("schema"),
        "source_ref": str(KNOWN_DARK_CLASSIFICATION_PATH.relative_to(REPO_ROOT)),
        "doc_ref": doc.get("doc_ref"),
        "classified_at": doc.get("classified_at"),
        "census_command": doc.get("census_command"),
        "items": items,
        "counts": dict(counts),
        "cio_relevant_count": sum(bool(i.get("cio_relevant")) for i in items),
        "unclassified_baseline_modules": sorted(baseline - classified) if baseline is not None else None,
        "baseline_check": "OK" if baseline is not None and not (baseline - classified) else (
            "UNKNOWN" if baseline is None else "UNCLASSIFIED_PRESENT"),
        "status": "AVAILABLE",
    }


def _capability_coverage(root: Path, *, composition_as_of: str | None = None) -> dict[str, Any]:
    """Classify capabilities from observed producer/consumer artifacts.

    A missing React field is never evidence of DARK.  Rules:

    * producer store missing, or no row matching the capability's predicate
      in the window -> DARK when the producer module is declared, else UNKNOWN;
    * producer rows but no explicit consumer reference -> PARTIAL;
    * producer rows plus an explicit consumer reference -> LIVE (capped at
      PARTIAL when the capability shares a store it cannot be told apart in);
    * no declared consumer contract -> UNWIRED.

    Staleness is a separate ``freshness`` field (FRESH/STALE/UNKNOWN).
    """
    composed = composition_as_of or _now()
    ceiling = _parse_ts(composed)
    cache: dict[str, list[dict[str, Any]]] = {}

    def window(name: str) -> list[dict[str, Any]]:
        if name not in cache:
            cache[name] = _rows(root / name)
        return cache[name]

    rows: list[dict[str, Any]] = []
    for spec in _CAPABILITY_SPECS:
        capability, producer, producer_name = spec["capability"], spec["producer"], spec["store"]
        consumers = spec["consumers"]
        producer_path = root / producer_name
        predicate = spec.get("predicate")
        producer_rows = [r for r in window(producer_name) if predicate is None or predicate(r)]
        producer_ids: set[str] = set()
        for row in producer_rows:
            producer_ids |= spec["ids"](row)
        tokens = {producer_name, producer_name.removesuffix(".jsonl")}
        direct: list[dict[str, Any]] = []
        consumer_refs: set[str] = set()
        ref_rows: list[tuple[dict[str, Any], set[str]]] = []
        for name, keys in consumers:
            for row in window(name):
                if name == producer_name and predicate is not None and predicate(row):
                    continue  # a producer row is not its own consumer
                refs = _consumer_refs(row, keys)
                named = " ".join(sorted(_ids_from(row, _SOURCE_REF_KEYS))).lower()
                if any(token in named for token in tokens) or (refs & producer_ids):
                    direct.append(row)
                elif refs:
                    ref_rows.append((row, refs))
                    consumer_refs |= refs
        # A reference outside the producer window still counts when it resolves
        # to a real producer row (small stores only; never a symbol join).
        if not direct and producer_rows and consumer_refs and producer_path.is_file() \
                and producer_path.stat().st_size <= _RESOLVE_SCAN_BYTES:
            needles = set(sorted(consumer_refs)[-_MAX_RESOLVE_NEEDLES:])
            resolved: set[str] = set()
            for row in _rows_containing(producer_path, needles):
                if predicate is None or predicate(row):
                    resolved |= spec["ids"](row) & needles
            direct = [row for row, refs in ref_rows if refs & resolved]
        module_path = REPO_ROOT / (producer.replace(".", "/") + ".py")
        module_declared = module_path.is_file()
        discriminated = spec.get("discriminated", True)
        if not consumers:
            state = "UNWIRED"
            reason = "declared producer has no declared consumer contract"
        elif not producer_rows:
            missing = "producer store is missing" if not producer_path.is_file() else (
                "no producer row matches this capability's predicate in the recent window")
            if module_declared:
                state = "DARK"
                reason = f"{missing}; declared producer module {producer} exists"
            else:
                state = "UNKNOWN"
                reason = f"{missing}; producer module {producer} is not present in this repo"
        elif direct and discriminated:
            state = "LIVE"
            reason = "producer rows matching the capability predicate and an explicit consumer reference were observed"
        elif direct:
            state = "PARTIAL"
            reason = f"capped at PARTIAL: {spec.get('indistinguishable_reason')}"
        else:
            state = "PARTIAL"
            reason = "producer rows observed; no consumer row carries an explicit reference to them"
        last_producer = _latest_stamp(producer_rows, not_after=ceiling)
        last_consumer = _latest_stamp(direct, not_after=ceiling)
        age = _age_seconds(last_producer, composed)
        stale_after = spec["stale_after_seconds"]
        freshness = "UNKNOWN" if age is None else ("FRESH" if age <= stale_after else "STALE")
        rows.append({
            "capability": capability,
            "contract": producer,
            "producer": producer,
            "producer_module_declared": module_declared,
            "producer_predicate": spec["predicate_desc"],
            "discriminated": discriminated,
            "consumer": ", ".join(name for name, _ in consumers) if consumers else None,
            "consumer_ref_keys": {name: list(keys) for name, keys in consumers},
            "producer_row_count": len(producer_rows),
            "consumer_reference_count": len(direct),
            "last_producer_event": last_producer,
            "last_consumer_event": last_consumer,
            "last_produced_at": last_producer,
            "last_consumed_at": last_consumer,
            "durable_artifact": str(producer_path),
            "artifact_age": age,
            "stale_after_seconds": stale_after,
            "freshness": freshness,
            "current_status": state,
            "state": state,
            "reason": reason,
            "source_sha": None,
            "source_version": _source_version(producer_path),
            "row_scope": "RECENT_WINDOW",
            "evidence_class": "RUNTIME_ARTIFACT_CENSUS",
        })
    counts = {state: sum(row["state"] == state for row in rows) for state in STATES}
    freshness_counts = {f: sum(row["freshness"] == f for row in rows) for f in ("FRESH", "STALE", "UNKNOWN")}
    source_as_of = max((r["last_produced_at"] for r in rows if r["last_produced_at"]),
                       key=lambda s: _parse_ts(s) or datetime.min.replace(tzinfo=timezone.utc), default=None)
    return {
        "rows": rows,
        "counts": counts,
        "freshness_counts": freshness_counts,
        "known_dark_classification": _known_dark_classification(),
        "source_as_of": source_as_of,
        "freshness": _freshness(source_as_of),
    }


def build_operator_evidence(
    *, now: str | None = None, decision_id: str | None = None,
    include_coverage: bool = True,
) -> dict[str, Any]:
    root = _root()
    composed = now or _now()
    research = _research_provenance(root, decision_id=decision_id)
    cognition = _cognition(root, decision_id=decision_id, composition_as_of=composed)
    learning = _learning(root, decision_id=decision_id, composition_as_of=composed)
    coverage = _capability_coverage(root, composition_as_of=composed) if include_coverage else {
        "rows": [],
        "counts": {state: 0 for state in STATES},
        "source_as_of": None,
        "freshness": "UNKNOWN",
        "reason": "omitted from exact decision lookup; unrelated capability stores are not scanned",
    }
    blocks = {"research": research, "institutional_cognition": cognition, "learning": learning, "capability_coverage": coverage}
    for block in blocks.values():
        block["composition_as_of"] = composed
        block["producer"] = "scripts.lib.cio_operator_evidence"
        block["freshness"] = block.get("freshness") or _freshness(block.get("source_as_of"))
        block["authority"] = AUTHORITY
    return {
        "ok": True,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "mutation": False,
        "memory_behavior_influence": 0,
        "source_as_of": min((b["source_as_of"] for b in blocks.values() if b.get("source_as_of")), default=None),
        "composition_as_of": composed,
        "blocks": blocks,
    }
