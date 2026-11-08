#!/usr/bin/env python3
"""Market Outlook Engine — evaluate one outlook and say what it measured (§2, §4.6).

    python scripts/market_outlook_evaluate.py --mode sunday --dry-run          # prints the brief, writes nothing
    python scripts/market_outlook_evaluate.py --mode sunday --apply            # writes the record + runtime JSON

Modes: ``sunday`` (the weekly view, whole-week horizon), ``monday`` (same skeleton re-scored at 07:00 ET, plus what
changed overnight) and ``daily`` (Tue-Fri, ~12 lines). ``event`` exists in the record vocabulary for WU-3's event
briefs and is not produced here.

The engine is advisory only: it never sizes, orders, stops or weights anything (MBI_BEHAVIOR = 0), it reads no
credential, and it refuses every row from a banned feed (yfinance / yahoo) instead of scoring it.

Exit codes: 0 = the evaluation ran and every required section was produced; 2 = the record failed its own structural
checks (the brief is still printed so the reason is visible), or a refused argument combination (``--hitrate`` with
``--apply``); 3 = the input could not be read at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.market_outlook import (  # noqa: E402
    CATEGORY_KEYS,
    brief as brief_mod,
    calendar as cal_mod,
    categories as cat_mod,
    confidence as conf_mod,
    levels as lvl_mod,
    policy as policy_mod,
    record as rec_mod,
    regime as regime_mod,
    scoring,
    sources,
)

ET = ZoneInfo("America/New_York")
MODES = ("sunday", "monday", "daily")
HORIZON_SESSIONS = {"sunday": 5, "monday": 2, "daily": 2}  # the event window each mode's brief covers


def _now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=ET).astimezone(timezone.utc)


def _state_root(explicit: str | None) -> Path:
    from scripts.lib.market_outlook import state_root as srmod

    return srmod.resolve(explicit)


def _connect(db: str):
    """A connection for the *record* write (``--apply`` only; the bundle has its own read-only reader)."""
    if db == "peer":  # the documented read-only peer path; never used for a write
        return sources._peer_conn()
    try:
        from scripts.session13_db import get_conn
    except ImportError:  # pragma: no cover - scripts/ on sys.path
        from session13_db import get_conn  # type: ignore[no-redef]

    return get_conn()


def _read_conn(db: str):
    """A read-only connection for the record SELECTs (prior band, grades, sequence).

    The reads run before ``--apply`` decides to write, so they must not hold a read-write session: on ``--db app``
    the lane connection is opened read-only by ``sources._app_conn`` (LQ-985 review: this used ``get_conn()``)."""
    return sources._peer_conn() if db == "peer" else sources._app_conn()


# ── prior record + grade history --------------------------------------------------------------------------------
def _prior_from_db(db: str, now: datetime) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """The most recent record strictly before ``now`` and the last few band/score pairs for hysteresis."""
    conn = None
    try:
        conn = _read_conn(db)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT record_id, as_of, band, score FROM market_outlook_records "
                "WHERE as_of < %s ORDER BY as_of DESC LIMIT 12",
                [now],
            )
            rows = [
                {"record_id": r[0], "as_of": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
                 "band": r[2], "score": None if r[3] is None else float(r[3])}
                for r in cur.fetchall()
            ]
        finally:
            cur.close()
    except Exception:  # noqa: BLE001 - a missing table (the migration is the lead's to apply) is not an error here
        return None, []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    return (rows[0] if rows else None), rows


def _prior_from_runtime(state_root: Path) -> dict[str, Any] | None:
    path = state_root / "data" / "runtime" / "market_outlook" / "latest.json"
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    rec = body.get("record") if isinstance(body, dict) and "record" in body else body
    if not isinstance(rec, dict) or not rec.get("band"):
        return None
    return {"record_id": rec.get("record_id"), "as_of": rec.get("as_of"), "band": rec.get("band"), "score": rec.get("score")}


def _hitrate(db: str, policy: dict[str, Any]) -> tuple[float, str]:
    conn = None
    try:
        conn = _read_conn(db)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT status, band_hit FROM market_outlook_grades ORDER BY week_ending DESC LIMIT 12"
            )
            grades = [{"status": r[0], "band_hit": r[1]} for r in cur.fetchall()]
        finally:
            cur.close()
    except Exception:  # noqa: BLE001
        grades = []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    return conf_mod.hitrate_from_grades(list(reversed(grades)), policy)


def _seq(db: str, state_root: Path, now: datetime, mode: str) -> int:
    day = now.astimezone(ET).date()
    conn = None
    try:
        conn = _read_conn(db)
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT count(*) FROM market_outlook_records WHERE record_id LIKE %s", [f"outlook:{day.isoformat()}:{mode}:%"]
            )
            n = int(cur.fetchone()[0])
            return n + 1
        finally:
            cur.close()
    except Exception:  # noqa: BLE001
        return 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ── the evaluation ----------------------------------------------------------------------------------------------
def evaluate(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    now = _now(args.now)
    policy = policy_mod.load_policy(args.policy)
    version = policy_mod.policy_version(args.policy)
    state_root = _state_root(args.state_root)
    fixture = Path(args.fixture) if args.fixture else None

    bundle = sources.load_bundle(policy, now=now, fixture=fixture, db=args.db, state_root=state_root)
    items = list(bundle.macro_events or [])

    regime = regime_mod.resolve(bundle, policy, now, CATEGORY_KEYS)
    weights = {c["key"]: float(c["weight"]) * float(regime.multipliers.get(c["key"], 1.0)) for c in policy["categories"]}

    tau, tau_detail = cal_mod.tilt(items, policy, now)
    surprise, surprise_detail = cal_mod.prior_surprise(bundle, policy, now, items)
    fomc_win, fomc_detail = cal_mod.fomc_window(items, policy, now)
    vix_pct = _vix_percentile(bundle)

    bctx = cat_mod.BuildContext(
        bundle=bundle,
        policy=policy,
        now=now,
        tilt=tau,
        tilt_detail=tau_detail,
        surprise=surprise,
        surprise_detail=surprise_detail,
        vix_pct=vix_pct,
        vix_value=regime.vix_value,
        vix_source=regime.vix_source,
    )
    cats = cat_mod.build_categories(bctx, weight_effective=weights)

    prior, history = _prior_from_db(args.db, now)
    if prior is None:
        prior = _prior_from_runtime(state_root)
    score = scoring.compute(cats, policy, regime, prior=prior, history=history, fomc_window=fomc_win)

    u_event, named_events = cal_mod.u_event(items, policy, now, HORIZON_SESSIONS[args.mode])
    hitrate, hitnote = _hitrate(args.db, policy) if args.hitrate is None else (float(args.hitrate), "operator override")
    confidence = conf_mod.compute(
        cats, policy, now, u_event=u_event, hitrate=hitrate,
        u_event_note=(f"U_event {u_event:.2f} for {', '.join(named_events)}" if named_events else "no HIGH event inside the horizon"),
    )
    confidence.notes.append(hitnote)

    atr = scoring.weekly_atr_pct(bundle.bars, policy["levels"]["proxy"])
    scen = scoring.scenarios(score.score or 0.0, regime.vix_value, atr, policy)
    levels = lvl_mod.key_levels(bundle, policy)
    triggers = lvl_mod.what_would_change_view(score.band, levels)
    catalysts = cal_mod.upcoming(items, now, HORIZON_SESSIONS[args.mode])

    actions = dict(policy["actions"].get(score.band or "NEUTRAL", {}))
    actions["band"] = score.band
    if confidence.band == "LOW":
        actions["downgrade"] = "LOW confidence: every action here is one notch toward NEUTRAL"

    seq = _seq(args.db, state_root, now, args.mode)
    record = rec_mod.build(
        now=now,
        mode=args.mode,
        seq=seq,
        policy_version=version,
        score=score,
        confidence=confidence,
        regime=regime,
        categories=cats,
        scenarios=scen,
        levels=levels,
        catalysts=catalysts,
        what_would_change_view=triggers,
        actions_template=actions,
        prior_record_id=(prior or {}).get("record_id"),
        commit=args.engine_commit,
    )
    problems = rec_mod.validate(record)

    payload = {
        "record": record,
        "problems": problems,
        "regime": regime.to_dict(),
        "score": score.to_dict(),
        "confidence": confidence.to_dict(),
        "unknown_reasons": {c.key: c.reason_unknown for c in cats if c.state == "UNKNOWN"},
        "fomc_window": {"active": fomc_win, "detail": fomc_detail},
        "event_tilt": {"tau": tau, "detail": tau_detail},
        "prior_record_id": (prior or {}).get("record_id"),
        "dry_run": not args.apply,
        "state_root": str(state_root),
    }
    return payload, {
        "bundle": bundle, "levels": levels, "triggers": triggers, "catalysts": catalysts,
        "policy": policy, "now": now, "state_root": state_root,
        "categories": cats, "score": score, "confidence": confidence, "regime": regime,
    }


def _vix_percentile(bundle: Any) -> float | None:
    rows = list((bundle.fred or {}).get("VIXCLS") or [])
    if len(rows) < 60:
        return None
    values = [float(r["value"]) for r in rows]
    return sum(1 for v in values if v <= values[-1]) / len(values)


# ── apply -------------------------------------------------------------------------------------------------------
def _write_runtime(state_root: Path, payload: dict[str, Any]) -> list[str]:
    rt = state_root / "data" / "runtime" / "market_outlook"
    (rt / "receipts").mkdir(parents=True, exist_ok=True)
    record = payload["record"]
    stamp = record["as_of"].replace(":", "-")
    written = []
    bodies = {
        rt / "latest.json": {"schema": "MarketOutlookLatest@v1", "updated_at": record["as_of"], "record": record},
        rt / "run_last.json": {
            "schema": "MarketOutlookRunLast@v1",
            "at": record["as_of"],
            "record_id": record["record_id"],
            "score": record["score"],
            "band": record["band"],
            "confidence": record["confidence"],
            "problems": payload.get("problems") or [],
            "state_root": str(state_root),
        },
        rt / "receipts" / f"{record['record_id'].replace(':', '-')}-{stamp}.json": record,
    }
    for path, body in bodies.items():
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(body, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        tmp.replace(path)
        written.append(str(path))
    return written


def _apply(args: argparse.Namespace, payload: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    from scripts.lib.writers import market_outlook_writer as writer

    if args.db == "peer":
        raise SystemExit("--apply cannot use --db peer: the peer role is read-only by design")
    if payload["problems"]:
        return {"written": [], "receipt": None, "refused": payload["problems"]}
    conn = _connect(args.db)
    try:
        cur = conn.cursor()
        try:
            receipt = writer.write_records(cur, [payload["record"]])
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
    finally:
        conn.close()
    files = _write_runtime(extra["state_root"], payload)
    return {"written": files, "receipt": receipt, "refused": None}


# ── main --------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate the Market Outlook (advisory only; never trades).")
    ap.add_argument("--mode", choices=MODES, default="sunday")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", dest="apply", action="store_false", help="print the brief, write nothing (default)")
    g.add_argument("--apply", dest="apply", action="store_true", help="write the record, runtime JSON and DB row")
    ap.set_defaults(apply=False)
    ap.add_argument("--policy", default=str(policy_mod.POLICY_PATH))
    ap.add_argument("--fixture", help="a Bundle JSON to evaluate instead of the database")
    ap.add_argument("--db", choices=("app", "peer"), default="app")
    ap.add_argument("--now", help="ISO instant to evaluate as of (default: now)")
    ap.add_argument("--state-root", help="persistent-state root (default: lane_state_root)")
    ap.add_argument("--engine-commit", help="override the engine_commit stamped on the record")
    ap.add_argument("--hitrate", type=float, help="override the trailing band hit rate (0..1 -> 0.5..1 confidence factor)")
    ap.add_argument("--json", action="store_true", help="print the record as JSON instead of the brief")
    args = ap.parse_args(argv)
    if args.hitrate is not None and args.apply:
        # the hit rate is evidence, and the record's confidence must be reproducible from the grades table: an
        # operator override may shape a dry-run view, but a written record keeps the measured value (LQ-985 review).
        print("--hitrate cannot be combined with --apply: a written record's confidence uses the measured "
              "market_outlook_grades hit rate, not an override (run the dry run without --apply to preview it)",
              file=sys.stderr)
        return 2

    try:
        payload, extra = evaluate(args)
    except policy_mod.PolicyError as exc:
        print(f"market outlook: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001 - the read layer's failure must be visible, not a traceback soup
        print(f"market outlook: could not evaluate: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    record = payload["record"]
    text = brief_mod.render_text(
        record=record,
        categories=extra["categories"],
        score=extra["score"],
        confidence=extra["confidence"],
        regime=extra["regime"],
        levels=extra["levels"],
        catalysts=extra["catalysts"],
        triggers=extra["triggers"],
        policy=extra["policy"],
        mode=args.mode,
        dry_run=not args.apply,
        data_as_of=(extra["bundle"].as_of if extra["bundle"] is not None else None),
    )

    applied = None
    if args.apply:
        applied = _apply(args, payload, extra)
        payload["apply"] = applied

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(text)
        if applied is not None:
            print("")
            if applied["refused"]:
                print("APPLY REFUSED: " + "; ".join(applied["refused"]))
            else:
                print(f"APPLIED {record['record_id']} — row {applied['receipt']['inserted']} inserted; "
                      f"{len(applied['written'])} runtime file(s) written")
                for f in applied["written"]:
                    print(f"  {f}")
    if payload["problems"]:
        print("RECORD PROBLEMS: " + "; ".join(payload["problems"]), file=sys.stderr)
        return 2
    if applied is not None and applied.get("refused"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
