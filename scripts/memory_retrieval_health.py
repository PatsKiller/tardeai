#!/usr/bin/env python3
"""memory-retrieval-health — the memory SHADOW contracts and the retrieval counterfactual (LQ-20261107-1614).

PROCESS   n8n lane ``memory-retrieval-health``, every 6 h, LaneRunReceipt@v2 under --apply. Reads the newest
          RECEIPT_WINDOW retrieval receipts, the contradiction verdicts/candidates and the Hermes results.
CONTRACT  two contracts, each OK / DEGRADED / BROKEN / UNVERIFIABLE; the run verdict is the worst of the two.
          embedding_step  ladder step 7 can hit:   OK hits > 0 in the window
                                                   DEGRADED it ran (cause miss) and never hit
                                                   BROKEN it never ran (flag_off / not_installed / error) on every
                                                          receipt of the window
                                                   UNVERIFIABLE fewer than MIN_RECEIPTS receipts
          adjudicator     a confirmed contradiction (LEFT/RIGHT/BOTH_STALE) is reachable:
                          contradiction_adjudicator.health()
          The counterfactual (would reusing memory have changed the answer, and was the change right) is a
          measurement, not a verdict.
HEAL      none automatic. One ``system_health`` warning per ESCALATION_COOLDOWN_H when a contract is BROKEN, under
          --apply. It may NOT set TRADEAI_EMBEDDINGS, index embeddings, re-run the adjudicator, or touch ENFORCE:
          those are a lane owner's change or the operator's decision.

Dry run is the default (reads only, nothing written, nothing escalated). ``--prices`` adds the forward-return
check through a read-only DB session. MBI_BEHAVIOR = 0; memory never changes an answer here.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "scripts", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import contradiction_adjudicator as ca  # noqa: E402

LANE_ID = "memory-retrieval-health"
ESCALATION_SOURCE = "memory_retrieval_health.py"
ESCALATION_COOLDOWN_H = 24
RECEIPT_WINDOW = 2000
MIN_RECEIPTS = 50
NOT_RUN_CAUSES = ("flag_off", "not_installed")
DIRECTION = {"STRENGTHENS": 1, "CONFIRMS": 1, "WEAKENS": -1}
FORWARD_SESSIONS = 5
DEAD_BAND = 0.01
RANK = {"OK": 0, "UNVERIFIABLE": 1, "DEGRADED": 2, "BROKEN": 3}


def tail_jsonl(path: Path, n: int) -> list[dict]:
    out: collections.deque = collections.deque(maxlen=n)
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                out.append(line)
    except OSError:
        return []
    rows = []
    for line in out:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def embedding_contract(receipts: Iterable[Mapping[str, Any]]) -> dict:
    causes: collections.Counter = collections.Counter()
    hits = n = 0
    for r in receipts:
        step = next((s for s in r.get("ladder") or [] if s.get("step") == 7), None)
        if step is None:
            continue
        n += 1
        hits += bool(step.get("hit"))
        causes[str(step.get("cause") or step.get("note") or "unknown")] += 1
    out = {"receipts": n, "hits": hits, "causes": dict(causes)}
    if n < MIN_RECEIPTS:
        return {**out, "verdict": "UNVERIFIABLE", "reason": "insufficient_receipts"}
    if hits:
        return {**out, "verdict": "OK", "reason": "step7_hits"}
    ran = sum(v for k, v in causes.items() if k in ("miss", "hit"))
    if ran:
        return {**out, "verdict": "DEGRADED", "reason": "step7_ran_never_hit"}
    errors = sum(v for k, v in causes.items() if k.startswith("error:"))
    return {**out, "verdict": "BROKEN", "reason": "step7_errors" if errors else "step7_never_ran"}


def _ts(r: Mapping[str, Any]) -> str:
    return str(r.get("completed_ts") or r.get("as_of") or "")


def counterfactual(results: list[dict], receipts_by_id: Mapping[str, Mapping[str, Any]]) -> dict:
    """For each generated result linked to its retrieval receipt: the newest earlier artifact the ladder reached
    (steps 1/3 + reused refs) is what memory would have answered. Same (classification, stance) = the paid call
    added nothing; a changed direction is a case for :func:`score_cases`."""
    by_id: dict[str, dict] = {}
    for r in results:
        for k in ("result_id", "research_id"):
            if r.get(k):
                by_id.setdefault(str(r[k]), r)
    c: collections.Counter = collections.Counter()
    by_decision: dict[str, collections.Counter] = {}
    cases: list[dict] = []
    for r in results:
        rc = receipts_by_id.get(str(r.get("retrieval_receipt_id") or ""))
        if rc is None:
            c["unlinked"] += 1
            continue
        refs = list(rc.get("reused_refs") or [])
        refs += [x for s in rc.get("ladder") or [] if s.get("step") in (1, 3) for x in s.get("refs") or []]
        prior = [by_id[x] for x in refs if x in by_id and by_id[x] is not r and _ts(by_id[x]) < _ts(r)]
        if not prior:
            c["no_prior_artifact"] += 1
            continue
        p = max(prior, key=_ts)
        same = (p.get("classification"), p.get("thesis_stance")) == (r.get("classification"), r.get("thesis_stance"))
        key = "same_conclusion" if same else "changed_conclusion"
        c[key] += 1
        by_decision.setdefault(str(rc.get("decision")), collections.Counter())[key] += 1
        so, sn = DIRECTION.get(p.get("classification"), 0), DIRECTION.get(r.get("classification"), 0)
        if so != sn and r.get("symbol"):
            cases.append({"symbol": str(r["symbol"]).upper(), "date": _ts(r)[:10], "memory_dir": so, "new_dir": sn,
                          "decision": rc.get("decision")})
    compared = c["same_conclusion"] + c["changed_conclusion"]
    return {"linked": len(results) - c["unlinked"], **dict(c), "compared": compared,
            "same_share": round(c["same_conclusion"] / compared, 4) if compared else None,
            "by_decision": {k: dict(v) for k, v in sorted(by_decision.items())},
            "directional_changes": len(cases), "_cases": cases}


def score_cases(cases: list[dict], closes: Callable[[str, str, int], list[float]]) -> dict:
    """Which side the FORWARD_SESSIONS-session return agreed with, outside a ±DEAD_BAND band."""
    out: collections.Counter = collections.Counter()
    for k in ("new_right", "memory_right", "neither", "flat", "no_forward_bars"):
        out[k] = 0
    for cs in cases:
        cl = closes(cs["symbol"], cs["date"], FORWARD_SESSIONS + 1)
        if len(cl) < FORWARD_SESSIONS + 1 or not cl[0]:
            out["no_forward_bars"] += 1
            continue
        ret = cl[FORWARD_SESSIONS] / cl[0] - 1
        move = 0 if abs(ret) < DEAD_BAND else (1 if ret > 0 else -1)
        if move == 0:
            out["flat"] += 1
        elif cs["new_dir"] == move:
            out["new_right"] += 1
        elif cs["memory_dir"] == move:
            out["memory_right"] += 1
        else:
            out["neither"] += 1
    return dict(out)


def _connect(read_only: bool):
    import psycopg2  # noqa: PLC0415

    kwargs: dict[str, Any] = {"dbname": os.getenv("DB_NAME", "trade_ai"), "user": os.getenv("DB_USER", "johnclaw"),
                              "host": os.getenv("DB_HOST", "/var/run/postgresql"), "connect_timeout": 10}
    if read_only:
        kwargs["options"] = "-c default_transaction_read_only=on"
    return psycopg2.connect(**kwargs)


def _db_closes(conn) -> Callable[[str, str, int], list[float]]:
    def closes(symbol: str, date: str, n: int) -> list[float]:
        with conn.cursor() as cur:
            cur.execute("SELECT close FROM market_ohlcv_bars WHERE timeframe = 'daily' AND symbol = %s "
                        "AND bar_time::date >= %s ORDER BY bar_time LIMIT %s", (symbol, date, n))
            return [float(x[0]) for x in cur.fetchall()]
    return closes


def _recently_escalated(conn, contract: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM alert_events WHERE source_script = %s AND alert_type = 'system_health' "
                    "AND parsed_payload->>'contract' = %s AND created_at > now() - make_interval(hours => %s) LIMIT 1",
                    (ESCALATION_SOURCE, contract, ESCALATION_COOLDOWN_H))
        return cur.fetchone() is not None


def _escalate_default(contract: str, result: Mapping[str, Any]) -> bool:
    from alert_event_writer import save_alert_event  # noqa: PLC0415

    return save_alert_event(
        alert_type="system_health", severity="warning", source_script=ESCALATION_SOURCE,
        raw_text=f"[{LANE_ID}] memory contract {contract} BROKEN: {result.get('reason')}",
        parsed_payload={"kind": "memory_contract", "contract": contract, "reason": result.get("reason")},
    ) is not None


def run(*, root: Path, apply: bool, prices: bool = False, conn=None,
        escalate: Callable[[str, Mapping[str, Any]], bool] = _escalate_default) -> dict:
    started = datetime.now(timezone.utc).isoformat()
    cio = root / "data" / "cio"
    receipts = tail_jsonl(cio / "retrieval_receipts.jsonl", RECEIPT_WINDOW)
    contracts = {
        "embedding_step": embedding_contract(receipts),
        "adjudicator": ca.health(ca.read_jsonl(ca.verdicts_path(root)),
                                 ca.read_jsonl(cio / "research_contradiction_candidates.jsonl", limit=400_000)),
    }
    all_receipts = {str(r.get("receipt_id")): r for r in ca.read_jsonl(cio / "retrieval_receipts.jsonl")
                    if r.get("receipt_id")}
    cf = counterfactual(ca.read_jsonl(cio / "hermes_research_results.jsonl"), all_receipts)
    cases = cf.pop("_cases")
    own = conn is None and (prices or apply)
    escalated: list[str] = []
    suppressed: list[str] = []
    try:
        if own:
            conn = _connect(read_only=not apply)
        if prices and conn is not None:
            cf["direction_vs_forward_return"] = score_cases(cases, _db_closes(conn))
            conn.rollback()
        if apply:
            for name, res in contracts.items():
                if res["verdict"] != "BROKEN":
                    continue
                if _recently_escalated(conn, name):
                    suppressed.append(name)
                elif escalate(name, res):
                    escalated.append(name)
            conn.commit()
    finally:
        if own and conn is not None:
            conn.close()
    verdict = max((c["verdict"] for c in contracts.values()), key=RANK.__getitem__)
    return {"lane_id": LANE_ID, "mode": "apply" if apply else "dry_run", "started_at": started, "verdict": verdict,
            "broken": sum(c["verdict"] == "BROKEN" for c in contracts.values()), "contracts": contracts, "counterfactual": cf, "escalated": escalated,
            "escalation_suppressed_cooldown": suppressed, "sends": 0, "memory_behavior_influence": 0}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0], allow_abbrev=False)
    ap.add_argument("--apply", action="store_true", help="escalate a BROKEN contract and write the receipt")
    ap.add_argument("--prices", action="store_true", help="score directional changes against forward returns (DB read)")
    ap.add_argument("--root", help="state root (default: the adjudicator's state root)")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else ca.state_root(dict(os.environ))
    summary = run(root=root, apply=a.apply, prices=a.prices)
    print(json.dumps(summary, indent=1, sort_keys=True, default=str))
    if a.apply:
        try:
            from scripts.lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415
        except ImportError:
            from lib.lane_last_receipt import write_lane_receipt  # type: ignore[no-redef]  # noqa: PLC0415
        write_lane_receipt(
            LANE_ID, ok=True, exit_code=0, started_at=summary["started_at"], script=__file__,
            summary={"verdict": summary["verdict"], "broken": summary["broken"], "escalated": summary["escalated"],
                     "contracts": {k: v["verdict"] for k, v in summary["contracts"].items()},
                     "same_share": summary["counterfactual"].get("same_share")},
            produced_count=len(summary["contracts"]), attempted_count=len(summary["contracts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
