"""memory_ring2 — Ring 2 of the Memory Enforcement Layer (01 §2, Wave 2).

Three existing chokepoints ask this module one question before they do work: *does this call carry a
MemoryContext?* The answer depends on the mode:

  SHADOW   (default, Wave 1/2 rollout)  — record the miss (counter + receipt row) and let the work through
  ENFORCED (per-surface, operator flip)  — refuse: raise ``MemoryContextRequired`` and write a REFUSED row

Chokepoints: ``llm_consumption.gate_and_generate`` (research-class processes), the governed model bridge
(:8766, header ``X-TradeAI-Context-Id``), ``research_thesis_delta.accept_research_result`` (every research
write), ``CIOActionLedger.create_action`` (every CIO action). Which processes count as research-class is
declared, not guessed: ``config/llm_process_registry.json`` ``memory_context_required: true`` per process,
falling back to category ∈ RESEARCH_CATEGORIES.

Mode resolution: ``config/memory_influence_policy.json`` → ``ring2`` → ``{"default": "SHADOW",
"surfaces": {"<surface>": "ENFORCED"}}``; env ``TRADEAI_INTELLIGENCE_MODE`` overrides everything (a global
kill switch back to SHADOW, or a test's ENFORCED). Never raises on its own failures: a broken policy file
means SHADOW.

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0 — this module can only refuse, never act.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path

SCHEMA = "Ring2Decision@v1"
NO_CONSUMER_REASON = (
    "Ring2Decision@v1 rows are appended beside the memory contexts and read by report_platform_conformance "
    "(memory compliance, 01 §6) from Wave 2 tranche 2; the four chokepoints import check() today"
)
RESEARCH_CATEGORIES = frozenset({"Research", "Hermes", "Watch", "AdvisoryDesk", "CIO"})
SURFACES = ("gate_and_generate", "model_bridge", "accept_research_result", "create_action")


class MemoryContextRequired(RuntimeError):
    """Refused in ENFORCED mode: the work carried no MemoryContext. The caller HOLDS."""

    def __init__(self, surface: str, who: str, detail: str = ""):
        super().__init__(f"MEMORY_CONTEXT_REQUIRED at {surface} for {who}: {detail or 'no context_id'} (01 §4: hold, never a raw-store fallback)")
        self.surface = surface
        self.who = who


def _proj_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _policy(env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    p = Path(env.get("TRADEAI_MEMORY_INFLUENCE_POLICY") or _proj_root() / "config" / "memory_influence_policy.json")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def mode_for(surface: str, env: dict | None = None) -> str:
    env = os.environ if env is None else env
    forced = str(env.get("TRADEAI_INTELLIGENCE_MODE", "")).upper()
    if forced in ("SHADOW", "ENFORCED"):
        return forced
    ring2 = (_policy(env).get("ring2") or {})
    m = str((ring2.get("surfaces") or {}).get(surface) or ring2.get("default") or "SHADOW").upper()
    return m if m in ("SHADOW", "ENFORCED") else "SHADOW"


def research_class(process_id: str | None, process_cfg: dict | None = None) -> bool:
    """Is this LLM process one that must retrieve before it generates (03 §4)?"""
    cfg = process_cfg or {}
    if "memory_context_required" in cfg:
        return bool(cfg["memory_context_required"])
    return str(cfg.get("category") or "") in RESEARCH_CATEGORIES


def _receipt(row: dict, env: dict | None = None) -> None:
    """Append a Ring2Decision row beside the memory contexts (fail-soft)."""
    try:
        from intelligence_client import contexts_path, _append  # type: ignore
        _append(contexts_path(None, env), {"schema": SCHEMA, "event": row.get("event", "MISS"),
                                           "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(), **row})
    except Exception:  # noqa: BLE001
        pass


def check(surface: str, who: str, context_id: str | None, *, required: bool = True, env: dict | None = None,
          extra: dict | None = None) -> dict:
    """Decide. Returns {"mode", "has_context", "required", "decision": ALLOW|ALLOW_MISS|REFUSE}.
    Raises MemoryContextRequired only when mode is ENFORCED and a required context is missing."""
    env = os.environ if env is None else env
    mode = mode_for(surface, env)
    has = bool(context_id)
    out = {"surface": surface, "who": who, "mode": mode, "has_context": has, "required": bool(required),
           "context_id": context_id, **(extra or {})}
    if has or not required:
        out["decision"] = "ALLOW"
        return out
    if mode == "ENFORCED":
        out["decision"] = "REFUSE"
        _receipt({**out, "event": "REFUSED", "disposition": "HOLD_MEMORY_CONTEXT_REQUIRED"}, env)
        raise MemoryContextRequired(surface, who)
    out["decision"] = "ALLOW_MISS"
    _receipt({**out, "event": "MISS"}, env)
    return out


__all__ = ["check", "mode_for", "research_class", "MemoryContextRequired", "SCHEMA", "SURFACES", "RESEARCH_CATEGORIES"]
