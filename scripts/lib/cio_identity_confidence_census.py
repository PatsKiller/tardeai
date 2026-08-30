"""P2-WS4 / P2-WS5 — identity confidence census + position-state matrix.

READ_ONLY_ADVISORY. MEMORY_BEHAVIOR_INFLUENCE = 0.

* WS4 — measure resolvable vs stamped ``subject_guid`` on NEW_POSITION_IF /
  reentry / watch / holdings; classify CUSIP vs ticker; publish the
  Identity Confidence Score definition and a live cohort score.
* WS5 — classify HELD / EXIT / WATCH / CASH / DUST using
  ``collect_surface_a_status`` (shares < 1 → EXITED), holdings truth
  (``DUST_POLICY`` $50 MV), and cash / CUSIP instrument-id rows.

Never mints identities. Never deletes lots. Never writes the registry or
holdings. Lookup and classification only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CIOIdentityConfidenceCensus@v1"
POSITION_SCHEMA = "CIOPositionStateMatrix@v1"

# Surface A material-held rule (Wave 2 slice 04 / SCHG-class).
MATERIAL_HELD_MIN_SHARES = 1.0

# Identity Confidence Score@v1 — promotion-grade definition (P2-WS4).
#
# Two numbers are never interchangeable (Wave 2 slice 13):
#   resolvable = registry can answer for the symbol today
#   stamped    = the payload row actually carries subject_guid
#
# Production records (master plan): HELD material + ACTIVE watch + EXIT with
# a former-table row. Dust, cash, and CUSIP-as-symbol are out of that
# denominator. Target: 100% resolvable for production records; stamped
# carriage is tracked separately as a follow-on stamping gap.
CONFIDENCE_SCORE_DEFINITION: dict[str, Any] = {
    "schema": "IdentityConfidenceScore@v1",
    "authority": AUTHORITY,
    "memory_behavior_influence": MBI,
    "production_record": (
        "HELD material (≥1 share AND not DUST_RESIDUAL under $50 MV policy) "
        "+ ACTIVE watch (opportunity_book ∪ watch_block) "
        "+ EXIT with former-table row"
    ),
    "exclusions": [
        "CASH / cash-vehicle rows",
        "CUSIP / ISIN / UNKNOWN_INSTRUMENT_ID held as symbol",
        "DUST_RESIDUAL ($50 MV aggregate)",
        "Surface A residual dust (<1 share) when scoring HELD material",
    ],
    "components": {
        "resolvable": {
            "weight": 0.50,
            "meaning": "identity_registry.lookup_symbol answers for the ticker",
        },
        "confirmed": {
            "weight": 0.30,
            "meaning": "entity.identity_status == CONFIRMED (durable instrument id)",
            "status_scores": {
                "CONFIRMED": 1.0,
                "CANDIDATE": 0.6,
                "UNRESOLVED_WITH_REASON": 0.2,
                "MISSING": 0.0,
            },
        },
        "stamped": {
            "weight": 0.20,
            "meaning": "payload row carries subject_guid (carriage, not registry)",
        },
    },
    "formula": (
        "cohort_score = 0.50 * resolvable_frac + 0.30 * mean(status_score) "
        "+ 0.20 * stamped_frac"
    ),
    "target": (
        "100% resolvable for production records; CONFIRMED preferred for HELD "
        "material; stamped carriage gap is measured, not auto-fixed here"
    ),
    "id_classes": {
        "TICKER": "eligible for production records when held/watched/exited",
        "CUSIP": "instrument_id — never rendered as ticker; not production ticker",
        "ISIN": "instrument_id — never rendered as ticker",
        "UNKNOWN_INSTRUMENT_ID": "instrument_id — resolve before any surface use",
        "CASH": "cash sleeve — never a security identity",
    },
    "never": [
        "ticker-as-security-GUID regression",
        "minting identities from this census",
        "lot DELETE",
    ],
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _pct(hit: int, total: int) -> Optional[float]:
    return round(100.0 * hit / total, 1) if total else None


def _frac(hit: int, total: int) -> float:
    return (hit / total) if total else 0.0


def _symbols_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    return [str(r.get("symbol") or "").strip().upper() for r in rows if r.get("symbol")]


def _status_score(identity_status: str | None) -> float:
    table = CONFIDENCE_SCORE_DEFINITION["components"]["confirmed"]["status_scores"]
    return float(table.get(str(identity_status or "MISSING"), 0.0))


def _cohort_score(
    *,
    n: int,
    resolvable_n: int,
    stamped_n: int,
    status_scores: list[float],
) -> Optional[float]:
    if n <= 0:
        return None
    weights = CONFIDENCE_SCORE_DEFINITION["components"]
    mean_status = sum(status_scores) / n if status_scores else 0.0
    score = (
        weights["resolvable"]["weight"] * _frac(resolvable_n, n)
        + weights["confirmed"]["weight"] * mean_status
        + weights["stamped"]["weight"] * _frac(stamped_n, n)
    )
    return round(score, 4)


def _surface_identity(
    *,
    name: str,
    rows: list[dict[str, Any]],
    registry: dict[str, Any],
    lookup_symbol,
) -> dict[str, Any]:
    syms = _symbols_from_rows(rows)
    status_scores: list[float] = []
    resolvable_n = 0
    stamped_n = 0
    unresolved: list[str] = []
    by_status: dict[str, int] = {}
    for i, sym in enumerate(syms):
        ent = lookup_symbol(registry, sym)
        if ent:
            resolvable_n += 1
            st = str(ent.get("identity_status") or "MISSING")
        else:
            st = "MISSING"
            unresolved.append(sym)
        by_status[st] = by_status.get(st, 0) + 1
        status_scores.append(_status_score(st if ent else "MISSING"))
        row = rows[i] if i < len(rows) else {}
        if isinstance(row, dict) and row.get("subject_guid"):
            stamped_n += 1
    unresolved_u = sorted(set(unresolved))
    return {
        "surface": name,
        "n": len(syms),
        "resolvable_n": resolvable_n,
        "resolvable_pct": _pct(resolvable_n, len(syms)),
        "stamped_n": stamped_n,
        "stamped_pct": _pct(stamped_n, len(syms)),
        "by_identity_status": by_status,
        "confidence_score": _cohort_score(
            n=len(syms),
            resolvable_n=resolvable_n,
            stamped_n=stamped_n,
            status_scores=status_scores,
        ),
        "unresolved_symbols": unresolved_u[:20],
        "unresolved_truncated": len(unresolved_u) > 20,
        "class": "D",
    }


def measure_holdings_identity(
    *,
    holdings: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Resolvable/stamped on held equity tickers; CUSIP vs ticker split."""
    from scripts.lib.holdings_universe import (
        classify_instrument_id,
        held_dust_tickers,
        held_equity_tickers,
        held_equity_tickers_nondust,
        held_instrument_id_rows,
        is_cash_row,
        is_held_equity_ticker,
        load_holdings_doc,
    )
    from scripts.lib.identity_registry import load_cached, lookup_symbol

    root_path = Path(root) if root else None
    doc = registry if registry is not None else load_cached(root_path)
    holdings = holdings if holdings is not None else load_holdings_doc(root=root_path)
    rows = holdings.get("holdings") if isinstance(holdings, dict) else None
    if not isinstance(rows, list):
        rows = []

    ticker_rows = [
        r for r in rows
        if isinstance(r, dict)
        and not is_cash_row(r)
        and is_held_equity_ticker(str(r.get("symbol") or ""))
    ]
    # One row per symbol for coverage (first occurrence); stamped if ANY row carries guid.
    by_sym: dict[str, dict[str, Any]] = {}
    stamped_syms: set[str] = set()
    for r in ticker_rows:
        sym = str(r.get("symbol") or "").upper()
        by_sym.setdefault(sym, r)
        if r.get("subject_guid"):
            stamped_syms.add(sym)

    if root_path is not None:
        all_tickers = held_equity_tickers(root=root_path)
        nondust = held_equity_tickers_nondust(root=root_path)
        dust = held_dust_tickers(root=root_path)
        instrument_ids = held_instrument_id_rows(root=root_path)
    else:
        from scripts.lib.cio_investment_product import (
            collect_held_instrument_ids,
            dust_symbols,
            held_equity_symbols_nondust,
        )

        all_tickers = sorted(by_sym)
        dust = dust_symbols(holdings)
        nondust = held_equity_symbols_nondust(holdings)
        instrument_ids = collect_held_instrument_ids(holdings).get("items") or []

    synthetic_rows = []
    for sym in all_tickers:
        row = dict(by_sym.get(sym) or {"symbol": sym})
        if sym in stamped_syms:
            row["subject_guid"] = row.get("subject_guid") or "stamped"
        synthetic_rows.append(row)

    held_cov = _surface_identity(
        name="holdings_equity",
        rows=synthetic_rows,
        registry=doc,
        lookup_symbol=lookup_symbol,
    )
    # Correct stamped against symbol set (synthetic may fake guid marker).
    held_cov["stamped_n"] = sum(1 for s in all_tickers if s in stamped_syms)
    held_cov["stamped_pct"] = _pct(held_cov["stamped_n"], len(all_tickers))
    held_cov["confidence_score"] = _cohort_score(
        n=held_cov["n"],
        resolvable_n=held_cov["resolvable_n"],
        stamped_n=held_cov["stamped_n"],
        status_scores=[
            _status_score(
                (lookup_symbol(doc, s) or {}).get("identity_status")
                if lookup_symbol(doc, s)
                else "MISSING"
            )
            for s in all_tickers
        ],
    )

    nondust_rows = [{"symbol": s} for s in nondust]
    nondust_cov = _surface_identity(
        name="holdings_held_nondust",
        rows=nondust_rows,
        registry=doc,
        lookup_symbol=lookup_symbol,
    )
    nondust_cov["stamped_n"] = sum(1 for s in nondust if s in stamped_syms)
    nondust_cov["stamped_pct"] = _pct(nondust_cov["stamped_n"], len(nondust))
    nondust_cov["confidence_score"] = _cohort_score(
        n=nondust_cov["n"],
        resolvable_n=nondust_cov["resolvable_n"],
        stamped_n=nondust_cov["stamped_n"],
        status_scores=[
            _status_score(
                (lookup_symbol(doc, s) or {}).get("identity_status")
                if lookup_symbol(doc, s)
                else "MISSING"
            )
            for s in nondust
        ],
    )
    cusip_vs_ticker = {
        "ticker_n": len(all_tickers),
        "held_nondust_n": len(nondust),
        "dust_residual_n": len(dust),
        "dust_residual_symbols": list(dust),
        "instrument_id_n": len(instrument_ids),
        "instrument_ids": [
            {
                "instrument_id": i.get("instrument_id"),
                "id_type": i.get("id_type") or classify_instrument_id(str(i.get("instrument_id") or "")),
                "is_ticker": False,
                "market_value": i.get("market_value"),
            }
            for i in instrument_ids
        ],
        "note": (
            "CUSIP/ISIN rows are instrument_id, not ticker. They are excluded "
            "from holdings_equity resolvable % and from production records."
        ),
    }

    return {
        "holdings_equity": held_cov,
        "holdings_held_nondust": nondust_cov,
        "cusip_vs_ticker": cusip_vs_ticker,
        "holdings_rows_with_subject_guid": len(stamped_syms),
    }


def measure_identity_confidence_census(
    *,
    product: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
    holdings: dict[str, Any] | None = None,
    previously_traded: list[dict[str, Any]] | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Full WS4 census: product surfaces + holdings + production cohort score."""
    from scripts.lib.cio_identity_coverage import SURFACE_PATHS, _dig, measure_identity_coverage
    from scripts.lib.cio_investment_product import build_product, collect_holdings
    from scripts.lib.identity_registry import load_cached, lookup_symbol

    root_path = Path(root) if root else None
    if product is None and root_path is not None:
        product = build_product(root=root_path)
    product = product or {}
    if holdings is None and root_path is not None:
        holdings = collect_holdings(root_path)
    holdings = holdings or {}
    doc = registry if registry is not None else load_cached(root_path)

    # Reuse slice-13 surface measure, then enrich with confidence scores.
    base = measure_identity_coverage(product=product, registry=doc, root=root_path)
    surfaces: list[dict[str, Any]] = []
    for name, paths in SURFACE_PATHS:
        rows: list[dict[str, Any]] = []
        for path in paths:
            rows = _dig(product, path)
            if rows:
                break
        surfaces.append(
            _surface_identity(name=name, rows=rows, registry=doc, lookup_symbol=lookup_symbol)
        )

    holdings_part = measure_holdings_identity(
        holdings=holdings, registry=doc, root=root_path
    )

    # ACTIVE watch = opportunity ∪ watch_block (unique).
    watch_rows: list[dict[str, Any]] = []
    seen_w: set[str] = set()
    for path in (("watch_block_summary", "top"), ("opportunity_book", "top")):
        for r in _dig(product, path):
            sym = str(r.get("symbol") or "").upper()
            if sym and sym not in seen_w:
                seen_w.add(sym)
                watch_rows.append(r)
    watch_cov = _surface_identity(
        name="active_watch",
        rows=watch_rows,
        registry=doc,
        lookup_symbol=lookup_symbol,
    )

    # EXIT former table.
    if previously_traded is None:
        try:
            from scripts.lib.cio_investment_product import collect_previously_traded

            previously_traded = collect_previously_traded()
        except Exception:
            previously_traded = []
    exit_rows = [
        r for r in (previously_traded or [])
        if isinstance(r, dict) and r.get("symbol")
    ]
    # Dedup by symbol for cohort scoring.
    exit_by: dict[str, dict[str, Any]] = {}
    for r in exit_rows:
        exit_by.setdefault(str(r["symbol"]).upper(), r)
    exit_cov = _surface_identity(
        name="exit_former_table",
        rows=list(exit_by.values()),
        registry=doc,
        lookup_symbol=lookup_symbol,
    )

    # Production cohort = HELD nondust ∪ active watch ∪ exit former.
    from scripts.lib.holdings_universe import held_equity_tickers_nondust

    if root_path is not None:
        held_material = held_equity_tickers_nondust(root=root_path)
    else:
        from scripts.lib.cio_investment_product import held_equity_symbols_nondust

        held_material = held_equity_symbols_nondust(holdings)

    prod_syms = sorted(set(held_material) | set(seen_w) | set(exit_by))
    stamped_lookup: set[str] = set()
    for _name, paths in SURFACE_PATHS:
        for path in paths:
            for r in _dig(product, path):
                if r.get("subject_guid") and r.get("symbol"):
                    stamped_lookup.add(str(r["symbol"]).upper())
    stamped_lookup |= {
        str(r.get("symbol") or "").upper()
        for r in (holdings.get("holdings") or [])
        if isinstance(r, dict) and r.get("subject_guid") and r.get("symbol")
    }
    prod_rows = [
        ({"symbol": s, "subject_guid": "present"} if s in stamped_lookup else {"symbol": s})
        for s in prod_syms
    ]
    production = _surface_identity(
        name="production_records",
        rows=prod_rows,
        registry=doc,
        lookup_symbol=lookup_symbol,
    )

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "minted": 0,
        "mint": False,
        "measured_at": _now(),
        "root": str(root_path) if root_path else None,
        "confidence_score_definition": CONFIDENCE_SCORE_DEFINITION,
        "surfaces": surfaces,
        "active_watch": watch_cov,
        "exit_former_table": exit_cov,
        "holdings": holdings_part,
        "production_records": production,
        "slice13_compat": {
            "total_rows": base.get("total_rows"),
            "total_resolvable_pct": base.get("total_resolvable_pct"),
            "total_stamped_pct": base.get("total_stamped_pct"),
            "registry_entities": base.get("registry_entities"),
            "registry_symbols": base.get("registry_symbols"),
        },
        "class": "D",
        "note": (
            "resolvable ≠ stamped. Production target is 100% resolvable. "
            "This census never mints and never stamps."
        ),
    }


def _row_shares(row: dict[str, Any] | None) -> float:
    if not isinstance(row, dict):
        return 0.0
    for key in ("shares", "broker_actual_shares", "quantity"):
        if row.get(key) is None:
            continue
        try:
            return float(row.get(key))
        except (TypeError, ValueError):
            continue
    return 0.0


def collect_position_state_matrix(
    *,
    holdings: dict[str, Any] | None = None,
    product: dict[str, Any] | None = None,
    previously_traded: list[dict[str, Any]] | None = None,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """P2-WS5 — HELD / EXIT / WATCH / CASH / DUST matrix (read-only).

    Rules (documented, not invented):
    * Surface A: shares ≥ 1 → HELD; 0 < shares < 1 → EXITED (SCHG-class);
      former table → EXITED; else UNAVAILABLE.
    * Holdings truth dust: aggregate MV < $50 → DUST_RESIDUAL (lot kept).
    * Cash never a security. CUSIP never a ticker.
    """
    from scripts.lib.cio_identity_coverage import _dig
    from scripts.lib.cio_investment_product import (
        build_product,
        collect_holdings,
        collect_held_instrument_ids,
        collect_surface_a_status,
    )
    from scripts.lib.holdings_universe import (
        DUST_POLICY,
        held_cash_rows,
        held_dust_tickers,
        held_equity_tickers_nondust,
        held_market_value_by_ticker,
        is_cash_row,
        is_held_equity_ticker,
        load_holdings_doc,
    )

    root_path = Path(root) if root else None
    if holdings is None and root_path is not None:
        holdings = collect_holdings(root_path)
    if holdings is None:
        holdings = load_holdings_doc(root=root_path) if root_path else {"holdings": []}
    if product is None and root_path is not None:
        product = build_product(root=root_path)
    product = product or {}

    if previously_traded is None:
        try:
            from scripts.lib.cio_investment_product import collect_previously_traded

            previously_traded = collect_previously_traded()
        except Exception:
            previously_traded = []

    rows = holdings.get("holdings") if isinstance(holdings, dict) else []
    if not isinstance(rows, list):
        rows = []

    # Share-rule dust (<1 share), aggregated per ticker.
    share_agg: dict[str, float] = {}
    for r in rows:
        if not isinstance(r, dict) or is_cash_row(r):
            continue
        sym = str(r.get("symbol") or "").upper()
        if not is_held_equity_ticker(sym):
            continue
        share_agg[sym] = share_agg.get(sym, 0.0) + _row_shares(r)

    share_dust = sorted(s for s, sh in share_agg.items() if 0 < sh < MATERIAL_HELD_MIN_SHARES)

    if root_path is not None:
        mv_dust = held_dust_tickers(root=root_path)
        held_nondust = held_equity_tickers_nondust(root=root_path)
        mv_by = held_market_value_by_ticker(root=root_path)
        cash_rows = held_cash_rows(root=root_path)
    else:
        from scripts.lib.cio_investment_product import dust_symbols, held_equity_symbols_nondust, market_value_by_symbol

        mv_dust = dust_symbols(holdings)
        held_nondust = held_equity_symbols_nondust(holdings)
        mv_by = market_value_by_symbol(holdings)
        cash_rows = [r for r in rows if isinstance(r, dict) and is_cash_row(r)]

    instrument_ids = collect_held_instrument_ids(holdings)

    # Surface A over: share-dust ∪ MV-dust ∪ held_nondust sample ∪ former defaults.
    probe = sorted(set(share_dust) | set(mv_dust) | set(held_nondust[:5]) | {"SCHG", "AXTI", "FATN", "FANG"})
    # Include all former-table symbols that also appear in share/MV dust for honesty.
    surface_a = collect_surface_a_status(
        symbols=probe,
        holdings=holdings,
        previously_traded=previously_traded,
    )

    # Default SCHG-class probe (canonical four).
    surface_a_default = collect_surface_a_status(
        holdings=holdings,
        previously_traded=previously_traded,
    )

    watch_syms: list[str] = []
    seen: set[str] = set()
    for path in (("watch_block_summary", "top"), ("opportunity_book", "top")):
        for r in _dig(product, path):
            sym = str(r.get("symbol") or "").upper()
            if sym and sym not in seen:
                seen.add(sym)
                watch_syms.append(sym)

    exit_syms = sorted({
        str(r.get("symbol") or "").upper()
        for r in (previously_traded or [])
        if isinstance(r, dict) and r.get("symbol")
    })

    cash_mv = 0.0
    for r in cash_rows:
        try:
            cash_mv += float(r.get("market_value") or 0)
        except (TypeError, ValueError):
            pass

    # Dust table: union of share-rule and MV-rule with both labels.
    dust_table: list[dict[str, Any]] = []
    for sym in sorted(set(share_dust) | set(mv_dust)):
        sh = round(share_agg.get(sym, 0.0), 6)
        mv = mv_by.get(sym)
        sa_items = {i["symbol"]: i for i in surface_a.get("items") or []}
        sa = sa_items.get(sym) or {}
        dust_table.append({
            "symbol": sym,
            "aggregate_shares": sh,
            "aggregate_market_value": mv,
            "share_rule_dust": sym in share_dust,  # <1 share
            "mv_rule_dust": sym in mv_dust,        # < $50
            "surface_a_status": sa.get("status"),
            "surface_a_reason": sa.get("status_reason"),
            "residual_shares": sa.get("residual_shares"),
            "holding_status_label": (
                "DUST_RESIDUAL" if sym in mv_dust
                else ("EXITED_SHARE_DUST" if sym in share_dust else "HELD")
            ),
            "class": "D",
        })

    # Dual reentry pipes — labeled, not merged (G-DUAL-01 / slice 10).
    reentry_book = product.get("reentry_book") if isinstance(product, dict) else {}
    reentry_n = len((reentry_book or {}).get("names") or []) if isinstance(reentry_book, dict) else 0
    opportunities = product.get("opportunities") if isinstance(product, dict) else {}
    queue_reentry = None
    if isinstance(opportunities, dict):
        queue_reentry = opportunities.get("reentry_total")

    return {
        "schema": POSITION_SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "deletes_lots": False,
        "measured_at": _now(),
        "root": str(root_path) if root_path else None,
        "states": ["HELD", "EXIT", "WATCH", "CASH", "DUST"],
        "rules": {
            "surface_a_material_held_min_shares": MATERIAL_HELD_MIN_SHARES,
            "surface_a_dust": "0 < shares < 1 → EXITED (residual_dust_not_material_held); SCHG fixture",
            "holdings_dust_policy": DUST_POLICY,
            "cash": "never a security identity / never HELD equity",
            "cusip": "instrument_id, not ticker; never active equity position",
            "reentry": "Surface A reentry_book and queue opportunities.reentry_total stay labeled, not merged",
        },
        "counts": {
            "HELD_nondust_mv_policy": len(held_nondust),
            "EXIT_former_table": len(exit_syms),
            "WATCH_active": len(watch_syms),
            "CASH_rows": len(cash_rows),
            "CASH_market_value": round(cash_mv, 2),
            "DUST_share_lt_1": len(share_dust),
            "DUST_mv_lt_50": len(mv_dust),
            "instrument_id_cusip": instrument_ids.get("instrument_id_n", 0),
        },
        "held_nondust_symbols": list(held_nondust),
        "watch_symbols_n": len(watch_syms),
        "exit_former_symbols_n": len(exit_syms),
        "cash_rows_n": len(cash_rows),
        "cash_market_value": round(cash_mv, 2),
        "dust_table": dust_table,
        "instrument_ids": instrument_ids,
        "surface_a_default_probe": surface_a_default,
        "surface_a_dust_probe": surface_a,
        "reentry_pipes": {
            "surface_a_reentry_book_n": reentry_n,
            "queue_opportunities_reentry_total": queue_reentry,
            "merged": False,
            "note": "Dual pipes stay labeled (Wave 2 slice 10 / G-DUAL-01).",
        },
        "invariants": {
            "dust_never_active_position": True,
            "cash_never_security": True,
            "schg_surface_a_exited": any(
                i.get("symbol") == "SCHG" and i.get("status") == "EXITED"
                for i in (surface_a_default.get("items") or [])
            ),
            "lots_deleted": False,
        },
        "class": "D",
        "note": (
            "Share-rule dust (<1) drives Surface A EXITED; $50 MV drives "
            "DUST_RESIDUAL holdings label. Both are labels — lots untouched."
        ),
    }


def run_census(
    *,
    root: Path | str,
    include_position_state: bool = True,
) -> dict[str, Any]:
    """One-shot read-only census for P2-WS4 (+ optional WS5 matrix)."""
    root_path = Path(root)
    identity = measure_identity_confidence_census(root=root_path)
    out: dict[str, Any] = {
        "schema": "CIODiligenceP2Census@v1",
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "root": str(root_path),
        "measured_at": _now(),
        "identity_confidence": identity,
    }
    if include_position_state:
        out["position_state"] = collect_position_state_matrix(root=root_path)
    return out
