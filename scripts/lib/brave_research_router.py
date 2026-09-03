#!/usr/bin/env python3
"""brave_research_router.py — the one governed entry point to paid Brave Search.

Why this module exists
----------------------
Measured 2026-09-03 against the deployed tree, the Brave surface had four
independent problems that a per-caller budget alone cannot fix:

1. **The plan ceiling was guessed, twice, differently.**
   ``brave_search.MONTHLY_BUDGET = 850`` carries the comment "out of 1000";
   ``phase2b_analyst`` caps itself at 5 symbols "to stay within 2000/mo free
   tier". Two hardcoded tiers, neither measured. Brave returns the real
   allowance on every response in ``X-RateLimit-*``; nothing read those
   headers, so the true plan was never observed. This module records them
   (:func:`observed_allowance`) and treats the configured ceiling as a
   *policy* cap that must be reconciled against the *measured* one.

2. **Caching was per-process.** ``brave_search._search_cache`` is a module
   dict. Every cron invocation starts cold, so two jobs a minute apart asking
   the identical question both spend. The cache here is a file under the
   canonical state root, so it survives the process that filled it.

3. **Nothing coalesced.** Concurrent agents asking one question spent one
   credit each. A fingerprint-scoped lock makes the second caller wait for
   the first and read its answer.

4. **Every failure looked like "no results".** ``search()`` returns ``[]`` for
   a missing key, a 429, a timeout, a weekend skip, a budget denial and a
   genuinely empty result set alike. A caller cannot tell "nothing was
   published" from "we were not allowed to ask", which is the same
   indistinguishable-thinner-answer failure ``search_health`` was built for.
   Every return here is an :class:`Outcome` carrying a distinct
   :class:`Status`.

Relationship to existing modules
--------------------------------
This does **not** re-implement the ledger. ``scripts.lib.search_budget`` is
already flock-serialized, fail-closed and atomic; it stays the single writer of
spend. This module adds the layers above it that Brave specifically needs:
purpose, priority, reserve, fingerprint, cache, coalescing and attribution.

Authority
---------
``READ_ONLY_ADVISORY``. This module issues HTTP GETs to a search provider and
returns discovery artifacts. Results are attributed ``SEARCH_DISCOVERY`` and are
never promoted to verified fact, native social sentiment, or any financial
truth. It holds no broker, order, position or risk authority.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Optional

SCHEMA = "BraveResearchRouter@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
PROVIDER = "brave"

WEB_URL = "https://api.search.brave.com/res/v1/web/search"
NEWS_URL = "https://api.search.brave.com/res/v1/news/search"

REQUEST_TIMEOUT = 10

# Attribution stamped on every result. A Brave hit that points at a Reddit or X
# page is a *pointer to* a discussion, not the discussion, and must never be
# counted as native social sentiment (Phase 7).
ATTRIBUTION = "SEARCH_DISCOVERY"


class Status(str, Enum):
    """Distinguishable outcomes. ``[]`` is not a diagnosis."""

    OK = "OK"  # served, >=1 result
    EMPTY = "EMPTY"  # served, genuinely 0 results
    CACHED = "CACHED"  # served from durable cache
    COALESCED = "COALESCED"  # another caller's in-flight answer

    DENIED_NO_KEY = "DENIED_NO_KEY"
    DENIED_BUDGET = "DENIED_BUDGET"
    DENIED_RESERVE = "DENIED_RESERVE"
    DENIED_PURPOSE_QUOTA = "DENIED_PURPOSE_QUOTA"
    DENIED_POLICY = "DENIED_POLICY"  # forbidden purpose (e.g. quotes)
    DENIED_NO_EVIDENCE_GAP = "DENIED_NO_EVIDENCE_GAP"
    DENIED_WEEKEND = "DENIED_WEEKEND"
    BUDGET_UNAVAILABLE = "BUDGET_UNAVAILABLE"

    UNAUTHORIZED = "UNAUTHORIZED"  # 401
    PAYMENT_REQUIRED = "PAYMENT_REQUIRED"  # 402
    FORBIDDEN = "FORBIDDEN"  # 403
    RATE_LIMITED = "RATE_LIMITED"  # 429
    SERVER_ERROR = "SERVER_ERROR"  # 5xx
    TIMEOUT = "TIMEOUT"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    MALFORMED = "MALFORMED"  # 200 with unparseable body


#: Statuses that mean "the provider was actually billed for this".
BILLED = frozenset({Status.OK, Status.EMPTY, Status.MALFORMED, Status.RATE_LIMITED, Status.SERVER_ERROR})

#: Statuses that mean "we never reached the provider".
NOT_CALLED = frozenset(
    {
        Status.CACHED,
        Status.COALESCED,
        Status.DENIED_NO_KEY,
        Status.DENIED_BUDGET,
        Status.DENIED_RESERVE,
        Status.DENIED_PURPOSE_QUOTA,
        Status.DENIED_POLICY,
        Status.DENIED_NO_EVIDENCE_GAP,
        Status.DENIED_WEEKEND,
        Status.BUDGET_UNAVAILABLE,
    }
)


class Purpose(str, Enum):
    """Brave's approved roles (source prompt Phase 4).

    Anything not on this list is not a reason to spend the subscription.
    """

    EVIDENCE_GAP = "EVIDENCE_GAP"
    CATALYST_CORROBORATION = "CATALYST_CORROBORATION"
    PRIMARY_SOURCE_DISCOVERY = "PRIMARY_SOURCE_DISCOVERY"
    LONG_TAIL_DISCOVERY = "LONG_TAIL_DISCOVERY"
    SOURCE_DISCOVERY = "SOURCE_DISCOVERY"
    SOCIAL_LEAD_DISCOVERY = "SOCIAL_LEAD_DISCOVERY"
    TRANSCRIPT_DISCOVERY = "TRANSCRIPT_DISCOVERY"
    CONTRADICTION_SEARCH = "CONTRADICTION_SEARCH"

    # Explicitly forbidden. Present as named values so a caller asking for one
    # is DENIED_POLICY with a reason, rather than silently allowed.
    QUOTE_RETRIEVAL = "QUOTE_RETRIEVAL"
    BULK_SYMBOL_POLLING = "BULK_SYMBOL_POLLING"
    PAGE_LOAD = "PAGE_LOAD"
    SENTIMENT_SCORING = "SENTIMENT_SCORING"


FORBIDDEN_PURPOSES = frozenset(
    {
        Purpose.QUOTE_RETRIEVAL,
        Purpose.BULK_SYMBOL_POLLING,
        Purpose.PAGE_LOAD,
        Purpose.SENTIMENT_SCORING,
    }
)


class Priority(int, Enum):
    """Held/proposed capital and urgent catalysts outrank cold-universe work."""

    HELD_CAPITAL = 0
    URGENT_CATALYST = 1
    PROPOSED_CAPITAL = 2
    WATCHLIST = 3
    COLD_UNIVERSE = 4


#: Priorities allowed to draw on the operator reserve once the soft floor is hit.
RESERVE_ELIGIBLE = frozenset({Priority.HELD_CAPITAL, Priority.URGENT_CATALYST})

# ── Configuration (measured/configured, never a guessed tier) ────────────────

#: Fraction of the monthly ceiling held back for unpredictable high-priority
#: events. Cold-universe and watchlist work is denied once remaining <= this.
DEFAULT_RESERVE_PCT = 15

#: Per-purpose share of the monthly ceiling. These MUST sum to at most
#: ``100 - DEFAULT_RESERVE_PCT``: quotas that sum to 100 would hand out the
#: operator reserve as ordinary purpose capacity, so the reserve would exist
#: only in the denial message. ``test_purpose_quotas_fit_within_the_cap_and_
#: leave_the_reserve`` pins the arithmetic.
DEFAULT_PURPOSE_QUOTA_PCT: dict[Purpose, int] = {
    Purpose.EVIDENCE_GAP: 26,
    Purpose.CATALYST_CORROBORATION: 17,
    Purpose.PRIMARY_SOURCE_DISCOVERY: 13,
    Purpose.CONTRADICTION_SEARCH: 9,
    Purpose.LONG_TAIL_DISCOVERY: 8,
    Purpose.TRANSCRIPT_DISCOVERY: 4,
    Purpose.SOURCE_DISCOVERY: 4,
    Purpose.SOCIAL_LEAD_DISCOVERY: 4,
}

assert sum(DEFAULT_PURPOSE_QUOTA_PCT.values()) <= 100 - DEFAULT_RESERVE_PCT, (
    "purpose quotas would consume the operator reserve"
)

#: Cache TTL by query class, in seconds. A catalyst question goes stale fast; a
#: primary-source or feed-discovery answer does not.
DEFAULT_TTL: dict[Purpose, int] = {
    Purpose.CATALYST_CORROBORATION: 30 * 60,
    Purpose.EVIDENCE_GAP: 6 * 3600,
    Purpose.SOCIAL_LEAD_DISCOVERY: 3 * 3600,
    Purpose.TRANSCRIPT_DISCOVERY: 24 * 3600,
    Purpose.PRIMARY_SOURCE_DISCOVERY: 24 * 3600,
    Purpose.CONTRADICTION_SEARCH: 12 * 3600,
    Purpose.LONG_TAIL_DISCOVERY: 7 * 24 * 3600,
    Purpose.SOURCE_DISCOVERY: 30 * 24 * 3600,
}

COALESCE_WAIT_SECONDS = 12


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default  # a bad override keeps the safe default


def reserve_pct() -> int:
    return max(0, min(100, _env_int("BRAVE_RESERVE_PCT", DEFAULT_RESERVE_PCT)))


# ── Paths (always parameterised so tests never touch production state) ───────


def _state_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    try:
        from scripts.lib.search_budget import budget_path

        return budget_path().parent.parent.parent
    except Exception:
        return Path.home() / "trade-ai-releases" / "persistent-state"


def cache_dir(root: Optional[Path] = None) -> Path:
    return _state_root(root) / "data" / "runtime" / "brave_router_cache"


def metrics_path(root: Optional[Path] = None) -> Path:
    return _state_root(root) / "data" / "runtime" / "brave_router_metrics.json"


def allowance_path(root: Optional[Path] = None) -> Path:
    return _state_root(root) / "data" / "runtime" / "brave_observed_allowance.json"


# ── Query fingerprinting ────────────────────────────────────────────────────

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s:/.\-]")


def normalize_query(query: str) -> str:
    """Normalise so trivially different spellings share one cache slot.

    Case, surrounding punctuation and whitespace runs are not semantic. Token
    ORDER is preserved: "TSLA recall" and "recall TSLA" are the same words but
    a search engine does not treat them identically, and silently merging them
    would return an answer to a question nobody asked.
    """
    q = _PUNCT.sub(" ", (query or "").lower())
    return _WS.sub(" ", q).strip()


def fingerprint(query: str, *, endpoint: str = "web", freshness: Optional[str] = None, count: int = 5) -> str:
    """Stable id for (normalised query, endpoint, freshness, count)."""
    payload = json.dumps(
        {
            "q": normalize_query(query),
            "endpoint": endpoint,
            "freshness": freshness or "",
            "count": int(count),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


# ── Result / outcome types ──────────────────────────────────────────────────


@dataclass
class Result:
    """One discovery artifact. Never a verified fact."""

    title: str
    url: str
    description: str
    age: str = ""
    source_domain: str = ""
    attribution: str = ATTRIBUTION
    is_primary_source: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Outcome:
    """What actually happened. Callers branch on ``status``, not on emptiness."""

    status: Status
    results: list[Result] = field(default_factory=list)
    reason: str = ""
    query: str = ""
    fingerprint: str = ""
    purpose: str = ""
    priority: int = Priority.COLD_UNIVERSE.value
    caller: str = ""
    endpoint: str = "web"
    provider_billed: bool = False
    cache_hit: bool = False
    http_status: Optional[int] = None
    latency_ms: Optional[int] = None
    observed_allowance: dict[str, Any] = field(default_factory=dict)
    budget_status: dict[str, Any] = field(default_factory=dict)
    as_of: str = ""
    schema: str = SCHEMA
    authority: str = AUTHORITY

    @property
    def ok(self) -> bool:
        """Served an answer we may use — including a legitimately empty one."""
        return self.status in (Status.OK, Status.EMPTY, Status.CACHED, Status.COALESCED)

    @property
    def degraded(self) -> bool:
        return not self.ok

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["results"] = [r.to_dict() for r in self.results]
        d["ok"] = self.ok
        d["degraded"] = self.degraded
        return d

    def degradation_note(self) -> str:
        """Operator-legible reason, for a UI that must not print DATA_UNAVAILABLE."""
        return {
            Status.OK: "",
            Status.EMPTY: "No results published for this query.",
            Status.CACHED: "",
            Status.COALESCED: "",
            Status.DENIED_NO_KEY: "Search unavailable: provider key not configured.",
            Status.DENIED_BUDGET: "Search budget exhausted for this period.",
            Status.DENIED_RESERVE: "Search reserved for held-capital and urgent catalysts.",
            Status.DENIED_PURPOSE_QUOTA: "Search quota for this purpose is exhausted.",
            Status.DENIED_POLICY: "Search not permitted for this purpose.",
            Status.DENIED_NO_EVIDENCE_GAP: "No material evidence gap; free sources answered.",
            Status.DENIED_WEEKEND: "Deferred to the next session: markets are closed and this is scheduled background research.",
            Status.BUDGET_UNAVAILABLE: "Search budget could not be established.",
            Status.UNAUTHORIZED: "Search provider rejected the credential.",
            Status.PAYMENT_REQUIRED: "Search provider reports the plan is exhausted.",
            Status.FORBIDDEN: "Search provider refused the request.",
            Status.RATE_LIMITED: "Search provider rate-limited the request.",
            Status.SERVER_ERROR: "Search provider error.",
            Status.TIMEOUT: "Search provider did not respond in time.",
            Status.TRANSPORT_ERROR: "Search provider unreachable.",
            Status.MALFORMED: "Search provider returned an unreadable response.",
        }.get(self.status, "Search unavailable.")


# ── Primary-source preference ───────────────────────────────────────────────

#: Domains that host the thing itself rather than someone's summary of it.
PRIMARY_SOURCE_PATTERNS = (
    ".gov",
    "sec.gov",
    "federalreserve.gov",
    "supremecourt.gov",
    "courtlistener.com",
    "uspto.gov",
    "fda.gov",
    "europa.eu",
    "gov.uk",
    "investor.",
    "ir.",
    "investors.",
    "/investor",
    "/press-release",
    "/news-releases",
    "businesswire.com",
    "prnewswire.com",
    "globenewswire.com",
    "accesswire.com",
    "nasdaq.com/market-activity",
    "nyse.com",
)


def _domain(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:
        return ""


def is_primary_source(url: str) -> bool:
    u = (url or "").lower()
    return any(p in u for p in PRIMARY_SOURCE_PATTERNS)


def rank_results(results: list[Result]) -> list[Result]:
    """Primary sources first, then one-per-domain for diversity, then the rest.

    Ranking never changes a snippet's trust level — it changes which discovery
    artifact a researcher reads first.
    """
    seen: set[str] = set()
    primary: list[Result] = []
    diverse: list[Result] = []
    rest: list[Result] = []
    for r in results:
        d = r.source_domain or _domain(r.url)
        if r.is_primary_source:
            primary.append(r)
        elif d and d not in seen:
            seen.add(d)
            diverse.append(r)
        else:
            rest.append(r)
    return primary + diverse + rest


def unique_domains(results: list[Result]) -> list[str]:
    out: list[str] = []
    for r in results:
        d = r.source_domain or _domain(r.url)
        if d and d not in out:
            out.append(d)
    return out


# ── Durable, cross-process cache ────────────────────────────────────────────


def _cache_file(fp: str, root: Optional[Path] = None) -> Path:
    return cache_dir(root) / f"{fp}.json"


def cache_get(fp: str, ttl: int, *, root: Optional[Path] = None, now: Optional[float] = None) -> Optional[list[Result]]:
    """Return cached results when still inside TTL, else ``None``.

    Unlike the in-process dict this replaces, this survives the process that
    filled it, which is the entire point: the duplicate spend being eliminated
    is between two *cron invocations*, not two calls in one function.
    """
    now = now if now is not None else time.time()
    path = _cache_file(fp, root)
    try:
        if not path.exists():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None  # unreadable cache = miss, never an error
    if not isinstance(doc, dict):
        return None
    if now - float(doc.get("stored_at", 0)) > ttl:
        return None
    try:
        return [Result(**r) for r in doc.get("results", [])]
    except Exception:
        return None


def cache_put(
    fp: str, results: list[Result], *, query: str = "", root: Optional[Path] = None, now: Optional[float] = None
) -> None:
    now = now if now is not None else time.time()
    path = _cache_file(fp, root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "fingerprint": fp,
                    "query": query,
                    "stored_at": now,
                    "stored_at_iso": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                    "results": [r.to_dict() for r in results],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(path)  # atomic; a torn cache reads as a miss
    except Exception:
        pass  # cache is an optimisation, never a gate


@contextmanager
def _coalesce_lock(fp: str, root: Optional[Path] = None) -> Iterator[bool]:
    """Serialize identical in-flight queries.

    Yields True when this caller holds the lock and should do the work, False
    when it waited for another caller that was already asking the same
    question — that caller's answer is now in the cache.
    """
    d = cache_dir(root)
    try:
        d.mkdir(parents=True, exist_ok=True)
        lock = d / f"{fp}.lock"
        lock.touch(exist_ok=True)
    except Exception:
        yield True  # cannot lock → proceed rather than stall
        return
    lf = None
    try:
        lf = open(lock, "a+")
        try:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield True
        except BlockingIOError:
            # Someone else is asking. Wait for them, then use their answer.
            deadline = time.time() + COALESCE_WAIT_SECONDS
            got = False
            while time.time() < deadline:
                try:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    got = True
                    break
                except BlockingIOError:
                    time.sleep(0.05)
            yield False if got else True
    except Exception:
        yield True
    finally:
        if lf is not None:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            try:
                lf.close()
            except Exception:
                pass


# ── Observed plan allowance (never a guessed tier) ──────────────────────────

_ALLOWANCE_HEADERS = (
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-ratelimit-policy",
)


def _parse_windowed(value: str) -> list[int]:
    out: list[int] = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part.split(";")[0].strip()))
        except ValueError:
            pass
    return out


def _parse_policy(value: str) -> list[int]:
    """``50;w=1, 0;w=2592000`` -> ``[1, 2592000]`` (window sizes, in order)."""
    windows: list[int] = []
    for part in str(value).split(","):
        m = re.search(r"w\s*=\s*(\d+)", part)
        windows.append(int(m.group(1)) if m else 0)
    return windows


def parse_allowance(headers: Any) -> dict[str, Any]:
    """Extract Brave's real rate-limit metadata from a response.

    Brave reports **one value per window**, ascending by window size, and names
    those windows in ``x-ratelimit-policy``:

        x-ratelimit-policy    50;w=1, 0;w=2592000
        x-ratelimit-limit     50, 0
        x-ratelimit-remaining 49, 0

    Measured live 2026-09-03: ``50;w=1`` is **50 requests per second**, and
    ``w=2592000`` is the 30-day billing window. Taking ``max()`` over those
    numbers — as an obvious first reading does — reports the per-second rate as
    a monthly quota, which is how a plan can look like it allows 50 calls a
    month. The billing window is the one with the **largest w**, not the
    largest value.

    A billing-window limit of ``0`` alongside a successful request is reported
    as ``billing_window_metered=False`` rather than "zero calls allowed": the
    provider is not publishing a monthly cap on this plan, and inventing either
    a number or an exhaustion from that would be a guess. Nothing in the tree
    read these headers before, which is why the ceiling stayed hardcoded.
    """
    out: dict[str, Any] = {}
    if headers is None:
        return out
    for h in _ALLOWANCE_HEADERS:
        try:
            v = headers.get(h) if hasattr(headers, "get") else None
        except Exception:
            v = None
        if v:
            out[h] = str(v).strip()

    limits = _parse_windowed(out.get("x-ratelimit-limit", ""))
    remaining = _parse_windowed(out.get("x-ratelimit-remaining", ""))
    resets = _parse_windowed(out.get("x-ratelimit-reset", ""))
    windows = _parse_policy(out.get("x-ratelimit-policy", "")) if out.get("x-ratelimit-policy") else []

    if not limits:
        return out
    out["limit_windows"] = limits
    if remaining:
        out["remaining_windows"] = remaining

    # Pick the billing window: largest declared w, else the last value (Brave
    # orders windows ascending, so the last one is the longest period).
    if windows and len(windows) == len(limits):
        idx = max(range(len(windows)), key=lambda i: windows[i])
        out["billing_window_seconds"] = windows[idx]
        if windows[0] == 1:
            out["rate_limit_per_second"] = limits[0]
    else:
        idx = len(limits) - 1
        if len(limits) > 1:
            out["rate_limit_per_second"] = limits[0]

    out["billing_window_limit"] = limits[idx]
    if idx < len(remaining):
        out["billing_window_remaining"] = remaining[idx]
    if idx < len(resets):
        out["billing_window_reset_seconds"] = resets[idx]
    out["billing_window_metered"] = limits[idx] > 0

    # Only publish a monthly number when the provider actually meters one.
    if limits[idx] > 0:
        out["measured_monthly_limit"] = limits[idx]
        if idx < len(remaining):
            out["measured_monthly_remaining"] = remaining[idx]
    return out


def record_allowance(observed: dict[str, Any], *, root: Optional[Path] = None, now: Optional[datetime] = None) -> None:
    """Persist the measured allowance so policy can be reconciled against it."""
    if not observed:
        return
    now = now or datetime.now(timezone.utc)
    path = allowance_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {}
        if path.exists():
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                doc = {}
        doc.update(
            {
                "schema": SCHEMA,
                "provider": PROVIDER,
                "observed_at": now.replace(microsecond=0).isoformat(),
                "observed": observed,
            }
        )
        hist = doc.setdefault("history", [])
        hist.append({"at": now.replace(microsecond=0).isoformat(), **observed})
        doc["history"] = hist[-50:]
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def observed_allowance(*, root: Optional[Path] = None) -> dict[str, Any]:
    """Last measured allowance, or ``{}`` when never measured.

    An empty return is meaningful: it means the configured ceiling has never
    been reconciled against the provider and is still an assumption.
    """
    try:
        p = allowance_path(root)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _reconciliation_note(configured, measured, obs: dict[str, Any]) -> str:
    if not obs:
        return (
            "Configured ceiling has never been reconciled against a measured "
            "provider allowance; it remains an assumption."
        )
    if obs.get("billing_window_metered") is False:
        rate = obs.get("rate_limit_per_second")
        return (
            "Provider publishes NO metered billing-window quota on this plan "
            f"(policy declares 0 for the {obs.get('billing_window_seconds')}s "
            f"window; rate limit {rate}/s). The configured monthly ceiling of "
            f"{configured} is therefore a LOCAL POLICY cap, not a provider "
            "limit, and must be justified on cost grounds rather than presented "
            "as the plan allowance."
        )
    if measured is None:
        return (
            "Provider returned rate-limit headers but no billing-window "
            "quota could be read; ceiling remains unreconciled."
        )
    if configured is not None and configured <= measured:
        return "Configured ceiling is at or below the measured plan allowance."
    return "Configured ceiling EXCEEDS the measured plan allowance — lower it."


def allowance_reconciliation(*, root: Optional[Path] = None) -> dict[str, Any]:
    """Compare the *configured* policy ceiling with the *measured* plan."""
    try:
        from scripts.lib.search_budget import _limits
    except Exception:
        try:
            from lib.search_budget import _limits  # type: ignore
        except Exception:
            _limits = None  # type: ignore
    configured = _limits(PROVIDER)["monthly"] if _limits else None
    obs = observed_allowance(root=root)
    obs_o = obs.get("observed") or {}
    measured = obs_o.get("measured_monthly_limit")
    return {
        "configured_monthly_limit": configured,
        "measured_monthly_limit": measured,
        "measured_at": obs.get("observed_at"),
        "reconciled": measured is not None,
        "rate_limit_per_second": obs_o.get("rate_limit_per_second"),
        "billing_window_seconds": obs_o.get("billing_window_seconds"),
        "billing_window_metered": obs_o.get("billing_window_metered"),
        "note": _reconciliation_note(configured, measured, obs_o),
    }


# ── Effectiveness metrics (optimise for adopted evidence, not call count) ────

_METRIC_KEYS = (
    "attempted",
    "allowed",
    "denied",
    "cache_hits",
    "coalesced",
    "nonempty",
    "empty",
    "errors",
    "billed",
    "adopted",
    "evidence_gaps_closed",
)


@contextmanager
def _metrics_lock(root: Optional[Path] = None) -> Iterator[Path]:
    path = metrics_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".json.lock")
    if not lock.exists():
        lock.touch()
    with open(lock, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield path
        finally:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _load_metrics(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": SCHEMA, "periods": {}}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            doc.setdefault("periods", {})
            return doc
    except Exception:
        pass
    return {"schema": SCHEMA, "periods": {}}


def record_metric(outcome: "Outcome", *, root: Optional[Path] = None, now: Optional[datetime] = None) -> None:
    """Count one routed decision. Never raises; metrics must not break research."""
    now = now or datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    try:
        with _metrics_lock(root) as path:
            doc = _load_metrics(path)
            p = doc["periods"].setdefault(month, {k: 0 for k in _METRIC_KEYS})
            for k in _METRIC_KEYS:
                p.setdefault(k, 0)
            p["attempted"] += 1
            if outcome.status in NOT_CALLED and outcome.status not in (Status.CACHED, Status.COALESCED):
                p["denied"] += 1
            if outcome.status is Status.CACHED:
                p["cache_hits"] += 1
            if outcome.status is Status.COALESCED:
                p["coalesced"] += 1
            if outcome.provider_billed:
                p["billed"] += 1
            if outcome.status in (Status.OK, Status.CACHED, Status.COALESCED):
                p["allowed"] += 1
                if outcome.results:
                    p["nonempty"] += 1
            if outcome.status is Status.EMPTY:
                p["allowed"] += 1
                p["empty"] += 1
            if outcome.status in (
                Status.UNAUTHORIZED,
                Status.PAYMENT_REQUIRED,
                Status.FORBIDDEN,
                Status.RATE_LIMITED,
                Status.SERVER_ERROR,
                Status.TIMEOUT,
                Status.TRANSPORT_ERROR,
                Status.MALFORMED,
            ):
                p["errors"] += 1

            by_purpose = doc.setdefault("by_purpose", {}).setdefault(month, {})
            bp = by_purpose.setdefault(outcome.purpose or "UNKNOWN", {"attempted": 0, "billed": 0, "adopted": 0})
            bp["attempted"] += 1
            if outcome.provider_billed:
                bp["billed"] += 1

            doms = doc.setdefault("domains", {}).setdefault(month, {})
            for d in unique_domains(outcome.results):
                doms[d] = doms.get(d, 0) + 1

            hb = doc.setdefault("heartbeat", {})
            iso = now.replace(microsecond=0).isoformat()
            hb["last_attempt"] = iso
            if outcome.status in (Status.OK, Status.EMPTY):
                hb["last_success"] = iso
            if outcome.results:
                hb["last_nonempty"] = iso

            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
    except Exception:
        pass


def record_adoption(
    fingerprint_or_purpose: str,
    *,
    purpose: str = "",
    closed_evidence_gap: bool = False,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> None:
    """Mark that a downstream research product actually cited a Brave result.

    Adoption is the metric that matters. A lane that spends its allowance and
    produces evidence nobody cites is ``PRODUCING_NOT_ADOPTED``, not healthy.
    """
    now = now or datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    try:
        with _metrics_lock(root) as path:
            doc = _load_metrics(path)
            p = doc["periods"].setdefault(month, {k: 0 for k in _METRIC_KEYS})
            p.setdefault("adopted", 0)
            p["adopted"] += 1
            if closed_evidence_gap:
                p["evidence_gaps_closed"] = p.get("evidence_gaps_closed", 0) + 1
            key = purpose or fingerprint_or_purpose
            bp = (
                doc.setdefault("by_purpose", {})
                .setdefault(month, {})
                .setdefault(key, {"attempted": 0, "billed": 0, "adopted": 0})
            )
            bp["adopted"] = bp.get("adopted", 0) + 1
            doc.setdefault("heartbeat", {})["last_adopted"] = now.replace(microsecond=0).isoformat()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
    except Exception:
        pass


def effectiveness_report(*, root: Optional[Path] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """The Phase-4 effectiveness view. Optimised for adoption, not volume."""
    now = now or datetime.now(timezone.utc)
    month = now.strftime("%Y-%m")
    path = metrics_path(root)
    doc = _load_metrics(path)
    p = dict(doc.get("periods", {}).get(month, {}))
    for k in _METRIC_KEYS:
        p.setdefault(k, 0)
    attempted = p["attempted"] or 0
    billed = p["billed"] or 0
    doms = doc.get("domains", {}).get(month, {})
    try:
        from scripts.lib.search_budget import status as _bstatus

        budget = _bstatus(PROVIDER, root=Path(root) if root else None)
    except Exception:
        budget = {}
    monthly_limit = budget.get("monthly_limit")
    monthly_used = budget.get("monthly_used")
    reserve = int((monthly_limit or 0) * reserve_pct() / 100)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "provider": PROVIDER,
        "period": month,
        "as_of": now.replace(microsecond=0).isoformat(),
        "attempted": attempted,
        "allowed": p["allowed"],
        "denied": p["denied"],
        "billed": billed,
        "cache_hits": p["cache_hits"],
        "coalesced": p["coalesced"],
        "cache_hit_rate_pct": round(p["cache_hits"] / attempted * 100, 1) if attempted else 0.0,
        "coalesce_rate_pct": round(p["coalesced"] / attempted * 100, 1) if attempted else 0.0,
        "nonempty": p["nonempty"],
        "empty": p["empty"],
        "errors": p["errors"],
        "nonempty_rate_pct": round(p["nonempty"] / billed * 100, 1) if billed else 0.0,
        "adopted": p["adopted"],
        "evidence_gaps_closed": p["evidence_gaps_closed"],
        "adoption_rate_pct": round(p["adopted"] / billed * 100, 1) if billed else 0.0,
        "calls_per_adopted_evidence": round(billed / p["adopted"], 2) if p["adopted"] else None,
        "unique_domains": len(doms),
        "top_domains": sorted(doms.items(), key=lambda kv: -kv[1])[:10],
        "by_purpose": doc.get("by_purpose", {}).get(month, {}),
        "heartbeat": doc.get("heartbeat", {}),
        "budget": budget,
        "monthly_limit": monthly_limit,
        "monthly_used": monthly_used,
        "monthly_remaining": (monthly_limit - monthly_used)
        if (monthly_limit is not None and monthly_used is not None)
        else None,
        "reserve_pct": reserve_pct(),
        "reserve_calls": reserve,
        "allowance_reconciliation": allowance_reconciliation(root=root),
    }


# ── Gating ──────────────────────────────────────────────────────────────────


def _api_key(project_root: Optional[Path] = None) -> Optional[str]:
    key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if key:
        return key
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    env = root / ".env"
    try:
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("BRAVE_SEARCH_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def purpose_quota(purpose: Purpose, monthly_limit: int) -> int:
    """Absolute call ceiling for one purpose this period."""
    env = os.getenv(f"BRAVE_QUOTA_{purpose.value}")
    if env:
        try:
            return max(0, int(env))
        except ValueError:
            pass
    pct = DEFAULT_PURPOSE_QUOTA_PCT.get(purpose, 5)
    return int(monthly_limit * pct / 100)


def _purpose_used(purpose: Purpose, *, root: Optional[Path] = None, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    doc = _load_metrics(metrics_path(root))
    bp = doc.get("by_purpose", {}).get(now.strftime("%Y-%m"), {})
    return int((bp.get(purpose.value) or {}).get("billed", 0))


#: Priorities exempt from the weekend deferral. The 2026-08 incident this
#: preserves: routing on-demand research through a bulk-job weekend heuristic
#: made every interactive Saturday lookup return ``[]`` — indistinguishable
#: from "nothing was published". Held capital and urgent catalysts are never
#: deferred, and a deferral is now a named status carrying a reason rather than
#: an empty list.
WEEKEND_EXEMPT = frozenset({Priority.HELD_CAPITAL, Priority.URGENT_CATALYST})

SKIP_WEEKENDS = True


def is_weekend(now: datetime) -> bool:
    return now.weekday() >= 5


def evaluate_gates(
    *,
    purpose: Purpose,
    priority: Priority,
    caller: str,
    evidence_gap: bool = True,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Optional[tuple[Status, str, dict]]:
    """Return ``None`` when the call may proceed, else the refusal.

    Order matters: policy before spend, so a forbidden purpose is refused for
    the right reason even when the budget is wide open.
    """
    now = now or datetime.now(timezone.utc)

    if purpose in FORBIDDEN_PURPOSES:
        return (Status.DENIED_POLICY, f"purpose {purpose.value} is not an approved use of paid search", {})

    if not evidence_gap:
        return (Status.DENIED_NO_EVIDENCE_GAP, "canonical free sources answered the question; no material gap", {})

    if SKIP_WEEKENDS and is_weekend(now) and priority not in WEEKEND_EXEMPT:
        return (
            Status.DENIED_WEEKEND,
            f"markets closed and priority {priority.name} is scheduled "
            f"background research; deferred to the next session",
            {},
        )

    try:
        from scripts.lib.search_budget import status as _bstatus
    except Exception:
        try:
            from lib.search_budget import status as _bstatus  # type: ignore
        except Exception:
            return (Status.BUDGET_UNAVAILABLE, "shared budget module unavailable — DENY (never fail open)", {})

    try:
        st = _bstatus(PROVIDER, now=now, root=Path(root) if root else None)
    except Exception as e:
        return (Status.BUDGET_UNAVAILABLE, f"{type(e).__name__}: {e}", {})

    monthly_limit = int(st.get("monthly_limit") or 0)
    monthly_used = int(st.get("monthly_used") or 0)
    remaining = monthly_limit - monthly_used

    if remaining <= 0:
        return (Status.DENIED_BUDGET, "MONTHLY_EXHAUSTED", st)
    if int(st.get("daily_used") or 0) >= int(st.get("daily_limit") or 0):
        return (Status.DENIED_BUDGET, "DAILY_EXHAUSTED", st)

    reserve = int(monthly_limit * reserve_pct() / 100)
    if remaining <= reserve and priority not in RESERVE_ELIGIBLE:
        return (
            Status.DENIED_RESERVE,
            f"remaining {remaining} is within the {reserve}-call operator "
            f"reserve; priority {priority.name} may not draw on it",
            st,
        )

    quota = purpose_quota(purpose, monthly_limit)
    used = _purpose_used(purpose, root=root, now=now)
    if quota and used >= quota:
        return (Status.DENIED_PURPOSE_QUOTA, f"purpose {purpose.value} used {used}/{quota} this period", st)

    return None


# ── The one governed entry point ────────────────────────────────────────────


def search(
    query: str,
    *,
    purpose: Purpose | str = Purpose.EVIDENCE_GAP,
    priority: Priority | int = Priority.WATCHLIST,
    caller: str = "unknown",
    count: int = 5,
    freshness: Optional[str] = None,
    endpoint: str = "web",
    evidence_gap: bool = True,
    project_root: Optional[Path] = None,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    allow_network: bool = True,
) -> Outcome:
    """Route one Brave query through policy, budget, cache and coalescing.

    Every path returns an :class:`Outcome`. No path returns a bare list, and no
    path raises: a research caller must always be able to tell *why* it has no
    results, and must never crash a scheduled job because a provider blinked.

    ``allow_network=False`` runs every gate and cache layer but refuses to make
    a real request — the dry-run mode the negative controls use.
    """
    now = now or datetime.now(timezone.utc)
    purpose = Purpose(purpose) if not isinstance(purpose, Purpose) else purpose
    priority = Priority(priority) if not isinstance(priority, Priority) else priority
    fp = fingerprint(query, endpoint=endpoint, freshness=freshness, count=count)
    iso = now.replace(microsecond=0).isoformat()

    def _out(
        status: Status,
        *,
        results: Optional[list[Result]] = None,
        reason: str = "",
        billed: bool = False,
        cache_hit: bool = False,
        http_status: Optional[int] = None,
        latency_ms: Optional[int] = None,
        allowance: Optional[dict] = None,
        budget: Optional[dict] = None,
    ) -> Outcome:
        o = Outcome(
            status=status,
            results=results or [],
            reason=reason,
            query=query,
            fingerprint=fp,
            purpose=purpose.value,
            priority=int(priority),
            caller=caller,
            endpoint=endpoint,
            provider_billed=billed,
            cache_hit=cache_hit,
            http_status=http_status,
            latency_ms=latency_ms,
            observed_allowance=allowance or {},
            budget_status=budget or {},
            as_of=iso,
        )
        record_metric(o, root=root, now=now)
        return o

    ttl = DEFAULT_TTL.get(purpose, 6 * 3600)

    # 1. Durable cache — before any gate, because a cache hit costs nothing and
    #    must not be denied by a budget it does not consume.
    cached = cache_get(fp, ttl, root=root)
    if cached is not None:
        return _out(Status.CACHED, results=rank_results(cached), cache_hit=True, reason=f"cache hit within {ttl}s TTL")

    # 2. Gates.
    refusal = evaluate_gates(
        purpose=purpose, priority=priority, caller=caller, evidence_gap=evidence_gap, root=root, now=now
    )
    if refusal is not None:
        status, reason, budget = refusal
        return _out(status, reason=reason, budget=budget)

    if not allow_network:
        return _out(Status.DENIED_POLICY, reason="allow_network=False (dry run): gates passed, no request made")

    key = _api_key(project_root)
    if not key:
        return _out(Status.DENIED_NO_KEY, reason="BRAVE_SEARCH_API_KEY not configured")

    # 3. Coalesce identical in-flight queries.
    with _coalesce_lock(fp, root) as should_work:
        if not should_work:
            waited = cache_get(fp, ttl, root=root)
            if waited is not None:
                return _out(
                    Status.COALESCED,
                    results=rank_results(waited),
                    cache_hit=True,
                    reason="shared an in-flight identical query",
                )
            # The other caller finished without a usable answer; fall through.

        # Re-check the cache: the holder may have filled it while we waited.
        again = cache_get(fp, ttl, root=root)
        if again is not None:
            return _out(
                Status.CACHED,
                results=rank_results(again),
                cache_hit=True,
                reason="cache filled by a concurrent identical query",
            )

        # 4. Atomically consume one budget unit. try_consume (not check) so two
        #    processes cannot both observe the last unit and both spend it.
        try:
            from scripts.lib.search_budget import try_consume
        except Exception:
            try:
                from lib.search_budget import try_consume  # type: ignore
            except Exception:
                return _out(Status.BUDGET_UNAVAILABLE, reason="shared budget module unavailable — DENY")
        verdict = try_consume(PROVIDER, caller=caller, root=Path(root) if root else None)
        if not verdict.get("allowed"):
            reason = str(verdict.get("reason") or "denied")
            status = Status.BUDGET_UNAVAILABLE if reason.startswith("BUDGET_UNAVAILABLE") else Status.DENIED_BUDGET
            return _out(status, reason=reason, budget=verdict.get("status") or {})

        # 5. Make the one paid request.
        return _execute(
            query, fp=fp, key=key, count=count, freshness=freshness, endpoint=endpoint, out=_out, root=root, now=now
        )


def _execute(
    query: str, *, fp: str, key: str, count: int, freshness: Optional[str], endpoint: str, out, root, now
) -> Outcome:
    """Issue the request and classify the response. Never raises."""
    base = NEWS_URL if endpoint == "news" else WEB_URL
    params = {
        "q": query,
        "count": max(1, min(int(count), 20)),
        "text_decorations": "false",
        "search_lang": "en",
        "country": "US",
    }
    if freshness:
        params["freshness"] = freshness
    url = f"{base}?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json", "Accept-Encoding": "gzip", "X-Subscription-Token": key}
    started = time.time()
    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read()
            allowance = parse_allowance(getattr(resp, "headers", None))
            http_status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as e:
        latency = int((time.time() - started) * 1000)
        allowance = parse_allowance(getattr(e, "headers", None))
        if allowance:
            record_allowance(allowance, root=root, now=now)
        status = {
            401: Status.UNAUTHORIZED,
            402: Status.PAYMENT_REQUIRED,
            403: Status.FORBIDDEN,
            429: Status.RATE_LIMITED,
        }.get(e.code, Status.SERVER_ERROR if e.code >= 500 else Status.TRANSPORT_ERROR)
        return out(
            status,
            reason=f"HTTP {e.code}: {e.reason}",
            billed=status in BILLED,
            http_status=e.code,
            latency_ms=latency,
            allowance=allowance,
        )
    except TimeoutError:
        return out(
            Status.TIMEOUT, reason=f"no response in {REQUEST_TIMEOUT}s", latency_ms=int((time.time() - started) * 1000)
        )
    except Exception as e:
        if "timed out" in str(e).lower():
            return out(
                Status.TIMEOUT, reason=f"{type(e).__name__}: {e}", latency_ms=int((time.time() - started) * 1000)
            )
        return out(
            Status.TRANSPORT_ERROR, reason=f"{type(e).__name__}: {e}", latency_ms=int((time.time() - started) * 1000)
        )

    latency = int((time.time() - started) * 1000)
    if allowance:
        record_allowance(allowance, root=root, now=now)

    try:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        doc = json.loads(raw)
    except Exception as e:
        return out(
            Status.MALFORMED,
            reason=f"unparseable body: {type(e).__name__}: {e}",
            billed=True,
            http_status=http_status,
            latency_ms=latency,
            allowance=allowance,
        )

    if endpoint == "news":
        raw_results = doc.get("results") or []
    else:
        raw_results = (doc.get("web") or {}).get("results") or []

    results: list[Result] = []
    for r in raw_results:
        if not isinstance(r, dict):
            continue
        u = r.get("url", "") or ""
        results.append(
            Result(
                title=(r.get("title") or "")[:300],
                url=u,
                description=(r.get("description") or "")[:600],
                age=r.get("age") or "",
                source_domain=_domain(u) or ((r.get("meta_url") or {}).get("hostname") or ""),
                attribution=ATTRIBUTION,
                is_primary_source=is_primary_source(u),
            )
        )

    results = rank_results(results)
    if results:
        cache_put(fp, results, query=query, root=root)
        return out(
            Status.OK, results=results, billed=True, http_status=http_status, latency_ms=latency, allowance=allowance
        )
    # A genuinely empty answer is still cached: re-asking it costs a credit and
    # returns the same nothing.
    cache_put(fp, [], query=query, root=root)
    return out(
        Status.EMPTY,
        reason="provider returned zero results",
        billed=True,
        http_status=http_status,
        latency_ms=latency,
        allowance=allowance,
    )


def health(*, root: Optional[Path] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """One lane row for research_lane_health, with the four separate clocks."""
    now = now or datetime.now(timezone.utc)
    rep = effectiveness_report(root=root, now=now)
    hb = rep.get("heartbeat", {})
    firing: list[str] = []
    if not _api_key():
        firing.append("brave_key_missing")
    if rep.get("monthly_remaining") is not None and rep["monthly_remaining"] <= 0:
        firing.append("brave_monthly_exhausted")
    if not rep["allowance_reconciliation"]["reconciled"]:
        firing.append("brave_allowance_never_measured")
    if rep["billed"] and rep["adopted"] == 0:
        firing.append("brave_producing_not_adopted")
    return {
        "lane": "brave-research-router",
        "ok": not firing,
        "firing": firing,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "last_attempt": hb.get("last_attempt"),
        "last_success": hb.get("last_success"),
        "last_nonempty": hb.get("last_nonempty"),
        "last_adopted": hb.get("last_adopted"),
        "effectiveness": rep,
    }
