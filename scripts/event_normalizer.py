#!/usr/bin/env python3
"""event_normalizer.py — canonical event state for a symbol.

WHY THIS EXISTS
---------------
BETA's confirmed earnings date sat in the database as a headline —

    "BETA Technologies to Announce Second Quarter 2026 Results on August 12, 2026"
    (catalyst_events, published 2026-07-15 07:00)

— while symbol_profiles.next_earnings_date was NULL. Every event gate reads the
profile field, so every gate saw "no earnings" for a stock with a confirmed print
inside any August contract. The information was present and unparsed.

THE SEVEN STATES
----------------
    SCHEDULED       a date is established
    NONE_CONFIRMED  a provider affirmatively answered "nothing booked"
    UNKNOWN         nothing could be established — NOT the same as NONE_CONFIRMED
    STALE           we had an answer, but not recently enough to rely on
    CONFLICTED      sources disagree on the date
    INVALID         a value exists but does not parse as a date
    PROVIDER_DOWN   the lookup path itself failed

Only NONE_CONFIRMED means "no earnings". The other six non-SCHEDULED states mean
"we do not know", and every consumer must fail closed on them. Collapsing UNKNOWN
into NONE_CONFIRMED is the exact defect this module exists to prevent.

THE PARSING HAZARD
------------------
2,270 catalyst headlines match an earnings-shaped pattern, and MOST ARE PAST
TENSE — "Reports Q2 Results", "Releases Q1 2027 Earnings". Those describe a print
that already happened. Extracting a date from them would manufacture a future
event out of a historical one, which is worse than the NULL it replaces.

So a headline only yields a date when it is BOTH forward-looking ("to announce",
"will report", "scheduled to release") AND carries an explicit calendar date. A
past-tense headline contributes nothing, however confident the source.

PURE: parsing and state logic take no database. `resolve()` accepts injected
source values so it can be tested without one.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

SCHEDULED = "SCHEDULED"
NONE_CONFIRMED = "NONE_CONFIRMED"
UNKNOWN = "UNKNOWN"
STALE = "STALE"
CONFLICTED = "CONFLICTED"
INVALID = "INVALID"
PROVIDER_DOWN = "PROVIDER_DOWN"

ALL_STATES = (SCHEDULED, NONE_CONFIRMED, UNKNOWN, STALE, CONFLICTED, INVALID, PROVIDER_DOWN)

# Every state except these two means "we do not know". Consumers fail closed.
ACTIONABLE_STATES = (SCHEDULED, NONE_CONFIRMED)

# A profile answer older than this is STALE, not NONE_CONFIRMED. Absence of a
# recent look is not evidence of absence of an event.
PROFILE_TRUST_DAYS = int(os.getenv("EVENT_PROFILE_TRUST_DAYS", "7"))

# A parsed headline older than this stops being taken as a live schedule.
HEADLINE_TRUST_DAYS = int(os.getenv("EVENT_HEADLINE_TRUST_DAYS", "45"))

# ── Headline parsing ──────────────────────────────────────────────────────────
# Forward-looking intent. "to announce", "will report", "scheduled to release",
# "to host ... call". Past tense is deliberately absent.
_FORWARD = re.compile(
    r"\b("
    r"to\s+(announce|report|release|host|issue)"
    r"|will\s+(announce|report|release|host|issue)"
    r"|scheduled\s+to\s+(announce|report|release)"
    r"|plans?\s+to\s+(announce|report|release)"
    r"|to\s+be\s+(announced|reported|released)"
    r")\b",
    re.I,
)

# Past tense — a headline matching this is describing a completed event and is
# refused even if it also contains a date.
_PAST = re.compile(
    r"\b("
    r"reported|reports|released|releases|announced|announces"
    r"|posted|posts|delivered|delivers|beat|beats|missed|misses"
    r")\b",
    re.I,
)

# The event must actually be an earnings/results event.
_EARNINGS_SUBJECT = re.compile(
    r"\b(earnings|results|quarter(ly)?|Q[1-4]\b|fiscal\s+(year|20\d\d)|financial\s+results)\b",
    re.I,
)

_MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}
_MONTHS.update({m[:3].lower(): i for m, i in list(_MONTHS.items())})

# "on August 12, 2026" / "August 12, 2026" / "on Aug. 12, 2026"
_DATE_MDY = re.compile(
    r"\b(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(?P<year>20\d{2})\b",
    re.I,
)
# "on 12 August 2026"
_DATE_DMY = re.compile(
    r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s*,?\s*(?P<year>20\d{2})\b",
    re.I,
)



def _as_date(value) -> Optional[date]:
    """Coerce to a plain date. datetime SUBCLASSES date, so `isinstance(x, date)`
    is True for a datetime and passing it through leaves date-vs-datetime
    subtraction to raise at the comparison site — which is exactly how this
    first failed against live catalyst_events rows (2026-07-20)."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class EventState:
    """One symbol's earnings timing, with its provenance attached.

    `state` is authoritative. `date` is only meaningful when state==SCHEDULED.
    """
    symbol: str
    state: str
    date: Optional[date] = None
    source: str = ""
    as_of: Optional[str] = None
    reason: str = ""
    candidates: tuple = field(default_factory=tuple)

    @property
    def is_actionable(self) -> bool:
        """True only when the state settles the question either way."""
        return self.state in ACTIONABLE_STATES

    @property
    def blocks_action(self) -> bool:
        """Any non-actionable state must fail closed at the call site."""
        return not self.is_actionable

    def inside_contract(self, expiration) -> Optional[bool]:
        """Does the event fall on or before `expiration`?

        None means UNDECIDABLE and must never be read as False. A caller that
        treats None as "clear" reintroduces the fail-open bug.
        """
        if self.state != SCHEDULED or not self.date or not expiration:
            return None
        exp = _as_date(expiration)
        return None if exp is None else (self.date <= exp)

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "state": self.state,
                "date": self.date.isoformat() if self.date else None,
                "source": self.source, "as_of": self.as_of,
                "reason": self.reason, "candidates": list(self.candidates)}


def parse_headline_date(headline: str, *, published_at=None) -> Optional[date]:
    """Extract a scheduled earnings date from a headline, or None.

    Returns None for every past-tense headline, for every headline without an
    explicit date, and for any headline whose subject is not earnings/results —
    all three are cases where guessing would invent an event.
    """
    if not headline:
        return None
    text = str(headline)

    if not _EARNINGS_SUBJECT.search(text):
        return None
    if not _FORWARD.search(text):
        return None

    # "Reports Q2 Results Tomorrow" carries past-tense verbs and no date; but a
    # headline like "X to Announce ... after reporting Y" can carry both. The
    # forward clause must come FIRST for the date to describe a future event.
    fwd = _FORWARD.search(text)
    past = _PAST.search(text)
    if past and past.start() < fwd.start():
        return None

    for rx in (_DATE_MDY, _DATE_DMY):
        m = rx.search(text)
        if not m:
            continue
        mon = _MONTHS.get(m.group("mon").lower().rstrip("."))
        if not mon:
            continue
        try:
            got = date(int(m.group("year")), mon, int(m.group("day")))
        except ValueError:
            continue          # e.g. February 31 — invalid, not merely unparsed
        # A "scheduled" date published after it passed is a report, not a plan.
        pub = _as_date(published_at)
        if pub is not None and got < pub:
            return None
        return got
    return None


def resolve(symbol: str, *,
            profile_date=None, profile_updated_at=None, profile_row_exists: bool = False,
            headline_events=(), today: Optional[date] = None,
            provider_failed: bool = False) -> EventState:
    """Combine sources into one canonical state.

    `headline_events` is an iterable of (headline, published_at) tuples.
    Nothing here touches a database; `resolve_from_db` supplies these.
    """
    today = _as_date(today) or date.today()
    sym = str(symbol or "").upper()

    if provider_failed:
        return EventState(sym, PROVIDER_DOWN, reason="earnings lookup path failed")

    # ── headline candidates ───────────────────────────────────────────────────
    parsed = []
    for headline, published in (headline_events or ()):
        got = parse_headline_date(headline, published_at=published)
        if not got:
            continue
        pub = _as_date(published)
        if pub and (today - pub).days > HEADLINE_TRUST_DAYS:
            continue                      # too old to describe a live schedule
        if got < today:
            continue                      # the print already happened
        parsed.append((got, headline, pub))

    headline_dates = sorted({p[0] for p in parsed})

    # ── profile value ─────────────────────────────────────────────────────────
    prof: Optional[date] = None
    prof_invalid = False
    if profile_date not in (None, ""):
        prof = _as_date(profile_date)
        prof_invalid = prof is None

    prof_fresh = False
    upd = _as_date(profile_updated_at)
    if upd is not None:
        prof_fresh = (today - upd).days <= PROFILE_TRUST_DAYS

    if prof_invalid and not headline_dates:
        return EventState(sym, INVALID, source="symbol_profiles",
                          as_of=str(profile_updated_at or ""),
                          reason=f"next_earnings_date={profile_date!r} does not parse")

    # A past profile date is not a future event.
    if prof and prof < today:
        prof = None

    # ── reconcile ─────────────────────────────────────────────────────────────
    if prof and headline_dates:
        if prof in headline_dates:
            return EventState(sym, SCHEDULED, date=prof,
                              source="symbol_profiles+catalyst_events",
                              as_of=str(profile_updated_at or ""),
                              reason="profile and headline agree",
                              candidates=tuple(d.isoformat() for d in headline_dates))
        return EventState(
            sym, CONFLICTED, source="symbol_profiles+catalyst_events",
            as_of=str(profile_updated_at or ""),
            reason=f"profile says {prof.isoformat()}, headline(s) say "
                   f"{', '.join(d.isoformat() for d in headline_dates)}",
            candidates=tuple([prof.isoformat()] + [d.isoformat() for d in headline_dates]))

    if headline_dates:
        if len(headline_dates) > 1:
            return EventState(
                sym, CONFLICTED, source="catalyst_events",
                reason="multiple distinct announced dates",
                candidates=tuple(d.isoformat() for d in headline_dates))
        hit = next(p for p in parsed if p[0] == headline_dates[0])
        return EventState(sym, SCHEDULED, date=headline_dates[0],
                          source="catalyst_events",
                          as_of=str(hit[2] or ""),
                          reason=f"parsed from announcement: {hit[1][:120]}")

    if prof:
        if prof_fresh:
            return EventState(sym, SCHEDULED, date=prof, source="symbol_profiles",
                              as_of=str(profile_updated_at or ""))
        return EventState(sym, STALE, date=prof, source="symbol_profiles",
                          as_of=str(profile_updated_at or ""),
                          reason=f"profile not refreshed within {PROFILE_TRUST_DAYS}d — "
                                 f"date retained but not trusted as current")

    # ── nothing found ─────────────────────────────────────────────────────────
    # This is the branch that used to silently mean "no earnings". A provider
    # only gets to say NONE_CONFIRMED when it actually looked, recently, and
    # came back empty.
    if profile_row_exists and prof_fresh:
        return EventState(sym, NONE_CONFIRMED, source="symbol_profiles",
                          as_of=str(profile_updated_at or ""),
                          reason="provider looked and found nothing scheduled")
    if profile_row_exists:
        return EventState(sym, STALE, source="symbol_profiles",
                          as_of=str(profile_updated_at or ""),
                          reason="profile exists but has not been refreshed recently enough "
                                 "to treat an empty value as 'nothing scheduled'")
    return EventState(sym, UNKNOWN, reason="no profile row and no parsable announcement")


def resolve_from_db(symbol: str, conn=None, *, today: Optional[date] = None) -> EventState:
    """Database-backed resolve(). Any failure surfaces as PROVIDER_DOWN rather
    than as an absence, so an outage cannot read as 'no earnings'."""
    sym = str(symbol or "").upper()
    try:
        if conn is None:
            from db_adapter import _get_conn
            conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""SELECT next_earnings_date, earnings_updated_at
                       FROM symbol_profiles WHERE upper(symbol) = %s LIMIT 1""", (sym,))
        row = cur.fetchone()
        prof_date, prof_upd = (row[0], row[1]) if row else (None, None)

        cur.execute("""SELECT headline, published_at FROM catalyst_events
                       WHERE upper(symbol) = %s
                         AND published_at > now() - interval '%s days'
                       ORDER BY published_at DESC LIMIT 40""",
                    (sym, HEADLINE_TRUST_DAYS))
        headlines = [(r[0], r[1]) for r in cur.fetchall()]
    except Exception as exc:
        return EventState(sym, PROVIDER_DOWN,
                          reason=f"{type(exc).__name__}: {str(exc)[:120]}")

    return resolve(sym, profile_date=prof_date, profile_updated_at=prof_upd,
                   profile_row_exists=bool(row), headline_events=headlines, today=today)
