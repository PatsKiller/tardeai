"""Universal Research Discovery Layer — domain registry loader + classifier.

Loads config/hermes_research_domains.yaml (base registry) merged with
config/hermes_custom_research_domains.yaml (operator extensions; a custom entry
with a base domain's name overrides it, and custom domains ALWAYS get
auto_promote hard-forced to false).

Fail-closed by design: an unknown risk_level, promotion_path, or candidate
type in either yaml aborts the load with DomainConfigError — a mistyped
config can never silently open a promotion path.

Advisory-only: this module never imports broker/execution modules and never
touches the DB. Holdings awareness (for TICKER classification) is a read-only
JSON file lookup delegated to subjects.held_symbols().

Public API (Stage 1 interface — later stages build on these):
    load_domains(...)            -> {name: policy_dict} (validated, cached)
    get_domain(name)             -> policy dict (raises on unknown — fail closed)
    domain_policy(name)          -> full policy incl. advisory / review labels
    classify_domain(candidate)   -> domain name (keyword/entity heuristics,
                                    fallback 'custom' which requires
                                    explicit classification)
    PROFESSIONAL_REVIEW_RISK_LEVELS / RISK_LEVELS / PROMOTION_PATHS constants
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = PROJECT_ROOT / "config" / "hermes_research_domains.yaml"
CUSTOM_PATH = PROJECT_ROOT / "config" / "hermes_custom_research_domains.yaml"

# financial|tax|planning|legal|operational|general|variable per spec Part A;
# `medical` is the custom-file extension (health_general).
RISK_LEVELS = frozenset({
    "financial", "tax", "planning", "legal", "operational", "general",
    "variable", "medical",
})

PROMOTION_PATHS = frozenset({
    "research_topic", "watch_directive", "staged_ticker_review",
    "source_registry", "escalation_candidate",
})

# Candidates classified into a domain with one of these risk levels ALWAYS
# carry the professional-review label and safe_action_level=OPERATOR_REVIEW_REQUIRED.
PROFESSIONAL_REVIEW_RISK_LEVELS = frozenset({"tax", "planning", "legal", "medical"})

DEFAULT_PROFESSIONAL_LABEL = "Research summary only — consult a qualified professional."
DEFAULT_ADVISORY_LABEL = ("Advisory research only — informational, never a "
                          "directive or trade instruction.")

FALLBACK_DOMAIN = "custom"

# Kept in sync with inbox.CANDIDATE_TYPES via a lazy cross-check at load time
# (lazy so this module never creates an import cycle with inbox.py).
_CANDIDATE_TYPES_FALLBACK = frozenset({
    "SOURCE_CANDIDATE", "TREND_CANDIDATE", "TICKER_CANDIDATE",
    "TOPIC_CANDIDATE", "CONNECTOR_CANDIDATE",
})

_BROKER_OPS_HINTS = ("broker", "brokerage", "schwab", "fidelity", "alpaca",
                     "snaptrade", "routing", "commission", "margin")


class DomainConfigError(Exception):
    """Raised when the domain registry fails validation (fail closed)."""


_cache: dict[str, dict[str, Any]] | None = None


def _candidate_types() -> frozenset[str]:
    try:  # lazy: inbox imports this module at top level, never the reverse
        from .inbox import CANDIDATE_TYPES
        return CANDIDATE_TYPES
    except Exception:
        return _CANDIDATE_TYPES_FALLBACK


def _read_yaml(path: Path, *, required: bool) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise DomainConfigError(f"domain registry missing: {path}")
        return {}
    import yaml
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise DomainConfigError(f"unparseable domain yaml {path}: {e}") from e
    if not isinstance(data, dict):
        raise DomainConfigError(f"domain yaml {path} must be a mapping, got {type(data).__name__}")
    return data


def _validate_domain(name: str, spec: dict[str, Any], *, source: str,
                     defaults: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise DomainConfigError(f"[{source}] domain {name!r} must be a mapping")

    risk = str(spec.get("risk_level") or "").strip().lower()
    if risk not in RISK_LEVELS:
        raise DomainConfigError(
            f"[{source}] domain {name!r}: unknown risk_level {risk!r} "
            f"(valid: {sorted(RISK_LEVELS)})")

    paths = list(spec.get("promotion_paths") or [])
    bad_paths = [p for p in paths if p not in PROMOTION_PATHS]
    if bad_paths:
        raise DomainConfigError(
            f"[{source}] domain {name!r}: unknown promotion_path(s) {bad_paths} "
            f"(valid: {sorted(PROMOTION_PATHS)})")

    ctypes = [str(t).upper() for t in (spec.get("allowed_candidate_types") or [])]
    bad_types = [t for t in ctypes if t not in _candidate_types()]
    if bad_types:
        raise DomainConfigError(
            f"[{source}] domain {name!r}: unknown allowed_candidate_types {bad_types} "
            f"(valid: {sorted(_candidate_types())})")

    needs_review = bool(spec.get("requires_professional_review_label")) or \
        risk in PROFESSIONAL_REVIEW_RISK_LEVELS

    policy: dict[str, Any] = {
        "name": name,
        "source": source,
        "description": str(spec.get("description") or "").strip(),
        "risk_level": risk,
        "allowed_candidate_types": ctypes,
        "promotion_paths": paths,
        "requires_operator_for_promotion": bool(
            spec.get("requires_operator_for_promotion",
                     defaults.get("requires_operator_for_promotion", True))),
        "requires_citation": bool(spec.get("requires_citation", False)),
        "requires_professional_review_label": needs_review,
        "no_personal_advice": bool(spec.get("no_personal_advice", needs_review)),
        "professional_review_label": (
            str(spec.get("professional_review_label") or DEFAULT_PROFESSIONAL_LABEL)
            if needs_review else None),
        "advisory_label": str(spec.get("advisory_label")
                              or defaults.get("advisory_label")
                              or DEFAULT_ADVISORY_LABEL),
        "requires_classification": bool(spec.get("requires_classification", False)),
        "classification_keywords": [str(k).lower() for k in
                                    (spec.get("classification_keywords") or [])],
        # auto_promote is ALWAYS false — hard rule, regardless of the yaml.
        "auto_promote": False,
    }
    # custom-file-only extensions (harmless to carry for base domains too)
    for extra in ("allowed_source_types", "blocked_source_types",
                  "denylist_terms", "entity_types"):
        policy[extra] = list(spec.get(extra) or [])
    policy["llm_review_required"] = bool(spec.get("llm_review_required", False))
    return policy


def load_domains(registry_path: Path | str | None = None,
                 custom_path: Path | str | None = None,
                 force_reload: bool = False) -> dict[str, dict[str, Any]]:
    """Load + merge + validate both domain yamls.

    Custom entries override/extend the base registry. Result is cached for the
    default paths; explicit paths (tests) always load fresh. Any validation
    failure raises DomainConfigError — the discovery layer fails closed rather
    than classifying against a broken registry.
    """
    global _cache
    default_paths = registry_path is None and custom_path is None
    if default_paths and _cache is not None and not force_reload:
        return _cache

    reg_p = Path(registry_path) if registry_path else REGISTRY_PATH
    cus_p = Path(custom_path) if custom_path else CUSTOM_PATH

    base = _read_yaml(reg_p, required=True)
    custom = _read_yaml(cus_p, required=False)

    defaults = dict(base.get("defaults") or {})
    merged: dict[str, dict[str, Any]] = {}
    for name, spec in (base.get("domains") or {}).items():
        merged[str(name)] = _validate_domain(str(name), spec, source="registry",
                                             defaults=defaults)
    for name, spec in (custom.get("domains") or {}).items():
        merged[str(name)] = _validate_domain(str(name), spec, source="custom",
                                             defaults=defaults)

    if FALLBACK_DOMAIN not in merged:
        raise DomainConfigError(
            f"domain registry must define the {FALLBACK_DOMAIN!r} fallback domain")

    if default_paths:
        _cache = merged
    return merged


def get_domain(name: str) -> dict[str, Any]:
    """Fetch one domain policy. Unknown name raises (fail closed)."""
    doms = load_domains()
    key = str(name or "").strip().lower()
    if key not in doms:
        raise DomainConfigError(
            f"unknown research domain {name!r} (registered: {sorted(doms)})")
    return dict(doms[key])


def domain_policy(name: str) -> dict[str, Any]:
    """Full policy for a domain, including advisory/professional-review labels."""
    return get_domain(name)


# ── classification ───────────────────────────────────────────────────────────

def _candidate_text(candidate: dict[str, Any]) -> str:
    """Flatten the searchable text of a candidate dict (label, summary,
    meta keywords/specialty, evidence notes)."""
    parts: list[str] = [str(candidate.get("label") or ""),
                        str(candidate.get("summary") or "")]
    meta = candidate.get("meta_json") or candidate.get("meta") or {}
    if isinstance(meta, dict):
        for key in ("keywords", "specialty", "tags", "entities"):
            val = meta.get(key)
            if isinstance(val, (list, tuple)):
                parts.extend(str(v) for v in val)
            elif val:
                parts.append(str(val))
    for item in (candidate.get("evidence_json") or candidate.get("evidence") or []):
        if isinstance(item, dict) and item.get("note"):
            parts.append(str(item["note"]))
    return " ".join(parts).lower()


def _keyword_hits(text: str, keywords: list[str]) -> int:
    hits = 0
    for kw in keywords:
        if not kw:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])", text):
            hits += 1
    return hits


def classify_domain(candidate: dict[str, Any]) -> str:
    """Heuristic domain classification for a candidate dict.

    Order of precedence:
      1. explicit meta.research_domain (validated) — stability on re-sightings;
      2. TICKER_CANDIDATE → portfolio_holdings when the symbol is currently
         held (read-only holdings.json lookup), else watchlist;
      3. CONNECTOR_CANDIDATE → broker_ops on broker-ish text, else system_ops;
      4. best classification_keywords hit count across all domains;
      5. fallback 'custom' (requires explicit classification before promotion).
    """
    doms = load_domains()

    meta = candidate.get("meta_json") or candidate.get("meta") or {}
    if isinstance(meta, dict):
        pinned = str(meta.get("research_domain") or "").strip().lower()
        if pinned and pinned in doms:
            return pinned

    ctype = str(candidate.get("candidate_type") or "").strip().upper()
    text = _candidate_text(candidate)

    if ctype == "TICKER_CANDIDATE":
        symbol = str(candidate.get("label") or "").strip().upper()
        try:  # lazy import: subjects imports this module at top level
            from .subjects import held_symbols
            if symbol and symbol in held_symbols():
                return "portfolio_holdings"
        except Exception:
            pass
        return "watchlist"

    if ctype == "CONNECTOR_CANDIDATE":
        if any(h in text for h in _BROKER_OPS_HINTS):
            return "broker_ops"
        return "system_ops"

    best_name, best_hits = FALLBACK_DOMAIN, 0
    for name, policy in doms.items():
        if name == FALLBACK_DOMAIN:
            continue
        if ctype and policy["allowed_candidate_types"] and \
                ctype not in policy["allowed_candidate_types"]:
            continue
        hits = _keyword_hits(text, policy["classification_keywords"])
        if hits > best_hits:
            best_name, best_hits = name, hits
    return best_name if best_hits > 0 else FALLBACK_DOMAIN


def is_professional_review_domain(name: str) -> bool:
    """True when candidates in this domain must carry the professional-review
    label and OPERATOR_REVIEW_REQUIRED safe action level."""
    return bool(get_domain(name).get("requires_professional_review_label"))


# test/support hook
def _reset_cache() -> None:
    global _cache
    _cache = None


# Optional env override for the config dir (mirrors no-hardcoded-values rule).
_env_dir = os.getenv("HERMES_RESEARCH_DOMAINS_DIR")
if _env_dir:
    REGISTRY_PATH = Path(_env_dir) / "hermes_research_domains.yaml"
    CUSTOM_PATH = Path(_env_dir) / "hermes_custom_research_domains.yaml"
