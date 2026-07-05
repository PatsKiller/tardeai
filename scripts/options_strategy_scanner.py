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

Usage:
    .venv/bin/python scripts/options_strategy_scanner.py --dry-run [--json]
    .venv/bin/python scripts/options_strategy_scanner.py --dry-run --universe all
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

SUPPORTED_STRATEGIES = (STRATEGY_ID,)
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
) -> dict:
    """Full scan: universe → eligibility → feasibility → gates → rank → (queue top N | dry-run).

    Injectable underlyings/analysis_fn/queue_writer keep this deterministic in tests.
    """
    if strategy not in SUPPORTED_STRATEGIES:
        return {"ok": False, "error": f"unsupported strategy '{strategy}' "
                                      f"(supported: {list(SUPPORTED_STRATEGIES)})"}

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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Paper-only options strategy winner scanner (Stage A)")
    ap.add_argument("--run", action="store_true", help="scan and queue winners (manual-review lane)")
    ap.add_argument("--dry-run", action="store_true", help="scan and print — write NOTHING")
    ap.add_argument("--json", action="store_true", help="emit full JSON result")
    ap.add_argument("--strategy", default=STRATEGY_ID)
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
        print(f"[{result['strategy']}] {'DRY-RUN' if result['dry_run'] else 'RUN'} "
              f"— universe={result.get('universe')} session={ms['session']}")
        if ms.get("note"):
            print(f"  note: {ms['note']}")
        print(f"  underlyings considered: {result['underlyings_considered']}")
        for tier, st in (result.get("tier_stats") or {}).items():
            print(f"  tier {tier:26} resolved={st['resolved']:<3} scanned={st['scanned']:<3} "
                  f"winners={st['winners']:<2} rejects={st['rejects']:<3} "
                  f"allowlist_skipped={st['allowlist_skipped']}")
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
            ivc = w.get("iv_context") or {}
            iv_bit = (f" IVrank={ivc.get('iv_rank')}%({ivc.get('verdict')})"
                      if ivc.get("available")
                      else f" IV:{(ivc.get('reason') or 'n/a')[:28]}")
            print(f"    {w['symbol']:6} ${w['strike']} {w['exp']} ({w['dte']}d) "
                  f"Δ{w['delta']} debit=${w['debit']} BE=${w['breakeven']} "
                  f"score={w['edge_score']}{iv_bit} → discovery #339")
        print(f"  queue: {json.dumps(result['queue_result'], default=str)}")
        print(f"  suggested cron (NOT installed): {SUGGESTED_CRON}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
