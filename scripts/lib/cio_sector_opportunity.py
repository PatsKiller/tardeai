"""cio_sector_opportunity.py — Alex's sector-opportunity synthesis (Phase 5).

Turns the raw "Sector X is improving" signal (sector momentum engine / rotation
ladder) into the full institutional statement the acceptance shape requires:

    Sector X is improving. Current portfolio exposure = Y%. Policy/target posture
    = Z%. Potential incremental capital = $A. Best current candidates = B/C/D. B
    is Watch READY, C needs research, D is too extended. I recommend no deployment
    / staged deployment / research first.

Everything here is READ-ONLY and advisory. Pure functions are deterministic and
separated from the live reader (injectable executor) so the synthesis is dry-testable
with no live DB / broker / LLM. It never promotes, mutates, or executes.

Sector states (from sector_momentum_engine.classify): LEADING / WEAKENING /
LAGGING / IMPROVING. A sector "opportunity" is LEADING or IMPROVING.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

# Executor signature matches db_adapter._execute(sql, params=None, fetch=None).
Executor = Callable[..., Any]

# ── Taxonomy ─────────────────────────────────────────────────────────────────

SECTOR_STATES = frozenset({"LEADING", "WEAKENING", "LAGGING", "IMPROVING"})
OPPORTUNITY_STATES = frozenset({"LEADING", "IMPROVING"})

# Canonical GICS sectors (momentum engine's 11) — the only names eligible for a
# sector-level target posture.
CANONICAL_SECTORS = (
    "Technology", "Financials", "Healthcare", "Energy", "Industrials",
    "Consumer Discretionary", "Consumer Staples", "Utilities", "Materials",
    "Real Estate", "Communications",
)

CANDIDATE_READINESS = ("WATCH_READY", "NEEDS_RESEARCH", "TOO_EXTENDED", "UNKNOWN")

DEPLOYMENT_RECOMMENDATIONS = frozenset({
    "NO_DEPLOYMENT", "STAGED_DEPLOYMENT", "RESEARCH_FIRST",
})

# Extension thresholds (deterministic, advisory). A candidate with RSI at/above
# RSI_EXTENDED or price at/above price/vwap * VWAP_EXTENDED_RATIO is "too extended".
RSI_EXTENDED = 70.0
VWAP_EXTENDED_RATIO = 1.03

# Fallback comfort target when no sector target is configured (operator comfort
# line, matching rotation_sector_targets.default_comfort_pct).
DEFAULT_SECTOR_TARGET_PCT = 18.0

# Sector-name normalization (momentum engine canonical ← aliases from other sources).
SECTOR_ALIASES = {
    "technology": "Technology",
    "financials": "Financials",
    "financial services": "Financials",
    "financial": "Financials",
    "healthcare": "Healthcare",
    "health care": "Healthcare",
    "energy": "Energy",
    "industrials": "Industrials",
    "consumer discretionary": "Consumer Discretionary",
    "consumer cyclical": "Consumer Discretionary",
    "consumer staples": "Consumer Staples",
    "consumer defensive": "Consumer Staples",
    "utilities": "Utilities",
    "materials": "Materials",
    "basic materials": "Materials",
    "real estate": "Real Estate",
    "communications": "Communications",
    "communication services": "Communications",
}


def canonical_sector(name: Any) -> str:
    """Normalize a sector name to the momentum engine's 11 canonical GICS labels.

    Unknown names pass through title-cased (never silently collapsed), so an
    unmapped sector stays visible as itself rather than being miscategorized.
    """
    raw = str(name or "").strip()
    if not raw:
        return ""
    key = raw.lower()
    if key in SECTOR_ALIASES:
        return SECTOR_ALIASES[key]
    return raw.title()


def classify_state(rs20: Optional[float], slope: Optional[float]) -> Optional[str]:
    """Replicate sector_momentum_engine.classify — pure, no I/O."""
    if rs20 is None or slope is None:
        return None
    if rs20 >= 0:
        return "LEADING" if slope >= 0 else "WEAKENING"
    return "IMPROVING" if slope >= 0 else "LAGGING"


def is_opportunity_state(state: Optional[str]) -> bool:
    return state in OPPORTUNITY_STATES


# ─────────────────────────────────────────────────────────────────────────────
# Pure normalization (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def normalize_sector_row(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Normalize one sector row into a canonical sector signal, or None.

    Accepts rows from the momentum engine (`state` present) or the rotation
    ladder (`rs_score` present). Requires a sector name. Derives `state` from
    `rs20`+`slope` (or `rs_score`) when not supplied.
    """
    if not isinstance(row, dict):
        return None
    sector = canonical_sector(row.get("sector") or row.get("name"))
    if not sector:
        return None

    state = str(row.get("state") or "").upper().strip() or None
    if state and state not in SECTOR_STATES:
        state = None

    rs20 = row.get("rs20")
    slope = row.get("slope")
    rs_score = row.get("rs_score")
    try:
        rs20 = float(rs20) if rs20 is not None else None
    except (TypeError, ValueError):
        rs20 = None
    try:
        slope = float(slope) if slope is not None else None
    except (TypeError, ValueError):
        slope = None
    try:
        rs_score = float(rs_score) if rs_score is not None else None
    except (TypeError, ValueError):
        rs_score = None

    # Derive state when absent: prefer rs20+slope (momentum), else rotation RS.
    if state is None:
        if rs20 is not None and slope is not None:
            state = classify_state(rs20, slope)
        elif rs_score is not None:
            # rotation ladder RS is a 0-100 rank; high = leading, else neutral
            state = "LEADING" if rs_score >= 70 else "IMPROVING" if rs_score >= 55 else "LAGGING"

    book_pct = row.get("book_pct") or row.get("exposure_pct") or row.get("weight_pct")
    try:
        book_pct = float(book_pct) if book_pct is not None else None
    except (TypeError, ValueError):
        book_pct = None

    book_dollars = row.get("book_dollars") or row.get("exposure_usd")
    try:
        book_dollars = float(book_dollars) if book_dollars is not None else None
    except (TypeError, ValueError):
        book_dollars = None

    return {
        "sector": sector,
        "etf": str(row.get("etf") or "").upper() or None,
        "state": state,
        "rs20": rs20,
        "slope": slope,
        "rs5": _num(row.get("rs5")),
        "rs_score": rs_score,
        "book_pct": book_pct,
        "book_dollars": book_dollars,
    }


def normalize_candidate(candidate: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Normalize one watchlist candidate into a canonical candidate, or None."""
    if not isinstance(candidate, dict):
        return None
    symbol = str(candidate.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    sector = canonical_sector(candidate.get("sector"))
    return {
        "symbol": symbol,
        "sector": sector,
        "status": str(candidate.get("status") or "").strip().lower() or None,
        "readiness": str(candidate.get("readiness") or "").strip().upper() or None,
        "rsi": _num(candidate.get("rsi")),
        "price": _num(candidate.get("price")),
        "vwap": _num(candidate.get("vwap")),
        "research_score": _num(candidate.get("hermes_research_score")
                               or candidate.get("research_score")),
        "confluence_score": _num(candidate.get("confluence_score")),
    }


def _num(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Pure classification (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def classify_candidate_readiness(candidate: dict[str, Any]) -> str:
    """Classify a candidate's readiness: WATCH_READY / NEEDS_RESEARCH / TOO_EXTENDED.

    Order matters (fail toward caution):
      1. explicit `readiness` override wins when valid.
      2. TOO_EXTENDED: RSI >= threshold or price >= vwap * ratio.
      3. WATCH_READY: `status == 'researched'` or a research_score present.
      4. NEEDS_RESEARCH: otherwise.
    """
    c = normalize_candidate(candidate)
    if c is None:
        return "UNKNOWN"

    readiness = c.get("readiness")
    if readiness in CANDIDATE_READINESS and readiness != "UNKNOWN":
        return readiness

    rsi = c.get("rsi")
    price = c.get("price")
    vwap = c.get("vwap")
    if rsi is not None and rsi >= RSI_EXTENDED:
        return "TOO_EXTENDED"
    if price is not None and vwap is not None and vwap > 0 and price >= vwap * VWAP_EXTENDED_RATIO:
        return "TOO_EXTENDED"

    if c.get("status") == "researched" or c.get("research_score") is not None:
        return "WATCH_READY"

    return "NEEDS_RESEARCH"


def deployment_recommendation(
    state: Optional[str],
    book_pct: Optional[float],
    target_pct: Optional[float],
    capital_usd: Optional[float],
    ready_count: int,
) -> str:
    """Deterministic deployment stance (fail-closed toward caution).

    Only an opportunity sector (LEADING/IMPROVING) is eligible for deployment;
    anything else is RESEARCH_FIRST (do not act on a non-improving sector).
    """
    if not is_opportunity_state(state):
        return "RESEARCH_FIRST"

    target = target_pct if target_pct is not None else DEFAULT_SECTOR_TARGET_PCT
    over_target = book_pct is not None and book_pct > target
    has_capital = (capital_usd or 0) > 0

    if over_target:
        return "NO_DEPLOYMENT"
    if not has_capital:
        return "NO_DEPLOYMENT"
    if ready_count > 0:
        return "STAGED_DEPLOYMENT"
    return "RESEARCH_FIRST"


# ─────────────────────────────────────────────────────────────────────────────
# Pure synthesis (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def build_sector_opportunity(
    sector_row: dict[str, Any],
    *,
    target_pct: Optional[float] = None,
    capital_usd: Optional[float] = None,
    candidates: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build ONE sector opportunity statement from a normalized sector signal.

    Returns the full acceptance-shape envelope with a deterministic
    `opportunity_key` (hash-pinned) for idempotent downstream wake/dedup.
    """
    now = now or datetime.now(timezone.utc)
    sector = normalize_sector_row(sector_row)
    if sector is None:
        return {"sector": "", "state": None, "opportunity": False}

    cands = [normalize_candidate(c) for c in (candidates or [])]
    cands = [c for c in cands if c is not None and c.get("sector") == sector["sector"]]

    readiness_map = {c["symbol"]: classify_candidate_readiness(c) for c in cands}
    ready = [c for c in cands if readiness_map[c["symbol"]] == "WATCH_READY"]
    research = [c for c in cands if readiness_map[c["symbol"]] == "NEEDS_RESEARCH"]
    extended = [c for c in cands if readiness_map[c["symbol"]] == "TOO_EXTENDED"]

    target = target_pct if target_pct is not None else DEFAULT_SECTOR_TARGET_PCT
    rec = deployment_recommendation(
        sector["state"], sector["book_pct"], target_pct, capital_usd, len(ready)
    )

    opportunity = is_opportunity_state(sector["state"])

    top_candidates = []
    for c in ready + research + extended:
        top_candidates.append({
            "symbol": c["symbol"],
            "readiness": readiness_map[c["symbol"]],
            "rsi": c["rsi"],
            "price": c["price"],
            "research_score": c["research_score"],
        })

    envelope = {
        "computed_at": now.isoformat(),
        "sector": sector["sector"],
        "etf": sector["etf"],
        "state": sector["state"],
        "opportunity": opportunity,
        "rs20": sector["rs20"],
        "slope": sector["slope"],
        "rs_score": sector["rs_score"],
        "current_exposure_pct": sector["book_pct"],
        "target_posture_pct": round(target, 2),
        "potential_capital_usd": round(float(capital_usd or 0.0), 2),
        "candidates": top_candidates,
        "candidate_counts": {
            "watch_ready": len(ready),
            "needs_research": len(research),
            "too_extended": len(extended),
        },
        "recommendation": rec,
    }
    key_raw = json.dumps(
        {
            "sector": sector["sector"],
            "state": sector["state"],
            "rs20": sector["rs20"],
            "slope": sector["slope"],
            "book_pct": sector["book_pct"],
            "capital": envelope["potential_capital_usd"],
            "recommendation": rec,
            "candidate_keys": [c["symbol"] for c in top_candidates],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    envelope["opportunity_key"] = hashlib.sha256(key_raw.encode("utf-8")).hexdigest()[:32]
    envelope["statement"] = render_statement(envelope)
    return envelope


def synthesize_sector_opportunities(
    sector_rows: list[dict[str, Any]],
    *,
    sector_targets: Optional[dict[str, float]] = None,
    capital_usd: Optional[float] = None,
    candidates: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    include_non_opportunity: bool = False,
) -> dict[str, Any]:
    """Synthesize the ordered sector-opportunity list from sector signals.

    Only LEADING/IMPROVING sectors are emitted by default (the "improving"
    acceptance shape). `sector_targets` maps canonical sector name → comfort pct.
    """
    now = now or datetime.now(timezone.utc)
    targets = sector_targets or {}

    opportunities: list[dict[str, Any]] = []
    for row in sector_rows or []:
        sector = normalize_sector_row(row)
        if sector is None:
            continue
        target = _lookup_target(targets, sector["sector"])
        opp = build_sector_opportunity(
            row, target_pct=target, capital_usd=capital_usd,
            candidates=candidates, now=now,
        )
        if opp.get("opportunity") or include_non_opportunity:
            opportunities.append(opp)

    # Order: opportunity first, then by state priority (LEADING before IMPROVING),
    # then by RS/momentum descending.
    state_rank = {"LEADING": 0, "IMPROVING": 1, "WEAKENING": 2, "LAGGING": 3}
    opportunities.sort(
        key=lambda o: (
            not o.get("opportunity"),
            state_rank.get(o.get("state"), 9),
            -(o.get("rs20") if o.get("rs20") is not None else -999),
        )
    )

    digest_raw = "|".join(o["opportunity_key"] for o in opportunities)
    return {
        "computed_at": now.isoformat(),
        "digest": hashlib.sha256(digest_raw.encode("utf-8")).hexdigest(),
        "count": len(opportunities),
        "opportunity_count": sum(1 for o in opportunities if o.get("opportunity")),
        "capital_usd": round(float(capital_usd or 0.0), 2),
        "opportunities": opportunities,
    }


def _lookup_target(targets: dict[str, float], sector: str) -> Optional[float]:
    """Resolve a sector comfort target from a name-keyed map (case/alias tolerant)."""
    if not targets:
        return None
    if sector in targets:
        return float(targets[sector])
    canon = canonical_sector(sector)
    for k, v in targets.items():
        if canonical_sector(k) == canon:
            return float(v)
    return None


def render_statement(opp: dict[str, Any]) -> str:
    """Render the acceptance-shape natural-language statement."""
    sector = opp.get("sector") or "Unknown sector"
    state = opp.get("state") or ""
    verb = "is leading" if state == "LEADING" else "is improving"
    if state not in OPPORTUNITY_STATES:
        verb = f"is {state.lower()}"

    exposure = opp.get("current_exposure_pct")
    exposure_s = f"{exposure:.1f}%" if exposure is not None else "unknown"
    target = opp.get("target_posture_pct")
    target_s = f"{target:.0f}%" if target is not None else "no explicit target"
    capital = opp.get("potential_capital_usd") or 0.0

    cands = opp.get("candidates") or []
    cand_parts = []
    for c in cands[:5]:
        label = {
            "WATCH_READY": "Watch READY",
            "NEEDS_RESEARCH": "needs research",
            "TOO_EXTENDED": "too extended",
        }.get(c.get("readiness"), "unknown")
        cand_parts.append(f"{c.get('symbol')} is {label}")
    cand_s = ", ".join(cand_parts) if cand_parts else "no candidates"

    rec = {
        "NO_DEPLOYMENT": "no deployment",
        "STAGED_DEPLOYMENT": "staged deployment",
        "RESEARCH_FIRST": "research first",
    }.get(opp.get("recommendation"), "research first")

    return (
        f"Sector {sector} {verb}. Current portfolio exposure = {exposure_s}. "
        f"Policy/target posture = {target_s}. Potential incremental capital = "
        f"${capital:,.0f}. Best current candidates: {cand_s}. "
        f"I recommend {rec}."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Live reader (injectable executor; separated from pure logic)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_sector_opportunity_inputs(
    executor: Executor,
    *,
    capital_usd: Optional[float] = None,
) -> dict[str, Any]:
    """Read sector signals, targets, and candidates for the live synthesis.

    Fail-soft: each source degrades to an empty/None value rather than raising.
    The executor must accept `(sql, params=None, fetch="all")` and return rows
    (list of dicts) or None.
    """
    sector_rows: list[dict[str, Any]] = []
    try:
        rows = executor(
            """SELECT etf, sector, state, rs5, rs20, rs60, slope, book_pct, book_dollars
               FROM sector_momentum_state
               WHERE as_of = (SELECT max(as_of) FROM sector_momentum_state)
               ORDER BY book_pct DESC NULLS LAST""",
            fetch="all",
        )
        sector_rows = [dict(r) for r in (rows or []) if r.get("sector")]
    except Exception:
        sector_rows = []

    candidates: list[dict[str, Any]] = []
    try:
        rows = executor(
            """SELECT wi.symbol, ie.sector, wi.status, wi.rsi, wi.price,
                      wi.hermes_research_score, ie.confluence_score
               FROM watchlist_items wi
               LEFT JOIN intelligence_entities ie ON ie.display_name = wi.symbol
               WHERE wi.status IN ('active','researched')
               ORDER BY wi.score DESC NULLS LAST
               LIMIT 200""",
            fetch="all",
        )
        candidates = [dict(r) for r in (rows or [])]
    except Exception:
        candidates = []

    return {
        "sector_rows": sector_rows,
        "candidates": candidates,
        "capital_usd": capital_usd,
    }


def build_synthesis_from_executor(
    executor: Executor,
    *,
    sector_targets: Optional[dict[str, float]] = None,
    capital_usd: Optional[float] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Convenience: read inputs and synthesize in one call."""
    inputs = fetch_sector_opportunity_inputs(executor, capital_usd=capital_usd)
    return synthesize_sector_opportunities(
        inputs["sector_rows"],
        sector_targets=sector_targets,
        capital_usd=inputs["capital_usd"],
        candidates=inputs["candidates"],
        now=now,
    )
