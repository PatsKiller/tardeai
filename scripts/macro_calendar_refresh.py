#!/usr/bin/env python3
"""macro_calendar_refresh.py — build the 08:30 ET macro-release calendar for the release train's 08:00 window.

Operator ruling 2026-10-21: FRED is the primary source, plus a yearly file for FOMC and overrides
(``config/macro_calendar_overrides.json``); n8n runs this (lane ``macro-calendar-refresh``, daily ~05:00 ET);
the host controller decides (``scripts/lib/macro_calendar.py``); fail closed.

One run:

1. ``GET /fred/releases`` (read-only): every id in :data:`RELEASE_MAP` must exist and carry the expected name.
   A missing or renamed id fails the run: a silently wrong id would make an 08:30 day look clear.
2. ``GET /fred/releases/dates`` with ``realtime_start`` = today (ET), ``realtime_end`` = today + horizon,
   ``include_release_dates_with_no_data=true`` (future dates), paged until ``count`` rows are read.
3. Keep the mapped releases. FRED gives dates, not times: the 08:30 ET flag comes from :data:`RELEASE_MAP`
   (each release's published time). ``valid_through`` is the earliest "last scheduled date" across the mapped
   releases, capped at the horizon: past it at least one release's schedule is unknown, so the reader fails closed.
4. Merge the overrides file: FOMC decision dates (recorded at 14:00 ET; they skip 08:00 only if the operator sets
   ``fomc.skips_0800``), operator ``add`` and ``remove`` rows (a reason is required on each).
5. Write ``<state root>/data/runtime/macro_calendar.json`` (``MacroCalendar@v1``) atomically, then the lane receipt
   ``data/runtime/macro-calendar-refresh_last.json`` (LaneRunReceipt@v2; ``ok_at`` only on success).

A failed run writes no calendar (the previous one stays and ages into STALE, so the 08:00 window is skipped) and a
failed receipt. ``--dry-run`` fetches and prints the same summary and writes nothing.

The API key is ``FRED_API_KEY`` from the process environment (under n8n the executor passes it as an allowlisted
env name). It is never printed, logged, stored or put in an error message; a run reports only whether
it is configured. Exit codes: 0 = calendar written (or dry run printed); 1 = FRED unavailable or answered non-JSON
(e.g. its maintenance page), an id failed verification, the overrides file is invalid, or no key; 2 = usage.

Authority: READ_ONLY_ADVISORY. No DB, no model, no sender, no broker. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT / "scripts"), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib.macro_calendar import ET, FILE_NAME, LANE_ID, SCHEMA  # noqa: E402

FRED_BASE = "https://api.stlouisfed.org/fred"
KEY_ENV = "FRED_API_KEY"
OVERRIDES_REL = "config/macro_calendar_overrides.json"
OVERRIDES_SCHEMA = "MacroCalendarOverrides@v1"
DEFAULT_HORIZON_DAYS = 120
PAGE_LIMIT = 1000
MAX_PAGES = 25
HTTP_TIMEOUT_S = 30
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EVENT_RE = re.compile(r"^[a-z][a-z0-9_]{1,47}$")


@dataclass(frozen=True)
class Release:
    """One FRED release that publishes at a fixed ET time. ``why`` documents the id choice."""

    release_id: int
    event: str
    label: str
    name_re: str
    time_et: str
    agency: str
    why: str


#: FRED release ids that publish at 08:30 ET. Each id is checked against ``GET /fred/releases`` on every run
#: (name must match ``name_re``); the ids and the reasons are documented in docs/ops/MACRO_CALENDAR.md §2.
RELEASE_MAP: tuple[Release, ...] = (
    Release(50, "employment_situation", "Employment Situation (jobs report)", r"^employment situation$", "08:30",
            "BLS", "FRED release 50 'Employment Situation' (PAYEMS, UNRATE); BLS publishes at 08:30 ET"),
    Release(10, "cpi", "Consumer Price Index", r"^consumer price index$", "08:30",
            "BLS", "FRED release 10 'Consumer Price Index' (CPIAUCSL); BLS publishes at 08:30 ET"),
    Release(46, "ppi", "Producer Price Index", r"^producer price index$", "08:30",
            "BLS", "FRED release 46 'Producer Price Index' (PPIFIS); BLS publishes at 08:30 ET"),
    Release(9, "retail_sales", "Advance Retail Sales", r"advance monthly sales for retail and food services",
            "08:30", "Census", "FRED release 9 'Advance Monthly Sales for Retail and Food Services' (RSAFS); "
            "Census publishes at 08:30 ET"),
    Release(53, "gdp", "Gross Domestic Product", r"^gross domestic product$", "08:30",
            "BEA", "FRED release 53 'Gross Domestic Product' (GDP; advance, second and third estimates); "
            "BEA publishes at 08:30 ET"),
    Release(180, "jobless_claims", "Unemployment Insurance Weekly Claims", r"unemployment insurance weekly claims",
            "08:30", "DOL", "FRED release 180 'Unemployment Insurance Weekly Claims Report' (ICSA); DOL publishes "
            "Thursdays at 08:30 ET, the day before on a Thursday holiday week (FRED carries the actual date)"),
    Release(54, "pce", "Personal Income and Outlays (PCE)", r"^personal income and outlays$", "08:30",
            "BEA", "FRED release 54 'Personal Income and Outlays' (PCE, PCEPI); BEA publishes at 08:30 ET"),
    Release(95, "durable_goods", "Durable Goods (Manufacturers' Shipments, Inventories, and Orders)",
            r"manufacturers'? shipments,? inventories,? (and|&) orders|durable goods", "08:30", "Census",
            "FRED release 95 'Manufacturers' Shipments, Inventories, and Orders' (DGORDER). Census publishes the "
            "advance durable-goods report at 08:30 ET and the full M3 report at 10:00 ET; FRED dates may include "
            "both, so this can over-skip (the safe direction), never under-skip"),
    Release(27, "housing_starts", "Housing Starts (New Residential Construction)", r"^new residential construction$",
            "08:30", "Census", "FRED release 27 'New Residential Construction' (HOUST); Census publishes at 08:30 ET"),
)


#: Failure kind -> the closed N8nExpectedOutput skip-reason enum (scripts/check_n8n_workflow_framework.py
#: FATAL_SKIP_REASONS). The kind itself is kept in the receipt summary (``failure_kind``).
SKIP_REASON_OF_KIND = {
    "dependency_unavailable": "dependency_unavailable",  # FRED HTTP error, unreachable, non-JSON, short read, no dates
    "verification_failed": "unconfigured",  # a mapped release id is missing from /fred/releases or renamed
    "config_invalid": "unconfigured",  # config/macro_calendar_overrides.json unreadable or invalid
    "no_credentials": "no_credentials",  # FRED_API_KEY absent
}


class RefreshError(Exception):
    """A run that must not write a calendar. ``reason`` is the failure kind (a key of :data:`SKIP_REASON_OF_KIND`)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason

    @property
    def skip_reason(self) -> str:
        return SKIP_REASON_OF_KIND.get(self.reason, "dependency_unavailable")


# ── FRED ───────────────────────────────────────────────────────────────────────────────────────────────────────


def _scrub(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def urllib_fetch(path: str, params: dict[str, Any], key: str) -> bytes:
    """GET ``FRED_BASE + path`` with ``params`` and the key. Errors carry the status only, never the URL."""
    q = urllib.parse.urlencode({**params, "api_key": key, "file_type": "json"})
    req = urllib.request.Request(f"{FRED_BASE}{path}?{q}", headers={"Accept": "application/json",
                                                                   "User-Agent": "tradeai-macro-calendar/1"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310 — fixed https host
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise RefreshError("dependency_unavailable", f"FRED {path} HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RefreshError("dependency_unavailable", f"FRED {path} unreachable: {type(exc).__name__}") from None


Fetcher = Callable[[str, dict, str], bytes]


def fred_json(fetch: Fetcher, path: str, params: dict[str, Any], key: str) -> dict:
    raw = fetch(path, params, key)
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        head = _scrub(bytes(raw[:80]).decode("utf-8", "replace"), key).replace("\n", " ") if raw else ""
        maint = " (maintenance page)" if b"maintenance" in bytes(raw[:2000]).lower() else ""
        raise RefreshError("dependency_unavailable", f"FRED {path} answered non-JSON{maint}: {head!r}") from None
    if not isinstance(body, dict):
        raise RefreshError("dependency_unavailable", f"FRED {path} answered a non-object")
    if "error_code" in body or "error_message" in body:
        raise RefreshError("dependency_unavailable",
                           _scrub(f"FRED {path} error {body.get('error_code')}: {body.get('error_message')}"[:240], key))
    return body


def fred_paged(fetch: Fetcher, path: str, params: dict[str, Any], key: str, list_key: str) -> tuple[list[dict], dict]:
    """Every row of a paged FRED list. Fails unless exactly ``count`` rows were read."""
    rows: list[dict] = []
    meta: dict = {}
    for page in range(MAX_PAGES):
        body = fred_json(fetch, path, {**params, "limit": PAGE_LIMIT, "offset": page * PAGE_LIMIT}, key)
        chunk = body.get(list_key)
        if not isinstance(chunk, list):
            raise RefreshError("dependency_unavailable", f"FRED {path} has no {list_key} list")
        if page == 0:
            meta = {k: body.get(k) for k in ("realtime_start", "realtime_end", "count")}
        rows.extend(r for r in chunk if isinstance(r, dict))
        count = body.get("count")
        if not isinstance(count, int) or count < 0:
            raise RefreshError("dependency_unavailable", f"FRED {path} has no count")
        if len(rows) >= count or not chunk:
            if len(rows) != count:
                raise RefreshError("dependency_unavailable", f"FRED {path} returned {len(rows)} rows of {count}")
            return rows, meta
    raise RefreshError("dependency_unavailable", f"FRED {path} needs more than {MAX_PAGES} pages")


def verify_release_ids(releases: list[dict]) -> list[dict]:
    """One row per mapped id: {release_id, event, fred_name, ok}. Raises when any id is missing or renamed."""
    by_id = {r.get("id"): r for r in releases}
    out, bad = [], []
    for rel in RELEASE_MAP:
        row = by_id.get(rel.release_id)
        name = str((row or {}).get("name") or "")
        ok = bool(row) and re.search(rel.name_re, name.strip(), re.I) is not None
        out.append({"release_id": rel.release_id, "event": rel.event, "fred_name": name or None,
                    "press_release": (row or {}).get("press_release"), "ok": ok})
        if not ok:
            bad.append(f"{rel.release_id} ({rel.event}): FRED name {name!r}" if row else
                       f"{rel.release_id} ({rel.event}): not in /fred/releases")
    if bad:
        raise RefreshError("verification_failed", "release ids failed verification: " + "; ".join(bad))
    return out


# ── overrides ──────────────────────────────────────────────────────────────────────────────────────────────────


def _iso_date(value: Any, where: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise RefreshError("config_invalid", f"{where}: bad date {value!r}") from None


def load_overrides(path: Path) -> tuple[dict, str]:
    """(validated body, sha256). Any defect raises ``config_invalid``: a half-applied override file is not used."""
    try:
        raw = path.read_bytes()
        body = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise RefreshError("config_invalid", f"{path.name} unreadable: {type(exc).__name__}") from None
    if not isinstance(body, dict) or body.get("schema") != OVERRIDES_SCHEMA:
        raise RefreshError("config_invalid", f"{path.name}: schema is not {OVERRIDES_SCHEMA}")
    fomc = body.get("fomc")
    if not isinstance(fomc, dict) or not isinstance(fomc.get("decision_dates"), list) or not fomc["decision_dates"]:
        raise RefreshError("config_invalid", f"{path.name}: fomc.decision_dates missing")
    if not TIME_RE.match(str(fomc.get("time_et"))) or not isinstance(fomc.get("skips_0800"), bool):
        raise RefreshError("config_invalid", f"{path.name}: fomc.time_et / fomc.skips_0800 invalid")
    for i, d in enumerate(fomc["decision_dates"]):
        _iso_date(d.get("date") if isinstance(d, dict) else d, f"fomc.decision_dates[{i}]")
    for kind in ("add", "remove"):
        rows = body.get(kind, [])
        if not isinstance(rows, list):
            raise RefreshError("config_invalid", f"{path.name}: {kind} is not a list")
        for i, row in enumerate(rows):
            where = f"{kind}[{i}]"
            if not isinstance(row, dict):
                raise RefreshError("config_invalid", f"{where} is not an object")
            _iso_date(row.get("date"), where)
            if not str(row.get("reason") or "").strip():
                raise RefreshError("config_invalid", f"{where} has no reason (every override needs one)")
            ev = str(row.get("event") or "")
            if not (EVENT_RE.match(ev) or (kind == "remove" and ev == "*")):
                raise RefreshError("config_invalid", f"{where}: event {ev!r} is not an event key")
            if kind == "add":
                if not TIME_RE.match(str(row.get("time_et") or "")):
                    raise RefreshError("config_invalid", f"{where}: time_et must be HH:MM (ET)")
                if "skips_0800" in row and not isinstance(row["skips_0800"], bool):
                    raise RefreshError("config_invalid", f"{where}: skips_0800 must be true or false")
    return body, hashlib.sha256(raw).hexdigest()


# ── build ──────────────────────────────────────────────────────────────────────────────────────────────────────


def _event(event: str, name: str, time_et: str, skips: bool, source: str, **extra: Any) -> dict:
    return {"event": event, "name": name, "time_et": time_et, "skips_0800": skips, "source": source, **extra}


def build_calendar(release_rows: list[dict], verified: list[dict], overrides: dict, *, today: date, horizon_end: date,
                   fetched_at: datetime, receipts: list[dict]) -> dict:
    """Pure: FRED rows + verification + overrides -> the MacroCalendar@v1 body. Raises when coverage is unknown."""
    by_id = {r.release_id: r for r in RELEASE_MAP}
    per_release: dict[int, set[date]] = {rid: set() for rid in by_id}
    for row in release_rows:
        rid = row.get("release_id")
        if rid not in by_id:
            continue
        try:
            d = date.fromisoformat(str(row.get("date")))
        except ValueError:
            raise RefreshError("dependency_unavailable", f"FRED release {rid} has a bad date {row.get('date')!r}") from None
        if today <= d <= horizon_end:
            per_release[rid].add(d)
    missing = [f"{rid} ({by_id[rid].event})" for rid, ds in per_release.items() if not ds]
    if missing:
        raise RefreshError("dependency_unavailable",
                           f"no scheduled dates in {today}..{horizon_end} for {', '.join(missing)}: coverage unknown")
    last = {rid: max(ds) for rid, ds in per_release.items()}
    valid_through = min([horizon_end, *last.values()])
    bounded_by = sorted(by_id[rid].event for rid, d in last.items() if d == valid_through)

    events: dict[date, list[dict]] = {}
    for rid, ds in per_release.items():
        rel = by_id[rid]
        for d in ds:
            events.setdefault(d, []).append(_event(rel.event, rel.label, rel.time_et, rel.time_et == "08:30", "fred",
                                                   release_id=rid, agency=rel.agency))
    fomc = overrides["fomc"]
    for row in fomc["decision_dates"]:
        d = date.fromisoformat(str(row.get("date") if isinstance(row, dict) else row))
        events.setdefault(d, []).append(_event(str(fomc.get("event") or "fomc_decision"),
                                               str(fomc.get("name") or "FOMC rate decision"), fomc["time_et"],
                                               bool(fomc["skips_0800"]), "overrides:fomc",
                                               sep=bool(row.get("sep")) if isinstance(row, dict) else None))
    applied = {"added": [], "removed": []}
    for row in overrides.get("add", []):
        d = date.fromisoformat(row["date"])
        skips = row.get("skips_0800", row["time_et"] == "08:30")
        events.setdefault(d, []).append(_event(row["event"], str(row.get("name") or row["event"]), row["time_et"],
                                               bool(skips), "overrides:add", reason=row["reason"]))
        applied["added"].append({"date": d.isoformat(), "event": row["event"], "reason": row["reason"]})
    for row in overrides.get("remove", []):
        d = date.fromisoformat(row["date"])
        before = events.get(d, [])
        keep = [e for e in before if row["event"] != "*" and e["event"] != row["event"]]
        gone = [e["event"] for e in before if e not in keep]
        if keep:
            events[d] = keep
        else:
            events.pop(d, None)
        applied["removed"].append({"date": d.isoformat(), "event": row["event"], "reason": row["reason"],
                                   "matched": gone})

    dates = {}
    for d in sorted(events):
        if today <= d <= valid_through:
            evs = sorted(events[d], key=lambda e: (e["time_et"], e["event"]))
            dates[d.isoformat()] = {"weekday": d.strftime("%a"),
                                    "has_0830": any(e["time_et"] == "08:30" for e in evs),
                                    "skip_0800": any(e["skips_0800"] for e in evs),
                                    "events": evs}
    return {
        "schema": SCHEMA,
        "lane_id": LANE_ID,
        "timezone": "America/New_York",
        "fetched_at": fetched_at.astimezone(timezone.utc).isoformat(),
        "covers_from": today.isoformat(),
        "valid_through": valid_through.isoformat(),
        "valid_through_bounded_by": bounded_by,
        "horizon_end": horizon_end.isoformat(),
        "rule_0800": "skip the 08:00 ET window on a date whose entry has skip_0800 true (an event with skips_0800: "
                     "every 08:30 FRED release; FOMC only if the operator sets it); skip, failing closed, when this "
                     "file is missing, corrupt, older than 72 h or does not cover the date (scripts/lib/macro_calendar.py)",
        "release_days_0830": [k for k, v in dates.items() if v["has_0830"]],
        "skip_days_0800": [k for k, v in dates.items() if v["skip_0800"]],
        "dates": dates,
        "release_map": [{"release_id": r.release_id, "event": r.event, "label": r.label, "time_et": r.time_et,
                         "agency": r.agency, "last_scheduled": last[r.release_id].isoformat()} for r in RELEASE_MAP],
        "verification": verified,
        "fomc_decisions": [str(r.get("date") if isinstance(r, dict) else r) for r in fomc["decision_dates"]],
        "overrides_applied": applied,
        "source_receipts": receipts,
    }


def resolve_key(env: Optional[dict] = None) -> str:
    """FRED_API_KEY from the process env only. Returns '' when absent; never logs it.

    Under n8n the executor hands the lane exactly its allowlisted env names (enforce mode), FRED_API_KEY among them,
    from its own rendered-secrets environment. There is deliberately no in-process env-file loader here: the
    whole-file read path of lib/env_bootstrap fails the enforce-mode closure check
    (tests/test_n8n_executor_env_allowlist_20261009.py), and a manual run gets the key from the caller's
    environment like every other enforced lane."""
    import os

    if env is not None:
        return str(env.get(KEY_ENV) or "").strip()
    return str(os.environ.get(KEY_ENV) or "").strip()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def refresh(key: str, *, fetch: Optional[Fetcher] = None, overrides_path: Path = ROOT / OVERRIDES_REL,
            now: Optional[datetime] = None, horizon_days: int = DEFAULT_HORIZON_DAYS) -> dict:
    """Fetch, verify, merge. Returns the calendar body; raises ``RefreshError``. Writes nothing."""
    if not key:
        raise RefreshError("no_credentials", f"{KEY_ENV} is not configured")
    fetch = fetch or urllib_fetch
    now = now or _utcnow()
    today = now.astimezone(ET).date()
    horizon_end = today + timedelta(days=horizon_days)
    overrides, ov_sha = load_overrides(overrides_path)
    releases, rmeta = fred_paged(fetch, "/releases", {"order_by": "release_id", "sort_order": "asc"}, key, "releases")
    verified = verify_release_ids(releases)
    params = {"realtime_start": today.isoformat(), "realtime_end": horizon_end.isoformat(),
              "include_release_dates_with_no_data": "true", "order_by": "release_date", "sort_order": "asc"}
    rows, dmeta = fred_paged(fetch, "/releases/dates", params, key, "release_dates")
    rows_sha = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
    receipts = [
        {"source": "fred", "endpoint": "/fred/releases", "fetched_at": now.isoformat(), "count": rmeta.get("count"),
         "rows": len(releases)},
        {"source": "fred", "endpoint": "/fred/releases/dates", "fetched_at": now.isoformat(), **{
            k: dmeta.get(k) for k in ("realtime_start", "realtime_end", "count")},
         "params": dict(params), "rows": len(rows), "rows_sha256": rows_sha},
        {"source": "overrides", "path": OVERRIDES_REL, "sha256": ov_sha, "as_of": overrides.get("as_of")},
    ]
    return build_calendar(rows, verified, overrides, today=today, horizon_end=horizon_end, fetched_at=now,
                          receipts=receipts)


# ── output ─────────────────────────────────────────────────────────────────────────────────────────────────────


def summary_lines(cal: dict, *, upcoming: int = 25) -> list[str]:
    out = ["release id verification (GET /fred/releases):"]
    for v in cal["verification"]:
        out.append(f"  {'OK ' if v['ok'] else 'BAD'} {v['release_id']:>4}  {v['event']:<22} FRED name: {v['fred_name']}")
    out.append(f"coverage: {cal['covers_from']} .. {cal['valid_through']} (bounded by "
               f"{', '.join(cal['valid_through_bounded_by'])}; horizon {cal['horizon_end']})")
    out.append(f"08:30 ET release days in coverage: {len(cal['release_days_0830'])}; "
               f"08:00 skip days: {len(cal['skip_days_0800'])}")
    shown = 0
    for d, entry in cal["dates"].items():
        if shown >= upcoming:
            break
        flag = "SKIP 08:00" if entry["skip_0800"] else "clear     "
        evs = ", ".join(f"{e['event']}@{e['time_et']}" for e in entry["events"])
        out.append(f"  {d} {entry['weekday']}  {flag}  {evs}")
        shown += 1
    ov = cal["overrides_applied"]
    out.append(f"overrides: {len(cal['fomc_decisions'])} FOMC dates on file, {len(ov['added'])} added, "
               f"{len(ov['removed'])} removed")
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], allow_abbrev=False)
    ap.add_argument("--dry-run", action="store_true", help="fetch and print; write nothing")
    ap.add_argument("--json", action="store_true", help="print the full calendar JSON")
    ap.add_argument("--horizon-days", type=int, default=DEFAULT_HORIZON_DAYS)
    ap.add_argument("--overrides", default=str(ROOT / OVERRIDES_REL))
    a = ap.parse_args(argv)
    if not 14 <= a.horizon_days <= 400:
        print("[macro-calendar] --horizon-days must be in 14..400", file=sys.stderr)
        return 2

    from lib.lane_last_receipt import dry_run_report, now_iso, receipt_path, write_lane_receipt

    started = now_iso()
    key = resolve_key()
    print(f"[macro-calendar] {KEY_ENV} configured: {'yes' if key else 'no'}")
    try:
        cal = refresh(key, overrides_path=Path(a.overrides), horizon_days=a.horizon_days)
    except RefreshError as exc:
        print(f"[macro-calendar] FAILED ({exc.reason}): {_scrub(str(exc), key)} — no calendar written; the 08:00 "
              "window stays skipped once the previous calendar goes stale", file=sys.stderr)
        if not a.dry_run:
            write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started, script="macro_calendar_refresh.py",
                               error=f"RefreshError: {exc.reason}",
                               summary={"failure_kind": exc.reason, "detail": _scrub(str(exc), key)[:300]},
                               output={"produced_count": 0, "attempted_count": len(RELEASE_MAP),
                                       "skipped_reasons": {exc.skip_reason: 1}})
        return 1
    for line in summary_lines(cal):
        print(line)
    if a.json:
        print(json.dumps(cal, indent=1, sort_keys=True))
    target = receipt_path(LANE_ID).parent / FILE_NAME
    if a.dry_run:
        dry_run_report(LANE_ID, {"covers_from": cal["covers_from"], "valid_through": cal["valid_through"],
                                 "release_days_0830": len(cal["release_days_0830"]),
                                 "skip_days_0800": len(cal["skip_days_0800"]),
                                 "verified_ids": [v["release_id"] for v in cal["verification"] if v["ok"]]},
                       would_write=[str(target), f"data/runtime/{LANE_ID}_last.json"])
        return 0
    from lib.atomic_json_store import atomic_write_json

    atomic_write_json(target, cal, indent=1)
    n = len(cal["skip_days_0800"])
    write_lane_receipt(LANE_ID, ok=True, exit_code=0, started_at=started, script="macro_calendar_refresh.py",
                       summary={"calendar": str(target), "covers_from": cal["covers_from"],
                                "valid_through": cal["valid_through"], "skip_days_0800": n,
                                "fetched_at": cal["fetched_at"]},
                       output={"produced_count": n, "attempted_count": len(RELEASE_MAP),
                               "output_evidence": [{"kind": "file_artifact", "ref": str(target),
                                                    "fetched_at": cal["fetched_at"]}]})
    print(f"[macro-calendar] wrote {target} ({n} 08:00 skip days, valid through {cal['valid_through']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
