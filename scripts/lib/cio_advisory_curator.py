"""DeepSeek curates the PRESENTATION of an advisory. It may not touch the facts.

The deterministic renderer produces correct but unreadable output: a wall of
sections, detector strings, and repeated blocks. Curation is a legitimate use of
a model — arranging what is already true — and an illegitimate one is letting it
restate the book.

So the contract is narrow and enforced in code, not in the prompt:

  * every numeric token in the output must already appear in the input.
    A model that invents, rounds, or "corrects" a figure is REJECTED.
  * the plan_id must survive, or the operator cannot act on the message.
  * no growth: curation compresses; a longer result means it added something.

Any violation, any exception, any empty response returns the DETERMINISTIC
message unchanged. Fail-open is right here and fail-closed is wrong: the input
is already correct and already sent-worthy, so the worst acceptable outcome is
the ugly version, never no version and never an invented one.

OFF unless CIO_ADVISORY_CURATOR=1. READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

SCHEMA = "AdvisoryCuration@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
LANE = "agent_narrative"          # existing FAST lane; no new governance invented
MODEL = "deepseek-v4-flash"

# Digit runs, so 630,784.82 / 42.1pct / desk@v4 / 2026-08-30 all normalise.
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

SYSTEM = (
    "You reformat an existing investment desk advisory for a phone screen. "
    "You are a typesetter and editor, not an analyst.\n"
    "HARD RULES (violating any one voids the result):\n"
    "1. Never introduce a number, ticker, date, percentage or claim absent from "
    "the input. Never round, recompute or 'correct' one. Copy them exactly.\n"
    "2. Never add analysis, opinion or a recommendation of your own.\n"
    "3. Keep the authority footer and the READ_ONLY marker verbatim.\n"
    "4. Keep the plan id and any links exactly.\n"
    "WHAT TO DO:\n"
    "- Open with the single decision the reader faces and the recommended "
    "option, in one short line.\n"
    "- Then the evidence that drives it, as terse bullets.\n"
    "- Merge sections that repeat each other. Delete filler, restated jargon "
    "and any 'detector flags' noise that carries no meaning for a human.\n"
    "- Convert raw key=value blobs into plain phrases, keeping the values.\n"
    "- Aim for roughly half the original length. Shorter is better as long as "
    "no fact is lost.\n"
    "Return only the reformatted message, no preamble."
)


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUM_RE.finditer(text or "")}


def enabled() -> bool:
    return os.environ.get("CIO_ADVISORY_CURATOR", "").strip().lower() in (
        "1", "true", "yes", "on")


def validate(original: str, curated: str, *, plan_id: str | None = None) -> Optional[str]:
    """Return a rejection reason, or None when the curation is safe to send."""
    if not curated or not curated.strip():
        return "empty"
    invented = _numbers(curated) - _numbers(original)
    if invented:
        return "invented_numbers:" + ",".join(sorted(invented)[:5])
    if plan_id and plan_id not in curated:
        return "dropped_plan_id"
    # The authority marker is the whole basis on which the operator reads this
    # as advice and not instruction. The first live curation quietly dropped it.
    if "READ_ONLY" in (original or "") and "READ_ONLY" not in curated:
        return "dropped_authority_marker"
    if len(curated) > len(original):
        return "grew"
    return None


def curate(
    text: str,
    *,
    plan_id: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Return {"text": ..., "curated": bool, "reason": ...}. Never raises."""
    out = {"schema": SCHEMA, "authority": AUTHORITY, "text": text,
           "curated": False, "reason": None, "model": MODEL}
    if not enabled():
        out["reason"] = "disabled"
        return out
    if not text or not text.strip():
        out["reason"] = "empty_input"
        return out
    try:
        try:
            from scripts.lib.deepseek_client import chat
        except Exception:
            from lib.deepseek_client import chat          # type: ignore
        resp = chat(
            model_id=MODEL,
            prompt=text,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": text}],
            max_tokens=1400,
            temperature=0.2,
            timeout=timeout,
            source_service="cio",
            source_process="cio_advisory_curator",
            source_lane=LANE,
            agent="maria",
        )
        content = ""
        for attr in ("content", "text", "message"):
            v = getattr(resp, attr, None)
            if isinstance(v, str) and v.strip():
                content = v
                break
        if not content and isinstance(resp, dict):
            content = str(resp.get("content") or "")
        reason = validate(text, content, plan_id=plan_id)
        if reason:
            out["reason"] = "rejected:" + reason
            return out
        out["text"] = content.strip()
        out["curated"] = True
        out["reason"] = "ok"
        return out
    except Exception as exc:                                    # noqa: BLE001
        out["reason"] = "error:" + exc.__class__.__name__
        return out
