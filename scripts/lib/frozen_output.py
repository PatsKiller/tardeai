"""Frozen-output verdict: a lane that succeeds while its output never changes and its inputs do (LQ-20261107-1613).

The runtime output verdict (scripts/lib/n8n_output_verdict.py) asks "did this run produce anything?". This one asks
the question that verdict cannot see: across the last K runs, did the output *move* when the inputs moved? A
classifier that writes a fresh row every run, with the same label and confidence while the numbers underneath it
change, passes every count-based check and is still broken.

Contract (config/frozen_output_contracts.json, ``FrozenOutputContracts@v1``), one per lane:

    {"lane_id": ..., "k": 4, "source": {...}, "output_fields": [...], "input_fields": [...]}

Verdicts, over the newest ``k`` runs (oldest first in ``history``):

==================  ==========================================================================================
``OK``              the output fingerprint changed at least once across the window
``STABLE_INPUTS``   output unchanged, and so were the inputs: nothing moved, so nothing should (OK)
``FROZEN``          output unchanged across k runs while the input fingerprint took >= 2 values -> DEGRADED
``UNVERIFIABLE``    fewer than k runs in the window, or a run with no input/output fingerprint
==================  ==========================================================================================

Pure: no I/O. AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "FrozenOutputContracts@v1"
VERDICTS = ("OK", "STABLE_INPUTS", "FROZEN", "UNVERIFIABLE")
#: lane health vocabulary each verdict maps to
HEALTH = {"OK": "OK", "STABLE_INPUTS": "OK", "FROZEN": "DEGRADED", "UNVERIFIABLE": "UNVERIFIABLE"}
K_MIN, K_MAX = 3, 48
_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_PATH = re.compile(r"^[a-z_][a-z0-9_]{0,62}(\.[A-Za-z_][A-Za-z0-9_]{0,62}){0,3}$")
SOURCE_KINDS = ("pg_rows",)


def dig(doc: Any, path: str) -> Any:
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
    return cur


def _drop(doc: Any, path: str) -> Any:
    """A copy of ``doc`` without the dotted ``path`` (a per-run id inside an input blob is not an input)."""
    head, _, rest = path.partition(".")
    if not isinstance(doc, Mapping) or head not in doc:
        return doc
    out = dict(doc)
    if rest:
        out[head] = _drop(out[head], rest)
    else:
        del out[head]
    return out


def _canon(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, Mapping):
        return {str(k): _canon(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    if v is None or isinstance(v, (str, int, bool)):
        return v
    return str(v)


def fingerprint(row: Mapping[str, Any], fields: Sequence[str], exclude: Iterable[str] = ()) -> str | None:
    """sha256 over the canonical JSON of the selected dotted fields; None when every field is absent."""
    picked: dict[str, Any] = {}
    for f in fields:
        val = dig(row, f)
        for ex in exclude:
            if ex.startswith(f + "."):
                val = _drop(val, ex[len(f) + 1:])
        picked[f] = _canon(val)
    if all(v is None for v in picked.values()):
        return None
    blob = json.dumps(picked, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def evaluate(history: Sequence[Mapping[str, Any]], k: int) -> dict[str, Any]:
    """``history``: runs oldest-first, each ``{"at", "output_fp", "input_fp"}``. Judges the newest ``k``."""
    window = list(history)[-k:]
    base = {"k": k, "runs": len(window), "window_from": window[0].get("at") if window else None,
            "window_to": window[-1].get("at") if window else None}
    if len(window) < k:
        return {**base, "verdict": "UNVERIFIABLE", "reason": "insufficient_history"}
    if any(not r.get("output_fp") or not r.get("input_fp") for r in window):
        return {**base, "verdict": "UNVERIFIABLE", "reason": "fingerprint_missing"}
    outputs = {r["output_fp"] for r in window}
    inputs = {r["input_fp"] for r in window}
    detail = {**base, "distinct_outputs": len(outputs), "distinct_inputs": len(inputs)}
    if len(outputs) > 1:
        return {**detail, "verdict": "OK", "reason": "output_moved"}
    if len(inputs) == 1:
        return {**detail, "verdict": "STABLE_INPUTS", "reason": "inputs_unchanged"}
    return {**detail, "verdict": "FROZEN", "reason": "output_unchanged_while_inputs_changed"}


def validate_contract(c: Any) -> list[str]:
    tag = f"frozen_output[{c.get('lane_id') if isinstance(c, Mapping) else '?'}]"
    if not isinstance(c, Mapping):
        return [f"{tag}: must be an object"]
    errs: list[str] = []
    if not isinstance(c.get("lane_id"), str) or not c["lane_id"]:
        errs.append(f"{tag}: lane_id is required")
    k = c.get("k")
    if not (isinstance(k, int) and not isinstance(k, bool) and K_MIN <= k <= K_MAX):
        errs.append(f"{tag}: k must be an int in [{K_MIN}, {K_MAX}]")
    for key in ("output_fields", "input_fields"):
        v = c.get(key)
        if not isinstance(v, list) or not v or not all(isinstance(x, str) and _PATH.match(x) for x in v):
            errs.append(f"{tag}: {key} must be a non-empty list of dotted field paths")
    if set(c.get("output_fields") or []) & set(c.get("input_fields") or []):
        errs.append(f"{tag}: a field cannot be both output and input")
    ex = c.get("input_exclude", [])
    if not isinstance(ex, list) or not all(isinstance(x, str) and _PATH.match(x) and "." in x for x in ex):
        errs.append(f"{tag}: input_exclude must be dotted paths inside an input field")
    src = c.get("source")
    if not isinstance(src, Mapping) or src.get("kind") not in SOURCE_KINDS:
        errs.append(f"{tag}: source.kind must be one of {SOURCE_KINDS}")
    else:
        for key in ("table", "time_column"):
            if not isinstance(src.get(key), str) or not _IDENT.match(src[key]):
                errs.append(f"{tag}: source.{key} must be a lower-case SQL identifier")
        days = src.get("window_days", 14)
        if not (isinstance(days, int) and not isinstance(days, bool) and 1 <= days <= 60):
            errs.append(f"{tag}: source.window_days must be an int in [1, 60]")
        join = src.get("input_join")
        if join is not None:
            if not isinstance(join, Mapping):
                errs.append(f"{tag}: source.input_join must be an object")
            else:
                for key in ("table", "match_column", "key_column", "value_column"):
                    if not isinstance(join.get(key), str) or not _IDENT.match(join[key]):
                        errs.append(f"{tag}: source.input_join.{key} must be a lower-case SQL identifier")
                if not isinstance(join.get("match_from"), str) or not _PATH.match(join["match_from"]):
                    errs.append(f"{tag}: source.input_join.match_from must be a dotted field path")
    if not str(c.get("why") or "").strip():
        errs.append(f"{tag}: why is required (what a frozen output means for this lane)")
    return errs


def validate_document(doc: Any, known_lanes: Iterable[str] | None = None) -> list[str]:
    if not isinstance(doc, Mapping) or doc.get("schema") != SCHEMA:
        return [f"document schema must be {SCHEMA}"]
    contracts = doc.get("contracts")
    if not isinstance(contracts, list):
        return ["contracts must be a list"]
    errs: list[str] = []
    seen: set[str] = set()
    known = set(known_lanes) if known_lanes is not None else None
    for c in contracts:
        errs.extend(validate_contract(c))
        lid = c.get("lane_id") if isinstance(c, Mapping) else None
        if lid in seen:
            errs.append(f"frozen_output[{lid}]: duplicate lane_id")
        seen.add(lid)
        if known is not None and lid not in known:
            errs.append(f"frozen_output[{lid}]: lane_id is not a registry lane")
    return errs
