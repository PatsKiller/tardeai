#!/usr/bin/env python3
"""shadow_batch_generator.py — bounded batch generation of shadow decision packets.

SHADOW ONLY. Produces decision packets; queues, approves, submits, confirms
nothing.

OPERATOR AUTHORISATION (2026-07-21): generate packets for
  - the TOP N (default 50) watchlist symbols by Hermes rank whose recommendation
    is in the eligible set {STRONG_BUY, BUY, ADD, ADD_ON_PULLBACK, HOLD}
    (i.e. strong buy / buy / hold / wait-for-pullback), and
  - ALL operator-starred symbols.

WHY BOUNDED. A blind pass is two cloud-model calls per symbol. HOLD alone is
~1,047 symbols; generating for the whole rated universe (~1,588) would be ~3,200
model calls per run — real, recurring spend. So the set is capped at N + starred
(~60), every threshold is env-configurable, and the run is IDEMPOTENT: a symbol
with a live packet younger than the freshness window is skipped, so re-running
costs nothing for what is already fresh.

NO SILENT TRUNCATION. If the eligible set exceeds the cap, the dropped count is
logged — a bounded run must say what it did not cover.

    python shadow_batch_generator.py --dry-run          # print the set, spend nothing
    python shadow_batch_generator.py --run              # generate (respects freshness)
    python shadow_batch_generator.py --run --top 100    # wider
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Eligible ratings: strong buy / buy / add / wait-for-pullback / hold.
ELIGIBLE_RATINGS = ("STRONG_BUY", "BUY", "ADD", "ADD_ON_PULLBACK", "HOLD")

TOP_N = int(os.getenv("SHADOW_BATCH_TOP_N", "50"))
CONCURRENCY = int(os.getenv("SHADOW_BATCH_CONCURRENCY", "3"))
FRESH_HOURS = float(os.getenv("SHADOW_BATCH_FRESH_HOURS", "12"))
HARD_CAP = int(os.getenv("SHADOW_BATCH_HARD_CAP", "150"))   # absolute safety ceiling
STATUS_FILE = PROJECT_ROOT / "data" / "runtime" / "shadow_batch_status.json"


def _now():
    return datetime.now(timezone.utc)


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def select_targets(top_n: int = TOP_N) -> dict:
    """The bounded target set: starred ∪ top-N-by-rank(eligible ratings).

    Returns the set plus provenance so the caller can show WHY each symbol is in.
    Deterministic, read-only.
    """
    conn = _conn()
    cur = conn.cursor()
    ratings = "(" + ",".join("'%s'" % r for r in ELIGIBLE_RATINGS) + ")"

    # top N by hermes rank among eligible-rated names
    cur.execute(f"""
        SELECT DISTINCT ON (wi.symbol) wi.symbol, wi.hermes_rank,
               UPPER(COALESCE(fs.recommendation, rc.latest_recommendation)) AS rec
        FROM watchlist_items wi
        LEFT JOIN watchlist_final_synthesis fs ON UPPER(fs.symbol)=UPPER(wi.symbol)
        LEFT JOIN watchlist_research_cards rc ON rc.symbol=wi.symbol
        WHERE wi.status <> 'removed' AND wi.symbol ~ '^[A-Z]{{1,5}}$'
          AND UPPER(COALESCE(fs.recommendation, rc.latest_recommendation)) IN {ratings}
        ORDER BY wi.symbol, wi.hermes_rank NULLS LAST
    """)
    rated = {r[0].upper(): {"symbol": r[0].upper(), "hermes_rank": r[1], "rec": r[2]}
             for r in cur.fetchall()}
    # rank across the whole rated set, then take top N
    top = sorted(rated.values(),
                 key=lambda d: (d["hermes_rank"] is None, d["hermes_rank"] or 1e9))[:top_n]
    top_syms = {d["symbol"] for d in top}

    cur.execute("SELECT DISTINCT UPPER(symbol) FROM operator_starred_symbols")
    starred = {r[0] for r in cur.fetchall()}

    members = {}
    for d in top:
        members[d["symbol"]] = {"symbol": d["symbol"], "reason": "top_rank",
                                "hermes_rank": d["hermes_rank"], "rec": d["rec"]}
    for s in starred:
        if s in members:
            members[s]["reason"] = "top_rank+starred"
        else:
            members[s] = {"symbol": s, "reason": "starred",
                          "hermes_rank": (rated.get(s) or {}).get("hermes_rank"),
                          "rec": (rated.get(s) or {}).get("rec")}

    eligible_total = len(rated)
    dropped = max(0, eligible_total - len(top_syms))   # rated names below the top-N cut
    return {"members": sorted(members.values(), key=lambda d: (d["reason"] != "starred",
                                                               d["hermes_rank"] or 1e9)),
            "top_n": top_n, "starred": len(starred),
            "eligible_total": eligible_total, "dropped_below_cap": dropped}


def _fresh_symbols(symbols: list, hours: float) -> set:
    """Symbols with a live packet younger than `hours` — skipped as already fresh."""
    if not symbols:
        return set()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT upper(symbol) FROM decision_packets
                   WHERE superseded_by IS NULL
                     AND generated_at > now() - (%s || ' hours')::interval
                     AND upper(symbol) = ANY(%s)""",
                (hours, [s.upper() for s in symbols]))
    return {r[0] for r in cur.fetchall()}


def _generate_one(symbol: str) -> dict:
    """Evaluate + persist one packet. Never raises — a batch must not die on one
    symbol; the failure is recorded and the run continues."""
    try:
        import shadow_decision_service as svc
        pkt = svc.evaluate(symbol, run_models=True, origin="batch")
        pid = svc.persist(pkt, origin="batch")
        mr = pkt.get("model_review") or {}
        return {"symbol": symbol, "ok": True, "packet_id": pid,
                "model_mode": mr.get("mode"),
                "lanes": len(mr.get("lanes_completed") or [])}
    except Exception as exc:
        return {"symbol": symbol, "ok": False,
                "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _write_status(status: dict):
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(status, default=str))
    except Exception:
        pass


def run(*, top_n: int = TOP_N, dry_run: bool = False, force: bool = False,
        concurrency: int = CONCURRENCY, fresh_hours: float = FRESH_HOURS) -> dict:
    sel = select_targets(top_n)
    members = sel["members"]
    if len(members) > HARD_CAP:
        members = members[:HARD_CAP]
    symbols = [m["symbol"] for m in members]

    fresh = set() if force else _fresh_symbols(symbols, fresh_hours)
    todo = [s for s in symbols if s not in fresh]

    summary = {
        "authorised": "operator 2026-07-21: top N by rank (eligible ratings) + all starred",
        "eligible_ratings": list(ELIGIBLE_RATINGS),
        "top_n": top_n, "concurrency": concurrency, "fresh_hours": fresh_hours,
        "target_count": len(symbols), "starred_count": sel["starred"],
        "eligible_total": sel["eligible_total"],
        "dropped_below_cap": sel["dropped_below_cap"],
        "already_fresh_skipped": len(fresh),
        "to_generate": len(todo), "members": members,
        "started_at": _now().isoformat(), "state": "dry_run" if dry_run else "running",
    }
    if sel["dropped_below_cap"]:
        print(f"[batch] NOTE: {sel['dropped_below_cap']} eligible-rated symbols are below the "
              f"top-{top_n} cut and were NOT included (raise --top to cover more).")

    if dry_run:
        summary["state"] = "dry_run"
        _write_status(summary)
        return summary

    _write_status(summary)
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(_generate_one, s): s for s in todo}
        done = 0
        for fut in as_completed(futs):
            r = fut.result(); results.append(r); done += 1
            summary["done"] = done
            summary["last"] = r
            _write_status(summary)
            print(f"[batch] {done}/{len(todo)} {r['symbol']} "
                  f"{'ok packet ' + str(r.get('packet_id')) if r['ok'] else 'FAILED ' + r.get('error','')}")

    ok = [r for r in results if r["ok"]]
    summary.update(state="complete", completed_at=_now().isoformat(),
                   generated=len(ok), failed=len(results) - len(ok),
                   results=results)
    _write_status(summary)
    return summary


def status() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text()) if STATUS_FILE.exists() else {"state": "never_run"}
    except Exception:
        return {"state": "unreadable"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Bounded shadow decision-packet batch generator")
    ap.add_argument("--dry-run", action="store_true", help="print the target set, spend nothing")
    ap.add_argument("--run", action="store_true", help="generate packets")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--top", type=int, default=TOP_N)
    ap.add_argument("--force", action="store_true", help="ignore freshness, regenerate all")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.status:
        out = status()
    elif args.dry_run:
        out = run(top_n=args.top, dry_run=True)
    elif args.run:
        out = run(top_n=args.top, force=args.force)
    else:
        out = {"error": "specify --dry-run, --run, or --status"}

    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"\n  state={out.get('state')} target={out.get('target_count')} "
              f"to_generate={out.get('to_generate')} "
              f"already_fresh={out.get('already_fresh_skipped')} "
              f"generated={out.get('generated')} failed={out.get('failed')}")
        if out.get("state") in ("dry_run",):
            print("  members (reason · rank · rec):")
            for m in out.get("members", [])[:80]:
                print(f"    {m['symbol']:6s} {m['reason']:16s} rank={m.get('hermes_rank')} rec={m.get('rec')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
