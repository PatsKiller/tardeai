#!/usr/bin/env python3
"""broker_proposal_autocal.py — auto-recalibrate live broker queue proposals in DB.

Fetches batch Schwab quotes, persists current_price / drift / entry zone, clears list cache.
Used by cron, broker-proposals API (throttled), and manual CLI.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from broker_queue_hygiene import fetch_broker_queue_rows

BROKER_AUTOCAL_INTERVAL_SEC = int(os.getenv("BROKER_AUTOCAL_INTERVAL_SEC", "300"))
BROKER_AUTOCAL_MAX_AGE_MIN = int(os.getenv("BROKER_PRICE_MAX_AGE_MIN", "20"))
AUTOCAL_STATE_PATH = PROJECT_ROOT / "data" / "runtime" / "broker_autocal_last.json"


def _parse_ts(val) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    try:
        s = str(val).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s[:26])
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _price_age_min(row: dict) -> float | None:
    ts = _parse_ts(row.get("updated_at")) or _parse_ts(row.get("last_price_checked_at"))
    if not ts:
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60.0


def _is_stale_row(row: dict) -> bool:
    age = _price_age_min(row)
    if age is None:
        return True
    return age > BROKER_AUTOCAL_MAX_AGE_MIN


def batch_live_quotes(symbols: list[str]) -> dict:
    """One Schwab call per 50 symbols; per-symbol fallback via market_quote_provider."""
    syms = sorted({str(s or "").upper() for s in symbols if s})
    if not syms:
        return {}
    now_iso = datetime.now(timezone.utc).isoformat()[:19]
    out: dict = {}
    try:
        import schwab_transport as _st
        for i in range(0, len(syms), 50):
            chunk = syms[i:i + 50]
            sq = _st.get_quotes(chunk)
            if sq.get("status") != "ok":
                continue
            for sym, q in (sq.get("quotes") or {}).items():
                last = q.get("last")
                if last is None:
                    continue
                bid, ask = q.get("bid"), q.get("ask")
                spread = spread_pct = None
                if bid is not None and ask is not None and float(bid) > 0:
                    spread = round(float(ask) - float(bid), 4)
                    spread_pct = round(spread / float(bid) * 100, 3)
                out[str(sym).upper()] = {
                    "last": float(last),
                    "bid": float(bid) if bid is not None else None,
                    "ask": float(ask) if ask is not None else None,
                    "spread": spread,
                    "spread_pct": spread_pct,
                    "provider": "schwab",
                    "refreshed_at": now_iso,
                }
    except Exception:
        pass
    for sym in [s for s in syms if s not in out]:
        try:
            from market_quote_provider import get_best_quote
            q = get_best_quote(sym) or {}
            last = q.get("last_price")
            if last is None:
                continue
            out[sym] = {
                "last": float(last),
                "bid": q.get("bid"),
                "ask": q.get("ask"),
                "spread": q.get("spread"),
                "spread_pct": q.get("spread_pct"),
                "provider": q.get("provider") or "market",
                "refreshed_at": now_iso,
            }
        except Exception:
            continue
    return out


def _db_update_proposal(row: dict, quote: dict) -> bool:
    pid = int(row.get("id") or 0)
    sym = str(row.get("symbol") or "").upper()
    if not pid or not quote.get("last"):
        return False
    last = float(quote["last"])
    entry = float(row.get("proposed_entry") or 0)
    strat = str(row.get("strategy_id") or "momentum_scalp")
    provider = str(quote.get("provider") or "schwab")  # hardcode-ok fallback label when provider missing
    drift_pct = None
    entry_zone = row.get("entry_zone_status")
    if entry > 0:
        drift_pct = round((last - entry) / entry * 100, 2)
        try:
            from proposal_lifecycle import evaluate_lifecycle_status
            lc = evaluate_lifecycle_status(
                strat, last, entry,
                row.get("created_at"), row.get("expires_at"),
            )
            entry_zone = lc.get("entry_zone_status") or entry_zone
            drift_pct = lc.get("price_drift_pct") or drift_pct
        except Exception:
            pass
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn:
            return False
        cur = conn.cursor()
        cur.execute(
            """UPDATE paper_trade_proposals
               SET current_price=%s, price_drift_pct=%s, entry_zone_status=%s,
                   last_price_source=%s, last_price_checked_at=NOW(), updated_at=NOW()
               WHERE id=%s""",
            (last, drift_pct, entry_zone, provider, pid),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        try:
            conn.rollback()  # type: ignore
        except Exception:
            pass
        return False


def _clear_broker_list_cache() -> None:
    try:
        import api_v2 as av2
        av2._BROKER_LIST_CACHE.clear()
    except Exception:
        pass
    try:
        disk = PROJECT_ROOT / "data" / "runtime" / "broker_list_cache.json"
        if disk.exists():
            disk.unlink()
    except Exception:
        pass


def apply_live_quotes_to_rows(rows: list[dict], quote_map: dict | None = None) -> list[dict]:
    """Enrich row dicts with live thesis validity (display path)."""
    if not rows:
        return rows
    qmap = quote_map or batch_live_quotes([r.get("symbol") for r in rows])
    if not qmap:
        return rows
    out = []
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        q = qmap.get(sym)
        if not q:
            out.append(r)
            continue
        nr = dict(r)
        nr["quote_last"] = q["last"]
        if q.get("bid") is not None:
            nr["quote_bid"] = q["bid"]
        if q.get("ask") is not None:
            nr["quote_ask"] = q["ask"]
        nr["quote_provider"] = q.get("provider")
        nr["refreshed_at"] = q.get("refreshed_at")
        try:
            from broker_thesis_validity import attach_thesis_validity
            attach_thesis_validity(nr, quote=q)
            nr["live_rr"] = (nr.get("thesis_validity") or {}).get("current_rr")
            if (nr.get("thesis_validity") or {}).get("drift_pct") is not None:
                nr["price_drift_pct"] = nr["thesis_validity"]["drift_pct"]
        except Exception:
            pass
        out.append(nr)
    return out


def recalibrate_broker_queue(
    *,
    stale_only: bool = True,
    dry_run: bool = False,
    max_rows: int = 500,
) -> dict:
    """Persist live quotes + drift/zone for broker queue rows."""
    rows = fetch_broker_queue_rows()
    if stale_only:
        rows = [r for r in rows if _is_stale_row(r)]
    rows = rows[:max_rows]
    syms = [r.get("symbol") for r in rows]
    qmap = batch_live_quotes(syms)
    updated = skipped = failed = 0
    details: list[dict] = []
    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        q = qmap.get(sym)
        if not q or q.get("last") is None:
            skipped += 1
            continue
        if dry_run:
            updated += 1
            details.append({"id": row.get("id"), "symbol": sym, "would_update": q["last"]})
            continue
        if _db_update_proposal(row, q):
            updated += 1
            details.append({"id": row.get("id"), "symbol": sym, "price": q["last"], "provider": q.get("provider")})
        else:
            failed += 1
    if updated and not dry_run:
        _clear_broker_list_cache()
    return {
        "ok": True,
        "dry_run": dry_run,
        "checked": len(rows),
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "stale_only": stale_only,
        "ran_at": datetime.now(timezone.utc).isoformat()[:19],
        "details": details[:30],
    }


def maybe_auto_recalibrate(*, force: bool = False) -> dict:
    """Throttled auto-recal — runs at most every BROKER_AUTOCAL_INTERVAL_SEC."""
    if os.getenv("BROKER_AUTOCAL_DISABLE", "").lower() in ("1", "true", "yes"):
        return {"skipped": True, "reason": "disabled"}
    now = time.time()
    last = 0.0
    try:
        if AUTOCAL_STATE_PATH.exists():
            blob = json.loads(AUTOCAL_STATE_PATH.read_text(encoding="utf-8"))
            last = float(blob.get("ts") or 0)
    except Exception:
        pass
    if not force and (now - last) < BROKER_AUTOCAL_INTERVAL_SEC:
        return {"skipped": True, "reason": "throttled", "sec_until_next": int(BROKER_AUTOCAL_INTERVAL_SEC - (now - last))}
    result = recalibrate_broker_queue(stale_only=True, dry_run=False)
    try:
        AUTOCAL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUTOCAL_STATE_PATH.write_text(
            json.dumps({"ts": now, "result": {k: result.get(k) for k in ("updated", "checked", "skipped", "failed")}}, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description="Auto-recalibrate broker queue proposals in DB")
    p.add_argument("--apply", action="store_true", help="Persist (default is dry-run)")
    p.add_argument("--all", action="store_true", help="Recal all rows, not just stale")
    p.add_argument("--force", action="store_true", help="Ignore throttle")
    args = p.parse_args()
    if args.force:
        out = recalibrate_broker_queue(stale_only=not args.all, dry_run=not args.apply)
    else:
        out = maybe_auto_recalibrate(force=True) if args.apply else recalibrate_broker_queue(
            stale_only=not args.all, dry_run=not args.apply,
        )
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()