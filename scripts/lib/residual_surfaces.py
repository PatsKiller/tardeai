#!/usr/bin/env python3
"""residual_surfaces.py — the five Command Center surfaces that still lied.

Each of these had the same shape of defect: a number that looked settled while
the thing behind it was unresolved, missing, or two different things wearing one
label. Each projection below answers with a named state instead.

  watch_projection        one population for catalog/matched/held/starred/filtered,
                          with page and total, and a loading state that terminates
  closed_loop_separation  CIO decision lineage and Hermes outcome feedback are two
                          circulations; one going stale must not age the other
  research_provenance     stale is not missing, and a producer being fresh is not
                          the artifact being fresh is not a consumer having adopted it
  writer_status           declared / scheduled / enabled / attempted / succeeded /
                          non-empty / durably written / adopted are eight questions
  reentry_projection      one canonical status with a reason, because today a row
                          carries gates and no status at all

AUTHORITY: READ_ONLY_ADVISORY. Pure functions over payloads already fetched. No
network, broker, order, scheduler or production mutation. News, social, search,
RAG and LLM prose are evidence here, never canonical financial truth.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

AUTHORITY = "READ_ONLY_ADVISORY"
CALCULATION_VERSION = "1.0.0"

# ── shared surface states. A surface is always in exactly one. ───────────────
POPULATED = "POPULATED"
LEGITIMATE_EMPTY = "LEGITIMATE_EMPTY"
STALE = "STALE"
PARTIAL = "PARTIAL"
DEGRADED = "DEGRADED"
DISCONNECTED = "DISCONNECTED"
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
MALFORMED = "MALFORMED"
ERROR = "ERROR"
LOADING = "LOADING"

TERMINAL_STATES = (
    POPULATED,
    LEGITIMATE_EMPTY,
    STALE,
    PARTIAL,
    DEGRADED,
    DISCONNECTED,
    UNAUTHORIZED,
    FORBIDDEN,
    MALFORMED,
    ERROR,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _parse(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    text = ts.strip()
    tail = text.rsplit(" ", 1)[-1].upper() if " " in text else ""
    tz = {"ET": -4, "EDT": -4, "EST": -5, "UTC": 0, "Z": 0}.get(tail)
    if tz is not None:
        text = text.rsplit(" ", 1)[0].strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        from datetime import timedelta

        dt = dt.replace(tzinfo=timezone(timedelta(hours=tz or 0)))
    return dt


def _age_h(ts: Any, now: datetime | None = None) -> float | None:
    dt = _parse(ts)
    if dt is None:
        return None
    return round(((now or _now()) - dt.astimezone(timezone.utc)).total_seconds() / 3600.0, 3)


def classify_transport(status: int | None, error: str | None) -> str | None:
    """A transport answer, when there is one. None means the payload arrived."""
    if status == 401:
        return UNAUTHORIZED
    if status == 403:
        return FORBIDDEN
    if status is not None and status >= 500:
        return ERROR
    if error:
        return DISCONNECTED
    return None


def _envelope(state: str, reason: str, **extra: Any) -> dict[str, Any]:
    out = {
        "state": state,
        "state_reason": reason,
        "terminal": state in TERMINAL_STATES,
        "authority": AUTHORITY,
        "calculation_version": CALCULATION_VERSION,
        "as_of": _iso(_now()),
    }
    out.update(extra)
    return out


def escalate_envelope(row_states: list[str], *, degraded: set[str], stale: set[str]) -> tuple[str, str]:
    """Derive the summary state from the rows underneath it.

    A summary that is hard-coded POPULATED whenever it has any rows is the same defect
    this module was written to remove: the header stays green while everything below it
    is stale, unadopted or broken, and a consumer that reads only `state` is misled by
    a surface whose whole job is to stop that happening.

    Worst-wins, and the reason names the counts so the escalation is checkable.
    """
    if not row_states:
        return LEGITIMATE_EMPTY, "there are no rows, which is a real answer"
    bad = [s for s in row_states if s in degraded]
    old = [s for s in row_states if s in stale]
    total = len(row_states)
    if bad and len(bad) == total:
        return DEGRADED, f"all {total} row(s) are in a failed state: {sorted(set(bad))}"
    if old and len(old) == total:
        return STALE, f"all {total} row(s) are stale: {sorted(set(old))}"
    if bad or old:
        return PARTIAL, (
            f"{len(bad) + len(old)} of {total} row(s) are degraded or stale "
            f"({sorted(set(bad + old))}); the rest resolved"
        )
    return POPULATED, f"all {total} row(s) resolved"


# ── 1. Watch ─────────────────────────────────────────────────────────────────

WATCH_SCHEMA = "WatchProjection@v1"

#: Every count below is drawn from THIS list, so the summary can never describe a
#: population the table is not showing.
WATCH_POPULATIONS = (
    "catalog",
    "matched",
    "held",
    "starred",
    "filtered",
    "page_shown",
    "total",
)


def watch_projection(
    payload: dict[str, Any] | None,
    *,
    http_status: int | None = None,
    error: str | None = None,
    filters: dict[str, Any] | None = None,
    page: int = 1,
    page_size: int | None = None,
    stale_after_hours: float = 6.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One projection for every Watch count, from one list.

    The defect: summary counts stayed authoritative while the list projection was
    still resolving, and an initial filter could silently empty the catalogue
    while the header still claimed hundreds of names.
    """
    transport = classify_transport(http_status, error)
    if transport:
        return {
            **_envelope(transport, f"transport answered {http_status or error!r}"),
            "schema": WATCH_SCHEMA,
            "counts": None,
            "counts_authoritative": False,
            "note": "counts are withheld: the list they would describe was never received",
        }

    if payload is None:
        return {
            **_envelope(LOADING, "the list projection has not resolved yet"),
            "schema": WATCH_SCHEMA,
            "counts": None,
            "counts_authoritative": False,
            "note": "summary counts must not render while the list is unresolved",
        }

    items = payload.get("items")
    if not isinstance(items, list):
        return {
            **_envelope(MALFORMED, f"items is {type(items).__name__}, expected a list"),
            "schema": WATCH_SCHEMA,
            "counts": None,
            "counts_authoritative": False,
        }

    rows = [r for r in items if isinstance(r, dict)]
    malformed_rows = len(items) - len(rows)

    def _truthy(r: dict[str, Any], *names: str) -> bool:
        return any(bool(r.get(n)) for n in names)

    catalog = len(rows)
    held = sum(1 for r in rows if _truthy(r, "held", "is_held", "in_portfolio"))
    starred = sum(1 for r in rows if _truthy(r, "starred", "is_starred", "star"))
    matched = sum(1 for r in rows if _truthy(r, "in_directive_watch", "matched"))

    active = {k: v for k, v in (filters or {}).items() if v not in (None, "", "all")}
    filtered = rows
    for key, want in active.items():
        filtered = [r for r in filtered if str(r.get(key)) == str(want)]

    declared_total = payload.get("count")
    total = declared_total if isinstance(declared_total, int) else catalog
    size = page_size or catalog or 1
    observed = payload.get("as_of") or payload.get("generated_at") or payload.get("updated_at")
    age = _age_h(observed, now)

    if malformed_rows:
        state, reason = PARTIAL, f"{malformed_rows} row(s) were not objects and were excluded"
    elif catalog == 0:
        state, reason = LEGITIMATE_EMPTY, "the producer returned an empty catalogue, which is a real answer"
    elif active and not filtered:
        state, reason = (
            DEGRADED,
            f"the active filter {active} eliminates every one of the {catalog} catalogue rows; "
            "the catalogue is not empty, the filter is",
        )
    elif age is not None and age >= stale_after_hours:
        state, reason = STALE, f"the catalogue was observed {age:.1f}h ago"
    elif isinstance(declared_total, int) and declared_total != catalog and page == 1 and page_size is None:
        state, reason = PARTIAL, f"the producer declares {declared_total} rows but returned {catalog}"
    else:
        state, reason = POPULATED, "the catalogue resolved and every count is drawn from it"

    return {
        **_envelope(state, reason),
        "schema": WATCH_SCHEMA,
        "counts": {
            "catalog": catalog,
            "matched": matched,
            "held": held,
            "starred": starred,
            "filtered": len(filtered),
            "page_shown": min(len(filtered), size),
            "total": total,
        },
        "counts_authoritative": state in (POPULATED, STALE, LEGITIMATE_EMPTY),
        "counts_population_rule": (
            "every count is computed from the rows this response returned; none is read from a second store"
        ),
        "active_filters": active,
        "filters_eliminate_catalog": bool(active) and not filtered and catalog > 0,
        "page": page,
        "page_size": size,
        "malformed_rows": malformed_rows,
        "source": payload.get("source") or "/api/v2/watchlist/items",
        "quality": "OK" if state == POPULATED else state,
        "observation": {"observed_at": observed, "age_hours": age, "stale_after_hours": stale_after_hours},
        "provider_calls_on_load": 0,
        "provider_call_rule": "this projection reads an already-fetched payload; it calls no provider",
    }


# ── 2. Closed Loop ───────────────────────────────────────────────────────────

CLOSED_LOOP_SCHEMA = "ClosedLoopSeparation@v1"

LANES = (
    ("cio_decision_lineage", "CIO decision lineage", "decisions the CIO recorded, and what became of them"),
    ("hermes_outcome_feedback", "Hermes outcome feedback", "evaluations Hermes produced about past outcomes"),
    ("research_to_thesis", "research-to-thesis circulation", "research that reached a thesis"),
    ("outcome_to_lesson", "outcome-to-lesson circulation", "outcomes that became a recorded lesson"),
)


def _lane(
    key: str, label: str, description: str, spec: dict[str, Any] | None, stale_after_hours: float, now: datetime | None
) -> dict[str, Any]:
    spec = spec or {}
    artifact_at = spec.get("latest_artifact_at")
    age = _age_h(artifact_at, now)
    count = spec.get("count")
    if spec.get("error"):
        state, reason = ERROR, str(spec["error"])[:160]
    elif artifact_at is None and not count:
        state, reason = LEGITIMATE_EMPTY, "this circulation has produced nothing yet"
    elif age is None:
        state, reason = MALFORMED, f"latest artifact timestamp {artifact_at!r} does not parse"
    elif age >= stale_after_hours:
        state, reason = STALE, f"the newest artifact in this lane is {age / 24:.1f} days old"
    else:
        state, reason = POPULATED, "this lane has a recent artifact"
    return {
        "lane": key,
        "label": label,
        "description": description,
        "state": state,
        "state_reason": reason,
        "producer": spec.get("producer"),
        "latest_successful_artifact": spec.get("latest_artifact_id"),
        "latest_artifact_at": artifact_at,
        "artifact_age_hours": age,
        "artifact_count": count,
        "consumer": spec.get("consumer"),
        "adoption_state": spec.get("adoption_state", "UNKNOWN"),
        "authority_ceiling": spec.get("authority", "READ_ONLY_ADVISORY"),
    }


def closed_loop_separation(
    lanes: dict[str, dict[str, Any]] | None = None,
    *,
    http_status: int | None = None,
    error: str | None = None,
    stale_after_hours: float = 72.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Four circulations, each aging on its own clock.

    The defect: a stale Hermes evaluation made CIO lineage read as stale, and the
    reverse. They are different loops with different producers; one being quiet
    says nothing about the other.
    """
    transport = classify_transport(http_status, error)
    if transport:
        return {
            **_envelope(transport, f"transport answered {http_status or error!r}"),
            "schema": CLOSED_LOOP_SCHEMA,
            "lanes": None,
        }
    src = lanes or {}
    rows = [_lane(k, label, desc, src.get(k), stale_after_hours, now) for k, label, desc in LANES]
    return {
        **_envelope(
            POPULATED if any(r["state"] == POPULATED for r in rows) else PARTIAL,
            "each lane carries its own state; no lane's age is inherited from another",
        ),
        "schema": CLOSED_LOOP_SCHEMA,
        "lanes": rows,
        "lane_states": {r["lane"]: r["state"] for r in rows},
        "independence_rule": (
            "a lane's state is computed only from its own producer and artifact; "
            "staleness never propagates between lanes"
        ),
    }


# ── 3. Research provenance ───────────────────────────────────────────────────

RESEARCH_SCHEMA = "ResearchProvenance@v1"


def research_provenance(
    freshness: dict[str, Any] | None,
    *,
    http_status: int | None = None,
    error: str | None = None,
    expected_categories: Iterable[str] = (),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Stale topics and missing coverage are different problems.

    A category with rows that have aged is stale. A category with no rows at all
    is uncovered. Rendering both as "0 fresh" hides which one an operator has.
    """
    transport = classify_transport(http_status, error)
    if transport:
        return {
            **_envelope(transport, f"transport answered {http_status or error!r}"),
            "schema": RESEARCH_SCHEMA,
            "categories": None,
        }
    if freshness is None:
        return {**_envelope(LOADING, "the freshness projection has not resolved"), "schema": RESEARCH_SCHEMA}
    by_cat = freshness.get("by_category")
    if not isinstance(by_cat, dict):
        return {**_envelope(MALFORMED, f"by_category is {type(by_cat).__name__}"), "schema": RESEARCH_SCHEMA}

    stale_topics, uncovered, rows = [], [], []
    for name, c in sorted(by_cat.items()):
        c = c if isinstance(c, dict) else {}
        count = int(c.get("count") or 0)
        stale = int(c.get("stale") or 0)
        fresh = int(c.get("fresh") or 0)
        needs = int(c.get("needs_refresh") or 0)
        if count == 0:
            uncovered.append(name)
            state = "MISSING_COVERAGE"
        elif stale > 0:
            stale_topics.append(name)
            state = "STALE_TOPICS"
        elif needs > 0:
            state = "NEEDS_REFRESH"
        else:
            state = "CURRENT"
        rows.append(
            {
                "category": name,
                "state": state,
                "row_count": count,
                "stale_rows": stale,
                "fresh_rows": fresh,
                "needs_refresh": needs,
                "avg_age_hours": c.get("avg_age_h"),
                "freshest_hours": c.get("freshest_h"),
                "slo_hours": c.get("slo_hours"),
                "slo_ok": c.get("slo_ok"),
            }
        )

    for name in expected_categories:
        if name not in by_cat:
            uncovered.append(name)
            rows.append(
                {
                    "category": name,
                    "state": "MISSING_COVERAGE",
                    "row_count": 0,
                    "stale_rows": 0,
                    "fresh_rows": 0,
                    "needs_refresh": 0,
                }
            )

    observed = freshness.get("as_of")
    return {
        **_envelope(
            *escalate_envelope(
                [r["state"] for r in rows],
                degraded={"MISSING_COVERAGE"},
                stale={"STALE_TOPICS"},
            )
        ),
        "schema": RESEARCH_SCHEMA,
        "categories": rows,
        "stale_topics": sorted(set(stale_topics)),
        "missing_coverage": sorted(set(uncovered)),
        "freshness_layers": {
            "source_acquisition": {
                "observed_at": observed,
                "age_hours": _age_h(observed, now),
                "meaning": "when the freshness scan itself ran",
            },
            "research_row": {"meaning": "per-category row ages, in `categories[].avg_age_hours`"},
            "durable_artifact": {
                "observed_at": freshness.get("artifact_as_of"),
                "age_hours": _age_h(freshness.get("artifact_as_of"), now),
                "meaning": "when a durable research artifact was last written",
            },
            "consumer_adoption": {
                "observed_at": freshness.get("adopted_as_of"),
                "age_hours": _age_h(freshness.get("adopted_as_of"), now),
                "meaning": "when a consumer last adopted a research output",
            },
        },
        "provenance_complete": all(r.get("row_count", 0) == 0 or r.get("avg_age_hours") is not None for r in rows),
        "decision_eligible": not uncovered and not stale_topics,
        "decision_eligibility_rule": (
            "research is eligible to inform a decision only when no expected category is "
            "uncovered and none carries stale rows"
        ),
        "evidence_class": "EVIDENCE_NOT_CANONICAL_FINANCIAL_TRUTH",
        "evidence_note": (
            "news, social, search, RAG and LLM prose are evidence; they never become a "
            "canonical financial fact by being cited here"
        ),
    }


# ── 4. Writer status ─────────────────────────────────────────────────────────

WRITER_SCHEMA = "WriterStatus@v1"

WORKING_END_TO_END = "WORKING_END_TO_END"
PRODUCING_NOT_ADOPTED = "PRODUCING_NOT_ADOPTED"
MANUAL = "MANUAL"
PAUSED = "PAUSED"
ABSENT = "ABSENT"
STALE_WRITER = "STALE"
BROKEN = "BROKEN"
UNKNOWN_WRITER = "UNKNOWN"

WRITER_STATES = (
    WORKING_END_TO_END,
    PRODUCING_NOT_ADOPTED,
    MANUAL,
    PAUSED,
    ABSENT,
    STALE_WRITER,
    BROKEN,
    UNKNOWN_WRITER,
)


def writer_status(
    writers: dict[str, dict[str, Any]] | None,
    *,
    http_status: int | None = None,
    error: str | None = None,
    stale_after_hours: float = 48.0,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Eight separate questions about a writer, answered separately.

    "It produced something" is not "it wrote something durable" is not "anyone
    adopted it". A surface that implies automatic thesis minting where the writer
    is manual is the specific lie this replaces.
    """
    transport = classify_transport(http_status, error)
    if transport:
        return {
            **_envelope(transport, f"transport answered {http_status or error!r}"),
            "schema": WRITER_SCHEMA,
            "writers": None,
        }
    src = writers or {}
    rows = []
    for name, w in sorted(src.items()):
        w = w if isinstance(w, dict) else {}
        declared = bool(w.get("declared", True))
        configured = bool(w.get("configured"))
        scheduled = bool(w.get("scheduled"))
        enabled = bool(w.get("enabled"))
        manual = bool(w.get("manual"))
        last_attempt = w.get("last_attempt")
        last_success = w.get("last_success")
        last_nonempty = w.get("last_nonempty_output")
        last_durable = w.get("last_durable_write")
        last_adopted = w.get("last_adopted_output")
        failure = w.get("failure_reason")
        age = _age_h(last_durable or last_success or last_attempt, now)

        if not declared:
            state, reason = ABSENT, "no such writer is declared"
        elif manual:
            state, reason = MANUAL, "this writer only runs when an operator runs it"
        elif declared and not configured:
            state, reason = ABSENT, "declared but never configured"
        elif scheduled and not enabled:
            state, reason = PAUSED, "scheduled but disabled"
        elif failure:
            state, reason = BROKEN, f"last run failed: {str(failure)[:120]}"
        elif last_attempt and not last_success:
            state, reason = BROKEN, "it has attempted and never succeeded"
        elif last_durable and last_adopted:
            state = WORKING_END_TO_END if (age is None or age < stale_after_hours) else STALE_WRITER
            reason = (
                "produced, written durably and adopted"
                if state == WORKING_END_TO_END
                else f"last durable write was {age:.1f}h ago"
            )
        elif last_nonempty or last_durable:
            state, reason = (
                PRODUCING_NOT_ADOPTED,
                ("it produces output that reaches durable storage, but no consumer has adopted it"),
            )
        elif not last_attempt:
            state, reason = UNKNOWN_WRITER, "nothing recorded about this writer at all"
        else:
            state, reason = UNKNOWN_WRITER, "the recorded signals do not decide a state"

        rows.append(
            {
                "writer": name,
                "kind": w.get("kind"),
                "state": state,
                "state_reason": reason,
                "declared": declared,
                "configured": configured,
                "scheduled": scheduled,
                "enabled": enabled,
                "manual": manual,
                "last_attempt": last_attempt,
                "last_success": last_success,
                "last_nonempty_output": last_nonempty,
                "last_durable_write": last_durable,
                "last_adopted_output": last_adopted,
                "freshness_hours": age,
                "failure_reason": failure,
                "authority": w.get("authority", "READ_ONLY_ADVISORY"),
                "implies_automatic_minting": False,
            }
        )

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return {
        **_envelope(
            *escalate_envelope(
                [r["state"] for r in rows],
                degraded={BROKEN, ABSENT, UNKNOWN_WRITER},
                stale={STALE_WRITER, PRODUCING_NOT_ADOPTED},
            )
        ),
        "schema": WRITER_SCHEMA,
        "writers": rows,
        "state_counts": dict(sorted(counts.items())),
        "manual_writers": [r["writer"] for r in rows if r["state"] == MANUAL],
        "rule": ("a MANUAL writer must never be rendered as if a schedule mints its output; producing is not adopting"),
    }


# ── 5. Re-entry ──────────────────────────────────────────────────────────────

REENTRY_SCHEMA = "ReentryStatus@v1"

READY = "READY"
BLOCKED_GATE = "BLOCKED_GATE"
WASH_BLOCKED = "WASH_BLOCKED"
HELD = "HELD"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
STALE_INPUT = "STALE_INPUT"
UNKNOWN_STATUS = "UNKNOWN"

REENTRY_STATES = (READY, BLOCKED_GATE, WASH_BLOCKED, HELD, NOT_ELIGIBLE, STALE_INPUT, UNKNOWN_STATUS)

OBSERVED = "OBSERVED"
INFERRED = "INFERRED"


def reentry_row_status(row: dict[str, Any], *, stale_hours: float = 6.0) -> dict[str, Any]:
    """One canonical status for one row, with the reason and the gates behind it.

    The served desk carries `gates`, `held` and `wash_blocked` but no status at
    all, so every consumer re-derives its own — which is how two surfaces disagree
    about the same symbol.
    """
    gates = row.get("gates")
    gates = gates if isinstance(gates, list) else []
    failed = [g.get("id") or g.get("label") for g in gates if isinstance(g, dict) and g.get("pass") is False]
    passed = [g.get("id") or g.get("label") for g in gates if isinstance(g, dict) and g.get("pass") is True]
    age = row.get("price_age_h")

    if row.get("held"):
        status, reason = HELD, "already held; a re-entry does not apply"
    elif row.get("wash_blocked"):
        status, reason = WASH_BLOCKED, f"wash-sale window until {row.get('wash_until')}"
    elif not gates:
        status, reason = UNKNOWN_STATUS, "no gates were evaluated for this row"
    elif isinstance(age, (int, float)) and age >= stale_hours:
        status, reason = STALE_INPUT, f"the quote behind these gates is {age:.1f}h old"
    elif failed:
        status, reason = BLOCKED_GATE, f"{len(failed)} gate(s) did not pass: {', '.join(map(str, failed[:4]))}"
    elif passed:
        status, reason = READY, f"all {len(passed)} gates passed"
    else:
        status, reason = NOT_ELIGIBLE, "no gate passed and none failed"

    return {
        "symbol": row.get("symbol"),
        "status": status,
        "state_reason": reason,
        "contributing_gates": [
            {"id": g.get("id"), "label": g.get("label"), "pass": g.get("pass"), "value": g.get("value")}
            for g in gates
            if isinstance(g, dict)
        ],
        "gates_failed": failed,
        "gates_passed": passed,
        "account_scope": row.get("account") or "ALL_ACCOUNTS",
        "source_observations": {
            "price_as_of": row.get("price_as_of"),
            "price_source": row.get("price_source"),
            "price_age_hours": age,
            "plan_as_of": row.get("plan_as_of"),
            "indicator_source": row.get("indicator_source"),
        },
        "observation_class": OBSERVED,
        "held": bool(row.get("held")),
    }


def reentry_projection(
    payload: dict[str, Any] | None,
    *,
    http_status: int | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    transport = classify_transport(http_status, error)
    # rows is None, never [], whenever the desk did not actually read anything. An
    # empty list here is a measurement -- "there are no re-entry candidates" -- and a
    # read that failed has measured nothing. Returning [] makes an outage and a quiet
    # market render identically, which is the exact defect this surface exists to end.
    if transport:
        return {
            **_envelope(transport, f"transport answered {http_status or error!r}"),
            "schema": REENTRY_SCHEMA,
            "rows": None,
        }
    if payload is None:
        return {**_envelope(LOADING, "the desk has not resolved"), "schema": REENTRY_SCHEMA, "rows": None}
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return {**_envelope(MALFORMED, f"rows is {type(rows).__name__}"), "schema": REENTRY_SCHEMA, "rows": None}

    criteria = payload.get("criteria") or {}
    stale_hours = float(criteria.get("stale_hours") or 6.0)
    out = [reentry_row_status(r, stale_hours=stale_hours) for r in rows if isinstance(r, dict)]
    counts: dict[str, int] = {}
    for r in out:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    computed = payload.get("computed_at")
    return {
        **_envelope(
            POPULATED if out else LEGITIMATE_EMPTY, "every row carries one canonical status and the gates behind it"
        ),
        "schema": REENTRY_SCHEMA,
        "contract_version": payload.get("version"),
        "calculated_at": computed,
        "calculated_age_hours": _age_h(computed, now),
        "criteria": criteria,
        "row_count": len(out),
        "status_counts": dict(sorted(counts.items())),
        "rows": out,
        "observation_class": OBSERVED,
        "inference_rule": (
            "rows without a directly recorded status are projected as INFERRED with this "
            "rule and version; an inferred status is never rewritten as observed history"
        ),
    }


def reentry_infer_historical(record: dict[str, Any], *, rule_version: str = "1.0.0") -> dict[str, Any]:
    """Project a historical record that predates the status contract.

    Marked INFERRED, always. A history that never recorded a status does not
    acquire one retroactively just because we can guess well.
    """
    status = UNKNOWN_STATUS
    reason = "no status was recorded and no gate evidence survives"
    if record.get("held"):
        status, reason = HELD, "the record shows the position was held"
    elif record.get("action") or record.get("executed"):
        status, reason = READY, "the record shows an action was taken, implying the gates had passed"
    elif record.get("blocked_reason"):
        status, reason = BLOCKED_GATE, f"the record names a block: {record['blocked_reason']}"
    return {
        "symbol": record.get("symbol"),
        "status": status,
        "state_reason": reason,
        "observation_class": INFERRED,
        "inference_rule": "derived from held / action / blocked_reason on a pre-contract record",
        "inference_rule_version": rule_version,
        "never_rewritten_as_observed": True,
        "source_record_date": record.get("date") or record.get("as_of"),
    }


# ── 6. Financial record conflicts ────────────────────────────────────────────

CONFLICT_SCHEMA = "FinancialConflictState@v1"


def financial_conflict_state(
    sidecars: dict[str, Any] | None,
    *,
    http_status: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Which financial records are unverified, and what that is allowed to block.

    A record no authority could settle must not be shown as a value. It must also not
    take the whole application down with it: one disputed historical tax lot is not a
    reason to stop rendering Watch, Closed Loop, or the other records in its own store.

    So this returns per-record scope. `blocks` names only the calculations that actually
    consume the disputed record; everything absent from that list is explicitly declared
    unaffected, which is what lets the rest of the site stay live and honest at once.
    """
    transport = classify_transport(http_status, error)
    if transport:
        return {
            **_envelope(transport, f"transport answered {http_status or error!r}"),
            "schema": CONFLICT_SCHEMA,
            "conflicts": None,
        }

    if sidecars is None:
        return {
            **_envelope(ERROR, "conflict state was never read; absence of a sidecar is not proof of no conflict"),
            "schema": CONFLICT_SCHEMA,
            "conflicts": None,
        }

    conflicts: list[dict[str, Any]] = []
    malformed: list[str] = []
    for store, doc in sorted(sidecars.items()):
        if not isinstance(doc, dict) or "records" not in doc:
            malformed.append(store)
            continue
        for rec in doc.get("records") or []:
            key = rec.get("record_key")
            conflicts.append(
                {
                    "store": store,
                    "record_key": key,
                    "render_as": rec.get("render_as", "UNVERIFIED"),
                    "status": rec.get("status", "UNRESOLVED_OPERATOR_REVIEW"),
                    "defects": rec.get("defects") or [],
                    # A record can be settled for one property and unusable for another:
                    # the broker proves a share count, and has no opinion on the basis.
                    "quantity_disposition": rec.get("quantity_disposition"),
                    "basis_disposition": rec.get("basis_disposition"),
                    "reason": rec.get("reason"),
                    "both_originals_preserved": bool(rec.get("producer_sha256") and rec.get("served_sha256")),
                    # Scope is deliberately narrow and explicit.
                    "blocks": _conflict_blast_radius(store, key),
                    "does_not_block": (
                        "every other record in this store, and every surface that does not read this record"
                    ),
                }
            )

    if malformed:
        return {
            **_envelope(DEGRADED, f"{len(malformed)} conflict sidecar(s) could not be parsed: {malformed}"),
            "schema": CONFLICT_SCHEMA,
            "conflicts": conflicts,
            "malformed_sidecars": malformed,
        }
    if not conflicts:
        return {
            **_envelope(LEGITIMATE_EMPTY, "no unresolved financial record conflicts"),
            "schema": CONFLICT_SCHEMA,
            "conflicts": [],
            "unresolved_record_count": 0,
        }
    return {
        **_envelope(
            DEGRADED,
            f"{len(conflicts)} financial record(s) are unresolved and render UNVERIFIED; "
            "the calculations that read them fail closed and nothing else is affected",
        ),
        "schema": CONFLICT_SCHEMA,
        "conflicts": conflicts,
        "unresolved_record_count": len(conflicts),
        "no_disputed_value_presented_as_truth": True,
    }


#: What a disputed record in each store is actually allowed to stop.
_BLAST_RADIUS = {
    "tax_lots.json": ["cost_basis", "realized_gain_loss", "tax_lot_selection", "holding_period"],
    "stops.json": ["protection_coverage_for_this_symbol"],
    "trade_journal.json": ["holding_period_for_this_lot"],
    "performance_history.json": ["performance_series"],
    "performance_attribution.json": ["attribution_metrics"],
}


def _conflict_blast_radius(store: str, record_key: str | None) -> list[str]:
    scoped = _BLAST_RADIUS.get(store, ["unknown_calculation"])
    return [f"{c}[{record_key}]" for c in scoped]
