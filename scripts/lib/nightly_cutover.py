"""nightly_cutover.py — the ONE evaluator of the nightly n8n cutover controller (2026-10-16).

Operator approval, in writing, 2026-10-16: "building, testing and operating a bounded nightly automatic cutover process
for the already approved migration scope, including the necessary controlled crontab edits". AGENTS.md 12.0.0 §23.25
(approved families go to n8n; F07 and every registry_systemd asset stay unchanged).

This module is pure apart from ``gather_world`` (read-only I/O). ``evaluate(world)`` is shared by ``plan``,
``dry-run`` and ``apply`` (scripts/nightly_cutover_controller.py); apply calls ``gather_world`` + ``evaluate`` itself
and never reads an earlier plan.

Per-lane state machine (each state needs every check of the states before it):

    candidate     the lane is in the approved cohort (§23.25 family, not F07 / registry_systemd / a hold / unknown),
                  its registry row is a cron row at stage canary, ACTIVE, and its retire lines are exact
    evidence_ok   versions agree (CURRENT sha, n8n workflow graph hash, registry, allowlist, mode, contract versions)
                  and a qualifying live n8n run exists (RUN_DONE, exit 0, output_verdict produced or verified-empty,
                  downstream evidence where the lane sends; F09 natural slot only; P1: one completed NYSE session)
    protected     every trigger that remains after the retire is semantically protected (append/send/LLM lanes:
                  effect key armed for n8n, ledger owner n8n, served wrapper with the 10-16 semantics, the exact
                  TRADEAI_EFFECT_CLAIM=<lane> switch on every remaining live crontab line)
    drained       no in-flight run (an old one past its timeout is named), no CLAIMED / UNKNOWN effect claim
    applied       (apply only) the exact lines were commented by the narrow edit capability under the lock, with the
                  crontab hash unchanged since evaluation, backup + byte-exact read-back + ownership
    reconciled    (apply only) registry row -> §23.11 dispatcher row, health contract -> stage cutover, per-lane
                  rollback receipt written

A failed check is ``held:<actionable reason>`` for that lane. A shared control failure (ledger unreadable, CURRENT
unresolvable or changed, crontab unreadable / lock / hash, registry or allowlist unreadable, n8n workflow inventory
unreadable, registry write failure) raises CohortStop: the whole cohort stops.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No broker, order, secret, send or write here.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

NO_CONSUMER_REASON = (
    "Library of scripts/nightly_cutover_controller.py (the nightly cutover controller lane) and of "
    "scripts/n8n_cutover_wave.py (completed_sessions_after for the P1 overlap rule)."
)

PLAN_SCHEMA = "NightlyCutoverPlan@v1"
CONFIG_SCHEMA = "NightlyCutoverControllerConfig@v1"
LANE_ID = "nightly-cutover-controller"
ET = ZoneInfo("America/New_York")
STATES = ("candidate", "evidence_ok", "protected", "drained", "applied", "reconciled")
#: The served wrapper must carry the 2026-10-16 semantics (PR #1823): owner n8n exits 0 skipped_effect, fail-open
#: ledger, decision file. A filename alone is not protection.
WRAPPER_REL = "scripts/effect_claim_cron.sh"
WRAPPER_MARKERS = ("skipped_effect", "owner --process", "--decision-out", "effect_fenced_owner n8n")
VERDICTS_OK = frozenset({"produced", "empty_allowed"})
IN_FLIGHT_STATES = frozenset({"REQUESTED", "RUNNING", "QUEUED", "CLAIMED", "STARTED"})
FAILED_RUN_STATES = frozenset({"RUN_FAILED", "RUN_TIMEOUT"})
AMBIGUOUS_EFFECT_STATES = frozenset({"CLAIMED", "UNKNOWN"})
DISPATCHER_WORKFLOW = "tradeai-dispatcher"
TIER_APPEND = 2
TIER_SEND = 3
SENDER_TIERS = frozenset({TIER_SEND})

DEFAULT_CONFIG: dict[str, Any] = {
    "schema": CONFIG_SCHEMA,
    "max_lanes_per_night": 5,
    "proof_max_age_hours": 72,
    "p1_proof_max_age_days": 7,
    "approved_workflows": [DISPATCHER_WORKFLOW],
    "grant_tier": "cron",
    "grant_token": LANE_ID,
    "registry_root": "~/trade-ai-v12-rebuild/trade-ai-v12-rebuild",
    "receipt_dir": "data/runtime/nightly_cutover",
    "lock_path": "/tmp/n8n_cutover.lock",
    "forced_canary": {"enabled": True, "max_per_night": 5, "poll_seconds": 600, "natural_only_families": ["F09"]},
    "downstream_evidence": {},
    "summary": {"priority": "P3", "producer": LANE_ID},
}


class CohortStop(RuntimeError):
    """A shared control failed: the whole cohort stops (nothing further is applied tonight)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ── config ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def load_config(path: Path) -> dict[str, Any]:
    """The controller config merged over DEFAULT_CONFIG. Unreadable or wrong schema -> CohortStop (fail closed)."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CohortStop(f"controller_config_unreadable:{type(exc).__name__}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != CONFIG_SCHEMA:
        raise CohortStop("controller_config_unreadable:schema")
    out = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in doc.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    cap = out.get("max_lanes_per_night")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0 or cap > 50:
        raise CohortStop("controller_config_unreadable:max_lanes_per_night")
    return out


# ── NYSE sessions (P1 overlap) ─────────────────────────────────────────────────────────────────────────────────────

def _session_bounds(d: date) -> Optional[tuple[datetime, datetime]]:
    """(open, close) of the NYSE regular session on `d` in ET, or None when the exchange is closed. Holidays and the
    13:00 early closes come from the repo's NYSE calendar (scripts/lib/cio_market_session.py), never the federal
    holiday table (which closes on Columbus/Veterans Day and opens on Good Friday)."""
    from scripts.lib.cio_market_session import EARLY_CLOSE_TIME, RTH_CLOSE, RTH_OPEN, nyse_early_closes, nyse_holidays

    if d.weekday() >= 5 or d in nyse_holidays(d.year):
        return None
    close = EARLY_CLOSE_TIME if d in nyse_early_closes(d.year) else RTH_CLOSE
    return (datetime.combine(d, RTH_OPEN, tzinfo=ET), datetime.combine(d, close, tzinfo=ET))


def completed_sessions_after(proof: datetime, now: datetime) -> int:
    """NYSE regular sessions that STARTED at or after `proof` and had CLOSED by `now`. A session already open when the
    proof landed does not count, and crossing midnight counts nothing: only a whole session observed after the proof
    does (operator 2026-10-16: "ONE COMPLETED TRADING SESSION after valid proof")."""
    if proof.tzinfo is None or now.tzinfo is None:
        raise ValueError("completed_sessions_after needs timezone-aware datetimes")
    d, last = proof.astimezone(ET).date(), now.astimezone(ET).date()
    n = 0
    while d <= last:
        b = _session_bounds(d)
        if b is not None and b[0] >= proof and b[1] <= now:
            n += 1
        d += timedelta(days=1)
    return n


# ── n8n workflow graph hash ────────────────────────────────────────────────────────────────────────────────────────

def graph_hash(workflow: Mapping[str, Any]) -> str:
    """sha256 of the behaviour-bearing graph (nodes, connections, settings) exactly as the drift check normalises it
    (scripts/check_n8n_workflow_drift.normalise), so a live copy and its git copy hash equal when they do not drift."""
    from scripts import check_n8n_workflow_drift as drift

    norm = drift.normalise(dict(workflow), placeholder=drift.DEFAULT_PLACEHOLDER)
    return hashlib.sha256(json.dumps(norm, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def sha16(raw: bytes) -> str:
    """The executor's policy version (scripts/lib/n8n_policy_reload.PolicyFile.version)."""
    return hashlib.sha256(raw).hexdigest()[:16]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── the world snapshot ─────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class World:
    now: datetime
    config: Mapping[str, Any]
    policy: Mapping[str, Any]                       # lane_dispatch.load_cutover_policy shape
    disposition: Mapping[str, Mapping[str, str]]    # lane -> first disposition row
    current_sha: str
    registry: Mapping[str, Mapping[str, Any]]       # served (CURRENT) registry rows
    registry_root_rows: Mapping[str, Mapping[str, Any]]
    allowlist: Mapping[str, Mapping[str, Any]]
    allowlist_version: str
    contracts: Mapping[str, Mapping[str, Any]]
    contracts_version: str
    effect_raw: Mapping[str, Mapping[str, Any]]     # config/n8n_effect_keys.json lanes (raw, for tiering)
    effect_lanes: Mapping[str, Mapping[str, Any]]   # effect_claim.load_effect_lanes view
    relay_live: frozenset
    crontab: str
    runs: Mapping[str, list]                        # lane -> run dicts (receipt parsed), oldest first
    in_flight: Mapping[str, list]                   # lane -> in-flight run dicts
    owners: Mapping[str, str]                       # process -> owner
    ambiguous_claims: Mapping[str, list]            # process -> [(effect_key, state)]
    served_wrapper_ok: bool
    served_wrapper_why: str
    workflow_live: Mapping[str, str]                # workflow id -> graph hash (live n8n)
    workflow_git: Mapping[str, str]                 # workflow id -> graph hash (served release, reviewed set)
    lane_workflows: Mapping[str, str] = field(default_factory=dict)   # lane -> its own generated live workflow id
    downstream_mtimes: Mapping[str, float] = field(default_factory=dict)  # configured downstream path -> mtime

    @property
    def crontab_sha(self) -> str:
        return sha256_text(self.crontab)


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _sched(row: Mapping[str, Any]) -> Mapping[str, Any]:
    s = row.get("scheduler")
    return s if isinstance(s, Mapping) else {}


def entry_script(entry: Optional[Mapping[str, Any]]) -> Optional[str]:
    for t in (entry or {}).get("command") or []:
        t = str(t)
        if t.endswith((".py", ".sh")) and "/" in t:
            return t
    return None


def workflow_of(run: Mapping[str, Any]) -> Optional[str]:
    rb = str(run.get("requested_by") or "")
    return rb.split("n8n:workflow:", 1)[1] if rb.startswith("n8n:workflow:") else None


def _is_live_line(ln: str) -> bool:
    s = ln.lstrip()
    return bool(s) and not s.startswith("#") and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", s)


def remaining_triggers(crontab: str, lane: str, script: Optional[str], retire_idx: Iterable[int]) -> list[tuple[int, str]]:
    """Live crontab lines that still fire this lane after the retire: they run its script or carry its TRADEAI_LANE
    tag, and are not in the retire set."""
    skip = set(retire_idx)
    tag = re.compile(r"#\s*TRADEAI_LANE\s+" + re.escape(lane) + r"(\s|$)")
    out = []
    for i, ln in enumerate(crontab.splitlines()):
        if i in skip or not _is_live_line(ln):
            continue
        if (script and script in ln) or tag.search(ln):
            out.append((i, ln))
    return out


def line_switched_on(line: str, lane: str) -> bool:
    """The exact enablement switch of the cron-side effect wrapper for THIS lane (not a crontab-wide export)."""
    return (f"TRADEAI_EFFECT_CLAIM={lane} " in line or f"TRADEAI_EFFECT_CLAIM={lane}\t" in line) and \
        re.search(r"effect_claim_cron\.sh\s+" + re.escape(lane) + r"\s", line) is not None


# ── evaluation ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _hold(v: dict[str, Any], reason: str) -> dict[str, Any]:
    v["held"] = reason
    v["status"] = f"held:{reason}"
    return v


def cohort(world: World) -> list[str]:
    """Candidate lane ids: registry cron rows at stage canary whose lane is in the policy's family map (sorted; P1
    lanes after every other lane)."""
    p1 = set(world.policy.get("p1_last") or ())
    ids = [lid for lid, r in world.registry.items()
           if _sched(r).get("kind") == "cron" and _sched(r).get("stage") == "canary"]
    return sorted(ids, key=lambda x: (x in p1, x))


def check_cohort(world: World, lane: str, v: dict[str, Any]) -> Optional[str]:
    fam = (world.policy.get("families") or {}).get(lane)
    disp = world.disposition.get(lane) or {}
    v["family_id"] = fam
    if (world.policy.get("holds") or {}).get(lane):
        return "operator_hold:" + str(world.policy["holds"][lane]).split(":", 1)[0]
    if not fam:
        return "unknown_family: lane not in config/lane_cutover_policy.json families (fail closed)"
    if fam == "F07":
        return "excluded_F07: deferred by §23.25"
    if disp.get("source") == "registry_systemd":
        return "excluded_registry_systemd: deferred by §23.25"
    if not disp:
        return "not_in_disposition_scope: no MIGRATE_N8N/STAY_HOST row in LANE_DISPOSITION_20261015.csv"
    if disp.get("family_id") and disp.get("family_id") != fam:
        return f"family_disagrees: policy {fam} vs disposition {disp.get('family_id')}"
    row = world.registry[lane]
    s = _sched(row)
    if row.get("state") not in (None, "ACTIVE"):
        return f"registry_state_{row.get('state')}"
    if s.get("kind") != "cron" or s.get("stage") != "canary":
        return f"registry_not_cron_canary:{s.get('kind')}/{s.get('stage')}"
    if (row.get("dispatch") or {}).get("mode") != "live":
        return f"dispatch_mode_{(row.get('dispatch') or {}).get('mode')}: promote the row to dispatch.mode live first"
    return None


def retire_edits(world: World, lane: str, date_s: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    """The exact crontab edits for this lane (every live line its scheduler.match names), or a hold reason."""
    from scripts.lib import cutover_lane_facts as W

    lines, probs = W.live_lines(world.crontab, _sched(world.registry[lane]))
    tagged = [i + 1 for i, ln in enumerate(world.crontab.splitlines())
              if re.search(r"RETIRED\s+\d{4}-\d{2}-\d{2}\s+n8n-cutover\s+" + re.escape(lane) + r"\s", ln)]
    if tagged and not lines:
        return [], (f"already_retired_outside_controller: L{','.join(map(str, tagged))} carry the n8n-cutover tag; "
                    "registry row is still cron canary: flip it in a cutover-rows PR (n8n_cutover_wave.py cutover)")
    if probs:
        return [], "cron_line_" + probs[0].split(":", 1)[0] + ": " + "; ".join(probs)[:200]
    edits = [{"lane_id": lane, "index": i, "line": i + 1, "before": ln, "before_sha": sha256_text(ln),
              "after": W.TAG.format(date=date_s, lane=lane) + ln} for i, ln in lines]
    return edits, None


def _verdict(run: Mapping[str, Any]) -> str:
    return str(((run.get("receipt") or {}).get("output_verdict") or {}).get("verdict") or "absent")


def qualify_run(world: World, lane: str, run: Mapping[str, Any]) -> Optional[str]:
    """None when this live run is a qualifying proof on the CURRENT versions; otherwise why not."""
    rc = run.get("receipt") or {}
    if run.get("mode") != "live" or run.get("state") != "RUN_DONE" or run.get("exit_code") != 0:
        return f"not_live_done:{run.get('state')}/exit {run.get('exit_code')}"
    if rc.get("lock_skipped"):
        return "lock_skipped"
    if rc.get("run_id") not in (None, run.get("run_id")):
        return "receipt_not_this_attempt"
    clamp = rc.get("stage_clamp") or {}
    if clamp and clamp.get("effective_mode") != "live":
        return f"stage_clamped:{clamp.get('effective_mode')}"
    v = _verdict(run)
    if v not in VERDICTS_OK:
        return f"output_verdict_{v}"
    if str(rc.get("code_sha") or "")[:40] != world.current_sha:
        return f"proof_release_mismatch:{str(rc.get('code_sha') or '?')[:9]}!=CURRENT {world.current_sha[:9]}"
    pol = rc.get("policy") or {}
    if pol.get("allowlist_version") != world.allowlist_version:
        return f"allowlist_version_mismatch:{pol.get('allowlist_version')}!={world.allowlist_version}"
    if pol.get("expected_outputs_version") != world.contracts_version:
        return f"contract_version_mismatch:{pol.get('expected_outputs_version')}!={world.contracts_version}"
    wid = workflow_of(run)
    approved = set(world.config.get("approved_workflows") or []) | (
        {world.lane_workflows[lane]} if lane in world.lane_workflows else set())
    if wid is None and not str(run.get("run_id") or "").startswith("nc:"):
        return f"not_an_n8n_run:{run.get('requested_by')}"
    if wid is not None:
        if wid not in approved:
            return f"workflow_not_in_cohort:{wid}"
        if wid not in world.workflow_git:
            return f"workflow_not_in_git:{wid}"
        if world.workflow_live.get(wid) != world.workflow_git.get(wid):
            return f"workflow_graph_drift:{wid}"
    fin = _ts(run.get("finished_at"))
    max_age = timedelta(hours=float(world.config.get("proof_max_age_hours") or 72))
    if fin is None or world.now - fin > max_age:
        return f"proof_too_old:{run.get('finished_at')}"
    return None


def downstream_evidence(world: World, lane: str, run: Mapping[str, Any], sender: bool) -> Optional[str]:
    """None when the lane's downstream consumption/delivery is evidenced (or not applicable); else the reason."""
    spec = (world.config.get("downstream_evidence") or {}).get(lane)
    if spec is None:
        return "downstream_evidence_unconfigured: sender lane; declare downstream_evidence[<lane>] " \
               "(receipt_field or file_mtime_after) in config/nightly_cutover_controller.json" if sender else None
    kind = spec.get("kind")
    if kind == "receipt_field":
        cur: Any = run.get("receipt") or {}
        for part in str(spec.get("path") or "").split("."):
            cur = cur.get(part) if isinstance(cur, Mapping) else None
        return None if cur not in (None, 0, False, "", [], {}) else f"downstream_missing:receipt.{spec.get('path')}"
    if kind == "file_mtime_after":
        fin = _ts(run.get("finished_at"))
        mt = world.downstream_mtimes.get(str(spec.get("path")))
        if fin is None or mt is None or mt <= fin.timestamp():
            return f"downstream_missing:{spec.get('path')} not written after the run"
        return None
    return f"downstream_evidence_bad_kind:{kind}"


def check_evidence(world: World, lane: str, v: dict[str, Any], *, tier: int, sender: bool) -> Optional[str]:
    runs = [r for r in world.runs.get(lane) or [] if r.get("mode") == "live"]
    if not runs:
        return "no_live_n8n_run: needs a live n8n run (natural slot or forced canary)"
    fam = v.get("family_id")
    natural_only = set((world.config.get("forced_canary") or {}).get("natural_only_families") or ["F09"])
    why_not: list[str] = []
    best = None
    for r in reversed(runs):                     # newest first
        if fam in natural_only and not str(r.get("run_id") or "").startswith("d:"):
            why_not.append(f"{r.get('run_id')}:natural_slot_required_{fam}")
            continue
        why = qualify_run(world, lane, r)
        if why is None:
            best = r
            break
        why_not.append(f"{r.get('run_id')}:{why}")
    if best is None:
        return "no_qualifying_live_run: newest " + "; ".join(why_not[:2])
    v["proof_run"] = {"run_id": best.get("run_id"), "finished_at": best.get("finished_at"),
                      "verdict": _verdict(best), "workflow": workflow_of(best)}
    ds = downstream_evidence(world, lane, best, sender)
    if ds:
        return ds
    if lane in set(world.policy.get("p1_last") or ()):
        need = int(world.policy.get("cron_overlap_trading_days") or 1)
        window = timedelta(days=float(world.config.get("p1_proof_max_age_days") or 7))
        ok = [r for r in runs if r.get("state") == "RUN_DONE" and r.get("exit_code") == 0
              and _verdict(r) in VERDICTS_OK and (_ts(r.get("finished_at")) or world.now) >= world.now - window]
        failed = [r for r in runs if r.get("state") in FAILED_RUN_STATES]
        first = None
        for r in ok:                              # earliest valid proof with no failed live run after it
            t = _ts(r.get("finished_at"))
            if t and not any((_ts(f.get("finished_at") or f.get("requested_at")) or t) > t for f in failed):
                first = r
                break
        if first is None:
            return "p1_no_valid_proof_chain: a failed live run follows every valid proof in the window"
        got = completed_sessions_after(_ts(first.get("finished_at")), world.now)
        v["p1"] = {"proof": first.get("run_id"), "completed_sessions": got, "need": need}
        if got < need:
            return f"p1_session_pending: {got}/{need} completed NYSE session(s) after proof {first.get('finished_at')}"
    return None


def check_protected(world: World, lane: str, v: dict[str, Any], *, tier: int, retire_idx: list[int]) -> Optional[str]:
    entry = world.allowlist.get(lane)
    script = entry_script(entry)
    rest = remaining_triggers(world.crontab, lane, script, retire_idx)
    v["remaining_cron_triggers"] = [i + 1 for i, _ in rest]
    if tier < TIER_APPEND:
        return None
    spec = world.effect_lanes.get(lane)
    if spec is None or not spec.get("n8n_claim"):
        return "effect_key_not_armed_for_n8n: an append/send/LLM lane needs config/n8n_effect_keys.json n8n_claim true"
    owner = world.owners.get(spec["process"], "none")
    if owner != "n8n":
        return f"effect_owner_{owner}: effect_claim.py set-owner --process {spec['process']} --owner n8n first"
    for i, ln in rest:
        if not world.served_wrapper_ok:
            return f"served_wrapper_lacks_1016_semantics: L{i + 1} remains ({world.served_wrapper_why})"
        if not line_switched_on(ln, lane):
            return f"remaining_trigger_unprotected: L{i + 1} lacks `env TRADEAI_EFFECT_CLAIM={lane} bash " \
                   f"scripts/effect_claim_cron.sh {lane}`"
    return None


def check_drained(world: World, lane: str, v: dict[str, Any]) -> Optional[str]:
    timeout = float((world.allowlist.get(lane) or {}).get("timeout_s") or 0)
    for r in world.in_flight.get(lane) or []:
        started = _ts(r.get("started_at") or r.get("requested_at"))
        age = (world.now - started).total_seconds() if started else None
        if age is not None and timeout and age > timeout:
            return f"stale_in_flight_run:{r.get('run_id')} {r.get('state')} {int(age)}s > timeout {int(timeout)}s " \
                   "(reap it: the executor's executor_lost finish)"
        return f"in_flight_run:{r.get('run_id')} {r.get('state')}"
    spec = world.effect_lanes.get(lane)
    if spec is not None:
        amb = world.ambiguous_claims.get(spec["process"]) or []
        if amb:
            k, st = amb[0]
            return f"ambiguous_effect:{k} {st} (never auto-released; reconcile by hand)"
    return None


def evaluate(world: World, *, date_s: Optional[str] = None) -> dict[str, Any]:
    """The plan: one verdict per cohort lane. Pure."""
    from scripts.lib import cutover_lane_facts as W

    date_s = date_s or world.now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    lanes_out: list[dict[str, Any]] = []
    ready: list[dict[str, Any]] = []
    used_lines: dict[int, str] = {}
    for lane in cohort(world):
        v: dict[str, Any] = {"lane_id": lane, "state": None, "status": None, "held": None}
        lanes_out.append(v)
        why = check_cohort(world, lane, v)
        if why:
            _hold(v, why)
            continue
        edits, why = retire_edits(world, lane, date_s)
        if why:
            _hold(v, why)
            continue
        clash = [e["line"] for e in edits if e["index"] in used_lines]
        if clash:
            _hold(v, f"cron_line_shared_with:{used_lines[edits[0]['index']]}")
            continue
        v["edits"] = edits
        v["state"] = "candidate"
        row, entry = world.registry[lane], world.allowlist.get(lane)
        if entry is None or entry.get("live_arg") is None:
            _hold(v, "allowlist_no_live_arg: the lane has no live argv in config/n8n_run_allowlist.json")
            continue
        root_row = world.registry_root_rows.get(lane)
        if root_row != row:
            _hold(v, "registry_root_row_differs_from_served: reconcile the registry root with CURRENT first")
            continue
        if lane not in world.relay_live:
            _hold(v, "not_relay_live: add the lane to TRADEAI_N8N_RELAY_LIVE_LANES (n8n live fires are refused)")
            continue
        c = world.contracts.get(lane)
        if not c or c.get("status") != "REVIEWED" or c.get("stage") != "canary":
            _hold(v, f"contract_disagrees_with_registry: health contract {(c or {}).get('status')}/stage "
                     f"{(c or {}).get('stage')} vs registry canary; promote the REVIEWED contract to canary first")
            continue
        disp = dict(world.disposition.get(lane) or {})
        line_text = " ".join(e["before"] for e in edits)
        tier = W.tier_of(disp, row, entry, world.effect_raw, line_text)
        sender = W.is_sender_lane(disp, row, world.effect_raw, line_text)
        v["tier"], v["sender"] = tier, sender
        why = check_evidence(world, lane, v, tier=tier, sender=sender)
        if why:
            _hold(v, why)
            continue
        v["state"] = "evidence_ok"
        why = check_protected(world, lane, v, tier=tier, retire_idx=[e["index"] for e in edits])
        if why:
            _hold(v, why)
            continue
        v["state"] = "protected"
        why = check_drained(world, lane, v)
        if why:
            _hold(v, why)
            continue
        v["state"] = "drained"
        v["status"] = "ready"
        for e in edits:
            used_lines[e["index"]] = lane
        ready.append(v)
    cap = int(world.config.get("max_lanes_per_night") or 0)
    for v in ready[cap:]:
        _hold(v, f"nightly_cap_reached: max_lanes_per_night={cap}")
    counts: dict[str, int] = {}
    for v in lanes_out:
        k = "ready" if v["status"] == "ready" else "held"
        counts[k] = counts.get(k, 0) + 1
    return {"schema": PLAN_SCHEMA, "evaluated_at": world.now.isoformat(), "current_sha": world.current_sha,
            "crontab_sha": world.crontab_sha, "allowlist_version": world.allowlist_version,
            "contracts_version": world.contracts_version, "date": date_s, "cap": cap,
            "counts": counts, "lanes": lanes_out}


# ── read-only gathering ────────────────────────────────────────────────────────────────────────────────────────────

def _read_json(p: Path, what: str) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CohortStop(f"{what}_unreadable:{type(exc).__name__}") from exc


def resolve_current(current_link: Path) -> tuple[Path, str]:
    try:
        root = Path(current_link).resolve(strict=True)
        sha = (root / "GIT_SHA").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CohortStop(f"current_unresolvable:{type(exc).__name__}") from exc
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise CohortStop("current_unresolvable:GIT_SHA")
    return root, sha


def load_relay_live(path: Path) -> frozenset:
    """Lane names from TRADEAI_N8N_RELAY_LIVE_LANES= (the only key read; lane ids, not secrets). Missing -> empty."""
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.startswith("TRADEAI_N8N_RELAY_LIVE_LANES="):
                return frozenset(line.split("=", 1)[1].strip().strip('"').split())
    except OSError:
        pass
    return frozenset()


def read_ledger(ledger: Path, lanes: list[str], processes: list[str], since: datetime
                ) -> tuple[dict[str, list], dict[str, list], dict[str, str], dict[str, list]]:
    """(runs, in_flight, owners, ambiguous_claims) from the coordination ledger, opened mode=ro. Any failure ->
    CohortStop("ledger_unreadable")."""
    try:
        if not Path(ledger).exists():
            raise sqlite3.OperationalError("ledger_missing")
        c = sqlite3.connect(f"{Path(ledger).resolve().as_uri()}?mode=ro", uri=True, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            runs: dict[str, list] = {}
            fl: dict[str, list] = {}
            for lane in lanes:
                rows = c.execute(
                    "SELECT run_id, lane_id, mode, state, requested_by, requested_at, started_at, finished_at, "
                    "exit_code, receipt_json FROM runs WHERE lane_id=? AND (requested_at>=? OR state IN "
                    "('REQUESTED','RUNNING','QUEUED','CLAIMED','STARTED')) ORDER BY requested_at",
                    (lane, since.isoformat())).fetchall()
                for r in rows:
                    d = {k: r[k] for k in r.keys() if k != "receipt_json"}
                    try:
                        d["receipt"] = json.loads(r["receipt_json"] or "{}")
                    except ValueError:
                        d["receipt"] = {}
                    (fl if d["state"] in IN_FLIGHT_STATES else runs).setdefault(lane, []).append(d)
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            owners: dict[str, str] = {}
            amb: dict[str, list] = {}
            if "effect_owners" in tables:
                for r in c.execute("SELECT process, owner FROM effect_owners"):
                    owners[r[0]] = r[1]
            if "effect_claims" in tables and processes:
                q = ",".join("?" * len(processes))
                for r in c.execute(f"SELECT effect_key, process, state FROM effect_claims WHERE process IN ({q}) "
                                   "AND state IN ('CLAIMED','UNKNOWN') ORDER BY claimed_at", processes):
                    amb.setdefault(r[1], []).append((r[0], r[2]))
        finally:
            c.close()
    except sqlite3.Error as exc:
        raise CohortStop(f"ledger_unreadable:{exc}") from exc
    return runs, fl, owners, amb


def gather_world(*, served_root: Path, current_sha: str, registry_root: Path, crontab: str, ledger: Path,
                 relay_live_path: Path, config: Mapping[str, Any], now: datetime,
                 workflow_reader: Callable[[], list[dict]], state_root: Optional[Path] = None,
                 policy_path: Optional[Path] = None) -> World:
    """Read-only snapshot. Everything config-shaped comes from the SERVED release (what actually runs)."""
    from scripts.lib import cutover_lane_facts as W
    from scripts.lib import lane_dispatch as LD
    from scripts.lib.effect_claim import EffectKeyError, load_effect_lanes

    reg = _read_json(served_root / "config/lane_registry.json", "registry")
    registry = {r["lane_id"]: r for r in reg.get("lanes") or [] if isinstance(r, dict) and r.get("lane_id")}
    root_reg = _read_json(registry_root / "config/lane_registry.json", "registry_root")
    root_rows = {r["lane_id"]: r for r in root_reg.get("lanes") or [] if isinstance(r, dict) and r.get("lane_id")}
    try:
        al_raw = (served_root / "config/n8n_run_allowlist.json").read_bytes()
        c_raw = (served_root / "config/n8n_health_contracts.json").read_bytes()
        al, cdoc = json.loads(al_raw), json.loads(c_raw)
    except (OSError, ValueError) as exc:
        raise CohortStop(f"allowlist_or_contracts_unreadable:{type(exc).__name__}") from exc
    allowlist = {e["lane_id"]: e for e in al.get("lanes") or [] if isinstance(e, dict) and e.get("lane_id")}
    contracts = {c["id"]: c for c in cdoc.get("contracts") or [] if isinstance(c, dict) and c.get("kind") == "lane"}
    fx_path = served_root / "config/n8n_effect_keys.json"
    try:
        effect_lanes = load_effect_lanes(fx_path)
    except EffectKeyError as exc:
        raise CohortStop("effect_config_unreadable") from exc
    effect_raw = (_read_json(fx_path, "effect_config").get("lanes") or {}) if fx_path.exists() else {}
    policy = LD.load_cutover_policy(policy_path or (served_root / "config/lane_cutover_policy.json"))
    if not policy.get("families"):
        raise CohortStop("cutover_policy_unreadable: served release has no config/lane_cutover_policy.json families")
    disp = {r["lane_id"]: r for r in W.scope_rows(W.load_disposition(served_root))}
    for row in W.load_disposition(served_root):        # keep registry_systemd/F07 rows visible to the cohort check
        disp.setdefault(row.get("lane_id") or "", row)
    p1 = set(policy.get("p1_last") or ())
    lanes = [lid for lid, r in registry.items() if _sched(r).get("kind") == "cron" and _sched(r).get("stage") == "canary"]
    procs = sorted({effect_lanes[lid]["process"] for lid in lanes if lid in effect_lanes})
    since = now - timedelta(days=max(float(config.get("p1_proof_max_age_days") or 7),
                                     float(config.get("proof_max_age_hours") or 72) / 24.0) + 1)
    runs, fl, owners, amb = read_ledger(ledger, lanes, procs, since)
    wrapper = served_root / WRAPPER_REL
    try:
        wtext = wrapper.read_text(encoding="utf-8")
        missing = [m for m in WRAPPER_MARKERS if m not in wtext]
        wok, wwhy = (not missing), ("ok" if not missing else "missing " + ",".join(missing))
    except OSError:
        wok, wwhy = False, "wrapper file missing in CURRENT"
    try:
        live = {str(w.get("id")): graph_hash(w) for w in workflow_reader() if w.get("active")}
    except Exception as exc:  # noqa: BLE001 - any inventory failure is a shared control failure
        raise CohortStop(f"n8n_workflow_inventory_unreadable:{type(exc).__name__}") from exc
    from scripts import check_n8n_workflow_drift as drift
    try:
        git = drift.git_reviewed_set(served_root / "docs/implementation/n8n-parallel/workflows/generated",
                                     served_root / "docs/implementation/n8n-maturity/workflows")
    except (OSError, ValueError) as exc:
        raise CohortStop(f"n8n_git_workflows_unreadable:{exc}") from exc
    git_h = {wid: graph_hash(doc) for wid, (_, doc) in git.items()}
    lane_wf: dict[str, str] = {}
    idx = served_root / "docs/implementation/n8n-parallel/workflows/generated/INDEX.json"
    if idx.exists():
        for e in (_read_json(idx, "workflow_index").get("lanes") or []):
            if isinstance(e, dict) and e.get("lane_id") and e.get("live_workflow_id"):
                lane_wf[e["lane_id"]] = e["live_workflow_id"]
    del p1
    mtimes: dict[str, float] = {}
    for spec in (config.get("downstream_evidence") or {}).values():
        if isinstance(spec, Mapping) and spec.get("kind") == "file_mtime_after" and state_root is not None:
            try:
                mtimes[str(spec.get("path"))] = (Path(state_root) / str(spec.get("path"))).stat().st_mtime
            except OSError:
                pass
    return World(now=now, config=config, policy=policy, disposition=disp, current_sha=current_sha,
                 registry=registry, registry_root_rows=root_rows, allowlist=allowlist,
                 allowlist_version=sha16(al_raw), contracts=contracts, contracts_version=sha16(c_raw),
                 effect_raw=effect_raw, effect_lanes=effect_lanes, relay_live=load_relay_live(relay_live_path),
                 crontab=crontab, runs=runs, in_flight=fl, owners=owners, ambiguous_claims=amb,
                 served_wrapper_ok=wok, served_wrapper_why=wwhy, workflow_live=live, workflow_git=git_h,
                 lane_workflows=lane_wf, downstream_mtimes=mtimes)


# ── registry reconciliation (apply; writes only the registry root) ─────────────────────────────────────────────────

def _serialise(doc: Any, ensure_ascii: bool) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=ensure_ascii) + "\n"


def _load_exact(path: Path) -> tuple[Any, str, bool]:
    raw = path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    for ea in (False, True):
        if _serialise(doc, ea) == raw:
            return doc, raw, ea
    raise CohortStop(f"registry_write_failure:{path.name} serialisation would churn other lines")


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".nightly-tmp")
    tmp.write_text(text, encoding="utf-8")
    import os
    os.replace(tmp, path)


def dispatcher_row(row: Mapping[str, Any], wave: str) -> dict[str, Any]:
    """The §23.11 dispatcher row (scripts/n8n_cutover_wave.cutover_rows semantics)."""
    from scripts.lib import lane_dispatch as LD

    new = json.loads(json.dumps(row))
    sched = dict(_sched(row))
    slots = list((row.get("dispatch") or {}).get("cron") or [])
    s2 = {"kind": "n8n", "expression": LD.DISPATCHER_EXPRESSION, "match": sched.get("match"),
          "cadence": slots[0] if slots else sched.get("expression"), "stage": "cutover",
          "wave": sched.get("wave"), "cutover_wave": wave, "command_text": sched.get("command_text")}
    if len(slots) > 1:
        s2["cadence_slots"] = slots
    new["scheduler_before_cutover"] = sched
    new["scheduler"] = {k: v for k, v in s2.items() if v is not None}
    return new


def cutover_contract(contract: Mapping[str, Any], wave: str) -> dict[str, Any]:
    """Health contract -> stage cutover; the canary binding that counted a cron-twin lock skip as healthy is
    superseded (after the retire a lock skip means a stray trigger, not the twin)."""
    new = json.loads(json.dumps(contract))
    new["stage"] = "cutover"
    healthy = []
    for h in new.get("healthy") or []:
        if h.get("check") == "canary_live_done":
            h = {"check": "canary_live_done",
                 "text": "every dispatcher fire of this lane ends RUN_DONE in mode live (cron line retired: a "
                         "RUN_SKIPPED_LOCK is a stray trigger, not the cron twin)"}
        healthy.append(h)
    new["healthy"] = healthy
    note = f"{wave}: stage cutover (nightly-cutover-controller); cron line retired"
    new["state_note"] = (str(new.get("state_note") or "") + " | " + note).lstrip(" |")
    return new


def reconcile_registry(registry_root: Path, lane: str, wave: str, expect_row: Mapping[str, Any]
                       ) -> dict[str, Any]:
    """Flip the lane's registry row and health contract in the registry root. Returns the before/after (for the
    rollback receipt). Any failure -> CohortStop("registry_write_failure:...")."""
    reg_p = registry_root / "config/lane_registry.json"
    con_p = registry_root / "config/n8n_health_contracts.json"
    try:
        reg, reg_raw, reg_ea = _load_exact(reg_p)
        con, con_raw, con_ea = _load_exact(con_p)
        idx = next((i for i, r in enumerate(reg["lanes"]) if isinstance(r, dict) and r.get("lane_id") == lane), None)
        if idx is None or reg["lanes"][idx] != expect_row:
            raise CohortStop(f"registry_write_failure:{lane} row changed since evaluation")
        before_row = reg["lanes"][idx]
        reg["lanes"][idx] = dispatcher_row(before_row, wave)
        cidx = next((i for i, c in enumerate(con["contracts"]) if isinstance(c, dict) and c.get("kind") == "lane"
                     and c.get("id") == lane), None)
        before_c = con["contracts"][cidx] if cidx is not None else None
        if cidx is not None:
            con["contracts"][cidx] = cutover_contract(before_c, wave)
        _write_atomic(reg_p, _serialise(reg, reg_ea))
        if cidx is not None:
            _write_atomic(con_p, _serialise(con, con_ea))
        back = json.loads(reg_p.read_text(encoding="utf-8"))
        if back["lanes"][idx] != reg["lanes"][idx]:
            raise CohortStop(f"registry_write_failure:{lane} read-back differs")
    except CohortStop:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CohortStop(f"registry_write_failure:{type(exc).__name__}:{exc}") from exc
    return {"registry_path": str(reg_p), "contracts_path": str(con_p), "row_before": before_row,
            "row_after": reg["lanes"][idx], "contract_before": before_c,
            "contract_after": con["contracts"][cidx] if cidx is not None else None,
            "registry_sha_before": sha256_text(reg_raw), "contracts_sha_before": sha256_text(con_raw)}


def restore_registry(registry_root: Path, lane: str, rec: Mapping[str, Any]) -> list[str]:
    """Put the lane's row and contract back to the receipt's before-images (only if they still equal the after)."""
    problems = []
    for rel, key, coll, idk, before, after in (
            ("config/lane_registry.json", "lane_id", "lanes", lane, rec.get("row_before"), rec.get("row_after")),
            ("config/n8n_health_contracts.json", "id", "contracts", lane, rec.get("contract_before"),
             rec.get("contract_after"))):
        if before is None:
            continue
        p = registry_root / rel
        try:
            doc, _, ea = _load_exact(p)
            i = next((i for i, r in enumerate(doc[coll]) if isinstance(r, dict) and r.get(key) == idk), None)
            if i is None or doc[coll][i] != after:
                problems.append(f"{rel}: {lane} changed since the cutover; not restored")
                continue
            doc[coll][i] = before
            _write_atomic(p, _serialise(doc, ea))
        except (OSError, ValueError, CohortStop) as exc:
            problems.append(f"{rel}: {exc}")
    return problems
