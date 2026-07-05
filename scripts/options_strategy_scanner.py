#!/usr/bin/env python3
"""options_strategy_scanner.py — winner scanner for paper-only options strategies (Stage A).

Resolves eligible underlyings (current equity holdings + watchlist buy/strong_buy
names), runs the deep-ITM feasibility engine per underlying, ranks winners, and
queues the top N into the EXISTING options desk approval queue
(options_approval_queue, manual-review lane) with educational/paper flags via
lib.options_pipeline.deep_itm_generator. Every proposal links back to Hermes
discovery candidate #339 (meta.discovery_ref) so paper outcomes close the loop.

Market-hours aware: outside regular sessions (weekend/holiday) chains may be stale
or empty — each underlying degrades honestly with a per-symbol reason; nothing is
fabricated.

HARD SAFETY: no broker submit / order / 2FA imports (test-enforced). Dry-run
prints proposals without writing anything.

Stage 1 universe expansion: --universe selects which tiers of
config/options_universe.yaml are scanned (default holdings_watchlist — the
original holdings + watchlist buy/strong_buy behavior). Per-tier
resolved/scanned/winners/rejects stats land in the report, and each tier's
strategy_allowlist is respected (a symbol whose tier does not allow the
strategy is skipped, disclosed). config/options_strategy_registry.yaml gates
which strategies may scan at all (paper_enabled, fail-closed live policy).

MULTI-STRATEGY Stage 2 (operator spec Part D): --strategy also accepts
atm_call | atm_put | all. deep_itm_call stays the default and keeps the exact
Stage-1 single-strategy flow (full backward compatibility). atm_* / all route
per-underlying through lib.options_pipeline.strategy_matcher.run_matchers
(thesis gating owned by the matcher, contract math by the generators);
strategy=all evaluates every registry-paper_enabled scanner-supported strategy
per symbol and reports honest per-strategy counts {scanned, pass, watch, fail,
not_applicable, degraded, queued, top_symbols} plus per-symbol matcher reasons.
Queued rows carry meta.match_json (why_matched + other_strategies verdicts) and
meta.alpaca_paper_enabled (registry, at scan time) for the desk card. Queue
writes reuse deep_itm_generator.submit_to_desk_queue (idempotent proposal_id
upsert, fail-closed paper-flag checks — live_eligible true is never written).

Usage:
    .venv/bin/python scripts/options_strategy_scanner.py --dry-run [--json]
    .venv/bin/python scripts/options_strategy_scanner.py --dry-run --universe all
    .venv/bin/python scripts/options_strategy_scanner.py --dry-run --strategy all
    .venv/bin/python scripts/options_strategy_scanner.py --run [--json]
    .venv/bin/python scripts/options_strategy_scanner.py --run --strategy deep_itm_call

Suggested cron (NOT installed by this script — operator installs explicitly):
    15 10 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/options_strategy_scanner.py --run --strategy deep_itm_call >> logs/options_strategy_scanner.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

from lib.options_pipeline.deep_itm_generator import (  # noqa: E402
    STRATEGY_ID,
    generate_deep_itm_proposals,
    load_pipeline_config,
    submit_to_desk_queue,
)
from lib.options_pipeline.strategy_matcher import run_matchers  # noqa: E402
from lib.options_pipeline.universe import (  # noqa: E402
    UNIVERSE_SELECTORS,
    UniverseConfigError,
    RegistryConfigError,
    load_strategy_registry,
    load_universe_config,
    resolve_universe,
    strategy_allowed_for_entry,
)

DEFAULT_UNIVERSE = "holdings_watchlist"   # preserves the original scanner scope

# Matcher-backed strategies this scanner can run (registry paper_enabled is
# checked on top at run time). "all" = every paper_enabled one of these.
SCANNER_STRATEGIES = (STRATEGY_ID, "atm_call", "atm_put")
SUPPORTED_STRATEGIES = SCANNER_STRATEGIES + ("all",)
SUGGESTED_CRON = (
    "15 10 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && "
    ".venv/bin/python scripts/options_strategy_scanner.py --run --strategy deep_itm_call "
    ">> logs/options_strategy_scanner.log 2>&1"
)
BUY_VERDICTS = frozenset({"strong_buy", "buy"})

# Runtime state dir override (worktrees / tests) — defaults to the repo's state dir.
STATE_DIR = Path(os.getenv("OPTIONS_PIPELINE_STATE_DIR",
                           str(PROJECT_ROOT / "data" / "portfolios" / "state")))


def _f(v, default=0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return default if x != x else x


def _normalize_verdict(raw) -> Optional[str]:
    if not raw:
        return None
    r = str(raw).strip().lower().replace(" ", "_").replace("-", "_")
    if r == "strongbuy":
        r = "strong_buy"
    return r if r in BUY_VERDICTS else None


def _load_holdings_symbols() -> Dict[str, float]:
    """{symbol: shares} for non-cash equity holdings from the desk's holdings snapshot."""
    out: Dict[str, float] = {}
    try:
        raw = json.loads((STATE_DIR / "holdings.json").read_text(encoding="utf-8"))
    except Exception:
        return out
    for h in raw.get("holdings") or []:
        sym = (h.get("symbol") or "").upper()
        if not sym or h.get("is_cash") or not sym.isalpha() or len(sym) > 6:
            continue
        if sym in ("CASH", "SPAXX", "FCASH", "CORE"):
            continue
        shares = _f(h.get("shares"))
        if shares > 0:
            out[sym] = out.get(sym, 0.0) + shares
    return out


def _fetch_watchlist_verdicts() -> List[dict]:
    """Watchlist buy/strong_buy names (research card, CIO synthesis) — read-only DB query."""
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return []
        rows = _execute(
            """SELECT wi.symbol,
                      rc.latest_recommendation AS card_rec,
                      fs.recommendation AS synth_rec,
                      wi.hermes_composite_score
               FROM watchlist_items wi
               LEFT JOIN watchlist_research_cards rc ON rc.symbol = wi.symbol
               LEFT JOIN watchlist_final_synthesis fs ON UPPER(fs.symbol) = UPPER(wi.symbol)
               WHERE wi.status <> 'removed'
                 AND wi.symbol ~ '^[A-Z]{1,5}$'
               ORDER BY wi.hermes_composite_score DESC NULLS LAST, wi.symbol""",
            fetch="all",
        ) or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def resolve_eligible_underlyings(
    *,
    limit: int = 15,
    holdings: Optional[Dict[str, float]] = None,
    watchlist_rows: Optional[List[dict]] = None,
    conviction_floor: float = 0.55,
) -> List[dict]:
    """Holdings equities + watchlist buy/strong_buy names → deduped, capped list.

    Conviction: strong_buy 0.85, buy 0.70, held-only 0.60; held AND buy-rated
    names get +0.05 (capped 0.95). Ties inside a conviction band break on
    hermes_composite_score (held names above unheld) so a run never fills with
    alphabetical microcaps. Injectable inputs keep this unit-testable.
    """
    held = _load_holdings_symbols() if holdings is None else holdings
    wl = _fetch_watchlist_verdicts() if watchlist_rows is None else watchlist_rows

    out: Dict[str, dict] = {}
    for row in wl:
        sym = (row.get("symbol") or "").upper()
        if not sym:
            continue
        verdict = (_normalize_verdict(row.get("card_rec"))
                   or _normalize_verdict(row.get("synth_rec")))
        if verdict not in BUY_VERDICTS:
            continue
        conviction = 0.85 if verdict == "strong_buy" else 0.70
        source = f"watchlist_{verdict}"
        if sym in held:
            conviction = min(0.95, conviction + 0.05)
            source += "+held"
        out[sym] = {"symbol": sym, "conviction": round(conviction, 2),
                    "conviction_source": source, "verdict": verdict,
                    "held_shares": held.get(sym),
                    "rank_score": _f(row.get("hermes_composite_score"))}
    for sym, shares in held.items():
        if sym not in out:
            out[sym] = {"symbol": sym, "conviction": 0.60,
                        "conviction_source": "current_holding", "verdict": None,
                        "held_shares": shares, "rank_score": 0.0}

    eligible = [u for u in out.values() if u["conviction"] >= conviction_floor]
    eligible.sort(key=lambda u: (-u["conviction"],
                                 0 if u.get("held_shares") else 1,
                                 -_f(u.get("rank_score")),
                                 u["symbol"]))
    return eligible[: max(1, int(limit))]


def _tier_of(u: dict) -> str:
    """Tier attribution for an underlying (explicit source_tier wins)."""
    if u.get("source_tier"):
        return str(u["source_tier"])
    src = str(u.get("conviction_source") or "")
    if u.get("held_shares") or src == "current_holding":
        return "holdings"
    if src.startswith("watchlist"):
        return "watchlist_buy_strong_buy"
    return "injected"


def _resolve_universe_underlyings(universe: str, u_cfg: dict, floor: float) -> List[dict]:
    """Resolve the selected universe tiers to underlying dicts (pre-cap, deduped).

    holdings + watchlist keep the original conviction-ranked resolver (behavior
    preserved); other tiers come from lib.options_pipeline.universe. Precedence:
    holdings > watchlist > static/discovery tiers (first occurrence wins).
    """
    tiers_cfg = u_cfg.get("tiers") or {}
    wanted = UNIVERSE_SELECTORS[universe] or list(u_cfg.get("tier_precedence") or [])
    merged: Dict[str, dict] = {}

    if "holdings" in wanted or "watchlist_buy_strong_buy" in wanted:
        rich = resolve_eligible_underlyings(limit=10_000, conviction_floor=floor)
        for u in rich:
            tier = "holdings" if u.get("held_shares") else "watchlist_buy_strong_buy"
            t_cfg = tiers_cfg.get(tier) or {}
            if tier not in wanted or not t_cfg.get("enabled", True):
                continue
            merged[u["symbol"]] = dict(
                u, source_tier=tier,
                strategy_allowlist=list(t_cfg.get("strategy_allowlist") or []),
                reason_included=t_cfg.get("reason_included"))

    others = [t for t in wanted if t not in ("holdings", "watchlist_buy_strong_buy")]
    if others:
        for e in resolve_universe(others, config=u_cfg):
            merged.setdefault(e["symbol"], e)
    return list(merged.values())


def _blank_tier_stats() -> dict:
    return {"resolved": 0, "scanned": 0, "winners": 0, "rejects": 0,
            "allowlist_skipped": 0}


def _market_session_note() -> dict:
    try:
        from market_session import current_market_session
        session = current_market_session()
    except Exception:
        session = "unknown"
    note = ""
    if session in ("weekend", "holiday", "closed"):
        note = (f"market session={session} — option chains may be stale or empty; "
                "per-underlying results degrade honestly (no fabricated quotes)")
    return {"session": session, "note": note}


def run_scan(
    *,
    strategy: str = STRATEGY_ID,
    dry_run: bool = True,
    universe: str = DEFAULT_UNIVERSE,
    limit_underlyings: Optional[int] = None,
    top_n: Optional[int] = None,
    underlyings: Optional[List[dict]] = None,
    analysis_fn: Optional[Callable[..., dict]] = None,
    queue_writer: Optional[Callable[[List[dict]], dict]] = None,
    matcher_fn: Optional[Callable[..., dict]] = None,
) -> dict:
    """Full scan: universe → eligibility → feasibility → gates → rank → (queue top N | dry-run).

    strategy=deep_itm_call (default) keeps the exact Stage-1 single-strategy
    flow. atm_call / atm_put / all route through the per-symbol strategy
    matcher (multi-strategy report shape with per_strategy counts).

    Injectable underlyings/analysis_fn/queue_writer/matcher_fn keep this
    deterministic in tests.
    """
    if strategy not in SUPPORTED_STRATEGIES:
        return {"ok": False, "error": f"unsupported strategy '{strategy}' "
                                      f"(supported: {list(SUPPORTED_STRATEGIES)})"}
    if strategy != STRATEGY_ID:
        return _run_multi_strategy_scan(
            strategy=strategy, dry_run=dry_run, universe=universe,
            limit_underlyings=limit_underlyings, top_n=top_n,
            underlyings=underlyings, analysis_fn=analysis_fn,
            queue_writer=queue_writer, matcher_fn=matcher_fn)
    return _run_deep_itm_scan(
        strategy=strategy, dry_run=dry_run, universe=universe,
        limit_underlyings=limit_underlyings, top_n=top_n,
        underlyings=underlyings, analysis_fn=analysis_fn,
        queue_writer=queue_writer)


def _run_deep_itm_scan(
    *,
    strategy: str,
    dry_run: bool,
    universe: str,
    limit_underlyings: Optional[int],
    top_n: Optional[int],
    underlyings: Optional[List[dict]],
    analysis_fn: Optional[Callable[..., dict]],
    queue_writer: Optional[Callable[[List[dict]], dict]],
) -> dict:
    """Stage-1 deep-ITM single-strategy flow — behavior preserved verbatim."""
    cfg = load_pipeline_config()
    # Lifecycle + safety refusals (fail-closed): paused/killed configs never scan;
    # a config that lost its paper-only guarantees never scans.
    status = (cfg.get("status") or "UNVALIDATED").upper()
    if status in ("PAUSED", "KILLED"):
        return {"ok": False, "error": f"strategy {strategy} status={status} — scanner refuses to run"}
    if not cfg.get("paper_only") or cfg.get("execution_mode") != "manual_review_only" \
            or (cfg.get("execution") or {}).get("live_allowed"):
        return {"ok": False, "error": "config integrity check failed — deep_itm_call must be "
                                      "paper_only + manual_review_only with live_allowed=false"}

    # Strategy registry gate (fail-closed): an invalid registry — including any
    # live_enabled=true row without the explicit policy env — refuses the scan.
    try:
        registry = load_strategy_registry()
    except RegistryConfigError as e:
        return {"ok": False, "error": f"strategy registry invalid — scanner refuses (fail-closed): {e}"}
    reg_row = (registry.get("strategies") or {}).get(strategy)
    if reg_row is not None and not reg_row.get("paper_enabled"):
        return {"ok": False, "error": f"strategy {strategy} has paper_enabled=false "
                                      "in options_strategy_registry — scanner refuses to run"}

    # Universe config (fail-closed) — also supplies default limit/top caps.
    if universe not in UNIVERSE_SELECTORS:
        return {"ok": False, "error": f"unknown universe selector '{universe}' "
                                      f"(known: {sorted(UNIVERSE_SELECTORS)})"}
    try:
        u_cfg = load_universe_config()
    except UniverseConfigError as e:
        return {"ok": False, "error": f"options universe config invalid — scanner refuses (fail-closed): {e}"}
    u_defaults = u_cfg.get("defaults") or {}

    policy = cfg.get("selection_policy") or {}
    cap = int(limit_underlyings or u_defaults.get("max_underlyings_per_run")
              or policy.get("max_underlyings_per_run") or 15)
    winners_cap = int(top_n or u_defaults.get("max_proposals_per_run")
                      or policy.get("max_proposals_per_run") or 5)
    floor = _f((cfg.get("underlying_quality_gate") or {}).get("conviction_floor"), 0.55)

    session = _market_session_note()
    if underlyings is None:
        underlyings = _resolve_universe_underlyings(universe, u_cfg, floor)

    # Per-tier accounting + strategy allowlist enforcement (skip ≠ reject silently).
    tier_stats: Dict[str, dict] = {}

    def _bump(tier: str, key: str, n: int = 1) -> None:
        tier_stats.setdefault(tier, _blank_tier_stats())[key] += n

    scan_list: List[dict] = []
    allowlist_skips: List[dict] = []
    for u in underlyings:
        _bump(_tier_of(u), "resolved")
        if strategy_allowed_for_entry(u, strategy):
            scan_list.append(u)
        else:
            allowlist_skips.append(u)
            _bump(_tier_of(u), "allowlist_skipped")
    scan_list = scan_list[:cap]
    for u in scan_list:
        _bump(_tier_of(u), "scanned")

    # Generator honors its own policy cap — align it with the scanner's cap.
    gen_cfg = dict(cfg)
    gen_cfg["selection_policy"] = dict(policy, max_underlyings_per_run=cap)
    gen = generate_deep_itm_proposals(scan_list, gen_cfg, analysis_fn=analysis_fn)
    ranked = gen.get("proposals") or []
    winners = ranked[:winners_cap]
    # Stage 2 (Part E payload): the desk card gates its Send-to-Alpaca-Paper
    # button on the registry's per-strategy alpaca_paper_enabled, captured at
    # scan time. Meta-only disclosure — grants nothing by itself.
    for w in winners:
        w.setdefault("meta", {})["alpaca_paper_enabled"] = bool(
            (reg_row or {}).get("alpaca_paper_enabled"))

    tier_by_symbol = {u["symbol"]: _tier_of(u) for u in scan_list}
    ok_symbols = {pu.get("symbol") for pu in (gen.get("per_underlying") or [])
                  if pu.get("status") == "ok"}
    for u in scan_list:
        if u["symbol"] not in ok_symbols:
            _bump(tier_by_symbol[u["symbol"]], "rejects")
    for w in winners:
        _bump(tier_by_symbol.get(w.get("symbol"), "injected"), "winners")

    per_underlying = [
        {"symbol": u["symbol"], "status": "skipped",
         "reason": f"strategy {strategy} not in {_tier_of(u)} tier strategy_allowlist"}
        for u in allowlist_skips
    ] + list(gen.get("per_underlying") or [])

    queue_result: dict = {"ok": True, "skipped": True, "reason": "dry_run — nothing written"}
    if not dry_run and winners:
        writer = queue_writer or submit_to_desk_queue
        queue_result = writer(winners)
    elif not dry_run:
        queue_result = {"ok": True, "upserted": 0, "reason": "no winners passed gates"}

    return {
        "ok": True,
        "strategy": strategy,
        "dry_run": dry_run,
        "universe": universe,
        "generated_at": gen.get("generated_at"),
        "market_session": session,
        "underlyings_considered": len(scan_list),
        "underlyings": [{"symbol": u["symbol"], "conviction": u["conviction"],
                         "source": u.get("conviction_source"),
                         "tier": _tier_of(u)} for u in scan_list],
        "tier_stats": tier_stats,
        "per_underlying": per_underlying,
        "candidates_passed_gates": len(ranked),
        "winners": winners,
        "winner_summary": [
            {"symbol": p.get("symbol"), "strike": p.get("strike"), "exp": p.get("expiration"),
             "dte": p.get("dte"), "delta": p.get("delta"), "debit": p.get("premium_total"),
             "breakeven": p.get("breakeven"), "edge_score": p.get("edge_score"),
             "iv_context": p.get("iv_context"),
             "discovery_ref": (p.get("meta") or {}).get("discovery_ref", {}).get("candidate_id")}
            for p in winners
        ],
        "queue_result": queue_result,
        "queue_target": "options_approval_queue (existing options desk manual-review lane)",
        "suggested_cron": SUGGESTED_CRON,
    }


# ── MULTI-STRATEGY Stage 2 (operator spec Part D): matcher-driven scan ────────

DEGRADED_MARKER = "chain unavailable"   # matcher fail-reason prefix for degraded chains
PER_SYMBOL_REPORT_CAP = 40              # --json verbosity cap (honest, disclosed)


def _blank_strategy_stats() -> dict:
    return {"scanned": 0, "pass": 0, "watch": 0, "fail": 0,
            "not_applicable": 0, "degraded": 0, "skipped": 0,
            "queued": 0, "top_symbols": []}


def _strategy_allowed_for_underlying(u: dict, sid: str,
                                     reg_row: Optional[dict]) -> tuple:
    """(allowed, reason) — per-strategy tier gating for the multi-strategy scan.

    Two tier gates exist: the universe tier's strategy_allowlist
    (config/options_universe.yaml, Stage 1) and the registry row's
    allowed_underlying_tiers (config/options_strategy_registry.yaml — the gate
    source of record for WHERE a strategy may run). Both are honored. The
    Stage-1 universe allowlists predate the ATM pair, so for atm_call/atm_put
    a tier the REGISTRY explicitly admits scans even when the older tier
    allowlist does not mention the strategy (disclosed semantics, not a
    live/execution gate — the desk's paper walls are untouched).
    """
    tier = _tier_of(u)
    reg_tiers = (reg_row or {}).get("allowed_underlying_tiers") or []
    if reg_tiers and tier != "injected" and tier not in reg_tiers:
        return False, f"tier {tier} not in registry allowed_underlying_tiers"
    allow = u.get("strategy_allowlist") or []
    if allow and sid not in allow:
        if sid in ("atm_call", "atm_put") and tier in reg_tiers:
            return True, ""   # registry admits the tier; Stage-1 allowlist predates ATM
        return False, f"strategy {sid} not in {tier} tier strategy_allowlist"
    return True, ""


def _load_paper_strategy_config(sid: str) -> dict:
    """Per-strategy pipeline config (deep-ITM loader for deep_itm_call, ATM
    loader for atm_call/atm_put). LivePolicyViolation propagates (fail-closed)."""
    if sid == STRATEGY_ID:
        return load_pipeline_config()
    from lib.options_pipeline.atm_long_premium_generator import (
        load_pipeline_config as load_atm_pipeline_config)
    return load_atm_pipeline_config(sid)


def _strategy_refusal(sid: str) -> Optional[str]:
    """Honest per-strategy lifecycle/safety refusal reason, or None if scannable.

    Mirrors the Stage-1 deep-ITM refusals: PAUSED/KILLED never scan; a config
    that lost its paper-only guarantees never scans (fail-closed)."""
    try:
        cfg = _load_paper_strategy_config(sid)
    except Exception as e:
        return f"strategy {sid} config failed to load (fail-closed): {str(e)[:140]}"
    status = (cfg.get("status") or "UNVALIDATED").upper()
    if status in ("PAUSED", "KILLED"):
        return f"strategy {sid} status={status} — scanner refuses to run"
    if not cfg.get("paper_only") or cfg.get("execution_mode") != "manual_review_only" \
            or (cfg.get("execution") or {}).get("live_allowed"):
        return (f"config integrity check failed — {sid} must be paper_only + "
                "manual_review_only with live_allowed=false")
    return None


def _why_matched(sid: str, status: str, reason: str, proposal: dict,
                 matcher_context: dict) -> str:
    """One honest line: this strategy's pass/watch reason + the thesis source."""
    intel = (proposal.get("meta") or {}).get("underlying_intel") or {}
    thesis_src = intel.get("conviction_source")
    if not thesis_src:
        key = "bearish_source" if sid == "atm_put" else "bullish_source"
        thesis_src = (matcher_context or {}).get(key) or "unknown"
    why = f"{reason} · thesis: {thesis_src}"
    if intel.get("conviction") is not None:
        try:
            why += f" (conviction {round(float(intel['conviction']) * 100)}%)"
        except (TypeError, ValueError):
            pass
    return why


def _run_multi_strategy_scan(
    *,
    strategy: str,
    dry_run: bool,
    universe: str,
    limit_underlyings: Optional[int],
    top_n: Optional[int],
    underlyings: Optional[List[dict]],
    analysis_fn: Optional[Callable[..., dict]],
    queue_writer: Optional[Callable[[List[dict]], dict]],
    matcher_fn: Optional[Callable[..., dict]],
) -> dict:
    """Matcher-driven scan for atm_call / atm_put / all.

    Per symbol: run_matchers evaluates every requested strategy honestly
    (pass/watch/fail/not_applicable + reason). pass/watch proposals rank per
    strategy and the top N per strategy queue via the SAME fail-closed
    submit_to_desk_queue upsert the deep-ITM lane uses (idempotent on the
    deterministic proposal_id; live_eligible true is never written). Each
    queued row carries meta.match_json {why_matched, other_strategies} and
    meta.alpaca_paper_enabled (registry, at scan time) for the desk card.
    """
    from datetime import datetime, timezone

    # Strategy registry gate (fail-closed) — an invalid registry refuses the scan.
    try:
        registry = load_strategy_registry()
    except RegistryConfigError as e:
        return {"ok": False, "error": f"strategy registry invalid — scanner refuses (fail-closed): {e}"}
    known = registry.get("strategies") or {}

    strategy_notes: Dict[str, str] = {}
    if strategy == "all":
        wanted: List[str] = []
        for sid in SCANNER_STRATEGIES:
            row = known.get(sid)
            if row is None:
                strategy_notes[sid] = "not in options_strategy_registry — excluded"
            elif not row.get("paper_enabled"):
                strategy_notes[sid] = (f"paper_enabled=false in registry "
                                       f"(status {row.get('status')}) — excluded")
            else:
                wanted.append(sid)
    else:
        row = known.get(strategy)
        if row is not None and not row.get("paper_enabled"):
            return {"ok": False, "error": f"strategy {strategy} has paper_enabled=false "
                                          "in options_strategy_registry — scanner refuses to run"}
        wanted = [strategy]

    active: List[str] = []
    for sid in wanted:
        refusal = _strategy_refusal(sid)
        if refusal is None:
            active.append(sid)
        elif strategy == "all":
            strategy_notes[sid] = refusal      # all: exclude + disclose, keep scanning
        else:
            return {"ok": False, "error": refusal}
    if not active:
        return {"ok": False, "strategy_notes": strategy_notes,
                "error": "no scanner-supported strategy is paper_enabled — nothing to scan"}

    # Universe config (fail-closed) — same defaults/caps as the Stage-1 flow.
    if universe not in UNIVERSE_SELECTORS:
        return {"ok": False, "error": f"unknown universe selector '{universe}' "
                                      f"(known: {sorted(UNIVERSE_SELECTORS)})"}
    try:
        u_cfg = load_universe_config()
    except UniverseConfigError as e:
        return {"ok": False, "error": f"options universe config invalid — scanner refuses (fail-closed): {e}"}
    u_defaults = u_cfg.get("defaults") or {}
    cap = int(limit_underlyings or u_defaults.get("max_underlyings_per_run") or 15)
    winners_cap = int(top_n or u_defaults.get("max_proposals_per_run") or 5)
    try:   # same resolver junk-floor the deep-ITM flow uses; matcher owns real gates
        floor = _f((load_pipeline_config().get("underlying_quality_gate") or {})
                   .get("conviction_floor"), 0.55)
    except Exception:
        floor = 0.55

    session = _market_session_note()
    if underlyings is None:
        underlyings = _resolve_universe_underlyings(universe, u_cfg, floor)

    tier_stats: Dict[str, dict] = {}

    def _bump(tier: str, key: str, n: int = 1) -> None:
        tier_stats.setdefault(tier, _blank_tier_stats())[key] += n

    per_symbol: List[dict] = []
    scan_rows: List[tuple] = []   # (underlying, allowed_strategy_ids, {sid: skip_reason})
    for u in underlyings:
        _bump(_tier_of(u), "resolved")
        allowed, skipped = [], {}
        for sid in active:
            ok, reason = _strategy_allowed_for_underlying(u, sid, known.get(sid))
            (allowed.append(sid) if ok else skipped.__setitem__(sid, reason))
        if allowed:
            scan_rows.append((u, allowed, skipped))
        else:
            _bump(_tier_of(u), "allowlist_skipped")
            per_symbol.append({
                "symbol": u["symbol"], "tier": _tier_of(u), "status": "skipped",
                "reason": f"no scanned strategy allowed for {_tier_of(u)} tier "
                          "(tier strategy_allowlist / registry allowed_underlying_tiers)"})
    scan_rows = scan_rows[:cap]
    for u, _allowed, _skipped in scan_rows:
        _bump(_tier_of(u), "scanned")

    matcher = matcher_fn or run_matchers
    stats: Dict[str, dict] = {sid: _blank_strategy_stats() for sid in active}
    candidates: Dict[str, List[dict]] = {sid: [] for sid in active}
    tier_by_symbol = {u["symbol"]: _tier_of(u) for u, _a, _s in scan_rows}

    for u, allowed, skipped in scan_rows:
        sym = u["symbol"]
        context = {k: u[k] for k in ("verdict", "held_shares", "conviction",
                                     "conviction_source")
                   if u.get(k) is not None}
        kwargs: Dict[str, object] = {"registry": registry}
        if analysis_fn is not None:
            kwargs["deep_itm_analysis_fn"] = analysis_fn
        try:
            res = matcher(sym, context, allowed, **kwargs)
        except Exception as e:   # one bad symbol never kills the run — disclosed
            per_symbol.append({"symbol": sym, "tier": tier_by_symbol[sym],
                               "status": "error", "reason": str(e)[:160]})
            continue
        results = (res or {}).get("strategy_results") or {}
        sym_detail = {"symbol": sym, "tier": tier_by_symbol[sym], "strategies": {}}
        for sid, skip_reason in skipped.items():
            stats[sid]["skipped"] += 1
            sym_detail["strategies"][sid] = {"status": "skipped",
                                             "reason": skip_reason[:160]}
        for sid in allowed:
            r = results.get(sid) or {"status": "fail",
                                     "reason": "matcher returned no result for this strategy"}
            st = str(r.get("status") or "fail")
            reason = str(r.get("reason") or "")
            stats[sid]["scanned"] += 1
            if st == "fail" and DEGRADED_MARKER in reason:
                stats[sid]["degraded"] += 1
            elif st in ("pass", "watch", "fail", "not_applicable"):
                stats[sid][st] += 1
            else:
                stats[sid]["fail"] += 1
            sym_detail["strategies"][sid] = {"status": st, "reason": reason[:160]}
            if st in ("pass", "watch") and r.get("proposals"):
                others = {osid: {"status": (results.get(osid) or {}).get("status"),
                                 "reason": str((results.get(osid) or {}).get("reason")
                                               or "")[:160]}
                          for osid in results if osid != sid}
                alpaca_ok = bool((known.get(sid) or {}).get("alpaca_paper_enabled"))
                for p in r["proposals"]:
                    meta = p.setdefault("meta", {})
                    meta["match_json"] = {
                        "strategy": sid,
                        "status": st,
                        "why_matched": _why_matched(sid, st, reason, p,
                                                    (res or {}).get("context") or {}),
                        "other_strategies": others,
                    }
                    meta["alpaca_paper_enabled"] = alpaca_ok
                candidates[sid].extend(r["proposals"])
        per_symbol.append(sym_detail)

    # Rank + cap per strategy → the queue set (dry-run: reported, not written).
    winners: List[dict] = []
    for sid in active:
        ranked = sorted(candidates[sid], key=lambda p: -_f(p.get("edge_score")))
        picked = ranked[:winners_cap]
        stats[sid]["queued"] = len(picked)
        stats[sid]["top_symbols"] = list(dict.fromkeys(
            str(p.get("symbol")) for p in picked))[:5]
        winners.extend(picked)

    winner_symbols = {p.get("symbol") for p in winners}
    for w in winners:
        _bump(tier_by_symbol.get(w.get("symbol"), "injected"), "winners")
    for u, _allowed, _skipped in scan_rows:
        if u["symbol"] not in winner_symbols:
            _bump(tier_by_symbol[u["symbol"]], "rejects")

    queue_result: dict = {"ok": True, "skipped": True, "reason": "dry_run — nothing written"}
    if not dry_run and winners:
        writer = queue_writer or submit_to_desk_queue
        queue_result = writer(winners)
    elif not dry_run:
        queue_result = {"ok": True, "upserted": 0, "reason": "no winners passed gates"}

    return {
        "ok": True,
        "strategy": strategy,
        "strategies": active,
        "strategy_notes": strategy_notes,
        "dry_run": dry_run,
        "universe": universe,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_session": session,
        "underlyings_considered": len(scan_rows),
        "underlyings": [{"symbol": u["symbol"], "conviction": u.get("conviction"),
                         "source": u.get("conviction_source"),
                         "tier": _tier_of(u)} for u, _a, _s in scan_rows],
        "tier_stats": tier_stats,
        "per_strategy": stats,
        "per_symbol": per_symbol[:PER_SYMBOL_REPORT_CAP],
        "per_symbol_truncated": max(0, len(per_symbol) - PER_SYMBOL_REPORT_CAP),
        "candidates_passed_gates": sum(len(v) for v in candidates.values()),
        "winners": winners,
        "winner_summary": [
            {"symbol": p.get("symbol"), "strategy": p.get("strategy"),
             "strike": p.get("strike"), "exp": p.get("expiration"),
             "dte": p.get("dte"), "delta": p.get("delta"),
             "debit": p.get("premium_total"), "breakeven": p.get("breakeven"),
             "edge_score": p.get("edge_score"),
             "match_status": ((p.get("meta") or {}).get("match_json") or {}).get("status")}
            for p in winners
        ],
        "queue_result": queue_result,
        "queue_target": "options_approval_queue (existing options desk manual-review lane)",
        "suggested_cron": SUGGESTED_CRON,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Paper-only options strategy winner scanner (Stage A)")
    ap.add_argument("--run", action="store_true", help="scan and queue winners (manual-review lane)")
    ap.add_argument("--dry-run", action="store_true", help="scan and print — write NOTHING")
    ap.add_argument("--json", action="store_true", help="emit full JSON result")
    # No argparse choices on purpose: unknown strategies refuse inside run_scan
    # with an honest report-shaped error (Stage-1 behavior, test-enforced).
    ap.add_argument("--strategy", default=STRATEGY_ID,
                    help="deep_itm_call (default, Stage-1 flow) | atm_call | "
                         "atm_put | all (every registry paper_enabled "
                         "scanner-supported strategy, per-symbol matcher)")
    ap.add_argument("--universe", default=DEFAULT_UNIVERSE,
                    choices=sorted(UNIVERSE_SELECTORS),
                    help="universe tiers to scan (config/options_universe.yaml); "
                         f"default {DEFAULT_UNIVERSE} = original scanner scope")
    ap.add_argument("--limit", type=int, default=None, help="max underlyings (default from config)")
    ap.add_argument("--top", type=int, default=None, help="max winners queued (default from config)")
    args = ap.parse_args(argv)

    if args.run and args.dry_run:
        print("ERROR: choose one of --run or --dry-run", file=sys.stderr)
        return 2
    dry = not args.run  # default safe: dry-run unless --run given explicitly

    result = run_scan(strategy=args.strategy, dry_run=dry, universe=args.universe,
                      limit_underlyings=args.limit, top_n=args.top)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        if not result.get("ok"):
            print(f"SCAN REFUSED: {result.get('error')}")
            return 1
        ms = result["market_session"]
        strategies_bit = (f" strategies={','.join(result['strategies'])}"
                          if result.get("strategies") else "")
        print(f"[{result['strategy']}] {'DRY-RUN' if result['dry_run'] else 'RUN'} "
              f"— universe={result.get('universe')} session={ms['session']}"
              f"{strategies_bit}")
        if ms.get("note"):
            print(f"  note: {ms['note']}")
        for sid, note in (result.get("strategy_notes") or {}).items():
            print(f"  excluded {sid}: {note}")
        print(f"  underlyings considered: {result['underlyings_considered']}")
        for tier, st in (result.get("tier_stats") or {}).items():
            print(f"  tier {tier:26} resolved={st['resolved']:<3} scanned={st['scanned']:<3} "
                  f"winners={st['winners']:<2} rejects={st['rejects']:<3} "
                  f"allowlist_skipped={st['allowlist_skipped']}")
        if result.get("per_strategy") is not None:
            # MULTI-STRATEGY report shape (atm_call / atm_put / all)
            for sid, st in result["per_strategy"].items():
                print(f"  strategy {sid:14} scanned={st['scanned']:<3} pass={st['pass']:<2} "
                      f"watch={st['watch']:<2} fail={st['fail']:<3} "
                      f"n/a={st['not_applicable']:<2} degraded={st['degraded']:<3} "
                      f"skipped={st.get('skipped', 0):<3} queued={st['queued']:<2} "
                      f"top={','.join(st['top_symbols']) or '—'}")
            for row in result.get("per_symbol") or []:
                if row.get("strategies"):
                    bits = "  ".join(
                        f"{sid}={d['status']}"
                        + (f"({d['reason'][:60]})" if d.get("reason")
                           and d["status"] != "pass" else "")
                        for sid, d in row["strategies"].items())
                    print(f"  {row['symbol']:6} {bits}")
                else:
                    print(f"  {row['symbol']:6} {row.get('status')} — {row.get('reason')}")
            if result.get("per_symbol_truncated"):
                print(f"  … {result['per_symbol_truncated']} more symbol(s) "
                      "(--json for the capped detail)")
        else:
            for pu in result.get("per_underlying") or []:
                line = f"  {pu['symbol']:6} {pu['status']}"
                if pu.get("reason"):
                    line += f" — {pu['reason']}"
                if pu.get("proposals"):
                    line += f" — {pu['proposals']} proposal(s)"
                print(line)
        print(f"  gate survivors: {result['candidates_passed_gates']} — "
              f"winners queued: {0 if result['dry_run'] else len(result['winners'])}"
              f"{' (dry-run: printed only)' if result['dry_run'] else ''}")
        for w in result["winner_summary"]:
            strat_bit = f" [{w['strategy']}]" if w.get("strategy") else ""
            ivc = w.get("iv_context") or {}
            iv_bit = (f" IVrank={ivc.get('iv_rank')}%({ivc.get('verdict')})"
                      if ivc.get("available")
                      else (f" IV:{(ivc.get('reason') or 'n/a')[:28]}"
                            if ivc else ""))
            tail = " → discovery #339" if result.get("per_strategy") is None else ""
            print(f"    {w['symbol']:6}{strat_bit} ${w['strike']} {w['exp']} ({w['dte']}d) "
                  f"Δ{w['delta']} debit=${w['debit']} BE=${w['breakeven']} "
                  f"score={w['edge_score']}{iv_bit}{tail}")
        print(f"  queue: {json.dumps(result['queue_result'], default=str)}")
        print(f"  suggested cron (NOT installed): {SUGGESTED_CRON}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
