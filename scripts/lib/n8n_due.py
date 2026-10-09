"""n8n_due.py — the pure `coordination/due` computation (N8N Maturity design 02 §3.2, component B5.3).

`compute_due` answers "which (lane, mode, slot) is due now" from three inputs and the coordination ledger:
  * the lane registry rows (`dispatch` block, scripts/lib/lane_dispatch.py) — the schedule of record;
  * the run allowlist entries (config/n8n_run_allowlist.json) — the mode must have a non-null dry_run_arg / live_arg;
  * the retry policies (config/n8n_retry_policies.json, scripts/lib/n8n_retry_policy.py).
It returns DueResponse@v1 (docs/implementation/n8n-maturity/schemas/due-response.schema.json).

READ-ONLY. Nothing here writes the ledger, a file or a socket. The only ledger calls are reads:
`runs_by_key_range`, `recent_done`, `get_dead_letter` and `breaker` (LedgerRunStore). A `run_store` of None is an
empty ledger (every slot in the window is DUE).

Slot identity. Slots come from `cron_schedule.fires_between(expr, now - catchup_min, now, tz)` (start exclusive,
end inclusive, DST gap fires once at the first valid minute, fold fires once on fold 0), so the key
`d:<lane>:<mode>:<YYYYMMDDTHHMM local>` is one per local wall-clock minute. Attempt n > 1 appends `:a<n>` (n ≤ 9).
`catchup_min` is the block's own value, else the retry policy's. A sub-hourly lane (any cron that can fire twice in
an hour) keeps only its newest slot and never replays a backlog (a newer fire supersedes an older retry chain).

Older slots in view (daily-or-slower lanes). A slot that fired before the catch-up window is still evaluated when
it has unfinished business, looking back max(catchup, config retry_view_lookback_min, deadline + catchup of each
`after` edge): an IN_FLIGHT attempt; a retry chain while now < retry_at + catchup (after that it is held MISSED
with its retry_at, never silently dropped); an after-gated attempt-1 slot still waiting while now < its latest
deadline + catchup, or released by its gate while now < release + catchup (reason catchup). DONE / DEAD_LETTER
slots drop out, and a released dead letter re-arms inside the catch-up window only.

Bounds (tz, limit, lane filter, held, the lookback, the soft-edge default deadline) come from config/n8n_due.json
(N8nDueConfig@v1), loaded at import; the gateway and relay import them from here.

State per slot (design §3.2 table; the slot's runs are the rows whose run_id is the base key or base `:a<n>`):
  DUE            no row, no dead letter                                          → item, attempt 1
  IN_FLIGHT      latest attempt REQUESTED / RUNNING                              → nothing
  DONE           latest attempt RUN_DONE / RUN_SKIPPED_LOCK (or verdict ok/skipped)
  RETRY_DUE      latest attempt retryable (n8n_retry_policy.class_verdict), attempt < effective_max_attempts,
                 backoff over                                                    → item, attempt n+1, reason retry
                 OR a RELEASED dead letter that ledger.dead_letter_rearmable accepts and whose re-armed attempt has
                 no row yet                                                      → item, attempts+1, reason dlq_release
  RETRY_WAIT     retryable, backoff not over                                     → held, retry_at
  DEAD_LETTER    an unreleased dead_letters row, or a terminal / exhausted latest attempt the executor has not
                 finalized yet                                                   → held
  WAITING_AFTER  attempt-1 slot whose `after` predecessor has no RUN_DONE in the required mode on the slot's local
                 day (same_day, default) or in the 24 h before the slot (same_day false). A live lane needs a
                 LIVE predecessor run; a dry_run lane accepts dry_run or live. Soft edges stop waiting at
                 slot + deadline_min (config soft_after_default_deadline_min when the edge has none); hard edges
                 keep waiting (the watcher raises after_deadline_missed on wait_deadline < now). A sub-hourly
                 lane counts deadlines from its first fire of the local day. Takes precedence over BREAKER_OPEN.
                                                                                 → held, wait_deadline, waiting_on
  BREAKER_OPEN   the lane's breaker is open (ledger.breaker_is_open) and the slot would otherwise be emitted
                                                                                 → held
  MISSED         the most recent fire at or before the window start has no row, no dead letter and is not in
                 view (daily-or-slower lanes only; only that ONE latest fire, one lookup per cron expression, so
                 older gaps are not re-reported); or an older retry chain that expired un-requested
                                                                                 → held, report only
Mode filter everywhere: keys carry the mode, so a dry_run row never satisfies a live slot.

Lanes are considered only when the row's dispatch mode is not off, `lane_dispatch.dispatch_eligible` passes (a
forbidden lane is skipped silently, whatever its block says — check_lane_registry reports it) and the allowlist
supports the mode. Per-lane defects go to `errors[]` and never stop other lanes: not_allowlisted,
unknown_retry_policy, class_not_permitted (pre-R1 classes AND the policy's permitted_classes),
after_unknown_lane, bad_cron (an unparseable cron in a block whose mode is dry_run/live). Two `after` codes keep
the lane evaluated: after_not_dispatched (the predecessor is off / on cron / ineligible, so it writes no ledger
row and the edge can only time out) and after_mode_unsatisfiable (a live lane after a dry_run-dispatched
predecessor). Any other malformed dispatch block is mode off (lane_dispatch fails closed) and is reported by
check_lane_registry, not here.

`source` "event" and "digest" (design §6, §9) are NOT computed yet: they return the schema shape with no items
(follow-up: event cursors / digest windows).

Shas. `registry_sha`, `allowlist_sha`, `policies_sha` should be the sha256 of the FILE BYTES (the gateway passes
them from its loaders, see `file_sources`). When a caller omits one, the sha256 of the canonical JSON
(sort_keys, compact separators) of the given object is used instead; RetryPolicies carries its own file sha.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

try:
    from scripts.lib import cron_schedule as _cron
    from scripts.lib import lane_dispatch as _ld
    from scripts.lib import n8n_retry_policy as _rp
    from scripts.lib.n8n_coordination_ledger import dead_letter_rearmable as _ld_rearmable
except ImportError:                                        # imported as lib.n8n_due
    from lib import cron_schedule as _cron  # type: ignore
    from lib import lane_dispatch as _ld  # type: ignore
    from lib import n8n_retry_policy as _rp  # type: ignore
    from lib.n8n_coordination_ledger import dead_letter_rearmable as _ld_rearmable  # type: ignore

NO_CONSUMER_REASON = (
    "Imported by scripts/lib/n8n_coordination_gateway.py (operation `due`, and the slot-key check in `run`); "
    "no lane runs it directly."
)

SCHEMA = "DueResponse@v1"
SOURCES = ("schedule", "event", "digest")
#: Structural, not tunable: the key format allows `:a2`..`:a9` (KEY_RE, due-response.schema.json item.attempt).
MAX_ATTEMPT = 9
ALLOWLIST_SCHEMA = "N8nRunAllowlist@v1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = ROOT / "config" / "lane_registry.json"
DUE_CONFIG_PATH = ROOT / "config" / "n8n_due.json"
DUE_CONFIG_SCHEMA = "N8nDueConfig@v1"
#: Integer bounds of config/n8n_due.json. The upper bounds of the first four are the ceilings in
#: schemas/due-response.schema.json (limit.maximum, lane_filter.maxItems, held.maxItems): the config may lower a
#: bound, never raise it past what the response schema accepts.
_DUE_CONFIG_INTS = {"default_limit": (1, 100), "max_limit": (1, 100), "max_lane_filter": (1, 8),
                    "max_held": (1, 200), "retry_view_lookback_min": (1, 10080),
                    "soft_after_default_deadline_min": (1, 720)}


class DueConfigError(ValueError):
    """config/n8n_due.json is missing or malformed. Raised at import: the gateway and relay fail closed."""


@dataclass(frozen=True)
class DueConfig:
    tz: str
    default_limit: int
    max_limit: int
    max_lane_filter: int
    max_held: int
    retry_view_lookback_min: int
    soft_after_default_deadline_min: int


def load_due_config(path: Path | str | None = None) -> DueConfig:
    """Validate and load the `due` bounds (config/n8n_due.json, N8nDueConfig@v1). DueConfigError on any defect."""
    p = Path(path) if path is not None else DUE_CONFIG_PATH
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DueConfigError(f"{p.name}: {type(exc).__name__}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != DUE_CONFIG_SCHEMA:
        raise DueConfigError(f"{p.name}: schema must be {DUE_CONFIG_SCHEMA}")
    unknown = set(doc) - {"schema", "as_of", "description", "tz"} - set(_DUE_CONFIG_INTS)
    if unknown:
        raise DueConfigError(f"{p.name}: unknown keys {sorted(unknown)}")
    vals: dict[str, Any] = {}
    for k, (lo, hi) in _DUE_CONFIG_INTS.items():
        v = doc.get(k)
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise DueConfigError(f"{p.name}: {k} must be an integer in [{lo}, {hi}]")
        vals[k] = v
    tz = doc.get("tz")
    try:
        ZoneInfo(str(tz))
    except Exception as exc:                                  # ZoneInfoNotFoundError / ValueError
        raise DueConfigError(f"{p.name}: unknown tz {tz!r}") from exc
    if vals["default_limit"] > vals["max_limit"]:
        raise DueConfigError(f"{p.name}: default_limit exceeds max_limit")
    return DueConfig(tz=str(tz), **vals)


CONFIG = load_due_config()
DEFAULT_TZ = CONFIG.tz
DEFAULT_LIMIT = CONFIG.default_limit
MAX_LIMIT = CONFIG.max_limit
MAX_LANE_FILTER = CONFIG.max_lane_filter
MAX_HELD = CONFIG.max_held

STATES = ("DUE", "RETRY_DUE", "IN_FLIGHT", "DONE", "RETRY_WAIT", "DEAD_LETTER", "WAITING_AFTER", "BREAKER_OPEN",
          "MISSED")
EMITTED = frozenset({"DUE", "RETRY_DUE"})
HELD = frozenset({"RETRY_WAIT", "WAITING_AFTER", "BREAKER_OPEN", "MISSED", "DEAD_LETTER"})
KEY_PREFIXES = ("d:", "e:", "g:")
KEY_RE = re.compile(r"^([deg]):([a-z0-9][a-z0-9._-]{1,63}):(dry_run|live):([0-9]{8}T[0-9]{4})(?::a([2-9]))?$")
_MODE_ARG = {"dry_run": "dry_run_arg", "live": "live_arg"}
_IN_FLIGHT = frozenset({"REQUESTED", "RUNNING"})
_DONE = frozenset({"RUN_DONE", "RUN_SKIPPED_LOCK"})


class DueSourceError(ValueError):
    """A due input could not be loaded. ``code`` is registry_unreadable | allowlist_unreadable | policies_unreadable."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class SlotEval:
    lane_id: str
    mode: str
    slot_local: str
    at: datetime
    state: str
    priority: int
    klass: str
    attempt: int = 1
    reason: str = "schedule"
    parent_run_id: Optional[str] = None
    retry_at: Optional[datetime] = None
    wait_deadline: Optional[datetime] = None
    waiting_on: list[str] = field(default_factory=list)
    #: internal (never serialized): when the slot became runnable (retry_at for a retry, the after-gate release for
    #: attempt 1) and, for WAITING_AFTER, until when an out-of-window slot stays in view.
    release_at: Optional[datetime] = None
    view_until: Optional[datetime] = None

    @property
    def base_key(self) -> str:
        return slot_key(self.lane_id, self.mode, self.slot_local)

    @property
    def key(self) -> str:
        return slot_key(self.lane_id, self.mode, self.slot_local, self.attempt)


class SlotCheck(tuple):
    """(ok, state) plus what `_run` stores on accept: slot_key, attempt, parent_run_id, klass, priority."""

    def __new__(cls, ok: bool, state: str, ev: Optional[SlotEval] = None):
        obj = super().__new__(cls, (ok, state))
        obj.slot_key = ev.base_key if ev else None
        obj.attempt = ev.attempt if ev else None
        obj.parent_run_id = ev.parent_run_id if ev else None
        obj.klass = ev.klass if ev else None
        obj.priority = ev.priority if ev else None
        return obj

    @property
    def ok(self) -> bool:
        return bool(self[0])

    @property
    def state(self) -> str:
        return str(self[1])


# ── small helpers ────────────────────────────────────────────────────────────────────────────────

def slot_key(lane_id: str, mode: str, slot_local: str, attempt: int = 1, prefix: str = "d") -> str:
    """`d:<lane>:<mode>:<slot_local>`, plus `:a<n>` for attempt n > 1."""
    base = f"{prefix}:{lane_id}:{mode}:{slot_local}"
    return base if attempt <= 1 else f"{base}:a{attempt}"


def parse_key(key: str) -> Optional[tuple[str, str, str, str, int]]:
    """(prefix, lane_id, mode, slot_local, attempt) of a server-minted key, None when malformed."""
    m = KEY_RE.fullmatch(key or "")
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3), m.group(4), int(m.group(5) or 1)


def is_server_minted(key: Any) -> bool:
    return isinstance(key, str) and key.startswith(KEY_PREFIXES)


def canonical_sha(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _as_utc(now: datetime | float) -> datetime:
    if isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        return now.astimezone(timezone.utc)
    return datetime.fromtimestamp(float(now), timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _row_attempt(row: Mapping[str, Any]) -> int:
    a = row.get("attempt")
    if isinstance(a, int) and a >= 1:
        return a
    parsed = parse_key(str(row.get("run_id") or ""))
    return parsed[4] if parsed else 1


def _rows(registry_rows: Any) -> list[dict]:
    if isinstance(registry_rows, Mapping):
        registry_rows = registry_rows.get("lanes") or []
    return [r for r in (registry_rows or []) if isinstance(r, dict) and isinstance(r.get("lane_id"), str)]


def allowlist_entries(allowlist: Any) -> dict[str, dict]:
    """lane_id -> entry. Accepts the N8nRunAllowlist@v1 document or an already-built mapping. Like the gateway's
    load_run_allowlist, only entries with a `command` list count."""
    if isinstance(allowlist, Mapping) and "lanes" in allowlist and isinstance(allowlist.get("lanes"), list):
        out = {}
        for e in allowlist["lanes"]:
            if isinstance(e, dict) and isinstance(e.get("lane_id"), str) and isinstance(e.get("command"), list):
                out[e["lane_id"]] = e
        return out
    if isinstance(allowlist, Mapping):
        return {str(k): v for k, v in allowlist.items() if isinstance(v, Mapping)}
    return {}


# ── loaders (gateway) ────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DueSources:
    """Injectable loaders. Each returns (data, sha256-of-file-bytes) or raises DueSourceError."""

    load_registry: Callable[[], tuple[list[dict], str]]
    load_allowlist: Callable[[], tuple[dict[str, dict], str]]
    load_policies: Callable[[], tuple[Any, str]]
    tz: str = DEFAULT_TZ


def _read_json(path: Path, code: str) -> tuple[Any, str]:
    try:
        raw = Path(path).read_bytes()
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError) as exc:
        raise DueSourceError(code, type(exc).__name__) from exc


def file_sources(registry_path: Path | str | None = None, allowlist_path: Path | str | None = None,
                 policies_path: Path | str | None = None) -> DueSources:
    """Loaders that re-read the files on every call (the registry is the schedule of record; a promote changes it)."""
    reg_p = Path(registry_path) if registry_path else DEFAULT_REGISTRY_PATH
    allow_p = Path(allowlist_path) if allowlist_path else ROOT / "config" / "n8n_run_allowlist.json"
    pol_p = Path(policies_path) if policies_path else _rp.DEFAULT_PATH

    def registry() -> tuple[list[dict], str]:
        doc, sha = _read_json(reg_p, "registry_unreadable")
        if not isinstance(doc, dict) or not isinstance(doc.get("lanes"), list):
            raise DueSourceError("registry_unreadable", "no lanes list")
        return _rows(doc), sha

    def allowlist() -> tuple[dict[str, dict], str]:
        doc, sha = _read_json(allow_p, "allowlist_unreadable")
        if not isinstance(doc, dict) or doc.get("schema") != ALLOWLIST_SCHEMA or not isinstance(doc.get("lanes"), list):
            raise DueSourceError("allowlist_unreadable", "not N8nRunAllowlist@v1")
        return allowlist_entries(doc), sha

    def policies() -> tuple[Any, str]:
        try:
            pol = _rp.load_policies(pol_p)
        except _rp.RetryPolicyError as exc:
            raise DueSourceError("policies_unreadable", "; ".join(exc.errors)[:160]) from exc
        return pol, pol.sha256

    return DueSources(registry, allowlist, policies)


# ── the computation ──────────────────────────────────────────────────────────────────────────────

@dataclass
class _Lane:
    row: dict
    block: Any
    policy: Any
    mode: str


def _err(lane: str, code: str, detail: str) -> dict[str, str]:
    return {"lane_id": lane, "code": code, "detail": detail[:160]}


def _dispatched_mode(row: Mapping[str, Any], entries: Mapping[str, Mapping]) -> Optional[str]:
    """The mode the dispatcher runs `row` in (so the ledger gets RUN_DONE rows for it), or None: mode off, a
    malformed block, ineligible (forbidden / stay-behind / on cron), or no allowlist argv for the mode."""
    try:
        block = _ld.parse_dispatch_block(row)
    except _ld.DispatchBlockError:
        return None
    if block is None or block.mode == "off" or not _ld.dispatch_eligible(row)[0]:
        return None
    entry = entries.get(str(row.get("lane_id")))
    if entry is None or entry.get(_MODE_ARG[block.mode]) is None:
        return None
    return block.mode


def _after_errors(lane: str, block: Any, by_id: Mapping[str, dict], entries: Mapping[str, Mapping]) -> list[dict]:
    """errors[] for `after` edges that can never be satisfied by a ledger row. The lane is still evaluated: a soft
    edge releases at its deadline, a hard edge holds WAITING_AFTER (the watcher raises after_deadline_missed)."""
    out = []
    for e in block.after:
        pm = _dispatched_mode(by_id[e.lane_id], entries)
        how = "released at its soft deadline" if e.soft else "hard edge waits; watcher raises after_deadline_missed"
        if pm is None:
            out.append(_err(lane, "after_not_dispatched",
                            f"after {e.lane_id}: predecessor is not dispatched (off/on cron), it writes no ledger "
                            f"row; {how}"))
        elif block.mode == "live" and pm != "live":
            out.append(_err(lane, "after_mode_unsatisfiable",
                            f"after {e.lane_id}: a live lane needs a live predecessor run, predecessor is {pm}; {how}"))
    return out


def _eligible_lanes(rows: list[dict], entries: Mapping[str, Mapping], policies: Any,
                    lane_filter: Optional[Iterable[str]]) -> tuple[list[_Lane], list[dict]]:
    by_id = {r["lane_id"]: r for r in rows}
    known = set(by_id)
    wanted = set(lane_filter) if lane_filter else None
    lanes: list[_Lane] = []
    errors: list[dict] = []
    for row in rows:
        lane = row["lane_id"]
        if wanted is not None and lane not in wanted:
            continue
        try:
            block = _ld.parse_dispatch_block(row)
        except _ld.DispatchBlockError as exc:
            raw = row.get("dispatch") if isinstance(row.get("dispatch"), dict) else {}
            if exc.code == _ld.ISSUE_BAD_CRON and raw.get("mode") in ("dry_run", "live"):
                errors.append(_err(lane, "bad_cron", exc.detail))
            continue                                       # fail closed: a malformed block is mode off
        if block is None or block.mode == "off":
            continue
        if not _ld.dispatch_eligible(row)[0]:
            continue                                       # forbidden / stay-behind: never emitted
        entry = entries.get(lane)
        if entry is None:
            errors.append(_err(lane, "not_allowlisted", "no run allowlist entry"))
            continue
        if entry.get(_MODE_ARG[block.mode]) is None:
            errors.append(_err(lane, "not_allowlisted", f"allowlist {_MODE_ARG[block.mode]} is null: mode {block.mode} unavailable"))
            continue
        policy = (getattr(policies, "policies", None) or {}).get(block.retry_policy)
        if policy is None:                                 # RetryPolicies.get would return UNRESOLVED_POLICY
            errors.append(_err(lane, "unknown_retry_policy", f"retry_policy {block.retry_policy!r}"))
            continue
        if block.klass not in _ld.PERMITTED_CLASSES_PRE_R1 or not _rp.policy_permits_class(policy, block.klass):
            errors.append(_err(lane, "class_not_permitted", f"class {block.klass!r} under policy {policy.name!r}"))
            continue
        bad_after = [e.lane_id for e in block.after if e.lane_id not in known or e.lane_id == lane]
        if bad_after:
            errors.append(_err(lane, "after_unknown_lane", f"after {bad_after}"))
            continue
        errors.extend(_after_errors(lane, block, by_id, entries))
        lanes.append(_Lane(row, block, policy, block.mode))
    return lanes, errors


class _Ledger:
    """Read-only view of the run store with per-call caches. None store = empty ledger."""

    def __init__(self, store: Any) -> None:
        self.s = store
        self._done: dict[tuple[str, frozenset], list[dict]] = {}

    def slot_rows(self, lo_key: str, hi_key: str) -> list[dict]:
        if self.s is None:
            return []
        return list(self.s.runs_by_key_range(lo_key, hi_key))

    def dead_letter(self, base: str) -> Optional[dict]:
        return None if self.s is None else self.s.get_dead_letter(base)

    def breaker_open(self, lane: str) -> bool:
        if self.s is None:
            return False
        row = self.s.breaker(lane)
        return bool(row and row.get("open"))

    def done(self, lane: str, modes: frozenset) -> list[dict]:
        k = (lane, modes)
        if k not in self._done:
            self._done[k] = [] if self.s is None else list(self.s.recent_done(lane, modes=sorted(modes)))
        return self._done[k]


def _catchup(lane: _Lane) -> int:
    return int(lane.block.catchup_min or lane.policy.catchup_min)


def _edge_deadline_min(edge: Any) -> Optional[int]:
    """An edge's deadline in minutes. A soft edge without one takes config soft_after_default_deadline_min, so a
    soft edge never waits forever; a hard edge without one has no deadline (it waits inside the window)."""
    if edge.deadline_min:
        return int(edge.deadline_min)
    return CONFIG.soft_after_default_deadline_min if edge.soft else None


def _lookback_min(lane: _Lane, sub: bool) -> int:
    """How far back slots stay in view. Daily-or-slower lanes: the catch-up window, widened to keep an open retry
    chain (config retry_view_lookback_min) and an after-gated slot (deadline + catch-up) visible. Sub-hourly lanes
    keep only the newest slot, so their window is the catch-up window."""
    catchup = _catchup(lane)
    if sub:
        return catchup
    extra = [_edge_deadline_min(e) for e in lane.block.after]
    after = max((d + catchup for d in extra if d), default=0)
    return max(catchup, CONFIG.retry_view_lookback_min, after)


def _slots(lane: _Lane, now: datetime, tz: str) -> tuple[list[Any], list[Any], Optional[Any], bool]:
    """(fires in the catch-up window, older fires still in view, the most recent fire at or before the window
    start or None, sub_hourly). ValueError on a bad cron."""
    start = now - timedelta(minutes=_catchup(lane))
    fires: dict[str, Any] = {}
    sub = any(_cron.is_sub_hourly(expr) for expr in lane.block.cron)
    for expr in lane.block.cron:
        for f in _cron.fires_between(expr, start, now, tz):
            if f.slot_local not in fires or f.at < fires[f.slot_local].at:
                fires[f.slot_local] = f
    ordered = sorted(fires.values(), key=lambda f: f.at)
    if sub and ordered:
        ordered = ordered[-1:]
    older: dict[str, Any] = {}
    missed = None
    if not sub:
        view_start = now - timedelta(minutes=_lookback_min(lane, sub))
        for expr in lane.block.cron:
            for f in _cron.fires_between(expr, view_start, start, tz):
                if f.slot_local not in fires and (f.slot_local not in older or f.at < older[f.slot_local].at):
                    older[f.slot_local] = f
            f = _cron.last_fire_at_or_before(expr, start, tz)
            if f is not None and f.slot_local not in fires and (missed is None or f.at > missed.at):
                missed = f
    return ordered, sorted(older.values(), key=lambda f: f.at), missed, sub


def _day_anchor(lane: _Lane, fire: Any, tz: str) -> datetime:
    """First fire of the lane on the slot's local day: a sub-hourly lane's after-deadlines count from here, since
    its newest slot is never older than one interval and a deadline from the slot would never pass."""
    zone = ZoneInfo(tz)
    local = fire.at.astimezone(zone)
    midnight = datetime(local.year, local.month, local.day, tzinfo=zone)
    firsts = []
    for expr in lane.block.cron:
        fs = _cron.fires_between(expr, midnight - timedelta(minutes=1), fire.at, tz)
        if fs:
            firsts.append(fs[0].at)
    return min(firsts) if firsts else fire.at


@dataclass
class _AfterState:
    waiting: list[str]
    wait_deadline: Optional[datetime]           # earliest deadline among the waiting edges
    view_until: Optional[datetime]              # latest waiting deadline + catch-up (None: no deadline)
    released_at: datetime                       # when the last edge was satisfied (or a soft edge timed out)


def _after_wait(lane: _Lane, fire: Any, now: datetime, tz: str, led: _Ledger, sub: bool) -> _AfterState:
    modes = frozenset({"live"}) if lane.mode == "live" else frozenset({"live", "dry_run"})
    zone = ZoneInfo(tz)
    day = fire.at.astimezone(zone).date()
    anchor = _day_anchor(lane, fire, tz) if (sub and lane.block.after) else fire.at
    waiting: list[str] = []
    deadlines: list[datetime] = []
    released = fire.at
    for edge in lane.block.after:
        sat: Optional[datetime] = None
        for r in led.done(edge.lane_id, modes):
            t = _parse_ts(r.get("finished_at"))
            if t is None or t > now:
                continue
            if (t.astimezone(zone).date() == day) if edge.same_day else (t >= fire.at - timedelta(hours=24)):
                sat = t if sat is None else min(sat, t)
        if sat is not None:
            released = max(released, sat)
            continue
        dmin = _edge_deadline_min(edge)
        deadline = anchor + timedelta(minutes=dmin) if dmin else None
        if edge.soft and deadline is not None and now >= deadline:
            released = max(released, deadline)              # soft edge: run anyway at the deadline
            continue
        waiting.append(edge.lane_id)
        if deadline is not None:
            deadlines.append(deadline)
    catchup = timedelta(minutes=_catchup(lane))
    return _AfterState(waiting, min(deadlines) if deadlines else None,
                       (max(deadlines) + catchup) if deadlines else None, released)


def _evaluate_slot(lane: _Lane, fire: Any, newest: bool, rows: list[dict], now: datetime, tz: str,
                   led: _Ledger, breaker_open: bool, sub: bool = False) -> SlotEval:
    b = lane.block
    ev = SlotEval(lane_id=lane.row["lane_id"], mode=lane.mode, slot_local=fire.slot_local, at=fire.at, state="DUE",
                  priority=b.priority, klass=b.klass, reason="schedule" if newest else "catchup")
    latest = max(rows, key=_row_attempt) if rows else None
    latest_attempt = _row_attempt(latest) if latest else 0
    dl = led.dead_letter(ev.base_key)
    if dl is not None:
        if not dl.get("released_at"):
            ev.state = "DEAD_LETTER"
            return ev
        dead_attempts = int(dl.get("attempts") or latest_attempt or 1)
        if not _ld_rearmable(dl)[0]:
            ev.state = "DEAD_LETTER"                        # B5.4 contract: send/learn/single-attempt/unknown never re-arm
            return ev
        if latest_attempt <= dead_attempts:
            n = dead_attempts + 1
            if n > MAX_ATTEMPT:
                ev.state = "DEAD_LETTER"
                return ev
            ev.state, ev.attempt, ev.reason = "RETRY_DUE", n, "dlq_release"
            ev.parent_run_id = (latest or {}).get("run_id") or dl.get("last_run_id")
            if breaker_open:
                ev.state = "BREAKER_OPEN"
            return ev
    if latest is None:
        aw = _after_wait(lane, fire, now, tz, led, sub)
        ev.release_at = aw.released_at
        if aw.waiting:
            ev.state, ev.waiting_on, ev.wait_deadline, ev.view_until = ("WAITING_AFTER", aw.waiting,
                                                                         aw.wait_deadline, aw.view_until)
        elif breaker_open:
            ev.state = "BREAKER_OPEN"
        return ev
    ev.attempt = latest_attempt
    state = str(latest.get("state") or "")
    if state in _IN_FLIGHT:
        ev.state = "IN_FLIGHT"
        return ev
    if state in _DONE:
        ev.state = "DONE"
        return ev
    receipt = latest.get("receipt") if isinstance(latest.get("receipt"), Mapping) else {}
    exit_code = latest.get("exit_code")
    verdict = latest.get("verdict") or _rp.class_verdict(state, exit_code if isinstance(exit_code, int) else None,
                                                         receipt.get("reason"), lane.policy, lane.block.klass)
    if verdict in (_rp.VERDICT_OK, _rp.VERDICT_SKIPPED):
        ev.state = "DONE"
        return ev
    max_attempts = min(_rp.effective_max_attempts(lane.policy, lane.block.klass), MAX_ATTEMPT)
    if verdict == _rp.VERDICT_RETRYABLE and latest_attempt < max_attempts:
        finished = _parse_ts(latest.get("finished_at")) or _parse_ts(latest.get("requested_at")) or now
        retry_at = _rp.next_attempt_at(lane.policy, latest_attempt, finished, lane.block.klass)
        if retry_at is not None:
            ev.release_at = retry_at
            if now >= retry_at:
                ev.state, ev.attempt, ev.reason = "RETRY_DUE", latest_attempt + 1, "retry"
                ev.parent_run_id = str(latest["run_id"])
                if breaker_open:
                    ev.state = "BREAKER_OPEN"
            else:
                ev.state, ev.retry_at = "RETRY_WAIT", retry_at
            return ev
    ev.state = "DEAD_LETTER"                                # terminal or exhausted, finalize may not have run yet
    return ev


def _older_view(ev: SlotEval, now: datetime, catchup: timedelta) -> Optional[SlotEval]:
    """A slot that fired before the catch-up window stays in view only while it still has unfinished business:
    an in-flight attempt, a retry chain (until retry_at + catch-up; after that it is reported MISSED with its
    retry_at), an after-gated slot still waiting (until its latest deadline + catch-up) or released by its gate
    (until release + catch-up). Settled slots (DONE / DEAD_LETTER) and dead-letter re-arms drop out: a release
    re-arms inside the catch-up window only (design 02 §3.3)."""
    if ev.state in ("IN_FLIGHT", "RETRY_WAIT"):
        return ev
    if ev.reason == "dlq_release":
        return None
    if ev.reason == "retry" and ev.state in ("RETRY_DUE", "BREAKER_OPEN") and ev.release_at is not None:
        if now < ev.release_at + catchup:
            return ev
        ev.state, ev.retry_at = "MISSED", ev.release_at      # the chain expired without a request
        return ev
    if ev.state == "WAITING_AFTER":
        return ev if ev.view_until is not None and now < ev.view_until else None
    if ev.attempt == 1 and ev.state in ("DUE", "BREAKER_OPEN") and ev.release_at is not None:
        if now < ev.release_at + catchup:
            ev.reason = "catchup"
            return ev
    return None


def _lane_evals(lane: _Lane, now: datetime, tz: str, led: _Ledger) -> list[SlotEval]:
    fires, older, missed, sub = _slots(lane, now, tz)
    lane_id = lane.row["lane_id"]
    every = fires + older + ([missed] if missed is not None else [])
    if not every:
        return []
    lo = slot_key(lane_id, lane.mode, min(f.slot_local for f in every))
    hi = slot_key(lane_id, lane.mode, max(f.slot_local for f in every)) + ":a9"
    by_slot: dict[str, list[dict]] = {}
    for r in led.slot_rows(lo, hi):
        parsed = parse_key(str(r.get("run_id") or ""))
        if parsed and parsed[0] == "d" and parsed[1] == lane_id and parsed[2] == lane.mode:
            by_slot.setdefault(parsed[3], []).append(r)
    breaker_open = led.breaker_open(lane_id)
    catchup = timedelta(minutes=_catchup(lane))
    out: list[SlotEval] = []
    in_view: set[str] = set()
    for f in older:
        rows = by_slot.get(f.slot_local, [])
        if not rows and not lane.block.after:
            continue                                        # nothing pending on it: not in view
        ev = _older_view(_evaluate_slot(lane, f, False, rows, now, tz, led, breaker_open, sub), now, catchup)
        if ev is not None:
            out.append(ev)
            in_view.add(f.slot_local)
    if missed is not None and missed.slot_local not in in_view and not by_slot.get(missed.slot_local):
        base = slot_key(lane_id, lane.mode, missed.slot_local)
        if led.dead_letter(base) is None:
            out.append(SlotEval(lane_id=lane_id, mode=lane.mode, slot_local=missed.slot_local, at=missed.at,
                                state="MISSED", priority=lane.block.priority, klass=lane.block.klass, reason="catchup"))
    for i, f in enumerate(fires):
        out.append(_evaluate_slot(lane, f, i == len(fires) - 1, by_slot.get(f.slot_local, []), now, tz, led,
                                  breaker_open, sub))
    return out


def evaluate(registry_rows: Any, allowlist: Any, policies: Any, run_store: Any, now: datetime | float, *,
             lane_filter: Optional[Iterable[str]] = None, tz: str = DEFAULT_TZ,
             source: str = "schedule") -> tuple[list[SlotEval], list[dict]]:
    """Every evaluated slot plus per-lane errors. Pure apart from ledger reads."""
    now_utc = _as_utc(now)
    lanes, errors = _eligible_lanes(_rows(registry_rows), allowlist_entries(allowlist), policies, lane_filter)
    if source != "schedule":
        return [], errors                                  # event / digest: follow-up (design §6, §9)
    led = _Ledger(run_store)
    evals: list[SlotEval] = []
    for lane in lanes:
        try:
            evals.extend(_lane_evals(lane, now_utc, tz, led))
        except ValueError as exc:
            errors.append(_err(lane.row["lane_id"], "bad_cron", str(exc)))
    return evals, errors


def compute_due(registry_rows: Any, allowlist: Any, policies: Any, run_store: Any, now: datetime | float,
                source: str = "schedule", lane_filter: Optional[Sequence[str]] = None, limit: int = DEFAULT_LIMIT,
                tz: str = DEFAULT_TZ, *, registry_sha: Optional[str] = None, allowlist_sha: Optional[str] = None,
                policies_sha: Optional[str] = None) -> dict[str, Any]:
    """DueResponse@v1 for `now`. Read-only. See the module docstring for the state table and sha rules."""
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    limit = max(1, min(int(limit), MAX_LIMIT))
    now_utc = _as_utc(now)
    evals, errors = evaluate(registry_rows, allowlist, policies, run_store, now_utc, lane_filter=lane_filter, tz=tz,
                             source=source)
    counts = {s: 0 for s in STATES}
    for ev in evals:
        counts[ev.state] += 1
    actionable = sorted((e for e in evals if e.state in EMITTED),
                        key=lambda e: (e.priority, e.at, e.lane_id, e.mode))
    items = [{"lane_id": e.lane_id, "mode": e.mode, "idempotency_key": e.key, "attempt": e.attempt,
              "slot_local": e.slot_local, "reason": e.reason, "priority": e.priority} for e in actionable[:limit]]
    held = []
    for e in sorted((e for e in evals if e.state in HELD), key=lambda e: (e.priority, e.at, e.lane_id)):
        h: dict[str, Any] = {"lane_id": e.lane_id, "mode": e.mode, "state": e.state, "slot_local": e.slot_local}
        if e.retry_at is not None:
            h["retry_at"] = _iso_z(e.retry_at)
        if e.wait_deadline is not None:
            h["wait_deadline"] = _iso_z(e.wait_deadline)
        if e.waiting_on:
            h["waiting_on"] = list(e.waiting_on)
        held.append(h)
    out: dict[str, Any] = {
        "schema": SCHEMA, "ok": True, "source": source, "computed_at": _iso_z(now_utc), "tz": tz,
        "registry_sha": registry_sha or canonical_sha(registry_rows),
        "allowlist_sha": allowlist_sha or canonical_sha(allowlist),
        "policies_sha": policies_sha or getattr(policies, "sha256", None) or canonical_sha(repr(policies)),
        "limit": limit, "truncated": max(0, len(actionable) - limit), "items": items, "counts": counts,
        "held": held[:MAX_HELD], "errors": errors,
    }
    if lane_filter:
        out["lane_filter"] = list(lane_filter)
    return out


def check_slot_key(key: str, lane_id: str, mode: str, *, registry_rows: Any, allowlist: Any, policies: Any,
                   run_store: Any, now: datetime | float, tz: str = DEFAULT_TZ) -> SlotCheck:
    """Recompute due for ONE lane and say whether `key` is currently DUE / RETRY_DUE in `mode`.

    Not-ok states: MALFORMED_KEY, KEY_MISMATCH (lane/mode differ from the request), UNSUPPORTED_SOURCE (e:/g:
    until §6/§9 land), LANE_NOT_DISPATCHED (mode off, ineligible, or an errors[] lane), MODE_MISMATCH (the
    registry dispatches the lane in the other mode), NOT_A_SLOT (no fire in the catch-up window: forged,
    future or too old), ATTEMPT_MISMATCH, or the slot's own state (IN_FLIGHT, DONE, RETRY_WAIT, ...)."""
    parsed = parse_key(key)
    if parsed is None:
        return SlotCheck(False, "MALFORMED_KEY")
    prefix, k_lane, k_mode, k_slot, k_attempt = parsed
    if k_lane != lane_id or k_mode != mode:
        return SlotCheck(False, "KEY_MISMATCH")
    if prefix != "d":
        return SlotCheck(False, "UNSUPPORTED_SOURCE")
    lanes, _errors = _eligible_lanes(_rows(registry_rows), allowlist_entries(allowlist), policies, [lane_id])
    if not lanes:
        return SlotCheck(False, "LANE_NOT_DISPATCHED")
    if lanes[0].mode != mode:
        return SlotCheck(False, "MODE_MISMATCH")
    try:
        evals = _lane_evals(lanes[0], _as_utc(now), tz, _Ledger(run_store))
    except ValueError:
        return SlotCheck(False, "LANE_NOT_DISPATCHED")
    match = [e for e in evals if e.slot_local == k_slot and e.state != "MISSED"]
    if not match:
        return SlotCheck(False, "NOT_A_SLOT")
    ev = match[0]
    if ev.state not in EMITTED:
        return SlotCheck(False, ev.state)
    if ev.attempt != k_attempt:
        return SlotCheck(False, "ATTEMPT_MISMATCH")
    return SlotCheck(True, ev.state, ev)


def validate_slot_key(key: str, lane_id: str, mode: str, **kwargs: Any) -> tuple[bool, str]:
    """(ok, state) — `check_slot_key` without the accept details."""
    c = check_slot_key(key, lane_id, mode, **kwargs)
    return c.ok, c.state
