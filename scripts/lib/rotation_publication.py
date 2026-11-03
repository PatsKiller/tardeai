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

from .account_state import observation_instant, position_observation, project_account_state

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


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _aware_time(value):
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp if stamp.tzinfo is not None and stamp.utcoffset() is not None else None
    except ValueError:
        return None


def _market_row(row: Any) -> dict | None:
    if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip() for k in ("etf", "name")):
        return None

    def number(key):
        value = row.get(key)
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None

    out = {"etf": row["etf"], "name": row["name"]}
    out.update({key: number(key) for key in ("return_1m", "return_3m", "return_6m")})
    quality = number("data_quality")
    proven = quality is not None and quality > 0 and any(out[k] is not None for k in ("return_1m", "return_3m", "return_6m"))
    out.update({"data_quality": quality, "quality_status": "KNOWN" if proven else "UNKNOWN",
                "rs_raw": number("rs_raw") if proven else None,
                "rs_score": number("rs_score") if proven else None})
    return out


def market_research(summary: dict, *, now: datetime) -> dict:
    """Project neutral market groups, independently of account advice readiness.

    The existing snapshot is read only. Never call the adapter's get/build path:
    it may query a DB or write a cache. No thesis transitions pass this allowlist.
    """
    candidate = summary.get("sector_ladders")
    source = "summary.sector_ladders"
    if not isinstance(candidate, dict) or not (candidate.get("sectors") or candidate.get("industries")):
        candidate = summary.get("market_research")
        source = "summary.market_research"
        if not isinstance(candidate, dict) or candidate.get("schema") != "RotationMarketResearch@v1":
            candidate = None
    snapshot_bytes = None
    if candidate is None:
        from .data_broker import rotation_ladders
        path = getattr(rotation_ladders, "SNAPSHOT_PATH", None)
        source = "stored_rotation_ladders"
        if path is not None:
            try:
                snapshot_bytes = path.read_bytes()
                value = json.loads(snapshot_bytes)
                candidate = value if isinstance(value, dict) else None
            except (OSError, ValueError, TypeError):
                candidate = None
    candidate = candidate or {}
    sectors = [_market_row(r) for r in candidate.get("sectors", [])] if isinstance(candidate.get("sectors"), list) else []
    industries = []
    groups = candidate.get("industries")
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict) or not isinstance(group.get("sector"), str) or not isinstance(group.get("industries"), list):
            continue
        members = [_market_row(r) for r in group["industries"]]
        industries.append({"sector": group["sector"], "industries": [r for r in members if r is not None]})
    computed = observation_instant(candidate.get("computed_at"), now=now)
    return {
        "schema": "RotationMarketResearch@v1", "scope": "MARKET_GROUP_OBSERVATIONS",
        "available": any(r is not None for r in sectors) or any(g["industries"] for g in industries),
        "sectors": [r for r in sectors if r is not None], "industries": industries,
        "computed_at": _iso_utc(computed) if computed else None,
        "quote_as_of": None, "freshness": "UNKNOWN",
        "gaps": ["Underlying quote observation times are not retained; computed_at is a build clock."],
        "cache": {"source": source, "snapshot_read_only": source == "stored_rotation_ladders",
                  "source_sha256": hashlib.sha256(snapshot_bytes).hexdigest() if snapshot_bytes is not None else None,
                  "build_age_seconds": max(0, (now - computed).total_seconds()) if computed else None,
                  "build_age_basis": "computed_at"},
    }


def project_summary(summary: dict, holdings: dict, *, cached: bool = False,
                    now: datetime | None = None, market_service=None) -> dict:
    """Apply source truth at both computed-output and persisted-cache boundaries."""
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    out = copy.deepcopy(summary) if isinstance(summary, dict) else {}
    out["market_research"] = market_research(out, now=now)
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
    required_positions = dated_positions = dated_accounts = day_precision_positions = 0
    from .cio_market_aware_freshness import is_stale
    from .cio_domain_registry import CIODomainRegistry
    try:
        capability = CIODomainRegistry.load().get("portfolio")
    except (OSError, ValueError, KeyError, RuntimeError):
        capability = None
        unavailable.append("freshness_policy_unavailable")
    def source_is_stale(stamp, window):
        try:
            return is_stale(stamp, now, window * 3600,
                            market_hours_only=capability.freshness_market_hours_only, service=market_service)
        except Exception:  # noqa: BLE001 - a failed calendar is unavailable evidence
            unavailable.append("freshness_calendar_unavailable")
            return False

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
        as_of = block.get("last_sync_at") if "last_sync_at" in block else projected.get("state_as_of")
        window = block.get("sync_window_hours")
        valid_window = isinstance(window, (int, float)) and not isinstance(window, bool) and math.isfinite(window) and window > 0
        position_stamp, _, position_precision = position_observation(row, now=now)
        if position_stamp is None or position_stamp > now:
            unavailable.append("invalid_position_clock")
        else:
            dated_positions += 1
            bound_times.append(position_stamp)
            if position_precision == "day":
                day_precision_positions += 1
            if valid_window and capability and source_is_stale(position_stamp, window):
                stale.append("position_evidence_stale")
        if acct in used:
            continue
        used.add(acct)
        account_stamp = observation_instant(as_of, now=now)
        accounts.append({"account_key": acct, "state": state,
                         "source_as_of": _iso_utc(account_stamp) if account_stamp else None,
                         "source_as_of_raw": as_of})
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
            stamp = observation_instant(as_of, now=now)
            if stamp is None or stamp > now or not valid_window:
                unavailable.append("invalid_account_clock")
            else:
                # Reuse the existing portfolio market-calendar contract. Friday
                # close during the weekend is not stale just because 48h passed.
                if capability and source_is_stale(stamp, window):
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
        "checked_at": _iso_utc(now), "input_sha256": source_digest,
        "source_as_of": _iso_utc(min(bound_times)) if bound_times and dated_positions == required_positions and dated_accounts == len(accounts) else None,
        "oldest_known_source_as_of": _iso_utc(min(bound_times)) if bound_times else None,
        "newest_known_source_as_of": _iso_utc(max(bound_times)) if bound_times else None,
        "source_as_of_basis": "oldest_required_position_or_account_timestamp",
        "holdings_reported_as_of": holdings.get("as_of") if isinstance(holdings, dict) else None,
        "coverage": {"required_positions": required_positions, "dated_positions": dated_positions,
                     "day_precision_positions": day_precision_positions,
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
            and all(isinstance(a, dict) and isinstance(a.get("account_key"), str) and a["account_key"].strip()
                    and a.get("state") == "LIVE" and _aware_time(a.get("source_as_of")) is not None
                    and _aware_time(a["source_as_of"]) <= now for a in p["accounts"]))


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
