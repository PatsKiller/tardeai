#!/usr/bin/env python3
"""market_event_detect.py — lane market-event-detect (LQ-20261107-332, WP1+WP2; spec §4.1–4.2).

Every 30 minutes, weekends included: decide whether a market event is open, keep its state, and re-rank its
re-entry candidates. Advisory only. MBI_BEHAVIOR = 0: this lane never sizes, orders, stops or reaches a broker.
Deterministic, no LLM. Every threshold and weight is in config/market_event_policy.json.

Opens an episode (one open per kind+scope) when:
  * broad_selloff/market: MRE tier >= detector.open.mre_tier_at_least, OR an index (SPY/QQQ) is down
    >= index_drawdown_pct from its highest close of the last index_lookback_sessions sessions;
  * sector_rotation/<group>: an MRE sector group's rs5 <= -sector_rel_move_pct while no broad selloff is open;
  * a configured seed episode (the 11-05/06 broad selloff, baseline 2026-11-04 close) that does not exist yet.
State: OPEN -> STABILIZING (median candidate drawdown made no new low for N sessions) -> RECOVERING (median
candidate recovered >= recovering_pct of its drawdown) -> CLOSED (MRE <= YELLOW for N sessions AND median
recovered >= close pct). single_name_shock is configured but not opened by this slice (named, not hidden).

``--dry-run`` (default) reads the DB read-only and prints what it would write; nothing is written.
``--apply`` upserts episodes and candidates and writes a LaneRunReceipt v2.
The MRE snapshot is read from lib.lane_last_receipt.runtime_dir() (the same state root as the receipt);
``TRADEAI_ENV_FILE`` overrides the .env used for DB credentials (default <repo>/.env).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib import market_event_rank as rank  # noqa: E402
from lib import market_event_store as store  # noqa: E402
from lib import market_event_sector_proxies as sector_proxies  # noqa: E402

LANE_ID = "market-event-detect"
MRE_REL = "data/runtime/market_risk_latest.json"


# ------------------------------------------------------------------------------------------------ pure logic
def tier_at_least(tier: str | None, floor: str, order: list[str]) -> bool:
    return tier in order and order.index(tier) >= order.index(floor)


def mre_fresh(mre: Mapping[str, Any], now: datetime, max_age_h: float) -> bool:
    try:
        as_of = datetime.fromisoformat(str(mre.get("as_of")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return (now - as_of).total_seconds() <= max_age_h * 3600


def mre_groups(mre: Mapping[str, Any]) -> list[dict]:
    return list(((mre.get("sectors") or {}).get("groups")) or [])


def affected_groups(mre: Mapping[str, Any], cfg: Mapping[str, Any]) -> list[str]:
    out = []
    for g in mre_groups(mre):
        if g.get("kind") not in cfg.get("kinds", ["sector", "theme"]):
            continue
        rel = g.get(cfg.get("rel_field", "rs5"))
        if g.get("state") in cfg.get("states", []) or (rel is not None and float(rel) <= -float(cfg["rel_move_pct"])):
            out.append(str(g.get("key")))
    return sorted(out)


def index_triggers(closes: Mapping[str, Mapping[str, float]], last_session: str, pct: float) -> list[dict]:
    """closes = {symbol: {session_iso: close}}; trigger when the last close is down >= pct from the window high."""
    out = []
    for sym, series in sorted(closes.items()):
        if last_session not in series or len(series) < 2:
            continue
        peak_day = max((d for d in series if d < last_session), key=lambda d: (series[d], d), default=None)
        if peak_day is None:
            continue
        dd = (series[last_session] / series[peak_day] - 1.0) * 100.0
        if dd <= -pct:
            out.append({"symbol": sym, "peak_session": peak_day, "drawdown_pct": round(dd, 3)})
    return out


def evaluate_triggers(mre: Mapping[str, Any], index_closes: Mapping[str, Mapping[str, float]], last_session: str,
                      policy: Mapping[str, Any], now: datetime,
                      bar_moves: Mapping[str, Any] | None = None) -> dict:
    det = policy["detector"]
    op = det["open"]
    fresh = mre_fresh(mre, now, float(det.get("mre_max_age_hours", 6)))
    tier = mre.get("tier") if fresh else None
    sector_hits = []
    for g in mre_groups(mre) if fresh else []:
        if g.get("kind") not in op.get("sector_group_kinds", ["sector", "theme"]):
            continue
        rel = g.get(op.get("sector_rel_field", "rs5"))
        if rel is not None and float(rel) <= -float(op["sector_rel_move_pct"]):
            sector_hits.append({"group": g.get("key"), op.get("sector_rel_field", "rs5"): rel})
    return {
        "mre": {"tier": mre.get("tier"), "score": mre.get("score"), "as_of": mre.get("as_of"), "fresh": fresh,
                "hit": bool(tier and tier_at_least(tier, op["mre_tier_at_least"], det["tier_order"]))},
        "index": index_triggers(index_closes, last_session, float(op["index_drawdown_pct"])),
        "sectors": sector_proxies.merge_sector_hits(
            sector_hits,
            sector_proxies.sector_hits(bar_moves, rel_field=op.get("sector_rel_field", "rs5"),
                                       rel_move_pct=float(op["sector_rel_move_pct"]),
                                       kinds=op.get("sector_group_kinds", ["sector", "theme"])) if bar_moves else []),
        "affected_groups": affected_groups(mre, det["affected_groups"]) if fresh else [],
        "last_session": last_session,
    }


def plan_episodes(existing: list[dict], triggers: Mapping[str, Any], policy: Mapping[str, Any],
                  now: datetime) -> list[dict]:
    """Existing open episodes (affected groups refreshed) plus any episode the triggers or seeds open."""
    det = policy["detector"]
    pv = policy["policy_version"]
    by_id = {e["episode_id"]: dict(e) for e in existing}
    open_keys = {(e["kind"], e["scope"]) for e in existing if e.get("state") != "CLOSED"}
    eps = [dict(e) for e in existing if e.get("state") != "CLOSED"]

    def new(kind: str, scope: str, baseline: str, opened_at: str, trig: dict, affected: list[str]) -> None:
        eid = store.episode_id(kind, scope, baseline)
        if eid in by_id or (kind, scope) in open_keys:
            return
        ep = {"episode_id": eid, "kind": kind, "scope": scope, "state": "OPEN", "opened_at": opened_at,
              "closed_at": None, "trigger": trig, "baseline_date": baseline, "affected_sectors": affected,
              "policy_version": pv, "last_eval": {}, "_new": True}
        eps.append(ep)
        by_id[eid] = ep
        open_keys.add((kind, scope))

    for seed in det.get("seed_episodes", []):
        new(seed["kind"], seed["scope"], seed["baseline_date"], seed["opened_at"],
            {"seed": seed.get("reason"), "at_open": dict(triggers)}, list(triggers.get("affected_groups") or []))

    if triggers["mre"]["hit"] or triggers["index"]:
        last = date.fromisoformat(triggers["last_session"])
        peaks = [t["peak_session"] for t in triggers["index"]]
        baseline = min(peaks) if peaks else rank.prev_trading_day(last).isoformat()
        new("broad_selloff", "market", baseline, now.isoformat(), dict(triggers),
            list(triggers.get("affected_groups") or []))

    broad_open = ("broad_selloff", "market") in open_keys
    if not broad_open:
        last = date.fromisoformat(triggers["last_session"])
        for hit in triggers["sectors"]:
            new("sector_rotation", str(hit["group"]), rank.prev_trading_day(last).isoformat(), now.isoformat(),
                {"sector": hit, "at_open": dict(triggers)}, [str(hit["group"])])

    for ep in eps:
        if ep["kind"] == "broad_selloff" and not ep.get("_new"):
            ep["affected_sectors"] = sorted(set(ep.get("affected_sectors") or []) |
                                            set(triggers.get("affected_groups") or []))
    return eps


def advance_state(ep: dict, cands: list[dict], triggers: Mapping[str, Any], policy: Mapping[str, Any],
                  now: datetime) -> dict:
    """Update last_eval (troughs, calm sessions, median drawdown by session) and the episode state."""
    det = policy["detector"]
    ev = dict(ep.get("last_eval") or {})
    session = triggers["last_session"]
    troughs = dict(ev.get("troughs") or {})
    recovered = []
    for c in cands:
        s, b, last = c["symbol"], c["baseline_price"], c["last_price"]
        t = min(float(troughs.get(s, last)), last)
        troughs[s] = t
        if b and b > t:
            recovered.append((last - t) / (b - t) * 100.0)
    med_rec = round(statistics.median(recovered), 3) if recovered else 0.0
    by_session = dict(ev.get("median_drawdown_by_session") or {})
    if cands:
        by_session[session] = round(statistics.median(c["drawdown_pct"] for c in cands), 3)
    calm = list(ev.get("calm_sessions") or [])
    tier = triggers["mre"]["tier"] if triggers["mre"]["fresh"] else None
    if tier and not tier_at_least(tier, det["tier_order"][det["tier_order"].index(det["close"]["mre_tier_at_most"]) + 1],
                                  det["tier_order"]):
        if session not in calm:
            calm.append(session)
    elif tier:
        calm = []
    sessions = sorted(by_session)
    low_session = min(sessions, key=lambda d: (by_session[d], d)) if sessions else session
    since_low = sum(1 for d in sessions if d > low_session)
    st = det["states"]
    state = "OPEN"
    if since_low >= int(st["stabilizing_sessions_without_new_low"]):
        state = "STABILIZING"
    if med_rec >= float(st["recovering_pct_of_drawdown"]):
        state = "RECOVERING"
    cl = det["close"]
    closed_at = ep.get("closed_at")
    if len(calm) >= int(cl["sessions"]) and med_rec >= float(cl["median_candidate_recovered_pct_of_drawdown"]):
        state, closed_at = "CLOSED", now.isoformat()
    ev.update({"evaluated_at": now.isoformat(), "session": session, "troughs": troughs,
               "median_recovered_pct": med_rec, "median_drawdown_by_session": dict(sorted(by_session.items())[-30:]),
               "calm_sessions": calm[-10:], "sessions_since_low": since_low, "mre_tier": triggers["mre"]["tier"],
               "candidates": len(cands)})
    return {**ep, "state": state, "closed_at": closed_at, "last_eval": ev}


# ------------------------------------------------------------------------------------------------ IO
def load_mre(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def index_closes(conn, policy: Mapping[str, Any], last_session: date) -> dict[str, dict[str, float]]:
    det = policy["detector"]
    days = [last_session]
    while len(days) < int(det["open"]["index_lookback_sessions"]) + 1:
        days.append(rank.prev_trading_day(days[-1]))
    out: dict[str, dict[str, float]] = {}
    for d in days:
        for sym, px in rank.session_closes(conn, det["index_symbols"], d, policy).items():
            out.setdefault(sym, {})[d.isoformat()] = px
    return out


def connect(read_only: bool):
    from lib import ops_lanes
    env_file = Path(os.environ.get("TRADEAI_ENV_FILE") or ROOT / ".env")
    conn = ops_lanes.pg_connect(ops_lanes.db_params(env_file=env_file), read_only=read_only)
    if read_only:
        from lib import lane_last_receipt
        lane_last_receipt.enforce_readonly(conn)
    return conn


def run(args: argparse.Namespace) -> int:
    from lib import lane_last_receipt as lr
    started = lr.now_iso()
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    policy = rank.load_policy(args.policy)
    mre = load_mre(Path(args.mre) if args.mre else lr.runtime_dir() / Path(MRE_REL).name)
    conn = connect(read_only=not args.apply)
    try:
        last_session = rank.last_completed_session(now, policy["data"].get("close_time_et", "16:00"))
        triggers = evaluate_triggers(mre, index_closes(conn, policy, last_session), last_session.isoformat(),
                                     policy, now, bar_moves=sector_proxies.read_moves(conn, policy, now=now))
        have_tables = store.tables_exist(conn)
        existing = store.list_episodes(conn) if have_tables else []
        episodes = plan_episodes(existing, triggers, policy, now)
        results = []
        for ep in episodes:
            built = rank.build_candidates(conn, ep, mre, policy, now) if policy["detector"].get("rank_on_detect") else \
                {"candidates": [], "excluded": {}, "inputs": {}}
            cands = built["candidates"][: int(policy["ranking"].get("max_candidates", 25)) * 4]
            ep2 = advance_state(ep, cands, triggers, policy, now)
            results.append((ep2, cands, built))
        summary = {
            "tables_exist": have_tables, "triggers": triggers,
            "episodes": [{"episode_id": e["episode_id"], "new": bool(e.get("_new")), "state": e["state"],
                          "affected_sectors": e["affected_sectors"], "baseline_date": e["baseline_date"],
                          "inputs": b["inputs"], "excluded": b["excluded"].get("counts"),
                          "candidates": len(c), "median_recovered_pct": e["last_eval"].get("median_recovered_pct"),
                          "top": [{k: x[k] for k in ("rank", "symbol", "source", "drawdown_pct", "quality_score",
                                                      "discount_score", "combined_score", "fell_for_reason")}
                                  | {"group": x["reason_evidence"]["group"],
                                     "unexplained_excess_drop": x["reason_evidence"].get("unexplained_excess_drop"),
                                     "coverage": x["reason_evidence"]["quality_coverage"]}
                                  for x in c[: args.top]]}
                         for e, c, b in results],
        }
        if args.evidence_out:
            Path(args.evidence_out).write_text(json.dumps(
                {"summary": summary, "candidates": {e["episode_id"]: c for e, c, _ in results}}, indent=1, default=str))
        if not args.apply:
            lr.dry_run_report(LANE_ID, summary, would_write=[
                f"market_event_episodes:{e['episode_id']} ({e['state']})" for e, _, _ in results] + [
                f"market_event_candidates:{e['episode_id']} x{len(c)}" for e, c, _ in results])
            return 0
        if not have_tables:
            lr.write_lane_receipt(LANE_ID, ok=False, exit_code=2, started_at=started, script="scripts/market_event_detect.py",
                                  summary={"error": "tables missing: apply migrations/2026_11_07_market_event.sql"},
                                  error="tables missing")
            print("market_event tables missing; apply migrations/2026_11_07_market_event.sql", file=sys.stderr)
            return 2
        written = 0
        conn.autocommit = False
        for ep, cands, _ in results:
            store.upsert_episode(conn, {k: v for k, v in ep.items() if not k.startswith("_")})
            written += store.upsert_candidates(conn, ep["episode_id"], cands)
            store.unrank_missing(conn, ep["episode_id"], [c["symbol"] for c in cands])
        conn.commit()
        lr.write_lane_receipt(
            LANE_ID, ok=True, exit_code=0, started_at=started, script="scripts/market_event_detect.py",
            summary={"episodes": len(results), "candidates_written": written,
                     "open": [e["episode_id"] for e, _, _ in results if e["state"] != "CLOSED"]},
            produced_count=written, attempted_count=len(results),
            output_evidence=[{"table": "market_event_candidates", "episode_id": e["episode_id"], "rows": len(c)}
                             for e, c, _ in results],
            empty_reason=None if written else "no_open_episode")
        print(json.dumps({"ok": True, "episodes": len(results), "candidates_written": written}))
        return 0
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="read-only; print what would be written (default)")
    mode.add_argument("--apply", action="store_true", help="write episodes, candidates and the lane receipt")
    ap.add_argument("--policy", help="policy file (default config/market_event_policy.json)")
    ap.add_argument("--mre", help="MarketRiskSnapshot file (default <state root>/data/runtime/market_risk_latest.json)")
    ap.add_argument("--now", help="ISO time to evaluate at (replay)")
    ap.add_argument("--top", type=int, default=25, help="candidates per episode in the printed summary")
    ap.add_argument("--evidence-out", help="also write the full summary + candidates JSON here")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
