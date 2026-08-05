"""Once-per-market-day CIO digest trigger with material-change gating.

Idempotent across restarts and duplicate scheduler invocations.
No provider call when no material change or digest already complete for the day.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATE_DIR = PROJECT_ROOT / "data" / "runtime" / "rockville"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_DIR / "cio_scheduler_state.json"
ARTIFACTS_DIR = STATE_DIR / "cio_digests"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

PROMPT_VERSION = "rockville-cio-prompt-v1"
POLICY_VERSION = "rockville-watch-cio-v1.0.0"
DEFAULT_DIGEST_TIME = "16:20"  # America/New_York


def market_date_et(now: datetime | None = None) -> str:
    n = now.astimezone(ET) if now else datetime.now(ET)
    return n.date().isoformat()


def is_market_day(d: datetime | None = None) -> bool:
    n = d.astimezone(ET) if d else datetime.now(ET)
    return n.weekday() < 5  # Mon-Fri; holiday calendar can plug in later


def idempotency_key(market_date: str, material_hash: str) -> str:
    return f"cio-watch-digest:{market_date}:{material_hash}:{PROMPT_VERSION}:{POLICY_VERSION}"


def _load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


@dataclass
class CioTriggerDecision:
    action: str  # RUN | SKIP_ALREADY_COMPLETE | SKIP_NO_MATERIAL_CHANGE | SKIP_NOT_MARKET_DAY | SKIP_LOCKED
    market_date: str
    material_hash: str
    dirty: bool
    idempotency_key: str
    reason: str
    provider_call_allowed: bool


def evaluate_cio_trigger(
    material_hash: str,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> CioTriggerDecision:
    """Decide whether to call CIO_DAILY_PRO. Never more than once per market day auto."""
    md = market_date_et(now)
    key = idempotency_key(md, material_hash)
    state = _load_state()
    day = state.get("days") or {}
    day_rec = day.get(md) or {}

    if not is_market_day(now) and not force:
        return CioTriggerDecision(
            action="SKIP_NOT_MARKET_DAY",
            market_date=md,
            material_hash=material_hash,
            dirty=False,
            idempotency_key=key,
            reason="not a market day",
            provider_call_allowed=False,
        )

    # Mark dirty if material hash changed vs last known
    last_hash = state.get("last_material_hash")
    dirty = bool(last_hash is None or last_hash != material_hash)
    if dirty:
        state["dirty"] = True
        state["last_material_hash"] = material_hash
        state["dirty_since"] = datetime.now(ET).isoformat()
        _save_state(state)

    # Successful artifact already for this market date
    if day_rec.get("status") == "COMPLETE" and day_rec.get("artifact_id") and not force:
        return CioTriggerDecision(
            action="SKIP_ALREADY_COMPLETE",
            market_date=md,
            material_hash=material_hash,
            dirty=bool(state.get("dirty")),
            idempotency_key=key,
            reason="successful CIO artifact already exists for market date",
            provider_call_allowed=False,
        )

    # In-flight lock (restart safety)
    if day_rec.get("status") == "IN_FLIGHT" and day_rec.get("idempotency_key") == key:
        return CioTriggerDecision(
            action="SKIP_LOCKED",
            market_date=md,
            material_hash=material_hash,
            dirty=True,
            idempotency_key=key,
            reason="request already in flight for this idempotency key",
            provider_call_allowed=False,
        )

    dirty_now = bool(state.get("dirty", dirty))
    if not dirty_now and not force:
        return CioTriggerDecision(
            action="SKIP_NO_MATERIAL_CHANGE",
            market_date=md,
            material_hash=material_hash,
            dirty=False,
            idempotency_key=key,
            reason="DIRTY is false — publish NO_MATERIAL_CHANGE without provider call",
            provider_call_allowed=False,
        )

    return CioTriggerDecision(
        action="RUN",
        market_date=md,
        material_hash=material_hash,
        dirty=True,
        idempotency_key=key,
        reason="material change and no complete artifact for market date",
        provider_call_allowed=True,
    )


def mark_in_flight(decision: CioTriggerDecision) -> None:
    state = _load_state()
    days = state.setdefault("days", {})
    days[decision.market_date] = {
        "status": "IN_FLIGHT",
        "idempotency_key": decision.idempotency_key,
        "material_hash": decision.material_hash,
        "started_at": datetime.now(ET).isoformat(),
    }
    _save_state(state)


def mark_complete(decision: CioTriggerDecision, artifact: dict) -> Path:
    path = ARTIFACTS_DIR / f"{decision.market_date}_{artifact.get('artifact_id', 'art')}.json"
    path.write_text(json.dumps(artifact, indent=2, default=str), encoding="utf-8")
    state = _load_state()
    days = state.setdefault("days", {})
    days[decision.market_date] = {
        "status": "COMPLETE",
        "idempotency_key": decision.idempotency_key,
        "material_hash": decision.material_hash,
        "artifact_id": artifact.get("artifact_id"),
        "artifact_path": str(path),
        "finished_at": datetime.now(ET).isoformat(),
    }
    state["dirty"] = False
    state["last_successful_artifact_id"] = artifact.get("artifact_id")
    state["last_successful_market_date"] = decision.market_date
    _save_state(state)
    # also write latest pointer
    (STATE_DIR / "cio_latest.json").write_text(
        json.dumps({"path": str(path), "artifact_id": artifact.get("artifact_id"), "market_date": decision.market_date}, indent=2),
        encoding="utf-8",
    )
    return path


def mark_failed(decision: CioTriggerDecision, failure_code: str, message: str) -> None:
    state = _load_state()
    days = state.setdefault("days", {})
    days[decision.market_date] = {
        "status": "FAILED",
        "idempotency_key": decision.idempotency_key,
        "material_hash": decision.material_hash,
        "failure_code": failure_code,
        "message": message[:500],
        "finished_at": datetime.now(ET).isoformat(),
    }
    # keep dirty true so a later retry same day can run once after failure recovery
    state["dirty"] = True
    _save_state(state)


def publish_no_material_change(material_hash: str, *, now: datetime | None = None) -> dict:
    """Deterministic no-call artifact — NEVER claims a DeepSeek provider run."""
    md = market_date_et(now)
    art = {
        "artifact_id": f"nmc-{md}-{material_hash[:12]}",
        "market_date": md,
        "generated_at": datetime.now(ET).isoformat(),
        "watchlist_material_hash": material_hash,
        "previous_artifact_id": (_load_state().get("last_successful_artifact_id")),
        "changed_symbol_count": 0,
        "unchanged_symbol_count": 0,
        "held_position_change_count": 0,
        "executive_stance": {
            "posture": "INSUFFICIENT_EVIDENCE",
            "summary": "No decision-relevant Watchlist fingerprint change since last digest.",
            "confidence": 1.0,
        },
        "operator_priority_queue": [],
        "ready_now": [],
        "waiting_for_confirmation": [],
        "blocked_or_avoid": [],
        "held_position_attention": [],
        "portfolio_level_conflicts": [],
        "sector_and_factor_concentrations": [],
        "next_7_day_events": [],
        "material_catalysts": [],
        "data_quality_and_freshness_risks": [],
        "unresolved_contradictions": [],
        "what_changed_since_prior_digest": [],
        "what_did_not_change": ["watchlist_material_hash unchanged"],
        "evidence_refs": [],
        # Truthful no-call provenance — do not default to DeepSeek model/policy labels.
        "provenance": {
            "provider": None,
            "model": None,
            "policy": "NO_CALL",
            "thinking": False,
            "effort": None,
            "execution": "deterministic_scheduler",
            "artifact_type": "no_change_decision",
            "prompt_version": PROMPT_VERSION,
            "input_hash": material_hash,
            "output_hash": hashlib.sha256(b"NO_MATERIAL_CHANGE").hexdigest(),
            "request_id": None,
            "provider_call_occurred": False,
        },
        "usage": {
            "cache_hit_input_tokens": 0,
            "cache_miss_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "actual_cost_usd": 0.0,
            "latency_ms": 0,
            "finish_reason": "no_provider_call",
        },
        "status": "NO_MATERIAL_CHANGE",
        "failure_code": None,
    }
    # Do not mark COMPLETE with provider cost; store as no-change pointer for the day
    state = _load_state()
    days = state.setdefault("days", {})
    if days.get(md, {}).get("status") != "COMPLETE":
        days[md] = {
            "status": "NO_MATERIAL_CHANGE",
            "material_hash": material_hash,
            "artifact_id": art["artifact_id"],
            "finished_at": art["generated_at"],
        }
        _save_state(state)
    path = ARTIFACTS_DIR / f"{md}_{art['artifact_id']}.json"
    path.write_text(json.dumps(art, indent=2), encoding="utf-8")
    return art


def load_latest_artifact() -> dict | None:
    ptr = STATE_DIR / "cio_latest.json"
    if not ptr.exists():
        # fallback: newest file
        files = sorted(ARTIFACTS_DIR.glob("*.json"), reverse=True)
        if not files:
            return None
        return json.loads(files[0].read_text(encoding="utf-8"))
    meta = json.loads(ptr.read_text(encoding="utf-8"))
    path = Path(meta.get("path") or "")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def load_history(limit: int = 14) -> list[dict]:
    files = sorted(ARTIFACTS_DIR.glob("*.json"), reverse=True)[:limit]
    out = []
    for f in files:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out
