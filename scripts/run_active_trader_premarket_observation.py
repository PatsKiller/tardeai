"""Stage 5 harness — thin composition root for the premarket observation launcher.

Wires the deterministic modules (calendar, observation core, symbol selector, scheduler) and
the DATA-ONLY adapter. Business logic lives in the modules; this file only composes and routes.

Modes:
  --mode schedule   : print the schedule plan + rendered transient-unit (redacted). Nothing runs.
  --mode dry-run    : alias of schedule (explicit dry-run of the scheduler renderer).
  --mode replay     : run the deterministic core over an event fixture; emit artifacts.
  --execute-schedule: returns NOT_AUTHORIZED_BY_BUILD_TRANSACTION (never schedules here).
  --mode live       : verify the owner authorization marker; without it returns
                      BLOCKED_OWNER_AUTHORIZATION_REQUIRED and does NOT start OpenD.

NO OpenD / login / trade / scheduler action is performed by this build transaction.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from active_trader import market_calendar as cal
from active_trader import premarket_observation as po
from active_trader import premarket_symbol_selector as sel
from active_trader import premarket_observation_schedule as sched

_TZ = ZoneInfo("America/New_York")
LAUNCHER_PATH = str(Path(__file__).resolve())
WORKTREE = str(Path(__file__).resolve().parents[1])
STATE_DIR = str(Path.home() / ".local/state/trade-ai-lab/moomoo/observation")
LOG_DIR = str(Path.home() / ".local/state/trade-ai-lab/moomoo/logs")


def _now() -> _dt.datetime:
    return _dt.datetime.now(_TZ)


# ---- event fixture -> ObservationEvent (replay glue) -----------------------

_BASE_DATE = _dt.date(2026, 1, 2)          # a supported qualifying session, for `t`-only fixtures


def event_from_record(r: dict) -> po.ObservationEvent:
    if r.get("receive_ts"):
        rts = _dt.datetime.fromisoformat(r["receive_ts"])
        if rts.tzinfo is None:
            rts = rts.replace(tzinfo=_TZ)
    else:
        secs = float(r["t"])
        rts = _dt.datetime.combine(_BASE_DATE, _dt.time(0, 0), _TZ) + _dt.timedelta(seconds=secs)
    return po.ObservationEvent(
        observation_session_id=r.get("observation_session_id", "fixture"),
        symbol=r["symbol"], symbol_role=r.get("symbol_role", "BASELINE"),
        stream=r["stream"], receive_ts=rts,
        provider_timestamp=r.get("provider_timestamp"),
        server_bid_timestamp=r.get("server_bid_timestamp"),
        server_ask_timestamp=r.get("server_ask_timestamp"),
        provider_seq=r.get("provider_seq"),
        cached_first_push=bool(r.get("cached_first_push", False)),
        freshness_state=r.get("freshness_state", po.Freshness.FRESH.value),
        gap_state=r.get("gap_state", po.GapKind.NONE.value),
        queue_state=r.get("queue_state", "HEALTHY"),
        entitlement_state=r.get("entitlement_state", "RESOLVED"),
        market_state=r.get("market_state"),
        bid=r.get("bid"), ask=r.get("ask"), bid_size=r.get("bid_size"), ask_size=r.get("ask_size"),
        bids=[tuple(x) for x in r["bids"]] if r.get("bids") else None,
        asks=[tuple(x) for x in r["asks"]] if r.get("asks") else None,
        last=r.get("last"), trade_size=r.get("trade_size"))


def run_replay(fixture_path: Path, out_dir: Path | None = None) -> dict:
    data = json.loads(Path(fixture_path).read_text())
    meta = data.get("meta", {})
    events = [event_from_record(r) for r in data["events"]]
    symbols = meta.get("symbols") or sorted({e.symbol for e in events})
    rep = meta.get("representative")
    rank = bool(meta.get("rank_available", rep is not None))
    v = po.evaluate(events, symbols=symbols, representative=rep, rank_available=rank,
                    entitlement_ok=meta.get("entitlement_ok", True),
                    critical_failures=meta.get("critical_failures"),
                    wal_parquet_replay_ok=meta.get("wal_parquet_replay_ok", True),
                    safety_ok=meta.get("safety_ok", True))
    # replay-equality
    a = json.dumps(v.as_dict(), sort_keys=True, default=str)
    b = json.dumps(po.evaluate(events, symbols=symbols, representative=rep, rank_available=rank,
                               entitlement_ok=meta.get("entitlement_ok", True),
                               critical_failures=meta.get("critical_failures"),
                               wal_parquet_replay_ok=meta.get("wal_parquet_replay_ok", True),
                               safety_ok=meta.get("safety_ok", True)).as_dict(),
                   sort_keys=True, default=str)
    result = {"verdicts": v.as_dict(), "replay_equal": a == b}
    if out_dir:
        out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "PREMARKET_SESSION_LEVEL2_QUALITY.json").write_text(
            json.dumps(v.level2_metrics, indent=2, sort_keys=True, default=str))
        (out_dir / "PREMARKET_SESSION_VERDICTS.json").write_text(
            json.dumps({k: getattr(v, k) for k in
                        ("premarket_transport", "level2_momentum_suitability",
                         "rth_continuous_capture", "session_counted", "critical_failures", "notes")},
                       indent=2, sort_keys=True, default=str))
    return result


def current_git_sha() -> str:
    try:
        return subprocess.check_output(["git", "-C", WORKTREE, "rev-parse", "HEAD"],
                                       text=True).strip()
    except Exception:
        return "UNKNOWN"


def run_live(args) -> dict:
    """Refuses without an owner authorization marker. Never starts OpenD in this build."""
    marker = None
    if args.authorization_marker:
        marker = sched.ObservationAuthorizationMarker.from_dict(
            json.loads(Path(args.authorization_marker).read_text()))
    check = sched.verify_live_authorization(
        marker, current_git_sha=current_git_sha(), worktree_clean=False,
        session_number=args.session_index, now=_now(), smoke_pass=True,
        credential_green=True, trade_scan_pass=True)
    if not check.authorized:
        return {"mode": "live", "result": check.status, "authorization": check.as_dict(),
                "opend_started": False, "moomoo_login": False}
    # Authorized path is intentionally NOT wired to OpenD in this build transaction.
    return {"mode": "live", "result": "AUTHORIZED_BUT_LIVE_CAPTURE_NOT_ENABLED_IN_BUILD",
            "opend_started": False}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Stage 5 premarket observation launcher (data-only)")
    ap.add_argument("--mode", choices=("schedule", "dry-run", "replay", "live"), default="schedule")
    ap.add_argument("--fixture", type=str)
    ap.add_argument("--out", type=str)
    ap.add_argument("--session-index", type=int, default=1)
    ap.add_argument("--authorization-marker", type=str)
    ap.add_argument("--execute-schedule", action="store_true")
    args = ap.parse_args(argv)

    if args.execute_schedule:
        print(json.dumps(sched.execute_schedule(), indent=2))
        return 0

    if args.mode in ("schedule", "dry-run"):
        plan = sched.schedule_plan(_now())
        unit = sched.render_transient_unit(
            now=_now(), launcher_path=LAUNCHER_PATH, worktree=WORKTREE,
            state_dir=STATE_DIR, log_dir=LOG_DIR, session_number=args.session_index)
        print(json.dumps({"schedule": plan, "transient_unit_render": unit,
                          "scheduler_executed": False}, indent=2, default=str))
        return 0

    if args.mode == "replay":
        if not args.fixture:
            print("--fixture required", file=sys.stderr)
            return 2
        print(json.dumps(run_replay(Path(args.fixture), Path(args.out) if args.out else None),
                         indent=2, default=str))
        return 0

    print(json.dumps(run_live(args), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
