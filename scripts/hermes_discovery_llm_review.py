#!/usr/bin/env python3
"""hermes_discovery_llm_review.py — CLI for the URDL Stage-2 LLM review lane.

Advisory-only: reviews discovery candidates (local gemma first, policy-gated
free-OAuth cloud escalation) and stores meta_json.llm_review_json + an
LLM_REVIEW audit row. NEVER changes candidate status — operators decide.

Usage:
  python3 scripts/hermes_discovery_llm_review.py --review-ready --limit 20 --json
      Review READY_FOR_REVIEW + NEEDS_VALIDATION candidates (highest
      discovery_score first), capped by llm_review_daily_cap.
  python3 scripts/hermes_discovery_llm_review.py --candidate-id 42 [--lanes local]
      Review one candidate.
  python3 scripts/hermes_discovery_llm_review.py --review-ready --dry-run
      Select + print what WOULD be reviewed (caps, escalation hints) — no
      LLM calls, no writes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.hermes_discovery import domains, llm_review  # noqa: E402


def _jsonable(obj):
    return json.loads(json.dumps(obj, default=str))


def _dry_row(cand: dict) -> dict:
    """What a review WOULD do for this candidate — computed without any LLM
    call (escalation hint = domain policy only; relevance ambiguity is only
    knowable after the local pass)."""
    meta = cand.get("meta_json") or {}
    domain = str(meta.get("research_domain") or "").strip().lower() \
        or domains.classify_domain(cand)
    try:
        policy = domains.domain_policy(domain)
    except domains.DomainConfigError:
        policy = {}
    return {
        "id": cand["id"], "candidate_type": cand["candidate_type"],
        "label": cand["label"], "status": cand["status"],
        "discovery_score": (float(cand["discovery_score"])
                            if cand.get("discovery_score") is not None else None),
        "domain": domain,
        "domain_llm_review_required": bool(policy.get("llm_review_required")),
        "professional_review_domain": bool(
            policy.get("requires_professional_review_label")),
        "already_reviewed": "llm_review_json" in (meta or {}),
        "ticker_validation": ((meta.get("ticker_validation") or {}).get("verdict")
                              if cand["candidate_type"] == "TICKER_CANDIDATE"
                              else None),
    }


def cmd_review_ready(limit: int, lanes: str, dry_run: bool, as_json: bool) -> int:
    batch = llm_review.select_review_batch(limit=limit)
    selected = batch["selected"]
    header = {k: batch[k] for k in ("daily_cap", "cloud_lane_daily_cap",
                                    "used_today", "remaining_today")}
    if dry_run:
        payload = {"dry_run": True, "lanes": lanes, **header,
                   "would_review": [_dry_row(c) for c in selected]}
        if as_json:
            print(json.dumps(_jsonable(payload), indent=2))
        else:
            print(f"DRY RUN — no LLM calls, no writes. lanes={lanes} "
                  f"cap={header['daily_cap']} used_today={header['used_today']} "
                  f"remaining={header['remaining_today']} "
                  f"cloud_cap={header['cloud_lane_daily_cap']}")
            if not payload["would_review"]:
                print("Nothing to review (empty selection or daily cap reached).")
            for r in payload["would_review"]:
                extra = " LLM-REVIEW-REQUIRED" if r["domain_llm_review_required"] else ""
                extra += " PRO-REVIEW" if r["professional_review_domain"] else ""
                extra += f" tv={r['ticker_validation']}" if r["ticker_validation"] else ""
                print(f"  #{r['id']} [{r['status']}] {r['candidate_type']} "
                      f"{r['label']!r} domain={r['domain']} "
                      f"score={r['discovery_score']}{extra}")
        return 0

    results = []
    for cand in selected:
        try:
            results.append(llm_review.review_candidate(cand["id"], lanes=lanes))
        except Exception as e:  # one bad candidate must not kill the batch
            results.append({"ok": False, "candidate_id": cand["id"],
                            "error": str(e)[:200]})
    payload = {**header, "lanes": lanes, "reviewed": len(results),
               "results": results}
    if as_json:
        print(json.dumps(_jsonable(payload), indent=2))
    else:
        print(f"Reviewed {len(results)} candidate(s) "
              f"(cap {header['daily_cap']}, used today {header['used_today']}).")
        for r in results:
            if r.get("ok"):
                rv = r["llm_review_json"]
                print(f"  #{r['candidate_id']} OK action={rv['recommended_action']} "
                      f"conf={rv['confidence']} lanes={','.join(r['lanes_used'])} "
                      f"status={r['status']} (unchanged)")
            else:
                print(f"  #{r['candidate_id']} FAILED: {r.get('error')} "
                      f"{r.get('detail', '')}")
    return 0 if all(r.get("ok") for r in results) or not results else 1


def cmd_candidate(candidate_id: int, lanes: str, dry_run: bool, as_json: bool) -> int:
    if dry_run:
        from lib.hermes_discovery import inbox
        cand = inbox.get_candidate(candidate_id)
        if not cand:
            print(f"candidate {candidate_id} not found", file=sys.stderr)
            return 1
        payload = {"dry_run": True, "lanes": lanes, "would_review": _dry_row(cand)}
        print(json.dumps(_jsonable(payload), indent=2) if as_json
              else f"DRY RUN {json.dumps(_jsonable(payload['would_review']))}")
        return 0
    result = llm_review.review_candidate(candidate_id, lanes=lanes)
    print(json.dumps(_jsonable(result), indent=2))
    return 0 if result.get("ok") else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--review-ready", action="store_true",
                    help="review the READY_FOR_REVIEW + NEEDS_VALIDATION queue")
    ap.add_argument("--candidate-id", type=int, help="review one candidate by id")
    ap.add_argument("--limit", type=int, default=20,
                    help="max candidates this run (further capped by "
                         "llm_review_daily_cap; default 20)")
    ap.add_argument("--lanes", choices=("auto", "local"), default="auto",
                    help="'auto' = local + policy-gated cloud escalation; "
                         "'local' = never cloud (default auto)")
    ap.add_argument("--dry-run", action="store_true",
                    help="select + print only — no LLM calls, no writes")
    ap.add_argument("--json", action="store_true", help="JSON output")
    args = ap.parse_args()

    if args.candidate_id is not None:
        return cmd_candidate(args.candidate_id, args.lanes, args.dry_run, args.json)
    if args.review_ready:
        return cmd_review_ready(args.limit, args.lanes, args.dry_run, args.json)
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
