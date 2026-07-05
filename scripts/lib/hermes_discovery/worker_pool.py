"""White-Space Discovery — bounded research worker pool (spec Part E).

Runs the worker lanes defined in config/hermes_research_worker_lanes.yaml
under a bounded ThreadPoolExecutor (never more than MAX_WORKERS=4 threads),
with per-lane:

  * flock-style lock file        two runs of the same lane never overlap
  * cadence gate                 state-file enforced minimum minutes between
                                 live runs (dry runs always allowed)
  * wall-clock timeout           an overrunning runner is abandoned + reported
  * max_candidates_per_run cap   payload truncation, counted per lane
  * domain fences                allowed_domains / blocked_domains per lane
  * citation gate                requires_citations lanes drop evidence-less payloads
  * do-no-harm gate REUSE        the exact make_intake_gate/effective_caps
                                 machinery from hermes_discovery_ingestors.py
                                 (schedule caps + scorecard pause/tighten)

Lanes only ever write DISCOVERY CANDIDATES via inbox.upsert_candidate — never
watchlists, directives, proposals, or producer tables. Candidate promotion is
structurally impossible here: lane configs are validated fail-closed
(promotion_allowed must be false, promotion_requires_operator must be true,
do_no_harm_policy must be 'respect') and the pool exposes no promotion API.

Lane-registration API (Stages 2-4 register their runners):

    from lib.hermes_discovery import worker_pool
    worker_pool.register_lane_runner("strategy", my_runner)

    def my_runner(lane_cfg: dict, *, dry_run: bool) -> list[dict]:
        '''Return inbox.upsert_candidate payload dicts:
        {candidate_type, label, summary?, evidence?, seed_symbols?, meta?, ...}
        Runners NEVER write anything themselves.'''

Stage 1 ships runners for the holdings + watchlist lanes, wired to the
existing coverage adapters (lib/hermes_discovery/coverage.py). Lanes without
a registered runner are reported skipped ("no_runner") — never an error.

Every live lane run appends a WORKER_LANE_RUN row to hermes_discovery_audit.
Dry runs write NOTHING (no candidates, no audit, no state).

Advisory-only: never imports broker/execution modules.
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import coverage, domains

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LANES_PATH = Path(os.getenv("HERMES_WORKER_LANES_YAML")
                  or PROJECT_ROOT / "config" / "hermes_research_worker_lanes.yaml")
LOCK_DIR = Path(os.getenv("HERMES_WORKER_LOCK_DIR")
                or PROJECT_ROOT / "data" / "runtime" / "hermes_worker_locks")
STATE_PATH = Path(os.getenv("HERMES_WORKER_STATE_JSON")
                  or PROJECT_ROOT / "data" / "runtime"
                  / "hermes_worker_pool_state.json")

MAX_WORKERS = 4  # hard pool bound — never exceeded regardless of arguments

LANE_IDS = ("holdings", "watchlist", "white_space", "strategy", "private_proxy",
            "legal_domain", "tax_retirement", "system_ops", "custom_domain")

# Hard rules a lane config can NEVER override (validated fail-closed).
_HARD_RULES = {
    "promotion_allowed": False,
    "promotion_requires_operator": True,
    "requires_operator_review": True,
}
_DO_NO_HARM_POLICY = "respect"

_INT_FIELDS = ("cadence_minutes", "max_candidates_per_run",
               "max_llm_reviews_per_run", "timeout_seconds")
_BOOL_FIELDS = ("enabled", "sensitive_domain", "requires_citations",
                "requires_operator_review", "cloud_allowed", "local_llm_allowed",
                "promotion_allowed", "promotion_requires_operator")


class LaneConfigError(Exception):
    """Raised when the lane registry fails validation (fail closed)."""


class LaneRunnerError(Exception):
    """Raised on lane-runner registration problems."""


_lanes_cache: dict[str, dict[str, Any]] | None = None
_RUNNERS: dict[str, Callable[..., list[dict[str, Any]]]] = {}


# ── lane config: load + validate (fail closed) ───────────────────────────────

def _validate_lane(lane_id: str, spec: dict[str, Any],
                   defaults: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise LaneConfigError(f"lane {lane_id!r} must be a mapping")
    merged: dict[str, Any] = dict(defaults)
    merged.update(spec)

    lane: dict[str, Any] = {"lane_id": lane_id,
                            "description": str(merged.get("description") or "").strip()}
    for key in _BOOL_FIELDS:
        val = merged.get(key)
        if not isinstance(val, bool):
            raise LaneConfigError(f"lane {lane_id!r}: {key} must be a boolean "
                                  f"(got {val!r})")
        lane[key] = val
    for key in _INT_FIELDS:
        try:
            lane[key] = int(merged.get(key))
        except (TypeError, ValueError):
            raise LaneConfigError(f"lane {lane_id!r}: {key} must be an integer "
                                  f"(got {merged.get(key)!r})")
        if lane[key] <= 0:
            raise LaneConfigError(f"lane {lane_id!r}: {key} must be > 0")
    for key in ("allowed_domains", "blocked_domains"):
        raw = merged.get(key) or []
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise LaneConfigError(f"lane {lane_id!r}: {key} must be a list of strings")
        lane[key] = [x.strip().lower() for x in raw if x.strip()]

    # HARD RULES — a yaml edit can never open promotion or drop operator review
    for key, required in _HARD_RULES.items():
        if lane[key] is not required:
            raise LaneConfigError(
                f"lane {lane_id!r}: {key} must be {required} (hard rule)")
    policy = str(merged.get("do_no_harm_policy") or "").strip().lower()
    if policy != _DO_NO_HARM_POLICY:
        raise LaneConfigError(
            f"lane {lane_id!r}: do_no_harm_policy must be "
            f"{_DO_NO_HARM_POLICY!r} (hard rule), got {policy!r}")
    lane["do_no_harm_policy"] = policy
    return lane


def load_lanes(path: Path | str | None = None,
               force_reload: bool = False) -> dict[str, dict[str, Any]]:
    """Load + validate config/hermes_research_worker_lanes.yaml.

    Any validation failure raises LaneConfigError — the pool fails closed
    rather than running against a mis-declared lane. Cached for the default
    path; explicit paths (tests) always load fresh.
    """
    global _lanes_cache
    default_path = path is None
    if default_path and _lanes_cache is not None and not force_reload:
        return _lanes_cache

    p = Path(path) if path else LANES_PATH
    if not p.exists():
        raise LaneConfigError(f"worker lane registry missing: {p}")
    import yaml
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise LaneConfigError(f"unparseable lane yaml {p}: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("lanes"), dict) \
            or not data["lanes"]:
        raise LaneConfigError(f"lane yaml {p} must define a non-empty 'lanes' mapping")

    defaults = data.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise LaneConfigError(f"lane yaml {p}: 'defaults' must be a mapping")

    lanes = {str(lane_id).strip().lower():
             _validate_lane(str(lane_id).strip().lower(), spec, defaults)
             for lane_id, spec in data["lanes"].items()}
    if default_path:
        _lanes_cache = lanes
    return lanes


# ── lane-runner registry (Stages 2-4 hook in here) ───────────────────────────

def register_lane_runner(lane_id: str,
                         runner: Callable[..., list[dict[str, Any]]],
                         *, replace: bool = False) -> None:
    """Register the callable that produces a lane's candidate payloads.

    Contract: runner(lane_cfg: dict, *, dry_run: bool) -> list of
    inbox.upsert_candidate payload dicts. Runners must be read-only — the
    pool owns all writes (candidates-only, via the gated upsert loop).
    """
    key = str(lane_id or "").strip().lower()
    if not key:
        raise LaneRunnerError("lane_id is required")
    if not callable(runner):
        raise LaneRunnerError(f"runner for lane {key!r} must be callable")
    if key in _RUNNERS and not replace:
        raise LaneRunnerError(f"lane {key!r} already has a runner "
                              f"(pass replace=True to override)")
    _RUNNERS[key] = runner


def get_lane_runner(lane_id: str) -> Callable[..., list[dict[str, Any]]] | None:
    return _RUNNERS.get(str(lane_id or "").strip().lower())


def registered_lanes() -> list[str]:
    return sorted(_RUNNERS)


def _holdings_runner(lane_cfg: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """Stage-1 holdings lane → existing coverage adapter (read-only)."""
    return coverage.holdings_findings()


def _watchlist_runner(lane_cfg: dict[str, Any], *, dry_run: bool) -> list[dict[str, Any]]:
    """Stage-1 watchlist lane → existing coverage adapter (read-only)."""
    return coverage.watchlist_findings()


register_lane_runner("holdings", _holdings_runner, replace=True)
register_lane_runner("watchlist", _watchlist_runner, replace=True)


# ── per-lane lock + cadence state ────────────────────────────────────────────

class _LaneLock:
    """flock-style non-blocking per-lane lock file."""

    def __init__(self, lane_id: str, lock_dir: Path | None = None):
        self.path = (lock_dir or LOCK_DIR) / f"{lane_id}.lock"
        self._fh = None

    def acquire(self) -> bool:
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._fh.close()
            self._fh = None
            return False

    def release(self) -> None:
        if self._fh is not None:
            import fcntl
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


_state_lock = threading.Lock()


def _load_state(state_path: Path | None = None) -> dict[str, Any]:
    p = state_path or STATE_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _mark_lane_run(lane_id: str, state_path: Path | None = None) -> None:
    p = state_path or STATE_PATH
    with _state_lock:
        state = _load_state(p)
        state.setdefault("lanes", {})[lane_id] = {
            "last_run_at": datetime.now(timezone.utc).isoformat()}
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _cadence_due(lane_id: str, cadence_minutes: int,
                 state_path: Path | None = None) -> bool:
    last = (((_load_state(state_path).get("lanes") or {}).get(lane_id) or {})
            .get("last_run_at"))
    if not last:
        return True
    try:
        ts = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
    return age_min >= float(cadence_minutes)


# ── lane gate: domain fences + citations, composed over the shared gate ──────

def _payload_domain(payload: dict[str, Any]) -> str:
    meta = payload.get("meta") or {}
    pinned = str(meta.get("research_domain") or "").strip().lower()
    if pinned:
        return pinned
    return domains.classify_domain({
        "candidate_type": payload.get("candidate_type"),
        "label": payload.get("label"), "summary": payload.get("summary"),
        "meta": meta, "evidence": payload.get("evidence") or [],
    })


def _has_citation(payload: dict[str, Any]) -> bool:
    for item in (payload.get("evidence") or []):
        if isinstance(item, dict) and (item.get("url") or item.get("source_domain")):
            return True
    return bool(payload.get("source_url"))


def _make_lane_gate(lane: dict[str, Any],
                    shared_gate: Callable[[dict], tuple[bool, str | None]] | None,
                    skipped: dict[str, int],
                    ) -> Callable[[dict], tuple[bool, str | None]]:
    """Compose lane fences over the shared do-no-harm intake gate."""
    allowed = set(lane["allowed_domains"])
    blocked = set(lane["blocked_domains"])

    def _deny(reason: str) -> tuple[bool, str]:
        skipped[reason] = skipped.get(reason, 0) + 1
        return False, reason

    def gate(payload: dict[str, Any]) -> tuple[bool, str | None]:
        try:
            domain = _payload_domain(payload)
        except Exception:
            return _deny("domain_classification_failed")
        if domain in blocked:
            return _deny(f"lane_domain_blocked:{domain}")
        if allowed and domain not in allowed:
            return _deny(f"lane_domain_not_allowed:{domain}")
        if lane["requires_citations"] and not _has_citation(payload):
            return _deny("missing_citation")
        if shared_gate is not None:
            ok, reason = shared_gate(payload)
            if not ok:
                skipped[reason or "gated"] = skipped.get(reason or "gated", 0) + 1
                return False, reason
        return True, None

    return gate


# ── single-lane run ──────────────────────────────────────────────────────────

def run_lane(lane_id: str, *, dry_run: bool = False, force: bool = False,
             lanes: dict[str, dict[str, Any]] | None = None,
             shared_gate: Callable[[dict], tuple[bool, str | None]] | None = None,
             lock_dir: Path | None = None,
             state_path: Path | None = None) -> dict[str, Any]:
    """Run one lane end-to-end: lock → cadence → runner (timeout) → cap →
    lane+do-no-harm gates → candidates-only upsert → audit. Returns the
    per-lane report; never raises for a lane-local failure."""
    lane_id = str(lane_id or "").strip().lower()
    all_lanes = lanes if lanes is not None else load_lanes()
    report: dict[str, Any] = {"lane": lane_id, "dry_run": bool(dry_run),
                              "scanned": 0, "upserted": 0,
                              "skipped_payloads": 0, "skipped_reasons": {},
                              "candidates": []}
    lane = all_lanes.get(lane_id)
    if lane is None:
        report["error"] = f"unknown lane {lane_id!r}"
        return report
    report["llm_reviews"] = {"cap": lane["max_llm_reviews_per_run"], "used": 0}

    if not lane["enabled"]:
        report["skipped"] = "disabled"
        return report
    if not dry_run and not force and not _cadence_due(
            lane_id, lane["cadence_minutes"], state_path):
        report["skipped"] = "cadence"
        return report

    runner = get_lane_runner(lane_id)
    if runner is None:
        report["skipped"] = "no_runner"
        return report

    lock = _LaneLock(lane_id, lock_dir)
    if not lock.acquire():
        report["skipped"] = "locked"
        return report

    started = time.monotonic()
    try:
        # runner under a wall-clock budget; an overrun is abandoned + reported
        pool = ThreadPoolExecutor(max_workers=1,
                                  thread_name_prefix=f"lane-{lane_id}")
        try:
            future = pool.submit(runner, dict(lane), dry_run=dry_run)
            payloads = future.result(timeout=lane["timeout_seconds"])
        except FutureTimeoutError:
            report["error"] = f"timeout after {lane['timeout_seconds']}s"
            return report
        except Exception as e:
            report["error"] = f"runner failed: {e}"[:300]
            return report
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        payloads = list(payloads or [])
        report["scanned"] = len(payloads)
        cap = lane["max_candidates_per_run"]
        if len(payloads) > cap:
            report["skipped_reasons"]["lane_run_cap"] = len(payloads) - cap
            report["skipped_payloads"] += len(payloads) - cap
            payloads = payloads[:cap]

        skipped: dict[str, int] = report["skipped_reasons"]
        gate = _make_lane_gate(lane, shared_gate, skipped)
        from hermes_discovery_ingestors import _upsert_all  # lazy: scripts/ on sys.path
        res = _upsert_all(payloads, actor=f"worker:{lane_id}",
                          dry_run=dry_run, gate=gate)
        report["upserted"] = res.get("upserted", 0)
        report["skipped_payloads"] += res.get("skipped", 0)
        report["candidates"] = [
            {k: c.get(k) for k in ("candidate_type", "label", "id", "status",
                                   "seen_count") if c.get(k) is not None}
            for c in (res.get("candidates") or [])[:10]]

        if not dry_run:
            _mark_lane_run(lane_id, state_path)
            try:  # audit trail: one WORKER_LANE_RUN row per live run
                from . import inbox
                inbox._audit(None, "WORKER_LANE_RUN", f"worker:{lane_id}", None,
                             {"lane": lane_id, "scanned": report["scanned"],
                              "upserted": report["upserted"],
                              "skipped_payloads": report["skipped_payloads"],
                              "skipped_reasons": report["skipped_reasons"]},
                             f"worker pool lane run ({lane_id})")
            except Exception as e:
                report["audit_error"] = str(e)[:200]
        return report
    finally:
        report["duration_ms"] = int((time.monotonic() - started) * 1000)
        lock.release()


# ── the pool ─────────────────────────────────────────────────────────────────

def run_pool(lane_ids: list[str] | None = None, *, dry_run: bool = False,
             force: bool = False, max_workers: int | None = None,
             lanes_path: Path | str | None = None,
             config_path: Path | str | None = None,
             scorecard_path: Path | str | None = None,
             lock_dir: Path | None = None,
             state_path: Path | None = None) -> dict[str, Any]:
    """Run the selected lanes (default: all) on a bounded thread pool.

    Reuses the scheduled-intake machinery for caps + do-no-harm: schedule
    config, scorecard recommendation, effective_caps, make_intake_gate —
    exactly the gate the coverage adapters run under. Broken lane/schedule
    config fails closed (report error, zero writes). Returns
    {mode, generated_at, dry_run, do_no_harm, caps_applied, lanes: {...},
    skipped_reasons}.
    """
    report: dict[str, Any] = {
        "mode": "worker_pool",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": bool(dry_run),
        "do_no_harm": None,
        "caps_applied": {},
        "max_workers": min(int(max_workers or MAX_WORKERS), MAX_WORKERS),
        "lanes": {},
        "skipped_reasons": {},
    }
    try:
        all_lanes = load_lanes(lanes_path)
    except LaneConfigError as e:
        report["error"] = f"lane config load failed: {e}"[:300]
        return report

    selected = [str(x).strip().lower() for x in (lane_ids or list(all_lanes))]
    unknown = [x for x in selected if x not in all_lanes]
    if unknown:
        report["error"] = f"unknown lane(s): {unknown}"
        return report

    # do-no-harm + caps: the SAME machinery as scheduled/coverage intake
    try:
        from hermes_discovery_ingestors import (  # lazy: scripts/ on sys.path
            _domain_counts_today, effective_caps, load_schedule_config,
            load_scorecard_do_no_harm, make_intake_gate)
        cfg = load_schedule_config(config_path)
        dnh = (load_scorecard_do_no_harm(scorecard_path)
               if cfg.get("do_no_harm_pause_respected", True) else "steady")
        caps = effective_caps(cfg, dnh)
    except Exception as e:  # broken schedule config → fail closed, no writes
        report["error"] = f"schedule config load failed: {e}"[:300]
        return report
    report["do_no_harm"] = dnh
    report["caps_applied"] = caps

    if caps.get("paused"):
        # every lane declares do_no_harm_policy: respect (validated) — a pause
        # quietly skips all lane intake, exactly like scheduled ingestion.
        for lane_id in selected:
            report["lanes"][lane_id] = {"lane": lane_id, "skipped": "paused"}
        report["skipped_reasons"] = {"paused": len(selected)}
        return report

    shared_skipped: dict[str, int] = {}
    raw_gate = make_intake_gate(caps, _domain_counts_today(), shared_skipped)
    gate_mutex = threading.Lock()

    def shared_gate(payload: dict[str, Any]) -> tuple[bool, str | None]:
        with gate_mutex:  # the gate mutates counters; lanes run concurrently
            return raw_gate(payload)

    workers = report["max_workers"]
    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix="hermes-worker") as pool:
        futures = {
            lane_id: pool.submit(run_lane, lane_id, dry_run=dry_run, force=force,
                                 lanes=all_lanes, shared_gate=shared_gate,
                                 lock_dir=lock_dir, state_path=state_path)
            for lane_id in selected}
        for lane_id, future in futures.items():
            try:
                report["lanes"][lane_id] = future.result()
            except Exception as e:  # one broken lane never blocks the others
                report["lanes"][lane_id] = {"lane": lane_id,
                                            "error": str(e)[:200]}
    report["skipped_reasons"] = shared_skipped
    return report


# test/support hook
def _reset_lanes_cache() -> None:
    global _lanes_cache
    _lanes_cache = None
