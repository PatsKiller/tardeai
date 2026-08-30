"""WebSourceRef@v1 — librarian-lite for the residual web lane.

Every URL the residual web lane touches becomes a typed ref before it may
influence anything:

    source_id | grade A-D | as_of | stale_after_days

The grade law itself is NOT re-implemented here. `cio_research_registry`
already owns the A/B/C/D/X vocabulary and `cio_corpus_index.CLOSING_GRADES`
already says only A and B may close a question. Two grade laws over one corpus
drift apart silently, so this module imports both and adds only the axis that
was genuinely missing: **age**.

A source can be perfectly graded and still be the wrong answer, because it was
true in April. `stale_after_days` is what makes "this A-grade filing is 14
months old" a refusal rather than a corpus_hit. Hence:

    may_close(ref)  ==  grade in {A, B}  AND  not stale

Discovery is likewise not re-implemented: `cio_source_discovery.discover()`
already enforces the 3-CANDIDATE-per-entity-per-week cap and already refuses to
grade a candidate. This module re-exports it so the lane has one door, and adds
no ingest path of its own.

No network. This module never fetches a URL; it types one the caller already
has. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlsplit

from scripts.lib.cio_corpus_index import CLOSING_GRADES, CONTEXT_ONLY_GRADES
from scripts.lib.cio_research_registry import normalize_grade

SCHEMA = "WebSourceRef@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
FINANCIAL_ACTION = False

# Official primary records. The operator's law: an ENTITY question may be
# answered from an official page, not from a blog. These are the hosts whose
# pages are the entity's own filed/published record rather than commentary
# about it.
OFFICIAL_HOST_SUFFIXES: tuple[str, ...] = (
    "sec.gov",
    "federalreserve.gov",
    "stlouisfed.org",          # FRED
    "bls.gov",
    "bea.gov",
    "treasury.gov",
    "ecb.europa.eu",
    "europa.eu",
    "cftc.gov",
    "finra.org",
    "nasdaq.com",
    "nyse.com",
)

# Investor-relations pages are official for the issuer even on a corporate
# domain. Matched on the leading label or path, not on the registrable domain,
# because IR lives at ir.<company>.com about as often as <company>.com/investors.
IR_HOST_PREFIXES: tuple[str, ...] = ("ir.", "investor.", "investors.")
IR_PATH_MARKERS: tuple[str, ...] = ("/investor", "/investors", "/ir/")

# Hosts that are commentary by construction. Never official, never A.
BLOG_HOST_MARKERS: tuple[str, ...] = (
    "blogspot.", "wordpress.", "substack.com", "medium.com", "seekingalpha.com",
    "reddit.com", "twitter.com", "x.com", "stocktwits.com", "quora.com",
    "tumblr.", "facebook.com", "linkedin.com", "youtube.com",
)

# How long a ref of each grade may still close a question. Age is the axis the
# grade does not carry: an A-grade filing is still an A-grade filing at 14
# months, and still the wrong answer to "what is priced in now".
DEFAULT_STALE_AFTER_DAYS: dict[str, int] = {
    "A": 180,
    "B": 45,
    "C": 21,
    "D": 7,
}
FALLBACK_STALE_AFTER_DAYS = 7


class SourceRefRefused(ValueError):
    """Raised when a URL cannot be typed into a lawful ref at all."""


def _utc(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    s = str(ts).replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        try:
            d = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def host_of(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def is_official(url: str) -> bool:
    """True for a primary/official record: regulator, central bank, or issuer IR."""
    host = host_of(url)
    if not host:
        return False
    if any(host == suf or host.endswith("." + suf) for suf in OFFICIAL_HOST_SUFFIXES):
        return True
    if any(host.startswith(p) for p in IR_HOST_PREFIXES):
        return True
    try:
        path = (urlsplit(str(url)).path or "").lower()
    except ValueError:
        return False
    return any(m in path for m in IR_PATH_MARKERS)


def is_blog(url: str) -> bool:
    host = host_of(url)
    return bool(host) and any(m in host for m in BLOG_HOST_MARKERS)


def source_id_for(url: str) -> str:
    """Stable id: host plus a digest of the full URL.

    Host-first so a human scanning the ledger can see where a claim came from
    without resolving the hash.
    """
    u = str(url or "").strip()
    if not u:
        raise SourceRefRefused("empty url")
    digest = hashlib.sha256(u.encode("utf-8")).hexdigest()[:12]
    host = host_of(u) or "unknown"
    return f"web:{host}:{digest}"


def default_grade_for(url: str) -> str:
    """Grade a URL by what KIND of record it is, never by what it says.

    Official primary record  -> A
    Blog / forum / social    -> D
    Everything else          -> C  (exploratory; context only until reviewed)

    B is deliberately not auto-assigned: 'independently reproduced with usable
    N' is a judgement a critique pass makes, not something a hostname earns.
    """
    if is_official(url):
        return "A"
    if is_blog(url):
        return "D"
    return "C"


def stale_after_days_for(grade: str) -> int:
    return DEFAULT_STALE_AFTER_DAYS.get(
        normalize_grade(grade) or "", FALLBACK_STALE_AFTER_DAYS)


def source_ref(
    url: str,
    *,
    as_of: Any = None,
    grade: Any = None,
    stale_after_days: Optional[int] = None,
    title: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Type one URL into a WebSourceRef@v1. Never fetches it."""
    now = _utc(now)
    u = str(url or "").strip()
    if not u:
        raise SourceRefRefused("empty url")
    if not host_of(u):
        raise SourceRefRefused(f"unparseable url: {url!r}")

    g = normalize_grade(grade) or default_grade_for(u)
    # A caller may not promote a blog to a closing grade by asserting one.
    # Grades come from what the source IS; letting the prompt hand back "A"
    # for a substack is exactly the laundering this lane exists to prevent.
    if g in CLOSING_GRADES and is_blog(u):
        g = "D"
    sad = int(stale_after_days if stale_after_days is not None
              else stale_after_days_for(g))

    as_of_dt = _parse(as_of) or now
    return {
        "schema": SCHEMA,
        "source_id": source_id_for(u),
        "url": u,
        "title": title,
        "host": host_of(u),
        "grade": g,
        "official": is_official(u),
        "as_of": as_of_dt.isoformat(),
        "stale_after_days": sad,
        "stale_at": (as_of_dt + timedelta(days=sad)).isoformat(),
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
    }


def is_stale(ref: dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    now = _utc(now)
    stale_at = _parse(ref.get("stale_at"))
    if stale_at is None:
        as_of = _parse(ref.get("as_of"))
        if as_of is None:
            return True                     # undated is stale, fail closed
        sad = int(ref.get("stale_after_days") or FALLBACK_STALE_AFTER_DAYS)
        stale_at = as_of + timedelta(days=sad)
    return now >= stale_at


def may_close(ref: dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    """Whether this ref may close a question (i.e. support a corpus_hit).

    Both axes must hold. A C/D ref never closes — it attaches as challenge
    context — and neither does a stale A.
    """
    grade = normalize_grade(ref.get("grade")) or ""
    if grade not in CLOSING_GRADES:
        return False
    return not is_stale(ref, now=now)


def context_only(ref: dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    """True when the ref may attach only as challenge context."""
    return not may_close(ref, now=now)


def admissible_for_entity_question(ref: dict[str, Any]) -> bool:
    """Entity questions may use official pages, not blogs.

    Separate from `may_close`: this is about whether the lane may CITE the ref
    for an entity-level question at all, before age is considered.
    """
    if is_blog(ref.get("url") or ""):
        return False
    return bool(ref.get("official")) or (
        normalize_grade(ref.get("grade")) in CLOSING_GRADES)


def summarize(refs: list[dict[str, Any]], *,
              now: Optional[datetime] = None) -> dict[str, Any]:
    """Grade/staleness census for a receipt block."""
    now = _utc(now)
    by_grade: dict[str, int] = {}
    for r in refs:
        g = normalize_grade(r.get("grade")) or "?"
        by_grade[g] = by_grade.get(g, 0) + 1
    closing = [r for r in refs if may_close(r, now=now)]
    return {
        "schema": SCHEMA,
        "as_of": now.isoformat(),
        "count": len(refs),
        "by_grade": dict(sorted(by_grade.items())),
        "closing_grades": sorted(CLOSING_GRADES),
        "context_only_grades": sorted(CONTEXT_ONLY_GRADES),
        "may_close": [r.get("source_id") for r in closing],
        "stale": [r.get("source_id") for r in refs if is_stale(r, now=now)],
        "authority": AUTHORITY,
    }


# ── discovery ──────────────────────────────────────────────────────────────
#
# Re-exported rather than reimplemented. `cio_source_discovery` already caps
# proposals at 3 per entity per week, already refuses to grade a CANDIDATE, and
# already declines to download anything. The lane gets one door to it.

def discover(entity: str, **kwargs: Any) -> dict[str, Any]:
    from scripts.lib.cio_source_discovery import discover as _discover
    return _discover(entity, **kwargs)


MAX_CANDIDATES_PER_ENTITY_PER_WEEK = 3
