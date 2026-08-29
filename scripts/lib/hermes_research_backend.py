"""HermesResearchBackend protocol — research intelligence only.

Worker claims jobs, validates, persists, and callbacks.
Backend only turns ResearchRequest → unstamped result body.

READ_ONLY_ADVISORY. No Telegram, no JSONL writes, no broker orders.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable


RESULT_BODY_KEYS = frozenset({
    "as_of",
    "answers",
    "findings",
    "desk_implications",
    "limitations",
    "evidence_links",
    "sources",
    "source_urls",
    "summary",
    "symbol",
    "thesis_version_at_request",
})

SUGGESTION_BIASES = frozenset({
    "hold_with_thesis", "hold_cash", "review", "observe",
})

_EXEC_RE = re.compile(
    r"\b(buy|sell|trim now|place stop|enter order|market order|submit order|"
    r"buy now|sell now|force fill)\b",
    re.I,
)


class HermesBackendError(Exception):
    """Hard failure from a research backend. Worker marks request failed."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@runtime_checkable
class HermesResearchBackend(Protocol):
    """
    Execute research for one ResearchRequest.
    Returns an unstamped result body (no result_id / status / worker provenance).
    Worker stamps identity, validates, and persists.
    """

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        """
        Returns hermes_result@v1 body fields:
          as_of, answers[], findings[], desk_implications, limitations[],
          evidence_links[], symbol?, thesis_version_at_request?
        Raises HermesBackendError on hard failure.
        """
        ...


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def questions_from_request(request: dict[str, Any]) -> list[dict[str, str]]:
    """Normalize questions to {id, text, intent}. Prefer question_id then id."""
    out: list[dict[str, str]] = []
    for i, q in enumerate(request.get("questions") or []):
        if isinstance(q, str):
            text = q.strip()
            if text:
                out.append({"id": f"q{i+1}", "text": text, "intent": "other"})
            continue
        if not isinstance(q, dict):
            continue
        text = str(q.get("text") or q.get("question") or "").strip()
        if not text:
            continue
        try:
            from scripts.lib.cio_question_ids import question_id_for

            qid = question_id_for(q, index=i)
        except Exception:                                       # pragma: no cover
            qid = str(q.get("question_id") or q.get("id") or f"q{i+1}")
        intent = str(q.get("intent") or "other")
        out.append({"id": qid, "text": text, "intent": intent})
    return out


def assert_no_execution_language(*texts: str) -> None:
    for t in texts:
        if t and _EXEC_RE.search(t):
            raise HermesBackendError(
                f"execution language not allowed in research output: {t[:120]}",
                retryable=False,
            )


def empty_answer(qid: str, *, reason: str) -> dict[str, Any]:
    return {
        "question_id": qid,
        "status": "unanswered",
        "summary": reason,
        "detail": "",
        "confidence": 0.0,
        "citations": [],
    }


def normalize_desk_bias(bias: Any) -> str:
    b = str(bias or "observe").strip().lower()
    return b if b in SUGGESTION_BIASES else "observe"


def assert_readonly_authority(request: dict[str, Any]) -> None:
    auth = str(request.get("authority") or "").strip()
    if auth != "READ_ONLY_ADVISORY":
        raise HermesBackendError("authority must be READ_ONLY_ADVISORY", retryable=False)


class StubHermesResearchBackend:
    """Deterministic backend for unit tests and host dry-runs."""

    def __init__(self, *, mark_partial: bool = False):
        self.mark_partial = mark_partial

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        assert_readonly_authority(request)
        qs = questions_from_request(request)
        if not qs:
            raise HermesBackendError("no questions", retryable=False)

        symbol = (
            (request.get("subject") or {}).get("symbol")
            or request.get("symbol")
            or ""
        )
        pin = request.get("thesis_version") or "desk@?"
        answers = []
        for q in qs:
            status = "partial" if self.mark_partial else "answered"
            summary = (
                f"Stub finding for {symbol or 'book'} under {pin}: "
                f"{q['text'][:160]}"
            )
            assert_no_execution_language(summary)
            answers.append({
                "question_id": q["id"],
                "status": status,
                "summary": summary,
                "detail": f"intent={q['intent']}",
                "confidence": 0.5,
                "citations": [],
            })

        return {
            "as_of": utc_now_iso(),
            "symbol": symbol or None,
            "thesis_version_at_request": request.get("thesis_version"),
            "answers": answers,
            "findings": [
                {
                    "id": "f_stub",
                    "kind": "other",
                    "severity": "low",
                    "text": "StubHermesResearchBackend placeholder finding — observe/hold language only",
                    "confidence": 0.5,
                }
            ],
            "desk_implications": {
                "suggestion_bias": "observe",
                "changes_materiality": False,
                "recommended_revisit": None,
                "watch_triggers": [],
                "notes": "stub backend — replace with BridgeHermesResearchBackend for live intel",
            },
            "limitations": ["stub_backend"],
            "evidence_links": [],
        }


class CatalystFirstHermesBackend:
    """Prefer calendar/catalyst context when intents are catalyst_map; else stub."""

    def __init__(self, *, fallback: HermesResearchBackend | None = None):
        self.fallback = fallback or StubHermesResearchBackend()

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        body = self.fallback.run(request)
        qs = questions_from_request(request)
        intents = [q["intent"] for q in qs]
        if not any("catalyst" in i for i in intents):
            return body
        cat = request.get("catalyst") or request.get("catalyst_pack") or {}
        ne = cat.get("next_event") if isinstance(cat, dict) else None
        if isinstance(ne, dict) and ne.get("session_date"):
            line = (
                f"Calendar: {ne.get('kind')} on {ne.get('session_date')} "
                f"severity={ne.get('severity')} — observe through event; "
                f"does not alone authorize size change under READ_ONLY."
            )
            assert_no_execution_language(line)
            findings = list(body.get("findings") or [])
            findings.insert(0, {
                "id": "f_catalyst",
                "kind": "catalyst",
                "severity": str(ne.get("severity") or "low"),
                "text": line,
                "confidence": 0.65,
            })
            body["findings"] = findings
            body["summary"] = line  # optional body field used by some callers
            body["limitations"] = list(body.get("limitations") or []) + ["catalyst_first"]
        return body


class RoutingHermesResearchBackend:
    """Route by majority questions[].intent to specialized handlers."""

    def __init__(
        self,
        default: HermesResearchBackend,
        routes: dict[str, HermesResearchBackend] | None = None,
    ):
        self.default = default
        self.routes = routes or {}

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        qs = questions_from_request(request)
        intents = [q["intent"] for q in qs]
        primary = max(set(intents), key=intents.count) if intents else "other"
        backend = self.routes.get(primary, self.default)
        return backend.run(request)


def build_hermes_backend(name: str | None = None) -> HermesResearchBackend:
    """
    Factory. Default HERMES_BACKEND=stub until live bridge proven.

    Names: stub|test · catalyst · bridge|live|hermes
    """
    name = (name or os.getenv("HERMES_BACKEND", "stub")).strip().lower()
    if name in ("stub", "test", ""):
        return StubHermesResearchBackend()
    if name in ("catalyst", "catalyst_first"):
        return CatalystFirstHermesBackend()
    if name in ("bridge", "live", "hermes"):
        try:
            from lib.hermes_bridge_backend import BridgeHermesResearchBackend
        except ImportError:
            from scripts.lib.hermes_bridge_backend import BridgeHermesResearchBackend  # type: ignore
        return BridgeHermesResearchBackend()
    raise ValueError(f"unknown HERMES_BACKEND={name}")
