#!/usr/bin/env python3
"""Live CURRENT/DB acceptance measurement for the canonical Transferson universe.

READ_ONLY_ADVISORY. No R17. No deploy. No remote push. No broker mutation.
Does not write into the CURRENT pin. Evidence is written next to this script.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

WT = Path("/home/johnclaw/trade-ai-v12-rebuild/wt-r16-learning")
CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
EVIDENCE = Path(__file__).resolve().parent
sys.path.insert(0, str(WT))

from scripts.lib.env_bootstrap import load_env  # noqa: E402

load_env()

from scripts.lib.holdings_universe import (  # noqa: E402
    CASH_SYMBOLS,
    held_equity_tickers,
    held_unresolved_cusips,
    is_held_equity_ticker,
)
from scripts.lib.security_identity import normalize_symbol  # noqa: E402
from scripts.lib.transferson_universe import (  # noqa: E402
    READY_NEAR,
    REENTRY_EXCLUDED_FROM_T1,
    SCHEDULER_REASONS,
    collect_live_sources,
    get_identity_lineage,
    get_related_by_catalyst,
    get_related_by_industry,
    get_related_by_sector,
    graph_coverage_report,
    load_universe,
    metrics as universe_metrics,
    research_tier_index,
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
        if s:
            out.add(s)
    return out


def _cashless(values: set[str]) -> set[str]:
    return {s for s in values if s not in CASH_SYMBOLS}


def _q(sql: str, params: tuple = ()):
    try:
        from scripts.db_adapter import _execute
        rows = _execute(sql, params, fetch="all")
        return [dict(r) for r in (rows or [])]
    except Exception as exc:
        return [{"_error": f"{type(exc).__name__}:{exc}"}]


def _uuid(ns: str, value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:{ns}:{value}"))


def compact_rec(rec: dict) -> dict:
    return {
        "symbol": rec.get("symbol"),
        "tier": rec.get("current_research_tier"),
        "reasons": rec.get("membership_reasons") or [],
        "sources": rec.get("membership_sources") or [],
        "identity_status": rec.get("identity_status"),
        "issuer_guid": rec.get("issuer_guid"),
        "security_guid": rec.get("security_guid"),
        "listing_guid": rec.get("listing_guid"),
        "ticker_guid": rec.get("ticker_guid"),
        "currently_held": rec.get("currently_held"),
        "historically_held": rec.get("historically_held"),
        "sold_history_present": rec.get("sold_history_present"),
        "reentry_status": rec.get("reentry_status"),
        "active_proposal": rec.get("active_proposal"),
        "watch_directive_active": rec.get("watch_directive_active"),
        "hermes_rank": rec.get("hermes_rank"),
        "incubator_status": rec.get("incubator_status"),
        "scope_governor_status": rec.get("scope_governor_status"),
        "sector": rec.get("sector"),
        "industry": rec.get("industry"),
        "catalyst_n": len(rec.get("catalyst_guids") or []),
        "unresolved_identity": rec.get("unresolved_identity"),
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
    reentry_all = _cashless(_syms(sources.get("reentry")))
    reentry_ready = set()
    reentry_wait = set()
    reentry_sold = set()
    reentry_states: dict[str, int] = Counter()
    for row in sources.get("reentry") or []:
        if not isinstance(row, dict):
            continue
        intel = row.get("intel") if isinstance(row.get("intel"), dict) else {}
        state = str(intel.get("state") or row.get("state") or row.get("status") or "").strip().upper()
        sym = normalize_symbol(row.get("symbol"))
        if not sym or sym in CASH_SYMBOLS:
            continue
        reentry_states[state or "EMPTY"] += 1
        held = row.get("held") is True
        if state in READY_NEAR and not held:
            reentry_ready.add(sym)
        if state in (REENTRY_EXCLUDED_FROM_T1 - {"CURRENTLY HELD"}) and not held:
            reentry_wait.add(sym)
            reentry_sold.add(sym)

    proposals_active = _cashless(_syms(sources.get("proposals_active")))
    proposals_recent = _cashless(_syms(sources.get("proposals_recent")))
    watch = _cashless(_syms(sources.get("watch_directives")))
    incubator = _cashless(_syms(sources.get("incubator")))
    profiles = _cashless(_syms(sources.get("symbol_profiles")))
    graph = _cashless(_syms(sources.get("graph_profiles")))
    ranks = sources.get("hermes_ranks") or {}
    hermes_all = _cashless(set(normalize_symbol(s) for s in ranks))
    hermes_t1 = set()
    for sym, rank in ranks.items():
        s = normalize_symbol(sym)
        if not s or s in CASH_SYMBOLS:
            continue
        try:
            if int(rank) <= int(TOP_RANK_N):
                hermes_t1.add(s)
        except (TypeError, ValueError):
            continue
    scope_s3 = _cashless(set(normalize_symbol(x) for x in (sources.get("scope_s3") or [])))

    membership_sets = {
        "holdings": holdings,
        "cusips": cusips,
        "reentry_all": reentry_all,
        "reentry_ready_near": reentry_ready,
        "reentry_wait_retained": reentry_wait,
        "proposals_active": proposals_active,
        "proposals_recent": proposals_recent,
        "watch_directives": watch,
        "hermes_rank_t1": hermes_t1,
        "hermes_rank_all": hermes_all,
        "incubator": incubator,
        "symbol_profiles": profiles,
        "graph_profiles": graph,
    }
    # Scope S3 is an overlay/demotion, not an add. Discovery queried separately.
    authorized_union = set()
    for key, s in membership_sets.items():
        if key in {"reentry_ready_near", "reentry_wait_retained", "hermes_rank_t1"}:
            continue  # subsets of reentry_all / hermes_rank_all
        authorized_union |= s
    only_in_union = sorted(authorized_union - canonical)
    only_in_canonical = sorted(canonical - authorized_union)

    def missing(src: set[str]) -> list[str]:
        return sorted(src - canonical)

    # Identity
    ident_status = Counter(r.get("identity_status") or "NONE" for r in secs)
    issuer_n = sum(1 for r in secs if r.get("issuer_guid"))
    security_n = sum(1 for r in secs if r.get("security_guid"))
    listing_n = sum(1 for r in secs if r.get("listing_guid"))
    ticker_only = [
        r["symbol"] for r in secs
        if r.get("ticker_guid") and not r.get("security_guid") and not r.get("issuer_guid") and not r.get("listing_guid")
    ]
    sg_eq_tg = [r["symbol"] for r in secs if r.get("security_guid") and r.get("security_guid") == r.get("ticker_guid")]
    minted_from_ticker = []
    for r in secs:
        sg = r.get("security_guid")
        sym = r.get("symbol")
        if not sg or not sym:
            continue
        suspects = {
            _uuid("ticker", sym),
            _uuid("ticker", sym.lower()),
            _uuid("security", sym),
            _uuid("security", f"{sym}|common|equity"),
            str(uuid.uuid5(uuid.NAMESPACE_URL, f"tradeai:ticker:{sym}")),
        }
        if r.get("ticker_guid"):
            suspects.add(r["ticker_guid"])
        if sg in suspects:
            minted_from_ticker.append(sym)
    sg_to_syms: dict[str, list[str]] = defaultdict(list)
    for r in secs:
        if r.get("security_guid"):
            sg_to_syms[r["security_guid"]].append(r["symbol"])
    duplicate_security = {k: v for k, v in sg_to_syms.items() if len(set(v)) > 1}
    share_class_pairs = []
    for a, b in [("GOOG", "GOOGL"), ("BRK.A", "BRK.B"), ("BF.A", "BF.B"), ("FOX", "FOXA")]:
        if a in by_sym and b in by_sym:
            share_class_pairs.append({
                "a": a, "b": b,
                "security_guid_a": by_sym[a].get("security_guid"),
                "security_guid_b": by_sym[b].get("security_guid"),
                "collapsed": bool(by_sym[a].get("security_guid") and by_sym[a].get("security_guid") == by_sym[b].get("security_guid")),
            })

    graph_profiled = sorted(s for s, r in by_sym.items() if "GRAPH_PROFILE" in (r.get("membership_reasons") or []))
    not_graph = sorted(s for s in canonical if s not in set(graph_profiled))
    resolved_not_graph = [
        s for s in not_graph
        if by_sym[s].get("security_guid") and by_sym[s].get("identity_status") != "UNRESOLVED_WITH_REASON"
    ]
    unresolved = [s for s, r in by_sym.items() if r.get("identity_status") == "UNRESOLVED_WITH_REASON"]

    # Scheduler reconciliation
    sched = load_scheduler(root=CURRENT)
    sched_syms = set(sched)
    only_in_canonical_not_sched = sorted(canonical - sched_syms)
    only_in_sched_not_canonical = sorted(sched_syms - canonical)
    tier_disagree = []
    for sym in sorted(canonical & sched_syms):
        ct = by_sym[sym].get("current_research_tier")
        st = (sched.get(sym) or {}).get("tier")
        if ct != st:
            tier_disagree.append({"symbol": sym, "canonical_tier": ct, "scheduler_tier": st})
    only_canonical_reasons = Counter()
    for s in only_in_canonical_not_sched:
        for reason in by_sym[s].get("membership_reasons") or []:
            only_canonical_reasons[reason] += 1
        if not set(by_sym[s].get("membership_reasons") or []).intersection(SCHEDULER_REASONS):
            only_canonical_reasons["NO_SCHEDULER_REASON"] += 1

    # Holdings coverage
    holdings_rows = []
    for s in sorted(holdings):
        rec = by_sym.get(s) or {}
        holdings_rows.append(compact_rec(rec) if rec else {"symbol": s, "MISSING": True})
    missing_holdings = missing(holdings)

    # Sold / re-entry examples
    sold_examples = []
    for s in sorted(reentry_sold):
        rec = by_sym.get(s)
        if not rec:
            continue
        if rec.get("currently_held"):
            continue
        if rec.get("current_research_tier") == "T0-HOLD":
            continue
        sold_examples.append(compact_rec(rec))
        if len(sold_examples) >= 12:
            break
    ready_examples = [compact_rec(by_sym[s]) for s in sorted(reentry_ready) if s in by_sym][:12]
    wait_examples = [
        compact_rec(by_sym[s]) for s in sorted(reentry_wait)
        if s in by_sym and not by_sym[s].get("currently_held")
    ][:12]

    # SCHD sell-sim: drop SCHD from holdings, rebuild
    schd_sim = None
    if "SCHD" in holdings:
        sim_sources = dict(sources)
        sim_sources["holdings"] = [s for s in (sources.get("holdings") or []) if normalize_symbol(s) != "SCHD"]
        sim_manifest = load_universe(root=CURRENT, sources=sim_sources, pin=pin)
        diff = universe_diff(manifest, sim_manifest)
        schd_before = compact_rec(by_sym["SCHD"])
        schd_after_full = next((r for r in sim_manifest.get("securities") or [] if r.get("symbol") == "SCHD"), None)
        schd_sim = {
            "before": schd_before,
            "after": compact_rec(schd_after_full) if schd_after_full else None,
            "added": diff.get("added"),
            "removed": diff.get("removed"),
            "tier_changed_schd": [x for x in (diff.get("tier_changed") or []) if x.get("symbol") == "SCHD"],
            "false_remove_add": ("SCHD" in (diff.get("removed") or []) or "SCHD" in (diff.get("added") or [])),
            "diff_counts": {
                "added_n": len(diff.get("added") or []),
                "removed_n": len(diff.get("removed") or []),
                "tier_changed_n": len(diff.get("tier_changed") or []),
            },
        }

    # Lineage samples
    sample_syms = []
    for s in ("NOC", "SCHD", "ADBE", "ALXO", "ANET", "NVDA", "AAPL", "MSFT"):
        if s in by_sym:
            sample_syms.append(s)
    # add one from other sectors if present
    by_sector: dict[str, list[str]] = defaultdict(list)
    for r in secs:
        if r.get("sector"):
            by_sector[str(r["sector"])].append(r["symbol"])
    for sector, syms in sorted(by_sector.items()):
        if len(sample_syms) >= 8:
            break
        if syms[0] not in sample_syms:
            sample_syms.append(syms[0])

    lineage = []
    graph_by_sym = {}
    for row in sources.get("graph_profiles") or []:
        if isinstance(row, dict) and row.get("symbol"):
            graph_by_sym[normalize_symbol(row["symbol"])] = row
    for s in sample_syms:
        rec = by_sym[s]
        ind = get_related_by_industry(manifest, s)
        sec = get_related_by_sector(manifest, s)
        cat = get_related_by_catalyst(manifest, s)
        ident = get_identity_lineage(manifest, s)
        g = graph_by_sym.get(s) or {}
        edges = g.get("relationships") or []
        edge_kinds = Counter(e.get("target_kind") for e in edges if isinstance(e, dict))
        edge_prov = sum(1 for e in edges if isinstance(e, dict) and (e.get("producer") or e.get("source_type") or e.get("source_refs")))
        reverse_cat = []
        for guid in (rec.get("catalyst_guids") or [])[:2]:
            rev = get_related_by_catalyst(manifest, guid)
            reverse_cat.append({
                "catalyst_guid": guid,
                "related_n": len(rev.get("related_symbols") or []),
                "related_sample": (rev.get("related_symbols") or [])[:8],
            })
        lineage.append({
            "symbol": s,
            "sector": rec.get("sector"),
            "industry": rec.get("industry"),
            "A_identity": ident,
            "A_graph_edges": {
                "n": len(edges),
                "kinds": dict(edge_kinds),
                "with_provenance_n": edge_prov,
                "sample": edges[:6],
            },
            "B_industry": {
                "industry": ind.get("industry"),
                "related_n": len(ind.get("related_symbols") or []),
                "related_sample": (ind.get("related_symbols") or [])[:8],
                "not_supply_chain": ind.get("not_supply_chain"),
            },
            "C_sector": {
                "sector": sec.get("sector"),
                "related_n": len(sec.get("related_symbols") or []),
                "related_sample": (sec.get("related_symbols") or [])[:8],
                "not_supply_chain": sec.get("not_supply_chain"),
            },
            "D_catalyst": {
                "catalyst_guids": rec.get("catalyst_guids") or [],
                "related_n": len(cat.get("related_symbols") or []),
                "related_sample": (cat.get("related_symbols") or [])[:8],
                "reverse": reverse_cat,
            },
            "peers_on_graph": g.get("peers") or [],
        })

    # Discovery / screener / scope
    db_probe = {
        "db_enabled": bool(os.getenv("DB_HOST") and os.getenv("DB_PASSWORD")),
        "db_name": os.getenv("DB_NAME"),
        "symbol_profiles_n": len(sources.get("symbol_profiles") or []),
        "proposals_active_n": len(sources.get("proposals_active") or []),
        "scope_status": _q(
            "SELECT status, scope_tier, COUNT(DISTINCT UPPER(symbol)) AS n "
            "FROM watchlist_items GROUP BY 1, 2 ORDER BY 1, 2"
        ),
        "screener_tables": _q(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND (table_name ILIKE '%screener%' "
            "OR table_name ILIKE '%discover%') ORDER BY 1"
        ),
    }
    discovery_symbols: set[str] = set()
    discovery_note = []
    for tbl_row in db_probe["screener_tables"]:
        tbl = tbl_row.get("table_name")
        if not tbl or tbl_row.get("_error"):
            continue
        cols = _q(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s",
            (tbl,),
        )
        col_names = {c.get("column_name") for c in cols}
        if "symbol" in col_names:
            rows = _q(f"SELECT DISTINCT UPPER(symbol) AS symbol FROM {tbl} WHERE symbol IS NOT NULL LIMIT 20000")
            if rows and not rows[0].get("_error"):
                got = _cashless(_syms(rows))
                discovery_note.append({"table": tbl, "unique_n": len(got), "missing_from_canonical_n": len(got - canonical)})
                discovery_symbols |= got

    # 126 hunter
    counts_for_126 = {
        "canonical": len(canonical),
        "graph_profiles": len(graph),
        "trs_lines": sum(1 for _ in (CURRENT / "data/cio/ticker_research_state.jsonl").read_text().splitlines() if _.strip()),
        "holdings_equity": len(holdings),
        "cusips": len(cusips),
        "holdings_plus_cusips": len(holdings | cusips),
        "reentry_all": len(reentry_all),
        "holdings_plus_reentry_naive_sum": len(holdings) + len(reentry_all),
        "holdings_union_reentry": len(holdings | reentry_all),
        "reentry_ready": len(reentry_ready),
        "reentry_wait": len(reentry_wait),
        "watch": len(watch),
        "proposals_active": len(proposals_active),
        "incubator": len(incubator),
        "scheduler": len(sched_syms),
        "hermes_t1": len(hermes_t1),
        "t0_hold_plus_t0_prop": (manifest.get("tier_counts") or {}).get("T0-HOLD", 0) + (manifest.get("tier_counts") or {}).get("T0-PROP", 0),
        "graph_plus_cusips": len(graph) + len(cusips),
        "graph_plus_holdings_not_in_graph": len(graph) + len(holdings - graph),
        "ticker_alias_only": len(ticker_only),
        "confirmed": ident_status.get("CONFIRMED", 0),
        "unresolved": ident_status.get("UNRESOLVED_WITH_REASON", 0),
    }
    equals_126 = {k: v for k, v in counts_for_126.items() if v == 126}
    db_126 = _q(
        """
        SELECT 'paper_trade_proposals_distinct' AS k, COUNT(DISTINCT symbol)::int AS n FROM paper_trade_proposals
        UNION ALL SELECT 'incubator_all_status', COUNT(DISTINCT symbol)::int FROM incubator_universe
        UNION ALL SELECT 'watch_directives_all', COUNT(DISTINCT spec->>'symbol')::int FROM watch_directives WHERE spec ? 'symbol'
        UNION ALL SELECT 'watch_directives_active', COUNT(DISTINCT spec->>'symbol')::int FROM watch_directives WHERE kind='ticker' AND status='active' AND spec ? 'symbol'
        UNION ALL SELECT 'symbol_profiles', COUNT(DISTINCT symbol)::int FROM symbol_profiles
        UNION ALL SELECT 'hermes_symbols', COUNT(DISTINCT symbol)::int FROM hermes_score_history
        """
    )

    cov = graph_coverage_report(manifest)
    cov_slim = dict(cov)
    cov_slim["missing"] = cov_slim.get("missing_n")
    met = universe_metrics(manifest)

    # Graph CURRENT identity vs manifest identity
    graph_issuer = sum(1 for r in (sources.get("graph_profiles") or []) if isinstance(r, dict) and r.get("issuer_guid"))
    graph_security = sum(1 for r in (sources.get("graph_profiles") or []) if isinstance(r, dict) and r.get("security_guid"))
    graph_company = sum(1 for r in (sources.get("graph_profiles") or []) if isinstance(r, dict) and r.get("company"))

    receipt = {
        "schema": "TransfersonLiveAcceptance@v1",
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "financial_action": False,
        "as_of": _now(),
        "source_pin": pin,
        "current_path": str(CURRENT.resolve()),
        "worktree": str(WT),
        "top_rank_n": int(TOP_RANK_N),
        "r17_auto_checkpoint": "blocked until this identity/universe contract is accepted",
        "section_1_counts": {
            "canonical_universe_count": manifest.get("canonical_universe_count"),
            "graph_profiled_count": manifest.get("graph_profiled_count"),
            "graph_coverage_pct": round(100.0 * (manifest.get("graph_profiled_count") or 0) / max(1, manifest.get("canonical_universe_count") or 1), 4),
            "graph_coverage": manifest.get("graph_coverage"),
            "identity_resolved_count": security_n,
            "identity_unresolved_count": ident_status.get("UNRESOLVED_WITH_REASON", 0),
            "tier_counts": manifest.get("tier_counts"),
            "metrics": met,
        },
        "section_2_source_reconciliation": {
            "raw_unique_counts": {k: len(v) for k, v in membership_sets.items()},
            "scope_s3_overlay_n": len(scope_s3),
            "scope_s3_in_canonical": len(scope_s3 & canonical),
            "scope_s3_not_in_canonical": len(scope_s3 - canonical),
            "scope_note": "scope_s3 is a research-priority overlay/demotion, not a membership add",
            "authorized_union_n": len(authorized_union),
            "canonical_n": len(canonical),
            "union_equals_canonical": authorized_union == canonical,
            "only_in_union": only_in_union[:50],
            "only_in_union_n": len(only_in_union),
            "only_in_canonical": only_in_canonical[:50],
            "only_in_canonical_n": len(only_in_canonical),
            "overlaps": {
                "holdings_and_reentry": len(holdings & reentry_all),
                "holdings_and_graph": len(holdings & graph),
                "watch_and_hermes_t1": len(watch & hermes_t1),
                "incubator_and_profiles": len(incubator & profiles),
                "proposals_active_and_recent": len(proposals_active & proposals_recent),
            },
            "naive_sum_all_membership_sources": sum(len(membership_sets[k]) for k in (
                "holdings", "cusips", "reentry_all", "proposals_active", "proposals_recent",
                "watch_directives", "hermes_rank_all", "incubator", "symbol_profiles", "graph_profiles",
            )),
            "discovery": {
                "tables": db_probe["screener_tables"],
                "notes": discovery_note,
                "union_n": len(discovery_symbols),
                "missing_from_canonical_n": len(discovery_symbols - canonical) if discovery_symbols else 0,
                "wired_as_membership_source": False,
            },
            "reentry_states": dict(reentry_states),
        },
        "section_3_holdings": {
            "held_equity_n": len(holdings),
            "missing_current_holdings": missing_holdings,
            "missing_n": len(missing_holdings),
            "cusips": sorted(cusips),
            "cusips_in_universe": sorted(s for s in cusips if s in canonical),
            "rows": holdings_rows,
        },
        "section_4_sold_reentry": {
            "reentry_all_n": len(reentry_all),
            "reentry_all_missing": missing(reentry_all)[:20],
            "reentry_all_missing_n": len(missing(reentry_all)),
            "ready_near_n": len(reentry_ready),
            "wait_retained_n": len(reentry_wait),
            "sold_examples": sold_examples,
            "ready_examples": ready_examples,
            "wait_examples": wait_examples,
            "rule": "SOLD remains member; READY/NEAR may promote to T1; WAIT/OVERSOLD may demote but does not disappear; tier change is not add/remove",
        },
        "section_5_proposal_watch_incubator": {
            "proposals_active_missing": missing(proposals_active),
            "watch_missing": missing(watch),
            "hermes_rank_t1_missing": missing(hermes_t1),
            "incubator_missing": missing(incubator),
            "counts": {
                "proposals_active": len(proposals_active),
                "watch": len(watch),
                "hermes_t1": len(hermes_t1),
                "incubator": len(incubator),
            },
        },
        "section_6_scheduler": {
            "canonical_n": len(canonical),
            "scheduler_n": len(sched_syms),
            "only_in_canonical_n": len(only_in_canonical_not_sched),
            "only_in_scheduler_n": len(only_in_sched_not_canonical),
            "only_in_scheduler": only_in_sched_not_canonical[:30],
            "tier_disagreement_n": len(tier_disagree),
            "tier_disagreement_sample": tier_disagree[:20],
            "only_in_canonical_reason_counts": dict(only_canonical_reasons),
            "distinction": {
                "institutional_universe_membership": "TransfersonUniverseManifest@v1 securities",
                "active_research_scheduler_membership": "research_tier_index over SCHEDULER_REASONS",
            },
        },
        "section_7_graph_coverage": {
            "graph_profiled_count": len(graph_profiled),
            "canonical_universe_count": len(canonical),
            "ratio": f"{len(graph_profiled)} / {len(canonical)}",
            "not_yet_graph_profiled_n": len(not_graph),
            "identity_resolved_but_not_graph_profiled_n": len(resolved_not_graph),
            "unresolved_identity_n": len(unresolved),
            "graph_profiled_sample": graph_profiled[:15],
            "not_graph_sample": not_graph[:15],
            "coverage_report": cov_slim,
            "seed_graph_from_universe_applied_to_CURRENT": False,
        },
        "section_8_126": {
            "status": "UNRESOLVED_WITH_REASON" if not equals_126 else "CANDIDATE_COINCIDENCE_ONLY",
            "equals_126_live_counts": equals_126,
            "all_live_counts": counts_for_126,
            "db_counts": db_126,
            "note": "No exact producer/query/function found that emits 126 as a universe denominator. Coincidences are not producers.",
        },
        "section_9_identity": {
            "by_status": dict(ident_status),
            "issuer_guid_resolved": issuer_n,
            "security_guid_resolved": security_n,
            "listing_guid_resolved": listing_n,
            "ticker_alias_only_n": len(ticker_only),
            "ticker_alias_only_sample": ticker_only[:20],
            "UNRESOLVED_WITH_REASON": ident_status.get("UNRESOLVED_WITH_REASON", 0),
            "CANDIDATE": ident_status.get("CANDIDATE", 0),
            "CONFIRMED": ident_status.get("CONFIRMED", 0),
            "security_guid_equals_ticker_guid": sg_eq_tg,
            "security_guid_fabricated_from_ticker_n": len(minted_from_ticker),
            "security_guid_fabricated_from_ticker_sample": minted_from_ticker[:20],
            "duplicate_security_identities": duplicate_security,
            "share_class_pairs": share_class_pairs,
            "graph_file_issuer_guid_n": graph_issuer,
            "graph_file_security_guid_n": graph_security,
            "graph_file_company_n": graph_company,
            "identity_wiring_note": "CURRENT graph profiles carry issuer_guid on company-bearing rows; universe loader copies TRS security_guid but does not copy graph issuer_guid/company onto the manifest.",
        },
        "section_10_lineage": lineage,
        "section_11_diff": {
            "schd_sell_sim": schd_sim,
            "as_of": manifest.get("as_of"),
            "source_pin": pin,
            "tier_counts": manifest.get("tier_counts"),
            "membership_reason_counts": manifest.get("membership_reason_counts"),
            "graph_coverage": manifest.get("graph_coverage"),
        },
        "section_12_consumers": None,  # filled by caller after static audit
        "db_probe": {
            "db_enabled": db_probe["db_enabled"],
            "db_name": db_probe["db_name"],
            "symbol_profiles_n": db_probe["symbol_profiles_n"],
            "proposals_active_n": db_probe["proposals_active_n"],
            "scope_status": db_probe["scope_status"],
        },
        "coverage": cov_slim,
    }

    slim_manifest = {k: v for k, v in manifest.items() if k != "securities"}
    slim_manifest["holdings"] = holdings_rows
    slim_manifest["sample"] = [compact_rec(by_sym[s]) for s in sample_syms]

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "LIVE_ACCEPTANCE.json").write_text(json.dumps(receipt, indent=2, default=str) + "\n", encoding="utf-8")
    (EVIDENCE / "LIVE_MANIFEST_SLIM.json").write_text(json.dumps(slim_manifest, indent=2, default=str) + "\n", encoding="utf-8")
    with gzip.open(EVIDENCE / "LIVE_MANIFEST.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(manifest, fh, default=str)
    with (EVIDENCE / "LIVE_SECURITIES_INDEX.jsonl").open("w", encoding="utf-8") as fh:
        for rec in secs:
            fh.write(json.dumps(compact_rec(rec), default=str) + "\n")

    print(json.dumps({
        "canonical_universe_count": manifest.get("canonical_universe_count"),
        "graph_coverage": manifest.get("graph_coverage"),
        "tier_counts": manifest.get("tier_counts"),
        "union_equals_canonical": authorized_union == canonical,
        "only_in_union_n": len(only_in_union),
        "only_in_canonical_n": len(only_in_canonical),
        "missing_holdings": missing_holdings,
        "scheduler_n": len(sched_syms),
        "only_in_canonical_not_sched": len(only_in_canonical_not_sched),
        "identity": dict(ident_status),
        "issuer_guid": issuer_n,
        "security_guid": security_n,
        "equals_126": equals_126,
        "proposals_missing": missing(proposals_active),
        "watch_missing": missing(watch),
        "incubator_missing": missing(incubator),
        "hermes_t1_missing": missing(hermes_t1)[:10],
        "hermes_t1_missing_n": len(missing(hermes_t1)),
        "schd_false_remove_add": (schd_sim or {}).get("false_remove_add"),
        "wrote": [
            "LIVE_ACCEPTANCE.json",
            "LIVE_MANIFEST_SLIM.json",
            "LIVE_MANIFEST.json.gz",
            "LIVE_SECURITIES_INDEX.jsonl",
        ],
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
