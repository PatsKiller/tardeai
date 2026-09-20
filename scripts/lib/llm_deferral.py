"""Off-peak deferral for paid LLM work, with an operator-set priority per caller.

Why this exists (operator directive, 2026-09-19): when the free lanes are exhausted the
work has to reach DeepSeek, but not at any hour and not at any price. DeepSeek bills peak
hours at roughly double off-peak, so anything that is not time-sensitive belongs in a queue
that drains inside the off-peak window. Only work the operator asked for directly, or a
caller the operator has marked critical, spends at peak.

What already existed and why it was not enough: `deepseek_offpeak.should_scheduled_skip`
returns True at peak and the wrapper logs PEAK_SKIP and exits 0. That **drops** the work.
Nothing records that a question went unasked, and nothing ever asks it. This module keeps
the same window arithmetic and replaces the drop with a durable queue.

Three tiers, resolved per `process_id`:

  critical   spend now, any hour. The operator's own asks, and callers they have marked.
  standard   spend now inside the off-peak window; queue for the next one outside it.
  deferred   always queue, never spend on demand.

`standard` is the default, and an unknown caller gets it — a caller nobody has classified
must not silently acquire the right to spend at peak.

Nothing here is enabled by default. `LLM_DEFER_OFFPEAK=1` arms it, so it ships inert and is
turned on deliberately, the way RESEARCH_FREE_FALLBACK was.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.deepseek_offpeak import (  # noqa: E402
    ET,
    is_scheduled_deepseek_window,
)

class DeferredToOffPeak(RuntimeError):
    """Raised instead of spending at peak. The work is queued, not lost.

    A RuntimeError subclass on purpose: the callers of gate_and_generate already treat
    RuntimeError as "this call did not produce text", so an unaware caller degrades
    exactly as it would on any other refusal instead of crashing. The difference is that
    this one carries a queue id, and something will run it.
    """

    def __init__(self, process_id: str, lane: str, request_id: str | None,
                 run_after, reason: str):
        self.process_id = process_id
        self.lane = lane
        self.request_id = request_id
        self.run_after = run_after
        self.reason = reason
        when = run_after.isoformat() if hasattr(run_after, "isoformat") else str(run_after)
        queued = f"queued as {request_id}" if request_id else "already queued"
        super().__init__(
            f"DEFERRED_TO_OFFPEAK: {process_id} on {lane} ({reason}) — {queued}, "
            f"runs after {when}"
        )


ENABLE_ENV = "LLM_DEFER_OFFPEAK"
TRUTHY = {"1", "true", "yes", "on"}

TIER_CRITICAL = "critical"
TIER_STANDARD = "standard"
TIER_DEFERRED = "deferred"
TIERS = (TIER_CRITICAL, TIER_STANDARD, TIER_DEFERRED)
DEFAULT_TIER = TIER_STANDARD

# A queued question is about a moment. Re-asking a stale one wastes the money the queue
# exists to save, so a request that missed its window by this much is retired, not run.
DEFAULT_TTL_HOURS = float(os.environ.get("LLM_DEFER_TTL_HOURS", "24"))
# Walk forward in steps to find the next open window. 15 minutes is finer than any
# boundary the window arithmetic uses, and 8 days covers a holiday weekend.
_STEP = timedelta(minutes=15)
_HORIZON = timedelta(days=8)

REGISTRY_PATH = ROOT / "config" / "llm_process_registry.json"


def enabled() -> bool:
    return os.environ.get(ENABLE_ENV, "").strip().lower() in TRUTHY


# --------------------------------------------------------------------------- tiers


def _registry_tiers() -> dict[str, str]:
    """Seed tiers declared in the process registry. The DB overrides these."""
    try:
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for proc in reg.get("processes") or []:
        if not isinstance(proc, dict):
            continue
        tier = str(proc.get("offpeak_tier") or "").strip().lower()
        if tier in TIERS and proc.get("id"):
            out[str(proc["id"])] = tier
    return out


def _db_tiers() -> dict[str, str]:
    """Operator-set tiers. A DB that is down must not silently promote callers to critical."""
    try:
        from db_adapter import _execute
        rows = _execute(
            "SELECT process_id, tier FROM llm_caller_priority", fetch="all"
        ) or []
    except Exception:
        return {}
    out: dict[str, str] = {}
    for r in rows:
        pid = r["process_id"] if isinstance(r, dict) else r[0]
        tier = str((r["tier"] if isinstance(r, dict) else r[1]) or "").strip().lower()
        if tier in TIERS:
            out[str(pid)] = tier
    return out


def resolve_tier(process_id: str) -> str:
    """Operator setting wins, then the registry seed, then `standard`."""
    pid = str(process_id or "")
    return _db_tiers().get(pid) or _registry_tiers().get(pid) or DEFAULT_TIER


def list_callers() -> list[dict[str, Any]]:
    """Every registered paid caller with its effective tier and where that tier came from.

    The operator sets these, so the page must show which are their explicit choice and
    which are merely defaults — otherwise an unreviewed default reads as a decision.
    """
    db, seed = _db_tiers(), _registry_tiers()
    try:
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        procs = reg.get("processes") or []
    except (OSError, ValueError):
        procs = []
    out = []
    for proc in procs:
        if not isinstance(proc, dict) or not proc.get("id"):
            continue
        pid = str(proc["id"])
        source = "operator" if pid in db else ("registry" if pid in seed else "default")
        out.append({
            "process_id": pid,
            "name": proc.get("name") or pid,
            "category": proc.get("category") or "",
            "lane_policy": proc.get("lane_policy") or "",
            "daily_cost_cap_usd": proc.get("daily_cost_cap_usd"),
            "tier": db.get(pid) or seed.get(pid) or DEFAULT_TIER,
            "tier_source": source,
        })
    return sorted(out, key=lambda r: (r["category"], r["process_id"]))


def set_tier(process_id: str, tier: str, *, updated_by: str = "operator",
             note: str | None = None) -> None:
    tier = str(tier or "").strip().lower()
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")
    ensure_schema()
    from db_adapter import _execute
    _execute(
        """
        INSERT INTO llm_caller_priority (process_id, tier, note, updated_by, updated_at)
        VALUES (%s, %s, %s, %s, NOW())
        ON CONFLICT (process_id) DO UPDATE
           SET tier = EXCLUDED.tier, note = EXCLUDED.note,
               updated_by = EXCLUDED.updated_by, updated_at = NOW()
        """,
        (str(process_id), tier, note, str(updated_by)),
    )


# --------------------------------------------------------------------------- decision


@dataclass
class Decision:
    defer: bool
    reason: str
    tier: str
    run_after: datetime | None = None


def next_window_start(now: datetime | None = None) -> datetime:
    """The next instant the off-peak window is open.

    Stepped rather than solved: the window is the intersection of an ET operator window
    and DeepSeek's UTC peak table, which straddle each other across DST and weekends.
    Stepping asks the same predicate the gate uses instead of re-deriving it, so the two
    can never disagree — the bug this arithmetic has already produced twice.
    """
    cur = (now or datetime.now(ET)).astimezone(ET)
    end = cur + _HORIZON
    probe = cur
    while probe <= end:
        if is_scheduled_deepseek_window(probe):
            return probe
        probe += _STEP
    return cur + _HORIZON  # pathological; the drainer will expire it rather than hang


def evaluate(process_id: str, *, manual_trigger: bool = False,
             bypass: bool = False, now: datetime | None = None) -> Decision:
    """Should this paid call happen now, or wait for the off-peak window?

    The two short-circuits come FIRST, before `resolve_tier`, because resolving a tier
    costs a database round-trip and a registry read. This sits on the paid-call
    chokepoint, so with the feature disabled — its shipped state — it ran a
    `SELECT ... FROM llm_caller_priority` on EVERY DeepSeek call and, if the table did
    not exist, printed a SQL error for each one. A feature that is switched off must
    cost nothing and say nothing. The tier is reported `unresolved` on these paths
    because it genuinely was not looked up; the defer path below resolves it for real,
    and that is the only path whose tier is ever stored.
    """
    if bypass:
        return Decision(False, "DRAIN_BYPASS", "unresolved")
    if not enabled():
        return Decision(False, "DEFERRAL_DISABLED", "unresolved")
    tier = resolve_tier(process_id)
    if manual_trigger:
        # The operator is waiting. This is the exemption the off-peak rule already carries.
        return Decision(False, "OPERATOR_REQUEST", tier)
    if tier == TIER_CRITICAL:
        return Decision(False, "CRITICAL_CALLER", tier)
    if tier != TIER_DEFERRED and is_scheduled_deepseek_window(now):
        return Decision(False, "IN_OFFPEAK_WINDOW", tier)
    reason = "TIER_ALWAYS_DEFERRED" if tier == TIER_DEFERRED else "OUTSIDE_OFFPEAK_WINDOW"
    return Decision(True, reason, tier, run_after=next_window_start(now))


# --------------------------------------------------------------------------- queue


DDL = """
CREATE TABLE IF NOT EXISTS llm_caller_priority (
    process_id  TEXT PRIMARY KEY,
    tier        TEXT NOT NULL,
    note        TEXT,
    updated_by  TEXT NOT NULL DEFAULT 'operator',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS llm_deferred_requests (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    process_id    TEXT NOT NULL,
    lane          TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    task_summary  TEXT,
    payload       JSONB NOT NULL DEFAULT '{}'::jsonb,
    tier          TEXT NOT NULL DEFAULT 'standard',
    reason        TEXT NOT NULL,
    dedupe_key    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    attempts      INT  NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    run_after     TIMESTAMPTZ NOT NULL,
    expires_at    TIMESTAMPTZ NOT NULL,
    claimed_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    error         TEXT
);

-- One pending row per identical question. An hourly caller deferring for twelve hours
-- would otherwise queue the same prompt twelve times and pay for it twelve times.
CREATE UNIQUE INDEX IF NOT EXISTS llm_deferred_pending_dedupe
    ON llm_deferred_requests (dedupe_key) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS llm_deferred_due
    ON llm_deferred_requests (status, run_after);
"""


def ensure_schema() -> None:
    from db_adapter import _execute
    _execute(DDL)


def dedupe_key(process_id: str, prompt: str) -> str:
    h = hashlib.sha256()
    h.update(str(process_id).encode("utf-8"))
    h.update(b"\x00")
    h.update(str(prompt).encode("utf-8"))
    return h.hexdigest()


def enqueue(*, process_id: str, lane: str, prompt: str, decision: Decision,
            task_summary: str | None = None, payload: dict | None = None,
            ttl_hours: float | None = None, now: datetime | None = None) -> str | None:
    """Queue a deferred call. Returns its id, or None when an identical one is pending."""
    ensure_schema()
    from db_adapter import _execute
    base = (now or datetime.now(ET)).astimezone(ET)
    run_after = decision.run_after or next_window_start(base)
    ttl = DEFAULT_TTL_HOURS if ttl_hours is None else float(ttl_hours)
    # The clock starts at the window, not at enqueue: a request deferred on Friday night
    # for a Monday window would otherwise expire before it was ever eligible.
    expires_at = run_after + timedelta(hours=ttl)
    row = _execute(
        """
        INSERT INTO llm_deferred_requests
            (process_id, lane, prompt, task_summary, payload, tier, reason,
             dedupe_key, run_after, expires_at)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s)
        ON CONFLICT (dedupe_key) WHERE status = 'pending' DO NOTHING
        RETURNING id
        """,
        (str(process_id), str(lane), str(prompt), task_summary,
         json.dumps(payload or {}), decision.tier, decision.reason,
         dedupe_key(process_id, prompt), run_after, expires_at),
        fetch="one",
    )
    if not row:
        return None
    return str(row["id"] if isinstance(row, dict) else row[0])


def claim_due(limit: int = 25, now: datetime | None = None) -> list[dict[str, Any]]:
    """Lease due rows. SKIP LOCKED so two drainers cannot run the same question twice."""
    ensure_schema()
    from db_adapter import _execute
    return _execute(
        """
        UPDATE llm_deferred_requests SET status = 'claimed', claimed_at = NOW(),
               attempts = attempts + 1
        WHERE id IN (
            SELECT id FROM llm_deferred_requests
            WHERE status = 'pending' AND run_after <= %s AND expires_at > %s
            ORDER BY run_after
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        RETURNING id, process_id, lane, prompt, task_summary, payload, tier
        """,
        (now or datetime.now(ET), now or datetime.now(ET), int(limit)),
        fetch="all",
    ) or []


def expire_stale(now: datetime | None = None) -> int:
    """Retire requests whose window passed. Counted, never silently dropped."""
    ensure_schema()
    from db_adapter import _execute
    rows = _execute(
        """
        UPDATE llm_deferred_requests SET status = 'expired', completed_at = NOW()
        WHERE status = 'pending' AND expires_at <= %s
        RETURNING id
        """,
        (now or datetime.now(ET),), fetch="all",
    ) or []
    return len(rows)


def complete(request_id: str, *, ok: bool, error: str | None = None) -> None:
    from db_adapter import _execute
    _execute(
        """
        UPDATE llm_deferred_requests
           SET status = %s, completed_at = NOW(), error = %s
         WHERE id = %s::uuid
        """,
        ("done" if ok else "failed", (error or None), str(request_id)),
    )


def queue_summary(now: datetime | None = None) -> dict[str, Any]:
    """Counts by status plus the next due time — what the Command Center shows."""
    ensure_schema()
    from db_adapter import _execute
    rows = _execute(
        "SELECT status, COUNT(*) n FROM llm_deferred_requests GROUP BY status", fetch="all"
    ) or []
    counts = {str(r["status"] if isinstance(r, dict) else r[0]):
              int(r["n"] if isinstance(r, dict) else r[1]) for r in rows}
    nxt = _execute(
        "SELECT MIN(run_after) t FROM llm_deferred_requests WHERE status = 'pending'",
        fetch="one",
    )
    t = (nxt["t"] if isinstance(nxt, dict) else (nxt[0] if nxt else None)) if nxt else None
    return {
        "counts": counts,
        "pending": counts.get("pending", 0),
        "next_run_after": t.isoformat() if t else None,
        "window_open_now": is_scheduled_deepseek_window(now),
        "enabled": enabled(),
    }
