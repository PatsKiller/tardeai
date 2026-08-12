"""LLM-as-judge + structural judge for Hermes golden tests.

Hard structural asserts stay in tests/hermes_contract.py.
This module scores *quality* drift vs reference/rubric.

CI default: StructuralGoldenJudge (no bridge).
Host/nightly: HERMES_GOLDEN_LLM_JUDGE=1 → BridgeGoldenJudge.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Protocol, runtime_checkable

try:
    from lib.hermes_research_backend import questions_from_request
except ImportError:  # pragma: no cover
    from scripts.lib.hermes_research_backend import questions_from_request  # type: ignore


JUDGE_VERSION = "judge_hermes@v1"
STRUCTURAL_VERSION = "judge_structural@v1"

WEIGHTS = {
    "coverage": 0.20,
    "grounding": 0.20,
    "read_only": 0.20,
    "usefulness": 0.15,
    "agreement": 0.15,
    "calibration": 0.10,
}

_EXEC_RE = re.compile(
    r"\b(buy now|sell now|place stop|enter order|market order|submit order|force fill)\b",
    re.I,
)

SYSTEM_PROMPT = """You are a golden-test judge for Hermes READ_ONLY research outputs.
Score the CANDIDATE against the RUBRIC and the REFERENCE output (if provided).

Rules:
- Do not rewrite the candidate.
- Do not give investment advice.
- Flag execution language as critical_defect.
- Flag invented portfolio numbers not in request.context_snapshot as critical_defect.
- Non-action biases (hold_with_thesis, hold_cash, observe) can score 5 on usefulness.
- If reference is provided, "agreement" means same suggestion_bias direction and no contradictory hard facts — not identical wording.

Return ONLY JSON:
{
  "scores": {
    "coverage": 1-5,
    "grounding": 1-5,
    "read_only": 1-5,
    "usefulness": 1-5,
    "agreement": 1-5,
    "calibration": 1-5
  },
  "rationales": { "coverage": "one line", "grounding": "one line", "read_only": "one line", "usefulness": "one line", "agreement": "one line", "calibration": "one line" },
  "critical_defects": [],
  "summary": "one sentence"
}
"""


def weighted_total(scores: dict[str, Any]) -> float:
    total = 0.0
    for k, w in WEIGHTS.items():
        try:
            v = float(scores.get(k, 1))
        except (TypeError, ValueError):
            v = 1.0
        total += w * max(1.0, min(5.0, v))
    return total


def code_side_defects(candidate: dict[str, Any], request: dict[str, Any] | None = None) -> list[str]:
    """Deterministic critical defects (auto-fail)."""
    defects: list[str] = []
    blob = json.dumps(candidate, ensure_ascii=False).lower()
    if _EXEC_RE.search(blob):
        defects.append("execution_language")

    answers = candidate.get("answers") or []
    if not answers and not (candidate.get("findings") or []) and not candidate.get("summary"):
        defects.append("empty_answers")
    elif answers:
        useful = [
            a for a in answers
            if isinstance(a, dict)
            and a.get("status") in ("answered", "partial")
            and str(a.get("summary") or "").strip()
        ]
        if not useful:
            defects.append("empty_answers")

    # Optional: invented % / $ not present in context_snapshot (soft list, hard if egregious)
    if request:
        ctx = json.dumps(request.get("context_snapshot") or {}, ensure_ascii=False)
        # simple: if summary claims a weight_pct number not in context, flag as inventing
        # only hard-flag when both weight and a number appear that aren't in snapshot text
        pass
    return defects


@runtime_checkable
class GoldenJudge(Protocol):
    def score(
        self,
        *,
        request: dict[str, Any],
        candidate: dict[str, Any],
        reference: dict[str, Any] | None,
        rubric_notes: str = "",
    ) -> dict[str, Any]:
        ...


class StructuralGoldenJudge:
    """No LLM — structural proxy for default CI."""

    def score(
        self,
        *,
        request: dict[str, Any],
        candidate: dict[str, Any],
        reference: dict[str, Any] | None = None,
        rubric_notes: str = "",
    ) -> dict[str, Any]:
        defects = code_side_defects(candidate, request)
        qs = questions_from_request(request)
        qids = {q["id"] for q in qs}
        got = {
            a.get("question_id")
            for a in (candidate.get("answers") or [])
            if isinstance(a, dict)
        }
        if qids and qids <= got:
            coverage = 5
        elif qids and (got & qids):
            coverage = 3
        else:
            coverage = 1

        read_only = 1 if "execution_language" in defects else 5
        agreement = 5
        if reference:
            rb = (reference.get("desk_implications") or {}).get("suggestion_bias")
            cb = (candidate.get("desk_implications") or {}).get("suggestion_bias")
            if rb and cb:
                agreement = 5 if rb == cb else 2
            elif rb and not cb:
                agreement = 2

        scores = {
            "coverage": coverage,
            "grounding": 4,
            "read_only": read_only,
            "usefulness": 3 if not defects else 1,
            "agreement": agreement,
            "calibration": 3,
        }
        return {
            "scores": scores,
            "total": round(weighted_total(scores), 3),
            "rationales": {"note": "structural judge — no LLM"},
            "critical_defects": defects,
            "summary": "structural",
            "judge_prompt_version": STRUCTURAL_VERSION,
        }


class BridgeGoldenJudge:
    """LLM-as-judge via governed bridge (:8766)."""

    def __init__(
        self,
        *,
        bridge_url: str | None = None,
        model: str | None = None,
        timeout_s: float = 90.0,
        max_tokens: int = 4096,
    ):
        self.bridge_url = (
            bridge_url
            or os.getenv("HERMES_JUDGE_BRIDGE_URL")
            or os.getenv("HERMES_BRIDGE_URL")
            or "http://127.0.0.1:8766"
        ).rstrip("/")
        self.model = model or os.getenv("HERMES_JUDGE_MODEL", "deepseek-v4-flash")
        self.timeout_s = timeout_s
        self.max_tokens = max_tokens
        self.agent = os.getenv("HERMES_JUDGE_AGENT", "advisory_desk")
        self.task_type = os.getenv("HERMES_JUDGE_TASK", "advisory_opinion")
        self.process_id = os.getenv("HERMES_JUDGE_PROCESS", "advisory_desk_opinion")

    def score(
        self,
        *,
        request: dict[str, Any],
        candidate: dict[str, Any],
        reference: dict[str, Any] | None,
        rubric_notes: str = "",
    ) -> dict[str, Any]:
        # Always apply code-side defects first
        base_defects = code_side_defects(candidate, request)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": {
                            "authority": request.get("authority"),
                            "thesis_version": request.get("thesis_version"),
                            "subject": request.get("subject"),
                            "questions": request.get("questions"),
                            "context_snapshot": request.get("context_snapshot") or {},
                        },
                        "reference_body": reference,
                        "candidate_body": candidate,
                        "rubric_notes": rubric_notes,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ]
        try:
            content = self._chat(messages)
            data = self._parse_json(content)
        except Exception as e:
            # Fail-soft to structural so CI/host doesn't flake hard when bridge is odd
            fallback = StructuralGoldenJudge().score(
                request=request,
                candidate=candidate,
                reference=reference,
                rubric_notes=rubric_notes,
            )
            fallback["summary"] = f"llm_judge_fallback:{type(e).__name__}:{e}"
            fallback["judge_prompt_version"] = f"{JUDGE_VERSION}+fallback"
            return fallback

        scores = dict(data.get("scores") or {})
        for k in WEIGHTS:
            try:
                scores[k] = max(1, min(5, int(float(scores.get(k, 1)))))
            except (TypeError, ValueError):
                scores[k] = 1
        total = weighted_total(scores)
        defects = list(data.get("critical_defects") or []) + base_defects
        # de-dupe defects
        seen: set[str] = set()
        uniq: list[str] = []
        for d in defects:
            s = str(d)
            if s not in seen:
                seen.add(s)
                uniq.append(s)

        return {
            "scores": scores,
            "total": round(total, 3),
            "rationales": data.get("rationales") or {},
            "critical_defects": uniq,
            "summary": data.get("summary") or "",
            "judge_prompt_version": JUDGE_VERSION,
        }

    def _chat(self, messages: list[dict]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
        }
        req = urllib.request.Request(
            f"{self.bridge_url}/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-TradeAI-Agent": self.agent,
                "X-TradeAI-Task-Type": self.task_type,
                "X-TradeAI-Process-Id": self.process_id,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"judge bridge HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"judge bridge unreachable: {e}") from e

        try:
            msg = obj["choices"][0]["message"]
            content = msg.get("content") or ""
            if not str(content).strip():
                content = msg.get("reasoning_content") or msg.get("reasoning") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"judge unexpected shape: {str(obj)[:200]}") from e
        if not str(content).strip():
            raise RuntimeError("judge empty content")
        return str(content)

    def _parse_json(self, content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                raise
            return json.loads(m.group(0))


def build_golden_judge(*, use_llm: bool | None = None) -> GoldenJudge:
    if use_llm is None:
        use_llm = os.getenv("HERMES_GOLDEN_LLM_JUDGE", "0").strip() in ("1", "true", "yes", "on")
    if use_llm:
        return BridgeGoldenJudge()
    return StructuralGoldenJudge()
