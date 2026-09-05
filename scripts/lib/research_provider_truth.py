"""research_provider_truth.py — what the PROVIDER imposes vs what WE chose.

READ_ONLY_ADVISORY. Pure functions. No network, no credentials, no side effects.

THE DEFECT THIS EXISTS TO MAKE UNSTATEABLE
------------------------------------------
`brave_search.py` says, in code:

    Daily budget cap: 30 requests/day (900/month with buffer for 1,000/month free tier)
    MONTHLY_BUDGET = 850  # Reserve 150 for P0/manual searches out of 1000

Nothing in this repository ever observed a 1,000/month Brave plan. The number is
an assumption written as a fact, and the ceiling derived from it — 850 — then
reads as "the provider allows 1000, we reserve 150", when it is really "we chose
850 for our own reasons". Every caller, dashboard and operator inherits that
framing.

Worse, `brave_search.py` discards the answer. It calls `urlopen(...)` and reads
only `resp.read()`; the `X-RateLimit-*` headers Brave returns on every response
are never parsed. The one authority that could settle provider capacity is
received and thrown away on every single call.

This is the same shape as the Command Center header defects fixed this week: a
value that was true-or-assumed once, rendered as a live fact, with the real
measurement available and unread.

So this module keeps two things apart and refuses to merge them:

  ProviderCapacity   what the provider TOLD us, parsed from response headers.
                     `observed=False` until a real response says otherwise, and
                     an unobserved capacity is never given a number.

  LocalCostPolicy    what WE chose, with a name and an owner. It is a cost and
                     risk decision, not a provider limit, and it says so.

A caller may ask "am I within policy?" and get a truthful answer whether or not
the provider has ever been observed. It may not ask this module to invent a
provider limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

SCHEMA = "ResearchProviderTruth@v1"

# Brave documents these on every REST response. Names are matched case-insensitively
# because header casing is not guaranteed across proxies.
#   X-RateLimit-Limit      e.g. "1, 15000"   (per-second, per-month) — comma-separated windows
#   X-RateLimit-Remaining  e.g. "1, 14999"
#   X-RateLimit-Reset      e.g. "1, 1419704"  seconds until each window resets
HDR_LIMIT = "x-ratelimit-limit"
HDR_REMAINING = "x-ratelimit-remaining"
HDR_RESET = "x-ratelimit-reset"
HDR_POLICY = "x-ratelimit-policy"

#: Window labels, in the order Brave emits them.
WINDOW_LABELS = ("per_second", "per_month")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _split_windows(raw: Any) -> list[Optional[int]]:
    """Parse a comma-separated rate-limit header into per-window integers.

    A value we cannot parse becomes None rather than 0 — "unknown" and "none
    left" are different answers and must not collapse.
    """
    if raw is None:
        return []
    out: list[Optional[int]] = []
    for part in str(raw).split(","):
        part = part.strip()
        try:
            out.append(int(part))
        except (TypeError, ValueError):
            out.append(None)
    return out


@dataclass
class ProviderCapacity:
    """What the provider said. Never what we assumed."""

    provider: str
    observed: bool = False
    observed_at: Optional[str] = None
    #: window label -> limit / remaining / reset-seconds, as reported.
    windows: dict[str, dict[str, Optional[int]]] = field(default_factory=dict)
    policy: Optional[str] = None
    raw_headers: dict[str, str] = field(default_factory=dict)
    reason: str = "no provider response observed yet"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "provider": self.provider,
            "observed": self.observed,
            "observed_at": self.observed_at,
            "windows": self.windows,
            "policy": self.policy,
            "reason": self.reason,
            # Deliberately absent when unobserved: there is no "assumed_limit"
            # field, because a field like that is how an assumption becomes a fact.
        }

    def monthly_limit(self) -> Optional[int]:
        """The provider's monthly ceiling, or None if it has never said.

        A reported limit of **0** is NOT a ceiling of zero. Brave returns
        ``x-ratelimit-limit: 50, 0`` with ``policy: 50;w=1, 0;w=2592000`` on a
        key whose requests succeed with HTTP 200 — measured 2026-09-05. A window
        that admits traffic cannot have a real ceiling of zero, so 0 here means
        "this window is not metered", which is an absence of information and
        must be reported as None. Returning 0 made ``reconcile`` announce
        "provider reports 0/month — the local ceiling cannot be honoured" about
        a key that was serving fine: an invented limit, the exact defect class
        this module exists to prevent, produced by this module.
        """
        if not self.observed:
            return None
        lim = (self.windows.get("per_month") or {}).get("limit")
        if lim is not None and lim <= 0:
            return None
        return lim

    def monthly_metered(self) -> bool:
        """True only when the provider states a positive monthly ceiling."""
        return self.monthly_limit() is not None

    def describe(self) -> str:
        if not self.observed:
            return f"{self.provider} capacity NOT OBSERVED — {self.reason}"
        bits = []
        for label, w in self.windows.items():
            lim, rem = w.get("limit"), w.get("remaining")
            if lim is None:
                continue
            bits.append(f"{label} {rem if rem is not None else '?'}/{lim}")
        return f"{self.provider} observed {', '.join(bits) or 'no parseable window'}"


def parse_provider_capacity(
    provider: str,
    headers: Optional[Mapping[str, Any]],
    *,
    now: Optional[str] = None,
) -> ProviderCapacity:
    """Build a ProviderCapacity from a real HTTP response's headers.

    Absent or unparseable headers yield `observed=False` with a stated reason —
    never a default number. A provider that did not tell us its limit has not
    told us its limit.
    """
    cap = ProviderCapacity(provider=provider)
    if not headers:
        cap.reason = "response carried no headers"
        return cap

    lower = {str(k).lower(): str(v) for k, v in dict(headers).items()}
    limit_raw = lower.get(HDR_LIMIT)
    if limit_raw is None:
        cap.reason = f"response had no {HDR_LIMIT} header"
        cap.raw_headers = {k: v for k, v in lower.items() if "ratelimit" in k}
        return cap

    limits = _split_windows(limit_raw)
    remaining = _split_windows(lower.get(HDR_REMAINING))
    resets = _split_windows(lower.get(HDR_RESET))

    windows: dict[str, dict[str, Optional[int]]] = {}
    for i, lim in enumerate(limits):
        label = WINDOW_LABELS[i] if i < len(WINDOW_LABELS) else f"window_{i}"
        windows[label] = {
            "limit": lim,
            "remaining": remaining[i] if i < len(remaining) else None,
            "reset_seconds": resets[i] if i < len(resets) else None,
        }

    if not any(w.get("limit") is not None for w in windows.values()):
        cap.reason = f"{HDR_LIMIT} present but no window parsed: {limit_raw!r}"
        cap.raw_headers = {k: v for k, v in lower.items() if "ratelimit" in k}
        return cap

    cap.observed = True
    cap.observed_at = now or _now()
    cap.windows = windows
    cap.policy = lower.get(HDR_POLICY)
    cap.raw_headers = {k: v for k, v in lower.items() if "ratelimit" in k}
    cap.reason = "parsed from provider response headers"
    return cap


@dataclass(frozen=True)
class LocalCostPolicy:
    """A ceiling WE chose. Not a provider limit, and it must never be shown as one.

    `owner` and `rationale` are required by construction. A budget nobody owns is
    a number that outlives the reason for it — which is exactly how
    "850 out of 1000" survived long enough to be read as Brave's plan.
    """

    name: str
    owner: str
    rationale: str
    daily_calls: Optional[int] = None
    monthly_calls: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "kind": "local_cost_policy",
            "name": self.name,
            "owner": self.owner,
            "rationale": self.rationale,
            "daily_calls": self.daily_calls,
            "monthly_calls": self.monthly_calls,
            "authority": "LOCAL — chosen by this system, not imposed by the provider",
        }

    def describe(self) -> str:
        parts = []
        if self.daily_calls is not None:
            parts.append(f"{self.daily_calls}/day")
        if self.monthly_calls is not None:
            parts.append(f"{self.monthly_calls}/month")
        return f"{self.name} (local policy, owner {self.owner}): {', '.join(parts) or 'no ceiling'}"


#: The ceiling this repo has always applied, now named for what it is.
#:
#: The numbers are unchanged — this is not a behaviour change. What changes is
#: that they no longer claim to be derived from a 1,000/month provider plan
#: nobody measured. If the provider is ever observed to allow less than this,
#: `reconcile()` reports the conflict rather than silently over-spending.
BRAVE_LOCAL_COST_POLICY = LocalCostPolicy(
    name="LOCAL_MONTHLY_COST_POLICY",
    owner="operator (John) — Trade AI research cost control",
    rationale=(
        "Self-imposed spend ceiling for Brave research. Chosen locally to bound cost "
        "and leave manual/P0 headroom. NOT a provider plan: no Brave response observed "
        "by this system has ever stated a monthly quota."
    ),
    daily_calls=25,
    monthly_calls=850,
)


def reconcile(capacity: ProviderCapacity, policy: LocalCostPolicy) -> dict[str, Any]:
    """State both authorities and whether they conflict. Never merge them.

    `binding` names which ceiling actually constrains us, and is honest when the
    provider has never been observed: local policy binds because it is the only
    ceiling we know, not because it is the smaller of two.
    """
    provider_monthly = capacity.monthly_limit()
    local_monthly = policy.monthly_calls

    if provider_monthly is None:
        raw_month = (capacity.windows.get("per_month") or {}).get("limit")
        if capacity.observed and raw_month is not None and raw_month <= 0:
            # Observed, and the provider declined to meter this window.
            note = (
                f"provider reports a per_month window of {raw_month} (unmetered or "
                "not published in headers) — this is NOT a ceiling of zero; local "
                "policy is the only numeric ceiling"
            )
        else:
            note = "provider capacity unobserved — local policy is the only known ceiling"
        binding, conflict = "local_policy", None
    elif local_monthly is None:
        binding, note, conflict = "provider", "no local monthly ceiling set", None
    elif local_monthly > provider_monthly:
        binding = "provider"
        note = "local policy exceeds observed provider capacity"
        conflict = (
            f"LOCAL_MONTHLY_COST_POLICY allows {local_monthly}/month but the provider "
            f"reports {provider_monthly}/month — the local ceiling cannot be honoured"
        )
    else:
        binding, note, conflict = (
            "local_policy",
            "local policy is stricter than observed provider capacity",
            None,
        )

    return {
        "schema": SCHEMA,
        "generated_at": _now(),
        "provider_capacity": capacity.to_dict(),
        "local_policy": policy.to_dict(),
        "binding_ceiling": binding,
        "binding_reason": note,
        "conflict": conflict,
        # For a surface that wants one line without flattening the two authorities.
        "summary": f"{capacity.describe()} · {policy.describe()} · binding: {binding}",
    }
