#!/usr/bin/env python3
"""schwab_shadow_recon.py — Stage 2a shadow-reconciliation harness (Part A1). STRICTLY READ-ONLY.

During a canary session the operator places orders MANUALLY in thinkorswim. This harness, on a ~30s
cadence, READS the orders back via the fenced transport (get_orders_raw) and diffs Schwab's actual
representation against the translator's PREDICTED payload (broker_order_intents.translation_json for
the matching draft). Verdict per order:

  match            — empty diff (∅): Schwab's runtime representation equals our prediction
  rename_only      — diffs exist but every one is in DOCUMENTED_RENAMES (known field renames/recodes)
  mismatch         — Schwab restructured/renamed something we did NOT document → future order
                     tracking would silently misread it; ABORT condition per the protocol
  unmatched_order  — an order with no predicted draft (e.g. operator's unrelated manual order)

NEVER submits/replaces/cancels via API: this module calls ONLY transport reads. The no-writes
validator proves that statically and the write fence (NotProvenWrite) backs it at runtime.

  python3 scripts/schwab_shadow_recon.py --once                 # one poll, JSON report
  python3 scripts/schwab_shadow_recon.py --watch [--interval 30]  # session mode
  python3 scripts/schwab_shadow_recon.py --selftest             # offline fixture diff (no API)
Results: schwab_shadow_recon_runs / _items + appended markdown session log (docs/brokers/).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

MD_LOG = PROJECT_ROOT / "docs" / "brokers" / "stage2a-reconciliation-log.md"

# Fields Schwab adds at runtime that the translator can never predict — recorded, never a mismatch.
RUNTIME_FIELDS = {
    "orderId", "status", "statusDescription", "enteredTime", "closeTime", "releaseTime", "tag",
    "accountNumber", "filledQuantity", "remainingQuantity", "quantity", "cancelable", "editable",
    "orderActivityCollection", "destinationLinkName", "requestedDestination", "cancelTime",
    "legId", "orderLegType", "cusip", "instrumentId", "positionEffect", "complexOrderStrategyType",
    "settlementInstruction", "specialInstruction", "description", "netChange",
}

# DOCUMENTED RENAMES: (json_path_suffix, predicted_value) -> set of acceptable observed values.
# Populated from real session observations; starts with the SDK-documented enum aliases only.
DOCUMENTED_RENAMES: dict[tuple[str, str], set] = {
    # example shape (filled in as sessions teach us): ("duration", "GOOD_TILL_CANCEL"): {"GTC"},
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def diff_payload(predicted, observed, path="") -> list[dict]:
    """Recursive structural diff: every predicted field must appear in observed with an equal value
    (numeric-tolerant: '3.50' == 3.5). Observed-only fields are ignored if RUNTIME_FIELDS, else
    reported as additions. Returns [] (∅) on a clean match."""
    diffs: list[dict] = []
    if isinstance(predicted, dict) and isinstance(observed, dict):
        for k, pv in predicted.items():
            p = f"{path}.{k}" if path else k
            if k not in observed:
                diffs.append({"path": p, "kind": "missing_in_observed", "predicted": pv})
            else:
                diffs += diff_payload(pv, observed[k], p)
        for k in observed:
            if k not in predicted and k.split(".")[-1] not in RUNTIME_FIELDS:
                diffs.append({"path": f"{path}.{k}" if path else k, "kind": "unexpected_addition",
                              "observed": observed[k] if not isinstance(observed[k], (dict, list)) else "<structure>"})
    elif isinstance(predicted, list) and isinstance(observed, list):
        if len(predicted) != len(observed):
            diffs.append({"path": path, "kind": "length_mismatch",
                          "predicted": len(predicted), "observed": len(observed)})
        for i, (pv, ov) in enumerate(zip(predicted, observed)):
            diffs += diff_payload(pv, ov, f"{path}[{i}]")
    else:
        pn, on = _num(predicted), _num(observed)
        equal = (pn is not None and on is not None and abs(pn - on) < 1e-9) or predicted == observed
        if not equal:
            key = (path.split(".")[-1].split("[")[0], str(predicted))
            if str(observed) in DOCUMENTED_RENAMES.get(key, set()):
                diffs.append({"path": path, "kind": "documented_rename",
                              "predicted": predicted, "observed": observed})
            else:
                diffs.append({"path": path, "kind": "value_mismatch",
                              "predicted": predicted, "observed": observed})
    return diffs


def verdict_for(diffs: list[dict]) -> str:
    if not diffs:
        return "match"
    if all(d["kind"] == "documented_rename" for d in diffs):
        return "rename_only"
    return "mismatch"


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _schwab_accounts() -> list[str]:
    cur = _conn().cursor()
    cur.execute("SELECT account_key FROM broker_accounts WHERE broker ILIKE '%schwab%' ORDER BY account_key")
    return [r[0] for r in cur.fetchall()]


def _predicted_intents() -> list[dict]:
    """Recent TRANSLATED drafts with their predicted Schwab payloads (the prediction side of the diff)."""
    cur = _conn().cursor()
    cur.execute("""SELECT intent_id, symbol, intent_json, translation_json FROM broker_order_intents
                   WHERE broker='schwab' AND state='TRANSLATED' AND translation_json IS NOT NULL
                   ORDER BY created_at DESC LIMIT 50""")
    out = []
    for iid, sym, ij, tj in cur.fetchall():
        ij = ij if isinstance(ij, dict) else json.loads(ij or "{}")
        tj = tj if isinstance(tj, dict) else json.loads(tj or "{}")
        for o in tj.get("orders") or []:
            out.append({"intent_id": str(iid), "symbol": (sym or "").upper(), "payload": o,
                        "qty": (ij.get("quantity") or {}).get("qty")})
    return out


def _match_prediction(observed: dict, predictions: list[dict]):
    """Match an observed order to a predicted payload: symbol + entry-leg quantity + orderType."""
    legs = observed.get("orderLegCollection") or [{}]
    sym = ((legs[0].get("instrument") or {}).get("symbol") or "").upper()
    qty = _num(legs[0].get("quantity"))
    typ = observed.get("orderType")
    best = None
    for p in predictions:
        pl = (p["payload"].get("orderLegCollection") or [{}])[0]
        if p["symbol"] != sym:
            continue
        if _num(pl.get("quantity")) == qty and p["payload"].get("orderType") == typ:
            return p
        best = best or p          # symbol-only fallback (still useful to diff)
    return best


def run_once(accounts=None, md_log=True) -> dict:
    import schwab_transport as st
    accounts = accounts or _schwab_accounts()
    predictions = _predicted_intents()
    conn = _conn(); cur = conn.cursor()
    cur.execute("INSERT INTO schwab_shadow_recon_runs (accounts) VALUES (%s) RETURNING id", (accounts,))
    run_id = cur.fetchone()[0]; conn.commit()
    seen = matched = mismatched = unmatched = 0
    lines = []
    status, detail = "ok", None
    for ak in accounts:
        raw = st.get_orders_raw(ak)
        if isinstance(raw, dict):                       # error/degraded — never fabricate observations
            status, detail = "error", f"{ak}: {raw.get('status')} {raw.get('error') or raw.get('reason') or ''}"[:300]
            continue
        for o in raw:
            seen += 1
            pred = _match_prediction(o, predictions)
            if not pred:
                unmatched += 1
                v, diffs, iid, predicted = "unmatched_order", [], None, None
            else:
                diffs = diff_payload(pred["payload"], o)
                v = verdict_for(diffs)
                iid, predicted = pred["intent_id"], pred["payload"]
                if v in ("match", "rename_only"):
                    matched += 1
                else:
                    mismatched += 1
            legs = o.get("orderLegCollection") or [{}]
            sym = ((legs[0].get("instrument") or {}).get("symbol") or "").upper()
            cur.execute("""INSERT INTO schwab_shadow_recon_items
                             (run_id, account_key, broker_order_id, symbol, intent_id, verdict, diff,
                              observed, predicted)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (run_id, ak, str(o.get("orderId") or ""), sym, iid, v,
                         json.dumps(diffs), json.dumps(o), json.dumps(predicted) if predicted else None))
            lines.append(f"| {dt.datetime.now().strftime('%H:%M:%S')} | {ak} | {sym} | "
                         f"{o.get('orderType')}/{o.get('status')} | **{v}** | "
                         f"{('∅' if not diffs else '; '.join(d['path'] + ':' + d['kind'] for d in diffs[:4]))} |")
    cur.execute("""UPDATE schwab_shadow_recon_runs SET orders_seen=%s, matched=%s, mismatched=%s,
                   unmatched=%s, status=%s, detail=%s WHERE id=%s""",
                (seen, matched, mismatched, unmatched, status, detail, run_id))
    conn.commit()
    if md_log and lines:
        hdr = not MD_LOG.exists()
        with MD_LOG.open("a") as f:
            if hdr:
                f.write("# Stage 2a — Shadow Reconciliation Log (read-only harness)\n\n"
                        "| time | account | symbol | type/status | verdict | diff |\n|---|---|---|---|---|---|\n")
            f.write("\n".join(lines) + "\n")
    report = {"run_id": run_id, "accounts": accounts, "orders_seen": seen, "matched": matched,
              "mismatched": mismatched, "unmatched": unmatched, "status": status, "detail": detail,
              "abort_condition": mismatched > 0}
    print(json.dumps(report, default=str))
    return report


def selftest() -> int:
    """Offline fixture proof: translator prediction vs synthetic Schwab read-back. No API, no DB."""
    from brokers.order_intent import (OrderIntent, Instrument, Direction, EntrySpec, EntryMethod,
                                      Quantity, ExitPolicy, StopSpec, TargetSpec)
    from brokers.translators.schwab import translate
    intent = OrderIntent(instrument=Instrument("TST"), direction=Direction.LONG,
                         entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=3.50),
                         quantity=Quantity(qty=2),
                         exit_policy=ExitPolicy(stop=StopSpec(price=3.20), targets=[TargetSpec(price=3.80)]))
    predicted = translate(intent)["orders"][0]
    observed = json.loads(json.dumps(predicted))         # deep copy
    # Schwab runtime additions (expected — must still be ∅/match)
    observed.update({"orderId": 123456, "status": "WORKING", "enteredTime": "2026-06-12T14:30:00+0000",
                     "filledQuantity": 0, "remainingQuantity": 2, "cancelable": True, "editable": True})
    observed["orderLegCollection"][0].update({"legId": 1, "orderLegType": "EQUITY", "positionEffect": "OPENING"})
    d1 = diff_payload(predicted, observed)
    ok1 = verdict_for(d1) == "match"
    print(f"  [{'PASS' if ok1 else 'FAIL'}] runtime-only additions => ∅ match (diffs={d1})")
    # a real restructure must be caught
    observed2 = json.loads(json.dumps(observed))
    observed2["orderType"] = "STOP_LIMIT"
    observed2["price"] = "3.49"
    d2 = diff_payload(predicted, observed2)
    ok2 = verdict_for(d2) == "mismatch" and len(d2) == 2
    print(f"  [{'PASS' if ok2 else 'FAIL'}] renamed/changed fields => mismatch flagged ({len(d2)} diffs)")
    return 0 if (ok1 and ok2) else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--accounts", help="comma-separated account_keys (default: all schwab)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    accounts = [s.strip() for s in a.accounts.split(",")] if a.accounts else None
    if a.watch:
        print(f"shadow recon watching every {a.interval}s — Ctrl-C to stop (READ-ONLY)")
        while True:
            r = run_once(accounts)
            if r["mismatched"]:
                print("⛔ MISMATCH BEYOND DOCUMENTED RENAMES — protocol ABORT condition. Stop placing orders.")
            time.sleep(a.interval)
    else:
        run_once(accounts)


if __name__ == "__main__":
    main()
