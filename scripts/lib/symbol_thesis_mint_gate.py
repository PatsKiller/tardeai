"""Sandbox/paper-trade research → normal CIO symbol thesis.

Paper-trade is a sandbox lane, not a reason to drop a good thesis.
If substantiveness PASSes, mint into the living CIO thesis store.

Still skip empty rows, cost-cap/error rows, and true broker-execution
language. Do not skip because the source said "paper-trade".

READ_ONLY_ADVISORY. No new LLM. No notify.
"""
from __future__ import annotations

import re
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
BLOCK_ERROR = "research_is_error_or_cost_cap"
BLOCK_EMPTY = "no_nonempty_external_research_or_summary_lt_40"
BLOCK_EXEC = "research_is_execution_language"

SANDBOX_WRAPPER_RE = re.compile(
    r"paper[- ]trade proposal"
    r"|pre-approval critique"
    r"|cannot approve, promote, or recommend executing",
    re.I,
)
LIVING_THESIS_RE = re.compile(
    r"(?:My living thesis is that|Living thesis:\s*)(.+)",
    re.I | re.S,
)
ERROR_RE = re.compile(
    r"^\[ERROR\b"
    r"|COST_CAP_EXCEEDED"
    r"|GROK_RUN_FAILED"
    r"|personal-team-blocked"
    r"|SKIPPED_BUDGET",
    re.I,
)
# True broker verbs — not "I cannot recommend executing this sandbox proposal".
EXECUTION_RE = re.compile(
    r"\b(place|submit|send)\b.{0,40}\b(order|buy|sell)\b"
    r"|\bbroker[- ]ready\b"
    r"|\broute to schwab\b",
    re.I,
)
FLOOR_CHARS = 40
PROVENANCE = (
    "Source: sandbox/paper-trade research promoted to CIO symbol thesis. Not an order."
)


def mint_blockers_for_research(text: str | None) -> list[str]:
    """Block empty / error / broker-exec. Paper-trade is not a blocker."""
    t = (text or "").strip()
    if not t or len(t) < FLOOR_CHARS:
        return [BLOCK_EMPTY]
    if t.startswith("[") or ERROR_RE.search(t[:240]):
        return [BLOCK_ERROR]
    if EXECUTION_RE.search(t):
        return [BLOCK_EXEC]
    return []


def sandbox_to_cio_thesis_text(symbol: str, text: str | None) -> str:
    """Move sandbox/paper-trade prose onto the CIO thesis body. No LLM."""
    t = " ".join((text or "").split()).strip()
    if not t:
        return ""
    sym = str(symbol or "").upper()
    if SANDBOX_WRAPPER_RE.search(t):
        m = LIVING_THESIS_RE.search(t)
        if m and len(m.group(0)) >= FLOOR_CHARS:
            t = m.group(0).strip()
        t = re.sub(
            r"^As the external (?:challenge analyst|high-stakes research analyst)[^.]*\.\s*",
            "",
            t,
            flags=re.I,
        )
        t = re.sub(
            r"I cannot approve, promote, or recommend executing this [^.]+\.\s*",
            "",
            t,
            flags=re.I,
        )
        if PROVENANCE.lower() not in t.lower():
            t = f"{t} {PROVENANCE}".strip()
    if sym and not re.search(rf"\b{re.escape(sym)}\b", t, re.I):
        t = f"{sym}: {t}"
    return t


def evaluate_mint_eligibility(
    symbol: str,
    recommendation: str | None,
    dissent: str | None = None,
    evidence: Any = None,
) -> dict[str, Any]:
    """Grade the CIO-facing body. Paper-trade PASS → would_mint, not ignore."""
    from scripts.lib.thesis_substantiveness import (
        grade_text,
        join_research_text,
        mint_state_for,
    )

    rec = recommendation or ""
    joined = join_research_text(rec, dissent, evidence)
    raw_body = joined or rec
    blockers = mint_blockers_for_research(raw_body)
    cio_body = sandbox_to_cio_thesis_text(symbol, raw_body) if not blockers else raw_body
    g = grade_text(str(symbol or "").upper(), cio_body or raw_body)
    raw_state = mint_state_for(g)
    would = raw_state in {"CURRENT", "THIN"} and not blockers
    return {
        "symbol": str(symbol or "").upper(),
        "would_mint": would,
        "would_mint_state": raw_state if would else "SKIP",
        "would_mint_current": would and raw_state == "CURRENT",
        "would_mint_thin": would and raw_state == "THIN",
        "blockers": blockers,
        "raw_state": raw_state,
        "grade": g.get("grade"),
        "cio_body": cio_body if would else "",
        "from_sandbox": bool(SANDBOX_WRAPPER_RE.search(raw_body or "")),
        "authority": AUTHORITY,
        "financial_action": False,
    }
