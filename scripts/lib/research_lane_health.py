"""Raw-store research lane health.

READ_ONLY_ADVISORY. Reads hermes_external_research (and overnight
deep_research_local rows) WITHOUT the scheduler last_real filter
`recommendation NOT LIKE '[%'`. That filter made a 100% error lane look
like "no new research yet" for 8 days.

Fires when, per lane:
  * the newest N rows are all error-prefixed (`[…]`) or empty, or
  * zero non-error rows in the last 24h.

Does not grant financial_action. Does not call LLMs.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ResearchLaneHealth@v1"

# Auto-dispatched writer lanes in hermes_external_research.
EXTERNAL_AUTO_LANES = ("deepseek", "grok", "chatgpt")
EXTERNAL_MANUAL_LANES = ("claude",)
OVERNIGHT_LANE = "overnight-deep"
COVERAGE_STALL_LANE = "coverage-stall"

DEFAULT_STREAK = 5
DEFAULT_SILENCE_HOURS = 24
# DeepSeek must stay in the watched set even when ok. Silence on weekdays only
# would false-fire Saturday after a Friday success — coverage-stall is the
# "research happened, brain did not learn" alarm.


def error_streak_n() -> int:
    try:
        n = int(os.getenv("RESEARCH_LANE_ERROR_STREAK", str(DEFAULT_STREAK)))
    except ValueError:
        n = DEFAULT_STREAK
    return max(1, n)


def silence_hours() -> int:
    try:
        n = int(os.getenv("RESEARCH_LANE_SILENCE_HOURS", str(DEFAULT_SILENCE_HOURS)))
    except ValueError:
        n = DEFAULT_SILENCE_HOURS
    return max(1, n)


def is_error_recommendation(rec: Any) -> bool:
    """RAW error: empty OR bracket-prefixed. Do not invert last_real."""
    s = str(rec or "").strip()
    if not s:
        return True
    return s.startswith("[")


def consecutive_error_streak(rows_newest_first: Iterable[dict[str, Any]]) -> int:
    n = 0
    for row in rows_newest_first:
        rec = row.get("recommendation")
        if rec is None:
            rec = row.get("summary")
        if is_error_recommendation(rec):
            n += 1
        else:
            break
    return n


def non_error_count(rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    for row in rows:
        rec = row.get("recommendation")
        if rec is None:
            rec = row.get("summary")
        if not is_error_recommendation(rec):
            n += 1
    return n


def evaluate_lane(
    lane: str,
    *,
    newest_first: list[dict[str, Any]],
    last_24h: list[dict[str, Any]],
    silence: bool = True,
    streak_n: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Return a health row. `silence=False` skips the 24h zero-ok rule (manual lanes)."""
    now = now or datetime.now(timezone.utc)
    k = streak_n if streak_n is not None else error_streak_n()
    streak = consecutive_error_streak(newest_first)
    ok_24h = non_error_count(last_24h)
    attempts_24h = len(last_24h)
    last_any = newest_first[0].get("created_at") if newest_first else None
    firing: list[str] = []
    if streak >= k and attempts_24h > 0:
        firing.append(f"error_streak:{streak}>={k}")
    if silence and ok_24h == 0:
        firing.append(f"zero_non_error_{silence_hours()}h")
    return {
        "lane": lane,
        "ok": not firing,
        "firing": firing,
        "error_streak": streak,
        "streak_threshold": k,
        "non_error_24h": ok_24h,
        "attempts_24h": attempts_24h,
        "last_any": last_any,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
    }


def _project_root():
    from pathlib import Path
    return Path(__file__).resolve().parents[2]


def _db_rows(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    try:
        from db_adapter import _execute
        rows = _execute(sql, params, fetch="all") or []
        return [dict(r) for r in rows]
    except Exception:
        return []


def load_external_rows(lane: str, *, since: datetime, limit: int = 50) -> tuple[list[dict], list[dict]]:
    """RAW rows — no NOT LIKE filter."""
    newest = _db_rows(
        """SELECT created_at, recommendation, status, symbol
           FROM hermes_external_research
           WHERE lane=%s
           ORDER BY created_at DESC
           LIMIT %s""",
        (lane, limit),
    )
    last_24h = _db_rows(
        """SELECT created_at, recommendation, status, symbol
           FROM hermes_external_research
           WHERE lane=%s AND created_at >= %s
           ORDER BY created_at DESC""",
        (lane, since),
    )
    return newest, last_24h


def load_overnight_rows(*, since: datetime, limit: int = 50) -> tuple[list[dict], list[dict]]:
    newest = _db_rows(
        """SELECT created_at, summary AS recommendation, status, symbol, model_used
           FROM hermes_research_intelligence
           WHERE research_type='deep_research_local'
           ORDER BY created_at DESC
           LIMIT %s""",
        (limit,),
    )
    last_24h = _db_rows(
        """SELECT created_at, summary AS recommendation, status, symbol, model_used
           FROM hermes_research_intelligence
           WHERE research_type='deep_research_local' AND created_at >= %s
           ORDER BY created_at DESC""",
        (since,),
    )
    return newest, last_24h


def _deepseek_ok(lanes: list[dict[str, Any]]) -> int:
    for r in lanes:
        if r.get("lane") == "deepseek":
            try:
                return int(r.get("non_error_24h") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def collect_coverage_stall(
    *,
    now: Optional[datetime] = None,
    deepseek_ok_24h: int = 0,
    thesis_current: Optional[int] = None,
    thesis_held: Optional[int] = None,
    snap_path: Optional[Any] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Fire when research rows arrive and living thesis CURRENT does not move.

    Today (2026-08-22): 545 DeepSeek ok, held CURRENT still 3/22. That fires.
    """
    now = now or datetime.now(timezone.utc)
    from pathlib import Path
    root = _project_root()
    if snap_path is None:
        snap_path = root / "data" / "runtime" / "coverage_stall_snapshot.json"
    snap_path = Path(snap_path)
    if thesis_current is None or thesis_held is None:
        try:
            from scripts.lib.cio_held_thesis_coverage import build_held_coverage_report
            cov = build_held_coverage_report(root=root)
            thesis_current = int(cov.get("current_count") or 0)
            thesis_held = int(cov.get("held_count") or 0)
        except Exception:
            try:
                p = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio/held_thesis_coverage_latest.json")
                if p.is_file():
                    import json
                    d = json.loads(p.read_text())
                    thesis_current = int(d.get("current_count") or 0)
                    thesis_held = int(d.get("held_count") or 0)
            except Exception:
                pass
    prev = {}
    try:
        import json
        if snap_path.is_file():
            prev = json.loads(snap_path.read_text()) or {}
    except Exception:
        prev = {}
    prev_research = int(prev.get("deepseek_ok_24h") or 0)
    prev_thesis = prev.get("thesis_current")
    firing: list[str] = []
    if (
        deepseek_ok_24h >= 20
        and thesis_current is not None
        and thesis_held
        and thesis_current < max(1, int(0.8 * thesis_held))
        and (prev_thesis is None or int(prev_thesis) <= thesis_current)
        and deepseek_ok_24h >= prev_research
    ):
        firing.append(
            f"research_up_thesis_flat:deepseek_ok_24h={deepseek_ok_24h}"
            f",thesis_current={thesis_current}/{thesis_held}"
        )
    rec = {
        "lane": COVERAGE_STALL_LANE,
        "ok": not firing,
        "firing": firing,
        "error_streak": 0,
        "non_error_24h": deepseek_ok_24h,
        "attempts_24h": deepseek_ok_24h,
        "thesis_current": thesis_current,
        "thesis_held": thesis_held,
        "prev_deepseek_ok_24h": prev_research,
        "prev_thesis_current": prev_thesis,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
    }
    if persist:
        try:
            import json
            snap_path.parent.mkdir(parents=True, exist_ok=True)
            snap_path.write_text(json.dumps({
                "as_of": rec["as_of"],
                "deepseek_ok_24h": deepseek_ok_24h,
                "thesis_current": thesis_current,
                "thesis_held": thesis_held,
            }, indent=2) + "\n")
        except OSError:
            pass
    return rec


def collect_report(*, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=silence_hours())
    lanes: list[dict[str, Any]] = []
    for lane in EXTERNAL_AUTO_LANES:
        newest, last_24h = load_external_rows(lane, since=since)
        lanes.append(evaluate_lane(lane, newest_first=newest, last_24h=last_24h, silence=True, now=now))
    for lane in EXTERNAL_MANUAL_LANES:
        newest, last_24h = load_external_rows(lane, since=since)
        lanes.append(evaluate_lane(lane, newest_first=newest, last_24h=last_24h, silence=False, now=now))
    if os.getenv("RESEARCH_LANE_HEALTH_OVERNIGHT", "1").strip().lower() not in {"0", "false", "off", "no"}:
        newest, last_24h = load_overnight_rows(since=since)
        lanes.append(
            evaluate_lane(
                OVERNIGHT_LANE,
                newest_first=newest,
                last_24h=last_24h,
                silence=True,
                now=now,
            )
        )
    if os.getenv("RESEARCH_LANE_HEALTH_PIN", "1").strip().lower() not in {"0", "false", "off", "no"}:
        try:
            from scripts.lib.current_pin_integrity import collect_pin_report
        except Exception:
            from current_pin_integrity import collect_pin_report  # type: ignore
        lanes.append(collect_pin_report(now=now))
    if os.getenv("RESEARCH_LANE_HEALTH_DRIVE", "1").strip().lower() not in {"0", "false", "off", "no"}:
        try:
            from scripts.lib.drive_sync_health import collect_drive_report
        except Exception:
            from drive_sync_health import collect_drive_report  # type: ignore
        lanes.append(collect_drive_report(now=now))
    if os.getenv("RESEARCH_LANE_HEALTH_COVERAGE_STALL", "1").strip().lower() not in {
        "0", "false", "off", "no"
    }:
        lanes.append(collect_coverage_stall(now=now, deepseek_ok_24h=_deepseek_ok(lanes)))
    firing = [r for r in lanes if not r["ok"]]
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "reads_raw_store": True,
        "filters_last_real": False,
        "lanes": lanes,
        "firing": [r["lane"] for r in firing],
        "ok": not firing,
    }
