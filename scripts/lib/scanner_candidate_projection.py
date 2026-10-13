"""Shared read-only scanner/advisory candidates (operator 2026-10-12).

Consumes existing scanner cache and ActiveTrader advisory journal, without importing
an engine, broker, credential loader or writer. Both Command Center views consume
SharedMomentumCandidates@v1. Source verdicts are observations, never approvals.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .momentum_setup_evidence import build_setup_evidence, observation_lineage

SCHEMA = "SharedMomentumCandidates@v1"
AT_CONTRACT = "active-trader-momentum-alert-v1"
ET = ZoneInfo("America/New_York")
SOURCE_NAMES = ("ACTIVE_TRADER", "TRADE_AI")
TRADE_VERDICTS = {"GO", "WAIT", "AVOID", "NOGO", "NO_GO", "MANUAL_REVIEW", "AWARE", "EXCLUDED", "REVIEW"}
UNAVAILABLE = {"MISSING", "MALFORMED", "OVERSIZED", "UNAVAILABLE"}


def _stamp(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, timezone.utc) if math.isfinite(value) else None
        except (ValueError, OverflowError, OSError):
            return None
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None


def _day(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _symbol(value):
    if not isinstance(value, str):
        return None
    value = value.strip().upper()
    return value if re.fullmatch(r"[A-Z0-9][A-Z0-9.^/-]{0,19}", value) else None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _source_view(observations, status, day):
    unique = {_digest(o): o for o in observations}
    rows = sorted(unique.values(), key=lambda o: (o.get("observed_at") or "", _digest(o)), reverse=True)
    dates = {o["session_date"] for o in rows if o.get("session_date")}
    state = "UNKNOWN" if not dates else "CURRENT_SESSION" if day in dates else "STALE_SESSION"
    if status in UNAVAILABLE:
        state = "UNKNOWN"
    return {
        "status": status if status in UNAVAILABLE else "OBSERVED" if rows else "MISSING",
        "session_state": state,
        "verdicts": sorted({o["verdict"] for o in rows}),
        "observations": rows,
    }


def build_candidate_projection(
    cache, journal, *, now=None, source_status=None, source_details=None, criteria=None, criteria_source=None
):
    """Union both populations without changing either authoritative input."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("projection clock must be timezone-aware")
    today = now.astimezone(ET).date().isoformat()
    statuses = dict(source_status or {})
    valid_cache = isinstance(cache, dict) and isinstance(cache.get("tickers"), list)
    valid_journal = isinstance(journal, list)
    statuses.setdefault("TRADE_AI", "AVAILABLE" if valid_cache else "MALFORMED")
    statuses.setdefault("ACTIVE_TRADER", "AVAILABLE" if valid_journal else "MALFORMED")
    cache = cache if isinstance(cache, dict) else {}
    summary = cache.get("setup_run_summary") if isinstance(cache.get("setup_run_summary"), dict) else {}
    cache_run = summary.get("run_id") or cache.get("run_id")
    business_date = _day(summary.get("run_date")) or _day(cache_run) or _day(cache.get("run_date"))
    top_date = _day(cache.get("run_date")) or _day(cache.get("date"))
    groups = {}
    invalid = {name: 0 for name in SOURCE_NAMES}

    def add(symbol, source, observation):
        lineage = observation["lineage"]
        scope = (
            lineage.get("security_guid") or f"unresolved:{symbol}",
            lineage.get("session_date"),
            lineage.get("event_id"),
            lineage.get("event_at"),
        )
        groups.setdefault((symbol, scope), {name: [] for name in SOURCE_NAMES})[source].append(observation)

    if valid_cache and statuses["TRADE_AI"] not in UNAVAILABLE:
        owner_observations = cache.get("source_observations")
        for row in owner_observations if isinstance(owner_observations, list) else cache["tickers"]:
            if not isinstance(row, dict) or not (sym := _symbol(row.get("symbol"))):
                invalid["TRADE_AI"] += 1
                continue
            raw_verdict = str(row.get("decision") or "UNKNOWN").upper()
            verdict = raw_verdict if raw_verdict in TRADE_VERDICTS else "UNKNOWN"
            run_id = row.get("run_id")
            if not isinstance(run_id, str):
                run_id = (
                    f"{row['run_date']}::{row['run_label']}" if row.get("run_date") and row.get("run_label") else None
                )
            lineage = observation_lineage(row, source_name="TRADE_AI", run_id=run_id)
            stamp = _stamp(lineage["observed_at"])
            session_date = (
                _day(run_id)
                or _day(row.get("run_date"))
                or (stamp.astimezone(ET).date().isoformat() if stamp else None)
            )
            add(
                sym,
                "TRADE_AI",
                {
                    "verdict": verdict,
                    "reported_verdict": raw_verdict,
                    "observed_at": stamp.isoformat() if stamp else None,
                    "session_date": session_date,
                    "run_id": run_id,
                    "run_type": row.get("run_type") if isinstance(row.get("run_type"), str) else None,
                    "cache_run_id": cache_run,
                    "source": "TRADE_AI",
                    "lineage": lineage,
                    "event_at": lineage["event_at"],
                    "source_ref": lineage["source_ref"],
                    "security_guid": lineage["security_guid"],
                    "setup_evidence": build_setup_evidence(
                        row,
                        now=now,
                        observed_at=stamp.isoformat() if stamp else None,
                        source_name="TRADE_AI",
                        source_stale=bool(cache.get("stale") or cache.get("cache_error")),
                        criteria=criteria,
                        criteria_source=criteria_source,
                    ),
                    "freshness": "STALE" if cache.get("stale") or cache.get("cache_error") else "NOT_MEASURED",
                },
            )
    if valid_journal and statuses["ACTIVE_TRADER"] not in UNAVAILABLE:
        for row in journal:
            if (
                not isinstance(row, dict)
                or row.get("contract") != AT_CONTRACT
                or not isinstance(row.get("candidate"), dict)
            ):
                invalid["ACTIVE_TRADER"] += 1
                continue
            c = row["candidate"]
            if not (sym := _symbol(c.get("symbol"))):
                invalid["ACTIVE_TRADER"] += 1
                continue
            advisory_at = _stamp(row.get("ts_epoch"))
            source_observation = dict(c)
            if not source_observation.get("observed_at") and advisory_at:
                source_observation["observed_at"] = advisory_at.isoformat()
            lineage = observation_lineage(source_observation, source_name="ACTIVE_TRADER")
            # The journal timestamp proves publication of the advisory, not the quote's observation time.
            stamp = _stamp(lineage["observed_at"])
            verdict = row.get("verdict") if row.get("verdict") in {"ALERT", "VETO"} else "UNKNOWN"
            add(
                sym,
                "ACTIVE_TRADER",
                {
                    "verdict": verdict,
                    "observed_at": stamp.isoformat() if stamp else None,
                    "session_date": _day(c.get("session_date"))
                    or (stamp.astimezone(ET).date().isoformat() if stamp else None),
                    "run_id": c.get("run_id") if isinstance(c.get("run_id"), str) else None,
                    "kind": row.get("kind") if isinstance(row.get("kind"), str) else "UNKNOWN",
                    "sent": row.get("sent") if isinstance(row.get("sent"), bool) else None,
                    "source": "ACTIVE_TRADER",
                    "lineage": lineage,
                    "observation_basis": "ADVISORY_PUBLICATION" if not c.get("observed_at") else "SOURCE_OBSERVATION",
                    "event_at": lineage["event_at"],
                    "source_ref": lineage["source_ref"],
                    "security_guid": lineage["security_guid"],
                    "published_at": (_stamp(row.get("ts_epoch")).isoformat() if _stamp(row.get("ts_epoch")) else None),
                    "setup_evidence": build_setup_evidence(
                        c,
                        now=now,
                        observed_at=stamp.isoformat() if stamp else None,
                        source_name="ACTIVE_TRADER",
                        criteria=criteria,
                        criteria_source=criteria_source,
                    ),
                    "freshness": "NOT_MEASURED",
                },
            )
    candidates = []
    for (symbol, scope), observations in sorted(groups.items(), key=lambda item: str(item[0])):
        ta = _source_view(observations["TRADE_AI"], statuses["TRADE_AI"], today)
        at = _source_view(observations["ACTIVE_TRADER"], statuses["ACTIVE_TRADER"], today)
        conflicts = []
        if len(ta["verdicts"]) > 1:
            conflicts.append("TRADE_AI_VERDICT_CONFLICT")
        if len(at["verdicts"]) > 1:
            conflicts.append("ACTIVE_TRADER_VERDICT_CONFLICT")
        comparable = bool(scope[0] and not scope[0].startswith("unresolved:") and scope[1] and scope[3])
        if comparable and (
            ("ALERT" in at["verdicts"] and set(ta["verdicts"]) & {"AVOID", "NOGO", "NO_GO", "EXCLUDED"})
            or ("VETO" in at["verdicts"] and "GO" in ta["verdicts"])
        ):
            conflicts.append("CROSS_SOURCE_DISAGREEMENT")
        classification = (
            "CONFLICT"
            if conflicts
            else "UNKNOWN"
            if ta["observations"] and ta["session_state"] == "UNKNOWN"
            else "STALE"
            if ta["observations"]
            and (ta["session_state"] == "STALE_SESSION" or cache.get("stale") or cache.get("cache_error"))
            else ta["verdicts"][0]
            if len(ta["verdicts"]) == 1
            else "PENDING"
            if at["observations"]
            else "UNKNOWN"
        )
        candidates.append(
            {
                "candidate_id": f"symbol:{symbol}:{_digest(scope)[:16]}",
                "symbol": symbol,
                "security_guid": scope[0] if not scope[0].startswith("unresolved:") else None,
                "session_date": scope[1],
                "event_id": scope[2],
                "event_at": scope[3],
                "reconciliation_status": "COMPARABLE_EVENT" if comparable else "IDENTITY_OR_EVENT_UNRESOLVED",
                "sources": [name for name in SOURCE_NAMES if observations[name]],
                "trade_ai": ta,
                "active_trader": at,
                "classification": classification,
                "conflicts": conflicts,
                "execution_authority": "NONE",
            }
        )
    for name in SOURCE_NAMES:
        if invalid[name] and statuses[name] not in UNAVAILABLE:
            statuses[name] = "PARTIAL"
    usable = sum(statuses[name] not in UNAVAILABLE for name in SOURCE_NAMES)
    status = (
        "UNAVAILABLE"
        if not usable
        else "PARTIAL"
        if usable < 2 or any(invalid.values()) or any(statuses[name] == "PARTIAL" for name in SOURCE_NAMES)
        else "AVAILABLE"
    )
    details = source_details or {}
    metadata = {
        name: {
            "status": statuses[name],
            "invalid_rows": invalid[name],
            "freshness_bound_seconds": "NOT_MEASURED",
            **details.get(name, {}),
        }
        for name in SOURCE_NAMES
    }
    metadata["TRADE_AI"].update(
        {
            "cache_run_id": cache_run,
            "business_run_date": business_date,
            "business_date_mismatch": bool(top_date and business_date and top_date != business_date),
            "summary": {
                k: v
                for k, v in summary.items()
                if k
                in {
                    "run_id",
                    "run_date",
                    "run_label",
                    "run_timestamp",
                    "source",
                    "scanned_count",
                    "classified_count",
                    "go_count",
                    "wait_count",
                    "nogo_count",
                    "excluded_count",
                    "error_count",
                    "count_integrity",
                    "count_integrity_reason",
                    "freshness_status",
                }
                and isinstance(v, (str, int, float, bool, type(None)))
            },
            "stale": cache.get("stale"),
            "cache_error": cache.get("cache_error"),
            "cache_generated_at": cache.get("_cached_at"),
        }
    )
    identity = [{**r, "trade_ai": r["trade_ai"], "active_trader": r["active_trader"]} for r in candidates]
    projection_hash = _digest(
        {
            "schema": SCHEMA,
            "candidates": identity,
            "source_status": statuses,
            "source_metadata": {
                name: {key: value for key, value in fields.items() if key != "cache_generated_at"}
                for name, fields in metadata.items()
            },
        }
    )
    source_sha = cache.get("source_sha") or cache.get("code_sha")
    if not isinstance(source_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        source_sha = "UNKNOWN"
    finished = _stamp(summary.get("run_timestamp"))
    if finished is None and cache.get("run_id") == cache_run:
        finished = _stamp(cache.get("latest_run_timestamp"))
    return {
        "population_contract": "shared_signal_union",
        "run_id": cache_run,
        "run_date": business_date,
        "source_sha": source_sha,
        "finished_at": finished.isoformat() if finished else None,
        "projection_hash": projection_hash,
        "source_verdicts_preserved": True,
        "schema": SCHEMA,
        "owner": "platform",
        "producer": "scanner_candidate_projection",
        "consumers": ["Trade AI", "Active Trader"],
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "calculation_version": "1.1.0",
        "session_date": today,
        "generated_at": now.astimezone(timezone.utc).isoformat(),
        "snapshot_id": projection_hash,
        "status": status,
        "candidate_count": len(candidates) if usable else None,
        "candidate_count_scope": "OBSERVED_SOURCE_UNION",
        "source_read_consistency": "INDEPENDENT_OWNER_SNAPSHOTS",
        "candidates": candidates,
        "source_metadata": metadata,
        "note": "Source verdicts remain separate; candidate union grants no execution or approval authority.",
    }


def read_candidate_snapshot(
    cache_path: Path, journal_path: Path, *, now=None, max_cache_bytes=16_000_000, max_journal_bytes=4_000_000
):
    """Bounded read only. Missing/unreadable sources are explicit, never empty success."""
    statuses, details = {}, {}
    cache, journal = None, None
    try:
        if cache_path.stat().st_size > max_cache_bytes:
            statuses["TRADE_AI"] = "OVERSIZED"
        else:
            with cache_path.open("rb") as fh:
                raw_cache = fh.read(max_cache_bytes + 1)
            if len(raw_cache) > max_cache_bytes:
                statuses["TRADE_AI"] = "OVERSIZED"
                raw_cache = None
            cache = json.loads(raw_cache) if raw_cache is not None else None
            statuses.setdefault(
                "TRADE_AI",
                "AVAILABLE" if isinstance(cache, dict) and isinstance(cache.get("tickers"), list) else "MALFORMED",
            )
    except FileNotFoundError:
        statuses["TRADE_AI"] = "MISSING"
    except (OSError, ValueError):
        statuses["TRADE_AI"] = "MALFORMED"
    try:
        size = journal_path.stat().st_size
        truncated = size > max_journal_bytes
        with journal_path.open("rb") as fh:
            if truncated:
                fh.seek(size - max_journal_bytes)
                fh.readline()
            lines = fh.read(max_journal_bytes).decode("utf-8", "replace").splitlines()
        journal, bad = [], 0
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    journal.append(row)
                else:
                    bad += 1
            except ValueError:
                bad += 1
        statuses["ACTIVE_TRADER"] = "PARTIAL" if bad or truncated else "AVAILABLE"
        details["ACTIVE_TRADER"] = {"tail_truncated": truncated, "malformed_lines": bad}
    except FileNotFoundError:
        statuses["ACTIVE_TRADER"] = "MISSING"
    except OSError:
        statuses["ACTIVE_TRADER"] = "MALFORMED"
    from .scalp_go_criteria import load_criteria

    return build_candidate_projection(
        cache,
        journal,
        now=now,
        source_status=statuses,
        source_details=details,
        criteria=load_criteria(),
        criteria_source="scripts/lib/scalp_go_criteria.py:load_criteria (config or documented fallback)",
    )
