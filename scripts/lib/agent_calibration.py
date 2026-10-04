"""AgentCalibration@v1 — stated confidence vs realized hit rate, per agent.

Operator-approved 2026-10-03 (Policy Review P4). Reads settled outcome
observations and joins each to the decision that produced it (AgentRunTrace
decision_id -> agent, surface, confidence). Only observations that were
actually scored count: a directional recommendation against its raw move, or
a recorded ExpectationPolicy@v1 expectation against its benchmark. Below the
sample floor an agent shows INSUFFICIENT_SAMPLE, never a rate. An observation
whose decision has no trace stays "unattributed" — it is never guessed onto an
agent. Read-only advisory (MBI=0).
"""
from __future__ import annotations

import json
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "AgentCalibration@v1"
UNATTRIBUTED = "unattributed"
_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"key": None, "value": None}
_TRACE_INDEX: dict[str, Any] = {"key": None, "index": None}

OBSERVATIONS_REL = Path("data") / "cio" / "outcome_observations.jsonl"
TRACES_REL = Path("data") / "cio" / "agent_run_traces.jsonl"


def _stat(path: Path) -> tuple[str, Optional[int], Optional[int]]:
    try:
        st = path.stat()
        return (str(path), st.st_size, st.st_mtime_ns)
    except OSError:
        return (str(path), None, None)


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row
    except OSError:
        return


def _trace_index(path: Path) -> dict[str, dict[str, Any]]:
    """decision_id -> {agent, surface, confidence}; reparsed only when the file changes."""
    key = _stat(path)
    if _TRACE_INDEX["key"] == key and _TRACE_INDEX["index"] is not None:
        return _TRACE_INDEX["index"]
    index: dict[str, dict[str, Any]] = {}
    for t in _iter_jsonl(path):
        d = t.get("decision") if isinstance(t.get("decision"), dict) else {}
        did = str(d.get("decision_id") or "").strip()
        if not did:
            continue
        index[did] = {
            "agent": str(t.get("agent") or "").strip() or UNATTRIBUTED,
            "surface": str(d.get("surface") or t.get("role") or "").strip() or "unknown",
            "confidence": d.get("confidence"),
        }
    _TRACE_INDEX["key"], _TRACE_INDEX["index"] = key, index
    return index


def confidence_bucket(value: Any) -> tuple[str, Optional[float]]:
    """(bucket label, probability in [0,1] when numeric)."""
    if value is None or value == "":
        return "not_stated", None
    if isinstance(value, str):
        label = value.strip().upper()
        try:
            value = float(label)
        except ValueError:
            return (label if label in {"HIGH", "MEDIUM", "LOW"} else "not_stated"), None
    try:
        p = float(value)
    except (TypeError, ValueError):
        return "not_stated", None
    if p != p or p < 0:
        return "not_stated", None
    if p > 1.0:
        if p > 100.0:
            return "not_stated", None
        p = p / 100.0
    lo = min(int(p * 5), 4) * 20
    return f"{lo}-{lo + 20}%", p


def scored_verdict(obs: dict[str, Any]) -> tuple[Optional[bool], Optional[str]]:
    """(hit, basis) for one observation, or (None, None) when it was not scored."""
    from scripts.lib.outcome_to_lesson import _direction, expectation_verdict

    realized = obs.get("realized_state") if isinstance(obs.get("realized_state"), dict) else {}
    rec = str(realized.get("recommendation") or (obs.get("original_decision_state") or {}).get("recommendation") or "")
    change = realized.get("change_pct")
    if _direction(0.0, rec) is not None:
        v = _direction(change if isinstance(change, (int, float)) else None, rec)
        return (None, None) if v is None else (v == "CONFIRMED", "DIRECTIONAL")
    v = expectation_verdict(realized)
    return (None, None) if v is None else (v == "CONFIRMED", "EXPECTATION")


def build_calibration(
    observations: Iterable[dict[str, Any]],
    traces: dict[str, dict[str, Any]],
    *,
    min_sample: int = 20,
) -> dict[str, Any]:
    agents: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    unscored = 0
    for obs in observations:
        oid = str(obs.get("outcome_id") or "")
        if oid and oid in seen:
            continue
        hit, basis = scored_verdict(obs)
        if hit is None:
            unscored += 1
            continue
        if oid:
            seen.add(oid)
        meta = traces.get(str(obs.get("decision_id") or "")) or {}
        agent = meta.get("agent") or UNATTRIBUTED
        a = agents.setdefault(agent, {"n": 0, "hits": 0, "brier_sum": 0.0, "brier_n": 0,
                                      "buckets": defaultdict(lambda: [0, 0]), "basis": defaultdict(int),
                                      "surfaces": defaultdict(int)})
        a["n"] += 1
        a["hits"] += int(hit)
        a["basis"][basis] += 1
        a["surfaces"][meta.get("surface") or "unknown"] += 1
        label, p = confidence_bucket(meta.get("confidence"))
        a["buckets"][label][0] += 1
        a["buckets"][label][1] += int(hit)
        if p is not None:
            a["brier_sum"] += (p - (1.0 if hit else 0.0)) ** 2
            a["brier_n"] += 1

    rows = []
    for agent, a in sorted(agents.items(), key=lambda kv: (-kv[1]["n"], kv[0])):
        enough = a["n"] >= min_sample
        rows.append({
            "agent": agent,
            "scored_outcomes": a["n"],
            "status": "MEASURED" if enough else "INSUFFICIENT_SAMPLE",
            "hit_rate": round(a["hits"] / a["n"], 4) if enough else None,
            "brier": round(a["brier_sum"] / a["brier_n"], 4) if enough and a["brier_n"] >= min_sample else None,
            "by_confidence": [
                {"bucket": b, "n": n, "hit_rate": round(h / n, 4) if n >= min_sample else None}
                for b, (n, h) in sorted(a["buckets"].items())
            ],
            "by_basis": dict(a["basis"]),
            "by_surface": dict(a["surfaces"]),
        })
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "min_sample": min_sample,
        "agents": rows,
        "unscored_observations": unscored,
        "note": ("Only scored outcomes count: directional calls against their move, other calls only against "
                 "a recorded ExpectationPolicy@v1 expectation. Observations without a traced decision are "
                 "'unattributed', never guessed."),
    }


def get_agent_calibration(root: Path | str) -> dict[str, Any]:
    """Cached on both stores' (size, mtime_ns)."""
    from scripts.lib.expectation_policy import load_policy

    root_p = Path(root)
    obs_path, trace_path = root_p / OBSERVATIONS_REL, root_p / TRACES_REL
    key = (_stat(obs_path), _stat(trace_path))
    with _LOCK:
        if _CACHE["key"] == key and _CACHE["value"] is not None:
            return json.loads(json.dumps(_CACHE["value"]))
        min_sample = int((load_policy() or {}).get("calibration_min_sample") or 20)
        value = build_calibration(_iter_jsonl(obs_path), _trace_index(trace_path), min_sample=min_sample)
        value["sources"] = {
            "observations": {"path": str(OBSERVATIONS_REL), "available": key[0][1] is not None},
            "traces": {"path": str(TRACES_REL), "available": key[1][1] is not None},
        }
        _CACHE["key"], _CACHE["value"] = key, value
        return json.loads(json.dumps(value))
