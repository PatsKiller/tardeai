"""Append-only record of the capital-plan position decisions the operator saw.

Capital-plan decision ids (cio_decision_semantics.make_decision_id) hash symbol,
stance, delta and why_now. They are recomputed on every plan build and were
never persisted, so an id the operator opened stopped resolving as soon as its
text changed, and nothing written later could join to it. This store keeps one
row per decision id, written the first time the id is seen.

Writer of an authoritative store: registered in config/data_source_authority.json
(domain capital_plan_decisions), operator-approved 2026-10-03.

The write runs on the plan request path, so it is best-effort and bounded: an
in-process id index keyed on the file's (size, mtime_ns) means a repeat build
parses nothing, only unseen ids are appended, and any error is swallowed.
"""
from __future__ import annotations

import fcntl
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "CIOCapitalPlanDecision@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
STORE_RELATIVE = Path("data") / "cio" / "cio_capital_plan_decisions.jsonl"
PRODUCER = "api_v2._cio_capital_plan"

_FIELDS = (
    "symbol", "account", "cio_stance", "stance_code", "action_label", "recommended_delta_usd",
    "why_now", "decision_input_digest", "decision_evidence_digest", "decision_policy_version",
    "decision_generated_at", "generated_at",
)

_INDEX: dict[str, tuple[tuple[int, int], dict[str, dict[str, Any]]]] = {}
_LOCK = threading.Lock()


def store_path(path: Path | str | None = None) -> Path:
    if path:
        return Path(path)
    configured = (os.environ.get("CIO_CAPITAL_PLAN_DECISIONS_JSONL") or "").strip()
    if configured:
        return Path(configured)
    from scripts.lib.canonical_store_registry import production_state_root

    return Path(production_state_root()) / STORE_RELATIVE


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stat_key(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _rows_by_id(path: Path) -> dict[str, dict[str, Any]]:
    """id -> first stored row, parsed once per file version."""
    key = _stat_key(path)
    if key is None:
        return {}
    hit = _INDEX.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            did = row.get("decision_id") if isinstance(row, dict) else None
            if did and did not in rows:
                rows[str(did)] = row
    _INDEX[str(path)] = (key, rows)
    return rows


# Desk-thesis posture keys that build_position_decisions consumes to size each
# decision (cio_capital_plan.build_capital_plan: max_single_name_pct,
# concentration_fire_pct). cash_band_min_pct shapes the plan, not a decision row.
_SIZING_POSTURE_KEYS = ("max_single_name_weight_pct", "concentration_fire_pct")


def framework_fields(desk_thesis: dict[str, Any] | None, posture: dict[str, Any] | None) -> dict[str, Any]:
    """The framework that sized this build's decisions, or {} when none applied.

    Only when the desk thesis actually supplied a sizing parameter is it named:
    absent those keys the builder used policy defaults, and naming the thesis
    would claim an influence it did not have. Scope is stated: the desk thesis is
    portfolio-level, shared by every decision in the build.
    """
    desk = desk_thesis if isinstance(desk_thesis, dict) else {}
    applied = {k: (posture or {}).get(k) for k in _SIZING_POSTURE_KEYS if (posture or {}).get(k) is not None}
    version = desk.get("thesis_version") or (
        f"{desk.get('thesis_id')}@v{desk.get('version')}" if desk.get("thesis_id") and desk.get("version") else None
    )
    if not applied or not version:
        return {}
    return {
        "framework_refs": [f"cio_thesis:{version}"],
        "framework_scope": "portfolio (desk thesis risk posture)",
        "framework_parameters": applied,
    }


def _row(decision: dict[str, Any], *, producer: str, recorded_at: str) -> dict[str, Any]:
    did = str(decision["decision_id"])
    row: dict[str, Any] = {
        "schema": SCHEMA,
        "decision_id": did,
        "recorded_at": recorded_at,
        "source_ref": f"cio_capital_plan_decisions:{did}",
        "producer": producer,
        "authority": AUTHORITY,
        "memory_behavior_influence": 0,
        "financial_action": False,
    }
    for key in _FIELDS:
        if decision.get(key) is not None:
            row[key] = decision[key]
    # Same mapping the live catalog uses (api_v3_cio.catalog_from_position_decisions).
    action = decision.get("action") or decision.get("stance") or decision.get("stance_code")
    if action:
        row["action"] = action
    if decision.get("decision_policy_version"):
        # The versioned sizing method that computed this decision.
        row["methodology_ref"] = decision["decision_policy_version"]
    return row


def _rationale(row: dict[str, Any]) -> dict[str, Any] | None:
    """DecisionRationale@v1 from the plan's own stated fields (why_now, stance, policy)."""
    try:
        from scripts.lib.decision_rationale import rationale_for_capital_plan_row
        return rationale_for_capital_plan_row(row)
    except Exception:
        return None


def record_position_decisions(
    decisions: Iterable[dict[str, Any]] | None,
    *,
    path: Path | str | None = None,
    producer: str = PRODUCER,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append each not-yet-stored decision once. Never raises.

    ``extra`` is merged into every new row (e.g. the framework refs that governed
    this build); it never overrides a decision field.
    """
    try:
        target = store_path(path)
        fresh = [d for d in (decisions or []) if isinstance(d, dict) and str(d.get("decision_id") or "").strip()]
        if not fresh:
            return {"written": 0, "path": str(target)}
        with _LOCK:
            seen = _rows_by_id(target)
            todo = [d for d in fresh if str(d["decision_id"]) not in seen]
            if not todo:
                return {"written": 0, "path": str(target)}
            target.parent.mkdir(parents=True, exist_ok=True)
            recorded_at = _now()
            with target.open("a", encoding="utf-8") as fh:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                try:
                    # Another process may have appended since our index was built.
                    _INDEX.pop(str(target), None)
                    seen = _rows_by_id(target) if target.stat().st_size else {}
                    written = 0
                    for d in todo:
                        did = str(d["decision_id"])
                        if did in seen:
                            continue
                        row = {**(extra or {}), **_row(d, producer=producer, recorded_at=recorded_at)}
                        rationale = _rationale(row)
                        if rationale:
                            row["rationale"] = rationale
                        fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
                        seen[did] = row
                        written += 1
                    fh.flush()
                    os.fsync(fh.fileno())
                finally:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            _INDEX.pop(str(target), None)
            return {"written": written, "path": str(target)}
    except Exception as exc:  # the plan build must never fail on its audit record
        return {"written": 0, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def load_decision(decision_id: str, *, path: Path | str | None = None) -> dict[str, Any] | None:
    """The stored row for one decision id, or None (missing/unreadable store)."""
    did = str(decision_id or "").strip()
    if not did:
        return None
    try:
        with _LOCK:
            row = _rows_by_id(store_path(path)).get(did)
        return dict(row) if row else None
    except Exception:
        return None
