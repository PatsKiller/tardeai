"""MaturityScorecard@v1 — GET-only, file-backed dimensions.

A dimension with no fresh metric (missing file, or last_measured_at older
than FRESHNESS_TTL_DAYS=7) is status=UNMEASURED and score=null — never a
stale number.

READ_ONLY_ADVISORY. financial_action=false. No mutations. No new datastore.
Does not set MEMORY_BEHAVIOR_INFLUENCE (reports the env value; default 0).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "MaturityScorecard@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
STATUS_MEASURED = "MEASURED"
STATUS_UNMEASURED = "UNMEASURED"
FRESHNESS_TTL_DAYS = 7  # documented TTL; older artifacts are UNMEASURED
PAYLOAD_SCHEMA = "DecisionPayload@v1"
REQUIRED_DECISION_SURFACES = frozenset({
    "reentry", "material_scan", "watch", "holdings", "advisory", "opportunity",
})

SKIP_CODES_UNCHANGED = frozenset({"SKIP_UNCHANGED", "UNCHANGED"})
SKIP_CODES_EXECUTED = frozenset({"RESEARCH_EXECUTED", "EXECUTED"})
SKIP_CODES_TRIGGERED = frozenset({"RESEARCH_TRIGGERED", "TRIGGERED"})
SKIP_CODES_FRESH = frozenset({"SKIP_FRESH", "FRESH"})
METERED_LANES = frozenset({
    "deepseek", "flash", "deepseek-flash", "deepseek-v4-flash",
    "claude", "metered", "anthropic",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_root(root: Path | str | None = None) -> Path:
    if root:
        return Path(root)
    for env in ("TRADEAI_ROOT", "MATURITY_CONTROL_ROOT"):
        v = os.environ.get(env)
        if v:
            return Path(v)
    return Path(__file__).resolve().parents[2]


def _file_mtime(path: Path) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _is_fresh(last: Optional[datetime], now: datetime) -> bool:
    if last is None:
        return False
    return last >= now - timedelta(days=FRESHNESS_TTL_DAYS)


def _unmeasured(*, metric_path: str, reason: str, last: Optional[datetime] = None) -> dict[str, Any]:
    return {
        "score": None,
        "status": STATUS_UNMEASURED,
        "inputs": {"reason": reason, "ttl_days": FRESHNESS_TTL_DAYS},
        "last_measured_at": _iso(last),
        "metric_path": metric_path,
    }


def _measured(
    score: float | int | None,
    *,
    inputs: dict[str, Any],
    metric_path: str,
    last: Optional[datetime],
) -> dict[str, Any]:
    return {
        "score": score,
        "status": STATUS_MEASURED,
        "inputs": inputs,
        "last_measured_at": _iso(last),
        "metric_path": metric_path,
    }


def _load_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _row_code(row: dict[str, Any]) -> str:
    for k in ("code", "decision", "skip_code", "action", "result"):
        v = str(row.get(k) or "").strip().upper()
        if v:
            return v
    return ""


def _row_ts(row: dict[str, Any]) -> Optional[datetime]:
    for k in (
        "at", "ts", "as_of", "created_at", "timestamp", "when",
        "prediction_timestamp", "outcome_timestamp", "evaluated_at", "frozen_at",
    ):
        dt = _parse_dt(row.get(k))
        if dt is not None:
            return dt
    return None


def _is_metered(row: dict[str, Any]) -> bool:
    if row.get("metered") is True:
        return True
    lane = str(row.get("lane") or row.get("provider") or row.get("model_lane") or "").strip().lower()
    return lane in METERED_LANES


def _is_material(row: dict[str, Any], code: str) -> bool:
    if row.get("material") is True or row.get("material_change") is True:
        return True
    return code in SKIP_CODES_EXECUTED or code in SKIP_CODES_TRIGGERED


def _research_skip_dimension(root: Path, now: datetime) -> dict[str, Any]:
    rel = "data/cio/research_skip_ledger.jsonl"
    path = root / rel
    if not path.is_file():
        return _unmeasured(metric_path=rel, reason="missing")
    rows = _load_jsonl(path)
    stamps = [t for t in (_row_ts(r) for r in rows) if t is not None]
    last = max(stamps) if stamps else _file_mtime(path)
    if not rows or not _is_fresh(last, now):
        return _unmeasured(
            metric_path=rel,
            reason="empty" if not rows else "stale",
            last=last,
        )
    n = len(rows)
    skip_n = sum(1 for r in rows if _row_code(r) in SKIP_CODES_UNCHANGED)
    exec_n = sum(1 for r in rows if _row_code(r) in SKIP_CODES_EXECUTED)
    trig_n = sum(1 for r in rows if _row_code(r) in SKIP_CODES_TRIGGERED)
    fresh_n = sum(1 for r in rows if _row_code(r) in SKIP_CODES_FRESH)
    material_n = sum(1 for r in rows if _is_material(r, _row_code(r)))
    metered_n = sum(
        1 for r in rows
        if _is_metered(r) and _row_code(r) in (SKIP_CODES_EXECUTED | SKIP_CODES_TRIGGERED)
    )
    skip_rate = round(skip_n / n, 6)
    exec_rate = round(exec_n / n, 6)
    metered_per = round(metered_n / material_n, 6) if material_n else None
    return _measured(
        skip_rate,
        inputs={
            "n": n,
            "skip_unchanged_n": skip_n,
            "research_executed_n": exec_n,
            "research_triggered_n": trig_n,
            "skip_fresh_n": fresh_n,
            "skip_unchanged_rate": skip_rate,
            "research_executed_rate": exec_rate,
            "material_change_n": material_n,
            "metered_executed_n": metered_n,
            "metered_calls_per_material_change": metered_per,
        },
        metric_path=rel,
        last=last,
    )


def _holdings_universe_dimension(root: Path, now: datetime) -> dict[str, Any]:
    rel = "data/cio/holdings_universe_latest.json"
    path = root / rel
    data = _load_json(path)
    if data is None:
        return _unmeasured(metric_path=rel, reason="missing")
    last = _parse_dt(data.get("as_of")) or _file_mtime(path)
    n = data.get("held_equity_ticker_n")
    try:
        n_int = int(n) if n is not None else None
    except (TypeError, ValueError):
        n_int = None
    if n_int is None or not _is_fresh(last, now):
        return _unmeasured(
            metric_path=rel,
            reason="missing_field" if n_int is None else "stale",
            last=last,
        )
    return _measured(
        n_int,
        inputs={
            "held_equity_ticker_n": n_int,
            "schema": data.get("schema"),
        },
        metric_path=rel,
        last=last,
    )


def _held_coverage_dimension(root: Path, now: datetime) -> dict[str, Any]:
    rel = "data/cio/held_thesis_coverage_latest.json"
    path = root / rel
    data = _load_json(path)
    if data is None:
        return _unmeasured(metric_path=rel, reason="missing")
    last = _parse_dt(data.get("as_of")) or _file_mtime(path)
    coverage = data.get("coverage_pct")
    if coverage is None:
        coverage = data.get("held_current_pct")
    fresh_pct = data.get("fresh_pct")
    try:
        cov_f = float(coverage) if coverage is not None else None
        if cov_f is not None and cov_f != cov_f:
            cov_f = None
    except (TypeError, ValueError):
        cov_f = None
    try:
        fresh_f = float(fresh_pct) if fresh_pct is not None else None
        if fresh_f is not None and fresh_f != fresh_f:
            fresh_f = None
    except (TypeError, ValueError):
        fresh_f = None
    # File absent until R3 → UNMEASURED. File present without coverage fields → UNMEASURED.
    # fresh_pct may stay null until R3 adds it; coverage_pct/held_current_pct still MEASURED.
    if cov_f is None or not _is_fresh(last, now):
        return _unmeasured(
            metric_path=rel,
            reason="missing_field" if cov_f is None else "stale",
            last=last,
        )
    return _measured(
        round(cov_f, 4),
        inputs={
            "coverage_pct": round(cov_f, 4),
            "fresh_pct": None if fresh_f is None else round(fresh_f, 4),
            "held_count": data.get("held_count"),
            "current_count": data.get("current_count"),
            "schema": data.get("schema"),
        },
        metric_path=rel,
        last=last,
    )


def _decision_payload_dimension(root: Path, now: datetime) -> dict[str, Any]:
    rel = "data/cio/agent_run_traces.jsonl"
    path = root / rel
    if not path.is_file():
        return _unmeasured(metric_path=rel, reason="missing")
    rows = _load_jsonl(path)
    v1_n = 0
    surfaces: set[str] = set()
    stamps: list[datetime] = []
    for r in rows:
        for k in ("ended_at", "started_at", "as_of"):
            dt = _parse_dt(r.get(k))
            if dt is not None:
                stamps.append(dt)
                break
        dec = r.get("decision")
        if isinstance(dec, dict) and dec.get("schema") == PAYLOAD_SCHEMA:
            v1_n += 1
            surface = str(dec.get("surface") or "").strip().lower()
            if surface:
                surfaces.add(surface)
            dt = _parse_dt(dec.get("as_of"))
            if dt is not None:
                stamps.append(dt)
    last = max(stamps) if stamps else _file_mtime(path)
    if not _is_fresh(last, now):
        return _unmeasured(metric_path=rel, reason="stale", last=last)
    covered = sorted(REQUIRED_DECISION_SURFACES & surfaces)
    missing = sorted(REQUIRED_DECISION_SURFACES - surfaces)
    coverage = round(len(covered) / len(REQUIRED_DECISION_SURFACES), 6)
    return _measured(
        v1_n,
        inputs={
            "decision_payload_n": v1_n,
            "trace_rows": len(rows),
            "required_surfaces": sorted(REQUIRED_DECISION_SURFACES),
            "covered_surfaces": covered,
            "missing_surfaces": missing,
            "surface_coverage": coverage,
            "schema": PAYLOAD_SCHEMA,
        },
        metric_path=rel,
        last=last,
    )


def _decision_payload_coverage_dimension(root: Path, now: datetime) -> dict[str, Any]:
    legacy = _decision_payload_dimension(root, now)
    if legacy["status"] != STATUS_MEASURED:
        return legacy
    inputs = dict(legacy["inputs"])
    return _measured(
        inputs["surface_coverage"],
        inputs=inputs,
        metric_path=legacy["metric_path"],
        last=_parse_dt(legacy.get("last_measured_at")),
    )


def _thesis_freshness_dimension(root: Path, now: datetime) -> dict[str, Any]:
    coverage = _held_coverage_dimension(root, now)
    if coverage["status"] != STATUS_MEASURED:
        return coverage
    fresh = coverage["inputs"].get("fresh_pct")
    if fresh is None:
        return _unmeasured(
            metric_path=coverage["metric_path"],
            reason="fresh_pct_missing",
            last=_parse_dt(coverage.get("last_measured_at")),
        )
    return _measured(
        fresh,
        inputs=dict(coverage["inputs"]),
        metric_path=coverage["metric_path"],
        last=_parse_dt(coverage.get("last_measured_at")),
    )


def _research_utilization_dimension(root: Path, now: datetime) -> dict[str, Any]:
    rel = "data/cio/research_thesis_deltas.jsonl"
    path = root / rel
    rows = _load_jsonl(path)
    if not path.is_file() or not rows:
        return _unmeasured(metric_path=rel, reason="missing" if not path.is_file() else "empty")
    last = max((t for t in (_row_ts(r) for r in rows) if t), default=_file_mtime(path))
    if not _is_fresh(last, now):
        return _unmeasured(metric_path=rel, reason="stale", last=last)
    classified = [r for r in rows if r.get("schema") == "ResearchThesisDelta@v1" and r.get("classification")]
    linked = [r for r in classified if r.get("research_id") and r.get("prompt_context_hash")]
    material = [r for r in classified if r.get("thesis_publish_eligible")]
    score = round(len(linked) / len(rows), 6)
    return _measured(score, inputs={
        "delta_rows": len(rows),
        "classified_rows": len(classified),
        "research_linked_rows": len(linked),
        "publish_eligible_rows": len(material),
        "utilization_rate": score,
    }, metric_path=rel, last=last)


def _source_provenance_dimension(root: Path, now: datetime) -> dict[str, Any]:
    rel = "data/cio/research_thesis_deltas.jsonl"
    path = root / rel
    rows = _load_jsonl(path)
    if not path.is_file() or not rows:
        return _unmeasured(metric_path=rel, reason="missing" if not path.is_file() else "empty")
    last = max((t for t in (_row_ts(r) for r in rows) if t), default=_file_mtime(path))
    if not _is_fresh(last, now):
        return _unmeasured(metric_path=rel, reason="stale", last=last)
    complete = [r for r in rows if all((
        r.get("research_id"), r.get("provider"), r.get("model"),
        r.get("prompt_context_hash"), r.get("source_refs"), r.get("evidence_as_of"),
    ))]
    score = round(len(complete) / len(rows), 6)
    return _measured(score, inputs={
        "delta_rows": len(rows),
        "complete_provenance_rows": len(complete),
        "provenance_coverage": score,
        "required_fields": [
            "research_id", "provider", "model", "prompt_context_hash", "source_refs", "evidence_as_of",
        ],
    }, metric_path=rel, last=last)


def _feedback_dimension(root: Path, now: datetime) -> dict[str, Any]:
    rel = "data/cio/operator_ticker_feedback.jsonl"
    path = root / rel
    rows = _load_jsonl(path)
    if not path.is_file() or not rows:
        return _unmeasured(metric_path=rel, reason="missing" if not path.is_file() else "empty")
    last = max((t for t in (_row_ts(r) for r in rows) if t), default=_file_mtime(path))
    if not _is_fresh(last, now):
        return _unmeasured(metric_path=rel, reason="stale", last=last)
    active = [r for r in rows if str(r.get("status") or "ACTIVE").upper() == "ACTIVE"]
    retro = [r for r in rows if str(r.get("status") or "").upper() == "RETRO_LABELED"]
    linked = [r for r in active if r.get("linkage_complete") is True]
    score = round(len(linked) / len(active), 6) if active else None
    if score is None:
        return _unmeasured(metric_path=rel, reason="no_active_feedback", last=last)
    return _measured(score, inputs={
        "active_rows": len(active), "retro_rows": len(retro),
        "linked_active_rows": len(linked), "active_linkage_rate": score,
        "retro_excluded_from_promotion_metrics": True,
    }, metric_path=rel, last=last)


def _outcome_dimension(root: Path, now: datetime) -> dict[str, Any]:
    rel = "data/cio/advisory_outcomes_v1.jsonl"
    path = root / rel
    rows = _load_jsonl(path)
    if not path.is_file() or not rows:
        return _unmeasured(metric_path=rel, reason="missing" if not path.is_file() else "empty")
    last = max((t for t in (_row_ts(r) for r in rows) if t), default=_file_mtime(path))
    if not _is_fresh(last, now):
        return _unmeasured(metric_path=rel, reason="stale", last=last)
    frozen_ids = {str(r.get("record_id")) for r in rows if r.get("status") == "FROZEN" and r.get("record_id")}
    evaluated_ids = {str(r.get("record_id")) for r in rows if r.get("status") == "EVALUATED" and r.get("record_id")}
    benchmarked = [r for r in rows if r.get("status") == "EVALUATED" and r.get("benchmark_relative_return") is not None]
    score = round(len(evaluated_ids) / len(frozen_ids), 6) if frozen_ids else None
    if score is None:
        return _unmeasured(metric_path=rel, reason="no_frozen_predictions", last=last)
    return _measured(score, inputs={
        "predictions_frozen": len(frozen_ids), "outcomes_evaluated": len(evaluated_ids),
        "benchmarked_rows": len(benchmarked), "outcome_coverage": score,
    }, metric_path=rel, last=last)


def _notification_dimension(root: Path, now: datetime) -> dict[str, Any]:
    rel = "data/cio/cio_notification_metrics.jsonl"
    path = root / rel
    rows = _load_jsonl(path)
    if not path.is_file() or not rows:
        return _unmeasured(metric_path=rel, reason="missing" if not path.is_file() else "empty")
    last = max((t for t in (_row_ts(r) for r in rows) if t), default=_file_mtime(path))
    if not _is_fresh(last, now):
        return _unmeasured(metric_path=rel, reason="stale", last=last)
    immediate = sum(int(r.get("immediate_notifications") or 0) for r in rows)
    digest = sum(int(r.get("digest_notifications") or 0) for r in rows)
    suppressed = sum(
        int(r.get("suppressed_unchanged") or 0) + int(r.get("suppressed_post_reject") or 0)
        for r in rows
    )
    duplicates = sum(int(r.get("duplicate_notifications") or r.get("duplicates") or 0) for r in rows)
    logical = immediate + digest + suppressed
    score = round(1.0 - (duplicates / logical), 6) if logical else None
    if score is None:
        return _unmeasured(metric_path=rel, reason="no_notification_decisions", last=last)
    return _measured(max(0.0, score), inputs={
        "immediate": immediate, "digest": digest, "suppressed": suppressed,
        "duplicates": duplicates, "logical_notifications": logical,
        "signal_noise_score": max(0.0, score),
    }, metric_path=rel, last=last)


def _artifact_dimension(
    root: Path,
    now: datetime,
    *,
    rel: str,
    score_field: str,
    required_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    path = root / rel
    data = _load_json(path)
    if data is None:
        return _unmeasured(metric_path=rel, reason="missing")
    last = _parse_dt(data.get("as_of")) or _file_mtime(path)
    if not _is_fresh(last, now):
        return _unmeasured(metric_path=rel, reason="stale", last=last)
    if score_field not in data or any(field not in data for field in required_fields):
        return _unmeasured(metric_path=rel, reason="missing_field", last=last)
    try:
        score = float(data[score_field])
    except (TypeError, ValueError):
        return _unmeasured(metric_path=rel, reason="invalid_score", last=last)
    return _measured(round(score, 6), inputs=data, metric_path=rel, last=last)


def _memory_influence_dimension(now: datetime) -> dict[str, Any]:
    raw = os.environ.get("MEMORY_BEHAVIOR_INFLUENCE", "0")
    try:
        val = int(str(raw).strip() or "0")
    except (TypeError, ValueError):
        val = 0
    return _measured(
        val,
        inputs={
            "MEMORY_BEHAVIOR_INFLUENCE": val,
            "note": "reported only; this endpoint does not set the env",
        },
        metric_path="env:MEMORY_BEHAVIOR_INFLUENCE",
        last=now,
    )


def compute_scorecard(
    *,
    root: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Pure compute. No file writes. No provider calls."""
    root_p = resolve_root(root)
    now_dt = now or _now()
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    dimensions = {
        "research_skip": _research_skip_dimension(root_p, now_dt),
        "research_acquisition": _research_skip_dimension(root_p, now_dt),
        "research_utilization": _research_utilization_dimension(root_p, now_dt),
        "holdings_universe": _holdings_universe_dimension(root_p, now_dt),
        "held_thesis_coverage": _held_coverage_dimension(root_p, now_dt),
        "thesis_freshness": _thesis_freshness_dimension(root_p, now_dt),
        "decision_payload": _decision_payload_dimension(root_p, now_dt),
        "decision_payload_coverage": _decision_payload_coverage_dimension(root_p, now_dt),
        "feedback_coverage": _feedback_dimension(root_p, now_dt),
        "outcome_coverage": _outcome_dimension(root_p, now_dt),
        "source_provenance": _source_provenance_dimension(root_p, now_dt),
        "notification_signal_noise": _notification_dimension(root_p, now_dt),
        "rag_freshness": _artifact_dimension(
            root_p, now_dt,
            rel="data/cio/rag_freshness_latest.json",
            score_field="freshness_score",
            required_fields=("total_embeddings",),
        ),
        "pin_integrity": _artifact_dimension(
            root_p, now_dt,
            rel="data/cio/pin_integrity_latest.json",
            score_field="integrity_score",
            required_fields=("pin_match", "process_fresh"),
        ),
        "gpu_policy_compliance": _artifact_dimension(
            root_p, now_dt,
            rel="data/cio/gpu_policy_latest.json",
            score_field="compliance_score",
            required_fields=("gpu_mode", "source_violation_count", "installed_generative_count"),
        ),
        "tree_root_integrity": _artifact_dimension(
            root_p, now_dt,
            rel="data/cio/ops_tree_pin_audit_latest.json",
            score_field="integrity_score",
            required_fields=("tradeai_n", "drift_n"),
        ),
        "memory_influence": _memory_influence_dimension(now_dt),
    }
    return {
        "ok": True,
        "authority": AUTHORITY,
        "financial_action": False,
        "mutation": False,
        "service_control": False,
        "provider_call": False,
        "auto_promotion_to_trading": False,
        "schema": SCHEMA,
        "as_of": _iso(now_dt),
        "ttl_days": FRESHNESS_TTL_DAYS,
        "dimensions": dimensions,
    }
