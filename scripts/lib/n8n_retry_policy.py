"""Retry policies, run verdicts and the dead-letter/breaker outcome (n8n maturity B5.4, design 02 §3.4, F8/F9).

``config/n8n_retry_policies.json`` (N8nRetryPolicies@v1, schema
docs/implementation/n8n-maturity/schemas/retry-policy.schema.json) names the policies a registry lane picks with
``dispatch.retry_policy``. This module loads and validates that file, maps a finished run to a verdict, and
(``finalize_outcome``) writes the verdict, the dead letter and the breaker through ``LedgerRunStore``.

Program rules enforced on top of the JSON schema (``validate_policies``):

- ``len(backoff_s) == max_attempts - 1``;
- a policy permitted for class ``send`` or ``learn`` has ``max_attempts == 1`` (a retry could double-send or
  double-write);
- a policy permitted for class ``llm`` has terminal_reason_patterns that match both ``COST_CAP`` and ``PEAK_SKIP``
  (case-insensitive sample strings, not pattern equality);
- ``terminal_exit_codes`` / ``terminal_reason_patterns`` always win over the retryable lists (``verdict``).

Retries are never run here or in n8n: ``coordination/due`` (B5.3) mints the next attempt key.

Contract for B5.3 ``compute_due`` (read-only consumer of what this module writes):

- ``runs.verdict`` of the latest attempt of a slot: ``retryable`` with ``attempt < max_attempts`` ⇒ RETRY_WAIT
  until ``next_attempt_at(policy, attempt, finished_at)``, then RETRY_DUE with ``attempt + 1``.
- A ``dead_letters`` row for the slot key with ``released_at`` NULL ⇒ DEAD_LETTER (not emitted).
- A RELEASED dead letter (``released_at`` set) ⇒ due re-arms that slot as RETRY_DUE with
  ``attempt = attempts + 1`` and reason ``"dlq_release"``, ONLY while the slot is inside ``catchup_min`` AND
  ``dead_letter_rearmable(row) == (True, "")`` (never send/learn, never a single-attempt policy, never an unknown
  class/policy); outside the window the release only clears the breaker. The store also refuses such releases.
- Due must use ``class_verdict``/``effective_max_attempts`` (not the raw policy) when deciding RETRY_DUE, and a
  missing/unknown ``dispatch.retry_policy`` resolves to ``UNRESOLVED_POLICY`` (never retries).
- Breaker open iff the ``breakers`` row has ``opened_at`` and (``released_at`` is NULL or
  ``released_at < opened_at``) — ``scripts.lib.n8n_coordination_ledger.breaker_is_open``. Open ⇒ BREAKER_OPEN for
  every slot of the lane.

Contract for B5.5 executor v2: after ``LedgerRunStore.finish(...)`` call
``finalize_outcome(store, finished_row, policy, breaker_threshold=policies.breaker_threshold, now=time.time())``
and forward ``outcome.findings`` (``{source, item, severity, detail, detected_at}``) to the incident fan-in.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

from scripts.lib.n8n_coordination_ledger import SINGLE_ATTEMPT_CLASSES, dead_letter_rearmable  # noqa: F401  (re-export)

NO_CONSUMER_REASON = (
    "Library for the n8n maturity dispatch core (design 02 §3.4); consumed by scripts/n8n_dlq.py now and by "
    "coordination/due (B5.3) and executor v2 (B5.5) once they land."
)

SCHEMA = "N8nRetryPolicies@v1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "config" / "n8n_retry_policies.json"
CLASSES = ("monitor", "report", "hygiene", "pipeline", "heavy", "llm", "ingest", "send", "learn")
RETRYABLE_STATE_CHOICES = ("RUN_TIMEOUT", "RUN_FAILED")
SEVERITIES = ("P1", "P2", "P3")
VERDICT_OK, VERDICT_RETRYABLE, VERDICT_TERMINAL, VERDICT_SKIPPED = "ok", "retryable", "terminal", "skipped"
LLM_TERMINAL_SAMPLES = ("COST_CAP", "PEAK_SKIP")
#: LLM-class runs whose reason matches these are terminal, whatever their policy says (F8: no double spend).
LLM_HARD_TERMINAL_RE = re.compile(r"(?i)cost_cap|peak_skip")
UNRESOLVED_POLICY_NAME = "unresolved"
log = logging.getLogger(__name__)
_TOP_KEYS = {"schema", "as_of", "default_policy", "breaker_threshold", "class_caps", "policies"}
_POLICY_REQUIRED = ("max_attempts", "backoff_s", "retryable_states", "retryable_exit_codes", "terminal_exit_codes",
                    "terminal_reason_patterns", "catchup_min")
_POLICY_KEYS = set(_POLICY_REQUIRED) | {"description", "retryable_reason_patterns", "dlq_severity", "permitted_classes"}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class RetryPolicyError(ValueError):
    """The policy file is missing, unreadable or invalid. ``errors`` lists every defect found."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = list(errors)


@dataclass(frozen=True)
class RetryPolicy:
    name: str
    max_attempts: int
    backoff_s: tuple[int, ...]
    retryable_states: frozenset[str]
    retryable_exit_codes: frozenset[int]
    retryable_reason_patterns: tuple[str, ...]
    terminal_exit_codes: frozenset[int]
    terminal_reason_patterns: tuple[str, ...]
    catchup_min: int
    dlq_severity: str = "P2"
    permitted_classes: frozenset[str] = frozenset(CLASSES)
    description: str = ""


@dataclass(frozen=True)
class RetryPolicies:
    sha256: str
    default_policy: str
    breaker_threshold: int
    class_caps: Mapping[str, int]
    policies: Mapping[str, RetryPolicy]
    as_of: str = ""

    def get(self, name: Optional[str] = None) -> RetryPolicy:
        """The named policy. A None/empty or unknown name does NOT fall back to the default: it returns
        ``UNRESOLVED_POLICY`` (single attempt, nothing retryable, so every failure is terminal) and logs a
        warning. Use ``default()`` to ask for the default policy explicitly."""
        if name and name in self.policies:
            return self.policies[name]
        log.warning("n8n retry policy %r unresolved; treating the run as single-attempt terminal", name)
        return UNRESOLVED_POLICY

    def default(self) -> RetryPolicy:
        """The file's ``default_policy``, asked for explicitly (e.g. by the registry checker)."""
        return self.policies[self.default_policy]


#: What ``RetryPolicies.get`` returns for a missing/unknown policy name: one attempt, every failure terminal.
UNRESOLVED_POLICY = RetryPolicy(
    name=UNRESOLVED_POLICY_NAME, max_attempts=1, backoff_s=(), retryable_states=frozenset(),
    retryable_exit_codes=frozenset(), retryable_reason_patterns=(), terminal_exit_codes=frozenset(),
    terminal_reason_patterns=("(?i)cost_cap", "(?i)peak_skip"), catchup_min=30, dlq_severity="P2",
    permitted_classes=frozenset(CLASSES), description="missing or unknown retry policy: never retry")


@dataclass
class Outcome:
    verdict: str
    dead_letter: Optional[dict[str, Any]] = None
    breaker_opened: bool = False
    breaker_closed: bool = False
    consecutive_dead: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)


def _int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _matches_any(patterns: Any, text: str) -> bool:
    for pat in patterns or ():
        try:
            if re.search(pat, text):
                return True
        except re.error:
            continue
    return False


def _validate_policy(name: str, pol: Any) -> list[str]:
    errs: list[str] = []
    where = f"policies.{name}"
    if not isinstance(pol, Mapping):
        return [f"{where}: not an object"]
    for k in _POLICY_REQUIRED:
        if k not in pol:
            errs.append(f"{where}: missing {k}")
    for k in pol:
        if k not in _POLICY_KEYS:
            errs.append(f"{where}: unknown key {k}")
    if errs:
        return errs
    n = pol["max_attempts"]
    if not _int(n) or not 1 <= n <= 5:
        errs.append(f"{where}: max_attempts must be an integer 1..5")
        n = None
    back = pol["backoff_s"]
    if not isinstance(back, list) or not all(_int(b) and 10 <= b <= 3600 for b in back):
        errs.append(f"{where}: backoff_s must be integers 10..3600")
    elif n is not None and len(back) != n - 1:
        errs.append(f"{where}: backoff_s length {len(back)} != max_attempts-1 ({n - 1})")
    states = pol["retryable_states"]
    if not isinstance(states, list) or len(set(states)) != len(states) or any(
            s not in RETRYABLE_STATE_CHOICES for s in states):
        errs.append(f"{where}: retryable_states must be unique items of {list(RETRYABLE_STATE_CHOICES)}")
    for k in ("retryable_exit_codes", "terminal_exit_codes"):
        v = pol[k]
        if not isinstance(v, list) or len(set(v)) != len(v) or not all(_int(c) and 1 <= c <= 255 for c in v):
            errs.append(f"{where}: {k} must be unique integers 1..255")
    for k in ("retryable_reason_patterns", "terminal_reason_patterns"):
        v = pol.get(k, [])
        if not isinstance(v, list) or not all(isinstance(p, str) and len(p) <= 80 for p in v):
            errs.append(f"{where}: {k} must be strings of at most 80 chars")
            continue
        for p in v:
            try:
                re.compile(p)
            except re.error as exc:
                errs.append(f"{where}: {k} bad regex {p!r}: {exc}")
    cm = pol["catchup_min"]
    if not _int(cm) or not 1 <= cm <= 1440:
        errs.append(f"{where}: catchup_min must be an integer 1..1440")
    if "description" in pol and (not isinstance(pol["description"], str) or len(pol["description"]) > 200):
        errs.append(f"{where}: description must be a string of at most 200 chars")
    if pol.get("dlq_severity", "P2") not in SEVERITIES:
        errs.append(f"{where}: dlq_severity must be one of {list(SEVERITIES)}")
    classes = pol.get("permitted_classes", list(CLASSES))
    if not isinstance(classes, list) or len(set(classes)) != len(classes) or any(c not in CLASSES for c in classes):
        errs.append(f"{where}: permitted_classes must be unique items of {list(CLASSES)}")
        classes = []
    # program rules
    if n is not None and n != 1 and ({"send", "learn"} & set(classes)):
        errs.append(f"{where}: permitted for send/learn so max_attempts must be 1 (senders and learning writers never retry)")
    if "llm" in classes and isinstance(pol["terminal_reason_patterns"], list):
        for sample in LLM_TERMINAL_SAMPLES:
            if not (_matches_any(pol["terminal_reason_patterns"], sample)
                    and _matches_any(pol["terminal_reason_patterns"], sample.lower())):
                errs.append(f"{where}: permitted for llm so terminal_reason_patterns must match {sample} (any case)")
    return errs


def validate_policies(doc: Any) -> list[str]:
    """Every defect in an N8nRetryPolicies@v1 document (schema + program rules); [] when valid. Pure."""
    if not isinstance(doc, Mapping):
        return ["document is not an object"]
    errs: list[str] = []
    for k in sorted(_TOP_KEYS - set(doc)):
        errs.append(f"missing {k}")
    for k in sorted(set(doc) - _TOP_KEYS):
        errs.append(f"unknown key {k}")
    if doc.get("schema") != SCHEMA:
        errs.append(f"schema must be {SCHEMA}")
    if "as_of" in doc and (not isinstance(doc["as_of"], str) or not _DATE_RE.match(doc["as_of"])):
        errs.append("as_of must be YYYY-MM-DD")
    bt = doc.get("breaker_threshold")
    if "breaker_threshold" in doc and (not _int(bt) or not 2 <= bt <= 10):
        errs.append("breaker_threshold must be an integer 2..10")
    caps = doc.get("class_caps")
    if "class_caps" in doc:
        if not isinstance(caps, Mapping):
            errs.append("class_caps must be an object")
        else:
            for k in ("global", "reserved_priority_max"):
                if k not in caps:
                    errs.append(f"class_caps: missing {k}")
            for k, v in caps.items():
                if k == "global":
                    ok = _int(v) and 1 <= v <= 8
                elif k == "reserved_priority_max":
                    ok = _int(v) and 0 <= v <= 9
                elif k in CLASSES:
                    ok = _int(v) and v >= 1
                else:
                    errs.append(f"class_caps: unknown key {k}")
                    continue
                if not ok:
                    errs.append(f"class_caps.{k}: out of range")
    pols = doc.get("policies")
    if "policies" in doc:
        if not isinstance(pols, Mapping) or not pols:
            errs.append("policies must be a non-empty object")
        else:
            for name, pol in pols.items():
                if not isinstance(name, str) or not _NAME_RE.match(name):
                    errs.append(f"policies: bad policy name {name!r}")
                errs.extend(_validate_policy(str(name), pol))
            if isinstance(doc.get("default_policy"), str) and doc["default_policy"] not in pols:
                errs.append(f"default_policy {doc['default_policy']!r} is not a defined policy")
    if "default_policy" in doc and not isinstance(doc["default_policy"], str):
        errs.append("default_policy must be a string")
    return errs


def _build(name: str, pol: Mapping[str, Any]) -> RetryPolicy:
    return RetryPolicy(
        name=name,
        max_attempts=int(pol["max_attempts"]),
        backoff_s=tuple(int(b) for b in pol["backoff_s"]),
        retryable_states=frozenset(pol["retryable_states"]),
        retryable_exit_codes=frozenset(int(c) for c in pol["retryable_exit_codes"]),
        retryable_reason_patterns=tuple(pol.get("retryable_reason_patterns", [])),
        terminal_exit_codes=frozenset(int(c) for c in pol["terminal_exit_codes"]),
        terminal_reason_patterns=tuple(pol["terminal_reason_patterns"]),
        catchup_min=int(pol["catchup_min"]),
        dlq_severity=str(pol.get("dlq_severity", "P2")),
        permitted_classes=frozenset(pol.get("permitted_classes", CLASSES)),
        description=str(pol.get("description", "")),
    )


def load_policies(path: Optional[Path | str] = None) -> RetryPolicies:
    """Load + validate the policy file (default config/n8n_retry_policies.json). RetryPolicyError on any defect."""
    p = Path(path) if path is not None else DEFAULT_PATH
    try:
        raw = p.read_bytes()
        doc = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise RetryPolicyError([f"unreadable {p.name}: {type(exc).__name__}"]) from exc
    errs = validate_policies(doc)
    if errs:
        raise RetryPolicyError(errs)
    policies = {name: _build(name, pol) for name, pol in doc["policies"].items()}
    return RetryPolicies(
        sha256=hashlib.sha256(raw).hexdigest(),
        default_policy=str(doc["default_policy"]),
        breaker_threshold=int(doc["breaker_threshold"]),
        class_caps=MappingProxyType({str(k): int(v) for k, v in doc["class_caps"].items()}),
        policies=MappingProxyType(policies),
        as_of=str(doc.get("as_of", "")),
    )


def verdict(state: str, exit_code: Optional[int], reason: Optional[str], policy: RetryPolicy) -> str:
    """ok | retryable | terminal | skipped for one finished run. Pure.

    RUN_DONE→ok; RUN_SKIPPED_LOCK→skipped; RUN_REFUSED→terminal; terminal exit codes / reason patterns always win;
    RUN_TIMEOUT retryable iff in retryable_states; RUN_FAILED retryable iff in retryable_states AND (exit code in
    retryable_exit_codes OR reason matches retryable_reason_patterns); anything else terminal."""
    if state == "RUN_DONE":
        return VERDICT_OK
    if state == "RUN_SKIPPED_LOCK":
        return VERDICT_SKIPPED
    if state == "RUN_REFUSED":
        return VERDICT_TERMINAL
    text = reason or ""
    if exit_code is not None and exit_code in policy.terminal_exit_codes:
        return VERDICT_TERMINAL
    if text and _matches_any(policy.terminal_reason_patterns, text):
        return VERDICT_TERMINAL
    if state not in policy.retryable_states:
        return VERDICT_TERMINAL
    if state == "RUN_TIMEOUT":
        return VERDICT_RETRYABLE
    if state == "RUN_FAILED":
        if exit_code is not None and exit_code in policy.retryable_exit_codes:
            return VERDICT_RETRYABLE
        if text and _matches_any(policy.retryable_reason_patterns, text):
            return VERDICT_RETRYABLE
    return VERDICT_TERMINAL


def _as_dt(value: datetime | str) -> datetime:
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def effective_max_attempts(policy: RetryPolicy, klass: Optional[str] = None) -> int:
    """The policy's max_attempts, hard-capped in code: 1 for send/learn classes and for a class the policy does
    not permit. ``klass`` None (legacy run with no class) keeps the policy value."""
    if klass is not None and (klass in SINGLE_ATTEMPT_CLASSES or not policy_permits_class(policy, klass)):
        return 1
    return policy.max_attempts


def next_attempt_at(policy: RetryPolicy, attempt: int, finished_at: datetime | str,
                    klass: Optional[str] = None) -> Optional[datetime]:
    """When attempt ``attempt + 1`` becomes RETRY_DUE: ``finished_at + backoff_s[attempt-1]``; None when
    ``attempt >= effective_max_attempts(policy, klass)`` (so never for send/learn or an unpermitted class).
    ``finished_at`` may be an ISO string (naive = UTC)."""
    if attempt < 1 or attempt >= effective_max_attempts(policy, klass):
        return None
    return _as_dt(finished_at) + timedelta(seconds=policy.backoff_s[attempt - 1])


def policy_permits_class(policy: RetryPolicy, klass: str) -> bool:
    return klass in policy.permitted_classes


def class_verdict(state: str, exit_code: Optional[int], reason: Optional[str], policy: RetryPolicy,
                  klass: Optional[str] = None) -> str:
    """``verdict`` plus the code-level class rails, which hold whatever the policy file says:

    - a class the policy does not permit: any non-ok/non-skipped run is terminal;
    - send / learn: never retryable (terminal);
    - llm: a reason matching COST_CAP or PEAK_SKIP (any case) is terminal.
    ``klass`` None (legacy run) applies the policy alone."""
    v = verdict(state, exit_code, reason, policy)
    if v != VERDICT_RETRYABLE or klass is None:
        return v
    if not policy_permits_class(policy, klass) or klass in SINGLE_ATTEMPT_CLASSES:
        return VERDICT_TERMINAL
    if klass == "llm" and LLM_HARD_TERMINAL_RE.search(reason or ""):
        return VERDICT_TERMINAL
    return v



def slot_local_of(slot_key: Optional[str]) -> Optional[str]:
    """``d:<lane>:<mode>:<YYYYMMDDTHHMM>`` -> the local wall-clock minute; None for any other key shape."""
    if not slot_key:
        return None
    last = slot_key.rsplit(":", 1)[-1]
    return last if re.fullmatch(r"\d{8}T\d{4}", last) else None


def _finding(source: str, item: str, severity: str, detail: str, now: float) -> dict[str, Any]:
    return {"source": source, "item": item, "severity": severity, "detail": detail[:160],
            "detected_at": datetime.fromtimestamp(now, timezone.utc).isoformat()}


def finalize_outcome(store: Any, run_row: Mapping[str, Any], policy: Optional[RetryPolicy], *, breaker_threshold: int,
                     now: float, severity: Optional[str] = None, klass: Optional[str] = None) -> Outcome:
    """Verdict + dead letter + breaker for one FINISHED run row (as returned by ``LedgerRunStore.finish``).

    ``store`` is a ``LedgerRunStore``. Writes ``runs.verdict``; on terminal, or retryable with
    ``attempt >= max_attempts``, upserts ``dead_letters`` (key = row ``slot_key`` or, for legacy rows, ``run_id``)
    and returns finding ``dlq:<lane>`` (``severity`` overrides the policy's dlq_severity, e.g. a P1 lane); when the
    lane then has ``consecutive_dead >= breaker_threshold`` and no open breaker, opens it (finding
    ``breaker:<lane>`` P2). A RUN_DONE (verdict ok) auto-releases an open breaker (by ``auto:run_done``).
    ``now`` is unix seconds.

    Code-level rails (``class_verdict`` / ``effective_max_attempts``), whatever the policy file says: the run's
    class (``klass`` or the row's ``class``) not permitted by the policy ⇒ terminal; send/learn ⇒ one attempt,
    never retryable; llm with a COST_CAP/PEAK_SKIP reason ⇒ terminal. ``policy`` None (missing/unknown name) ⇒
    ``UNRESOLVED_POLICY``: every failure terminal. The dead letter records ``class`` and the effective
    ``max_attempts`` so ``dead_letter_rearmable`` can refuse re-arming single-attempt / send / learn slots."""
    if policy is None:
        log.warning("finalize_outcome: no retry policy for lane %r; terminal on failure", run_row.get("lane_id"))
        policy = UNRESOLVED_POLICY
    lane = str(run_row["lane_id"])
    klass = klass if klass is not None else run_row.get("class")
    receipt = run_row.get("receipt") or {}
    reason = receipt.get("reason") if isinstance(receipt, Mapping) else None
    exit_code = run_row.get("exit_code")
    v = class_verdict(str(run_row["state"]), exit_code if _int(exit_code) else None, reason, policy, klass)
    max_attempts = effective_max_attempts(policy, klass)
    with store.lock:
        store.set_verdict(str(run_row["run_id"]), v)
        out = Outcome(verdict=v)
        if v == VERDICT_OK:
            if store.release_breaker(lane, "auto:run_done", now) is not None:
                out.breaker_closed = True
            return out
        attempt = int(run_row.get("attempt") or 1)
        if not (v == VERDICT_TERMINAL or (v == VERDICT_RETRYABLE and attempt >= max_attempts)):
            return out
        slot_key = str(run_row.get("slot_key") or run_row["run_id"])
        out.dead_letter = store.record_dead_letter(
            slot_key=slot_key, lane_id=lane, mode=run_row.get("mode"), slot_local=slot_local_of(slot_key),
            attempts=attempt, last_run_id=str(run_row["run_id"]), last_state=str(run_row["state"]),
            last_reason=reason, verdict=v, now=now, klass=klass, max_attempts=max_attempts,
            policy=policy.name)
        sev = severity if severity in SEVERITIES else policy.dlq_severity
        out.findings.append(_finding("dlq", f"dlq:{lane}", sev,
                                     f"{slot_key} {run_row['state']} {reason or ''} attempt {attempt}/{max_attempts}"
                                     f" policy {policy.name}",
                                     now))
        out.consecutive_dead = store.consecutive_dead(lane)
        brk = store.breaker(lane)
        if out.consecutive_dead >= breaker_threshold and not (brk and brk["open"]):
            store.open_breaker(lane, out.consecutive_dead, now)
            out.breaker_opened = True
            out.findings.append(_finding("dlq", f"breaker:{lane}", "P2",
                                         f"{out.consecutive_dead} consecutive dead slots; lane paused", now))
    return out
