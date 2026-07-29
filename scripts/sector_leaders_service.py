#!/usr/bin/env python3
"""sector_leaders_service.py — Defense Desk sector → industry → names descent.

Backs GET /api/v2/defense/sector-leaders. Answers the question the current
Defense Desk cannot: given that a sector is leading, which individual names
inside it deserve attention, and is the ETF actually the better instrument.

READ-ONLY. This module opens no write path of any kind: no INSERT/UPDATE/DELETE,
no proposal or order table, no broker adapter import. Every DB statement here is
a SELECT.

THE NULL CONTRACT
    Every numeric field in the response is Optional. When a value cannot be
    sourced we return None and append a human-readable reason to `data_gaps`.
    The frontend renders None through <Val> as an explicit "unknown". This is
    the server half of the fix for the live `breadth 55% (56/— covered)` defect,
    where a null denominator rendered as punctuation inside a confident sentence.

SOURCES (all verified live during SL-S0 recon, 2026-07-29 —
see docs/_findings/sector_leaders_recon_2026-07-29.md)

    sector header/state/RS  sector_momentum_state      (17:25 wd)
    industry composites     industry_momentum_state    (12:30 + 16:18 wd)
    industry membership     trade_ai_scans             (continuous, RTH)
    per-name returns/stats  data/state/ticker_enrichment_cache.json
    effective book weight   sector_momentum_state.book_pct
                            (already fund_lookthrough.effective_sector_exposure)
    account routability     broker_accounts            (canonical)
    shorting permission     config/account_capabilities.json
    core registry           operator_core_registry

WINDOW DISCIPLINE — the load-bearing constraint
    rs_vs_industry = name return − its industry composite return, over the SAME
    window. Both sides are Finviz: the name from the enrichment cache
    (perf_month_pct) and the composite from industry_momentum_state (perf_month),
    which is the Finviz group export. Same vendor, same window definition, so the
    subtraction is apples-to-apples.

    Do NOT source either side from ticker_prices. Recon measured the divergence:
    an equal-weighted composite computed from ticker_prices reads Semiconductors
    at −18.93 against Finviz's cap-weighted −9.00. Mixing the two would put ~9pp
    of pure methodology error into every constituent row of that industry and it
    would look entirely plausible on screen.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent

# Liquidity/quality floor for a name to be shown as actionable. Mirrors the
# existing short-side rails in config/defense_recommendations.json.
MIN_PRICE = 5.00
MIN_ADV_20D_USD = 2_000_000
MIN_MARKET_CAP_USD = 300_000_000

# Dispersion thresholds. Priors — revisit once measured against outcomes.
DISPERSION_NAMES_SPREAD_PP = 12.0
DISPERSION_NAMES_EXCESS_PP = 4.0
DISPERSION_ETF_SPREAD_PP = 6.0
DISPERSION_MIN_NAMES = 8

# Refresh intervals, in hours, taken from each producer's own crontab line.
# Used only to badge staleness — never to hide a row.
REFRESH_INTERVAL_HOURS = {
    "sector": 24.0,      # sector_momentum_engine.py    — 17:25 weekdays
    "industry": 24.0,    # finviz_industry_groups.py    — 12:30 + 16:18 weekdays
    "enrichment": 24.0,  # Finviz enrichment cache      — rolling daily
}

# Finviz window names, per horizon. Both sides of rs_vs_industry must index the
# same row of this table or the metric is meaningless.
HORIZONS = {
    "W": {"industry_col": "perf_week", "name_key": "perf_week_pct", "label": "1 week"},
    "M": {"industry_col": "perf_month", "name_key": "perf_month_pct", "label": "1 month"},
    "Q": {"industry_col": "perf_quarter", "name_key": "perf_quarter_pct", "label": "1 quarter"},
}

# An industry confirms its sector when it is in one of these states. Matches the
# existing board filter at ActionableSectorDecisionBoard.tsx:229.
CONFIRMING_STATES = ("LEADING", "IMPROVING")

_ENRICH_CACHE: Optional[dict] = None
_CAPS_CACHE: Optional[dict] = None


# --------------------------------------------------------------------------
# Core computations — pure, unit-testable, no DB
# --------------------------------------------------------------------------

def relative_strength_vs_industry(
    name_return_pct: Optional[float],
    industry_composite_return_pct: Optional[float],
) -> Optional[float]:
    """RS of a name against its OWN industry composite over the same window.

    This is the load-bearing metric of the whole card. Inside a leading sector
    every constituent shows positive RS against SPY — that is sector beta, not
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
    """Spread across the supplied group, and how far its top quartile beats the ETF.

    LEVEL CONTRACT (operator correction, 2026-07-29 — supersedes README §3.3):
    the caller MUST pass a SINGLE INDUSTRY's constituent returns, and the SECTOR
    ETF's return.

      spread  — measured WITHIN the industry. That is the pool selection actually
                happens from.
      excess  — measured against the SECTOR ETF. That is the instrument otherwise
                bought; there is usually no tradeable industry ETF, so XLE stays
                the benchmark for every Energy industry.

    The question this answers: given I am picking from Oil & Gas Integrated, is
    there enough spread that picking matters, and does the top quartile beat
    simply buying XLE?

    Do NOT pass a sector-wide pool. Pooling 30–245 names across up to 20
    industries measures INTER-INDUSTRY separation, not intra-group dispersion —
    the p90–p10 spread is then dominated by how far Oil & Gas Integrated sits
    from Thermal Coal, not by how far XOM sits from OXY. Measured that way 10 of
    11 sectors returned "buy names" and the verdict carried no information.

    Do NOT pass the industry's own composite as etf_return_pct. That is
    near-tautological: the top quartile always beats its own mean.

    Requires at least 8 non-null returns IN THAT INDUSTRY; below that both fields
    return None and the verdict is omitted rather than pooled upward to rescue it.
    """
    vals = sorted(v for v in constituent_returns_pct if v is not None)
    if len(vals) < DISPERSION_MIN_NAMES:
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


def dispersion_verdict(dispersion: Optional[dict]) -> Optional[str]:
    """ETF-versus-names call for ONE industry. None when the sample is too thin.

    Thresholds are deliberately unchanged from the original design (12 / 4 / 6).
    The 2026-07-29 correction moved the LEVEL the computation runs at, not the
    cut points — changing both at once would leave neither testable against
    outcome data later.

    FOUR states as of 2026-07-29 (operator, superseding visual contract §6):

        spread >= 12 and excess >= 4   -> "buy names"
        spread >= 12 and excess <  0   -> "leaders trail the ETF"
        spread <= 6                    -> "buy the ETF"
        otherwise                      -> "mixed"

    The third state is a PRESENTATION split, not a threshold change: it was
    already inside "mixed" and behaved identically. A group that is widely
    dispersed but whose top quartile still trails the ETF is a materially
    different situation from an undispersed one, and collapsing both into
    "mixed" hid it.

    Note for anyone re-reading contract §6: it asserted that a negative excess
    could produce "buy names" at a wide spread. It could not, and never could —
    "buy names" requires BOTH bounds, so excess < 0 fails `>= 4` at any spread.
    The numbers §6 cited belonged to a different industry.
    """
    if not dispersion:
        return None
    spread = dispersion.get("spread_pp")
    excess = dispersion.get("top_quartile_excess_pp")
    if spread is None:
        return None
    if spread >= DISPERSION_NAMES_SPREAD_PP:
        if excess is not None and excess >= DISPERSION_NAMES_EXCESS_PP:
            return "buy names"
        if excess is not None and excess < 0:
            return "leaders trail the ETF"
    if spread <= DISPERSION_ETF_SPREAD_PP:
        return "buy the ETF"
    return "mixed"


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

    Fails closed: an account whose capability is unknown is blocked, never
    permitted by omission. See _accounts() for how the flags are sourced.
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
            reason = "account cannot short — inverse ETF or covered calls only"

    return blocked, reason


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------

@dataclass
class Constituent:
    symbol: str
    price: Optional[float] = None
    rs_vs_industry: Optional[float] = None
    rs_vs_spy: Optional[float] = None
    return_pct: Optional[float] = None
    pct_from_52w_high: Optional[float] = None
    adv_20d: Optional[float] = None
    market_cap: Optional[float] = None
    days_to_earnings: Optional[int] = None
    held: Optional[dict[str, Any]] = None
    is_core: bool = False
    lags_own_group: bool = False
    blocked_accounts: list[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    data_age_hours: Optional[float] = None


@dataclass
class IndustryBlock:
    key: str
    name: str
    state: Optional[str] = None
    rank: Optional[int] = None
    rank_total: Optional[int] = None
    rank_change: Optional[int] = None
    composite_return_pct: Optional[float] = None
    constituent_count: Optional[int] = None
    passing_count: Optional[int] = None
    filter_summary: Optional[str] = None
    source_note: Optional[str] = None
    # Dispersion measured WITHIN this industry. Additive to the sector-level
    # figure the design specifies — see the dispersion_scope note on the sector.
    dispersion: Optional[dict[str, Optional[float]]] = None
    dispersion_verdict: Optional[str] = None
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
    as_of: Optional[str] = None
    horizon: str = "M"
    horizon_label: Optional[str] = None
    book_weight_pct: Optional[float] = None
    book_weight_basis: Optional[str] = None
    rank_implied_weight_pct: Optional[tuple[float, float]] = None
    exposure_gap: Optional[dict[str, Any]] = None
    data_age_hours: Optional[float] = None
    refresh_interval_hours: Optional[float] = None
    dispersion: Optional[dict[str, Optional[float]]] = None
    dispersion_verdict: Optional[str] = None
    dispersion_scope: Optional[str] = None
    # Card-level routing. For a long entry the blocked set is identical on every
    # row, so it belongs here, not repeated per name. Per-row blocked_accounts
    # stays in the payload and the UI chips it only where it DIFFERS from this.
    accounts: Optional[dict[str, Any]] = None
    # Set whenever the card has no industries to show. Distinguishes a JOIN
    # FAILURE from a genuine absence of candidates — the two look identical on
    # screen and only one is a bug.
    empty_reason: Optional[str] = None
    defensive_lean: Optional[dict[str, Any]] = None
    industries: list[IndustryBlock] = field(default_factory=list)
    data_gaps: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------

def _enrichment() -> dict:
    """Finviz per-symbol cache. Same file defense_recommendations._enrich() reads."""
    global _ENRICH_CACHE
    if _ENRICH_CACHE is None:
        try:
            _ENRICH_CACHE = json.loads(
                (ROOT / "data" / "state" / "ticker_enrichment_cache.json").read_text()
            )
        except Exception:
            _ENRICH_CACHE = {}
    return _ENRICH_CACHE


def _capabilities() -> dict:
    global _CAPS_CACHE
    if _CAPS_CACHE is None:
        try:
            _CAPS_CACHE = json.loads(
                (ROOT / "config" / "account_capabilities.json").read_text()
            ).get("accounts", {})
        except Exception:
            _CAPS_CACHE = {}
    return _CAPS_CACHE


def _f(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _age_hours(ts) -> Optional[float]:
    if not ts:
        return None
    try:
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - ts).total_seconds() / 3600.0, 1)
    except Exception:
        return None


def _sector_key(name: str) -> str:
    return str(name or "").strip().lower().replace(" ", "_").replace("&", "and")


def _accounts(cur) -> list[dict[str, Any]]:
    """Routable-account matrix.

    Routability is derived from broker_accounts, which is already canonical for
    live_trading_interlock — deliberately NOT a second source of truth in
    account_capabilities.json. api_write_enabled is NOT NULL DEFAULT false, so
    every account carries an explicit boolean and a missing/disabled row can only
    resolve to read_only=True.

    Shorting permission is a different fact (margin agreement, not API wiring)
    and stays in config/account_capabilities.json. A key absent there yields
    can_short=False — fail closed, never permitted by omission.
    """
    caps = _capabilities()
    out: list[dict[str, Any]] = []
    cur.execute(
        """SELECT account_key, display_name, broker, environment,
                  COALESCE(is_enabled, false), COALESCE(api_write_enabled, false)
             FROM broker_accounts ORDER BY account_key"""
    )
    for key, label, broker, env, enabled, can_write in cur.fetchall():
        c = caps.get(key) or {}
        out.append({
            "key": key,
            "label": label or key,
            "broker": broker,
            "environment": env,
            # read-only unless the broker row explicitly enables writes AND the
            # account is enabled. Alpaca/moomoo live rows are api_write_enabled
            # =false, so they can never route.
            "read_only": not (bool(enabled) and bool(can_write)),
            "can_short": bool(c.get("can_short_stock", False)),
            "capability_record": key in caps,
        })
    return out


# --------------------------------------------------------------------------
# DB layer
# --------------------------------------------------------------------------

def _sector_rows(cur) -> list[dict[str, Any]]:
    """Sector momentum rows, ranked by rs20. STYLE:* rows are index/style spreads
    sharing the table, not sectors — excluded from the ranking.

    Reads the SAME disk snapshot /api/v2/defense/posture serves
    (data/runtime/sector_momentum_latest.json), not a fresh max(as_of) query.
    That matters: the snapshot carries the last known row for ALL 11 configured
    sectors, while max(as_of) on the table returns only the 9 that refreshed on
    the most recent run — XLC last wrote 2026-07-23 and XLRE 2026-07-13. Querying
    the table directly would rank "1 of 9" on a page whose other cards say 11,
    and would silently drop two sectors that carry real book exposure
    (Communications 3.0%, Real Estate 0.6%).

    Each row keeps its OWN as_of so staleness is badged per sector rather than
    assumed uniform. Falls back to the table if the snapshot is missing.
    """
    rows: list[dict[str, Any]] = []
    snap = None
    try:
        snap = json.loads((ROOT / "data" / "runtime" / "sector_momentum_latest.json").read_text())
    except Exception:
        snap = None

    if snap and snap.get("rows"):
        for r in snap["rows"]:
            etf = r.get("etf") or ""
            if etf.startswith("STYLE"):
                continue
            rows.append({
                "etf": etf, "sector": r.get("sector"), "state": r.get("state"),
                "rs20": _f(r.get("rs20")), "slope": _f(r.get("slope")),
                "breadth_pct": _f(r.get("breadth_pct")), "breadth_n": r.get("breadth_n"),
                "book_pct": _f(r.get("book_pct")), "book_dollars": _f(r.get("book_dollars")),
                "as_of": r.get("as_of"), "created_at": snap.get("generated_at"),
                "exposure_basis": snap.get("exposure_basis"),
            })
    else:
        cur.execute(
            """SELECT DISTINCT ON (etf) etf, sector, state, rs20, slope, breadth_pct,
                      breadth_n, book_pct, book_dollars, as_of, created_at
                 FROM sector_momentum_state
                WHERE etf NOT LIKE 'STYLE:%'
                ORDER BY etf, as_of DESC"""
        )
        for r in cur.fetchall():
            rows.append({
                "etf": r[0], "sector": r[1], "state": r[2], "rs20": _f(r[3]),
                "slope": _f(r[4]), "breadth_pct": _f(r[5]), "breadth_n": r[6],
                "book_pct": _f(r[7]), "book_dollars": _f(r[8]),
                "as_of": r[9], "created_at": r[10], "exposure_basis": None,
            })

    rows.sort(key=lambda x: (x["rs20"] is None, -(x["rs20"] or 0)))
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows


def _prior_sector_ranks(cur) -> dict[str, int]:
    cur.execute(
        """SELECT etf FROM sector_momentum_state
            WHERE as_of = (SELECT max(as_of) FROM sector_momentum_state
                            WHERE as_of < (SELECT max(as_of) FROM sector_momentum_state))
              AND etf NOT LIKE 'STYLE:%'
            ORDER BY rs20 DESC NULLS LAST"""
    )
    return {r[0]: i for i, r in enumerate(cur.fetchall(), start=1)}


def _rank_implied_band(rank: Optional[int]) -> Optional[tuple[float, float]]:
    """Operator sizing policy: rank → target weight band.

    Returns None, deliberately. SL-S0 recon established that no rank-keyed band
    exists anywhere in the tree:

      - config/rotation_sector_targets.json is THEME-keyed and self-labelled
        "operator comfort lines, NOT a model output"
      - defense_recommendations.json carries flat scalars (neutral 9.1 /
        underweight floor 4.0 / overweight alert 10.0) identical for rank 1 and
        rank 11 — rank-independent by construction
      - defense_data_quality.allocation_decision() reads cfg["allocation_policy"],
        which is absent from the config, so it degrades to a flat 9.1% for every
        sector

    An invented sizing band rendered as a confident exposure gap is precisely
    the failure mode this codebase has been fighting. None → the UI renders
    "unknown" → the operator is told the truth. When a policy lands, implement
    it here and the gap turns on with no other change.
    """
    return None


def _sector_aliases(sector_name: str) -> list[str]:
    """ETF-label sector name → the Finviz names industry_momentum_state uses.

    industry_momentum_state.sector carries FINVIZ names ('Financial Services',
    'Consumer Cyclical', 'Basic Materials', 'Consumer Defensive',
    'Communication Services') while sector_momentum_state.sector carries ETF
    labels ('Financials', 'Consumer Discretionary', …). Only 6 of 11 match
    directly. Resolving through the SAME alias map C2 introduced for the
    breadth/hermes/news queries — without it, 5 of 9 sectors on the board return
    zero confirming industries and the card renders confidently empty.
    """
    try:
        aliases = json.loads(
            (ROOT / "config" / "sector_momentum.json").read_text()
        ).get("sector_aliases", {})
    except Exception:
        aliases = {}
    names = list(aliases.get(sector_name) or [])
    if sector_name not in names:
        names.append(sector_name)
    return names


def _industry_rows(cur, sector_name: str, horizon: str) -> list[dict[str, Any]]:
    """Industries in one sector, carrying their GLOBAL rank among all 144.

    Rank is global, not within-sector, so the number agrees with the Industries
    list at the foot of the page (operator decision 2026-07-29). Rendered as
    "rank N of 144" so the basis is unambiguous.
    """
    col = HORIZONS[horizon]["industry_col"]
    cur.execute(
        f"""WITH ranked AS (
              SELECT industry, sector, state, rel1w, rel1m, {col} AS composite,
                     stocks, as_of, created_at,
                     RANK() OVER (ORDER BY {col} DESC NULLS LAST) AS global_rank,
                     count(*) OVER () AS global_total
                FROM industry_momentum_state
               WHERE as_of = (SELECT max(as_of) FROM industry_momentum_state)
            )
            SELECT industry, state, rel1w, rel1m, composite, stocks, as_of,
                   created_at, global_rank, global_total
              FROM ranked
             WHERE sector = ANY(%s)
             ORDER BY composite DESC NULLS LAST""",
        (_sector_aliases(sector_name),),
    )
    return [{
        "industry": r[0], "state": r[1], "rel1w": _f(r[2]), "rel1m": _f(r[3]),
        "composite": _f(r[4]), "stocks": r[5], "as_of": r[6], "created_at": r[7],
        "global_rank": r[8], "global_total": r[9],
    } for r in cur.fetchall()]


def _industry_members(cur, industries: list[str]) -> dict[str, list[str]]:
    """Industry → constituent symbols.

    This is the same join the short-side advisories use
    (defense_recommendations.taxable_short, lines 627-630). That call site is
    not industry-state-aware — the lagging restriction lives entirely in the
    industry list it passes in — so pointing it at leading industries needs no
    new machinery.

    Provenance caveat that must reach the UI: trade_ai_scans is a discovery-scan
    accumulation, not an official constituent list. Membership is complete for
    liquid names and thin in the tail. config/defense_breadth_policy.json already
    names this scope: "covered_screener_membership_not_official_etf_constituents".
    """
    if not industries:
        return {}
    cur.execute(
        """SELECT DISTINCT ON (symbol) symbol, industry
             FROM trade_ai_scans
            WHERE industry = ANY(%s)
            ORDER BY symbol, scanned_at DESC""",
        (industries,),
    )
    out: dict[str, list[str]] = {}
    for sym, ind in cur.fetchall():
        out.setdefault(ind, []).append(sym)
    return out


def _prices(cur, symbols) -> dict[str, float]:
    """Latest close per symbol from ticker_prices.

    The Finviz enrichment cache carries NO price field — same reason
    defense_recommendations._prices() exists. Do not reach for e['price'].
    """
    if not symbols:
        return {}
    cur.execute(
        """SELECT DISTINCT ON (symbol) symbol, close_price FROM ticker_prices
            WHERE symbol = ANY(%s) ORDER BY symbol, price_date DESC""",
        (list(symbols),),
    )
    return {r[0]: float(r[1]) for r in cur.fetchall() if r[1]}


def _held_map(cur) -> dict[str, list[dict[str, Any]]]:
    """Current positions per symbol, from the holdings snapshot (there is no
    holdings table in Postgres)."""
    try:
        h = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
    except Exception:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for pos in h.get("holdings") or []:
        if pos.get("is_cash"):
            continue
        sym = pos.get("symbol")
        if not sym:
            continue
        out.setdefault(sym, []).append({
            "account": pos.get("account"),
            "shares": _f(pos.get("shares")),
            "market_value": _f(pos.get("market_value")),
        })
    return out


def _core_symbols(cur) -> set[str]:
    cur.execute("SELECT DISTINCT symbol FROM operator_core_registry")
    return {r[0] for r in cur.fetchall()}


def _earnings_map(cur, symbols: list[str]) -> dict[str, date]:
    if not symbols:
        return {}
    cur.execute(
        """SELECT symbol, next_earnings_date FROM symbol_profiles
            WHERE symbol = ANY(%s) AND next_earnings_date IS NOT NULL""",
        (symbols,),
    )
    return {r[0]: r[1] for r in cur.fetchall()}


def _etf_return(etf: str, horizon: str) -> Optional[float]:
    """ETF return over the SAME window and from the SAME source as the
    constituent returns, or dispersion excess is meaningless."""
    e = _enrichment().get(etf) or {}
    return _f(e.get(HORIZONS[horizon]["name_key"]))


def _defensive_lean() -> Optional[dict[str, Any]]:
    """The standing operator directive (2026-07-18). Surfaced alongside any
    exposure reading so the card never points away from it silently."""
    try:
        cfg = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())
        lean = (cfg.get("rotation_pairs") or {}).get("defensive_lean") or {}
    except Exception:
        return None
    if not lean.get("enabled"):
        return None
    return {
        "enabled": True,
        "defensive_sectors": lean.get("defensive_sectors") or [],
        "set_by": lean.get("set_by"),
    }


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_sector_leaders(sector_key: str, horizon: str = "M", cur=None) -> dict[str, Any]:
    """Assemble the full payload. Read-only. Never writes."""
    if cur is None:
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from db_adapter import _get_conn  # local import: no module-level DB dependency
        with _get_conn() as conn, conn.cursor() as c:
            return build_sector_leaders(sector_key, horizon, cur=c)

    horizon = (horizon or "M").upper()
    if horizon not in HORIZONS:
        horizon = "M"
    hz = HORIZONS[horizon]

    out = SectorLeaders(key=sector_key, name="", etf="", horizon=horizon,
                        horizon_label=hz["label"])

    # ---- 1. sector header --------------------------------------------------
    rows = _sector_rows(cur)
    want = _sector_key(sector_key)
    row = next((r for r in rows
                if _sector_key(r["sector"]) == want or r["etf"].lower() == want), None)
    if not row:
        out.data_gaps.append(
            f"no sector row for '{sector_key}' in sector_momentum_state "
            f"(as of {rows[0]['as_of'] if rows else 'no data'}); "
            f"{len(rows)} of 11 configured sectors present"
        )
        return asdict(out)

    out.key = _sector_key(row["sector"])
    out.name = row["sector"]
    out.etf = row["etf"]
    out.state = row["state"]
    out.rs20 = row["rs20"]
    out.rank = row["rank"]
    out.rank_total = len(rows)

    prior = _prior_sector_ranks(cur)
    if row["etf"] in prior:
        out.rank_change = prior[row["etf"]] - row["rank"]

    # Staleness is measured against THIS sector's own as_of, not the snapshot's
    # generation time — XLC and XLRE are carried forward from older runs and must
    # say so rather than inherit the freshest row's age.
    out.as_of = str(row["as_of"]) if row["as_of"] else None
    out.refresh_interval_hours = REFRESH_INTERVAL_HOURS["sector"]
    try:
        d = date.fromisoformat(str(row["as_of"])[:10])
        out.data_age_hours = round((date.today() - d).days * 24.0, 1)
    except Exception:
        out.data_age_hours = _age_hours(row["created_at"])
    if out.data_age_hours is None:
        out.data_gaps.append("sector row has no usable as_of; freshness unknown")
    elif out.data_age_hours > 2 * REFRESH_INTERVAL_HOURS["sector"]:
        out.data_gaps.append(
            f"{out.name} last refreshed {row['as_of']} — carried forward from an "
            f"older run; the sector engine did not write a row on the most recent close"
        )

    # ---- 2. effective book weight -----------------------------------------
    # Already the fund look-through figure: sector_momentum_engine.py:268-270
    # writes book_pct from fund_lookthrough.effective_sector_exposure(). Read it;
    # do not fork the calculation.
    out.book_weight_pct = row["book_pct"]
    out.book_weight_basis = (
        (row.get("exposure_basis") or "effective (direct + config fund lookthrough)")
        + " — % of the mapped equity book, not of total portfolio value"
    )
    if out.book_weight_pct is None:
        out.data_gaps.append("effective sector weight unavailable for this sector")

    # ---- 3. sizing band ----------------------------------- OPERATOR POLICY
    band = _rank_implied_band(out.rank)
    out.rank_implied_weight_pct = band
    out.exposure_gap = exposure_gap_pp(out.book_weight_pct, band)
    if band is None:
        out.data_gaps.append(
            "no rank-implied sizing policy configured — exposure gap not computed; "
            "compare rank against weight directly"
        )

    out.defensive_lean = _defensive_lean()

    # ---- 3b. account routing ----------------------------------------------
    accounts = _accounts(cur)
    long_blocked, long_reason = account_eligibility({}, "long", accounts)
    short_blocked, _ = account_eligibility({}, "short", accounts)
    out.accounts = {
        "routable_long": [a["label"] for a in accounts if a["label"] not in long_blocked],
        "blocked_long": long_blocked,
        "blocked_long_reason": long_reason,
        "routable_short": [a["label"] for a in accounts if a["label"] not in short_blocked],
        "blocked_short": short_blocked,
        "note": (
            "routability from broker_accounts.api_write_enabled (canonical, same source as "
            "live_trading_interlock); shorting permission from config/account_capabilities.json. "
            "An account missing from either resolves to blocked."
        ),
    }

    # ---- 4. confirming industries + constituents ---------------------------
    inds = _industry_rows(cur, row["sector"], horizon)
    confirming = [i for i in inds
                  if str(i["state"] or "").upper() in CONFIRMING_STATES]

    # ---- GUARD 1: confidently empty ----------------------------------------
    # An empty industries list is a WELL-FORMED answer, so <Val> cannot catch it —
    # <Val> catches a null number, not a null result set. The Finviz-vs-ETF sector
    # key mismatch would have shipped most sectors rendering a clean card with no
    # industries, which reads as "no candidates today" rather than "the join
    # broke". A sector that holds real book weight and returns nothing must say
    # why, explicitly.
    if not inds:
        out.empty_reason = (
            f"no industry rows at all for {row['sector']} — industry_momentum_state "
            f"has no row under any alias of this sector name "
            f"({', '.join(_sector_aliases(row['sector']))}). This is a JOIN failure, "
            f"not an absence of candidates."
        )
        out.data_gaps.append(out.empty_reason)
    elif not confirming:
        out.empty_reason = (
            f"{len(inds)} industry rows exist for {row['sector']} but none is in "
            f"{'/'.join(CONFIRMING_STATES)} as of {inds[0]['as_of']} — the sector is "
            f"not confirmed from below. This is an absence of candidates, not a "
            f"join failure."
        )
        out.data_gaps.append(out.empty_reason)

    members = _industry_members(cur, [i["industry"] for i in confirming])
    enrich = _enrichment()
    held = _held_map(cur)
    core = _core_symbols(cur)

    all_syms = [s for syms in members.values() for s in syms]
    earnings = _earnings_map(cur, all_syms)
    prices = _prices(cur, all_syms)
    today = date.today()

    for _pos, ind in enumerate(confirming, start=1):
        blk = IndustryBlock(
            key=_sector_key(ind["industry"]),
            name=ind["industry"],
            state=ind["state"],
            # GLOBAL rank among all industries, so it agrees with the Industries
            # list at the foot of the page. rank_total makes the basis explicit.
            rank=ind.get("global_rank"),
            rank_total=ind.get("global_total"),
            composite_return_pct=ind["composite"],
            filter_summary=(
                f"price >= ${MIN_PRICE:.0f}, ADV20 >= ${MIN_ADV_20D_USD/1e6:.0f}M, "
                f"mcap >= ${MIN_MARKET_CAP_USD/1e6:.0f}M"
            ),
            source_note=(
                f"covered screener membership (trade_ai_scans), not official ETF "
                f"constituents · industry composite from Finviz group export "
                f"{hz['industry_col']} as of {ind['as_of']}"
            ),
        )
        if ind["composite"] is None:
            out.data_gaps.append(
                f"{ind['industry']}: no {hz['industry_col']} composite — "
                f"rs_vs_industry cannot be computed for its names"
            )
        # Finviz's own universe count is not captured by the group export loader.
        blk.constituent_count = ind["stocks"]

        syms = members.get(ind["industry"], [])
        kept: list[Constituent] = []
        for sym in syms:
            e = enrich.get(sym) or {}
            price = prices.get(sym)
            ret = _f(e.get(hz["name_key"]))
            # avg_vol_m is THOUSANDS of shares despite the _m suffix; market_cap_b
            # is MILLIONS despite the _b suffix. Same arithmetic as
            # defense_recommendations.py:637.
            avg_vol = _f(e.get("avg_vol_m"))
            mcap_m = _f(e.get("market_cap_b"))
            if price is None:
                continue
            if price < MIN_PRICE:
                continue
            adv = (avg_vol * 1000 * price) if (avg_vol is not None) else None
            if adv is not None and adv < MIN_ADV_20D_USD:
                continue
            if mcap_m is not None and mcap_m * 1e6 < MIN_MARKET_CAP_USD:
                continue

            rs_ind = relative_strength_vs_industry(ret, ind["composite"])
            spy_ret = _f((enrich.get("SPY") or {}).get(hz["name_key"]))
            nxt = earnings.get(sym)
            c = Constituent(
                symbol=sym,
                price=price,
                return_pct=ret,
                rs_vs_industry=rs_ind,
                rs_vs_spy=relative_strength_vs_industry(ret, spy_ret),
                pct_from_52w_high=_f(e.get("week52_high_pct")),
                adv_20d=round(adv) if adv is not None else None,
                market_cap=round(mcap_m * 1e6) if mcap_m is not None else None,
                days_to_earnings=((nxt - today).days if nxt else None),
                held=({"positions": held[sym]} if sym in held else None),
                is_core=sym in core,
                lags_own_group=(rs_ind is not None and rs_ind < 0),
                data_age_hours=_age_hours(e.get("cached_at")),
            )
            c.blocked_accounts, c.blocked_reason = account_eligibility(
                {"symbol": sym}, "long", accounts
            )
            kept.append(c)

        kept.sort(key=lambda c: (c.rs_vs_industry is None, -(c.rs_vs_industry or 0)))
        blk.constituents = kept
        blk.passing_count = len(kept)
        blk.dispersion = compute_dispersion([c.return_pct for c in kept],
                                            _etf_return(row["etf"], horizon))
        blk.dispersion_verdict = dispersion_verdict(blk.dispersion)
        if syms and not kept:
            out.data_gaps.append(
                f"{ind['industry']}: {len(syms)} member(s) found, none cleared the "
                f"price/ADV/market-cap floor"
            )
        out.industries.append(blk)

    if not any(i.constituents for i in out.industries):
        out.data_gaps.append("no constituents cleared the liquidity floor in any confirming industry")

    unpriced = [c.symbol for i in out.industries for c in i.constituents if c.return_pct is None]
    if unpriced:
        out.data_gaps.append(
            f"{len(unpriced)} name(s) have no {hz['name_key']} in the enrichment cache "
            f"({', '.join(sorted(unpriced)[:6])}{'…' if len(unpriced) > 6 else ''}) — "
            f"rs_vs_industry renders unknown and they are excluded from dispersion"
        )

    # ---- 5. dispersion -----------------------------------------------------
    # THE verdict is per-industry and was already computed in the loop above,
    # from that industry's own constituents against the SECTOR ETF.
    #
    # The sector-level figure below is retained as a DIAGNOSTIC only. It is not
    # rendered as a verdict: pooling every confirming industry measures
    # inter-industry separation, which is large almost always, which made the
    # verdict constant. Keep computing it so the pooling effect stays visible and
    # measurable, but never let it decide anything.
    etf_ret = _etf_return(out.etf, horizon)
    all_returns = [c.return_pct for ind in out.industries for c in ind.constituents]
    out.dispersion = compute_dispersion(all_returns, etf_ret)
    out.dispersion_verdict = None  # per-industry only — see IndustryBlock.dispersion_verdict
    out.dispersion_scope = (
        f"DIAGNOSTIC ONLY — {out.dispersion.get('n')} priced names pooled across "
        f"{len(out.industries)} confirming industries. Pooled spread measures "
        f"inter-industry separation, not intra-group dispersion; the actionable "
        f"verdict is computed per industry."
    )

    decided = [i for i in out.industries if i.dispersion_verdict]
    undecided = [i for i in out.industries
                 if not i.dispersion_verdict and i.constituents]
    for i in undecided:
        n = (i.dispersion or {}).get("n")
        out.data_gaps.append(
            f"{i.name}: dispersion needs >={DISPERSION_MIN_NAMES} priced names in "
            f"the industry; had {n} — verdict omitted"
        )
    if not decided and out.industries:
        out.data_gaps.append(
            f"no confirming industry in {out.name} has >={DISPERSION_MIN_NAMES} priced "
            f"names — no ETF-versus-names verdict for this sector"
        )
    if etf_ret is None:
        out.data_gaps.append(
            f"{out.etf} has no {hz['name_key']} in the enrichment cache; "
            f"top-quartile excess not computed for any industry"
        )

    return asdict(out)


def book_sector_ranks(cur=None) -> dict[str, dict[str, Any]]:
    """symbol -> {sector, rank, rank_total} or {reason} for the Your-book column.

    Two distinct cases, and only one of them is a data gap:

      1. Single-sector holding. symbol_profiles.sector carries a FINVIZ name
         ('Financial Services') while the ranked board carries ETF labels
         ('Financials'), so the lookup goes through the SAME alias map in
         reverse. Without it V — the book's largest single name — resolves to
         nothing. Same root cause as the SL-S1 join bug.

      2. Multi-sector holding (SCHD, JEPI, BND, ARKX, DIVI…). A fund spanning
         ten sectors has no single sector rank. That is not a missing value, it
         is a category error, and it renders `unk` with a reason rather than an
         invented 'broad'/'thematic' label — no such classification exists in
         config anywhere (operator decision 2026-07-29).
    """
    if cur is None:
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from db_adapter import _get_conn
        with _get_conn() as conn, conn.cursor() as c:
            return book_sector_ranks(cur=c)

    ranked = {r["sector"]: r for r in _sector_rows(cur)}
    total = len(ranked)
    # ETF-label -> itself, plus every Finviz alias -> the ETF label.
    reverse: dict[str, str] = {}
    for label in ranked:
        for alias in _sector_aliases(label):
            reverse[alias] = label

    try:
        funds = json.loads((ROOT / "config" / "fund_lookthrough.json").read_text())["funds"]
    except Exception:
        funds = {}

    try:
        holdings = json.loads(
            (ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text()
        ).get("holdings") or []
    except Exception:
        return {}

    symbols = sorted({h["symbol"] for h in holdings if h.get("symbol") and not h.get("is_cash")})
    if not symbols:
        return {}
    cur.execute(
        "SELECT symbol, sector FROM symbol_profiles WHERE symbol = ANY(%s)", (symbols,)
    )
    profile = dict(cur.fetchall())

    out: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        fund = funds.get(sym) or {}
        weights = fund.get("weights") or {}
        if len(weights) > 1:
            out[sym] = {"sector": None, "rank": None, "rank_total": total,
                        "reason": f"multi-sector holding ({len(weights)} sectors) — no single sector rank"}
            continue
        if fund.get("lookthrough") == "none":
            why = (fund.get("why") or "no sector look-through available").strip()
            out[sym] = {"sector": None, "rank": None, "rank_total": total, "reason": why}
            continue
        raw = profile.get(sym)
        label = reverse.get(raw) if raw else None
        if label and label in ranked:
            out[sym] = {"sector": label, "rank": ranked[label]["rank"],
                        "rank_total": total, "reason": None}
        elif len(weights) == 1:
            only = reverse.get(next(iter(weights)))
            if only and only in ranked:
                out[sym] = {"sector": only, "rank": ranked[only]["rank"],
                            "rank_total": total, "reason": None}
            else:
                out[sym] = {"sector": None, "rank": None, "rank_total": total,
                            "reason": "fund's single sector is not on the ranked board"}
        else:
            out[sym] = {"sector": None, "rank": None, "rank_total": total,
                        "reason": (f"no sector on symbol_profiles" if not raw
                                   else f"sector '{raw}' is not a ranked board sector")}
    return out


def list_sectors(cur=None) -> list[dict[str, Any]]:
    """Rank/weight strip for every sector on the board. Policy-free: it reports
    rank beside weight and lets the juxtaposition speak."""
    if cur is None:
        import sys
        sys.path.insert(0, str(ROOT / "scripts"))
        from db_adapter import _get_conn
        with _get_conn() as conn, conn.cursor() as c:
            return list_sectors(cur=c)

    rows = _sector_rows(cur)
    prior = _prior_sector_ranks(cur)
    total = len(rows)
    return [{
        "key": _sector_key(r["sector"]),
        "name": r["sector"],
        "etf": r["etf"],
        "state": r["state"],
        "rank": r["rank"],
        "rank_total": total,
        "rank_change": (prior[r["etf"]] - r["rank"]) if r["etf"] in prior else None,
        "rs20": r["rs20"],
        "book_weight_pct": r["book_pct"],
        "as_of": str(r["as_of"]) if r["as_of"] else None,
    } for r in rows]
