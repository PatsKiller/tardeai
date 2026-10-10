"""search_routing_policy.py — load and validate ``config/search_routing_policy.json`` (SearchRoutingPolicy@v1).

The policy says, for every question class, which sources are asked and in what order
(cache -> free lane -> paid Brave -> declared no_coverage), what counts as a good enough
free answer, and how many dollars each budget pool may spend. ``scripts/lib/search_router.py``
is the only reader that acts on it; ``scripts/check_search_routing_policy.py`` (wired into
``scripts/check_data_source_authority.py``) fails the build on an invalid policy.

Pure: reads one JSON file (and, for cross-checks, the authority registry). No network, no
writes. AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

SCHEMA = "SearchRoutingPolicy@v1"
ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "config" / "search_routing_policy.json"
REGISTRY_PATH = ROOT / "config" / "data_source_authority.json"

TIER_OF_KIND = {"cache": 0, "free": 1, "paid": 2}
PAID_TRIGGERS = ("insufficient_free",)
NO_COVERAGE = ("say_so", "declared_gap", "refuse_up_front")
POOL_LINES = ("working_target_usd", "local_ceiling_usd", "non_priority_stop_usd")
QUALITY_KEYS = ("min_results", "min_trusted", "min_relevant", "freshness_hours", "min_fresh")
KINDS = ("web", "news")


class PolicyInvalid(ValueError):
    """The routing policy breaks an invariant; the engine must not run on it."""


def load_policy(path: Optional[Path] = None, *, registry: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Read and validate. Raises PolicyInvalid listing every broken rule."""
    p = Path(path) if path else POLICY_PATH
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PolicyInvalid(f"unreadable policy at {p}: {type(exc).__name__}: {exc}") from exc
    errors = validate_policy(doc, registry=registry)
    if errors:
        raise PolicyInvalid("; ".join(errors))
    return doc


def _registry(registry: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if registry is not None:
        return registry
    try:
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — cross-checks are skipped, never invented
        return None


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_policy(doc: Any, *, registry: Optional[dict[str, Any]] = None) -> list[str]:
    """Every broken rule, as a list of strings. Empty list = valid."""
    e: list[str] = []
    if not isinstance(doc, dict):
        return ["policy is not an object"]
    if doc.get("schema") != SCHEMA:
        e.append(f"schema must be {SCHEMA}")
    if doc.get("registry_domain") != "web_search":
        e.append("registry_domain must be web_search")

    pricing = doc.get("pricing") or {}
    if not _num(pricing.get("usd_per_request")) or pricing.get("usd_per_request") <= 0:
        e.append("pricing.usd_per_request must be a positive number")
    if not _num(pricing.get("free_credit_usd_per_month")) or pricing.get("free_credit_usd_per_month") < 0:
        e.append("pricing.free_credit_usd_per_month must be >= 0")

    b = doc.get("budget") or {}
    lines = {k: b.get(k) for k in ("account_cap_usd", "local_ceiling_usd", "working_target_usd", "non_priority_stop_usd")}
    if not all(_num(v) and v > 0 for v in lines.values()):
        e.append("budget lines (account_cap/local_ceiling/working_target/non_priority_stop) must be positive numbers")
    else:
        if not (lines["non_priority_stop_usd"] <= lines["working_target_usd"] <= lines["local_ceiling_usd"]
                < lines["account_cap_usd"]):
            e.append("budget lines must satisfy non_priority_stop <= working_target <= local_ceiling < account_cap")
    if b.get("caps_basis") not in ("gross", "net"):
        e.append("budget.caps_basis must be gross or net")
    if not _num(b.get("alert_at_pct_of_target")) or not (0 < b.get("alert_at_pct_of_target") <= 100):
        e.append("budget.alert_at_pct_of_target must be in (0, 100]")
    pacing = b.get("pacing") or {}
    for k in ("carry_over_max_days", "floor_fraction_of_base", "non_trading_day_fraction_of_base"):
        if not _num(pacing.get(k)) or pacing.get(k) < 0:
            e.append(f"budget.pacing.{k} must be a number >= 0")
    pools = b.get("pools") or {}
    if not pools:
        e.append("budget.pools is empty")
    shares = 0.0
    for name, pool in pools.items():
        if not _num((pool or {}).get("share")) or not (0 <= pool["share"] <= 1):
            e.append(f"pool {name}: share must be in [0, 1]")
            continue
        shares += float(pool["share"])
        if pool.get("month_line") not in POOL_LINES:
            e.append(f"pool {name}: month_line must be one of {POOL_LINES}")
        for other in pool.get("may_borrow_unused_daily_from") or []:
            if other not in pools:
                e.append(f"pool {name}: borrows from undeclared pool {other}")
            elif (pools[other] or {}).get("reserve"):
                e.append(f"pool {name}: may not borrow from reserve pool {other}")
    if pools and abs(shares - 1.0) > 1e-6:
        e.append(f"pool shares must sum to 1.0 (got {shares:.4f})")
    reserve_lines = {p.get("month_line") for p in pools.values() if (p or {}).get("reserve")}
    for name, pool in pools.items():
        if not pool.get("reserve") and not pool.get("first_claim") and pool.get("month_line") != "non_priority_stop_usd":
            e.append(f"pool {name}: a background pool must stop at non_priority_stop_usd")
    if reserve_lines and reserve_lines != {"local_ceiling_usd"}:
        e.append("the reserve pool's month_line must be local_ceiling_usd")

    free = ((doc.get("free_lane") or {}).get("searxng") or {})
    never = set(free.get("never_engines") or [])
    if "braveapi" not in never:
        e.append("free_lane.searxng.never_engines must include braveapi (the paid API keyed into SearXNG)")
    engines = free.get("engines") or {}
    for kind in KINDS:
        lst = engines.get(kind) or []
        if not lst:
            e.append(f"free_lane.searxng.engines.{kind} must name at least one engine")
        bad = sorted(set(lst) & never)
        if bad:
            e.append(f"free_lane.searxng.engines.{kind} names a never-engine: {bad}")

    sources = doc.get("sources") or {}
    for need in ("cache", "searxng", "brave"):
        if need not in sources:
            e.append(f"sources.{need} must be declared")
    for name, s in sources.items():
        if (s or {}).get("tier") not in (0, 1, 2):
            e.append(f"source {name}: tier must be 0, 1 or 2")
        if (s or {}).get("cost_class") == "paid" and s.get("tier") != 2:
            e.append(f"source {name}: a paid source must be tier 2")
        if (s or {}).get("cost_class") == "free" and s.get("tier") == 2:
            e.append(f"source {name}: a free source must not be tier 2")

    q = doc.get("quality") or {}
    if not q.get("trusted_domains"):
        e.append("quality.trusted_domains must be non-empty")
    pools_declared = set(pools)
    classes = doc.get("classes") or {}
    if not classes:
        e.append("classes is empty")
    for cname, c in classes.items():
        if not isinstance(c, dict):
            e.append(f"class {cname}: not an object")
            continue
        if c.get("pool") not in pools_declared:
            e.append(f"class {cname}: pool {c.get('pool')!r} undeclared")
        if c.get("kind") not in KINDS:
            e.append(f"class {cname}: kind must be web or news")
        if not isinstance(c.get("cache_ttl_s"), int) or c["cache_ttl_s"] < 0:
            e.append(f"class {cname}: cache_ttl_s must be an int >= 0")
        tiers = c.get("free_tiers") or []
        if not tiers:
            e.append(f"class {cname}: free_tiers must name at least one free source")
        for t in tiers:
            src = sources.get(t)
            if not src:
                e.append(f"class {cname}: free tier {t!r} undeclared in sources")
            elif src.get("tier") != 1:
                e.append(f"class {cname}: free tier {t!r} is not a tier-1 source")
        paid = c.get("paid") or {}
        if not isinstance(paid.get("allowed"), bool):
            e.append(f"class {cname}: paid.allowed must be true or false")
        elif paid["allowed"]:
            if paid.get("trigger") not in PAID_TRIGGERS:
                e.append(f"class {cname}: paid.trigger must be one of {PAID_TRIGGERS}")
            if paid.get("kind") not in KINDS:
                e.append(f"class {cname}: paid.kind must be web or news")
            if pools.get(c.get("pool"), {}).get("share", 0) <= 0:
                e.append(f"class {cname}: paid allowed but its pool has no share")
            g = paid.get("goggle")
            if g is not None and g not in (doc.get("goggles") or {}):
                e.append(f"class {cname}: goggle {g!r} undeclared")
        cq = c.get("quality") or {}
        for k in QUALITY_KEYS:
            if k not in cq:
                e.append(f"class {cname}: quality.{k} missing")
        if c.get("no_coverage") not in NO_COVERAGE:
            e.append(f"class {cname}: no_coverage must be one of {NO_COVERAGE}")

    callers = doc.get("callers") or {}
    for caller, cname in callers.items():
        if cname not in classes:
            e.append(f"caller {caller}: class {cname!r} undeclared")
    for caller in doc.get("promotable_to_priority") or []:
        if caller not in callers:
            e.append(f"promotable_to_priority: caller {caller!r} not in callers")
    if "scalp_priority" in classes and (classes["scalp_priority"].get("pool") != "scalp"):
        e.append("class scalp_priority must draw on pool scalp")
    pri = ((doc.get("priority") or {}).get("scalp") or {})
    for k in ("eligible_decisions", "trigger_proximity_points", "research_stale_after_min", "max_per_cycle",
              "max_list_age_min", "sessions_et", "momentum_override"):
        if k not in pri:
            e.append(f"priority.scalp.{k} missing")
    if "AVOID" in (pri.get("eligible_decisions") or []):
        e.append("priority.scalp.eligible_decisions must not include AVOID")

    reg = _registry(registry)
    if reg is not None:
        providers = reg.get("providers") or {}
        doms = {d.get("domain"): d for d in reg.get("domains") or [] if isinstance(d, dict)}
        ws = doms.get("web_search") or {}
        if ws.get("routing_policy") != "config/search_routing_policy.json":
            e.append("registry domains[web_search].routing_policy must point at config/search_routing_policy.json")
        for name, s in sources.items():
            prov = (s or {}).get("registry_provider")
            if not prov:
                continue
            row = providers.get(prov)
            if not row:
                e.append(f"source {name}: registry provider {prov!r} undeclared (propose a registry row first)")
            elif row.get("status") == "retired":
                e.append(f"source {name}: registry provider {prov!r} is retired")
        brave = providers.get("brave") or {}
        if "web_search" not in (brave.get("supplies") or []):
            e.append("registry providers.brave must supply web_search")
    return e


def class_for_caller(policy: dict[str, Any], caller: str) -> Optional[str]:
    return (policy.get("callers") or {}).get(str(caller or ""))


__all__ = ["SCHEMA", "POLICY_PATH", "PolicyInvalid", "load_policy", "validate_policy", "class_for_caller"]
