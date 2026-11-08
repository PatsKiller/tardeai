#!/usr/bin/env python3
"""Lane ``market-event-outcomes`` (WP6, LQ-20261107-339): daily after the close, score every candidate of every
market event episode at +5/+20/+60 sessions from baseline and from each READY tranche.

Advisory telemetry. Reads market_event_episodes, market_event_candidates and Finviz closes (ticker_prices,
source='finviz'); writes only market_event_outcomes. No broker, no orders, no LLM.

  --dry-run   (default) read-only: prints what would be written; writes no row and no receipt
  --apply     upsert market_event_outcomes and write the lane receipt
  --scorecard EPISODE_ID   print the per-episode scorecard (read-only) and exit
  --friday-check           print the spec-4.7 Friday-close -> Mon/Tue check for the newest episode (read-only)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import market_event_outcomes as MO  # noqa: E402

LANE = "market-event-outcomes"
LOOKBACK_DAYS = 150


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        env = Path(os.environ.get("TRADEAI_ENV_FILE", ""))
    if env and env.is_file():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def _connect(read_only: bool):
    import psycopg2  # noqa: PLC0415

    _load_env()
    opts = "-c default_transaction_read_only=on" if read_only else None
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], dbname=os.environ["DB_NAME"],
                            user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                            application_name=LANE, connect_timeout=10, options=opts)


def _table_exists(cur, name: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{name}",))
    return bool(cur.fetchone()[0])


def load_world(cur, today: date) -> dict:
    cur.execute("SELECT episode_id, baseline_date, state, opened_at FROM market_event_episodes "
                "WHERE opened_at >= %s ORDER BY opened_at", (today - timedelta(days=LOOKBACK_DAYS),))
    episodes = [dict(zip(("episode_id", "baseline_date", "state", "opened_at"), r)) for r in cur.fetchall()]
    cands: dict[str, list] = {e["episode_id"]: [] for e in episodes}
    if episodes:
        cur.execute("SELECT episode_id, symbol, baseline_price, last_price, state, plan FROM market_event_candidates "
                    "WHERE episode_id = ANY(%s)", ([e["episode_id"] for e in episodes],))
        for eid, sym, bp, lp, st, plan in cur.fetchall():
            cands[eid].append({"symbol": sym, "baseline_price": float(bp) if bp is not None else None,
                               "last_price": float(lp) if lp is not None else None,
                               "state": st, "plan": plan if isinstance(plan, dict) else None})
    syms = sorted({c["symbol"] for cs in cands.values() for c in cs})
    closes: dict[str, dict[date, float]] = {}
    if syms:
        floor = min((e["baseline_date"] for e in episodes if e["baseline_date"]), default=today) - timedelta(days=10)
        cur.execute("SELECT symbol, price_date, close_price FROM ticker_prices "
                    "WHERE source='finviz' AND symbol = ANY(%s) AND price_date >= %s", (syms, floor))
        for s, d, c in cur.fetchall():
            if c is not None:
                closes.setdefault(s, {})[d] = float(c)
    return {"episodes": episodes, "candidates": cands, "closes": closes}


def sessions_for(today: date) -> list[date]:
    start, end = today - timedelta(days=LOOKBACK_DAYS + 30), today + timedelta(days=120)
    try:
        return MO.xnys_sessions(start, end)
    except ImportError:
        return MO.weekday_calendar(start, end)


def score_world(world: dict, sessions: list[date], now: datetime) -> tuple[list[dict], dict[str, int]]:
    today = now.astimezone(MO.ET).date()
    out, skipped = [], {}
    for ep in world["episodes"]:
        rows, sk = MO.build_signals(ep, world["candidates"][ep["episode_id"]], world["closes"], sessions, now)
        out += MO.score_rows(rows, world["closes"], sessions, today)
        for k, v in sk.items():
            skipped[k] = skipped.get(k, 0) + v
    return out, skipped


UPSERT = """
INSERT INTO market_event_outcomes
  (episode_id, symbol, signal, signal_at, anchor_session, price, price_source, signal_basis, ret_5, ret_20, ret_60, scored_at)
VALUES (%(episode_id)s, %(symbol)s, %(signal)s, %(signal_at)s, %(anchor_session)s, %(price)s, %(price_source)s,
        %(signal_basis)s, %(ret_5)s, %(ret_20)s, %(ret_60)s, now())
ON CONFLICT (episode_id, symbol, signal) DO UPDATE SET
  ret_5 = COALESCE(EXCLUDED.ret_5, market_event_outcomes.ret_5),
  ret_20 = COALESCE(EXCLUDED.ret_20, market_event_outcomes.ret_20),
  ret_60 = COALESCE(EXCLUDED.ret_60, market_event_outcomes.ret_60),
  scored_at = now()
"""  # entry fields (signal_at, price, anchor) are never updated: a re-score cannot move the entry


def _now() -> datetime:
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", default=True)
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--scorecard", metavar="EPISODE_ID")
    ap.add_argument("--friday-check", action="store_true")
    a = ap.parse_args(argv)
    apply = bool(a.apply)
    started = _now()
    now = started
    read_only = not apply
    conn = _connect(read_only)
    try:
        cur = conn.cursor()
        today = now.astimezone(MO.ET).date()
        if not (_table_exists(cur, "market_event_episodes") and _table_exists(cur, "market_event_candidates")):
            print(json.dumps({"lane": LANE, "status": "inputs_missing", "detail": "episodes/candidates tables not present yet"}))
            return 0
        if apply and not _table_exists(cur, "market_event_outcomes"):
            print(json.dumps({"lane": LANE, "status": "outcomes_table_missing",
                              "detail": "apply migrations/2026_11_07_market_event_outcomes.sql first"}))
            return 1
        world = load_world(cur, today)
        sessions = sessions_for(today)
        scored, skipped = score_world(world, sessions, now)
        if a.scorecard:
            print(json.dumps(MO.scorecard(scored, a.scorecard), indent=1, default=str))
            return 0
        if a.friday_check:
            if not world["episodes"]:
                print(json.dumps({"status": "no_episode"}))
                return 0
            ep = world["episodes"][-1]
            syms = [c["symbol"] for c in world["candidates"][ep["episode_id"]]]
            start = ep["baseline_date"] or ep["opened_at"].date()
            print(json.dumps(MO.friday_check(world["closes"], syms, sessions, start, today), indent=1, default=str))
            return 0
        observed = sum(1 for r in scored for n in MO.HORIZONS if r.get(f"ret_{n}") is not None)
        summary = {"lane": LANE, "mode": "apply" if apply else "dry_run", "episodes": len(world["episodes"]),
                   "signal_rows": len(scored), "returns_observed": observed, "skipped": skipped}
        if apply:
            for r in scored:
                cur.execute(UPSERT, r)
            conn.commit()
            from scripts.lib.lane_last_receipt import write_lane_receipt  # noqa: PLC0415

            # produced_count == 0 has two causes and the receipt must name which one (LQ-20261107-479, the same
            # shape as LQ-458 in market_event_detect): no episode at all in the lookback (normal idle), or
            # episodes in scope with nothing to signal -- an open episode the ranker left empty. The second is
            # NOT "no new input"; before this both wrote the same receipt and the second graded
            # empty_reason_not_allowed (RUN_FAILED) once the lane became dispatchable. Causes that really are
            # failures (a candidate with no price, a malformed episode) stay failures through the contract's
            # fatal_skip_reasons, which outranks any allowed empty reason.
            empty = "no_new_input" if not world["episodes"] else "no_candidates_in_scope"
            write_lane_receipt(LANE, ok=True, exit_code=0, started_at=started, script="scripts/market_event_outcomes.py",
                               summary=summary, produced_count=len(scored), attempted_count=len(scored),
                               skipped_reasons=skipped or None, empty_reason=empty if not scored else None)
        print(json.dumps(summary, default=str))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
