"""Append-only record of operator-relevant CIO artifacts that were otherwise transient.

Thirteen CIO outputs reach the operator (mostly on Telegram) or shape a decision
but were never stored, so the Command Center could not show them afterwards
(CIOCompletenessMeasurement@v2, 2026-10-03: 13 operator-relevant schemas
produced and not surfaced). This is the ONE governed store for them, approved
by the operator 2026-10-03 and registered in config/data_source_authority.json
(domain cio_operator_artifacts).

Each row keeps the artifact's own schema and ids; nothing is re-derived. Writes
are best-effort: a recording failure never blocks or changes a send or a
producer. Payloads are bounded and a truncation is always marked.

BuyReadyInstitutionalPacket@v2 is NOT copied here: it already has a durable
store (data/runtime/buy_ready_packets/<SYM>.json), so the reader serves it from
there instead of duplicating truth.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

SCHEMA = "CIOOperatorArtifact@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
STORE_RELATIVE = Path("data") / "cio" / "cio_operator_artifacts.jsonl"
BUY_READY_RELATIVE = Path("data") / "runtime" / "buy_ready_packets"
MAX_PAYLOAD_BYTES = 32_000
READ_TAIL_BYTES = 4_000_000

ALERT_QUALITY = "AlertQuality@v1"
ADVISORY_MESSAGE = "CIOAdvisoryMessage@v1"
ADVISORY_SYNTHESIS = "CIOAdvisorySynthesis@v1"
AGENT_BRIEF = "CIOAgentBrief@v1"
ATTENTION_ANSWER = "CIOAttentionAnswer@v1"
WHAT_CHANGED = "CIOWhatChanged@v1"
COMPOSED_NARRATIVE = "CioComposedNarrative@v1"
MODEL_NARRATION = "CioModelNarration@v1"
WAKE_COMPOSITION = "CioWakeComposition@v1"
GROK_CRITIQUE = "GrokCritique@v1"
INVESTMENT_DECISION = "InvestmentDecision@v1"
INTELLIGENCE_CARD = "InvestmentIntelligenceCard@v1"
BUY_READY_PACKET = "BuyReadyInstitutionalPacket@v2"

_LINK_KEYS = ("decision_id", "run_id", "trace_id", "wake_id", "plan_id", "research_id", "symbol")
_INDEX: dict[str, tuple[tuple[int, int], set[tuple[str, str]]]] = {}
_LOCK = threading.Lock()


def store_path(root: Path | str | None = None) -> Path:
    configured = (os.environ.get("CIO_OPERATOR_ARTIFACTS_JSONL") or "").strip()
    if configured:
        return Path(configured)
    if root:
        return Path(root) / STORE_RELATIVE
    from scripts.lib.canonical_store_registry import production_state_root
    return Path(production_state_root()) / STORE_RELATIVE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def _bounded(payload: Any) -> tuple[Any, bool, int]:
    text = json.dumps(payload, default=str, sort_keys=True)
    size = len(text.encode("utf-8"))
    if size <= MAX_PAYLOAD_BYTES:
        return _jsonable(payload), False, size
    # Keep a readable prefix; the marker says exactly what was cut.
    return {"_truncated": True, "_original_bytes": size,
            "_prefix": text.encode("utf-8")[:MAX_PAYLOAD_BYTES].decode("utf-8", "ignore")}, True, size


def _seen(path: Path) -> set[tuple[str, str]]:
    try:
        st = path.stat()
        key = (st.st_size, st.st_mtime_ns)
    except OSError:
        return set()
    hit = _INDEX.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    out: set[tuple[str, str]] = set()
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.add((str(row.get("original_schema")), str(row.get("artifact_id"))))
    _INDEX[str(path)] = (key, out)
    return out


def record_operator_artifact(
    original_schema: str,
    payload: Any,
    *,
    producer: str,
    artifact_id: str | None = None,
    links: Mapping[str, Any] | None = None,
    source_as_of: str | None = None,
    evidence_class: str = "PRODUCER_OUTPUT",
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Append one artifact once per (schema, artifact_id). Never raises."""
    try:
        if not original_schema or payload is None:
            return {"written": False, "reason": "empty"}
        basis = "producer_id"
        aid = str(artifact_id or "").strip()
        if not aid:
            basis = "content_sha256"
            aid = hashlib.sha256(json.dumps(payload, default=str, sort_keys=True).encode("utf-8")).hexdigest()[:24]
        body, truncated, size = _bounded(payload)
        row = {
            "schema": SCHEMA,
            "original_schema": original_schema,
            "artifact_id": aid,
            "artifact_id_basis": basis,
            "producer": producer,
            "source_as_of": source_as_of,
            "persisted_at": _now(),
            "evidence_class": evidence_class,
            "authority": AUTHORITY,
            "memory_behavior_influence": 0,
            "financial_action": False,
            "payload_bytes": size,
            "payload_truncated": truncated,
            "payload": body,
        }
        for key in _LINK_KEYS:
            value = (links or {}).get(key)
            if value not in (None, "", [], {}):
                row[key] = value if isinstance(value, (str, int, float)) else _jsonable(value)
        target = store_path(root)
        with _LOCK:
            if (original_schema, aid) in _seen(target):
                return {"written": False, "reason": "duplicate", "artifact_id": aid}
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    _INDEX.pop(str(target), None)
                    if target.stat().st_size and (original_schema, aid) in _seen(target):
                        return {"written": False, "reason": "duplicate", "artifact_id": aid}
                    fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            _INDEX.pop(str(target), None)
        return {"written": True, "artifact_id": aid, "path": str(target)}
    except Exception as exc:  # noqa: BLE001 - recording must never break a producer
        return {"written": False, "reason": f"{type(exc).__name__}"}


# One typed writer per schema: each names the schema it records, so the
# completeness measurement can verify the writer -> store -> reader edge.

def record_alert_quality(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(ALERT_QUALITY, payload, **kw)


def record_advisory_message(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(ADVISORY_MESSAGE, payload, **kw)


def record_advisory_synthesis(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(ADVISORY_SYNTHESIS, payload, **kw)


def record_agent_brief(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(AGENT_BRIEF, payload, **kw)


def record_attention_answer(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(ATTENTION_ANSWER, payload, **kw)


def record_what_changed(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(WHAT_CHANGED, payload, **kw)


def record_composed_narrative(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(COMPOSED_NARRATIVE, payload, **kw)


def record_model_narration(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(MODEL_NARRATION, payload, **kw)


def record_wake_composition(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(WAKE_COMPOSITION, payload, **kw)


def record_grok_critique(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(GROK_CRITIQUE, payload, **kw)


def record_investment_decision(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(INVESTMENT_DECISION, payload, **kw)


def record_intelligence_card(payload: Any, **kw: Any) -> dict[str, Any]:
    return record_operator_artifact(INTELLIGENCE_CARD, payload, **kw)


def _tail_rows(path: Path) -> list[dict[str, Any]]:
    try:
        size = path.stat().st_size
    except OSError:
        return []
    with path.open("rb") as fh:
        if size > READ_TAIL_BYTES:
            fh.seek(size - READ_TAIL_BYTES)
            fh.readline()  # drop the partial first line
        data = fh.read().decode("utf-8", "replace")
    rows = []
    for line in data.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _buy_ready_rows(root: Path | None, limit: int) -> list[dict[str, Any]]:
    """BuyReady packets from their own durable store (data/runtime/buy_ready_packets)."""
    base = (root or Path(__file__).resolve().parents[2]) / BUY_READY_RELATIVE
    try:
        files = sorted(base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    except OSError:
        return []
    out = []
    for f in files:
        try:
            packet = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(packet, dict):
            continue
        out.append({
            "schema": SCHEMA,
            "original_schema": packet.get("schema") or BUY_READY_PACKET,
            "artifact_id": f"{f.stem}@{packet.get('as_of') or packet.get('generated_at') or ''}",
            "artifact_id_basis": "store_file",
            "producer": "cio_options_fluency.build_buy_ready_packet",
            "source_as_of": packet.get("as_of") or packet.get("generated_at"),
            "persisted_at": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(),
            "evidence_class": "DURABLE_RUNTIME_ARTIFACT",
            "authority": AUTHORITY,
            "source_ref": f"buy_ready_packets/{f.name}",
            "symbol": packet.get("symbol") or f.stem,
            "decision_id": packet.get("decision_id"),
            "payload": _bounded(packet)[0],
        })
    return out


def list_operator_artifacts(
    *,
    schema: str | None = None,
    decision_id: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Newest-first operator artifacts, filtered; bounded to the store's tail."""
    limit = max(1, min(int(limit or 50), 200))
    root_p = Path(root) if root else None
    rows: list[dict[str, Any]] = []
    path = store_path(root_p)
    rows.extend(_tail_rows(path))
    rows.extend(_buy_ready_rows(root_p, 50))
    cadi_rows, cadi_status = _cadi_rows(root_p, limit)
    rows.extend(cadi_rows)

    def keep(row: dict[str, Any]) -> bool:
        if schema and row.get("original_schema") != schema:
            return False
        if decision_id and str(row.get("decision_id") or "") != decision_id:
            return False
        if symbol and str(row.get("symbol") or "").upper() != symbol.upper():
            return False
        return True

    rows = [r for r in rows if keep(r)]
    rows.sort(key=lambda r: str(r.get("persisted_at") or r.get("source_as_of") or ""), reverse=True)
    counts: dict[str, int] = {}
    for r in rows:
        counts[str(r.get("original_schema"))] = counts.get(str(r.get("original_schema")), 0) + 1
    return {
        "schema": "CIOOperatorArtifacts@v1",
        "store": "cio_operator_artifacts.jsonl",
        "store_present": path.is_file(),
        "artifacts": rows[:limit],
        "counts_by_schema": counts,
        "total_matched": len(rows),
        "authority": AUTHORITY,
        "as_of": _now(),
        "cadi_records": {"status": cadi_status, "store": "cross_asset_decisions.sqlite"},
    }


def _cadi_rows(root: Path | None, limit: int) -> tuple[list[dict[str, Any]], str]:
    """Read existing CADI records; never copy them or create a second writer.

    Explicit roots are fixture/import inspection only. Production reads require
    both source approvals and a separate activation flag; neither is inferred
    from the presence of code, a file, or a scheduler-shadow receipt.
    """
    from scripts.lib.cross_asset.decision_store import DecisionStore, STORE_RELATIVE
    from scripts.lib.cross_asset.canonical_decision import (
        ERROR_SCHEMA, SCHEMA as DECISION_SCHEMA, validate_decision, validate_error_receipt,
    )

    if root is None:
        registry_path = Path(__file__).resolve().parents[2] / "config" / "data_source_authority.json"
        try:
            domains = json.loads(registry_path.read_text())["domains"]
        except (OSError, ValueError, TypeError, KeyError):
            return [], "AUTHORITY_UNAVAILABLE"
        if not isinstance(domains, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("domain"), str) for row in domains
        ):
            return [], "AUTHORITY_UNAVAILABLE"
        required = {"cross_asset_evaluation_history", "cross_asset_decision_projection"}
        approved = {
            row["domain"] for row in domains
            if row.get("domain") in required
            and row.get("writer") == "scripts/lib/cross_asset/decision_store.py"
            and isinstance(row.get("approval"), dict)
            and all(isinstance(row["approval"].get(key), str) and row["approval"][key].strip()
                    for key in ("approved_by", "approved_on", "reference", "scope"))
        }
        if approved != required:
            return [], "SOURCE_APPROVAL_REQUIRED"
        if os.environ.get("TRADEAI_CADI_RECORDS_READ_ENABLED") != "1":
            return [], "NOT_ACTIVATED"
        from scripts.lib.canonical_store_registry import production_state_root

        root = Path(production_state_root())
    store = DecisionStore(root / STORE_RELATIVE)
    if not store.path.is_file():
        return [], "UNAVAILABLE"
    try:
        records = store.history(limit=limit)
        for row in records:
            if not isinstance(row, dict):
                return [], "STORE_READ_FAILED"
            if row.get("schema") == DECISION_SCHEMA:
                errors = validate_decision(row)
            elif row.get("schema") == ERROR_SCHEMA:
                errors = validate_error_receipt(row)
            else:
                return [], "STORE_READ_FAILED"
            if errors:
                return [], "STORE_READ_FAILED"
        # Use retained decisions as a bounded source for latest views. More
        # complete cross-asset pagination/ranking belongs to CADI-07.
        for symbol in sorted({row["identity"]["symbol"] for row in records if isinstance(row.get("identity"), dict)}):
            try:
                records.append(store.projection(symbol))
            except ValueError as exc:
                # Distinct securities sharing one ticker must not be joined.
                if str(exc) == "PROJECTION_IDENTITY_CONFLICT":
                    return [], "IDENTITY_CONFLICT"
                raise
        return [
            {
                "schema": SCHEMA,
                "original_schema": row["schema"],
                "artifact_id": row.get("evaluation_id") or f"projection:{row['symbol']}@{row.get('as_of')}",
                "artifact_id_basis": "source_evaluation",
                "producer": "cross_asset.decision_store.DecisionStore",
                "source_as_of": row.get("as_of"),
                "persisted_at": None,  # Decision as_of is not a measured append time.
                "evidence_class": "decision-shadow",
                "authority": AUTHORITY,
                "financial_action": False,
                "source_ref": f"{STORE_RELATIVE}#{row.get('evaluation_id') or row.get('symbol')}",
                "symbol": ((row.get("symbol") if isinstance(row.get("symbol"), str) else None)
                           or (row["identity"].get("symbol") if isinstance(row.get("identity"), dict) else None)),
                "decision_id": row.get("evaluation_id"),
                "payload": _bounded(row)[0],
            } for row in records
        ], "AVAILABLE"
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return [], "STORE_READ_FAILED"


__all__: Iterable[str] = [
    "SCHEMA", "record_operator_artifact", "list_operator_artifacts", "store_path",
]
