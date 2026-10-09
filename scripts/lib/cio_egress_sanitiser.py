"""The single egress sanitiser (AGENTS.md §2A, §23.4, §23.10 P4; guardrail audit B H3).

§2A: "Every outbound model call should pass through one function that applies this rule, so the policy
is enforced in code rather than remembered by each caller ... a single `sanitise_for_external()` on the
egress path, with the permitted set as data and a test that a forbidden field cannot pass."

    sanitise_for_external(messages, process_id) -> {"messages", "counts", "total", ...}

is that function. The rules are data (config/egress_sanitiser_policy.json, EgressSanitiserPolicy@v1):
credentials / keys / tokens / cookies, .env lines, account numbers and broker account identifiers,
personal identifiers, internal host paths / hostnames / addresses, and - until the operator settles the
§2A "permitted set" - position dollars and quantities.

The governed bridge applies it to EVERY process before any provider call (execute_governed_call, before
Step 7) through apply_egress_sanitiser(), whose mode is TRADEAI_EGRESS_SANITISER:

    off      not scanned (an explicit operator choice; recorded on the response envelope)
    report   DEFAULT. Scanned; messages are sent UNCHANGED; a call with any match appends one
             EgressSanitiserReport@v1 line (counts per category, no content, no matched value) to
             data/runtime/egress_sanitiser_report.jsonl
    enforce  Scanned; every match is replaced with [REDACTED:<category>] before the provider call;
             the same report line is written with action "redacted"

Enforce never refuses: a refusal on a forbidden-field hit is reserved for free-text Agent input
(§23.4 free_text_allowed), which is not built here. A policy file that cannot be read is fail-closed in
enforce (typed EGRESS_POLICY_UNAVAILABLE refusal) and recorded in report.

AUTHORITY: READ_ONLY_ADVISORY. Pure string transforms plus one append-only diagnostic file. Never logs,
returns or writes a matched value.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

NO_CONSUMER_REASON = (
    "consumed in-process by scripts/lib/cio_governed_model_bridge.execute_governed_call (every governed "
    "provider call); the report file is an ops diagnostic read by the operator, not a CIO surface"
)

POLICY_SCHEMA = "EgressSanitiserPolicy@v1"
REPORT_SCHEMA = "EgressSanitiserReport@v1"
MODE_ENV = "TRADEAI_EGRESS_SANITISER"
MODES = ("off", "report", "enforce")
DEFAULT_MODE = "report"
POLICY_ENV = "TRADEAI_EGRESS_SANITISER_POLICY"
REPORT_ENV = "TRADEAI_EGRESS_SANITISER_REPORT"
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = _PROJECT_ROOT / "config" / "egress_sanitiser_policy.json"

_POLICY_LOCK = threading.Lock()
_POLICY_CACHE: dict[str, Any] = {}
_COUNTS_LOCK = threading.Lock()
_COUNTS: dict[str, dict[str, int]] = {}


class EgressPolicyUnavailable(RuntimeError):
    """The policy file is missing, unreadable, or has no usable category."""


def egress_mode() -> str:
    raw = (os.environ.get(MODE_ENV) or DEFAULT_MODE).strip().lower()
    return raw if raw in MODES else DEFAULT_MODE


def policy_path() -> Path:
    raw = os.environ.get(POLICY_ENV)
    return Path(raw) if raw else DEFAULT_POLICY_PATH


def report_path() -> Path | None:
    """None under pytest unless the test names a file, so a test never writes the live report."""
    raw = os.environ.get(REPORT_ENV)
    if raw:
        return Path(raw)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    state_root = os.environ.get("TRADEAI_STATE_ROOT")
    base = Path(state_root) if state_root else _PROJECT_ROOT
    return base / "data" / "runtime" / "egress_sanitiser_report.jsonl"


def load_policy() -> dict[str, Any]:
    """Compiled policy, cached by path + mtime + size. Raises EgressPolicyUnavailable, never returns empty."""
    path = policy_path()
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError as exc:
        raise EgressPolicyUnavailable(f"policy file missing: {path.name}") from exc
    with _POLICY_LOCK:
        if _POLICY_CACHE.get("key") == key:
            return _POLICY_CACHE["policy"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise EgressPolicyUnavailable(f"policy file unreadable: {type(exc).__name__}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != POLICY_SCHEMA:
        raise EgressPolicyUnavailable("policy schema mismatch")
    categories: list[tuple[str, list[re.Pattern[str]]]] = []
    for cat in doc.get("categories") or []:
        if not isinstance(cat, dict) or not cat.get("id"):
            continue
        compiled = []
        for pattern in cat.get("patterns") or []:
            try:
                compiled.append(re.compile(str(pattern)))
            except re.error as exc:
                raise EgressPolicyUnavailable(f"bad pattern in category {cat['id']}: {exc}") from exc
        if compiled:
            categories.append((str(cat["id"]), compiled))
    if not categories:
        raise EgressPolicyUnavailable("policy has no category")
    policy = {"version": doc.get("version"), "categories": categories}
    with _POLICY_LOCK:
        _POLICY_CACHE["key"] = key
        _POLICY_CACHE["policy"] = policy
    return policy


def _sanitise_text(text: str, categories: list[tuple[str, list[re.Pattern[str]]]],
                   counts: dict[str, int]) -> str:
    """Apply categories in policy order; a span replaced by one category is not re-counted by a later one."""
    out = text
    for cat_id, patterns in categories:
        token = f"[REDACTED:{cat_id}]"
        for pattern in patterns:
            out, n = pattern.subn(token, out)
            if n:
                counts[cat_id] = counts.get(cat_id, 0) + n
    return out


def _sanitise_message(msg: Any, categories: list, counts: dict[str, int]) -> Any:
    if not isinstance(msg, dict):
        return msg
    out = dict(msg)
    content = out.get("content")
    if isinstance(content, str):
        out["content"] = _sanitise_text(content, categories, counts)
    elif isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                part = {**part, "text": _sanitise_text(part["text"], categories, counts)}
            elif isinstance(part, str):
                part = _sanitise_text(part, categories, counts)
            parts.append(part)
        out["content"] = parts
    tool_calls = out.get("tool_calls")
    if isinstance(tool_calls, list):
        calls = []
        for call in tool_calls:
            if isinstance(call, dict) and isinstance(call.get("function"), dict) \
                    and isinstance(call["function"].get("arguments"), str):
                fn = dict(call["function"])
                fn["arguments"] = _sanitise_text(fn["arguments"], categories, counts)
                call = {**call, "function": fn}
            calls.append(call)
        out["tool_calls"] = calls
    return out


def sanitise_for_external(messages: list[dict], process_id: str) -> dict[str, Any]:
    """§2A egress rule for one outbound call. Pure: does not record, does not mutate `messages`.

    Returns {"process_id", "messages" (a redacted copy), "counts" {category: n}, "total",
    "messages_scanned", "policy_version"}. Raises EgressPolicyUnavailable when the rules cannot load.
    """
    policy = load_policy()
    counts: dict[str, int] = {}
    redacted = [_sanitise_message(copy.deepcopy(m), policy["categories"], counts) for m in (messages or [])]
    return {
        "process_id": str(process_id),
        "messages": redacted,
        "counts": counts,
        "total": sum(counts.values()),
        "messages_scanned": len(redacted),
        "policy_version": policy.get("version"),
    }


def _count(process_id: str, key: str, n: int = 1) -> None:
    with _COUNTS_LOCK:
        row = _COUNTS.setdefault(process_id, {})
        row[key] = row.get(key, 0) + n


def snapshot() -> dict[str, Any]:
    """Counters for the bridge's GET /health. Names and integers only."""
    with _COUNTS_LOCK:
        counts = {pid: dict(row) for pid, row in _COUNTS.items()}
    return {"mode": egress_mode(), "by_process": counts}


def reset() -> None:
    with _COUNTS_LOCK:
        _COUNTS.clear()
    with _POLICY_LOCK:
        _POLICY_CACHE.clear()


def _write_report(line: dict[str, Any]) -> None:
    path = report_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError:
        pass


def apply_egress_sanitiser(messages: list[dict], process_id: str,
                           request_id: str | None = None) -> dict[str, Any]:
    """Mode-aware wrapper the bridge calls before every provider call.

    Returns {"messages": what to send, "verdict": {...}} or {"refused": {...}} (enforce + no policy only).
    The verdict carries mode, action and counts; never content.
    """
    mode = egress_mode()
    pid = str(process_id)
    _count(pid, "calls")
    if mode == "off":
        return {"messages": messages, "verdict": {"mode": "off", "action": "not_scanned", "total": 0}}
    try:
        result = sanitise_for_external(messages, pid)
    except EgressPolicyUnavailable as exc:
        _count(pid, "policy_unavailable")
        _write_report({
            "schema": REPORT_SCHEMA, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "process_id": pid, "request_id": request_id, "mode": mode, "action": "policy_unavailable",
            "counts": {}, "total": 0, "reason": str(exc)[:120], "authority": "READ_ONLY_ADVISORY",
        })
        if mode == "enforce":
            return {"refused": {"code": "EGRESS_POLICY_UNAVAILABLE", "status": 503,
                                "message": "Egress sanitiser policy unavailable; enforce mode sends nothing"}}
        return {"messages": messages,
                "verdict": {"mode": mode, "action": "policy_unavailable", "total": 0}}
    _count(pid, "scanned")
    action = "clean"
    if result["total"]:
        action = "redacted" if mode == "enforce" else "reported"
        _count(pid, "with_matches")
        for cat, n in result["counts"].items():
            _count(pid, f"match:{cat}", n)
        _write_report({
            "schema": REPORT_SCHEMA,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "process_id": pid,
            "request_id": request_id,
            "mode": mode,
            "action": action,
            "counts": dict(sorted(result["counts"].items())),
            "total": result["total"],
            "messages_scanned": result["messages_scanned"],
            "policy_version": result["policy_version"],
            "sent_unchanged": mode != "enforce",
            "authority": "READ_ONLY_ADVISORY",
        })
    verdict = {"mode": mode, "action": action, "total": result["total"],
               "counts": dict(sorted(result["counts"].items()))}
    return {"messages": result["messages"] if mode == "enforce" else messages, "verdict": verdict}
