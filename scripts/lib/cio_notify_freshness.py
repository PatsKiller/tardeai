"""Refuse to deliver an advisory whose narrative quotes a stale portfolio figure.

Found 2026-08-30: a live S6 plan was one wake away from telling the operator
"cash is elevated at 805800" when cash was 630,784.82 — a $175,015 overstatement
frozen into LLM prose on 2026-08-26 and never revalidated. The plan was
otherwise healthy: material, in-bar, past every existing gate.

An advisory that misstates the book is worse than no advisory, so this fails
CLOSED — no message beats a wrong message.

**Scoped deliberately.** It does NOT refuse everything older than the last
reprice: reprices run constantly, so that would silence the desk permanently
and the guard would be turned off within a day. It refuses only when the
narrative makes a checkable claim about a quantity we hold current truth for,
and that claim is contradicted. Plans that quote no figures are unaffected.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "NotifyFreshness@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

# How far a quoted figure may sit from truth before it is called a misstatement.
# 2% absorbs intraday drift and rounding in prose ("about 630k"); the case that
# prompted this was off by 27.8%.
TOLERANCE_PCT = 2.0

# A plan sets its own revisit horizon at 24h (situation detector default), so
# "past revisit" describes 617 of 618 open plans and cannot gate anything —
# blocking on it would silence the desk. Evidence age can: against a 24h
# horizon, research two weeks old is not current advice. Measured 2026-08-30
# across the 42 open S6 plans: 15-30d = 8, 8-14d = 16, 3-7d = 11, 0-2d = 7.
# A 14-day bar refuses those 8 and lets 34 through.
EVIDENCE_MAX_AGE_DAYS = 14

# A number is only checked when the prose ties it to a quantity we can verify.
# "cash is elevated at 805800" / "805,800 in cash" both match; "RSI=50.56" and
# "portfolio heat 0.09%" do not, which is the point — this is not a numeric
# scanner, it is a claim checker.
_NUM = r"\$?\s*([0-9][0-9,]{2,}(?:\.[0-9]+)?)"

# `cash` as a WORD or as part of a snake_case identifier. The first cut used
# \bcash\b and silently missed `total_cash=578107.50` and `cash_buying_power`,
# because an underscore is a word character so the boundary never matched. That
# hole shipped a message quoting 578,107.50 against an actual 630,784.82 while
# the guard reported the plan clean — measured 2026-08-30.
_CASH = r"(?<![A-Za-z])(?:[a-z]+_)*cash(?:_[a-z]+)*(?![A-Za-z])"
_CASH_CLAIM_RE = re.compile(
    rf"(?i){_CASH}[^.;\n]{{0,60}}?{_NUM}"
    rf"|{_NUM}[^.;\n]{{0,40}}?{_CASH}"
)


def _to_float(raw: str) -> Optional[float]:
    try:
        return float(str(raw).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def current_cash(root: Path | str | None = None) -> Optional[float]:
    """Live total cash from the served holdings, or None when unknown.

    Unknown truth means this guard abstains — it must never block on its own
    inability to read the book.
    """
    # An explicit root is AUTHORITATIVE — no fallback. Falling back would let a
    # caller that names one book get answered from another, which is the exact
    # class of bug (root silently resolving elsewhere) this file exists to
    # guard the operator against. Only a root-less call consults the default.
    if root:
        candidates = [Path(root) / "data" / "portfolios" / "state" / "holdings.json"]
    else:
        candidates = [
            Path.home() / "trade-ai-releases" / "persistent-state"
            / "data" / "portfolios" / "state" / "holdings.json"
        ]
    for p in candidates:
        try:
            if not p.is_file():
                continue
            tot = (json.loads(p.read_text(encoding="utf-8")) or {}).get("portfolio_totals") or {}
            val = tot.get("total_cash")
            f = _to_float(val) if val is not None else None
            if f is not None:
                return f
        except Exception:                                        # noqa: BLE001
            continue
    return None


def narrative_text(plan: Any) -> str:
    """The prose that actually reaches the operator."""
    if not isinstance(plan, dict):
        return ""
    parts = [
        plan.get("summary"), plan.get("recommendation"),
        plan.get("thesis_alignment"), plan.get("multi_domain_summary"),
        plan.get("title"),
    ]
    return "\n".join(str(p) for p in parts if p)


def stale_claim(
    plan: Any,
    *,
    root: Path | str | None = None,
    tolerance_pct: float = TOLERANCE_PCT,
) -> Optional[dict[str, Any]]:
    """Return the contradicted claim, or None when the narrative is safe."""
    text = narrative_text(plan)
    if not text:
        return None
    truth = current_cash(root)
    if truth is None or truth <= 0:
        return None                      # cannot verify -> do not block
    for m in _CASH_CLAIM_RE.finditer(text):
        raw = m.group(1) or m.group(2)
        claimed = _to_float(raw)
        if claimed is None or claimed <= 0:
            continue
        # Ignore obviously non-dollar magnitudes (percentages, small counts).
        if claimed < 1000:
            continue
        drift = abs(claimed - truth) / truth * 100.0
        if drift > tolerance_pct:
            return {
                "schema": SCHEMA,
                "authority": AUTHORITY,
                "field": "cash",
                "claimed": claimed,
                "actual": truth,
                "drift_pct": round(drift, 1),
                "excerpt": text[max(0, m.start() - 40):m.end() + 40].strip(),
                "reason": "narrative_quotes_stale_cash",
            }
    return None


def _age_days(raw: Any, now: datetime | None = None) -> Optional[int]:
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if not d.tzinfo:
            d = d.replace(tzinfo=timezone.utc)
        return ((now or datetime.now(timezone.utc)) - d).days
    except Exception:                                            # noqa: BLE001
        return None


def evidence_age_days(plan: Any, now: datetime | None = None) -> Optional[int]:
    """Age of the NEWEST dated evidence, or None when nothing is dated."""
    if not isinstance(plan, dict):
        return None
    ages = []
    for e in plan.get("evidence_refs") or []:
        if not isinstance(e, dict):
            continue
        a = _age_days(e.get("as_of") or e.get("date") or e.get("ts"), now)
        if a is not None:
            ages.append(a)
    return min(ages) if ages else None


def stale_evidence(
    plan: Any,
    *,
    now: datetime | None = None,
    max_age_days: int = EVIDENCE_MAX_AGE_DAYS,
) -> Optional[dict[str, Any]]:
    """Refuse advice whose newest evidence is older than the bar.

    Undated evidence does NOT block — absence of a date is not proof of age,
    and this guard must not punish a plan for a metadata gap.
    """
    age = evidence_age_days(plan, now)
    if age is None or age <= max_age_days:
        return None
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "field": "evidence",
        "age_days": age,
        "max_age_days": max_age_days,
        "reason": "evidence_older_than_bar",
    }


def blocks_notify(plan: Any, *, root: Path | str | None = None) -> bool:
    return (stale_claim(plan, root=root) is not None
            or stale_evidence(plan) is not None)


def describe(plan: Any, *, root: Path | str | None = None) -> dict[str, Any]:
    hit = stale_claim(plan, root=root)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "block_notify": hit is not None,
        "claim": hit,
        "tolerance_pct": TOLERANCE_PCT,
        "rule": "narrative may not quote a portfolio figure current truth contradicts",
    }
