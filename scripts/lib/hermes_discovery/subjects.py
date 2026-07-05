"""Universal Research Discovery Layer — subject builder.

Builds the subject_json envelope every discovery candidate now carries in
meta_json (wired by inbox.upsert_candidate). A subject is the stable,
domain-aware identity of WHAT is being researched — symbol, theme, tax rule,
legal topic, connector, … — independent of which producer surfaced it.

Holdings awareness is a READ-ONLY lookup against the canonical
data/portfolios/state/holdings.json snapshot (the holdings-mirror tables are
retired) and is applied to TICKER candidates only. No DB writes, no broker
imports — advisory-only like the rest of the package.

Public API:
    build_subject(candidate, domain) -> subject dict (schema in docstring)
    subject_id(domain, subject_type, key) -> stable "subj_<hash16>" id
    subject_type_for(candidate, domain) -> one of SUBJECT_TYPES
    held_symbols() / holdings_for_symbol(sym) -> read-only holdings lookups
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import dedupe, domains

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HOLDINGS_PATH = Path(os.getenv("TRADE_AI_HOLDINGS_JSON")
                     or PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json")

SUBJECT_TYPES = frozenset({
    "symbol", "sector", "theme", "regulation", "tax_rule", "retirement_topic",
    "legal_topic", "macro_event", "source", "connector", "system_health",
    "custom",
})

SUBJECT_SCHEMA_VERSION = "discovery-subject-v1"

# domain → subject_type for TREND/TOPIC-shaped candidates
_DOMAIN_SUBJECT_TYPES = {
    "sectors": "sector",
    "taxes": "tax_rule",
    "retirement": "retirement_topic",
    "legal": "legal_topic",
    "legal_general": "legal_topic",
    "macro": "macro_event",
    "geopolitical": "macro_event",
    "system_ops": "system_health",
    "custom": "custom",
}

_REGULATION_HINTS = ("regulation", "rulemaking", "rule change", "final rule",
                     "proposed rule", "statute")

# ── read-only holdings lookup (TICKER candidates only) ───────────────────────

_holdings_cache: tuple[float, list[dict[str, Any]]] | None = None


def _load_holdings() -> list[dict[str, Any]]:
    """holdings.json rows, cached by file mtime. Missing/broken file → []
    (subjects still build; they just carry no holdings context)."""
    global _holdings_cache
    try:
        mtime = HOLDINGS_PATH.stat().st_mtime
    except OSError:
        return []
    if _holdings_cache and _holdings_cache[0] == mtime:
        return _holdings_cache[1]
    try:
        data = json.loads(HOLDINGS_PATH.read_text(encoding="utf-8"))
        rows = data.get("holdings") if isinstance(data, dict) else data
        rows = [r for r in (rows or []) if isinstance(r, dict)]
    except Exception:
        rows = []
    _holdings_cache = (mtime, rows)
    return rows


def held_symbols() -> set[str]:
    """Currently held (non-cash, value > 0) symbols across all accounts."""
    return {str(r.get("symbol") or "").upper() for r in _load_holdings()
            if r.get("symbol") and not r.get("is_cash")
            and float(r.get("market_value") or 0) > 0}


def holdings_for_symbol(symbol: str) -> list[dict[str, Any]]:
    """Trimmed per-account holding rows for one symbol (read-only)."""
    sym = str(symbol or "").strip().upper()
    out = []
    for r in _load_holdings():
        if str(r.get("symbol") or "").upper() != sym or r.get("is_cash"):
            continue
        out.append({
            "account": r.get("account") or r.get("account_id"),
            "shares": r.get("shares"),
            "market_value": r.get("market_value"),
            "portfolio_pct": r.get("portfolio_pct"),
            "as_of": r.get("as_of"),
        })
    return out


# ── subject identity ─────────────────────────────────────────────────────────

def subject_id(domain: str, subject_type: str, key: str) -> str:
    """Stable subject id: same (domain, subject_type, normalized key) always
    hashes to the same id, across runs and producers."""
    basis = f"{domain}|{subject_type}|{dedupe.normalize_key(str(key))}"
    return "subj_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def subject_type_for(candidate: dict[str, Any], domain: str) -> str:
    """Map candidate shape + domain to a subject_type."""
    ctype = str(candidate.get("candidate_type") or "").strip().upper()
    if ctype == "TICKER_CANDIDATE":
        return "symbol"
    if ctype == "SOURCE_CANDIDATE":
        return "source"
    if ctype == "CONNECTOR_CANDIDATE":
        return "connector"
    # TREND / TOPIC: domain decides
    if domain in ("legal", "legal_general"):
        text = (str(candidate.get("label") or "") + " "
                + str(candidate.get("summary") or "")).lower()
        if any(h in text for h in _REGULATION_HINTS):
            return "regulation"
    mapped = _DOMAIN_SUBJECT_TYPES.get(domain)
    if mapped:
        return mapped
    return "theme"


# ── helpers ──────────────────────────────────────────────────────────────────

def _iso(ts: Any) -> str:
    if isinstance(ts, datetime):
        return (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)).isoformat()
    if ts:
        return str(ts)
    return datetime.now(timezone.utc).isoformat()


def _uniq(items) -> list:
    seen, out = set(), []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _source_refs(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in (candidate.get("evidence_json") or candidate.get("evidence") or []):
        if not isinstance(item, dict):
            continue
        ref = {k: item.get(src) for k, src in
               (("source_domain", "source_domain"), ("url", "url"), ("note", "note"))
               if item.get(src)}
        if ref:
            refs.append(ref)
    if candidate.get("source_url"):
        refs.append({"url": candidate["source_url"],
                     "source_domain": candidate.get("source_domain")})
    return refs[:10]


# ── the subject builder ──────────────────────────────────────────────────────

def build_subject(candidate: dict[str, Any], domain: str) -> dict[str, Any]:
    """Build subject_json for a candidate in a domain.

    Schema (SUBJECT_SCHEMA_VERSION):
      subject_id                stable hash id (domain + type + normalized label)
      canonical_label, aliases
      domain, subject_type      subject_type ∈ SUBJECT_TYPES
      entities, tickers, sectors
      accounts_if_relevant      accounts holding the symbol (TICKER only)
      holdings_if_relevant      trimmed holding rows (TICKER only, read-only join)
      source_refs               evidence-derived {source_domain,url,note} refs
      first_seen, last_seen, recurrence_count, cross_source_count
      source_quality_summary    {distinct_domains, domains, credibility?}
      risk_classification       the domain's risk_level
      safe_action_level         OPERATOR_REVIEW_REQUIRED forced for
                                professional-review domains (tax/legal/
                                retirement/medical)
      recommended_action        human-readable next step incl. promotion paths

    Raises domains.DomainConfigError on an unknown domain (fail closed).
    """
    policy = domains.domain_policy(domain)
    label = str(candidate.get("label") or "").strip()
    ctype = str(candidate.get("candidate_type") or "").strip().upper()
    stype = subject_type_for(candidate, domain)
    norm_key = candidate.get("normalized_key") or dedupe.normalize_key(label)

    meta = candidate.get("meta_json") or candidate.get("meta") or {}
    if not isinstance(meta, dict):
        meta = {}

    tickers = _uniq([str(s).upper() for s in
                     ([label] if ctype == "TICKER_CANDIDATE" else [])
                     + list(candidate.get("seed_symbols") or [])
                     + list(candidate.get("extracted_symbols") or [])])
    sectors = _uniq([str(s) for s in (meta.get("sectors") or [])]
                    + ([label] if domain == "sectors" else []))
    entities = _uniq([str(e) for e in (meta.get("entities") or [])]
                     + [str(k) for k in (meta.get("keywords") or [])])

    refs = _source_refs(candidate)
    ref_domains = _uniq([(r.get("source_domain") or "").lower()
                         for r in refs if r.get("source_domain")])
    if candidate.get("source_domain"):
        ref_domains = _uniq(ref_domains + [str(candidate["source_domain"]).lower()])

    accounts: list[str] = []
    holdings: list[dict[str, Any]] = []
    if ctype == "TICKER_CANDIDATE" and label:
        holdings = holdings_for_symbol(label)
        accounts = _uniq([h.get("account") for h in holdings])

    quality: dict[str, Any] = {"distinct_domains": len(ref_domains),
                               "domains": ref_domains[:6]}
    if meta.get("credibility") is not None:
        try:
            quality["credibility"] = float(meta["credibility"])
        except (TypeError, ValueError):
            pass

    professional = bool(policy.get("requires_professional_review_label"))
    safe_level = ("OPERATOR_REVIEW_REQUIRED" if professional
                  else str(candidate.get("safe_action_level")
                           or "OPERATOR_REVIEW_REQUIRED"))

    paths = policy.get("promotion_paths") or []
    action = (f"Operator review required; eligible promotion paths: "
              f"{', '.join(paths) if paths else 'none (classify first)'}.")
    if professional:
        action += f" {policy.get('professional_review_label')}"

    return {
        "version": SUBJECT_SCHEMA_VERSION,
        "subject_id": subject_id(domain, stype, norm_key or label),
        "canonical_label": label,
        "aliases": _uniq([label, norm_key] + [str(a) for a in (meta.get("aliases") or [])]),
        "domain": domain,
        "subject_type": stype,
        "entities": entities[:12],
        "tickers": tickers[:12],
        "sectors": sectors[:8],
        "accounts_if_relevant": accounts,
        "holdings_if_relevant": holdings,
        "source_refs": refs,
        "first_seen": _iso(candidate.get("created_at") or candidate.get("first_seen")),
        "last_seen": _iso(candidate.get("last_seen_at") or candidate.get("last_seen")),
        "recurrence_count": int(candidate.get("seen_count") or 1),
        "cross_source_count": len(ref_domains),
        "source_quality_summary": quality,
        "risk_classification": policy["risk_level"],
        "safe_action_level": safe_level,
        "recommended_action": action,
    }
