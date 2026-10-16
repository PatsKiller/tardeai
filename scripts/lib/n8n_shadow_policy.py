"""n8n_shadow_policy.py — which dry runs are worth running (process consolidation cohort 1, 2026-10-16).

Operator 2026-10-16: "Stop continuous shadow rehearsals for accepted production lanes. Retain purposeful regression
and canary checks after relevant changes." Policy file: config/n8n_shadow_policy.json (N8nShadowPolicy@v1).

Two pure planners, READ-ONLY (no ledger write, no dispatch, no registry edit; mode 'report' is the only mode):

* ``plan_regression_canaries`` — for every ACCEPTED lane (dispatch.mode live at a stage in policy.accepted.stages,
  with a live RUN_DONE), is a purposeful dry run due? Due only when, between the code_sha of the lane's last verified
  live run and the current release sha, (a) the lane's own config changed: the canonical digest of its registry row
  + allowlist entry + health contract (``config_digest(sha, lane)``), or (b) its entry script changed
  (``entry_changed(old_sha, new_sha, lane)``); with ``any_release`` true, any sha change. Same sha -> never due.
  Nothing continuous: a lane whose inputs did not change gets no dry run, however many releases pass.
* ``cadence_savings`` — the shadow-cadence proposals' fires per week (cron_schedule.fires_between, America/New_York)
  and the worker-seconds they would save at the measured mean duration. Proposals are an operator §17 call.

The CLI is scripts/report_n8n_shadow_policy.py (git reads for the digests; nothing else).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

try:
    from scripts.lib import cron_schedule as _cron
except ImportError:  # imported as lib.n8n_shadow_policy
    from lib import cron_schedule as _cron  # type: ignore

SCHEMA = "N8nShadowPolicy@v1"
MODES = ("report",)
TRIGGERS = ("lane_config_changed", "entry_script_changed")
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = ROOT / "config" / "n8n_shadow_policy.json"
VERIFIED_LIVE_VERDICTS = ("produced", "empty_allowed", "no_rule", "declared_not_enforced")
WEEK_START = datetime(2026, 10, 12, 4, 0, tzinfo=timezone.utc)  # a fixed Monday 00:00 ET, so counts are stable


class ShadowPolicyError(ValueError):
    pass


def validate_policy(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise ShadowPolicyError(f"schema must be {SCHEMA}")
    if doc.get("mode") not in MODES:
        raise ShadowPolicyError(f"mode must be one of {MODES} (enforcement is an operator ruling, not a flag)")
    acc = doc.get("accepted") or {}
    if not isinstance(acc.get("stages"), list) or not acc["stages"] or acc.get("dispatch_mode") != "live":
        raise ShadowPolicyError("accepted.stages must be a non-empty list and accepted.dispatch_mode 'live'")
    rc = doc.get("regression_canary") or {}
    trig = rc.get("triggers")
    if not isinstance(trig, list) or not trig or any(t not in TRIGGERS for t in trig):
        raise ShadowPolicyError(f"regression_canary.triggers must be a non-empty subset of {TRIGGERS}")
    if not isinstance(rc.get("any_release"), bool):
        raise ShadowPolicyError("regression_canary.any_release must be a boolean")
    if not isinstance(rc.get("max_per_window"), int) or not 1 <= rc["max_per_window"] <= 200:
        raise ShadowPolicyError("regression_canary.max_per_window must be an int in 1..200")
    for lane, p in (doc.get("shadow_cadence_proposals") or {}).items():
        if lane.startswith("_"):
            continue
        for k in ("current_cron", "proposed_cron"):
            if not isinstance(p.get(k), list) or not p[k]:
                raise ShadowPolicyError(f"{lane}.{k} must be a non-empty cron list")
            for expr in p[k]:
                _cron.parse(expr)  # raises on a bad cron
    return doc


def load_policy(path: Path | str | None = None) -> dict[str, Any]:
    return validate_policy(json.loads(Path(path or DEFAULT_POLICY_PATH).read_text(encoding="utf-8")))


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def lane_config(registry: Mapping[str, Any], allowlist: Mapping[str, Any], contracts: Any, lane: str) -> dict:
    """The lane's own config: registry row, allowlist entry, health contract (None when absent)."""
    row = next((r for r in registry.get("lanes") or [] if isinstance(r, dict) and r.get("lane_id") == lane), None)
    entries = allowlist.get("lanes") if isinstance(allowlist, Mapping) else None
    entry = next((e for e in entries or [] if isinstance(e, dict) and e.get("lane_id") == lane), None)
    cs = contracts.get("contracts") if isinstance(contracts, Mapping) else contracts
    items = cs.values() if isinstance(cs, Mapping) else (cs or [])
    contract = next((c for c in items if isinstance(c, dict) and c.get("id") == lane), None)
    return {"registry_row": row, "allowlist_entry": entry, "health_contract": contract}


def entry_script(entry: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The first ``scripts/...`` path of an allowlist entry's command (the lane's own code)."""
    for tok in (entry or {}).get("command") or []:
        if isinstance(tok, str) and tok.startswith("scripts/") and tok.endswith((".py", ".sh")):
            return tok
    return None


def accepted_lanes(registry: Mapping[str, Any], last_live: Mapping[str, Mapping[str, Any]],
                   policy: Mapping[str, Any]) -> list[str]:
    stages = set(policy["accepted"]["stages"])
    out = []
    for row in registry.get("lanes") or []:
        if not isinstance(row, dict):
            continue
        d = row.get("dispatch") if isinstance(row.get("dispatch"), dict) else {}
        s = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
        if d.get("mode") == policy["accepted"]["dispatch_mode"] and s.get("stage") in stages \
                and row.get("lane_id") in last_live:
            out.append(str(row["lane_id"]))
    return sorted(out)


def last_verified_live(receipts: Iterable[Mapping[str, Any]]) -> dict[str, dict]:
    """lane -> newest live RUN_DONE receipt whose output verdict is not failing (with a code_sha)."""
    out: dict[str, dict] = {}
    for r in receipts:
        if r.get("mode") != "live" or r.get("state") != "RUN_DONE" or not r.get("code_sha"):
            continue
        v = (r.get("output_verdict") or {}).get("verdict") if isinstance(r.get("output_verdict"), Mapping) else None
        if v is not None and v not in VERIFIED_LIVE_VERDICTS:
            continue
        lane = str(r.get("lane_id") or "")
        if lane and str(r.get("finished_at") or "") >= str(out.get(lane, {}).get("finished_at") or ""):
            out[lane] = dict(r)
    return out


def plan_regression_canaries(lanes: Iterable[str], last_live: Mapping[str, Mapping[str, Any]], current_sha: str,
                             policy: Mapping[str, Any], *,
                             config_digest: Callable[[str, str], Optional[str]],
                             entry_changed: Callable[[str, str, str], Optional[bool]]) -> dict[str, Any]:
    """Pure apart from the two injected readers. An unreadable digest is reported (``unknown``), never 'due'."""
    rc = policy["regression_canary"]
    items = []
    for lane in lanes:
        old = str(last_live[lane].get("code_sha") or "")
        reasons: list[str] = []
        unknown: list[str] = []
        if old and old != current_sha:
            if rc["any_release"]:
                reasons.append("release_sha_changed")
            if "lane_config_changed" in rc["triggers"]:
                a, b = config_digest(old, lane), config_digest(current_sha, lane)
                if a is None or b is None:
                    unknown.append("lane_config")
                elif a != b:
                    reasons.append("lane_config_changed")
            if "entry_script_changed" in rc["triggers"]:
                ch = entry_changed(old, current_sha, lane)
                if ch is None:
                    unknown.append("entry_script")
                elif ch:
                    reasons.append("entry_script_changed")
        items.append({"lane_id": lane, "last_live_sha": old[:12], "current_sha": current_sha[:12],
                      "last_live_run": last_live[lane].get("run_id"), "due": bool(reasons),
                      "reasons": reasons, "unknown": unknown})
    due = [i for i in items if i["due"]]
    return {"schema": "N8nRegressionCanaryPlan@v1", "mode": policy["mode"], "current_sha": current_sha,
            "accepted_lanes": len(items), "due": len(due), "capped_at": rc["max_per_window"],
            "due_lanes": [i["lane_id"] for i in due][: rc["max_per_window"]],
            "continuous_dry_runs_planned": 0, "items": items}


def fires_per_week(crons: Iterable[str], tz: str = "America/New_York") -> int:
    lo = WEEK_START - timedelta(seconds=1)
    hi = WEEK_START + timedelta(days=7) - timedelta(seconds=1)
    return len({f.at for c in crons for f in _cron.fires_between(c, lo, hi, tz)})


def cadence_savings(policy: Mapping[str, Any]) -> dict[str, Any]:
    rows = []
    for lane, p in (policy.get("shadow_cadence_proposals") or {}).items():
        if lane.startswith("_"):
            continue
        cur, new = fires_per_week(p["current_cron"]), fires_per_week(p["proposed_cron"])
        m = p.get("measured") or {}
        mean = (m.get("worker_s") or 0.0) / m["runs"] if m.get("runs") else 0.0
        rows.append({"lane_id": lane, "current_cron": p["current_cron"], "proposed_cron": p["proposed_cron"],
                     "fires_per_week": {"current": cur, "proposed": new, "saved": cur - new},
                     "mean_duration_s": round(mean, 3),
                     "worker_s_per_week": {"current": round(cur * mean, 1), "proposed": round(new * mean, 1)}})
    tot = {k: sum(r["fires_per_week"][k] for r in rows) for k in ("current", "proposed", "saved")}
    ws = {k: round(sum(r["worker_s_per_week"][k] for r in rows), 1) for k in ("current", "proposed")}
    return {"lanes": rows, "fires_per_week": tot, "worker_s_per_week": ws}


__all__ = ["SCHEMA", "ShadowPolicyError", "validate_policy", "load_policy", "digest", "lane_config", "entry_script",
           "accepted_lanes", "last_verified_live", "plan_regression_canaries", "fires_per_week", "cadence_savings"]
