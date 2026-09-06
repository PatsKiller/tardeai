"""Tag INBOUND operator questions with the same identity spine as discovery.

WHY
---
Audited 2026-09-06: identity tagging was **one-way**. Research and news carry
subject_guid / issuer_guid / gics_sector. The inbound path carried nothing —

    cio_telegram_bot.py             identity_registry=0  subject_guid=0
    telegram_callback_handler.py    identity_registry=0  subject_guid=0
    run_telegram_callback_poller.py identity_registry=0  subject_guid=0

— and inbound messages were not stored at all, only a checkpoint of the last
`update_id`. So "Alex, what's the analyst target for Visa, and where's support?"
produced nothing tagged, nothing persisted, nothing joinable. The agent could not
later know the question had been asked, and the answer could not be attached to
the same issuer as the research that would inform it.

WHAT RESOLVES, AND WHAT HONESTLY DOES NOT
-----------------------------------------
`V` resolves. **`VISA` does not.** The registry holds ticker aliases only — no
company-name index exists anywhere in the system (12 of 8,633
intelligence_entities have a real display_name, and those are planning concepts).

So this module resolves TICKERS deterministically and records everything else as
an explicit unresolved mention rather than dropping it. A name like "Visa" is
genuine ambiguity, which is `identity_resolution_advisor`'s job — it proposes a
CANDIDATE, and only a deterministic identifier ever promotes to CONFIRMED.

Recording the unresolved mention matters: it is the measurement of how much of
the operator's actual vocabulary the spine cannot yet reach.

NO MODEL RUNS HERE
------------------
Extraction is a regex; resolution is a registry lookup. The advisor is a separate,
opt-in step so that a tag written by this module is always deterministic.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA = "InboundIdentityTag@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: $TICKER is unambiguous intent. Bare uppercase runs are candidates only and are
#: never trusted without a registry hit — "CIO", "ETF" and "OK" are not symbols.
_CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z.\-]{0,6})\b")
_BARE = re.compile(r"\b([A-Z][A-Z.\-]{0,6})\b")

#: Words that look like tickers and are not. Without this the first question
#: containing "CIO" or "ETF" tags a security. Registry membership already filters
#: most of it; this covers the collisions that ARE real symbols but are far more
#: likely to be the English word in an operator sentence.
_STOPWORDS = frozenset({
    "A", "I", "IT", "BE", "SO", "ON", "OR", "AT", "BY", "DO", "GO", "IF", "IN",
    "IS", "MY", "NO", "OF", "TO", "UP", "US", "WE", "AN", "AS", "AM", "ALL",
    "AND", "ANY", "ARE", "BUT", "CAN", "FOR", "GET", "HAS", "HOW", "NEW", "NOW",
    "OUT", "SEE", "THE", "WHY", "YOU", "CEO", "CFO", "CIO", "ETF", "IPO", "USD",
    "EPS", "PE", "RSI", "ATR", "AI", "OK", "PM", "AM", "EST", "EDT", "UTC",
})

#: Topics an operator asks about. Recorded so a later reader knows WHAT was asked
#: about the issuer, not merely that it was mentioned.
_TOPICS = (
    ("analyst_target", re.compile(r"\banalyst|price target|pt\b|target price", re.I)),
    ("support_resistance", re.compile(r"\bsupport\b|\bresistance\b|\bs/r\b", re.I)),
    ("earnings", re.compile(r"\bearnings\b|\bquarter\b|\bq[1-4]\b|\beps\b", re.I)),
    ("valuation", re.compile(r"\bvaluation\b|\bp/e\b|\bmultiple\b", re.I)),
    ("position", re.compile(r"\bposition\b|\bhow much\b|\bshares\b|\bcost basis\b", re.I)),
    ("risk", re.compile(r"\bstop\b|\brisk\b|\bdownside\b|\bexposure\b", re.I)),
)


def extract_topics(text: str) -> list[str]:
    return [name for name, rx in _TOPICS if rx.search(text or "")]


#: Title-Case words that are almost never a company in an operator sentence.
#: Without this, "Alex" and "What" become unresolved mentions and the measurement
#: becomes noise instead of a signal.
_NAME_STOPWORDS = frozenset({
    "Alex", "Maria", "Steph", "Hermes", "Iris", "Claude", "Telegram",
    "What", "Where", "When", "Why", "How", "Who", "Which", "Is", "Are", "Can",
    "Should", "Would", "Could", "Do", "Does", "Did", "Give", "Show", "Tell",
    "Please", "Thanks", "Hey", "Hi", "Also", "And", "But", "The", "This",
    "Today", "Tomorrow", "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
})

#: A capitalised word mid-sentence is a plausible company NAME. It cannot be
#: resolved — no company-name index exists in this system — but it must still be
#: COUNTED, because "Visa" is what an operator actually types and pretending the
#: question had no subject makes coverage look better than it is.
_NAME_LIKE = re.compile(r"\b([A-Z][a-z]{2,15})\b")


def extract_name_mentions(text: str) -> list[str]:
    out: list[str] = []
    for m in _NAME_LIKE.finditer(text or ""):
        w = m.group(1)
        if w in _NAME_STOPWORDS or w in out:
            continue
        out.append(w)
    return out


def extract_candidates(text: str) -> list[str]:
    """Cashtags first (explicit intent), then bare uppercase runs."""
    if not text:
        return []
    out: list[str] = []
    for m in _CASHTAG.finditer(text):
        s = m.group(1).upper()
        if s not in out:
            out.append(s)
    for m in _BARE.finditer(text):
        s = m.group(1).upper()
        if s in _STOPWORDS or s in out:
            continue
        out.append(s)
    return out


def tag_inbound(text: str, *, registry: Optional[dict[str, Any]] = None,
                now: Optional[datetime] = None) -> dict[str, Any]:
    """Resolve an inbound message to identity tags. Writes nothing.

    Returns resolved tags AND unresolved mentions — the second is the honest
    measurement of what the spine cannot reach, and dropping it would make
    coverage look better than it is.
    """
    from lib import research_identity as RI  # noqa: PLC0415

    now = now or datetime.now(timezone.utc)
    doc = registry if registry is not None else RI.load_registry()
    resolved: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for cand in extract_candidates(text):
        tag = RI.resolve(doc, cand)
        if tag is None:
            unresolved.append(cand)
            continue
        if any(r["subject_guid"] == tag["subject_guid"] for r in resolved):
            continue
        resolved.append({
            "symbol": tag["symbol"],
            "subject_guid": tag["subject_guid"],
            "issuer_guid": tag["issuer_guid"],
            "identity_status": tag["identity_status"],
        })

    # Capitalised words that may be company names. Tried against the registry
    # first — a name that happens to be a registered alias should resolve, not be
    # filed as a gap — then recorded as unresolved so the shortfall is visible.
    for name in extract_name_mentions(text):
        tag = RI.resolve(doc, name)
        if tag is not None:
            if not any(r["subject_guid"] == tag["subject_guid"] for r in resolved):
                resolved.append({
                    "symbol": tag["symbol"], "subject_guid": tag["subject_guid"],
                    "issuer_guid": tag["issuer_guid"],
                    "identity_status": tag["identity_status"]})
        elif name.upper() not in unresolved:
            unresolved.append(name)

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "topics": extract_topics(text),
        "resolved": resolved,
        # Kept, not discarded: "Visa" lands here because no company-name index
        # exists, and that gap is the point of measuring it.
        "unresolved_mentions": unresolved,
        "financial_action": False,
    }
