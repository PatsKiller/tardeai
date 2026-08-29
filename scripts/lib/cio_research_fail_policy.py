"""Hermes research failure classification, histogram and replay policy.

Wave 2 slices 19 / 20 / 21.

READ_ONLY_ADVISORY. MBI=0. Reads the request ledger; writes nothing.

The four buckets the operator asked for, plus the residue, and — the part that
matters — **whether each is the worker's fault**:

| class | retryable | worker bug |
|---|---|---|
| `cost_cap` | no, until the cap window rolls | **no** — a process cap doing its job |
| `execution_language` | **no, ever** | no — the output was correctly refused |
| `truncated` | yes, at most 1 replay per plan per day | no |
| `schema_invalid` | no | no — the model answered off-contract |
| `provider_error` / `timeout` | yes | no |
| `other` | no | unknown — inspect |

`cost_cap` deserves the emphasis. On CURRENT it arrives under **two** different
shapes: an honest HTTP 429 `COST_CAP_EXCEEDED`, and an HTTP 500
`RESERVATION_FAILED` whose message is `COST_CAP_EXCEEDED: daily request cap`.
The second looks like a server fault and is not one. Classifying on the code
alone would file 114 of 302 failures as provider errors and send someone
debugging a bridge that is behaving correctly.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CIOResearchFailHistogram@v1"
FAILED_EVENT = "HERMES_RESEARCH_FAILED"
WINDOW_DAYS = 7
MAX_REPLAYS_PER_PLAN_PER_DAY = 1

COST_CAP = "cost_cap"
EXECUTION_LANGUAGE = "execution_language"
TRUNCATED = "truncated"
SCHEMA_INVALID = "schema_invalid"
PROVIDER_ERROR = "provider_error"
TIMEOUT = "timeout"
OTHER = "other"

# class -> (retryable, is_worker_bug)
CLASS_POLICY: dict[str, tuple[bool, bool]] = {
    COST_CAP: (False, False),
    EXECUTION_LANGUAGE: (False, False),
    TRUNCATED: (True, False),
    SCHEMA_INVALID: (False, False),
    PROVIDER_ERROR: (True, False),
    TIMEOUT: (True, False),
    OTHER: (False, False),
}

_CODE_RE = re.compile(r'"code"\s*:\s*"([A-Z_]+)"')
_SCHEMA_ERRORS = frozenset({"questions_required", "confidence_out_of_range"})


def classify_failure(error: Any) -> dict[str, Any]:
    """Map a raw Hermes failure string to a class + policy. Never raises."""
    text = str(error or "").strip()
    low = text.lower()
    code_match = _CODE_RE.search(text)
    code = code_match.group(1) if code_match else None

    if "cost_cap_exceeded" in low or "cost cap" in low:
        # Catches BOTH the 429 COST_CAP_EXCEEDED and the 500 RESERVATION_FAILED
        # whose message is "COST_CAP_EXCEEDED: daily request cap".
        cls = COST_CAP
    elif low.startswith("execution language") or "execution language not allowed" in low:
        cls = EXECUTION_LANGUAGE
    elif "truncated" in low or "incomplete" in low:
        cls = TRUNCATED
    elif text in _SCHEMA_ERRORS or low in _SCHEMA_ERRORS:
        cls = SCHEMA_INVALID
    elif "timed out" in low or "timeout" in low:
        cls = TIMEOUT
    elif code in {"PROVIDER_ERROR"} or "provider failure" in low:
        cls = PROVIDER_ERROR
    else:
        cls = OTHER

    retryable, worker_bug = CLASS_POLICY[cls]
    return {
        "class": cls,
        "code": code,
        "retryable": retryable,
        "is_worker_bug": worker_bug,
        "prefix": text[:70],
        "note": (
            "process cap, not a worker bug — do not debug the bridge"
            if cls == COST_CAP else
            "output correctly refused; never requeue" if cls == EXECUTION_LANGUAGE else
            None
        ),
    }


def _parse_ts(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def iter_failure_rows(path: Path | str) -> Iterable[dict[str, Any]]:
    """Yield HERMES_RESEARCH_FAILED rows from the request ledger. Fail-soft."""
    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line or FAILED_EVENT not in line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("event") == FAILED_EVENT:
                yield row


def build_fail_histogram(
    rows: Iterable[dict[str, Any]],
    *,
    window_days: int = WINDOW_DAYS,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Failure histogram over the trailing window. Counting only — no requeue."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=int(window_days))

    by_class: Counter[str] = Counter()
    by_day: dict[str, Counter[str]] = defaultdict(Counter)
    by_prefix: Counter[str] = Counter()
    plans_by_class: dict[str, set[str]] = defaultdict(set)
    total = in_window = undated = 0

    for row in rows:
        total += 1
        ts = _parse_ts(row.get("updated_ts") or row.get("ts"))
        if ts is None:
            undated += 1
            continue
        if ts < cutoff:
            continue
        in_window += 1
        info = classify_failure(row.get("error"))
        cls = info["class"]
        by_class[cls] += 1
        by_day[ts.date().isoformat()][cls] += 1
        by_prefix[info["prefix"]] += 1
        if row.get("plan_id"):
            plans_by_class[cls].add(str(row["plan_id"]))

    retryable_n = sum(c for k, c in by_class.items() if CLASS_POLICY[k][0])
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "window_days": int(window_days),
        "as_of": now.replace(microsecond=0).isoformat(),
        "failures_total_all_time": total,
        "failures_in_window": in_window,
        "undated_rows": undated,
        "by_class": dict(by_class.most_common()),
        "by_class_policy": {
            k: {
                "n": v,
                "retryable": CLASS_POLICY[k][0],
                "is_worker_bug": CLASS_POLICY[k][1],
                "distinct_plans": len(plans_by_class.get(k, ())),
            }
            for k, v in by_class.most_common()
        },
        "by_day": {d: dict(c) for d, c in sorted(by_day.items())},
        "top_error_prefixes": [
            {"prefix": p, "n": n} for p, n in by_prefix.most_common(8)
        ],
        "retryable_n": retryable_n,
        "non_retryable_n": in_window - retryable_n,
        "worker_bug_n": 0,
        "class": "D",
        "note": (
            "cost_cap arrives as both HTTP 429 COST_CAP_EXCEEDED and HTTP 500 "
            "RESERVATION_FAILED ('COST_CAP_EXCEEDED: daily request cap'). Both "
            "are the process cap working, not a worker bug."
        ),
    }


# The request ledger is ~9MB and /v3/cio/home rebuilds the product on every
# request. Cache on (path, mtime_ns, size, window, hour) rather than a TTL: a new
# failure is picked up on its next read, and the trailing window still advances
# hourly on a quiet ledger. Same pattern as identity_registry.load_cached.
_HIST_CACHE: dict[tuple, dict[str, Any]] = {}


def load_fail_histogram(
    *,
    root: Path | str,
    window_days: int = WINDOW_DAYS,
    now: Optional[datetime] = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    path = Path(root) / "data" / "cio" / "hermes_research_requests.jsonl"
    try:
        st = path.stat()
        stamp: tuple = (st.st_mtime_ns, st.st_size)
        available = True
    except OSError:
        stamp, available = (0, 0), False

    at = now or datetime.now(timezone.utc)
    key = (str(path), stamp, int(window_days), at.strftime("%Y-%m-%dT%H"))
    if use_cache and key in _HIST_CACHE:
        return _HIST_CACHE[key]

    hist = build_fail_histogram(
        iter_failure_rows(path), window_days=window_days, now=at,
    )
    hist["source"] = str(path)
    hist["source_available"] = available
    if use_cache:
        _HIST_CACHE.clear()          # one window at a time; never grows
        _HIST_CACHE[key] = hist
    return hist


# ── slices 20 / 21: what may be enqueued again ───────────────────────────────

def replay_decision(
    *,
    prior_failures: Iterable[dict[str, Any]],
    plan_id: str = "",
    now: Optional[datetime] = None,
    max_per_plan_per_day: int = MAX_REPLAYS_PER_PLAN_PER_DAY,
) -> dict[str, Any]:
    """May this plan be enqueued again given how it failed before?

    Slice 20 — an `execution_language` failure is **never** requeued. The model
    was told not to write execution verbs and did; running it again spends money
    to be refused again.

    Slice 21 — a `truncated` failure is retryable, but at most
    `max_per_plan_per_day` replays per plan per calendar day. The cap is not
    raised anywhere; this only decides eligibility.
    """
    now = now or datetime.now(timezone.utc)
    today = now.date()
    rows = [r for r in prior_failures if isinstance(r, dict)]

    classes: list[str] = []
    replays_today = 0
    latest: Optional[dict[str, Any]] = None
    latest_ts: Optional[datetime] = None

    for row in rows:
        info = classify_failure(row.get("error"))
        classes.append(info["class"])
        ts = _parse_ts(row.get("updated_ts") or row.get("ts"))
        if ts and ts.date() == today:
            replays_today += 1
        if ts and (latest_ts is None or ts > latest_ts):
            latest_ts, latest = ts, row

    def _out(allow: bool, reason: str, **extra: Any) -> dict[str, Any]:
        return {
            "schema": "CIOResearchReplayDecision@v1",
            "authority": AUTHORITY,
            "financial_action": False,
            "plan_id": plan_id,
            "allow_enqueue": allow,
            "reason": reason,
            "prior_failure_n": len(rows),
            "prior_classes": sorted(set(classes)),
            "failures_today": replays_today,
            "max_per_plan_per_day": int(max_per_plan_per_day),
            "last_failure_class": (
                classify_failure(latest.get("error"))["class"] if latest else None
            ),
            "raises_cost_cap": False,
            **extra,
        }

    if EXECUTION_LANGUAGE in classes:
        return _out(False, "execution_language_non_retryable",
                    is_worker_bug=False,
                    detail="output was correctly refused; requeueing only pays to be refused again")
    if COST_CAP in classes and all(c == COST_CAP for c in classes):
        return _out(False, "cost_cap_wait_for_window",
                    is_worker_bug=False,
                    detail="process cap, not a worker bug; eligible again when the cap window rolls")
    if TRUNCATED in classes and replays_today >= int(max_per_plan_per_day):
        return _out(False, "truncated_replay_cap_reached",
                    is_worker_bug=False,
                    detail=f"already {replays_today} failure(s) today for this plan")
    if not rows:
        return _out(True, "no_prior_failure", is_worker_bug=False)
    return _out(True, "retryable_within_cap", is_worker_bug=False)


# ── slice 25: critique verdict counts over completed results ────────────────

_VERDICT_CACHE: dict[tuple, dict[str, Any]] = {}


def build_verdict_counts(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """VALID / PARTIAL / FAIL-family counts over completed Hermes results.

    The attach rule is VALID **or** PARTIAL (hermes_research_loop
    ._SUCCESS_VERDICTS). Reporting only "VALID" would understate what actually
    joins a plan, so `attachable_n` is stated separately from `valid_n`.
    """
    from scripts.lib.research_quality import critique

    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    total = 0
    for rec in results:
        if not isinstance(rec, dict):
            continue
        total += 1
        verdict = critique(rec)
        counts[str(verdict.get("verdict"))] += 1
        for reason in verdict.get("reasons") or []:
            reasons[str(reason)] += 1
    attachable = counts.get("VALID", 0) + counts.get("PARTIAL", 0)
    return {
        "schema": "CIOResearchVerdictCounts@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "completed_n": total,
        "by_verdict": dict(counts.most_common()),
        "valid_n": counts.get("VALID", 0),
        "partial_n": counts.get("PARTIAL", 0),
        "fail_family_n": total - attachable,
        "attachable_n": attachable,
        "attach_rule": "VALID|PARTIAL",
        "attach_rule_source": "hermes_research_loop.research_complete_is_attachable",
        "top_reasons": dict(reasons.most_common(6)),
        "class": "D",
        "note": (
            "attachable = VALID + PARTIAL. PARTIAL attaches by design and is not "
            "silently tightened; a PARTIAL is usually 'no_sources'."
        ),
    }


def load_verdict_counts(
    *,
    root: Path | str,
    use_cache: bool = True,
) -> dict[str, Any]:
    path = Path(root) / "data" / "cio" / "hermes_research_results.jsonl"
    try:
        st = path.stat()
        stamp: tuple = (st.st_mtime_ns, st.st_size)
        available = True
    except OSError:
        stamp, available = (0, 0), False

    key = (str(path), stamp)
    if use_cache and key in _VERDICT_CACHE:
        return _VERDICT_CACHE[key]

    def _rows() -> Iterable[dict[str, Any]]:
        try:
            handle = open(path, "r", encoding="utf-8")
        except OSError:
            return
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    yield row

    out = build_verdict_counts(_rows())
    out["source"] = str(path)
    out["source_available"] = available
    if use_cache:
        _VERDICT_CACHE.clear()
        _VERDICT_CACHE[key] = out
    return out
