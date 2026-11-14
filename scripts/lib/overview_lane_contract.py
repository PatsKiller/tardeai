"""INC-OVW / OP-042 (2026-11-14): the 24/7 ``overview-projection`` lane contract, DERIVED from the registry.

Why this module exists. On Saturday 2026-11-14 the Command Center header answered UNKNOWN because the
producer was scheduled ``*/1 4-20 * * 1-5`` (weekday, 04:00-20:00 ET) while the reader's last-good window
was ``LAST_GOOD_MAX_S = 1800``. Two numbers that MUST agree were maintained in two places, and they drifted:
the last body was 17.7 hours old when the page asked for it. A comment cannot keep them together; a
function can. So the contract is a pure function of the files that actually drive the dispatcher:

    last_good_max_s  >  max_real_gap_s  +  retry_span_s  +  dispatch_delay_s

Every term is read from its real home, never hand-written:

  schedule          config/lane_registry.json          row ``overview-projection``
                    (``scheduler.cadence_slots`` / ``scheduler.cadence``, must equal ``dispatch.cron``)
  retries + timeout config/n8n_retry_policies.json     ``policies[<dispatch.retry_policy>]``
                    config/n8n_run_allowlist.json      entry ``timeout_s``
  dispatch delay    scripts/lib/n8n_coordination_gateway.py ``DUE_MAX_SKEW_S``
  last-good window  scripts/lib/overview_projection.py ``LAST_GOOD_MAX_S``

``max_real_gap_s`` is MEASURED with the dispatcher's own DST-safe calendar (``cron_schedule.fires_between``,
the same function ``n8n_due`` admits slots with) over five reference weeks - a plain week, two holiday weeks
and both DST transitions - by walking every minute of each week. It is not read off the cron string, because
the cron string cannot tell you that the repeated 01:xx hour on a fall-back night fires only once and leaves a
real 65-minute hole.

Two terms of the inequality that the schedule cannot remove:

  * the fall-back fold. The lane's slots are local wall-clock times and ``fires_between`` fires a repeated
    slot once (fold 0), so after 01:55 EDT the next admission is 02:00 EST - 65 real minutes later.
  * the executor's class cap (``class_caps.pipeline``). A full pipeline queue DEFERS a start (the slot stays
    claimed and retries); it does not refuse it. That is why the retry span, not the nominal interval, is the
    term that covers late starts.

Nothing here writes, dispatches, calls a broker, or decides what to order. It reads config and does
arithmetic. ``MBI_BEHAVIOR = 0``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

LANE_ID = "overview-projection"
PRODUCER = "scripts/build_overview_projection.py"
#: The stored-only reader's window lives in ``scripts/lib/overview_projection.py``, which this deliverable does not
#: own (held by the R8 fold). Its change ships as a verified patch; this is where a reader of a refusal finds it.
PATCH_REL = "docs/ops/packets/inc-ovw-20261114/overview_projection.patch"
TZ = "America/New_York"
REGISTRY_REL = "config/lane_registry.json"
ALLOWLIST_REL = "config/n8n_run_allowlist.json"
RETRY_REL = "config/n8n_retry_policies.json"

#: (name, first local date, exclusive end date). OP-042 names the two holiday weeks and both DST weeks; the
#: plain week is the control. Dates are America/New_York calendar dates, not UTC days.
REFERENCE_WEEKS: tuple[tuple[str, str, str], ...] = (
    ("plain", "2026-11-09", "2026-11-16"),
    ("thanksgiving", "2026-11-23", "2026-11-30"),
    ("christmas", "2026-12-21", "2026-12-28"),
    ("fall_back", "2026-10-25", "2026-11-02"),
    ("spring_forward", "2027-03-08", "2027-03-15"),
)

#: Body fields that carry SOURCE evidence: the clock of the data the overview reports. A rebuild re-reads the
#: stores, so on a weekend or holiday these stay on the last completed session; they are never stamped from the
#: build's own wall clock. Paths are dotted and rooted at the BODY the producer stores - the object
#: ``api_v2._overview_with_today_move()`` returns, not the ``{"ok":…,"data":{…}}`` wire envelope around it. Every
#: path below was read off a real OverviewProjection@v1 built on 2026-11-14 (Saturday; a weekend rebuild keeps the
#: Friday clocks, which is exactly what this document must be able to show); an invented path would record the whole
#: set as absent and a reader could not tell data age from build age.
SOURCE_CLOCK_PATHS: tuple[str, ...] = (
    "as_of",                                        # the holdings read instant the body was assembled from
    "data_as_of",                                   # the store's statement date
    "lookthrough_as_of",                            # fund look-through date (a Friday close, on a Saturday)
    "last_repriced",                                # the mark clock, in the producer's legacy ET text
    "truth.as_of",                                  # positions_current's own statement clock
    "pricing.holdings_as_of",
    "pricing.last_repriced",
    "clock_provenance.positions.as_of",             # oldest declared per-row observation instant
    "clock_provenance.positions.oldest_known_as_of",
    "clock_provenance.positions.newest_known_as_of",
    "clock_provenance.position_list.as_of",
    "clock_provenance.quote.as_of",
    "clock_provenance.day_pnl.as_of",               # null + a gap reason while stored day_change has no clock
    "portfolio_aggregate.position_observation_oldest",
    "portfolio_aggregate.position_observation_newest",
    "trade_ai.vix_observation_time",
    "journal.last_ingested_at",
    "journal.last_close_date",
    "market_session.latest_open_at",                # session identity, not a build stamp
    "market_session.latest_open_session",
)

#: Clocks that are RE-DERIVED from live queries on every build by design (operational monitors, the product
#: wrapper's own assembly stamps). They are deliberately NOT source evidence: they may advance on a Saturday
#: because the monitor ran, not because the market did. Named so a reader can tell the difference.
LIVE_CLOCK_PATHS: tuple[str, ...] = (
    "market_session.as_of",              # the session resolver's request clock: today, every build
    "observation.snapshot_computed_at",  # this build's read instant
    "measures.generated_at",             # this build's measure stamp
    "paper.as_of",                       # the paper-trade query instant, not the trades' clock
    "paper.age_hours",
    "clock_provenance.valuation.as_of",  # the valuation store's generated_at, re-generated on every read
)


class ContractError(RuntimeError):
    """A config file the contract depends on is missing, ambiguous, or internally inconsistent."""


def repo_root() -> Path:
    """The repository this module lives in (``<root>/scripts/lib/overview_lane_contract.py``)."""
    return Path(__file__).resolve().parents[2]


def _json(rel: str, root: Path | None = None) -> Any:
    path = (root or repo_root()) / rel
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContractError(f"{rel}: unreadable ({exc})") from None
    except ValueError as exc:
        raise ContractError(f"{rel}: not JSON ({exc})") from None


def load_registry(root: Path | None = None) -> list[dict[str, Any]]:
    doc = _json(REGISTRY_REL, root)
    rows = doc.get("lanes") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ContractError(f"{REGISTRY_REL}: no `lanes` list")
    return rows


def overview_row(root: Path | None = None, rows: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """The ONE registry row for this lane. Two rows is a second scheduler and is refused, not merged."""
    rows = list(rows) if rows is not None else load_registry(root)
    found = [r for r in rows if str(r.get("lane_id")) == LANE_ID]
    if not found:
        raise ContractError(f"{REGISTRY_REL}: no row for {LANE_ID}")
    if len(found) > 1:
        raise ContractError(f"{REGISTRY_REL}: {len(found)} rows for {LANE_ID} (one scheduler only)")
    return dict(found[0])


def load_allowlist(root: Path | None = None) -> list[dict[str, Any]]:
    doc = _json(ALLOWLIST_REL, root)
    lanes = doc.get("lanes") if isinstance(doc, dict) else None
    if not isinstance(lanes, list):
        raise ContractError(f"{ALLOWLIST_REL}: no `lanes` list")
    return lanes


def allowlist_entry(root: Path | None = None, lanes: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    lanes = list(lanes) if lanes is not None else load_allowlist(root)
    found = [e for e in lanes if str(e.get("lane_id")) == LANE_ID]
    if len(found) != 1:
        raise ContractError(f"{ALLOWLIST_REL}: {len(found)} entries for {LANE_ID} (expected exactly 1)")
    return dict(found[0])


def retry_policy(row: Mapping[str, Any], root: Path | None = None) -> dict[str, Any]:
    name = str((row.get("dispatch") or {}).get("retry_policy") or "")
    doc = _json(RETRY_REL, root)
    policies = doc.get("policies") if isinstance(doc, dict) else None
    if not isinstance(policies, dict) or name not in policies:
        raise ContractError(f"{RETRY_REL}: dispatch.retry_policy {name!r} is not a known policy")
    pol = dict(policies[name])
    pol["name"] = name
    return pol


def declared_schedules(row: Mapping[str, Any]) -> tuple[str, ...]:
    """The cron expressions that drive this lane, as a sorted tuple, with the two homes cross-checked.

    ``scheduler.cadence_slots`` (when present) and ``scheduler.cadence`` are joined by ``" + "`` by the
    registry convention; both must be the SAME SET as ``dispatch.cron``, which is what the dispatcher reads.
    A drift here is the incident repeating itself, so it raises.
    """
    from scripts.lib.cron_schedule import cron_schedules

    sched = row.get("scheduler") or {}
    dispatch = row.get("dispatch") or {}
    slots_raw = sched.get("cadence_slots")
    slots = [s for s in slots_raw if isinstance(s, str) and s.strip()] if isinstance(slots_raw, list) else []
    cadence = str(sched.get("cadence") or "").strip()
    cadence_exprs = cron_schedules(cadence) if cadence else []
    if slots and cadence and not set(cadence_exprs) <= set(slots):
        raise ContractError(f"scheduler.cadence {cadence_exprs} is not a subset of cadence_slots {slots}")
    expressions = sorted(set(slots or cadence_exprs))
    cron = [c for c in (dispatch.get("cron") or []) if isinstance(c, str) and c.strip()]
    if not expressions:
        raise ContractError("scheduler declares no cadence and no cadence_slots")
    if sorted(set(cron)) != expressions:
        raise ContractError(f"dispatch.cron {sorted(set(cron))} != scheduler expressions {expressions}")
    return tuple(expressions)


def _minute_step(expr: str) -> int:
    """The nominal interval, in minutes, of one 5-field expression (``*/1`` -> 1, ``*/5`` -> 5, ``5`` -> 60)."""
    field = str(expr).split()[0]
    if field.startswith("*/"):
        try:
            return max(1, int(field[2:]))
        except ValueError:
            pass
    return 60


def nominal_interval_s(expressions: Iterable[str]) -> int:
    """The smallest declared step: the cadence the schedule promises while it is in its dense period."""
    return 60 * min((_minute_step(e) for e in expressions), default=60)


def _week_bounds(first: str, end: str) -> tuple[datetime, datetime]:
    zone = ZoneInfo(TZ)
    start = datetime.fromisoformat(first).replace(tzinfo=zone)
    stop = datetime.fromisoformat(end).replace(tzinfo=zone)
    if stop <= start:
        raise ContractError(f"week {first}..{end} is empty")
    return start, stop


def fires(expressions: Iterable[str], start: datetime, stop: datetime) -> list[datetime]:
    """Every admission instant of the union of ``expressions`` in (start, stop], ascending, UTC, deduped.

    Uses ``cron_schedule.fires_between`` - the dispatcher's own DST-safe calendar. A local slot that repeats
    on a fall-back night appears once (fold 0), which is the behaviour being measured, not a bug to hide.
    """
    return [at for at, _expr in fires_with_source(expressions, start, stop)]


def fires_with_source(expressions: Iterable[str], start: datetime, stop: datetime) -> list[tuple[datetime, str]]:
    """``fires()`` plus the expression that produced each instant (first expression wins a duplicate)."""
    from scripts.lib.cron_schedule import fires_between

    merged: dict[datetime, str] = {}
    for expr in expressions:
        for fire in fires_between(expr, start, stop, TZ):
            at = fire.at.astimezone(timezone.utc)
            if start < at <= stop and at not in merged:
                merged[at] = expr
    return sorted(merged.items())


def week_profile(expressions: Sequence[str], name: str, first: str, end: str) -> dict[str, Any]:
    """Walk every minute of one week and report the real gaps, the fold gaps, and the hourly coverage.

    ``gaps_over_interval`` names every gap longer than the nominal cadence together with whether it is a
    fall-back fold (an offset DECREASE between the two instants). A non-fold gap over the interval is a
    schedule hole; the acceptance test refuses it.
    """
    zone = ZoneInfo(TZ)
    start, stop = _week_bounds(first, end)
    sourced = fires_with_source(expressions, start, stop)
    ats = [at for at, _expr in sourced]
    interval_s = nominal_interval_s(expressions)
    # A gap is a HOLE only when it exceeds the cadence of the expression that produced its left edge: the
    # 5-minute off-hours/fold period is not a hole just because the in-hours period fires every minute.
    gaps: list[dict[str, Any]] = []
    for (prev, expr), cur in zip(sourced, ats[1:]):
        expected_s = float(60 * _minute_step(expr))
        gap = (cur - prev).total_seconds()
        if gap > expected_s:
            folded = (cur.astimezone(zone).utcoffset() or timedelta(0)) < (prev.astimezone(zone).utcoffset() or timedelta(0))
            gaps.append({
                "gap_s": gap,
                "expected_s": expected_s,
                "expression": expr,
                "from_local": prev.astimezone(zone).isoformat(),
                "to_local": cur.astimezone(zone).isoformat(),
                "fold": bool(folded),
            })
    # the leading edge: how long the week's first admission waits, and the trailing edge to the window end
    lead_s = (ats[0] - start).total_seconds() if ats else None
    tail_s = (stop - ats[-1]).total_seconds() if ats else None

    all_gaps = [(cur - prev).total_seconds() for prev, cur in zip(ats, ats[1:])]

    # every existing local hour must have at least one admission; a local hour that does not exist (the
    # spring-forward 02:00 hour) is not a hole and cannot be one. The walk steps in UTC so a wall-clock hour
    # that never happened is never fabricated by naive local arithmetic.
    utc = timezone.utc
    hour_of_fire = {a.astimezone(zone).strftime("%Y-%m-%dT%H") for a in ats}
    missing: list[str] = []
    minute = start.astimezone(utc)
    stop_utc = stop.astimezone(utc)
    one = timedelta(minutes=1)
    while minute < stop_utc:
        key = minute.astimezone(zone).strftime("%Y-%m-%dT%H")
        if key not in hour_of_fire:
            missing.append(key)
        minute += one
    if ats:
        # the two hours at the window edges are partial; they are covered by the adjacent week's walk
        edge = {start.astimezone(zone).strftime("%Y-%m-%dT%H"), (stop - one).astimezone(zone).strftime("%Y-%m-%dT%H")}
        missing = [h for h in missing if h not in edge]
    return {
        "name": name,
        "start": start.isoformat(),
        "end": stop.isoformat(),
        "fires": len(ats),
        "interval_s": interval_s,
        "max_gap_s": max(all_gaps, default=0.0),
        "gaps_over_interval": gaps,
        "lead_s": lead_s,
        "tail_s": tail_s,
        "hours_without_a_fire": sorted(set(missing)),
        "first": ats[0].astimezone(zone).isoformat() if ats else None,
        "last": ats[-1].astimezone(zone).isoformat() if ats else None,
    }


@lru_cache(maxsize=4)
def _contract_cached(root_key: str) -> dict[str, Any]:
    root = Path(root_key)
    row = overview_row(root)
    entry = allowlist_entry(root)
    expressions = declared_schedules(row)
    schedules = list(expressions)

    weeks = {name: week_profile(schedules, name, first, end) for name, first, end in REFERENCE_WEEKS}
    worst = max(weeks.values(), key=lambda w: w["max_gap_s"])

    policy = retry_policy(row, root)
    attempts = int(policy.get("max_attempts") or 1)
    backoffs = [float(b) for b in (policy.get("backoff_s") or [])]
    timeout_s = float(entry.get("timeout_s") or 0)
    if timeout_s <= 0:
        raise ContractError(f"{ALLOWLIST_REL}: {LANE_ID} timeout_s must be positive")
    retry_backoff_s = sum(backoffs)
    retry_span_s = attempts * timeout_s + retry_backoff_s

    from scripts.lib.n8n_coordination_gateway import DUE_MAX_SKEW_S

    dispatch_delay_s = float(DUE_MAX_SKEW_S)

    floor_s = worst["max_gap_s"] + retry_span_s + dispatch_delay_s
    floor_minimal_s = worst["max_gap_s"] + retry_backoff_s + dispatch_delay_s

    reader, last_good_max_s = reader_window()
    return {
        "lane_id": LANE_ID,
        "reader": reader,
        "invariant_applies": last_good_max_s is not None,
        "schedules": schedules,
        "nominal_interval_s": nominal_interval_s(schedules),
        "weeks": weeks,
        "max_gap_s": worst["max_gap_s"],
        "max_gap_week": worst["name"],
        "retry": {
            "policy": policy.get("name"),
            "max_attempts": attempts,
            "backoff_s": backoffs,
            "timeout_s": timeout_s,
            "retry_backoff_s": retry_backoff_s,
            "retry_span_s": retry_span_s,
            "catchup_min": policy.get("catchup_min"),
        },
        "dispatch_delay_s": dispatch_delay_s,
        "floor_s": floor_s,
        "floor_minimal_s": floor_minimal_s,
        "last_good_max_s": last_good_max_s,
        "patched_last_good_max_s": patched_window(root),
        "patch_rel": PATCH_REL,
        "headroom_s": None if last_good_max_s is None else last_good_max_s - floor_s,
        "invariant": "last_good_max_s > max_gap_s + retry_span_s + dispatch_delay_s",
        #: an INLINE reader (R6, and R8's rollback to it) computes on the request thread and has no last-good
        #: window at all; the inequality is then vacuously satisfied, and saying so is not the same as passing it.
        "ok": True if last_good_max_s is None else last_good_max_s > floor_s,
    }


def patched_window(root: Path | None = None) -> float | None:
    """The last-good window the INC-OVW patch installs, read out of the patch; None when the patch is absent.

    Why read the patch instead of the module: the module is held by another claim, so the number a release needs
    and the number a tree carries can differ for one fold. Naming both is what lets a refusal say "this tree has
    1800 s; the verified patch sets 5400 s" instead of asking an operator to work it out.
    """
    import re

    try:
        text = (Path(root) if root is not None else repo_root()) / PATCH_REL
        text = Path(text).read_text(encoding="utf-8")
    except OSError:
        return None
    found = re.search(r"^\+LAST_GOOD_MAX_S = ([\d.]+)$", text, re.M)
    return float(found.group(1)) if found else None


def reader_window() -> tuple[str, float | None]:
    """(reader mode, last-good window) read from the module that actually serves the route.

    ``stored_only``  ``overview_projection.LAST_GOOD_MAX_S`` exists - the route can answer from disk alone, so the
                     window must exceed the schedule's floor or a weekend answers UNKNOWN. That is the incident.
    ``inline``       R8 reverted the stored-only reader: the module has no window and ``serve()`` computes inline
                     when it cannot serve a body. There is no window to satisfy, and inventing one (or refusing on
                     its absence) would refuse the very rollback the incident calls for.
    Nothing here guesses from a docstring or a config flag: the attribute's presence IS the stored-only path's
    existence, because ``read()`` takes the window as its default argument.
    """
    try:
        from scripts.lib import overview_projection as op
    except ImportError:  # pragma: no cover - imported as lib.*
        from lib import overview_projection as op  # type: ignore[no-redef]
    value = getattr(op, "LAST_GOOD_MAX_S", None)
    if value is None:
        return "inline", None
    return "stored_only", float(value)


def contract(root: Path | None = None) -> dict[str, Any]:
    """The derived contract for this lane. Cached per repository root; ~2 s the first time."""
    return _contract_cached(str((root or repo_root()).resolve()))


def source_clocks(body: Mapping[str, Any]) -> dict[str, Any]:
    """The body's source clocks, copied VERBATIM. Never re-stamped, never parsed, never invented.

    Returns ``{"clocks": {path: value}, "absent": [path, …], "null": [path, …], "live_excluded": [path, …]}``.
    An absent path is recorded as absent so "the read did not carry it" is a fact on the document, not a silence;
    a present-but-null path is recorded separately, because "this source declares no instant" is a different fact
    from "this build did not carry the field". Values are whatever the producer wrote - this function does not
    know what a clock means, only where it is.
    """
    clocks: dict[str, Any] = {}
    absent: list[str] = []
    null: list[str] = []
    for path in SOURCE_CLOCK_PATHS:
        value: Any = body
        found = True
        for part in path.split("."):
            if isinstance(value, Mapping) and part in value:
                value = value[part]
            else:
                found = False
                break
        if found and value is not None:
            clocks[path] = value
        elif found:
            # the field EXISTS and is null: the source declared no observation instant. That is evidence of a gap
            # (today: stored day_change carries no per-row clock), not the same fact as a field that is not there.
            null.append(path)
        else:
            absent.append(path)
    return {"clocks": clocks, "absent": absent, "null": null, "live_excluded": list(LIVE_CLOCK_PATHS)}


def lane_health(*, projection: Mapping[str, Any] | None, projection_readable: bool,
                receipt: Mapping[str, Any] | None, receipt_readable: bool, now: float,
                contract_doc: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Facts and verdicts for one lane, from the projection document and its last run receipt.

    Pure: the two documents are passed in already parsed. A caller that cannot read one passes
    ``None`` with ``*_readable=False`` - unreadable is never a fresh read.
    """
    doc = dict(contract_doc or contract())
    reader = str(doc.get("reader") or "stored_only")
    last_good = None if doc.get("last_good_max_s") is None else float(doc["last_good_max_s"])
    max_gap = float(doc["max_gap_s"])
    retry_span = float(doc["retry"]["retry_span_s"])
    delay = float(doc["dispatch_delay_s"])
    floor = float(doc["floor_s"])

    built_at = None
    age_s = None
    status = None
    if projection_readable and isinstance(projection, Mapping):
        status = projection.get("status")
        raw = projection.get("built_at_epoch")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            built_at = float(raw)
        elif isinstance(projection.get("built_at"), str):
            try:
                built_at = datetime.fromisoformat(str(projection["built_at"]).replace("Z", "+00:00")).timestamp()
            except ValueError:
                built_at = None
        if built_at is not None:
            age_s = now - built_at

    failure_age_s = None
    rec_status = None
    empty_reason = None
    consecutive = None
    if receipt_readable and isinstance(receipt, Mapping):
        rec_status = receipt.get("status")
        empty_reason = receipt.get("empty_reason")
        consecutive = receipt.get("consecutive_failures")
        stamp = receipt.get("finished_at") or receipt.get("ok_at")
        if isinstance(stamp, str):
            try:
                failure_age_s = now - datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
            except ValueError:
                failure_age_s = None

    headroom_s = None if (age_s is None or last_good is None) else last_good - age_s
    verdicts = {
        # the reader would answer UNKNOWN: the projection is past its last-good window. A reader with no window
        # (inline) can never answer UNKNOWN from a stored body, so the state does not exist there.
        "expired": bool(last_good is not None and age_s is not None and age_s > last_good),
        # the projection is missing or unreadable - never treat that as fresh
        "missing": not projection_readable or (isinstance(projection, Mapping) and projection.get("status") not in ("ok",)) and age_s is None,
        # a whole slot plus its retries plus the allowed dispatch delay has passed with no new body
        "missed": bool(age_s is not None and age_s > floor),
        # the body would expire before a missed slot's retries could land
        "headroom_low": bool(last_good is not None and headroom_s is not None and headroom_s < max_gap + retry_span),
        # a failed run that has outlived the next scheduled slot
        "failed": bool(rec_status is not None and rec_status != "ok"
                       and (failure_age_s is None or failure_age_s > max_gap)),
        # the producer never gets the lock: an in-flight refusal that has outlived the whole retry span
        "refused_streak": bool(empty_reason == "build_in_flight" and age_s is not None and age_s > floor),
    }
    broken = [k for k, v in verdicts.items() if v]
    if "expired" in broken or "missing" in broken:
        action = ("Re-dispatch `overview-projection` and read its receipt; the header answers UNKNOWN until a body "
                  "lands. Do not read the header as zero meanwhile.")
    elif "failed" in broken or "refused_streak" in broken:
        action = "Read the lane receipt (status / empty_reason) and fix the producer; the served body is ageing out."
    elif "missed" in broken or "headroom_low" in broken:
        action = "A scheduled slot has not landed. Check the dispatcher's next slot and the executor queue."
    else:
        action = "none"
    return {
        "lane_id": LANE_ID,
        "now": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "reader": reader,
        "projection": {
            "readable": bool(projection_readable),
            "status": status,
            "built_at_epoch": built_at,
            "age_s": None if age_s is None else round(age_s, 1),
            "code_identity": (projection or {}).get("code_identity") if isinstance(projection, Mapping) else None,
            "source_clocks": ((projection or {}).get("source_clocks") or {}) if isinstance(projection, Mapping) else {},
        },
        "receipt": {
            "readable": bool(receipt_readable),
            "status": rec_status,
            "empty_reason": empty_reason,
            "consecutive_failures": consecutive,
            "age_s": None if failure_age_s is None else round(failure_age_s, 1),
            "code_sha": (receipt or {}).get("code_sha") if isinstance(receipt, Mapping) else None,
        },
        "expected": {
            "max_gap_s": max_gap,
            "retry_span_s": retry_span,
            "dispatch_delay_s": delay,
            "floor_s": floor,
            "last_good_max_s": last_good,
            "headroom_s": None if headroom_s is None else round(headroom_s, 1),
        },
        "verdicts": verdicts,
        "broken": broken,
        "next_action": action,
    }
