"""
sector_leaders_service.py  -  REFERENCE IMPLEMENTATION v1
Trade AI v12 - Defense Desk sector -> industry -> names descent

STATUS: reference implementation, NOT drop-in.
    Every table name, column name, and join below is a PLACEHOLDER marked
    ADAPT:. The live schema is authoritative. Reconcile before writing code.
    Documentation in this project is known stale; do not trust it over psql.

WHAT THIS DOES
    Assembles the payload for GET /api/v3/defense/sector-leaders. It answers
    the question the current Defense Desk cannot: given that a sector is
    leading, which individual names inside it should be concentrated on, and
    is the ETF actually the better instrument.

WHAT THIS MUST NEVER DO
    - Write to paper_trade_proposals or any proposal/order table
    - Import a broker adapter
    - Place, stage, or approve anything
    - Return a value it cannot source. Return None and a reason instead.

THE NULL CONTRACT
    Every numeric field in the response is Optional. When a value cannot be
    sourced, return None and append a human-readable reason to `data_gaps`.
    The frontend renders None as an explicit "unknown". This is the server
    half of the fix for the live `breadth 55% (56/-- covered)` defect, where
    a null denominator rendered as punctuation inside a confident sentence.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

# ADAPT: use the project's existing connection helper. Do not open a new pool.
#   Known-good fallback pattern when shell psql auth fails:
#   import sys; sys.path.insert(0, 'scripts'); from db_adapter import _get_conn
from db_adapter import _get_conn  # type: ignore  # ADAPT


# --------------------------------------------------------------------------
# Config surface. ADAPT: these belong in config/, not in this module.
# The sizing bands in particular are OPERATOR POLICY and must be sourced from
# wherever the rotation sizing rules already live. Do not invent them.
# --------------------------------------------------------------------------

MIN_PRICE = 5.00
MIN_ADV_20D_USD = 2_000_000
MIN_MARKET_CAP_USD = 300_000_000

# Dispersion thresholds. Priors - move to config once measured against outcomes.
DISPERSION_NAMES_SPREAD_PP = 12.0
DISPERSION_NAMES_EXCESS_PP = 4.0
DISPERSION_ETF_SPREAD_PP = 6.0

# ADAPT: rank -> target weight band. THIS IS OPERATOR POLICY, NOT A CONSTANT.
# It must respect the defensive-lean directive and the core registry. If no
# policy source exists, return None for the band rather than using this stub,
# and let the UI render "unknown". Flag it back; do not ship the stub.
RANK_IMPLIED_WEIGHT_BAND_STUB: dict[int, tuple[float, float]] = {}


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------

@dataclass
class Constituent:
    symbol: str
    price: Optional[float] = None
    rs_vs_industry: Optional[float] = None
    rs_vs_spy: Optional[float] = None
    pct_from_52w_high: Optional[float] = None
    adv_20d: Optional[float] = None
    market_cap: Optional[float] = None
    days_to_earnings: Optional[int] = None
    held: Optional[dict[str, Any]] = None
    is_core: bool = False
    blocked_accounts: list[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None


@dataclass
class IndustryBlock:
    key: str
    name: str
    rank: Optional[int] = None
    rank_change: Optional[int] = None
    constituent_count: Optional[int] = None
    passing_count: Optional[int] = None
    filter_summary: Optional[str] = None
    source_note: Optional[str] = None
    constituents: list[Constituent] = field(default_factory=list)


@dataclass
class SectorLeaders:
    key: str
    name: str
    etf: str
    state: Optional[str] = None
    rank: Optional[int] = None
    rank_total: Optional[int] = None
    rank_change: Optional[int] = None
    rs20: Optional[float] = None
    book_weight_pct: Optional[float] = None
    rank_implied_weight_pct: Optional[tuple[float, float]] = None
    data_age_hours: Optional[float] = None
    refresh_interval_hours: Optional[float] = None
    dispersion: Optional[dict[str, Optional[float]]] = None
    industries: list[IndustryBlock] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Core computations - pure, unit-testable, no DB
# --------------------------------------------------------------------------

def relative_strength_vs_industry(
    name_return_pct: Optional[float],
    industry_composite_return_pct: Optional[float],
) -> Optional[float]:
    """RS of a name against its OWN industry composite over the same window.

    This is the load-bearing metric of the whole card. Inside a leading sector
    every constituent shows positive RS against SPY - that is sector beta, not
    name selection. Only the intra-group measure separates the leaders inside
    a leading group from the passengers.
    """
    if name_return_pct is None or industry_composite_return_pct is None:
        return None
    return round(name_return_pct - industry_composite_return_pct, 2)


def compute_dispersion(
    constituent_returns_pct: list[Optional[float]],
    etf_return_pct: Optional[float],
) -> dict[str, Optional[float]]:
    """Spread across the group, and how far the top quartile beats the ETF.

    Drives the ETF-versus-names decision. Requires at least 8 non-null returns
    to be meaningful; below that both fields return None and the UI omits the
    verdict rather than guessing.
    """
    vals = sorted(v for v in constituent_returns_pct if v is not None)
    if len(vals) < 8:
        return {"spread_pp": None, "top_quartile_excess_pp": None, "n": len(vals)}

    p10 = vals[int(0.10 * (len(vals) - 1))]
    p90 = vals[int(0.90 * (len(vals) - 1))]
    spread = round(p90 - p10, 2)

    q_start = int(0.75 * (len(vals) - 1))
    top_q = vals[q_start:]
    top_q_mean = sum(top_q) / len(top_q) if top_q else None

    excess = (
        None if (top_q_mean is None or etf_return_pct is None)
        else round(top_q_mean - etf_return_pct, 2)
    )
    return {"spread_pp": spread, "top_quartile_excess_pp": excess, "n": len(vals)}


def exposure_gap_pp(
    book_weight_pct: Optional[float],
    band: Optional[tuple[float, float]],
) -> Optional[dict[str, Any]]:
    """Signed distance from the rank-implied weight band, in percentage points."""
    if book_weight_pct is None or band is None:
        return None
    lo, hi = band
    if book_weight_pct < lo:
        return {"pp": round(book_weight_pct - lo, 2), "state": "underweight"}
    if book_weight_pct > hi:
        return {"pp": round(book_weight_pct - hi, 2), "state": "overweight"}
    return {"pp": 0.0, "state": "in band"}


def account_eligibility(
    symbol_meta: dict[str, Any],
    direction: str,
    accounts: list[dict[str, Any]],
) -> tuple[list[str], Optional[str]]:
    """Which accounts cannot take this trade, and why.

    Standing rules that must hold regardless of what the DB says:
      - Taxable (margin) may short.
      - Rollover IRA and Roth IRA may NOT short. Inverse ETF / covered calls only.
      - Alpaca live accounts are read-only and can never route.
    """
    blocked: list[str] = []
    reason: Optional[str] = None

    for acct in accounts:
        if acct.get("read_only"):
            blocked.append(acct["label"])
            reason = "read-only broker integration"
            continue
        if direction == "short" and not acct.get("can_short"):
            blocked.append(acct["label"])
            reason = "account cannot short - inverse ETF or covered calls only"

    return blocked, reason


# --------------------------------------------------------------------------
# Assembly - the DB-touching half. ALL of this is ADAPT:.
# --------------------------------------------------------------------------

def build_sector_leaders(sector_key: str, horizon: str = "M") -> dict[str, Any]:
    """Assemble the full payload. Read-only. Never writes.

    ADAPT: every query below is a placeholder. Before writing the real ones,
    confirm against the live DB:
      1. Which table holds sector RS / rank / state, and its exact columns
      2. Which table maps industry -> constituent symbols, and whether it is
         populated for ALL 144 Finviz industries or only the lagging pool used
         by the short-side advisories
      3. Whether a per-name return column exists over the same window used for
         the industry composite. If not, rs_vs_industry CANNOT be computed and
         this stage must flag back before proceeding - see README.
      4. Which table holds current positions per account, and how core registry
         membership is recorded
    """
    out = SectorLeaders(key=sector_key, name="", etf="")

    with _get_conn() as conn, conn.cursor() as cur:
        # ---- 1. sector header ------------------------------------------- ADAPT
        cur.execute(
            """
            SELECT name, etf, state, rank, rank_total, rank_change, rs20,
                   computed_at
              FROM sector_momentum          -- ADAPT: real table name
             WHERE sector_key = %s AND horizon = %s
            """,
            (sector_key, horizon),
        )
        row = cur.fetchone()
        if not row:
            out.data_gaps.append(f"no sector row for {sector_key} at horizon {horizon}")
            return asdict(out)

        (out.name, out.etf, out.state, out.rank, out.rank_total,
         out.rank_change, out.rs20, computed_at) = row

        if computed_at:
            age = (datetime.now(timezone.utc) - computed_at).total_seconds() / 3600.0
            out.data_age_hours = round(age, 1)
        else:
            out.data_gaps.append("sector row has no computed_at; freshness unknown")

        out.refresh_interval_hours = 24.0  # ADAPT: read from the job's own config

        # ---- 2. book weight --------------------------------------------- ADAPT
        # Must use EFFECTIVE weight (direct holdings + fund look-through), which
        # is what the Defense Desk already reports elsewhere. Do not recompute
        # from holdings.json alone - that undercounts.
        out.book_weight_pct = _effective_sector_weight(cur, sector_key)
        if out.book_weight_pct is None:
            out.data_gaps.append("effective sector weight unavailable")

        # ---- 3. sizing band ------------------------------------- OPERATOR POLICY
        band = _rank_implied_band(cur, out.rank)
        out.rank_implied_weight_pct = band
        if band is None:
            out.data_gaps.append(
                "no rank-implied sizing policy configured; exposure gap not computed"
            )

        # ---- 4. confirming industries + constituents -------------------- ADAPT
        out.industries = _confirming_industries(cur, sector_key, horizon)

        # ---- 5. dispersion ---------------------------------------------- ADAPT
        all_returns = [
            c.rs_vs_spy for ind in out.industries for c in ind.constituents
        ]
        etf_return = _etf_return(cur, out.etf, horizon)
        out.dispersion = compute_dispersion(all_returns, etf_return)
        if out.dispersion.get("spread_pp") is None:
            out.data_gaps.append(
                f"dispersion needs >=8 priced constituents; "
                f"had {out.dispersion.get('n')}"
            )

    return asdict(out)


# --------------------------------------------------------------------------
# Placeholder helpers - implement against live schema
# --------------------------------------------------------------------------

def _effective_sector_weight(cur, sector_key: str) -> Optional[float]:
    """ADAPT: reuse the existing effective-exposure calculation. Do not fork it."""
    raise NotImplementedError("wire to the existing effective exposure module")


def _rank_implied_band(cur, rank: Optional[int]) -> Optional[tuple[float, float]]:
    """ADAPT: read operator sizing policy from config. Return None if absent.

    Do NOT fall back to a hardcoded band. An invented sizing policy rendered as
    a confident exposure gap is exactly the failure mode this codebase has been
    fighting. None -> the UI renders "unknown" -> the operator is told the truth.
    """
    return None


def _confirming_industries(cur, sector_key: str, horizon: str) -> list[IndustryBlock]:
    """ADAPT: join industry ranking to constituent membership.

    The short-side advisories already resolve industry -> named constituent
    (XPEV/Auto Manufacturers, ACM/Engineering & Construction,
    PLAB/Semiconductor Equipment & Materials). Find that join and reuse it
    rather than building a second one. If it only covers the lagging pool,
    extending it to the leading pool is the actual work of this stage.
    """
    raise NotImplementedError("locate and reuse the short-side industry join")


def _etf_return(cur, etf: str, horizon: str) -> Optional[float]:
    """ADAPT: same window as the constituent returns, or dispersion is meaningless."""
    raise NotImplementedError("wire to the price history table")
