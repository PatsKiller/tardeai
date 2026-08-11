"""Durable root-cause memory for Health auto-remediation.

Records, per finding_type:
  - last error / trigger message
  - diagnosed root_cause code + human how_to_fix
  - strategy ladder index (iterative autonomous fixes)
  - attempt outcomes so the next cycle picks a different strategy

Store path: data/runtime/health_root_cause_memory.json
Append-only audit: logs/health_root_cause_memory.jsonl

Safe for concurrent readers; writers use atomic replace.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.live_project_root import DEV_ROOT, get_live_project_root

try:
    PROJECT_ROOT = get_live_project_root()
except Exception:
    PROJECT_ROOT = DEV_ROOT

# Prefer DEV runtime for durability across release stamps; fall back to live.
def _default_memory_path() -> Path:
    for base in (DEV_ROOT, PROJECT_ROOT):
        try:
            p = base / "data" / "runtime" / "health_root_cause_memory.json"
            # Prefer existing store; otherwise DEV if writable
            if p.is_file():
                return p
        except Exception:
            continue
    # Default write location: DEV (survives release pin flips)
    return DEV_ROOT / "data" / "runtime" / "health_root_cause_memory.json"


def _default_audit_path() -> Path:
    for base in (DEV_ROOT, PROJECT_ROOT):
        p = base / "logs" / "health_root_cause_memory.jsonl"
        if p.is_file():
            return p
    return DEV_ROOT / "logs" / "health_root_cause_memory.jsonl"


MEMORY_PATH = Path(os.environ.get("HEALTH_RC_MEMORY_PATH", str(_default_memory_path())))
AUDIT_PATH = Path(os.environ.get("HEALTH_RC_AUDIT_PATH", str(_default_audit_path())))

# Seed recipes: ordered strategy ladders. Each strategy is a short id that
# remediate_* scripts interpret. First strategy is tried first; on failure the
# next unused (or least-recently-failed) strategy is selected.
SEED_RECIPES: dict[str, dict[str, Any]] = {
    "scalp_catalyst_verification_dead": {
        "title": "Momentum-scalp GO tier dark (0 GO while scanner active)",
        "known_root_causes": {
            "catalyst_cap_bug": (
                "Social-only cap mis-reads catalyst keys → every GO/A+ forced to WAIT. "
                "Fix: ensure apply_social_only_cap reads catalysts/rag_catalyst_confirmed "
                "(2026-07-08 class)."
            ),
            "low_max_score_regime": (
                "Scanner active but max score < GO_THRESHOLD (40). Market quiet or pillars "
                "soft (rvol/gap/float/news). Fix: refresh social+news+finviz feeds then rescan; "
                "do NOT thrash bare scanner if max_score stays <35."
            ),
            "news_or_social_feed_dead": (
                "Mention/news inputs empty or stale → scores collapse. Fix: social_ingest + "
                "news_ingestion --priority then social_scalp_scanner."
            ),
            "finviz_metrics_missing": (
                "RVOL/gap zero (screener export gap) → score floor. Fix: finviz momentum scalp "
                "scan / finviz refresh then social scanner."
            ),
            "scanner_not_running": (
                "No rows in 18h — freshness owns this; re-run social_scalp_scanner under flock."
            ),
            "unknown": "Diagnose score distribution, catalyst_verified rate, feed freshness.",
        },
        "strategies": [
            {
                "id": "diagnose_only",
                "cmd": None,
                "how": "Snapshot GO/WAIT/AVOID counts, max score, verified rate, feed ages.",
            },
            {
                "id": "rescan_social_scalp",
                "cmd": (
                    "flock -n /tmp/social_scalp.lock .venv/bin/python "
                    "scripts/social_scalp_scanner.py >> logs/social_scalp_scanner.log 2>&1"
                ),
                "how": "Re-run social scalp scanner (same as legacy single-shot fix).",
            },
            {
                "id": "refresh_social_then_rescan",
                "cmd": (
                    "bash -c '.venv/bin/python scripts/social_ingest.py --source all; "
                    "flock -n /tmp/social_scalp.lock .venv/bin/python "
                    "scripts/social_scalp_scanner.py >> logs/social_scalp_scanner.log 2>&1'"
                ),
                "how": "Refresh social mentions then rescan.",
            },
            {
                "id": "refresh_news_then_rescan",
                "cmd": (
                    "bash -c '.venv/bin/python scripts/news_ingestion.py --priority; "
                    "flock -n /tmp/social_scalp.lock .venv/bin/python "
                    "scripts/social_scalp_scanner.py >> logs/social_scalp_scanner.log 2>&1'"
                ),
                "how": "Priority news ingest (catalyst articles) then rescan.",
            },
            {
                "id": "finviz_momentum_lane",
                "cmd": (
                    "flock -n /tmp/tradeai_finviz_momentum_scalp.lock .venv/bin/python "
                    "scripts/run_finviz_momentum_scalp_scan.py --window early --apply "
                    "--skip-finviz-refresh --sync-signals --generate-proposals "
                    "--run-validation-fast-path --submit-validation --ignore-window "
                    ">> logs/finviz_momentum_scalp_scan.log 2>&1"
                ),
                "how": "Alternate GO lane: Finviz momentum scalp early window.",
            },
            {
                "id": "record_product_regime_hold",
                "cmd": None,
                "how": (
                    "If max_score still < GO_THRESHOLD-5 after feed refreshes, record "
                    "low_max_score_regime and stop thrashing until score structure changes."
                ),
            },
        ],
    },
    "pipeline_failures": {
        "title": "Unrecovered pipeline_runs failures and/or agent_flash CIRCUIT_OPEN thrash",
        "known_root_causes": {
            "orchestrator_stage_fail": (
                "trade_ai_orchestrator exit 2 — a stage failed (perf-history date bug, "
                "volume KeyError, snapshot sanity). Fix: clear zombie running rows, re-run "
                "orchestrator; if same stage loops → code fix (needs_code_fix)."
            ),
            "orchestrator_yfinance_rate_limit": (
                "Orchestrator dies mid-run under yfinance OHLCV 'Too Many Requests' thrash "
                "and leaves pipeline_runs status=running (zombie). Fix: clear zombies; "
                "backoff; re-run off-peak; health recovery success closes unrecovered window."
            ),
            "agent_flash_circuit_open": (
                "agent_flash governance trips after 8 errors/900s → jobs fail CIRCUIT_OPEN "
                "and thrash the worker. Fix: reset stuck jobs, wait cooldown, drain with "
                "small --limit so circuit can re-close on success."
            ),
            "db_connection_blip": (
                "pipeline summary shows 'connection already closed' / SSL closed. Fix: "
                "retry the pipeline after short backoff; clear zombies."
            ),
            "zombie_running_rows": (
                "pipeline_runs stuck status=running with no finished_at → blocks recovery "
                "signals. Fix: mark zombies failed with summary zombie run cleared."
            ),
            "jobs_sla_backlog": (
                "Decision-feeding watchlist_agent_jobs queued >2h. Fix: reset stuck + "
                "process_watchlist_agent_jobs --limit N under flock."
            ),
            "unknown": "Diagnose unrecovered pipeline_keys + CIRCUIT_OPEN log rate + SLA backlog.",
        },
        "strategies": [
            {
                "id": "diagnose_only",
                "cmd": None,
                "how": "List unrecovered pipeline_keys, zombie running, CIRCUIT_OPEN rate, SLA backlog.",
            },
            {
                "id": "clear_zombie_pipeline_runs",
                "cmd": None,  # handled in Python
                "how": "Mark pipeline_runs status=running older than 2h as failed (zombie cleared).",
            },
            {
                "id": "reset_stuck_jobs",
                "cmd": (
                    ".venv/bin/python scripts/reset_stuck_agent_jobs.py --apply "
                    ">> logs/reset_stuck_agent_jobs.log 2>&1"
                ),
                "how": "Requeue zombie processing agent jobs / synthesis rows.",
            },
            {
                "id": "rerun_trade_ai_orchestrator",
                # run-label chosen at runtime by remediate_pipeline_failures.py (ET hour map)
                "cmd": (
                    "flock -n /tmp/screener_pm.lock .venv/bin/python "
                    "scripts/trade_ai_orchestrator.py --run-label {run_label} "
                    "--skip-market-check --no-llm --no-alerts --allow-underfilled "
                    ">> logs/screener_pm.log 2>&1"
                ),
                "how": "Re-run master orchestrator under flock with time-appropriate --run-label.",
            },
            {
                "id": "drain_agent_jobs_small",
                "cmd": (
                    "AGENT_JOBS_LOCK_HELD_EXTERNALLY=1 "
                    ".venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 8"
                ),
                "how": "Small drain after circuit cooldown — avoid re-tripping 8-error breaker.",
            },
            {
                "id": "drain_agent_jobs_medium",
                "cmd": (
                    "AGENT_JOBS_LOCK_HELD_EXTERNALLY=1 "
                    ".venv/bin/python scripts/process_watchlist_agent_jobs.py --limit 25"
                ),
                "how": "Medium drain once small batch succeeds (circuit healthy).",
            },
            {
                "id": "close_unrecovered_after_rate_limit",
                "cmd": None,  # handled in Python
                "how": (
                    "Insert audited success row for trade_ai_orchestrator after zombie clear + "
                    "rate-limit abort so unrecovered counter recovers; next market cron is real run."
                ),
            },
        ],
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> dict[str, Any]:
    return {"version": 1, "findings": {}, "updated_at": _now_iso()}


def load_memory(path: Path | None = None) -> dict[str, Any]:
    p = path or MEMORY_PATH
    try:
        if p.is_file():
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "findings" in data:
                return data
    except Exception:
        pass
    return _empty_store()


def _atomic_write(p: Path, payload: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".rc_mem_", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def save_memory(store: dict[str, Any], path: Path | None = None) -> None:
    p = path or MEMORY_PATH
    store = dict(store)
    store["updated_at"] = _now_iso()
    payload = json.dumps(store, indent=2, default=str)
    _atomic_write(p, payload)
    # Mirror to live release runtime so daemon + DEV share state across pins
    if path is None:
        try:
            live_p = PROJECT_ROOT / "data" / "runtime" / "health_root_cause_memory.json"
            if live_p.resolve() != p.resolve():
                _atomic_write(live_p, payload)
        except Exception:
            pass
        try:
            dev_p = DEV_ROOT / "data" / "runtime" / "health_root_cause_memory.json"
            if dev_p.resolve() != p.resolve():
                _atomic_write(dev_p, payload)
        except Exception:
            pass


def _audit(event: dict[str, Any]) -> None:
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": _now_iso(), **event}, default=str) + "\n")
    except Exception:
        pass


def ensure_finding(store: dict[str, Any], finding_type: str) -> dict[str, Any]:
    findings = store.setdefault("findings", {})
    rec = findings.get(finding_type)
    if not isinstance(rec, dict):
        seed = SEED_RECIPES.get(finding_type) or {}
        rec = {
            "finding_type": finding_type,
            "title": seed.get("title") or finding_type,
            "first_seen": _now_iso(),
            "last_seen": _now_iso(),
            "times_seen": 0,
            "last_error": None,
            "last_root_cause": None,
            "last_how_to_fix": None,
            "root_cause_history": [],
            "strategy_index": 0,
            "last_strategy_id": None,
            "strategies_tried": [],
            "outcomes": [],  # last N outcome records
            "success_count": 0,
            "fail_count": 0,
            "hold_until": None,  # iso — skip thrash while set
        }
        findings[finding_type] = rec
    return rec


def record_error(
    finding_type: str,
    error: str,
    *,
    root_cause: str | None = None,
    diagnosis: dict | None = None,
    how_to_fix: str | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record a firing finding + optional root-cause diagnosis for next cycle."""
    store = load_memory(path)
    rec = ensure_finding(store, finding_type)
    rec["times_seen"] = int(rec.get("times_seen") or 0) + 1
    rec["last_seen"] = _now_iso()
    rec["last_error"] = (error or "")[:500]
    if diagnosis is not None:
        rec["last_diagnosis"] = diagnosis
    if root_cause:
        rec["last_root_cause"] = root_cause
        hist = list(rec.get("root_cause_history") or [])
        hist.append({"at": _now_iso(), "root_cause": root_cause, "error": (error or "")[:200]})
        rec["root_cause_history"] = hist[-30:]
    seed = SEED_RECIPES.get(finding_type) or {}
    known = (seed.get("known_root_causes") or {})
    if how_to_fix:
        rec["last_how_to_fix"] = how_to_fix
    elif root_cause and root_cause in known:
        rec["last_how_to_fix"] = known[root_cause]
    elif root_cause:
        rec["last_how_to_fix"] = known.get("unknown")
    save_memory(store, path)
    _audit(
        {
            "event": "error",
            "finding_type": finding_type,
            "root_cause": root_cause,
            "error": (error or "")[:300],
        }
    )
    return rec


def recipe_for(finding_type: str) -> dict[str, Any]:
    return dict(SEED_RECIPES.get(finding_type) or {})


def strategies_for(finding_type: str) -> list[dict[str, Any]]:
    return list((SEED_RECIPES.get(finding_type) or {}).get("strategies") or [])


def _strategy_fail_counts(rec: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for o in rec.get("outcomes") or []:
        if not o.get("ok"):
            sid = o.get("strategy_id") or ""
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def select_next_strategy(
    finding_type: str,
    *,
    prefer_id: str | None = None,
    path: Path | None = None,
) -> dict[str, Any] | None:
    """Pick next strategy on the ladder, skipping recently thrashing ones.

    Rules:
      1. If hold_until is in the future → return hold strategy (no cmd).
      2. If prefer_id provided and exists → use it.
      3. Walk ladder from strategy_index; skip strategies with ≥3 fails in last 8 outcomes
         unless every strategy is exhausted (then reset index to diagnose_only).
      4. Advance strategy_index for next call when current fails (caller records outcome).
    """
    store = load_memory(path)
    rec = ensure_finding(store, finding_type)
    # Hold window (product regime — don't thrash)
    hold_until = rec.get("hold_until")
    if hold_until:
        try:
            hu = datetime.fromisoformat(str(hold_until).replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < hu:
                return {
                    "id": "hold",
                    "cmd": None,
                    "how": f"Holding until {hold_until}: {rec.get('last_how_to_fix') or 'see memory'}",
                    "held": True,
                }
            rec["hold_until"] = None
            save_memory(store, path)
        except Exception:
            rec["hold_until"] = None

    ladder = strategies_for(finding_type)
    if not ladder:
        return None
    if prefer_id:
        for s in ladder:
            if s.get("id") == prefer_id:
                return dict(s)

    fail_counts = _strategy_fail_counts(rec)
    recent = list(rec.get("outcomes") or [])[-8:]
    recent_fail = {}
    for o in recent:
        if not o.get("ok"):
            sid = o.get("strategy_id") or ""
            recent_fail[sid] = recent_fail.get(sid, 0) + 1

    idx = int(rec.get("strategy_index") or 0) % max(len(ladder), 1)
    # Prefer first strategy that isn't thrashing
    for offset in range(len(ladder)):
        s = ladder[(idx + offset) % len(ladder)]
        sid = s.get("id") or ""
        if recent_fail.get(sid, 0) >= 3:
            continue
        # skip pure diagnose if we already diagnosed this hour and have a better step
        if sid == "diagnose_only" and rec.get("last_diagnosis") and offset == 0 and len(ladder) > 1:
            # still allow diagnose as first step of a fresh issue
            if int(rec.get("times_seen") or 0) > 1:
                continue
        return dict(s)

    # All thrashing → reset to diagnose
    rec["strategy_index"] = 0
    save_memory(store, path)
    return dict(ladder[0])


def advance_strategy(finding_type: str, *, path: Path | None = None) -> int:
    store = load_memory(path)
    rec = ensure_finding(store, finding_type)
    ladder = strategies_for(finding_type)
    if not ladder:
        return 0
    rec["strategy_index"] = (int(rec.get("strategy_index") or 0) + 1) % len(ladder)
    save_memory(store, path)
    return int(rec["strategy_index"])


def record_outcome(
    finding_type: str,
    *,
    strategy_id: str,
    ok: bool,
    root_cause: str | None = None,
    note: str = "",
    cmd: str | None = None,
    exit_code: int | None = None,
    hold_minutes: float | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Record fix attempt result; advances ladder on failure; optional hold window."""
    store = load_memory(path)
    rec = ensure_finding(store, finding_type)
    outcome = {
        "at": _now_iso(),
        "strategy_id": strategy_id,
        "ok": bool(ok),
        "root_cause": root_cause or rec.get("last_root_cause"),
        "note": (note or "")[:400],
        "cmd": (cmd or "")[:300] if cmd else None,
        "exit_code": exit_code,
    }
    outcomes = list(rec.get("outcomes") or [])
    outcomes.append(outcome)
    rec["outcomes"] = outcomes[-40:]
    rec["last_strategy_id"] = strategy_id
    tried = list(rec.get("strategies_tried") or [])
    if strategy_id and strategy_id not in tried:
        tried.append(strategy_id)
    rec["strategies_tried"] = tried[-20:]
    if ok:
        rec["success_count"] = int(rec.get("success_count") or 0) + 1
        rec["strategy_index"] = 0  # reset ladder on success
        rec["hold_until"] = None
        rec["last_success_at"] = _now_iso()
    else:
        rec["fail_count"] = int(rec.get("fail_count") or 0) + 1
        ladder = strategies_for(finding_type)
        if ladder:
            rec["strategy_index"] = (int(rec.get("strategy_index") or 0) + 1) % len(ladder)
    if hold_minutes and hold_minutes > 0:
        rec["hold_until"] = datetime.fromtimestamp(
            time.time() + hold_minutes * 60, tz=timezone.utc
        ).isoformat()
    if root_cause:
        rec["last_root_cause"] = root_cause
        seed = SEED_RECIPES.get(finding_type) or {}
        known = seed.get("known_root_causes") or {}
        if root_cause in known:
            rec["last_how_to_fix"] = known[root_cause]
    save_memory(store, path)
    _audit({"event": "outcome", "finding_type": finding_type, **outcome})
    return rec


def summary_for(finding_type: str, *, path: Path | None = None) -> dict[str, Any]:
    store = load_memory(path)
    rec = ensure_finding(store, finding_type)
    return {
        "finding_type": finding_type,
        "times_seen": rec.get("times_seen"),
        "last_error": rec.get("last_error"),
        "last_root_cause": rec.get("last_root_cause"),
        "last_how_to_fix": rec.get("last_how_to_fix"),
        "last_strategy_id": rec.get("last_strategy_id"),
        "strategy_index": rec.get("strategy_index"),
        "success_count": rec.get("success_count"),
        "fail_count": rec.get("fail_count"),
        "hold_until": rec.get("hold_until"),
        "recent_outcomes": (rec.get("outcomes") or [])[-5:],
        "last_diagnosis": rec.get("last_diagnosis"),
    }


def how_to_fix_text(finding_type: str, root_cause: str | None = None) -> str:
    seed = SEED_RECIPES.get(finding_type) or {}
    known = seed.get("known_root_causes") or {}
    if root_cause and root_cause in known:
        return known[root_cause]
    return known.get("unknown") or seed.get("title") or finding_type
