"""Operator evidence contract — did the desk assemble the facts the house already had?

2026-09-13 18:56. The operator asked what sectors to concentrate on into Q3/Q4
given September seasonality and the midterm cycle. The reply came from the
model's general knowledge and told him "your actual holdings, weights, and cash
are not available in my current facts (cash_pct, buying_power,
holdings_for_symbols all empty)". At that moment the CIO snapshot carried
total_cash $710,933 (56% of $1.268M), sector weights, the investment policy,
risk, rotation ladders and 2,088 promoted research rows. The builder read keys
that do not exist and never read most domains. Nothing measured the distance
between what the store had and what the model was handed.

This module measures it. ``config/operator_evidence_contract.json`` declares,
per intent kind, which snapshot domains / broker projections / state files MUST
be read and which facts keys MUST be populated when the store has them.
:func:`check` compares one gathered evidence dict against the snapshot it was
built from and reports:

    MISSING_FACT        the store has it, the facts key is absent
    FALSE_EMPTY_CLAIM   the store has it, the facts key is present but None/empty
                        (the model reads null and tells the operator "empty")

Pure: no DB, no network, no filesystem beyond reading the contract file (path
injectable). The gatherers call it fail-soft and attach the findings as
``evidence["contract_findings"]`` plus soft gaps of ``gap_type == "contract"``,
so the reply can say "facts were available but not assembled" instead of
"empty". Consumers: scripts/lib/cio_operator_desk_loop.py (both gatherers).

AUTHORITY: READ_ONLY_ADVISORY. Reports; never fills, never writes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = "OperatorEvidenceContract@v1"

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = PROJECT_ROOT / "config" / "operator_evidence_contract.json"

#: Domain states that mean "the store answered". PARTIAL is populated with a
#: declared gap (cash_buying_power is PARTIAL because buying power is holdings-
#: derived, and it still carries total_cash 710,933).
AVAILABLE_STATES = frozenset({"AVAILABLE", "PARTIAL"})

_cache: dict[str, Any] = {"path": None, "mtime": None, "doc": None}


# ── contract ─────────────────────────────────────────────────────────────────


def load_contract(path: Path | None = None) -> dict[str, Any]:
    """The contract document (mtime-cached). Missing/unreadable -> {} (check() then reports nothing)."""
    p = path or CONTRACT_PATH
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {}
    if _cache["path"] == str(p) and _cache["mtime"] == mtime and _cache["doc"] is not None:
        return _cache["doc"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return {}
    _cache.update({"path": str(p), "mtime": mtime, "doc": doc})
    return doc


def kinds_for_intent(intent: dict[str, Any]) -> list[str]:
    """Contract kinds an intent dict resolves to — mirrors gather_tradeai_evidence's routing.

    meta_system answers from runtime facts only; freeform/unclear without re-entry
    needs go to gather_freeform_context (so their portfolio/cash needs are NOT
    desk-path facts); everything else is the desk path, one kind per need.
    """
    name = str(intent.get("intent") or "")
    needs = {str(n) for n in (intent.get("needs") or [])}
    if name == "meta_system":
        return ["meta_system"]
    if name in ("freeform", "unclear") and not (needs & {"reentry_ready", "reentry_levels"}):
        return ["freeform"]
    kinds: list[str] = []
    if name == "reentry" or needs & {"reentry_ready", "reentry_levels"}:
        kinds.append("reentry")
    if name == "attention":
        kinds.append("attention")
    if name == "cash" or "cash" in needs:
        kinds.append("cash")
    if name == "portfolio" or "portfolio" in needs:
        kinds.append("portfolio")
    if name == "risk" or "risk" in needs:
        kinds.append("risk")
    if name == "research" or "research" in needs:
        kinds.append("research")
    if name == "analyst_view" or "analyst_view" in needs:
        kinds.append("analyst")
    if name == "options_strategy" or "options_strategy" in needs:
        kinds.append("options_strategy")
    return kinds


# ── snapshot access (both envelope shapes) ───────────────────────────────────


def domain_state(snapshot: dict[str, Any], domain: str) -> str | None:
    """'AVAILABLE' | 'PARTIAL' | 'DATA_UNAVAILABLE' | ... | None when the domain is absent."""
    d = ((snapshot or {}).get("domains") or {}).get(domain)
    if not isinstance(d, dict):
        return None
    st = d.get("state") or d.get("quality_state")
    if st is None and d:
        # a raw payload with no state marker (tests, older collectors): it answered
        return "AVAILABLE"
    return str(st) if st is not None else None


def domain_payload(snapshot: dict[str, Any], domain: str) -> dict[str, Any]:
    """The unwrapped payload: envelope.data when present, else the flat legacy dict."""
    d = ((snapshot or {}).get("domains") or {}).get(domain)
    if not isinstance(d, dict):
        return {}
    if "data" in d and isinstance(d.get("data"), dict):
        return d["data"]
    return d


def _walk(obj: Any, path: str) -> tuple[bool, Any]:
    """(key_present, value) for a dotted path; key_present is False when any hop is missing.

    A hop that lands on None counts as PRESENT-and-empty: ``facts["cash"] = None``
    is exactly the 18:56 shape the model read as "cash is empty".
    """
    cur = obj
    for hop in path.split("."):
        if cur is None and cur is not obj:
            return True, None
        if isinstance(cur, dict):
            if hop not in cur:
                return False, None
            cur = cur[hop]
        elif isinstance(cur, list) and hop.isdigit() and int(hop) < len(cur):
            cur = cur[int(hop)]
        else:
            return False, None
    return True, cur


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _summ(v: Any) -> str:
    if isinstance(v, (list, dict)):
        return f"{type(v).__name__}[{len(v)}]"
    s = str(v)
    return s if len(s) <= 40 else s[:37] + "..."


# ── the check ────────────────────────────────────────────────────────────────


def check(intent: dict[str, Any], evidence: dict[str, Any], snapshot: dict[str, Any],
          contract: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Findings for one gathered evidence dict. Empty list == the contract is met.

    Pure. A missing contract, an empty snapshot or an unknown intent produce no
    findings (there is nothing to measure against) — never an exception.
    """
    doc = contract if contract is not None else load_contract()
    intents = (doc or {}).get("intents") or {}
    if not intents or not isinstance(snapshot, dict) or not (snapshot.get("domains") or {}):
        return []
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for kind in kinds_for_intent(intent or {}):
        spec = intents.get(kind) or {}
        for req in spec.get("facts_required") or []:
            domain = str(req.get("domain") or "")
            field = str(req.get("domain_field") or "")
            paths = req.get("fact")
            paths = [paths] if isinstance(paths, str) else list(paths or [])
            if not (domain and field and paths):
                continue
            state = domain_state(snapshot, domain)
            if state not in AVAILABLE_STATES:
                continue
            _, store_value = _walk(domain_payload(snapshot, domain), field)
            if _empty(store_value):
                continue  # the store does not have it either; not a contract failure
            present = False
            key_present = False
            for p in paths:
                kp, val = _walk(evidence or {}, p)
                key_present = key_present or kp
                if kp and not _empty(val):
                    present = True
                    break
            if present:
                continue
            code = "FALSE_EMPTY_CLAIM" if key_present else "MISSING_FACT"
            key = (code, paths[0])
            if key in seen:
                continue
            seen.add(key)
            findings.append({
                "code": code,
                "intent": kind,
                "fact": paths[0],
                "fact_alternatives": paths[1:],
                "domain": domain,
                "domain_field": field,
                "domain_state": state,
                "store_has": _summ(store_value),
                "reason": (
                    f"{domain}.{field} is {state} in the snapshot ({_summ(store_value)}) but "
                    f"{paths[0]} is {'None/empty' if key_present else 'not assembled'}"
                ),
            })
    return findings


def findings_to_gaps(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Soft gaps (gap_type 'contract') the reply path can say out loud.

    Deliberately NOT 'missing_market_data': the data is not missing, the
    assembly is. Phase 7 must not queue a pull for a fact that is already here.
    """
    out: list[dict[str, Any]] = []
    for f in findings or []:
        out.append({
            "domain": f.get("domain"),
            "symbol": None,
            "field": str(f.get("fact") or "").rsplit(".", 1)[-1],
            "reason": f"facts were available but not assembled: {f.get('reason')}",
            "gap_type": "contract",
            "code": f.get("code"),
        })
    return out


# ── coverage of the contract itself ──────────────────────────────────────────


def coverage(contract: dict[str, Any], snapshot_domains: list[str] | None = None,
             projection_ids: list[str] | None = None) -> dict[str, Any]:
    """Which live domains / projections no intent claims and never_needed does not excuse.

    ``snapshot_domains`` defaults to the contract's own observed list; pass the
    live ``get_cio_snapshot()['domains']`` keys to measure against reality.
    """
    doc = contract or {}
    intents = doc.get("intents") or {}
    never = doc.get("never_needed") or {}
    claimed_domains: set[str] = set()
    claimed_projections: set[str] = set()
    for spec in intents.values():
        claimed_domains.update(spec.get("snapshot_domains") or [])
        claimed_projections.update(spec.get("broker_projections") or [])
    excused_domains = set((never.get("domains") or {}).keys())
    excused_projections = set((never.get("broker_projections") or {}).keys())
    live_domains = list(snapshot_domains if snapshot_domains is not None
                        else ((doc.get("snapshot_domains_observed") or {}).get("domains") or []))
    live_projections = list(projection_ids if projection_ids is not None
                            else ((doc.get("broker_projections_observed") or {}).get("ids") or []))
    return {
        "unclaimed_domains": sorted(d for d in live_domains if d not in claimed_domains and d not in excused_domains),
        "unclaimed_projections": sorted(p for p in live_projections if p not in claimed_projections and p not in excused_projections),
        "claimed_but_not_live_domains": sorted(d for d in claimed_domains if d not in live_domains),
        "claimed_but_not_live_projections": sorted(p for p in claimed_projections if p not in live_projections),
        "excused_and_claimed": sorted((claimed_domains & excused_domains) | (claimed_projections & excused_projections)),
        "intents": sorted(intents.keys()),
    }
