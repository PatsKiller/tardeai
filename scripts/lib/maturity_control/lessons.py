"""Unified learning view for Command Center (never calls RATIFIED_CONTEXT production policy)."""
from __future__ import annotations

import copy
import json
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.lib.kb_lesson_counters import apply_counter_events
from scripts.lib.maturity_control.schema import map_kb_status_to_lesson_state
from scripts.lib.maturity_control.store import load_json_map, resolve_root


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            import json
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def _latest_by_id_stream(path: Path, key: str = "id") -> list[dict[str, Any]]:
    """Latest row per id, parsing one line at a time.

    advisory_kb_lessons.jsonl is ~270 MB of ~75 KB rows; materialising every
    row before de-duplicating peaked the API at ~900 MB per request.
    """
    if not path.is_file():
        return []
    by: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                lid = str(obj.get(key) or obj.get("lesson_id") or "")
                if lid:
                    by[lid] = obj
    return list(by.values())


def _count_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def _stat_key(*paths: Path) -> tuple:
    out = []
    for path in paths:
        try:
            st = path.stat()
            out.append((str(path), st.st_size, st.st_mtime_ns))
        except OSError:
            out.append((str(path), None, None))
    return tuple(out)


# collect_lessons is called by the maturity API, the CIO investment product, the
# research prompt context and the autonomy watchdog. Its inputs change about
# once a day, so the result is shared until any input changes.
_LESSONS_CACHE: dict[str, Any] = {"key": None, "value": None}
_LESSONS_LOCK = threading.Lock()


def _latest_by_id(rows: list[dict[str, Any]], key: str = "id") -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        lid = str(r.get(key) or r.get("lesson_id") or "")
        if lid:
            by[lid] = r
    return list(by.values())


def collect_lessons(*, root: Path | str | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    runtime = base / "data" / "runtime"
    cio = base / "data" / "cio"
    overlays = load_json_map("lessons", root=base)
    key = (
        _stat_key(
            runtime / "advisory_kb_lessons.jsonl",
            runtime / "advisory_kb_lesson_candidates.jsonl",
            runtime / "advisory_kb_lesson_applications.jsonl",
            cio / "cio_reflection_candidates.json",
        ),
        json.dumps(overlays, sort_keys=True, default=str),
    )
    with _LESSONS_LOCK:
        if _LESSONS_CACHE["key"] != key:
            _LESSONS_CACHE.update({"key": key, "value": _collect_lessons(base, runtime, cio, overlays)})
        # Callers get their own copy; the cached value is never handed out.
        return copy.deepcopy(_LESSONS_CACHE["value"])


def _collect_lessons(base: Path, runtime: Path, cio: Path, overlays: dict[str, Any]) -> dict[str, Any]:
    # 2026-10-09: counters = latest content row + counter events after it (the
    # writer no longer re-appends whole rows per application/hit).
    kb = apply_counter_events(
        _latest_by_id_stream(runtime / "advisory_kb_lessons.jsonl"),
        runtime / "advisory_kb_lesson_applications.jsonl",
    )
    cands = _latest_by_id_stream(runtime / "advisory_kb_lesson_candidates.jsonl")
    application_events = _count_rows(runtime / "advisory_kb_lesson_applications.jsonl")
    by_id: dict[str, dict[str, Any]] = {}
    for row in cands + kb:
        lid = str(row.get("id") or "")
        if not lid:
            continue
        by_id[lid] = row

    # reflection proposals that are candidate lessons
    snap_path = cio / "cio_reflection_candidates.json"
    reflection_props: list[dict[str, Any]] = []
    if snap_path.is_file():
        try:
            snap = json.loads(snap_path.read_text(encoding="utf-8"))
        except Exception:
            snap = {}
        for p in snap.get("proposals") or []:
            if not isinstance(p, dict):
                continue
            if p.get("kind") == "candidate_lesson":
                reflection_props.append(p)
                cid = str(p.get("case_id") or p.get("decision_id") or "")
                if cid and cid not in by_id:
                    by_id[f"refl_{cid}"] = {
                        "id": f"refl_{cid}",
                        "status": "candidate",
                        "title": (p.get("text") or "")[:120],
                        "body": p.get("text") or "",
                        "source": "cio_nightly_reflection",
                        "evidence_refs": [cid],
                        "symbols": [],
                        "applications": 0,
                        "hits": 0,
                        "hit_rate": None,
                        "citations": 0,
                    }

    lessons = []
    for lid, row in by_id.items():
        overlay = (overlays.get(lid) or {}).get("state")
        state = map_kb_status_to_lesson_state(row.get("status"), overlay)
        lessons.append({
            "lesson_id": lid,
            "lifecycle": state,
            "source": row.get("source") or "advisory_kb",
            "title": row.get("title") or "",
            "body": row.get("body") or "",
            "evidence_refs": row.get("evidence_refs") or [],
            "symbols": row.get("symbols") or [],
            "sectors": row.get("sectors") or [],
            "verdict_classes": row.get("verdict_types") or row.get("verdict_classes") or [],
            "applications": int(row.get("applications") or 0),
            "hits": int(row.get("hits") or 0),
            "hit_rate": row.get("hit_rate"),
            "citations": int(row.get("citations") or 0),
            "created_at": row.get("ts") or row.get("created_at"),
            "ratified_at": row.get("ratified_at"),
            "ratified_by": row.get("ratified_by"),
            "retired_at": row.get("retired_at"),
            "retire_reason": row.get("retire_reason"),
            "not_production_policy": state == "RATIFIED_CONTEXT",
        })

    counts = Counter(l["lifecycle"] for l in lessons)
    return {
        "authority": "READ_ONLY_ADVISORY",
        "auto_promotion_to_trading": False,
        "application_events": application_events,
        "reflection_candidate_lessons": len(reflection_props),
        "counts": {k: counts.get(k, 0) for k in (
            "CANDIDATE", "RATIFIED_CONTEXT", "SHADOW_INFLUENCE",
            "ADVISORY_ACTIVE", "RESTRICTED", "RETIRED",
        )},
        "lessons": sorted(lessons, key=lambda r: str(r.get("created_at") or ""), reverse=True),
    }


def collect_cases(*, root: Path | str | None = None) -> dict[str, Any]:
    base = resolve_root(root)
    from scripts.lib import cio_production_case as cs
    # materialize from shared default unless tests patch DEFAULT_PATH
    cases_path = base / "data" / "cio" / "cio_production_cases.jsonl"
    if cases_path.is_file():
        cases = cs.materialize_cases(path=cases_path)
    else:
        cases = []
    by_status: Counter[str] = Counter(str(c.get("status") or "").upper() for c in cases)
    return {
        "authority": "READ_ONLY_ADVISORY",
        "cases_seen": len(cases),
        "by_status": dict(by_status),
        "cases": [
            {
                "case_id": c.get("case_id"),
                "decision_id": c.get("decision_id"),
                "status": c.get("status"),
                "operator_disposition": c.get("operator_disposition"),
                "note": c.get("note"),
                "outcome": c.get("outcome"),
                "darwin": c.get("darwin"),
            }
            for c in cases[:400]
        ],
    }
