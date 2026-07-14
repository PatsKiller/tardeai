"""redeploy_capital_book — portfolio-wide capital-allocation book (advisory only).

The event modal answers "what about this sale?"; this module answers the
portfolio-level questions: which historical sales remain unresolved, what cash
is still unallocated by account, which plans are stale or partially deployed,
and what exposure gaps exist independent of any single sale.

All fill math uses production evidence only (environment='production' —
P0 audit 2026-07-13). Read-only: nothing here mutates events or plans.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from lib.redeploy_data_truth import _as_float

BOOK_VERSION = "capital_book_1.0.0"

# A plan whose quotes/creation are older than these bounds is flagged stale.
PLAN_STALE_DAYS = 5
QUOTE_STALE_MINUTES = 30
COMPLETED_DEPLOY_RATIO = 0.95


def _meta(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {}
    return raw or {}


def _age_days(d: Any) -> float | None:
    if not d:
        return None
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        except Exception:
            return None
    if isinstance(d, date) and not isinstance(d, datetime):
        d = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - d).total_seconds() / 86400.0, 2)


def _latest_quotes(cur, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    cur.execute(
        """SELECT DISTINCT ON (upper(symbol)) upper(symbol), price, fetched_at
           FROM market_quotes WHERE upper(symbol) = ANY(%s)
           ORDER BY upper(symbol), fetched_at DESC""",
        ([s.upper() for s in symbols],),
    )
    return {r[0]: {"price": _as_float(r[1]), "fetched_at": r[2]} for r in cur.fetchall()}


def _fills_by_event(cur, event_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not event_ids:
        return {}
    cur.execute(
        """SELECT deploy_event_id, ticker, stage, filled_shares, filled_price,
                  filled_dollars, filled_at, plan_archetype
           FROM redeploy_stage_fills
           WHERE deploy_event_id = ANY(%s) AND environment='production'
           ORDER BY filled_at""",
        (event_ids,),
    )
    cols = [d[0] for d in cur.description]
    out: dict[int, list[dict[str, Any]]] = {}
    for row in cur.fetchall():
        f = dict(zip(cols, row))
        out.setdefault(int(f["deploy_event_id"]), []).append(f)
    return out


def _quarantined_counts(cur, event_ids: list[int]) -> dict[int, int]:
    if not event_ids:
        return {}
    cur.execute(
        """SELECT deploy_event_id, count(*) FROM redeploy_stage_fills
           WHERE deploy_event_id = ANY(%s) AND environment <> 'production'
           GROUP BY deploy_event_id""",
        (event_ids,),
    )
    return {int(r[0]): int(r[1]) for r in cur.fetchall()}


def _latest_restoration(cur, event_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not event_ids:
        return {}
    cur.execute(
        """SELECT DISTINCT ON (deploy_event_id) deploy_event_id, restoration_metrics,
                  plan_archetype, snapshot_at
           FROM redeploy_monitor_snapshots
           WHERE deploy_event_id = ANY(%s)
           ORDER BY deploy_event_id, snapshot_at DESC""",
        (event_ids,),
    )
    out: dict[int, dict[str, Any]] = {}
    for eid, metrics, arch, at in cur.fetchall():
        out[int(eid)] = {"restoration": _meta(metrics), "plan_archetype": arch, "snapshot_at": at}
    return out


def _plan_summaries(cur, event_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Per event: plan count, latest version, best-confidence archetype, freshest quote age."""
    if not event_ids:
        return {}
    cur.execute(
        """SELECT p.deploy_event_id,
                  count(DISTINCT p.id) FILTER (WHERE p.version = lv.latest_version) AS plan_count,
                  count(DISTINCT p.id) AS draft_count_all_versions,
                  max(p.version) AS latest_version,
                  max(p.created_at) AS latest_plan_at,
                  -- staleness is judged on the LATEST version only — superseded v1 legs
                  -- must not keep a freshly recomputed plan set flagged stale forever
                  min(l.price_as_of) FILTER (WHERE p.version = lv.latest_version) AS oldest_quote_at,
                  bool_or(l.price_stale) FILTER (WHERE p.version = lv.latest_version) AS any_quote_stale
           FROM deploy_plans p
           JOIN (SELECT deploy_event_id, max(version) AS latest_version
                 FROM deploy_plans WHERE deploy_event_id = ANY(%s)
                 GROUP BY deploy_event_id) lv ON lv.deploy_event_id = p.deploy_event_id
           LEFT JOIN redeploy_plan_legs l ON l.deploy_plan_id = p.id
           WHERE p.deploy_event_id = ANY(%s)
           GROUP BY p.deploy_event_id""",
        (event_ids, event_ids),
    )
    cols = [d[0] for d in cur.description]
    return {int(r[0]): dict(zip(cols, r)) for r in cur.fetchall()}


def _locked_plan_labels(cur, plan_ids: list[int]) -> dict[int, dict[str, Any]]:
    ids = [p for p in plan_ids if p]
    if not ids:
        return {}
    cur.execute(
        """SELECT id, plan_archetype, version, confidence, oversight_status, created_at
           FROM deploy_plans WHERE id = ANY(%s)""",
        (ids,),
    )
    cols = [d[0] for d in cur.description]
    return {int(r[0]): dict(zip(cols, r)) for r in cur.fetchall()}


def build_capital_book(cur, *, limit: int = 500, include_dismissed: bool = True) -> dict[str, Any]:
    """One row per deploy event, portfolio-wide, with deployment/restoration truth."""
    from lib.redeploy_monitor import ensure_monitor_tables

    ensure_monitor_tables(cur)
    cur.execute(
        """SELECT id, event_key, symbol, account, sold_at, proceeds_usd, shares_sold,
                  realized_pnl, status, operator_status, reconciliation_status,
                  net_proceeds_usd, deployable_cash_usd, locked_plan_id,
                  locked_plan_version, plan_locked_at, dismiss_reason, source,
                  instrument_type, metadata, created_at, updated_at
           FROM deploy_events
           ORDER BY sold_at DESC, id DESC
           LIMIT %s""",
        (limit,),
    )
    cols = [d[0] for d in cur.description]
    events = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not include_dismissed:
        events = [e for e in events if e.get("status") != "dismissed"]

    event_ids = [int(e["id"]) for e in events]
    fills_map = _fills_by_event(cur, event_ids)
    quarantined = _quarantined_counts(cur, event_ids)
    restoration_map = _latest_restoration(cur, event_ids)
    plan_map = _plan_summaries(cur, event_ids)
    locked_map = _locked_plan_labels(cur, [e.get("locked_plan_id") for e in events])

    fill_symbols = sorted({f["ticker"].upper() for fl in fills_map.values() for f in fl})
    quotes = _latest_quotes(cur, fill_symbols)

    rows: list[dict[str, Any]] = []
    totals = {"proceeds": 0.0, "deployed": 0.0, "unallocated": 0.0, "open_events": 0}
    for e in events:
        eid = int(e["id"])
        meta = _meta(e.get("metadata"))
        fills = fills_map.get(eid, [])
        deployed = round(sum(_as_float(f["filled_dollars"]) for f in fills), 2)
        net = _as_float(e.get("net_proceeds_usd")) or _as_float(e.get("proceeds_usd"))
        deployable = _as_float(e.get("deployable_cash_usd")) or net
        remaining = round(max(0.0, deployable - deployed), 2)

        # Current market value + P/L of redeployed legs
        mv = 0.0
        pl_known = True
        for f in fills:
            q = quotes.get(str(f["ticker"]).upper())
            if q and q["price"] > 0:
                mv += q["price"] * int(f["filled_shares"] or 0)
            else:
                pl_known = False
        current_pl = round(mv - deployed, 2) if (fills and pl_known) else None

        resto = restoration_map.get(eid, {})
        restoration_pct = (resto.get("restoration") or {}).get("restoration_pct")

        plans = plan_map.get(eid, {})
        locked = locked_map.get(int(e["locked_plan_id"])) if e.get("locked_plan_id") else None
        plan_age = _age_days(plans.get("latest_plan_at"))
        quote_age_min = None
        if plans.get("oldest_quote_at"):
            age_d = _age_days(plans["oldest_quote_at"])
            quote_age_min = round(age_d * 1440, 1) if age_d is not None else None

        if e.get("status") == "dismissed":
            completion = "dismissed"
        elif deployable > 0 and deployed >= deployable * COMPLETED_DEPLOY_RATIO:
            completion = "completed"
        elif deployed > 0:
            completion = "partial"
        else:
            completion = "open"

        warnings: list[str] = []
        if completion in ("open", "partial"):
            if e.get("reconciliation_status") == "unsettled":
                warnings.append("settlement_unverified")
            if plan_age is not None and plan_age > PLAN_STALE_DAYS:
                warnings.append(f"plan_stale_{int(plan_age)}d")
            if plans.get("any_quote_stale") or (
                quote_age_min is not None and quote_age_min > QUOTE_STALE_MINUTES
            ):
                warnings.append("quotes_stale")
            if not plans.get("plan_count"):
                warnings.append("no_plans_generated")
        if quarantined.get(eid):
            warnings.append(f"quarantined_test_fills_{quarantined[eid]}")
        if not e.get("account"):
            warnings.append("missing_account_mapping")
        if fills and not e.get("locked_plan_id"):
            warnings.append("fills_without_locked_plan")

        rows.append({
            "event_id": eid,
            "event_key": e.get("event_key"),
            "symbol": e.get("symbol"),
            "instrument_type": e.get("instrument_type"),
            "account": e.get("account"),
            "sold_at": str(e.get("sold_at")) if e.get("sold_at") else None,
            "sale_age_days": _age_days(e.get("sold_at")),
            "proceeds_usd": _as_float(e.get("proceeds_usd")),
            "net_proceeds_usd": _as_float(e.get("net_proceeds_usd")) or None,
            "deployable_usd": round(deployable, 2),
            "settled": e.get("reconciliation_status") == "verified",
            "reconciliation_status": e.get("reconciliation_status"),
            "status": e.get("status"),
            "operator_status": e.get("operator_status"),
            "source": e.get("source"),
            "dismiss_reason": e.get("dismiss_reason"),
            "plan_selected": (
                f"{locked['plan_archetype']} v{locked['version']}" if locked else None
            ),
            "locked_plan_id": e.get("locked_plan_id"),
            "plan_count": int(plans.get("plan_count") or 0),
            "latest_plan_version": plans.get("latest_version"),
            "plan_age_days": plan_age,
            "quote_age_minutes": quote_age_min,
            "deployed_usd": deployed,
            "remaining_usd": remaining,
            "fill_count": len(fills),
            "restoration_pct": restoration_pct,
            "redeployed_market_value_usd": round(mv, 2) if fills and pl_known else None,
            "redeployed_pl_usd": current_pl,
            "monitoring_status": "active" if fills else ("none" if completion == "open" else "n/a"),
            "completion_status": completion,
            "warnings": warnings,
        })
        totals["proceeds"] += _as_float(e.get("proceeds_usd"))
        totals["deployed"] += deployed
        if completion in ("open", "partial"):
            totals["open_events"] += 1
            totals["unallocated"] += remaining

    return {
        "ok": True,
        "advisory_only": True,
        "book_version": BOOK_VERSION,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "totals": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in totals.items()},
        "rows": rows,
    }


def build_history(cur, *, days: int = 3650) -> dict[str, Any]:
    """All material SELL transactions vs deploy_events — finds unresolved proceeds."""
    from lib.sale_event_detector import event_key_for_row, load_sell_transactions

    sells = load_sell_transactions(days=days)
    cur.execute("SELECT event_key, id, status, operator_status FROM deploy_events")
    by_key = {r[0]: {"event_id": int(r[1]), "status": r[2], "operator_status": r[3]}
              for r in cur.fetchall()}

    rows = []
    counts = {"sells_found": len(sells), "matched": 0, "unmatched": 0,
              "open": 0, "dismissed": 0, "completed_or_reviewing": 0}
    for s in sells:
        key = event_key_for_row(s)
        match = by_key.get(key)
        if match:
            counts["matched"] += 1
            st = match["status"]
            if st == "open":
                counts["open"] += 1
            elif st == "dismissed":
                counts["dismissed"] += 1
            else:
                counts["completed_or_reviewing"] += 1
        else:
            counts["unmatched"] += 1
        rows.append({
            "event_key": key,
            "symbol": str(s.get("symbol") or "").upper(),
            "account": s.get("account"),
            "trade_date": str(s.get("trade_date"))[:10],
            "proceeds_usd": round(abs(_as_float(s.get("amount")) or
                                      _as_float(s.get("quantity")) * _as_float(s.get("price"))), 2),
            "matched_event_id": match["event_id"] if match else None,
            "event_status": match["status"] if match else None,
        })
    return {
        "ok": True,
        "advisory_only": True,
        "window_days": days,
        "counts": counts,
        "rows": rows,
    }


def build_capital_pools(cur) -> dict[str, Any]:
    """Unallocated capital by account: visible cash + open-event undeployed proceeds."""
    from lib.sale_event_detector import _cash_by_account

    cash = _cash_by_account()
    book = build_capital_book(cur, include_dismissed=False)
    pools: dict[str, dict[str, Any]] = {}
    for acct, amount in cash.items():
        pools[acct] = {"account": acct, "visible_cash_usd": round(amount, 2),
                       "open_event_remaining_usd": 0.0, "open_events": []}
    for row in book["rows"]:
        if row["completion_status"] not in ("open", "partial"):
            continue
        acct = row["account"] or "unknown"
        pool = pools.setdefault(acct, {"account": acct, "visible_cash_usd": 0.0,
                                       "open_event_remaining_usd": 0.0, "open_events": []})
        pool["open_event_remaining_usd"] = round(
            pool["open_event_remaining_usd"] + row["remaining_usd"], 2)
        pool["open_events"].append({
            "event_id": row["event_id"], "symbol": row["symbol"],
            "sold_at": row["sold_at"], "remaining_usd": row["remaining_usd"],
        })
    return {
        "ok": True,
        "advisory_only": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "pools": sorted(pools.values(), key=lambda p: -p["visible_cash_usd"]),
    }


def _portfolio_sector_weights() -> dict[str, Any]:
    from pathlib import Path

    from lib.redeploy_data_truth import STATE, _load_json, portfolio_totals

    hold = _load_json(Path(STATE) / "holdings.json", {}).get("holdings") or []
    sector_cache = _load_json(Path(STATE) / "sector_cache.json", {}) or {}
    manual = _load_json(Path(STATE) / "manual_sector_map.json", {}) or {}

    def sector_of(sym: str) -> str:
        s = sector_cache.get(sym) or manual.get(sym) or {}
        if isinstance(s, dict):
            return str(s.get("sector") or "Unknown")
        return str(s or "Unknown")

    weights: dict[str, float] = {}
    total = 0.0
    for h in hold:
        if h.get("is_cash"):
            continue
        mv = _as_float(h.get("market_value"))
        weights[sector_of(str(h.get("symbol") or "").upper())] = (
            weights.get(sector_of(str(h.get("symbol") or "").upper()), 0.0) + mv
        )
        total += mv
    rows = [
        {"sector": k, "market_value_usd": round(v, 2),
         "weight_pct": round(v / total * 100.0, 2) if total > 0 else 0.0}
        for k, v in sorted(weights.items(), key=lambda x: -x[1])
    ]
    return {"totals": portfolio_totals(), "sector_weights": rows}


def build_opportunity_set(cur) -> dict[str, Any]:
    """Portfolio-wide exposure gaps + deployable capital independent of any single sale."""
    ctx = _portfolio_sector_weights()
    book = build_capital_book(cur, include_dismissed=False)
    open_rows = [r for r in book["rows"] if r["completion_status"] in ("open", "partial")]
    return {
        "ok": True,
        "advisory_only": True,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "deployable_capital_usd": round(sum(r["remaining_usd"] for r in open_rows), 2),
        "open_events": [
            {"event_id": r["event_id"], "symbol": r["symbol"],
             "remaining_usd": r["remaining_usd"], "warnings": r["warnings"]}
            for r in open_rows
        ],
        "portfolio_context": ctx,
        "note": "candidate ranking comes from the candidate-research engine (Part C)",
    }
