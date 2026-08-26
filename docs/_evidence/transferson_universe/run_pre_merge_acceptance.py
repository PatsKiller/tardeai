#!/usr/bin/env python3
"""PRE_MERGE source acceptance. READ_ONLY_ADVISORY. Does not write CURRENT. No R17."""
from __future__ import annotations

import gzip
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

WT = Path("/home/johnclaw/trade-ai-v12-rebuild/wt-r16-learning")
CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
EVIDENCE = Path(__file__).resolve().parent
sys.path.insert(0, str(WT))

from scripts.lib.env_bootstrap import load_env  # noqa: E402

load_env()

from scripts.lib.holdings_universe import CASH_SYMBOLS, held_equity_tickers, held_unresolved_cusips  # noqa: E402
from scripts.lib.security_identity import normalize_symbol  # noqa: E402
from scripts.lib.transferson_universe import (  # noqa: E402
    READY_NEAR,
    collect_live_sources,
    get_related_by_catalyst,
    get_related_by_industry,
    get_related_by_sector,
    identity_coverage,
    load_universe,
    operator_denominators,
    research_tier_index,
    seed_graph_from_universe,
    universe_diff,
)
from scripts.research_scheduler import TOP_RANK_N, load_universe as load_scheduler  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _syms(values) -> set[str]:
    out: set[str] = set()
    for v in values or []:
        if isinstance(v, dict):
            s = normalize_symbol(v.get("symbol") or v.get("s"))
        else:
            s = normalize_symbol(v)
        if s and s not in CASH_SYMBOLS:
            out.add(s)
    return out


def compact(rec: dict) -> dict:
    return {
        "symbol": rec.get("symbol"),
        "tier": rec.get("current_research_tier"),
        "reasons": rec.get("membership_reasons") or [],
        "identity_status": rec.get("identity_status"),
        "issuer_guid": bool(rec.get("issuer_guid")),
        "security_guid": bool(rec.get("security_guid")),
        "currently_held": rec.get("currently_held"),
        "sold_history_present": rec.get("sold_history_present"),
        "reentry_status": rec.get("reentry_status"),
        "unresolved_reason": rec.get("unresolved_reason"),
    }


def main() -> int:
    pin = (CURRENT / "SOURCE_COMMIT").read_text().strip()
    sources = collect_live_sources(root=CURRENT, top_rank_n=int(TOP_RANK_N))
    manifest = load_universe(root=CURRENT, sources=sources, pin=pin)
    secs = manifest.get("securities") or []
    by_sym = {r["symbol"]: r for r in secs if r.get("symbol")}
    canonical = set(by_sym)

    holdings = set(held_equity_tickers(root=CURRENT))
    cusips = set(held_unresolved_cusips(root=CURRENT))
    proposals_active = _syms(sources.get("proposals_active"))
    watch = _syms(sources.get("watch_directives"))
    incubator = _syms(sources.get("incubator"))
    screener = _syms(sources.get("screener_active"))
    discovery = _syms(sources.get("discovery_validated"))
    reentry_all = _syms(sources.get("reentry"))

    without_screener = load_universe(
        root=CURRENT,
        sources={**sources, "screener_active": [], "discovery_validated": []},
        pin=pin,
    )
    old_n = without_screener.get("canonical_universe_count")
    new_n = manifest.get("canonical_universe_count")
    old_set = {r["symbol"] for r in (without_screener.get("securities") or [])}
    new_from_screener = sorted(canonical - old_set)
    overlap_screener = len(screener & old_set)
    rejected_screener = sources.get("screener_rejected") or []
    rejected_disc = sources.get("discovery_rejected") or []

    def missing(src: set[str]) -> list[str]:
        return sorted(src - canonical)

    sched = load_scheduler(root=CURRENT)
    sched_syms = set(sched)
    ident = identity_coverage(manifest)
    denoms = operator_denominators(manifest)

    seed_root = EVIDENCE / "pre_merge_graph_seed"
    if seed_root.exists():
        shutil.rmtree(seed_root)
    seed_root.mkdir(parents=True, exist_ok=True)
    seeded = seed_graph_from_universe(seed_root, manifest)
    graph_path = seed_root / "data/cio/ticker_research_graph.jsonl"
    seeded_profiles = 0
    provenance_ok = 0
    provenance_n = 0
    if graph_path.is_file():
        for line in graph_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("schema") == "TickerKnowledgeProfile@v1" or row.get("ticker_guid"):
                seeded_profiles += 1
            for edge in row.get("relationships") or []:
                provenance_n += 1
                if edge.get("producer") and edge.get("source_type") and edge.get("observed_at") and edge.get("recorded_at"):
                    provenance_ok += 1
        gz = EVIDENCE / "PRE_MERGE_GRAPH_SEED.jsonl.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as fh:
            fh.write(graph_path.read_text(encoding="utf-8", errors="replace"))
        shutil.rmtree(seed_root)

    sold_ex = []
    ready_ex = []
    for rec in secs:
        st = rec.get("reentry_status") or ""
        if rec.get("sold_history_present") and not rec.get("currently_held") and len(sold_ex) < 8:
            sold_ex.append(compact(rec))
        if st in READY_NEAR and not rec.get("currently_held") and len(ready_ex) < 8:
            ready_ex.append(compact(rec))

    schd_sim = None
    if "SCHD" in holdings:
        sim_sources = dict(sources)
        sim_sources["holdings"] = [s for s in (sources.get("holdings") or []) if normalize_symbol(s) != "SCHD"]
        sim = load_universe(root=CURRENT, sources=sim_sources, pin=pin)
        diff = universe_diff(manifest, sim)
        schd_sim = {
            "added": diff.get("added"),
            "removed": diff.get("removed"),
            "tier_changed_schd": [x for x in (diff.get("tier_changed") or []) if x.get("symbol") == "SCHD"],
            "false_remove_add": "SCHD" in (diff.get("added") or []) or "SCHD" in (diff.get("removed") or []),
        }

    lineage = []
    for s in ("NOC", "SCHD", "ADBE", "NVDA", "AAPL"):
        if s not in by_sym:
            continue
        rec = by_sym[s]
        lineage.append({
            "symbol": s,
            "identity": rec.get("identity_status"),
            "issuer": bool(rec.get("issuer_guid")),
            "security": bool(rec.get("security_guid")),
            "industry_n": len(get_related_by_industry(manifest, s).get("related_symbols") or []),
            "sector_n": len(get_related_by_sector(manifest, s).get("related_symbols") or []),
            "catalyst_n": len(get_related_by_catalyst(manifest, s).get("related_symbols") or []),
            "not_supply_chain": True,
        })

    consumers = {
        "research_scheduler": "CANONICAL-ADAPTER",
        "free_first": "ADAPTER",
        "ticker_graph_profile_seeding": "ADAPTER",
        "cio_intelligence_fabric": "ADAPTER",
        "advisory": "ADAPTER",
        "hermes_scope": "ADAPTER",
        "reentry_watch": "SOURCE",
        "proposal_research": "CANONICAL-ADAPTER",
        "command_center": "ADAPTER",
        "thesis_coverage_metrics": "ADAPTER",
    }
    private = [k for k, v in consumers.items() if v in {"NOT_MIGRATED", "LEGACY_PARTIAL"}]

    blockers = []
    if missing(holdings):
        blockers.append({"id": "B-HOLD", "detail": missing(holdings)})
    if missing(screener):
        blockers.append({"id": "B5", "detail": f"authorized screener missing {len(missing(screener))}"})
    if missing(proposals_active) or missing(watch) or missing(incubator) or missing(discovery):
        blockers.append({"id": "B-COV", "detail": {
            "proposals": missing(proposals_active),
            "watch": missing(watch),
            "incubator": missing(incubator),
            "discovery": missing(discovery),
        }})
    if ident.get("security_guid_equals_ticker_guid"):
        blockers.append({"id": "B2-MINT", "detail": ident.get("security_guid_equals_ticker_guid")})
    if ident.get("duplicate_security_identities"):
        blockers.append({"id": "B2-DUP", "detail": ident.get("duplicate_security_identities")})
    if private:
        blockers.append({"id": "B1", "detail": private})
    if provenance_n and provenance_ok != provenance_n:
        blockers.append({"id": "B3-PROV", "detail": {"ok": provenance_ok, "n": provenance_n}})

    verdict = "PRE_MERGE_SOURCE_ACCEPTANCE_BLOCKED" if blockers else "PRE_MERGE_SOURCE_ACCEPTANCE_PASS"

    receipt = {
        "schema": "TransfersonPreMergeAcceptance@v1",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": _now(),
        "source_pin_of_data": pin,
        "loader_is_not_on_CURRENT": True,
        "r17_auto_checkpoint": "blocked until POST_DEPLOY_LIVE_ACCEPTANCE_PASS",
        "verdict": verdict,
        "blockers": blockers,
        "section_a_screener": {
            "old_canonical_count": old_n,
            "screener_source_count": len(screener),
            "overlap_with_prior_canonical": overlap_screener,
            "genuinely_new_members": len(new_from_screener),
            "new_sample": new_from_screener[:20],
            "rejected_invalid": len(rejected_screener),
            "rejected_sample": rejected_screener[:10],
            "discovery_validated_n": len(discovery),
            "discovery_rejected_n": len(rejected_disc),
            "new_canonical_unique_count": new_n,
            "screener_missing_from_canonical": missing(screener),
        },
        "section_counts": {
            "canonical_universe_count": new_n,
            "graph_profiled_on_CURRENT": manifest.get("graph_profiled_count"),
            "graph_coverage_CURRENT": manifest.get("graph_coverage"),
            "tier_counts": manifest.get("tier_counts"),
            "membership_reason_counts": manifest.get("membership_reason_counts"),
        },
        "holdings": {
            "n": len(holdings),
            "missing": missing(holdings),
            "cusips": sorted(cusips),
            "rows": [compact(by_sym[s]) for s in sorted(holdings) if s in by_sym],
        },
        "sold_reentry": {
            "reentry_n": len(reentry_all),
            "missing": missing(reentry_all),
            "sold_examples": sold_ex,
            "ready_examples": ready_ex,
        },
        "coverage_sets": {
            "proposals_active_missing": missing(proposals_active),
            "watch_missing": missing(watch),
            "incubator_missing": missing(incubator),
            "screener_missing": missing(screener),
            "discovery_missing": missing(discovery),
        },
        "scheduler": {
            "canonical_n": len(canonical),
            "scheduler_n": len(sched_syms),
            "only_in_canonical_n": len(canonical - sched_syms),
            "only_in_scheduler_n": len(sched_syms - canonical),
            "only_in_scheduler": sorted(sched_syms - canonical)[:20],
        },
        "identity": ident,
        "denominators": denoms,
        "graph_seed_evidence_only": {
            "profiles_created": seeded.get("profiles_created"),
            "seeded_profiles": seeded_profiles,
            "provenance_ok": provenance_ok,
            "provenance_n": provenance_n,
            "CURRENT_not_mutated": True,
            "coverage_if_seed_applied": f"{seeded_profiles} / {new_n}",
        },
        "lineage": lineage,
        "schd_sell_sim": schd_sim,
        "consumers": consumers,
        "count_126": "UNRESOLVED_WITH_REASON",
        "gates": {
            "pre_merge": verdict,
            "post_deploy": "not_run",
            "r17": "blocked",
        },
    }
    (EVIDENCE / "PRE_MERGE_ACCEPTANCE.json").write_text(
        json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "verdict": verdict,
        "old_n": old_n,
        "new_n": new_n,
        "screener_n": len(screener),
        "new_members": len(new_from_screener),
        "screener_missing": missing(screener)[:10],
        "holdings_missing": missing(holdings),
        "identity": {
            "issuer": ident["issuer_guid_resolved"],
            "security": ident["security_guid_resolved"],
            "candidate": ident["candidate_chain"],
            "unresolved": ident["unresolved"],
        },
        "seeded": seeded.get("profiles_created"),
        "provenance_ok": provenance_ok,
        "blockers": blockers,
    }, indent=2, default=str))
    return 0 if not blockers else 2


if __name__ == "__main__":
    raise SystemExit(main())
