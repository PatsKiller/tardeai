"""Route-side attachment of ``BrokerEvidence@v1`` to a payload the route already publishes (b3).

The adapter layer (:mod:`lib.broker_contract_adapters`) wraps a payload; this module is the one
call a route makes to attach the result. It exists so the route edit is one line, the logic has a
unit test, and a failure to build evidence can never take the page down or hide itself:

* the payload is returned **unchanged except for one additive ``evidence`` key**;
* the version vector is the payload's own stamps — a missing stamp is *omitted*, never defaulted,
  so a missing input cannot masquerade as an older or a newer one;
* if an adapter raises, the block says ``FAILED`` with the exception class and message and a
  ``next_action``. It is never omitted, never silently ``None``;
* no read: no DB, no file, no provider, no clock of its own. ``now`` is injected.

Directive B (one broker): a page consumes the canonical projection and this block; it does not
recompute a financial number. Directive C: the typed fields are the payload's, carried through.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from lib.broker_contract_adapters import portfolio_evidence, positions_evidence, stale_window
from lib.broker_metrics import metrics, scope_coverage


def version_vector(payload: dict[str, Any]) -> dict[str, Any]:
    """product -> the stamp the payload itself publishes. Missing inputs are omitted, not defaulted.

    The three products are the three inputs the holdings payload names: the positions store read,
    the quote marks, and the market-day measure materialization. ``measures_materialized_at`` is
    written by the repricer (``scripts/portfolio_repricer.py``); a payload built before that block
    existed omits it, and the snapshot id then honestly differs from a later one.
    """
    out: dict[str, Any] = {}
    for product, field in (
        ("positions_store", "positions_as_of"),
        ("quote_price", "quote_as_of"),
        ("portfolio_market_day", "measures_materialized_at"),
    ):
        value = payload.get(field)
        if value:
            out[product] = value
    return out


def scope_of(payload: dict[str, Any]) -> dict[str, Any]:
    """The accounts the payload actually carries, plus the payload's own cutoff and session.

    The account list is taken from the rows, so a scope line cannot claim an account the book does
    not contain. ``session_id`` is threaded through when the producer supplies it and left null
    otherwise — this module does not invent a market session.
    """
    accounts = sorted({str(r.get("account_id")) for r in payload.get("holdings") or []
                       if isinstance(r, dict) and r.get("account_id")})
    return {"accounts": accounts,
            "session_id": payload.get("session_id"),
            "cutoff": payload.get("positions_as_of")}


def _failed(exc: BaseException) -> dict[str, Any]:
    return {"verdict": "FAILED",
            "cause": {"code": "EVIDENCE_BUILD_FAILED",
                      "detail": f"{type(exc).__name__}: {exc}",
                      "owner": "broker-contract",
                      "next_action": "read the route log; the payload itself is unchanged"}}


_UNSET = object()


def attach(payload: dict[str, Any], *, now: datetime | None = None,
           window_domain: str = "positions_store", window: Any = _UNSET) -> dict[str, Any]:
    """Return ``payload`` with an additive ``evidence`` block: portfolio and positions envelopes.

    ``window`` is the declared stale window of the domain the route serves. Omitted, the registry row
    for ``window_domain`` is read once (read-only). Passed as ``None`` it means *no declared window*
    and is honoured as such — the adapter then reports ``UNKNOWN`` / ``NO_FRESHNESS_CONTRACT``. The
    distinction matters: "not given" is a lookup, "None" is a fact.

    This function does not raise: the route wraps the whole call in nothing because there is nothing
    to wrap. Every failure path returns the payload with a named block.
    """
    try:
        return _attach(payload, now=now or datetime.now(timezone.utc),
                       domain=window_domain, window=window)
    except Exception as exc:  # noqa: BLE001 -- the page keeps its payload; the block names the failure
        out = dict(payload) if isinstance(payload, dict) else {}
        out["evidence"] = {"portfolio": _failed(exc), "positions": _failed(exc)}
        return out


def _attach(payload: dict[str, Any], *, now: datetime, domain: str, window: Any) -> dict[str, Any]:
    versions = version_vector(payload)
    scope = scope_of(payload)
    declared = stale_window(domain) if window is _UNSET else window
    evidence: dict[str, Any] = {}
    for name, build in (("portfolio", portfolio_evidence), ("positions", positions_evidence)):
        try:
            evidence[name] = build(payload, versions=versions, scope=scope,
                                   stale_after_hours=declared, now=now)
        except Exception as exc:  # noqa: BLE001 -- one failed block does not blank the other
            evidence[name] = _failed(exc)
    out = dict(payload)
    out["evidence"] = evidence
    # HQ-07 / PR-002: every figure the page publishes is citable by a metric id under this snapshot, and
    # the row census behind it is stated. Both are lifted from the payload; neither adds a number. A payload
    # whose portfolio envelope did not build has no snapshot id, so it publishes no metrics and says why.
    snapshot = (evidence.get("portfolio") or {}).get("snapshot_id")
    if not snapshot:
        out["metrics"] = []
        out["metrics_failure"] = {
            "verdict": "UNKNOWN",
            "cause": {"code": "NO_SNAPSHOT",
                      "detail": "the portfolio envelope did not build, so there is no snapshot to cite",
                      "owner": "broker-contract",
                      "next_action": "read evidence.portfolio.cause"}}
        return out
    try:
        out["metrics"] = metrics(payload, snapshot_id=snapshot, scope=scope)
        out["scope_coverage"] = scope_coverage(payload, snapshot_id=snapshot, scope=scope)
    except Exception as exc:  # noqa: BLE001 -- the page keeps its payload; the failure names itself
        out["metrics"] = []
        out["metrics_failure"] = _failed(exc)
    return out
