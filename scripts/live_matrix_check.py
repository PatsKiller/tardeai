#!/usr/bin/env python3
"""Part G — seven-name live matrix. Advisory only; generates + verifies parity.
No order queued/submitted; no 2FA. Run: python scripts/live_matrix_check.py"""
import sys, json, os
sys.path.insert(0, "scripts")
from concurrent.futures import ThreadPoolExecutor, as_completed

import shadow_decision_service as svc
import decision_action_policy as pol
import packet_invalidation as inv
from db_adapter import _get_conn

SYMBOLS = {
    "BETA": "negative label · conditional · earnings · 0 shares · options all-rejected",
    "ADVB": "evidence-selected IGNORE (material move)",
    "YSXT": "evidence-selected AVOID (volume-confirmed move)",
    "DXCM": "held · earnings event",
    "ANET": "held · earnings event",
    "CSCO": "held · earnings · options",
    "V":    "held · liquid options (eligible/conditional candidate)",
}


def _gen(sym):
    try:
        pkt = svc.evaluate(sym, run_models=True, origin="matrix")
        pid = svc.persist(pkt, origin="matrix")
        return sym, pid, None
    except Exception as e:
        return sym, None, f"{type(e).__name__}: {str(e)[:120]}"


def verify(sym):
    conn = _get_conn(); cur = conn.cursor()
    cur.execute("""SELECT packet_id, packet, generated_at FROM decision_packets
                   WHERE upper(symbol)=%s AND superseded_by IS NULL ORDER BY generated_at DESC LIMIT 1""", (sym,))
    r = cur.fetchone()
    if not r:
        return {"symbol": sym, "error": "no live packet"}
    pid, pkt, gen = r[0], (r[1] if isinstance(r[1], dict) else json.loads(r[1])), r[2]

    snap = inv.build_current_input_snapshot(sym, conn)
    res = pol.evaluate_action(pkt, packet_id=pid, generated_at=str(gen), current_snapshot=snap)

    # family roll-up vs persisted blueprints
    cur.execute("SELECT family, state FROM decision_blueprints WHERE packet_id=%s", (pid,))
    bp = {}
    for fam, st in cur.fetchall():
        bp.setdefault(fam, []).append(st)
    import decision_packet as dp
    rollup_ok = True
    for fam_key, fam in (pkt.get("plan_families") or {}).items():
        fam_name = fam.get("family")
        children = [{"state": s} for s in bp.get(fam_name, [])]
        if children:
            expected = dp.rollup_family_state(children)
            # a family with a single self-row (no structures) is trivially consistent
            if len(children) > 1 and expected != fam.get("state"):
                rollup_ok = False

    dq = pkt.get("data_quality", {})
    return {
        "symbol": sym,
        "packet_id": pid,
        "packet_hash": pkt.get("input_hash"),
        "current_hash": snap.get("input_hash"),
        "inputs_match": res.get("inputs_match"),
        "action": res.get("action"), "allowed": res.get("allowed"), "state": res.get("state"),
        "invalidation": res.get("invalidation_reasons"),
        "families": {k: (v.get("state")) for k, v in (pkt.get("plan_families") or {}).items()},
        "rollup_matches_blueprints": rollup_ok,
        "ownership_held": pkt.get("ownership", {}).get("held"),
        "event": f"{pkt['event_state']['earnings'].get('state')} {pkt['event_state']['earnings'].get('date')}",
        "dq_state": dq.get("state"), "dq_dims": dq.get("dimensions"),
        "fund_state": (dq.get("fundamentals_provenance") or {}).get("state"),
        "legacy": (pkt.get("legacy_summary") or {}).get("recommendation"),
    }


def main():
    print("=== generating 7 packets (blind pass, ~concurrency 3) ===", flush=True)
    with ThreadPoolExecutor(max_workers=3) as ex:
        for fut in as_completed([ex.submit(_gen, s) for s in SYMBOLS]):
            sym, pid, err = fut.result()
            print(f"  {sym}: {'packet ' + str(pid) if pid else 'FAILED ' + str(err)}", flush=True)

    print("\n=== PARITY VERIFICATION ===", flush=True)
    rows = [verify(s) for s in SYMBOLS]
    for v in rows:
        if v.get("error"):
            print(f"\n{v['symbol']}: {v['error']}"); continue
        print(f"\n{v['symbol']:5s} [{SYMBOLS[v['symbol']]}]")
        print(f"  hashes: packet={v['packet_hash']} current={v['current_hash']} match={v['inputs_match']}")
        print(f"  action={v['action']} allowed={v['allowed']} state={v['state']} inval={v['invalidation']}")
        print(f"  families={v['families']}  rollup_ok={v['rollup_matches_blueprints']}")
        print(f"  ownership_held={v['ownership_held']} event={v['event']} legacy={v['legacy']}")
        print(f"  data_quality={v['dq_state']} dims={v['dq_dims']} fundamentals={v['fund_state']}")

    print("\n=== MUTATION TESTS (prove a current packet flips to STALE) ===", flush=True)
    conn = _get_conn(); cur = conn.cursor()
    for sym, mut in (("BETA", "ownership"), ("ADVB", "catalyst"),
                     ("DXCM", "earnings"), ("ANET", "price")):
        cur.execute("""SELECT packet_id, packet, generated_at FROM decision_packets
                       WHERE upper(symbol)=%s AND superseded_by IS NULL ORDER BY generated_at DESC LIMIT 1""", (sym,))
        r = cur.fetchone()
        if not r:
            print(f"  {sym}: no packet"); continue
        pkt = r[1] if isinstance(r[1], dict) else json.loads(r[1])
        snap = inv.build_current_input_snapshot(sym, conn)
        base = pol.evaluate_action(pkt, generated_at=str(r[2]), current_snapshot=snap)
        m = json.loads(json.dumps(snap))
        if mut == "ownership":
            m["ownership"]["ownership_content_hash"] = "MUT_OWN"
        elif mut == "catalyst":
            m["events"]["latest_catalyst_at"] = "2099-01-01T00:00:00+00:00"
        elif mut == "earnings":
            m["events"]["event_content_hash"] = "MUT_EV"; m["events"]["earnings_date"] = "2099-01-01"
        elif mut == "price":
            m["market"]["price"] = (pkt.get("price_used") or 100) * 1.5
        m["input_hash"] = inv.compute_input_hash(m)
        after = pol.evaluate_action(pkt, generated_at=str(r[2]), current_snapshot=m)
        ok = after["state"] == "STALE" and after["allowed"] is False
        print(f"  {sym} mutate {mut:9s}: base={base['state']}/{base['allowed']} "
              f"-> after={after['state']}/{after['allowed']} reasons={after.get('invalidation_reasons')} {'PASS' if ok else 'CHECK'}")


if __name__ == "__main__":
    raise SystemExit(main())
