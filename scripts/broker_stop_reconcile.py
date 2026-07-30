#!/usr/bin/env python3
"""broker_stop_reconcile.py — make the BROKER the source of truth for stop coverage.

Problem this fixes (2026-07-20, Phase-189 recurrence): stop status is computed
by portfolio_stops.py from a local file, data/portfolios/state/stops.json.
Stops placed directly at Schwab never appear there, so protected positions are
reported "NO STOP" and the daily reminder nags about them forever — JEPI had
reached reminder #14 and SPCX #24 while 7 of the 8 flagged names had live
working stop orders at the broker.

This reconciler reads open stop orders across ALL Schwab accounts and merges
them into stops.json with provenance:

  source=broker  — mirrored from a live broker order (broker_order_id recorded)
  source=manual  — pre-existing local entry; NEVER overwritten by this script

A broker-sourced entry whose order no longer exists at the broker is REMOVED,
so a canceled stop correctly reverts to unprotected instead of lingering as a
phantom. Manual entries are always left alone.

READ-ONLY to the broker: queries orders, never places/cancels/replaces.

  broker_stop_reconcile.py            # report only (default, writes nothing)
  broker_stop_reconcile.py --apply    # merge into stops.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

STOPS_JSON = ROOT / "data" / "portfolios" / "state" / "stops.json"

# Schwab statuses that mean "this stop is live at the broker and will fire".
# QUEUED and AWAITING_STOP_CONDITION matter as much as WORKING — a reconciler
# that only accepts WORKING misses stops that simply have not activated yet.
OPEN_STATUSES = {
    "WORKING", "QUEUED", "ACCEPTED", "PENDING_ACTIVATION",
    "AWAITING_STOP_CONDITION", "AWAITING_PARENT_ORDER", "AWAITING_CONDITION",
}
STOP_ORDER_TYPES = {"STOP", "STOP_LIMIT", "TRAILING_STOP", "TRAILING_STOP_LIMIT"}

# account number suffix -> internal account key
SUFFIX_TO_ACCOUNT = {"258": "schwab_rollover_ira", "415": "schwab_roth", "469": "schwab_taxable"}


def _stop_key(symbol: str, account: str) -> str:
    return f"{str(symbol or '').upper()}:{account}"


def _legacy_symbol_for_key(key: str) -> str:
    return str(key or "").split(":", 1)[0]


def fetch_broker_stops() -> tuple[dict, list]:
    """Return ({SYMBOL:ACCOUNT: entry}, [problems]). Never raises on a single account."""
    from schwab_transport import build_client
    problems: list[str] = []
    client, err = build_client("rollover")
    if err:
        return {}, [f"broker client unavailable: {err}"]

    try:
        accts = client.get_account_numbers().json()
    except Exception as e:
        return {}, [f"account enumeration failed: {e}"]

    found: dict[str, dict] = {}
    for a in accts:
        num, h = a.get("accountNumber", ""), a.get("hashValue", "")
        acct_key = SUFFIX_TO_ACCOUNT.get(str(num)[-3:], f"schwab_{str(num)[-3:]}")
        try:
            resp = client.get_orders_for_account(
                h,
                from_entered_datetime=datetime.now() - timedelta(days=180),
                to_entered_datetime=datetime.now() + timedelta(days=1))
            orders = resp.json() if resp.status_code == 200 else []
        except Exception as e:
            problems.append(f"{acct_key}: order fetch failed: {e}")
            continue
        if not isinstance(orders, list):
            problems.append(f"{acct_key}: unexpected order payload")
            continue

        for o in orders:
            if (o.get("status") or "").upper() not in OPEN_STATUSES:
                continue
            otype = (o.get("orderType") or "").upper()
            if otype not in STOP_ORDER_TYPES:
                continue
            for leg in o.get("orderLegCollection", []):
                if (leg.get("instruction") or "").upper() not in ("SELL", "SELL_SHORT"):
                    continue
                sym = ((leg.get("instrument") or {}).get("symbol") or "").upper()
                if not sym:
                    continue
                stop_px = o.get("stopPrice")
                entry = {
                    "stop": float(stop_px) if stop_px not in (None, "") else 0.0,
                    "trail_pct": 0.0,
                    "account": acct_key,
                    "source": "broker",
                    "broker_order_id": str(o.get("orderId") or ""),
                    "order_type": otype,
                    "order_status": (o.get("status") or "").upper(),
                    "qty": o.get("quantity"),
                    "set_date": (o.get("enteredTime") or "")[:10],
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                }
                if stop_px in (None, ""):
                    # Trailing stops report no absolute stopPrice until they arm.
                    # Record honestly rather than inventing a number: the position
                    # IS protected, but the trigger price is not yet knowable.
                    entry["notes"] = (f"{otype} — broker has not published an absolute "
                                      f"stop price yet (status {entry['order_status']})")
                    entry["stop_price_unavailable"] = True
                # Keep identity account-aware: V in Roth must not collapse V in Rollover.
                key = _stop_key(sym, acct_key)
                prev = found.get(key)
                if not prev or entry["stop"] > prev.get("stop", 0):
                    found[key] = entry
    return found, problems


def reconcile(apply: bool = False) -> dict:
    local = {}
    if STOPS_JSON.exists():
        try:
            local = json.loads(STOPS_JSON.read_text())
        except Exception as e:
            return {"ok": False, "error": f"stops.json unreadable: {e}"}

    broker, problems = fetch_broker_stops()
    if problems and not broker:
        # Fail closed: never delete local mirrors because the broker was unreachable.
        return {"ok": False, "error": "broker unreachable — refusing to reconcile",
                "problems": problems}

    added, updated, removed, kept_manual, migrated_legacy = [], [], [], [], []
    merged = dict(local)

    def _is_stop_entry(k, v) -> bool:
        """stops.json carries metadata keys alongside stop dicts — never treat those as stops."""
        return isinstance(v, dict) and not str(k).startswith("_")

    for key, entry in broker.items():
        sym = _legacy_symbol_for_key(key)
        cur = local.get(key)
        legacy = local.get(sym)
        if cur is not None and not isinstance(cur, dict):
            cur = None      # metadata collision; treat as absent
        if cur and cur.get("source") not in (None, "broker"):
            kept_manual.append(key)          # exact account-aware manual entry wins; never clobbered
            continue
        if cur is None and isinstance(legacy, dict) and legacy.get("source") == "broker" and legacy.get("account") == entry.get("account"):
            cur = legacy
            migrated_legacy.append(sym)
        elif cur is None and isinstance(legacy, dict) and legacy.get("source") not in (None, "broker"):
            kept_manual.append(sym)          # legacy manual symbol entry remains untouched
        # Broker truth wins on the NUMBER, but local analyst context is kept:
        # a note like "Below 200d MA" explains why the level was chosen and is
        # not recoverable from the broker payload.
        new = dict(entry)
        if cur:
            for keep in ("notes", "auto_generated"):
                if cur.get(keep) is not None and keep not in new:
                    new[f"local_{keep}" if keep == "notes" else keep] = cur[keep]
        if not cur:
            added.append(key)
            merged[key] = new
        elif (cur.get("stop") != new["stop"]
              or cur.get("broker_order_id") != new["broker_order_id"]
              or cur.get("account") != new.get("account")):
            updated.append(key)
            merged[key] = new
        elif key not in merged:
            # Account-aware compatibility: preserve the broker mirror under the non-colliding key.
            merged[key] = new

    # Drop broker-sourced mirrors whose order is gone (canceled/filled/expired).
    for key, cur in list(local.items()):
        if not _is_stop_entry(key, cur):
            continue
        if cur.get("source") != "broker":
            continue
        if ":" not in key:
            # Legacy symbol-only broker mirrors are ambiguous when duplicate symbols exist.
            # Keep them unless an account-aware broker mirror for the same account replaces them.
            acct_key = cur.get("account")
            sym = _legacy_symbol_for_key(key)
            replacement_key = _stop_key(sym, acct_key) if acct_key else None
            if replacement_key and replacement_key in broker:
                removed.append(key)
                merged.pop(key, None)
            continue
        if key not in broker:
            removed.append(key)
            merged.pop(key, None)

    if apply and (added or updated or removed):
        STOPS_JSON.parent.mkdir(parents=True, exist_ok=True)
        STOPS_JSON.write_text(json.dumps(merged, indent=2, sort_keys=True))

    return {"ok": True, "applied": bool(apply), "broker_stops_found": len(broker),
            "added": sorted(added), "updated": sorted(updated),
            "removed": sorted(removed), "kept_manual": sorted(set(kept_manual)),
            "migrated_legacy": sorted(set(migrated_legacy)),
            "account_aware_keys": sorted(broker),
            "problems": problems, "local_total_after": len(merged)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile local stops.json against live broker stop orders")
    ap.add_argument("--apply", action="store_true", help="write the merge (default: report only)")
    ap.add_argument("--json", action="store_true", help="machine output")
    args = ap.parse_args()

    rep = reconcile(apply=args.apply)
    if args.json:
        print(json.dumps(rep, indent=1))
    else:
        if not rep.get("ok"):
            print(f"REFUSED: {rep.get('error')}")
            for p in rep.get("problems", []):
                print(f"  - {p}")
            return 1
        mode = "APPLIED" if rep["applied"] else "DRY RUN (use --apply)"
        print(f"broker stop reconcile — {mode}")
        print(f"  live broker stop orders : {rep['broker_stops_found']}")
        print(f"  added to stops.json     : {rep['added'] or 'none'}")
        print(f"  updated                 : {rep['updated'] or 'none'}")
        print(f"  removed (order gone)    : {rep['removed'] or 'none'}")
        print(f"  manual entries untouched: {rep['kept_manual'] or 'none'}")
        print(f"  account-aware broker keys: {rep.get('account_aware_keys') or 'none'}")
        for p in rep.get("problems", []):
            print(f"  PROBLEM: {p}")
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
