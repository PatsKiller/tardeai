#!/usr/bin/env python3
"""MAIN desk free-LLM critics — trading-day Flash batch (policy 2026-08-03).

Default lanes: deepseek-flash + local + grok + chatgpt (NO Pro/v4).
Cadence: trading days (skip if critics already ran with same ticket hash /
within FRESH_HOURS). Weekly stamp file kept for UI compatibility.

Never schedules premium / paid Pro by default. Never submits orders. Advisory only.

Usage:
  python scripts/main_desk_free_llm_weekly.py --dry-run
  python scripts/main_desk_free_llm_weekly.py --run
  python scripts/main_desk_free_llm_weekly.py --run --force   # ignore freshness
  python scripts/main_desk_free_llm_weekly.py --status
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

try:
    from llm_route_policy import FREE_CRITIC_LANES, free_critic_lanes_csv
    LANES = FREE_CRITIC_LANES
    LANES_CSV = free_critic_lanes_csv()
except Exception:
    LANES = ("deepseek-flash", "local", "grok", "chatgpt")
    LANES_CSV = "deepseek-flash,local,grok,chatgpt"
# Re-run if last free-lane stamp older than this (trading-day freshness)
FRESH_DAYS = 0.85  # ~20h — once per trading day unless data/ticket changed
FRESH_HOURS = 20
DEFAULT_CAP = 60
STAMP_NAME = "main_desk_free_llm_weekly.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _runtime_dir() -> Path:
    """Prefer shared canon runtime so portfolio-server (release data symlink) can read the stamp."""
    candidates = [
        Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/runtime"),
        Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild" / "data" / "runtime",
        # Only use PROJECT_ROOT if it already looks like a live data tree (has sibling state/portfolios)
        PROJECT_ROOT / "data" / "runtime",
    ]
    for path in candidates:
        try:
            parent = path.parent
            # Prefer trees that already host portfolio state / other runtime artifacts
            live = (parent / "portfolios").exists() or (parent / "state").exists() or any(path.glob("*.json"))
            path.mkdir(parents=True, exist_ok=True)
            if live or path == candidates[0]:
                return path
        except Exception:
            continue
    path = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/runtime")
    path.mkdir(parents=True, exist_ok=True)
    return path


def stamp_path() -> Path:
    return _runtime_dir() / STAMP_NAME


def load_stamp() -> dict:
    path = stamp_path()
    if not path.exists():
        return {"ok": False, "exists": False, "path": str(path)}
    try:
        data = json.loads(path.read_text())
        data["ok"] = True
        data["exists"] = True
        data["path"] = str(path)
        return data
    except Exception as exc:
        return {"ok": False, "exists": True, "path": str(path), "error": str(exc)[:200]}


def write_stamp(payload: dict) -> Path:
    path = stamp_path()
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _lane_ran_at(review: dict | None) -> datetime | None:
    if not isinstance(review, dict):
        return None
    for key in ("ran_at", "reviewed_at", "completed_at", "generated_at", "as_of", "ts"):
        dt = _parse_ts(review.get(key))
        if dt:
            return dt
    return None


def _reviews_fresh(reviews: dict, *, force: bool) -> bool:
    if force:
        return False
    if not isinstance(reviews, dict):
        return False
    stamps = []
    for lane in LANES:
        block = reviews.get(lane) or {}
        if not block.get("verdict"):
            return False
        stamps.append(_lane_ran_at(block))
    # All three present: fresh if newest is within FRESH_DAYS
    present = [s for s in stamps if s]
    if len(present) < len(LANES):
        return False
    newest = max(present)
    return (_now() - newest) < timedelta(days=FRESH_DAYS)


def list_main_symbols(conn, *, cap: int = DEFAULT_CAP) -> list[dict]:
    """MAIN desk symbols — prefer live portfolio-server lane=main (same as CC desk)."""
    import urllib.error
    import urllib.request

    # 1) Prefer the same API the MAIN desk uses (admission + cap already applied).
    for port in (7777, 8787, 8090):
        try:
            url = f"http://127.0.0.1:{port}/api/v2/watchlist/items?lane=main&limit={int(cap)}"
            with urllib.request.urlopen(url, timeout=45) as resp:
                payload = json.loads(resp.read().decode())
            items = (payload.get("data") or payload).get("items") or payload.get("items") or []
            if items:
                out = []
                for it in items:
                    sym = str(it.get("symbol") or "").upper()
                    if not sym:
                        continue
                    out.append({
                        "symbol": sym,
                        "now_status": it.get("now_status"),
                        "lane": it.get("lane") or "main",
                        "source": it.get("source"),
                        "hermes_rank": it.get("hermes_rank"),
                        "decision_quality_status": it.get("decision_quality_status"),
                    })
                return out[:cap]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            continue

    # 2) Fallback: hermes-ranked active watchlist symbols (admission not applied).
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (upper(symbol))
               upper(symbol) AS symbol, source, status, score,
               hermes_rank, hermes_composite_score, origin_system
        FROM watchlist_items
        WHERE status <> 'removed'
        ORDER BY upper(symbol), hermes_rank ASC NULLS LAST, updated_at DESC NULLS LAST
        LIMIT %s
        """,
        (int(cap),),
    )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _packet_for(conn, symbol: str) -> tuple[str | None, dict]:
    cur = conn.cursor()
    cur.execute(
        """SELECT packet_id, packet FROM decision_packets
           WHERE upper(symbol)=%s AND superseded_by IS NULL""",
        (symbol,),
    )
    row = cur.fetchone()
    if not row:
        return None, {}
    return row[0], (row[1] or {})


def plan_symbol(conn, item: dict, *, force: bool) -> dict:
    import watch_packet_quality as packet_quality

    symbol = str(item.get("symbol") or "").upper()
    packet_id, packet = _packet_for(conn, symbol)
    if not packet_id:
        return {
            "symbol": symbol,
            "action": "skip",
            "reason": "no_live_packet",
            "now_status": item.get("now_status"),
        }

    selected = packet_quality.select_governing_validation(packet)
    validation = selected.get("validation") or {}
    deterministic = selected.get("deterministic") or "NOT_RUN"
    quality = validation.get("quality_admission") or {}
    prior = packet.get("ticket_review") or {}
    reviews = prior.get("reviews") or {}
    missing = [lane for lane in LANES if not (reviews.get(lane) or {}).get("verdict")]
    fresh = _reviews_fresh(reviews, force=force)

    may_review = (
        deterministic in {"PASS", "REVIEW_REQUIRED"}
        and quality.get("state") == "ADMITTED"
        and quality.get("new_entry_allowed") is not False
    )

    if not may_review:
        return {
            "symbol": symbol,
            "action": "skip",
            "reason": "not_eligible",
            "deterministic": deterministic,
            "quality": quality.get("state"),
            "new_entry_allowed": quality.get("new_entry_allowed"),
            "now_status": item.get("now_status"),
            "missing_lanes": missing,
        }

    if fresh and not missing:
        last = max((_lane_ran_at(reviews.get(lane) or {}) for lane in LANES), default=None)
        return {
            "symbol": symbol,
            "action": "skip",
            "reason": "fresh_within_week",
            "last_lane_at": last.isoformat() if last else None,
            "now_status": item.get("now_status"),
        }

    return {
        "symbol": symbol,
        "action": "run",
        "reason": "force" if force else ("missing_lanes" if missing else "stale_weekly"),
        "missing_lanes": missing,
        "deterministic": deterministic,
        "quality": quality.get("state"),
        "now_status": item.get("now_status"),
        "packet_id": packet_id,
    }


def run_batch(*, dry_run: bool, force: bool, cap: int, lanes: str) -> dict:
    from env_bootstrap import load_env
    load_env()
    from db_adapter import _get_conn

    started = _now()
    conn = _get_conn()
    main_items = list_main_symbols(conn, cap=cap)
    plan_rows = [plan_symbol(conn, it, force=force) for it in main_items]

    to_run = [r for r in plan_rows if r.get("action") == "run"]
    skipped = [r for r in plan_rows if r.get("action") == "skip"]

    results: list[dict] = []
    if dry_run:
        payload = {
            "ok": True,
            "dry_run": True,
            "lanes": lanes,
            "started_at": _iso(started),
            "finished_at": _iso(),
            "main_pool_n": len(main_items),
            "planned_run_n": len(to_run),
            "planned_skip_n": len(skipped),
            "planned_run": to_run,
            "planned_skip": skipped[:80],
            "cadence": "weekly",
            "fresh_days": FRESH_DAYS,
            "policy": "free lanes only — local, grok OAuth, chatgpt OAuth; never premium",
        }
        return payload

    # Live runs — sequential so OAuth/local lanes do not stampede
    from run_ticket_review_job import main as review_main

    for row in to_run:
        sym = row["symbol"]
        t0 = time.time()
        entry = {
            "symbol": sym,
            "started_at": _iso(),
            "lanes": lanes,
            "reason": row.get("reason"),
        }
        try:
            # Each symbol gets a fresh process-level review (new DB inside job).
            review_main(sym, lanes)
            entry["ok"] = True
        except Exception as exc:
            entry["ok"] = False
            entry["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        # Always re-open DB after long OAuth/local calls (conn may be dead).
        try:
            conn = _get_conn()
            _pid, packet = _packet_for(conn, sym)
            reviews = ((packet or {}).get("ticket_review") or {}).get("reviews") or {}
            entry["verdicts"] = {
                lane: (reviews.get(lane) or {}).get("verdict")
                for lane in LANES
            }
            rec = ((packet or {}).get("ticket_review") or {}).get("reconciled") or {}
            entry["reconciled"] = rec.get("state") if isinstance(rec, dict) else rec
            entry["ran_at"] = {
                lane: ((_lane_ran_at(reviews.get(lane) or {}) or _now()).isoformat())
                for lane in LANES
                if (reviews.get(lane) or {}).get("verdict")
            }
            # If any lane wrote a verdict, treat batch row as ok even if re-read had noise
            if any(entry.get("verdicts", {}).values()):
                entry["ok"] = True
                entry.pop("error", None)
        except Exception as exc:
            entry.setdefault("error", f"reread:{type(exc).__name__}:{str(exc)[:120]}")
        entry["finished_at"] = _iso()
        entry["elapsed_sec"] = round(time.time() - t0, 2)
        results.append(entry)
        time.sleep(0.5)

    finished = _now()
    ok_n = sum(1 for r in results if r.get("ok"))
    payload = {
        "ok": True,
        "dry_run": False,
        "lanes": lanes,
        "cadence": "weekly",
        "fresh_days": FRESH_DAYS,
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "duration_sec": round((finished - started).total_seconds(), 1),
        "main_pool_n": len(main_items),
        "ran_n": len(results),
        "ok_n": ok_n,
        "fail_n": len(results) - ok_n,
        "skipped_n": len(skipped),
        "skip_reasons": _count_reasons(skipped),
        "results": results,
        "skipped": skipped[:100],
        "next_due_after": _iso(finished + timedelta(days=7)),
        "policy": "free lanes only — local, grok OAuth, chatgpt OAuth; never premium",
        "stamp_version": 1,
    }
    path = write_stamp(payload)
    payload["path"] = str(path)
    return payload


def _count_reasons(rows: list[dict]) -> dict:
    out: dict[str, int] = {}
    for row in rows:
        key = str(row.get("reason") or "unknown")
        out[key] = out.get(key, 0) + 1
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Execute free LLM weekly batch and write stamp")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no model calls")
    parser.add_argument("--force", action="store_true", help="Ignore weekly freshness; re-run eligible")
    parser.add_argument("--status", action="store_true", help="Print last stamp JSON")
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP, help="Max MAIN symbols (default 60)")
    parser.add_argument("--lanes", default=LANES_CSV, help="Comma lanes (default local,grok,chatgpt)")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(load_stamp(), indent=2, default=str))
        return 0

    if not args.run and not args.dry_run:
        # default safe
        args.dry_run = True

    out = run_batch(
        dry_run=bool(args.dry_run and not args.run),
        force=bool(args.force),
        cap=int(args.cap or DEFAULT_CAP),
        lanes=str(args.lanes or LANES_CSV),
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
