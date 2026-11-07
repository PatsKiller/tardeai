"""ANCHOR: RUN_QUALITY_20261106 — run QUALITY grade per lane for /ops/jobs: not "did it run" but "did it run live and produce what it should".

Operator 2026-11-06: "We have information that something ran, but it's not quantifiable. How good was it? Did it produce
what it was needed? Is it degraded? Is it as designed? ... Just saying it ran is a false positive. It may have ran
garbage in, garbage out."

One grade per lane (``quality.grade``), with one plain-English line per reason (``quality.reasons``) and the checks
behind it (``quality.checks``: each ``{"result": "pass" | "fail" | "unknown", "value": ...}``):

* ``FAILED``   — the last run errored or exited non-zero.
* ``NOT_LIVE`` — the last run was a dry run, shadow, rehearsal or skip (``sub`` says which and why), or the lane is not
                 active. Never OK.
* ``EMPTY``    — ran live and ok but produced nothing: its output was not written by this run, or its item count is 0.
* ``DEGRADED`` — ran live and wrote output, but its receipt reports partial/fallback/gaps/errors, its item count fell
                 more than half below its own median, its duration is far outside its history, or an input freshness /
                 data plausibility check that maps to it is failing.
* ``UNPROVEN`` — ran live and ok but nothing lets us check its output (say what is missing), or no run is recorded.
* ``GOOD``     — live, ok, output written by this run, count within its band, no degradation flags.

Separately, ``quality.as_designed`` (``False`` + ``design_issues``) flags a lane whose claimed state disagrees with what
ran: registry stage cutover / n8n live but the last n8n run was a dry run or a skip, contract stage ≠ registry stage, a
shadow dry run still firing after cutover, two schedulers racing for one lock, or a scheduled slot that was missed.

Read-only. Sources (all optional; a missing one makes its check ``unknown``, never ``pass``):
``config/lane_registry.json`` (output_signal, stage, dispatch, freshness_contracts), ``config/n8n_health_contracts.json``
(stage, baseline duration, expected_output), the lane's own receipt (``data/runtime/<lane>_last.json`` or its declared
JSON output), the n8n coordination ledger's RunReceipt@v3 fields (output mtime before/after, produced_count, duration),
``data/runtime/data_plausibility_last_run.json``, open ``data/runtime/supervisor_breaches.jsonl`` STALE_OUTPUT /
INPUT_STARVATION rows, and ``data/runtime/run_quality_history.jsonl`` (per-run counts appended by
``scripts/run_quality_snapshot.py --apply``; the only writer of that file).

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import statistics

GRADES = ("GOOD", "DEGRADED", "EMPTY", "FAILED", "NOT_LIVE", "UNPROVEN")
HISTORY_FILE = "data/runtime/run_quality_history.jsonl"
HISTORY_SCHEMA = "RunQualitySample@v1"
LEDGER_DAYS = 10
LEDGER_PER_LANE = 30
HISTORY_TAIL_BYTES = 8 * 1024 * 1024
BREACH_TAIL_BYTES = 4 * 1024 * 1024
BREACH_OPEN_HOURS = 72
#: A file written up to this long before the run's recorded start still counts as written by this run (clock skew).
WRITE_TOLERANCE = timedelta(seconds=5)
#: A receipt belongs to the graded run when it started within this of the run's start.
SAME_RUN = timedelta(minutes=2)
MIN_COUNT_HISTORY = 3
MIN_DURATION_HISTORY = 5
COUNT_DROP = 0.5
DRY_MODES = {"dry_run", "dry-run", "dryrun", "preflight", "rehearsal", "plan"}
SHADOW_MODES = {"shadow", "shadow_only", "shadow-only"}
SKIP_STATUSES = {"skipped", "skip", "noop", "no_op", "no-op", "not_due", "market_closed", "closed"}
FAIL_STATUSES = {"failed", "fail", "error", "run_failed", "crashed", "timeout", "timed_out"}
PARTIAL_STATUSES = {"partial", "degraded", "warn", "warning", "fallback", "incomplete", "unhealthy", "stale"}
_FAILED_RESULTS = {"failed", "timed_out", "refused"}
_INACTIVE = {"PAUSED", "RETIRED", "NEVER_SCHEDULED", "DISABLED"}
#: Ordered: the first numeric key present in the receipt (top level, then summary) is the lane's item count.
COUNT_KEYS = ("produced_count", "written", "rows_written", "rows", "items", "inserted", "upserted", "updated",
              "saved", "recorded", "classified", "scored", "checked", "symbols", "processed", "fetched", "candidates",
              "staged", "results", "count", "total", "universe")
_ERROR_KEY = re.compile(r"(^|_)(errors?|failures?|failed|rejected|exceptions?)$")
_GAP_KEY = re.compile(r"(^|_)(gaps?|missing)$")
_BENIGN_SKIP = re.compile(r"^(already|no|not|nothing|unchanged|duplicate|up_to_date|undecided|cached|fresh)")
_SKIP_REASON = {"flock_held": "another copy of the job still held its lock",
                "lock_held": "another copy of the job still held its lock",
                "market_closed": "the market was closed", "not_trading_day": "it was not a trading day"}


def _at(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _ago(when: datetime | None, now: datetime) -> str:
    if when is None:
        return "at an unknown time"
    secs = max(0, (now - when).total_seconds())
    if secs < 5400:
        return f"{int(secs // 60)} min ago"
    if secs < 172800:
        return f"{secs / 3600:.0f} h ago"
    return f"{secs / 86400:.0f} d ago"


def _check(result, value=None, detail=None):
    out = {"result": result, "value": value}
    if detail:
        out["detail"] = detail
    return out


# ── receipt reading ───────────────────────────────────────────────────────────────────────────────────────────────

def receipt_mode(receipt: dict) -> str:
    """live | dry_run | shadow — from mode, run_mode, dry_run flags (a receipt that does not say is live)."""
    modes = {str(receipt.get(k) or "").lower() for k in ("mode", "run_mode")}
    summary = receipt.get("summary") if isinstance(receipt.get("summary"), dict) else {}
    if receipt.get("dry_run") is True or summary.get("dry_run") is True or modes & DRY_MODES:
        return "dry_run"
    if modes & SHADOW_MODES or receipt.get("shadow") is True or summary.get("shadow") is True:
        return "shadow"
    return "live"


def receipt_start(receipt: dict):
    """The run's start: started_at (or run_ts_utc), else finish minus its stated duration; never a bare as_of."""
    start = next((t for t in (_at(receipt.get(k)) for k in ("started_at", "run_ts_utc")) if t), None)
    if start is None:
        finish, secs = receipt_finish(receipt), _num(receipt.get("seconds", receipt.get("duration_s")))
        start = finish - timedelta(seconds=secs) if finish and secs is not None and secs >= 0 else None
    return start


def receipt_finish(receipt: dict):
    return next((t for t in (_at(receipt.get(k)) for k in ("finished_at", "ended_at", "completed_at", "ok_at",
                                                              "last_ok_at", "as_of")) if t), None)


def receipt_status(receipt: dict) -> str:
    """ok | failed | skipped | unknown, from the receipt's own words."""
    summary = receipt.get("summary") if isinstance(receipt.get("summary"), dict) else {}
    status = str(receipt.get("status") or receipt.get("overall_status") or receipt.get("state") or "").lower()
    code = receipt.get("exit", receipt.get("exit_code"))
    if status in FAIL_STATUSES or receipt.get("ok") is False or (type(code) is int and code not in (0, 75)):
        return "failed"
    if status in SKIP_STATUSES or (type(code) is int and code == 75) or str(summary.get("status") or "").lower() in SKIP_STATUSES:
        return "skipped"
    if status in {"ok", "success", "succeeded", "done", "run_done", "reconciled", "green"} or receipt.get("ok") is True \
            or code == 0 or receipt.get("ok_at") or receipt.get("last_ok_at") or status in PARTIAL_STATUSES:
        return "ok"
    return "unknown"


def skip_reason(receipt: dict | None, run: dict | None = None) -> str | None:
    texts = []
    if run and run.get("reason"):
        texts.append(str(run["reason"]))
    for doc in (receipt or {}, (receipt or {}).get("summary") if isinstance((receipt or {}).get("summary"), dict) else {}):
        for key in ("skip_reason", "skipped_reason", "no_op_reason", "shadow_reason", "empty_reason", "reason"):
            if doc.get(key) and isinstance(doc[key], str):
                texts.append(doc[key])
    for text in texts:
        return _SKIP_REASON.get(text.strip().lower(), text.strip()[:200])
    return None


def item_count(receipt: dict | None) -> tuple[int | float | None, str | None]:
    """(count, key used). Top-level produced_count first, then the summary's count-like keys in COUNT_KEYS order."""
    if not receipt:
        return None, None
    if _num(receipt.get("produced_count")) is not None:
        return receipt["produced_count"], "produced_count"
    summary = receipt.get("summary") if isinstance(receipt.get("summary"), dict) else {}
    for source, doc in (("summary", summary), ("receipt", receipt)):
        for key in COUNT_KEYS:
            value = doc.get(key)
            if _num(value) is not None:
                return value, f"{source}.{key}"
            if key in {"results", "rows", "items", "candidates"} and isinstance(value, list):
                return len(value), f"{source}.{key}[]"
    return None, None


def receipt_flags(receipt: dict | None, count=None) -> list[str]:
    """Plain-English degradation flags the receipt states about its own run (partial, fallback, gaps, errors, ...)."""
    if not receipt:
        return []
    flags = []
    summary = receipt.get("summary") if isinstance(receipt.get("summary"), dict) else {}

    def truthy(v):
        return (v is True) or (_num(v) is not None and v > 0) or (isinstance(v, (list, dict)) and len(v) > 0) or \
            (isinstance(v, str) and v.strip() not in {"", "0", "none", "null", "false"})

    for where, doc in (("receipt", receipt), ("summary", summary)):
        for key in ("status", "overall_status", "verdict"):
            if str(doc.get(key) or "").lower() in PARTIAL_STATUSES:
                flags.append(f"{where} {key} is {str(doc[key]).upper()}")
        for key, value in doc.items():
            k = str(key).lower()
            if k in {"consecutive_failures", "worker_failures"} and where == "receipt" and k == "consecutive_failures":
                continue
            if k.endswith("_at") or k.endswith("_ts") or k in {"skipped_reasons", "empty_reason", "error_budget"}:
                continue
            if _ERROR_KEY.search(k) and truthy(value):
                shown = value if _num(value) is not None else (len(value) if isinstance(value, (list, dict)) else "set")
                flags.append(f"{where} reports {key} = {shown}")
            elif "fallback" in k and truthy(value):
                flags.append(f"{where} reports a fallback ({key} = {value if _num(value) is not None or value is True else 'set'})")
            elif _GAP_KEY.search(k) and truthy(value):
                shown = value if _num(value) is not None else (len(value) if isinstance(value, (list, dict)) else "set")
                flags.append(f"{where} reports {key} = {shown}")
            elif k in {"unread", "stale", "stale_inputs", "degraded", "partial", "warnings"} and truthy(value):
                shown = value if _num(value) is not None or value is True else len(value) if isinstance(value, (list, dict)) else "set"
                flags.append(f"{where} reports {key} = {shown}")
    if receipt.get("receipt_complete") is False:
        flags.append("receipt says it is incomplete")
    skipped = _num(summary.get("skipped", receipt.get("skipped")))
    reasons = receipt.get("skipped_reasons") if isinstance(receipt.get("skipped_reasons"), dict) else {}
    skipped_sum = sum(v for v in reasons.values() if _num(v)) if reasons else 0
    skipped = skipped if skipped is not None else (skipped_sum or None)
    benign = bool(reasons) and all(_BENIGN_SKIP.search(str(k).lower()) or not _num(v) for k, v in reasons.items())
    if skipped and count is not None and skipped > count and not benign:
        flags.append(f"skipped {skipped:g} items, more than it produced ({count:g})")
    return list(dict.fromkeys(flags))


# ── grading (pure) ────────────────────────────────────────────────────────────────────────────────────────────────

def _median(values):
    values = [v for v in values if _num(v) is not None]
    return statistics.median(values) if values else None


def _latest_finished_live(row: dict) -> dict | None:
    for run in row.get("runs") or []:  # newest first
        if run.get("mode") == "live" and run.get("result") not in {"running", "requested"}:
            return run
    last = row.get("last_run")
    return last if last and last.get("mode") == "live" and last.get("result") not in {"running", "requested"} else None


def grade(row: dict, lane: dict, evidence: dict, *, now: datetime) -> dict:
    """The quality of one lane's latest run. ``row`` is the jobs_history row; ``evidence`` comes from ``gather``."""
    reasons, checks, design = [], {}, []
    state = lane.get("state") or row.get("state") or "UNKNOWN"
    signal = lane.get("output_signal") or {}
    kind = signal.get("kind") or "none"
    scheduler = lane.get("scheduler") or {}
    dispatch = lane.get("dispatch") or {}
    stage = scheduler.get("stage")
    contract = evidence.get("contract") or {}
    receipt = evidence.get("receipt")
    ledger = evidence.get("ledger") or []  # oldest first
    live_ledger = [r for r in ledger if r.get("mode") == "live"]
    dry_ledger = [r for r in ledger if r.get("mode") != "live"]

    def result(grade_, sub=None, headline=None, graded=None, count=None):
        if contract.get("stage") and stage and contract["stage"] != stage:
            design.append(f"registry stage is {stage} but its n8n health contract says {contract['stage']}")
        if row.get("status") in {"missed", "late"} and state == "ACTIVE":
            design.append(f"scheduled but {row['status']}: {row.get('status_reason') or 'no run in its slot'}")
        if stage == "cutover" and dry_ledger and dry_ledger[-1]["started"] and now - dry_ledger[-1]["started"] < timedelta(days=3):
            design.append(f"stage is cutover but a dry-run shadow of it still fires (last {_ago(dry_ledger[-1]['started'], now)})")
        skips = [r for r in live_ledger if r.get("state") == "RUN_SKIPPED_LOCK"]
        if skips and scheduler.get("kind") not in {"n8n", None} and dispatch.get("mode") == "live":
            design.append(f"both {scheduler.get('kind')} and n8n fire this lane; {len(skips)} of its last "
                          f"{len(live_ledger)} n8n runs were skipped because the other held the lock")
        issues = list(dict.fromkeys(design))
        checks["as_designed"] = _check("fail" if issues else ("pass" if state == "ACTIVE" else "unknown"),
                                       len(issues), "; ".join(issues) or None)
        out = {"grade": grade_, "sub": sub, "headline": headline or (reasons[0] if reasons else grade_),
               "reasons": reasons + [f"Not as designed: {d}" for d in issues],
               "checks": checks, "as_designed": (not issues) if state == "ACTIVE" else None, "design_issues": issues,
               "graded_run": graded, "count": count}
        return out

    # 0. inactive lanes are never "OK"
    if state in _INACTIVE or state != "ACTIVE":
        reasons.append(f"Job is {state.lower().replace('_', ' ')}; nothing is expected to run"
                       + (f" ({lane.get('state_reason')[:160]})" if lane.get("state_reason") else ""))
        checks["ran_live"] = _check("unknown", state)
        return result("NOT_LIVE", "inactive")

    # 1. pick the run to grade: the newest finished live run, or the lane's own receipt if that is newer
    run = _latest_finished_live(row)
    run_start = _at((run or {}).get("started_at")) or _at((run or {}).get("finished_at"))
    r_mode = receipt_mode(receipt) if receipt else None
    r_start = receipt_start(receipt) if receipt else None
    r_finish = receipt_finish(receipt) if receipt else None
    graded = None
    r_when = r_start or r_finish
    use_receipt = bool(receipt) and r_mode == "live" and r_when is not None and (
        run is None or run_start is None or run.get("source") == "run receipt (last run only)"
        or r_when > run_start + SAME_RUN)
    if run is not None and not use_receipt:
        graded = {"source": run.get("source"), "started_at": run.get("started_at"), "finished_at": run.get("finished_at"),
                  "mode": "live", "result": run.get("result"), "run_id": run.get("run_id")}
    elif use_receipt:
        status = receipt_status(receipt)
        res = {"ok": "succeeded", "failed": "failed", "skipped": "skipped", "unknown": "unknown"}[status]
        graded = {"source": "lane receipt", "started_at": _iso(r_start), "finished_at": _iso(r_finish), "mode": "live",
                  "result": res, "run_id": receipt.get("run_id")}
        run_start = r_when
    # the receipt describes the graded run when it started near it (or finished inside it)
    same_receipt = bool(receipt) and r_mode == "live" and run_start is not None and (
        use_receipt or (r_start is not None and abs(r_start - run_start) <= SAME_RUN)
        or (r_start is None and r_finish is not None and r_finish >= run_start - WRITE_TOLERANCE))

    # 2. nothing live at all
    if graded is None:
        dry_seen = (receipt and r_mode in {"dry_run", "shadow"}) or dry_ledger or \
            any(r.get("mode") != "live" for r in row.get("runs") or []) or dispatch.get("mode") == "dry_run"
        if dry_seen:
            sub = "shadow" if receipt and r_mode == "shadow" else "dry_run"
            when = r_start if receipt and r_mode in {"dry_run", "shadow"} else (dry_ledger[-1]["started"] if dry_ledger else None)
            reasons.append(f"Only {'shadow' if sub == 'shadow' else 'dry'} runs are recorded (last {_ago(when, now)}); "
                           "a dry run writes nothing, so nothing was produced")
            if stage in {"cutover"} or dispatch.get("mode") == "live":
                design.append(f"registry says it runs live (stage {stage or '-'}, n8n dispatch {dispatch.get('mode') or '-'}) "
                              "but no live run is recorded")
            checks["ran_live"] = _check("fail", sub)
            return result("NOT_LIVE", sub)
        output_at = evidence.get("output_at")
        reasons.append("No run of this job is recorded (no ledger row, wrapper journal entry, unit run or run receipt)"
                       + (f"; its output file was last written {_ago(output_at, now)}, but a file time does not prove a "
                          "run or what it produced" if output_at else "; and no output file was found")
                       + (f" ({row['history_gap']})" if row.get("history_gap") else ""))
        checks["ran_live"] = _check("unknown", None)
        checks["output_written"] = _check("unknown", _iso(output_at), "file write time only")
        return result("UNPROVEN", "no_run_record")

    when = _at(graded["finished_at"]) or _at(graded["started_at"])
    checks["ran_live"] = _check("pass", graded["source"])
    led = next((r for r in reversed(live_ledger) if graded.get("run_id") and r.get("run_id") == graded["run_id"]), None)
    # 3a. the n8n executor failed an exit-0 run for its OUTPUT: that is EMPTY / UNPROVEN, not a crash
    if led and led.get("state") == "RUN_FAILED" and led.get("reason") in {"empty_output", "output_unverifiable"} \
            and (run or {}).get("exit_code") in (0, None):
        checks["run_result"] = _check("fail", led["reason"], led.get("why"))
        if led["reason"] == "empty_output":
            reasons.append(f"Ran live {_ago(when, now)} and exited 0, but the n8n executor found it produced nothing "
                           "its contract requires (empty_output)")
            checks["item_count"] = _check("fail", led.get("produced"), "n8n output_verdict.produced_count")
            return result("EMPTY", "unexpected", graded=graded)
        reasons.append(f"Ran live {_ago(when, now)} and exited 0, but the n8n executor could not verify its output "
                       f"(output_unverifiable: {led.get('why') or 'no reason given'})")
        checks["output_written"] = _check("unknown", None, led.get("why"))
        return result("UNPROVEN", "output_unverifiable", graded=graded)
    # 3. failed
    if graded["result"] in _FAILED_RESULTS or graded["result"] == "failed" or (
            same_receipt and receipt_status(receipt) == "failed"):
        why = (run or {}).get("reason") if not use_receipt else None
        why = why or (receipt or {}).get("error") or (receipt or {}).get("reason") if same_receipt or use_receipt else why
        code = (run or {}).get("exit_code") if not use_receipt else (receipt or {}).get("exit", (receipt or {}).get("exit_code"))
        streak = _num((receipt or {}).get("consecutive_failures")) if (same_receipt or use_receipt) else None
        reasons.append(f"Last live run {_ago(when, now)} failed"
                       + (f" (exit {code})" if type(code) is int else "")
                       + (f": {str(why)[:200]}" if why else (" (its receipt says status failed)" if use_receipt or same_receipt else ""))
                       + (f"; {streak:g} failures in a row" if streak and streak > 1 else ""))
        checks["run_result"] = _check("fail", graded["result"])
        return result("FAILED", None, graded=graded)
    # 4. skipped / shadow inside a live slot
    receipt_skip = same_receipt and receipt_status(receipt) == "skipped"
    if graded["result"] in {"skipped_lock", "skipped"} or receipt_skip:
        why = skip_reason(receipt if (same_receipt or use_receipt) else None, run if not use_receipt else None)
        reasons.append(f"Last live slot {_ago(when, now)} was skipped, so it did no work"
                       + (f": {why}" if why else " (the record does not say why)"))
        if receipt and r_mode == "live" and r_start and run_start and graded["source"] != "lane receipt" \
                and receipt_status(receipt) == "ok" and r_finish and r_finish >= run_start - SAME_RUN:
            count, key = item_count(receipt)
            reasons.append(f"Its own receipt shows another scheduler's live run started {_ago(r_start, now)} and finished ok"
                           + (f" ({key} = {count:g})" if count is not None else ""))
        consecutive = 0
        for r in reversed(live_ledger):
            if r.get("state") != "RUN_SKIPPED_LOCK":
                break
            consecutive += 1
        if consecutive >= 2:
            reasons.append(f"The last {consecutive} n8n live slots were all skipped")
        if stage == "cutover" or (scheduler.get("kind") == "n8n" and dispatch.get("mode") == "live"):
            design.append("n8n is the scheduler of record but its last live slot did nothing")
        checks["ran_live"] = _check("fail", "skipped", why)
        checks["run_result"] = _check("fail", graded["result"])
        return result("NOT_LIVE", "skipped", graded=graded)
    if same_receipt and r_mode == "shadow":
        reasons.append(f"Last run {_ago(when, now)} ran in shadow mode; it wrote nothing live")
        checks["ran_live"] = _check("fail", "shadow")
        return result("NOT_LIVE", "shadow", graded=graded)
    checks["run_result"] = _check("pass" if graded["result"] == "succeeded" else "unknown", graded["result"])

    # 5. output written by this run?
    written, written_detail = None, None
    output_at = evidence.get("output_at")
    receipt_is_output = bool(signal.get("path")) and evidence.get("receipt_path") == signal.get("path")
    if led and _num(led.get("mtime_after")) and _num(led.get("mtime_before")) is not None:
        written = led["mtime_after"] > led["mtime_before"]
        written_detail = "n8n receipt: output file time before vs after the run"
    elif kind == "json_key" and same_receipt and receipt_is_output:
        key_at = _at(receipt.get(signal.get("key"))) if signal.get("key") else None
        written = key_at is not None and key_at >= run_start - WRITE_TOLERANCE
        written_detail = f"receipt key {signal.get('key')} = {_iso(key_at) or 'absent'}"
    elif kind in {"file_mtime", "json_key"} and output_at is not None and run_start is not None:
        written = output_at >= run_start - WRITE_TOLERANCE
        written_detail = f"output file written {_iso(output_at)}"
    elif kind in {"file_mtime", "json_key"} and output_at is None and signal.get("path"):
        written = False
        written_detail = "declared output file is missing"
    if written is None:
        missing = {"none": "the registry declares no output signal for this job",
                   "db_max": f"its output is a database column ({signal.get('table')}.{signal.get('column')}) "
                             "this page does not query"}.get(kind, f"output signal kind {kind} cannot be read here")
        checks["output_written"] = _check("unknown", None, missing)
    else:
        checks["output_written"] = _check("pass" if written else "fail", written, written_detail)

    # 6. item count
    count, count_key = None, None
    if same_receipt:
        count, count_key = item_count(receipt)
    if count is None and led and _num(led.get("produced")) is not None:
        count, count_key = led["produced"], "n8n output_verdict.produced_count"
    past = [h for h in evidence.get("history") or [] if h.get("count_key") == count_key and _num(h.get("count")) is not None
            and (_at(h.get("run_started_at")) or now) < (run_start or now) - SAME_RUN]
    if count_key == "n8n output_verdict.produced_count":
        past = [{"count": r["produced"]} for r in live_ledger if r is not led and _num(r.get("produced")) is not None
                and r.get("state") == "RUN_DONE"]
    median = _median([h["count"] for h in past])
    count_info = {"value": count, "key": count_key, "median": median, "history_n": len(past)}
    allowed = set((contract.get("expected_output") or {}).get("empty_allowed_reasons") or [])
    empty_reason = (receipt or {}).get("empty_reason") if same_receipt else None
    checks["item_count"] = _check("unknown" if count is None else ("fail" if count == 0 else "pass"), count, count_key)

    if written is False:
        reasons.append(f"Ran live {_ago(when, now)} and exited ok, but its output was not written by that run"
                       + (f" ({written_detail})" if written_detail else ""))
        return result("EMPTY", "not_written", graded=graded, count=count_info)
    if count == 0:
        idle = bool(empty_reason) and (empty_reason in allowed or _BENIGN_SKIP.search(str(empty_reason).lower()))
        reasons.append(f"Ran live {_ago(when, now)} and exited ok but produced nothing ({count_key} = 0"
                       + (f"; receipt says: {empty_reason}" if empty_reason else "; the receipt does not say why") + ")")
        return result("EMPTY", "nothing_due" if idle else "unexpected", graded=graded, count=count_info)
    if same_receipt is False and receipt and receipt_is_output and r_mode == "live" and r_start and run_start \
            and r_start < run_start - SAME_RUN and written is None:
        reasons.append(f"Ran live {_ago(when, now)} but its receipt is from an earlier run ({_ago(r_start, now)})")
        return result("EMPTY", "not_written", graded=graded, count=count_info)

    # 7. degradation
    degraded = []
    flags = receipt_flags(receipt, count) if same_receipt else []
    checks["receipt_flags"] = _check("fail" if flags else ("pass" if same_receipt else "unknown"), len(flags),
                                     "; ".join(flags) or None)
    degraded += flags
    if count is not None and median and len(past) >= MIN_COUNT_HISTORY and count < COUNT_DROP * median:
        degraded.append(f"item count {count:g} is {100 * (1 - count / median):.0f}% below its median {median:g} "
                        f"over {len(past)} earlier runs ({count_key})")
        checks["count_vs_history"] = _check("fail", count, f"median {median:g} over {len(past)} runs")
    else:
        checks["count_vs_history"] = _check("unknown" if count is None or len(past) < MIN_COUNT_HISTORY else "pass",
                                            count, f"{len(past)} earlier runs with {count_key}" if count_key else None)
    duration = _num((run or {}).get("duration_s")) if not use_receipt else None
    if duration is None and same_receipt and r_start and r_finish and r_finish >= r_start:
        duration = round((r_finish - r_start).total_seconds(), 3)
    durations = [r["duration_s"] for r in live_ledger if r is not led and r.get("state") == "RUN_DONE"
                 and _num(r.get("duration_s")) is not None]
    durations += [h["duration_s"] for h in evidence.get("history") or [] if _num(h.get("duration_s")) is not None
                  and (_at(h.get("run_started_at")) or now) < (run_start or now) - SAME_RUN]
    if not durations:
        durations = [r["duration_s"] for r in (row.get("runs") or [])[1:] if r.get("result") == "succeeded"
                     and _num(r.get("duration_s")) is not None]
    dmed = _median(durations)
    limit = _num(((contract.get("baseline") or {}).get("duration_degraded_above_s")))
    dur_flag = None
    if duration is not None and dmed is not None and len(durations) >= MIN_DURATION_HISTORY:
        if duration > max(3 * dmed, dmed + 60):
            dur_flag = f"took {duration:.0f} s, far above its median {dmed:.0f} s"
        elif dmed >= 30 and duration < dmed / 10:
            dur_flag = f"took {duration:.1f} s, far below its median {dmed:.0f} s (did it do its work?)"
    if dur_flag is None and duration is not None and limit and duration > limit:
        dur_flag = f"took {duration:.0f} s, above its contract's {limit:.0f} s degraded limit"
    checks["duration_vs_history"] = _check("fail" if dur_flag else ("unknown" if duration is None or
                                           (dmed is None and not limit) else "pass"), duration,
                                           dur_flag or (f"median {dmed:.1f} s over {len(durations)} runs" if dmed is not None else None))
    if dur_flag:
        degraded.append(dur_flag)
    fresh = evidence.get("freshness") or []
    checks["input_freshness"] = _check("fail" if fresh else "unknown" if not evidence.get("freshness_known") else "pass",
                                       len(fresh), "; ".join(fresh) or None)
    degraded += fresh
    plaus = evidence.get("plausibility") or []
    checks["data_plausibility"] = _check("fail" if plaus else ("pass" if evidence.get("plausibility_known") else "unknown"),
                                         len(plaus), "; ".join(plaus) or None)
    degraded += plaus
    if degraded:
        reasons.append(f"Ran live {_ago(when, now)} and wrote output, but: " + degraded[0])
        reasons += [f"Also: {d}" for d in degraded[1:]]
        return result("DEGRADED", None, graded=graded, count=count_info)

    # 8. unproven vs good
    if written is None and count is None:
        reasons.append(f"Ran live {_ago(when, now)} and exited ok, but nothing lets us check what it produced: "
                       + checks["output_written"]["detail"] + "; and its receipt reports no item count")
        return result("UNPROVEN", "output_unverifiable", graded=graded, count=count_info)
    if receipt_is_output and count is None:
        reasons.append(f"Ran live {_ago(when, now)} and exited ok, but its only output signal is its own receipt and the "
                       "receipt reports no item count, so what it produced is unproven")
        return result("UNPROVEN", "output_unverifiable", graded=graded, count=count_info)
    if graded["result"] != "succeeded":
        reasons.append(f"Ran live {_ago(when, now)}, but its record does not state success or failure, so the run is unproven"
                       + (f" (it reports {count_key} = {count:g})" if count is not None else ""))
        return result("UNPROVEN", "result_unknown", graded=graded, count=count_info)
    parts = [f"Ran live {_ago(when, now)}"]
    if written:
        parts.append("wrote its output")
    if count is not None:
        band = f" (median {median:g})" if median is not None and len(past) >= MIN_COUNT_HISTORY else ""
        parts.append(f"produced {count:g} by {count_key}{band}")
    else:
        parts.append("no item count reported")
    reasons.append(", ".join(parts))
    return result("GOOD", None, graded=graded, count=count_info)


# ── evidence (read-only) ──────────────────────────────────────────────────────────────────────────────────────────

def _read_json(path: Path, limit=512 * 1024):
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
        doc = json.loads(raw) if len(raw) <= limit else None
        return doc if isinstance(doc, dict) else None
    except (OSError, ValueError):
        return None


def _tail_jsonl(path: Path, limit: int) -> list[dict]:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            start = max(0, size - limit)
            stream.seek(start)
            raw = stream.read(limit)
    except OSError:
        return []
    lines = raw.split(b"\n")[1:] if start else raw.split(b"\n")
    out = []
    for line in lines:
        try:
            row = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def receipt_candidates(lane: dict) -> list[str]:
    lane_id = str(lane.get("lane_id") or lane.get("id") or "")
    signal = lane.get("output_signal") or {}
    out = []
    if str(signal.get("path") or "").endswith(".json"):
        out.append(str(signal["path"]))
    out += [f"data/runtime/{lane_id}_last.json", f"data/runtime/{lane_id.replace('-', '_')}_last.json"]
    return list(dict.fromkeys(out))


def read_receipt(lane: dict, root: Path) -> tuple[dict | None, str | None]:
    """The lane's own last-run receipt: its declared JSON output if that looks like a run receipt, else <lane>_last.json."""
    base = root.resolve()
    allowed = (base / "data", base / "logs")
    for rel in receipt_candidates(lane):
        path = (base / rel).resolve()
        if not any(path.is_relative_to(a) for a in allowed):
            continue
        doc = _read_json(path)
        if doc and any(k in doc for k in ("started_at", "finished_at", "ok_at", "last_ok_at", "status", "mode", "exit",
                                          "summary", "produced_count", "overall_status", "as_of")):
            return doc, rel
    return None, None


def read_ledger_quality(path: Path, now: datetime) -> dict[str, list[dict]]:
    """Per lane, its newest runs with the RunReceipt@v3 quality fields (oldest first). ``mode=ro``."""
    out: dict[str, list[dict]] = defaultdict(list)
    if not path.is_file():
        return out
    since = (now - timedelta(days=LEDGER_DAYS)).isoformat()
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        try:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
            if "receipt_json" not in cols:
                return out
            rows = conn.execute(
                "SELECT lane_id, run_id, mode, state, started_at, requested_at, duration_s, produced, mb, ma, reason, why "
                "FROM (SELECT lane_id, run_id, mode, state, started_at, requested_at, duration_s, "
                "receipt_json ->> '$.output_verdict.produced_count' AS produced, "
                "receipt_json ->> '$.output_signal_mtime_before' AS mb, receipt_json ->> '$.output_signal_mtime_after' AS ma, "
                "receipt_json ->> '$.reason' AS reason, receipt_json ->> '$.output_verdict.why' AS why, "
                "row_number() OVER (PARTITION BY lane_id ORDER BY requested_at DESC) AS rn "
                "FROM runs WHERE requested_at >= ?) WHERE rn <= ? ORDER BY requested_at", (since, LEDGER_PER_LANE)).fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return out
    for lane_id, run_id, mode, state, started, requested, duration, produced, mb, ma, reason, why in rows:
        out[lane_id].append({"run_id": run_id, "mode": "live" if mode == "live" else "dry_run", "state": state,
                             "started": _at(started) or _at(requested), "duration_s": _num(duration),
                             "produced": _num(produced), "mtime_before": _num(mb), "mtime_after": _num(ma),
                             "reason": reason, "why": why})
    return out


def read_breaches(path: Path, registry: dict, now: datetime) -> dict[str, list[str]]:
    """Open STALE_OUTPUT / INPUT_STARVATION breaches (newest row per lane+kind+contract), mapped to registry lanes."""
    by_key = {str(c.get("key")): str(c.get("lane_id")) for c in registry.get("freshness_contracts") or []
              if isinstance(c, dict) and c.get("lane_id")}
    latest: dict[tuple, dict] = {}
    for row in _tail_jsonl(path, BREACH_TAIL_BYTES):
        if row.get("kind") not in {"STALE_OUTPUT", "INPUT_STARVATION"}:
            continue
        ev = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        latest[(row.get("lane_id"), row.get("kind"), ev.get("contract"))] = row
    out: dict[str, list[str]] = defaultdict(list)
    for (lane_ref, kind, contract), row in latest.items():
        detected = _at(row.get("detected_at"))
        if row.get("state") != "OPEN" or detected is None or now - detected > timedelta(hours=BREACH_OPEN_HOURS):
            continue
        ref = str(lane_ref or "")
        lane_id = by_key.get(ref.removeprefix("freshness:")) or by_key.get(str(contract)) or ref
        ev = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        signal = ev.get("signal") if isinstance(ev.get("signal"), dict) else {}
        what = signal.get("table") or signal.get("path") or contract or ref
        last = (ev.get("observed") or {}).get("last_output_at") if isinstance(ev.get("observed"), dict) else None
        text = (f"input freshness breach open: {what} is stale" + (f" (newest {last[:16]})" if last else "")
                if kind == "STALE_OUTPUT" else f"input starvation breach open since {_iso(detected)[:16]}")
        out[lane_id].append(text)
    return out


def read_plausibility(path: Path, registry: dict, contracts: dict) -> tuple[dict[str, list[str]], bool]:
    """Failing data-plausibility columns mapped to the lanes that write their table."""
    doc = _read_json(path, 4 * 1024 * 1024)
    if not doc:
        return {}, False
    writers: dict[str, set] = defaultdict(set)
    for lane in registry.get("lanes") or []:
        sig = lane.get("output_signal") or {}
        if sig.get("table"):
            writers[str(sig["table"])].add(str(lane.get("lane_id")))
    for c in registry.get("freshness_contracts") or []:
        sig = (c or {}).get("signal") or {}
        if sig.get("table") and c.get("lane_id"):
            writers[str(sig["table"])].add(str(c["lane_id"]))
    tables = {str(r.get("table")) for r in doc.get("results") or [] if isinstance(r, dict) and r.get("table")}
    for cid, c in contracts.items():
        for edge in c.get("connects_to") or []:
            if isinstance(edge, dict) and edge.get("kind") == "store" and edge.get("direction") in {"write", "read_write"}:
                for table in tables:
                    if re.search(rf"\b{re.escape(table)}\b", str(edge.get("name") or "")):
                        writers[table].add(cid)
    out: dict[str, list[str]] = defaultdict(list)
    for r in doc.get("results") or []:
        if not isinstance(r, dict) or (str(r.get("status") or "OK").upper() == "OK" and not _num(r.get("violations"))):
            continue
        text = (f"data plausibility {r.get('status')}: {r.get('table')}.{r.get('column')} has {r.get('violations')} "
                f"violating rows ({str(r.get('detail') or '')[:120]})")
        for lane_id in writers.get(str(r.get("table")), ()):
            out[lane_id].append(text)
    return out, True


def read_history(path: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for row in _tail_jsonl(path, HISTORY_TAIL_BYTES):
        if row.get("schema") == HISTORY_SCHEMA and row.get("lane_id"):
            out[str(row["lane_id"])].append(row)
    return out


def gather(registry: dict, root: Path, *, now: datetime, contracts_path: Path | None = None) -> dict[str, dict]:
    """Evidence per lane id, from production stores read-only."""
    from scripts.lib import cron_outage_watchdog as W
    repo = Path(__file__).resolve().parents[2]
    contracts_doc = _read_json(contracts_path or repo / "config/n8n_health_contracts.json", 16 * 1024 * 1024) or {}
    contracts = {str(c.get("id")): c for c in contracts_doc.get("contracts") or [] if isinstance(c, dict)}
    ledger = read_ledger_quality(root / "data/governance/n8n_coordination_ledger.sqlite", now)
    breach_path = root / "data/runtime/supervisor_breaches.jsonl"
    breaches = read_breaches(breach_path, registry, now)
    plaus, plaus_known = read_plausibility(root / "data/runtime/data_plausibility_last_run.json", registry, contracts)
    history = read_history(root / HISTORY_FILE)
    freshness_lanes = {str(c.get("lane_id")) for c in registry.get("freshness_contracts") or [] if isinstance(c, dict)}
    base = root.resolve()
    out = {}
    for lane in registry.get("lanes") or []:
        lane_id = W.identity(lane)
        receipt, receipt_path = (read_receipt(lane, root) if lane.get("state") == "ACTIVE" else (None, None))
        output_at = None
        signal = lane.get("output_signal") or {}
        if signal.get("kind") in {"file_mtime", "json_key"} and signal.get("path"):
            path = (base / str(signal["path"])).resolve()
            if path.is_relative_to(base / "data") or path.is_relative_to(base / "logs"):
                try:
                    output_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                except OSError:
                    output_at = None
        out[lane_id] = {"receipt": receipt, "receipt_path": receipt_path, "output_at": output_at,
                        "ledger": ledger.get(lane_id, []), "history": history.get(lane_id, []),
                        "contract": contracts.get(lane_id), "freshness": breaches.get(lane_id, []),
                        "freshness_known": breach_path.is_file() and (lane_id in freshness_lanes or lane_id in breaches),
                        "plausibility": plaus.get(lane_id, []), "plausibility_known": plaus_known}
    return out


def attach(result: dict, registry: dict, root: Path, *, now: datetime, evidence: dict | None = None) -> dict:
    """Add ``quality`` to every jobs_history row and ``quality_counts`` to its summary (in place; returns it)."""
    lanes = {str(lane.get("lane_id") or lane.get("id")): lane for lane in registry.get("lanes") or []}
    try:
        evidence = evidence if evidence is not None else gather(registry, root, now=now)
    except Exception as exc:  # noqa: BLE001 -- the grade is advisory; a reader error must not take the page down
        evidence = {}
        result.setdefault("gaps", []).append(f"run quality evidence could not be read ({type(exc).__name__})")
    counts = {g: 0 for g in GRADES}
    not_live = defaultdict(int)
    not_designed = 0
    for row in result.get("rows") or []:
        lane = lanes.get(row["lane_id"]) or {"lane_id": row["lane_id"], "state": row.get("state")}
        quality = grade(row, lane, evidence.get(row["lane_id"]) or {}, now=now)
        row["quality"] = quality
        counts[quality["grade"]] += 1
        if quality["grade"] == "NOT_LIVE":
            not_live[quality["sub"] or "other"] += 1
        if quality["as_designed"] is False:
            not_designed += 1
    summary = result.setdefault("summary", {})
    summary["quality_counts"] = counts
    summary["quality_not_live_by_reason"] = dict(not_live)
    summary["quality_not_as_designed"] = not_designed
    return result


# ── per-run history sample (written only by scripts/run_quality_snapshot.py --apply) ─────────────────────────────

def sample(lane: dict, receipt: dict | None, receipt_path: str | None, *, now: datetime) -> dict | None:
    if not receipt:
        return None
    start, finish = receipt_start(receipt), receipt_finish(receipt)
    if start is None and finish is None:
        return None
    count, key = item_count(receipt)
    duration = round((finish - start).total_seconds(), 3) if start and finish and finish >= start else None
    return {"schema": HISTORY_SCHEMA, "lane_id": str(lane.get("lane_id") or lane.get("id")), "recorded_at": _iso(now),
            "run_started_at": _iso(start or finish), "run_finished_at": _iso(finish), "mode": receipt_mode(receipt),
            "status": receipt_status(receipt), "count": count, "count_key": key, "duration_s": duration,
            "receipt": receipt_path}
