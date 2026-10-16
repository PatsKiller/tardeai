"""What n8n did today — Command Center read model (operator 2026-10-16: "how do i know whats n8n did").

Reads ONLY existing receipts under the persistent state root; never opens n8n, the DB or a provider:

- ``data/runtime/n8n_runs/d:<lane>:<mode>:<YYYYMMDDTHHMM>.json`` — the run executor's per-slot receipts. Selected by
  the ET date fragment in the FILE NAME (one ``listdir``; only today's files are opened), so a request never parses
  the whole 12k-file directory.
- ``data/runtime/n8n_relay/relay_log.jsonl`` — tail-read backwards to today's ET midnight, bounded by
  ``MAX_RELAY_BYTES``; ``n8n-workflow-error`` event intakes and refusals are counted.
- ``data/runtime/n8n_diagnoses/diagnoses.jsonl`` — failure-diagnosis rows (escalations and heals), same tail read.
- ``data/runtime/n8n_cutover/*-cutover.json`` — cutover receipts applied today.

Output ``N8nToday@v1``: runs by state split live / dry_run, failures with reason, lock skips by lane, heals and
diagnoses, lanes cut over today (an applied cutover receipt, or the lane's first-ever live receipt is today).
Cached per process for ``CACHE_TTL_S`` keyed on the inputs' mtimes. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import collections
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SCHEMA = "N8nToday@v1"
CACHE_TTL_S = 60.0
MAX_RELAY_BYTES = 32 * 1024 * 1024
MAX_LIST = 200
RUNS_REL = Path("data") / "runtime" / "n8n_runs"
RELAY_REL = Path("data") / "runtime" / "n8n_relay" / "relay_log.jsonl"
DIAG_REL = Path("data") / "runtime" / "n8n_diagnoses" / "diagnoses.jsonl"
CUTOVER_REL = Path("data") / "runtime" / "n8n_cutover"
HEAL_DECISIONS = {"heal", "retry", "remediate", "rerun", "auto_heal", "self_heal"}

_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


def default_state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def _parse(ts: Any) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def tail_rows_since(path: Path, since: datetime, *, max_bytes: int = MAX_RELAY_BYTES, block: int = 1 << 20):
    """JSON rows of an append-only jsonl whose ``at`` >= since, read backwards from the end. Bounded; never raises.
    Returns (rows oldest-first, truncated)."""
    rows: list[dict] = []
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            pos, carry, read, done = size, b"", 0, False
            while pos > 0 and not done:
                step = min(block, pos)
                pos -= step
                fh.seek(pos)
                buf = fh.read(step) + carry
                read += step
                lines = buf.split(b"\n")
                carry = lines[0] if pos > 0 else b""
                for raw in reversed(lines[1:] if pos > 0 else lines):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except ValueError:
                        continue
                    at = _parse(row.get("at")) if isinstance(row, dict) else None
                    if at is None:
                        continue
                    if at < since:
                        done = True
                        break
                    rows.append(row)
                if read >= max_bytes and not done:
                    rows.reverse()
                    return rows, True
    except OSError:
        return [], False
    rows.reverse()
    return rows, False


def _day_bounds(now: datetime) -> tuple[str, datetime]:
    et_now = now.astimezone(ET)
    midnight = datetime(et_now.year, et_now.month, et_now.day, tzinfo=ET)
    return et_now.date().isoformat(), midnight.astimezone(timezone.utc)


def _receipt_names(runs_dir: Path) -> list[str]:
    try:
        return [n for n in os.listdir(runs_dir) if n.startswith("d:") and n.endswith(".json")]
    except OSError:
        return []


def build(state_root: Optional[Path] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """The uncached projection."""
    root = Path(state_root or default_state_root())
    now = now or datetime.now(timezone.utc)
    day, since = _day_bounds(now)
    frag = day.replace("-", "") + "T"
    runs_dir = root / RUNS_REL
    names = _receipt_names(runs_dir)

    by_state: dict[str, collections.Counter] = {"live": collections.Counter(), "dry_run": collections.Counter()}
    lanes_live_today: set[str] = set()
    first_live: dict[str, str] = {}
    failures: list[dict] = []
    lock_skips: collections.Counter = collections.Counter()
    lanes_seen: set[str] = set()
    for name in names:
        parts = name[:-5].split(":")
        if len(parts) < 4:
            continue
        lane, mode, slot = parts[1], parts[2], parts[-1]
        if mode == "live":
            if lane not in first_live or slot < first_live[lane]:
                first_live[lane] = slot
        if not slot.startswith(frag):
            continue
        try:
            doc = json.loads((runs_dir / name).read_text())
        except (OSError, ValueError):
            doc = {"state": "UNREADABLE"}
        state = str(doc.get("state") or "UNKNOWN")
        bucket = by_state.setdefault(mode, collections.Counter())
        bucket[state] += 1
        lanes_seen.add(lane)
        if mode == "live":
            lanes_live_today.add(lane)
        if state == "RUN_SKIPPED_LOCK":
            lock_skips[(lane, mode)] += 1
        elif state in ("RUN_FAILED", "RUN_REFUSED", "RUN_TIMEOUT", "UNREADABLE") or state.endswith("FAILED"):
            failures.append({
                "lane": lane, "mode": mode, "slot": slot, "state": state,
                "reason": doc.get("reason"), "exit_code": doc.get("exit_code"),
                "finished_at": doc.get("finished_at"), "run_id": doc.get("run_id") or name[:-5],
            })
    failures.sort(key=lambda r: str(r.get("slot")), reverse=True)

    relay_rows, relay_truncated = tail_rows_since(root / RELAY_REL, since)
    relay = collections.Counter()
    workflow_errors: list[dict] = []
    for r in relay_rows:
        relay[f"{r.get('op') or 'run'}:{r.get('state')}"] += 1
        if r.get("op") == "event" and r.get("lane_id") == "n8n-workflow-error":
            workflow_errors.append({"at": r.get("at"), "workflow_id": r.get("workflow_id"), "node": r.get("node"),
                                    "execution_id": r.get("execution_id"), "duplicate": r.get("duplicate")})

    diag_rows, diag_truncated = tail_rows_since(root / DIAG_REL, since)
    diag_by = collections.Counter()
    heals: list[dict] = []
    diagnoses: list[dict] = []
    for d in diag_rows:
        decision = d.get("decision") if isinstance(d.get("decision"), dict) else {}
        kind = str(decision.get("kind") or "")
        diag_by[f"{d.get('event_type')}:{kind or 'none'}"] += 1
        row = {"at": d.get("at"), "lane": d.get("lane"), "event_type": d.get("event_type"), "cause": d.get("cause"),
               "decision": kind or None, "priority": decision.get("priority"), "outcome": d.get("outcome"),
               "remediation_run_id": d.get("remediation_run_id"),
               "run": (d.get("incident_refs") or {}).get("run") if isinstance(d.get("incident_refs"), dict) else None}
        if kind.lower() in HEAL_DECISIONS or d.get("remediation_run_id"):
            heals.append(row)
        else:
            diagnoses.append(row)
    diag_lanes = collections.Counter(str(r.get("lane")) for r in diagnoses)

    cutovers: list[dict] = []
    try:
        for p in sorted((root / CUTOVER_REL).glob("*-cutover.json")):
            try:
                doc = json.loads(p.read_text())
            except (OSError, ValueError):
                continue
            at = _parse(doc.get("at"))
            if at and at >= since and doc.get("applied") and doc.get("action") == "cutover":
                cutovers.append({"lane": doc.get("lane_id"), "at": doc.get("at"), "source": "cutover_receipt",
                                 "scheduler_before": (doc.get("scheduler_before") or {}).get("kind")})
    except OSError:
        pass
    named = {c["lane"] for c in cutovers}
    for lane, slot in sorted(first_live.items()):
        if slot.startswith(frag) and lane not in named:
            cutovers.append({"lane": lane, "at": slot, "source": "first_live_receipt_today", "scheduler_before": None})

    return {
        "schema": SCHEMA,
        "status": "OK" if names else "NO_RECEIPTS",
        "day": day,
        "as_of": now.isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "runs": {
            "by_mode_state": {m: dict(c) for m, c in by_state.items()},
            "totals": {m: sum(c.values()) for m, c in by_state.items()},
            "lanes_active": len(lanes_seen),
            "lanes_live": len(lanes_live_today),
        },
        "failures": failures[:MAX_LIST],
        "failures_total": len(failures),
        "lock_skips": [{"lane": lane, "mode": mode, "count": n}
                       for (lane, mode), n in sorted(lock_skips.items(), key=lambda kv: (-kv[1], kv[0]))],
        "relay": {"counts": dict(relay), "truncated": relay_truncated, "workflow_errors": workflow_errors[-MAX_LIST:]},
        "diagnoses": {
            "counts": dict(diag_by),
            "by_lane": dict(diag_lanes.most_common(30)),
            "recent": diagnoses[-50:][::-1],
            "total": len(diagnoses),
            "truncated": diag_truncated,
        },
        "heals": heals[-MAX_LIST:][::-1],
        "cutovers_today": cutovers,
        "sources": [str(RUNS_REL), str(RELAY_REL), str(DIAG_REL), str(CUTOVER_REL)],
        "note": ("Executor receipts by slot date (ET); n8n-wf-* workflow receipts are not dated by name and are "
                 "counted in relay REQUESTED rows instead."),
    }


def get_n8n_today(state_root: Optional[Path] = None, now: Optional[datetime] = None, *,
                  ttl_s: float = CACHE_TTL_S) -> dict[str, Any]:
    """Cached :func:`build`: reused for ``ttl_s`` while the receipt dir, relay log and diagnoses are unchanged."""
    root = Path(state_root or default_state_root())
    key = (str(root), (now or datetime.now(timezone.utc)).astimezone(ET).date().isoformat(),
           _mtime(root / RUNS_REL), _mtime(root / RELAY_REL), _mtime(root / DIAG_REL), _mtime(root / CUTOVER_REL))
    with _LOCK:
        hit = _CACHE.get(str(root))
        if hit and hit["key"] == key and time.monotonic() - hit["at"] < ttl_s:
            return {**hit["doc"], "cache": "HIT"}
    doc = build(root, now)
    with _LOCK:
        _CACHE[str(root)] = {"key": key, "at": time.monotonic(), "doc": doc}
    return {**doc, "cache": "MISS"}


__all__ = ["build", "get_n8n_today", "tail_rows_since", "SCHEMA"]

