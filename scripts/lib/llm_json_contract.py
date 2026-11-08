"""Strict JSON contract enforcement for structured model outputs.

``generate_structured`` is the DeepSeek path (its own client). The ``recover_*`` helpers below are
provider-neutral and are the ONE place a response is turned into a JSON object, so a caller on the
governed gateway and a caller on the DeepSeek client cannot disagree about what "valid JSON" means.

Why recovery exists (LQ-20261107-1010). Lanes answer with a well-formed object inside a ```json
fence, or with one sentence before it. Until 2026-11-08 the governed gateway's ``response_json``
check was a bare ``json.loads``: contradiction_adjudicator lost 116 answers in 14 days that way
(``ANTHROPIC_OUTPUT_INVALID``, ``response_chars=0``) — each one already sent and paid for — while
``parse_verdict`` had its own brace-slice that would have read them. Recovery is bounded and
explicit about how it read the text; it never invents a value, and a response with no object in it
is still a failure.
"""
from __future__ import annotations

import json
import re
from typing import Any

from lib.deepseek_client import DeepSeekError, chat, parse_strict_json
from lib.llm_output_schemas import SCHEMA_MODELS, schema_example, validate_process_output

MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"

#: How a response was read, in order of preference. ``strict`` costs nothing; the other two are
#: recoveries and are recorded on the receipt so a lane that needs them is visible.
READ_STRICT = "strict"
READ_FENCED = "fenced"
READ_EMBEDDED = "embedded"

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


class JsonContractError(ValueError):
    """The response carries no JSON object this module is willing to read."""

    def __init__(self, reason: str, text: str = ""):
        self.reason = reason
        self.excerpt = (text or "")[:200]
        super().__init__(f"{reason}: {self.excerpt}")


def _as_object(value: Any, text: str) -> dict:
    if not isinstance(value, dict):
        raise JsonContractError("json_root_not_object", text)
    return value


def recover_json_object(text: str, *, allow_embedded: bool = True) -> tuple[dict, str]:
    """Read one JSON object out of a model answer. Returns ``(object, how)``.

    ``strict`` — the whole answer is the object.
    ``fenced`` — the answer is one ```json fence (the fence markers are not JSON).
    ``embedded`` — the answer has prose around the outermost ``{...}``.

    Raises :class:`JsonContractError` when none of those yields an object. A caller that must not
    accept prose-stripped answers passes ``allow_embedded=False``.
    """
    raw = "" if text is None else str(text)
    t = raw.strip()
    if not t:
        raise JsonContractError("json_empty", raw)
    try:
        return _as_object(json.loads(t), raw), READ_STRICT
    except (ValueError, TypeError):
        pass
    m = _FENCE.search(t)
    if m:
        try:
            return _as_object(json.loads(m.group(1).strip()), raw), READ_FENCED
        except (ValueError, TypeError):
            pass
    if allow_embedded:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            try:
                return _as_object(json.loads(t[start:end + 1]), raw), READ_EMBEDDED
            except (ValueError, TypeError):
                pass
    raise JsonContractError("json_unreadable", raw)


def is_json_response(text: str, *, allow_embedded: bool = True) -> bool:
    """True when :func:`recover_json_object` would read an object. Never raises."""
    try:
        recover_json_object(text, allow_embedded=allow_embedded)
        return True
    except JsonContractError:
        return False


def generate_structured(
    *,
    policy: str,
    prompt: str,
    schema_id: str,
    timeout: float = 90.0,
    operator_confirmed: bool = False,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    """One primary attempt + one bounded repair. No silent fallback."""
    if schema_id not in SCHEMA_MODELS:
        raise DeepSeekError(MODEL_OUTPUT_INVALID, f"unknown schema_id {schema_id}")

    example = schema_example(schema_id)
    full_prompt = (
        f"{prompt.strip()}\n\n"
        f"Return a single JSON object only (response_format=json_object). "
        f"schema_id must be {schema_id!r}. Example:\n"
        f"{json.dumps(example)}\n"
    )

    attempts: list[dict[str, Any]] = []
    last_err: str | None = None
    resp = chat(
        policy=policy,
        prompt=full_prompt,
        response_json=True,
        timeout=timeout,
        operator_confirmed=operator_confirmed,
        max_tokens=max_tokens,
    )
    attempts.append(resp.to_dict())
    if not resp.ok:
        raise DeepSeekError(resp.error_class or MODEL_OUTPUT_INVALID, resp.error_message or "provider failed")

    try:
        data = parse_strict_json(resp.content)
        validated = validate_process_output(schema_id, data)
        return {
            "ok": True,
            "data": validated,
            "schema_id": schema_id,
            "attempts": 1,
            "provenance": resp.to_dict(),
        }
    except Exception as e:
        last_err = str(e)[:400]

    # Bounded single repair
    repair_prompt = (
        f"Your previous response failed validation for schema {schema_id}.\n"
        f"Errors: {last_err}\n"
        f"Return corrected JSON only. Example:\n{json.dumps(example)}\n"
        f"Original task:\n{prompt.strip()}\n"
    )
    resp2 = chat(
        policy=policy,
        prompt=repair_prompt,
        response_json=True,
        timeout=timeout,
        operator_confirmed=operator_confirmed,
        max_tokens=max_tokens,
    )
    attempts.append(resp2.to_dict())
    if not resp2.ok:
        raise DeepSeekError(MODEL_OUTPUT_INVALID, f"repair failed: {resp2.error_class}")
    try:
        data2 = parse_strict_json(resp2.content)
        validated2 = validate_process_output(schema_id, data2)
        return {
            "ok": True,
            "data": validated2,
            "schema_id": schema_id,
            "attempts": 2,
            "provenance": resp2.to_dict(),
            "repair_used": True,
        }
    except Exception as e:
        raise DeepSeekError(MODEL_OUTPUT_INVALID, f"repair validation failed: {e}") from e
