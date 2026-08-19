"""Shared watchlist_agent_jobs enqueue governance.

Dedupe, supersede, stale defer, producer backpressure, thesis/materiality —
not "raise --limit". Never destructive-delete historical rows.

READ_ONLY_ADVISORY. No broker/order/stop/risk/2FA mutation.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

Action = Literal[
    "INSERT",
    "DEDUPED",
    "REUSED_FRESH",
    "SUPERSEDED_OLDER",
    "DEFERRED_BACKPRESSURE",
    "STALE",
    "INVALID_SYMBOL",
]

STALE_HOURS_TAIL = int(os.environ.get("AGENT_JOB_STALE_HOURS_TAIL", "36"))
STALE_HOURS_MATERIAL = int(os.environ.get("AGENT_JOB_STALE_HOURS_MATERIAL", "168"))
FRESH_HOURS_TAIL = int(os.environ.get("AGENT_JOB_FRESH_HOURS_TAIL", "12"))
FRESH_HOURS_MATERIAL = int(os.environ.get("AGENT_JOB_FRESH_HOURS_MATERIAL", "4"))

QUEUE_PRESSURE_HIGH = int(os.environ.get("AGENT_JOB_QUEUE_PRESSURE_HIGH", "200"))
T2_MAX_WHEN_PRESSURE = int(os.environ.get("AGENT_JOB_T2_MAX_WHEN_PRESSURE", "80"))
T3_MAX_WHEN_PRESSURE = int(os.environ.get("AGENT_JOB_T3_MAX_WHEN_PRESSURE", "40"))

ACTIVE_STATUSES = ("queued", "pending", "running", "processing")


@dataclass
class EnqueueRequest:
    symbol: str
    requested_agent: str
    request_type: str
    submitted_from: str = "unknown"
    priority: int = 5
    note: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    job_id: str | None = None
    thesis_id: str | None = None
    thesis_version: str | None = None
    research_gap_id: str | None = None
    evidence_fingerprint: str | None = None
    time_horizon: str = "default"
    universe_tier: str = "T3"  # T0 holding, T1 reentry, T2 material watch, T3/T4 tail
    material: bool = False


@dataclass
class EnqueueResult:
    action: Action
    job_id: str | None = None
    semantic_key: str = ""
    reason: str = ""
    superseded_ids: list[str] = field(default_factory=list)


def normalize_symbol(symbol: str | None) -> str:
    return str(symbol or "").upper().strip()


def semantic_key(req: EnqueueRequest) -> str:
    """Stable identity: symbol+agent+request_type+thesis/gap/evidence/horizon.

    submitted_from is classified auto vs manual so two automatic producers of the
    same research question collapse; explicit manual still shares the key so we
    do not double-pay.
    """
    src = str(req.submitted_from or "").strip().lower()
    src_class = "manual" if src in {
        "watchlist_requeue", "api", "operator_telegram", "cio_telegram", "operator",
    } else "auto"
    raw = "|".join(
        [
            normalize_symbol(req.symbol),
            str(req.requested_agent or "").lower().strip(),
            str(req.request_type or "").lower().strip(),
            str(req.thesis_id or req.payload.get("thesis_id") or ""),
            str(req.research_gap_id or req.payload.get("research_gap_id") or ""),
            str(req.evidence_fingerprint or req.payload.get("evidence_fingerprint") or ""),
            str(req.time_horizon or "default"),
            src_class,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def infer_universe_tier(req: EnqueueRequest) -> str:
    t = str(req.universe_tier or "").upper()
    if t in {"T0", "T1", "T2", "T3", "T4"}:
        return t
    prio = int(req.priority or 99)
    rt = str(req.request_type or "").lower()
    if prio <= 1 and rt in {"full_analysis", "research_gap", "event", "proposal_review"}:
        return "T0"
    if prio <= 2:
        return "T1"
    if prio <= 3:
        return "T2"
    if prio <= 5:
        return "T3"
    return "T4"


def backpressure_allows(tier: str, queued_count: int, *, material: bool = False) -> tuple[bool, str]:
    """When queue pressure is high: T0/T1 material still enters; T3/T4 coalesce/defer."""
    tier = str(tier or "T3").upper()
    if queued_count < QUEUE_PRESSURE_HIGH:
        return True, "pressure_normal"
    if tier == "T0" or (tier == "T1" and material):
        return True, "pressure_high_but_t0_t1_material"
    if tier == "T1":
        return True, "pressure_high_t1_reentry_allowed"
    if tier == "T2":
        if queued_count >= T2_MAX_WHEN_PRESSURE and queued_count >= QUEUE_PRESSURE_HIGH:
            return False, "t2_bounded_under_pressure"
        return True, "t2_bounded_ok"
    return False, "t3_t4_deferred_under_pressure"


def classify_queued_age(
    *,
    created_at: datetime | None,
    tier: str,
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    if created_at is None:
        return "CURRENT_AND_MATERIAL" if str(tier).upper() in {"T0", "T1"} else "CURRENT_LOW_PRIORITY"
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    age = now - created_at.astimezone(timezone.utc)
    t = str(tier).upper()
    limit = timedelta(hours=STALE_HOURS_MATERIAL if t in {"T0", "T1"} else STALE_HOURS_TAIL)
    if age > limit:
        return "STALE"
    if t in {"T0", "T1"}:
        return "CURRENT_AND_MATERIAL"
    return "CURRENT_LOW_PRIORITY"


def _row_payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("payload")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def governed_enqueue(cur, req: EnqueueRequest, *, queued_count: int | None = None) -> EnqueueResult:
    """Apply governance then INSERT or skip. Does not commit. Never DELETE."""
    sym = normalize_symbol(req.symbol)
    key = semantic_key(req)
    if not sym or not str(req.requested_agent or "").strip():
        return EnqueueResult(action="INVALID_SYMBOL", semantic_key=key, reason="missing_symbol_or_agent")

    tier = infer_universe_tier(req)
    if queued_count is None:
        cur.execute(
            "SELECT COUNT(*) FROM watchlist_agent_jobs WHERE status IN ('queued','pending','running','processing')"
        )
        row = cur.fetchone()
        queued_count = int((row[0] if not isinstance(row, dict) else list(row.values())[0]) or 0)

    allow, why = backpressure_allows(tier, int(queued_count), material=bool(req.material))
    if not allow:
        return EnqueueResult(action="DEFERRED_BACKPRESSURE", semantic_key=key, reason=why)

    cur.execute(
        """
        SELECT id, status, created_at, payload FROM watchlist_agent_jobs
        WHERE UPPER(symbol)=%s AND LOWER(requested_agent)=LOWER(%s) AND LOWER(request_type)=LOWER(%s)
          AND status = ANY(%s)
        ORDER BY created_at ASC
        """,
        (sym, req.requested_agent, req.request_type, list(ACTIVE_STATUSES)),
    )
    active = cur.fetchall() or []
    matching_ids: list[str] = []
    for row in active:
        if isinstance(row, dict):
            r = row
        elif isinstance(row, (tuple, list)):
            r = {
                "id": row[0],
                "status": row[1] if len(row) > 1 else None,
                "created_at": row[2] if len(row) > 2 else None,
                "payload": row[3] if len(row) > 3 else {},
            }
        else:
            r = {"id": row}
        payload = _row_payload(r)
        if str(payload.get("semantic_key") or "") == key or not payload.get("semantic_key"):
            matching_ids.append(str(r.get("id") or r.get("ID")))
    if matching_ids:
        return EnqueueResult(
            action="DEDUPED",
            job_id=matching_ids[-1],
            semantic_key=key,
            reason="equivalent_queued_or_running",
        )

    fresh_h = FRESH_HOURS_MATERIAL if tier in {"T0", "T1"} or req.material else FRESH_HOURS_TAIL
    cur.execute(
        """
        SELECT id FROM watchlist_agent_jobs
        WHERE UPPER(symbol)=%s AND LOWER(requested_agent)=LOWER(%s) AND LOWER(request_type)=LOWER(%s)
          AND status='completed'
          AND completed_at > NOW() - (%s || ' hours')::interval
        ORDER BY completed_at DESC LIMIT 1
        """,
        (sym, req.requested_agent, req.request_type, str(int(fresh_h))),
    )
    fresh = cur.fetchone()
    if fresh and not req.evidence_fingerprint:
        fid = fresh[0] if not isinstance(fresh, dict) else fresh.get("id")
        return EnqueueResult(action="REUSED_FRESH", job_id=str(fid), semantic_key=key, reason="fresh_completed_no_new_evidence")

    # Supersede older queued twins that lack semantic_key but same triple and older note.
    superseded: list[str] = []
    job_id = req.job_id or f"gov-{sym.lower()}-{req.requested_agent}-{uuid.uuid4().hex[:8]}"
    payload = dict(req.payload or {})
    payload.update({
        "semantic_key": key,
        "universe_tier": tier,
        "provider_policy": "FLASH_FIRST_AUTO_QUEUE",
        "thesis_id": req.thesis_id,
        "research_gap_id": req.research_gap_id,
        "evidence_fingerprint": req.evidence_fingerprint,
        "manual_vs_automatic": "automatic" if infer_auto(req.submitted_from) else "manual",
    })
    cur.execute(
        """
        INSERT INTO watchlist_agent_jobs
            (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, payload, created_at)
        VALUES (%s,%s,%s,%s,%s,'queued',%s,%s,%s,NOW())
        ON CONFLICT (id) DO NOTHING
        """,
        (
            job_id,
            sym,
            req.requested_agent,
            req.request_type,
            req.note,
            int(req.priority),
            req.submitted_from,
            json.dumps(payload),
        ),
    )
    return EnqueueResult(
        action="INSERT",
        job_id=job_id,
        semantic_key=key,
        reason=why,
        superseded_ids=superseded,
    )


def infer_auto(submitted_from: str | None) -> bool:
    src = str(submitted_from or "").strip().lower()
    return src not in {
        "watchlist_requeue", "api", "operator_telegram", "cio_telegram", "operator",
    }


def govern_existing_queued(cur, *, now: datetime | None = None, limit: int = 5000, dry_run: bool = False) -> dict[str, int]:
    """Classify queued backlog: supersede duplicates, defer stale. Never DELETE."""
    now = now or datetime.now(timezone.utc)
    cur.execute(
        """
        SELECT id, symbol, requested_agent, request_type, submitted_from, priority, created_at, payload, note
        FROM watchlist_agent_jobs
        WHERE status IN ('queued','pending')
        ORDER BY created_at ASC
        LIMIT %s
        """,
        (int(limit),),
    )
    rows = cur.fetchall() or []
    seen: dict[str, str] = {}
    counts = {
        "examined": 0,
        "superseded": 0,
        "stale_deferred": 0,
        "kept": 0,
        "invalid": 0,
    }
    for raw in rows:
        counts["examined"] += 1
        if isinstance(raw, dict):
            row = raw
        else:
            row = {
                "id": raw[0], "symbol": raw[1], "requested_agent": raw[2],
                "request_type": raw[3], "submitted_from": raw[4], "priority": raw[5],
                "created_at": raw[6], "payload": raw[7], "note": raw[8] if len(raw) > 8 else "",
            }
        req = EnqueueRequest(
            symbol=str(row.get("symbol") or ""),
            requested_agent=str(row.get("requested_agent") or ""),
            request_type=str(row.get("request_type") or ""),
            submitted_from=str(row.get("submitted_from") or "unknown"),
            priority=int(row.get("priority") or 5),
            payload=_row_payload(row),
        )
        if not normalize_symbol(req.symbol):
            if not dry_run:
                cur.execute(
                    """UPDATE watchlist_agent_jobs SET status='deferred',
                   note=COALESCE(note,'') || ' [INVALID_SYMBOL]',
                   payload=COALESCE(payload,'{}'::jsonb) || %s::jsonb
                   WHERE id=%s AND status IN ('queued','pending')""",
                    (json.dumps({"archive_class": "INVALID_SYMBOL"}), row["id"]),
                )
            counts["invalid"] += 1
            continue
        key = str((_row_payload(row) or {}).get("semantic_key") or semantic_key(req))
        tier = infer_universe_tier(req)
        age_class = classify_queued_age(created_at=row.get("created_at"), tier=tier, now=now)
        if age_class == "STALE":
            if not dry_run:
                cur.execute(
                    """UPDATE watchlist_agent_jobs SET status='deferred',
                   note=COALESCE(note,'') || ' [STALE backlog — not paid]',
                   payload=COALESCE(payload,'{}'::jsonb) || %s::jsonb
                   WHERE id=%s AND status IN ('queued','pending')""",
                    (json.dumps({"archive_class": "STALE", "governed_at": now.isoformat()}), row["id"]),
                )
            counts["stale_deferred"] += 1
            continue
        if key in seen:
            if not dry_run:
                cur.execute(
                    """UPDATE watchlist_agent_jobs SET status='superseded',
                   note=COALESCE(note,'') || ' [SUPERSEDED duplicate]',
                   payload=COALESCE(payload,'{}'::jsonb) || %s::jsonb
                   WHERE id=%s AND status IN ('queued','pending')""",
                    (json.dumps({
                        "archive_class": "DUPLICATE",
                        "superseded_by": seen[key],
                        "reason": "equivalent_semantic_key",
                        "governed_at": now.isoformat(),
                    }), row["id"]),
                )
            counts["superseded"] += 1
            continue
        seen[key] = str(row["id"])
        counts["kept"] += 1
    return counts
