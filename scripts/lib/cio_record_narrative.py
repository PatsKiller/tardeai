"""The Command Center renders the record's narrative. It does not call a model.

Slice C. `cio_run` stays a DETERMINISTIC_PRODUCT: the narrative blob is an
INPUT it renders, exactly like a number. The agent wrote the prose earlier, in
its own governed lane, and the record carries it forward — which is what lets
the desk say "the operator deferred this" on a page that never asks an LLM
anything.

Fallback is deterministic and never blank. A page that empties itself when
memory is missing teaches the reader that memory is optional.

THE CASH LETTER is the constrained one. SLEEVE:CASH is the $630k question and
the easiest place for an advisory surface to drift into instruction, so its
shape is enforced rather than requested:

  * option_ids restricted to hold_cash | stage_into_X | wait_until_month
  * standalone_sell is always False
  * "deploy $N into TICKER" is refused by a guard, not by a prompt
  * it must cite next_eligible_at, so the reader can see when the desk
    intends to look again
  * it carries a regime hash, so "did this change?" is answerable

MBI_BEHAVIOR=0. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.cio_instrument_record import (
    CASH_SLEEVE,
    content_hash,
    normalize_writer_author,
)

SCHEMA = "CashSleeveLetter@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0

CASH_OPTION_IDS = ("hold_cash", "stage_into_X", "wait_until_month")

# A dollar amount pointed at a ticker is an instruction wearing a letter's
# clothes. Refused in code because prompts do not hold.
_DEPLOY_INTO_TICKER = re.compile(
    r"(?i)\b(?:deploy|buy|allocate|put|move)\b[^.]{0,40}?"
    r"\$?\s*[\d,]{3,}[^.]{0,30}?\b(?:into|to)\b\s+[A-Z]{1,5}\b")


class InstructionInLetter(ValueError):
    """The cash letter tried to tell the operator to move money."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def assert_no_instruction(text: str) -> None:
    m = _DEPLOY_INTO_TICKER.search(str(text or ""))
    if m:
        raise InstructionInLetter(
            f"cash letter may not direct capital at a symbol: {m.group(0)!r}")


def regime_summary(
    *,
    capital_plan: Optional[dict[str, Any]] = None,
    seasonality: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """The regime the letter is written against. Context, never a trigger."""
    cp = capital_plan or {}
    sea = seasonality or {}
    month = (sea.get("month") or {}) if isinstance(sea.get("month"), dict) else {}
    cyc = (sea.get("presidential_cycle") or {}) if isinstance(
        sea.get("presidential_cycle"), dict) else {}
    out = {
        "cash_posture": cp.get("cash_posture"),
        "month": month.get("month_name"),
        "month_bucket": month.get("hypothesis_bucket"),
        "worst_six_months_window": month.get("worst_six_months_window"),
        "cycle_label": cyc.get("cycle_label"),
        "calendar_effects": list(sea.get("calendar_effects") or [])[:3],
        "role": "risk_modifier_or_context",
    }
    out["regime_hash"] = content_hash(
        {k: v for k, v in out.items() if k != "regime_hash"})
    return out


def _cash_letter_as_of(capital_plan, now):
    """The age of the money in this letter, or None. Never the build clock.

    Reads the capital plan's own cash evidence -- the same derivation the operator
    product and the freshness board use -- so the letter cannot disagree with the
    block it describes. An unstamped or missing plan yields None, a visible absence,
    because "we do not know how old this is" and "it is current" are different
    statements and only one of them is honest here.
    """
    ev = (capital_plan or {}).get("cash_as_of")
    if isinstance(ev, dict):
        return None if ev.get("unstamped") else ev.get("as_of")
    return ev or None


def build_cash_letter(
    record: Optional[dict[str, Any]],
    *,
    capital_plan: Optional[dict[str, Any]] = None,
    seasonality: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """The SLEEVE:CASH letter. Present even when notify is off."""
    now = now or _now()
    rec = record or {}
    cp = capital_plan or {}
    regime = regime_summary(capital_plan=cp, seasonality=seasonality)

    cash_usd = rec.get("cash_usd")
    if cash_usd is None:
        cash_usd = cp.get("cash_total_usd")

    narrative = rec.get("cc_narrative") or {}
    what = str(narrative.get("what") or "").strip()
    if not what:
        # Deterministic fallback — never a blank page.
        what = (f"Cash sleeve {cash_usd:,.2f}." if isinstance(cash_usd, (int, float))
                else "Cash sleeve: DATA_UNAVAILABLE — no cash figure attached.")

    month_ctx = (
        f"{regime.get('month') or 'month'} "
        f"({regime.get('month_bucket') or 'no reproduced bucket'})"
        + (" · worst-six-months window" if regime.get("worst_six_months_window") else "")
    )

    # Passthrough: writer names the author, never the migration copy step.
    stamps = normalize_writer_author(
        writer=narrative.get("writer") or "deterministic_fallback",
        author=narrative.get("author"),
    )
    letter = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "subject_key": CASH_SLEEVE,
        "cash_usd": cash_usd,
        "cash_source": rec.get("cash_source") or cp.get("cash_source"),
        "cash_investable_usd": cp.get("cash_investable_usd"),
        "regime": regime,
        "month_context": month_ctx,
        "what": what,
        "option_ids": list(CASH_OPTION_IDS),
        "recommendation_option_id": (
            narrative.get("recommendation_option_id")
            if narrative.get("recommendation_option_id") in CASH_OPTION_IDS
            else "hold_cash"),
        "standalone_sell": False,
        "financial_action": False,
        "next_eligible_at": rec.get("next_eligible_at"),
        "writer": stamps["writer"],
        "author": stamps["author"],
        # PP2. This was `now.isoformat()` -- the build clock, printed directly beside
        # the cash figure, so a balance last confirmed weeks ago read as of this
        # second. `as_of` on a cash letter is the age of the dollars above it; the
        # moment the letter was composed is a separate field and is kept.
        "as_of": _cash_letter_as_of(cp, now),
        "cash_as_of": cp.get("cash_as_of"),
        "composed_at": now.isoformat(),
        "from_record": bool(record),
    }
    if stamps.get("copy_step"):
        letter["copy_step"] = stamps["copy_step"]
    elif narrative.get("copy_step"):
        letter["copy_step"] = narrative.get("copy_step")
    # The guard runs on what actually reaches the reader.
    assert_no_instruction(" ".join(str(letter[k]) for k in ("what", "month_context")))
    return letter


def narrative_for(
    subject_key: str,
    *,
    store: Any = None,
    fallback: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Prefer the record's narrative; fall back deterministically."""
    rec = None
    if store is not None:
        try:
            rec = store.load(subject_key)
        except Exception:                                        # noqa: BLE001
            rec = None
    nar = (rec or {}).get("cc_narrative")
    if nar and str(nar.get("what") or "").strip():
        out = dict(nar)
        out["from_record"] = True
        out["subject_key"] = subject_key
        out["next_eligible_at"] = (rec or {}).get("next_eligible_at")
        stamps = normalize_writer_author(
            writer=out.get("writer"), author=out.get("author"))
        out["writer"] = stamps["writer"]
        out["author"] = stamps["author"]
        if stamps.get("copy_step"):
            out["copy_step"] = stamps["copy_step"]
        return out
    if fallback:
        out = dict(fallback)
        out["from_record"] = False
        out["subject_key"] = subject_key
        stamps = normalize_writer_author(
            writer=out.get("writer"), author=out.get("author"))
        out["writer"] = stamps["writer"]
        out["author"] = stamps["author"]
        if stamps.get("copy_step"):
            out["copy_step"] = stamps["copy_step"]
        return out
    return None


def record_narratives(store: Any, *, kinds: tuple[str, ...] = ("HELD", "EXIT", "WATCH", "SECTOR")) -> dict[str, Any]:
    """{subject_key: narrative} for every record that carries prose."""
    out: dict[str, Any] = {}
    try:
        rows = store.all()
    except Exception:                                            # noqa: BLE001
        return out
    for rec in rows:
        if str(rec.get("kind") or "").upper() not in kinds:
            continue
        nar = rec.get("cc_narrative") or {}
        if not str(nar.get("what") or "").strip():
            continue
        key = str(rec.get("subject_key"))
        stamps = normalize_writer_author(
            writer=nar.get("writer"), author=nar.get("author"))
        row = {
            "subject_key": key,
            "kind": rec.get("kind"),
            "symbols": rec.get("symbols") or [],
            "what": nar.get("what"),
            "thesis_fit": nar.get("thesis_fit"),
            "recommendation_option_id": nar.get("recommendation_option_id"),
            "risks": list(nar.get("risks") or [])[:4],
            "writer": stamps["writer"],
            "author": stamps["author"],
            "as_of": nar.get("as_of"),
            "next_eligible_at": rec.get("next_eligible_at"),
            "next_research_question": rec.get("next_research_question"),
            "notify_priority": rec.get("notify_priority"),
            "from_record": True,
        }
        if stamps.get("copy_step") or nar.get("copy_step"):
            row["copy_step"] = stamps.get("copy_step") or nar.get("copy_step")
        out[key] = row
    return out
