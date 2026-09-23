"""Maria parity hook stub — Stage 2 specialist honesty + future Stages 1/3 entry.

Maria's Telegram path is OpenClaw (not cio_telegram_converse). Until the sibling
Stages 1+3 shared internal-first / Hermes-join library lands, this module is the
Trade-AI-side contract Maria skills must call for specialist honesty.

When the shared entry exists (coordinate via Project store
``internal/impl-openclaw-parity-join-*``), ``try_shared_perspective_entry``
imports it and returns its reply. Until then it returns None and callers keep
using house reads + this Stage 2 scrub only.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No invented grants.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from scripts.lib.specialist_attribution import (
    A2A_DENY_NOTICE,
    AttributionDecision,
    SpecialistRunEvidence,
    scrub_operator_specialist_claims,
)

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "MariaParityHook@v1-stage2"

#: Import path the Stages 1+3 sibling is expected to publish. Do not invent a
#: second LEGEND/footer dialect here — only call that entry when present.
SHARED_INTERNAL_FIRST_MODULE = "scripts.lib.operator_internal_first"
SHARED_INTERNAL_FIRST_ENTRY = "build_perspective_reply"

#: Skill CLI name Maria should exec once the OpenClaw skill is installed
#: (requires openclaw grant to land under ~/.openclaw/skills/).
SKILL_HOOK_COMMAND = (
    "python3 {skill_root}/scripts/specialist_honesty_hook.py "
    "--a2a {a2a} --text-file -"
)


def a2a_off_preamble(*, a2a_enabled: bool) -> str:
    """Return the one-shot A2A-off notice, or empty when A2A is on."""
    if a2a_enabled:
        return ""
    return A2A_DENY_NOTICE


def scrub_maria_outbound(
    text: str,
    *,
    a2a_enabled: bool = False,
    evidence: Sequence[SpecialistRunEvidence] | None = None,
) -> tuple[str, AttributionDecision]:
    """Stage 2: ban Iris/Alex/CIO roleplay on Maria when evidence/A2A missing."""
    return scrub_operator_specialist_claims(
        text,
        surface="maria",
        a2a_enabled=a2a_enabled,
        evidence=evidence,
        inject_a2a_notice=True,
    )


def try_shared_perspective_entry(
    *,
    question: str,
    symbol: Optional[str] = None,
    subject_guid: Optional[str] = None,
    a2a_enabled: bool = False,
    specialist_evidence: Sequence[SpecialistRunEvidence] | None = None,
    **kwargs: Any,
) -> Optional[dict[str, Any]]:
    """Call shared Stages 1+3 entry when sibling library is importable.

    Returns None when the library is not landed yet (this Stage 2 stub alone).
    When present, the shared entry owns house→Hermes→finalize_operator_reply;
    we still scrub specialist claims on the body before return.
    """
    try:
        mod = __import__(SHARED_INTERNAL_FIRST_MODULE, fromlist=[SHARED_INTERNAL_FIRST_ENTRY])
        build = getattr(mod, SHARED_INTERNAL_FIRST_ENTRY, None)
    except Exception:
        return None
    if not callable(build):
        return None
    result = build(
        question=question,
        symbol=symbol,
        subject_guid=subject_guid,
        a2a_enabled=a2a_enabled,
        specialist_evidence=list(specialist_evidence or ()),
        **kwargs,
    )
    if not isinstance(result, dict):
        return None
    body = str(result.get("text") or result.get("body") or "")
    scrubbed, decision = scrub_maria_outbound(
        body, a2a_enabled=a2a_enabled, evidence=specialist_evidence
    )
    result = dict(result)
    result["text"] = scrubbed
    result["body"] = scrubbed
    result["specialist_attribution"] = decision.to_dict()
    result["maria_parity_hook"] = SCHEMA
    return result


__all__ = [
    "A2A_DENY_NOTICE",
    "AUTHORITY",
    "SCHEMA",
    "SHARED_INTERNAL_FIRST_ENTRY",
    "SHARED_INTERNAL_FIRST_MODULE",
    "SKILL_HOOK_COMMAND",
    "a2a_off_preamble",
    "scrub_maria_outbound",
    "try_shared_perspective_entry",
]
