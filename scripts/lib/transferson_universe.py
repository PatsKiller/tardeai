"""Canonical Transferson universe — membership ≠ research priority.

Universe count is always derived from live sources. Never hard-code a profile
cohort size, an unexplained view count, or any other ticker count.
Graph-profiled names are a coverage cohort, not the universe denominator.

READ_ONLY_ADVISORY. Does not mint security_guid from ticker text.
Does not infer supply-chain from shared industry/sector.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from scripts.lib.holdings_universe import (
    CASH_SYMBOLS,
    held_equity_tickers,
    held_unresolved_cusips,
    is_held_equity_ticker,
)
from scripts.lib.security_identity import (
    classify_unresolved_symbol,
    normalize_symbol,
    resolve_identity_spine,
)
from scripts.lib.ticker_knowledge_graph import seed_profiles

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "TransfersonUniverseManifest@v1"
MBI = 0

TIERS = ("T0-HOLD", "T0-PROP", "T1-WATCH", "T2-INCUB", "T3-COLD")
READY_NEAR = frozenset({"READY TO REVIEW", "NEAR ENTRY", "READY", "NEAR"})
REENTRY_EXCLUDED_FROM_T1 = frozenset({
    "WAIT", "OVERSOLD", "OVERSOLD REVIEW", "CURRENTLY HELD", "WASH BLOCK",
    "STALE", "MISSING MARKET", "MISSING PLAN", "OVERBOUGHT WAIT", "BLOCK",
})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _root(root: Path | str | None) -> Path:
    if root is None:
        return Path(__file__).resolve().parents[2]
    return Path(root)


def _q(sql: str, params: tuple = ()) -> list:
    try:
        from db_adapter import _execute  # type: ignore
        return _execute(sql, params, fetch="all") or []
    except Exception:
        return []


def _tier_order(tier: str) -> int:
    try:
        return TIERS.index(tier)
    except ValueError:
        return len(TIERS)


def _json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _entry(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "ticker_guid": None,
        "issuer_guid": None,
        "security_guid": None,
        "listing_guid": None,
        "current_research_tier": "T3-COLD",
        "membership_reasons": [],
        "membership_sources": [],
        "first_seen_at": None,
        "last_seen_at": None,
        "currently_held": False,
        "historically_held": False,
        "sold_history_present": False,
        "reentry_status": None,
        "active_proposal": False,
        "watch_directive_active": False,
        "hermes_rank": None,
        "incubator_status": None,
        "scope_governor_status": None,
        "sector": None,
        "industry": None,
        "subindustry": None,
        "catalyst_guids": [],
        "unresolved_identity": None,
        "source_provenance": [],
    }


def _touch(uni: dict[str, dict[str, Any]], symbol: str, *, reason: str, source: str, **fields: Any) -> dict[str, Any]:
    sym = normalize_symbol(symbol)
    if not sym or sym in CASH_SYMBOLS:
        return {}
    row = uni.setdefault(sym, _entry(sym))
    if reason and reason not in row["membership_reasons"]:
        row["membership_reasons"].append(reason)
    if source and source not in row["membership_sources"]:
        row["membership_sources"].append(source)
    if source and source not in row["source_provenance"]:
        row["source_provenance"].append(source)
    for key, value in fields.items():
        if value is None:
            continue
        if key in {"currently_held", "historically_held", "sold_history_present", "active_proposal", "watch_directive_active"}:
            row[key] = bool(value) or row[key]
        elif key == "current_research_tier":
            if _tier_order(str(value)) < _tier_order(row["current_research_tier"]):
                row["current_research_tier"] = str(value)
        elif key == "catalyst_guids":
            for g in value or []:
                if g and g not in row["catalyst_guids"]:
                    row["catalyst_guids"].append(g)
        elif key in {"hermes_rank"} and row.get(key) is None:
            row[key] = value
        elif not row.get(key):
            row[key] = value
    return row


def collect_live_sources(*, root: Path | str | None = None, top_rank_n: int = 200) -> dict[str, Any]:
    """Fail-soft live collectors. Missing files/DB yield empty lists, never invented names."""
    root_p = _root(root)
    repo = Path(__file__).resolve().parents[2]
    allow_db = root_p.resolve() == repo.resolve() or (root_p / "SOURCE_COMMIT").is_file()
    holdings = held_equity_tickers(root=root_p)
    cusips = held_unresolved_cusips(root=root_p)
    reentry_rows = []
    desk = _json(root_p / "data/runtime/reentry_decision_desk_latest.json")
    if isinstance(desk, dict):
        raw = desk.get("rows") or []
        if isinstance(raw, dict):
            raw = list(raw.values())
        for row in raw or []:
            if isinstance(row, dict):
                reentry_rows.append(row)
    graph_profiles = []
    for row in _jsonl(root_p / "data/cio/ticker_research_graph.jsonl"):
        if row.get("research_artifact_guid"):
            continue
        if row.get("ticker_guid") or row.get("schema") == "TickerKnowledgeProfile@v1":
            graph_profiles.append(row)
    trs = _jsonl(root_p / "data/cio/ticker_research_state.jsonl")
    q = _q if allow_db else (lambda *a, **k: [])
    proposals_active = [dict(r).get("symbol") for r in q(
        """SELECT DISTINCT symbol FROM paper_trade_proposals
           WHERE status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST')""")]
    proposals_recent = [dict(r).get("symbol") for r in q(
        """SELECT DISTINCT symbol FROM paper_trade_proposals
           WHERE created_at > NOW() - INTERVAL '21 days'""")]
    hermes_ranks = {dict(r)["symbol"]: dict(r)["rank"] for r in q(
        """SELECT DISTINCT ON (symbol) symbol, rank FROM hermes_score_history
           ORDER BY symbol, scored_at DESC""") if dict(r).get("symbol")}
    watch_directives = [dict(r).get("s") for r in q(
        """SELECT spec->>'symbol' AS s FROM watch_directives
           WHERE kind='ticker' AND status='active' AND spec ? 'symbol'""")]
    incubator = [dict(r).get("symbol") for r in q(
        """SELECT DISTINCT symbol FROM incubator_universe
           WHERE status='active' AND symbol IS NOT NULL""")]
    symbol_profiles = [dict(r) for r in q(
        "SELECT DISTINCT ON (symbol) symbol, sector, industry FROM symbol_profiles ORDER BY symbol")]
    scope_s3 = {str(dict(r).get("symbol") or "").upper() for r in q(
        """SELECT DISTINCT UPPER(symbol) AS symbol FROM watchlist_items
           WHERE scope_tier='S3' AND status IN ('active','researched')""")}
    return {
        "holdings": holdings,
        "cusips": cusips,
        "reentry": reentry_rows,
        "graph_profiles": graph_profiles,
        "trs": trs,
        "proposals_active": [s for s in proposals_active if s],
        "proposals_recent": [s for s in proposals_recent if s],
        "hermes_ranks": hermes_ranks,
        "watch_directives": [s for s in watch_directives if s],
        "incubator": [s for s in incubator if s],
        "symbol_profiles": symbol_profiles,
        "scope_s3": scope_s3,
        "top_rank_n": top_rank_n,
        "root": str(root_p),
    }


def build_universe(*, sources: dict[str, Any], as_of: str | None = None, pin: str | None = None) -> dict[str, Any]:
    uni: dict[str, dict[str, Any]] = {}
    top_n = int(sources.get("top_rank_n") or 200)

    for sym in sources.get("holdings") or []:
        _touch(uni, sym, reason="CURRENTLY_HELD", source="holdings.json",
               currently_held=True, historically_held=True, current_research_tier="T0-HOLD")

    for sym in sources.get("cusips") or []:
        row = _touch(uni, sym, reason="UNRESOLVED_IDENTITY", source="holdings.json")
        if row:
            row["unresolved_identity"] = classify_unresolved_symbol(sym)
            row["current_research_tier"] = "T3-COLD"

    for row in sources.get("reentry") or []:
        if not isinstance(row, dict):
            continue
        intel = row.get("intel") if isinstance(row.get("intel"), dict) else {}
        state = str(intel.get("state") or row.get("state") or row.get("status") or "").strip().upper()
        sym = row.get("symbol")
        held = row.get("held") is True
        rec = _touch(uni, sym, reason="REENTRY_HISTORY", source="reentry_decision_desk_latest.json",
                     reentry_status=state or None, historically_held=True)
        if not rec:
            continue
        if state in READY_NEAR and not held:
            _touch(uni, sym, reason="REENTRY_READY_NEAR", source="reentry_decision_desk_latest.json",
                   current_research_tier="T1-WATCH", reentry_status=state)
        if state in (REENTRY_EXCLUDED_FROM_T1 - {"CURRENTLY HELD"}) and not rec.get("currently_held"):
            rec["sold_history_present"] = True
            rec["historically_held"] = True

    for sym in sources.get("proposals_active") or []:
        _touch(uni, sym, reason="ACTIVE_PROPOSAL", source="paper_trade_proposals",
               active_proposal=True, current_research_tier="T0-PROP")
    for sym in sources.get("proposals_recent") or []:
        _touch(uni, sym, reason="RECENT_PROPOSAL", source="paper_trade_proposals",
               current_research_tier="T2-INCUB")

    ranks = sources.get("hermes_ranks") or {}
    for sym, rank in ranks.items():
        _touch(uni, sym, reason="HERMES_RANK", source="hermes_score_history", hermes_rank=rank)
        try:
            r = int(rank)
        except (TypeError, ValueError):
            continue
        if r <= top_n:
            _touch(uni, sym, reason="HERMES_RANK_T1", source="hermes_score_history",
                   current_research_tier="T1-WATCH", hermes_rank=r)

    for sym in sources.get("watch_directives") or []:
        _touch(uni, sym, reason="WATCH_DIRECTIVE", source="watch_directives",
               watch_directive_active=True, current_research_tier="T1-WATCH")

    for sym in sources.get("incubator") or []:
        _touch(uni, sym, reason="INCUBATOR", source="incubator_universe",
               incubator_status="active", current_research_tier="T2-INCUB")

    for row in sources.get("symbol_profiles") or []:
        if not isinstance(row, dict):
            continue
        _touch(uni, row.get("symbol"), reason="SYMBOL_PROFILE", source="symbol_profiles",
               current_research_tier="T3-COLD", sector=row.get("sector"), industry=row.get("industry"))

    for row in sources.get("graph_profiles") or []:
        if not isinstance(row, dict):
            continue
        rec = _touch(uni, row.get("symbol"), reason="GRAPH_PROFILE", source="ticker_research_graph.jsonl",
                     current_research_tier="T3-COLD", ticker_guid=row.get("ticker_guid") or row.get("ticker_id"),
                     sector=row.get("sector"), industry=row.get("industry"),
                     subindustry=row.get("subindustry"),
                     catalyst_guids=row.get("catalyst_guids") or [])
        if rec and not rec.get("security_guid"):
            rec["security_guid"] = row.get("security_guid")  # only if already present; never mint

    trs_by_sym = {}
    for row in sources.get("trs") or []:
        if isinstance(row, dict) and row.get("symbol"):
            trs_by_sym[normalize_symbol(row["symbol"])] = row
    for sym, rec in uni.items():
        ident = trs_by_sym.get(sym) or {}
        if ident.get("security_guid"):
            rec["security_guid"] = ident.get("security_guid")
        if ident.get("issuer_guid"):
            rec["issuer_guid"] = ident.get("issuer_guid")
        if ident.get("listing_guid"):
            rec["listing_guid"] = ident.get("listing_guid")
        if ident.get("ticker_guid") and not rec.get("ticker_guid"):
            rec["ticker_guid"] = ident.get("ticker_guid")
        spine = resolve_identity_spine(rec)
        rec["ticker_guid_is_not_security"] = True
        rec["identity_status"] = spine.get("identity_status")
        if spine.get("issuer_guid") and not rec.get("issuer_guid"):
            rec["issuer_guid"] = spine["issuer_guid"]
        if spine.get("listing_guid") and not rec.get("listing_guid"):
            rec["listing_guid"] = spine["listing_guid"]
        if spine.get("security_guid") and not rec.get("security_guid"):
            rec["security_guid"] = spine["security_guid"]
        if not rec.get("security_guid"):
            rec["unresolved_identity"] = rec.get("unresolved_identity") or classify_unresolved_symbol(sym)
            rec["identity_status"] = "UNRESOLVED_WITH_REASON"

    s3 = {normalize_symbol(x) for x in (sources.get("scope_s3") or [])}
    for sym, rec in uni.items():
        if rec.get("currently_held"):
            rec["current_research_tier"] = "T0-HOLD"
        if rec.get("reentry_status") in READY_NEAR and rec["current_research_tier"] not in {"T0-HOLD", "T0-PROP"}:
            rec["current_research_tier"] = "T1-WATCH"
        if sym in s3 and rec["current_research_tier"] in {"T1-WATCH", "T2-INCUB"} and rec.get("reentry_status") not in READY_NEAR:
            rec["current_research_tier"] = "T3-COLD"
            rec["scope_governor_status"] = "S3"
            _touch(uni, sym, reason="SCOPE_S3", source="watchlist_items")
        rec["membership_reasons"] = sorted(set(rec["membership_reasons"]))
        rec["membership_sources"] = sorted(set(rec["membership_sources"]))

    securities = [uni[k] for k in sorted(uni)]
    tiers = {t: 0 for t in TIERS}
    reasons: dict[str, int] = {}
    for rec in securities:
        tiers[rec["current_research_tier"]] = tiers.get(rec["current_research_tier"], 0) + 1
        for reason in rec["membership_reasons"]:
            reasons[reason] = reasons.get(reason, 0) + 1
    graph_n = sum(1 for r in securities if "GRAPH_PROFILE" in r["membership_reasons"])
    held_n = sum(1 for r in securities if r["currently_held"])
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "as_of": as_of or _now(),
        "source_pin": pin,
        "canonical_universe_count": len(securities),
        "graph_profiled_count": graph_n,
        "persistent_graph_profiled": graph_n,
        "free_first_circulated_count": graph_n,
        "research_due_count": 0,
        "research_executed_count": 0,
        "graph_coverage": f"{graph_n} graph-profiled / {len(securities)} universe",
        "tier_counts": tiers,
        "membership_reason_counts": reasons,
        "holdings_in_universe": held_n,
        "unresolved_identity_n": sum(1 for r in securities if r.get("identity_status") == "UNRESOLVED_WITH_REASON" or (r.get("unresolved_identity") and not r.get("security_guid"))),
        "ticker_guid_is_not_security": True,
        "securities": securities,
        "note": "Counts are observations. persistent_graph_profiled is not Universe.",
    }


def load_universe(*, root: Path | str | None = None, sources: dict[str, Any] | None = None, pin: str | None = None) -> dict[str, Any]:
    src = sources if sources is not None else collect_live_sources(root=root)
    if pin is None:
        try:
            pin = (_root(root) / "SOURCE_COMMIT").read_text().strip()
        except OSError:
            pin = None
    return build_universe(sources=src, pin=pin)


# Reasons that qualify a name for the research-scheduler tier index.
# Universe membership can be broader (WAIT/sold/graph-profile only).
SCHEDULER_REASONS = frozenset({
    "CURRENTLY_HELD",
    "ACTIVE_PROPOSAL",
    "RECENT_PROPOSAL",
    "REENTRY_READY_NEAR",
    "HERMES_RANK_T1",
    "WATCH_DIRECTIVE",
    "INCUBATOR",
    "SYMBOL_PROFILE",
})


def research_tier_index(manifest: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, dict[str, Any]]:
    """Scheduler-compatible {symbol: {tier, rank, ...}} view.

    WAIT/sold/graph-only names remain in the universe manifest but do not enter
    the research-priority index merely by membership.
    """
    if manifest is None:
        manifest = load_universe(**kwargs)
    out: dict[str, dict[str, Any]] = {}
    for rec in manifest.get("securities") or []:
        sym = rec.get("symbol")
        if not is_held_equity_ticker(sym):
            continue
        reasons = set(rec.get("membership_reasons") or [])
        if not reasons.intersection(SCHEDULER_REASONS):
            continue
        row = {
            "tier": rec.get("current_research_tier") or "T3-COLD",
            "rank": rec.get("hermes_rank"),
            "reentry_ready_near": rec.get("reentry_status") in READY_NEAR,
            "sector": rec.get("sector"),
            "industry": rec.get("industry"),
        }
        out[sym] = row
    return out


def get_symbol(manifest: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    want = normalize_symbol(symbol)
    for rec in manifest.get("securities") or []:
        if rec.get("symbol") == want:
            return rec
    return None


def get_membership_lineage(manifest: dict[str, Any], symbol: str) -> dict[str, Any]:
    rec = get_symbol(manifest, symbol) or {}
    return {
        "schema": "MembershipLineage@v1",
        "symbol": normalize_symbol(symbol),
        "membership_reasons": rec.get("membership_reasons") or [],
        "membership_sources": rec.get("membership_sources") or [],
        "current_research_tier": rec.get("current_research_tier"),
        "unresolved_identity": rec.get("unresolved_identity"),
        "authority": AUTHORITY,
    }


def _by_field(manifest: dict[str, Any], symbol: str, field: str) -> list[str]:
    rec = get_symbol(manifest, symbol)
    if not rec or not rec.get(field):
        return []
    value = rec[field]
    return sorted({
        r["symbol"] for r in (manifest.get("securities") or [])
        if r.get(field) == value and r.get("symbol") != rec["symbol"]
    })


def get_related_by_industry(manifest: dict[str, Any], symbol: str) -> dict[str, Any]:
    rec = get_symbol(manifest, symbol) or {}
    return {
        "schema": "IndustryRelation@v1",
        "symbol": normalize_symbol(symbol),
        "industry": rec.get("industry"),
        "related_symbols": _by_field(manifest, symbol, "industry"),
        "not_supply_chain": True,
        "authority": AUTHORITY,
    }


def get_related_by_sector(manifest: dict[str, Any], symbol: str) -> dict[str, Any]:
    rec = get_symbol(manifest, symbol) or {}
    return {
        "schema": "SectorRelation@v1",
        "symbol": normalize_symbol(symbol),
        "sector": rec.get("sector"),
        "related_symbols": _by_field(manifest, symbol, "sector"),
        "not_supply_chain": True,
        "authority": AUTHORITY,
    }


def get_related_by_catalyst(manifest: dict[str, Any], symbol_or_catalyst: str) -> dict[str, Any]:
    key = str(symbol_or_catalyst or "")
    rec = get_symbol(manifest, key)
    if rec:
        guids = set(rec.get("catalyst_guids") or [])
        related = []
        for other in manifest.get("securities") or []:
            if other.get("symbol") == rec.get("symbol"):
                continue
            if guids.intersection(other.get("catalyst_guids") or []):
                related.append(other["symbol"])
        return {
            "schema": "CatalystRelation@v1",
            "query": key,
            "catalyst_guids": sorted(guids),
            "related_symbols": sorted(set(related)),
            "authority": AUTHORITY,
        }
    related = [
        r["symbol"] for r in (manifest.get("securities") or [])
        if key in (r.get("catalyst_guids") or [])
    ]
    return {
        "schema": "CatalystRelation@v1",
        "query": key,
        "catalyst_guids": [key],
        "related_symbols": sorted(set(related)),
        "authority": AUTHORITY,
    }


def get_mentions(manifest: dict[str, Any], symbol: str) -> dict[str, Any]:
    rec = get_symbol(manifest, symbol) or {}
    return {
        "schema": "Mentions@v1",
        "symbol": normalize_symbol(symbol),
        "catalyst_guids": rec.get("catalyst_guids") or [],
        "industry": rec.get("industry"),
        "sector": rec.get("sector"),
        "authority": AUTHORITY,
    }


def universe_diff(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    prev = {r["symbol"]: r for r in previous.get("securities") or [] if r.get("symbol")}
    curr = {r["symbol"]: r for r in current.get("securities") or [] if r.get("symbol")}
    added = sorted(set(curr) - set(prev))
    removed = sorted(set(prev) - set(curr))
    tier_changed = []
    reason_changed = []
    for sym in sorted(set(prev) & set(curr)):
        if prev[sym].get("current_research_tier") != curr[sym].get("current_research_tier"):
            tier_changed.append({
                "symbol": sym,
                "from": prev[sym].get("current_research_tier"),
                "to": curr[sym].get("current_research_tier"),
                "event": "TIER_CHANGED",
            })
        if prev[sym].get("membership_reasons") != curr[sym].get("membership_reasons"):
            reason_changed.append(sym)
    return {
        "schema": "TransfersonUniverseDiff@v1",
        "previous_as_of": previous.get("as_of"),
        "current_as_of": current.get("as_of"),
        "previous_count": previous.get("canonical_universe_count"),
        "current_count": current.get("canonical_universe_count"),
        "added": added,
        "removed": removed,
        "tier_changed": tier_changed,
        "membership_reason_changed": reason_changed,
        "authority": AUTHORITY,
    }


def persist_manifest(root: Path | str | None, manifest: dict[str, Any]) -> Path:
    path = _root(root) / "data/cio/transferson_universe_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    slim = dict(manifest)
    path.write_text(json.dumps(slim, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    """Permanent metric names. Never alias graph-profiled as Universe."""
    tiers = manifest.get("tier_counts") or {}
    return {
        "schema": "TransfersonUniverseMetrics@v1",
        "canonical_universe_count": manifest.get("canonical_universe_count"),
        "graph_profiled_count": manifest.get("graph_profiled_count"),
        "persistent_graph_profiled": manifest.get("persistent_graph_profiled"),
        "free_first_circulated_count": manifest.get("free_first_circulated_count"),
        "research_due_count": manifest.get("research_due_count") or 0,
        "research_executed_count": manifest.get("research_executed_count") or 0,
        "t0_hold": tiers.get("T0-HOLD", 0),
        "t0_prop": tiers.get("T0-PROP", 0),
        "t1_watch": tiers.get("T1-WATCH", 0),
        "t2_incub": tiers.get("T2-INCUB", 0),
        "t3_cold": tiers.get("T3-COLD", 0),
        "graph_coverage": manifest.get("graph_coverage"),
        "ticker_guid_is_not_security": True,
        "authority": AUTHORITY,
    }


def graph_coverage_report(manifest: dict[str, Any]) -> dict[str, Any]:
    missing = []
    for rec in manifest.get("securities") or []:
        if "GRAPH_PROFILE" not in (rec.get("membership_reasons") or []):
            missing.append({
                "symbol": rec.get("symbol"),
                "reasons": rec.get("membership_reasons") or [],
                "tier": rec.get("current_research_tier"),
                "identity_status": rec.get("identity_status"),
                "missing_reason": "NO_GRAPH_PROFILE",
            })
    n = manifest.get("canonical_universe_count") or 0
    g = manifest.get("graph_profiled_count") or 0
    return {
        "schema": "GraphCoverageReport@v1",
        "canonical_universe_count": n,
        "graph_profiled_count": g,
        "persistent_graph_profiled": g,
        "graph_coverage": f"{g} / {n}",
        "missing": missing,
        "missing_n": len(missing),
        "direction": "canonical_universe → identity → graph/profile → research/free-first",
        "authority": AUTHORITY,
    }


def seed_graph_from_universe(root: Path | str | None, manifest: dict[str, Any]) -> dict[str, Any]:
    """Seed ticker profiles FROM the canonical universe. Does not define the universe."""
    missing = graph_coverage_report(manifest)["missing"]
    rows = []
    for item in missing:
        rec = get_symbol(manifest, item["symbol"]) or {}
        rows.append({
            "symbol": rec.get("symbol"),
            "sector": rec.get("sector"),
            "industry": rec.get("industry"),
            "memberships": rec.get("membership_reasons") or [],
            "security_guid": rec.get("security_guid"),
            "issuer_guid": rec.get("issuer_guid"),
            "listing_guid": rec.get("listing_guid"),
        })
    result = seed_profiles(_root(root), rows) if rows else {"profiles_created": 0}
    result["seeded_from"] = "canonical_universe"
    result["missing_before"] = len(missing)
    result["authority"] = AUTHORITY
    return result


def get_identity_lineage(manifest: dict[str, Any], symbol: str) -> dict[str, Any]:
    rec = get_symbol(manifest, symbol) or {}
    return {
        "schema": "IdentityLineage@v1",
        "symbol": normalize_symbol(symbol),
        "issuer_guid": rec.get("issuer_guid"),
        "security_guid": rec.get("security_guid"),
        "listing_guid": rec.get("listing_guid"),
        "ticker_guid": rec.get("ticker_guid"),
        "ticker_alias": rec.get("symbol"),
        "ticker_guid_is_not_security": True,
        "identity_status": rec.get("identity_status"),
        "unresolved_identity": rec.get("unresolved_identity"),
        "industry": rec.get("industry"),
        "sector": rec.get("sector"),
        "catalyst_guids": rec.get("catalyst_guids") or [],
        "authority": AUTHORITY,
    }
