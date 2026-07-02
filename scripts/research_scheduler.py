#!/usr/bin/env python3
"""research_scheduler.py — tiered, SLA-driven, priority-ordered external/LLM research dispatcher.

Implements docs/RESEARCH_PRIORITIZATION.md:
  • Assigns every tracked symbol the highest tier it qualifies for (holdings > proposals > watchlist >
    incubator > cold universe).
  • Enforces a per-tier refresh SLA ("at least X times in Y days") per external lane.
  • Orders the due set by an exposure/overdue/catalyst/rank/divergence priority score.
  • Dispatches within a per-run external-lane budget (so the free OAuth lanes don't exhaust).
  • Holdings (T0) are refreshed several times/day and material changes are surfaced to card + Telegram.

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
PY = str(ROOT / ".venv" / "bin" / "python")
RESEARCHER = str(ROOT / "scripts" / "hermes_external_researcher.py")
HOLDINGS_FILE = ROOT / "data" / "portfolios" / "state" / "holdings.json"

# ── tunables (env-overridable) ───────────────────────────────────────────────
EXTERNAL_BUDGET = int(os.getenv("RESEARCH_EXTERNAL_BUDGET_PER_RUN", "40"))
TOP_RANK_N      = int(os.getenv("RESEARCH_TOP_RANK_N", str(WATCHLIST_TOP_N)))
COLD_FLOOR_DAYS = int(os.getenv("RESEARCH_COLD_FLOOR_DAYS", "14"))
CALL_TIMEOUT    = int(os.getenv("RESEARCH_CALL_TIMEOUT", "150"))

# ── Hermes lane registry (the whole 24/7 fleet, cheapest→scarcest) ────────────
# Symbol-level research producers. local-gemma is the broad workhorse (enqueued, drained by the
# always-on watchlist_agent_jobs workers); internal-deep is the overnight gemma3:27b window; grok/
# chatgpt are the free but rate-limited external OAuth skeptics; claude is METERED → arbitration only,
# never auto-dispatched here. Topic/source/news lanes run on their own cadence (see the doc) and are
# governed by the same tier priorities but not symbol-fanned-out by this scheduler.
LANES = {
    "local-gemma":   {"cost": "free-fast",    "dispatch": "queue",    "auto": True},
    "internal-deep": {"cost": "free-slow",    "dispatch": "queue",    "auto": True},
    "grok":          {"cost": "free-limited", "dispatch": "external", "auto": True},
    "chatgpt":       {"cost": "free-limited", "dispatch": "external", "auto": True},
    "claude":        {"cost": "metered",      "dispatch": "external", "auto": False},  # arbitration only
}

# tier → (sla_refreshes, sla_window_days, lanes[]).  Local always covers; externals are tier-gated.
TIER_SLA = {
    "T0-HOLD":  (3, 1,  ["local-gemma", "internal-deep", "grok", "chatgpt"]),
    "T0-PROP":  (2, 1,  ["local-gemma", "grok", "chatgpt"]),
    "T1-WATCH": (4, 7,  ["local-gemma", "grok", "chatgpt"]),   # externals rotated (one per refresh)
    "T2-INCUB": (1, 7,  ["local-gemma", "chatgpt"]),           # external only on catalyst
    "T3-COLD":  (1, 14, ["local-gemma"]),                      # external only on catalyst
}
TIER_WEIGHT = {"T0-HOLD": 1.0, "T0-PROP": 0.9, "T1-WATCH": 0.6, "T2-INCUB": 0.3, "T3-COLD": 0.1}
EXTERNAL_LANES = {"grok", "chatgpt", "claude"}


def _q(sql, params=()):
    from db_adapter import _execute
    return _execute(sql, params, fetch="all") or []


def _is_symbol(s: str) -> bool:
    s = (s or "").upper().strip()
    return bool(s) and s.isalpha() and 1 <= len(s) <= 5  # drop CUSIPs / cash rows


# ── universe assembly ────────────────────────────────────────────────────────
def load_universe() -> dict:
    """symbol -> {'tier': str, 'rank': int|None}. Highest tier wins."""
    uni: dict[str, dict] = {}

    def add(sym, tier, rank=None):
        sym = sym.upper().strip()
        if not _is_symbol(sym):
            return
        cur = uni.get(sym)
        if cur is None or _tier_order(tier) < _tier_order(cur["tier"]):
            uni[sym] = {"tier": tier, "rank": rank}
        elif rank is not None and uni[sym].get("rank") is None:
            uni[sym]["rank"] = rank

    # T0-HOLD
    try:
        d = json.loads(HOLDINGS_FILE.read_text())
        items = d if isinstance(d, list) else (d.get("holdings") or d.get("positions") or [])
        for x in items:
            if isinstance(x, dict) and x.get("symbol"):
                add(x["symbol"], "T0-HOLD")
    except Exception:
        pass
    # T0-PROP
    for r in _q("""SELECT DISTINCT symbol FROM paper_trade_proposals
                   WHERE status IN ('PENDING','APPROVED','APPROVED_FOR_PAPER_TEST')"""):
        add(dict(r)["symbol"], "T0-PROP")
    # T1-WATCH: top-N Hermes rank + operator watch directives
    for r in _q("""SELECT DISTINCT ON (symbol) symbol, rank FROM hermes_score_history
                   ORDER BY symbol, scored_at DESC"""):
        d = dict(r)
        if d.get("rank") is not None and d["rank"] <= TOP_RANK_N:
            add(d["symbol"], "T1-WATCH", d["rank"])
    for r in _q("""SELECT spec->>'symbol' AS s FROM watch_directives
                   WHERE kind='ticker' AND status='active' AND spec ? 'symbol'"""):
        if dict(r).get("s"):
            add(dict(r)["s"], "T1-WATCH")
    # T2-INCUB: recently-proposed names + active incubator members (incl. claude_challenger cohort)
    for r in _q("""SELECT DISTINCT symbol FROM paper_trade_proposals
                   WHERE created_at > NOW() - INTERVAL '21 days'"""):
        add(dict(r)["symbol"], "T2-INCUB")
    for r in _q("""SELECT DISTINCT symbol FROM incubator_universe
                   WHERE status='active' AND symbol IS NOT NULL"""):
        add(dict(r)["symbol"], "T2-INCUB")
    # T3-COLD: the rest of the profiled universe
    for r in _q("SELECT DISTINCT symbol FROM symbol_profiles"):
        add(dict(r)["symbol"], "T3-COLD")

    # attach latest rank for everyone (for scoring) if missing
    ranks = {dict(r)["symbol"]: dict(r)["rank"] for r in _q(
        "SELECT DISTINCT ON (symbol) symbol, rank FROM hermes_score_history ORDER BY symbol, scored_at DESC")}
    for s in uni:
        if uni[s].get("rank") is None:
            uni[s]["rank"] = ranks.get(s)

    # Scope-governor binding (Phase 1 §1.3): one governor owns research scope too. A symbol the
    # governor archived (scope_tier S3) never holds a T1/T2 research slot — it drops to T3-COLD
    # (metadata-only under the budget guard) until an event or the governor reactivates it.
    # T0 (capital exposed) is never downgraded.
    s3 = {dict(r)["symbol"].upper() for r in _q(
        """SELECT DISTINCT UPPER(symbol) AS symbol FROM watchlist_items
           WHERE scope_tier='S3' AND status IN ('active','researched')""")}
    for s, info in uni.items():
        if s in s3 and info["tier"] in ("T1-WATCH", "T2-INCUB"):
            info["tier"] = "T3-COLD"
    return uni


def _tier_order(t: str) -> int:
    return ["T0-HOLD", "T0-PROP", "T1-WATCH", "T2-INCUB", "T3-COLD"].index(t)


_LANE_ROT_CACHE: dict = {}


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


# ── scoring ──────────────────────────────────────────────────────────────────
def priority(sym, info, age_days, sla_days, catalyst) -> float:
    overdue = (age_days / sla_days) if sla_days else 0.0
    rank = info.get("rank")
    rank_score = (1.0 - min(rank, 2000) / 2000.0) if rank else 0.0
    return (100 * TIER_WEIGHT[info["tier"]]
            + 40 * min(overdue, 3.0)
            + 25 * (1.0 if catalyst else 0.0)
            + 15 * rank_score)


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


def _enqueue_local(sym, tier, deep=False) -> dict:
    """Queue a local-gemma research job; the always-on watchlist_agent_jobs workers drain it.
    Idempotent-ish: skips if an unprocessed job for this symbol/agent already queued."""
    agent = "full_chain" if deep else "maria"
    prio = 1 if tier.startswith("T0") else (3 if tier == "T1-WATCH" else 5)
    try:
        from db_adapter import _execute
        dup = _execute("""SELECT 1 FROM watchlist_agent_jobs WHERE symbol=%s AND requested_agent=%s
                          AND status IN ('queued','running') LIMIT 1""", (sym, agent), fetch="one")
        if dup:
            return {"ok": True, "tail": "already queued"}
        # id is a TEXT primary key (no sequence) — generate a stable, unique-per-minute string
        job_id = f"sched-{sym}-{agent}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        _execute("""INSERT INTO watchlist_agent_jobs
                    (id, symbol, requested_agent, request_type, note, priority, status, submitted_from, payload, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,'queued','research_scheduler','{}',NOW())
                    ON CONFLICT (id) DO NOTHING""",
                 (job_id, sym, agent, "scheduled_research",
                  f"{tier} scheduled research ({'deep' if deep else 'standard'})", prio), fetch=None)
        return {"ok": True, "tail": f"enqueued {agent} p{prio}"}
    except Exception as e:
        return {"ok": False, "tail": str(e)[:100]}


def dispatch(sym, lane, tier, apply) -> dict:
    """Route by lane kind: queue lanes enqueue local work; external lanes call the researcher."""
    meta = LANES.get(lane, {})
    if meta.get("dispatch") == "queue":
        if not apply:
            return {"ok": True, "tail": f"would enqueue {lane}"}
        return _enqueue_local(sym, tier, deep=(lane == "internal-deep"))
    # external (grok/chatgpt)
    kind = "position to hold" if tier == "T0-HOLD" else ("proposal to trade" if tier == "T0-PROP" else "candidate")
    q = QUESTION.format(sym=sym, kind=kind)
    prio = "P0" if tier.startswith("T0") else ("P1" if tier == "T1-WATCH" else "P2")
    cmd = [PY, RESEARCHER, "--lane", lane, "--symbol", sym, "--question", q,
           "--priority", prio, "--trigger", "research_scheduler"]
    if apply:
        cmd.append("--apply")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT)
        ok = "status=sent" in (r.stdout + r.stderr) or "recommendation:" in r.stdout
        return {"ok": ok, "tail": (r.stdout or r.stderr or "")[-160:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "tail": "timeout"}
    except Exception as e:
        return {"ok": False, "tail": str(e)[:120]}


def surface_holding_event(sym):
    """Diff latest two chatgpt opinions for a holding; alert on material change."""
    rows = _q("""SELECT recommendation, confidence, created_at FROM hermes_external_research
                 WHERE symbol=%s AND lane='chatgpt' AND recommendation NOT LIKE '[%%'
                 ORDER BY created_at DESC LIMIT 2""", (sym,))
    if len(rows) < 1:
        return
    new = dict(rows[0])
    prev = dict(rows[1]) if len(rows) > 1 else {}
    new_rec = (new.get("recommendation") or "")[:1].upper()
    old_rec = (prev.get("recommendation") or "")[:1].upper()
    conf_delta = abs(float(new.get("confidence") or 0) - float(prev.get("confidence") or 0))
    material = (not prev) or (new_rec != old_rec) or conf_delta >= 0.2
    if not material:
        return
    msg = (f"\U0001f4ca {sym} (holding) — ChatGPT research update\n"
           f"{(new.get('recommendation') or '')[:240]}\n(conf {new.get('confidence')})")
    try:
        from telegram_alert import _raw_send_telegram
        cid = (os.environ.get("TRADEAI_PROPOSAL_ALERT_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "").split(",")[0].strip()
        if cid:
            _raw_send_telegram(msg, chat_ids=[cid])
    except Exception:
        pass


def run(mode, apply, budget):
    uni = load_universe()
    counts = {}
    for v in uni.values():
        counts[v["tier"]] = counts.get(v["tier"], 0) + 1
    print(f"[scheduler] universe: {len(uni)} symbols {counts}")

    if mode == "holdings":
        targets = [s for s, v in uni.items() if v["tier"] == "T0-HOLD"]
        lanes_for = lambda t: TIER_SLA[t][2]   # full T0 fleet: local-gemma + internal-deep + grok + chatgpt
        ordered = [{"symbol": s, "tier": "T0-HOLD"} for s in targets]
    else:
        lane = "chatgpt"  # primary ordering lane; gemma assumed broad/elsewhere
        due = build_due(uni, lane, force_all=(mode == "backfill"))
        if mode == "priority":
            due = [d for d in due if d["tier"].startswith("T0") or d["tier"] == "T1-WATCH" or d["catalyst"]]
        elif mode == "watchlist":
            due = [d for d in due if d["tier"] in ("T1-WATCH",)]
        elif mode == "incubator":
            due = [d for d in due if d["tier"] in ("T2-INCUB",)]
        elif mode == "cold-floor":
            due = [d for d in due if d["tier"] == "T3-COLD"][: max(1, len(uni) // COLD_FLOOR_DAYS)]
        ordered = due
        lanes_for = lambda t: TIER_SLA[t][2]

    print(f"[scheduler] mode={mode} due={len(ordered)} external_budget={budget} apply={apply}")
    cats = catalyst_signals()
    # Resume guard: in backfill, skip an external lane for symbols already covered within the skip window
    # (so a relaunch continues where the last run stopped instead of redoing the top of the priority list).
    fresh_ext = {}
    if mode == "backfill":
        skip_h = int(os.getenv("RESEARCH_BACKFILL_SKIP_FRESH_HOURS", "6"))
        for ln in ("chatgpt", "grok"):
            rows = _q("""SELECT DISTINCT symbol FROM hermes_external_research
                         WHERE lane=%s AND recommendation NOT LIKE '[%%'
                         AND created_at > NOW() - (%s||' hours')::interval""", (ln, skip_h))
            fresh_ext[ln] = {dict(r)["symbol"] for r in rows}
        print(f"[scheduler] backfill resume: skipping externals covered in last {skip_h}h "
              f"(chatgpt {len(fresh_ext.get('chatgpt', set()))}, grok {len(fresh_ext.get('grok', set()))})")
    spent = 0      # external calls only
    done = 0
    ext_rot = 0
    for item in ordered:
        sym, tier = item["symbol"], item["tier"]
        all_lanes = lanes_for(tier)
        catalyst = cats.get(sym, False)
        # decide lanes for THIS symbol
        local_lanes = [l for l in all_lanes if LANES[l]["dispatch"] == "queue"]
        ext_lanes = [l for l in all_lanes if l in EXTERNAL_LANES and LANES[l]["auto"]]
        # T2/T3 externals only fire on a live catalyst
        if tier in ("T2-INCUB", "T3-COLD") and not catalyst:
            ext_lanes = []
        # T1 rotates ONE external per refresh; T0 gets all (true cross-check).
        # Phase 3: rotation weighted by graded outcome hit-rate (hermes_lane_usefulness) once
        # enough external recs have verdicts; uniform below the gate. No lane ever starves
        # (min weight floor) — a starved lane could never be re-measured.
        if tier == "T1-WATCH" and ext_lanes:
            ext_lanes = [_lane_rotation(ext_lanes)[ext_rot % len(_lane_rotation(ext_lanes))]]; ext_rot += 1
        tag = f"{item.get('score',0):.0f}" if "score" in item else "-"
        # local lanes: always (cheap, queued)
        for lane in local_lanes:
            print(f"  → {sym:6s} {tier:9s} lane={lane:13s} prio={tag}")
            if apply:
                res = dispatch(sym, lane, tier, apply)
                print(f"     {'ok' if res['ok'] else 'FAIL'}: {res['tail'][:80]}")
        # external lanes: budgeted (skip ones freshly covered this backfill — resume guard)
        for lane in ext_lanes:
            if sym in fresh_ext.get(lane, ()):
                continue
            if spent >= budget:
                print(f"[scheduler] external budget {budget} spent at {done} symbols — externals roll to next run (local still queued)")
                ext_lanes = []
                break
            print(f"  → {sym:6s} {tier:9s} lane={lane:13s} prio={tag} catalyst={catalyst}")
            if apply:
                res = dispatch(sym, lane, tier, apply)
                print(f"     {'ok' if res['ok'] else 'FAIL'}: {res['tail'][:80]}")
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
