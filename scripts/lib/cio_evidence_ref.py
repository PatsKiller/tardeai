"""Canonical EvidenceRef@v1 — the single evidence envelope for every material fact.

Every numerical conclusion in the investment office must trace to one or more
EvidenceRef objects. An EvidenceRef pins, for a single value/claim:

  - WHAT the fact is (value, hashed deterministically)
  - WHERE it came from (source, source_record_id, source_timestamp)
  - WHEN it was observed (observed_at) and how old it is (freshness_state)
  - HOW good it is (quality_state)
  - WHICH deterministic calculation produced it (deterministic_calculation_version)

This is a provider-call-free, pure module. It never invents values: callers pass
the value and the provenance; this module only derives freshness, hashes, and
renders the FACT -> SOURCE -> AGE -> QUALITY -> SPECIALIST -> CIO chain.

The freshness_state enum is separate from quality_state deliberately:
  - freshness_state = age of the source record vs its policy threshold (temporal)
  - quality_state   = completeness/authority of the evidence (semantic)
A fact can be FRESH but PARTIAL (e.g. holdings-derived cash, which is timely but
not verified broker buying power), or STALE but AVAILABLE (an old but complete
tax lot).

READ_ONLY_ADVISORY — no broker/order/stop/2FA authority, no provider calls.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.cio_domain_evidence import (
    QUALITY_STATE_AVAILABLE,
    QUALITY_STATE_CONFLICTED,
    QUALITY_STATE_DATA_UNAVAILABLE,
    QUALITY_STATE_ERROR,
    QUALITY_STATE_NOT_APPLICABLE,
    QUALITY_STATE_PARTIAL,
    QUALITY_STATE_STALE,
)

# ── freshness_state enum ──────────────────────────────────────────────────────

FRESHNESS_FRESH = "FRESH"
FRESHNESS_STALE = "STALE"
FRESHNESS_UNKNOWN = "UNKNOWN"
FRESHNESS_NOT_TIMESTAMPED = "NOT_TIMESTAMPED"
FRESHNESS_NOT_APPLICABLE = "NOT_APPLICABLE"

FRESHNESS_STATES = frozenset({
    FRESHNESS_FRESH,
    FRESHNESS_STALE,
    FRESHNESS_UNKNOWN,
    FRESHNESS_NOT_TIMESTAMPED,
    FRESHNESS_NOT_APPLICABLE,
})

# ── scope enum ────────────────────────────────────────────────────────────────

SCOPE_NONE = "none"
SCOPE_PORTFOLIO = "portfolio"
SCOPE_SLEEVE = "sleeve"
SCOPE_SECTOR = "sector"
SCOPE_SYMBOL = "symbol"
SCOPE_ACCOUNT = "account"
SCOPE_HOUSEHOLD = "household"

SCOPE_TYPES = frozenset({
    SCOPE_NONE,
    SCOPE_PORTFOLIO,
    SCOPE_SLEEVE,
    SCOPE_SECTOR,
    SCOPE_SYMBOL,
    SCOPE_ACCOUNT,
    SCOPE_HOUSEHOLD,
})

# EVIDENCE_QUALITY_STATES is the single source of truth; re-export the names used
# by callers so this module is the drop-in envelope.
EVIDENCE_QUALITY_STATES = frozenset({
    QUALITY_STATE_AVAILABLE,
    QUALITY_STATE_PARTIAL,
    QUALITY_STATE_STALE,
    QUALITY_STATE_DATA_UNAVAILABLE,
    QUALITY_STATE_CONFLICTED,
    QUALITY_STATE_ERROR,
    QUALITY_STATE_NOT_APPLICABLE,
})

BLOCKING_QUALITY_STATES = frozenset({
    QUALITY_STATE_DATA_UNAVAILABLE,
    QUALITY_STATE_ERROR,
    QUALITY_STATE_STALE,
    QUALITY_STATE_CONFLICTED,
})


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def value_hash(value: Any) -> str:
    """Deterministic sha256 of a value for provenance pinning.

    JSON round-trips via canonical key ordering so the same logical value always
    hashes identically regardless of dict insertion order. Non-JSON-serializable
    values fall back to repr() (rare; deterministic-only inputs expected).
    """
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        canonical = repr(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def freshness_state_for(
    source_timestamp: Optional[str],
    observed_at: Optional[str],
    threshold_seconds: Optional[int],
) -> str:
    """Derive freshness_state from the source record age vs its policy threshold.

    Returns NOT_TIMESTAMPED when the source carries no timestamp, UNKNOWN when
    the timestamp cannot be parsed, FRESH when within threshold, STALE when past.
    NOT_APPLICABLE when no threshold is configured for the domain.
    """
    if not source_timestamp:
        return FRESHNESS_NOT_TIMESTAMPED
    if threshold_seconds is None:
        return FRESHNESS_NOT_APPLICABLE

    try:
        src = datetime.fromisoformat(str(source_timestamp))
    except (ValueError, TypeError):
        return FRESHNESS_UNKNOWN
    if src.tzinfo is None:
        src = src.replace(tzinfo=timezone.utc)

    ref = None
    if observed_at:
        try:
            ref = datetime.fromisoformat(str(observed_at))
        except (ValueError, TypeError):
            ref = None
        if ref is not None and ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
    if ref is None:
        ref = datetime.now(timezone.utc)

    age_s = (ref - src).total_seconds()
    if age_s < 0:
        # Source timestamp is in the future (clock skew) — treat as FRESH, not STALE.
        return FRESHNESS_FRESH
    return FRESHNESS_FRESH if age_s <= threshold_seconds else FRESHNESS_STALE


@dataclass
class EvidenceRef:
    """One evidence envelope for one material fact. See module docstring."""

    domain: str
    ref_id: str = ""
    symbol: Optional[str] = None
    account: Optional[str] = None
    scope: Optional[str] = SCOPE_NONE
    source: str = ""
    source_record_id: str = ""
    source_timestamp: str = ""
    observed_at: str = ""
    freshness_state: str = FRESHNESS_UNKNOWN
    quality_state: str = QUALITY_STATE_AVAILABLE
    deterministic_calculation_version: str = ""
    value_hash: str = ""
    limitations: list[str] = field(default_factory=list)
    value: Any = None

    def __post_init__(self) -> None:
        if not self.ref_id:
            self.ref_id = f"ref_{uuid.uuid4().hex[:16]}"
        if not self.observed_at:
            self.observed_at = utc_now_iso()
        if self.scope is None:
            self.scope = SCOPE_NONE
        if self.quality_state not in EVIDENCE_QUALITY_STATES:
            raise ValueError(
                f"Invalid quality_state {self.quality_state!r}; "
                f"expected one of {sorted(EVIDENCE_QUALITY_STATES)}"
            )
        if self.freshness_state not in FRESHNESS_STATES:
            raise ValueError(
                f"Invalid freshness_state {self.freshness_state!r}; "
                f"expected one of {sorted(FRESHNESS_STATES)}"
            )
        if self.scope not in SCOPE_TYPES:
            raise ValueError(
                f"Invalid scope {self.scope!r}; expected one of {sorted(SCOPE_TYPES)}"
            )

    # ── properties ─────────────────────────────────────────────────────────

    @property
    def is_blocking(self) -> bool:
        return self.quality_state in BLOCKING_QUALITY_STATES

    @property
    def is_stale(self) -> bool:
        return self.freshness_state == FRESHNESS_STALE or self.quality_state == QUALITY_STATE_STALE

    @property
    def age_seconds(self) -> Optional[float]:
        if not self.source_timestamp:
            return None
        try:
            src = datetime.fromisoformat(str(self.source_timestamp))
        except (ValueError, TypeError):
            return None
        if src.tzinfo is None:
            src = src.replace(tzinfo=timezone.utc)
        try:
            obs = datetime.fromisoformat(str(self.observed_at))
        except (ValueError, TypeError):
            obs = datetime.now(timezone.utc)
        if obs.tzinfo is None:
            obs = obs.replace(tzinfo=timezone.utc)
        return (obs - src).total_seconds()

    # ── serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        d = {
            "ref_id": self.ref_id,
            "domain": self.domain,
            "scope": self.scope,
            "source": self.source,
            "source_record_id": self.source_record_id,
            "source_timestamp": self.source_timestamp,
            "observed_at": self.observed_at,
            "freshness_state": self.freshness_state,
            "quality_state": self.quality_state,
            "deterministic_calculation_version": self.deterministic_calculation_version,
            "value_hash": self.value_hash,
            "limitations": list(self.limitations),
        }
        if self.symbol is not None:
            d["symbol"] = self.symbol
        if self.account is not None:
            d["account"] = self.account
        if self.value is not None:
            d["value"] = self.value
        return d

    # ── builders ───────────────────────────────────────────────────────────

    def attach_value(self, value: Any) -> "EvidenceRef":
        """Set the value and compute its deterministic value_hash in place."""
        self.value = value
        self.value_hash = value_hash(value)
        return self


def make_ref(
    domain: str,
    value: Any,
    *,
    source: str = "",
    source_record_id: str = "",
    source_timestamp: str = "",
    observed_at: str = "",
    freshness_state: str = FRESHNESS_UNKNOWN,
    quality_state: str = QUALITY_STATE_AVAILABLE,
    deterministic_calculation_version: str = "",
    symbol: Optional[str] = None,
    account: Optional[str] = None,
    scope: Optional[str] = None,
    limitations: Optional[list[str]] = None,
) -> EvidenceRef:
    """Construct a fully-pinned EvidenceRef for a value in one call."""
    if scope is None:
        if symbol is not None:
            scope = SCOPE_SYMBOL
        elif account is not None:
            scope = SCOPE_ACCOUNT
        else:
            scope = SCOPE_NONE
    ref = EvidenceRef(
        domain=domain,
        symbol=symbol,
        account=account,
        scope=scope,
        source=source,
        source_record_id=source_record_id,
        source_timestamp=source_timestamp,
        observed_at=observed_at or utc_now_iso(),
        freshness_state=freshness_state,
        quality_state=quality_state,
        deterministic_calculation_version=deterministic_calculation_version,
        limitations=list(limitations or []),
    )
    ref.attach_value(value)
    return ref


# ── quality gate renderer ─────────────────────────────────────────────────────


def render_chain(
    ref: EvidenceRef,
    *,
    specialist: Optional[str] = None,
    cio: Optional[str] = None,
) -> str:
    """Render one evidence ref as FACT -> SOURCE -> AGE -> QUALITY -> SPECIALIST -> CIO."""
    fact = json.dumps(ref.value, default=str) if ref.value is not None else f"<{ref.domain}>"
    if ref.value is not None and ref.value_hash:
        fact += f" (h={ref.value_hash[:8]})"
    age = "—"
    if ref.age_seconds is not None:
        age = f"{int(ref.age_seconds)}s"
    source = ref.source or "(unsourced)"
    if ref.source_record_id:
        source += f"#{ref.source_record_id}"
    chain = [
        f"FACT: {fact}",
        f"SOURCE: {source}",
        f"AGE: {age} ({ref.freshness_state})",
        f"QUALITY: {ref.quality_state}",
    ]
    if specialist:
        chain.append(f"SPECIALIST: {specialist}")
    if cio:
        chain.append(f"CIO: {cio}")
    return " -> ".join(chain)


def render_evidence_chain(
    refs: list[EvidenceRef],
    *,
    specialist: Optional[str] = None,
    cio: Optional[str] = None,
) -> list[str]:
    """Render a list of refs as operator-facing FACT->SOURCE->AGE->QUALITY chains."""
    return [render_chain(r, specialist=specialist, cio=cio) for r in refs]


def gate_action(
    refs: list[EvidenceRef],
    required_domains: list[str],
) -> dict[str, Any]:
    """Fail-closed action gate over an evidence set.

    Returns ok=False if any required domain is missing (no ref, or a ref whose
    quality_state is in the blocking set). Never manufactures evidence — an
    absent required domain is a hard block.
    """
    by_domain: dict[str, list[EvidenceRef]] = {}
    for r in refs:
        by_domain.setdefault(r.domain, []).append(r)

    missing: list[str] = []
    blocking: list[str] = []
    for d in required_domains:
        entries = by_domain.get(d)
        if not entries:
            missing.append(d)
            continue
        if any(e.is_blocking for e in entries):
            blocking.append(d)

    return {
        "ok": not missing and not blocking,
        "required_domains": list(required_domains),
        "missing_domains": missing,
        "blocking_domains": blocking,
    }
