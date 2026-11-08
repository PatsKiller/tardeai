"""Structured ``error_class`` on a lane's run receipt (Fable n8n design audit item #11, LQ-20261107-992).

The audit (``inbox/claude-lead/FABLE-N8N-DESIGN-AUDIT-LQ-984.md``, Q4 and Q6 row #11) measured 19,483 diagnosis
events in one week, ``failure_kind: unknown`` on 19,036 of them (97.7%). The deterministic tier classified the SIEM
row's error TEXT, so a lane that exited non-zero without a traceback carried no class at all, and an 800-char tail
cut the useful frame out of the ones that had one. The receipt is the one artifact every terminal run has, so the
class is decided there, once, from evidence the receipt already holds:

1. the class the LANE declared in its own ``LaneRunReceipt.error_class`` (written through
   ``lib.lane_last_receipt.write_lane_receipt``) — the lane is the only party that knows why it failed;
2. else the executor's deterministic classification of state / exit code / reason / tails. The text rules are the
   ONE existing taxonomy (``n8n_self_heal.failure_kind``): ``code_error:<Exc>`` | auth | rate_limit | server |
   timeout | network | client. Receipt-only classes cover what text cannot say: lock_contention, refused,
   environment, killed, nonzero_exit, empty_output, output_unverifiable.

``unknown`` is reachable only when a RUN_FAILED receipt names neither an exit code, a reason nor any text. It is
recorded, never silently folded into a real class, and never invented for a run that did something.

A lane-declared value outside the vocabulary is NOT promoted to ``error_class``: it is kept, bounded, in
``error_class_declared`` so it stays auditable while the aggregates keep one vocabulary.

Consumers: ``scripts/n8n_run_executor.py`` stamps the field on every terminal receipt; the diagnoser
(``scripts/n8n_failure_diagnosis.py``) reads it before its text fallback; ``scripts/lib/scheduler_operations.py``
keeps it in the receipt view the jobs page serves.

Pure: no I/O, no network, no model. MBI_BEHAVIOR = 0 — classification only, nothing here sizes, orders, stops,
sends or touches a broker.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from scripts.lib.n8n_self_heal import failure_kind

SCHEMA = "N8nErrorClass@v1"
FIELD = "error_class"
SOURCE_FIELD = "error_class_source"
#: A lane declaration that is not in the vocabulary; bounded so a lane cannot grow the receipt.
DECLARED_FIELD = "error_class_declared"
DECLARED_MAX_CHARS = 80

LANE = "lane"
EXECUTOR = "executor"

#: Classes the deterministic executor can reach without any lane text.
LOCK_CONTENTION = "lock_contention"
REFUSED = "refused"
ENVIRONMENT = "environment"
KILLED = "killed"
NONZERO_EXIT = "nonzero_exit"
EMPTY_OUTPUT = "empty_output"
OUTPUT_UNVERIFIABLE = "output_unverifiable"
UNKNOWN = "unknown"
RECEIPT_CLASSES = frozenset({LOCK_CONTENTION, REFUSED, ENVIRONMENT, KILLED, NONZERO_EXIT, EMPTY_OUTPUT,
                             OUTPUT_UNVERIFIABLE, UNKNOWN})
#: Classes the text tier produces (n8n_self_heal's vocabulary), accepted from a lane declaration too.
TEXT_CLASSES = frozenset({"auth", "rate_limit", "server", "timeout", "network", "client"})
CODE_ERROR_PREFIX = "code_error:"
_SAFE_CLASS = re.compile(r"^[a-z][a-z0-9_]{0,40}(?::[A-Za-z_][A-Za-z0-9_.]{0,60})?$")
_SAFE_EXCEPTION = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,60}$")


def normalise_declared(value: Any) -> Optional[str]:
    """The lane's declared class when it is in the vocabulary, else None. Never raises."""
    if value is None:
        return None
    token = str(value).strip()
    if not token or len(token) > DECLARED_MAX_CHARS or not _SAFE_CLASS.match(token):
        return None
    if token.startswith(CODE_ERROR_PREFIX):
        return token if _SAFE_EXCEPTION.match(token[len(CODE_ERROR_PREFIX):]) else None
    return token if token in TEXT_CLASSES or token in RECEIPT_CLASSES else None


def is_valid(value: Any) -> bool:
    return normalise_declared(value) is not None


def _exit_code(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify(
    *,
    state: Any,
    reason: Any = None,
    exit_code: Any = None,
    stdout_tail: Any = None,
    stderr_tail: Any = None,
    timed_out: Any = False,
    output_verdict: Any = None,
    lane_class: Any = None,
) -> tuple[Optional[str], Optional[str]]:
    """``(error_class, source)`` for one terminal receipt; ``(None, None)`` for a clean RUN_DONE.

    A lane-declared class wins (source ``lane``). Everything else is derived in this order from evidence that
    cannot disagree with itself: the state, a RUN_FAILED reason that already names the class
    (``empty_output``/``output_unverifiable``), a spawn failure, then the shared text taxonomy, then the exit code.
    """
    declared = normalise_declared(lane_class)
    if declared:
        return declared, LANE
    st = str(state or "").upper()
    verdict = output_verdict.get("verdict") if isinstance(output_verdict, Mapping) else None
    if st == "RUN_DONE":
        if verdict == "empty_violation":
            return EMPTY_OUTPUT, EXECUTOR
        if verdict == "unverifiable":
            return OUTPUT_UNVERIFIABLE, EXECUTOR
        return None, None
    if st == "RUN_SKIPPED_LOCK":
        return LOCK_CONTENTION, EXECUTOR
    if st == "RUN_REFUSED":
        return REFUSED, EXECUTOR
    if timed_out or st == "RUN_TIMEOUT":
        return "timeout", EXECUTOR
    reason_s = str(reason or "")
    if reason_s in (EMPTY_OUTPUT, OUTPUT_UNVERIFIABLE):
        return reason_s, EXECUTOR
    if reason_s.startswith("spawn:"):
        return ENVIRONMENT, EXECUTOR
    text = " ".join(str(x) for x in (reason_s, stdout_tail or "", stderr_tail or "") if x)
    kind = failure_kind(text)
    if kind != UNKNOWN:
        return kind, EXECUTOR
    code = _exit_code(exit_code)
    if code is not None and code < 0:
        return KILLED, EXECUTOR
    if code is not None and code != 0:
        return NONZERO_EXIT, EXECUTOR
    return UNKNOWN, EXECUTOR


def stamp(receipt: dict[str, Any], *, lane_class: Any = None) -> dict[str, Any]:
    """Write ``error_class`` / ``error_class_source`` (and a rejected declaration) on a receipt in place.

    Idempotent: re-stamping after the output verdict replaces the executor's first guess with the lane's declared
    class, or with ``empty_output`` when the verdict turned a RUN_DONE into a failure.
    """
    if lane_class not in (None, "") and normalise_declared(lane_class) is None:
        receipt[DECLARED_FIELD] = str(lane_class)[:DECLARED_MAX_CHARS]
    else:
        receipt.pop(DECLARED_FIELD, None)
    klass, source = classify(
        state=receipt.get("state"),
        reason=receipt.get("reason"),
        exit_code=receipt.get("exit_code"),
        stdout_tail=receipt.get("stdout_tail"),
        stderr_tail=receipt.get("stderr_tail"),
        timed_out=receipt.get("timed_out"),
        output_verdict=receipt.get("output_verdict"),
        lane_class=lane_class,
    )
    if klass is None:
        receipt.pop(FIELD, None)
        receipt.pop(SOURCE_FIELD, None)
    else:
        receipt[FIELD] = klass
        receipt[SOURCE_FIELD] = source
    return receipt


def from_receipt(row: Any) -> Optional[str]:
    """``error_class`` off a ledger ``runs`` row (its ``receipt_json``), or None when absent/unreadable/not a class."""
    if not isinstance(row, Mapping):
        return None
    import json

    try:
        rec = json.loads(row.get("receipt_json") or "") or {}
    except (TypeError, ValueError):
        return None
    if not isinstance(rec, Mapping):
        return None
    return normalise_declared(rec.get(FIELD))


def resolve(err: Any, row: Any, *, event_type: Any = None) -> tuple[str, str]:
    """``(failure_class, source)`` for one SIEM occurrence: the receipt's ``error_class`` FIRST (the executor
    decided it from the failed run's own evidence), else the text rules. Source is ``receipt`` or ``text``."""
    classed = from_receipt(row)
    if classed:
        return classed, "receipt"
    return failure_kind(err, event_type=event_type), "text"


def declared_from_lane_receipt(state_root: Any, lane_id: str, run_id: str) -> Any:
    """The ``error_class`` the lane wrote for THIS attempt: the immutable attempt receipt first, then the mutable
    ``<lane>_last.json`` only when its ``run_id`` is this run's (a concurrent cron run's receipt is not evidence)."""
    try:
        from scripts.lib.lane_last_receipt import attempt_receipt_path, receipt_path
    except ImportError:  # scripts/ on sys.path, repo root not
        from lib.lane_last_receipt import attempt_receipt_path, receipt_path  # type: ignore[no-redef] -- same module through its scripts/-relative name when only scripts/ is on sys.path
    import json
    from pathlib import Path

    docs = []
    try:
        docs.append(json.loads(attempt_receipt_path(lane_id, run_id, Path(state_root)).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    for doc in docs:
        if isinstance(doc, Mapping):
            return doc.get(FIELD)
    try:
        last = json.loads(receipt_path(lane_id, Path(state_root)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(last, Mapping) and str(last.get("run_id") or "") == str(run_id):
        return last.get(FIELD)
    return None
