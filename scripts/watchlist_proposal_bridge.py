#!/usr/bin/env python3
"""watchlist_proposal_bridge.py — Surface watchlist BUY/STRONG_BUY rows as tagged broker proposals.

Gap this closes: watchlist_research_cards / watchlist_final_synthesis can rate a name BUY or
STRONG_BUY, but nothing copied that into paper_trade_proposals — so Broker Proposals stayed empty
while 500+ buy-rated watchlist names existed (origin=watchlist count was 0).

Behavior:
  • Upsert paper_trade_proposals with origin='watchlist', intended_broker=schwab (configurable)
  • Tag discovery_source + sizing_basis.watchlist_rating for UI
  • Refresh entry/stop/target from watchlist_entry_plans while rating stays buy+
  • Reject watchlist-origin rows when rating drops below BUY
  • Skip symbols that already have a non-watchlist active proposal (screener wins)

Usage:
    .venv/bin/python scripts/watchlist_proposal_bridge.py --dry-run
    .venv/bin/python scripts/watchlist_proposal_bridge.py --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger("watchlist_proposal_bridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

BUY_RATINGS = frozenset({"buy", "strong_buy", "add", "add_on_pullback"})
DEFAULT_STRATEGY = "momentum_scalp"
DEFAULT_BROKER = os.getenv("WATCHLIST_BROKER_ACCOUNT", "schwab_taxable")
MAX_NEW_PER_RUN = int(os.getenv("WATCHLIST_PROPOSAL_MAX_NEW", "40"))
ACTIVE_STATUSES = ("PENDING", "APPROVED", "MODIFIED", "APPROVED_FOR_PAPER_TEST", "BROKER_SUBMITTED")


def _get_conn():
    from db_adapter import _get_conn
    return _get_conn()


def _f(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v


def _normalize_rating(raw: str | None) -> str | None:
    if not raw:
        return None
    r = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if r in BUY_RATINGS:
        return r
    if r in ("strongbuy",):
        return "strong_buy"
    return r if r in ("hold", "sell", "strong_sell", "ignore", "avoid") else None


def _is_buy_plus(rating: str | None) -> bool:
    return _normalize_rating(rating) in BUY_RATINGS


def _best_rating(card_rec, synth_rec, analyst_rec) -> tuple[str | None, str]:
    """Pick strongest buy-side rating + source label."""
    candidates = []
    for rec, src in ((card_rec, "research_card"), (synth_rec, "cio_synthesis"), (analyst_rec, "pro_analyst")):
        norm = _normalize_rating(rec)
        if _is_buy_plus(norm):
            rank = 2 if norm == "strong_buy" else 1
            candidates.append((rank, norm, src))
    if not candidates:
        return None, ""
    candidates.sort(reverse=True)
    return candidates[0][1], candidates[0][2]


def _fetch_buy_candidates(cur) -> list[dict]:
    cur.execute(
        """SELECT wi.symbol, wi.status AS wl_status, wi.hermes_composite_score, wi.hermes_rank,
                  wi.trend, wi.source AS wl_source,
                  rc.latest_recommendation AS card_rec,
                  fs.recommendation AS synth_rec,
                  ad.recommendation_key AS analyst_rec,
                  ep.limit_price, ep.entry_zone_low, ep.entry_zone_high,
                  ep.proposal_tag AS entry_tag, ep.urgency AS entry_urgency,
                  wsc.strategy_type AS wl_strategy,
                  wsc.ideal_entry AS card_entry, wsc.stop_loss AS card_stop, wsc.target_price AS card_target,
                  wsc.support AS card_support, wsc.resistance AS card_resistance, wsc.risk_reward AS card_rr
           FROM watchlist_items wi
           LEFT JOIN watchlist_research_cards rc ON rc.symbol = wi.symbol
           LEFT JOIN watchlist_final_synthesis fs ON UPPER(fs.symbol) = UPPER(wi.symbol)
           LEFT JOIN LATERAL (
               SELECT payload->>'recommendation_key' AS recommendation_key
               FROM analyst_data_history
               WHERE UPPER(symbol) = UPPER(wi.symbol)
               ORDER BY as_of DESC NULLS LAST LIMIT 1
           ) ad ON true
           LEFT JOIN LATERAL (
               SELECT limit_price, entry_zone_low, entry_zone_high, proposal_tag, urgency
               FROM watchlist_entry_plans WHERE symbol = wi.symbol
               ORDER BY created_at DESC LIMIT 1
           ) ep ON true
           LEFT JOIN LATERAL (
               SELECT strategy_type, ideal_entry, stop_loss, target_price,
                      support, resistance, risk_reward
               FROM watchlist_strategy_cards
               WHERE symbol = wi.symbol ORDER BY updated_at DESC NULLS LAST LIMIT 1
           ) wsc ON true
           WHERE wi.status <> 'removed'
             AND wi.symbol ~ '^[A-Z]{1,5}$'
           ORDER BY wi.hermes_composite_score DESC NULLS LAST, wi.symbol"""
    )
    cols = [d[0] for d in cur.description]
    out = []
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        rating, src = _best_rating(d.get("card_rec"), d.get("synth_rec"), d.get("analyst_rec"))
        if not rating:
            continue
        d["watchlist_rating"] = rating
        d["rating_source"] = src
        out.append(d)
    return out


def _active_proposal(cur, symbol: str) -> dict | None:
    cur.execute(
        """SELECT id, origin, status, intended_broker, target_account, proposed_entry,
                  proposed_stop, proposed_target1, proposed_shares
           FROM paper_trade_proposals
           WHERE symbol = %s AND status = ANY(%s)
           ORDER BY CASE WHEN origin = 'watchlist' THEN 0 ELSE 1 END, created_at DESC
           LIMIT 1""",
        (symbol.upper(), list(ACTIVE_STATUSES)),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def _derive_levels(c: dict, quote_cache: dict | None = None) -> tuple[float, float, float, dict, str] | None:
    """Entry / stop / target from authoritative plan only — no generic 2R gambling geometry."""
    import broker_trade_plan_gate as btpg

    sym = str(c.get("symbol") or "").upper()
    conn = _get_conn()
    resolved = btpg.resolve_authoritative_levels(conn, sym, candidate=c, quote_cache=quote_cache)
    if not resolved:
        log.info(f"skip {sym}: no authoritative trade plan (trade_plans/card/confluence required)")
        return None
    return (
        resolved["entry"],
        resolved["stop"],
        resolved["target"],
        resolved["exit_rationale"],
        str(resolved.get("plan_source") or "authoritative"),
    )


def _size_shares(entry: float, stop: float) -> int:
    """Risk-based share count — avoids broker API calls that can close the DB connection."""
    risk_ps = max(0.01, entry - stop)
    max_risk = float(os.getenv("WATCHLIST_DEFAULT_RISK_USD", "150"))
    cap_shares = int(os.getenv("WATCHLIST_DEFAULT_MAX_SHARES", "500"))
    return max(1, min(cap_shares, int(max_risk / risk_ps)))


def _reconcile_sleeve_strategy_ids(cur, *, dry_run: bool) -> int:
    """Fix watchlist proposals still tagged with sleeve labels (income, core_holding)."""
    import broker_strategy_resolver as bsr

    cur.execute(
        """SELECT id, symbol, strategy_id, sizing_basis
           FROM paper_trade_proposals
           WHERE origin = 'watchlist'
             AND status = ANY(%s)
             AND lower(strategy_id) = ANY(%s)""",
        (list(ACTIVE_STATUSES), list(bsr.WATCHLIST_SLEEVES)),
    )
    cols = [d[0] for d in cur.description]
    n = 0
    for row in cur.fetchall():
        d = dict(zip(cols, row))
        sym = str(d.get("symbol") or "").upper()
        sleeve = str(d.get("strategy_id") or "")
        resolved = bsr.resolve_executable_strategy(sym, sleeve)
        new_sid = resolved["strategy_id"]
        if not new_sid or new_sid == sleeve:
            continue
        n += 1
        if dry_run:
            continue
        basis = d.get("sizing_basis")
        if isinstance(basis, str):
            try:
                basis = json.loads(basis)
            except Exception:
                basis = {}
        if not isinstance(basis, dict):
            basis = {}
        basis.update({
            "watchlist_sleeve": sleeve,
            "strategy_resolve_source": resolved.get("resolve_source"),
            "classified_strategy": resolved.get("classified_strategy"),
            "strategy_reconciled_at": datetime.now(timezone.utc).isoformat(),
        })
        cur.execute(
            """UPDATE paper_trade_proposals
               SET strategy_id=%s,
                   sizing_basis=COALESCE(sizing_basis, '{}'::jsonb) || %s::jsonb,
                   updated_at=NOW()
               WHERE id=%s""",
            (new_sid, json.dumps(basis), int(d["id"])),
        )
        log.info(f"reconciled #{d['id']} {sym} {sleeve} → {new_sid}")
    return n


def _dedupe_watchlist_proposals(cur, *, dry_run: bool) -> int:
    """Reject older duplicate watchlist PENDING rows for the same symbol."""
    cur.execute(
        """SELECT symbol, array_agg(id ORDER BY created_at DESC) AS ids
           FROM paper_trade_proposals
           WHERE origin = 'watchlist' AND status = ANY(%s)
           GROUP BY symbol HAVING count(*) > 1""",
        (list(ACTIVE_STATUSES),),
    )
    n = 0
    for sym, ids in cur.fetchall():
        keep_id = int(ids[0])
        for dup_id in ids[1:]:
            n += 1
            if not dry_run:
                cur.execute(
                    """UPDATE paper_trade_proposals
                       SET status='REJECTED', lifecycle_status='EXPIRED',
                           rejection_reason='duplicate_watchlist_proposal',
                           updated_at=NOW()
                       WHERE id=%s AND status = ANY(%s)""",
                    (int(dup_id), list(ACTIVE_STATUSES)),
                )
                log.info(f"deduped watchlist #{dup_id} {sym} — keep #{keep_id}")
    return n


def _expire_stale_watchlist(cur, valid_symbols: set[str], *, dry_run: bool) -> int:
    cur.execute(
        """SELECT id, symbol FROM paper_trade_proposals
           WHERE origin = 'watchlist'
             AND status = ANY(%s)""",
        (list(ACTIVE_STATUSES),),
    )
    n = 0
    for pid, sym in cur.fetchall():
        if str(sym).upper() not in valid_symbols:
            n += 1
            if not dry_run:
                cur.execute(
                    """UPDATE paper_trade_proposals
                       SET status='REJECTED', lifecycle_status='EXPIRED',
                           rejection_reason='watchlist_rating_no_longer_buy',
                           updated_at=NOW()
                       WHERE id=%s""",
                    (pid,),
                )
    return n


def sync_watchlist_proposals(*, dry_run: bool = False, max_new: int | None = None) -> dict:
    conn = _get_conn()
    cur = conn.cursor()
    candidates = _fetch_buy_candidates(cur)
    valid_syms = {c["symbol"].upper() for c in candidates}
    reconciled = _reconcile_sleeve_strategy_ids(cur, dry_run=dry_run)
    deduped = _dedupe_watchlist_proposals(cur, dry_run=dry_run)
    expired = _expire_stale_watchlist(cur, valid_syms, dry_run=dry_run)

    created = refreshed = skipped = 0
    cap = max_new if max_new is not None else MAX_NEW_PER_RUN
    broker = DEFAULT_BROKER

    # Batch quotes only for top-ranked names missing entry plans (avoid 500+ sequential quote calls).
    quote_cache: dict[str, float] = {}
    need_quotes = [
        str(c["symbol"]).upper() for c in candidates[:80]
        if not (c.get("limit_price") or c.get("card_entry") or c.get("entry_zone_high"))
    ]
    if need_quotes:
        try:
            import schwab_transport as _st
            sq = _st.get_quotes(need_quotes[:40])
            if sq.get("status") == "ok":
                for sym, q in (sq.get("quotes") or {}).items():
                    if q.get("last"):
                        quote_cache[str(sym).upper()] = float(q["last"])
        except Exception:
            pass

    new_eligible: list[dict] = []  # collected, then ranked by R:R + setup before the cap
    for c in candidates:
        sym = str(c["symbol"]).upper()
        existing = _active_proposal(cur, sym)
        if existing and existing.get("origin") != "watchlist":
            skipped += 1
            continue

        levels = _derive_levels(c, quote_cache)
        if not levels:
            skipped += 1
            continue
        entry, stop, target, exit_rationale, plan_source = levels
        import broker_strategy_resolver as bsr
        strat = str(exit_rationale.get("strategy_id") or exit_rationale.get("resolve", {}).get("strategy_id") or "")
        if not strat:
            resolved = bsr.resolve_executable_strategy(sym, str(c.get("wl_strategy") or DEFAULT_STRATEGY))
            strat = resolved["strategy_id"]
        shares = _size_shares(entry, stop)
        if shares <= 0:
            skipped += 1
            continue

        dollar_size = round(shares * entry, 2)
        dollar_risk = round(abs(entry - stop) * shares, 2)
        rr = round((target - entry) / (entry - stop), 2) if entry > stop else 0
        expires = datetime.now(timezone.utc) + timedelta(days=7)
        resolve_meta = exit_rationale.get("resolve") or {}
        basis = {
            "engine": "watchlist_proposal_bridge",
            "plan_source": plan_source,
            "watchlist_rating": c["watchlist_rating"],
            "rating_source": c["rating_source"],
            "wl_status": c.get("wl_status"),
            "watchlist_sleeve": resolve_meta.get("watchlist_sleeve") or c.get("wl_strategy"),
            "strategy_resolve_source": resolve_meta.get("resolve_source"),
            "classified_strategy": resolve_meta.get("classified_strategy"),
            "exit_rationale": exit_rationale,
            "exit_summary": bsr.build_exit_summary(exit_rationale, entry, stop, target),
            "hermes_score": _f(c.get("hermes_composite_score")),
            "hermes_rank": c.get("hermes_rank"),
            "entry_urgency": c.get("entry_urgency"),
            "entry_tag": c.get("entry_tag"),
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

        if existing:
            refreshed += 1
            if dry_run:
                continue
            cur.execute(
                """UPDATE paper_trade_proposals SET
                       strategy_id=%s,
                       proposed_entry=%s, proposed_stop=%s, proposed_target1=%s,
                       proposed_shares=%s, proposed_dollar_size=%s, proposed_dollar_risk=%s,
                       proposed_rr=%s, cio_view=%s, discovery_source='watchlist',
                       expires_at=%s, max_expires_at=%s, lifecycle_status='ACTIVE',
                       sizing_basis=COALESCE(sizing_basis, '{}'::jsonb) || %s::jsonb,
                       updated_at=NOW()
                   WHERE id=%s""",
                (strat, entry, stop, target, shares, dollar_size, dollar_risk, rr,
                 c["watchlist_rating"].upper(), expires, expires, json.dumps(basis), existing["id"]),
            )
            continue

        # NEW promotion — collect; ranked + capped after the loop (best R:R / setup first).
        new_eligible.append({
            "sym": sym, "strat": strat, "entry": entry, "stop": stop, "target": target,
            "shares": shares, "dollar_size": dollar_size, "dollar_risk": dollar_risk,
            "rr": rr, "basis": basis, "expires": expires, "c": c,
        })

    # Rank new promotions: highest R:R first, then best setup (Hermes composite score). Only the
    # top `cap` get created this run — the rest stay on the watchlist for a later run. This bounds
    # per-run volume (each new PENDING proposal triggers LLM oversight) and promotes the best first.
    new_eligible.sort(key=lambda x: (-(x["rr"] or 0), -(_f(x["c"].get("hermes_composite_score")) or 0)))
    skipped += max(0, len(new_eligible) - cap)
    for item in new_eligible[:cap]:
        created += 1
        if dry_run:
            continue
        c = item["c"]; sym = item["sym"]
        entry, stop, target, strat = item["entry"], item["stop"], item["target"], item["strat"]
        shares, dollar_size, dollar_risk, rr = item["shares"], item["dollar_size"], item["dollar_risk"], item["rr"]
        basis, expires = item["basis"], item["expires"]
        cur.execute(
            """INSERT INTO paper_trade_proposals
                   (symbol, strategy_id, status, origin, discovery_source,
                    intended_broker, target_account, proposed_account,
                    routing_state, proposed_entry, proposed_stop, proposed_target1,
                    proposed_shares, proposed_dollar_size, proposed_dollar_risk, proposed_rr,
                    proposed_stop_pct, cio_view, setup_description,
                    auto_created, proposed_by, expires_at, base_expires_at, max_expires_at,
                    lifecycle_status, proposal_timeframe_class, sizing_basis)
               VALUES (%s,%s,'PENDING','watchlist','watchlist',
                       %s,%s,%s,'queued',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       true,'watchlist_proposal_bridge',%s,%s,%s,'ACTIVE','swing',%s::jsonb)
               RETURNING id""",
            (sym, strat, broker, broker, broker,
             entry, stop, target, shares, dollar_size, dollar_risk, rr,
             round(abs(entry - stop) / entry, 4) if entry else 0,
             c["watchlist_rating"].upper(),
             f"Watchlist {c['watchlist_rating']} ({c.get('rating_source')}) — RR {rr} · Hermes #{c.get('hermes_rank') or '—'}",
             expires, expires, expires, json.dumps(basis)),
        )
        pid = cur.fetchone()[0]
        log.info(f"created watchlist proposal #{pid} {sym} {c['watchlist_rating']} RR {rr} @ ${entry}")

    if not dry_run:
        conn.commit()

    stats = {
        "ok": True,
        "candidates": len(candidates),
        "created": created,
        "refreshed": refreshed,
        "skipped": skipped,
        "reconciled": reconciled,
        "deduped": deduped,
        "expired_not_buy": expired,
        "dry_run": dry_run,
        "broker_account": broker,
    }
    log.info(f"sync done: {stats}")
    return stats


def maybe_sync_on_load() -> dict:
    """Light sync hook for broker-proposals / paper-proposals API loads."""
    if os.getenv("WATCHLIST_PROPOSAL_SYNC_ON_LOAD", "false").lower() != "true":
        return {"skipped": True, "reason": "WATCHLIST_PROPOSAL_SYNC_ON_LOAD=false"}
    try:
        return sync_watchlist_proposals(dry_run=False, max_new=int(os.getenv("WATCHLIST_PROPOSAL_SYNC_CAP", "25")))
    except Exception as e:
        log.warning(f"watchlist sync on load failed: {e}")
        return {"ok": False, "error": str(e)[:160]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-new", type=int, default=None)
    args = ap.parse_args()
    dry = args.dry_run or not args.apply
    stats = sync_watchlist_proposals(dry_run=dry, max_new=args.max_new)
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()