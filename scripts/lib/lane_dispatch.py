"""lane_dispatch.py — the optional `dispatch` and `watch` blocks on a lane-registry row.

N8N Maturity design 02 §2 (docs/implementation/n8n-maturity/02-six-workflow-architecture.md) and the schema
docs/implementation/n8n-maturity/schemas/registry-dispatch-block.schema.json. Consumers: compute_due (B5.3,
design §3.2) reads `DispatchBlock`; the heartbeat watcher (design §7) reads `WatchBlock`; the executor (B5.5)
and the gateway re-check `dispatch_eligible` before running anything.

Inert by default. A row with no `dispatch` block is mode "off": the dispatcher never emits it. A malformed
block is also "off" for `dispatch_mode` (fail closed) and is reported by `validate_dispatch_block` and by
scripts/check_lane_registry.py.

FORBIDDEN-TOKEN RULE (AGENTS.md §0 rails 1-2, §23.3). Broker, order, stop, positions, secret, guard, deploy and
sender lanes are never dispatch-eligible, whatever their dispatch block says. The tokens are derived from the
existing sources of truth, not a parallel list:
  * scripts/lib/n8n_coordination_gateway.FORBIDDEN_ROUTE_TOKENS — matched on token boundaries;
  * scripts/pipelines/pipeline_manifest.FORBIDDEN_COMMAND_TOKENS — script names, matched as substrings;
  * EXTRA_FORBIDDEN_TOKENS / EXTRA_FORBIDDEN_SUBSTRINGS below — secret/sm-render, stop/positions, guard, deploy,
    sender, which neither list spells out.
They are matched against the lane_id and the row's command-bearing fields (scheduler.expression,
scheduler.match, and a top-level command/script if a row ever carries one). A row with watch.stay_behind=true
is never eligible either.

Scalp exception, documented and NOT carved out here: trade-ai-scalp-live is governed by AGENTS.md 4.0.0 §23.3
through config/n8n_run_allowlist.json. Its cron expression wraps `scripts/market_day_gate.sh`, which is a
pipeline_manifest FORBIDDEN_COMMAND_TOKENS entry, so this rule marks it INELIGIBLE. Any exception must be an
explicit, reviewed change to this module (or to the allowlist contract), never a silent carve-out.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

try:
    from scripts.lib import cron_schedule as _cron
    from scripts.lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS as _ROUTE_TOKENS
    from scripts.pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS as _COMMAND_TOKENS
except ImportError:                                        # imported as lib.lane_dispatch
    from lib import cron_schedule as _cron  # type: ignore
    from lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS as _ROUTE_TOKENS  # type: ignore
    from pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS as _COMMAND_TOKENS  # type: ignore

DISPATCH_MODES = ("off", "dry_run", "live")
DISPATCH_CLASSES = ("monitor", "report", "hygiene", "pipeline", "heavy", "llm", "ingest", "send", "learn")
#: Refused until AGENTS rules R1/R2 (E §3) are ratified (design 02 §2).
RATIFICATION_GATED_CLASSES = frozenset({"llm", "ingest", "send", "learn"})
#: The classes a dispatch block may carry today. Pass a wider set to validate_dispatch_block once R1/R2 land.
PERMITTED_CLASSES_PRE_R1 = frozenset(DISPATCH_CLASSES) - RATIFICATION_GATED_CLASSES
DISPATCH_WAVES = ("W0", "W1", "W2", "W3", "W4", "W5")
DISPATCH_TZ = "America/New_York"
TRIGGER_SOURCES = ("run_done", "receipt", "cio_bus", "ledger_event", "outbox")
DIGEST_ROLES = ("preparer", "sender")
WATCH_SEVERITIES = ("P1", "P2", "P3")

#: Issue codes. The first four align with due-response.schema.json errors[].code.
ISSUE_BAD_CRON = "bad_cron"
ISSUE_UNKNOWN_RETRY_POLICY = "unknown_retry_policy"
ISSUE_CLASS_NOT_PERMITTED = "class_not_permitted"
ISSUE_AFTER_UNKNOWN_LANE = "after_unknown_lane"
ISSUE_BAD_BLOCK = "bad_block"
ISSUE_FORBIDDEN_LANE = "forbidden_lane"

EXTRA_FORBIDDEN_TOKENS = frozenset({
    "secret", "secrets", "stop", "stops", "position", "positions", "guard", "deploy", "sender",
})
EXTRA_FORBIDDEN_SUBSTRINGS = ("sm-render", "sm_render")
#: Token-boundary set: the gateway's route tokens plus the extras.
FORBIDDEN_LANE_TOKENS = frozenset(_ROUTE_TOKENS) | EXTRA_FORBIDDEN_TOKENS
#: Substring set: pipeline_manifest's excluded scripts plus the secret renderers.
FORBIDDEN_LANE_SUBSTRINGS = tuple(_COMMAND_TOKENS) + EXTRA_FORBIDDEN_SUBSTRINGS

_CRON_SHAPE = re.compile(r"^\S+ \S+ \S+ \S+ \S+$")
_RETRY_POLICY_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
_RECEIPT_REL = re.compile(r"^data/[A-Za-z0-9._/-]+$")
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

_DISPATCH_KEYS = frozenset({"mode", "cron", "tz", "wave", "class", "priority", "retry_policy", "catchup_min",
                            "min_interval_s", "after", "triggers", "sweep_cron", "digest_window", "digest_role"})
_DISPATCH_REQUIRED = ("mode", "cron", "class", "priority", "retry_policy", "wave")
_AFTER_KEYS = frozenset({"lane_id", "same_day", "deadline_min", "soft"})
_TRIGGER_KEYS = frozenset({"source", "lane_id", "receipt_rel", "event_type"})
_WATCH_KEYS = frozenset({"factor", "severity", "max_run_s", "stay_behind", "restart_safe"})


class DispatchBlockError(ValueError):
    """A dispatch or watch block that does not match the schema. `code` is an ISSUE_* value."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class AfterEdge:
    lane_id: str
    same_day: bool = True
    deadline_min: Optional[int] = None
    soft: bool = False


@dataclass(frozen=True)
class Trigger:
    source: str
    lane_id: Optional[str] = None
    receipt_rel: Optional[str] = None
    event_type: Optional[str] = None


@dataclass(frozen=True)
class DispatchBlock:
    mode: str
    cron: tuple[str, ...]
    tz: str
    wave: str
    klass: str
    priority: int
    retry_policy: str
    catchup_min: Optional[int]
    min_interval_s: int
    after: tuple[AfterEdge, ...]
    triggers: tuple[Trigger, ...]
    sweep_cron: tuple[str, ...]
    digest_window: Optional[str]
    digest_role: Optional[str]


@dataclass(frozen=True)
class WatchBlock:
    factor: float = 2.0
    severity: Optional[str] = None
    max_run_s: Optional[int] = None
    stay_behind: bool = False
    restart_safe: bool = False


@dataclass(frozen=True)
class DispatchIssue:
    lane_id: str
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"lane_id": self.lane_id, "code": self.code, "detail": self.detail[:160]}


# ── parsing ──────────────────────────────────────────────────────────────────────────────────────

def _bad(detail: str) -> DispatchBlockError:
    return DispatchBlockError(ISSUE_BAD_BLOCK, detail)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _int_in(obj: Mapping[str, Any], key: str, lo: int, hi: int, where: str) -> Optional[int]:
    if key not in obj:
        return None
    v = obj[key]
    if not _is_int(v) or not lo <= v <= hi:
        raise _bad(f"{where}.{key} must be an integer {lo}..{hi}, got {v!r}")
    return v


def _bool(obj: Mapping[str, Any], key: str, default: bool, where: str) -> bool:
    v = obj.get(key, default)
    if not isinstance(v, bool):
        raise _bad(f"{where}.{key} must be a boolean, got {v!r}")
    return v


def _str_or_none(obj: Mapping[str, Any], key: str, where: str) -> Optional[str]:
    v = obj.get(key)
    if v is not None and not isinstance(v, str):
        raise _bad(f"{where}.{key} must be a string, got {v!r}")
    return v


def _closed(obj: Any, allowed: frozenset[str], where: str) -> Mapping[str, Any]:
    if not isinstance(obj, dict):
        raise _bad(f"{where} must be an object")
    extra = sorted(set(obj) - allowed)
    if extra:
        raise _bad(f"{where} has unknown key(s) {extra}")
    return obj


def _cron_list(v: Any, max_items: int, where: str) -> tuple[str, ...]:
    if not isinstance(v, list) or len(v) > max_items:
        raise _bad(f"{where} must be a list of at most {max_items} cron strings")
    out = []
    for i, expr in enumerate(v):
        if not isinstance(expr, str) or not _CRON_SHAPE.match(expr):
            raise DispatchBlockError(ISSUE_BAD_CRON, f"{where}[{i}] is not a 5-field cron: {expr!r}")
        try:
            _cron.parse(expr)
        except ValueError as e:
            raise DispatchBlockError(ISSUE_BAD_CRON, f"{where}[{i}] {expr!r}: {e}") from None
        out.append(expr)
    return tuple(out)


def _after(v: Any) -> tuple[AfterEdge, ...]:
    if not isinstance(v, list) or len(v) > 8:
        raise _bad("dispatch.after must be a list of at most 8 edges")
    edges = []
    for i, e in enumerate(v):
        where = f"dispatch.after[{i}]"
        e = _closed(e, _AFTER_KEYS, where)
        lane = e.get("lane_id")
        if not isinstance(lane, str) or not lane:
            raise _bad(f"{where}.lane_id is required")
        edges.append(AfterEdge(lane_id=lane, same_day=_bool(e, "same_day", True, where),
                               deadline_min=_int_in(e, "deadline_min", 1, 720, where),
                               soft=_bool(e, "soft", False, where)))
    return tuple(edges)


def _triggers(v: Any) -> tuple[Trigger, ...]:
    if not isinstance(v, list) or len(v) > 8:
        raise _bad("dispatch.triggers must be a list of at most 8 triggers")
    out = []
    for i, t in enumerate(v):
        where = f"dispatch.triggers[{i}]"
        t = _closed(t, _TRIGGER_KEYS, where)
        if t.get("source") not in TRIGGER_SOURCES:
            raise _bad(f"{where}.source must be one of {TRIGGER_SOURCES}, got {t.get('source')!r}")
        rel = _str_or_none(t, "receipt_rel", where)
        if rel is not None and not _RECEIPT_REL.match(rel):
            raise _bad(f"{where}.receipt_rel must be data/<relative path>, got {rel!r}")
        ev = _str_or_none(t, "event_type", where)
        if ev is not None and len(ev) > 80:
            raise _bad(f"{where}.event_type longer than 80")
        out.append(Trigger(source=t["source"], lane_id=_str_or_none(t, "lane_id", where),
                           receipt_rel=rel, event_type=ev))
    return tuple(out)


def parse_dispatch_block(row: Mapping[str, Any]) -> Optional[DispatchBlock]:
    """The row's dispatch block, None when absent. Raises DispatchBlockError when malformed."""
    if "dispatch" not in row or row.get("dispatch") is None:
        return None
    d = _closed(row["dispatch"], _DISPATCH_KEYS, "dispatch")
    missing = [k for k in _DISPATCH_REQUIRED if k not in d]
    if missing:
        raise _bad(f"dispatch missing required key(s) {missing}")
    if d["mode"] not in DISPATCH_MODES:
        raise _bad(f"dispatch.mode must be one of {DISPATCH_MODES}, got {d['mode']!r}")
    tz = d.get("tz", DISPATCH_TZ)
    if tz != DISPATCH_TZ:
        raise _bad(f"dispatch.tz must be {DISPATCH_TZ}, got {tz!r}")
    if d["wave"] not in DISPATCH_WAVES:
        raise _bad(f"dispatch.wave must be one of {DISPATCH_WAVES}, got {d['wave']!r}")
    if d["class"] not in DISPATCH_CLASSES:
        raise _bad(f"dispatch.class must be one of {DISPATCH_CLASSES}, got {d['class']!r}")
    priority = _int_in(d, "priority", 0, 9, "dispatch")
    rp = d["retry_policy"]
    if not isinstance(rp, str) or not _RETRY_POLICY_NAME.match(rp):
        raise _bad(f"dispatch.retry_policy is not a policy name: {rp!r}")
    role = d.get("digest_role")
    if role is not None and role not in DIGEST_ROLES:
        raise _bad(f"dispatch.digest_role must be one of {DIGEST_ROLES}, got {role!r}")
    return DispatchBlock(
        mode=d["mode"],
        cron=_cron_list(d["cron"], 8, "dispatch.cron"),
        tz=tz,
        wave=d["wave"],
        klass=d["class"],
        priority=priority,  # type: ignore[arg-type]  # required, so never None here
        retry_policy=rp,
        catchup_min=_int_in(d, "catchup_min", 1, 1440, "dispatch"),
        min_interval_s=_int_in(d, "min_interval_s", 0, 86400, "dispatch") or 0,
        after=_after(d.get("after", [])),
        triggers=_triggers(d.get("triggers", [])),
        sweep_cron=_cron_list(d.get("sweep_cron", []), 4, "dispatch.sweep_cron"),
        digest_window=_str_or_none(d, "digest_window", "dispatch"),
        digest_role=role,
    )


def parse_watch_block(row: Mapping[str, Any]) -> WatchBlock:
    """The row's watch block; schema defaults when absent. Raises DispatchBlockError when malformed."""
    if row.get("watch") is None:
        return WatchBlock()
    w = _closed(row["watch"], _WATCH_KEYS, "watch")
    factor = w.get("factor", 2.0)
    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not 1.0 <= float(factor) <= 6.0:
        raise _bad(f"watch.factor must be a number 1.0..6.0, got {factor!r}")
    sev = w.get("severity")
    if sev is not None and sev not in WATCH_SEVERITIES:
        raise _bad(f"watch.severity must be one of {WATCH_SEVERITIES}, got {sev!r}")
    return WatchBlock(factor=float(factor), severity=sev,
                      max_run_s=_int_in(w, "max_run_s", 1, 86400, "watch"),
                      stay_behind=_bool(w, "stay_behind", False, "watch"),
                      restart_safe=_bool(w, "restart_safe", False, "watch"))


def dispatch_mode(row: Mapping[str, Any]) -> str:
    """"off" when the block is absent or unparseable (fail closed); otherwise the declared mode.

    This does NOT apply the forbidden-token rule: callers that run anything must also require
    dispatch_eligible(row)[0]."""
    try:
        block = parse_dispatch_block(row)
    except DispatchBlockError:
        return "off"
    return block.mode if block else "off"


# ── forbidden-token rule ─────────────────────────────────────────────────────────────────────────

def _command_fields(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    sched = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
    fields = [("lane_id", row.get("lane_id")),
              ("scheduler.expression", sched.get("expression")),
              ("scheduler.match", sched.get("match")),
              ("command", row.get("command")),
              ("script", row.get("script"))]
    return [(name, str(v).lower()) for name, v in fields if v]


def forbidden_hits(row: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Every (token, field) of the forbidden-token rule that this row trips, in a stable order."""
    hits: list[tuple[str, str]] = []
    for field, text in _command_fields(row):
        tokens = {t for t in _TOKEN_SPLIT.split(text) if t}
        hits.extend((tok, field) for tok in sorted(tokens & FORBIDDEN_LANE_TOKENS))
        hits.extend((sub, field) for sub in FORBIDDEN_LANE_SUBSTRINGS if sub.lower() in text)
    return hits


def dispatch_eligible(row: Mapping[str, Any]) -> tuple[bool, str]:
    """(eligible, reason). Never eligible: a stay-behind row, or any forbidden token in the lane id or command.

    Independent of the dispatch block: a block saying `live` cannot make a forbidden lane eligible."""
    try:
        watch = parse_watch_block(row)
    except DispatchBlockError as e:
        return False, f"bad_watch_block:{e.detail}"
    if watch.stay_behind:
        return False, "stay_behind"
    hits = forbidden_hits(row)
    if hits:
        tok, field = hits[0]
        return False, f"forbidden_token:{tok}@{field}"
    return True, "eligible"


# ── validation ───────────────────────────────────────────────────────────────────────────────────

def validate_dispatch_block(row: Mapping[str, Any], *, known_lane_ids: Optional[Iterable[str]] = None,
                            retry_policy_names: Optional[Iterable[str]] = None,
                            permitted_classes: Iterable[str] = PERMITTED_CLASSES_PRE_R1) -> list[DispatchIssue]:
    """Every issue with the row's dispatch/watch blocks. [] when both are absent or clean.

    known_lane_ids / retry_policy_names: None skips that cross-check (no policy file exists yet)."""
    lane = str(row.get("lane_id") or "?")
    issues: list[DispatchIssue] = []
    try:
        parse_watch_block(row)
    except DispatchBlockError as e:
        issues.append(DispatchIssue(lane, e.code, e.detail))
    try:
        block = parse_dispatch_block(row)
    except DispatchBlockError as e:
        return issues + [DispatchIssue(lane, e.code, e.detail)]
    if block is None:
        return issues
    if retry_policy_names is not None and block.retry_policy not in set(retry_policy_names):
        issues.append(DispatchIssue(lane, ISSUE_UNKNOWN_RETRY_POLICY, f"retry_policy {block.retry_policy!r}"))
    if block.klass not in set(permitted_classes):
        issues.append(DispatchIssue(lane, ISSUE_CLASS_NOT_PERMITTED,
                                    f"class {block.klass!r} is refused until AGENTS R1/R2 are ratified"
                                    if block.klass in RATIFICATION_GATED_CLASSES else f"class {block.klass!r}"))
    if known_lane_ids is not None:
        known = set(known_lane_ids)
        for i, edge in enumerate(block.after):
            if edge.lane_id not in known or edge.lane_id == lane:
                issues.append(DispatchIssue(lane, ISSUE_AFTER_UNKNOWN_LANE, f"after[{i}].lane_id {edge.lane_id!r}"))
        for i, trig in enumerate(block.triggers):
            if trig.source == "run_done" and (trig.lane_id not in known or trig.lane_id == lane):
                issues.append(DispatchIssue(lane, ISSUE_AFTER_UNKNOWN_LANE,
                                            f"triggers[{i}] run_done lane_id {trig.lane_id!r}"))
    if block.mode != "off":
        ok, why = dispatch_eligible(row)
        if not ok:
            issues.append(DispatchIssue(lane, ISSUE_FORBIDDEN_LANE, f"mode {block.mode} on an ineligible lane: {why}"))
    return issues


def registry_dispatch_errors(reg: Mapping[str, Any], *,
                             retry_policy_names: Optional[Iterable[str]] = None) -> list[str]:
    """check_lane_registry hook: one line per dispatch/watch issue across the registry."""
    rows = [r for r in (reg.get("lanes") or []) if isinstance(r, dict)]
    known = {str(r.get("lane_id")) for r in rows}
    out = []
    for r in rows:
        for issue in validate_dispatch_block(r, known_lane_ids=known, retry_policy_names=retry_policy_names):
            out.append(f"{issue.lane_id}: dispatch {issue.code}: {issue.detail}")
    return out
