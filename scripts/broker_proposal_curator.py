#!/usr/bin/env python3
"""broker_proposal_curator.py — 30m trading-hours broker queue curation.

For each Schwab/Fidelity queue row:
  1. Refresh live quotes (batch Schwab) and persist prices
  2. Recompute support / resistance levels
  3. Re-validate strategy fit (classifier must still qualify proposal strategy)
  4. Check thesis criteria (fresh price, zone, R:R, stop)
  5. Run hygiene sweep (expire/reject stale rows)
  6. Stamp last_curated_at + curation_snapshot on surviving rows

  python3 scripts/broker_proposal_curator.py [--apply]
  python3 scripts/broker_proposal_curator.py --apply --symbol RTX
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

MIN_LIVE_RR = float(os.getenv("BROKER_CURATOR_MIN_RR", "2"))
CURATOR_STATE_PATH = PROJECT_ROOT / "data" / "runtime" / "broker_curator_last.json"


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _ensure_schema(conn) -> None:
    mig = PROJECT_ROOT / "migrations" / "20260623_broker_proposal_curation.sql"
    if not mig.exists():
        return
    try:
        cur = conn.cursor()
        cur.execute(mig.read_text(encoding="utf-8"))
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _log_event(conn, proposal_id: int, symbol: str, event_type: str, payload: dict) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO proposal_event_log (proposal_id, symbol, event_type, event_source, payload)
               VALUES (%s, %s, %s, 'broker_curator', %s::jsonb)""",
            (proposal_id, symbol, event_type, json.dumps(payload, default=str)),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _compute_support_resistance(conn, symbol: str, live_price: float | None) -> dict:
    """Support/resistance from ticker_prices; fallback to watchlist_strategy_cards."""
    out = {"support_1": None, "support_2": None, "resistance_1": None, "resistance_2": None, "source": None}
    sym = str(symbol or "").upper()
    if not sym:
        return out
    try:
        from materialize_watchlist_strategy_cards import compute_support_resistance
        sr = compute_support_resistance(conn, sym)
        out["support_1"] = sr.get("support")
        out["resistance_1"] = sr.get("resistance")
        out["support_2"] = sr.get("low_50")
        out["resistance_2"] = sr.get("high_50")
        out["source"] = "ticker_prices_20d"
    except Exception:
        pass
    if out["support_1"] is None:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT support, resistance FROM watchlist_strategy_cards WHERE symbol=%s LIMIT 1",
                (sym,),
            )
            row = cur.fetchone()
            if row:
                out["support_1"], out["resistance_1"] = row[0], row[1]
                out["source"] = "watchlist_strategy_cards"
        except Exception:
            pass
    if live_price and out["support_1"] is None:
        out["support_1"] = round(live_price * 0.95, 2)
        out["resistance_1"] = round(live_price * 1.05, 2)
        out["source"] = "price_estimate"
    return out


def _strategy_still_valid(symbol: str, strategy_id: str, conn) -> dict:
    """Re-run classifier; proposal strategy must still qualify."""
    sym = str(symbol or "").upper()
    sid = str(strategy_id or "").strip()
    try:
        import directive_promotion as dp
        from finviz_enrichment import get_enriched
        tech = get_enriched(sym, project_root=str(PROJECT_ROOT)) or {}
        if not tech and os.getenv("BROKER_CURATOR_ENRICH", "").lower() in ("1", "true", "yes"):
            tech = dp.enrich_symbol_on_demand(sym, conn)
        if not tech:
            return {"ok": True, "reason": "no_tech_cache", "qualified": [], "strategy_match": True}
        qualified = [q[0] for q in dp.classify_tradeable(sym, tech)]
        match = sid in qualified if sid else bool(qualified)
        return {
            "ok": match,
            "reason": None if match else "strategy_no_longer_qualifies",
            "qualified": qualified[:8],
            "strategy_match": match,
            "primary_strategy": sid,
        }
    except Exception as e:
        return {"ok": True, "reason": f"classifier_deferred:{str(e)[:80]}", "qualified": [], "strategy_match": True}


def _criteria_from_row(row: dict) -> dict:
    from broker_thesis_validity import attach_thesis_validity
    attach_thesis_validity(row)
    tv = row.get("thesis_validity") or {}
    zone = str(tv.get("zone_status") or "unknown").lower()
    stale = bool(row.get("price_stale"))
    live_rr = tv.get("current_rr")
    reasons: list[str] = []
    status = "fresh"
    if stale:
        status = "stale"
        reasons.append("price_stale")
    elif zone in ("invalid", "stale_price"):
        status = "criteria_fail"
        reasons.append(f"zone_{zone}")
    elif zone == "at_risk":
        status = "warn"
        reasons.append("zone_at_risk")
    elif zone == "approaching":
        status = "warn"
        reasons.append("zone_approaching")
    if live_rr is not None and float(live_rr) < MIN_LIVE_RR:
        if status == "fresh":
            status = "warn"
        reasons.append(f"live_rr_below_{MIN_LIVE_RR}")
    return {
        "status": status,
        "zone_status": zone,
        "price_stale": stale,
        "live_rr": live_rr,
        "planned_rr": tv.get("planned_rr") or row.get("proposed_rr"),
        "drift_pct": tv.get("drift_pct") or row.get("price_drift_pct"),
        "actionable": bool(tv.get("actionable")),
        "reasons": reasons,
    }


def _upsert_tech_levels(conn, proposal_id: int, symbol: str, levels: dict, live_price: float | None) -> None:
    """Lightweight support/resistance row on proposal_technical_snapshots."""
    if not proposal_id:
        return
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO proposal_technical_snapshots
                   (proposal_id, symbol, timeframe, support_1, support_2, resistance_1, resistance_2,
                    source, computed_at)
               VALUES (%s, %s, 'daily', %s, %s, %s, %s, 'broker_curator', NOW())""",
            (
                proposal_id,
                symbol,
                levels.get("support_1"),
                levels.get("support_2"),
                levels.get("resistance_1"),
                levels.get("resistance_2"),
            ),
        )
        if live_price is not None:
            cur.execute(
                """UPDATE paper_trade_proposals SET technical_context = COALESCE(technical_context, '{}'::jsonb)
                       || %s::jsonb WHERE id=%s""",
                (
                    json.dumps(
                        {
                            "support_1": levels.get("support_1"),
                            "resistance_1": levels.get("resistance_1"),
                            "support_2": levels.get("support_2"),
                            "resistance_2": levels.get("resistance_2"),
                            "levels_source": levels.get("source"),
                            "levels_price": live_price,
                        }
                    ),
                    proposal_id,
                ),
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _update_price(conn, row: dict, quote: dict) -> bool:
    pid = int(row.get("id") or 0)
    if not pid or quote.get("last") is None:
        return False
    last = float(quote["last"])
    entry = float(row.get("proposed_entry") or 0)
    provider = str(quote.get("provider") or "schwab")  # hardcode-ok fallback when provider missing
    drift_pct = round((last - entry) / entry * 100, 2) if entry > 0 else None
    entry_zone = row.get("entry_zone_status")
    try:
        from proposal_lifecycle import evaluate_lifecycle_status
        lc = evaluate_lifecycle_status(
            str(row.get("strategy_id") or "momentum_scalp"),
            last,
            entry,
            row.get("created_at"),
            row.get("expires_at"),
        )
        entry_zone = lc.get("entry_zone_status") or entry_zone
        drift_pct = lc.get("price_drift_pct") or drift_pct
    except Exception:
        pass
    cur = conn.cursor()
    cur.execute(
        """UPDATE paper_trade_proposals
           SET current_price=%s, price_drift_pct=%s, entry_zone_status=%s,
               last_price_source=%s, last_price_checked_at=NOW(), updated_at=NOW()
           WHERE id=%s""",
        (last, drift_pct, entry_zone, provider, pid),
    )
    conn.commit()
    row["current_price"] = last
    row["price_drift_pct"] = drift_pct
    row["entry_zone_status"] = entry_zone
    return True


def _persist_curation(conn, proposal_id: int, status: str, snapshot: dict) -> None:
    try:
        cur = conn.cursor()
    except Exception:
        conn = _conn()
        cur = conn.cursor()
    cur.execute(
        """UPDATE paper_trade_proposals
           SET last_curated_at=NOW(), curation_status=%s, curation_snapshot=%s::jsonb, updated_at=NOW()
           WHERE id=%s""",
        (status, json.dumps(snapshot, default=str), proposal_id),
    )
    conn.commit()


def curate_broker_queue(*, apply: bool = False, symbol_filter: str | None = None) -> dict:
    from broker_proposal_autocal import apply_live_quotes_to_rows, batch_live_quotes
    from broker_queue_hygiene import classify_broker_queue_row, fetch_broker_queue_rows, find_active_symbol_proposal, _apply_hygiene

    conn = _conn()
    _ensure_schema(conn)
    now = datetime.now(timezone.utc)
    rows = fetch_broker_queue_rows()
    if symbol_filter:
        sf = symbol_filter.upper()
        rows = [r for r in rows if str(r.get("symbol") or "").upper() == sf]

    # 1) Refresh quotes into DB for queue rows in this pass
    price_result = {"skipped": True}
    if apply and rows:
        qmap_pre = batch_live_quotes([r.get("symbol") for r in rows])
        updated_px = 0
        for row in rows:
            sym = str(row.get("symbol") or "").upper()
            q = qmap_pre.get(sym)
            if q and _update_price(conn, row, q):
                updated_px += 1
        price_result = {"updated": updated_px, "checked": len(rows)}

    syms = [r.get("symbol") for r in rows]
    qmap = batch_live_quotes(syms) if syms else {}
    enriched = apply_live_quotes_to_rows(rows, qmap)

    curated = expired = rejected = skipped = 0
    details: list[dict] = []

    symbol_newest: dict[str, dict] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        active = find_active_symbol_proposal(sym)
        if active:
            symbol_newest[sym] = active

    for raw, live_row in zip(rows, enriched):
        pid = int(raw.get("id") or 0)
        sym = str(raw.get("symbol") or "").upper()
        strat = str(raw.get("strategy_id") or "")
        entry = {
            "proposal_id": pid,
            "symbol": sym,
            "strategy_id": strat,
            "curation_status": None,
            "action": "curate",
        }

        # 2) Hygiene — expire/reject before spending enrichment on dead rows
        clf = classify_broker_queue_row(live_row, now=now, newer_same_symbol=symbol_newest.get(sym))
        if clf.get("action") != "keep":
            entry["action"] = clf["action"]
            entry["hygiene_reasons"] = clf.get("reasons")
            if apply:
                if _apply_hygiene(clf, dry_run=False):
                    if clf["action"] == "expire":
                        expired += 1
                    else:
                        rejected += 1
                    _log_event(conn, pid, sym, f"curator_{clf['action']}", clf)
            else:
                if clf["action"] == "expire":
                    expired += 1
                else:
                    rejected += 1
            entry["curation_status"] = clf["action"]
            details.append(entry)
            continue

        live_px = live_row.get("quote_last") or live_row.get("current_price")
        levels = _compute_support_resistance(conn, sym, float(live_px) if live_px is not None else None)
        strat_check = _strategy_still_valid(sym, strat, conn)
        criteria = _criteria_from_row(live_row)

        status = criteria["status"]
        if not strat_check.get("strategy_match") and strat_check.get("reason") != "classifier_deferred":
            status = "strategy_changed"
        elif criteria["status"] == "fresh" and strat_check.get("reason") == "classifier_deferred":
            status = "fresh"

        snapshot = {
            "curated_at": now.isoformat()[:19],
            "price": {
                "last": live_px,
                "provider": live_row.get("quote_provider"),
                "refreshed_at": live_row.get("refreshed_at"),
                "stale": criteria.get("price_stale"),
            },
            "levels": levels,
            "strategy": strat_check,
            "criteria": criteria,
            "thesis_validity": live_row.get("thesis_validity"),
        }
        entry["curation_status"] = status
        entry["levels"] = levels
        entry["criteria"] = criteria
        entry["strategy_match"] = strat_check.get("strategy_match")

        if apply:
            _upsert_tech_levels(conn, pid, sym, levels, float(live_px) if live_px is not None else None)
            _persist_curation(conn, pid, status, snapshot)
            _log_event(conn, pid, sym, "curator_pass" if status == "fresh" else f"curator_{status}", snapshot)
            curated += 1
        else:
            curated += 1
        details.append(entry)

    out = {
        "ok": True,
        "mode": "APPLIED" if apply else "DRY-RUN",
        "ran_at": now.isoformat()[:19],
        "checked": len(rows),
        "curated": curated,
        "expired": expired,
        "rejected": rejected,
        "skipped": skipped,
        "price_refresh": price_result,
        "min_live_rr": MIN_LIVE_RR,
        "details": details[:40],
    }
    if apply:
        try:
            from broker_proposal_autocal import _clear_broker_list_cache
            _clear_broker_list_cache()
        except Exception:
            pass
        try:
            CURATOR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CURATOR_STATE_PATH.write_text(
                json.dumps(
                    {
                        "ts": now.timestamp(),
                        "checked": len(rows),
                        "curated": curated,
                        "expired": expired,
                        "rejected": rejected,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass
    conn.close()
    return out


def main():
    ap = argparse.ArgumentParser(description="Broker proposal curator — 30m trading-hours pass")
    ap.add_argument("--apply", action="store_true", help="Write DB updates (default dry-run)")
    ap.add_argument("--symbol", help="Curate single symbol only")
    args = ap.parse_args()
    result = curate_broker_queue(apply=args.apply, symbol_filter=args.symbol)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())