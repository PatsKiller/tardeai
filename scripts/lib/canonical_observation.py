#!/usr/bin/env python3
"""One canonical access contract per semantic question.

WHY THIS EXISTS
---------------
`/api/v2/overview` emits one dict built from four separate stores with no
consistency check between them, and the freshness field it publishes is a
literal. The audit (cc-truth-v1-20260902T202759Z) proved both halves:

* `_freshness.json`, `performance_history.json` and `portfolio_news.json` are
  written under the checkout (`$PROJ`) while the served API reads
  `persistent-state`. Separate inodes. Measured 2026-09-02: project copies
  dated 2026-09-02, served copies dated 2026-08-26.
* `portfolio_orchestrator.py` wrote ``"status": "fresh"`` unconditionally, so a
  file that stopped moving in August still reported ``fresh`` in September.

Either defect alone produces a false "fresh", and **fixing either one alone
looks like it worked** -- root synchronization leaves a literal that cannot
express staleness, and replacing the literal leaves it computing staleness from
a file nothing updates. This module addresses the pair together.

WRAP, DON'T REWRITE
-------------------
Nothing here is a new storage layer. Writes go through the existing
``portfolio_state_write_targets`` resolution (``scripts/lib/persistent_state_root.py``)
and the existing ``atomic_write_json``. The same fix already exists for
``risk_management.json`` in ``portfolio_stops.save_risk_state``; its docstring
predicted this recurrence -- "a cron-level fix leaves the next caller free to
reintroduce it" -- and three files were left behind. This module is the
resolution-layer version of that fix plus the metadata that makes the next
recurrence visible rather than silent.

FAIL-CLOSED
-----------
``compute_freshness`` has no input that yields FRESH by default. Missing,
unparsable, future-skewed and clock-regressed timestamps all return UNKNOWN;
an in-range timestamp older than the threshold returns STALE. That is the
property the literal lacked.

AUTHORITY
---------
READ_ONLY_ADVISORY metadata. This module performs no financial calculation,
places no order, touches no broker authority, and changes no scheduler,
guardrail or production configuration.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

CONTRACT_VERSION = "CanonicalObservation@v1"
CALCULATION_VERSION = "1.0.0"

#: A timestamp this far in the future is a clock fault, never freshness.
FUTURE_SKEW_TOLERANCE_S = 120.0

#: Per-dataset staleness thresholds, in hours. A dataset absent from this map
#: has no agreed threshold and is therefore UNKNOWN rather than assumed fresh.
DEFAULT_MAX_AGE_HOURS: dict[str, float] = {
    "_freshness.json": 36.0,
    "holdings.json": 24.0,
    "performance_history.json": 36.0,
    "portfolio_news.json": 48.0,
    "risk_management.json": 24.0,
}

# ── freshness status ─────────────────────────────────────────────────────────

FRESH = "FRESH"
STALE = "STALE"
UNKNOWN = "UNKNOWN"

#: Every status that is not an affirmative freshness claim.
NOT_FRESH = (STALE, UNKNOWN)

# ── quality / entitlement / fallback vocabularies ────────────────────────────

QUALITY_OK = "OK"
QUALITY_DEGRADED = "DEGRADED"
QUALITY_MISSING = "MISSING"
QUALITY_UNPARSABLE = "UNPARSABLE"

ENTITLEMENT_INTERNAL = "INTERNAL"

FALLBACK_NONE = "NONE"
FALLBACK_USED = "FALLBACK_USED"
FALLBACK_MISSING = "SOURCE_MISSING"


def new_trace_id() -> str:
    """Correlation id for one observation set. Not a secret, not an account id."""
    return uuid.uuid4().hex[:16]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Naive datetimes are local-clock producer stamps; attach the local zone.

    The producers in this repository write ``datetime.now().isoformat()`` with
    no zone. Treating those as UTC would shift them by the machine's offset and
    silently move them across a staleness threshold, which is the bug class
    this module exists to close. ``astimezone()`` on a naive value applies the
    system zone, which is what the producer actually meant.
    """
    return value.astimezone(timezone.utc)


def parse_timestamp(raw: Any) -> tuple[datetime | None, str]:
    """Parse a producer timestamp. Returns ``(dt_or_None, reason)``.

    Accepts ISO-8601 with or without a zone, ``YYYY-MM-DD HH:MM:SS ET`` and
    date-only ``YYYY-MM-DD``. A date-only value is reported as such by the
    reason string so a caller can refuse to treat midnight as a wall-clock
    instant -- the audit measured a 16.75h swing from exactly that ambiguity
    against a 36h threshold.
    """
    if raw is None or raw == "":
        return None, "missing"
    if isinstance(raw, datetime):
        return _as_utc(raw), "datetime"
    if isinstance(raw, date):
        return _as_utc(datetime(raw.year, raw.month, raw.day)), "date_only"
    if not isinstance(raw, str):
        return None, f"unparsable_type:{type(raw).__name__}"

    text = raw.strip()
    if not text:
        return None, "missing"

    # "2026-09-02 16:45:02 ET" — the repo's own mixed format.
    zone_suffix = ""
    for suffix in (" ET", " EST", " EDT", " UTC", " Z"):
        if text.upper().endswith(suffix.upper()):
            zone_suffix = suffix.strip()
            text = text[: -len(suffix)].strip()
            break

    # Date-only: no time component at all.
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None, "unparsable"
        return _as_utc(parsed), "date_only"

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None, "unparsable"
    reason = "iso" if not zone_suffix else f"iso_zone_suffix:{zone_suffix}"
    return _as_utc(parsed), reason


def compute_freshness(
    observed_at: Any,
    *,
    max_age_hours: float | None,
    now: datetime | None = None,
    future_skew_tolerance_s: float = FUTURE_SKEW_TOLERANCE_S,
) -> dict[str, Any]:
    """Derive a freshness verdict. **No input yields FRESH by default.**

    UNKNOWN (never FRESH) when the timestamp is missing, unparsable, in the
    future beyond ``future_skew_tolerance_s`` (clock fault or regression), or
    when no threshold has been agreed for the dataset. STALE when the age
    exceeds the threshold. FRESH only when a real timestamp is within a real
    threshold.

    ``date_only`` inputs are additionally marked in ``precision`` so a consumer
    can see that midnight was assumed.
    """
    now = now or utc_now()
    parsed, reason = parse_timestamp(observed_at)
    out: dict[str, Any] = {
        "status": UNKNOWN,
        "age_seconds": None,
        "age_hours": None,
        "threshold_hours": max_age_hours,
        "reason": reason,
        "precision": "date_only" if reason == "date_only" else "instant",
        "observed_at_utc": parsed.isoformat() if parsed else None,
        "evaluated_at_utc": now.isoformat(),
    }
    if parsed is None:
        out["reason"] = f"not_fresh:{reason}"
        return out

    age = (now - parsed).total_seconds()
    out["age_seconds"] = round(age, 1)
    out["age_hours"] = round(age / 3600.0, 3)

    if age < -abs(future_skew_tolerance_s):
        out["reason"] = "not_fresh:future_skew"
        return out
    if max_age_hours is None:
        out["reason"] = "not_fresh:no_agreed_threshold"
        return out
    if age > max_age_hours * 3600.0:
        out["status"] = STALE
        out["reason"] = "stale:over_threshold"
        return out

    out["status"] = FRESH
    out["reason"] = "fresh:within_threshold"
    return out


def market_session(at: datetime | None = None) -> str:
    """Coarse US-equity session label. Advisory only; no trading logic reads it."""
    at = at or utc_now()
    et_offset = timedelta(hours=-4)  # coarse; ET, not a tz database lookup
    local = at + et_offset
    if local.weekday() >= 5:
        return "WEEKEND"
    minutes = local.hour * 60 + local.minute
    if minutes < 4 * 60:
        return "CLOSED"
    if minutes < 9 * 60 + 30:
        return "PRE_MARKET"
    if minutes < 16 * 60:
        return "REGULAR"
    if minutes < 20 * 60:
        return "AFTER_HOURS"
    return "CLOSED"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class ObservationEnvelope:
    """Value and metadata from ONE object, so they cannot be recombined wrongly.

    The audit's central finding was not that Home showed stale data -- it showed
    *fresh values wearing stale metadata*, because the number and its date came
    from different stores. Anything that emits a value must emit this envelope
    with it.
    """

    dataset: str
    source_identity: str
    account_scope: str = "ALL_ACCOUNTS"
    provider_timestamp: str | None = None
    observed_at: str | None = None
    received_at: str | None = None
    normalized_at: str | None = None
    business_date: str | None = None
    market_session: str = "UNKNOWN"
    timezone_label: str = "UTC"
    freshness: dict[str, Any] = field(default_factory=dict)
    quality: str = QUALITY_OK
    entitlement: str = ENTITLEMENT_INTERNAL
    sequence: int | None = None
    source_hash: str | None = None
    calculation_version: str = CALCULATION_VERSION
    contract_version: str = CONTRACT_VERSION
    fallback: str = FALLBACK_NONE
    trace_id: str = field(default_factory=new_trace_id)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def is_fresh(self) -> bool:
        return self.freshness.get("status") == FRESH

    @property
    def status(self) -> str:
        return str(self.freshness.get("status") or UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _state_dirs(checkout_root: Path | str | None = None) -> list[Path]:
    """Served copy first, then the checkout copy. Deduped by realpath."""
    from lib.persistent_state_root import portfolio_state_write_targets  # noqa: PLC0415

    return list(portfolio_state_write_targets(Path(checkout_root or ROOT)))


def canonical_state_path(filename: str, checkout_root: Path | str | None = None) -> Path:
    """The path a *reader* should use: the served copy when it exists."""
    dirs = _state_dirs(checkout_root)
    return (dirs[0] if dirs else Path(checkout_root or ROOT) / "data" / "portfolios" / "state") / filename


def write_state_json(
    filename: str,
    payload: Any,
    *,
    checkout_root: Path | str | None = None,
) -> dict[str, Any]:
    """Write ONE in-memory object to every state root a reader may use.

    This is the whole fix for the root split. The producer keeps writing once;
    the resolution layer decides where "once" lands. A second destination
    failing never breaks the first -- the same rule ``save_risk_state`` already
    applies.
    """
    from lib.atomic_json_store import atomic_write_json  # noqa: PLC0415

    written: list[str] = []
    errors: list[str] = []
    for directory in _state_dirs(checkout_root):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            atomic_write_json(directory / filename, payload)
            written.append(str(directory / filename))
        except OSError as exc:  # never let target 2 break target 1
            errors.append(f"{directory / filename}: {type(exc).__name__}: {exc}")
    return {"written": written, "errors": errors, "target_count": len(written)}


def observe_state_file(
    filename: str,
    *,
    checkout_root: Path | str | None = None,
    observed_at_field: str = "completed_at",
    account_scope: str = "ALL_ACCOUNTS",
    max_age_hours: float | None = None,
    trace_id: str | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], ObservationEnvelope]:
    """Read a state file and return ``(payload, envelope)`` from one read.

    The envelope records the resolved path actually read, its content hash and
    both clocks -- the producer's own ``observed_at_field`` and the file mtime.
    When those two disagree the diagnostics show it, which is exactly the signal
    that was missing when a September page served an August file.
    """
    now = now or utc_now()
    path = canonical_state_path(filename, checkout_root)
    threshold = max_age_hours if max_age_hours is not None else DEFAULT_MAX_AGE_HOURS.get(filename)
    env = ObservationEnvelope(
        dataset=filename,
        source_identity=str(path),
        account_scope=account_scope,
        timezone_label="UTC",
        market_session=market_session(now),
        trace_id=trace_id or new_trace_id(),
    )
    env.received_at = now.isoformat()
    env.normalized_at = now.isoformat()

    if not path.exists():
        env.quality = QUALITY_MISSING
        env.fallback = FALLBACK_MISSING
        env.freshness = compute_freshness(None, max_age_hours=threshold, now=now)
        env.diagnostics = {"exists": False}
        return {}, env

    raw = path.read_bytes()
    env.source_hash = sha256_bytes(raw)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        env.quality = QUALITY_UNPARSABLE
        env.fallback = FALLBACK_MISSING
        env.freshness = compute_freshness(None, max_age_hours=threshold, now=now)
        env.diagnostics = {"exists": True, "parse_error": type(exc).__name__}
        return {}, env
    if not isinstance(payload, dict):
        payload = {"_value": payload}

    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    producer_stamp = payload.get(observed_at_field)
    env.provider_timestamp = str(producer_stamp) if producer_stamp else None
    env.observed_at = env.provider_timestamp or mtime.isoformat()
    env.business_date = str(payload.get("holdings_as_of") or payload.get("as_of") or "") or None
    env.sequence = payload.get("run_id") if isinstance(payload.get("run_id"), int) else None
    env.freshness = compute_freshness(env.observed_at, max_age_hours=threshold, now=now)

    mtime_fresh = compute_freshness(mtime.isoformat(), max_age_hours=threshold, now=now)
    env.diagnostics = {
        "exists": True,
        "file_mtime_utc": mtime.isoformat(),
        "file_mtime_status": mtime_fresh["status"],
        "file_mtime_age_hours": mtime_fresh["age_hours"],
        "producer_stamp_field": observed_at_field,
        "root_kind": "persistent" if _looks_persistent(path) else "checkout",
    }
    # A producer stamp that claims freshness while the file it lives in has not
    # moved for days is the exact shape of the proven defect. Surface it.
    if env.freshness["status"] == FRESH and mtime_fresh["status"] in NOT_FRESH:
        env.quality = QUALITY_DEGRADED
        env.diagnostics["stamp_mtime_disagreement"] = True
    if payload.get("status") == "fresh" and env.freshness["status"] in NOT_FRESH:
        env.diagnostics["literal_status_field_contradicted"] = str(payload.get("status"))
    return payload, env


def _looks_persistent(path: Path) -> bool:
    try:
        from lib.persistent_state_root import good_persistent_root  # noqa: PLC0415

        return str(path.resolve()).startswith(str(Path(good_persistent_root()).resolve()))
    except Exception:
        return False


def position_count_contract(scopes: dict[str, int]) -> dict[str, Any]:
    """Publish named position-count scopes instead of two unlabeled integers.

    The audit measured overview 14 against risk 15. Neither number was wrong:
    they count different populations (overview counts non-cash holdings above
    $100; risk counts non-``risk_excluded`` rows in the risk store). Two
    unlabeled integers cannot express that, so a consumer is forced to read one
    as a contradiction of the other. This returns every scope by name plus an
    explicit agreement flag.
    """
    values = sorted(set(scopes.values()))
    return {
        "contract_version": CONTRACT_VERSION,
        "scopes": dict(scopes),
        "agree": len(values) <= 1,
        "distinct_values": values,
        "primary_scope": next(iter(scopes), None),
    }


def envelope_diagnostics(envelopes: dict[str, ObservationEnvelope]) -> dict[str, Any]:
    """Structured, secret-free summary: source path, age, version, fallback.

    Contains no account identifier, credential, token or holding. ``dataset``,
    ``source_identity`` (a filesystem path) and ages are the whole payload.
    """
    return {
        "contract_version": CONTRACT_VERSION,
        "calculation_version": CALCULATION_VERSION,
        "datasets": {
            name: {
                "source_identity": env.source_identity,
                "root_kind": env.diagnostics.get("root_kind"),
                "status": env.status,
                "age_hours": env.freshness.get("age_hours"),
                "threshold_hours": env.freshness.get("threshold_hours"),
                "reason": env.freshness.get("reason"),
                "quality": env.quality,
                "fallback": env.fallback,
                "source_hash": (env.source_hash or "")[:16] or None,
            }
            for name, env in envelopes.items()
        },
        "any_not_fresh": any(e.status in NOT_FRESH for e in envelopes.values()),
    }


def worst_status(envelopes: dict[str, ObservationEnvelope]) -> str:
    """The surface is only as fresh as its oldest contributing dataset.

    AGENTS.md 9.1: "a 27-day-old $500 makes the block 27 days old." UNKNOWN
    outranks STALE because an unknown age cannot be argued down to a stale one.
    """
    statuses = {e.status for e in envelopes.values()}
    if UNKNOWN in statuses:
        return UNKNOWN
    if STALE in statuses:
        return STALE
    return FRESH if statuses else UNKNOWN


def orchestrator_freshness_status(
    completed_at: Any,
    *,
    max_age_hours: float | None = None,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """Status the pipeline should record for its own run.

    Replaces ``"status": "fresh"``. The producer writes what it measured, not a
    constant, so a file that stops moving stops claiming freshness.
    """
    threshold = max_age_hours if max_age_hours is not None else DEFAULT_MAX_AGE_HOURS["_freshness.json"]
    verdict = compute_freshness(completed_at, max_age_hours=threshold, now=now)
    return verdict["status"].lower(), verdict


__all__ = [
    "CALCULATION_VERSION",
    "CONTRACT_VERSION",
    "DEFAULT_MAX_AGE_HOURS",
    "FRESH",
    "NOT_FRESH",
    "STALE",
    "UNKNOWN",
    "ObservationEnvelope",
    "canonical_state_path",
    "compute_freshness",
    "envelope_diagnostics",
    "market_session",
    "new_trace_id",
    "observe_state_file",
    "orchestrator_freshness_status",
    "parse_timestamp",
    "position_count_contract",
    "worst_status",
    "write_state_json",
]
