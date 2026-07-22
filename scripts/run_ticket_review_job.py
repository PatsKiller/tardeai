#!/usr/bin/env python3
"""Detached worker: run free critic lanes on a symbol's live actionable ticket
and persist results into the packet's ticket_review (jsonb update). Advisory
only; deterministic authority unchanged."""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))


def main(symbol: str, lanes: str):
    from env_bootstrap import load_env
    load_env()
    from db_adapter import _get_conn
    import strategy_ticket_review as strv
    import strategy_ticket_reconciler as strec
    import shadow_decision_service as svc
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""SELECT packet_id, packet FROM decision_packets
                   WHERE upper(symbol)=%s AND superseded_by IS NULL""", (symbol.upper(),))
    row = cur.fetchone()
    if not row:
        print(json.dumps({"ok": False, "error": "no live packet"}))
        return
    pid, packet = row
    cap = packet.get("current_actionable_plan")
    if not isinstance(cap, dict):
        cap = None
    validation = (cap or {}).get("ticket_validation") or {}
    facts = {"live_price": packet.get("current_price"),
             "enriched_price": packet.get("price_used"),
             "atr": ((packet.get("input_snapshot") or {}).get("market") or {}).get("atr"),
             "live_price_as_of": packet.get("facts_as_of"), "symbol": symbol.upper()}
    target = cap or ((packet.get("plan_families") or {}).get("swing") or {}
                     ).get("structures", [{}])[0]
    reviews = strv.run_free_reviews(symbol.upper(), target or {}, facts, validation,
                                    lanes=tuple(lanes.split(",")))
    prior = (packet.get("ticket_review") or {})
    merged_reviews = {**(prior.get("reviews") or {}), **reviews}
    reconciled = strec.reconcile(validation or {"state": "PASS"}, merged_reviews)
    tr = {**prior, "reviews": merged_reviews, "reconciled": reconciled}
    cur.execute("""UPDATE decision_packets
                   SET packet = jsonb_set(packet, '{ticket_review}', %s::jsonb)
                   WHERE packet_id=%s""", (json.dumps(tr, default=str), pid))
    conn.commit()
    print(json.dumps({"ok": True, "packet_id": pid,
                      "verdicts": {k: v.get("verdict") for k, v in merged_reviews.items()
                                   if isinstance(v, dict) and not k.startswith("_")},
                      "reconciled": reconciled.get("state")}))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "local,grok,chatgpt")
