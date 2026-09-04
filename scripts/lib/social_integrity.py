#!/usr/bin/env python3
"""social_integrity.py — reposts and coordinated bursts, made visible.

Why
---
Social mention counts are trivially inflatable. The same claim reposted forty
times reads, to any counter, as forty independent people agreeing — and a
sentiment score computed over that count reports overwhelming consensus where
there is one source and thirty-nine echoes. A burst of near-identical posts from
freshly created accounts in a ninety-second window reads the same way.

This module does not decide what is true. It attaches two structural findings to
a social sample so that a downstream consumer, and an operator, can see the
difference between *forty voices* and *one voice amplified forty times*:

* :func:`detect_reposts` — groups near-identical content, names one original per
  group by earliest observation, and reports how much of the apparent volume is
  echo.
* :func:`detect_bot_burst` — flags temporal clustering combined with author
  concentration and template similarity.

Deliberately NOT done here
--------------------------
Reposts are **not deleted**. A repost is evidence of amplification, which is
itself worth seeing; silently dropping it would replace one distortion with
another and would hide coordinated promotion rather than surface it. Everything
is annotated, nothing is removed.

Authority
---------
``READ_ONLY_ADVISORY``. Social signals are awareness-only. Nothing in this
module may authorize, size, gate or veto an order, and
:func:`assess_social_sample` stamps ``can_authorize_order=False`` on every
result it returns so a consumer cannot lose that fact by accident.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence

SCHEMA = "SocialIntegrity@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

# ── Normalisation ───────────────────────────────────────────────────────────

_URL = re.compile(r"https?://\S+")
_MENTION = re.compile(r"[@$]\w+")
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]")
#: Retweet / crosspost prefixes that carry no content of their own.
_ECHO_PREFIX = re.compile(r"^\s*(rt|via|repost|crosspost|x-post)\b[:\s]*", re.I)


def normalize_text(text: str) -> str:
    """Reduce a post to its content for near-duplicate comparison.

    URLs, @/$ handles, case, punctuation and whitespace runs are stripped: a
    repost that swaps the tracking parameters on a link, or adds a cashtag, is
    the same claim. The ``RT @user:`` prefix goes too, because that is exactly
    what an amplified post looks like.
    """
    t = _ECHO_PREFIX.sub("", text or "")
    t = _URL.sub(" ", t)
    t = _MENTION.sub(" ", t)
    t = _PUNCT.sub(" ", t.lower())
    return _WS.sub(" ", t).strip()


def content_fingerprint(text: str) -> str:
    """Stable id for normalised content."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()[:32]


def shingles(text: str, k: int = 5) -> set[str]:
    """Word k-shingles of the normalised text, for near-duplicate scoring."""
    words = normalize_text(text).split()
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def similarity(a: str, b: str, k: int = 5) -> float:
    """Jaccard similarity over k-shingles. 1.0 == identical after normalisation."""
    sa, sb = shingles(a, k), shingles(b, k)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


# ── Post model ──────────────────────────────────────────────────────────────


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _post_text(p: dict) -> str:
    return " ".join(str(p.get(k) or "") for k in ("title", "body", "text", "description")).strip()


def _post_author(p: dict) -> str:
    for k in ("author", "user", "username", "account", "channel"):
        v = p.get(k)
        if v:
            return str(v)
    return "unknown"


def _post_time(p: dict) -> Optional[datetime]:
    for k in ("created_at", "published_at", "observed_at", "timestamp", "ts", "created_utc"):
        if k in p:
            t = _parse_ts(p[k])
            if t:
                return t
    return None


# ── Repost / amplification ──────────────────────────────────────────────────


@dataclass
class RepostGroup:
    fingerprint: str
    original_index: int
    member_indices: list[int]
    authors: list[str]
    distinct_authors: int
    size: int
    exact: bool
    similarity_floor: float = 1.0

    @property
    def echo_count(self) -> int:
        return max(0, self.size - 1)


@dataclass
class RepostFinding:
    schema: str = SCHEMA
    authority: str = AUTHORITY
    total_posts: int = 0
    distinct_claims: int = 0
    echo_posts: int = 0
    amplification_ratio: float = 0.0
    max_group_size: int = 1
    single_author_amplification: bool = False
    groups: list[dict] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: Jaccard floor above which two posts are treated as the same claim.
NEAR_DUPLICATE_THRESHOLD = 0.80


def detect_reposts(posts: Sequence[dict], *, threshold: float = NEAR_DUPLICATE_THRESHOLD) -> RepostFinding:
    """Group near-identical posts and report how much volume is echo.

    Exact matches are grouped by fingerprint first (cheap, and catches verbatim
    reposts). Remaining posts are compared pairwise by shingle similarity, which
    catches the reworded repost that a hash cannot.

    The **original** is the earliest observation in the group. Posts with no
    usable timestamp never become the original — an undated post cannot be shown
    to have come first, and guessing would let an amplifier be credited as the
    source.
    """
    n = len(posts)
    if n == 0:
        return RepostFinding(note="no posts")

    by_fp: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(posts):
        by_fp[content_fingerprint(_post_text(p))].append(i)

    groups: list[RepostGroup] = []
    ungrouped: list[int] = []
    for fp, idxs in by_fp.items():
        if len(idxs) > 1:
            groups.append(_build_group(posts, idxs, fp, exact=True, floor=1.0))
        else:
            ungrouped.append(idxs[0])

    # Near-duplicate pass over what exact matching did not catch.
    used: set[int] = set()
    for pos, i in enumerate(ungrouped):
        if i in used:
            continue
        members = [i]
        floor = 1.0
        for j in ungrouped[pos + 1 :]:
            if j in used:
                continue
            s = similarity(_post_text(posts[i]), _post_text(posts[j]))
            if s >= threshold:
                members.append(j)
                floor = min(floor, s)
        if len(members) > 1:
            used.update(members)
            groups.append(
                _build_group(posts, members, content_fingerprint(_post_text(posts[i])), exact=False, floor=floor)
            )

    echo = sum(g.echo_count for g in groups)
    distinct = n - echo
    ratio = round(echo / n, 4) if n else 0.0
    max_size = max((g.size for g in groups), default=1)
    single_author = any(g.distinct_authors == 1 and g.size > 1 for g in groups)

    if not groups:
        note = "No repeated content detected; every post is a distinct claim."
    else:
        note = (
            f"{echo} of {n} posts repeat an existing claim "
            f"({ratio:.0%} amplification). Apparent volume overstates distinct "
            f"sources by {n - distinct}."
        )
        if single_author:
            note += " At least one claim was repeated by a single author."

    return RepostFinding(
        total_posts=n,
        distinct_claims=distinct,
        echo_posts=echo,
        amplification_ratio=ratio,
        max_group_size=max_size,
        single_author_amplification=single_author,
        groups=[asdict(g) for g in sorted(groups, key=lambda g: -g.size)],
        note=note,
    )


def _build_group(posts: Sequence[dict], idxs: list[int], fp: str, *, exact: bool, floor: float) -> RepostGroup:
    dated = [(i, _post_time(posts[i])) for i in idxs]
    timed = [(i, t) for i, t in dated if t is not None]
    # Earliest dated post is the original; if none is dated, fall back to input
    # order but never treat an undated post as provably first.
    original = min(timed, key=lambda it: it[1])[0] if timed else min(idxs)
    authors = [_post_author(posts[i]) for i in idxs]
    return RepostGroup(
        fingerprint=fp,
        original_index=original,
        member_indices=sorted(idxs),
        authors=authors,
        distinct_authors=len(set(authors)),
        size=len(idxs),
        exact=exact,
        similarity_floor=round(floor, 4),
    )


# ── Bot / coordinated burst ─────────────────────────────────────────────────


@dataclass
class BurstFinding:
    schema: str = SCHEMA
    authority: str = AUTHORITY
    detected: bool = False
    window_seconds: int = 0
    peak_count: int = 0
    peak_window_start: Optional[str] = None
    distinct_authors_in_peak: int = 0
    author_concentration: float = 0.0
    template_similarity: float = 0.0
    reasons: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


#: A burst needs at least this many posts before concentration means anything.
MIN_BURST_POSTS = 5
#: Share of a window's posts coming from its most active author.
AUTHOR_CONCENTRATION_THRESHOLD = 0.60
#: Mean pairwise similarity within the window suggesting a shared template.
TEMPLATE_SIMILARITY_THRESHOLD = 0.60


def detect_bot_burst(
    posts: Sequence[dict], *, window_seconds: int = 300, min_posts: int = MIN_BURST_POSTS
) -> BurstFinding:
    """Flag temporal clustering combined with concentration or templating.

    Volume alone is never enough. A genuine catalyst produces a spike from many
    authors saying different things; that must not be flagged, or the detector
    becomes a news detector. A burst is reported only when a dense window
    *also* shows author concentration or template similarity — the structural
    marks of amplification rather than interest.
    """
    timed = [(p, _post_time(p)) for p in posts]
    dated = [(p, t) for p, t in timed if t is not None]
    if len(dated) < min_posts:
        return BurstFinding(
            window_seconds=window_seconds,
            note=(
                f"{len(dated)} timestamped posts is below the {min_posts}-post "
                f"floor; concentration is not meaningful at this size."
            ),
        )

    dated.sort(key=lambda it: it[1])
    span = timedelta(seconds=window_seconds)

    best: tuple[int, int, int] = (0, 0, 0)  # count, start_idx, end_idx
    j = 0
    for i in range(len(dated)):
        while dated[i][1] - dated[j][1] > span:
            j += 1
        if i - j + 1 > best[0]:
            best = (i - j + 1, j, i)

    count, lo, hi = best
    window = [p for p, _ in dated[lo : hi + 1]]
    authors = [_post_author(p) for p in window]
    top_author_share = (Counter(authors).most_common(1)[0][1] / count) if count else 0.0

    texts = [_post_text(p) for p in window]
    pairs = [(a, b) for x, a in enumerate(texts) for b in texts[x + 1 :]]
    mean_sim = (sum(similarity(a, b) for a, b in pairs) / len(pairs)) if pairs else 0.0

    reasons: list[str] = []
    if count >= min_posts and top_author_share >= AUTHOR_CONCENTRATION_THRESHOLD:
        reasons.append(f"author_concentration:{top_author_share:.0%}_of_{count}_posts")
    if count >= min_posts and mean_sim >= TEMPLATE_SIMILARITY_THRESHOLD:
        reasons.append(f"template_similarity:{mean_sim:.2f}")

    detected = bool(reasons)
    if detected:
        note = (
            f"{count} posts within {window_seconds}s showing "
            + " and ".join(r.split(":")[0].replace("_", " ") for r in reasons)
            + ". Treat the apparent consensus as unverified."
        )
    else:
        note = (
            f"Densest window holds {count} posts from "
            f"{len(set(authors))} authors with mean similarity {mean_sim:.2f}; "
            f"no concentration or templating marks. Volume alone is not a burst."
        )

    return BurstFinding(
        detected=detected,
        window_seconds=window_seconds,
        peak_count=count,
        peak_window_start=dated[lo][1].replace(microsecond=0).isoformat(),
        distinct_authors_in_peak=len(set(authors)),
        author_concentration=round(top_author_share, 4),
        template_similarity=round(mean_sim, 4),
        reasons=reasons,
        note=note,
    )


# ── Combined assessment ─────────────────────────────────────────────────────


def assess_social_sample(
    posts: Sequence[dict], *, symbol: Optional[str] = None, window_seconds: int = 300
) -> dict[str, Any]:
    """Both findings plus the corrected volume, with authority stamped on.

    ``effective_distinct_claims`` is the number a consumer should reason about;
    ``total_posts`` is what a naive count would have reported. Publishing both
    is the point — the gap between them is the finding.
    """
    rep = detect_reposts(posts)
    burst = detect_bot_burst(posts, window_seconds=window_seconds)
    degraded = rep.amplification_ratio > 0 or burst.detected
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "symbol": symbol,
        "total_posts": rep.total_posts,
        "effective_distinct_claims": rep.distinct_claims,
        "amplification_ratio": rep.amplification_ratio,
        "repost": rep.to_dict(),
        "burst": burst.to_dict(),
        "integrity_degraded": degraded,
        "confidence_qualifier": ("AMPLIFIED_OR_COORDINATED" if degraded else "NO_STRUCTURAL_DISTORTION"),
        # Stamped on every result. A consumer that forwards this dict cannot
        # drop the fact that social evidence is awareness-only.
        "can_authorize_order": False,
        "verification_status": "UNVERIFIED",
    }
