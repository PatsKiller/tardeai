"""Maria parity hook — Stage 2 specialist honesty + Stages 1+3 shared entry.

Maria's Telegram path is OpenClaw (not cio_telegram_converse). This module is
the Trade-AI-side contract Maria skills call for:

  1. Stage 2 — scrub fake Iris/Alex/CIO labels when A2A/evidence missing
  2. Stages 1+3 — ``answer_internal_first`` when
     ``scripts.lib.operator_internal_first`` is importable (sibling join library)

Do not invent a second LEGEND/Sources footer — the shared entry owns finalize.

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

#: Sibling Stages 1+3 API (branch cursor/parity-join-chokepoint-a92b).
SHARED_INTERNAL_FIRST_MODULE = "scripts.lib.operator_internal_first"
SHARED_INTERNAL_FIRST_ENTRY = "answer_internal_first"

#: Skill CLI name Maria should exec once the skill is installed
#: (requires gateway grant to land under the live skills tree).
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


def _result_to_dict(result: Any) -> Optional[dict[str, Any]]:
    if result is None:
        return None
    if hasattr(result, "to_dict") and callable(result.to_dict):
        d = result.to_dict()
        return dict(d) if isinstance(d, dict) else None
    if isinstance(result, dict):
        return dict(result)
    return None


def try_shared_perspective_entry(
    *,
    question: str,
    symbol: Optional[str] = None,
    subject_guid: Optional[str] = None,
    a2a_enabled: bool = False,
    specialist_evidence: Sequence[SpecialistRunEvidence] | None = None,
    chat_id: str = "",
    message_id: str = "",
    channel: str = "skill",
    use_desk: bool = True,
    **kwargs: Any,
) -> Optional[dict[str, Any]]:
    """Call ``answer_internal_first`` when the join library is importable.

    Returns None when ``scripts.lib.operator_internal_first`` is absent (this
    Stage 2 tree alone). When present, the shared entry owns
    house→Hermes→finalize_operator_reply; we still scrub specialist claims on
    the body before return.

    ``symbol`` / ``subject_guid`` are accepted for callers but identity is
    resolved inside ``answer_internal_first`` from ``question`` (same as desk).
    """
    del symbol, subject_guid  # resolved from question text by the shared entry
    try:
        mod = __import__(SHARED_INTERNAL_FIRST_MODULE, fromlist=[SHARED_INTERNAL_FIRST_ENTRY])
        answer = getattr(mod, SHARED_INTERNAL_FIRST_ENTRY, None)
    except Exception:
        return None
    if not callable(answer):
        return None

    hub_finder = kwargs.get("hub_finder")
    dry_run = bool(kwargs.get("dry_run", False))
    try:
        result = answer(
            question,
            chat_id=str(chat_id or ""),
            message_id=str(message_id or ""),
            channel=str(channel or "skill"),
            surface="maria",
            use_desk=bool(use_desk),
            hub_finder=hub_finder,
            dry_run=dry_run,
        )
    except TypeError:
        # Older/partial stub — fail soft to None rather than crash Maria.
        return None
    except Exception:
        return None

    out = _result_to_dict(result)
    if out is None:
        return None

    body = str(out.get("text") or out.get("body") or "")
    scrubbed, decision = scrub_maria_outbound(
        body, a2a_enabled=a2a_enabled, evidence=specialist_evidence
    )
    out["text"] = scrubbed
    out["body"] = scrubbed
    out["specialist_attribution"] = decision.to_dict()
    out["maria_parity_hook"] = SCHEMA
    return out


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
