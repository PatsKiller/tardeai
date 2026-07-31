"""Lane-aware, escalation-gated LLM helper for FLEET critic pipelines.

Master switch: AGENT_RUNTIME_CRITIC_LANES (default off). When off, callers get
deterministic-only results with honest provenance (provider_family=deterministic).
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

AMBIGUOUS_LOW = 0.4
AMBIGUOUS_HIGH = 0.6
LOCAL_MODEL = os.environ.get("AGENT_RUNTIME_SHADOW_MODEL", "gemma3:4b").strip() or "gemma3:4b"
DEFAULT_OLLAMA = os.environ.get("AGENT_RUNTIME_OLLAMA_BASE", "http://127.0.0.1:11434").rstrip("/")
DAILY_SOFT_CAP = int(os.environ.get("AGENT_RUNTIME_CRITIC_LANE_DAILY_CAP", "20"))

_VERDICT = Literal["CONTRADICTION", "DUPLICATE", "NOVEL"]

_PATTpairs = [
    (re.compile(r"\$\s?\d[\d,]*(\.\d+)?"), "$[REDACTED_AMOUNT]"),
    (re.compile(r"\b\d{6,}\b"), "[REDACTED_NUM]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    (re.compile(r"sk-[A-Za-z0-9]{16,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{36}|xoxb-[A-Za-z0-9-]+"), "[REDACTED_KEY]"),
    (re.compile(r"\b\d{1,3}(,\d{3})+(\.\d+)?\b"), "[REDACTED_NUM]"),
]
_FORBIDDEN_SUBSTR = [
    "api_key", "apikey", "secret", "password", "token", "credential",
    "ANTHROPIC", "ALPACA", "DB_PASSWORD", "BEGIN PRIVATE", "-----BEGIN",
]
_REMAINING_CURRENCY = re.compile(r"\$\s?\d")
_REMAINING_COMMA_NUM = re.compile(r"\b\d{1,3}(,\d{3})+(\.\d+)?\b")


class EgressClass(str, Enum):
    TEXT_ONLY = "TEXT_ONLY"
    LOCAL_ONLY = "LOCAL_ONLY"


@dataclass(frozen=True)
class CriticLlmResult:
    text: str
    provider_family: str
    model: str
    lane_used: str
    escalated: bool
    cost_usd: float = 0.0


def lanes_enabled() -> bool:
    return os.environ.get("AGENT_RUNTIME_CRITIC_LANES", "").strip().lower() in ("1", "true", "yes", "on")


def should_escalate(*, severity: str, confidence: float | None = None, doc_count: int = 0) -> bool:
    sev = (severity or "info").lower()
    if sev in {"high", "critical"}:
        return True
    if doc_count > 3:
        return True
    if confidence is not None and AMBIGUOUS_LOW <= float(confidence) <= AMBIGUOUS_HIGH:
        return True
    return False


def _vendored_redact(text: str) -> str:
    s = str(text)
    for pat, repl in _PATTpairs:
        s = pat.sub(repl, s)
    low = s.lower()
    for frag in _FORBIDDEN_SUBSTR:
        if frag.lower() in low:
            s = "\n".join(ln for ln in s.splitlines() if frag.lower() not in ln.lower())
    return s


def redact_or_refuse(text: str | None) -> str | None:
    if text is None:
        return None
    s = str(text)
    try:
        from hermes_external_researcher import redact as _redact  # type: ignore

        s = _redact(s)
    except Exception:
        s = _vendored_redact(s)
    if _REMAINING_CURRENCY.search(s) or _REMAINING_COMMA_NUM.search(s):
        return None
    return s


def _process_id(agent_id: str) -> str:
    return f"fleet_critic_{agent_id}"


def _lane_circuit_open(lane: str) -> bool:
    try:
        from hermes_external_researcher import lane_circuit_open  # type: ignore

        return bool(lane_circuit_open(lane))
    except Exception:
        return False


def _oauth_generate(lane: str, prompt: str, *, agent_id: str, timeout: int = 90) -> str | None:
    try:
        from lib.oauth_lane_status import lane_available  # type: ignore

        if not lane_available(lane):
            return None
    except Exception:
        return None
    if _lane_circuit_open(lane):
        return None
    try:
        import llm_lane  # type: ignore

        return llm_lane.generate(
            prompt,
            lane=lane,
            timeout=timeout,
            process_id=_process_id(agent_id),
            task_summary=f"fleet_critic:{agent_id}",
            metadata={"agent_id": agent_id, "subsystem": "fleet_critic"},
        )
    except Exception:
        return None


def _ollama_available() -> bool:
    try:
        req = urllib.request.Request(f"{DEFAULT_OLLAMA}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _local_generate(prompt: str, *, timeout: int = 120) -> str | None:
    try:
        import local_llm  # type: ignore

        return local_llm.generate(prompt, model=LOCAL_MODEL, timeout=timeout)
    except Exception:
        pass
    if not _ollama_available():
        return None
    payload = json.dumps(
        {"model": LOCAL_MODEL, "prompt": prompt, "stream": False, "options": {"temperature": 0}},
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{DEFAULT_OLLAMA}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.load(resp)
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None
    text = str(body.get("response") or "").strip()
    return text or None


def generate_for_critic(
    *,
    agent_id: str,
    prompt: str,
    egress: EgressClass,
    severity: str = "info",
    confidence: float | None = None,
    doc_count: int = 0,
    force: bool = False,
    timeout: int = 90,
) -> CriticLlmResult:
    """Escalation-gated generation with honest provenance and cost_usd=0.0."""
    _deterministic = CriticLlmResult(
        text="",
        provider_family="deterministic",
        model="none",
        lane_used="deterministic",
        escalated=False,
        cost_usd=0.0,
    )
    if not lanes_enabled() and not force:
        return _deterministic
    if not force and not should_escalate(severity=severity, confidence=confidence, doc_count=doc_count):
        return _deterministic

    if egress is EgressClass.LOCAL_ONLY:
        text = _local_generate(prompt, timeout=max(timeout, 120))
        if text:
            return CriticLlmResult(
                text=text,
                provider_family="local/ollama",
                model=LOCAL_MODEL,
                lane_used="local",
                escalated=True,
                cost_usd=0.0,
            )
        return _deterministic

    redacted = redact_or_refuse(prompt)
    if redacted is None:
        text = _local_generate(prompt, timeout=max(timeout, 120))
        if text:
            return CriticLlmResult(
                text=text,
                provider_family="local/ollama",
                model=LOCAL_MODEL,
                lane_used="local",
                escalated=True,
                cost_usd=0.0,
            )
        return _deterministic

    for lane, family, model in (
        ("grok", "cloud_free/grok", "grok-3-mini"),
        ("chatgpt", "cloud_free/chatgpt", "gpt-5.4"),
    ):
        text = _oauth_generate(lane, redacted, agent_id=agent_id, timeout=timeout)
        if text:
            return CriticLlmResult(
                text=text,
                provider_family=family,
                model=model,
                lane_used=lane,
                escalated=True,
                cost_usd=0.0,
            )

    text = _local_generate(redacted, timeout=max(timeout, 120))
    if text:
        return CriticLlmResult(
            text=text,
            provider_family="local/ollama",
            model=LOCAL_MODEL,
            lane_used="local",
            escalated=True,
            cost_usd=0.0,
        )
    return _deterministic


def extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def classify_lesson_verdict(
    *,
    candidate_id: str,
    candidate_statement: str,
    ratified: list[dict[str, Any]],
    agent_id: str = "iris",
) -> tuple[_VERDICT | None, CriticLlmResult]:
    """Classify one candidate lesson against ratified knowledge."""
    ratified_block = "\n".join(
        f"{row.get('lesson_id')}: {row.get('statement')}" for row in ratified[:20]
    )
    prompt = (
        "You are a knowledge-base librarian. Classify the CANDIDATE lesson against RATIFIED lessons.\n"
        "Reply with ONLY compact JSON: "
        '{"verdict":"CONTRADICTION|DUPLICATE|NOVEL","ref":"R# or null"}\n\n'
        f"RATIFIED:\n{ratified_block}\n\n"
        f"CANDIDATE ({candidate_id}): {candidate_statement}\n"
    )
    result = generate_for_critic(
        agent_id=agent_id,
        prompt=prompt,
        egress=EgressClass.TEXT_ONLY,
        severity="warning",
        confidence=0.5,
        doc_count=len(ratified) + 1,
        force=True,
    )
    if not result.text:
        return None, result
    parsed = extract_json_object(result.text) or {}
    verdict_raw = str(parsed.get("verdict") or "").upper()
    if verdict_raw in {"CONTRADICTION", "DUPLICATE", "NOVEL"}:
        return verdict_raw, result  # type: ignore[return-value]
    return None, result


def finding_from_lesson_verdict(
    *,
    lesson_id: str,
    verdict: _VERDICT | None,
    ref: str | None = None,
) -> dict[str, Any]:
    if verdict == "CONTRADICTION":
        return {
            "code": "contradiction_confirmed",
            "severity": "high",
            "message": f"Lesson {lesson_id} contradicts ratified knowledge{f' ({ref})' if ref else ''} — human review required",
            "lesson_id": lesson_id,
            "verdict": "contradiction",
            "ref": ref,
        }
    if verdict == "DUPLICATE":
        return {
            "code": "duplicate_lesson",
            "severity": "warning",
            "message": f"Lesson {lesson_id} duplicates ratified knowledge{f' ({ref})' if ref else ''}",
            "lesson_id": lesson_id,
            "verdict": "duplicate",
            "ref": ref,
        }
    if verdict == "NOVEL":
        return {
            "code": "support_ratification",
            "severity": "info",
            "message": f"Lesson {lesson_id} is novel and passes contradiction screen",
            "lesson_id": lesson_id,
            "verdict": "support",
        }
    return {
        "code": "classification_deferred",
        "severity": "info",
        "message": f"Lesson {lesson_id} requires human review — model classification unavailable",
        "lesson_id": lesson_id,
        "verdict": "caution",
    }
