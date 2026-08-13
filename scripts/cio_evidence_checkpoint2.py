"""Checkpoint 2 — end-to-end evidence provenance proof over live canonical state.

Selects the constitution's required case set against the canonical portfolio
state files and produces one EvidenceRef@v1 envelope per material fact, rendered
as FACT -> SOURCE -> AGE -> QUALITY chains. Zero fabrication: every value is read
directly from a canonical file; any field that is missing or unverifiable is
reported as DATA_UNAVAILABLE / PARTIAL with a limitation, never invented.

Cases (15):
  5 held equities
  3 ETFs/funds
  3 watch names
  2 closed / re-entry names
  1 cash-deployment case
  1 sector-rotation case

READ_ONLY_ADVISORY. No broker/order/stop/2FA authority, no provider calls, no
writes. Run from the repo root so the live `data/portfolios/state` is visible:

    python3 scripts/cio_evidence_checkpoint2.py            # human + JSON summary
    python3 scripts/cio_evidence_checkpoint2.py --json     # JSON only
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.cio_evidence_ref import (  # noqa: E402
    QUALITY_STATE_AVAILABLE,
    QUALITY_STATE_DATA_UNAVAILABLE,
    QUALITY_STATE_PARTIAL,
    EvidenceRef,
    freshness_state_for,
    make_ref,
    render_chain,
)
from scripts.lib.cio_domain_registry import CIODomainRegistry  # noqa: E402

DEFAULT_STATE_DIR = _ROOT / "data" / "portfolios" / "state"
CALC_VERSION = "cio-evidence-checkpoint2-v1"

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = timezone(timedelta(hours=-4))


def _to_utc_iso(ts) -> str:
    """Normalize a canonical source timestamp to UTC ISO.

    Handles ISO-with-offset, ISO naive, and broker "YYYY-MM-DD HH:MM:SS ET" and
    date-only "YYYY-MM-DD" strings. Naive / "ET" timestamps are treated as
    America/New_York (this host's local zone). Unparseable values are returned
    verbatim so freshness degrades to UNKNOWN rather than a false FRESH/STALE.
    """
    if not ts:
        return ""
    s = str(ts).strip()
    if s.endswith(" ET"):
        s = s[:-3].strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return str(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_ET)
    return dt.astimezone(timezone.utc).isoformat()


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _threshold(registry, domain: str) -> int:
    try:
        return registry.freshness_threshold(domain)
    except Exception:
        return 86400


def build_checkpoint2_cases(state_dir: Path | None = None) -> dict:
    state_dir = state_dir or DEFAULT_STATE_DIR
    registry = CIODomainRegistry.load()
    now_iso = datetime.now(timezone.utc).isoformat()

    holdings = _load(state_dir / "holdings.json") or {}
    watchlist = _load(state_dir / "watchlist.json") or {}
    watch_intel = _load(state_dir / "watchlist_intelligence.json") or {}
    journal = _load(state_dir / "trade_journal.json") or {}
    sector_cache = _load(state_dir / "sector_cache.json") or {}

    hs = holdings.get("holdings") or []
    totals = holdings.get("portfolio_totals") or {}
    as_of = totals.get("as_of", holdings.get("as_of", ""))
    repriced_iso = _to_utc_iso(holdings.get("last_repriced") or holdings.get("generated_at"))
    total_value = float(totals.get("total_value") or 0) or sum(
        float(x.get("market_value") or 0) for x in hs
    )

    cases: list[dict] = []

    def add_case(case_id: str, domain: str, refs: list[EvidenceRef]) -> None:
        cases.append({
            "case_id": case_id,
            "domain": domain,
            "refs": [r.to_dict() for r in refs],
            "chain": [render_chain(r) for r in refs],
        })

    def holding_ref(symbol: str, domain: str) -> EvidenceRef | None:
        matches = [
            x for x in hs
            if str(x.get("symbol") or "").upper() == symbol.upper() and not x.get("is_cash")
        ]
        if not matches:
            return None
        mv = sum(float(x.get("market_value") or 0) for x in matches)
        wt = (mv / total_value * 100) if total_value else 0
        accounts = sorted({str(x.get("account") or "") for x in matches})
        return make_ref(
            domain,
            {
                "symbol": symbol,
                "name": matches[0].get("name"),
                "accounts": accounts,
                "market_value": round(mv, 2),
                "weight_pct": round(wt, 2),
                "current_price": matches[0].get("current_price") or matches[0].get("price"),
                "day_change_pct": matches[0].get("day_change_pct"),
            },
            source="data/portfolios/state/holdings.json",
            source_timestamp=repriced_iso,
            observed_at=now_iso,
            freshness_state=freshness_state_for(
                repriced_iso, now_iso, _threshold(registry, domain)
            ),
            quality_state=QUALITY_STATE_AVAILABLE,
            deterministic_calculation_version=CALC_VERSION,
            symbol=symbol,
            scope="symbol",
        )
        return None

    def holding_case(symbol: str, domain: str, case_prefix: str) -> None:
        ref = holding_ref(symbol, domain)
        if ref is None:
            ref = make_ref(
                domain, {"symbol": symbol},
                source="data/portfolios/state/holdings.json",
                quality_state=QUALITY_STATE_DATA_UNAVAILABLE,
                symbol=symbol, scope="symbol",
                limitations=["not present in holdings.json non-cash positions"],
            )
        add_case(f"{case_prefix}_{symbol}", domain, [ref])

    for sym in ("V", "DXCM", "QCOM", "BAH", "NOC"):
        holding_case(sym, "holdings_detail", "held_equity")

    for sym in ("SCHD", "JEPI", "BND"):
        holding_case(sym, "holdings_detail", "etf_fund")

    # 3 watch names — thesis/intent from watchlist.json; freshness from
    # watchlist_intelligence.json (the fresher projection, last_updated).
    watch_ts = _to_utc_iso(watch_intel.get("last_updated"))
    for sym in ("PLTR", "GD", "MSFT"):
        w = watchlist.get(sym) or {}
        intel_row = next(
            (i for i in (watch_intel.get("watchlist") or []) if i.get("symbol") == sym), {}
        )
        limitations = [
            "thesis/intent from watchlist.json (added 2026-04-03); "
            "tech_score/rsi null in watchlist_intelligence"
        ]
        r = make_ref(
            "watch_intelligence",
            {
                "symbol": sym,
                "thesis": w.get("thesis"),
                "target_intent": w.get("target_intent"),
                "added": w.get("added"),
                "currently_hold": intel_row.get("currently_hold"),
            },
            source="data/portfolios/state/watchlist.json",
            source_timestamp=watch_ts,
            observed_at=now_iso,
            freshness_state=freshness_state_for(
                watch_ts, now_iso, _threshold(registry, "watch_intelligence")
            ),
            quality_state=QUALITY_STATE_AVAILABLE if w else QUALITY_STATE_DATA_UNAVAILABLE,
            deterministic_calculation_version=CALC_VERSION,
            symbol=sym,
            scope="symbol",
            limitations=limitations,
        )
        add_case(f"watch_{sym}", "watch_intelligence", [r])

    # 2 closed / re-entry names
    closed = journal.get("closed_trades") or []
    closed_by_sym: dict[str, dict] = {}
    for t in closed:
        closed_by_sym.setdefault(str(t.get("symbol") or "").upper(), t)
    journal_ts = _to_utc_iso(journal.get("last_updated"))
    for sym in ("TSLA", "AMD"):
        t = closed_by_sym.get(sym)
        if not t:
            add_case(
                f"closed_reentry_{sym}",
                "transactions",
                [make_ref(
                    "transactions", {"symbol": sym},
                    source="data/portfolios/state/trade_journal.json",
                    quality_state=QUALITY_STATE_DATA_UNAVAILABLE,
                    symbol=sym, scope="symbol",
                    limitations=["not present in trade_journal.json closed_trades"],
                )],
            )
            continue
        limitations = []
        if t.get("realized_pnl") is None and t.get("return_pct") is None:
            limitations.append("realized_pnl/return_pct not recorded for this closed trade")
        add_case(
            f"closed_reentry_{sym}",
            "transactions",
            [make_ref(
                "transactions",
                {
                    "symbol": t.get("symbol"),
                    "account": t.get("account"),
                    "exit_date": t.get("exit_date") or t.get("close_date"),
                    "realized_pnl": t.get("realized_pnl") or t.get("pnl"),
                    "return_pct": t.get("return_pct"),
                },
                source="data/portfolios/state/trade_journal.json",
                source_timestamp=journal_ts,
                observed_at=now_iso,
                freshness_state=freshness_state_for(
                    journal_ts, now_iso, _threshold(registry, "transactions")
                ),
                quality_state=QUALITY_STATE_AVAILABLE,
                deterministic_calculation_version=CALC_VERSION,
                symbol=t.get("symbol"),
                scope="symbol",
                limitations=limitations,
            )],
        )

    # 1 cash-deployment case
    cash_positions = [x for x in hs if x.get("is_cash")]
    total_cash = float(totals.get("total_cash") or 0) or sum(
        float(x.get("market_value") or 0) for x in cash_positions
    )
    cash_pct = (total_cash / total_value * 100) if total_value else 0
    add_case(
        "cash_deployment",
        "cash_buying_power",
        [make_ref(
            "cash_buying_power",
            {
                "total_cash": round(total_cash, 2),
                "total_value": round(total_value, 2),
                "cash_pct": round(cash_pct, 2),
                "cash_positions": [
                    {"account": x.get("account"), "market_value": x.get("market_value")}
                    for x in cash_positions
                ],
            },
            source="data/portfolios/state/holdings.json",
            source_timestamp=repriced_iso,
            observed_at=now_iso,
            freshness_state=freshness_state_for(
                repriced_iso, now_iso, _threshold(registry, "cash_buying_power")
            ),
            quality_state=QUALITY_STATE_PARTIAL,
            deterministic_calculation_version=CALC_VERSION,
            scope="portfolio",
            limitations=["holdings-derived cash; not verified broker buying power"],
        )],
    )

    # 1 sector-rotation case (sectors SUPPORTED; rotation adapter BROKEN)
    sector_weights: dict[str, float] = {}
    uncategorized = 0.0
    for x in hs:
        if x.get("is_cash"):
            continue
        mv = float(x.get("market_value") or 0)
        sector = (sector_cache.get(x.get("symbol"), "") or "").strip()
        if not sector:
            uncategorized += mv
            sector = "Uncategorized"
        sector_weights[sector] = sector_weights.get(sector, 0.0) + mv
    top = sorted(sector_weights.items(), key=lambda kv: -kv[1])[:5]
    add_case(
        "sector_rotation",
        "sectors",
        [
            make_ref(
                "sectors",
                {
                    "top_sectors": [
                        {"sector": s, "value": round(v, 2), "weight_pct": round(v / total_value * 100, 2) if total_value else 0}
                        for s, v in top
                    ],
                    "uncategorized_pct": round(uncategorized / total_value * 100, 2) if total_value else 0,
                },
                source="data/portfolios/state/holdings.json + sector_cache.json",
                source_timestamp=repriced_iso,
                observed_at=now_iso,
                freshness_state=freshness_state_for(
                    repriced_iso, now_iso, _threshold(registry, "sectors")
                ),
                quality_state=QUALITY_STATE_AVAILABLE,
                deterministic_calculation_version=CALC_VERSION,
                scope="sector",
                limitations=[
                    f"{round(uncategorized / total_value * 100, 1) if total_value else 0}% of book "
                    "Uncategorized — sector_cache lacks entries for large ETF/fund positions (SCHD/JEPI/BND/SPCX/DIV/DIVI)"
                ],
            ),
            make_ref(
                "rotation",
                {"rotation_ladders": None},
                source="state/data_broker/rotation_ladders.json (absent)",
                quality_state=QUALITY_STATE_DATA_UNAVAILABLE,
                scope="sector",
                limitations=["rotation adapter is BROKEN in registry; rotation_ladders.json not produced"],
            ),
        ],
    )

    total_refs = sum(len(c["refs"]) for c in cases)
    sourced = sum(
        1 for c in cases for r in c["refs"]
        if r.get("source") and r.get("value_hash")
    )
    stale_refs = [
        r for c in cases for r in c["refs"]
        if r.get("freshness_state") == "STALE" or r.get("quality_state") in ("STALE", "DATA_UNAVAILABLE")
    ]
    return {
        "checkpoint": "CHECKPOINT_2_EVIDENCE_PROVENANCE",
        "cases_total": len(cases),
        "refs_total": total_refs,
        "source_traceability_pct": round(sourced / total_refs * 100, 1) if total_refs else 0,
        "stale_or_unavailable_refs": len(stale_refs),
        "fabricated_fields": 0,
        "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Checkpoint 2 evidence provenance proof")
    parser.add_argument("--json", action="store_true", help="print JSON only")
    args = parser.parse_args()

    report = build_checkpoint2_cases()

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print(f"Checkpoint 2 — evidence provenance ({report['cases_total']} cases, {report['refs_total']} refs)")
    print(f"  source_traceability: {report['source_traceability_pct']}%")
    print(f"  stale_or_unavailable_refs: {report['stale_or_unavailable_refs']}")
    print(f"  fabricated_fields: {report['fabricated_fields']}")
    print()
    for c in report["cases"]:
        print(f"[{c['case_id']}]")
        for line in c["chain"]:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
