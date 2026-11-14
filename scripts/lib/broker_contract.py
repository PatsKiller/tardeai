"""BrokerContract@v1 — one evidence/snapshot envelope per business domain (SPRINT 8H-2 b1).

Package §4 ("Shared broker and consistency contract"): every payload binds to a
``snapshot_id``/input version vector and a declared scope, and keeps ``source_as_of``,
``built_at``, ``checked_at``, ``served_at``, ``stale_after``, ``expires_at`` and
``session_id`` DISTINCT. "A fresh wrapper/build cannot rejuvenate stale contents." Relative text
is computed at render, never stored as prose.

This module is ADDITIVE to ``scripts/lib/data_broker/envelope.py`` (``BrokerReadEnvelope@v1``,
250 call sites): that remains the wire shape existing consumers already read, and
:func:`to_read_envelope` renders this contract back to it, so adoption is per-endpoint and no
consumer breaks. Nothing here reads a database, filesystem or clock of its own — ``now`` is
injected, so every state is testable.

Semantics that are deliberate, not incidental
---------------------------------------------
* **Staleness derives from ``source_as_of`` and the domain's declared window only.** ``built_at``,
  ``checked_at`` and ``served_at`` are provenance, never freshness. A rebuild over a stale source
  stays STALE.
* **A future observation is invalid evidence**, not freshness: :func:`build_evidence` raises and
  :func:`validate` rejects it. A future *event* time (a session open, an expiry) is a legitimate
  event time when ``kind="event"``.
* **No fabricated values.** An explicitly missing value with an OK verdict becomes UNKNOWN with
  ``cause.code == "NO_VALUE"``. A domain without a registry row (no declared stale window) is
  UNKNOWN with ``cause.code == "NO_FRESHNESS_CONTRACT"``, never OK-by-default.
* **P&L is never verified by agreement.** ``pnl()`` returns ``verified: false`` unless a signed
  reconciliation is supplied; two candidate numbers matching is an arithmetic check only.
* **A plan never promotes broker UNKNOWN.** ``resolve_authority`` keeps the canonical authority
  first and exposes a planning record as a separate facet.

AUTHORITY: READ_ONLY_ADVISORY. Adds metadata and verdicts; never changes a projection's data.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SCHEMA = "BrokerEvidence@v1"
READ_ENVELOPE_SCHEMA = "BrokerReadEnvelope@v1"

VERDICTS = (
    "OK",
    "STALE",
    "UNKNOWN",
    "PARTIAL",
    "FAILED",
    "NEVER_MEASURED",
    "CORRECTED",
    "SUPERSEDED",
)

#: The seven clocks the package requires to stay distinct. Order is the reading order in a trace.
CLOCK_FIELDS = (
    "source_as_of",
    "built_at",
    "checked_at",
    "served_at",
    "stale_after_hours",
    "expires_at",
    "session_id",
)

#: Which source may establish a claim, most authoritative first (package §4 + PR-018's list).
#: A lower entry NEVER upgrades a higher one: see :func:`resolve_authority`.
AUTHORITY_PRECEDENCE: dict[str, tuple[str, ...]] = {
    "positions": ("broker_position_receipts", "broker_positions_store", "plan_store"),
    "quantity": ("broker_position_receipts", "broker_positions_store"),
    "marks": ("quote_observations", "third_party_mark_estimate"),
    "protection": ("broker_order_receipts", "plan_store"),
    "pnl": ("signed_account_reconciliation", "account_change", "price_move"),
    "concentration": ("approved_policy",),
    "lifecycle": ("current_state_store",),
}

#: Sources that are a FACET of a claim, never the claim. A plan describes intent; it cannot answer
#: "is this position protected at the broker". Excluded from authority selection even when it is the
#: only candidate present (b1 review F1).
FACET_SOURCES = frozenset({"plan_store"})

_UNSET = object()


# ── time helpers (pure; ``now`` always injected) ─────────────────────────────


def _as_dt(value: Any) -> datetime | None:
    """Coerce datetime / ISO string / epoch to an aware UTC datetime; None when unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(value: Any) -> str | None:
    """Normalise to ISO-8601: datetimes keep their isoformat, strings render with a ``Z`` suffix."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    dt = _as_dt(value)
    if dt is None:
        return None
    return dt.isoformat().replace("+00:00", "Z")


def age_hours(source_as_of: Any, now: datetime) -> float | None:
    dt = _as_dt(source_as_of)
    if dt is None:
        return None
    return round(max(0.0, (now - dt).total_seconds() / 3600.0), 2)


# ── identity ─────────────────────────────────────────────────────────────────


def canonical_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    """Normalise a scope for identity: sorted accounts/instruments, explicit session and cutoff.

    The scope is part of the snapshot identity: a value computed for one account set or session
    must never equal the same value computed for another.
    """
    s = dict(scope or {})
    out: dict[str, Any] = {
        "accounts": sorted(str(a) for a in (s.get("accounts") or [])),
        "instruments": sorted(str(i).upper() for i in (s.get("instruments") or [])),
        "session_id": s.get("session_id"),
        "cutoff": iso(s.get("cutoff")) if s.get("cutoff") else None,
    }
    for k, v in s.items():
        if k not in out:
            out[k] = v
    return out


def version_vector(versions: dict[str, Any] | None) -> dict[str, str]:
    """{product: version} with every version rendered as a string; empty versions are refused."""
    out: dict[str, str] = {}
    for k, v in (versions or {}).items():
        if v is None or v == "":
            raise ValueError(f"version vector entry {k!r} is empty: an input with no version cannot be cited")
        out[str(k)] = str(v)
    if not out:
        raise ValueError("a snapshot needs at least one input version")
    return dict(sorted(out.items()))


def snapshot_id(versions: dict[str, Any] | None, scope: dict[str, Any] | None) -> str:
    """Deterministic identity over the version vector + scope: ``snap_<16 hex>``.

    Serving the same inputs again (a reload, a later ``served_at``) reproduces the same id; any
    input version or scope difference produces a different one.
    """
    payload = {"versions": version_vector(versions), "scope": canonical_scope(scope)}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return f"snap_{digest[:16]}"


# ── the envelope ─────────────────────────────────────────────────────────────


def _cause(code: str, *, detail: str | None = None, owner: str | None = None, next_action: str | None = None) -> dict[str, Any]:
    """A named cause: what is wrong, who owns it, and the exact next action (never a bare null)."""
    return {"code": code, "detail": detail, "owner": owner, "next_action": next_action}


def build_evidence(
    domain: str,
    *,
    verdict: str = "OK",
    versions: dict[str, Any] | None,
    scope: dict[str, Any] | None = None,
    source_as_of: Any,
    built_at: Any = None,
    checked_at: Any = None,
    served_at: Any = None,
    stale_after_hours: float | None = None,
    expires_at: Any = None,
    session_id: str | None = None,
    completeness: dict[str, Any] | None = None,
    last_good: dict[str, Any] | None = None,
    value: Any = _UNSET,
    cause: dict[str, Any] | None = None,
    kind: str = "observation",
    on_demand: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one domain's evidence envelope.

    Args:
        kind: ``"observation"`` (default) — a source timestamp after ``now`` is invalid and raises;
              ``"event"`` — a scheduled future time is a legitimate event time.
        on_demand: the domain has no freshness contract by design and declares that explicitly;
              without it, a missing window is UNKNOWN (``NO_FRESHNESS_CONTRACT``).
        value: omit to leave the value out of the verdict logic; pass ``None`` to assert absence
              (``value=None`` under an OK verdict becomes UNKNOWN / ``NO_VALUE``).
        now: the evaluation clock. Defaults to the real clock only when a caller omits it.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"verdict {verdict!r} is not one of {VERDICTS}")
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)

    src_dt = _as_dt(source_as_of)
    if src_dt is not None and src_dt > ref and kind != "event":
        raise ValueError(
            f"source_as_of {iso(source_as_of)} is in the future relative to the evaluation clock "
            f"{ref.isoformat()}: an impossible observation is not freshness"
        )

    clocks = {
        "source_as_of": iso(source_as_of),
        "built_at": iso(built_at),
        "checked_at": iso(checked_at),
        "served_at": iso(served_at),
        "stale_after_hours": stale_after_hours,
        "expires_at": iso(expires_at),
        "session_id": session_id,
    }

    out_cause = dict(cause) if cause else None

    # 1. a value asserted absent can never be reported OK (the fabricated-zero class). A caller's
    #    cause explains the absence; it never licenses the claim, so the downgrade is unconditional.
    if value is not _UNSET and value is None and verdict == "OK":
        verdict = "UNKNOWN"
        out_cause = out_cause or _cause(
            "NO_VALUE", detail="the value is absent for this scope", next_action="refresh the source or read coverage"
        )
    # 2. no declared window ⇒ no freshness claim, whatever cause the caller supplied.
    if stale_after_hours is None and verdict in ("OK", "STALE"):
        if on_demand:
            out_cause = out_cause or _cause("ON_DEMAND", detail="this domain has no freshness contract by design")
        else:
            out_cause = out_cause or _cause(
                "NO_FRESHNESS_CONTRACT",
                detail=f"no stale window is declared for {domain!r}",
                next_action="add the domain to config/data_source_authority.json",
            )
        verdict = "UNKNOWN"
    # 3. staleness from the source clock only — never from built/checked/served
    gap: dict[str, Any] | None = None
    if verdict in ("OK", "STALE") and stale_after_hours is not None:
        age = age_hours(source_as_of, ref)
        if src_dt is None:
            verdict = "UNKNOWN"
            out_cause = _cause("NO_SOURCE_CLOCK", detail="no source observation time", next_action="re-run the producer")
        elif expires_at is not None and _as_dt(expires_at) is not None and _as_dt(expires_at) <= ref:
            verdict = "STALE"
            out_cause = _cause("EXPIRED", detail=f"evidence expired at {iso(expires_at)}", next_action="refresh the source")
            gap = {"kind": "stale", "last_as_of": iso(source_as_of)}
        elif age is not None and age > float(stale_after_hours):
            verdict = "STALE"
            out_cause = _cause(
                "AGE_EXCEEDS_WINDOW",
                detail=f"{age}h > {stale_after_hours}h",
                next_action="run the producer or investigate why it stopped",
            )
            gap = {"kind": "stale", "last_as_of": iso(source_as_of)}

    out: dict[str, Any] = {
        "schema": SCHEMA,
        "domain": domain,
        "kind": kind,
        "verdict": verdict,
        "snapshot_id": snapshot_id(versions, scope),
        "version_vector": version_vector(versions),
        "scope": canonical_scope(scope),
        "clocks": clocks,
        "completeness": completeness or {"counted": None, "total": None, "exclusions": []},
        "last_good": last_good,
        "cause": out_cause,
    }
    if value is not _UNSET:
        out["value"] = value
    if gap is not None:
        out["gap"] = gap
    return out


def validate(evidence: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Reject an envelope that claims something its clocks cannot support. Returns it unchanged."""
    if evidence.get("schema") != SCHEMA:
        raise ValueError(f"not a {SCHEMA} envelope: {evidence.get('schema')!r}")
    if evidence.get("verdict") not in VERDICTS:
        raise ValueError(f"verdict {evidence.get('verdict')!r} is not one of {VERDICTS}")
    clocks = evidence.get("clocks") or {}
    for k in CLOCK_FIELDS:
        if k not in clocks:
            raise ValueError(f"clock {k!r} is missing: the seven clocks must stay distinct")
    ref = now or datetime.now(timezone.utc)
    src = _as_dt(clocks.get("source_as_of"))
    if src is not None and src > ref and evidence.get("kind") != "event":
        raise ValueError(f"source_as_of {clocks.get('source_as_of')} is in the future relative to {ref.isoformat()}")
    if evidence.get("verdict") == "OK" and evidence.get("value", _UNSET) is None:
        raise ValueError("an OK verdict with value None would fabricate a value")
    if evidence.get("verdict") == "OK" and clocks.get("stale_after_hours") is None:
        raise ValueError("an OK verdict with no declared stale window cannot claim freshness")
    return evidence


# ── reconciliation (HQ-07 / PR-007) ─────────────────────────────────────────


def reconcile(
    *,
    headline_cents: int,
    rows: list[tuple[str, int | None]],
    tolerance_cents: int = 300,
) -> dict[str, Any]:
    """Bridge a headline to its contributing rows, or say exactly why it cannot be bridged.

    ``residual_cents`` is ``sum(rows) - headline``. A missing contributor (``None``) leaves the
    result INCOMPLETE with ``residual_cents: None`` — an incomplete population never produces a
    number that could be mistaken for reconciliation.
    """
    missing = [row_id for row_id, cents in rows if cents is None]
    if missing:
        return {
            "verdict": "INCOMPLETE",
            "headline_cents": headline_cents,
            "sum_cents": None,
            "residual_cents": None,
            "tolerance_cents": tolerance_cents,
            "missing": missing,
            "bridge": [{"id": i, "cents": c} for i, c in rows],
        }
    total = sum(int(c) for _, c in rows)
    residual = total - int(headline_cents)
    within = abs(residual) <= int(tolerance_cents)
    return {
        "verdict": "ARITHMETIC_OK" if within else "ARITHMETIC_RESIDUAL",
        "headline_cents": int(headline_cents),
        "sum_cents": total,
        "residual_cents": residual,
        "tolerance_cents": int(tolerance_cents),
        "missing": [],
        "bridge": [{"id": i, "cents": int(c)} for i, c in rows],
    }


def pnl(
    *,
    price_move_cents: int | None,
    account_change_cents: int | None,
    sign_off: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Daily P&L: price move and account change are distinct typed measures; verification is separate.

    Economic P&L becomes ``verified`` only with a signed reconciliation (an id, a signer, a time).
    Two candidate numbers agreeing is an arithmetic observation, not evidence: flows, income and
    fees must be sourced for a verified result.
    """
    out: dict[str, Any] = {
        "price_move_cents": price_move_cents,
        "account_change_cents": account_change_cents,
        "basis": "price_move",
        "verified": False,
        "reconciliation_id": None,
    }
    if not sign_off:
        out["reason"] = "no signed account reconciliation exists; price move is an estimate, not economic P&L"
        return out
    for k in ("reconciliation_id", "signed_at", "by"):
        if not sign_off.get(k):
            raise ValueError(f"sign_off is incomplete: {k!r} is required for a verified result")
    out["verified"] = True
    out["basis"] = "signed_account_reconciliation"
    out["reconciliation_id"] = sign_off["reconciliation_id"]
    out["signed_at"] = iso(sign_off["signed_at"])
    out["signed_by"] = sign_off["by"]
    return out


# ── authority ───────────────────────────────────────────────────────────────


def resolve_authority(*, domain: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick the most authoritative available source for a claim; never let a weaker one upgrade it.

    ``candidates`` are ``{"source", "state", "value"}`` records. The canonical authority (first in
    :data:`AUTHORITY_PRECEDENCE` that is present) decides the claim. A source in
    :data:`FACET_SOURCES` is a facet only: when the broker has not answered, the result is
    ``authority=None`` / ``state=UNKNOWN`` / ``cause.code=NO_AUTHORITY_SOURCE`` and the plan stays
    visible beside it (never promoted to the claim).
    """
    precedence = AUTHORITY_PRECEDENCE.get(domain)
    if not precedence:
        raise ValueError(f"no authority precedence is declared for domain {domain!r}")
    present = {c.get("source"): c for c in candidates}
    plan = next((c for c in candidates if c.get("source") == "plan_store"), None)
    plan_facet = {"source": plan.get("source"), "value": plan.get("value")} if plan else None
    chosen = next((present[s] for s in precedence if s in present and s not in FACET_SOURCES), None)
    if chosen is None:
        return {
            "domain": domain,
            "authority": None,
            "state": "UNKNOWN",
            "value": None,
            "plan": plan_facet,
            "cause": _cause("NO_AUTHORITY_SOURCE", detail="no declared source answered for this claim",
                            next_action="read the broker source or report the gap"),
        }
    return {
        "domain": domain,
        "authority": chosen.get("source"),
        "state": chosen.get("state") or "UNKNOWN",
        "value": chosen.get("value"),
        "plan": plan_facet,
        "cause": None if chosen.get("state") not in (None, "UNKNOWN") else _cause(
            "AUTHORITY_UNKNOWN",
            detail=f"{chosen.get('source')} answered with no evidence",
            next_action="reconcile the broker read",
        ),
    }


# ── registry coverage ───────────────────────────────────────────────────────


def registry_gaps(required: list[str], registry: dict[str, Any]) -> list[str]:
    """Required domains with no registry row (no stale window, closed-hours window or dead-feed rule)."""
    return [d for d in required if d not in (registry or {})]


# ── BrokerReadEnvelope@v1 compatibility ─────────────────────────────────────


def to_read_envelope(evidence: dict[str, Any], *, now: datetime | None = None, source: dict[str, Any] | None = None) -> dict[str, Any]:
    """Render this contract as the existing ``BrokerReadEnvelope@v1`` shape every consumer reads."""
    clocks = evidence.get("clocks") or {}
    src = {"domain": evidence.get("domain"), **(source or {})}
    age = age_hours(clocks.get("source_as_of"), now or datetime.now(timezone.utc))
    verdict = evidence.get("verdict")
    return {
        "schema": READ_ENVELOPE_SCHEMA,
        "as_of": clocks.get("source_as_of"),
        "age_hours": age,
        "source": src,
        "stale": verdict == "STALE",
        "stale_after_hours": clocks.get("stale_after_hours"),
        "snapshot_id": evidence.get("snapshot_id"),
        "verdict": verdict,
    }


def from_read_envelope(
    read_envelope: dict[str, Any],
    *,
    domain: str,
    scope: dict[str, Any] | None,
    versions: dict[str, Any] | None,
    built_at: Any = None,
    checked_at: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Lift an existing ``BrokerReadEnvelope@v1`` payload into the contract without re-reading data."""
    if read_envelope.get("schema") != READ_ENVELOPE_SCHEMA:
        raise ValueError(f"not a {READ_ENVELOPE_SCHEMA} envelope: {read_envelope.get('schema')!r}")
    verdict = "STALE" if read_envelope.get("stale") else "OK"
    if read_envelope.get("as_of") is None:
        verdict = "UNKNOWN"
    return build_evidence(
        domain,
        verdict=verdict,
        versions=versions,
        scope=scope,
        source_as_of=read_envelope.get("as_of"),
        built_at=built_at,
        checked_at=checked_at,
        served_at=now,
        stale_after_hours=read_envelope.get("stale_after_hours"),
        session_id=(scope or {}).get("session_id"),
        cause=None if verdict != "UNKNOWN" else _cause("NO_COVERAGE", detail="the source answered nothing"),
        now=now,
    )
