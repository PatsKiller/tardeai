"""Read-only publication checks for rotation; never calculates financial advice.

The scorer remains the owner of financial math. This adapter binds its existing
projection to exact accounts and source evidence, or withholds it. Old caches
remain readable as UNAVAILABLE until the existing producer refreshes them.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from typing import Any

from .account_state import parse_time, project_account_state

SCHEMA = "RotationPublication@v1"
WITHHELD_FIELDS = (
    "research_rotation_ideas", "top_rotation_ideas", "top_pairs", "top_candidates",
    "degraded_holdings", "etf_candidates", "fee_swaps", "sector_overweights", "sector_underweights",
)


class PublicationError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def input_digest(holdings: dict) -> str:
    return hashlib.sha256(_canonical(holdings).encode()).hexdigest()


def unique_rows(rows: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """Keep original order and selection. Conflicting identities are not choices."""
    seen: dict[tuple, str] = {}
    out = []
    for row in rows:
        identity = tuple(row.get(k) for k in keys)
        if any(not isinstance(v, str) or not v.strip() for v in identity):
            raise PublicationError("missing_identity")
        wire = _canonical(row)
        if identity in seen:
            if seen[identity] != wire:
                raise PublicationError("conflicting_identity")
        else:
            seen[identity] = wire
            out.append(row)
    return out


def account_key(row: dict) -> str | None:
    # Same identity fields as rotation_intelligence_engine.score_row; no inferred
    # account-type/symbol joins and no broker/account-specific literals.
    value = row.get("account_key") or row.get("account")
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def exact_position(rows: list[dict], symbol: str, account: str | None) -> dict:
    if not account:
        raise PublicationError("missing_account_identity")
    found = [x for x in rows if x.get("symbol") == symbol and account_key(x) == account]
    if not found:
        raise PublicationError("missing_account_position")
    # Duplicate source rows with the same symbol/account may be lots or a source
    # conflict; only exactly identical copies are safe to collapse.
    if len({_canonical(x) for x in found}) != 1:
        raise PublicationError("conflicting_account_position")
    return found[0]


def project_summary(summary: dict, holdings: dict, *, cached: bool = False,
                    now: datetime | None = None, market_service=None) -> dict:
    """Apply source truth at both computed-output and persisted-cache boundaries."""
    now = now or datetime.now(timezone.utc)
    out = copy.deepcopy(summary) if isinstance(summary, dict) else {}
    unavailable, stale, accounts = [], [], []
    unavailable.extend(out.pop("_publication_errors", []))
    prior = out.get("publication") or {}
    if not isinstance(prior, dict):
        prior = {}
        unavailable.append("malformed_publication")
    try:
        source_digest = input_digest(holdings)
    except (ValueError, TypeError):
        source_digest = None
        unavailable.append("malformed_input")
    if cached and (prior.get("schema") != SCHEMA or prior.get("input_sha256") != source_digest):
        unavailable.append("unbound_cache_inputs")
    if prior.get("status") in {"UNAVAILABLE", "STALE"}:
        # A re-read is never a new production attempt that cures held output.
        (stale if prior["status"] == "STALE" else unavailable).extend(prior.get("reasons") or ["prior_output_held"])
    producer_ok = prior.get("producer_ok") if cached and prior.get("schema") == SCHEMA else out.get("ok")
    if producer_ok is not True:
        unavailable.append("source_unavailable")
    if out.get("stale") is True:
        stale.append("cache_stale")
    cached_ts = out.get("_cached_ts")
    if cached_ts is not None:
        if not isinstance(cached_ts, (int, float)) or isinstance(cached_ts, bool) or not math.isfinite(cached_ts) or cached_ts > now.timestamp() + 60:
            unavailable.append("invalid_cache_clock")
        elif now.timestamp() - cached_ts > 900:  # existing rotation cache SLA
            stale.append("cache_stale")
    elif cached:
        unavailable.append("missing_cache_clock")
    rows = holdings.get("holdings") if isinstance(holdings, dict) else None
    summaries = holdings.get("account_summaries") if isinstance(holdings, dict) else None
    if not isinstance(rows, list) or not rows or not isinstance(summaries, dict):
        unavailable.append("missing_input")
        rows, summaries = [], {}
    used = set()
    for row in rows:
        if not isinstance(row, dict):
            unavailable.append("malformed_input")
            continue
        if row.get("is_cash"):
            continue
        acct = account_key(row)
        if not acct:
            unavailable.append("missing_account_identity")
            continue
        if acct in used:
            continue
        used.add(acct)
        raw = summaries.get(acct)
        if not isinstance(raw, dict):
            unavailable.append("missing_account_state")
            continue
        projected = project_account_state(raw)
        block = raw.get("account_state") or {}
        if not isinstance(block, dict):
            block = {}
            unavailable.append("malformed_account_state")
        state = projected["state"]
        as_of = block.get("last_sync_at") or projected.get("state_as_of")
        accounts.append({"account_key": acct, "state": state, "source_as_of": as_of})
        if state == "STALE":
            stale.append("account_stale")  # never override an explicit producer refusal
        elif state != "LIVE":
            unavailable.append("account_unavailable")
        else:
            stamp = parse_time(as_of)
            window = block.get("sync_window_hours")
            if stamp is None or stamp > now or not isinstance(window, (int, float)) or isinstance(window, bool) or not math.isfinite(window) or window <= 0:
                unavailable.append("invalid_account_clock")
            else:
                # Reuse the existing portfolio market-calendar contract. Friday
                # close during the weekend is not stale just because 48h passed.
                from .cio_market_aware_freshness import is_stale
                from .cio_domain_registry import CIODomainRegistry
                try:
                    capability = CIODomainRegistry.load().get("portfolio")
                    if is_stale(stamp, now, window * 3600,
                                market_hours_only=capability.freshness_market_hours_only, service=market_service):
                        stale.append("account_evidence_stale")
                except (OSError, ValueError, KeyError, RuntimeError):
                    unavailable.append("freshness_policy_unavailable")
    try:
        out["research_rotation_ideas"] = unique_rows(out.get("research_rotation_ideas") or [], ("from_account_key", "from_symbol", "to_symbol"))
        for idea in out["research_rotation_ideas"]:
            position = exact_position(rows, idea["from_symbol"], idea["from_account_key"])
            idea["from_shares_held"] = position.get("shares")
            idea["position_as_of"] = position.get("broker_position_as_of_at") or position.get("broker_position_as_of") or position.get("as_of")
            dg = idea.get("from_degradation") or {}
            rng = idea.get("review_amount_range") or {}
            if "stop hit" in str(rng.get("basis") or "").lower() and not (
                dg.get("deterministic") is True and dg.get("signal_source") == "stop_distance"
                and dg.get("thesis_status") in {"triggered", "danger", "warning"}
            ):
                unavailable.append("unsupported_stop_claim")
    except (PublicationError, TypeError, ValueError, AttributeError) as exc:
        unavailable.append(str(exc) if isinstance(exc, PublicationError) else "malformed_proposal")
    status = "UNAVAILABLE" if unavailable else "STALE" if stale else "READY"
    out["publication"] = {
        "schema": SCHEMA, "status": status, "reasons": sorted(set(unavailable + stale)),
        "producer_ok": producer_ok is True,
        "checked_at": now.isoformat(), "input_sha256": source_digest,
        "source_as_of": holdings.get("as_of") if isinstance(holdings, dict) else None,
        "cache_generated_at": out.get("generated_at"), "cached_at": out.get("cached_at") or out.get("_cached_at"),
        "accounts": accounts,
    }
    if status != "READY":
        out["ok"] = False
        out["stale"] = status == "STALE" or bool(stale)
        for key in WITHHELD_FIELDS:
            out[key] = []
    return out


def ready(summary: dict) -> bool:
    if not isinstance(summary, dict):
        return False
    p = summary.get("publication")
    if not isinstance(p, dict) or p.get("schema") != SCHEMA or p.get("status") != "READY" or summary.get("ok") is not True:
        return False
    checked = parse_time(p.get("checked_at"))
    now = datetime.now(timezone.utc)
    digest = p.get("input_sha256")
    return (checked is not None and 0 <= (now - checked).total_seconds() <= 900
            and isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
            and p.get("reasons") == [] and isinstance(p.get("accounts"), list) and bool(p["accounts"]))
