#!/usr/bin/env python3
"""options_lifecycle_intake.py — Phase 1: broker → canonical model reconciler.

The broker is canonical (diagnosis §5). This intake reads every option leg the
brokers report, groups legs per (broker, account, underlying) into ONE economic
structure, classifies it, and reconciles against open canonical strategies:

  NEW        broker legs with no canonical match → register (basis from broker
             avg_entry when present; NULL = UNKNOWN, never 0)
  MATCHED    canonical strategy whose open OCC set == broker's → refresh
             broker_position_id / contracts drift check
  DRIFTED    contract counts differ → data_quality 'unreconciled' + flagged
  VANISHED   canonical open leg absent at broker → leg closed with
             closed_price NULL (broker evidence of absence; economics UNKNOWN
             until fill evidence arrives) + strategy flagged 'unreconciled'

Never guesses. Never invents prices. Advisory/persistence only — zero orders.

Sources:
  - Schwab: schwab_transport.get_positions per verified account; OCC-parse
    (same recognition rule as options_engine._fetch_schwab_option_positions —
    that engine remains untouched and keeps its own monitor).
  - Alpaca paper: AlpacaPaperAdapter.get_positions, asset_class us_option.
  - Fidelity: NO automated source (SnapTrade flattens options) — operator
    manual registration only, via register_strategy(source='operator_manual').

Usage: options_lifecycle_intake.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from options_lifecycle_model import (ensure_tables, parse_occ, classify_strategy,
                                     register_strategy, open_strategies)

HOLDINGS = ROOT / "data" / "portfolios" / "state" / "holdings.json"


def _held_shares(account_key: str, symbol: str) -> float:
    try:
        h = json.loads(HOLDINGS.read_text())
        alias = {"schwab_roth_ira": "schwab_roth"}
        acct = alias.get(account_key, account_key)
        return sum(float(r.get("shares") or 0) for r in h.get("holdings", [])
                   if (r.get("symbol") or "").upper() == symbol.upper()
                   and (r.get("account") or "") in (acct, account_key) and not r.get("is_cash"))
    except Exception:
        return 0.0


def fetch_broker_option_legs() -> tuple[list[dict], dict]:
    """Every option leg every broker reports right now. Returns (legs, errors);
    an account in errors contributes NO legs and must NOT trigger VANISHED
    transitions (absence proves nothing when the read failed)."""
    legs, errors = [], {}
    try:
        from db_adapter import _get_conn
        import schwab_transport as st
        cur = _get_conn().cursor()
        cur.execute("SELECT account_key FROM broker_accounts WHERE broker ILIKE '%schwab%' ORDER BY 1")
        for (ak,) in cur.fetchall():
            try:
                pos = st.get_positions(ak)
                if isinstance(pos, dict):
                    errors[ak] = str(pos.get("status"))[:80]
                    continue
                for p in pos:
                    ident = parse_occ(str(p.get("symbol") or ""))
                    if not ident:
                        continue
                    qty = float(p.get("qty") or 0)
                    legs.append({"broker": "schwab", "account_key": ak,
                                 "occ_symbol": str(p["symbol"]),
                                 "underlying": ident["underlying"],
                                 "option_type": ident["option_type"],
                                 "strike": ident["strike"],
                                 "expiration": ident["expiration"],
                                 "side": "short" if qty < 0 else "long",
                                 "contracts": abs(qty),
                                 "opening_price": (abs(float(p["avg_entry_price"]))
                                                   if p.get("avg_entry_price") not in (None, 0) else None),
                                 "broker_position_id": str(p.get("symbol"))})
            except Exception as e:
                errors[ak] = str(e)[:80]
    except Exception as e:
        errors["schwab"] = str(e)[:80]
    try:
        from alpaca_paper_adapter import AlpacaPaperAdapter
        for p in AlpacaPaperAdapter().get_positions() or []:
            if (p.get("asset_class") or "").lower() not in ("us_option", "option"):
                continue
            ident = parse_occ(str(p.get("symbol") or ""))
            if not ident:
                continue
            qty = float(p.get("qty") or 0)
            legs.append({"broker": "alpaca_paper", "account_key": "alpaca_paper",
                         "occ_symbol": str(p["symbol"]), "underlying": ident["underlying"],
                         "option_type": ident["option_type"], "strike": ident["strike"],
                         "expiration": ident["expiration"],
                         "side": "short" if qty < 0 else "long", "contracts": abs(qty),
                         "opening_price": (abs(float(p["avg_entry_price"]))
                                           if p.get("avg_entry_price") not in (None, 0) else None),
                         "broker_position_id": str(p.get("asset_id") or p.get("symbol"))})
    except Exception as e:
        errors["alpaca_paper"] = str(e)[:80]
    return legs, errors


def reconcile(dry: bool = False) -> dict:
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    ensure_tables(cur, conn)
    broker_legs, errors = fetch_broker_option_legs()

    # group broker legs into candidate structures
    groups: dict[tuple, list[dict]] = {}
    for l in broker_legs:
        groups.setdefault((l["broker"], l["account_key"], l["underlying"]), []).append(l)

    canon = open_strategies(cur)
    canon_by_key: dict[tuple, list[dict]] = {}
    for s in canon:
        canon_by_key.setdefault((("alpaca_paper" if s["broker"] == "alpaca_paper" else s["broker"]),
                                 s["account_key"], s["underlying"]), []).append(s)

    report = {"new": [], "matched": [], "drifted": [], "vanished": [], "errors": errors}

    for key, legs in groups.items():
        broker, ak, und = key
        occ_set = {(l["occ_symbol"], l["side"]) for l in legs}
        matched = None
        for s in canon_by_key.get(key, []):
            s_occ = {(l["occ_symbol"], l["side"]) for l in s["legs"] if l["status"] == "open"}
            if s_occ == occ_set:
                matched = s
                break
        if matched:
            drift = []
            for bl in legs:
                cl = next((x for x in matched["legs"]
                           if x["occ_symbol"] == bl["occ_symbol"] and x["side"] == bl["side"]), None)
                if cl and float(cl["contracts"]) != bl["contracts"]:
                    drift.append(f"{bl['occ_symbol']}: canonical {cl['contracts']} vs broker {bl['contracts']}")
            if drift and not dry:
                cur.execute("""UPDATE options_strategy_positions
                               SET data_quality_status='unreconciled', updated_at=now()
                               WHERE strategy_position_id=%s""", (matched["strategy_position_id"],))
            (report["drifted"] if drift else report["matched"]).append(
                {"strategy_position_id": matched["strategy_position_id"], "key": list(key),
                 **({"drift": drift} if drift else {})})
        else:
            held = _held_shares(ak, und) if broker == "schwab" else 0.0
            if dry:
                report["new"].append({"key": list(key), "legs": len(legs),
                                      "would_classify": classify_strategy(
                                          [{**l, "instruction": ""} for l in legs], held_shares=held)})
            else:
                for l in legs:
                    l["instruction"] = ("STO" if l["side"] == "short" else "BTO")
                spid = register_strategy(
                    cur, conn, broker=broker, account_key=ak, underlying=und,
                    legs=legs, source="broker_sync", held_shares=held,
                    notes="registered by lifecycle intake reconciler")
                # v1.1 P5: broker holding a position IS fill evidence — OPEN event + bridge
                try:
                    from options_journal_bridge import (ensure_bridge_tables, emit_event,
                                                        upsert_trade_instance)
                    ensure_bridge_tables(cur, conn)
                    emit_event(cur, conn, spid, "OPEN", "broker_sync",
                               ref=f"{broker}:{ak}", details={"legs": len(legs)})
                    upsert_trade_instance(cur, conn, spid)
                except Exception as _e:
                    print(f"  [journal-bridge] non-blocking: {str(_e)[:120]}")
                report["new"].append({"strategy_position_id": spid, "key": list(key), "legs": len(legs)})

    # VANISHED: canonical open legs the broker no longer reports (skip errored accounts)
    for s in canon:
        skey = (s["broker"], s["account_key"], s["underlying"])
        if s["account_key"] in errors or s["broker"] in errors:
            continue
        if s["broker"] == "fidelity":
            continue  # no automated source — operator evidence only
        broker_occ = {(l["occ_symbol"], l["side"]) for l in groups.get(skey, [])}
        gone = [l for l in s["legs"] if l["status"] == "open"
                and (l["occ_symbol"], l["side"]) not in broker_occ]
        if gone:
            if not dry:
                for l in gone:
                    cur.execute("""UPDATE options_strategy_legs
                                   SET status='closed', closed_at=now(), closed_price=NULL
                                   WHERE leg_id=%s""", (l["leg_id"],))
                still_open = [l for l in s["legs"] if l["status"] == "open"
                              and (l["occ_symbol"], l["side"]) in broker_occ]
                cur.execute("""UPDATE options_strategy_positions
                               SET status=%s, data_quality_status='unreconciled',
                                   closed_at=CASE WHEN %s THEN now() ELSE closed_at END,
                                   updated_at=now()
                               WHERE strategy_position_id=%s""",
                            ("open" if still_open else "closed", not still_open,
                             s["strategy_position_id"]))
            report["vanished"].append({"strategy_position_id": s["strategy_position_id"],
                                       "legs_gone": [l["occ_symbol"] for l in gone],
                                       "note": "closed_price UNKNOWN until fill evidence — flagged unreconciled"})
    if not dry:
        conn.commit()
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    r = reconcile(dry=a.dry_run)
    print(json.dumps(r, indent=1, default=str))
