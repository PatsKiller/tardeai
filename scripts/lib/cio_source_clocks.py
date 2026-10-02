"""CIOSourceClocks@v1 — one data clock per CIO source, never composition time.

Each CIO source row says *when the source's own data was produced*
(``source_as_of``) separately from *when this projection was composed*
(``composition_as_of``).  Freshness is FRESH / STALE against an explicit
``stale_after_seconds``; a source with no trustworthy clock is UNKNOWN and a
source that cannot be read at all is UNAVAILABLE.  A timestamp merely existing
is never treated as fresh.

Read-only and cheap: ``stat`` + bounded tail reads of JSONL stores, a full
parse only for small JSON documents, and ``SELECT max(<clock>)`` on producer
tables.  No source is ever written, refreshed, or recomputed here.

The same probes back the Advisory Desk dependency clocks
(``scripts/api_v3_advisory.py``) so the desk and the CIO surface read one
clock per producer.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from zoneinfo import ZoneInfo

SCHEMA = "CIOSourceClocks@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

FRESH = "FRESH"
STALE = "STALE"
UNKNOWN = "UNKNOWN"
UNAVAILABLE = "UNAVAILABLE"

ET = ZoneInfo("America/New_York")
# Cron expressions in config/lane_registry.json fire in the host's local zone.
CRON_TZ = ZoneInfo(os.getenv("TRADEAI_CRON_TZ") or "America/New_York")
LANE_REGISTRY_REL = "config/lane_registry.json"

# Clocks further than this in the future are not trustworthy source clocks.
FUTURE_SKEW = timedelta(minutes=5)
TAIL_BYTES = int(os.getenv("CIO_SOURCE_CLOCK_TAIL_BYTES") or 256 * 1024)
# Small JSON documents are parsed whole; larger ones are not read on this path.
MAX_JSON_BYTES = int(os.getenv("CIO_SOURCE_CLOCK_MAX_JSON_BYTES") or 4 * 1024 * 1024)

HOUR = 3600
DAY = 24 * HOUR


def _stale_after(name: str, default: int) -> int:
    """Declared staleness budget, overridable per source by env."""
    raw = os.getenv(f"CIO_SOURCE_CLOCK_STALE_S_{name.upper()}")
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


@dataclass(frozen=True)
class SourceSpec:
    source: str
    producer: str
    kind: str  # json_keys | jsonl_tail | db_max
    ref: str  # project-relative path, or "table.column" for db_max
    clock_keys: tuple[str, ...]
    stale_after_seconds: int
    evidence_class: str
    note: str = ""
    lane_ids: tuple[str, ...] = field(default_factory=tuple)


# One row per CIO source.  Each clock key is the source's *own* data clock;
# keys that are rewritten on every composition (holdings ``generated_at`` /
# ``updated_at`` / ``total_cash_written_at`` are rewritten by every 15-minute
# reprice, indicator_snapshot.json ``computed_at`` is stamped when the
# snapshot is re-projected) are deliberately excluded.
SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        source="portfolio_cash",
        producer="broker position sync -> holdings.json position list (positions + cash rows)",
        kind="json_keys",
        ref="data/portfolios/state/holdings.json",
        clock_keys=("positions_built_at", "data_as_of"),
        stale_after_seconds=_stale_after("portfolio_cash", 36 * HOUR),
        evidence_class="BROKER_POSITION_SNAPSHOT",
        note="last_repriced/generated_at are the price clock (reprice every 15m), not the position/cash clock",
        lane_ids=(),
    ),
    SourceSpec(
        source="decision",
        producer="CIO natural cycle (CIOInvestmentProduct@v1)",
        kind="json_keys",
        ref="data/cio/cio_investment_brief.json",
        clock_keys=("as_of", "generated_at"),
        stale_after_seconds=_stale_after("decision", 26 * HOUR),
        evidence_class="DURABLE_RUNTIME_ARTIFACT",
    ),
    SourceSpec(
        source="research",
        producer="security research spine (SecurityResearchSpine@v1)",
        kind="jsonl_tail",
        ref="data/cio/security_research_spine.jsonl",
        clock_keys=("as_of", "created_at", "recorded_at"),
        stale_after_seconds=_stale_after("research", 48 * HOUR),
        evidence_class="DURABLE_RUNTIME_ARTIFACT",
    ),
    SourceSpec(
        source="memory",
        producer="durable memory commits (MemoryCommit@v1)",
        kind="jsonl_tail",
        ref="data/cio/memory_contexts.jsonl",
        clock_keys=("committed_at", "created_at", "as_of"),
        stale_after_seconds=_stale_after("memory", 36 * HOUR),
        evidence_class="DURABLE_RUNTIME_ARTIFACT",
    ),
    SourceSpec(
        source="analyst_data",
        producer="yahoo analyst targets snapshot (yahoo_analyst_targets_history)",
        kind="db_max",
        ref="yahoo_analyst_targets_history.snapshot_date",
        clock_keys=("snapshot_date",),
        stale_after_seconds=_stale_after("analyst_data", 4 * DAY),
        evidence_class="DB_PRODUCER_TABLE",
        note="date-precision clock (snapshot_date)",
    ),
    SourceSpec(
        source="technicals",
        producer="indicator_cache_refresh (indicator_confluence_cache)",
        kind="db_max",
        ref="indicator_confluence_cache.computed_at",
        clock_keys=("computed_at",),
        stale_after_seconds=_stale_after("technicals", 26 * HOUR),
        evidence_class="DB_PRODUCER_TABLE",
        note="state/data_broker/indicator_snapshot.json computed_at is projection time, not the technicals clock",
        lane_ids=("indicator-cache-refresh",),
    ),
    SourceSpec(
        source="hermes_research",
        producer="Hermes research results (hermes_result@v1)",
        kind="jsonl_tail",
        ref="data/cio/hermes_research_results.jsonl",
        clock_keys=("completed_ts", "completed_at", "as_of"),
        stale_after_seconds=_stale_after("hermes_research", 48 * HOUR),
        evidence_class="DURABLE_RUNTIME_ARTIFACT",
    ),
    SourceSpec(
        source="outcome_belief",
        producer="outcome observations (OutcomeObservation@v1) feeding the instrument belief writer",
        kind="jsonl_tail",
        ref="data/cio/outcome_observations.jsonl",
        clock_keys=("source_as_of", "observed_at", "created_at"),
        stale_after_seconds=_stale_after("outcome_belief", 48 * HOUR),
        evidence_class="DURABLE_RUNTIME_ARTIFACT",
        lane_ids=("instrument-belief-writer",),
    ),
)
SPECS_BY_SOURCE = {spec.source: spec for spec in SOURCE_SPECS}


# ── clock parsing ────────────────────────────────────────────────────────────

def parse_clock(value: Any, *, naive_tz: Any = None) -> Optional[datetime]:
    """Parse a source clock to an aware UTC datetime.

    Handles ISO with/without ``Z``, naive ISO (UTC unless ``naive_tz`` says the
    producer stamped local wall time), date-only (midnight UTC),
    ``datetime``/``date`` objects, epoch numbers, and the repricer's
    ``"2026-10-02 11:45:01 ET"`` form (America/New_York, DST-aware).
    """
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=naive_tz or timezone.utc)).astimezone(timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    zone: Any = None
    for suffix in (" ET", " EDT", " EST"):
        if s.endswith(suffix):
            s, zone = s[: -len(suffix)].strip(), ET
            break
    if s.endswith(" UTC"):
        s, zone = s[:-4].strip(), timezone.utc
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            return datetime(int(s[0:4]), int(s[5:7]), int(s[8:10]), tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone or naive_tz or timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    dt = parse_clock(value)
    return dt.isoformat() if dt else None


def classify(source_as_of: Any, stale_after_seconds: Optional[int], now: datetime) -> tuple[Optional[int], str]:
    """(age_seconds, FRESH|STALE|UNKNOWN) against an explicit budget."""
    dt = parse_clock(source_as_of)
    if dt is None:
        return None, UNKNOWN
    age = max(0, int((now - dt).total_seconds()))
    if stale_after_seconds is None:
        return age, UNKNOWN
    return age, STALE if age > stale_after_seconds else FRESH


def newest_clock(values: Iterable[Any], *, now: Optional[datetime] = None) -> Optional[str]:
    """Newest parseable clock (compared as instants), ignoring future clocks."""
    ceiling = (now or datetime.now(timezone.utc)) + FUTURE_SKEW
    best: Optional[tuple[datetime, Any]] = None
    for raw in values:
        dt = parse_clock(raw)
        if dt is None or dt > ceiling:
            continue
        if best is None or dt > best[0]:
            best = (dt, raw)
    if best is None:
        return None
    raw = best[1]
    return raw.isoformat() if isinstance(raw, (datetime, date)) else str(raw)


# ── probes ───────────────────────────────────────────────────────────────────

def _file_version(path: Path) -> Optional[str]:
    try:
        st = path.stat()
    except OSError:
        return None
    return f"bytes={st.st_size};mtime_ns={st.st_mtime_ns}"


def _tail_rows(path: Path, max_bytes: int) -> list[dict[str, Any]]:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(-max_bytes, os.SEEK_END)
            handle.readline()  # discard partial first line
        lines = handle.read().decode("utf-8", errors="replace").splitlines()
    out: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _first_key(row: dict[str, Any], keys: tuple[str, ...]) -> tuple[Any, Optional[str]]:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", []):
            return value, key
    return None, None


def _probe_file(spec: SourceSpec, root: Path, now: datetime) -> dict[str, Any]:
    path = root / spec.ref
    out: dict[str, Any] = {"source_ref": str(path), "source_version": None, "source_as_of": None, "clock_field": None}
    if not path.is_file():
        out["reason"] = "source_missing"
        out["available"] = False
        return out
    out["source_version"] = _file_version(path)
    out["available"] = True
    try:
        if spec.kind == "json_keys":
            if path.stat().st_size > MAX_JSON_BYTES:
                out["reason"] = "document_too_large_for_request_path"
                return out
            doc = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(doc, dict):
                out["reason"] = "document_not_an_object"
                return out
            for key in spec.clock_keys:
                value = doc.get(key)
                if value in (None, "") or parse_clock(value) is None:
                    continue
                if parse_clock(value) > now + FUTURE_SKEW:
                    continue
                out["source_as_of"], out["clock_field"] = str(value), key
                break
        else:  # jsonl_tail
            rows = _tail_rows(path, TAIL_BYTES)
            stamps: list[tuple[Any, str]] = []
            for row in rows:
                value, key = _first_key(row, spec.clock_keys)
                if key:
                    stamps.append((value, key))
            newest = newest_clock((v for v, _ in stamps), now=now)
            if newest is not None:
                out["source_as_of"] = newest
                out["clock_field"] = next((k for v, k in stamps if str(v) == newest), None)
            out["rows_scanned"] = len(rows)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        out["reason"] = f"read_error:{type(exc).__name__}"
        return out
    if out["source_as_of"] is None:
        out["reason"] = "no_trustworthy_source_timestamp"
    return out


def _default_db_execute(sql: str) -> Any:
    from db_adapter import _execute  # type: ignore[import-not-found]

    return _execute(sql, fetch="one")


def _probe_db(spec: SourceSpec, now: datetime, db_execute: Optional[Callable[[str], Any]]) -> dict[str, Any]:
    table, column = spec.ref.split(".", 1)
    out: dict[str, Any] = {"source_ref": f"db:{spec.ref}", "source_version": None, "source_as_of": None, "clock_field": column}
    try:
        row = (db_execute or _default_db_execute)(f"SELECT max({column}) AS m FROM {table}")
    except Exception as exc:  # noqa: BLE001 — UNAVAILABLE, never raise
        out.update({"available": False, "reason": f"db_unavailable:{type(exc).__name__}"})
        return out
    out["available"] = True
    value = row.get("m") if isinstance(row, dict) else (row[0] if isinstance(row, (list, tuple)) and row else None)
    dt = parse_clock(value)
    if dt is None or dt > now + FUTURE_SKEW:
        out["reason"] = "no_trustworthy_source_timestamp"
        return out
    shown = value.isoformat() if isinstance(value, (datetime, date)) else str(value)
    out["source_as_of"] = shown
    out["source_version"] = f"db_max={shown}"
    return out


def probe_source(
    spec: SourceSpec,
    *,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    db_execute: Optional[Callable[[str], Any]] = None,
) -> dict[str, Any]:
    """One CIOSourceClocks@v1 row for ``spec``.  Never raises."""
    now = now or datetime.now(timezone.utc)
    root = Path(root) if root else PROJECT_ROOT
    if spec.kind == "db_max":
        probe = _probe_db(spec, now, db_execute)
    else:
        probe = _probe_file(spec, root, now)
    available = bool(probe.pop("available", False))
    age, freshness = classify(probe.get("source_as_of"), spec.stale_after_seconds, now)
    if not available:
        freshness = UNAVAILABLE
    row = {
        "source": spec.source,
        "producer": spec.producer,
        "source_ref": probe.get("source_ref"),
        "source_version": probe.get("source_version"),
        "source_as_of": probe.get("source_as_of"),
        "clock_field": probe.get("clock_field"),
        "composition_as_of": now.isoformat(),
        "age_seconds": age,
        "stale_after_seconds": spec.stale_after_seconds,
        "freshness": freshness,
        "evidence_class": spec.evidence_class if available else UNAVAILABLE,
        "reason": probe.get("reason"),
    }
    if spec.note:
        row["note"] = spec.note
    if "rows_scanned" in probe:
        row["rows_scanned"] = probe["rows_scanned"]
    return row


def compose_cio_source_clocks(
    *,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    db_execute: Optional[Callable[[str], Any]] = None,
    specs: Iterable[SourceSpec] = SOURCE_SPECS,
) -> dict[str, Any]:
    """CIOSourceClocks@v1 envelope over every CIO source."""
    now = now or datetime.now(timezone.utc)
    started = time.monotonic()
    rows = [probe_source(spec, root=root, now=now, db_execute=db_execute) for spec in specs]
    counts = {state: 0 for state in (FRESH, STALE, UNKNOWN, UNAVAILABLE)}
    for row in rows:
        counts[row["freshness"]] = counts.get(row["freshness"], 0) + 1
    return {
        "ok": True,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": False,
        "mutation": False,
        "composition_as_of": now.isoformat(),
        "compose_ms": int((time.monotonic() - started) * 1000),
        "sources": rows,
        "counts": counts,
        "not_fresh": [row["source"] for row in rows if row["freshness"] != FRESH],
        "freshness_rule": (
            "FRESH when age_seconds <= stale_after_seconds of the source's own data clock; "
            "STALE beyond it; UNKNOWN when no trustworthy source timestamp exists; "
            "UNAVAILABLE when the source cannot be read. composition_as_of is never a source clock."
        ),
    }


_CACHE_LOCK = threading.Lock()
_ROW_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def cached_source_row(source: str, *, ttl_seconds: float = 60.0) -> Optional[dict[str, Any]]:
    """Request-path helper: one probe per source per ``ttl_seconds``."""
    spec = SPECS_BY_SOURCE.get(source)
    if spec is None:
        return None
    with _CACHE_LOCK:
        hit = _ROW_CACHE.get(source)
        if hit and time.monotonic() - hit[0] < ttl_seconds:
            return dict(hit[1])
    row = probe_source(spec)
    with _CACHE_LOCK:
        _ROW_CACHE[source] = (time.monotonic(), row)
    return dict(row)


# ── declared schedules (lane registry) ───────────────────────────────────────

_REGISTRY_CACHE: dict[str, Any] = {"key": None, "lanes": {}}


def _lane_registry(root: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    path = (Path(root) if root else PROJECT_ROOT) / LANE_REGISTRY_REL
    key = (str(path), _file_version(path))
    if _REGISTRY_CACHE.get("key") == key:
        return _REGISTRY_CACHE["lanes"]
    lanes: dict[str, dict[str, Any]] = {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        for lane in doc.get("lanes") or []:
            if isinstance(lane, dict) and lane.get("lane_id"):
                lanes[str(lane["lane_id"])] = lane
    except (OSError, json.JSONDecodeError):
        lanes = {}
    _REGISTRY_CACHE.update({"key": key, "lanes": lanes})
    return lanes


def _cron_field(spec: str, lo: int, hi: int) -> Optional[set[int]]:
    values: set[int] = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            step = int(step_s)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
            if step != 1:
                end = hi
        if start < lo or end > hi or step < 1:
            return None
        values.update(range(start, end + 1, step))
    return values


def next_cron_fire(expression: str, now: datetime, *, tz: ZoneInfo = CRON_TZ) -> Optional[datetime]:
    """Next fire of a 5-field cron expression (leading tokens of ``expression``)."""
    tokens = str(expression or "").split()
    if len(tokens) < 5:
        return None
    try:
        minutes = _cron_field(tokens[0], 0, 59)
        hours = _cron_field(tokens[1], 0, 23)
        doms = _cron_field(tokens[2], 1, 31)
        months = _cron_field(tokens[3], 1, 12)
        dows = _cron_field(tokens[4], 0, 7)
    except ValueError:
        return None
    if minutes is None or hours is None or doms is None or months is None or dows is None:
        return None
    dows = {0 if d == 7 else d for d in dows}
    dom_star, dow_star = tokens[2] == "*", tokens[4] == "*"
    cur = now.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = cur + timedelta(days=370)
    while cur < limit:
        cron_dow = (cur.weekday() + 1) % 7  # cron: Sun=0
        if dom_star or dow_star:
            day_ok = (cur.day in doms) and (cron_dow in dows)
        else:
            day_ok = (cur.day in doms) or (cron_dow in dows)
        if cur.month not in months or not day_ok:
            cur = (cur + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if cur.hour not in hours:
            cur = (cur + timedelta(hours=1)).replace(minute=0)
            continue
        if cur.minute in minutes:
            return cur.astimezone(timezone.utc)
        cur += timedelta(minutes=1)
    return None


_SYSTEMD_CACHE: dict[str, tuple[float, Optional[str]]] = {}


def _systemd_next_elapse(unit: str) -> Optional[str]:
    hit = _SYSTEMD_CACHE.get(unit)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    iso: Optional[str] = None
    try:
        out = subprocess.check_output(
            ["systemctl", "--user", "show", unit, "-p", "NextElapseUSecRealtime", "--value"],
            stderr=subprocess.DEVNULL, text=True, timeout=2,
        ).strip()
        if out.isdigit():
            usec = int(out)
            if usec > 0:
                iso = datetime.fromtimestamp(usec / 1_000_000, tz=timezone.utc).isoformat()
        elif out and out.lower() not in ("n/a", "0"):
            # systemd prints "Fri 2026-10-02 19:45:00 EDT" for --value.
            parts = out.split(" ", 1)
            text = parts[1] if len(parts) == 2 and parts[0].isalpha() else out
            parsed = parse_clock(text)
            iso = parsed.isoformat() if parsed else None
    except (subprocess.SubprocessError, OSError, ValueError):
        iso = None
    _SYSTEMD_CACHE[unit] = (time.monotonic(), iso)
    return iso


def next_scheduled_run(
    lane_ids: Iterable[str],
    *,
    now: Optional[datetime] = None,
    root: Optional[Path] = None,
    systemd_lookup: Optional[Callable[[str], Optional[str]]] = _systemd_next_elapse,
) -> dict[str, Any]:
    """Earliest next run across the declared lanes, or null + reason."""
    now = now or datetime.now(timezone.utc)
    lane_ids = list(lane_ids)
    if not lane_ids:
        return {"next_run_at": None, "reason": "no lane_registry entry declares this producer"}
    lanes = _lane_registry(root)
    best: Optional[tuple[datetime, dict[str, Any]]] = None
    reasons: list[str] = []
    for lane_id in lane_ids:
        lane = lanes.get(lane_id)
        if not lane:
            reasons.append(f"{lane_id}: not in lane_registry")
            continue
        if str(lane.get("state") or "").upper() != "ACTIVE":
            reasons.append(f"{lane_id}: lane state {lane.get('state')}")
            continue
        sched = lane.get("scheduler") or {}
        kind, expr = sched.get("kind"), str(sched.get("expression") or "")
        fire: Optional[datetime] = None
        if kind == "cron":
            fire = next_cron_fire(expr, now)
            if fire is None:
                reasons.append(f"{lane_id}: cron expression not parseable")
        elif kind == "systemd":
            fire = parse_clock(systemd_lookup(expr)) if systemd_lookup else None
            if fire is None:
                reasons.append(f"{lane_id}: systemd timer {expr} has no next elapse")
        else:
            reasons.append(f"{lane_id}: scheduler kind {kind!r} declares no time")
        if fire is not None and (best is None or fire < best[0]):
            best = (fire, {"lane_id": lane_id, "scheduler_kind": kind, "expression": expr})
    if best is None:
        return {"next_run_at": None, "reason": "; ".join(reasons) or "no declared schedule"}
    return {"next_run_at": best[0].isoformat(), "reason": None, **best[1]}
