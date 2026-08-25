#!/usr/bin/env python3
"""research_scheduler.py — tiered, SLA-driven, priority-ordered external/LLM research dispatcher.

Implements docs/RESEARCH_PRIORITIZATION.md + docs/ops/RESEARCH_LIFECYCLE_STANDARD.md:
  • Assigns every tracked symbol the highest tier it qualifies for (holdings > proposals > watchlist >
    incubator > cold universe). Reentry READY/NEAR join existing T1-WATCH (no new tier).
  • Enforces a per-tier refresh SLA ("at least X times in Y days") per external lane.
  • Orders the due set by an exposure/overdue/catalyst/rank/divergence priority score.
  • Dispatches within a per-run external-lane budget (so the free OAuth lanes don't exhaust).
  • Holdings (T0) are refreshed several times/day; material changes fingerprint downstream
    (`_research_fingerprint` on recommendation+confidence) — that is NOT the skip-before-call hash.
  • Skip-before-call (flag RESEARCH_SKIP_GATE, default OFF): execute_set = due ∩ (changed ∪ stale ∪
    triggered). Unchanged in-window sources are SKIP_UNCHANGED; hours-window reuse is SKIP_FRESH.
  • Local generative LLM routing is forbidden. DeepSeek remains the automatic judgment lane.
    ChatGPT OAuth overnight stays on the governed cloud path.

Modes: holdings | priority | watchlist | incubator | cold-floor | backfill
Dry by default; pass --apply to actually call the lanes. All numbers env-tunable (RESEARCH_*).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from watchlist_priority import WATCHLIST_TOP_N
from lib.research_call_accounting import (
    accounting_identity,
    append_event as append_call_event,
    call_id_for,
    new_run_id,
)
PY = str(ROOT / ".venv" / "bin" / "python")
RESEARCHER = str(ROOT / "scripts" / "hermes_external_researcher.py")

# ── tunables (env-overridable) ───────────────────────────────────────────────
EXTERNAL_BUDGET = int(os.getenv("RESEARCH_EXTERNAL_BUDGET_PER_RUN", "40"))
TOP_RANK_N      = int(os.getenv("RESEARCH_TOP_RANK_N", str(WATCHLIST_TOP_N)))
COLD_FLOOR_DAYS = int(os.getenv("RESEARCH_COLD_FLOOR_DAYS", "14"))
CALL_TIMEOUT    = int(os.getenv("RESEARCH_CALL_TIMEOUT", "150"))

# ── Hermes lane registry (the whole 24/7 fleet, cheapest→scarcest) ────────────
# DeepSeek is the governed V4 Flash external challenge (paid, no fallback) — the primary automated
# judgment lane. Claude is metered arbitration only and is never automatic here.
# grok/chatgpt OAuth are retained in LANES but not auto-dispatched by this scheduler. ChatGPT
# overnight judgment stays on hermes_deep_research_local (overnight_llm_policy).
LANES = {
    "deepseek":      {"cost": "metered",      "dispatch": "external", "auto": True},
    "grok":          {"cost": "free-limited", "dispatch": "external", "auto": False},
    "chatgpt":       {"cost": "free-limited", "dispatch": "external", "auto": False},
    "claude":        {"cost": "metered",      "dispatch": "external", "auto": False},  # arbitration only
}

# tier → (sla_refreshes, sla_window_days, lanes[]). Local listed for SLA accounting; auto-enqueue
# of queue lanes is gated by allow_local_research_llm(). Externals are tier-gated.
TIER_SLA = {
    "T0-HOLD":  (3, 1,  ["deepseek"]),
    "T0-PROP":  (2, 1,  ["deepseek"]),
    "T1-WATCH": (4, 7,  ["deepseek"]),
    "T2-INCUB": (1, 7,  ["deepseek"]),  # external only on catalyst
    "T3-COLD":  (1, 14, ["deepseek"]),  # DeepSeek only on catalyst; no 14d sweep
}
TIER_WEIGHT = {"T0-HOLD": 1.0, "T0-PROP": 0.9, "T1-WATCH": 0.6, "T2-INCUB": 0.3, "T3-COLD": 0.1}
EXTERNAL_LANES = {"deepseek", "claude"}

# Thesis-driven / RAG-first commissioning (P1.7). Flags are authoritative for
# AGENT_JOB_PRODUCER_MAP and tests — never invent thesis text.
THESIS_DRIVEN = True
RAG_FIRST = True
# R7.1 practical order when converting autonomous jobs toward thesis gaps:
R71_PIPELINE_ORDER = (
    "gap",
    "rag_support",
    "rag_contradict",
    "structured",
    "acquire_if_needed",
    "synthesize",
)


def thesis_driven_enabled() -> bool:
    raw = os.getenv("RESEARCH_THESIS_DRIVEN", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"} and THESIS_DRIVEN


def rag_first_enabled() -> bool:
    raw = os.getenv("RESEARCH_RAG_FIRST", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"} and RAG_FIRST


def skip_gate_enabled() -> bool:
    """Source-hash skip-before-call. Default OFF — DeepSeek dispatch parity with today."""
    return os.getenv("RESEARCH_SKIP_GATE", "0").strip().lower() not in {
        "0", "false", "no", "off", "",
    }


def allow_local_research_llm() -> bool:
    """Compatibility surface: local generative research cannot be re-enabled."""
    return False


def lanes_for(tier: str) -> list[str]:
    """Cloud lanes this run will consider."""
    _, _, lanes = TIER_SLA[tier]
    return list(lanes)


def build_thesis_gap_commission(
    symbol: str,
    *,
    tier: str,
    gap_request: dict | None = None,
    root: Path | None = None,
) -> dict | None:
    """Build a thesis-gap enqueue payload when gaps exist. Never invents thesis text.

    Returns None when no existing gap/request is available (caller keeps generic path).
    """
    if not thesis_driven_enabled():
        return None
    req = gap_request
    if req is None:
        try:
            from scripts.lib.symbol_thesis_research import research_requests_for_symbol
            reqs = research_requests_for_symbol(symbol, root=root)
            req = reqs[0] if reqs else None
        except Exception:
            req = None
    if not isinstance(req, dict):
        return None
    thesis_id = req.get("thesis_id")
    gap = req.get("research_gap") or req.get("research_gap_id")
    question = req.get("specific_question")
    if not thesis_id or not question:
        return None
    gap_id = (
        req.get("research_gap_id")
        or req.get("request_id")
        or f"gap_{symbol}_{str(gap)[:40]}".replace(" ", "_")[:80]
    )
    materiality = "T1" if str(tier).startswith("T0") or tier == "T1-WATCH" else "T1"
    return {
        "thesis_id": thesis_id,
        "thesis_version": req.get("thesis_version"),
        "research_gap_id": gap_id,
        "research_gap": gap,
        "specific_question": question,  # from coverage gap machinery — not invented
        "RAG_FIRST": True,
        "rag_first": rag_first_enabled(),
        "materiality": materiality,
        "pipeline_order": list(R71_PIPELINE_ORDER),
        "thesis_driven": True,
        "request_type": "thesis_gap_research",
        "note": f"{tier} thesis-gap research (RAG-first); gap={str(gap)[:80]}",
    }


def load_high_value_thesis_gaps(
    symbols: list[str],
    *,
    root: Path | None = None,
    limit: int = 40,
) -> dict[str, dict]:
    """Map symbol → first existing thesis-gap request. Fail-soft; never invents."""
    out: dict[str, dict] = {}
    for sym in symbols[: max(0, int(limit))]:
        s = str(sym or "").upper().strip()
        if not s or s in out:
            continue
        try:
            from scripts.lib.symbol_thesis_research import research_requests_for_symbol
            reqs = research_requests_for_symbol(s, root=root)
        except Exception:
            reqs = []
        if reqs:
            out[s] = reqs[0]
    return out


def _q(sql, params=()):
    try:
        from db_adapter import _execute
        return _execute(sql, params, fetch="all") or []
    except Exception:
        return []


def _is_symbol(s: str) -> bool:
    """T0-HOLD / universe membership. CASH and CUSIPs are not research tickers."""
    try:
        from scripts.lib.holdings_universe import is_held_equity_ticker
    except Exception:
        from lib.holdings_universe import is_held_equity_ticker  # type: ignore
    return is_held_equity_ticker(s)


REENTRY_READY_NEAR_STATES = frozenset({
    "READY TO REVIEW",
    "NEAR ENTRY",
    "READY",
    "NEAR",
})
# Explicitly excluded from T1-WATCH via reentry desk (do not add).
REENTRY_EXCLUDED_STATES = frozenset({
    "WAIT",
    "OVERSOLD",
    "OVERSOLD REVIEW",
    "CURRENTLY HELD",
    "WASH BLOCK",
    "STALE",
    "MISSING MARKET",
    "MISSING PLAN",
    "OVERBOUGHT WAIT",
    "BLOCK",
})


def load_reentry_ready_near_symbols(*, root: Path | None = None) -> list[str]:
    """READY/NEAR reentry names as T1-WATCH candidates. Fail-soft if the desk file is missing.

    Reads CURRENT-style path: <root>/data/runtime/reentry_decision_desk_latest.json
    rows[].intel.state (and scorecard READY/NEAR labels). Does not add WAIT / OVERSOLD /
    CURRENTLY HELD. CASH is not a ticker (`_is_symbol`).
    """
    path = (root or ROOT) / "data" / "runtime" / "reentry_decision_desk_latest.json"
    try:
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    rows = data.get("rows") if isinstance(data, dict) else None
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("held") is True:
            continue
        intel = row.get("intel") if isinstance(row.get("intel"), dict) else {}
        state = str(
            intel.get("state") or row.get("state") or row.get("status") or ""
        ).strip().upper()
        if state in REENTRY_EXCLUDED_STATES:
            continue
        if state not in REENTRY_READY_NEAR_STATES:
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if _is_symbol(sym):
            out.append(sym)
    return sorted(set(out))


# ── universe assembly ────────────────────────────────────────────────────────
def load_universe(*, root: Path | None = None) -> dict:
    """Research-priority index from the canonical Transferson universe.

    Membership (including WAIT/sold history) lives in
    scripts.lib.transferson_universe. This function remains the scheduler's
    highest-tier view and must not treat graph-profile count as the universe.
    """
    root = root or ROOT
    from scripts.lib.transferson_universe import collect_live_sources
    from scripts.lib.transferson_universe import load_universe as load_manifest
    from scripts.lib.transferson_universe import research_tier_index
    sources = collect_live_sources(root=root, top_rank_n=int(TOP_RANK_N))
    return research_tier_index(load_manifest(root=root, sources=sources))


def _tier_order(t: str) -> int:
    return ["T0-HOLD", "T0-PROP", "T1-WATCH", "T2-INCUB", "T3-COLD"].index(t)


_LANE_ROT_CACHE: dict = {}
_OUTCOME_BUS_CACHE: dict | None = None


def _load_outcome_bus() -> dict:
    """Cached read of nightly outcome_bus.json (tag multipliers for research depth)."""
    global _OUTCOME_BUS_CACHE
    if _OUTCOME_BUS_CACHE is not None:
        return _OUTCOME_BUS_CACHE
    try:
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        from lib.hermes_outcome_bus.bus import load_outcome_bus, research_tag_multipliers
        bus = load_outcome_bus()
        _OUTCOME_BUS_CACHE = {"bus": bus, "tag_mult": research_tag_multipliers(bus)}
    except Exception:
        _OUTCOME_BUS_CACHE = {"bus": {}, "tag_mult": {}}
    return _OUTCOME_BUS_CACHE


def _load_bus_reactions() -> dict:
    try:
        path = ROOT / "data" / "runtime" / "hermes_bus_reactions.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _watchlist_health_multiplier(sym: str) -> float:
    """Advisory research priority from watchlist health + stop quality component."""
    try:
        from lib.hermes_outcome_bus.lifecycle_slice import watchlist_research_multiplier
        cache = _load_outcome_bus()
        bus = cache.get("bus") or {}
        mult = watchlist_research_multiplier(sym, bus)
        runtime = _load_bus_reactions()
        runtime_mult = (runtime.get("watchlist_research_multipliers") or {}).get(sym.upper())
        if runtime_mult is not None:
            mult = float(runtime_mult)
        return mult
    except Exception:
        return 1.0


def _holdings_lifecycle_multiplier(sym: str) -> float:
    """Advisory research priority boost from holdings lifecycle stage (B2)."""
    try:
        from lib.hermes_outcome_bus.lifecycle_slice import holdings_research_multiplier
        cache = _load_outcome_bus()
        bus = cache.get("bus") or {}
        lc = bus.get("lifecycle") or {}
        if not lc:
            from lib.hermes_outcome_bus.lifecycle_slice import build_lifecycle_slice
            lc = build_lifecycle_slice()
        mult = holdings_research_multiplier(sym, lc)
        runtime = _load_bus_reactions()
        runtime_mult = (runtime.get("holdings_research_multipliers") or {}).get(sym.upper())
        if runtime_mult is not None:
            mult = max(mult, float(runtime_mult))
        return mult
    except Exception:
        return 1.0


def _symbol_tag_multiplier(sym: str, scope_tier: str | None = None) -> float:
    """Apply quality_multiplier for symbol's dominant tag from outcome bus."""
    cache = _load_outcome_bus()
    bus = cache.get("bus") or {}
    tag_mult = cache.get("tag_mult") or {}
    reactions = _load_bus_reactions()
    sym_meta = (bus.get("by_symbol") or {}).get(sym.upper()) or {}
    dom = sym_meta.get("dominant_tag")
    mult = 1.0
    if dom:
        by_tag = (bus.get("by_tag") or {}).get(dom) or {}
        if by_tag.get("quality_multiplier") is not None:
            mult = float(by_tag["quality_multiplier"])
        elif dom in tag_mult:
            mult = float(tag_mult[dom])
    elif tag_mult:
        mult = min(tag_mult.values()) if any(v < 1.0 for v in tag_mult.values()) else 1.0

    overrides = reactions.get("tag_multiplier_overrides") or {}
    if dom and dom in overrides:
        mult = min(mult, float(overrides[dom]))

    hot_boost = float(reactions.get("hot_tier_research_boost") or 1.0)
    hot_tiers = ("S0", "S1", "T0-HOLD", "T0-PROP", "T1-WATCH")
    if hot_boost > 1.0 and scope_tier in hot_tiers:
        mult = min(1.5, mult * hot_boost)
    return mult


def _lane_rotation(ext_lanes: list) -> list:
    """Phase 3: expand the rotation list proportional to each lane's graded outcome hit-rate
    (hermes_lane_usefulness). Below the sample gate → uniform. A floor weight keeps every
    lane in rotation so it can still be measured. Cached per process."""
    key = tuple(sorted(ext_lanes))
    if key in _LANE_ROT_CACHE:
        return _LANE_ROT_CACHE[key]
    rotation = list(ext_lanes)
    try:
        import yaml
        cfg = (yaml.safe_load((ROOT / "config" / "hermes_outcome_learning.yaml").read_text()) or {}).get("lanes", {})
        min_total = int(cfg.get("min_total_graded", 30))
        floor = float(cfg.get("min_lane_weight", 0.15))
        rows = {dict(r)["lane"]: dict(r) for r in _q(
            "SELECT lane, n, hit_rate FROM hermes_lane_usefulness")}
        total = sum((rows.get(l) or {}).get("n") or 0 for l in ext_lanes)
        if total >= min_total:
            weights = {}
            for l in ext_lanes:
                hr = (rows.get(l) or {}).get("hit_rate")
                weights[l] = max(floor, float(hr) if hr is not None else floor)
            wsum = sum(weights.values()) or 1.0
            rotation = []
            for l in ext_lanes:
                rotation += [l] * max(1, round(weights[l] / wsum * 10))
    except Exception:
        rotation = list(ext_lanes)
    _LANE_ROT_CACHE[key] = rotation
    return rotation


def last_real(lane: str) -> dict:
    """symbol -> datetime of latest NON-error research on this lane (errors are '[...]' prefixed)."""
    rows = _q("""SELECT symbol, max(created_at) mx FROM hermes_external_research
                 WHERE lane=%s AND recommendation IS NOT NULL AND recommendation NOT LIKE '[%%'
                 GROUP BY symbol""", (lane,))
    return {dict(r)["symbol"]: dict(r)["mx"] for r in rows}


def catalyst_signals() -> dict:
    """symbol -> bool catalyst today (high RVOL/gap, or social momentum_catalyst)."""
    sig = {}
    for r in _q("""SELECT DISTINCT ON (symbol) symbol, rvol, gap_pct FROM trade_ai_scans
                   WHERE run_date::date = CURRENT_DATE ORDER BY symbol, rvol DESC NULLS LAST"""):
        d = dict(r)
        if (d.get("rvol") or 0) >= 5 or abs(float(d.get("gap_pct") or 0)) >= 10:
            sig[d["symbol"]] = True
    for r in _q("""SELECT DISTINCT symbol FROM hermes_research_intelligence
                   WHERE research_type='momentum_catalyst' AND created_at > NOW() - INTERVAL '36 hours'"""):
        sig[dict(r)["symbol"]] = True
    return sig


def catalyst_event_records() -> dict[str, list[dict]]:
    """Material structured catalyst rows, kept separate from free-form news."""
    out: dict[str, list[dict]] = {}
    rows = _q("""SELECT id, UPPER(symbol) AS symbol, catalyst_type, severity, created_at
                 FROM catalyst_events
                 WHERE created_at > NOW() - INTERVAL '36 hours'
                   AND symbol IS NOT NULL""")
    aliases = {
        "M&A": "M_AND_A",
        "MA": "M_AND_A",
        "FDA_REGULATORY": "FDA",
        "ANALYST": "ANALYST_REVISION",
        "TARGET": "TARGET_REVISION",
    }
    for raw in rows:
        row = dict(raw)
        sym = str(row.get("symbol") or "").upper()
        event_type = str(row.get("catalyst_type") or "").upper().replace(" ", "_")
        event_type = aliases.get(event_type, event_type)
        out.setdefault(sym, []).append({
            "event_id": row.get("id"),
            "type": event_type,
            "severity": str(row.get("severity") or "MEDIUM").upper(),
            "as_of": row.get("created_at"),
        })
    return out


def market_regime_shifted() -> bool:
    rows = [dict(row) for row in _q(
        "SELECT regime_label FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 2"
    )]
    return len(rows) >= 2 and rows[0].get("regime_label") != rows[1].get("regime_label")


def _cached_market(sym: str) -> dict:
    try:
        from scripts.lib.research_prompt_context import _market_snapshot
        return _market_snapshot(sym, ROOT)
    except Exception:
        return {}


def scheduler_trigger_plan(
    sym: str,
    item: dict,
    *,
    events: list[dict],
    thesis_gap: dict | None,
    apply: bool,
    now: datetime | None = None,
) -> dict:
    """One trigger decision for a due scheduler row."""
    try:
        from scripts.lib.research_event_trigger import plan_research_trigger
        from scripts.lib.research_prompt_context import latest_delta
    except Exception:
        from lib.research_event_trigger import plan_research_trigger  # type: ignore
        from lib.research_prompt_context import latest_delta  # type: ignore
    prior_delta = latest_delta(sym, root=ROOT) or {}
    current = _cached_market(sym)
    previous = prior_delta.get("deterministic_snapshot") or {}
    changed = bool(thesis_gap) or current != previous
    invalidated = bool(prior_delta.get("invalidation_triggered"))
    need_data = str((thesis_gap or {}).get("trigger") or "").upper() == "OPERATOR_NEED_DATA"
    transitions = ["REENTRY_TRANSITION"] if item.get("reentry_ready_near") else []
    return plan_research_trigger(
        symbol=sym,
        memberships=[str(item.get("tier") or "")],
        due=True,
        changed=changed,
        stale=float(item.get("age_days") or 0) >= 14,
        current_market=current,
        previous_market=previous,
        events=events,
        state_transitions=transitions,
        operator_need_data=need_data,
        thesis_review_due=bool(thesis_gap),
        invalidation_triggered=invalidated,
        now=now,
        ledger_path=ROOT / "data/cio/research_trigger_ledger.jsonl",
        persist=apply,
    )


# ── scoring ──────────────────────────────────────────────────────────────────
def priority(sym, info, age_days, sla_days, catalyst) -> float:
    overdue = (age_days / sla_days) if sla_days else 0.0
    rank = info.get("rank")
    rank_score = (1.0 - min(rank, 2000) / 2000.0) if rank else 0.0
    base = (100 * TIER_WEIGHT[info["tier"]]
            + 40 * min(overdue, 3.0)
            + 25 * (1.0 if catalyst else 0.0)
            + 15 * rank_score)
    # Outcome bus: tag lift + watchlist/holdings lifecycle + stop-quality health (outcome yield > throughput)
    mult = _symbol_tag_multiplier(sym, scope_tier=info.get("tier"))
    tier = str(info.get("tier") or "")
    if tier == "T0-HOLD":
        mult *= _holdings_lifecycle_multiplier(sym)
    elif tier.startswith("S") or tier in ("S0", "S1", "S2", "S3"):
        mult *= _watchlist_health_multiplier(sym)
    return base * mult


def build_due(uni, lane, force_all=False):
    lr = last_real(lane)
    cats = catalyst_signals()
    now = datetime.now(timezone.utc)
    out = []
    for sym, info in uni.items():
        sla_n, sla_win, lanes = TIER_SLA[info["tier"]]
        last = lr.get(sym)
        age_days = (now - last).total_seconds() / 86400 if last else 9999
        per_refresh_window = sla_win / max(sla_n, 1)   # spacing between required refreshes
        is_t0 = info["tier"].startswith("T0")
        due = force_all or is_t0 or last is None or age_days >= per_refresh_window
        if not due:
            continue
        out.append({
            "symbol": sym, "tier": info["tier"], "rank": info.get("rank"),
            "age_days": round(age_days, 2), "catalyst": cats.get(sym, False),
            "score": priority(sym, info, age_days, per_refresh_window, cats.get(sym, False)),
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# ── dispatch ─────────────────────────────────────────────────────────────────
QUESTION = ("Is {sym} a sound {kind} right now? Flag any NEW catalysts, risks, or thesis changes in the "
            "last few days. Give a clear recommendation and what would change your mind. Advisory only.")


def result_is_budget_throttle(res: dict | None) -> bool:
    """True when the researcher hit COST_CAP — stop the rest of this run.

    Today the scheduler kept walking 426 symbols after the cap bound, each
    writing an [ERROR] row. Those are SKIPPED_BUDGET, and they must not retry
    inside the same process.
    """
    blob = str((res or {}).get("tail") or "")
    if (res or {}).get("budget_throttled"):
        return True
    return "SKIPPED_BUDGET" in blob or "COST_CAP_EXCEEDED" in blob


def _account(event: str, **kwargs) -> None:
    """Best-effort observability; accounting must never alter research policy."""
    try:
        append_call_event(event, **kwargs)
    except Exception as exc:
        print(f"[scheduler] accounting_error={type(exc).__name__}:{exc}")


def dispatch(
    sym, lane, tier, apply, *, thesis_gap: dict | None = None,
    run_id: str | None = None, call_id: str | None = None,
    producer: str = "research_scheduler", family: str = "A",
) -> dict:
    """Route governed cloud research; reject every local or unknown lane."""
    meta = LANES.get(lane, {})
    if not meta or meta.get("dispatch") != "external":
        return {"ok": False, "tail": "POLICY_LOCAL_GENERATIVE_FORBIDDEN"}
    # external (deepseek)
    kind = "position to hold" if tier == "T0-HOLD" else ("proposal to trade" if tier == "T0-PROP" else "candidate")
    commission = thesis_gap or (
        build_thesis_gap_commission(sym, tier=tier)
        if thesis_driven_enabled() and (str(tier).startswith("T0") or tier == "T1-WATCH")
        else None
    )
    if commission and commission.get("specific_question"):
        q = str(commission["specific_question"])
    else:
        q = QUESTION.format(sym=sym, kind=kind)
    prio = "P0" if tier.startswith("T0") else ("P1" if tier == "T1-WATCH" else "P2")
    cmd = [PY, RESEARCHER, "--lane", lane, "--symbol", sym, "--question", q,
           "--priority", prio, "--trigger", "research_scheduler"]
    if run_id:
        cmd.extend(["--run-id", run_id])
    if call_id:
        cmd.extend(["--call-id", call_id])
    cmd.extend(["--producer", producer, "--family", family])
    if apply:
        cmd.append("--apply")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
        blob = (r.stdout or "") + (r.stderr or "")
        throttled = result_is_budget_throttle({"tail": blob})
        ok = (not throttled) and ("status=sent" in blob or "recommendation:" in (r.stdout or ""))
        return {
            "ok": ok,
            "tail": blob[-160:],
            "budget_throttled": throttled,
            "thesis_id": (commission or {}).get("thesis_id"),
            "request_type": (commission or {}).get("request_type") or "scheduled_research",
            "rag_first": rag_first_enabled() if commission else False,
        }
    except subprocess.TimeoutExpired:
        if run_id and call_id:
            _account(
                "ERROR", producer=producer, family=family, run_id=run_id,
                call_id=call_id, symbol=sym, lane=lane, trigger="research_scheduler",
                reason="subprocess_timeout", attempt_no=1, apply=apply,
            )
        return {"ok": False, "tail": "timeout"}
    except Exception as e:
        if run_id and call_id:
            _account(
                "ERROR", producer=producer, family=family, run_id=run_id,
                call_id=call_id, symbol=sym, lane=lane, trigger="research_scheduler",
                reason=f"subprocess_error:{type(e).__name__}", attempt_no=1, apply=apply,
            )
        return {"ok": False, "tail": str(e)[:120]}


def surface_holding_event(sym):
    """Detect a material change in the latest governed DeepSeek opinion for a holding.

    2026-08-13: no longer pushes raw research prose to Telegram. The near-identical
    hourly "📊 {sym} (holding) — ChatGPT research update" spam came from a first-letter
    comparison + `_raw_send_telegram` (which bypassed the dedup router). The research
    now lands in `hermes_external_research` (the desk store) and is surfaced by the
    Advisory Desk `external_research` evidence loader — no per-symbol Telegram. This
    function only fingerprints the change (content hash) so downstream synthesis can
    decide when a *thesis* materially changed.
    """
    rows = _q("""SELECT recommendation, confidence, created_at FROM hermes_external_research
                 WHERE symbol=%s AND lane='deepseek' AND recommendation NOT LIKE '[%%'
                 ORDER BY created_at DESC LIMIT 2""", (sym,))
    if len(rows) < 1:
        return False
    new = dict(rows[0])
    prev = dict(rows[1]) if len(rows) > 1 else {}
    new_hash = _research_fingerprint(new)
    old_hash = _research_fingerprint(prev) if prev else None
    material = (not prev) or (new_hash != old_hash)
    if material:
        # Research change is surfaced via the desk, not Telegram. Log it for the
        # shadow run so a material-change signal is observable without phone noise.
        print(f"[scheduler] material research change: {sym} "
              f"(deepseek conf={new.get('confidence')}) — surfaced via advisory desk (no Telegram)")
    return material


def _research_fingerprint(row: dict) -> str:
    """Content hash of a research row — stable across re-runs that only rephrase prose.

    DOWNSTREAM DIFF only (surface_holding_event). Do not use as the skip-before-call hash.
    """
    import hashlib
    rec = (row.get("recommendation") or "").strip()
    conf = str(row.get("confidence") or "")
    return hashlib.sha256(f"{rec[:240]}|{conf}".encode()).hexdigest()[:16]


def _source_index_mods():
    try:
        from scripts.lib import research_source_index as rsi
        from scripts.lib import research_skip_ledger as rsl
        return rsi, rsl
    except Exception:
        from lib import research_source_index as rsi  # type: ignore
        from lib import research_skip_ledger as rsl  # type: ignore
        return rsi, rsl


def maybe_dispatch_metered(
    sym: str,
    lane: str,
    tier: str,
    apply: bool,
    *,
    catalyst: bool = False,
    thesis_gap: dict | None = None,
    hours_window_fresh: bool = False,
    source_as_of=None,
    extra: dict | None = None,
    now: datetime | None = None,
    dispatch_fn=None,
    index_path: Path | None = None,
    ledger_path: Path | None = None,
    reentry_ready_near: bool = False,
    run_id: str | None = None,
    call_id: str | None = None,
    producer: str = "research_scheduler",
    family: str = "A",
) -> dict:
    """Skip-before-call gate for a metered (DeepSeek) candidate.

    When RESEARCH_SKIP_GATE is off: parity with today — dispatch (or count as spent on
    dry-run) unless the existing backfill hours-window skip applies. No ledger write.

    When on: decide() → SKIP_* does not call the researcher; EXECUTED/TRIGGERED call as
    today then upsert the source index. Every gated candidate writes the skip ledger.
    """
    rsi, rsl = _source_index_mods()
    thesis_version = (thesis_gap or {}).get("thesis_version") if thesis_gap else None
    extra_payload = dict(extra or {})
    if reentry_ready_near:
        extra_payload["reentry_ready_near"] = True
    payload = rsi.source_payload_for_symbol(
        sym,
        tier=tier,
        catalyst=catalyst,
        thesis_version=thesis_version,
        source_as_of=source_as_of,
        extra=extra_payload or None,
    )
    content_hash = rsi.compute_hash(payload)
    source_id = rsi.source_id_for_symbol(sym, lane)
    now_dt = now or datetime.now(timezone.utc)
    call = dispatch_fn or dispatch
    gate = skip_gate_enabled()
    rid, cid = accounting_identity(
        producer=producer, family=family, symbol=sym, lane=lane,
        run_id=run_id, call_id=call_id,
    )

    def _log(code: str, reason: str) -> None:
        if not gate:
            return
        rsl.append_entry(
            source_id=source_id,
            code=code,
            symbol=sym,
            lane=lane,
            content_hash=content_hash,
            reason=reason,
            metered=True,
            path=ledger_path,
            now=now_dt,
        )

    # Existing backfill resume guard (hours-window, no source-hash). When the gate is
    # on this is SKIP_FRESH; when off it is the same silent continue as today.
    if hours_window_fresh and not catalyst:
        code = rsi.SKIP_FRESH
        _log(code, "RESEARCH_BACKFILL_SKIP_FRESH_HOURS")
        _account(
            "DEDUPED", producer=producer, family=family, run_id=rid, call_id=cid,
            symbol=sym, lane=lane, trigger="research_scheduler",
            reason="RESEARCH_BACKFILL_SKIP_FRESH_HOURS", apply=apply,
        )
        return {
            "code": code,
            "dispatched": False,
            "result": None,
            "content_hash": content_hash,
            "source_id": source_id,
        }

    if not gate:
        result = None
        if apply:
            result = call(
                sym, lane, tier, apply, thesis_gap=thesis_gap,
                run_id=rid, call_id=cid, producer=producer, family=family,
            )
        else:
            _account(
                "DRY_RUN", producer=producer, family=family, run_id=rid, call_id=cid,
                symbol=sym, lane=lane, trigger="research_scheduler",
                reason="would_dispatch", apply=False,
            )
        return {
            "code": rsi.RESEARCH_EXECUTED,
            "dispatched": True,
            "result": result,
            "content_hash": content_hash,
            "source_id": source_id,
        }

    code = rsi.decide(
        source_id,
        content_hash,
        triggered=bool(catalyst),
        now=now_dt,
        path=index_path,
    )
    if code in (rsi.SKIP_UNCHANGED, rsi.SKIP_FRESH):
        reason = "hash_match_in_window" if code == rsi.SKIP_UNCHANGED else "ttl_fresh"
        _log(code, reason)
        _account(
            "DEDUPED", producer=producer, family=family, run_id=rid, call_id=cid,
            symbol=sym, lane=lane, trigger="research_scheduler",
            reason=reason, apply=apply, metadata={"skip_code": code},
        )
        return {
            "code": code,
            "dispatched": False,
            "result": None,
            "content_hash": content_hash,
            "source_id": source_id,
        }

    result = None
    if apply:
        result = call(
            sym, lane, tier, apply, thesis_gap=thesis_gap,
            run_id=rid, call_id=cid, producer=producer, family=family,
        )
        ok = bool(result and result.get("ok"))
        if ok:
            rsi.upsert_row(
                source_id,
                content_hash=content_hash,
                last_modified_at=source_as_of or rsi.iso(now_dt),
                last_researched_at=rsi.iso(now_dt),
                extra={
                    "tier": tier,
                    "reentry_ready_near": bool(reentry_ready_near),
                },
                path=index_path,
                now=now_dt,
                tier=tier,
                symbol=sym,
                reentry_ready_near=reentry_ready_near,
            )
        _log(code, "metered_dispatch" if ok else "metered_dispatch_failed")
    else:
        _log(code, "dry_would_dispatch")
        _account(
            "DRY_RUN", producer=producer, family=family, run_id=rid, call_id=cid,
            symbol=sym, lane=lane, trigger="research_scheduler",
            reason="dry_would_dispatch", apply=False, metadata={"dispatch_code": code},
        )
    return {
        "code": code,
        "dispatched": True,
        "result": result,
        "content_hash": content_hash,
        "source_id": source_id,
    }


def run(mode, apply, budget, *, run_id: str | None = None):
    producer = "research_scheduler"
    family = "A"
    accounting_run_id = run_id or new_run_id(producer)
    uni = load_universe()
    counts = {}
    for v in uni.values():
        counts[v["tier"]] = counts.get(v["tier"], 0) + 1
    print(f"[scheduler] universe: {len(uni)} symbols {counts}")

    if mode == "holdings":
        targets = [s for s, v in uni.items() if v["tier"] == "T0-HOLD"]
        ordered = [{"symbol": s, "tier": "T0-HOLD",
                    "reentry_ready_near": bool(uni[s].get("reentry_ready_near"))} for s in targets]
    else:
        lane = "deepseek"
        due = build_due(uni, lane, force_all=(mode == "backfill"))
        if mode == "priority":
            due = [d for d in due if d["tier"].startswith("T0") or d["tier"] == "T1-WATCH" or d["catalyst"]]
        elif mode == "watchlist":
            due = [d for d in due if d["tier"] in ("T1-WATCH",)]
        elif mode == "incubator":
            due = [d for d in due if d["tier"] in ("T2-INCUB",)]
        elif mode == "cold-floor":
            # DEPRECATED 2026-08-22: 14d T3 sweep. T3 DeepSeek is catalyst-only.
            # Cron disabled. Manual --mode cold-floor still slices T3 due; ext_lanes
            # stay empty unless catalyst_signals()[sym] (same T2/T3 gate below).
            due = [d for d in due if d["tier"] == "T3-COLD"][: max(1, len(uni) // COLD_FLOOR_DAYS)]
        for d in due:
            d["reentry_ready_near"] = bool((uni.get(d["symbol"]) or {}).get("reentry_ready_near"))
        ordered = due

    print(f"[scheduler] mode={mode} due={len(ordered)} external_budget={budget} apply={apply} "
          f"thesis_driven={thesis_driven_enabled()} rag_first={rag_first_enabled()} "
          f"skip_gate={skip_gate_enabled()} local_llm={allow_local_research_llm()}")
    if not allow_local_research_llm():
        print("[scheduler] local_llm_disabled")
    cats = catalyst_signals()
    structured_events = catalyst_event_records()
    regime_shift = market_regime_shifted()
    # Preload thesis gaps for high-value symbols (T0/T1) — convert commissioning
    # toward thesis-gap requests when gaps exist. Never invent thesis text.
    gap_by_sym: dict = {}
    if thesis_driven_enabled():
        hv = [
            item["symbol"] for item in ordered
            if str(item.get("tier") or "").startswith("T0") or item.get("tier") == "T1-WATCH"
        ]
        gap_by_sym = load_high_value_thesis_gaps(hv)
        print(f"[scheduler] thesis gaps available for {len(gap_by_sym)}/{len(hv)} high-value symbols")
    # Resume guard: in backfill, skip an external lane for symbols already covered within the skip window
    # (so a relaunch continues where the last run stopped instead of redoing the top of the priority list).
    fresh_ext = {}
    if mode == "backfill":
        skip_h = int(os.getenv("RESEARCH_BACKFILL_SKIP_FRESH_HOURS", "6"))
        for ln in ("deepseek",):
            rows = _q("""SELECT DISTINCT symbol FROM hermes_external_research
                         WHERE lane=%s AND recommendation NOT LIKE '[%%'
                         AND created_at > NOW() - (%s||' hours')::interval""", (ln, skip_h))
            fresh_ext[ln] = {dict(r)["symbol"] for r in rows}
        print(f"[scheduler] backfill resume: skipping externals covered in last {skip_h}h "
              f"(deepseek {len(fresh_ext.get('deepseek', set()))})")
    spent = 0      # external calls only
    done = 0
    ext_rot = 0
    cap_hit = False
    for item in ordered:
        sym, tier = item["symbol"], item["tier"]
        all_lanes = lanes_for(tier)
        thesis_gap = gap_by_sym.get(sym)
        reentry_ready_near = bool(item.get("reentry_ready_near") or (uni.get(sym) or {}).get("reentry_ready_near"))
        item["reentry_ready_near"] = reentry_ready_near
        events = list(structured_events.get(sym) or [])
        if regime_shift and tier in {"T0-HOLD", "T0-PROP", "T1-WATCH"}:
            events.append({"type": "MARKET_REGIME_SHIFT", "severity": "MEDIUM"})
        trigger_plan = scheduler_trigger_plan(
            sym,
            item,
            events=events,
            thesis_gap=thesis_gap,
            apply=apply,
        )
        catalyst = bool(cats.get(sym, False) or trigger_plan.get("triggered"))
        all_call_ids = {
            lane: call_id_for(accounting_run_id, sym, lane) for lane in all_lanes
        }
        for lane in all_lanes:
            _account(
                "SCHEDULED", producer=producer, family=family,
                run_id=accounting_run_id, call_id=all_call_ids[lane], symbol=sym,
                lane=lane, trigger="research_scheduler", apply=apply,
                metadata={"mode": mode, "tier": tier, "catalyst": catalyst},
            )
        # decide lanes for THIS symbol
        local_lanes = [l for l in all_lanes if LANES[l]["dispatch"] == "queue"]
        ext_lanes = [l for l in all_lanes if l in EXTERNAL_LANES and LANES[l]["auto"]]
        # T2/T3 externals only fire on a live catalyst
        if tier in ("T2-INCUB", "T3-COLD") and not catalyst:
            ext_lanes = []
            for lane in [l for l in all_lanes if l in EXTERNAL_LANES]:
                _account(
                    "SKIP_GATED", producer=producer, family=family,
                    run_id=accounting_run_id, call_id=all_call_ids[lane], symbol=sym,
                    lane=lane, trigger="research_scheduler", reason="CATALYST_REQUIRED",
                    apply=apply, metadata={"mode": mode, "tier": tier},
                )
        if cap_hit:
            ext_lanes = []
            for lane in [l for l in all_lanes if l in EXTERNAL_LANES]:
                _account(
                    "SKIP_GATED", producer=producer, family=family,
                    run_id=accounting_run_id, call_id=all_call_ids[lane], symbol=sym,
                    lane=lane, trigger="research_scheduler", reason="UPSTREAM_COST_CAP",
                    apply=apply, metadata={"mode": mode, "tier": tier},
                )
        # T1 rotates ONE external per refresh; T0 gets all (true cross-check).
        # Phase 3: rotation weighted by graded outcome hit-rate (hermes_lane_usefulness) once
        # enough external recs have verdicts; uniform below the gate. No lane ever starves
        # (min weight floor) — a starved lane could never be re-measured.
        if tier == "T1-WATCH" and ext_lanes:
            ext_lanes = [_lane_rotation(ext_lanes)[ext_rot % len(_lane_rotation(ext_lanes))]]; ext_rot += 1
        tag = f"{item.get('score',0):.0f}" if "score" in item else "-"
        gap_tag = f" thesis_id={thesis_gap.get('thesis_id')}" if thesis_gap else ""
        if local_lanes:
            raise RuntimeError("POLICY_LOCAL_GENERATIVE_FORBIDDEN")
        # external lanes: budgeted; skip-gate decides execute vs SKIP_* when enabled.
        for lane in ext_lanes:
            if spent >= budget:
                print(f"[scheduler] external budget {budget} spent at {done} symbols — externals roll to next run (local still queued)")
                ext_lanes = []
                _account(
                    "SKIP_GATED", producer=producer, family=family,
                    run_id=accounting_run_id, call_id=all_call_ids[lane], symbol=sym,
                    lane=lane, trigger="research_scheduler", reason="RUN_BUDGET",
                    apply=apply, metadata={"mode": mode, "tier": tier, "budget": budget},
                )
                break
            hours_fresh = sym in fresh_ext.get(lane, ())
            outcome = maybe_dispatch_metered(
                sym, lane, tier, apply,
                catalyst=catalyst,
                thesis_gap=thesis_gap,
                hours_window_fresh=hours_fresh,
                reentry_ready_near=reentry_ready_near,
                extra=(
                    {"research_trigger": trigger_plan}
                    if trigger_plan.get("trigger_reasons")
                    else None
                ),
                run_id=accounting_run_id,
                call_id=all_call_ids[lane],
                producer=producer,
                family=family,
            )
            if not outcome.get("dispatched"):
                print(f"  skip {sym:6s} {tier:9s} lane={lane:13s} {outcome.get('code')}")
                continue
            print(f"  → {sym:6s} {tier:9s} lane={lane:13s} prio={tag} catalyst={catalyst}{gap_tag}")
            if apply:
                res = outcome.get("result") or {}
                print(f"     {'ok' if res.get('ok') else 'FAIL'}: {str(res.get('tail') or '')[:80]}")
                if result_is_budget_throttle(res):
                    print(f"[scheduler] SKIPPED_BUDGET at {sym} — stopping remaining externals this run")
                    cap_hit = True
                time.sleep(1)
            spent += 1
        if apply and tier == "T0-HOLD":
            surface_holding_event(sym)
        done += 1
    _summary(done, spent)


def _summary(done, spent):
    print(f"[scheduler] done: {done} symbols, {spent} external calls")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="priority",
                    choices=["holdings", "priority", "watchlist", "incubator", "cold-floor", "backfill"])
    ap.add_argument("--apply", action="store_true", help="actually call the lanes (default dry-run plan)")
    ap.add_argument("--budget", type=int, default=EXTERNAL_BUDGET, help="max external calls this run")
    a = ap.parse_args()
    run(a.mode, a.apply, a.budget)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
