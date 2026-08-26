"""agent_runtime_instrumentation.py — flag-gated material-wake observability hooks.

READ_ONLY_ADVISORY. This is the MINIMUM additive seam that lets a live material
wake emit ContextEnvelope@v1 and/or an AgentRunTrace@v1 — WITHOUT changing any
decision semantics.

Flags come ONLY from ``agent_feature_flags.load_feature_flags()``:

  * AGENT_CONTEXT_ENVELOPE=0 and AGENT_RUN_TRACE=0  -> exact pre-AIF behavior;
    nothing is built, nothing is appended, nothing is mutated (parity).
  * AGENT_CONTEXT_ENVELOPE=1  -> build ContextEnvelope@v1 via get_context_for_agent().
  * AGENT_RUN_TRACE=1         -> create ONE wake_id/trace_id lineage and append
    one structured, redacted AgentRunTrace@v1.

Invariants:

  * MEMORY_BEHAVIOR_INFLUENCE is NEVER enabled here (memory stays shadow/off).
  * Hooks FAIL SOFT: any observability failure returns an ``errors`` list and
    never fabricates financial truth, never mutates a decision, never raises.
  * Zero broker/order/stop/2FA/risk-policy mutation.

No network, no secrets, no side effects beyond the (flag-gated) trace append.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import os

from scripts.lib.agent_context_envelope import get_context_for_agent
from scripts.lib.agent_feature_flags import load_feature_flags
from scripts.lib.agent_run_trace import (
    DEFAULT_TRACE_PATH,
    append_trace,
    build_trace,
    new_trace_id,
)

ROLE_MATERIAL_SCAN = "material_scan"


def instrument_material_wake(
    wake: dict[str, Any],
    *,
    flags: Optional[dict[str, Any]] = None,
    memory_provider: Any = None,
    trace_path: Optional[Path | str] = None,
    decision_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Flag-gated observability hook for one material wake. Never raises.

    Returns a packet with:

      * ``instrumented``   — True only when at least one observability flag is on
      * ``wake_id``        — the canonical wake id (propagated to the trace)
      * ``trace_id``       — one deterministic trace id (same lineage downstream)
      * ``envelope``       — ContextEnvelope@v1 or None
      * ``trace``          — built AgentRunTrace@v1 or None
      * ``trace_appended`` — whether the trace was actually persisted
      * ``errors``         — any fail-soft observability errors

    With both flags off this returns immediately (instrumented=False, no build,
    no append) — byte-for-byte pre-AIF behavior.
    """
    flags = flags if flags is not None else load_feature_flags()
    envelope_on = int(flags.get("AGENT_CONTEXT_ENVELOPE") or 0) == 1
    trace_on = int(flags.get("AGENT_RUN_TRACE") or 0) == 1

    wake_id = str((wake or {}).get("wake_id") or "") or f"wake_{new_trace_id()}"
    if not envelope_on and not trace_on:
        return {
            "instrumented": False,
            "wake_id": wake_id,
            "trace_id": None,
            "envelope": None,
            "trace": None,
            "trace_appended": False,
            "errors": [],
        }

    errors: list[str] = []
    trace_id = new_trace_id(wake_id)

    envelope: Optional[dict[str, Any]] = None
    if envelope_on:
        try:
            attached = memory_provider
            if attached is None:
                provider_name = str(flags.get("MEMORY_PROVIDER") or "null")
                shadow = int(flags.get("MEMORY_SHADOW") or 0) == 1
                gov = str(os.environ.get("GOVERNED_MEMORY_ADVISORY_INFLUENCE") or "OFF").strip().upper()
                if provider_name in {"durable", "local"} and (
                    shadow or gov in {"SHADOW", "CANARY", "ACTIVE_ADVISORY"}
                ):
                    from scripts.lib.agent_memory_provider import get_memory_provider
                    attached = get_memory_provider(flags)
            wake_d = wake if isinstance(wake, dict) else {"wake_id": wake_id}
            try:
                from scripts.lib.cio_persistent_cognition import extract_symbols

                wake_symbols = extract_symbols(wake_d)
            except Exception:
                wake_symbols = []
            envelope = get_context_for_agent(
                agent="alex",
                wake=wake_d,
                memory_provider=attached,
                symbols=wake_symbols or None,
            )
        except Exception as exc:  # noqa: BLE001 — fail-soft observability boundary
            errors.append(f"envelope:{type(exc).__name__}")
            envelope = None

    trace: Optional[dict[str, Any]] = None
    trace_appended = False
    if trace_on:
        try:
            wake_d = wake if isinstance(wake, dict) else {}
            mem_ids = []
            if isinstance(envelope, dict):
                mem_ids = list((envelope.get("episodic_memory") or {}).get("memory_ids") or [])
            trace = build_trace(
                trace_id=trace_id,
                wake_id=wake_id,
                agent="alex",
                role=ROLE_MATERIAL_SCAN,
                trigger=wake_d.get("trigger") or wake_d.get("category") or wake_d.get("wake_type"),
                context_digest=(
                    envelope.get("provenance", {}).get("context_digest")
                    if isinstance(envelope, dict) else None
                ),
                decision_ids=list(decision_ids or []) or None,
                memory_ids=mem_ids or None,
                memory_behavior_influence=str(flags.get("MEMORY_BEHAVIOR_INFLUENCE") or "0"),
                memory_authority="NON_AUTHORITATIVE_CONTEXT",
            )
            dest = Path(trace_path) if trace_path is not None else DEFAULT_TRACE_PATH
            trace_appended = append_trace(trace, path=dest)
        except Exception as exc:  # noqa: BLE001 — fail-soft observability boundary
            errors.append(f"trace:{type(exc).__name__}")
            trace = None
            trace_appended = False

    return {
        "instrumented": True,
        "wake_id": wake_id,
        "trace_id": trace_id,
        "envelope": envelope,
        "trace": trace,
        "trace_appended": trace_appended,
        "errors": errors,
    }


def default_trace_path() -> Path:
    """The governed trace path used when the caller does not override it."""
    return Path(DEFAULT_TRACE_PATH)
