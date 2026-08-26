"""Governed narrative synthesis for material CIO situations.

Situation detection does not need an LLM. This module only runs when a material
situation exists and a persisted summary is insufficient.

Provider economy:
  unchanged           → LLM = 0
  persisted summary   → LLM = 0
  simple material     → DeepSeek Flash first
  disagreement/unc.   → challenger OAuth
  exceptional complex → DeepSeek Pro

Never routes to a local generative model.
"""
from __future__ import annotations

from typing import Any, Callable

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CIOAdvisorySynthesis@v1"
LOCAL_GENERATIVE_FORBIDDEN = "POLICY_LOCAL_GENERATIVE_FORBIDDEN"

GenerateFn = Callable[..., str]


def select_model(
    scan: dict[str, Any],
    *,
    persisted_summary: str | None = None,
    disagreement: bool = False,
    exceptional: bool = False,
) -> dict[str, Any]:
    notify = list(scan.get("notify") or [])
    material = int(scan.get("material_count") or 0)
    if material <= 0 or scan.get("notification_decision") == "SUPPRESS":
        return {
            "requested": None,
            "actual": None,
            "fallback": None,
            "cost": 0,
            "why_model_required": "UNCHANGED_NO_MODEL",
            "llm_calls": 0,
        }
    if persisted_summary and not disagreement and not exceptional:
        return {
            "requested": None,
            "actual": "persisted_summary",
            "fallback": None,
            "cost": 0,
            "why_model_required": "EXISTING_PERSISTED_SUMMARY",
            "llm_calls": 0,
        }
    if exceptional:
        requested = "deepseek-v4-pro"
        why = "EXCEPTIONAL_HIGH_VALUE_COMPLEX_SYNTHESIS"
    elif disagreement:
        requested = "oauth-challenger"
        why = "MATERIAL_UNCERTAINTY_OR_DISAGREEMENT"
    else:
        requested = "deepseek-v4-flash"
        why = "SIMPLE_MATERIAL_SYNTHESIS"
    if any("local" in str(requested).lower() for _ in [0]):
        raise RuntimeError(LOCAL_GENERATIVE_FORBIDDEN)
    return {
        "requested": requested,
        "actual": None,
        "fallback": None,
        "cost": None,
        "why_model_required": why,
        "llm_calls": 0,
        "notify_count": len(notify),
    }


def build_synthesis_prompt(
    *,
    previous_cio_view: str,
    what_changed: str,
    portfolio_facts: str,
    persistent_research: str,
    support: str,
    counterevidence: str,
    policy: str,
    market_seasonal: str,
) -> str:
    return (
        "PREVIOUS CIO VIEW:\n"
        f"{previous_cio_view or 'NONE'}\n\n"
        "WHAT CHANGED:\n"
        f"{what_changed or 'NO_NEW_INFO'}\n\n"
        "CURRENT VERIFIED PORTFOLIO FACTS:\n"
        f"{portfolio_facts or 'UNAVAILABLE'}\n\n"
        "PERSISTENT RESEARCH:\n"
        f"{persistent_research or 'NONE'}\n\n"
        "SUPPORT:\n"
        f"{support or 'NONE'}\n\n"
        "COUNTEREVIDENCE:\n"
        f"{counterevidence or 'NONE'}\n\n"
        "POLICY:\n"
        f"{policy or 'UNCONFIRMED'}\n\n"
        "MARKET / SEASONAL CONTEXT:\n"
        f"{market_seasonal or 'UNAVAILABLE'}\n\n"
        "TASK:\n"
        "Explain only what materially changed and what the operator should consider now.\n"
        "Do not start from scratch. Do not invent numbers. Do not emit orders."
    )


def synthesize(
    scan: dict[str, Any],
    *,
    envelope: dict[str, Any] | None = None,
    persisted_summary: str | None = None,
    generate: GenerateFn | None = None,
    disagreement: bool = False,
    exceptional: bool = False,
) -> dict[str, Any]:
    choice = select_model(
        scan,
        persisted_summary=persisted_summary,
        disagreement=disagreement,
        exceptional=exceptional,
    )
    if choice["requested"] is None:
        text = persisted_summary or ""
        return {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "text": text,
            "used_llm": False,
            "model": choice,
            "financial_action": False,
            "local_generative": False,
        }
    if generate is None:
        return {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "text": persisted_summary or "",
            "used_llm": False,
            "model": dict(choice, actual=None, fallback="NO_GENERATOR_BOUND", llm_calls=0),
            "financial_action": False,
            "local_generative": False,
        }
    notify = (scan.get("notify") or [None])[0] or {}
    prompt = build_synthesis_prompt(
        previous_cio_view=str((envelope or {}).get("previous_cio_view") or ""),
        what_changed=str(notify.get("what_changed") or ""),
        portfolio_facts=str((envelope or {}).get("portfolio_facts") or ""),
        persistent_research=str((envelope or {}).get("persistent_research") or ""),
        support=str(notify.get("support") or ""),
        counterevidence=str(notify.get("counterevidence") or ""),
        policy=str((envelope or {}).get("policy") or ""),
        market_seasonal=str((envelope or {}).get("market_seasonal") or ""),
    )
    if "local" in str(choice["requested"]).lower() or "ollama" in prompt.lower()[:20]:
        raise RuntimeError(LOCAL_GENERATIVE_FORBIDDEN)
    text = generate(prompt, model=choice["requested"])
    choice = dict(choice, actual=choice["requested"], llm_calls=1, cost=0)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "text": str(text or "").strip(),
        "used_llm": True,
        "model": choice,
        "financial_action": False,
        "local_generative": False,
        "prompt_task": "delta_only",
    }
