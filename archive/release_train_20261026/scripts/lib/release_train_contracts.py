"""Release Train v2 contracts: the six versioned schemas and their validators (Phase 1, 2026-10-21).

    TrainSubmission@v1   an agent asks that a published PR head be considered for a train
    TrainCandidate@v1    a frozen train: base SHA, full PR heads in dependency order, policy/classifier versions
    TrainEvidence@v1     one piece of qualifying evidence bound to an exact candidate SHA
    ReleaseControl@v1    a stop / pause / resume / revoke / hold / cancel command and its state
    TrainEvent@v1        one row of the append-only ``release_queue_events`` store
    TrainOutcome@v1      the terminal result of one train window

The JSON Schemas (draft 2020-12) live in ``config/schemas/release_train/*.v1.schema.json``, following the
``docs/implementation/n8n-maturity/schemas`` convention: ``title`` and a ``schema`` const name the contract, and a
pure Python validator in ``scripts/lib`` applies the schema plus program rules a schema cannot express.

The required CI runner has no ``jsonschema``, so this module carries a small validator for the keyword subset the
six files use (``SUPPORTED_KEYWORDS``). The tests pin that no schema file uses a keyword outside that subset, and,
where ``jsonschema`` is installed, that both validators agree on every fixture.

Producers: none in Phase 1 (the queue store's writers validate with ``validate``; the controller arrives in Phase 3).
Consumers: ``scripts/lib/release_train_queue.py`` (store read and write paths) and, through it,
``scripts/lib/release_train_view.py`` behind ``GET /api/v2/coordination/release-train*``.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. Pure: no I/O beyond reading the schema files.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "config" / "schemas" / "release_train"

TRAIN_SUBMISSION = "TrainSubmission@v1"
TRAIN_CANDIDATE = "TrainCandidate@v1"
TRAIN_EVIDENCE = "TrainEvidence@v1"
RELEASE_CONTROL = "ReleaseControl@v1"
TRAIN_EVENT = "TrainEvent@v1"
TRAIN_OUTCOME = "TrainOutcome@v1"

SCHEMA_FILES: dict[str, str] = {
    TRAIN_SUBMISSION: "train_submission.v1.schema.json",
    TRAIN_CANDIDATE: "train_candidate.v1.schema.json",
    TRAIN_EVIDENCE: "train_evidence.v1.schema.json",
    RELEASE_CONTROL: "release_control.v1.schema.json",
    TRAIN_EVENT: "train_event.v1.schema.json",
    TRAIN_OUTCOME: "train_outcome.v1.schema.json",
}

RISK_CLASSES = ("eligible", "needs_operator", "held", "blocked")  # least -> most restrictive
QUEUE_STATES = (
    "submitted", "classified", "ready", "held", "needs_operator", "blocked", "selected", "integrating",
    "qualified", "waiting_window", "merged", "promoting", "released", "observing", "rolled_back",
    "rollback_failed", "superseded", "quarantined", "cancelled",
)
OUTCOMES = ("NO_OP", "FAILED_PRE_MERGE", "MERGED_NOT_LIVE", "RELEASED_VERIFIED", "RELEASED_OBSERVING",
            "ROLLED_BACK", "ROLLBACK_FAILED", "STOPPED", "CANCELLED")
TRAIN_ID_RE = re.compile(r"^rt-[0-9]{8}-[0-9]{4}-[a-z0-9]{4,12}$")

SUPPORTED_KEYWORDS = frozenset({
    "$schema", "$id", "$defs", "$ref", "title", "description", "type", "const", "enum", "required", "properties",
    "additionalProperties", "items", "pattern", "minimum", "maximum", "minLength", "maxLength", "minItems",
    "maxItems", "uniqueItems", "format",
})

_TYPES = {
    "object": lambda v: isinstance(v, Mapping),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict:
    """The JSON Schema document for ``name`` (for example ``"TrainEvent@v1"``). Raises KeyError for an unknown name."""
    return json.loads((SCHEMA_DIR / SCHEMA_FILES[name]).read_text(encoding="utf-8"))


def parse_ts(value: Any) -> Optional[datetime]:
    """An ISO-8601 timestamp WITH an offset, else None (a naive time is not a time in a multi-zone system)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None


def _resolve(ref: str, root: Mapping[str, Any]) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError(f"only local $ref supported: {ref}")
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _check(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any], where: str, errs: list[str]) -> None:
    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), root, where, errs)
        return
    if "const" in schema and value != schema["const"]:
        errs.append(f"{where}: must be {schema['const']!r}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{where}: {value!r} not in {schema['enum']}")
        return
    types = schema.get("type")
    if types is not None:
        tl = [types] if isinstance(types, str) else list(types)
        if not any(_TYPES[t](value) for t in tl):
            errs.append(f"{where}: expected {'/'.join(tl)}")
            return
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{where}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{where}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{where}: does not match {schema['pattern']}")
        if schema.get("format") == "date-time" and parse_ts(value) is None:
            errs.append(f"{where}: not an ISO-8601 date-time with offset")
    if _TYPES["number"](value):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{where}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{where}: above {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{where}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = [json.dumps(v, sort_keys=True) for v in value]
            if len(set(seen)) != len(seen):
                errs.append(f"{where}: items not unique")
        if "items" in schema:
            for i, v in enumerate(value):
                _check(v, schema["items"], root, f"{where}[{i}]", errs)
    if isinstance(value, Mapping):
        props = schema.get("properties") or {}
        for k in schema.get("required") or ():
            if k not in value:
                errs.append(f"{where}: missing {k}")
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                _check(v, props[k], root, f"{where}.{k}", errs)
            elif extra is False:
                errs.append(f"{where}: unknown key {k}")
            elif isinstance(extra, Mapping):
                _check(v, extra, root, f"{where}.{k}", errs)


def schema_errors(name: str, doc: Any) -> list[str]:
    """JSON-Schema-only defects of ``doc`` against contract ``name``; [] when valid."""
    schema = load_schema(name)
    errs: list[str] = []
    _check(doc, schema, schema, "$", errs)
    return errs


# ── program rules (what a JSON Schema cannot say) ──────────────────────────────────────────────────────────────


def _rules_submission(d: Mapping[str, Any]) -> list[str]:
    errs = []
    want = f"rts-{d['pr_number']}-{d['head_sha'][:12]}"
    if d["submission_id"] != want:
        errs.append(f"submission_id must be {want}")
    if d["pr_number"] in (d.get("depends_on") or []):
        errs.append("a PR may not depend on itself")
    return errs


def _rules_candidate(d: Mapping[str, Any]) -> list[str]:
    errs = []
    members = d["members"]
    nums = [m["pr_number"] for m in members]
    if len(set(nums)) != len(nums):
        errs.append("members: duplicate pr_number")
    orders = sorted(m["order"] for m in members)
    if orders != list(range(1, len(members) + 1)):
        errs.append("members: order must be exactly 1..n")
    for m in members:
        if m["risk_class"] == "needs_operator" and not m.get("ride_approval_ref"):
            errs.append(f"member #{m['pr_number']}: needs_operator rides only with ride_approval_ref")
    order_of = {m["pr_number"]: m["order"] for m in members}
    graph: dict[int, list[int]] = {}
    for key, deps in (d.get("dependency_graph") or {}).items():
        if not str(key).isdigit() or int(key) not in order_of:
            errs.append(f"dependency_graph: {key} is not a member")
            continue
        for dep in deps:
            if dep not in order_of:
                errs.append(f"dependency_graph: #{key} depends on non-member #{dep}")
            elif order_of[dep] >= order_of[int(key)]:
                errs.append(f"dependency_graph: #{key} must come after its dependency #{dep}")
        graph[int(key)] = [x for x in deps if x in order_of]
    # an order-respecting graph is acyclic; the explicit check names a self-loop
    for k, deps in graph.items():
        if k in deps:
            errs.append(f"dependency_graph: #{k} depends on itself")
    return errs


def _rules_evidence(d: Mapping[str, Any]) -> list[str]:
    errs = []
    if d["kind"] == "ci_run" and (not d.get("workflow") or not d.get("run_id")):
        errs.append("ci_run evidence needs workflow and run_id")
    if d["kind"] == "artifact" and not d.get("digest"):
        errs.append("artifact evidence needs a sha256 digest")
    return errs


def _rules_control(d: Mapping[str, Any]) -> list[str]:
    errs = []
    if d["command"] in ("resume", "revoke") and not (d.get("reason") or "").strip():
        errs.append(f"{d['command']} needs a reason")
    st = d["state"]
    if st == "stopped" and d["command"] != "stop":
        errs.append("only a stop command reaches state 'stopped'")
    need = {"acknowledged": ["acknowledged_at"], "settling": ["acknowledged_at", "settled_at"],
            "stopped": ["acknowledged_at", "stopped_at"]}.get(st, [])
    for k in need:
        if not d.get(k):
            errs.append(f"state {st} needs {k}")
    if st == "refused" and not d.get("refusal_reason"):
        errs.append("state refused needs refusal_reason")
    chain = [parse_ts(d.get(k)) for k in ("requested_at", "acknowledged_at", "settled_at", "stopped_at")]
    present = [t for t in chain if t is not None]
    if present != sorted(present):
        errs.append("timestamps out of order (requested <= acknowledged <= settled <= stopped)")
    return errs


_PR_STATE_EVENTS = frozenset(QUEUE_STATES)


def _rules_event(d: Mapping[str, Any]) -> list[str]:
    errs = []
    kind, sid = d["subject_kind"], d["subject_id"]
    if kind == "pr":
        if not d.get("pr_number"):
            errs.append("a pr subject needs pr_number")
        elif sid != f"pr:{d['pr_number']}":
            errs.append(f"subject_id must be pr:{d['pr_number']}")
    elif kind == "train":
        if not d.get("train_id"):
            errs.append("a train subject needs train_id")
        elif sid != f"train:{d['train_id']}":
            errs.append(f"subject_id must be train:{d['train_id']}")
    elif kind == "control" and not sid.startswith("control:rtc-"):
        errs.append("a control subject_id is control:<control_id>")
    et = d["event_type"]
    if kind == "pr" and et in _PR_STATE_EVENTS and d.get("state_after") != et:
        errs.append(f"state_after must equal event_type {et} for a PR state event")
    if et == "classified" and d["payload"].get("risk_class") not in RISK_CLASSES:
        errs.append("classified payload needs risk_class in " + "/".join(RISK_CLASSES))
    nested = {"outcome_recorded": TRAIN_OUTCOME, "evidence_recorded": TRAIN_EVIDENCE}
    if et.startswith("control_"):
        nested[et] = RELEASE_CONTROL
    if et in nested:
        errs.extend(f"payload: {e}" for e in validate_as(nested[et], d["payload"]))
    return errs


def _rules_outcome(d: Mapping[str, Any]) -> list[str]:
    errs = []
    o = d["outcome"]
    if o == "NO_OP" and d["members"]:
        errs.append("NO_OP has no members")
    if o in ("RELEASED_VERIFIED", "RELEASED_OBSERVING"):
        for k in ("main_sha", "served_sha"):
            if not d.get(k):
                errs.append(f"{o} needs {k}")
    if o == "MERGED_NOT_LIVE" and not d.get("main_sha"):
        errs.append("MERGED_NOT_LIVE needs main_sha")
    if o in ("ROLLED_BACK", "ROLLBACK_FAILED") and not d.get("rollback_target"):
        errs.append(f"{o} needs rollback_target")
    s, f = parse_ts(d["started_at"]), parse_ts(d["finished_at"])
    if s and f and f < s:
        errs.append("finished_at before started_at")
    fa = d.get("failure_attribution") or {}
    for k, prs in fa.items():
        stray = sorted(set(prs) - set(d["members"]))
        if stray:
            errs.append(f"failure_attribution.{k}: non-members {stray}")
    return errs


_RULES = {
    TRAIN_SUBMISSION: _rules_submission,
    TRAIN_CANDIDATE: _rules_candidate,
    TRAIN_EVIDENCE: _rules_evidence,
    RELEASE_CONTROL: _rules_control,
    TRAIN_EVENT: _rules_event,
    TRAIN_OUTCOME: _rules_outcome,
}


def validate_as(name: str, doc: Any) -> list[str]:
    """Every defect of ``doc`` as contract ``name`` (schema, then program rules); [] when valid. Pure."""
    if name not in SCHEMA_FILES:
        return [f"unknown contract {name!r}"]
    errs = schema_errors(name, doc)
    if errs:
        return errs  # program rules assume a schema-valid document
    return _RULES[name](doc)


def validate(doc: Any) -> list[str]:
    """Dispatch on ``doc["schema"]``; [] when valid."""
    if not isinstance(doc, Mapping):
        return ["document is not an object"]
    name = doc.get("schema")
    if name not in SCHEMA_FILES:
        return [f"unknown or missing schema {name!r}"]
    return validate_as(name, doc)


def evidence_qualifies(ev: Mapping[str, Any], candidate_sha: str) -> bool:
    """True only for valid evidence on exactly ``candidate_sha`` whose conclusion is exactly ``success``.
    Skipped, neutral and pending are not passes (enhanced design section 10: 'skipped or neutral checks counted as
    passes' is a named failure)."""
    return (not validate_as(TRAIN_EVIDENCE, ev) and ev["candidate_sha"] == candidate_sha
            and ev["conclusion"] == "success")


def more_restrictive(a: str, b: str) -> str:
    """The more restrictive of two risk classes (the design's tie-break: the more restrictive rule wins)."""
    return a if RISK_CLASSES.index(a) >= RISK_CLASSES.index(b) else b
