"""BridgeHermesResearchBackend — production research via governed bridge.

Same egress pattern as CIO enrichment (:8766 /v1/chat/completions).
Returns unstamped result body for HermesWorker. No Telegram, no broker orders.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

try:
    from lib.hermes_research_backend import (
        HermesBackendError,
        assert_no_execution_language,
        empty_answer,
        normalize_desk_bias,
        questions_from_request,
        utc_now_iso,
    )
except ImportError:  # pragma: no cover
    from scripts.lib.hermes_research_backend import (  # type: ignore
        HermesBackendError,
        assert_no_execution_language,
        empty_answer,
        normalize_desk_bias,
        questions_from_request,
        utc_now_iso,
    )


DEFAULT_BRIDGE_URL = os.getenv("HERMES_BRIDGE_URL") or os.getenv(
    "CIO_GOVERNED_BRIDGE_URL", "http://127.0.0.1:8766"
)
DEFAULT_MODEL = os.getenv("HERMES_BRIDGE_MODEL", "deepseek-v4-flash")
DEFAULT_MAX_TOKENS = int(os.getenv("HERMES_BRIDGE_MAX_TOKENS", "1800"))
DEFAULT_TIMEOUT_S = float(os.getenv("HERMES_BRIDGE_TIMEOUT_S", "120"))


class BridgeHermesResearchBackend:
    """
    Hermes research via governed bridge (:8766 by default).

    - READ_ONLY_ADVISORY only
    - No Telegram, no broker order APIs
    - Returns unstamped result body for HermesWorker
    """

    def __init__(
        self,
        *,
        bridge_url: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        timeout_s: float | None = None,
        agent: str | None = None,
        task_type: str | None = None,
        process_id: str | None = None,
    ):
        self.bridge_url = (bridge_url or DEFAULT_BRIDGE_URL).rstrip("/")
        self.model = model or DEFAULT_MODEL
        self.max_tokens = max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS
        self.timeout_s = timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S
        # Prefer advisory_desk if hermes_research not yet on registry
        self.agent = agent or os.getenv("HERMES_BRIDGE_AGENT", "advisory_desk")
        self.task_type = task_type or os.getenv("HERMES_BRIDGE_TASK", "advisory_opinion")
        self.process_id = process_id or os.getenv(
            "HERMES_BRIDGE_PROCESS", "hermes_research_job",
        )

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        if (request.get("authority") or "") != "READ_ONLY_ADVISORY":
            raise HermesBackendError("authority must be READ_ONLY_ADVISORY", retryable=False)

        qs = questions_from_request(request)
        if not qs:
            raise HermesBackendError("no questions", retryable=False)

        messages = self._build_messages(request, qs)
        try:
            raw_text = self._chat_completions(messages)
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                body = str(e)
            retryable = e.code in (408, 429, 500, 502, 503, 504)
            raise HermesBackendError(
                f"bridge HTTP {e.code}: {body}", retryable=retryable,
            ) from e
        except urllib.error.URLError as e:
            raise HermesBackendError(f"bridge unreachable: {e}", retryable=True) from e
        except TimeoutError as e:
            raise HermesBackendError(str(e), retryable=True) from e

        parsed = self._parse_json_content(raw_text)
        body = self._normalize_body(parsed, request, qs)

        texts = [a.get("summary") or "" for a in body.get("answers") or []]
        texts += [a.get("detail") or "" for a in body.get("answers") or []]
        texts += [f.get("text") or "" for f in body.get("findings") or []]
        notes = (body.get("desk_implications") or {}).get("notes") or ""
        texts.append(notes)
        assert_no_execution_language(*texts)

        if not body.get("as_of"):
            body["as_of"] = utc_now_iso()
        return body

    def _system_prompt(self) -> str:
        return (
            "You are Hermes, a READ_ONLY research worker for a CIO advisory desk.\n"
            "You never recommend placing orders or stops. You never invent portfolio "
            "weights, cash, or prices not present in context_snapshot.\n"
            "Answer EACH question separately. Prefer evidence and uncertainty over hype.\n"
            "Return ONLY valid JSON with keys:\n"
            "  as_of (ISO timestamp),\n"
            "  answers: [{question_id, status, summary, detail, confidence, citations}],\n"
            "  findings: [{id, kind, severity, text, confidence}],\n"
            "  desk_implications: {suggestion_bias, changes_materiality, "
            "recommended_revisit, watch_triggers, notes},\n"
            "  limitations: [string]\n"
            "status for answers: answered | partial | unanswered\n"
            "suggestion_bias: hold_with_thesis | hold_cash | review | observe\n"
            "confidence: 0..1 when known\n"
            "kind: catalyst | risk | regime | other\n"
            "severity: low | medium | high\n"
        )

    def _build_messages(self, request: dict, qs: list[dict]) -> list[dict]:
        user_payload = {
            "research_id": request.get("research_id"),
            "plan_id": request.get("plan_id"),
            "thesis_version": request.get("thesis_version"),
            "stance": request.get("stance"),
            "subject": request.get("subject") or {},
            "trigger": request.get("trigger") or {},
            "priority": request.get("priority"),
            "questions": qs,
            "success_criteria": request.get("success_criteria") or [],
            "context_snapshot": request.get("context_snapshot") or {},
            "constraints": {
                "read_only": True,
                "no_order_language": True,
                **(request.get("constraints") or {}),
            },
        }
        return [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": (
                    "Research request JSON follows. Answer every question_id.\n\n"
                    + json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
                ),
            },
        ]

    def _chat_completions(self, messages: list[dict]) -> str:
        url = f"{self.bridge_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.2,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-TradeAI-Agent": self.agent,
                "X-TradeAI-Task-Type": self.task_type,
                "X-TradeAI-Process-Id": self.process_id,
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HermesBackendError(
                f"bridge non-JSON response: {raw[:200]}", retryable=False,
            ) from e

        try:
            msg = obj["choices"][0]["message"]
            content = msg.get("content") or ""
            if not str(content).strip():
                content = msg.get("reasoning_content") or msg.get("reasoning") or ""
        except (KeyError, IndexError, TypeError) as e:
            raise HermesBackendError(
                f"bridge unexpected shape: {str(obj)[:200]}", retryable=False,
            ) from e

        if content is None or str(content).strip() == "":
            raise HermesBackendError("bridge empty content", retryable=True)
        return str(content)

    def _parse_json_content(self, content: str) -> dict:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                raise HermesBackendError(
                    f"model content not JSON: {text[:200]}", retryable=False,
                )
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError as e:
                raise HermesBackendError(
                    f"model content not JSON: {text[:200]}", retryable=False,
                ) from e
        if not isinstance(obj, dict):
            raise HermesBackendError("model JSON root must be object", retryable=False)
        return obj

    def _normalize_body(
        self, raw: dict, request: dict, qs: list[dict],
    ) -> dict[str, Any]:
        by_id: dict[str, dict] = {}
        for a in raw.get("answers") or []:
            if isinstance(a, dict) and a.get("question_id"):
                by_id[str(a["question_id"])] = a

        answers = []
        for q in qs:
            a = by_id.get(q["id"])
            if not a:
                answers.append(empty_answer(q["id"], reason="backend omitted question"))
                continue
            conf = a.get("confidence")
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None
            status = (a.get("status") or "answered").lower()
            if status not in ("answered", "partial", "unanswered"):
                status = "partial"
            answers.append({
                "question_id": q["id"],
                "status": status,
                "summary": str(a.get("summary") or "")[:1000],
                "detail": str(a.get("detail") or "")[:4000],
                "confidence": conf_f,
                "citations": a.get("citations") or [],
            })

        findings = []
        for i, f in enumerate(raw.get("findings") or []):
            if not isinstance(f, dict):
                continue
            findings.append({
                "id": str(f.get("id") or f"f{i+1}"),
                "kind": str(f.get("kind") or "other"),
                "severity": str(f.get("severity") or "low"),
                "text": str(f.get("text") or "")[:1000],
                "confidence": f.get("confidence"),
            })

        di = raw.get("desk_implications") if isinstance(raw.get("desk_implications"), dict) else {}
        bias = normalize_desk_bias(di.get("suggestion_bias"))
        symbol = (request.get("subject") or {}).get("symbol") or request.get("symbol")

        return {
            "as_of": raw.get("as_of") or utc_now_iso(),
            "symbol": symbol,
            "thesis_version_at_request": request.get("thesis_version"),
            "answers": answers,
            "findings": findings,
            "desk_implications": {
                "suggestion_bias": bias,
                "changes_materiality": bool(di.get("changes_materiality", False)),
                "recommended_revisit": di.get("recommended_revisit"),
                "watch_triggers": di.get("watch_triggers") or [],
                "notes": str(di.get("notes") or "")[:1000],
            },
            "limitations": [str(x) for x in (raw.get("limitations") or [])][:20],
            "evidence_links": raw.get("evidence_links") or [],
        }
