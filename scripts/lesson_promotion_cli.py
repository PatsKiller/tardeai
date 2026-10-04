#!/usr/bin/env python3
"""lesson_promotion_cli.py — gather / enqueue / list / package / decide for the ONE lesson promotion queue (Wave 3 O-W3-2).

    lesson_promotion_cli.py gather                      # dry: what every source exposes
    lesson_promotion_cli.py enqueue --apply             # append new QUEUED rows
    lesson_promotion_cli.py list [--status QUEUED]
    lesson_promotion_cli.py package [--apply]           # QUEUED lessons → one ApprovalPackage (weekly batch)
    lesson_promotion_cli.py decide <procedure_id> PROMOTED|REFUTED|RETIRED --by operator:<who>:typed [--reason ..]

Promotion is operator-only (AGENTS §17; 04 §5): `decide` refuses any `--by` that is not operator:*; the
package path records the typed/button reply on the approval ledger first.
"""
NO_CONSUMER_REASON = (
    "LessonPromotion@v1 rows are read by intelligence_client (MemoryContext.lessons via lesson_promotion.promoted) "
    "and rendered by memory_influence under ADVISORY+; the weekly batch is an operator-run CLI, not a scheduled lane"
)

import argparse
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gather", "enqueue", "list", "package", "decide"])
    ap.add_argument("arg", nargs="?"); ap.add_argument("decision", nargs="?")
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--status"); ap.add_argument("--by", default="")
    ap.add_argument("--reason", default=""); ap.add_argument("--root"); ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args(argv)
    import lesson_promotion as lp  # type: ignore
    env = dict(os.environ)
    root = Path(a.root) if a.root else None
    if root is None and not env.get("TRADEAI_CIO_DIR"):
        if env.get("TRADEAI_STATE_ROOT"):
            root = Path(env["TRADEAI_STATE_ROOT"])
        else:
            try:
                from canonical_store_registry import production_state_root  # type: ignore
                root = Path(production_state_root())
            except Exception:  # noqa: BLE001
                root = Path.home() / "trade-ai-releases" / "persistent-state"
        if not (root / "data" / "cio").is_dir():
            root = Path.home() / "trade-ai-releases" / "persistent-state"
    if a.cmd == "gather":
        rows = lp.gather(root, env)
        by = {}
        for r in rows:
            by[r["source"]] = by.get(r["source"], 0) + 1
        print(json.dumps({"candidates": len(rows), "by_source": by}, indent=1))
        for r in rows[:15]:
            print(f"  {r['procedure_id']} [{r['source']}] {r['statement'][:110]}")
        return 0
    if a.cmd == "enqueue":
        import lesson_outcome_quality as loq  # type: ignore
        price_on, daily_vol = loq.default_lookups()
        print(json.dumps(lp.enqueue(root, env, apply=a.apply, price_on=price_on, daily_vol=daily_vol), indent=1)); return 0
    if a.cmd == "list":
        st = lp.state(root, env)
        rows = [r for r in st.values() if not a.status or r.get("status") == a.status.upper()]
        print(json.dumps({"total": len(st), "shown": len(rows), "by_status": {s: sum(1 for r in st.values() if r.get("status") == s) for s in lp.STATUSES}}, indent=1))
        for r in rows[:a.limit]:
            print(f"  {r['procedure_id']} {r.get('status'):<8} [{r.get('source')}] {str(r.get('statement'))[:100]}")
        return 0
    if a.cmd == "package":
        items = lp.package_items(root, env, limit=a.limit)
        if not items:
            print("nothing QUEUED"); return 0
        import approval_package as ap_  # type: ignore
        led = ap_.Ledger(ap_.ledger_path(root, env))
        pkg = ap_.new_package("cognitive-transformation-20260927", "Wave 3 · lesson promotion batch",
                              f"{len(items)} queued lesson(s) → procedural memory (04 §5). APPROVE promotes; DENY refutes; unanswered rows stay QUEUED.",
                              items, binds={"queue": str(lp.queue_path(root, env))})
        if a.apply:
            led.append({"event": "CREATED", "package_id": pkg["package_id"], "package": pkg})
            print("created", pkg["package_id"])
        else:
            print(json.dumps({"dry_run": True, "items": len(items), "package_id": pkg["package_id"]}, indent=1))
        return 0
    if a.cmd == "decide":
        if not a.arg or not a.decision:
            ap.error("decide <procedure_id> <PROMOTED|REFUTED|RETIRED> --by operator:...")
        print(json.dumps(lp.decide(a.arg, a.decision, by=a.by, reason=a.reason, root=root, env=env), indent=1)); return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
