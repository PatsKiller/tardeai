"""IntelligenceLineage@v1 — durable closed-loop identity.

READ_ONLY_ADVISORY. Never mutates broker/orders/stops/risk/2FA.
Never deletes challenge or case history. Drain appends EXPIRED/RESOLVED/DEAD_LETTER.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "IntelligenceLineage@v1"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

STATUSES = (
    "DISCOVERED",
    "RESEARCH_REQUESTED",
    "RESEARCH_IN_PROGRESS",
    "RESEARCH_COMPLETED",
    "RESEARCH_VALIDATED",
    "SYNTHESIZED",
    "MEMORY_ADMITTED",
    "MEMORY_RETRIEVED",
    "ADVISORY_USED",
    "OUTCOME_PENDING",
    "OUTCOME_OBSERVED",
    "SCORED",
    "LESSON_CANDIDATE",
    "LESSON_RATIFIED",
    "LESSON_REUSED",
    "CLOSED",
    "REJECTED",
    "EXPIRED",
    "FAILED",
)

_STATUS_RANK = {s: i for i, s in enumerate(STATUSES)}


def cio_dir() -> Path:
    env = os.environ.get("TRADEAI_CIO_DIR")
    if env:
        return Path(env)
    # Worker persist writes cwd-relative data/cio. Prefer the same dir so
    # overlay expire/lineage see the live store when invoked from CURRENT.
    cwd_cand = Path("data/cio")
    if cwd_cand.exists():
        return cwd_cand.resolve()
    cand = PROJECT_ROOT / "data" / "cio"
    if cand.exists():
        return cand
    return Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/cio")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat()


def _parse_ts(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _append_jsonl(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    payload = json.dumps(rec, sort_keys=True, default=str) + "\n"
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _atomic_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    data = json.dumps(obj, indent=2, sort_keys=True, default=str) + "\n"
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def lineage_paths(d: Path | None = None) -> tuple[Path, Path]:
    root = d or cio_dir()
    return root / "intelligence_lineages.jsonl", root / "intelligence_lineages.json"


def _hid(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _transition(status: str, producer: str, reason: str, refs: list[str] | None = None) -> dict[str, Any]:
    blob = json.dumps({"status": status, "reason": reason, "refs": refs or []}, sort_keys=True)
    digest = hashlib.sha256(blob.encode()).hexdigest()[:16]
    return {
        "at": _iso(),
        "status": status,
        "producer": producer,
        "reason": reason,
        "source_refs": refs or [],
        "input_digest": digest,
        "output_digest": digest,
    }


def empty_lineage(lineage_id: str, **kw: Any) -> dict[str, Any]:
    rec = {
        "schema": SCHEMA,
        "lineage_id": lineage_id,
        "created_at": _iso(),
        "updated_at": _iso(),
        "origin": kw.get("origin") or "rebuild",
        "status": "DISCOVERED",
        "symbol": kw.get("symbol"),
        "sector": kw.get("sector"),
        "industry": kw.get("industry"),
        "discovery_id": kw.get("discovery_id"),
        "theme_id": None,
        "directive_id": None,
        "research_request_ids": [],
        "research_result_ids": [],
        "research_review_ids": [],
        "financial_senses_receipt_ids": [],
        "thesis_id": kw.get("thesis_id"),
        "watchlist_id": None,
        "cio_case_id": kw.get("cio_case_id"),
        "decision_id": kw.get("decision_id"),
        "memory_ids": [],
        "memory_retrieval_ids": [],
        "outcome_id": None,
        "score_id": None,
        "reflection_id": None,
        "lesson_id": None,
        "promotion_id": None,
        "reuse_decision_id": None,
        "advisory_use": None,
        "transitions": [],
        "authority": AUTHORITY,
        "financial_action": False,
    }
    rec.update({k: v for k, v in kw.items() if k in rec and v is not None})
    return rec


def _advance(rec: dict[str, Any], status: str, producer: str, reason: str, refs: list[str] | None = None) -> None:
    if _STATUS_RANK.get(status, -1) >= _STATUS_RANK.get(str(rec.get("status")), -1):
        rec["status"] = status
    rec["updated_at"] = _iso()
    rec.setdefault("transitions", []).append(_transition(status, producer, reason, refs))


def challenge_latest(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for r in rows:
        sid = str(r.get("stream_id") or "")
        if sid:
            latest[sid] = r
    return latest


_TERMINAL_SUFFIXES = (
    "_EXPIRED",
    "_RESOLVED",
    "_DEAD_LETTER",
    "_FAILED",
    "_CANCELLED",
)
_TERMINAL_STATUSES = frozenset({
    "EXPIRED", "RESOLVED", "DEAD_LETTER", "CANCELLED", "FAILED", "CLOSED",
})


def challenge_pending(latest: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in latest.values():
        et = str(r.get("event_type") or "")
        if et in {"HERMES_CHALLENGE_GENESIS"}:
            continue
        if any(et.endswith(suf) for suf in _TERMINAL_SUFFIXES):
            continue
        status = str((r.get("payload") or {}).get("status") or "").upper()
        if status in _TERMINAL_STATUSES:
            continue
        if et == "HERMES_CHALLENGE_ENQUEUED" or status in {"", "PENDING", "ENQUEUED", "CLAIMED", "IN_PROGRESS"}:
            out.append(r)
    return out


def _challenge_symbols(rec: dict[str, Any]) -> list[str]:
    md = rec.get("metadata") or {}
    pl = rec.get("payload") or {}
    raw = md.get("symbols") or pl.get("symbols") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(s).upper() for s in raw if s]


def _fingerprint(rec: dict[str, Any]) -> str:
    pl = rec.get("payload") or {}
    md = rec.get("metadata") or {}
    return "|".join([
        str(pl.get("challenge_type") or ""),
        ",".join(sorted(_challenge_symbols(rec))),
        str(pl.get("source") or md.get("source") or "")[:80],
    ])


def drain_hermes_challenges(*, apply: bool = False, max_age_days: int = 7) -> dict[str, Any]:
    """Append EXPIRED/CANCELLED. Never delete JSONL rows. Never invent research."""
    path = cio_dir() / "hermes_challenge_queue.jsonl"
    rows = _read_jsonl(path)
    latest = challenge_latest(rows)
    pending = challenge_pending(latest)
    before = len(pending)
    report = {
        "before_pending": before,
        "expired_test": 0,
        "expired_dup": 0,
        "expired_stale": 0,
        "resolved_existing_research": 0,
        "left_pending": 0,
        "applied": apply,
        "deleted": 0,
        "authority": AUTHORITY,
    }
    by_fp: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in pending:
        by_fp[_fingerprint(rec)].append(rec)
    now = _now()
    cutoff = now - timedelta(days=max_age_days)
    keep: set[str] = set()
    actions: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    for _fp, group in by_fp.items():
        group.sort(key=lambda r: str(r.get("occurred_at") or ""), reverse=True)
        winner = group[0]
        for rec in group[1:]:
            actions.append(("expire", rec, {
                "reason": "duplicate_fingerprint",
                "fingerprint": _fp,
                "kept_stream_id": winner.get("stream_id"),
            }))
            report["expired_dup"] += 1
        syms = _challenge_symbols(winner)
        if any("TEST" in s or s in {"SPACEX", "SPACEX_TEST"} for s in syms):
            actions.append(("cancel", winner, {
                "reason": "test_or_fixture_symbol",
                "symbols": syms,
                "status": "DEAD_LETTER",
            }))
            report["expired_test"] += 1
            continue
        ts = _parse_ts(winner.get("occurred_at"))
        if ts and ts < cutoff:
            actions.append(("expire", winner, {
                "reason": f"stale_gt_{max_age_days}d",
                "age_days": (now - ts).days,
            }))
            report["expired_stale"] += 1
            continue
        keep.add(str(winner.get("stream_id")))

    report["left_pending"] = len(keep)
    report["actions"] = len(actions)
    if apply and actions:
        try:
            from lib.cio_hermes_challenge_queue import HermesChallengeQueue
        except ImportError:
            from scripts.lib.cio_hermes_challenge_queue import HermesChallengeQueue  # type: ignore
        q = HermesChallengeQueue(event_store_path=path)
        applied_n = 0
        errors: list[str] = []
        for kind, src, payload in actions:
            sid = str(src.get("stream_id") or "")
            if not sid:
                continue
            try:
                if kind == "cancel":
                    q.cancel(
                        sid,
                        reason=str(payload.get("reason") or "test_or_fixture_symbol"),
                        actor_id="closed_loop_p0_drain",
                    )
                else:
                    q.expire(
                        sid,
                        actor_id="closed_loop_p0_drain",
                        reason=str(payload.get("reason") or "expired"),
                    )
                applied_n += 1
            except Exception as exc:
                errors.append(f"{sid}:{type(exc).__name__}")
        report["applied_n"] = applied_n
        if errors:
            report["errors"] = errors[:20]
        after_rows = _read_jsonl(path)
        report["after_pending"] = len(challenge_pending(challenge_latest(after_rows)))
        report["after_events"] = len(after_rows)
        report["history_preserved"] = len(after_rows) >= len(rows)
    return report


def cases_path() -> Path:
    return cio_dir() / "cio_production_cases.jsonl"


def _case_opened_at(case: dict[str, Any], first_event_at: dict[str, datetime] | None = None) -> datetime | None:
    facts = case.get("decision_time_facts") if isinstance(case.get("decision_time_facts"), dict) else {}
    for cand in (
        facts.get("as_of"),
        facts.get("opened_at"),
        case.get("occurred_at"),
        case.get("created_at"),
    ):
        ts = _parse_ts(cand)
        if ts:
            return ts
    cid = str(case.get("case_id") or "")
    if first_event_at and cid in first_event_at:
        return first_event_at[cid]
    return None


def observe_overdue_cases(*, apply: bool = False, horizon_days: int = 7) -> dict[str, Any]:
    """Mark OPEN/AWAITING cases past horizon as EXPIRED (a legitimate matured outcome).

    Does not invent POSITIVE/NEGATIVE P&L. EXPIRED = horizon elapsed, no market outcome.
    Missing timestamps are skipped — never treated as overdue.
    """
    try:
        from lib.cio_production_case import (  # local import
            load_events,
            materialize_cases,
            maybe_score_if_mature,
            record_outcome,
        )
    except ImportError:
        from scripts.lib.cio_production_case import (  # type: ignore
            load_events,
            materialize_cases,
            maybe_score_if_mature,
            record_outcome,
        )

    path = cases_path()
    cases = materialize_cases(path=path)
    first_at: dict[str, datetime] = {}
    for ev in load_events(path=path):
        cid = str(ev.get("case_id") or "")
        if not cid or cid in first_at:
            continue
        ts = _parse_ts(ev.get("occurred_at") or ev.get("recorded_at"))
        if ts:
            first_at[cid] = ts
    cutoff = _now() - timedelta(days=horizon_days)
    observed = 0
    scored = 0
    skipped = 0
    unknown_ts = 0
    invented_pnl = 0
    for case in cases:
        status = str(case.get("status") or "").upper()
        if status in {"MATURED", "SCORED", "CLOSED"}:
            skipped += 1
            continue
        if case.get("outcome") and str((case.get("outcome") or {}).get("outcome_status") or "").upper() in {
            "POSITIVE", "NEGATIVE", "FLAT", "EXPIRED",
        }:
            skipped += 1
            continue
        opened = _case_opened_at(case, first_at)
        if opened is None:
            unknown_ts += 1
            skipped += 1
            continue
        if opened > cutoff:
            skipped += 1
            continue
        did = str(case.get("decision_id") or "")
        if not did:
            skipped += 1
            continue
        observed += 1
        if not apply:
            continue
        record_outcome(
            did,
            {
                "outcome_status": "EXPIRED",
                "evaluation_horizon": f"{horizon_days}d",
                "maturity_at": _iso(),
                "reason": "horizon_elapsed_no_market_outcome",
                "lookahead": False,
                "source": "closed_loop_p0_observer",
            },
            input_digest=str(case.get("decision_input_digest") or ""),
            evidence_digest=str(case.get("decision_evidence_digest") or ""),
            path=path,
        )
        case["outcome"] = {
            "outcome_status": "EXPIRED",
            "evaluation_horizon": f"{horizon_days}d",
            "maturity_at": _iso(),
        }
        case["status"] = "MATURED"
        scored_rec = maybe_score_if_mature(case, path=path)
        if scored_rec.get("eligible") or scored_rec.get("darwin_status") == "SCORED":
            scored += 1
    next_due = None
    due_times = []
    for case in cases:
        opened = _case_opened_at(case, first_at)
        if opened is None:
            continue
        due = opened + timedelta(days=horizon_days)
        if due > _now():
            due_times.append(due)
    if due_times:
        next_due = min(due_times).isoformat()
    return {
        "cases_total": len(cases),
        "observed_expired": observed,
        "scored": scored,
        "skipped": skipped,
        "unknown_timestamp": unknown_ts,
        "invented_pnl": invented_pnl,
        "applied": apply,
        "horizon_days": horizon_days,
        "authority": AUTHORITY,
        "path": str(path),
        "next_due_at": next_due,
        "observer_state": "PROVEN_IDLE" if observed == 0 else "OBSERVED",
    }


def rebuild_lineages() -> dict[str, Any]:
    d = cio_dir()
    jsonl_path, snap_path = lineage_paths(d)
    challenges = _read_jsonl(d / "hermes_challenge_queue.jsonl")
    latest = challenge_latest(challenges)
    pending = challenge_pending(latest)
    memories = _read_jsonl(d / "aif_memory.jsonl")
    results = _read_jsonl(d / "hermes_research_results.jsonl")
    lessons_path = d / "lessons.jsonl"
    if not lessons_path.exists():
        # maturity control lessons live under various names
        for cand in ("kb_lessons.jsonl", "advisory_lessons.jsonl"):
            if (d / cand).exists():
                lessons_path = d / cand
                break
    lessons = _read_jsonl(lessons_path)

    try:
        from lib.cio_production_case import materialize_cases
    except ImportError:
        from scripts.lib.cio_production_case import materialize_cases  # type: ignore
    cases = materialize_cases(path=cases_path())

    by_symbol: dict[str, dict[str, Any]] = {}

    def bucket(sym: str) -> dict[str, Any]:
        s = (sym or "").upper()
        if not s:
            s = "UNKNOWN"
        if s not in by_symbol:
            lid = "lin_" + _hid("symbol", s)
            by_symbol[s] = empty_lineage(lid, symbol=s, origin="live_rebuild", discovery_id="disc_" + _hid(s))
            _advance(by_symbol[s], "DISCOVERED", "rebuild", "symbol present in office evidence", [s])
        return by_symbol[s]

    for rec in results:
        et = str(rec.get("event") or rec.get("status") or "")
        if et and et not in {"HERMES_RESEARCH_COMPLETED", "completed", "COMPLETED"}:
            continue
        s = str(rec.get("symbol") or "").upper()
        if not s:
            continue
        lin = bucket(s)
        rid = str(rec.get("result_id") or "")
        req = str(rec.get("research_id") or "")
        if rid and rid not in lin["research_result_ids"]:
            lin["research_result_ids"].append(rid)
        if req and req not in lin["research_request_ids"]:
            lin["research_request_ids"].append(req)
        _advance(lin, "RESEARCH_COMPLETED", "hermes_research_results", et or "completed", [rid or req])

    for rec in pending:
        for s in _challenge_symbols(rec):
            lin = bucket(s)
            sid = str(rec.get("stream_id") or "")
            if sid and sid not in lin["research_request_ids"]:
                lin["research_request_ids"].append(sid)
            rid = str((rec.get("metadata") or {}).get("research_id") or "")
            if rid and rid not in lin["research_request_ids"]:
                lin["research_request_ids"].append(rid)
            _advance(lin, "RESEARCH_REQUESTED", "hermes_challenge_queue", "pending challenge", [sid])

    for rec in latest.values():
        et = str(rec.get("event_type") or "")
        if et.endswith("_RESOLVED"):
            for s in _challenge_symbols(rec):
                lin = bucket(s)
                sid = str(rec.get("stream_id") or "")
                if sid and sid not in lin["research_request_ids"]:
                    lin["research_request_ids"].append(sid)
                _advance(lin, "RESEARCH_COMPLETED", "hermes_challenge_queue", "challenge resolved", [sid])

    for mem in memories:
        mid = str(mem.get("memory_id") or "")
        status = str(mem.get("status") or mem.get("state") or "").upper()
        content = str(mem.get("content") or "")
        meta = mem.get("metadata") if isinstance(mem.get("metadata"), dict) else {}
        syms = meta.get("symbols") or mem.get("symbols") or []
        if isinstance(syms, str):
            syms = [syms]
        if not syms:
            # attach operator memory to UNKNOWN bucket as office-level
            syms = ["OFFICE"]
        for s in [str(x).upper() for x in syms if x]:
            lin = bucket(s)
            if mid and mid not in lin["memory_ids"]:
                lin["memory_ids"].append(mid)
            if status == "EXPIRED":
                continue
            _advance(lin, "MEMORY_ADMITTED", "aif_memory", mem.get("admission_reason") or "admitted", [mid])

    for case in cases:
        s = str(case.get("symbol") or "").upper() or "OFFICE"
        lin = bucket(s)
        cid = str(case.get("case_id") or "")
        did = str(case.get("decision_id") or "")
        if cid:
            lin["cio_case_id"] = cid
        if did:
            lin["decision_id"] = did
        st = str(case.get("status") or "").upper()
        if st == "SCORED":
            _advance(lin, "SCORED", "cio_production_cases", "darwin scored", [cid])
            lin["score_id"] = cid + ":darwin"
            lin["outcome_id"] = cid + ":outcome"
        elif st == "MATURED":
            _advance(lin, "OUTCOME_OBSERVED", "cio_production_cases", "case matured", [cid])
            lin["outcome_id"] = cid + ":outcome"
        elif st in {"AWAITING_OUTCOME", "OPEN"}:
            _advance(lin, "OUTCOME_PENDING", "cio_production_cases", st.lower(), [cid])
        if case.get("research"):
            _advance(lin, "MEMORY_RETRIEVED", "cio_production_cases", "retrieval recorded", [cid])
            rid = cid + ":retrieval"
            if rid not in lin["memory_retrieval_ids"]:
                lin["memory_retrieval_ids"].append(rid)

    # Do not infer ADVISORY_USED from symbol presence. Only from an explicit use receipt.

    for les in lessons:
        lid = str(les.get("lesson_id") or les.get("id") or "")
        state = str(les.get("state") or les.get("status") or "").upper()
        syms = les.get("symbols") or []
        if isinstance(syms, str):
            syms = [syms]
        if not syms:
            syms = ["OFFICE"]
        for s in [str(x).upper() for x in syms if x]:
            lin = bucket(s)
            if lid:
                lin["lesson_id"] = lid
            if "RATIF" in state:
                _advance(lin, "LESSON_RATIFIED", "lessons", state, [lid])
            elif "CANDIDATE" in state:
                _advance(lin, "LESSON_CANDIDATE", "lessons", state, [lid])
            elif "REUSE" in state or "ACTIVE" in state:
                _advance(lin, "LESSON_REUSED", "lessons", state, [lid])
                lin["reuse_decision_id"] = lid + ":reuse"

    lineages = sorted(by_symbol.values(), key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    for rec in lineages:
        rec["updated_at"] = rec.get("updated_at") or _iso()
    by_status = {
        s: sum(1 for r in lineages if r.get("status") == s)
        for s in STATUSES
        if any(r.get("status") == s for r in lineages)
    }
    pending_n = len(challenge_pending(challenge_latest(_read_jsonl(d / "hermes_challenge_queue.jsonl"))))
    snap = {
        "schema": SCHEMA,
        "generated_at": _iso(),
        "authority": AUTHORITY,
        "count": len(lineages),
        "by_status": by_status,
        "lineages": lineages,
        "pending_challenges": pending_n,
        "financial_action": False,
    }
    _append_jsonl(jsonl_path, {
        "event": "LINEAGE_REBUILD",
        "at": _iso(),
        "count": len(lineages),
        "by_status": by_status,
        "pending_challenges": pending_n,
        "authority": AUTHORITY,
        "lineage_ids": [r.get("lineage_id") for r in lineages],
    })
    _atomic_json(snap_path, snap)
    return snap


def load_snapshot() -> dict[str, Any]:
    _, snap = lineage_paths()
    if snap.is_file():
        try:
            return json.loads(snap.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"schema": SCHEMA, "count": 0, "lineages": [], "authority": AUTHORITY}


def get_lineage(lineage_id: str) -> dict[str, Any] | None:
    for rec in load_snapshot().get("lineages") or []:
        if rec.get("lineage_id") == lineage_id:
            return rec
    return None


def _upsert_snapshot_lineage(rec: dict[str, Any]) -> None:
    """Merge one live-forward lineage into the projection snapshot (idempotent)."""
    jsonl_path, snap_path = lineage_paths()
    _append_jsonl(jsonl_path, {
        "event": "LINEAGE_LIVE_FORWARD",
        "at": _iso(),
        "lineage_id": rec.get("lineage_id"),
        "status": rec.get("status"),
        "symbol": rec.get("symbol"),
        "research_request_ids": list(rec.get("research_request_ids") or []),
        "research_result_ids": list(rec.get("research_result_ids") or []),
        "authority": AUTHORITY,
    })
    snap = load_snapshot()
    rows = list(snap.get("lineages") or [])
    lid = str(rec.get("lineage_id") or "")
    replaced = False
    for i, r in enumerate(rows):
        if r.get("lineage_id") == lid:
            rows[i] = rec
            replaced = True
            break
    if not replaced:
        rows.insert(0, rec)
    by_status = {
        s: sum(1 for r in rows if r.get("status") == s)
        for s in STATUSES
        if any(r.get("status") == s for r in rows)
    }
    live_n = sum(1 for r in rows if str(r.get("origin") or "") == "live_forward")
    snap.update({
        "schema": SCHEMA,
        "generated_at": _iso(),
        "authority": AUTHORITY,
        "count": len(rows),
        "by_status": by_status,
        "live_forward_count": live_n,
        "lineages": rows[:500],
        "financial_action": False,
    })
    _atomic_json(snap_path, snap)


def _find_by_research_id(research_id: str) -> dict[str, Any] | None:
    rid = str(research_id or "").strip()
    if not rid:
        return None
    for rec in load_snapshot().get("lineages") or []:
        reqs = [str(x) for x in (rec.get("research_request_ids") or [])]
        if rid in reqs or rid == str(rec.get("discovery_id") or ""):
            return dict(rec)
    return None


def attach_research_requested(
    *,
    research_id: str,
    symbol: str | None = None,
    plan_id: str | None = None,
    thesis_version: str | None = None,
    fingerprint: str | None = None,
    discovery_id: str | None = None,
) -> dict[str, Any]:
    """Live-forward: enqueue → RESEARCH_REQUESTED. Idempotent on research_id."""
    existing = _find_by_research_id(research_id)
    if existing:
        reqs = list(existing.get("research_request_ids") or [])
        if research_id not in reqs:
            reqs.append(research_id)
            existing["research_request_ids"] = reqs
        _advance(existing, "RESEARCH_REQUESTED", "cio_hermes_research", "enqueue", [research_id])
        if plan_id:
            existing["cio_case_id"] = existing.get("cio_case_id") or plan_id
        if thesis_version:
            existing["thesis_id"] = thesis_version
        if fingerprint:
            existing.setdefault("transitions", [])  # keep
            existing["fingerprint"] = fingerprint
        _upsert_snapshot_lineage(existing)
        return {"ok": True, "lineage_id": existing.get("lineage_id"), "lineage": existing, "idempotent": True}

    lid = "lin_" + _hid("live", research_id, symbol or "", plan_id or "")
    rec = empty_lineage(
        lid,
        origin="live_forward",
        symbol=(symbol or "").upper() or None,
        discovery_id=discovery_id or research_id,
        thesis_id=thesis_version,
        cio_case_id=plan_id,
    )
    rec["research_request_ids"] = [research_id]
    if fingerprint:
        rec["fingerprint"] = fingerprint
    _advance(rec, "RESEARCH_REQUESTED", "cio_hermes_research", "enqueue", [research_id])
    _upsert_snapshot_lineage(rec)
    return {"ok": True, "lineage_id": lid, "lineage": rec, "idempotent": False}


def attach_research_completed(
    *,
    research_id: str,
    result_id: str,
    symbol: str | None = None,
    plan_id: str | None = None,
    memory_id: str | None = None,
    critique_verdict: str | None = None,
) -> dict[str, Any]:
    """Live-forward: result persisted → RESEARCH_COMPLETED (+ MEMORY_ADMITTED if memory_id)."""
    rec = _find_by_research_id(research_id)
    if not rec:
        # create then complete (late attach)
        created = attach_research_requested(
            research_id=research_id, symbol=symbol, plan_id=plan_id,
        )
        rec = created.get("lineage") or empty_lineage(
            "lin_" + _hid("late", research_id),
            origin="live_forward",
            symbol=(symbol or "").upper() or None,
        )
        rec["research_request_ids"] = list(dict.fromkeys(
            list(rec.get("research_request_ids") or []) + [research_id]
        ))
    results = list(rec.get("research_result_ids") or [])
    if result_id and result_id not in results:
        results.append(result_id)
    rec["research_result_ids"] = results
    if symbol and not rec.get("symbol"):
        rec["symbol"] = str(symbol).upper()
    if plan_id and not rec.get("cio_case_id"):
        rec["cio_case_id"] = plan_id
    _advance(rec, "RESEARCH_COMPLETED", "cio_hermes_research", "mark_completed", [result_id])
    if critique_verdict and str(critique_verdict).upper() in {"VALID", "PASS", "OK", "ACCEPTED"}:
        _advance(rec, "RESEARCH_VALIDATED", "research_quality", str(critique_verdict), [result_id])
    if memory_id:
        mids = list(rec.get("memory_ids") or [])
        if memory_id not in mids:
            mids.append(memory_id)
        rec["memory_ids"] = mids
        _advance(rec, "MEMORY_ADMITTED", "research_memory_bridge", "admit", [memory_id])
    _upsert_snapshot_lineage(rec)
    return {"ok": True, "lineage_id": rec.get("lineage_id"), "lineage": rec}


def attach_advisory_use(
    *,
    research_id: str | None = None,
    result_id: str | None = None,
    lineage_id: str | None = None,
    product_id: str | None = None,
    reassessment_id: str | None = None,
    decision_id: str | None = None,
    what_changed_material: bool | None = None,
) -> dict[str, Any]:
    """Live-forward: parent book reassessment → ADVISORY_USED / SYNTHESIZED."""
    rec = None
    if lineage_id:
        rec = get_lineage(lineage_id)
    if not rec and research_id:
        rec = _find_by_research_id(research_id)
    if not rec and result_id:
        for r in load_snapshot().get("lineages") or []:
            if result_id in [str(x) for x in (r.get("research_result_ids") or [])]:
                rec = dict(r)
                break
    if not rec:
        return {"ok": False, "error": "lineage_not_found"}
    use = {
        "product_id": product_id,
        "reassessment_id": reassessment_id,
        "decision_id": decision_id,
        "what_changed_material": what_changed_material,
        "at": _iso(),
    }
    rec["advisory_use"] = use
    if decision_id:
        rec["decision_id"] = decision_id
    refs = [x for x in (product_id, reassessment_id, decision_id, result_id) if x]
    _advance(rec, "SYNTHESIZED", "cio_product_reassessment", "product_persist", refs)
    _advance(rec, "ADVISORY_USED", "cio_product_reassessment", "reassess_on_research_completed", refs)
    if what_changed_material is False:
        # still advisory-used; quiet notify path
        pass
    _upsert_snapshot_lineage(rec)
    return {"ok": True, "lineage_id": rec.get("lineage_id"), "lineage": rec}


def challenge_view(limit: int = 40) -> dict[str, Any]:
    rows = _read_jsonl(cio_dir() / "hermes_challenge_queue.jsonl")
    latest = challenge_latest(rows)
    pending = challenge_pending(latest)
    items = []
    for rec in sorted(pending, key=lambda r: str(r.get("occurred_at") or ""), reverse=True)[:limit]:
        items.append({
            "stream_id": rec.get("stream_id"),
            "event_type": rec.get("event_type"),
            "occurred_at": rec.get("occurred_at"),
            "symbols": _challenge_symbols(rec),
            "challenge_type": (rec.get("payload") or {}).get("challenge_type"),
            "plan_id": (rec.get("metadata") or {}).get("plan_id"),
            "research_id": (rec.get("metadata") or {}).get("research_id"),
        })
    statuses: dict[str, int] = defaultdict(int)
    for rec in latest.values():
        et = str(rec.get("event_type") or "")
        if et == "HERMES_CHALLENGE_GENESIS":
            continue
        statuses[et.replace("HERMES_CHALLENGE_", "")] += 1
    return {
        "events": len(rows),
        "unique_streams": len([k for k in latest if k != "hermes_challenge_queue"]),
        "pending": len(pending),
        "by_latest_event": dict(statuses),
        "items": items,
        "authority": AUTHORITY,
    }


def summary() -> dict[str, Any]:
    snap = load_snapshot()
    ch = challenge_view()
    lineages = list(snap.get("lineages") or [])
    latest = lineages[0] if lineages else None
    return {
        "ok": True,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "mutation": False,
        "financial_action": False,
        "generated_at": snap.get("generated_at"),
        "lineage_count": int(snap.get("count") or len(lineages)),
        "by_status": snap.get("by_status") or {},
        "pending_challenges": ch["pending"],
        "challenge_events": ch["events"],
        "unique_streams": ch["unique_streams"],
        "latest_lineage_id": (latest or {}).get("lineage_id"),
        "challenges": ch,
        "lineages": lineages[:80],
    }


def reconcile(*, apply: bool = False, horizon_days: int = 7, max_age_days: int = 7) -> dict[str, Any]:
    drain = drain_hermes_challenges(apply=apply, max_age_days=max_age_days)
    observe = observe_overdue_cases(apply=apply, horizon_days=horizon_days)
    snap = rebuild_lineages()
    return {
        "ok": True,
        "authority": AUTHORITY,
        "applied": apply,
        "drain": drain,
        "observe": observe,
        "lineage": {
            "count": snap.get("count"),
            "by_status": snap.get("by_status"),
            "generated_at": snap.get("generated_at"),
            "pending_challenges": snap.get("pending_challenges"),
            "lineage_ids": [r.get("lineage_id") for r in (snap.get("lineages") or [])],
        },
        "financial_action": False,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Closed-loop reconcile (READ_ONLY_ADVISORY)")
    ap.add_argument("--apply", action="store_true", help="Append drain/observe events (default dry-run)")
    ap.add_argument("--horizon-days", type=int, default=7)
    ap.add_argument("--max-age-days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    rec = reconcile(apply=args.apply, horizon_days=args.horizon_days, max_age_days=args.max_age_days)
    if args.json:
        print(json.dumps(rec, indent=2, default=str))
    else:
        print(
            f"closed-loop reconcile apply={rec['applied']} "
            f"drain_pending {rec['drain'].get('before_pending')}->{rec['drain'].get('after_pending', rec['drain'].get('left_pending'))} "
            f"expired_test={rec['drain'].get('expired_test')} dup={rec['drain'].get('expired_dup')} stale={rec['drain'].get('expired_stale')} "
            f"observe_expired={rec['observe'].get('observed_expired')} scored={rec['observe'].get('scored')} "
            f"lineages={rec['lineage'].get('count')}"
        )
    return 0 if rec.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
