"""Universal Research Discovery Layer — coverage adapters (spec Part H).

Eight coverage areas emit TOPIC_CANDIDATE payloads for the Discovery Inbox
from data the platform ALREADY produces (no new tables, no producers touched):

  holdings    positions without stops (risk_management.json), upcoming
              earnings among held symbols (symbol_profiles), dividend-income
              concentration (holdings.json + ticker_dividend_data)
              → one TOPIC per finding CLASS, domain=portfolio_holdings
  watchlist   stale intelligence >7d and missing research among the governed
              (S0-S2) active watchlist → domain=watchlist
  sectors     sector clusters among active watchlist symbols → domain=sectors
  taxes       recent news/research rows matching tax terms → domain=taxes
  retirement  retirement/IRMAA/Medicare/Roth terms → domain=retirement
  legal       SEC/FINRA/IRS-guidance/litigation terms → domain=legal
  macro       Fed/CPI/rates terms → domain=macro
  system_ops  failing/stale system_health_checks components → domain=
              system_ops, promotion-path hint escalation_candidate

Every payload pins meta.research_domain, so inbox.upsert_candidate's Stage-1
enrichment classifies deterministically — and professional-review domains
(taxes/retirement/legal) automatically pick up required_review_label +
safe_action_level=OPERATOR_REVIEW_REQUIRED there.

Design rules (same as the rest of the package):
  * ADVISORY-ONLY: never imports broker/execution modules, never writes
    producer tables. Payloads only become rows via inbox.upsert_candidate.
  * Defensive reads: a missing table/file/column makes that finding class
    return nothing — it never raises out of an adapter.
  * One statement per DB call via db_adapter._execute (no held transactions).
  * Labels are stable per finding class so re-runs bump seen_count instead of
    spawning duplicates (idempotency comes free from upsert_candidate).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from . import subjects

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RISK_MGMT_PATH = Path(os.getenv("TRADE_AI_RISK_MGMT_JSON")
                      or PROJECT_ROOT / "data" / "portfolios" / "state"
                      / "risk_management.json")

# coverage area → pinned research domain (must exist in the domain registry)
COVERAGE_DOMAINS = {
    "holdings": "portfolio_holdings",
    "watchlist": "watchlist",
    "sectors": "sectors",
    "taxes": "taxes",
    "retirement": "retirement",
    "legal": "legal",
    "macro": "macro",
    "system_ops": "system_ops",
}

# term lists for the news/research term-recurrence adapters
TERM_SETS: dict[str, list[str]] = {
    "taxes": ["capital gains", "wash sale", "tax-loss", "roth conversion",
              "tax bracket", "estimated tax", "irs", "1099", "deduction",
              "cost-basis method"],
    "retirement": ["retirement", "ira", "401k", "rmd", "social security",
                   "medicare", "irmaa", "pension", "annuity",
                   "contribution limit"],
    "legal": ["sec enforcement", "finra", "irs guidance", "lawsuit",
              "litigation", "court ruling", "settlement", "rulemaking",
              "antitrust", "subpoena"],
    "macro": ["fed", "fomc", "cpi", "inflation", "interest rate",
              "treasury yield", "gdp", "unemployment", "recession",
              "yield curve"],
}

# statuses in system_health_checks that count as a healthy latest state
_HEALTHY_STATUSES = ("OK", "RECOVERED")


# ── low-level helpers ────────────────────────────────────────────────────────

def _rows(sql: str, params=None) -> list[dict[str, Any]]:
    """One-statement DB read; any failure (no DB, missing table) → []."""
    try:
        from db_adapter import _execute
        return [dict(r) for r in (_execute(sql, params, fetch="all") or [])]
    except Exception:
        return []


def _read_json(path: Path | str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _term_matches(text: str, term: str) -> bool:
    """Word-boundary term match (same boundary rule as domains._keyword_hits)."""
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(term.lower())
                          + r"(?![a-z0-9])", text.lower()))


def _topic_payload(area: str, label: str, summary: str, *,
                   evidence: list[dict[str, Any]] | None = None,
                   seed_symbols: list[str] | None = None,
                   finding_class: str, meta_extra: dict | None = None,
                   ) -> dict[str, Any]:
    """Standard TOPIC payload for inbox.upsert_candidate (domain pinned)."""
    meta = {
        "research_domain": COVERAGE_DOMAINS[area],
        "coverage_adapter": area,
        "finding_class": finding_class,
    }
    meta.update(meta_extra or {})
    return dict(
        candidate_type="TOPIC_CANDIDATE",
        label=label[:120],
        summary=(summary or "")[:400] or None,
        evidence=(evidence or [])[:8],
        seed_symbols=[s.upper() for s in (seed_symbols or [])][:12],
        meta=meta,
    )


# ── holdings (domain=portfolio_holdings) ─────────────────────────────────────

def holdings_findings(*, rm_path: Path | str | None = None,
                      earnings_days: int = 14,
                      dividend_concentration_pct: float = 0.40,
                      max_symbols: int = 12) -> list[dict[str, Any]]:
    """One TOPIC per finding class: stops gap, upcoming earnings,
    dividend-income concentration. Empty finding classes emit nothing."""
    payloads: list[dict[str, Any]] = []

    # (1) positions without stop protection — risk_management.json snapshot
    rm = _read_json(rm_path or RISK_MGMT_PATH)
    unprotected = [p for p in (rm.get("positions") or [])
                   if isinstance(p, dict)
                   and (str(p.get("status") or "").upper() == "NO STOP"
                        or p.get("protected") is False)
                   and float(p.get("market_value") or 0) > 0]
    if unprotected:
        syms = sorted({str(p.get("symbol") or "").upper()
                       for p in unprotected if p.get("symbol")})
        total_mv = sum(float(p.get("market_value") or 0) for p in unprotected)
        payloads.append(_topic_payload(
            "holdings", "Holdings coverage: positions without stops",
            f"{len(unprotected)} held position(s) without stop protection "
            f"(~${total_mv:,.0f} market value): {', '.join(syms[:max_symbols])}",
            evidence=[{"note": f"{p.get('symbol')} ${float(p.get('market_value') or 0):,.0f} "
                               f"in {p.get('account')} — no stop"}
                      for p in unprotected[:6]],
            seed_symbols=syms[:max_symbols],
            finding_class="stops_gap",
            meta_extra={"unprotected_count": len(unprotected),
                        "unprotected_mv": round(total_mv, 2),
                        "source_file": "risk_management.json"}))

    held = sorted(subjects.held_symbols())

    # (2) upcoming earnings among held symbols — symbol_profiles
    if held:
        rows = _rows(
            """SELECT UPPER(symbol) AS symbol, next_earnings_date
               FROM symbol_profiles
               WHERE UPPER(symbol) = ANY(%s)
                 AND next_earnings_date IS NOT NULL
                 AND next_earnings_date >= CURRENT_DATE
                 AND next_earnings_date <= CURRENT_DATE + %s::int
               ORDER BY next_earnings_date ASC""", (held, int(earnings_days)))
        if rows:
            syms = [r["symbol"] for r in rows]
            payloads.append(_topic_payload(
                "holdings",
                f"Holdings coverage: earnings within {int(earnings_days)} days",
                f"{len(rows)} held symbol(s) report earnings in the next "
                f"{int(earnings_days)}d: "
                + ", ".join(f"{r['symbol']} ({r['next_earnings_date']})"
                            for r in rows[:max_symbols]),
                evidence=[{"note": f"{r['symbol']} next earnings "
                                   f"{r['next_earnings_date']}"} for r in rows[:6]],
                seed_symbols=syms,
                finding_class="upcoming_earnings",
                meta_extra={"earnings_window_days": int(earnings_days)}))

    # (3) dividend-income concentration — holdings.json + ticker_dividend_data
    if held:
        div_rows = _rows(
            """SELECT UPPER(symbol) AS symbol, annual_dividend_per_share
               FROM ticker_dividend_data
               WHERE UPPER(symbol) = ANY(%s)
                 AND annual_dividend_per_share IS NOT NULL""", (held,))
        adps = {r["symbol"]: float(r["annual_dividend_per_share"] or 0)
                for r in div_rows}
        income: dict[str, float] = {}
        for sym, per_share in adps.items():
            shares = sum(float(h.get("shares") or 0)
                         for h in subjects.holdings_for_symbol(sym))
            est = shares * per_share
            if est > 0:
                income[sym] = est
        total_income = sum(income.values())
        if total_income > 0:
            top_sym, top_income = max(income.items(), key=lambda kv: kv[1])
            share = top_income / total_income
            if share >= float(dividend_concentration_pct):
                payloads.append(_topic_payload(
                    "holdings", "Holdings coverage: dividend income concentration",
                    f"{top_sym} contributes ~{share:.0%} of estimated annual "
                    f"dividend income (${top_income:,.0f} of ${total_income:,.0f} "
                    f"across {len(income)} paying holdings)",
                    evidence=[{"note": f"{s} est ${v:,.0f}/yr"}
                              for s, v in sorted(income.items(),
                                                 key=lambda kv: -kv[1])[:6]],
                    seed_symbols=[top_sym],
                    finding_class="dividend_concentration",
                    meta_extra={"top_symbol": top_sym,
                                "top_income_share": round(share, 3),
                                "threshold": float(dividend_concentration_pct)}))
    return payloads


# ── watchlist (domain=watchlist) ─────────────────────────────────────────────

def watchlist_findings(*, stale_days: int = 7, research_days: int = 30,
                       max_symbols: int = 12) -> list[dict[str, Any]]:
    """Stale-intelligence and missing-research finding classes over the
    governed (S0-S2) active watchlist."""
    payloads: list[dict[str, Any]] = []

    stale = _rows(
        """SELECT UPPER(symbol) AS symbol,
                  COALESCE(hermes_scored_at, last_enriched_at, updated_at) AS last_intel
           FROM watchlist_items
           WHERE status IN ('active','researched')
             AND scope_tier IN ('S0','S1','S2')
             AND COALESCE(hermes_scored_at, last_enriched_at, updated_at)
                 < now() - make_interval(days => %s)
           ORDER BY 2 ASC LIMIT 50""", (int(stale_days),))
    if stale:
        syms = [r["symbol"] for r in stale]
        payloads.append(_topic_payload(
            "watchlist",
            f"Watchlist coverage: stale intelligence over {int(stale_days)} days",
            f"{len(stale)} governed watchlist symbol(s) with no intelligence "
            f"refresh in {int(stale_days)}d: {', '.join(syms[:max_symbols])}",
            evidence=[{"note": f"{r['symbol']} last intel {r['last_intel']}"}
                      for r in stale[:6]],
            seed_symbols=syms[:max_symbols],
            finding_class="stale_intelligence",
            meta_extra={"stale_days": int(stale_days), "stale_count": len(stale)}))

    missing = _rows(
        """SELECT UPPER(wi.symbol) AS symbol
           FROM watchlist_items wi
           WHERE wi.status IN ('active','researched')
             AND wi.scope_tier IN ('S0','S1','S2')
             AND NOT EXISTS (
                   SELECT 1 FROM hermes_research_intelligence hri
                   WHERE UPPER(hri.symbol) = UPPER(wi.symbol)
                     AND hri.created_at > now() - make_interval(days => %s))
           ORDER BY wi.hermes_composite_score DESC NULLS LAST
           LIMIT 50""", (int(research_days),))
    if missing:
        syms = [r["symbol"] for r in missing]
        payloads.append(_topic_payload(
            "watchlist",
            f"Watchlist coverage: missing research over {int(research_days)} days",
            f"{len(missing)}{'+' if len(missing) >= 50 else ''} governed "
            f"watchlist symbol(s) with no research rows in {int(research_days)}d: "
            f"{', '.join(syms[:max_symbols])}",
            evidence=[{"note": f"{s} — no hermes_research_intelligence rows "
                               f"in {int(research_days)}d"} for s in syms[:6]],
            seed_symbols=syms[:max_symbols],
            finding_class="missing_research",
            meta_extra={"research_days": int(research_days),
                        "missing_count": len(missing)}))
    return payloads


# ── sectors (domain=sectors) ─────────────────────────────────────────────────

def sector_cluster_findings(*, min_cluster: int = 3, limit: int = 5,
                            max_symbols: int = 12) -> list[dict[str, Any]]:
    """Sector clusters among active watchlist symbols → one TOPIC per sector."""
    rows = _rows(
        """SELECT sp.sector AS sector, count(*) AS n,
                  (array_agg(UPPER(wi.symbol)
                             ORDER BY wi.hermes_composite_score DESC NULLS LAST))[1:24]
                      AS symbols
           FROM watchlist_items wi
           JOIN symbol_profiles sp ON UPPER(sp.symbol) = UPPER(wi.symbol)
           WHERE wi.status IN ('active','researched')
             AND wi.scope_tier IN ('S0','S1','S2')
             AND sp.sector IS NOT NULL AND sp.sector <> ''
           GROUP BY sp.sector
           HAVING count(*) >= %s
           ORDER BY count(*) DESC LIMIT %s""",
        (int(min_cluster), int(limit)))
    payloads = []
    for r in rows:
        sector = str(r.get("sector") or "").strip()
        syms = [s for s in (r.get("symbols") or []) if s]
        if not sector:
            continue
        payloads.append(_topic_payload(
            "sectors", f"Sector cluster: {sector}",
            f"{int(r['n'])} active governed watchlist symbol(s) cluster in "
            f"{sector}: {', '.join(syms[:max_symbols])}",
            evidence=[{"note": f"{int(r['n'])} governed watchlist symbols in {sector}"}],
            seed_symbols=syms[:max_symbols],
            finding_class="sector_cluster",
            meta_extra={"sectors": [sector], "cluster_size": int(r["n"])}))
    return payloads


# ── term-recurrence adapters (taxes / retirement / legal / macro) ────────────

def term_topic_findings(area: str, *, days: int = 7, limit: int = 5,
                        min_matches: int = 2) -> list[dict[str, Any]]:
    """Recent news_articles + hermes_research_intelligence rows matching the
    area's term list → one TOPIC per recurring term (domain pinned)."""
    terms = TERM_SETS.get(area)
    if not terms:
        return []
    ilikes_news = " OR ".join(["title ILIKE %s OR summary ILIKE %s"] * len(terms))
    news_params: list[Any] = [int(days)]
    for t in terms:
        news_params += [f"%{t}%", f"%{t}%"]
    rows = _rows(
        f"""SELECT COALESCE(title, '') AS text_a, COALESCE(summary, '') AS text_b,
                   COALESCE(source, 'news') AS source, source_url
            FROM news_articles
            WHERE created_at > now() - make_interval(days => %s)
              AND ({ilikes_news})
            ORDER BY created_at DESC LIMIT 300""", tuple(news_params))

    ilikes_hri = " OR ".join(["topic ILIKE %s OR summary ILIKE %s"] * len(terms))
    hri_params: list[Any] = [int(days)]
    for t in terms:
        hri_params += [f"%{t}%", f"%{t}%"]
    rows += _rows(
        f"""SELECT COALESCE(topic, '') AS text_a, COALESCE(summary, '') AS text_b,
                   COALESCE(source, 'hermes_research') AS source,
                   NULL AS source_url
            FROM hermes_research_intelligence
            WHERE created_at > now() - make_interval(days => %s)
              AND ({ilikes_hri})
            ORDER BY created_at DESC LIMIT 200""", tuple(hri_params))

    by_term: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        text = f"{r.get('text_a') or ''} {r.get('text_b') or ''}"
        for term in terms:
            if _term_matches(text, term):
                by_term.setdefault(term, []).append(r)

    payloads = []
    for term, matched in sorted(by_term.items(), key=lambda kv: -len(kv[1])):
        if len(matched) < max(1, int(min_matches)):
            continue
        if len(payloads) >= int(limit):
            break
        sources = sorted({str(m.get("source") or "unknown") for m in matched})
        payloads.append(_topic_payload(
            area, f"{area.replace('_', ' ').title()} research: {term}",
            f"{len(matched)} recent news/research item(s) in {int(days)}d "
            f"matched '{term}' (sources: {', '.join(sources[:5])})",
            evidence=[{"source_domain": m.get("source"),
                       "url": m.get("source_url"),
                       "note": (m.get("text_a") or "")[:140]}
                      for m in matched[:5]],
            finding_class="term_recurrence",
            meta_extra={"matched_term": term, "match_count": len(matched),
                        "window_days": int(days), "keywords": [term]}))
    return payloads


def taxes_findings(**kw) -> list[dict[str, Any]]:
    return term_topic_findings("taxes", **kw)


def retirement_findings(**kw) -> list[dict[str, Any]]:
    return term_topic_findings("retirement", **kw)


def legal_findings(**kw) -> list[dict[str, Any]]:
    return term_topic_findings("legal", **kw)


def macro_findings(**kw) -> list[dict[str, Any]]:
    return term_topic_findings("macro", **kw)


# ── system_ops (domain=system_ops) ───────────────────────────────────────────

def system_ops_findings(*, limit: int = 5) -> list[dict[str, Any]]:
    """Latest failing/stale system_health_checks components → one TOPIC each.
    Promotion path for these is escalation_candidate (operator-gated), which
    the system_ops domain registry entry allows."""
    rows = _rows(
        """SELECT component, check_type, status, severity, failure_count,
                  last_error, updated_at
           FROM (SELECT DISTINCT ON (check_type, component)
                        component, check_type, status, severity,
                        failure_count, last_error, updated_at
                 FROM system_health_checks
                 ORDER BY check_type, component, updated_at DESC) latest
           WHERE status NOT IN %s
           ORDER BY CASE WHEN severity = 'CRITICAL' THEN 0 ELSE 1 END,
                    updated_at DESC
           LIMIT %s""", (_HEALTHY_STATUSES, int(limit)))
    payloads = []
    for r in rows:
        component = str(r.get("component") or "unknown")
        status = str(r.get("status") or "UNKNOWN")
        err = (str(r.get("last_error") or "").strip())[:160]
        payloads.append(_topic_payload(
            "system_ops", f"System health: {component} {status}",
            f"{r.get('check_type')} check for {component} is {status} "
            f"(severity {r.get('severity')}, failure_count "
            f"{int(r.get('failure_count') or 0)})"
            + (f" — {err}" if err else ""),
            evidence=[{"note": f"system_health_checks: {component} "
                               f"{status} at {r.get('updated_at')}"
                               + (f" — {err}" if err else "")}],
            finding_class="health_check_failure",
            meta_extra={"promotion_path_hint": "escalation_candidate",
                        "component": component,
                        "check_type": r.get("check_type"),
                        "health_status": status,
                        "severity": r.get("severity")}))
    return payloads


# ── registry ─────────────────────────────────────────────────────────────────

COVERAGE_ADAPTERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "holdings": holdings_findings,
    "watchlist": watchlist_findings,
    "sectors": sector_cluster_findings,
    "taxes": taxes_findings,
    "retirement": retirement_findings,
    "legal": legal_findings,
    "macro": macro_findings,
    "system_ops": system_ops_findings,
}
