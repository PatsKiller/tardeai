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
import fcntl
import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

LOCK_PATH = "/tmp/shadow_batch.lock"

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


# Evidence conditions that qualify a symbol for analysis — NONE is the legacy
# label. The label gated the first version and recreated the original circular
# defect: an IGNORE/AVOID verdict blocked the very analysis that could revise it.
# Here the label is a SORT feature only (see _label_rank); access is by evidence.
INTEREST_MOVE_PCT = float(os.getenv("SHADOW_BATCH_MOVE_PCT", "5.0"))
INTEREST_MOVE_RVOL = float(os.getenv("SHADOW_BATCH_MOVE_RVOL", "2.0"))
CATALYST_DAYS = int(os.getenv("SHADOW_BATCH_CATALYST_DAYS", "3"))
CATALYST_CONF = float(os.getenv("SHADOW_BATCH_CATALYST_CONF", "0.7"))

# Rough per-symbol cost for the dry-run estimate: 2 cloud lanes per blind pass.
LANE_CALLS_PER_SYMBOL = 2


def _held_symbols() -> set:
    try:
        path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        d = json.loads(path.read_text()) if path.exists() else {}
        return {str(r.get("symbol", "")).upper()
                for r in (d.get("holdings") or [])
                if (r.get("market_value") or 0) or (r.get("quantity") or r.get("shares") or 0)}
    except Exception:
        return set()


def select_targets(top_n: int = TOP_N) -> dict:
    """Evidence-based target set. A symbol qualifies on any governed evidence of
    interest; the legacy recommendation affects ORDERING only, never inclusion.

    Deterministic, read-only. Returns members (each with its evidence reasons),
    the full composition report, and a cost estimate — so a dry run shows exactly
    what will be spent and WHY each symbol is in, before any model call.
    """
    conn = _conn()
    cur = conn.cursor()

    # One pass over the watchlist collecting every evidence signal per symbol.
    cur.execute("""
        SELECT UPPER(wi.symbol) AS symbol, wi.hermes_rank,
               UPPER(COALESCE(fs.recommendation, rc.latest_recommendation)) AS rec,
               COALESCE(wi.in_directive_watch, false) AS directive,
               UPPER(COALESCE(wi.scope_tier, '')) = 'S1' AS s1,
               (ABS(COALESCE(wi.change_pct,0)) >= %s AND COALESCE(wi.rvol,0) >= %s) AS moved,
               EXISTS (SELECT 1 FROM operator_starred_symbols s
                       WHERE UPPER(s.symbol) = UPPER(wi.symbol)) AS starred,
               EXISTS (SELECT 1 FROM catalyst_events ce
                       WHERE UPPER(ce.symbol) = UPPER(wi.symbol)
                         AND ce.catalyst_type <> 'other'
                         AND ce.published_at > now() - (%s || ' days')::interval
                         AND COALESCE(ce.confidence,0) >= %s) AS catalyst,
               EXISTS (SELECT 1 FROM decision_packets dp
                       WHERE UPPER(dp.symbol) = UPPER(wi.symbol)
                         AND dp.superseded_by IS NULL) AS has_packet
        FROM watchlist_items wi
        LEFT JOIN watchlist_final_synthesis fs ON UPPER(fs.symbol)=UPPER(wi.symbol)
        LEFT JOIN watchlist_research_cards rc ON rc.symbol=wi.symbol
        WHERE wi.status <> 'removed' AND wi.symbol ~ '^[A-Z]{1,5}$'
    """, (INTEREST_MOVE_PCT, INTEREST_MOVE_RVOL, CATALYST_DAYS, CATALYST_CONF))

    held = _held_symbols()
    rows = {}
    for r in cur.fetchall():
        sym, rank, rec, directive, s1, moved, starred, catalyst, has_pkt = r
        reasons = []
        if starred: reasons.append("starred")
        if directive: reasons.append("directive")
        if sym in held: reasons.append("held")
        if moved: reasons.append("material_move")
        if catalyst: reasons.append("catalyst")
        if s1: reasons.append("scope_s1")
        if not has_pkt: reasons.append("packet_absent")
        if reasons:
            rows[sym] = {"symbol": sym, "hermes_rank": rank, "rec": rec,
                         "reasons": reasons, "has_packet": has_pkt}

    # A held name not on the watchlist still qualifies (held is ground-truth interest).
    for sym in held:
        if sym not in rows:
            rows[sym] = {"symbol": sym, "hermes_rank": None, "rec": None,
                         "reasons": ["held"], "has_packet": False}

    def _label_rank(rec):
        # ORDERING only: buy-side first, then hold/neutral, then avoid/ignore last —
        # but every one is already INCLUDED. The label never gates access.
        order = {"STRONG_BUY": 0, "BUY": 1, "ADD": 1, "ADD_ON_PULLBACK": 2,
                 "HOLD": 3, "NEUTRAL": 4, "RESEARCH_MORE": 4,
                 "TRIM": 6, "SELL": 6, "AVOID": 7, "IGNORE": 7}
        return order.get(str(rec or "").upper(), 5)

    # Priority tiers by EVIDENCE strength — the legacy label is NOT a tier and is
    # only a final tiebreaker (so it cannot starve an IGNORE/AVOID name that has
    # real evidence). An unstarred IGNORE with a fresh catalyst or volume-
    # confirmed move sits in tier 2 and is selected on its own merits.
    def _priority(m):
        rs = set(m["reasons"])
        if "starred" in rs:                        tier = 0   # explicit operator interest
        elif "held" in rs:                         tier = 1   # ground-truth position
        elif rs & {"catalyst", "material_move"}:   tier = 2   # time-sensitive
        elif rs & {"directive", "scope_s1"}:       tier = 3   # governed watch
        else:                                      tier = 4   # packet-absent only
        return (tier, 0 if "packet_absent" in rs else 1,
                m["hermes_rank"] is None, m["hermes_rank"] or 1e9,
                _label_rank(m["rec"]))   # label: tiebreaker ONLY, never a gate

    ranked = sorted(rows.values(), key=_priority)
    selected = ranked[:top_n]
    deferred = ranked[top_n:]

    def _count(pool, reason):
        return sum(1 for m in pool if reason in m["reasons"])

    def _label_bucket(pool, labels):
        return sum(1 for m in pool if str(m["rec"] or "").upper() in labels)

    report = {
        "members": selected,
        "top_n": top_n,
        "total_qualifying": len(rows),
        "selected": len(selected),
        "deferred_by_cap": len(deferred),
        "by_reason": {r: _count(selected, r) for r in
                      ("starred", "directive", "held", "material_move",
                       "catalyst", "scope_s1", "packet_absent")},
        "starred": _count(selected, "starred"),
        "held": _count(selected, "held"),
        "catalyst": _count(selected, "catalyst"),
        "material_move": _count(selected, "material_move"),
        "legacy_buy_side": _label_bucket(selected, {"STRONG_BUY", "BUY", "ADD", "ADD_ON_PULLBACK", "HOLD"}),
        "legacy_ignore_avoid": _label_bucket(selected, {"IGNORE", "AVOID", "SELL", "TRIM"}),
        "est_lane_calls": len(selected) * LANE_CALLS_PER_SYMBOL,
        "est_cost_note": f"{len(selected) * LANE_CALLS_PER_SYMBOL} cloud-lane calls "
                         f"(2/symbol); free OAuth lanes — no per-call charge",
        # kept for back-compat with existing callers/tests
        "eligible_total": len(rows),
        "dropped_below_cap": len(deferred),
    }
    return report


def _fresh_symbols(symbols: list, hours: float) -> set:
    """(back-compat) symbols with a live packet younger than `hours`. The batch now
    uses classify_freshness() which also honours input-hash invalidation; this is
    retained for callers/tests that only want the coarse TTL view."""
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


def classify_freshness(symbols: list, hours: float) -> dict:
    """Split symbols into {fresh: [...], regenerate: {sym: reason}}.

    A symbol is FRESH only when its live packet is within TTL AND its input hash
    is unchanged AND there is no material price drift AND no newer catalyst — the
    full invalidation contract, not age alone. Everything else regenerates with an
    explicit reason, so a two-hour-old packet overtaken by a fresh catalyst or a
    material move is NOT silently skipped."""
    import packet_invalidation as inv
    if not symbols:
        return {"fresh": [], "regenerate": {}}
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol) AS s, packet, generated_at
                   FROM decision_packets
                   WHERE superseded_by IS NULL AND upper(symbol) = ANY(%s)
                   ORDER BY upper(symbol), generated_at DESC""",
                ([s.upper() for s in symbols],))
    live = {}
    for r in cur.fetchall():
        pkt = r[1] if isinstance(r[1], dict) else json.loads(r[1])
        live[r[0]] = (pkt, r[2])

    fresh, regen = [], {}
    for sym in {s.upper() for s in symbols}:
        if sym not in live:
            regen[sym] = "PACKET_ABSENT"
            continue
        pkt, gen = live[sym]
        try:
            current = inv.build_current_input_snapshot(sym, conn)
            res = inv.compare_packet_inputs(pkt, current, generated_at=str(gen), ttl_hours=hours)
            if res["inputs_match"]:
                fresh.append(sym)
            else:
                regen[sym] = ", ".join(res["invalidation_reasons"]) or "INPUT_HASH_MISMATCH"
        except Exception as exc:
            regen[sym] = f"INVALIDATION_CHECK_ERROR: {type(exc).__name__}"
    return {"fresh": fresh, "regenerate": regen}


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

    # Input-hash invalidation, not age alone: a symbol is skipped only when its
    # packet is genuinely current (within TTL, hash unchanged, no material drift,
    # no newer catalyst). Regenerations carry their exact reason.
    if force:
        fresh, regen_reasons = set(), {s: "forced" for s in symbols}
    else:
        _cls = classify_freshness(symbols, fresh_hours)
        fresh, regen_reasons = set(_cls["fresh"]), _cls["regenerate"]
    todo = [s for s in symbols if s not in fresh]

    # composition of WHY each regen fires — counted per invalidation reason CODE
    # across all regenerating symbols (a symbol may carry several).
    from collections import Counter as _Counter
    _regen_by_reason = _Counter()
    for _r in regen_reasons.values():
        for _code in str(_r).split(","):
            _regen_by_reason[_code.strip().split(" ")[0].split("(")[0]] += 1

    summary = {
        "authorised": "operator 2026-07-21: EVIDENCE-based eligibility (label is sort-only)",
        "eligibility": "star | directive | held | material-move+rvol | catalyst | scope-S1 | packet-absent",
        "invalidation": "ttl | packet_version | event/ownership/fundamentals hash | price_drift | fresh_catalyst",
        "regenerate_reasons": dict(regen_reasons),
        "regenerate_by_reason": dict(_regen_by_reason),
        "top_n": top_n, "concurrency": concurrency, "fresh_hours": fresh_hours,
        "target_count": len(symbols),
        "total_qualifying": sel["total_qualifying"], "selected": sel["selected"],
        "deferred_by_cap": sel["deferred_by_cap"], "by_reason": sel["by_reason"],
        "starred_count": sel["starred"], "held_count": sel["held"],
        "catalyst_count": sel["catalyst"], "material_move_count": sel["material_move"],
        "legacy_buy_side": sel["legacy_buy_side"],
        "legacy_ignore_avoid": sel["legacy_ignore_avoid"],
        "est_lane_calls": sel["est_lane_calls"], "est_cost_note": sel["est_cost_note"],
        "already_fresh_skipped": len(fresh),
        "to_generate": len(todo), "members": members,
        "started_at": _now().isoformat(), "state": "dry_run" if dry_run else "running",
    }
    if sel["deferred_by_cap"]:
        print(f"[batch] NOTE: {sel['deferred_by_cap']} qualifying symbols are below the "
              f"top-{top_n} cap and were deferred (raise --top to cover more). "
              f"NONE were excluded by their legacy label.")

    if dry_run:
        summary["state"] = "dry_run"
        _write_status(summary)
        return summary

    # Single-writer lock at the GENERATOR level, so no two runs overlap no matter
    # how they were launched — cron, the API button, or a manual invocation. A
    # first version put the lock only on the cron line, so a manual `--force` run
    # (no flock) overlapped the 08:15 cron and left the set half on the old
    # packet version. Harmless (idempotent, append-only) but messy; this prevents
    # it. A second run backs off rather than blocking.
    _lockf = open(LOCK_PATH, "w")
    try:
        fcntl.flock(_lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return {"ok": True, "state": "skipped_locked",
                "reason": "another batch run holds the lock"}

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
    try:
        fcntl.flock(_lockf, fcntl.LOCK_UN)
        _lockf.close()
    except Exception:
        pass
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
        print(f"\n  state={out.get('state')} qualifying={out.get('total_qualifying')} "
              f"selected={out.get('selected')} deferred={out.get('deferred_by_cap')} "
              f"to_generate={out.get('to_generate')} already_fresh={out.get('already_fresh_skipped')} "
              f"generated={out.get('generated')} failed={out.get('failed')}")
        if out.get("by_reason"):
            print(f"  by evidence reason: {out['by_reason']}")
            print(f"  legacy buy-side={out.get('legacy_buy_side')} "
                  f"ignore/avoid={out.get('legacy_ignore_avoid')} "
                  f"(label is sort-only, NOT a gate) · est {out.get('est_lane_calls')} lane calls")
        if out.get("state") == "dry_run":
            print("  members (evidence · rank · rec):")
            for m in out.get("members", [])[:80]:
                print(f"    {m['symbol']:6s} {'+'.join(m.get('reasons', [])):32s} "
                      f"rank={m.get('hermes_rank')} rec={m.get('rec')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
