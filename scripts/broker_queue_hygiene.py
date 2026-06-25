#!/usr/bin/env python3
"""broker_queue_hygiene.py — audit + auto-expire stale live-broker proposal queue rows.

Broker-promoted proposals (Schwab/Fidelity) stay APPROVED_FOR_PAPER_TEST and were exempt from
PENDING-only expiry sweeps — they could linger indefinitely. This module classifies and clears
stale broker queue rows and provides a shared symbol-active guard for proposal creation paths.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from proposal_routing import is_broker_routed

ACTIVE_SYMBOL_STATUSES = (
    "PENDING",
    "APPROVED",
    "MODIFIED",
    "APPROVED_FOR_PAPER_TEST",
    "BROKER_SUBMITTED",
)

BROKER_QUEUE_STATUSES = ("PENDING", "APPROVED_FOR_PAPER_TEST")

ENTRY_MISSED_DRIFT_MULT = float(os.getenv("BROKER_QUEUE_ENTRY_MISSED_MULT", "1.5"))
BROKER_MAX_AGE_HOURS = float(os.getenv("BROKER_QUEUE_MAX_AGE_HOURS", "24"))
BROKER_THESIS_RISK_EXPIRE_DAYS = float(os.getenv("BROKER_THESIS_RISK_EXPIRE_DAYS", "3"))
BROKER_STALE_PRICE_EXPIRE_DAYS = float(os.getenv("BROKER_STALE_PRICE_EXPIRE_DAYS", "1"))
BROKER_APPROACHING_EXPIRE_DAYS = float(os.getenv("BROKER_APPROACHING_EXPIRE_DAYS", "7"))


def _get_conn():
    from db_adapter import _get_conn
    return _get_conn()


def _q(sql, params=None, one=False):
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(sql, params or ())
        if one:
            row = cur.fetchone()
            if not row:
                conn.commit()
                return None
            cols = [d[0] for d in cur.description]
            conn.commit()
            return dict(zip(cols, row))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.commit()
        return rows
    except Exception:
        try:
            _get_conn().rollback()
        except Exception:
            pass
        return None if one else []


def _parse_ts(val):
    if not val:
        return None
    if isinstance(val, datetime):
        dt = val
    else:
        try:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def find_active_symbol_proposal(
    symbol: str,
    *,
    exclude_id: int | None = None,
    broker_only: bool = False,
) -> dict | None:
    """Return newest active proposal for symbol (optional broker-routed filter)."""
    sym = str(symbol or "").upper()
    if not sym:
        return None
    rows = _q(
        """SELECT id, symbol, status, strategy_id, origin,
                  intended_broker, target_account, proposed_account,
                  proposed_entry, proposed_stop, current_price, price_drift_pct,
                  entry_zone_status, created_at, expires_at, updated_at
           FROM paper_trade_proposals
           WHERE symbol = %s
             AND status = ANY(%s)
           ORDER BY created_at DESC""",
        (sym, list(ACTIVE_SYMBOL_STATUSES)),
    ) or []
    for row in rows:
        if exclude_id and int(row.get("id") or 0) == int(exclude_id):
            continue
        if broker_only and not is_broker_routed(row):
            continue
        return row
    return None


def fetch_broker_queue_rows(*, include_pending: bool = True) -> list[dict]:
    statuses = list(BROKER_QUEUE_STATUSES)
    if not include_pending:
        statuses = ["APPROVED_FOR_PAPER_TEST"]
    rows = _q(
        f"""SELECT id, symbol, status, strategy_id, origin,
                   intended_broker, target_account, proposed_account,
                   proposed_entry, proposed_stop, proposed_target1,
                   current_price, price_drift_pct, entry_zone_status,
                   created_at, expires_at, updated_at, routing_state
            FROM paper_trade_proposals
            WHERE status = ANY(%s)
              AND (
                lower(COALESCE(intended_broker, target_account, proposed_account, '')) LIKE 'schwab%%'
                OR lower(COALESCE(intended_broker, target_account, proposed_account, '')) LIKE 'fidelity%%'
              )
            ORDER BY created_at DESC""",
        (statuses,),
    ) or []
    return [r for r in rows if is_broker_routed(r)]


def _attach_thesis_zone(row: dict) -> dict:
    """Attach thesis_validity zone for hygiene (skip if already stamped or incomplete row)."""
    tv = row.get("thesis_validity") or {}
    if tv.get("zone_status"):
        return row
    if not (row.get("proposed_entry") and row.get("proposed_stop") and row.get("proposed_target1")):
        return row
    try:
        from broker_thesis_validity import attach_thesis_validity
        attach_thesis_validity(row)
    except Exception:
        pass
    return row


def _classify_thesis_zone(
    row: dict,
    *,
    now: datetime,
    created: datetime | None,
    reasons: list[str],
) -> tuple[str, str | None]:
    """Expire stale / at-risk thesis bands (all origins, including watchlist)."""
    action = "keep"
    new_status = None
    if not created:
        return action, new_status
    age_d = (now - created).total_seconds() / 86400
    tv = row.get("thesis_validity") or {}
    zone = str(tv.get("zone_status") or "").lower()
    if zone == "invalid":
        reasons.append("Thesis invalid — entry/stop/target band broken")
        return "expire", "EXPIRED"
    if zone == "stale_price" and age_d > BROKER_STALE_PRICE_EXPIRE_DAYS:
        reasons.append(
            f"Stale price {age_d:.1f}d > {BROKER_STALE_PRICE_EXPIRE_DAYS:.0f}d — refresh failed"
        )
        return "expire", "EXPIRED"
    if zone == "at_risk" and age_d > BROKER_THESIS_RISK_EXPIRE_DAYS:
        reasons.append(
            f"Thesis at_risk {age_d:.1f}d > {BROKER_THESIS_RISK_EXPIRE_DAYS:.0f}d cap"
        )
        return "expire", "EXPIRED"
    if zone == "approaching" and age_d > BROKER_APPROACHING_EXPIRE_DAYS:
        reasons.append(
            f"Thesis approaching edge {age_d:.1f}d > {BROKER_APPROACHING_EXPIRE_DAYS:.0f}d cap"
        )
        return "expire", "EXPIRED"
    return action, new_status


def _drift_threshold(strategy_id: str) -> float:
    try:
        from proposal_lifecycle import get_price_drift_threshold
        return float(get_price_drift_threshold(strategy_id or "momentum_scalp"))
    except Exception:
        return 5.0


def classify_broker_queue_row(
    row: dict,
    *,
    now: datetime | None = None,
    newer_same_symbol: dict | None = None,
) -> dict:
    """Classify a broker queue row — keep | expire | reject (no DB writes)."""
    now = now or datetime.now(timezone.utc)
    pid = int(row.get("id") or 0)
    sym = str(row.get("symbol") or "").upper()
    strat = str(row.get("strategy_id") or "")
    origin = str(row.get("origin") or "").lower()
    is_watchlist = origin == "watchlist"
    reasons: list[str] = []
    action = "keep"
    new_status = None

    created = _parse_ts(row.get("created_at"))
    expires = _parse_ts(row.get("expires_at"))
    entry = float(row.get("proposed_entry") or 0)
    stop = float(row.get("proposed_stop") or 0)
    live = row.get("current_price")
    live_f = float(live) if live is not None else None
    drift = row.get("price_drift_pct")
    drift_f = float(drift) if drift is not None else None
    if drift_f is None and live_f is not None and entry > 0:
        drift_f = round((live_f - entry) / entry * 100, 2)

    _attach_thesis_zone(row)
    t_action, t_status = _classify_thesis_zone(row, now=now, created=created, reasons=reasons)
    if t_action != "keep":
        action = t_action
        new_status = t_status

    # Watchlist-origin rows persist while BUY/STRONG_BUY — bridge handles rating-based expiry.
    if not is_watchlist and action == "keep":
        if expires and now > expires:
            reasons.append(f"Past expires_at ({expires.strftime('%Y-%m-%d %H:%M')} UTC)")
            action = "expire"
            new_status = "EXPIRED"

        thresh = _drift_threshold(strat)
        zone = str(row.get("entry_zone_status") or "").upper()
        if drift_f is not None and abs(drift_f) > thresh * ENTRY_MISSED_DRIFT_MULT:
            reasons.append(f"Entry missed — drift {drift_f:+.1f}% > {thresh * ENTRY_MISSED_DRIFT_MULT:.1f}% band")
            action = "expire"
            new_status = "EXPIRED"
        elif zone == "ENTRY_MISSED":
            reasons.append("Entry zone status ENTRY_MISSED")
            action = "expire"
            new_status = "EXPIRED"

        if live_f is not None and stop > 0 and live_f <= stop:
            reasons.append(f"Stop breached — live ${live_f:.4f} <= stop ${stop:.4f}")
            action = "expire"
            new_status = "EXPIRED"

        if created and BROKER_MAX_AGE_HOURS > 0:
            age_h = (now - created).total_seconds() / 3600
            if age_h > BROKER_MAX_AGE_HOURS:
                reasons.append(f"Broker queue age {age_h:.1f}h > {BROKER_MAX_AGE_HOURS:.0f}h cap")
                action = "expire"
                new_status = "EXPIRED"

    if newer_same_symbol and int(newer_same_symbol.get("id") or 0) != pid:
        newer_at = _parse_ts(newer_same_symbol.get("created_at"))
        newer_origin = str(newer_same_symbol.get("origin") or "").lower()
        if newer_at and created and newer_at > created:
            # Duplicate watchlist rows: reject older copy only (bridge should dedupe on sync).
            if is_watchlist and newer_origin == "watchlist":
                reasons.append(f"Duplicate watchlist row — keep #{newer_same_symbol.get('id')}")
                action = "reject"
                new_status = "REJECTED"
            elif not is_watchlist:
                reasons.append(
                    f"Superseded by newer active proposal #{newer_same_symbol.get('id')} "
                    f"({newer_same_symbol.get('origin') or 'unknown'})"
                )
                action = "reject"
                new_status = "REJECTED"

    tv = row.get("thesis_validity") or {}
    return {
        "proposal_id": pid,
        "symbol": sym,
        "strategy_id": strat,
        "action": action,
        "new_status": new_status,
        "reasons": reasons,
        "drift_pct": drift_f,
        "thesis_zone": tv.get("zone_status"),
        "expires_at": expires.isoformat() if expires else None,
        "created_at": created.isoformat() if created else None,
        "routing_state": row.get("routing_state"),
        "origin": row.get("origin"),
    }


def _apply_hygiene(classification: dict, *, dry_run: bool = True) -> bool:
    if classification.get("action") == "keep":
        return False
    pid = classification.get("proposal_id")
    new_status = classification.get("new_status") or "EXPIRED"
    label = "; ".join(classification.get("reasons") or [])[:500]
    prefix = "AUTO broker hygiene"
    if dry_run:
        return True
    try:
        conn = _get_conn()
        cur = conn.cursor()
        action_state = "REJECTED" if new_status == "REJECTED" else "EXPIRED"
        cur.execute(
            """UPDATE paper_trade_proposals
               SET status=%s,
                   lifecycle_status=CASE WHEN %s = 'EXPIRED' THEN 'EXPIRED' ELSE lifecycle_status END,
                   action_state=%s,
                   action_label=%s,
                   expiry_reason=%s,
                   routing_state=CASE WHEN routing_state IN ('queued','routing') THEN 'rejected' ELSE routing_state END,
                   updated_at=NOW()
               WHERE id=%s
                 AND status = ANY(%s)""",
            (
                new_status,
                new_status,
                action_state,
                label[:500],
                f"{prefix}: {label}"[:500],
                pid,
                list(BROKER_QUEUE_STATUSES),
            ),
        )
        changed = cur.rowcount > 0
        conn.commit()
        return changed
    except Exception:
        return False


def supersede_older_broker_rows(symbol: str, keep_id: int, *, dry_run: bool = False) -> int:
    """Reject other broker-queue rows for symbol when a fresher proposal is promoted."""
    sym = str(symbol or "").upper()
    if not sym or not keep_id:
        return 0
    n = 0
    for row in fetch_broker_queue_rows():
        if str(row.get("symbol") or "").upper() != sym:
            continue
        rid = int(row.get("id") or 0)
        if rid == int(keep_id):
            continue
        clf = {
            "proposal_id": rid,
            "action": "reject",
            "new_status": "REJECTED",
            "reasons": [f"Superseded by promoted proposal #{keep_id}"],
        }
        if _apply_hygiene(clf, dry_run=dry_run):
            n += 1
    return n


def sweep_broker_queue(*, dry_run: bool = True, refresh_quotes: bool = True) -> dict:
    """Audit + optionally expire/reject stale Schwab/Fidelity queue rows."""
    rows = fetch_broker_queue_rows()
    now = datetime.now(timezone.utc)
    details: list[dict] = []
    expired = rejected = kept = 0
    changed = 0

    symbol_newest: dict[str, dict] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        active = find_active_symbol_proposal(sym)
        if active:
            symbol_newest[sym] = active

    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        if refresh_quotes and sym:
            try:
                from market_quote_provider import get_best_quote
                q = get_best_quote(sym) or {}
                last = q.get("last_price")
                if last is not None and float(last) > 0:
                    entry = float(row.get("proposed_entry") or 0)
                    drift = round((float(last) - entry) / entry * 100, 2) if entry > 0 else None
                    row["current_price"] = last
                    row["price_drift_pct"] = drift
                    if not dry_run:
                        _q(
                            """UPDATE paper_trade_proposals
                               SET current_price=%s, price_drift_pct=%s, updated_at=NOW()
                               WHERE id=%s""",
                            (last, drift, row["id"]),
                        )
            except Exception:
                pass

        newer = symbol_newest.get(sym)
        clf = classify_broker_queue_row(row, now=now, newer_same_symbol=newer)
        details.append(clf)
        if clf["action"] == "keep":
            kept += 1
        elif clf["action"] == "expire":
            expired += 1
            if _apply_hygiene(clf, dry_run=dry_run):
                changed += 1
        elif clf["action"] == "reject":
            rejected += 1
            if _apply_hygiene(clf, dry_run=dry_run):
                changed += 1

    out = {
        "ok": True,
        "dry_run": dry_run,
        "checked": len(rows),
        "kept": kept,
        "changed": changed,
        "details": details,
        "ran_at": now.isoformat()[:19],
    }
    if dry_run:
        out["would_expire"] = expired
        out["would_reject"] = rejected
    else:
        out["expired"] = expired
        out["rejected"] = rejected
    return out


def audit_proposal_pipeline(*, days: int = 7) -> dict:
    """High-level audit of proposal funnel dysfunctions."""
    days = max(1, int(days))
    status_rows = _q(
        """SELECT status, count(*) AS n
           FROM paper_trade_proposals
           WHERE created_at > NOW() - (%s || ' days')::interval
           GROUP BY status ORDER BY n DESC""",
        (str(days),),
    ) or []
    pending_n = _q(
        "SELECT count(*) AS n FROM paper_trade_proposals WHERE status='PENDING'",
        one=True,
    ) or {"n": 0}
    broker_queue = fetch_broker_queue_rows()
    broker_classifications = [
        classify_broker_queue_row(r, newer_same_symbol=find_active_symbol_proposal(str(r.get("symbol") or "")))
        for r in broker_queue
    ]
    stale_broker = [c for c in broker_classifications if c["action"] != "keep"]
    dup_symbols = _q(
        """SELECT symbol, count(*) AS n, array_agg(id ORDER BY created_at DESC) AS ids
           FROM paper_trade_proposals
           WHERE status = ANY(%s)
           GROUP BY symbol HAVING count(*) > 1""",
        (list(ACTIVE_SYMBOL_STATUSES),),
    ) or []
    decisions = _q(
        """SELECT decision, count(*) AS n
           FROM auto_proposal_decisions
           WHERE created_at > NOW() - (%s || ' days')::interval
           GROUP BY decision ORDER BY n DESC LIMIT 15""",
        (str(days),),
    ) or []
    gaps = [
        {
            "id": "broker_queue_no_auto_expiry",
            "severity": "high",
            "detail": "Broker-promoted APPROVED_FOR_PAPER_TEST rows were exempt from PENDING-only expiry sweeps",
            "fix": "broker_queue_hygiene.sweep_broker_queue",
        },
        {
            "id": "duplicate_gate_misses_approved",
            "severity": "high",
            "detail": "check_duplicate ignored APPROVED_FOR_PAPER_TEST — same symbol could spawn paper + broker rows",
            "fix": "ACTIVE_SYMBOL_STATUSES includes APPROVED_FOR_PAPER_TEST",
        },
        {
            "id": "incubator_pending_only_dedup",
            "severity": "medium",
            "detail": "incubator_promoter deduped PENDING only, not approved active rows",
            "fix": "find_active_symbol_proposal guard before INSERT",
        },
        {
            "id": "zero_pending_backlog",
            "severity": "info",
            "detail": f"PENDING count={pending_n.get('n', 0)} — ATM fast-tracks to APPROVED/REJECTED",
        },
    ]
    return {
        "ok": True,
        "days": days,
        "status_breakdown": status_rows,
        "pending_count": int(pending_n.get("n") or 0),
        "broker_queue_count": len(broker_queue),
        "broker_queue_stale": stale_broker,
        "duplicate_active_symbols": dup_symbols,
        "auto_decision_breakdown": decisions,
        "known_gaps": gaps,
        "broker_queue_rows": broker_queue,
        "audited_at": datetime.now(timezone.utc).isoformat()[:19],
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Broker queue hygiene + proposal pipeline audit")
    parser.add_argument("--audit", action="store_true", help="Print pipeline audit JSON")
    parser.add_argument("--sweep", action="store_true", help="Sweep broker queue rows")
    parser.add_argument("--apply", action="store_true", help="Apply sweep changes (default dry-run)")
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args()

    if args.audit:
        print(json.dumps(audit_proposal_pipeline(days=args.days), indent=2, default=str))
    if args.sweep:
        print(json.dumps(sweep_broker_queue(dry_run=not args.apply), indent=2, default=str))
    if not args.audit and not args.sweep:
        parser.print_help()
        raise SystemExit(1)