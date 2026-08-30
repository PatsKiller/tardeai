#!/usr/bin/env python3
"""Regenerate plans the notify freshness guards refuse, so they deliver again.

On 2026-08-30, 35 of 42 open S6 plans were held back: 34 quoting cash figures
from the un-repriced $PROJ tree (578,10x against an actual 630,784.82, the bug
fixed in #663) and 8 carrying evidence older than the 14-day bar. Blocking them
was right. Leaving them blocked forever is not — the data underneath is now
correct, the plans simply never re-read it.

Two things made them un-self-healing:

  * `augment_multi_domain_evidence` only FILLED GAPS. A domain already present
    was skipped, so a plan enriched on 2026-08-11 quoted that day's cash
    forever. Fixed to take the newer snapshot.
  * nothing re-ran the deterministic narrative, and `summary` /
    `multi_domain_summary` are built from evidence facts — so refreshing the
    evidence regenerates the numbers with NO LLM CALL.

This tool therefore costs nothing and invents nothing: it re-reads the Data
Broker and rebuilds the template narrative from the refreshed facts.

LLM-narrated plans are SKIPPED by default. Rebuilding them deterministically
would replace richer prose with a template — defensible, since a correct
template beats a wrong essay, but it is a downgrade and the operator should
ask for it (--include-llm).

Dry-run by default. READ_ONLY_ADVISORY. MBI=0. No notify.

Usage:
  cd /home/johnclaw/trade-ai-releases/portfolio-server/CURRENT
  python3 scripts/cio_regenerate_stale_plans.py [--apply] [--include-llm] [--limit N]

  cwd MUST be the served release — CIOPlanStore uses a relative path.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

AUTHORITY = "READ_ONLY_ADVISORY"
NO_CONSUMER_REASON = (
    "operator CLI, run on demand or from cron like cio_draft_plan_hygiene.py; "
    "PlanRegeneration@v1 is a stdout receipt, not an ingested contract"
)
REGEN_REASON = "regenerated_stale_evidence"


def _blocked(plan: dict[str, Any]) -> str | None:
    from scripts.lib.cio_notify_freshness import stale_claim, stale_evidence
    hit = stale_claim(plan)
    if hit:
        return f"stale_cash:{hit['claimed']:.2f}"
    hit = stale_evidence(plan)
    if hit:
        return f"old_evidence:{hit['age_days']}d"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write PLAN_UPDATED (default dry-run)")
    ap.add_argument("--include-llm", action="store_true",
                    help="Also rebuild LLM-narrated plans as templates (a downgrade)")
    ap.add_argument("--situation", default="S6_CONCENTRATION_OR_DISPOSITION")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from scripts.api_v3_cio import get_cio_plans
    from scripts.lib.cio_plan_enrichment import (
        build_evidence_pack, template_narrative_from_plan,
    )
    from scripts.lib.cio_plans import CIOPlanStore

    # Refuse to run blind. augment_multi_domain_evidence is fail-soft: with no
    # Data Broker snapshot it silently refreshes nothing, and this tool would
    # then "regenerate" every plan back to the same stale numbers and report
    # success. That happened while developing this — running the tool from a
    # tree without data/ made `lib.data_broker` resolve somewhere empty.
    try:
        try:
            from lib.data_broker.cio_portfolio import get_cio_snapshot
        except Exception:
            from scripts.lib.data_broker.cio_portfolio import get_cio_snapshot  # type: ignore
        _snap = get_cio_snapshot(max_age_s=86400) or {}
        _doms = _snap.get("domains") or _snap
        _n = len(_doms) if isinstance(_doms, dict) else 0
    except Exception as exc:                                     # noqa: BLE001
        print(f"FATAL: Data Broker unavailable ({exc.__class__.__name__}); "
              f"refusing to regenerate against no evidence", file=sys.stderr)
        return 2
    # Domain COUNT is not enough: run from a tree without data/ and the broker
    # still returns 18 domains, with empty bodies. Check the field this tool
    # actually depends on.
    _cash = None
    if isinstance(_doms, dict):
        _raw = _doms.get("cash_buying_power") or {}
        _body = _raw.get("data") if isinstance(_raw.get("data"), dict) else _raw
        _cash = (_body or {}).get("total_cash")
    if _n < 3 or not isinstance(_cash, (int, float)):
        print(f"FATAL: Data Broker gave {_n} domains and "
              f"cash_buying_power.total_cash={_cash!r}; refusing to regenerate "
              f"against no evidence. Run from the served release "
              f"(cd .../portfolio-server/CURRENT) so `lib.data_broker` and the "
              f"plan store resolve to the served tree.", file=sys.stderr)
        return 2

    res = get_cio_plans(limit=900, situation_type=args.situation or None)
    plans = (res.get("plans") if isinstance(res, dict) else res) or []

    considered = regenerated = still_blocked = skipped_llm = failed = 0
    samples: list[dict[str, Any]] = []
    store = CIOPlanStore() if args.apply else None

    for plan in plans:
        reason = _blocked(plan)
        if not reason:
            continue
        considered += 1
        if str(plan.get("narrative_source")) == "llm" and not args.include_llm:
            skipped_llm += 1
            continue
        if args.limit and regenerated >= args.limit:
            break
        try:
            # Clear the old narrative BEFORE rebuilding. The template builder
            # folds the existing summary forward (pack["existing_summary"]), so
            # regenerating in place left the previous multi-domain line — and
            # its stale cash figure — embedded in `summary` even after
            # multi_domain_summary itself had been correctly refreshed.
            scratch = dict(plan)
            for _f in ("summary", "multi_domain_summary", "thesis_alignment"):
                scratch[_f] = ""
            pack = build_evidence_pack(scratch)
            narrative = template_narrative_from_plan(scratch, pack)
            fresh = dict(plan)
            for k in ("summary", "multi_domain_summary", "thesis_alignment",
                      "recommendation", "risks", "options"):
                if narrative.get(k) is not None:
                    fresh[k] = narrative[k]
            fresh["evidence_refs"] = pack.get("evidence_refs") or plan.get("evidence_refs")
            after = _blocked(fresh)
            if after:
                still_blocked += 1
                if len(samples) < 5:
                    samples.append({"plan_id": plan.get("plan_id"),
                                    "before": reason, "after": after})
                continue
            regenerated += 1
            if len(samples) < 5:
                samples.append({"plan_id": plan.get("plan_id"),
                                "before": reason, "after": "clear"})
            if store is not None:
                store.update_plan(
                    str(plan.get("plan_id")),
                    actor_id="cio_regenerate_stale_plans",
                    summary=fresh.get("summary"),
                    multi_domain_summary=fresh.get("multi_domain_summary"),
                    thesis_alignment=fresh.get("thesis_alignment"),
                    recommendation=fresh.get("recommendation"),
                    risks=fresh.get("risks"),
                    options=fresh.get("options"),
                    evidence_refs=fresh.get("evidence_refs"),
                    narrative_source="template",
                    revisit_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(),
                    status_reason=REGEN_REASON,
                )
        except Exception as exc:                                 # noqa: BLE001
            failed += 1
            if len(samples) < 5:
                samples.append({"plan_id": plan.get("plan_id"),
                                "error": exc.__class__.__name__})

    out = {
        "schema": "PlanRegeneration@v1",
        "authority": AUTHORITY,
        "situation": args.situation,
        "blocked_considered": considered,
        "regenerated": regenerated,
        "still_blocked": still_blocked,
        "skipped_llm_narratives": skipped_llm,
        "failed": failed,
        "apply": bool(args.apply),
        "financial_action": False,
        "notify": False,
        "samples": samples,
    }
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"blocked={considered} regenerated={regenerated} "
              f"still_blocked={still_blocked} skipped_llm={skipped_llm} "
              f"failed={failed} apply={args.apply}")
        for s in samples:
            print("  " + json.dumps(s, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
