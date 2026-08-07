"""Rotation Ladders — Data Broker read model for sector RS20 rankings over time.

Computes sector relative-strength rankings (RS ratings 0-100) from market_quotes,
industry rankings within sectors, and thesis transition states from the Aegis nightly
briefs. Provides the core rotation-ladder data that the /api/v2/rotation/summary
endpoint uses WITHOUT spawning the heavy engine subprocess (~50s).

Sector RS methodology: for each sector ETF, compute trailing return over 1m/3m/6m
lookback windows from market_quotes daily closes, normalize to RS score (0-100),
and rank within sectors. The "ladder" is the sector RS ranking over the latest
window — it tells the operator which sectors have the strongest vs weakest momentum.

Status: ADDITIVE. This module does not replace the full rotation engine; it provides
the sector + industry ranking data that complements the engine's pair-based output.
The engine subprocess call itself stays in the endpoint handler (api_v2.py).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SNAPSHOT_DIR = PROJECT_ROOT / "state" / "data_broker"
SNAPSHOT_PATH = SNAPSHOT_DIR / "rotation_ladders.json"
DEFAULT_MAX_AGE_S = 300  # 5 min

SECTOR_ETFS = [
    ("XLK", "Technology"),
    ("XLF", "Financials"),
    ("XLE", "Energy"),
    ("XLI", "Industrials"),
    ("XLB", "Materials"),
    ("XLRE", "Real Estate"),
    ("XLV", "Health Care"),
    ("XLY", "Consumer Discretionary"),
    ("XLC", "Communication Services"),
    ("XLU", "Utilities"),
    ("XLP", "Consumer Staples"),
    ("SMH", "Semiconductors"),
    ("IBB", "Biotech"),
]

INDUSTRY_GROUP_ETFS = [
    # Tech sub-sectors
    ("SOXX", "Semiconductor Equipment", "Technology"),
    ("IGV", "Software", "Technology"),
    ("CIBR", "Cybersecurity", "Technology"),
    ("SKYY", "Cloud Computing", "Technology"),
    # Financial sub-sectors
    ("KRE", "Regional Banks", "Financials"),
    ("KIE", "Insurance", "Financials"),
    ("XLF", "Financials Broad", "Financials"),
    # Energy sub-sectors
    ("XOP", "Oil & Gas Exploration", "Energy"),
    ("XES", "Oil & Gas Equipment", "Energy"),
    ("ICLN", "Clean Energy", "Energy"),
    # Health Care sub-sectors
    ("XBI", "Biotech", "Health Care"),
    ("IHI", "Medical Devices", "Health Care"),
    ("XLV", "Health Care Broad", "Health Care"),
    # Real Estate sub-sectors
    ("VNQ", "REITs Broad", "Real Estate"),
    ("XLRE", "Real Estate Broad", "Real Estate"),
    # Consumer sub-sectors
    ("XRT", "Retail", "Consumer Discretionary"),
    ("XLY", "Consumer Disc Broad", "Consumer Discretionary"),
    ("XLP", "Consumer Staples Broad", "Consumer Staples"),
    # Industrials sub-sectors
    ("ITA", "Aerospace & Defense", "Industrials"),
    ("XLI", "Industrials Broad", "Industrials"),
    # Materials sub-sectors
    ("XLB", "Materials Broad", "Materials"),
    ("GDX", "Gold Miners", "Materials"),
    # Utilities sub-sectors
    ("XLU", "Utilities Broad", "Utilities"),
    ("TAN", "Solar", "Utilities"),
    # Communication sub-sectors
    ("XLC", "Comm Services Broad", "Communication Services"),
]


def _compute_rs_score(changes: list[float]) -> float | None:
    """Compute a 0-100 RS score from a list of periodic returns.
    Weights: 1m=50%, 3m=30%, 6m=20% (when available)."""
    weights = [0.5, 0.3, 0.2]
    available = [(c, w) for c, w in zip(changes, weights) if c is not None]
    if not available:
        return None
    total_weight = sum(w for _, w in available)
    raw = sum(c * w for c, w in available) / total_weight if total_weight > 0 else 0
    return round(raw, 2)


def _normalize_rs(scores: dict[str, float]) -> dict[str, int]:
    """Map raw scores to 0-100 RS ratings."""
    if not scores:
        return {}
    valid = {k: v for k, v in scores.items() if v is not None}
    if not valid:
        return {k: 50 for k in scores}
    mn, mx = min(valid.values()), max(valid.values())
    if mx == mn:
        return {k: 50 for k in scores}
    return {k: round((scores.get(k, mn) - mn) / (mx - mn) * 100) if scores.get(k) is not None else 50
            for k in scores}


def _sector_momentum_returns(db_query, symbols: list[str]) -> dict[str, list[float | None]]:
    """Fetch trailing returns for symbols at 1m/3m/6m lookback from market_quotes daily closes."""
    results: dict[str, list[float | None]] = {s: [None, None, None] for s in symbols}
    now = datetime.now(timezone.utc)

    for idx, lookback_days in enumerate([21, 63, 126]):
        cutoff = now - timedelta(days=lookback_days + 7)  # pad for weekends
        try:
            rows = db_query(
                """SELECT DISTINCT ON (symbol) symbol, price, fetched_at
                   FROM market_quotes
                   WHERE upper(symbol) = ANY(%s)
                     AND fetched_at > %s
                   ORDER BY symbol, fetched_at ASC""",
                (symbols, cutoff.isoformat()),
                fetch="all",
            ) or []
            # For each symbol, we need earliest close in window
            by_sym: dict[str, float] = {}
            seen: set[str] = set()
            for row in rows:
                sym = str(row.get("symbol") or "").upper()
                if sym in seen:
                    continue
                seen.add(sym)
                px = row.get("price")
                if px is not None:
                    try:
                        by_sym[sym] = float(px)
                    except (TypeError, ValueError):
                        pass

            # Get latest close
            latest_rows = db_query(
                """SELECT DISTINCT ON (symbol) symbol, price, fetched_at
                   FROM market_quotes
                   WHERE upper(symbol) = ANY(%s)
                     AND fetched_at > now() - interval '24 hours'
                   ORDER BY symbol, fetched_at DESC""",
                (symbols,),
                fetch="all",
            ) or []
            latest: dict[str, float] = {}
            lseen: set[str] = set()
            for row in latest_rows:
                sym = str(row.get("symbol") or "").upper()
                if sym in lseen:
                    continue
                lseen.add(sym)
                px = row.get("price")
                if px is not None:
                    try:
                        latest[sym] = float(px)
                    except (TypeError, ValueError):
                        pass

            for sym in symbols:
                s = sym.upper()
                if s in by_sym and s in latest and by_sym[s] > 0:
                    results[s][idx] = round((latest[s] - by_sym[s]) / by_sym[s] * 100, 2)
        except Exception:
            pass

    return results


def _build(db_query) -> dict[str, Any]:
    """Recompute rotation ladders from market_quotes + aegis briefs."""
    now = datetime.now(timezone.utc)

    # 1. Sector RS20 rankings
    sector_symbols = [s[0] for s in SECTOR_ETFS]
    sector_returns = _sector_momentum_returns(db_query, sector_symbols)

    sectors = []
    for etf, name in SECTOR_ETFS:
        rets = sector_returns.get(etf.upper(), [None, None, None])
        rs_raw = _compute_rs_score(rets)
        sectors.append({
            "etf": etf,
            "name": name,
            "return_1m": rets[0],
            "return_3m": rets[1] if len(rets) > 1 else None,
            "return_6m": rets[2] if len(rets) > 2 else None,
            "rs_raw": rs_raw,
            "data_quality": sum(1 for r in rets if r is not None),
        })

    rs_norm = _normalize_rs({s["etf"]: s["rs_raw"] for s in sectors})
    for s in sectors:
        s["rs_score"] = rs_norm.get(s["etf"], 50)

    sectors.sort(key=lambda x: -(x["rs_score"] or 0))

    # 2. Industry rankings within sectors
    industry_symbols = [s[0] for s in INDUSTRY_GROUP_ETFS]
    industry_returns = _sector_momentum_returns(db_query, industry_symbols)

    by_sector_industries: dict[str, list[dict]] = {}
    for etf, name, parent_sector in INDUSTRY_GROUP_ETFS:
        rets = industry_returns.get(etf.upper(), [None, None, None])
        rs_raw = _compute_rs_score(rets)
        item = {
            "etf": etf,
            "name": name,
            "return_1m": rets[0],
            "return_3m": rets[1] if len(rets) > 1 else None,
            "return_6m": rets[2] if len(rets) > 2 else None,
            "rs_raw": rs_raw,
            "data_quality": sum(1 for r in rets if r is not None),
        }
        by_sector_industries.setdefault(parent_sector, []).append(item)

    for parent in by_sector_industries:
        items = by_sector_industries[parent]
        irs = _normalize_rs({it["etf"]: it["rs_raw"] for it in items})
        for it in items:
            it["rs_score"] = irs.get(it["etf"], 50)
        items.sort(key=lambda x: -(x["rs_score"] or 0))

    industries = [
        {"sector": parent, "industries": items}
        for parent, items in sorted(by_sector_industries.items())
    ]

    # 3. Transition states from Aegis nightly briefs
    transitions: list[dict] = []
    try:
        rows = db_query(
            """SELECT symbol, thesis_status, escalation_reason, what_changed, needs_steph_review
               FROM aegis_portfolio_briefs
               WHERE run_id = (SELECT run_id FROM aegis_portfolio_briefs ORDER BY observed_at DESC LIMIT 1)
                 AND thesis_status IS NOT NULL
                 AND thesis_status != 'stable'
               ORDER BY
                 CASE thesis_status
                   WHEN 'triggered' THEN 0 WHEN 'danger' THEN 1 WHEN 'broken' THEN 2
                   WHEN 'warning' THEN 3 WHEN 'weakening' THEN 4 ELSE 5
                 END
               LIMIT 30""",
            fetch="all",
        ) or []
        for row in rows:
            transitions.append({
                "symbol": (row.get("symbol") or "").upper(),
                "thesis_status": row.get("thesis_status"),
                "escalation_reason": row.get("escalation_reason"),
                "what_changed": (row.get("what_changed") or "")[:160] or None,
                "needs_review": bool(row.get("needs_steph_review")),
            })
    except Exception:
        pass

    return {
        "computed_at": now.isoformat(),
        "sectors": sectors,
        "industries": industries,
        "transitions": transitions,
        "source": "market_quotes + aegis_portfolio_briefs",
    }


def get_rotation_ladders(db_query=None, max_age_s: float = DEFAULT_MAX_AGE_S) -> dict[str, Any]:
    """Return cached rotation ladders if fresh, else recompute from market_quotes.

    Args:
        db_query: a callable(sql, params, fetch="all"|"one") — required for recompute.
        max_age_s: max age before recompute (default 300s).
    """
    cached = None
    if SNAPSHOT_PATH.exists() and max_age_s > 0:
        try:
            cached = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
            age = time.time() - datetime.fromisoformat(cached["computed_at"]).timestamp()
            if age <= max_age_s:
                cached["_cache"] = {"hit": True, "age_seconds": round(age, 1)}
                return cached
        except Exception:
            cached = None

    if db_query is None:
        if cached:
            cached["_cache"] = {"hit": True, "age_seconds": 0, "stale": True}
            return cached
        return {"computed_at": "", "sectors": [], "industries": [], "transitions": [],
                "source": "unavailable"}

    fresh = _build(db_query)
    try:
        from lib.data_broker.atomic_json import atomic_write_json_soft
        atomic_write_json_soft(SNAPSHOT_PATH, fresh)
    except Exception:
        try:
            SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
            SNAPSHOT_PATH.write_text(json.dumps(fresh, indent=2, default=str), encoding="utf-8")
        except Exception:
            pass
    fresh["_cache"] = {"hit": False, "age_seconds": 0}
    return fresh


if __name__ == "__main__":
    # Allow standalone testing with a real db_query injected
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from db_adapter import _execute as _db_q

    def db_query(sql, params=None, fetch="all"):
        from db_adapter import USE_DB
        if not USE_DB:
            print("No DB available; using mock data")
            return None
        return _db_q(sql, params, fetch=fetch)

    print(json.dumps(get_rotation_ladders(db_query=db_query, max_age_s=0), indent=2, default=str))
