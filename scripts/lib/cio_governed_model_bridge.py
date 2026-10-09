"""CIO Governed Model Bridge — OpenClaw → Trade AI governed LLM boundary.

P-1.2A: Local HTTP server implementing OpenAI-compatible /v1/chat/completions.
Server-side caller→process mapping, canonical governance (registration, model
policy resolution, reservation, cap enforcement, settlement, circuit breaker,
provenance). Mock provider only — no live DeepSeek calls.

P-1.2B: Added RealProvider for live DeepSeek calls through governance pipeline.
Switch with CIO_BRIDGE_MODE=canary env var.

Bind: 127.0.0.1 (never 0.0.0.0). Port: configurable (default 8766).
"""
from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# ── Project root for imports ───────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

log = logging.getLogger("tradeai.cio_bridge")

# Single source of truth for the exact DeepSeek model id (registry + env override).
from lib.llm_model_registry import deepseek_model_id  # noqa: E402

# ── Bind / port config ─────────────────────────────────────────────────
BIND_HOST = os.environ.get("CIO_BRIDGE_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("CIO_BRIDGE_PORT", "8766"))

# ── Provider mode ──────────────────────────────────────────────────────
# "mock" (default) = MockProvider only, zero real calls (P-1.2A)
# "canary" = RealProvider for live DeepSeek calls (P-1.2B)
BIND_MODE = os.environ.get("CIO_BRIDGE_MODE", "mock")

# ── Pre-shared auth header ─────────────────────────────────────────────
AUTH_HEADER = "X-TradeAI-Agent"

# ── Server-side caller → process_id mapping (NEVER trust client) ──────
# Gate-B: All six financial professional agents registered.
CALLER_PROCESS_MAP: dict[str, str] = {
    "alex": "alex_cio_synthesis",
    "maria": "maria_research_critique",
    "steph": "steph_allocation_review",
    "guardian": "guardian_risk_critique",
    "ledger": "ledger_tax_critique",
    "morgan": "morgan_wealth_synthesis",
    "advisory_desk": "advisory_desk_opinion",
    # n8n coordination model job (plan tranche D, 2026-10-07): one caller, one small-cap process.
    "n8n_model_job": "n8n_material_digest_draft",
}

# Task-type overrides for multi-policy callers (server-side only).
CALLER_TASK_PROCESS_MAP: dict[str, dict[str, str]] = {
    # 2026-10-08 (Phase 2 G1): the n8n model-job caller has two small-cap processes, chosen by task type
    # server-side; an unknown task type falls back to the digest (cannot escalate — tested).
    "n8n_model_job": {
        "model_job": "n8n_material_digest_draft",
        "ops_summary": "n8n_ops_summary_draft",
    },
    "advisory_desk": {
        "advisory_opinion": "advisory_desk_opinion",
        "advisory_synthesis": "advisory_desk_synthesis",
        # 2026-09-14: callers that all billed to advisory_desk_opinion, each on its own process id, so
        # the spend report can name them and scheduled work can be moved off-peak (operator decision).
        "operator_reply": "cio_operator_reply",
        "plan_enrichment": "cio_plan_enrichment",
        "prompt_judge": "cio_prompt_judge",
        "research_circle": "research_circle_analyzer",
        "hermes_cloud_json": "hermes_cloud_json",
        "usefulness_score": "hermes_usefulness_score",
        "hermes_research_job": "cio_hermes_research",
        "golden_judge": "hermes_golden_judge",
    },
}

# ── Reservation failure codes → HTTP status ────────────────────────────
# reserve_projected_cost() raises RuntimeError("<MACHINE_CODE>: detail") for
# every governance outcome. Flattening those into RESERVATION_FAILED/500 is a
# defect, not a simplification: classify_failure() lists RESERVATION_FAILED
# under RETRYABLE_TRANSIENT, so a hard cap breach was returned to callers with
# a retry policy that says "retry this". On 2026-09-06 that cost 46,106 rows —
# the caller read HTTP 500, treated it as a transient provider fault, and burned
# its entire remaining queue marking rows FAILED_PROVIDER in a few minutes.
#
# The request-count cap is enforced ONLY inside reserve_projected_cost; the
# check_cost_cap() pre-flight above covers dollar caps alone. So without this
# map there is no path by which a count breach can be reported as anything but
# a server fault.
_RESERVATION_CODE_STATUS: dict[str, int] = {
    "COST_CAP_EXCEEDED": 429,            # -> NON_RETRYABLE_COST. Budget, not fault.
    "COST_CONFIGURATION_INVALID": 500,   # -> NON_RETRYABLE_COST by code.
    "COST_PERSISTENCE_UNAVAILABLE": 503, # -> RETRYABLE_TRANSIENT. A ledger blip.
}


# ── Server-side caller → authorized task_types ─────────────────────────
# Caller-supplied process_id/model_id are never trusted.
# Each caller's task_type → server-selected policy.
CALLER_TASK_POLICY_MAP: dict[str, dict[str, str]] = {
    "alex": {
        "cio_synthesis": "PRO",
        "cio_escalation": "PRO_THINK",
    },
    "maria": {
        "research_critique": "FAST",
        "catalyst_narrative": "FAST",
        "agent_narrative": "FAST",
    },
    "steph": {
        "allocation_review": "PRO",
        "wealth_review": "FAST",
    },
    "guardian": {
        "risk_critique": "FAST",
    },
    "ledger": {
        "tax_critique": "FAST",
    },
    "morgan": {
        "wealth_synthesis": "FAST",
        "goal_tracking": "FAST",
    },
    "advisory_desk": {
        "advisory_opinion": "FAST",
        "advisory_synthesis": "PRO",
    },
}

# ── Policy → model resolution (generalized for all governed agents) ─────
POLICY_RESOLUTION: dict[str, dict[str, Any]] = {
    "PRO": {
        "provider": "deepseek",
        "model_id": deepseek_model_id("PRO"),
        "thinking": "disabled",
        "display_name": "DeepSeek V4.1 Flash (governed)",
    },
    "PRO_THINK": {
        "provider": "deepseek",
        "model_id": deepseek_model_id("PRO_THINK"),
        "thinking": "enabled",
        "reasoning_effort": "high",
        "display_name": "DeepSeek V4.1 Flash Think (governed)",
        "requires_deterministic_escalation_reason": True,
    },
    "FAST": {
        "provider": "deepseek",
        "model_id": deepseek_model_id("FAST"),
        "thinking": "disabled",
        "display_name": "DeepSeek V4.1 Flash (governed)",
    },
    "FAST_THINK": {
        "provider": "deepseek",
        "model_id": deepseek_model_id("FAST_THINK"),
        "thinking": "enabled",
        "display_name": "DeepSeek V4.1 Flash Think (governed)",
    },
}

# ── Legacy model IDs that must be rejected ─────────────────────────────
LEGACY_MODEL_IDS = frozenset({
    "deepseek-chat",
    "deepseek-reasoner",
    "deepseek-v4",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
})


# ── Circuit breaker (in-process, per-bridge instance) ──────────────────
_CIRCUIT: dict[str, Any] = {"errors": 0, "open_until": 0.0, "last_error": None}
CIRCUIT_ERROR_THRESHOLD = int(os.environ.get("CIO_BRIDGE_CIRCUIT_ERRORS", "8"))
CIRCUIT_COOLDOWN_SEC = int(os.environ.get("CIO_BRIDGE_CIRCUIT_COOLDOWN_SEC", "900"))


# ── Upstream deadline and in-flight slots (2026-09-14 bridge wedge) ────
# From 14:45 ET DeepSeek held non-streaming requests ~906 s while trickling keep-alive bytes, so the
# 90 s per-read timeout never fired, and this single-threaded server queued every caller (CIO research,
# desk answers, advisory) behind one held call for ~90 minutes. Each call now has a wall-clock deadline,
# the server is threaded with a bounded number of provider calls, and GET /health reports what is in flight.
UPSTREAM_DEADLINE_S = float(os.environ.get("CIO_BRIDGE_UPSTREAM_DEADLINE_S", "150"))
UPSTREAM_READ_TIMEOUT_S = float(os.environ.get("CIO_BRIDGE_UPSTREAM_READ_TIMEOUT_S", "60"))
MAX_INFLIGHT = int(os.environ.get("CIO_BRIDGE_MAX_INFLIGHT", "4"))
_INFLIGHT: dict[str, float] = {}
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT_SLOTS = threading.BoundedSemaphore(max(1, MAX_INFLIGHT))
_STARTED_AT = time.time()


class UpstreamDeadlineExceeded(Exception):
    """The provider kept one request open past UPSTREAM_DEADLINE_S."""


def read_body_with_deadline(resp: Any, started: float, deadline_s: float | None = None,
                            clock: Any = time.time) -> bytes:
    """Read a streamed response body, giving up at a wall-clock deadline measured from `started`.

    Keep-alive bytes from a provider that is holding the request still turn this loop, so the deadline
    is checked even when no single read ever times out.
    """
    limit = UPSTREAM_DEADLINE_S if deadline_s is None else float(deadline_s)
    buf = bytearray()
    try:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                buf.extend(chunk)
            if clock() - started > limit:
                raise UpstreamDeadlineExceeded(
                    f"upstream kept the request open past {limit:g}s ({len(buf)} bytes received)")
    finally:
        try:
            resp.close()
        except (OSError, RuntimeError, AttributeError):
            pass
    return bytes(buf)


def inflight_snapshot(now: float | None = None) -> dict[str, Any]:
    t = time.time() if now is None else now
    with _INFLIGHT_LOCK:
        starts = list(_INFLIGHT.values())
    return {"inflight": len(starts), "max_inflight": MAX_INFLIGHT,
            "oldest_inflight_s": round(t - min(starts), 1) if starts else None}


# ── Module-level global cap overrides ──────────────────────────────────
GLOBAL_DAILY_USD_CAP = os.environ.get("LLM_GLOBAL_DAILY_USD_CAP")


# ══════════════════════════════════════════════════════════════════════════
#  GOVERNANCE IMPORTS — lazy to avoid circular imports at module load
# ══════════════════════════════════════════════════════════════════════════

_governance_imports_ok: bool | None = None


def _ensure_governance_imports() -> bool:
    global _governance_imports_ok
    if _governance_imports_ok is not None:
        return _governance_imports_ok
    try:
        import lib.llm_consumption as lc_mod  # noqa: F401
        import lib.llm_model_registry as lmr  # noqa: F401
        import lib.consumption_run_manual as crm  # noqa: F401
        _governance_imports_ok = True
        return True
    except Exception as e:
        log.error("Governance imports failed: %s", e)
        _governance_imports_ok = False
        return False


# ══════════════════════════════════════════════════════════════════════════
#  CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════════════════

def circuit_open() -> bool:
    return time.time() < float(_CIRCUIT.get("open_until") or 0)


def _trip_circuit(err: str) -> None:
    _CIRCUIT["errors"] = int(_CIRCUIT.get("errors") or 0) + 1
    _CIRCUIT["last_error"] = (err or "")[:200]
    if int(_CIRCUIT["errors"]) >= CIRCUIT_ERROR_THRESHOLD:
        _CIRCUIT["open_until"] = time.time() + CIRCUIT_COOLDOWN_SEC
        log.error("CIO bridge circuit breaker OPEN until %s", _CIRCUIT["open_until"])


def _reset_circuit() -> None:
    _CIRCUIT["errors"] = 0
    _CIRCUIT["open_until"] = 0.0


# ══════════════════════════════════════════════════════════════════════════
#  IDENTITY RESOLUTION
# ══════════════════════════════════════════════════════════════════════════

def resolve_caller(caller: str | None, task_type: str | None = None) -> str | None:
    """Map caller (+ optional task_type) → process_id. Unknown callers → None.

    Client-supplied process_id is never trusted. Task type is advisory only
    when the caller has an entry in CALLER_TASK_PROCESS_MAP.
    """
    c = (caller or "").strip().lower()
    t = (task_type or "").strip().lower()
    task_map = CALLER_TASK_PROCESS_MAP.get(c) or {}
    if t and t in task_map:
        return task_map[t]
    return CALLER_PROCESS_MAP.get(c)


_CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


def client_request_id_from(value: Any) -> str | None:
    """A caller-supplied request id, accepted only in a bounded safe shape (<= 64 chars of [A-Za-z0-9._:-]).
    It becomes the governed call's `rid`: response id, reservation metadata, journal key and the
    provider_cost event's client_request_id. Anything else -> None -> the bridge mints its own."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text if _CLIENT_REQUEST_ID_RE.match(text) else None


# ── Routing policy (LlmRoutingPolicy@v1) ────────────────────────────────
# One row per registered process. Health is read from on-disk receipts only.
ROUTING_POLICY_SCHEMA = "LlmRoutingPolicy@v1"
ROUTING_POLICY_HEADER = "X-TradeAI-Routing-Policy"
_DEFAULT_ROUTING_POLICY_ID = "default"
_KNOWN_POLICY_NAMES = frozenset({"PRO", "FAST", "PRO_THINK", "FAST_THINK"})
_ROUTING_POLICY_CACHE: dict[str, Any] = {}
_ROUTING_POLICY_LOCK = threading.Lock()
_PROVIDER_SEMAPHORES: dict[str, threading.BoundedSemaphore] = {}
_PROVIDER_SEM_GUARD = threading.Lock()
_HEALTH_NOT_READ = {
    "provider_health": "not_read",
    "provider_health_worst": None,
    "deepseek_balance": "not_read",
    "deepseek_balance_available": None,
    "lanes": {},
}


def normalize_routing_policy_header(value: str | None) -> str:
    """Missing or blank selects policy_id default. Names are truncated to 64 characters."""
    if value is None:
        return _DEFAULT_ROUTING_POLICY_ID
    text = str(value).strip()
    if not text:
        return _DEFAULT_ROUTING_POLICY_ID
    return text[:64]


def _env_path(env_name: str, default: Path) -> Path:
    raw = os.environ.get(env_name)
    if raw:
        return Path(raw)
    return default


def routing_policy_path() -> Path:
    return _env_path("TRADEAI_LLM_ROUTING_POLICY", _PROJECT_ROOT / "config" / "llm_routing_policy.json")


def _receipt_path(env_name: str, default: Path) -> Path:
    """Explicit env wins. A pytest run does not read the host's live receipt.

    Production (no PYTEST_CURRENT_TEST) still reads data/runtime. A test that
    sets TRADEAI_LLM_PROVIDER_HEALTH or TRADEAI_DEEPSEEK_BALANCE_HISTORY reads
    that path, including a fixture it just wrote.
    """
    raw = os.environ.get(env_name)
    if raw:
        return Path(raw)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return Path("/tmp/tradeai-pytest-absent-receipts") / default.name
    return default


def provider_health_path() -> Path:
    return _receipt_path(
        "TRADEAI_LLM_PROVIDER_HEALTH",
        _PROJECT_ROOT / "data" / "runtime" / "llm_provider_health.json",
    )


def deepseek_balance_history_path() -> Path:
    return _receipt_path(
        "TRADEAI_DEEPSEEK_BALANCE_HISTORY",
        _PROJECT_ROOT / "data" / "runtime" / "deepseek_balance_history.jsonl",
    )


def load_routing_policy_document() -> dict[str, Any]:
    """Cache the policy file by path and mtime. A bad file loads as empty, never as healthy."""
    path = routing_policy_path()
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return {}
    with _ROUTING_POLICY_LOCK:
        if _ROUTING_POLICY_CACHE.get("key") == key and isinstance(_ROUTING_POLICY_CACHE.get("doc"), dict):
            return _ROUTING_POLICY_CACHE["doc"]
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        parsed = {}
    if not isinstance(parsed, dict) or parsed.get("schema") not in (None, ROUTING_POLICY_SCHEMA):
        parsed = {}
    with _ROUTING_POLICY_LOCK:
        _ROUTING_POLICY_CACHE["key"] = key
        _ROUTING_POLICY_CACHE["doc"] = parsed
    return parsed


def iter_routing_policies(document: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    loaded = document if isinstance(document, dict) else load_routing_policy_document()
    found: dict[str, dict[str, Any]] = {}
    policies = loaded.get("policies")
    if isinstance(policies, dict):
        for key, block in policies.items():
            if not isinstance(block, dict):
                continue
            found[str(key)] = block
            name = block.get("policy_id")
            if isinstance(name, str) and name.strip():
                found[name.strip()] = block
    if isinstance(loaded.get("processes"), dict):
        name = str(loaded.get("policy_id") or _DEFAULT_ROUTING_POLICY_ID)
        found.setdefault(name, loaded)
    return found


def routing_policy_known(name: str | None) -> bool:
    return normalize_routing_policy_header(name) in iter_routing_policies()


def _policy_block(name: str | None) -> dict[str, Any] | None:
    return iter_routing_policies().get(normalize_routing_policy_header(name))


def provider_concurrency_map(policy_name: str | None = None) -> dict[str, int]:
    block = _policy_block(policy_name) or {}
    raw = block.get("provider_concurrency")
    if not isinstance(raw, dict):
        return {}
    limits: dict[str, int] = {}
    for key, value in raw.items():
        try:
            limit = int(value)
        except (TypeError, ValueError):
            continue
        if limit > 0:
            limits[str(key)] = limit
    return limits


def provider_slot_limit(provider: str, policy_name: str | None = None) -> int:
    """Semaphore size from the loaded policy. An unlisted provider gets one slot, never a code constant."""
    limit = provider_concurrency_map(policy_name).get(str(provider or "deepseek"))
    if isinstance(limit, int) and limit > 0:
        return limit
    return 1


def provider_semaphore(provider: str, policy_name: str | None = None) -> threading.BoundedSemaphore:
    policy_id = normalize_routing_policy_header(policy_name)
    prov = str(provider or "deepseek")
    limit = provider_slot_limit(prov, policy_id)
    key = f"{policy_id}:{prov}:{limit}"
    with _PROVIDER_SEM_GUARD:
        sem = _PROVIDER_SEMAPHORES.get(key)
        if sem is None:
            sem = threading.BoundedSemaphore(limit)
            _PROVIDER_SEMAPHORES[key] = sem
        return sem


def _read_json_object(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.is_file():
        return None, "missing"
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None, "unreadable"
    if not isinstance(parsed, dict):
        return None, "unreadable"
    return parsed, "present"


def _last_jsonl_object(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.is_file():
        return None, "missing"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, "unreadable"
    last: dict[str, Any] | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            last = row
    if last is None:
        return None, "unreadable"
    return last, "present"


def _finding_hits_provider(finding: dict[str, Any], provider: str) -> bool:
    lane = str(finding.get("lane") or "").lower()
    prov = str(provider or "").lower()
    return bool(lane and prov and prov in lane)


def _balance_unavailable(row: dict[str, Any] | None, state: str) -> bool:
    if state != "present" or not isinstance(row, dict):
        return False
    if row.get("is_available") is False:
        return True
    total = row.get("total_balance")
    return isinstance(total, (int, float)) and not isinstance(total, bool) and total <= 0


def _provider_health_status(
    provider: str,
    health: dict[str, Any] | None,
    health_state: str,
    balance_row: dict[str, Any] | None,
    balance_state: str,
) -> str:
    """healthy only when a receipt says the writer ran and the provider is not indicted."""
    indicted = False
    if health_state == "present" and isinstance(health, dict):
        findings = health.get("findings")
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, dict) or finding.get("recovered") is True:
                    continue
                if not _finding_hits_provider(finding, provider):
                    continue
                kind = str(finding.get("kind") or "").upper()
                severity = str(finding.get("severity") or "").upper()
                if severity == "CRITICAL" or kind in {"BILLING", "AUTH"}:
                    indicted = True
                    break
    if provider == "deepseek":
        embedded = health.get("balance") if isinstance(health, dict) else None
        if _balance_unavailable(balance_row, balance_state) or _balance_unavailable(embedded if isinstance(embedded, dict) else None, health_state):
            indicted = True
    if indicted:
        return "unhealthy"
    if health_state == "present" and isinstance(health, dict):
        if str(health.get("worst_severity") or "") in {"OK", "WARN", "CRITICAL"}:
            return "healthy"
    return "unknown"


def read_health_snapshot(row: dict[str, Any] | None) -> dict[str, Any]:
    """Status words only. No paths, prompts, keys, or balance amounts."""
    health, health_state = _read_json_object(provider_health_path())
    balance_row, balance_state = _last_jsonl_object(deepseek_balance_history_path())
    providers: list[str] = []
    if isinstance(row, dict):
        for key in ("primary", "secondary", "fallback"):
            spec = row.get(key)
            if isinstance(spec, dict):
                prov = str(spec.get("provider") or "")
                if prov and prov not in providers:
                    providers.append(prov)
    lanes = {
        prov: _provider_health_status(prov, health, health_state, balance_row, balance_state)
        for prov in providers
    }
    available = None
    if balance_state == "present" and isinstance(balance_row, dict) and "is_available" in balance_row:
        available = bool(balance_row.get("is_available"))
    elif balance_state == "present" and isinstance(balance_row, dict):
        total = balance_row.get("total_balance")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            available = total > 0
    worst = None
    if health_state == "present" and isinstance(health, dict):
        worst = health.get("worst_severity")
    return {
        "provider_health": health_state,
        "provider_health_worst": worst,
        "deepseek_balance": balance_state,
        "deepseek_balance_available": available,
        "lanes": lanes,
    }


def _routing_decision(policy_id: str, lane_chosen: str | None, reason: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_id": policy_id,
        "lane_chosen": lane_chosen,
        "reason": reason,
        "health_snapshot": snapshot,
    }


def _lane_policy_name(spec: dict[str, Any]) -> str:
    name = str(spec.get("policy") or "FAST")
    if name not in _KNOWN_POLICY_NAMES:
        return "FAST"
    return name


def _on_health_unknown(block: dict[str, Any], row: dict[str, Any]) -> str:
    """route, refuse, or empty when the configured value is neither.

    A missing field keeps today's route. A process row overrides the policy.
    """
    if "on_health_unknown" in row:
        raw = row.get("on_health_unknown")
    elif "on_health_unknown" in block:
        raw = block.get("on_health_unknown")
    else:
        return "route"
    text = str(raw or "").strip().lower()
    if text in ("route", "refuse"):
        return text
    return ""


def select_governed_lane(process_id: str, routing_policy: str | None = None) -> dict[str, Any]:
    """Pick a lane, or a typed refusal that must be returned before reservation and before any provider call."""
    policy_id = normalize_routing_policy_header(routing_policy)
    if not routing_policy_known(policy_id):
        decision = _routing_decision(policy_id, None, "unknown_routing_policy", dict(_HEALTH_NOT_READ))
        return {
            "refused": "unknown_routing_policy",
            "refused_status": 400,
            "refused_message": f"Unknown routing policy {policy_id!r}",
            "routing_decision": decision,
        }
    block = _policy_block(policy_id) or {}
    processes = block.get("processes")
    row = processes.get(process_id) if isinstance(processes, dict) else None
    if not isinstance(row, dict):
        decision = _routing_decision(policy_id, None, "process_not_in_routing_policy", dict(_HEALTH_NOT_READ))
        return {"missing_process": True, "routing_decision": decision}
    snapshot = read_health_snapshot(row)
    lanes = snapshot.get("lanes") if isinstance(snapshot.get("lanes"), dict) else {}
    health_gate = bool(row.get("health_gate", True))
    chosen: str | None = None
    reason = "lane_unhealthy"
    primary = row.get("primary") if isinstance(row.get("primary"), dict) else None
    if not health_gate and primary is not None:
        chosen = "primary"
        reason = "health_gate_off"
    elif primary is not None and lanes.get(str(primary.get("provider") or "")) != "unhealthy":
        primary_status = lanes.get(str(primary.get("provider") or ""))
        if primary_status == "healthy":
            chosen = "primary"
            reason = "primary_healthy"
        else:
            choice = _on_health_unknown(block, row)
            if choice == "refuse":
                decision = _routing_decision(policy_id, None, "health_unknown_refused", snapshot)
                return {
                    "refused": "health_unknown",
                    "refused_status": 503,
                    "refused_message": (
                        f"Provider health for process {process_id} is not measured "
                        "and policy on_health_unknown is refuse"
                    ),
                    "routing_decision": decision,
                }
            if choice != "route":
                decision = _routing_decision(policy_id, None, "unknown_health_policy", snapshot)
                return {
                    "refused": "unknown_health_policy",
                    "refused_status": 400,
                    "refused_message": (
                        f"Routing policy {policy_id!r} on_health_unknown must be route or refuse"
                    ),
                    "routing_decision": decision,
                }
            chosen = "primary"
            reason = "health_unknown_routed"
    else:
        for lane_name in ("secondary", "fallback"):
            spec = row.get(lane_name)
            if not isinstance(spec, dict):
                continue
            if lanes.get(str(spec.get("provider") or "")) == "healthy":
                chosen = lane_name
                reason = f"failover_{lane_name}"
                break
    if chosen is None:
        decision = _routing_decision(policy_id, None, "lane_unhealthy", snapshot)
        return {
            "refused": "lane_unhealthy",
            "refused_status": 503,
            "refused_message": f"Every health-gated lane for process {process_id} is unhealthy",
            "routing_decision": decision,
        }
    spec = row.get(chosen)
    if not isinstance(spec, dict):
        decision = _routing_decision(policy_id, None, "lane_unhealthy", snapshot)
        return {
            "refused": "lane_unhealthy",
            "refused_status": 503,
            "refused_message": f"Routing row for process {process_id} has no usable lane",
            "routing_decision": decision,
        }
    policy_name = _lane_policy_name(spec)
    resolved = dict(POLICY_RESOLUTION.get(policy_name, POLICY_RESOLUTION["FAST"]))
    provider = str(spec.get("provider") or resolved.get("provider") or "deepseek")
    resolved["provider"] = provider
    resolved["requested_policy"] = policy_name
    decision = _routing_decision(policy_id, chosen, reason, snapshot)
    decision["provider"] = provider
    decision["requested_policy"] = policy_name
    resolved["routing_decision"] = decision
    resolved["health_gate"] = health_gate
    try:
        resolved["latency_budget_ms"] = float(row.get("latency_budget_ms"))
    except (TypeError, ValueError):
        resolved["latency_budget_ms"] = 0
    try:
        resolved["cost_ceiling_usd"] = float(row.get("cost_ceiling_usd"))
    except (TypeError, ValueError):
        resolved["cost_ceiling_usd"] = 0
    return {"policy": resolved, "routing_decision": decision}


def stream_policy_refusal(process_id: str, routing_policy: str | None, policy: dict[str, Any] | None) -> dict[str, Any] | None:
    """Typed JSON when the stream path's second resolve is not a usable lane.

    None means the lane is usable. A refused lane keeps its code, status, and
    routing_decision. A missing process is UNKNOWN_PROCESS / 400, with the
    not_routed decision execute_governed_call attaches when resolve returns None.
    """
    if (
        isinstance(policy, dict)
        and not policy.get("refused")
        and not policy.get("missing_process")
        and "model_id" in policy
    ):
        return None
    policy_id = normalize_routing_policy_header(routing_policy)
    decision = _routing_decision(policy_id, None, "not_routed", dict(_HEALTH_NOT_READ))
    if isinstance(policy, dict) and isinstance(policy.get("routing_decision"), dict):
        decision = policy["routing_decision"]
    if isinstance(policy, dict) and policy.get("refused"):
        code = str(policy["refused"])
        message = str(policy.get("refused_message") or policy["refused"])
        status = int(policy.get("refused_status") or 503)
    else:
        code = "UNKNOWN_PROCESS"
        message = f"Process '{process_id}' not registered in governance bridge"
        status = 400
    return {
        "error": {"code": code, "message": message, "status": status},
        "id": uuid.uuid4().hex[:12],
        "object": "chat.completion.error",
        "created": int(time.time()),
        "model": "tradeai_governed",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "cost_estimate": 0.0,
        "governance_pass": False,
        "routing_decision": decision,
    }


def unknown_routing_policy_response(policy_name: str | None) -> dict[str, Any]:
    """Refusal body for an unknown header. Does not read health receipts or call a provider."""
    policy_id = normalize_routing_policy_header(policy_name)
    return {
        "error": {
            "code": "unknown_routing_policy",
            "message": f"Unknown routing policy {policy_id!r}",
            "status": 400,
        },
        "id": uuid.uuid4().hex[:12],
        "object": "chat.completion.error",
        "created": int(time.time()),
        "model": "tradeai_governed",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "cost_estimate": 0.0,
        "governance_pass": False,
        "routing_decision": _routing_decision(policy_id, None, "unknown_routing_policy", dict(_HEALTH_NOT_READ)),
    }


def resolve_model_policy(
    process_id: str,
    task_type: str = "",
    routing_policy: str | None = None,
) -> dict[str, Any] | None:
    """Resolve provider, model_id, thinking, display_name, and requested_policy for a process.

    Unknown process_id returns None. An unknown routing policy or an unhealthy gated lane
    returns a refusal dict and does not call a provider.
    """
    selected = select_governed_lane(process_id, routing_policy)
    chosen = selected.get("policy") if isinstance(selected.get("policy"), dict) else None
    policy_name = chosen.get("requested_policy") if isinstance(chosen, dict) else None
    try:  # Wave 4 O-W4-3: the ONE chooser observes (shadow) — disagreement is a receipt, not a change
        try:
            from model_chooser import apply as _choose_apply  # type: ignore
        except ImportError:
            from scripts.lib.model_chooser import apply as _choose_apply  # type: ignore
        _choose_apply(
            process_id,
            "deepseek-flash" if policy_name in (None, "FAST") else "deepseek-pro",
            purpose=task_type,
            site="governed_model_bridge",
        )
    except Exception:  # noqa: BLE001
        pass
    if selected.get("refused"):
        return {
            "refused": selected["refused"],
            "refused_status": int(selected.get("refused_status") or 503),
            "refused_message": str(selected.get("refused_message") or selected["refused"]),
            "routing_decision": selected.get("routing_decision"),
        }
    if selected.get("missing_process") or chosen is None:
        return None
    return chosen


# ══════════════════════════════════════════════════════════════════════════
#  PRIVACY / LOGGING
# ══════════════════════════════════════════════════════════════════════════

def hash_content(content: str) -> str:
    """SHA-256 hash of full prompt/response content for audit trail."""
    return hashlib.sha256((content or "").encode("utf-8", errors="replace")).hexdigest()[:32]


def sanitize_log_summary(messages: list[dict]) -> str:
    """Return a safe summary for logging — role counts, no raw content."""
    parts = []
    for m in (messages or []):
        role = str(m.get("role") or "unknown")
        content_len = len(str(m.get("content") or ""))
        has_tools = "tools" in m
        has_tool_calls = "tool_calls" in m
        extra = []
        if has_tools:
            extra.append("tools")
        if has_tool_calls:
            extra.append("tool_calls")
        suffix = f"({','.join(extra)})" if extra else ""
        parts.append(f"{role}:{content_len}chars{suffix}")
    return "; ".join(parts)


# ══════════════════════════════════════════════════════════════════════════
#  MOCK PROVIDER (P-1.2A only — zero real provider calls)
# ══════════════════════════════════════════════════════════════════════════

class MockProvider:
    """Returns valid OpenAI-compatible chat completion fixtures.

    Supports tool_calls, structured_output, and streaming.
    Never makes any network call.
    """

    _instance: MockProvider | None = None

    def __init__(self) -> None:
        self.call_count = 0
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> MockProvider:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def generate(self, messages: list[dict], model_id: str,
                 tools: list[dict] | None = None,
                 tool_choice: str | None = None,
                 response_format: dict | None = None,
                 stream: bool = False,
                 max_tokens: int = 16384,
                 thinking: str = "disabled",
                 reasoning_effort: str | None = None,
                 client_request_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            self.call_count += 1

        # Check if client is requesting tool calls
        has_tools = bool(tools)
        tool_call_requested = has_tools and (tool_choice is None or tool_choice != "none")

        # Check if structured JSON requested
        has_json_schema = (
            response_format is not None
            and response_format.get("type") == "json_schema"
        )

        if tool_call_requested:
            content = None
            tool_calls = [{
                "id": f"mock_tool_call_{self.call_count}",
                "type": "function",
                "function": {
                    "name": (tools[0].get("function", {}).get("name") if tools
                             else "get_financial_data"),
                    "arguments": json.dumps({
                        "summary": "Governed mock tool response from CIO bridge",
                        "confidence": 0.95,
                        "source": "Trade AI canonical data",
                    }),
                },
            }]
            response_content = None
        elif has_json_schema:
            schema_name = response_format.get("json_schema", {}).get("name", "response")
            content = json.dumps({
                "analysis": f"Governed CIO bridge mock structured response for {schema_name}",
                "status": "ok",
                "model": model_id,
                "provider": "tradeai_governed_mock",
                "confidence": 0.92,
            })
            tool_calls = None
            response_content = content
        else:
            content = (
                f"[CIO Governed Bridge] Mock response for model={model_id}. "
                f"This is a governed, server-authorized response routed through "
                f"Trade AI's canonical LLM boundary. No live provider call was made."
            )
            tool_calls = None
            response_content = content

        return {
            "id": f"cio-bridge-mock-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_id,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_content,
                    **(dict(tool_calls=tool_calls) if tool_calls else {}),
                },
                "finish_reason": "tool_calls" if tool_calls else "stop",
            }],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
            },
            "_tradeai": {
                "mock": True,
                "bridge_version": "P-1.2A",
                "provider": "tradeai_governed_mock",
                "governance_pass": True,
            },
        }

    def generate_stream(self, messages: list[dict], model_id: str,
                        tools: list[dict] | None = None,
                        max_tokens: int = 16384) -> list[str]:
        """Return list of SSE-formatted strings for streaming simulation."""
        response = self.generate(messages, model_id, tools=tools, max_tokens=max_tokens,
                                 stream=False)
        content = response["choices"][0]["message"].get("content") or ""
        if content is None:
            content = ""

        chunks = []
        # Simulate streaming as chunks
        words = content.split()
        for i, word in enumerate(words):
            chunk = {
                "id": response["id"],
                "object": "chat.completion.chunk",
                "created": response["created"],
                "model": response["model"],
                "choices": [{
                    "index": 0,
                    "delta": {"content": word + " "},
                    "finish_reason": None,
                }],
            }
            chunks.append(f"data: {json.dumps(chunk)}\n\n")
        # Final chunk
        final = {
            "id": response["id"],
            "object": "chat.completion.chunk",
            "created": response["created"],
            "model": response["model"],
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
            "usage": response["usage"],
        }
        chunks.append(f"data: {json.dumps(final)}\n\n")
        chunks.append("data: [DONE]\n\n")
        return chunks


# ══════════════════════════════════════════════════════════════════════════
#  REAL PROVIDER (P-1.2B canary — live DeepSeek calls through governance)
# ══════════════════════════════════════════════════════════════════════════

def _emit_bridge_cost(
    *,
    outcome: str,
    model: str | None,
    request_id: str | None = None,
    client_request_id: str | None = None,
    raw_key: str | None = None,
    usage: dict | None = None,
    request_sent: bool = False,
    possibly_billable: bool = False,
    error_class: str | None = None,
) -> None:
    """Direct-bypass emit. RealProvider does not call deepseek_client.chat (tools)."""
    try:
        from lib.provider_cost.emit import emit_cost_event
        usage = usage or {}
        emit_cost_event(
            provider="deepseek",
            model=str(model or ""),
            outcome=outcome,
            request_id=request_id,
            client_request_id=client_request_id,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cache_hit_tokens=usage.get("prompt_cache_hit_tokens") or usage.get("cache_hit_tokens"),
            cache_miss_tokens=usage.get("prompt_cache_miss_tokens") or usage.get("cache_miss_tokens"),
            raw_key=raw_key,
            request_sent=request_sent,
            possibly_billable=possibly_billable,
            error_class=error_class,
            source_service="cio_governed_model_bridge",
            evidence_refs=["cio_governed_model_bridge.RealProvider"],
        )
    except Exception:
        return


class RealProvider:
    """Live DeepSeek V4 provider — governed, exact model, no fallback.

    Uses canonical deepseek_tradeai API key (never logs, never exposes).
    Own HTTP path because tools/tool_choice are not in deepseek_client.chat().
    Emits one ProviderCostEvent per attempt (does not also call chat()).
    """

    _instance: RealProvider | None = None

    def __init__(self) -> None:
        self.call_count = 0
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> RealProvider:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def generate(self, messages: list[dict], model_id: str,
                 tools: list[dict] | None = None,
                 tool_choice: str | None = None,
                 response_format: dict | None = None,
                 stream: bool = False,
                 max_tokens: int = 16384,
                 temperature: float = 0.3,
                 thinking: str = "disabled",
                 reasoning_effort: str | None = None,
                 client_request_id: str | None = None) -> dict[str, Any]:
        if stream:
            raise NotImplementedError("RealProvider does not support streaming in P-1.2B")

        with self._lock:
            self.call_count += 1

        # ── Import deepseek client ──────────────────────────────────────
        try:
            from scripts.lib.deepseek_client import chat as _ds_chat, DeepSeekError  # noqa: F811
            from lib.llm_model_registry import get_deepseek_api_key
        except Exception as e:
            log.error("RealProvider: cannot import deepseek_client: %s", e)
            raise RuntimeError(f"Cannot import deepseek_client: {e}") from e

        # ── Get API key (never log, never expose) ───────────────────────
        key, env_name, _legacy = get_deepseek_api_key()
        if not key:
            raise RuntimeError(
                "DeepSeek API key not configured (canonical env: deepseek_tradeai). "
                "RealProvider requires a configured key for live canary calls."
            )

        # ── Build request body ──────────────────────────────────────────
        import requests as _requests

        body: dict[str, Any] = {
            "model": model_id,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        # deepseek-v4-* default to reasoning mode when `thinking` is omitted, which
        # returns the whole budget as reasoning_content and an EMPTY content — breaking
        # every non-think caller (advisory FAST/PRO, steph, guardian, ledger, morgan).
        # Respect the resolved policy exactly like deepseek_client.chat() does.
        thinking_on = (thinking or "disabled").lower() in ("enabled", "on", "true", "1")
        body["thinking"] = {"type": "enabled"} if thinking_on else {"type": "disabled"}
        if thinking_on and reasoning_effort:
            body["reasoning_effort"] = reasoning_effort

        if tools:
            body["tools"] = tools
            if tool_choice:
                body["tool_choice"] = tool_choice

        # Temperature only in non-thinking mode
        if temperature is not None and not thinking_on:
            body["temperature"] = temperature

        # Response format
        if response_format and response_format.get("type") == "json_object":
            body["response_format"] = {"type": "json_object"}

        # ── Make HTTP call ──────────────────────────────────────────────
        base = "https://api.deepseek.com"
        # 2026-10-08: the caller's request id (the n8n job's correlation_id) is the provider_cost event's
        # client_request_id, so a job receipt can join its cost event. Before, every attempt minted a fresh
        # uuid here and the join never matched (settlement stayed NOT_MEASURED).
        client_rid = client_request_id or uuid.uuid4().hex[:12]
        t0 = time.time()

        try:
            r = _requests.post(
                f"{base}/v1/chat/completions",
                json=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "tradeai-cio-bridge/1.0",
                    "X-TradeAI-Request-Id": client_rid,
                },
                timeout=(10.0, min(UPSTREAM_READ_TIMEOUT_S, UPSTREAM_DEADLINE_S)),
                stream=True,
            )
            raw = read_body_with_deadline(r, t0)
        except (_requests.Timeout, UpstreamDeadlineExceeded) as timeout_exc:
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                client_request_id=client_rid,
                raw_key=key,
                request_sent=True,
                possibly_billable=True,
                error_class="TIMEOUT",
            )
            err = RuntimeError(f"DeepSeek API timeout after {time.time() - t0:.0f}s: {timeout_exc}")
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err
        except _requests.RequestException as e:
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                client_request_id=client_rid,
                raw_key=key,
                request_sent=True,
                possibly_billable=True,
                error_class="NETWORK_ERROR",
            )
            err = RuntimeError(f"DeepSeek API network error: {type(e).__name__}")
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err from e

        latency_ms = int((time.time() - t0) * 1000)
        provider_request_id = r.headers.get("x-request-id", client_rid)

        if r.status_code != 200:
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                request_id=provider_request_id,
                client_request_id=client_rid,
                raw_key=key,
                request_sent=True,
                possibly_billable=True,
                error_class=f"HTTP_{r.status_code}",
            )
            err = RuntimeError(
                f"DeepSeek API returned HTTP {r.status_code}: "
                f"{raw[:500].decode('utf-8', 'replace')}"
            )
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err

        try:
            payload = json.loads(raw)
        except Exception:
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                request_id=provider_request_id,
                client_request_id=client_rid,
                raw_key=key,
                request_sent=True,
                possibly_billable=True,
                error_class="JSON_INVALID",
            )
            err = RuntimeError("DeepSeek API returned non-JSON response")
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err

        returned_model = payload.get("model")
        if returned_model and returned_model != model_id:
            usage_mm = payload.get("usage") or {}
            _emit_bridge_cost(
                outcome="possibly_billable_attempt",
                model=model_id,
                request_id=provider_request_id,
                client_request_id=client_rid,
                raw_key=key,
                usage=usage_mm,
                request_sent=True,
                possibly_billable=True,
                error_class="MISMATCHED_RETURNED_MODEL",
            )
            err = RuntimeError(
                f"Model mismatch: requested {model_id}, returned {returned_model}"
            )
            err.request_sent = True  # type: ignore[attr-defined]
            err.possibly_billable = True  # type: ignore[attr-defined]
            raise err

        choice = (payload.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        finish_reason = choice.get("finish_reason")

        content = msg.get("content")
        # If the model still returned reasoning-only output (thinking ignored / budget
        # exhausted in reasoning), fall back to reasoning_content so the caller never
        # receives an empty answer.
        if not content:
            content = msg.get("reasoning_content") or msg.get("reasoning") or None

        usage = payload.get("usage") or {}
        import hashlib
        raw_hash = hashlib.sha256(raw).hexdigest()[:24]
        _emit_bridge_cost(
            outcome="success",
            model=returned_model or model_id,
            request_id=provider_request_id,
            client_request_id=client_rid,
            raw_key=key,
            usage=usage,
            request_sent=True,
            possibly_billable=True,
        )

        return {
            "id": client_rid,
            "object": "chat.completion",
            "created": int(time.time()),
            "model": returned_model or model_id,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    **({"tool_calls": msg["tool_calls"]} if msg.get("tool_calls") else {}),
                },
                "finish_reason": finish_reason,
            }],
            "usage": usage,
            "_tradeai": {
                "real": True,
                "bridge_version": "P-1.2B",
                "provider": "deepseek",
                "governance_pass": True,
                "provider_request_id": provider_request_id,
                "latency_ms": latency_ms,
                "provenance_hash": raw_hash,
            },
        }


# ══════════════════════════════════════════════════════════════════════════
#  GOVERNANCE PIPELINE
# ══════════════════════════════════════════════════════════════════════════

def execute_governed_call(
    messages: list[dict],
    *,
    process_id: str,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    response_format: dict | None = None,
    stream: bool = False,
    max_tokens: int = 16384,
    request_id: str | None = None,
    routing_policy: str | None = None,
) -> dict[str, Any]:
    """Governed CIO model call pipeline — fail-closed, no silent fallback.

    Pipeline:
      1. Circuit breaker check
      2. Process registration check
      3. Model policy resolution (server-side, ignore client model)
      4. Policy allowlist check
      5. Global + per-process cap check
      6. Reservation
      7. Mock provider response (P-1.2A) — NO live provider
      8. Settlement
      9. Return provenance-rich response

    Returns dict suitable for HTTP JSON response (OpenAI-compatible format).
    On any governance failure, returns error dict with cost_estimate=0.0.
    """
    rid = request_id or uuid.uuid4().hex[:12]
    t0 = time.time()
    selected_policy_id = normalize_routing_policy_header(routing_policy)
    routing_box: dict[str, Any] = {
        "decision": _routing_decision(selected_policy_id, None, "not_routed", dict(_HEALTH_NOT_READ)),
    }

    def _error(code: str, message: str, status: int = 400,
               **extra: Any) -> dict[str, Any]:
        if "retry" not in extra:
            from scripts.lib.cio_provider_retry_v1 import classify_failure

            extra["retry"] = classify_failure(code, http_status=status)
        return {
            "error": {
                "code": code,
                "message": message,
                "status": status,
                **extra,
            },
            "id": rid,
            "object": "chat.completion.error",
            "created": int(time.time()),
            "model": "tradeai_governed",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cost_estimate": 0.0,
            "governance_pass": False,
            "latency_ms": int((time.time() - t0) * 1000),
            "routing_decision": routing_box["decision"],
        }

    if not routing_policy_known(selected_policy_id):
        routing_box["decision"] = _routing_decision(
            selected_policy_id, None, "unknown_routing_policy", dict(_HEALTH_NOT_READ)
        )
        return _error(
            "unknown_routing_policy",
            f"Unknown routing policy {selected_policy_id!r}",
            status=400,
        )

    # ── Step 1: Circuit breaker ────────────────────────────────────────
    if circuit_open():
        return _error(
            "CIRCUIT_OPEN",
            f"CIO bridge circuit breaker open; cooldown until {_CIRCUIT['open_until']}",
            status=503,
            circuit_last_error=_CIRCUIT.get("last_error"),
        )

    # ── Step 2: Process registration ───────────────────────────────────
    if not _ensure_governance_imports():
        return _error(
            "GOVERNANCE_UNAVAILABLE",
            "CIO bridge cannot load governance modules",
            status=503,
        )
    import lib.llm_consumption as lc

    cfg = lc.get_process_config(process_id)
    if not cfg.get("registered"):
        return _error(
            "PROCESS_NOT_REGISTERED",
            f"Process '{process_id}' is not registered in llm_process_registry.json",
            status=404,
        )

    # ── Step 3: Model policy resolution (server-side) ──────────────────
    policy = resolve_model_policy(process_id, routing_policy=selected_policy_id)
    if isinstance(policy, dict) and isinstance(policy.get("routing_decision"), dict):
        routing_box["decision"] = policy["routing_decision"]
    if not isinstance(policy, dict) or policy.get("missing_process"):
        return _error("UNKNOWN_PROCESS", f"Process '{process_id}' not registered in governance bridge", status=400)
    if policy.get("refused"):
        return _error(
            str(policy["refused"]),
            str(policy.get("refused_message") or policy["refused"]),
            status=int(policy.get("refused_status") or 503),
        )
    model_id = policy["model_id"]

    # ── Step 4: Reject legacy model IDs ────────────────────────────────
    import lib.llm_model_registry as lmr
    try:
        lmr.reject_legacy_model_id(model_id)
    except lmr.RegistryError as e:
        return _error("LEGACY_MODEL_REJECTED", str(e), status=400)

    # Policy allowlist check from process config
    ds_pols = [str(x).upper() for x in (cfg.get("deepseek_allowed_policies") or [])]
    requested_policy = policy.get("requested_policy", "PRO")
    if ds_pols and requested_policy not in ds_pols:
        return _error(
            "POLICY_NOT_ALLOWED",
            f"Policy {requested_policy} not allowed for process {process_id}. "
            f"Allowed: {ds_pols}",
            status=403,
        )

    if BIND_MODE == "canary" and str(policy.get("provider") or "deepseek") != "deepseek":
        return _error(
            "provider_not_configured",
            "Live bridge transport is DeepSeek only; this lane's provider is not configured",
            status=503,
        )

    # ── Step 5: Cost cap checks ────────────────────────────────────────
    import lib.consumption_run_manual as crm

    # Validate caps exist
    try:
        crm.validate_paid_cap_config(cfg, require_global=True)
    except RuntimeError as e:
        return _error("COST_CONFIGURATION_INVALID", str(e), status=500)

    worst_case = crm.projected_max_cost_usd(
        model_id=model_id,
        max_input_tokens=cfg.get("max_input_tokens") or 32000,
        max_output_tokens=max_tokens,
    )
    # Caps count actual spend (operator decision 2026-09-14): project what this process's calls
    # have actually cost, not the 32k-token worst case that made a $0.50 cap refuse on phantom money.
    try:
        calibration = lc.calibrated_projected_usd(process_id, worst_case)
    except Exception as exc:  # noqa: BLE001 -- an unmeasurable process stays on the worst case
        calibration = {"projected_usd": worst_case, "basis": f"worst_case_calibration_error:{type(exc).__name__}"}
    projected = float(calibration["projected_usd"])

    try:
        gcap = float(GLOBAL_DAILY_USD_CAP) if GLOBAL_DAILY_USD_CAP not in (None, "") else None
    except (TypeError, ValueError):
        gcap = None

    cap_check = lc.check_cost_cap(process_id, projected_usd=projected, global_cap=gcap)
    if not cap_check.get("allow"):
        return _error(
            "COST_CAP_EXCEEDED",
            f"Cost cap would be exceeded: {cap_check}",
            status=429,
        )

    # ── Step 6: Reservation ────────────────────────────────────────────
    reservation_id: int | None = None
    try:
        reservation_id = lc.reserve_projected_cost(
            process_id, projected,
            model_id=model_id,
            process_config=cfg,
            global_cap=gcap,
            metadata={
                "bridge": "cio_governed",
                "request_id": rid,
                "policy": requested_policy,
            },
        )
    except RuntimeError as e:
        # Preserve the machine code the reservation raised rather than reporting
        # every governance outcome as a server fault.
        code, _, detail = str(e).partition(":")
        code = code.strip().upper()
        status = _RESERVATION_CODE_STATUS.get(code)
        if status is not None:
            log.warning("reservation refused for %s: %s (HTTP %d)", process_id, e, status)
            return _error(code, detail.strip() or str(e), status=status)
        # An unmapped RuntimeError is a genuine fault. Log the traceback: this
        # handler previously discarded it, which is why 2.7 MB of bridge log
        # held zero tracebacks while every request 500'd for 50 minutes.
        log.exception("reservation failed for %s: unmapped RuntimeError", process_id)
        return _error("RESERVATION_FAILED", str(e), status=500)
    except Exception as e:
        log.exception("reservation failed for %s", process_id)
        return _error("RESERVATION_FAILED", f"Unexpected reservation error: {type(e).__name__}",
                      status=500)

    # Real provider calls get a durable side-effect identity before dispatch.
    # Mock calls intentionally remain isolated from the production journal.
    provider_journal = None
    provider_semantic_key: str | None = None
    if BIND_MODE == "canary":
        from scripts.lib.cio_provider_retry_v1 import (
            ProviderRequestJournal,
            semantic_request_key,
        )

        provider_journal = ProviderRequestJournal()
        provider_semantic_key = semantic_request_key(
            request_id=rid,
            process_id=process_id,
            model_id=model_id,
        )
        journal_reservation = provider_journal.reserve(
            semantic_key=provider_semantic_key,
            request_id=rid,
            process_id=process_id,
            provider=str(policy["provider"]),
            model_id=model_id,
            task=str(requested_policy),
            projected_cost_usd=projected,
        )
        if not journal_reservation.get("allowed"):
            lc.settle_reservation(reservation_id, None, ok=False, billable_attempt=False)
            current = journal_reservation.get("current") or {}
            return _error(
                "PROVIDER_REQUEST_REPLAY_BLOCKED",
                "Provider request identity is already dispatched, ambiguous, completed, or exhausted",
                status=409,
                provider_request_state=current.get("state") or journal_reservation.get("reason"),
            )

    if isinstance(routing_box.get("decision"), dict) and reservation_id is not None:
        routing_box["decision"]["reservation_id"] = reservation_id

    # ── Step 7: Provider (mock or real based on BIND_MODE) ──────────────
    if BIND_MODE == "canary":
        provider = RealProvider.instance()
        log.info("RealProvider selected for canary: model=%s policy=%s", model_id, requested_policy)
        assert provider_journal is not None and provider_semantic_key is not None
        provider_journal.record(provider_semantic_key, state="DISPATCHED")
    else:
        provider = MockProvider.instance()
    try:
        try:
            from lib.provider_cost.context import cost_attribution
        except Exception:
            from contextlib import contextmanager as _cm

            @_cm
            def cost_attribution(**_kw):
                yield {}
        with cost_attribution(
            source_service="cio_governed_model_bridge",
            source_process=process_id,
            source_lane=requested_policy,
            reservation_id=str(reservation_id) if reservation_id is not None else None,
            run_id=rid,
        ):
            _provider_slot = provider_semaphore(
                str(policy.get("provider") or "deepseek"),
                selected_policy_id,
            )
            _provider_slot.acquire()
            try:
                response = provider.generate(
                    messages, model_id,
                    tools=tools,
                    tool_choice=tool_choice,
                    response_format=response_format,
                    stream=False,
                    max_tokens=max_tokens,
                    thinking=policy.get("thinking", "disabled"),
                    reasoning_effort=policy.get("reasoning_effort"),
                    client_request_id=rid,
                )
            finally:
                _provider_slot.release()
    except Exception as e:
        provider_name = "RealProvider" if BIND_MODE == "canary" else "MockProvider"
        _trip_circuit(f"provider_failure:{type(e).__name__}:{provider_name}")
        sent = bool(getattr(e, "possibly_billable", False) or getattr(e, "request_sent", False))
        lc.settle_reservation(reservation_id, None, ok=False, billable_attempt=sent)
        retry = None
        if provider_journal is not None and provider_semantic_key is not None:
            from scripts.lib.cio_provider_retry_v1 import classify_failure

            retry = classify_failure(type(e).__name__, request_sent=sent)
            journal_state = "AMBIGUOUS" if sent else (
                "RETRYABLE" if retry["retryable"] else "NON_RETRYABLE"
            )
            provider_journal.record(
                provider_semantic_key,
                state=journal_state,
                retry_disposition=retry["disposition"],
                error_class=type(e).__name__,
                request_sent=sent,
            )
        return _error(
            "PROVIDER_ERROR",
            f"{provider_name} failure: {type(e).__name__}",
            status=500,
            **({"retry": retry} if retry else {}),
        )

    # ── Step 8: Model mismatch check ───────────────────────────────────
    returned_model = response.get("model")
    if returned_model and returned_model != model_id:
        _trip_circuit(f"model_mismatch: expected {model_id}, got {returned_model}")
        lc.settle_reservation(reservation_id, None, ok=False, billable_attempt=False)
        if provider_journal is not None and provider_semantic_key is not None:
            from scripts.lib.cio_provider_retry_v1 import classify_failure

            retry = classify_failure("MODEL_MISMATCH")
            provider_journal.record(
                provider_semantic_key,
                state="NON_RETRYABLE",
                retry_disposition=retry["disposition"],
                error_class="MODEL_MISMATCH",
            )
        return _error(
            "MODEL_MISMATCH",
            f"Provider returned wrong model: expected {model_id}, got {returned_model}",
            status=502,
        )

    # ── Step 9: Settlement ─────────────────────────────────────────────
    usage = response.get("usage") or {}
    try:
        import lib.llm_model_registry as lmr2
        cost_est = lmr2.estimate_usd_cost(
            model_id=model_id,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        actual_cost = cost_est.get("estimated_cost_usd")
    except Exception:
        actual_cost = None

    try:
        lc.settle_reservation(
            reservation_id, actual_cost,
            ok=True,
            billable_attempt=True,
            projected_fallback=projected,
        )
    except Exception as e:
        _trip_circuit(f"settlement_failure:{type(e).__name__}")
        retry = None
        if provider_journal is not None and provider_semantic_key is not None:
            from scripts.lib.cio_provider_retry_v1 import classify_failure

            retry = classify_failure("SETTLEMENT_FAILED", request_sent=True)
            provider_journal.record(
                provider_semantic_key,
                state="AMBIGUOUS",
                retry_disposition=retry["disposition"],
                error_class=type(e).__name__,
                provider_succeeded=True,
            )
        return _error(
            "SETTLEMENT_FAILED",
            f"Settlement persistence failed: {type(e).__name__}",
            status=500,
            **({"retry": retry} if retry else {}),
        )

    if provider_journal is not None and provider_semantic_key is not None:
        provider_meta = response.get("_tradeai") or {}
        provider_journal.record(
            provider_semantic_key,
            state="COMPLETED",
            provider_request_id=provider_meta.get("provider_request_id"),
            usage={
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            },
            actual_cost_usd=actual_cost,
            result_hash=hashlib.sha256(
                json.dumps(response, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest(),
        )

    _reset_circuit()

    # ── Step 10: Assemble response with provenance ─────────────────────
    latency_ms = int((time.time() - t0) * 1000)
    is_mock = BIND_MODE != "canary"
    response["id"] = rid
    response["model"] = model_id
    response["_tradeai"] = {
        **response.get("_tradeai", {}),
        "governance_pass": True,
        "bridge": "cio_governed",
        "bridge_version": "P-1.2B" if BIND_MODE == "canary" else "P-1.2A",
        "process_id": process_id,
        "requested_policy": requested_policy,
        "model_id": model_id,
        "provider": policy["provider"],
        "latency_ms": latency_ms,
        "request_id": rid,
        "reservation_id": reservation_id,
        "cost_estimate": actual_cost,
        "cost_basis": "provider_usage_x_registry_snapshot",
        "legacy_model_ids_rejected": True,
        "client_model_ignored": True,
        "routing_decision": routing_box["decision"],
        "mock": is_mock,
        "provider_request_journal": (
            {
                "schema": "ProviderRequestJournal@v1",
                "semantic_key": provider_semantic_key,
                "state": "COMPLETED",
            }
            if provider_semantic_key else None
        ),
    }

    # ── Step 11: Log (sanitized) — must run before return ──────────────
    try:
        lc.log_call(
            lane=requested_policy.lower(),
            process_id=process_id,
            task_summary=sanitize_log_summary(messages),
            # A process registered as manual (an answer to the operator) is logged as ad hoc, not scheduled.
            trigger_mode="manual" if str(cfg.get("mode") or "") == "manual" else "automated",
            success=True,
            model_name=model_id,
            prompt="[content hashed: " + hash_content(json.dumps(messages)) + "]",
            response="[content hashed: " + hash_content(json.dumps(response)) + "]",
            tokens_in=usage.get("prompt_tokens"),
            tokens_out=usage.get("completion_tokens"),
            duration_ms=latency_ms,
            estimated_cost_usd=actual_cost,
            cost_basis="provider_usage_x_registry_snapshot",
            requested_policy=requested_policy,
            requested_model_id=model_id,
            returned_model=returned_model,
            provider_request_id=rid,
            metadata={
                "governance": "cio_bridge_v1",
                "mock": is_mock,
                "bridge_version": "P-1.2B" if BIND_MODE == "canary" else "P-1.2A",
                "reservation_id": reservation_id,
                **{k: v for k, v in response.get("_tradeai", {}).items()
                   if k not in ("usage",)},
            },
        )
    except Exception:
        pass

    return response


# ══════════════════════════════════════════════════════════════════════════
#  STREAM RE-EMIT (2026-10-09 guardrail audit B, H1)
# ══════════════════════════════════════════════════════════════════════════
# The stream path used to call the provider a SECOND time after execute_governed_call had already
# reserved, called and settled: no reservation, settlement, journal or cost event for that call.
# The governed result is the only provider output a stream may carry; these chunks re-emit it.

_SSE_PIECE = re.compile(r"\S+\s*|\s+")


def governed_result_sse_chunks(result: dict[str, Any]) -> list[str]:
    """SSE chunks for an already-governed chat.completion. Pure: no provider, no governance call.

    Concatenating every ``delta.content`` gives back the governed message content exactly; tool calls
    ride in one delta; the last data chunk carries finish_reason, usage and the governance provenance.
    """
    choices = result.get("choices") or [{}]
    choice = choices[0] if isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}
    content = message.get("content") or ""
    base = {
        "id": result.get("id"),
        "object": "chat.completion.chunk",
        "created": result.get("created") or int(time.time()),
        "model": result.get("model"),
    }

    def _chunk(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> str:
        body = {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **extra}
        return f"data: {json.dumps(body)}\n\n"

    chunks = [_chunk({"role": message.get("role") or "assistant", "content": ""})]
    chunks.extend(_chunk({"content": piece}) for piece in _SSE_PIECE.findall(content))
    if message.get("tool_calls"):
        tool_calls = [
            {**call, "index": i} if isinstance(call, dict) else call
            for i, call in enumerate(message["tool_calls"])
        ]
        chunks.append(_chunk({"tool_calls": tool_calls}))
    finish = choice.get("finish_reason") or ("tool_calls" if message.get("tool_calls") else "stop")
    final_extra: dict[str, Any] = {"usage": result.get("usage") or {}}
    if isinstance(result.get("_tradeai"), dict):
        final_extra["_tradeai"] = result["_tradeai"]
    chunks.append(_chunk({}, finish, **final_extra))
    chunks.append("data: [DONE]\n\n")
    return chunks


# ══════════════════════════════════════════════════════════════════════════
#  CALLER AUTHENTICATION (2026-10-09 guardrail audit B, H2) — REPORT-ONLY first
# ══════════════════════════════════════════════════════════════════════════
# X-TradeAI-Agent is self-asserted. A caller may now also present `Authorization: Bearer <key>`,
# checked in constant time against TRADEAI_BRIDGE_CALLER_KEY_<CALLER> (rotation overlap:
# ..._PREVIOUS). Keys come from the environment only (rendered from Secrets Manager); a key value is
# never logged, returned or written. TRADEAI_BRIDGE_CALLER_AUTH selects the mode:
#   off     - not checked (today's behaviour, no record)
#   report  - DEFAULT: every caller is served exactly as before; an unverified caller is counted and
#             recorded once per caller per hour in data/runtime/bridge_caller_auth_report.jsonl
#   enforce - an unverified caller gets a typed 401 before any reservation or provider call
# Changing callers to send keys is a later PR; this one only measures who still needs one.

CALLER_AUTH_ENV = "TRADEAI_BRIDGE_CALLER_AUTH"
CALLER_AUTH_MODES = ("off", "report", "enforce")
CALLER_AUTH_DEFAULT_MODE = "report"
CALLER_KEY_ENV_PREFIX = "TRADEAI_BRIDGE_CALLER_KEY_"
CALLER_KEY_MIN_LEN = 32
CALLER_AUTH_REPORT_SCHEMA = "BridgeCallerAuthReport@v1"
CALLER_AUTH_VERDICTS = ("verified", "unsigned", "bad_key", "no_key_configured")

_CALLER_AUTH_LOCK = threading.Lock()
_CALLER_AUTH_COUNTS: dict[str, dict[str, int]] = {}
_CALLER_AUTH_REPORTED: set[tuple[str, str]] = set()


def caller_auth_mode() -> str:
    raw = (os.environ.get(CALLER_AUTH_ENV) or CALLER_AUTH_DEFAULT_MODE).strip().lower()
    return raw if raw in CALLER_AUTH_MODES else CALLER_AUTH_DEFAULT_MODE


def caller_key_env_name(caller: str) -> str:
    return CALLER_KEY_ENV_PREFIX + re.sub(r"[^A-Za-z0-9]", "_", str(caller)).upper()


def _caller_keys(caller: str) -> list[bytes]:
    name = caller_key_env_name(caller)
    keys = []
    for env_name in (name, name + "_PREVIOUS"):
        value = os.environ.get(env_name) or ""
        if len(value) >= CALLER_KEY_MIN_LEN:
            keys.append(value.encode("utf-8"))
    return keys


def caller_auth_verdict(caller: str, authorization: str | None) -> str:
    """One of CALLER_AUTH_VERDICTS. Every configured key is compared, in constant time, even after a match."""
    keys = _caller_keys(caller)
    if not keys:
        return "no_key_configured"
    text = (authorization or "").strip()
    if not text.lower().startswith("bearer "):
        return "unsigned"
    presented = text[7:].strip().encode("utf-8")
    if not presented:
        return "unsigned"
    ok = False
    for key in keys:
        ok = hmac.compare_digest(hashlib.sha256(presented).digest(), hashlib.sha256(key).digest()) or ok
    return "verified" if ok else "bad_key"


def caller_auth_report_path() -> Path:
    state_root = os.environ.get("TRADEAI_STATE_ROOT")
    base = Path(state_root) if state_root else _PROJECT_ROOT
    return _receipt_path(
        "TRADEAI_BRIDGE_CALLER_AUTH_REPORT",
        base / "data" / "runtime" / "bridge_caller_auth_report.jsonl",
    )


def caller_auth_snapshot() -> dict[str, Any]:
    with _CALLER_AUTH_LOCK:
        counts = {caller: dict(row) for caller, row in _CALLER_AUTH_COUNTS.items()}
    return {"mode": caller_auth_mode(), "counts": counts}


def _reset_caller_auth() -> None:
    with _CALLER_AUTH_LOCK:
        _CALLER_AUTH_COUNTS.clear()
        _CALLER_AUTH_REPORTED.clear()


def record_caller_auth(caller: str, process_id: str, verdict: str, mode: str) -> None:
    """Count every verdict; append one report line per unverified caller per UTC hour. Never raises."""
    hour = time.strftime("%Y-%m-%dT%H", time.gmtime())
    with _CALLER_AUTH_LOCK:
        row = _CALLER_AUTH_COUNTS.setdefault(caller, {})
        row[verdict] = row.get(verdict, 0) + 1
        counts = dict(row)
        first_this_hour = verdict != "verified" and (caller, hour) not in _CALLER_AUTH_REPORTED
        if first_this_hour:
            _CALLER_AUTH_REPORTED.add((caller, hour))
    if not first_this_hour:
        return
    if os.environ.get("PYTEST_CURRENT_TEST") and not os.environ.get("TRADEAI_BRIDGE_CALLER_AUTH_REPORT"):
        return  # a test that did not name a report file writes none (counter only)
    line = {
        "schema": CALLER_AUTH_REPORT_SCHEMA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hour": hour,
        "caller": caller,
        "process_id": process_id,
        "verdict": verdict,
        "mode": mode,
        "served": mode != "enforce",
        "key_env": caller_key_env_name(caller),
        "key_configured": bool(_caller_keys(caller)),
        "counts": counts,
        "authority": "READ_ONLY_ADVISORY",
    }
    try:
        path = caller_auth_report_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, sort_keys=True) + "\n")
    except OSError:
        log.warning("caller auth report not written (caller=%s verdict=%s)", caller, verdict)


def caller_auth_refusal(caller: str, verdict: str) -> dict[str, Any]:
    code = "CALLER_AUTH_INVALID" if verdict == "bad_key" else "CALLER_AUTH_REQUIRED"
    return {
        "error": {
            "code": code,
            "message": f"Caller '{caller}' is not authenticated ({verdict}); "
                       f"send Authorization: Bearer <{caller_key_env_name(caller)}>",
            "status": 401,
        },
        "id": uuid.uuid4().hex[:12],
        "object": "chat.completion.error",
        "created": int(time.time()),
        "model": "tradeai_governed",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "cost_estimate": 0.0,
        "governance_pass": False,
        "caller_auth": {"mode": "enforce", "verdict": verdict, "key_env": caller_key_env_name(caller)},
    }


# ══════════════════════════════════════════════════════════════════════════
#  HTTP HANDLER
# ══════════════════════════════════════════════════════════════════════════

class GovernedBridgeHandler(http.server.BaseHTTPRequestHandler):
    """OpenAI-compatible /v1/chat/completions handler."""

    server_version = "TradeAI-CIO-Bridge/P-1.2A"

    def log_message(self, fmt: str, *args: Any) -> None:
        """Override to use project logger with sanitization."""
        log.info("HTTP %s", fmt % args)

    def do_GET(self) -> None:
        """Liveness for the watchdog: answers even while provider calls are in flight."""
        if self.path.split("?", 1)[0] != "/health":
            self._send_error(404, "NOT_FOUND", "Only GET /health is supported")
            return
        self._send_json(200, {
            "ok": not circuit_open(),
            "mode": BIND_MODE,
            "pid": os.getpid(),
            "uptime_s": round(time.time() - _STARTED_AT, 1),
            "circuit_open": circuit_open(),
            "circuit_errors": int(_CIRCUIT.get("errors") or 0),
            "last_error": _CIRCUIT.get("last_error"),
            "upstream_deadline_s": UPSTREAM_DEADLINE_S,
            "caller_auth": caller_auth_snapshot(),
            **inflight_snapshot(),
        })

    def do_POST(self) -> None:
        if self.path != "/v1/chat/completions":
            self._send_error(404, "NOT_FOUND", "Only /v1/chat/completions is supported")
            return

        # Auth: require X-TradeAI-Agent header
        caller = self.headers.get(AUTH_HEADER)
        if not caller:
            self._send_error(401, "UNAUTHORIZED",
                             f"Missing {AUTH_HEADER} header")
            return

        task_type = self.headers.get("X-TradeAI-Task-Type") or ""
        process_id = resolve_caller(caller, task_type=task_type)
        if not process_id:
            self._send_error(401, "UNAUTHORIZED",
                             f"Unknown caller '{caller}' — not in server-side mapping")
            return
        if not self._caller_auth_admits(caller, process_id):
            return

        routing_policy_name = normalize_routing_policy_header(self.headers.get(ROUTING_POLICY_HEADER))
        if not routing_policy_known(routing_policy_name):
            self._send_json(400, unknown_routing_policy_response(routing_policy_name))
            return

        # Ring 2 (01 §2): the bridge is the paid path that bypasses gate_and_generate (advisory desk,
        # Hermes worker). A research-class caller must carry X-TradeAI-Context-Id; SHADOW records
        # the miss, ENFORCED answers 428 and spends nothing.
        try:
            try:
                from memory_ring2 import check as _ring2_check, research_class as _ring2_research, MemoryContextRequired as _MCR  # type: ignore
            except ImportError:  # pragma: no cover
                from scripts.lib.memory_ring2 import check as _ring2_check, research_class as _ring2_research, MemoryContextRequired as _MCR  # type: ignore
            _ctx_id = self.headers.get("X-TradeAI-Context-Id") or None
            try:
                from llm_consumption import _registry_process as _reg  # type: ignore
            except ImportError:  # pragma: no cover
                from scripts.lib.llm_consumption import _registry_process as _reg  # type: ignore
            _r2 = _ring2_check("model_bridge", process_id, _ctx_id, required=_ring2_research(process_id, _reg(process_id) or {}),
                               extra={"caller": caller, "task_type": task_type})
        except _MCR as exc:
            self._send_error(428, "MEMORY_CONTEXT_REQUIRED", str(exc)[:300])
            return
        except Exception:  # noqa: BLE001 — Ring 2 failing must never take the bridge down
            pass

        # Read body
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length == 0:
                self._send_error(400, "BAD_REQUEST", "Empty body")
                return
            body = self.rfile.read(content_length)
            data = json.loads(body)
        except json.JSONDecodeError:
            self._send_error(400, "BAD_REQUEST", "Invalid JSON body")
            return
        except Exception:
            self._send_error(400, "BAD_REQUEST", "Cannot read request body")
            return

        messages = data.get("messages") or []
        if not messages:
            self._send_error(400, "BAD_REQUEST", "messages required")
            return

        # Client-supplied model is logged but IGNORED for resolution
        client_model = data.get("model")
        tools = data.get("tools")
        tool_choice = data.get("tool_choice")
        response_format = data.get("response_format")
        stream = bool(data.get("stream", False))
        max_tokens = int(data.get("max_tokens") or 16384)
        # 2026-10-08: the body's request_id was read nowhere, so execute_governed_call minted its own and the
        # caller's correlation id never reached the cost event. Shape-checked; anything else is ignored.
        request_id = client_request_id_from(data.get("request_id"))

        # Reject client-supplied legacy model IDs
        if client_model and client_model.strip().lower() in LEGACY_MODEL_IDS:
            self._send_error(400, "LEGACY_MODEL_REJECTED",
                             f"Legacy model {client_model!r} is rejected. "
                             f"Server resolves model independently.")
            return

        # Reject client arbitrary process/model injection
        client_process = data.get("process_id") or data.get("process")
        if client_process and str(client_process).strip().lower() != "alex_cio_synthesis":
            log.warning("Client attempted arbitrary process_id: %s", client_process)
            self._send_error(403, "PROCESS_ID_REJECTED",
                             "Client-supplied process_id is rejected. "
                             "Server resolves process from caller identity.")
            return

        # Execute governed call. A bounded number at once: when every slot is held, answer 503 now
        # rather than queue the caller behind a provider that is holding requests (2026-09-14).
        if not _INFLIGHT_SLOTS.acquire(blocking=False):
            self._send_error(503, "BRIDGE_BUSY",
                             f"{MAX_INFLIGHT} provider calls already in flight; retry later")
            return
        call_id = uuid.uuid4().hex
        with _INFLIGHT_LOCK:
            _INFLIGHT[call_id] = time.time()
        try:
            result = execute_governed_call(
                messages,
                process_id=process_id,
                tools=tools,
                tool_choice=tool_choice,
                response_format=response_format,
                stream=stream,
                max_tokens=max_tokens,
                request_id=request_id,
                routing_policy=routing_policy_name,
            )
        finally:
            with _INFLIGHT_LOCK:
                _INFLIGHT.pop(call_id, None)
            _INFLIGHT_SLOTS.release()

        # Check for governance error
        if "error" in result:
            status = result["error"].get("status", 500)
            self._send_json(status, result)
            return

        # Streaming support
        if stream:
            self._send_stream(result, messages, process_id, tools, max_tokens, routing_policy_name)
        else:
            self._send_json(200, result)

    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-TradeAI-Governed", "cio_bridge_p1_2a")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, code: str, message: str) -> None:
        result = {
            "error": {"code": code, "message": message, "status": status},
            "id": uuid.uuid4().hex[:12],
            "object": "chat.completion.error",
            "created": int(time.time()),
            "model": "tradeai_governed",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "cost_estimate": 0.0,
            "governance_pass": False,
        }
        self._send_json(status, result)

    def _caller_auth_admits(self, caller: str, process_id: str) -> bool:
        """False only in enforce mode for an unverified caller, after a typed 401 is sent (H2)."""
        mode = caller_auth_mode()
        if mode == "off":
            return True
        verdict = caller_auth_verdict(caller, self.headers.get("Authorization"))
        record_caller_auth(caller, process_id, verdict, mode)
        if mode == "enforce" and verdict != "verified":
            self._send_json(401, caller_auth_refusal(caller, verdict))
            return False
        return True

    def _send_stream(self, result: dict, messages: list, process_id: str,
                     tools: list | None, max_tokens: int, routing_policy: str | None = None) -> None:
        # 2026-10-09 (audit B, H1): `result` is already governed - reserved, capped, called once and
        # settled. Re-emit it; never resolve or call a provider again here.
        del messages, process_id, tools, max_tokens, routing_policy
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        # No Content-Length on a stream, so the end of the body is the close; "keep-alive" here left
        # the server waiting on the socket after [DONE] and a reader without SSE parsing never returned.
        self.send_header("Connection", "close")
        self.close_connection = True
        self.send_header("X-TradeAI-Governed", f"cio_bridge_{'p1_2b' if BIND_MODE == 'canary' else 'p1_2a'}")
        self.end_headers()
        chunks = governed_result_sse_chunks(result)
        for chunk in chunks:
            self.wfile.write(chunk.encode("utf-8"))
            self.wfile.flush()


# ══════════════════════════════════════════════════════════════════════════
#  SERVER LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════

def start_server(host: str = BIND_HOST, port: int = BIND_PORT) -> http.server.HTTPServer:
    """Start the CIO governed bridge server (blocking)."""
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"CIO bridge must bind to loopback only, got {host}")

    # Threaded: one call held by the provider must not block every other caller (2026-09-14).
    server = http.server.ThreadingHTTPServer((host, port), GovernedBridgeHandler)
    server.daemon_threads = True
    log.info("CIO Governed Bridge starting on %s:%d", host, port)
    log.info("Caller map: %s", CALLER_PROCESS_MAP)
    log.info("Mode: %s", "REAL (canary)" if BIND_MODE == "canary" else "MOCK (P-1.2A)")
    return server


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    version_label = "P-1.2B (canary)" if BIND_MODE == "canary" else "P-1.2A"
    provider_label = "REAL" if BIND_MODE == "canary" else "MOCK"
    log.info("CIO Governed Model Bridge %s", version_label)
    log.info("Bind: %s:%d | Auth: %s | Provider: %s", BIND_HOST, BIND_PORT, AUTH_HEADER, provider_label)

    server = start_server()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down CIO bridge")
        server.shutdown()


if __name__ == "__main__":
    main()
