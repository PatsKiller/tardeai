"""Read config/data_source_authority.json — the one declaration of which provider
answers which domain — for code that has to make a routing decision at runtime.

WHY
---
Measured 2026-09-13: Brave is live and paid, capped by us at 120/day and
1,500/month. On 09-13 there were 38 DAILY_EXHAUSTED denials (22 on 09-11) and
every one went nowhere, while a self-hosted SearXNG container with a 10,000/day
budget in the same registry sat idle and Tavily (20/day) was configured with no
caller. The registry already SAID ``web_search.backup = ["searxng", "tavily"]``
and ``spill_on = [DAILY_EXHAUSTED, MONTHLY_EXHAUSTED, HTTP_429]``; nothing read
it. Chains existed in code and nowhere as a decision.

This module is the reader. It answers three questions and nothing else:

  * ``resolve_backup(domain)``   the registry's backup chain for a domain, minus
                                 anything retired, refusing a cross-domain
                                 substitution (AGENTS.md §7A rule 5).
  * ``spill_on(domain)``         the denial reasons on which a domain spills.
  * ``provider_budget(name)``    ``providers[name].budget`` — the caps.

A backup answers the SAME question. ``resolve_backup`` raises
``CrossDomainSubstitution`` when a domain declares ``answers`` (the supply tags
that count as its question) and a backup provider supplies none of them — the
Finviz-performance-column-as-analyst-rating shape. A domain that does not yet
declare ``answers`` gets its declared list as-is: the registry is the decision
and the gate (check_data_source_authority.py) polices what goes into it.

READ_ONLY_ADVISORY. Never writes. Never calls a provider.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

AUTHORITY_PATH = Path(__file__).resolve().parents[2] / "config" / "data_source_authority.json"


class UnknownDomain(KeyError):
    """The domain is not declared in the registry."""


class CrossDomainSubstitution(ValueError):
    """A backup provider does not answer the domain's question (§7A rule 5)."""


@lru_cache(maxsize=1)
def _load_registry_file() -> dict[str, Any]:
    return json.loads(AUTHORITY_PATH.read_text(encoding="utf-8"))


def registry() -> dict[str, Any]:
    """The parsed registry. Tests inject one via ``registry=`` on each helper."""
    return _load_registry_file()


def _domains(reg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    doms = reg.get("domains") or []
    if isinstance(doms, dict):
        return {str(k): dict(v) for k, v in doms.items()}
    return {str(d.get("domain")): d for d in doms if isinstance(d, dict)}


def _providers(reg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(reg.get("providers") or {})


def domain(name: str, *, registry: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    reg = registry if registry is not None else globals()["registry"]()
    try:
        return _domains(reg)[str(name)]
    except KeyError as exc:
        raise UnknownDomain(f"domain {name!r} is not declared in {AUTHORITY_PATH.name}") from exc


def provider(name: str, *, registry: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    reg = registry if registry is not None else globals()["registry"]()
    return dict(_providers(reg).get(str(name or "").strip().lower(), {}))


def provider_budget(name: str, *, registry: Optional[dict[str, Any]] = None) -> dict[str, int]:
    """``providers[name].budget`` as ints — only the keys the registry declares."""
    budget = provider(name, registry=registry).get("budget") or {}
    out: dict[str, int] = {}
    for scope in ("daily", "monthly"):
        v = budget.get(scope)
        if v is None:
            continue
        try:
            out[scope] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _is_retired(name: str, reg: dict[str, Any]) -> bool:
    if (_providers(reg).get(name) or {}).get("status") == "retired":
        return True
    try:
        from scripts.lib.retired_providers import is_retired
    except ImportError:
        try:
            from lib.retired_providers import is_retired  # type: ignore
        except ImportError:
            return False
    try:
        return bool(is_retired(name))
    except Exception:
        return False


def _supplies(name: str, reg: dict[str, Any]) -> set[str]:
    return {str(s) for s in (_providers(reg).get(name) or {}).get("supplies") or []}


def resolve_backup(domain_name: str, *, registry: Optional[dict[str, Any]] = None) -> list[str]:
    """The registry's backup chain for ``domain_name`` — same question, nothing retired.

    Raises ``UnknownDomain`` for a domain the registry does not declare and
    ``CrossDomainSubstitution`` when the domain declares ``answers`` and a
    backup provider supplies none of those tags. Retired providers are dropped,
    not raised: the gate already fails the build on a retired call site, and a
    chain that consults this module should keep going to the next live slot.
    """
    reg = registry if registry is not None else globals()["registry"]()
    d = domain(domain_name, registry=reg)
    declared = [str(p).strip().lower() for p in (d.get("backup") or []) if str(p).strip()]
    answers = {str(a) for a in (d.get("answers") or [])}
    chain: list[str] = []
    for p in declared:
        if _is_retired(p, reg):
            continue
        if answers and p in _providers(reg):
            if not (_supplies(p, reg) & answers):
                raise CrossDomainSubstitution(
                    f"{p!r} supplies {sorted(_supplies(p, reg))} — none of which answers "
                    f"{domain_name!r} ({sorted(answers)}). A backup answers the same "
                    f"question (AGENTS.md §7A rule 5); this is a cross-domain substitution."
                )
        chain.append(p)
    return chain


def spill_on(domain_name: str, *, registry: Optional[dict[str, Any]] = None) -> frozenset[str]:
    """Denial reasons on which the domain's primary spills to its backup chain."""
    d = domain(domain_name, registry=registry)
    return frozenset(str(r) for r in (d.get("spill_on") or []))


def primary_provider(domain_name: str, *, registry: Optional[dict[str, Any]] = None) -> str:
    return str(domain(domain_name, registry=registry).get("primary_provider") or "")
