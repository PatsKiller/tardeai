"""Live Grok critique of one existing VALID artifact. The missing lane.

Contract: docs/ops/CIO_GROK_CRITIQUE_CONTRACT_2026-08-29.md

`research_quality.critique()` stays the deterministic lint and remains the
default everywhere. This module is reached only when a caller explicitly asks
for the live backend, so dry runs, stub runs and every existing test path are
byte-identical to before.

What it does NOT do, by construction:

  * does not attach — it returns a verdict; the caller applies the existing
    attach rules. Attaching here would make the reviewer the approver.
  * does not escalate — a REJECT buys nothing.
  * does not research — one artifact in, one verdict out.
  * does not build a prompt — the curated `grok_critique` template in
    `cio_research_templates` is the single place gate prompts live.
  * does not open an HTTP client — `llm_lane.generate` already owns the proxy,
    the retries and the consumption gate.

Failure posture is closed: any exception, unreachable proxy or unparseable body
yields PARTIAL / attachable=False. Failing closed costs a re-run; failing open
attaches unreviewed research.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

GROK_CRITIQUE_SCHEMA = "GrokCritique@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

# The critique is lane-agnostic by design: it asks "is this artifact
# attachable", not "which vendor has the best opinion". Defaults are the
# pairing the consumption gate actually permits.
#
# grok + maria_research_critique was the first choice and is refused:
# POLICY_NOT_ALLOWED, because no research/critique process lists lane=grok.
# Rather than widen that allowlist — which changes where spend may occur and
# which vendor sees artifact text — the default is the already-authorised
# DeepSeek pairing. The grok constants stay so the swap is one argument the day
# that lane is authorised.
LANE = "deepseek-v4-flash"
PROCESS_ID = "hermes_external_research"
MODEL = None                      # let the lane resolve its own model id

GROK_LANE = "grok"                # authorised: no research process, today
GROK_PROCESS_ID = "maria_research_critique"
GROK_MODEL = "grok-3"

TIMEOUT_S = 90

VALID, PARTIAL, REJECT = "VALID", "PARTIAL", "REJECT"
VERDICTS = (VALID, PARTIAL, REJECT)

# truncated/unparseable may retry once; execution_language never may.
RETRYABLE_ONCE = frozenset({"truncated", "unparseable_response", "transport_error"})
NEVER_RETRYABLE = frozenset({"execution_language", "cost_cap"})

# The gate returns its refusals as free text inside the exception message, so a
# literal set lookup misses them: a COST_CAP_EXCEEDED came back as
# ["transport_error", "COST_CAP_EXCEEDED: global cap"] and was marked retryable,
# which the contract forbids. Retrying a budget stop or a policy refusal is
# asking the same question until a different answer arrives.
_NEVER_RETRYABLE_MARKERS = (
    "cost_cap", "cost_cap_exceeded", "cost_configuration_invalid",
    "policy_not_allowed", "process_not_registered", "execution_language",
    "manual_mode",
)


def _is_retryable(reasons: list[str]) -> bool:
    blob = " ".join(str(r) for r in (reasons or [])).lower()
    if any(m in blob for m in _NEVER_RETRYABLE_MARKERS):
        return False
    return bool(set(reasons or []) & RETRYABLE_ONCE)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result(verdict: str, reasons: list[str], *, execution_language: bool = False,
            attachable: bool = False, cost_usd: float = 0.0,
            **extra: Any) -> dict[str, Any]:
    row = {
        "schema": GROK_CRITIQUE_SCHEMA,
        "verdict": verdict if verdict in VERDICTS else PARTIAL,
        "reasons": list(reasons or []),
        "execution_language": bool(execution_language),
        "attachable": bool(attachable),
        "cost_usd": round(float(cost_usd or 0.0), 6),
        "lane": LANE,
        "process_id": PROCESS_ID,
        "as_of": _utc(),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "retryable": _is_retryable(list(reasons or [])),
    }
    row.update(extra)
    return row


def _parse(text: Any) -> dict[str, Any]:
    """Parse the model body. Unreadable is PARTIAL, never VALID."""
    if isinstance(text, dict):
        body = text
    else:
        raw = str(text or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
            raw = raw.rsplit("```", 1)[0]
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return _result(PARTIAL, ["unparseable_response"])
        try:
            body = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return _result(PARTIAL, ["unparseable_response"])
    if not isinstance(body, dict):
        return _result(PARTIAL, ["unparseable_response"])

    verdict = str(body.get("verdict") or "").upper()
    reasons = [str(r) for r in (body.get("reasons") or [])]
    exec_lang = bool(body.get("execution_language"))
    attachable = bool(body.get("attachable"))

    if verdict not in VERDICTS:
        return _result(PARTIAL, reasons + ["unparseable_response"],
                       execution_language=exec_lang)
    # A tainted artifact is never attachable, whatever the model claims.
    if exec_lang:
        return _result(REJECT, reasons or ["execution_language"],
                       execution_language=True, attachable=False)
    if verdict != VALID:
        attachable = False
    return _result(verdict, reasons, execution_language=False,
                   attachable=attachable)


def critique_live(artifact: dict[str, Any], *, plan_id: Optional[str] = None,
                  research_id: Optional[str] = None,
                  question_ids: Optional[list[str]] = None,
                  generate: Any = None,
                  model: Optional[str] = MODEL,
                  lane: str = LANE,
                  process_id: str = PROCESS_ID) -> dict[str, Any]:
    """One live critique through an authorised lane. `generate` injectable."""
    # Local lint first: if our own matcher already finds an instruction, the
    # artifact is tainted and there is nothing to ask a model about.
    try:
        from scripts.lib.execution_language import find_imperative

        blob = json.dumps(artifact, default=str)
        if find_imperative and find_imperative(blob):
            return _result(REJECT, ["execution_language"],
                           execution_language=True, attachable=False,
                           detected_locally=True, calls_made=0,
                           lane=lane, process_id=process_id)
    except Exception:
        pass

    try:
        from scripts.lib.cio_research_templates import build as build_template

        tpl = build_template("grok_critique", artifact=artifact,
                             question_ids=question_ids or [],
                             research_id=research_id)
    except Exception as exc:                                   # noqa: BLE001
        return _result(PARTIAL, ["template_unavailable", str(exc)[:80]],
                       calls_made=0)

    prompt = tpl["system"] + "\n\n" + tpl["user"]

    if generate is None:
        try:
            from llm_lane import generate as _gen
        except Exception:
            try:
                from scripts.llm_lane import generate as _gen
            except Exception as exc:                           # noqa: BLE001
                return _result(PARTIAL, ["transport_error", str(exc)[:80]],
                               calls_made=0)
        generate = _gen

    # Report the lane/process ACTUALLY used, including on the failure paths.
    # `_result` seeds them from the module defaults, so a refused call on an
    # overridden lane was reporting the default — making a grok refusal read as
    # a deepseek one in the record.
    def _fail(verdict: str, reasons: list[str], **kw: Any) -> dict[str, Any]:
        row = _result(verdict, reasons, **kw)
        row["lane"] = lane
        row["process_id"] = process_id
        return row

    kwargs = {"lane": lane, "timeout": TIMEOUT_S, "process_id": process_id,
              "task_summary": f"research critique {plan_id or ''}".strip(),
              "response_json": True,
              "metadata": {"plan_id": plan_id, "research_id": research_id}}
    if model:
        kwargs["model"] = model
    try:
        text = generate(prompt, **kwargs)
    except Exception as exc:                                    # noqa: BLE001
        return _fail(PARTIAL, ["transport_error", str(exc)[:160]],
                     calls_made=1)

    cost = 0.0
    if isinstance(text, tuple) and len(text) == 2:
        text, prov = text
        cost = float((prov or {}).get("cost_usd") or 0.0)

    out = _parse(text)
    out["cost_usd"] = round(cost, 6)
    out["calls_made"] = 1
    out["plan_id"] = plan_id
    out["research_id"] = research_id
    out["model"] = model
    out["lane"] = lane
    out["process_id"] = process_id
    return out


def to_artifact(result: dict[str, Any], *, artifact_id: str,
                plan_id: Optional[str] = None,
                research_id: Optional[str] = None) -> dict[str, Any]:
    """Render the critique as a SpecialistArtifact row."""
    from scripts.lib.cio_specialist_artifact import build as build_artifact

    outcome = {VALID: "VALID", PARTIAL: "PARTIAL", REJECT: "FAIL"}[
        result.get("verdict", PARTIAL)]
    if result.get("execution_language"):
        outcome = "execution_language"
    return build_artifact(
        artifact_id=artifact_id, provider="grok_critique", outcome=outcome,
        cost_usd=float(result.get("cost_usd") or 0.0), plan_id=plan_id,
        research_id=research_id,
        source_refs=[{"verdict": result.get("verdict"),
                      "reasons": result.get("reasons"),
                      "attachable": result.get("attachable"),
                      "lane": result.get("lane", LANE),
                      "process_id": result.get("process_id", PROCESS_ID)}],
    )
