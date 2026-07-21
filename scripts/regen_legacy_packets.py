#!/usr/bin/env python3
"""Regenerate every LIVE legacy packet (no input_hash) so the population becomes
current under the Part A input-snapshot + Part D freshness + #5 roll-up invariants.
Advisory only; supersedes in place. No order queued/submitted; no 2FA."""
import sys, json, time
sys.path.insert(0, "scripts")
from concurrent.futures import ThreadPoolExecutor, as_completed
import shadow_decision_service as svc
from db_adapter import _get_conn

c = _get_conn().cursor()
c.execute("SELECT DISTINCT upper(symbol) FROM decision_packets "
          "WHERE superseded_by IS NULL AND packet->>'input_hash' IS NULL ORDER BY 1")
syms = [r[0] for r in c.fetchall()]
print(f"legacy live packets to regenerate: {len(syms)}", flush=True)


def _one(sym):
    try:
        pkt = svc.evaluate(sym, run_models=True, origin="legacy_regen")
        pid = svc.persist(pkt, origin="legacy_regen")
        return sym, pid, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}: {str(e)[:100]}"


done = fail = 0
with ThreadPoolExecutor(max_workers=3) as ex:
    for fut in as_completed([ex.submit(_one, s) for s in syms]):
        sym, pid, err = fut.result()
        if pid:
            done += 1
        else:
            fail += 1
        print(f"  {sym}: {'ok '+str(pid) if pid else 'FAIL '+str(err)}  [{done} ok / {fail} fail]", flush=True)

print(f"\nDONE regen: {done} ok, {fail} fail of {len(syms)}", flush=True)

# post-check: any remaining family-rollup inconsistency in the LIVE set?
import decision_packet as dp
c2 = _get_conn().cursor()
c2.execute("SELECT symbol,packet->'plan_families' f,packet->>'input_hash' ih "
           "FROM decision_packets WHERE superseded_by IS NULL")
bad = legacy = 0
for sym, fams, ih in c2.fetchall():
    if ih is None:
        legacy += 1
    for k, v in (fams or {}).items():
        kids = v.get("structures") or []
        if kids and dp.rollup_family_state(kids) != v.get("state"):
            bad += 1
print(f"POST-CHECK live: remaining legacy(no input_hash)={legacy}  rollup_inconsistencies={bad}", flush=True)
