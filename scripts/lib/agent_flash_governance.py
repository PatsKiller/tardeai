"""Governed DeepSeek Flash path for watchlist agent automation (issue #283).

Replaces ungoverned llm_router process_id + agent_flash labels with registered
process IDs, exact deepseek-v4-flash, reservation ledger, caps, and fail-closed
behavior. No silent provider fallback. No legacy model IDs.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any

# Exact model only
FLASH_MODEL = "deepseek-v4-flash"
FLASH_POLICY = "FAST"
FLASH_THINK_POLICY = "FAST_THINK"

LEGACY_MODEL_IDS = frozenset({
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-v4",
    "deepseek_v4",
    "v4",
})

# task_type → registered process_id
TASK_TO_PROCESS: dict[str, str] = {
    "agent_narrative": "watchlist_maria_flash_narrative",
    "agent_debate": "watchlist_agent_debate_flash",
    "sector_correlation": "watchlist_risk_flash_narrative",
    "cio_synthesis": "watchlist_steph_flash_narrative",
    "catalyst_classification": "watchlist_agent_flash_extract",
    "sentiment": "watchlist_agent_flash_extract",
    "fast_summary": "watchlist_agent_flash_extract",
    "code_generation": "watchlist_agent_flash_extract",
    "default": "watchlist_maria_flash_narrative",
}

# FAST_THINK only for reconciliation / contradiction-style debate
THINK_TASKS = frozenset({"agent_debate"})

# Per-process-run caps (in-memory; daily caps enforced by reservation ledger)
_RUN_LOCK = threading.Lock()
_RUN_COUNTS: dict[str, int] = {}
_RUN_ID = f"run_{int(time.time())}_{os.getpid()}"
_CIRCUIT: dict[str, Any] = {"errors": 0, "open_until": 0.0, "last_error": None}
_DEDUPE_LOCK = threading.Lock()
_DEDUPE_CACHE: dict[str, float] = {}  # hash → epoch
_DEDUPE_TTL_SEC = 6 * 3600
_DEDUPE_PATH = Path(os.environ.get(
    "AGENT_FLASH_DEDUPE_PATH",
    "/tmp/tradeai_agent_flash_dedupe.json",
))

DEFAULT_MAX_INPUT = 4000
DEFAULT_MAX_OUTPUT = 800
DEFAULT_TIMEOUT = 90
MAX_CALLS_PER_RUN = int(os.environ.get("AGENT_FLASH_MAX_CALLS_PER_RUN", "40"))
CIRCUIT_ERROR_THRESHOLD = int(os.environ.get("AGENT_FLASH_CIRCUIT_ERRORS", "8"))
CIRCUIT_COOLDOWN_SEC = int(os.environ.get("AGENT_FLASH_CIRCUIT_COOLDOWN_SEC", "900"))


def reject_legacy_model_id(model_id: str | None) -> None:
    mid = (model_id or "").strip().lower()
    if mid in LEGACY_MODEL_IDS or mid in {x.lower() for x in LEGACY_MODEL_IDS}:
        raise RuntimeError(
            f"LEGACY_MODEL_REJECTED: {model_id!r} is not allowed. "
            f"Use exact {FLASH_MODEL} / policy FAST or FAST_THINK only."
        )


def process_for_task(task_type: str) -> str:
    tt = (task_type or "default").strip()
    return TASK_TO_PROCESS.get(tt) or TASK_TO_PROCESS["default"]


def policy_for_task(task_type: str) -> str:
    tt = (task_type or "").strip()
    if tt in THINK_TASKS:
        return FLASH_THINK_POLICY
    return FLASH_POLICY


def evidence_hash(
    *,
    process_id: str,
    task_type: str,
    prompt: str,
    prompt_version: str = "v1",
    job_key: str | None = None,
) -> str:
    raw = "|".join([
        process_id,
        task_type or "",
        prompt_version,
        job_key or "",
        hashlib.sha256((prompt or "").encode("utf-8", errors="replace")).hexdigest(),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _load_dedupe() -> dict[str, float]:
    try:
        if _DEDUPE_PATH.exists():
            data = json.loads(_DEDUPE_PATH.read_text())
            if isinstance(data, dict):
                return {str(k): float(v) for k, v in data.items()}
    except Exception:
        pass
    return {}


def _save_dedupe(cache: dict[str, float]) -> None:
    try:
        now = time.time()
        pruned = {k: v for k, v in cache.items() if now - v < _DEDUPE_TTL_SEC}
        _DEDUPE_PATH.write_text(json.dumps(pruned))
    except Exception:
        pass


def already_completed(evidence_key: str) -> bool:
    with _DEDUPE_LOCK:
        cache = _load_dedupe()
        cache.update(_DEDUPE_CACHE)
        ts = cache.get(evidence_key)
        if ts is None:
            return False
        if time.time() - ts > _DEDUPE_TTL_SEC:
            return False
        return True


def mark_completed(evidence_key: str) -> None:
    with _DEDUPE_LOCK:
        _DEDUPE_CACHE[evidence_key] = time.time()
        cache = _load_dedupe()
        cache.update(_DEDUPE_CACHE)
        _save_dedupe(cache)


def circuit_open() -> bool:
    return time.time() < float(_CIRCUIT.get("open_until") or 0)


def _trip_circuit(err: str) -> None:
    _CIRCUIT["errors"] = int(_CIRCUIT.get("errors") or 0) + 1
    _CIRCUIT["last_error"] = (err or "")[:200]
    if int(_CIRCUIT["errors"]) >= CIRCUIT_ERROR_THRESHOLD:
        _CIRCUIT["open_until"] = time.time() + CIRCUIT_COOLDOWN_SEC


def _reset_circuit_on_success() -> None:
    _CIRCUIT["errors"] = 0
    _CIRCUIT["open_until"] = 0.0


def _check_run_budget(process_id: str) -> None:
    with _RUN_LOCK:
        n = int(_RUN_COUNTS.get(process_id, 0))
        if n >= MAX_CALLS_PER_RUN:
            raise RuntimeError(
                f"COST_CAP_EXCEEDED: per-run call cap {MAX_CALLS_PER_RUN} "
                f"for process {process_id} ({_RUN_ID})"
            )
        _RUN_COUNTS[process_id] = n + 1


def governed_flash_call(
    prompt: str,
    *,
    task_type: str = "agent_narrative",
    max_tokens: int = DEFAULT_MAX_OUTPUT,
    timeout: float = DEFAULT_TIMEOUT,
    metadata: dict | None = None,
    job_key: str | None = None,
    prompt_version: str = "v1",
    allow_fast_think: bool = True,
) -> dict[str, Any]:
    """Execute one governed DeepSeek Flash call. Fail closed. No silent fallback.

    Returns a result dict compatible with llm_router.get_llm_response consumers:
      success, response, model_used, provider, latency, cost_estimate, tokens, ...
    """
    reject_legacy_model_id(FLASH_MODEL)  # sanity — exact id not in legacy set

    if circuit_open():
        raise RuntimeError(
            f"CIRCUIT_OPEN: agent_flash circuit breaker open until "
            f"{_CIRCUIT.get('open_until')} last={_CIRCUIT.get('last_error')}"
        )

    process_id = process_for_task(task_type)
    policy = policy_for_task(task_type) if allow_fast_think else FLASH_POLICY
    if policy == FLASH_THINK_POLICY and not allow_fast_think:
        policy = FLASH_POLICY

    # Clamp tokens to process registry when available
    from lib import llm_consumption as lc
    cfg = lc.get_process_config(process_id)
    if not cfg.get("registered"):
        raise RuntimeError(f"PROCESS_NOT_REGISTERED: {process_id}")
    proc_out = cfg.get("max_output_tokens")
    proc_in = cfg.get("max_input_tokens")
    effective_out = int(max_tokens or DEFAULT_MAX_OUTPUT)
    if proc_out is not None:
        effective_out = min(effective_out, int(proc_out))
    effective_out = max(1, effective_out)
    if proc_in is not None:
        est_in = max(1, (len(prompt or "") + 3) // 4)
        if est_in > int(proc_in):
            raise RuntimeError(
                f"INPUT_LIMIT_EXCEEDED: prompt ~{est_in} tokens exceeds "
                f"max_input_tokens={proc_in} for {process_id}"
            )

    ekey = evidence_hash(
        process_id=process_id,
        task_type=task_type,
        prompt=prompt,
        prompt_version=prompt_version,
        job_key=job_key,
    )
    if already_completed(ekey):
        return {
            "success": False,
            "error": "DEDUPE_SKIP: identical evidence already completed successfully",
            "provider": "deepseek",
            "model_used": FLASH_MODEL,
            "dedupe": True,
            "evidence_hash": ekey,
            "process_id": process_id,
            "cost_estimate": 0.0,
            "latency": 0.0,
            "response": "",
        }

    _check_run_budget(process_id)

    meta = {
        **(metadata or {}),
        "task_type": task_type,
        "evidence_hash": ekey,
        "run_id": _RUN_ID,
        "governance": "agent_flash_v1",
        "fallback_used": False,
    }

    t0 = time.time()
    try:
        text, prov = lc.gate_and_generate(
            prompt,
            lane="deepseek-flash",
            process_id=process_id,
            task_summary=f"agent_flash:{task_type}:{job_key or ''}"[:160],
            manual_trigger=False,
            timeout=int(timeout or DEFAULT_TIMEOUT),
            model=FLASH_MODEL,
            policy=policy,
            max_tokens=effective_out,
            metadata=meta,
            return_provenance=True,
        )
    except Exception as e:
        _trip_circuit(str(e))
        # No silent fallback — surface failure
        return {
            "success": False,
            "error": str(e)[:300],
            "provider": "deepseek",
            "model_used": FLASH_MODEL,
            "process_id": process_id,
            "requested_policy": policy,
            "latency": round(time.time() - t0, 2),
            "cost_estimate": 0.0,
            "response": "",
            "fallback_used": False,
        }

    latency = round(time.time() - t0, 2)
    returned = (prov or {}).get("returned_model")
    requested = (prov or {}).get("requested_model_id") or FLASH_MODEL
    if returned and returned != FLASH_MODEL:
        _trip_circuit(f"mismatch {returned}")
        return {
            "success": False,
            "error": f"MISMATCHED_RETURNED_MODEL: requested {FLASH_MODEL} returned {returned}",
            "provider": "deepseek",
            "model_used": returned,
            "requested_model_id": requested,
            "returned_model": returned,
            "process_id": process_id,
            "latency": latency,
            "cost_estimate": float((prov or {}).get("estimated_cost_usd") or 0),
            "response": "",
            "fallback_used": bool((prov or {}).get("fallback_used")),
        }

    if (prov or {}).get("fallback_used"):
        _trip_circuit("fallback_used")
        return {
            "success": False,
            "error": "FALLBACK_FORBIDDEN: silent provider fallback is not allowed",
            "provider": "deepseek",
            "model_used": returned or FLASH_MODEL,
            "process_id": process_id,
            "latency": latency,
            "cost_estimate": float((prov or {}).get("estimated_cost_usd") or 0),
            "response": "",
            "fallback_used": True,
        }

    usage = (prov or {}).get("usage") or {}
    cost = (prov or {}).get("estimated_cost_usd")
    _reset_circuit_on_success()
    mark_completed(ekey)

    return {
        "success": True,
        "response": (text or "").strip(),
        "provider": "deepseek",
        "model_used": returned or FLASH_MODEL,
        "requested_model_id": requested,
        "returned_model": returned,
        "requested_policy": (prov or {}).get("requested_policy") or policy,
        "executed_policy": (prov or {}).get("executed_policy") or policy,
        "process_id": process_id,
        "latency": latency,
        "cost_estimate": float(cost) if cost is not None else 0.0,
        "cost_basis": "provider_usage_x_registry_snapshot",
        "tokens": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        },
        "provider_request_id": (prov or {}).get("request_id"),
        "evidence_hash": ekey,
        "fallback_used": False,
        "relative_units": None,  # never treat as USD
    }
