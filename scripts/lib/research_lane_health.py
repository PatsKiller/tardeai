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

import json
import re
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

try:  # same package as the caller: never a second spelling (DualImportIdentityError)
    from .research_refusal import classify_refusal as _classify_refusal
except ImportError:  # monitor path loads this file as a top-level module on scripts/lib
    try:
        from research_refusal import classify_refusal as _classify_refusal
    except ImportError:
        _classify_refusal = None

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ResearchLaneHealth@v1"

# Auto-dispatched writer lanes in hermes_external_research.
EXTERNAL_AUTO_LANES = ("deepseek", "grok", "chatgpt")
EXTERNAL_MANUAL_LANES = ("claude",)
OVERNIGHT_LANE = "overnight-deep"
COVERAGE_STALL_LANE = "coverage-stall"
#: The provider the overnight deep-research lane calls. Its own prober writes a verdict; the
#: overnight alarm must read it rather than report a bare silence (LQ-20261107-1659).
OVERNIGHT_PROVIDER_LANE = "chatgpt"
OAUTH_LANE_STATUS_REL = ("data", "runtime", "oauth_lane_status.json")

DEFAULT_STREAK = 5
DEFAULT_SILENCE_HOURS = 24
# Streak resets on one success. 441/1336 COST_CAP errors still look "ok".
DEFAULT_ERROR_RATE_PCT = 15.0
DEFAULT_ERROR_RATE_MIN_N = 10
# DeepSeek must stay in the watched set even when ok. Silence on weekdays only
# would false-fire Saturday after a Friday success — coverage-stall is the
# "research happened, brain did not learn" alarm.


def error_streak_n() -> int:
    try:
        n = int(os.getenv("RESEARCH_LANE_ERROR_STREAK", str(DEFAULT_STREAK)))
    except ValueError:
        n = DEFAULT_STREAK
    return max(1, n)


def error_rate_threshold_pct() -> float:
    try:
        n = float(os.getenv("RESEARCH_LANE_ERROR_RATE_PCT", str(DEFAULT_ERROR_RATE_PCT)))
    except ValueError:
        n = DEFAULT_ERROR_RATE_PCT
    return max(0.0, min(100.0, n))


def error_rate_min_n() -> int:
    try:
        n = int(os.getenv("RESEARCH_LANE_ERROR_RATE_MIN_N", str(DEFAULT_ERROR_RATE_MIN_N)))
    except ValueError:
        n = DEFAULT_ERROR_RATE_MIN_N
    return max(1, n)


def silence_hours() -> int:
    try:
        n = int(os.getenv("RESEARCH_LANE_SILENCE_HOURS", str(DEFAULT_SILENCE_HOURS)))
    except ValueError:
        n = DEFAULT_SILENCE_HOURS
    return max(1, n)


SKIPPED_BUDGET_PREFIX = "[SKIPPED_BUDGET]"


def is_skipped_budget(rec: Any) -> bool:
    """COST_CAP / request-cap throttle. Not a lane crash."""
    return str(rec or "").strip().startswith(SKIPPED_BUDGET_PREFIX)


def is_deferred_offpeak(rec: Any) -> bool:
    """A run parked for the off-peak lane (llm_deferral). It was never attempted, so it is not a lane error.

    2026-11-04: `[DEFERRED_TO_OFFPEAK]` rows counted as errors and produced the bogus 37.9% 24h rate that floored
    intelligence_quality at 60. Like SKIPPED_BUDGET, a deferral is a throttle, not a crash.
    """
    # ANCHORED (cc2 BLOCK): the live row is "[ERROR] DEFERRED_TO_OFFPEAK: …". A substring test would also
    # silence a genuine failure that merely MENTIONS the marker in its text, so the match starts at the head.
    return re.match(r"^\[ERROR\]\s*DEFERRED_TO_OFFPEAK\b", str(rec or "").strip()) is not None


def is_error_recommendation(rec: Any) -> bool:
    """RAW lane-broken: empty OR bracket-prefixed, excluding SKIPPED_BUDGET.

    Do not invert last_real. Do not treat a budget throttle as a broken lane —
    that is how 441 COST_CAP rows hid inside error_streak=0.
    """
    s = str(rec or "").strip()
    if not s:
        return True
    if is_skipped_budget(s) or is_deferred_offpeak(s):
        return False
    return s.startswith("[")


def is_success_recommendation(rec: Any) -> bool:
    s = str(rec or "").strip()
    if not s or is_skipped_budget(s):
        return False
    return not s.startswith("[")


def is_refusal_row(row: Any) -> bool:
    """A model declined to answer: neither research (ok) nor a broken lane (error).

    Three shapes reach the 24h window: status='refused' (writer classified it), the legacy
    status='sent' row whose prose is a refusal (written before the writer classified), and the
    '[REJECTED_DATA_QUALITY] llm_refusal' row. Status is read first because the text can be
    mis-bucketed by prefix alone: a refusal is not '[' prefixed, so it looks like success.
    """
    if not isinstance(row, dict):
        return False
    if str(row.get("status") or "").strip().lower() == "refused":
        return True
    rec = str(_row_rec(row) or "").strip()
    if rec.startswith("[REJECTED_DATA_QUALITY]") and "llm_refusal" in rec:
        return True
    if _classify_refusal is not None and rec and not rec.startswith("["):
        return bool(_classify_refusal(rec)[0])
    return False


def consecutive_error_streak(rows_newest_first: Iterable[dict[str, Any]]) -> int:
    n = 0
    for row in rows_newest_first:
        if is_refusal_row(row):
            # A refusal is neither a lane error nor a success: skip it, so it neither adds to the
            # streak nor ends it. Breaking here hid real errors interleaved with refusals (LQ-554).
            continue
        rec = row.get("recommendation")
        if rec is None:
            rec = row.get("summary")
        if is_error_recommendation(rec):
            n += 1
        else:
            break
    return n


def _row_rec(row: dict[str, Any]) -> Any:
    rec = row.get("recommendation")
    if rec is None:
        rec = row.get("summary")
    return rec


def non_error_count(rows: Iterable[dict[str, Any]]) -> int:
    """Successful research rows — excludes errors AND SKIPPED_BUDGET."""
    n = 0
    for row in rows:
        if is_success_recommendation(_row_rec(row)):
            n += 1
    return n


def skipped_budget_count(rows: Iterable[dict[str, Any]]) -> int:
    n = 0
    for row in rows:
        if is_skipped_budget(_row_rec(row)):
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
    refused_24h = sum(1 for r in last_24h if is_refusal_row(r))
    ok_24h = sum(1 for r in last_24h
                 if is_success_recommendation(_row_rec(r)) and not is_refusal_row(r))
    skip_24h = skipped_budget_count(last_24h)
    attempts_24h = len(last_24h)
    defer_24h = sum(1 for r in last_24h if is_deferred_offpeak(r.get("recommendation")
                                                               if isinstance(r, dict) else r))
    # A refusal is the model declining, not the lane breaking: it is neither ok nor error.
    err_24h = max(0, attempts_24h - ok_24h - skip_24h - defer_24h - refused_24h)
    judged = ok_24h + err_24h  # exclude throttle from lane-broken rate
    rate = round(100.0 * err_24h / judged, 1) if judged else 0.0
    last_any = newest_first[0].get("created_at") if newest_first else None
    firing: list[str] = []
    if streak >= k and attempts_24h > 0:
        firing.append(f"error_streak:{streak}>={k}")
    # Throttle is not silence. 441 SKIPPED_BUDGET with 0 sent is budget, not a dead lane.
    if silence and ok_24h == 0 and skip_24h == 0:
        firing.append(f"zero_non_error_{silence_hours()}h")
    thr = error_rate_threshold_pct()
    min_n = error_rate_min_n()
    if judged >= min_n and rate >= thr:
        firing.append(f"error_rate_24h:{rate}>={thr:g}")
    # Budget throttle with concurrent successes is expected cost-cap behavior — do not
    # fail the lane (that pinned platform health critical while deepseek still delivered).
    # Fail only when the lane produced zero successes and was entirely throttled.
    if skip_24h > 0 and ok_24h == 0:
        firing.append(f"budget_throttled:{skip_24h}/{attempts_24h}")
    return {
        "lane": lane,
        "ok": not firing,
        "firing": firing,
        "error_streak": streak,
        "streak_threshold": k,
        "non_error_24h": ok_24h,
        "attempts_24h": attempts_24h,
        "error_24h": err_24h,
        "skipped_budget_24h": skip_24h,
        "refused_24h": refused_24h,
        "error_rate_24h": rate,
        "last_any": last_any,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
    }


def _project_root():
    from pathlib import Path
    return Path(__file__).resolve().parents[2]


def oauth_lane_verdict(lane: str = OVERNIGHT_PROVIDER_LANE, *, path: Any = None) -> Optional[dict[str, Any]]:
    """The provider prober's own last verdict for ``lane`` (``data/runtime/oauth_lane_status.json``).

    LQ-20261107-1659. The overnight lane writes NO row when its provider refuses a target, so the
    RAW store can only say "zero non-error in 24h" — while the reason was already on disk in the
    prober's verdict (a 429 quota wall, not a broken scheduler or a target-selection bug). Reading
    it here is what lets the alert carry the cause instead of making the operator guess. Never
    raises; an absent/unreadable verdict is None, which reads as "no additional cause known".
    """
    from pathlib import Path

    p = Path(path) if path is not None else _project_root().joinpath(*OAUTH_LANE_STATUS_REL)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    row = doc.get(lane) if isinstance(doc, dict) else None
    return row if isinstance(row, dict) else None


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


def _lane_row(lanes: list[dict[str, Any]], lane: str) -> Optional[dict[str, Any]]:
    for r in lanes:
        if r.get("lane") == lane:
            return r
    return None


# Stall tracks PASS/CURRENT-quality, not mere presence. A THIN mint must not
# quiet this alarm. Threshold matches substantive_pct target (70%).
COVERAGE_STALL_SUBSTANTIVE_PCT = 0.70


def collect_coverage_stall(
    *,
    now: Optional[datetime] = None,
    deepseek_ok_24h: int = 0,
    thesis_current: Optional[int] = None,
    thesis_held: Optional[int] = None,
    thesis_substantive: Optional[int] = None,
    thesis_coverage: Optional[int] = None,
    research_leg: Optional[dict[str, Any]] = None,
    snap_path: Optional[Any] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Fire when research rows arrive and PASS-grade living thesis does not move.

    thesis_current is the PASS/CURRENT count (not row-exists). A 22/22 THIN
    mint with 5 PASS still fires. Target: substantive_pct >= 70.

    ``research_leg`` is the deepseek lane's row from this same report. LQ-20261107-1659: the
    alarm's premise is "research flowed, the brain did not learn", and ``deepseek_ok_24h >= 20``
    is a count of successes, not evidence that the leg is working — 33 successes beside 150
    failures is a lane that is 84% down, and then a flat thesis count is the *absence* of
    research, not a thesis-pipeline stall. When the leg is measurably broken the row is held
    (ok, no firing) and ``held_by`` names why; the deepseek lane carries that alarm on its own.
    """
    now = now or datetime.now(timezone.utc)
    from pathlib import Path
    root = _project_root()
    held_by: Optional[str] = None
    research_error_rate = None
    if research_leg is not None:
        try:
            attempts = int(research_leg.get("attempts_24h") or 0)
            rate = float(research_leg.get("error_rate_24h") or 0.0)
        except (AttributeError, TypeError, ValueError):
            attempts, rate = 0, 0.0
        research_error_rate = rate
        thr = error_rate_threshold_pct()
        if attempts >= error_rate_min_n() and rate >= thr:
            held_by = (f"research_lane_unhealthy:deepseek error_rate_24h={rate:g}>={thr:g} "
                       f"over {attempts} attempts")
    if snap_path is None:
        snap_path = root / "data" / "runtime" / "coverage_stall_snapshot.json"
    snap_path = Path(snap_path)
    if thesis_substantive is None and thesis_current is not None:
        thesis_substantive = thesis_current
    if thesis_held is None or thesis_substantive is None:
        try:
            from scripts.lib.cio_held_thesis_coverage import build_held_coverage_report
            cov = build_held_coverage_report(root=root)
            if thesis_held is None:
                thesis_held = int(cov.get("held_count") or 0)
            if thesis_substantive is None:
                thesis_substantive = int(
                    cov.get("substantive_count")
                    if cov.get("substantive_count") is not None
                    else (cov.get("current_count") or 0)
                )
            if thesis_coverage is None:
                thesis_coverage = int(cov.get("coverage_count") or cov.get("current_count") or 0)
            if thesis_current is None:
                thesis_current = thesis_substantive
        except Exception:
            try:
                p = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio/held_thesis_coverage_latest.json")
                if p.is_file():
                    import json
                    d = json.loads(p.read_text())
                    if thesis_held is None:
                        thesis_held = int(d.get("held_count") or 0)
                    if thesis_substantive is None:
                        thesis_substantive = int(
                            d.get("substantive_count")
                            if d.get("substantive_count") is not None
                            else (d.get("current_count") or 0)
                        )
                    if thesis_current is None:
                        thesis_current = thesis_substantive
                    if thesis_coverage is None:
                        thesis_coverage = int(d.get("coverage_count") or d.get("current_count") or 0)
            except Exception:
                pass
    if thesis_substantive is None:
        thesis_substantive = thesis_current
    prev = {}
    try:
        import json
        if snap_path.is_file():
            prev = json.loads(snap_path.read_text()) or {}
    except Exception:
        prev = {}
    prev_research = int(prev.get("deepseek_ok_24h") or 0)
    prev_thesis = prev.get("thesis_substantive")
    if prev_thesis is None:
        prev_thesis = prev.get("thesis_current")
    firing: list[str] = []
    threshold = max(1, int(COVERAGE_STALL_SUBSTANTIVE_PCT * (thesis_held or 0))) if thesis_held else 1
    if (
        held_by is None
        and deepseek_ok_24h >= 20
        and thesis_substantive is not None
        and thesis_held
        and thesis_substantive < threshold
        and (prev_thesis is None or int(prev_thesis) <= int(thesis_substantive))
        and deepseek_ok_24h >= prev_research
    ):
        firing.append(
            f"research_up_thesis_flat:deepseek_ok_24h={deepseek_ok_24h}"
            f",thesis_substantive={thesis_substantive}/{thesis_held}"
            f",coverage={thesis_coverage if thesis_coverage is not None else thesis_current}"
        )
    rec = {
        "lane": COVERAGE_STALL_LANE,
        "ok": not firing,
        "firing": firing,
        # Why a stall this metric plainly shows is NOT being charged to the thesis pipeline.
        # Carried on the row (and into the lane map) so /v3/health can say it, not just be quiet.
        "held_by": held_by,
        "research_error_rate_24h": research_error_rate,
        "error_streak": 0,
        "non_error_24h": deepseek_ok_24h,
        "attempts_24h": deepseek_ok_24h,
        "thesis_current": thesis_substantive,  # PASS count — do not treat as row-exists
        "thesis_substantive": thesis_substantive,
        "thesis_coverage": thesis_coverage,
        "thesis_held": thesis_held,
        "stall_threshold": threshold,
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
                "thesis_current": thesis_substantive,
                "thesis_substantive": thesis_substantive,
                "thesis_coverage": thesis_coverage,
                "thesis_held": thesis_held,
            }, indent=2) + "\n")
        except OSError:
            pass
    return rec


def collect_report(*, now: Optional[datetime] = None, cio_ask_health_reader=None) -> dict[str, Any]:
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
        row = evaluate_lane(
            OVERNIGHT_LANE,
            newest_first=newest,
            last_24h=last_24h,
            silence=True,
            now=now,
        )
        # LQ-20261107-1659: this lane writes no row when its provider refuses a target, so the RAW
        # store alone can only say "silence". The prober's verdict says WHY (a quota/rate wall is
        # not a broken scheduler and no re-run clears it). Attach it to the row the alert renders.
        verdict = oauth_lane_verdict()
        if verdict and verdict.get("ok") is False:
            row["provider_verdict"] = {
                "lane": verdict.get("lane") or OVERNIGHT_PROVIDER_LANE,
                "kind": verdict.get("kind"),
                "detail": verdict.get("detail"),
                "consec_fail": verdict.get("consec_fail"),
                "last_ok": verdict.get("last_ok"),
                "quota_exhausted": verdict.get("quota_exhausted"),
            }
        lanes.append(row)
    if os.getenv("RESEARCH_LANE_HEALTH_PIN", "1").strip().lower() not in {"0", "false", "off", "no"}:
        try:
            from scripts.lib.current_pin_integrity import collect_pin_report, collect_process_freshness
        except Exception:
            from current_pin_integrity import collect_pin_report, collect_process_freshness  # type: ignore
        lanes.append(collect_pin_report(now=now))
        lanes.append(collect_process_freshness(now=now))
    if os.getenv("RESEARCH_LANE_HEALTH_DRIVE", "1").strip().lower() not in {"0", "false", "off", "no"}:
        try:
            from scripts.lib.drive_sync_health import collect_drive_report
        except Exception:
            from drive_sync_health import collect_drive_report  # type: ignore
        lanes.append(collect_drive_report(now=now))
    if os.getenv("RESEARCH_LANE_HEALTH_COVERAGE_STALL", "1").strip().lower() not in {
        "0", "false", "off", "no"
    }:
        lanes.append(collect_coverage_stall(
            now=now,
            deepseek_ok_24h=_deepseek_ok(lanes),
            research_leg=_lane_row(lanes, "deepseek"),
        ))
    # Lane registry. This monitor learns its own lanes from the hardcoded tuples
    # above, so it can see a lane producing poorly but not a lane that produces
    # nothing because nobody told it the lane existed. That is how a lane
    # disabled on 2026-06-01 went unreported for three months. The registry is
    # the declaration; this appends its verdicts as one more lane row, in the
    # same shape as every other collector. It EXTENDS this monitor rather than
    # standing up a second one.
    if os.getenv("RESEARCH_LANE_HEALTH_REGISTRY", "1").strip().lower() not in {
        "0", "false", "off", "no"
    }:
        try:
            from scripts.lib.lane_registry import collect_lane_registry_report
        except Exception:
            from lane_registry import collect_lane_registry_report  # type: ignore
        lanes.append(collect_lane_registry_report(now=now))
    # Search providers. This monitor had zero lanes covering search: measured
    # 2026-08-30 the SearXNG pool returned ten results of which every one came
    # from bing, with duckduckgo and startpage CAPTCHA-suspended, and nothing
    # reported it. Off by default in CI (no local SearXNG to probe).
    if os.getenv("RESEARCH_LANE_HEALTH_SEARCH", "1").strip().lower() not in {
        "0", "false", "off", "no"
    }:
        try:
            from scripts.lib.search_health import collect_search_health
        except Exception:
            from search_health import collect_search_health  # type: ignore
        lanes.append(collect_search_health(now=now))
    try:
        from scripts.lib.identity_health import collect_identity_health
    except Exception:
        try:
            from lib.identity_health import collect_identity_health  # type: ignore
        except Exception:
            collect_identity_health = None                            # type: ignore
    if collect_identity_health is not None:
        # The GUID spine had no custodian at all until 2026-09-06: no freshness
        # check, no coverage regression alarm, and build_catalyst_graph had no
        # scheduler. Deterministic only — no model runs in this lane.
        lanes.append(collect_identity_health(now=now))
    # The CIO Hermes research queue (operator questions, plan research). Until 2026-09-14 no
    # lane read it: 62% of its requests failed in a week while every lane here was green.
    if os.getenv("RESEARCH_LANE_HEALTH_CIO_HERMES", "1").strip().lower() not in {"0", "false", "off", "no"}:
        try:
            from scripts.lib.cio_hermes_queue_health import collect_cio_hermes_queue_health
        except Exception:
            from cio_hermes_queue_health import collect_cio_hermes_queue_health  # type: ignore
        lanes.append(collect_cio_hermes_queue_health(now=now))
    # Ask lifecycle: transport success cannot stand in for hourly checks,
    # memory synchronization, canonical readback or delivery. The injectable
    # reader lets integration tests exercise registration without any host IO.
    if cio_ask_health_reader is None:
        from scripts.lib.cio_ask_lifecycle_health import collect_cio_ask_lifecycle_health
        cio_ask_health_reader = collect_cio_ask_lifecycle_health
    try:
        lanes.append(cio_ask_health_reader(now=now))
    except Exception:
        from scripts.lib.cio_ask_lifecycle_health import unavailable
        lanes.append(unavailable(now=now, code="collector_unavailable"))
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
