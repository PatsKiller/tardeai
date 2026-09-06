"""LLM-assisted identity resolution — proposes CANDIDATEs, commits nothing.

THE ONE PLACE A MODEL BELONGS IN IDENTITY
-----------------------------------------
5,243 of 10,279 registry entities are UNRESOLVED_WITH_REASON: no CUSIP, so the
deterministic path cannot place them. `catalyst_graph` separately skips 35,928
rows as `symbol_not_registered`. Resolving those means judging whether a symbol
in a filing is the same issuer as one already registered — across name variants,
share classes, ticker reuse after delisting and corporate actions.

That is ambiguity, and ambiguity is what a model is for. Everything else about
identity is a count, a clock or a lookup, and a model there would destroy the
auditability that makes the spine worth having: `uuid5` is a pure function.

PROPOSE, NEVER COMMIT
---------------------
This module returns proposals. It does not write the registry, does not mint a
GUID, and cannot promote anything.

  · output is always `identity_status = "CANDIDATE"`, never CONFIRMED
  · only a CUSIP from a source feed promotes to CONFIRMED, deterministically
  · the registry's rank is one-way (CONFIRMED > CANDIDATE > UNRESOLVED), so a
    proposal can never downgrade a confirmed entity even if the model is wrong
  · a proposal below the confidence floor is dropped rather than written weakly

The failure mode this guards against is the expensive one: a model that sounds
certain, writes a spine, and is believed. A CANDIDATE that is wrong costs a
review. A CONFIRMED that is wrong corrupts every join downstream, permanently,
because GUIDs are supposed to be stable.

FREE LANES ONLY
---------------
Batch reconciliation, not latency-sensitive. `lib/llm_fallback` free chain
(grok, then chatgpt); the paid lane is opt-in and never the default. Local models
are excluded for judgment by NEVER_CHAIN.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

SCHEMA = "IdentityResolutionProposal@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: Below this, a proposal is dropped. A weak guess written as data is worse than
#: no row: it looks like progress and it is read by joins.
MIN_CONFIDENCE = float(os.environ.get("IDENTITY_ADVISOR_MIN_CONFIDENCE", "0.75"))

#: Cap per run. This is a backlog of thousands and an unbounded loop against a
#: shared free lane starves everything else that needs it.
MAX_PER_RUN = int(os.environ.get("IDENTITY_ADVISOR_MAX_PER_RUN", "25"))

#: The only status this module may ever emit.
PROPOSAL_STATUS = "CANDIDATE"

PROMPT = """You are reconciling securities identities. Decide whether the UNRESOLVED
symbol refers to the same ISSUER as one of the candidate registered entities.

Answer ONLY with JSON:
  {"match": "<registered_symbol or null>", "confidence": 0.0-1.0, "reason": "<one sentence>"}

Rules you must follow:
- A ticker is an ALIAS. Tickers are reassigned after delisting, so a matching
  symbol is weak evidence, not proof.
- Different share classes of one issuer ARE the same issuer.
- A fund holding a company is NOT that company.
- If the evidence does not distinguish, answer null. Null is a correct answer and
  is preferred over a guess.

UNRESOLVED: __SUBJECT__
CANDIDATES: __CANDIDATES__
"""
# Substituted with .replace(), not .format(): the prompt contains literal JSON
# braces and str.format reads them as placeholders (KeyError: '"match"').


def _free_chain_call(prompt: str) -> Optional[str]:
    """Free OAuth lanes only. Returns None rather than raising — an advisor that
    breaks the batch when a lane is down is worse than one that yields nothing."""
    try:
        from lib.llm_fallback import generate_with_fallback
    except Exception:
        try:
            from scripts.lib.llm_fallback import generate_with_fallback  # type: ignore
        except Exception:
            return None
    try:
        # allow_paid=False pins this to the FREE chain (grok -> chatgpt). Batch
        # reconciliation has no deadline, so there is no argument for spending.
        res = generate_with_fallback(prompt, lane="grok", allow_paid=False,
                                     process_id="identity_resolution_advisor")
    except Exception:
        return None
    return getattr(res, "text", None) or getattr(res, "output", None) or (
        res if isinstance(res, str) else None)


def _parse(raw: Optional[str]) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        d = json.loads(raw[start:end + 1])
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    conf = d.get("confidence")
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        return None
    return {"match": d.get("match") or None, "confidence": conf,
            "reason": str(d.get("reason") or "")[:300]}


def propose(subject: dict[str, Any], candidates: Iterable[dict[str, Any]],
            *, now: Optional[datetime] = None) -> Optional[dict[str, Any]]:
    """One proposal, or None. Never writes anything."""
    now = now or datetime.now(timezone.utc)
    cands = list(candidates)[:12]
    if not cands:
        return None
    filled = (PROMPT
              .replace("__SUBJECT__", json.dumps(subject, default=str)[:800])
              .replace("__CANDIDATES__", json.dumps(cands, default=str)[:2000]))
    try:
        raw = _free_chain_call(filled)
    except Exception:
        # A lane failure must yield nothing, not abort the batch. This backlog is
        # thousands of rows; one dead provider must not cost the whole run.
        return None
    parsed = _parse(raw)
    if not parsed or not parsed["match"]:
        return None
    if parsed["confidence"] < MIN_CONFIDENCE:
        return None
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        # Structurally impossible to emit CONFIRMED from this module.
        "identity_status": PROPOSAL_STATUS,
        "subject_symbol": subject.get("symbol"),
        "proposed_match": parsed["match"],
        "confidence": parsed["confidence"],
        "reason": parsed["reason"],
        "as_of": now.replace(microsecond=0).isoformat(),
        "requires_operator_review": True,
        "financial_action": False,
        "promotes_to_confirmed": False,
    }
