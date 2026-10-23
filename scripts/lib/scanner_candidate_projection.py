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

from .momentum_setup_evidence import build_setup_evidence, observation_lineage, setup_readiness

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


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _clean(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def active_trader_catalyst(candidate, *, catalyst_lookup=None):
    """The catalyst the Active Trader alert prints, as evidence-row fields with its origin labelled.

    Same order as scripts/active_trader/momentum_alerts.py ``catalyst_line`` / ``_trade_ai_catalyst``:
    today's Trade-AI scan (setup_evidence.catalyst, then the raw column, then the day's earlier non-empty
    scan catalyst) -> Hermes scalp research through the data broker (FOUND only) -> nothing. The AT
    Candidate dataclass has no catalyst field, so before Gate 1 (2026-10-22) the projection read a
    top-level ``catalyst`` that never existed and every AT row showed no catalyst."""
    ta = _mapping(candidate.get("trade_ai"))
    facts = _mapping(ta.get("setup_evidence"))
    cat = _mapping(facts.get("catalyst"))
    day_cat = _mapping(ta.get("day_catalyst"))
    if _clean(cat.get("text")) or _clean(ta.get("catalyst")):
        reported = cat.get("reported_verified")
        if not isinstance(reported, bool):
            reported = ta.get("catalyst_verified") if isinstance(ta.get("catalyst_verified"), bool) else None
        return {
            "catalyst": _clean(cat.get("text")) or _clean(ta.get("catalyst")),
            "catalyst_source": _clean(cat.get("source")) or _clean(ta.get("catalyst_source")),
            "catalyst_url": cat.get("url") or ta.get("catalyst_url"),
            "catalyst_published_at": cat.get("original_published_at") or ta.get("catalyst_at"),
            "catalyst_verified": reported,
            "catalyst_verification_method": cat.get("verification_method"),
            "catalyst_origin": "TRADE_AI_SCAN",
        }
    if _clean(day_cat.get("text")):
        return {
            "catalyst": _clean(day_cat.get("text")),
            "catalyst_source": _clean(day_cat.get("source")),
            "catalyst_origin": "TRADE_AI_SCAN_EARLIER_TODAY",
        }
    symbol, day = _symbol(candidate.get("symbol")), _day(candidate.get("session_date"))
    rec = None
    if catalyst_lookup is not None and symbol and day:
        try:
            rec = catalyst_lookup(symbol, day)
        except Exception:  # noqa: BLE001 - a failed lookup is an absent catalyst, never a crash
            rec = None
    rec = _mapping(rec)
    text = _clean(rec.get("summary")) or _clean(rec.get("catalyst_type"))
    if rec.get("status") == "FOUND" and text:
        ctype = _clean(rec.get("catalyst_type"))
        return {
            "catalyst": text,
            "catalyst_source": f"Hermes {ctype}" if ctype else "Hermes",
            "catalyst_type": ctype,
            "catalyst_origin": "HERMES_SCALP_RESEARCH",
        }
    return {}


def _active_trader_evidence_row(candidate, *, catalyst_lookup=None):
    """The AT candidate plus the facts its alert already used: catalyst (labelled) and gap from today's
    Trade-AI row when the candidate has none (Gate 1 bug 5; the Candidate dataclass has no gap field)."""
    row = dict(candidate)
    if not _clean(row.get("catalyst")):
        row.update(active_trader_catalyst(candidate, catalyst_lookup=catalyst_lookup))
    ta = _mapping(candidate.get("trade_ai"))
    if row.get("gap_pct") is None and row.get("change_pct") is None:
        gap = ta.get("gap_pct") if ta.get("gap_pct") is not None else ta.get("change_pct")
        if gap is not None:
            row["gap_pct"] = gap
            fields = dict(_mapping(row.get("field_observations")))
            # The gap fact was observed by the Trade-AI scan, at the scan's time — not at the advisory's.
            fields["gap"] = {
                "observed_at": ta.get("scanned_at"),
                "source_ref": f"trade_ai_scans:{ta.get('scan_run_date') or ta.get('run_date')}",
            }
            row["field_observations"] = fields
    return row


_REGISTRY_MAX_CHAIN = 16  # scripts/lib/identity_registry.py MAX_CHAIN


def registry_entity(registry, symbol):
    """The current IdentityRegistry@v1 entity for a ticker — the semantics of identity_registry.lookup_symbol
    (by_symbol -> guid -> follow ``superseded_by`` to the active entity), on a document the caller read.

    identity_registry itself is not imported: its closure reaches canonical_store_registry and env reads that the
    n8n executor's reviewed inventory for this module's lanes does not allow
    (tests/test_n8n_executor_env_allowlist_20261009.py). Parity is pinned by a test against lookup_symbol."""
    sym = _symbol(symbol)
    if not isinstance(registry, dict) or not sym:
        return None
    entities = _mapping(registry.get("entities"))
    guid = _mapping(registry.get("by_symbol")).get(sym)
    if not guid:
        return None
    seen, cur = set(), str(guid)
    for _ in range(_REGISTRY_MAX_CHAIN):
        if cur in seen:
            break
        seen.add(cur)
        nxt = _mapping(entities.get(cur)).get("superseded_by")
        if not nxt:
            break
        cur = str(nxt)
    entity = entities.get(cur)
    return entity if isinstance(entity, dict) else None


def _registry_security_guid(registry, symbol):
    """security_guid from the identity registry. Never invented: an entity with no security_guid (ticker alias
    only, UNRESOLVED_WITH_REASON) stays unresolved."""
    return _clean(_mapping(registry_entity(registry, symbol)).get("security_guid"))


def _bind_event(registry, symbol, evidence_row):
    """SecurityEvent@v1 for an observation's catalyst — catalyst_graph.bind_catalyst's rules from the same
    primitives (event_identity.period_for / build_event): issuer-scoped, period-scoped by PUBLICATION time,
    status OCCURRED. None without a registered issuer or a publication time (a research timestamp is not a
    publication time). catalyst_graph itself is not imported: its closure reaches db_adapter."""
    if not registry:
        return None
    published = evidence_row.get("catalyst_published_at") or evidence_row.get("catalyst_at")
    if not published or not _clean(evidence_row.get("catalyst") or evidence_row.get("catalyst_headline")):
        return None
    entity = _mapping(registry_entity(registry, symbol))
    if not entity.get("issuer_guid"):
        return None
    try:
        try:
            from scripts.lib.event_identity import build_event, period_for
        except ModuleNotFoundError:
            from lib.event_identity import build_event, period_for  # type: ignore
        ctype = str(evidence_row.get("catalyst_type") or "other")
        period = period_for(ctype, published)
        if not period:
            return None
        event = build_event(
            issuer_guid=entity.get("issuer_guid"),
            security_guid=entity.get("security_guid"),
            event_type=ctype,
            period=period,
            status="OCCURRED",
            as_of=str(published),
        )
    except Exception:  # noqa: BLE001
        return None
    return event if event.get("event_guid") else None


def _source_view(observations, status, day):
    unique = {_digest(o): o for o in observations}
    rows = sorted(unique.values(), key=lambda o: (o.get("observed_at") or "", _digest(o)), reverse=True)
    dates = {o["session_date"] for o in rows if o.get("session_date")}
    # The source's CURRENT verdict: the verdicts observed at its newest timestamp. A later ALERT after
    # earlier VETOs (the fast loop journals a VETO every tick) is a change of mind, not a conflict;
    # only two different verdicts at the same newest instant are (operator 2026-10-19, BETR).
    newest = rows[0].get("observed_at") if rows else None
    latest = sorted({o["verdict"] for o in rows if o.get("observed_at") == newest})
    state = "UNKNOWN" if not dates else "CURRENT_SESSION" if day in dates else "STALE_SESSION"
    if status in UNAVAILABLE:
        state = "UNKNOWN"
    return {
        "status": status if status in UNAVAILABLE else "OBSERVED" if rows else "MISSING",
        "session_state": state,
        "verdicts": sorted({o["verdict"] for o in rows}),
        "latest_verdicts": latest,
        "latest_verdict": latest[0] if len(latest) == 1 else None,
        "observations": rows,
    }


def build_candidate_projection(
    cache,
    journal,
    *,
    now=None,
    source_status=None,
    source_details=None,
    criteria=None,
    criteria_source=None,
    identity_registry=None,
    catalyst_lookup=None,
):
    """Union both populations without changing either authoritative input.

    ``identity_registry`` (an IdentityRegistry@v1 document) and ``catalyst_lookup`` (Hermes scalp research,
    lib.data_broker.scalp_list.get_scalp_catalyst) are read-side resolvers; both default to None (pure)."""
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

    guid_cache = {}

    def resolve_guid(symbol, lineage):
        if lineage.get("security_guid"):
            return lineage["security_guid"], "SOURCE"
        if symbol not in guid_cache:
            guid_cache[symbol] = _registry_security_guid(identity_registry, symbol)
        return (guid_cache[symbol], "IDENTITY_REGISTRY") if guid_cache[symbol] else (None, None)

    def add(symbol, source, observation, evidence_row):
        lineage = observation["lineage"]
        guid, basis = resolve_guid(symbol, lineage)
        observation["security_guid"] = guid
        observation["security_guid_basis"] = basis
        observation["catalyst_event"] = _bind_event(identity_registry, symbol, evidence_row)
        # SetupReadiness@v1 (operator 2026-10-23): the one "driven by / ready / missing" verdict every surface
        # prints, from this observation's own evidence + today's Hermes research + (AT) its veto codes.
        hermes = None
        if catalyst_lookup is not None and observation.get("session_date"):
            try:
                hermes = catalyst_lookup(symbol, observation["session_date"])
            except Exception:  # noqa: BLE001 - a failed lookup is an absent record, never a crash
                hermes = None
        observation["readiness"] = setup_readiness(
            observation.get("setup_evidence"), hermes=hermes, veto_reasons=observation.get("veto_reasons")
        )
        scope = (
            guid or f"unresolved:{symbol}",
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
                # Cache tickers from /trade-ai use scan_run_*; orchestrator rows use run_date/run_label.
                _rd = row.get("run_date") or row.get("scan_run_date")
                _rl = row.get("run_label") or row.get("scan_run_label")
                run_id = f"{_rd}::{_rl}" if _rd and _rl else None
            lineage = observation_lineage(row, source_name="TRADE_AI", run_id=run_id)
            stamp = _stamp(lineage["observed_at"])
            session_date = (
                _day(run_id)
                or _day(row.get("run_date"))
                or _day(row.get("scan_run_date"))
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
                row,
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
            evidence_row = _active_trader_evidence_row(c, catalyst_lookup=catalyst_lookup)
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
                    "veto_reasons": [str(v) for v in (row.get("veto_reasons") or []) if isinstance(v, str)],
                    "source": "ACTIVE_TRADER",
                    "lineage": lineage,
                    "observation_basis": "ADVISORY_PUBLICATION" if not c.get("observed_at") else "SOURCE_OBSERVATION",
                    "event_at": lineage["event_at"],
                    "source_ref": lineage["source_ref"],
                    "security_guid": lineage["security_guid"],
                    "published_at": (_stamp(row.get("ts_epoch")).isoformat() if _stamp(row.get("ts_epoch")) else None),
                    "setup_evidence": build_setup_evidence(
                        evidence_row,
                        now=now,
                        observed_at=stamp.isoformat() if stamp else None,
                        source_name="ACTIVE_TRADER",
                        criteria=criteria,
                        criteria_source=criteria_source,
                    ),
                    "freshness": "NOT_MEASURED",
                },
                evidence_row,
            )
    candidates = []
    for (symbol, scope), observations in sorted(groups.items(), key=lambda item: str(item[0])):
        ta = _source_view(observations["TRADE_AI"], statuses["TRADE_AI"], today)
        at = _source_view(observations["ACTIVE_TRADER"], statuses["ACTIVE_TRADER"], today)
        conflicts = []
        if len(ta["verdicts"]) > 1:
            conflicts.append("TRADE_AI_VERDICT_CONFLICT")
        if len(at["latest_verdicts"]) > 1:
            conflicts.append("ACTIVE_TRADER_VERDICT_CONFLICT")
        event_id, event_at, event = scope[2], scope[3], None
        event_basis = "SOURCE" if scope[3] else None
        reasons = []
        if scope[0].startswith("unresolved:"):
            reasons.append("SECURITY_GUID_UNRESOLVED")
        if not scope[1]:
            reasons.append("SESSION_UNRESOLVED")
        if not scope[3]:
            # Read-side binding: each source's NEWEST observation's catalyst -> SecurityEvent@v1. One distinct
            # event across sources is the candidate's event; two different ones are a mismatch, never a pick.
            newest = [
                view["observations"][0].get("catalyst_event")
                for view in (ta, at)
                if view["observations"] and view["observations"][0].get("catalyst_event")
            ]
            distinct = {e["event_guid"]: e for e in newest}
            if len(distinct) == 1:
                event = next(iter(distinct.values()))
                event_id, event_at = event["event_guid"], _clean(event.get("as_of"))
                event_basis = "READ_SIDE_CATALYST_BINDING"
            if len(distinct) > 1:
                reasons.append("EVENT_MISMATCH")
            elif not event_at:
                reasons.append("EVENT_UNRESOLVED")
        comparable = bool(scope[0] and not scope[0].startswith("unresolved:") and scope[1] and event_at)
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
                "event_id": event_id,
                "event_at": event_at,
                "event_basis": event_basis,
                "event": event,
                "reconciliation_status": "COMPARABLE_EVENT" if comparable else "IDENTITY_OR_EVENT_UNRESOLVED",
                "reconciliation_reasons": [] if comparable else reasons,
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



def _row_session(row):
    """A journal row's session day: candidate.session_date, else its publication clock in ET."""
    if not isinstance(row, dict):
        return None
    candidate = row.get("candidate")
    day = _day(candidate.get("session_date")) if isinstance(candidate, dict) else None
    if day:
        return day
    stamp = _stamp(row.get("ts_epoch"))
    return stamp.astimezone(ET).date().isoformat() if stamp else None


def _line_session(line):
    try:
        return _row_session(json.loads(line))
    except ValueError:
        return None


def read_journal_session(path: Path, *, max_bytes=32_000_000, block_bytes=1_048_576):
    """Every row of the journal's LATEST session, read backwards from the end in blocks (Gate 1, 2026-10-22).

    The journal is append-only in time order. The old reader kept a fixed 4 MB byte tail of a 19 MB file, so a
    busy session's morning rows were dropped and the source always said PARTIAL. This reads back until it
    sees a complete row from an EARLIER session (the boundary), never past ``max_bytes``. ``tail_truncated``
    stays honest: True only when the bound was hit before the boundary and earlier bytes remain.

    Returns (rows, malformed_lines, details)."""
    size = path.stat().st_size
    target, boundary, pos, buf = None, False, size, b""
    with path.open("rb") as fh:
        while pos > 0 and size - pos < max_bytes:
            step = min(block_bytes, pos, max_bytes - (size - pos))
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
            lines = buf.split(b"\n")
            complete = lines if pos == 0 else lines[1:]
            if target is None:
                target = next((d for d in map(_line_session, reversed(complete)) if d), None)
            if target is not None:
                oldest = next((d for d in map(_line_session, complete) if d), None)
                if oldest is not None and oldest < target:
                    boundary = True
                    break
    lines = buf.split(b"\n")
    if pos > 0:
        lines = lines[1:]  # the first piece may be the tail of a row that starts before what was read
    rows, bad, earlier = [], 0, 0
    for raw in lines:
        if not raw.strip():
            continue
        try:
            row = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            bad += 1
            continue
        if not isinstance(row, dict):
            bad += 1
            continue
        day = _row_session(row)
        if target is not None and day is not None and day < target:
            earlier += 1
            continue
        rows.append(row)
    truncated = bool(pos > 0 and not boundary)
    return (
        rows,
        bad,
        {
            "tail_truncated": truncated,
            "malformed_lines": bad,
            "read_scope": "LATEST_SESSION",
            "session_window": target,
            "session_boundary_found": boundary or pos == 0,
            "bytes_read": size - pos,
            "max_bytes": max_bytes,
            "earlier_session_rows_excluded": earlier,
        },
    )


_DEFAULT = object()

HERMES_CATALYST_REL = Path("data") / "hermes" / "momentum_catalysts"  # lib/hermes_catalyst_store.REL
IDENTITY_REGISTRY_REL = Path("data") / "runtime" / "identity_registry.json"  # identity_registry.REGISTRY_RELATIVE


def _hermes_catalyst_lookup(state_root: Path):
    """Hermes scalp-catalyst research for the AT catalyst fallback: the canonical persistent-state day file
    (``<state>/data/hermes/momentum_catalysts/<day>_catalysts.jsonl``; lib/hermes_catalyst_store.py) read with the
    record selection lib.data_broker.scalp_list.get_scalp_catalyst uses (lib/hermes_scalp_catalyst_record.py).
    Same status vocabulary. Zero provider calls, never writes; one read per day file per projection."""
    try:
        try:
            from scripts.lib.hermes_scalp_catalyst_record import select_scalp_catalyst
        except ModuleNotFoundError:
            from lib.hermes_scalp_catalyst_record import select_scalp_catalyst  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    files = {}

    def lookup(symbol, day):
        if day not in files:
            try:
                path = state_root / HERMES_CATALYST_REL / f"{day}_catalysts.jsonl"
                files[day] = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                files[day] = None
        if files[day] is None:
            return {"symbol": symbol, "day": day, "status": "STORE_MISSING", "provider_calls": 0}
        found = select_scalp_catalyst(symbol, files[day])
        return {"symbol": symbol, "day": day, "provider_calls": 0, **(found or {"status": "NOT_RESEARCHED"})}

    return lookup


def _state_root_of(journal_path: Path, override=None):
    """``<state>`` for ``<state>/data/active_trader/momentum_alerts.jsonl``; None for any other layout."""
    if override is not None:
        return Path(override)
    parents = journal_path.parents
    if len(parents) > 2 and parents[0].name == "active_trader" and parents[1].name == "data":
        return parents[2]
    return None


_REGISTRY_CACHE = {}


def _identity_registry_for(root, *, max_bytes=64_000_000):
    """IdentityRegistry@v1 at the state root (``<state>/data/runtime/identity_registry.json``), read-only, parsed
    once per (path, mtime, size) like identity_registry.load_cached. Missing, oversized or unreadable -> None, and
    every symbol stays unresolved (never guessed)."""
    if root is None:
        return None
    path = Path(root) / IDENTITY_REGISTRY_REL
    try:
        st = path.stat()
        if st.st_size > max_bytes:
            return None
        stamp = (st.st_mtime_ns, st.st_size)
        hit = _REGISTRY_CACHE.get(str(path))
        if hit and hit[0] == stamp:
            return hit[1]
        doc = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("by_symbol"), dict) or not doc["by_symbol"]:
        return None
    _REGISTRY_CACHE.clear()
    _REGISTRY_CACHE[str(path)] = (stamp, doc)
    return doc


def read_candidate_snapshot(
    cache_path: Path,
    journal_path: Path,
    *,
    now=None,
    max_cache_bytes=16_000_000,
    max_journal_bytes=32_000_000,
    state_root=None,
    catalyst_lookup=_DEFAULT,
):
    """Bounded read only. Missing/unreadable sources are explicit, never empty success.

    The identity registry and Hermes research are read from ``state_root`` (default: the journal's own state
    root), so a fixture journal never resolves against live state."""
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
        journal, bad, read_details = read_journal_session(journal_path, max_bytes=max_journal_bytes)
        statuses["ACTIVE_TRADER"] = "PARTIAL" if bad or read_details["tail_truncated"] else "AVAILABLE"
        details["ACTIVE_TRADER"] = read_details
    except FileNotFoundError:
        statuses["ACTIVE_TRADER"] = "MISSING"
    except OSError:
        statuses["ACTIVE_TRADER"] = "MALFORMED"
    from .scalp_go_criteria import load_criteria

    root = _state_root_of(journal_path, state_root)
    if catalyst_lookup is _DEFAULT:
        catalyst_lookup = _hermes_catalyst_lookup(root) if root is not None else None
    return build_candidate_projection(
        cache,
        journal,
        now=now,
        source_status=statuses,
        source_details=details,
        criteria=load_criteria(),
        criteria_source="scripts/lib/scalp_go_criteria.py:load_criteria (config or documented fallback)",
        identity_registry=_identity_registry_for(root),
        catalyst_lookup=catalyst_lookup,
    )
