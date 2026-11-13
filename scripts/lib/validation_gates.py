"""Validation gates: declaration intake, check evaluation, state transitions, events (LQ-20261107-2141 / 2143).

Spec: HOME-BACKEND-SPEC-20261111 sec 2141 / 2143. Pure of I/O except through the cursor / callables handed in.

* ``parse_decl`` validates a ``ValidationGateDecl@v1`` file. A declaration can never carry SQL: ``sql_threshold`` /
  ``db_max`` / ``incident_absent`` reference a NAMED query (``config/validation_gate_queries.json``) by ``query_id``.
* ``apply_decl`` upserts a declaration keyed on ``gate_id`` + ``decl_sha256`` (the same file twice is a no-op) and
  applies a close request only after ``check_close`` passes (no self-certification, WAIVED is operator-only).
  The DB CHECKs in the migration enforce the same two rules a second time.
* ``evaluate`` runs one gate's check; ``next_state`` is the transition table; ``record_event`` writes a
  ``validation_events`` row with an idempotent ``dedupe_key``.
* ``read_model`` builds ``HomeGates@v1`` (all items, never truncated). Unknown is never 0: a failed read gives
  ``state: UNKNOWN`` with ``counts: null``; a snapshot older than ``THRESHOLD_S`` is served last-known-good as STALE.

Table shape: the LQ-2413 / 2665 superset (migrations 05/06). This writer owns ``source = 'declaration'`` rows only and
never evaluates or rewrites a board gate. ``blocks_trading`` is tri-state: absent / null = not declared = unknown,
never false. A named ``fix_ref`` makes an open gate MONITORING; a PASS (evaluated, or a vetted manual close) is
FIXED_UNPROVEN with ``proof_window_end``. Nothing here sets FIXED / ``proven_at``: proving over the window is 2413 scope.

Authority: writes validation_gates / validation_events only. No broker, order, stop or credential access.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

DECL_SCHEMA = "ValidationGateDecl@v1"
PAYLOAD_SCHEMA = "HomeGates@v1"
OPEN_SET = ("OPEN", "OVERDUE", "FAILED")
CHECK_KINDS = ("lane_fresh", "db_max", "incident_absent", "sql_threshold", "manual_evidence")
CLOSE_STATUSES = ("PASSED", "WAIVED")
OPS = {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
       "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
THRESHOLD_S = 900          # newest last_evaluated_at older than 15 min -> STALE
SYSTEM_ACTOR = "system:validation-gates-sync"
DEFAULT_PROOF_WINDOW_H = 24  # ASSUMPTION: the real window length comes from the 2149 registry (not built yet)
WRITER_LANE = "validation-gates-sync"
WRITER_RECEIPT = "data/runtime/validation-gates-sync_last.json"
_FORBIDDEN_SPEC_KEYS = {"sql", "query", "statement", "select", "where", "table", "column"}

FUTURE_SKEW_S = 360  # = the 0.1 h tolerance evaluate() allows
SOURCE = "declaration"
LABEL_TEXT = {"FIXED": "FIXED", "FIXED_UNPROVEN": "FIXED · UNPROVEN OVER TIME", "MONITORING": "MONITORING"}
_TOP_KEYS = {"schema", "gate_id", "title", "category", "lq_id", "blocks", "blocks_trading", "due_at", "opened_at",
             "owner", "declared_by", "check_kind", "check_spec", "close", "fix_ref"}
_REQ = ("gate_id", "title", "category", "blocks", "opened_at", "owner", "declared_by", "check_kind")
_CLOSE_KEYS = {"status", "closed_by", "evidence"}


class DeclError(ValueError):
    """A declaration is malformed or refused."""


def parse_ts(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("timestamp without an offset")
    return dt.astimezone(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _as_dt(v: Any) -> Optional[datetime]:
    try:
        return parse_ts(v)
    except (ValueError, TypeError):
        return None


def _scan_free_sql(spec: Any, path: str = "check_spec") -> Optional[str]:
    if isinstance(spec, Mapping):
        for k, v in spec.items():
            if str(k).lower() in _FORBIDDEN_SPEC_KEYS:
                return f"{path}.{k}: free SQL / identifiers are not allowed; use a named query_id"
            bad = _scan_free_sql(v, f"{path}.{k}")
            if bad:
                return bad
    elif isinstance(spec, list):
        for i, v in enumerate(spec):
            bad = _scan_free_sql(v, f"{path}[{i}]")
            if bad:
                return bad
    return None


def decl_sha256(doc: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_decl(doc: Any, *, queries: Optional[Mapping[str, Any]] = None) -> dict:
    """Validated, normalised declaration. Raises DeclError naming every problem found (first 10)."""
    errs: list[str] = []
    if not isinstance(doc, Mapping) or doc.get("schema") != DECL_SCHEMA:
        raise DeclError(f"schema must be {DECL_SCHEMA}")
    unknown = set(doc) - _TOP_KEYS
    if unknown:
        errs.append(f"unknown keys: {sorted(unknown)}")
    for k in _REQ:
        if not isinstance(doc.get(k), str) or not doc[k].strip():
            errs.append(f"{k} is required (string)")
    kind = doc.get("check_kind")
    if isinstance(kind, str) and kind not in CHECK_KINDS:
        errs.append(f"check_kind {kind!r} not in {CHECK_KINDS}")
    spec = doc.get("check_spec", {})
    if not isinstance(spec, Mapping):
        errs.append("check_spec must be an object")
        spec = {}
    bad = _scan_free_sql(spec)
    if bad:
        errs.append(bad)
    if kind == "lane_fresh" and not (isinstance(spec.get("lane_id"), str) and isinstance(spec.get("max_age_h"), (int, float))):
        errs.append("lane_fresh needs check_spec {lane_id, max_age_h}")
    if kind in ("db_max", "incident_absent", "sql_threshold"):
        qid = spec.get("query_id")
        if not isinstance(qid, str):
            errs.append(f"{kind} needs check_spec.query_id (a named query)")
        elif queries is not None and qid not in queries:
            errs.append(f"query_id {qid!r} is not in config/validation_gate_queries.json")
        if kind == "sql_threshold" and (spec.get("op") not in OPS or not isinstance(spec.get("value"), (int, float))):
            errs.append("sql_threshold needs check_spec {query_id, op, value}")
        if kind == "db_max" and not isinstance(spec.get("max_age_h"), (int, float)):
            errs.append("db_max needs check_spec {query_id, max_age_h}")
    for k in ("opened_at", "due_at"):
        try:
            if parse_ts(doc.get(k)) is None and k == "opened_at":
                errs.append("opened_at is required")
        except (ValueError, TypeError):
            errs.append(f"{k} is not an ISO timestamp with an offset")
    if doc.get("blocks_trading") is not None and not isinstance(doc["blocks_trading"], bool):
        errs.append("blocks_trading must be a boolean (omit it when not known: it is then 'not declared')")
    pw = spec.get("proof_window_h")
    if pw is not None and (isinstance(pw, bool) or not isinstance(pw, (int, float)) or pw <= 0):
        errs.append("check_spec.proof_window_h must be a number > 0")
    if doc.get("fix_ref") is not None and (not isinstance(doc["fix_ref"], str) or not doc["fix_ref"].strip()):
        errs.append("fix_ref must be a non-empty string (where the fix is live)")
    close = doc.get("close")
    if close is not None:
        if not isinstance(close, Mapping) or set(close) - _CLOSE_KEYS:
            errs.append("close must be an object with keys status, closed_by, evidence")
        elif close.get("status") not in CLOSE_STATUSES or not isinstance(close.get("closed_by"), str) \
                or not close["closed_by"].strip():
            errs.append(f"close needs status in {CLOSE_STATUSES} and closed_by")
    if errs:
        raise DeclError("; ".join(errs[:10]))
    out = {k: doc.get(k) for k in _TOP_KEYS if k in doc}
    out.setdefault("blocks_trading", None)  # not declared is unknown, never false
    out["check_spec"] = dict(spec)
    out["sha256"] = decl_sha256(doc)
    return out


def check_close(decl: Mapping[str, Any], close: Mapping[str, Any]) -> None:
    """Code-side twin of the DB CHECKs. Raises DeclError when the close request is refused."""
    by, status = close["closed_by"].strip(), close["status"]
    if status == "WAIVED" and by != "operator":
        raise DeclError(f"gate {decl['gate_id']}: WAIVED is operator-only (closed_by={by!r})")
    if decl["check_kind"] == "manual_evidence":
        if status != "PASSED" and status != "WAIVED":
            raise DeclError("manual_evidence closes only as PASSED or WAIVED")
        if by == decl["declared_by"]:
            raise DeclError(f"gate {decl['gate_id']}: self-certification refused (closed_by == declared_by)")
        if status == "PASSED" and not close.get("evidence"):
            raise DeclError(f"gate {decl['gate_id']}: manual_evidence PASSED needs evidence")
    elif status == "PASSED":
        raise DeclError(f"gate {decl['gate_id']}: {decl['check_kind']} gates pass only by an evaluated PASS")


# ---- DB writes -------------------------------------------------------------------------------------------------

def _j(v: Any) -> str:
    return json.dumps(v, sort_keys=True)


def _spec_obj(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) else v


def _tri(v: Any) -> Optional[bool]:
    return None if v is None else bool(v)


def proof_end_for(gate: Mapping[str, Any], at: datetime) -> datetime:
    """End of the proof window of a gate that passed at ``at``: check_spec.proof_window_h, else the default."""
    spec = _spec_obj(gate.get("check_spec")) or {}
    return at + timedelta(hours=float(spec.get("proof_window_h", DEFAULT_PROOF_WINDOW_H)))


def apply_decl(cur: Any, decl: Mapping[str, Any], *, now: datetime, decl_path: str = "") -> dict:
    """Upsert one declaration. Returns {"action": inserted|updated|noop|closed|refused, ...}. Keyed on gate_id +
    decl_sha256: the same file twice is a no-op. A declaration never changes a gate's status; only a vetted close
    request or the evaluator does."""
    cur.execute("SELECT status, decl_sha256, declared_by, check_kind, check_spec, blocks_trading, due_at, source, "
                "fix_ref, label FROM validation_gates WHERE gate_id = %s", (decl["gate_id"],))
    row = cur.fetchone()
    stamp = _iso(now)
    fix_ref = (decl.get("fix_ref") or "").strip() or None
    if row is None:
        if decl.get("close"):
            raise DeclError(f"gate {decl['gate_id']}: close request for a gate that does not exist")
        cur.execute(
            "INSERT INTO validation_gates (gate_id, title, category, lq_id, source, status, blocks, blocks_trading, "
            "due_at, opened_at, owner, declared_by, check_kind, check_spec, fix_ref, label, decl_path, decl_sha256, "
            "updated_at) VALUES (%s,%s,%s,%s,%s,'OPEN',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (decl["gate_id"], decl["title"], decl["category"], decl.get("lq_id"), SOURCE, decl["blocks"],
             _tri(decl.get("blocks_trading")), _iso(_as_dt(decl.get("due_at"))), _iso(_as_dt(decl["opened_at"])),
             decl["owner"], decl["declared_by"], decl["check_kind"], _j(decl["check_spec"]), fix_ref,
             "MONITORING" if fix_ref else None, decl_path, decl["sha256"], stamp))
        return {"action": "inserted", "gate_id": decl["gate_id"], "opened": True, "monitoring": bool(fix_ref)}
    status, old_sha, declared_by, check_kind = row[0], row[1], row[2], row[3]
    old_spec, old_blocks_trading, old_due, source, old_fix, old_label = row[4], row[5], row[6], row[7], row[8], row[9]
    if source != SOURCE:  # a board gate belongs to the board probe; a declaration file cannot touch it
        raise DeclError(f"gate {decl['gate_id']}: owned by source {source!r}; a declaration cannot change it")
    if old_sha == decl["sha256"]:
        return {"action": "noop", "gate_id": decl["gate_id"]}
    close = decl.get("close")
    if close:
        # judge the close against what the DB recorded, not what this file claims about itself
        check_close({"gate_id": decl["gate_id"], "declared_by": declared_by, "check_kind": check_kind}, close)
        if status in ("PASSED", "WAIVED"):
            return {"action": "noop", "gate_id": decl["gate_id"], "reason": "already closed"}
        passed = close["status"] == "PASSED"  # a vetted PASS is FIXED_UNPROVEN until its window ends; WAIVED is unlabelled
        end = _iso(proof_end_for({"check_spec": old_spec}, now)) if passed else None
        cur.execute(
            "UPDATE validation_gates SET status=%s, closed_at=%s, closed_by=%s, evidence=%s, label=%s, "
            "proof_window_end=%s, decl_path=%s, decl_sha256=%s, updated_at=%s WHERE gate_id=%s",
            (close["status"], stamp, close["closed_by"].strip(), _j(close.get("evidence") or []),
             "FIXED_UNPROVEN" if passed else None, end, decl_path, decl["sha256"], stamp, decl["gate_id"]))
        return {"action": "closed", "gate_id": decl["gate_id"], "status": close["status"], "from": status,
                "by": close["closed_by"].strip(), "proof_window_end": end}
    # FROZEN once a gate exists: the check, whether it blocks trading, and its deadline. Re-declaring a gate must not
    # be a way to loosen it (longer max_age_h, blocks_trading false, a later due_at) so it passes; a different check is a
    # different gate_id. Only descriptive fields change here.
    frozen = []
    if decl["check_kind"] != check_kind:
        frozen.append("check_kind")
    if _spec_obj(old_spec) != _spec_obj(decl["check_spec"]):
        frozen.append("check_spec")
    if _tri(old_blocks_trading) != _tri(decl.get("blocks_trading")):  # unknown -> yes/no is a change too
        frozen.append("blocks_trading")
    if _iso(_as_dt(old_due)) != _iso(_as_dt(decl.get("due_at"))):
        frozen.append("due_at")
    if frozen:
        raise DeclError(f"gate {decl['gate_id']}: {', '.join(frozen)} cannot change once declared; "
                        "declare a new gate_id")
    is_open = status in OPEN_SET  # a closed gate keeps the fix_ref / label it closed with
    new_fix = fix_ref if is_open else old_fix
    label = ("MONITORING" if fix_ref else None) if is_open else old_label
    cur.execute(
        "UPDATE validation_gates SET title=%s, category=%s, lq_id=%s, blocks=%s, owner=%s, fix_ref=%s, label=%s, "
        "decl_path=%s, decl_sha256=%s, updated_at=%s WHERE gate_id=%s",
        (decl["title"], decl["category"], decl.get("lq_id"), decl["blocks"], decl["owner"], new_fix, label,
         decl_path, decl["sha256"], stamp, decl["gate_id"]))
    return {"action": "updated", "gate_id": decl["gate_id"],
            "monitoring": bool(is_open and fix_ref and old_label != "MONITORING")}


# ---- evaluation + transitions ----------------------------------------------------------------------------------

def evaluate(gate: Mapping[str, Any], *, now: datetime,
             lane_ok_at: Callable[[str], Optional[datetime]],
             run_query: Callable[[str], Any]) -> tuple[str, dict]:
    """(PASS|FAIL|ERROR|NOT_EVALUABLE, detail). Never raises. A check that cannot be read is ERROR, never PASS."""
    kind = gate["check_kind"]
    spec = gate.get("check_spec") or {}
    if isinstance(spec, str):
        spec = json.loads(spec)
    try:
        if kind == "manual_evidence":
            return "NOT_EVALUABLE", {"reason": "manual evidence: closes only by a non-declarer's close request"}
        if kind == "lane_fresh":
            ok_at = lane_ok_at(spec["lane_id"])
            if ok_at is None:
                return "ERROR", {"reason": f"no receipt for lane {spec['lane_id']}"}
            age_h = (now - ok_at).total_seconds() / 3600
            if age_h < -0.1:  # a future receipt is a bad clock or bad data, never proof of freshness
                return "ERROR", {"reason": "lane receipt timestamp is in the future"}
            ok = age_h <= float(spec["max_age_h"])
            return ("PASS" if ok else "FAIL"), {"detail": f"lane {'fresh' if ok else 'stale'} {age_h:.1f} h "
                                                 f"{'<=' if ok else '>'} {spec['max_age_h']} h"}
        val = run_query(spec["query_id"])
        if val is None:
            return "ERROR", {"reason": f"query {spec['query_id']} returned no value"}
        if kind == "db_max":
            ts = _as_dt(val)
            if ts is None:
                return "ERROR", {"reason": "query value is not a timestamp"}
            age_h = (now - ts).total_seconds() / 3600
            if age_h < -0.1:  # a future timestamp is a bad clock or bad data, never proof of freshness
                return "ERROR", {"reason": "query timestamp is in the future"}
            ok = age_h <= float(spec["max_age_h"])
            return ("PASS" if ok else "FAIL"), {"detail": f"newest {age_h:.1f} h old, max {spec['max_age_h']} h"}
        num = float(val)
        if kind == "incident_absent":
            return ("PASS" if num == 0 else "FAIL"), {"detail": f"{num:g} matching incidents"}
        ok = OPS[spec["op"]](num, float(spec["value"]))
        return ("PASS" if ok else "FAIL"), {"detail": f"{num:g} {spec['op']} {spec['value']} is {ok}"}
    except Exception as exc:  # noqa: BLE001 -- an unreadable check is ERROR with the type named, never a pass
        return "ERROR", {"reason": type(exc).__name__}


def next_state(gate: Mapping[str, Any], result: str, *, now: datetime) -> Optional[tuple[str, str]]:
    """(new_status, transition) or None. PASS closes any open-set gate whose check is machine-evaluable;
    FAIL after due_at -> FAILED; any non-PASS after due_at -> OVERDUE; FAILED stays FAILED until a PASS."""
    status, kind = gate["status"], gate["check_kind"]
    if status not in OPEN_SET:
        return None
    due = _as_dt(gate.get("due_at"))
    past_due = bool(due and now > due)
    if result == "PASS" and kind != "manual_evidence":
        return "PASSED", "passed"
    if result == "FAIL" and past_due and status != "FAILED":
        return "FAILED", "failed"
    if past_due and status == "OPEN":
        return "OVERDUE", "overdue"
    return None


def event_dedupe_key(source_kind: str, source_id: str, transition: str, occurred_at: datetime) -> str:
    return f"{source_kind}:{source_id}:{transition}:{int(occurred_at.timestamp())}"


def record_event(cur: Any, gate: Mapping[str, Any], transition: str, *, occurred_at: datetime, run_id: str,
                 summary: str) -> bool:
    """Insert one gate transition into validation_events. True when a row was written, False on a duplicate key."""
    label = proof_end = None
    if transition == "passed":  # same label and window end as the gate row (proof_end_for)
        label = "FIXED_UNPROVEN"
        proof_end = _iso(proof_end_for(gate, occurred_at))
    cur.execute(
        "INSERT INTO validation_events (dedupe_key, source_kind, source_id, category, transition, label, "
        "proof_window_end, occurred_at, detected_at, summary, owner, evidence, run_id) "
        "VALUES (%s,'gate',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (dedupe_key) DO NOTHING",
        (event_dedupe_key("gate", gate["gate_id"], transition, occurred_at), gate["gate_id"], gate["category"],
         transition, label, proof_end, _iso(occurred_at), _iso(occurred_at), summary, gate.get("owner"),
         _j({"gate_id": gate["gate_id"]}), run_id))
    return cur.rowcount == 1


def record_refusal(cur: Any, raw: bytes, *, file_name: str, reason: str, occurred_at: datetime, run_id: str) -> bool:
    """A refused declaration becomes a validation_events row (source_kind 'declaration', transition 'refused'), deduped
    on the file's sha256 so one refusal shows once, not every run (LQ-2966, closes REVIEW-2963 C3). Never raises on a
    garbage file: the gate id is read from the JSON when there is one, else the file name is the source id."""
    gate_id, category, owner = None, "Declaration", None
    try:
        doc = json.loads(raw.decode("utf-8"))
        if isinstance(doc, Mapping):
            gate_id = doc.get("gate_id") if isinstance(doc.get("gate_id"), str) else None
            category = doc.get("category") if isinstance(doc.get("category"), str) and doc["category"].strip() else category
            owner = doc.get("owner") if isinstance(doc.get("owner"), str) else None
    except (ValueError, UnicodeDecodeError):
        pass
    source_id = (gate_id or file_name)[:200]
    digest = hashlib.sha256(raw).hexdigest()
    cur.execute(
        "INSERT INTO validation_events (dedupe_key, source_kind, source_id, category, transition, occurred_at, "
        "detected_at, summary, owner, evidence, run_id) "
        "VALUES (%s,'declaration',%s,%s,'refused',%s,%s,%s,%s,%s,%s) ON CONFLICT (dedupe_key) DO NOTHING",
        (f"declaration:{source_id}:refused:{digest}", source_id, category, _iso(occurred_at), _iso(occurred_at),
         f"declaration refused: {reason}"[:500], owner, _j({"file": file_name, "sha256": digest, "reason": reason[:300]}),
         run_id))
    return cur.rowcount == 1


GATE_EVAL_COLS = ("gate_id", "title", "category", "status", "due_at", "owner", "check_kind", "check_spec")
SELECT_OPEN_FOR_EVAL = ("SELECT gate_id, title, category, status, due_at, owner, check_kind, check_spec "
                        "FROM validation_gates WHERE source = 'declaration' AND status IN ('OPEN','OVERDUE','FAILED') "
                        "ORDER BY gate_id")


def evaluate_open(cur: Any, *, now: datetime, run_id: str, lane_ok_at: Callable, run_query: Callable) -> dict:
    """Evaluate every open-set gate, persist the result and any transition + its event. Returns counts."""
    cur.execute(SELECT_OPEN_FOR_EVAL)
    gates = [dict(zip(GATE_EVAL_COLS, r)) for r in cur.fetchall()]
    evaluated = transitions = errors = events = 0
    for g in gates:
        result, detail = evaluate(g, now=now, lane_ok_at=lane_ok_at, run_query=run_query)
        evaluated += 1
        errors += result == "ERROR"
        tr = next_state(g, result, now=now)
        stamp = _iso(now)
        if tr and tr[0] == "PASSED":
            cur.execute("UPDATE validation_gates SET status='PASSED', closed_at=%s, closed_by=%s, label='FIXED_UNPROVEN', "
                        "proof_window_end=%s, last_evaluated_at=%s, last_eval_result=%s, last_eval_detail=%s, "
                        "updated_at=%s WHERE gate_id=%s",
                        (stamp, SYSTEM_ACTOR, _iso(proof_end_for(g, now)), stamp, result, _j(detail), stamp,
                         g["gate_id"]))
        elif tr:
            cur.execute("UPDATE validation_gates SET status=%s, last_evaluated_at=%s, last_eval_result=%s, "
                        "last_eval_detail=%s, updated_at=%s WHERE gate_id=%s",
                        (tr[0], stamp, result, _j(detail), stamp, g["gate_id"]))
        else:
            cur.execute("UPDATE validation_gates SET last_evaluated_at=%s, last_eval_result=%s, last_eval_detail=%s, "
                        "updated_at=%s WHERE gate_id=%s", (stamp, result, _j(detail), stamp, g["gate_id"]))
        if tr:
            transitions += 1
            events += record_event(cur, g, tr[1], occurred_at=now, run_id=run_id,
                                   summary=f"{g['title']}: {tr[1]} ({detail.get('detail') or detail.get('reason')})")
    return {"evaluated": evaluated, "transitions": transitions, "errors": errors, "events": events}


# ---- read side -------------------------------------------------------------------------------------------------

READ_GATES_SQL = (
    "SELECT gate_id, title, category, source, status, blocks, blocks_trading, due_at, owner, fix_ref, label, "
    "proof_window_end, proven_at, last_eval_result, last_evaluated_at, last_eval_detail, evidence FROM validation_gates "
    "WHERE status IN ('OPEN','OVERDUE','FAILED')"
)
READ_FRESH_SQL = "SELECT MAX(last_evaluated_at) AS computed_at, COUNT(*) AS n FROM validation_gates"
_STATUS_RANK = {"OVERDUE": 0, "FAILED": 1, "OPEN": 2}
_BT_RANK = {True: 0, None: 1, False: 2}  # an undeclared blocks_trading is drawn as a risk, above a declared "no"


def _json_field(v: Any, default: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return default
    return default if v is None else v


def _sort_key(g: Mapping) -> tuple:
    due = _as_dt(g.get("due_at"))
    return (_BT_RANK[_tri(g.get("blocks_trading"))], _STATUS_RANK.get(g.get("status"), 9), due is None,
            due or datetime.max.replace(tzinfo=timezone.utc), str(g.get("gate_id")))


def read_model(rows: Optional[Iterable[Mapping]], fresh: Optional[Mapping], *, now: datetime,
               receipt_ok_at: Optional[datetime] = None) -> dict:
    """HomeGates@v1. ``rows`` / ``fresh`` None = the read failed -> UNKNOWN, counts None ("not available")."""
    writer = {"lane_id": WRITER_LANE, "last_ok_at": _iso(receipt_ok_at), "receipt": WRITER_RECEIPT}
    base = {"schema": PAYLOAD_SCHEMA, "served_at": _iso(now), "writer": writer}
    unknown = {**base, "state": "UNKNOWN", "snapshot": None, "counts": None, "items": [], "text": "not available"}
    if rows is None or fresh is None:
        return {**unknown, "reason": "gate store unreadable"}
    computed = _as_dt(fresh.get("computed_at"))
    if int(fresh.get("n") or 0) == 0:
        # An empty table is not zero evidence: only a fresh writer receipt proves the lane looked and found none.
        if receipt_ok_at is None:
            return {**unknown, "reason": "no snapshot written"}
        computed = receipt_ok_at
    elif computed is None:
        return {**unknown, "reason": "gates exist but none has ever been evaluated"}
    items_src = sorted((dict(r) for r in rows), key=_sort_key)
    age = (now - computed).total_seconds()
    if age < -FUTURE_SKEW_S:  # a snapshot from the future is a clock fault: unknown beats wrong, never "fresh"
        return {**unknown, "reason": "snapshot timestamp is in the future (clock skew)"}
    age = max(0.0, age)
    stale = age > THRESHOLD_S
    items = []
    for g in items_src:
        ev = _json_field(g.get("evidence"), [])
        detail = _json_field(g.get("last_eval_detail"), {}) or {}
        label = g.get("label")
        items.append({"gate_id": g["gate_id"], "title": g["title"], "category": g["category"], "status": g["status"],
                      "source": g.get("source") or SOURCE, "blocks": g["blocks"],
                      "blocks_trading": _tri(g.get("blocks_trading")),  # None = not declared: unknown, never "no"
                      "due_at": _iso(_as_dt(g.get("due_at"))), "owner": g["owner"], "fix_ref": g.get("fix_ref"),
                      "label": label, "label_text": LABEL_TEXT.get(label),
                      "proof_window_end": _iso(_as_dt(g.get("proof_window_end"))),
                      "proven_at": _iso(_as_dt(g.get("proven_at"))),
                      "last_eval": {"result": g.get("last_eval_result"),
                                    "at": _iso(_as_dt(g.get("last_evaluated_at"))),
                                    "detail": detail.get("detail") or detail.get("reason")},
                      "evidence": ev})
    counts = {"open": len(items), "blocks_trading": sum(1 for g in items if g["blocks_trading"] is True),
              "blocks_trading_unknown": sum(1 for g in items if g["blocks_trading"] is None),
              "overdue": sum(1 for g in items if g["status"] == "OVERDUE")}
    return {**base, "state": "STALE" if stale else "OK",
            "reason": f"snapshot {age:.0f}s old > {THRESHOLD_S}s" if stale else None,
            "snapshot": {"computed_at": _iso(computed), "age_s": round(age), "threshold_s": THRESHOLD_S},
            "counts": counts, "items": items}
