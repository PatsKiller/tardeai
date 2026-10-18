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
    "research_candidates", "sector_ladders",
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


def _aware_time(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo is not None and stamp.utcoffset() is not None else None
    except ValueError:
        return None


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
    generated = _aware_time(out.get("generated_at"))
    if generated is None or generated > now:
        unavailable.append("invalid_engine_clock")
    elif (now - generated).total_seconds() > 900:  # same declared rotation output/cache SLA
        stale.append("engine_output_stale")
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
    used, bound_times = set(), []
    required_positions = dated_positions = dated_accounts = 0
    from .cio_market_aware_freshness import is_stale
    from .cio_domain_registry import CIODomainRegistry
    try:
        capability = CIODomainRegistry.load().get("portfolio")
    except (OSError, ValueError, KeyError, RuntimeError):
        capability = None
        unavailable.append("freshness_policy_unavailable")
    for row in rows:
        if not isinstance(row, dict):
            unavailable.append("malformed_input")
            continue
        if row.get("is_cash"):
            continue
        required_positions += 1
        acct = account_key(row)
        if not acct:
            unavailable.append("missing_account_identity")
            continue
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
        if raw.get("state") and block.get("state") and raw["state"] != block["state"]:
            (stale if "STALE" in (raw["state"], block["state"]) else unavailable).append("account_state_conflict")
        if block.get("contract_version") != "AccountState@v1" or not block.get("state"):
            unavailable.append("unsupported_account_state")
        as_of = block.get("last_sync_at") or projected.get("state_as_of")
        window = block.get("sync_window_hours")
        valid_window = isinstance(window, (int, float)) and not isinstance(window, bool) and math.isfinite(window) and window > 0
        position_stamp = parse_time(row.get("broker_position_as_of_at") or row.get("broker_position_as_of") or row.get("as_of"))
        if position_stamp is None or position_stamp > now:
            unavailable.append("invalid_position_clock")
        else:
            dated_positions += 1
            bound_times.append(position_stamp)
            if valid_window and capability and is_stale(position_stamp, now, window * 3600,
                                                       market_hours_only=capability.freshness_market_hours_only, service=market_service):
                stale.append("position_evidence_stale")
        if acct in used:
            continue
        used.add(acct)
        account_stamp = parse_time(as_of)
        accounts.append({"account_key": acct, "state": state, "source_as_of": account_stamp.isoformat() if account_stamp else as_of})
        if account_stamp is None or account_stamp > now:
            unavailable.append("invalid_account_clock")
        else:
            dated_accounts += 1
            bound_times.append(account_stamp)
        if state == "STALE":
            stale.append("account_stale")  # never override an explicit producer refusal
        elif state != "LIVE":
            unavailable.append("account_unavailable")
        else:
            stamp = parse_time(as_of)
            if stamp is None or stamp > now or not valid_window:
                unavailable.append("invalid_account_clock")
            else:
                # Reuse the existing portfolio market-calendar contract. Friday
                # close during the weekend is not stale just because 48h passed.
                if capability and is_stale(stamp, now, window * 3600,
                                          market_hours_only=capability.freshness_market_hours_only, service=market_service):
                    stale.append("account_evidence_stale")
    try:
        out["research_rotation_ideas"] = unique_rows(out.get("research_rotation_ideas") or [], ("from_account_key", "from_symbol", "to_symbol"))
        for idea in out["research_rotation_ideas"]:
            position = exact_position(rows, idea["from_symbol"], idea["from_account_key"])
            idea["from_shares_held"] = position.get("shares")
            idea["position_as_of"] = position.get("broker_position_as_of_at") or position.get("broker_position_as_of") or position.get("as_of")
            dg = idea.get("from_degradation") or {}
            rng = idea.get("review_amount_range") or {}
            if rng and (not isinstance(rng, dict) or rng.get("action") not in {"trim", "review_trim", "reduce", "reduce_or_close"}):
                unavailable.append("unsupported_review_action")
            if rng and (set(rng) != {"low", "high", "basis", "action"} or not isinstance(rng.get("basis"), str)
                        or any(not isinstance(rng.get(k), (int, float)) or isinstance(rng.get(k), bool)
                               or not math.isfinite(rng[k]) or rng[k] < 0 for k in ("low", "high"))
                        or rng["low"] > rng["high"]):
                unavailable.append("malformed_review_range")
            if (rng.get("action") == "reduce_or_close" or "stop hit" in str(rng.get("basis") or "").lower()) and not (
                dg.get("deterministic") is True and dg.get("signal_source") == "stop_distance"
                and dg.get("thesis_status") in {"triggered", "danger", "warning"}
            ):
                unavailable.append("unsupported_stop_claim")
    except (PublicationError, TypeError, ValueError, AttributeError) as exc:
        unavailable.append(str(exc) if isinstance(exc, PublicationError) else "malformed_proposal")
    if not bound_times or not required_positions:
        unavailable.append("missing_bound_source_clock")
    status = "UNAVAILABLE" if unavailable else "STALE" if stale else "READY"
    out["publication"] = {
        "schema": SCHEMA, "status": status, "reasons": sorted(set(unavailable + stale)),
        "producer_ok": producer_ok is True,
        "checked_at": now.isoformat(), "input_sha256": source_digest,
        "source_as_of": min(bound_times).isoformat() if bound_times else None,
        "source_as_of_basis": "oldest_required_position_or_account_timestamp",
        "holdings_reported_as_of": holdings.get("as_of") if isinstance(holdings, dict) else None,
        "coverage": {"required_positions": required_positions, "dated_positions": dated_positions,
                     "accounts": len(accounts), "dated_accounts": dated_accounts},
        "cache_generated_at": out.get("generated_at"), "cached_at": out.get("cached_at") or out.get("_cached_at"),
        "accounts": accounts,
    }
    if status != "READY":
        out["ok"] = False
        out["stale"] = status == "STALE" or bool(stale)
        for key in WITHHELD_FIELDS:
            out[key] = None if key == "sector_ladders" else []
        out["summary"] = {}  # unavailable counters are not measured zeros
    return out


def ready(summary: dict) -> bool:
    if not isinstance(summary, dict):
        return False
    p = summary.get("publication")
    if not isinstance(p, dict) or p.get("schema") != SCHEMA or p.get("status") != "READY" or summary.get("ok") is not True:
        return False
    checked = _aware_time(p.get("checked_at"))
    now = datetime.now(timezone.utc)
    digest = p.get("input_sha256")
    engine_time = _aware_time(p.get("cache_generated_at"))
    source_time = _aware_time(p.get("source_as_of"))
    coverage = p.get("coverage")
    return (checked is not None and 0 <= (now - checked).total_seconds() <= 900
            and engine_time is not None and 0 <= (now - engine_time).total_seconds() <= 900
            and source_time is not None and source_time <= now
            and p.get("source_as_of_basis") == "oldest_required_position_or_account_timestamp"
            and isinstance(coverage, dict) and type(coverage.get("required_positions")) is int
            and coverage["required_positions"] > 0 and coverage.get("dated_positions") == coverage["required_positions"]
            and isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
            and p.get("producer_ok") is True and p.get("reasons") == []
            and isinstance(p.get("accounts"), list) and bool(p["accounts"])
            and coverage.get("dated_accounts") == coverage.get("accounts") == len(p["accounts"])
            and all(isinstance(a, dict) and isinstance(a.get("account_key"), str) and a["account_key"]
                    and a.get("state") == "LIVE" and parse_time(a.get("source_as_of")) is not None for a in p["accounts"]))


def publication_refusal(summary: dict) -> dict | None:
    """One typed consumer refusal, before provider/DB/research work."""
    if ready(summary):
        return None
    p = summary.get("publication") if isinstance(summary, dict) else None
    p = p if isinstance(p, dict) else {}
    status = "STALE" if p.get("schema") == SCHEMA and p.get("status") == "STALE" else "UNAVAILABLE"
    reasons = p.get("reasons")
    if not isinstance(reasons, list) or not reasons or not all(isinstance(r, str) for r in reasons):
        reasons = ["missing_or_unsupported_publication_evidence"]
    return {"ok": False, "advisory_only": True, "error": "rotation_publication_unavailable",
            "publication": {"schema": SCHEMA, "status": status, "reasons": reasons}}
