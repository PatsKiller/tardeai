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

#: A capitalised RUN is a plausible company name — "Visa", "Northrop Grumman",
#: "JPMorgan Chase". Runs are matched longest-first so a two-word company is not
#: split into two unresolvable single words.
_NAME_RUN = re.compile(r"\b([A-Z][A-Za-z.&\-]{1,15}(?:\s+[A-Z][A-Za-z.&\-]{1,15}){0,3})\b")


#: Ordinary English words that are ALSO real tickers. Capitalised at the start of
#: a sentence they look exactly like a company mention, and the agent's own
#: replies are full of them:
#:
#:   "You are 3.2% below resistance"  -> YOU  (Clear Secure)
#:   "On the weekly WMT support is"   -> ON   (ON Semiconductor)
#:
#: Both were tagged on the first four-turn test, attaching the operator's Walmart
#: question to two unrelated issuers. A single capitalised word in sentence
#: position is not evidence of a company; a multi-word run or a mid-sentence
#: capital still is.
_SENTENCE_STARTERS = frozenset({
    "You", "On", "It", "We", "He", "She", "They", "That", "This", "There",
    "Here", "Then", "Now", "So", "But", "And", "Or", "If", "As", "At", "By",
    "For", "From", "In", "Into", "Of", "Off", "Out", "Over", "To", "Up", "With",
    "Its", "Our", "Your", "My", "All", "Any", "Both", "Each", "Some", "Such",
    "No", "Not", "One", "Two", "New", "Old", "Best", "Good", "Well", "Just",
    "Only", "Also", "Still", "Yet", "Very", "Most", "More", "Less", "Next",
    "Last", "Same", "Other", "Own", "Right", "Left", "Long", "Short", "Open",
    "Close", "High", "Low", "Big", "Real", "Free", "Full", "Half", "Are", "Is",
    "Was", "Were", "Be", "Been", "Has", "Have", "Had", "Do", "Does", "Did",
    "Can", "Will", "Would", "Should", "Could", "May", "Might", "Must",
})

_SENT_BOUNDARY = re.compile(r"(?:^|[.!?\n]\s*)$")


def _is_sentence_initial(text: str, start: int) -> bool:
    return bool(_SENT_BOUNDARY.search(text[:start]))


def extract_name_mentions(text: str) -> list[str]:
    """Capitalised runs, longest first, with leading agent/question words peeled.

    "Alex what is the target for Northrop Grumman" must yield "Northrop Grumman",
    not "Alex" — so a run is trimmed from the left while its head is a stopword.
    """
    out: list[str] = []
    src = text or ""
    for m in _NAME_RUN.finditer(src):
        words = m.group(1).split()
        offset = m.start()
        while words and words[0] in _NAME_STOPWORDS:
            offset += len(words[0]) + 1
            words.pop(0)
        while words and words[-1] in _NAME_STOPWORDS:
            words.pop()
        if not words:
            continue
        # A lone capitalised English word opening a sentence is punctuation, not
        # a company. Multi-word runs and mid-sentence capitals still count.
        if (len(words) == 1 and words[0] in _SENTENCE_STARTERS
                and _is_sentence_initial(src, offset)):
            continue
        phrase = " ".join(words)
        if phrase not in out:
            out.append(phrase)
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
            # Uniform shape across both paths. A consumer must never have to ask
            # which branch produced a row before it can read it.
            "matched_via": "ticker",
            "matched_text": cand,
        })

    # Company names, resolved through the BROKER FEED — the same authoritative
    # record that supplies the CUSIP. Nothing here invents a mapping: if Schwab
    # does not carry the name, neither do we, and the mention is recorded as a
    # measured gap rather than guessed at.
    try:
        from lib.company_name_index import resolve_name  # noqa: PLC0415
    except Exception:
        resolve_name = None                                # type: ignore

    for name in extract_name_mentions(text):
        tag = RI.resolve(doc, name)          # a name that is also a ticker alias
        via = "ticker_alias"
        if tag is None and resolve_name is not None:
            hit = resolve_name(name)
            if hit:
                tag = RI.resolve(doc, hit["symbol"])
                via = "company_name"
        if tag is not None:
            if not any(r["subject_guid"] == tag["subject_guid"] for r in resolved):
                resolved.append({
                    "symbol": tag["symbol"], "subject_guid": tag["subject_guid"],
                    "issuer_guid": tag["issuer_guid"],
                    "identity_status": tag["identity_status"],
                    "matched_via": via, "matched_text": name})
        elif name not in unresolved:
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


def persist_turn(tag: dict[str, Any], *, conn, text: str, role: str,
                 chat_id: Any = None, message_id: Any = None,
                 thread_id: Any = None, reply_to_message_id: Any = None,
                 turn_index: Any = None, channel: str = "telegram") -> int:
    """Write ONE conversation turn — operator or agent — with its identity tags.

    Both halves are stored. A question without its answer loses what the agent
    actually said about the issuer, which is most of the value: an agent reading
    its own past answers is the point of persistent memory, and a follow-up
    ("no, I meant the weekly") is meaningless without the turn it replies to.

    `role` is NOT optional and is CHECK-constrained in the table. Without it the
    corpus is unreadable — an agent cannot tell its own words from the operator's
    and would end up learning from its own output.

    GRAIN: one row per (turn, resolved entity). A turn that resolved nothing
    still writes one row with null guids, because an unresolvable turn is the
    measurement of what the spine cannot reach.
    """
    if role not in ("operator", "agent"):
        raise ValueError(f"role must be 'operator' or 'agent', got {role!r}")

    rows = (tag.get("resolved") or [None])
    cur = conn.cursor()
    written = 0
    for r in rows:
        cur.execute(
            """INSERT INTO operator_conversation_turns
                 (role, channel, chat_id, message_id, thread_id,
                  reply_to_message_id, turn_index, text,
                  symbol, subject_guid, issuer_guid, identity_status,
                  matched_via, matched_text, topics, unresolved_mentions)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (role, channel,
             str(chat_id) if chat_id is not None else None,
             int(message_id) if message_id is not None else None,
             str(thread_id) if thread_id is not None else (
                 str(message_id) if message_id is not None else None),
             int(reply_to_message_id) if reply_to_message_id is not None else None,
             int(turn_index) if turn_index is not None else None,
             text,
             (r or {}).get("symbol"),
             (r or {}).get("subject_guid"),
             (r or {}).get("issuer_guid"),
             (r or {}).get("identity_status"),
             (r or {}).get("matched_via"),
             (r or {}).get("matched_text"),
             list(tag.get("topics") or []),
             list(tag.get("unresolved_mentions") or [])))
        written += 1
    conn.commit()
    return written


def thread_root(conn, *, chat_id: Any, message_id: Any,
                reply_to_message_id: Any) -> str:
    """The message_id every turn in this exchange shares.

    A reply inherits the root of the turn it answers, so a five-message
    back-and-forth is one WHERE clause instead of a reconstruction. A message
    that replies to nothing IS a root.
    """
    if reply_to_message_id is None:
        return str(message_id)
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT thread_id FROM operator_conversation_turns
                WHERE chat_id = %s AND message_id = %s AND thread_id IS NOT NULL
                LIMIT 1""",
            (str(chat_id) if chat_id is not None else None,
             int(reply_to_message_id)))
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception:
        pass
    # The parent is not in the store (bot restarted, or it predates capture).
    # Rooting on the parent still groups this reply with any sibling that also
    # answers it — better than starting a new thread per message.
    return str(reply_to_message_id)


def persist(tag: dict[str, Any], *, conn, question_text: str,
            chat_id: Any = None, message_id: Any = None,
            channel: str = "telegram") -> int:
    """Write a tagged question to `inbound_operator_questions`. Returns rows written.

    GRAIN: one row per (question, resolved entity). A question resolving to two
    symbols writes two rows.

    A question that resolved NOTHING still writes one row with null guids. That
    is deliberate: an unanswerable question is the measurement of what the spine
    cannot reach, and dropping it would make coverage look better than it is —
    the same reason unresolved_mentions is carried rather than discarded.
    """
    rows = tag.get("resolved") or [None]
    cur = conn.cursor()
    written = 0
    for r in rows:
        cur.execute(
            """INSERT INTO inbound_operator_questions
                 (channel, chat_id, message_id, question_text,
                  symbol, subject_guid, issuer_guid, identity_status,
                  matched_via, matched_text, topics, unresolved_mentions)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (channel,
             str(chat_id) if chat_id is not None else None,
             int(message_id) if message_id is not None else None,
             question_text,
             (r or {}).get("symbol"),
             (r or {}).get("subject_guid"),
             (r or {}).get("issuer_guid"),
             (r or {}).get("identity_status"),
             (r or {}).get("matched_via"),
             (r or {}).get("matched_text"),
             list(tag.get("topics") or []),
             list(tag.get("unresolved_mentions") or [])))
        written += 1
    conn.commit()
    return written
