"""Advisory Desk Phase 5 — shadow session runner.

Runs one operator-only advisory session under ADVISORY_DESK_V1 (optional live
Flash via env), records gates for the 20-session shadow track:

  - validation / plausibility / invariants
  - spend within budget
  - useful-rate from feedback (actionable rows)
  - changed-row estimate (material hash vs prior session)
  - specialist shadow artifacts (Guardian / Ledger)

Authority: READ_ONLY_ADVISORY. No broker paths.
"""
from __future__ import annotations

import fcntl
import json
import os
import statistics
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = PROJECT_ROOT / "data" / "runtime"
SHADOW_DIR = RUNTIME / "advisory_shadow"
SESSIONS_PATH = SHADOW_DIR / "sessions.jsonl"
SCOREBOARD_PATH = SHADOW_DIR / "scoreboard.json"
ARTIFACTS_DIR = SHADOW_DIR / "artifacts"

DEFAULT_SESSION_BUDGET_USD = 0.05
TARGET_SESSIONS = 20  # Phase 5 shadow track
PROMOTION_SESSIONS = 30  # Phase 7 final promotion
USEFUL_RATE_TARGET = 0.60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, default=str, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _useful_rate() -> dict[str, Any]:
    """Compute useful rate on feedback for actionable-style ratings."""
    from lib.advisory.advisory_memory import FEEDBACK_PATH, _read_jsonl as _rj

    fb = _rj(FEEDBACK_PATH)
    useful = notuseful = 0
    for e in fb:
        r = (e.get("rating") or "").lower()
        if r == "useful":
            useful += 1
        elif r == "notuseful":
            # indefensible if operator marks WRONG_FACT on material call
            notuseful += 1
    n = useful + notuseful
    rate = (useful / n) if n else None
    indefensible = sum(
        1 for e in fb
        if (e.get("rating") or "").lower() == "notuseful"
        and (e.get("reason_code") or "").upper() == "WRONG_FACT"
    )
    return {
        "useful": useful,
        "notuseful": notuseful,
        "n": n,
        "useful_rate": rate,
        "indefensible_wrong_fact": indefensible,
        "meets_60pct": (rate is not None and rate >= USEFUL_RATE_TARGET and n >= 5),
    }


def _hash_set_from_rows(rows: list[dict[str, Any]]) -> set[str]:
    return {str(r.get("advisory_row_hash") or "") for r in rows if r.get("advisory_row_hash")}


def run_shadow_session(
    *,
    live_llm: bool | None = None,
    max_rows: int = 10,
    budget_usd: float = DEFAULT_SESSION_BUDGET_USD,
    run_specialists: bool = True,
    session_label: str = "",
) -> dict[str, Any]:
    """Execute one shadow session and append to sessions.jsonl."""
    from lib.data_broker.advisory_desk import (
        build_advisory_desk,
        enrich_advisory_with_opinions,
    )

    session_id = str(uuid.uuid4())[:12]
    t0 = datetime.now(timezone.utc)

    # Operator-only live path: env ADVISORY_DESK_V1=true or explicit live_llm
    if live_llm is None:
        live_llm = os.environ.get("ADVISORY_DESK_V1", "").strip().lower() in (
            "1", "true", "yes", "on",
        )
    if live_llm:
        os.environ["ADVISORY_DESK_V1"] = "true"
        # Ensure global cap present for paid path
        os.environ.setdefault("LLM_GLOBAL_DAILY_USD_CAP", "0.25")

    desk = build_advisory_desk(force=True, max_age_s=0)
    data = desk.get("data") or {}
    meta = data.get("metadata") or {}
    rows = data.get("rows") or []
    hashes = _hash_set_from_rows(rows)

    # Prior session hashes for changed-row count
    prior_sessions = _read_jsonl(SESSIONS_PATH)
    prior_hashes: set[str] = set()
    if prior_sessions:
        prior_hashes = set(prior_sessions[-1].get("row_hashes") or [])
    changed = len(hashes - prior_hashes) if prior_hashes else len(hashes)
    unchanged = len(hashes & prior_hashes) if prior_hashes else 0

    enrich = enrich_advisory_with_opinions(
        desk,
        max_rows=max_rows,
        dry_run=not live_llm,
        include_synthesis=True,
    )
    opinions = enrich.get("opinions") or {}
    telemetry = opinions.get("telemetry") or {}
    spend = float(telemetry.get("cost_usd") or 0.0)

    gates = {
        "validation_ok": bool(meta.get("validation_ok")),
        "plausibility_pass": meta.get("plausibility_gate") == "PASS",
        "invariant_violations": int(meta.get("s4_invariant_violations") or 0),
        "invariants_green": int(meta.get("s4_invariant_violations") or 0) == 0,
        "spend_usd": spend,
        "budget_usd": budget_usd,
        "spend_within_budget": spend <= budget_usd + 1e-9,
        "live_llm": bool(live_llm),
    }
    gates["session_pass"] = (
        gates["validation_ok"]
        and gates["plausibility_pass"]
        and gates["invariants_green"]
        and gates["spend_within_budget"]
    )

    specialists: dict[str, Any] = {}
    if run_specialists:
        try:
            from lib.advisory.specialist_shadow import run_all_specialists
            specialists = run_all_specialists(session_id=session_id, desk=enrich)
        except Exception as e:
            specialists = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    useful = _useful_rate()
    elapsed_ms = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)

    record = {
        "event": "ADVISORY_SHADOW_SESSION",
        "session_id": session_id,
        "ts": _now_iso(),
        "label": session_label or ("live" if live_llm else "dry"),
        "mode": "SHADOW",
        "authority": "READ_ONLY_ADVISORY",
        "gates": gates,
        "metrics": {
            "holdings_rows": meta.get("holdings_rows"),
            "total_rows": meta.get("total_rows") or len(rows),
            "verdict_counts": meta.get("verdict_counts"),
            "changed_rows": changed,
            "unchanged_rows": unchanged,
            "rows_enriched": telemetry.get("rows_enriched"),
            "rows_called": telemetry.get("rows_called"),
            "rows_cache_hit": telemetry.get("rows_cache_hit"),
            "cache_hit_rate": telemetry.get("cache_hit_rate"),
            "actionable_covered": telemetry.get("actionable_covered"),
            "actionable_total": telemetry.get("actionable_total"),
            "synthesis_lead": (opinions.get("synthesis_meta") or {}).get("lead_symbol"),
        },
        "useful_rate": useful,
        "specialists": {
            "ok": specialists.get("ok"),
            "guardian_id": (specialists.get("guardian") or {}).get("artifact_id"),
            "ledger_id": (specialists.get("ledger") or {}).get("artifact_id"),
            "steph_id": (specialists.get("steph") or {}).get("artifact_id"),
            "contradictions": specialists.get("contradictions", 0),
            "darwin_scored": specialists.get("darwin_scored", 0),
            "sentinel_reviews": specialists.get("sentinel_reviews", 0),
        },
        "row_hashes": sorted(hashes),
        "elapsed_ms": elapsed_ms,
        "content_hash": data.get("content_hash"),
    }
    _append_jsonl(SESSIONS_PATH, record)
    scoreboard = rebuild_scoreboard()
    record["scoreboard"] = {
        "sessions_completed": scoreboard.get("sessions_completed"),
        "sessions_passed": scoreboard.get("sessions_passed"),
        "target": TARGET_SESSIONS,
        "promotion_target": PROMOTION_SESSIONS,
        "consecutive_passes": scoreboard.get("consecutive_passes"),
        "median_changed_rows": scoreboard.get("median_changed_rows"),
        "phase5_ready": scoreboard.get("phase5_ready"),
        "phase7_streak_met": scoreboard.get("phase7_streak_met"),
        "promotion_status": scoreboard.get("promotion_status"),
    }
    return record


def rebuild_scoreboard() -> dict[str, Any]:
    sessions = _read_jsonl(SESSIONS_PATH)
    passed = [s for s in sessions if (s.get("gates") or {}).get("session_pass")]
    changed = [int((s.get("metrics") or {}).get("changed_rows") or 0) for s in sessions]
    spends = [float((s.get("gates") or {}).get("spend_usd") or 0) for s in sessions]
    useful = _useful_rate()

    # Specialist artifact counts from disk
    art_n = 0
    if ARTIFACTS_DIR.exists():
        art_n = len(list(ARTIFACTS_DIR.glob("*.json")))

    # Trailing consecutive passes (Phase 7)
    consecutive = 0
    for s in reversed(sessions):
        if (s.get("gates") or {}).get("session_pass"):
            consecutive += 1
        else:
            break

    board = {
        "rebuilt_at": _now_iso(),
        "sessions_completed": len(sessions),
        "sessions_passed": len(passed),
        "target": TARGET_SESSIONS,
        "promotion_target": PROMOTION_SESSIONS,
        "consecutive_passes": consecutive,
        "pass_rate": (len(passed) / len(sessions)) if sessions else None,
        "median_changed_rows": statistics.median(changed) if changed else None,
        "mean_spend_usd": (sum(spends) / len(spends)) if spends else 0.0,
        "max_spend_usd": max(spends) if spends else 0.0,
        "useful_rate": useful,
        "specialist_artifacts_on_disk": art_n,
        "phase5_ready": (
            len(passed) >= TARGET_SESSIONS
            and useful.get("meets_60pct") is True
            and int(useful.get("indefensible_wrong_fact") or 0) == 0
            and art_n >= 20
        ),
        "phase7_streak_met": consecutive >= PROMOTION_SESSIONS,
        "remaining_sessions": max(0, TARGET_SESSIONS - len(passed)),
        "remaining_promotion_sessions": max(0, PROMOTION_SESSIONS - consecutive),
    }
    try:
        from lib.advisory.promotion_gate import load_promotion_state
        prom = load_promotion_state()
        board["promotion_status"] = prom.get("status")
        board["morning_path_default"] = bool(prom.get("morning_path_default"))
    except Exception:
        board["promotion_status"] = "UNKNOWN"
        board["morning_path_default"] = False
    try:
        SHADOW_DIR.mkdir(parents=True, exist_ok=True)
        SCOREBOARD_PATH.write_text(json.dumps(board, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass
    return board


def scoreboard_status() -> dict[str, Any]:
    if SCOREBOARD_PATH.exists():
        try:
            return json.loads(SCOREBOARD_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return rebuild_scoreboard()
