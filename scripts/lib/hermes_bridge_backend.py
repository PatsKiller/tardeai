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
    from lib.hermes_research_schema import (
        coerce_as_of,
        collect_sources,
        compact_catalyst,
        synthesize_summary,
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
    from scripts.lib.hermes_research_schema import (  # type: ignore
        coerce_as_of,
        collect_sources,
        compact_catalyst,
        synthesize_summary,
    )


DEFAULT_BRIDGE_URL = os.getenv("HERMES_BRIDGE_URL") or os.getenv(
    "CIO_GOVERNED_BRIDGE_URL", "http://127.0.0.1:8766"
)
DEFAULT_MODEL = os.getenv("HERMES_BRIDGE_MODEL", "deepseek-v4-flash")
# Flash often spends budget on reasoning_tokens; keep headroom so content is non-empty
DEFAULT_MAX_TOKENS = int(os.getenv("HERMES_BRIDGE_MAX_TOKENS", "8192"))
DEFAULT_TIMEOUT_S = float(os.getenv("HERMES_BRIDGE_TIMEOUT_S", "180"))


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
        # Use registered advisory_desk caller; process_id hermes_research_job
        # produced non-empty Flash content in host smokes (vs empty with long prompts).
        self.agent = agent or os.getenv("HERMES_BRIDGE_AGENT", "advisory_desk")
        self.task_type = task_type or os.getenv("HERMES_BRIDGE_TASK", "advisory_opinion")
        self.process_id = process_id or os.getenv(
            "HERMES_BRIDGE_PROCESS", "advisory_desk_opinion",
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
        # Keep compact: Flash can spend entire max_tokens on reasoning with long prompts.
        return (
            "Hermes READ_ONLY research for CIO desk. No orders/stops language. "
            "Do not invent portfolio numbers outside context_snapshot. "
            "Use catalyst.events as the event calendar. Cite event_id in citations. "
            "as_of must be today's UTC ISO timestamp, not a historical guess. "
            "Reply with JSON only (no markdown, no preamble). Schema:\n"
            '{"as_of":"ISO","answers":[{"question_id":"","status":"answered|partial|unanswered",'
            '"summary":"","detail":"","confidence":0.0,"citations":[]}],'
            '"findings":[{"id":"","kind":"catalyst|risk|regime|other","severity":"low|medium|high",'
            '"text":"","confidence":0.0}],'
            '"desk_implications":{"suggestion_bias":"hold_with_thesis|hold_cash|review|observe",'
            '"changes_materiality":false,"recommended_revisit":null,"watch_triggers":[],"notes":""},'
            '"limitations":[],"recommendation":"living thesis >=8 sentences",'
            '"classification":"CONFIRMS|STRENGTHENS|WEAKENS|INVALIDATES|NO_NEW_INFO|CONFLICTED|INSUFFICIENT_DATA",'
            '"confidence":0.0,"evidence_as_of":"ISO","evidence":[],"contradictory_evidence":[],'
            '"reason_summary":"","what_changed":[],"what_did_not_change":[],'
            '"research_gaps_remaining":[],"invalidation_triggered":false,'
            '"source_quality":{},"freshness":{},"source_refs":[],"thesis_stance":"HOLD|WATCH|TRIM|AVOID|"}\n'
            "Answer every question_id. Recommendation must compare the standing thesis with new evidence, "
            "not write a first-impression essay. Never reveal chain-of-thought. JSON only."
        )

    def _build_messages(self, request: dict, qs: list[dict]) -> list[dict]:
        # Compact user payload — only fields the model needs
        subject = request.get("subject") or {}
        user_payload = {
            "pin": request.get("thesis_version"),
            "symbol": subject.get("symbol") or request.get("symbol"),
            "situation": subject.get("situation_type") or request.get("situation_type"),
            "questions": [{"id": q["id"], "text": q["text"][:220], "intent": q["intent"]} for q in qs],
            "context": request.get("context_snapshot") or {},
            "catalyst": compact_catalyst(request),
            "criteria": (request.get("success_criteria") or "")[:200]
            if isinstance(request.get("success_criteria"), str)
            else (request.get("success_criteria") or [])[:4],
            "prompt_context": request.get("prompt_context") or {},
        }
        return [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": "JSON only. Request:\n"
                + json.dumps(user_payload, ensure_ascii=False, separators=(",", ":")),
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
        # Prefer outermost JSON object
        if not text.startswith("{"):
            m = re.search(r"\{.*\}", text, re.S)
            if m:
                text = m.group(0)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            # Truncated model output is common when reasoning ate budget — retryable
            if text.lstrip().startswith("{"):
                raise HermesBackendError(
                    f"model JSON truncated/incomplete: {text[:200]}",
                    retryable=True,
                ) from e
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
            if conf_f is not None:
                if conf_f < 0:
                    conf_f = 0.0
                elif conf_f > 1:
                    conf_f = 1.0
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

        draft = {
            "as_of": coerce_as_of(raw.get("as_of") or utc_now_iso()),
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
            "summary": str(raw.get("summary") or "")[:800],
            "evidence_links": raw.get("evidence_links") or [],
            "sources": raw.get("sources") or raw.get("source_urls") or [],
            "recommendation": str(raw.get("recommendation") or "")[:4000],
            "dissent": str(raw.get("dissent") or "")[:4000],
            "confidence": raw.get("confidence"),
            "classification": str(raw.get("classification") or "").upper(),
            "evidence_as_of": raw.get("evidence_as_of") or raw.get("as_of"),
            "evidence": list(raw.get("evidence") or [])[:20],
            "contradictory_evidence": list(raw.get("contradictory_evidence") or [])[:20],
            "reason_summary": str(raw.get("reason_summary") or "")[:800],
            "what_changed": list(raw.get("what_changed") or [])[:12],
            "what_did_not_change": list(raw.get("what_did_not_change") or [])[:12],
            "research_gaps_remaining": list(raw.get("research_gaps_remaining") or [])[:12],
            "invalidation_triggered": bool(raw.get("invalidation_triggered")),
            "source_quality": raw.get("source_quality") if isinstance(raw.get("source_quality"), dict) else {},
            "freshness": raw.get("freshness") if isinstance(raw.get("freshness"), dict) else {},
            "source_refs": list(raw.get("source_refs") or [])[:20],
            "thesis_stance": str(raw.get("thesis_stance") or "")[:40],
            "provider": "governed_bridge",
            "model": self.model,
        }
        draft["summary"] = synthesize_summary(draft, request)
        draft["sources"] = collect_sources(draft, request)
        draft["evidence_links"] = list(draft.get("evidence_links") or draft["sources"])[:20]
        return draft
