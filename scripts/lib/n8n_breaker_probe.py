"""n8n breaker half-open probe — the pure decisions (no I/O).

A lane's breaker opens after ``breaker_threshold`` consecutive dead slots (``n8n_retry_policy.finalize_outcome``) and
then holds every later slot (``n8n_due``: BREAKER_OPEN). Only a RUN_DONE or an operator release closes it, so an open
breaker never recovers on its own. On 2026-10-31 ten breakers had been open for 22 hours to 8 days.

Half-open, per lane, driven by ``scripts/n8n_breaker_probe.py`` on a host tick:

* **probe** — the breaker has been open for ``open_hours * backoff_factor**probes`` (capped at
  ``max_interval_hours``) and fewer than ``max_probes`` probes ran: release it once (``released_by`` =
  ``auto:half_open_probe``); the lane's next natural slot is the probe run.
* **judge** — after a probe release, the first finished run of the lane decides: RUN_DONE = passed (the breaker stays
  closed and the state is cleared); RUN_FAILED / RUN_TIMEOUT = failed: re-open at once with backoff (a release resets
  ``consecutive_dead``, so without this the lane would fail three more times before re-opening); no run inside
  ``probe_timeout_hours`` = re-open (the lane did not come due; try again later). RUN_SKIPPED_LOCK / RUN_REFUSED
  decide nothing (not the code's verdict).

Never probed: lanes matching ``never_probe_globs`` (broker, order, stop, execution, AGENTS.md §23.14).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from typing import Any, Iterable, Mapping, Optional

SCHEMA_RECEIPT = "N8nBreakerProbeReceipt@v1"
PASS_STATES = frozenset({"RUN_DONE"})
FAIL_STATES = frozenset({"RUN_FAILED", "RUN_TIMEOUT"})


def parse_ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def interval_hours(cfg: Mapping[str, Any], probes: int) -> float:
    return min(float(cfg["open_hours"]) * float(cfg["backoff_factor"]) ** int(probes), float(cfg["max_interval_hours"]))


def blocked(lane: str, cfg: Mapping[str, Any]) -> bool:
    return any(fnmatch(lane, g) for g in cfg.get("never_probe_globs") or [])


def decide(
    breakers: Iterable[Mapping[str, Any]],
    runs_after: Mapping[str, list[Mapping[str, Any]]],
    state: Mapping[str, Any],
    cfg: Mapping[str, Any],
    now: datetime,
) -> list[dict]:
    """One action per lane: probe | pass | fail | timeout | wait | exhausted | blocked.

    ``breakers``: ledger rows {lane_id, opened_at, released_at, consecutive, open}. ``runs_after``: lane -> finished
    runs requested after the lane's probe release, oldest first ({run_id, state, finished_at}). ``state``: lane ->
    {probes, probing_since, last_result, consecutive}."""
    acts: list[dict] = []
    for b in breakers or []:
        lane = str(b["lane_id"])
        st = dict(state.get(lane) or {})
        probes = int(st.get("probes") or 0)
        if st.get("probing_since"):
            since = parse_ts(st["probing_since"])
            verdict = next((r for r in runs_after.get(lane, []) if r.get("state") in PASS_STATES | FAIL_STATES), None)
            if verdict and verdict["state"] in PASS_STATES:
                acts.append({"lane": lane, "action": "pass", "run_id": verdict.get("run_id"), "probes": probes})
            elif verdict:
                acts.append(
                    {
                        "lane": lane,
                        "action": "fail",
                        "run_id": verdict.get("run_id"),
                        "probes": probes,
                        "run_state": verdict["state"],
                        "consecutive": st.get("consecutive") or 1,
                    }
                )
            elif since and now - since >= timedelta(hours=float(cfg["probe_timeout_hours"])):
                acts.append(
                    {"lane": lane, "action": "timeout", "probes": probes, "consecutive": st.get("consecutive") or 1}
                )
            else:
                acts.append({"lane": lane, "action": "wait", "probes": probes})
            continue
        if not b.get("open"):
            continue
        if blocked(lane, cfg):
            acts.append({"lane": lane, "action": "blocked", "probes": probes})
            continue
        if probes >= int(cfg["max_probes"]):
            if not st.get("exhausted_at"):  # page once; then it waits for a code fix and an operator release
                acts.append({"lane": lane, "action": "exhausted", "probes": probes})
            continue
        opened = parse_ts(b.get("opened_at"))
        need = interval_hours(cfg, probes)
        if opened and now - opened >= timedelta(hours=need):
            acts.append(
                {
                    "lane": lane,
                    "action": "probe",
                    "probes": probes,
                    "open_hours": round((now - opened).total_seconds() / 3600, 1),
                    "interval_hours": need,
                    "consecutive": b.get("consecutive"),
                }
            )
        else:
            acts.append({"lane": lane, "action": "wait", "probes": probes, "interval_hours": need})
    return acts


def next_state(state: Mapping[str, Any], act: Mapping[str, Any], now: datetime) -> dict:
    """The probe state after an action was carried out."""
    st = {k: dict(v) for k, v in (state or {}).items()}
    lane = act["lane"]
    cur = st.get(lane, {})
    a = act["action"]
    if a == "probe":
        cur.update(probing_since=now.isoformat(), consecutive=act.get("consecutive"))
    elif a == "pass":
        st.pop(lane, None)
        return st
    elif a == "exhausted":
        cur.update(exhausted_at=now.isoformat())
    elif a in ("fail", "timeout"):
        cur.update(probes=int(cur.get("probes") or 0) + 1, probing_since=None, last_result=a, last_at=now.isoformat())
    else:
        return st
    st[lane] = cur
    return st


def receipt(act: Mapping[str, Any], now: datetime, *, applied: bool) -> dict:
    return {"schema": SCHEMA_RECEIPT, "at": now.isoformat(), "applied": applied, **act}


def render(acts: list[dict]) -> Optional[str]:
    moved = [a for a in acts if a["action"] in ("probe", "pass", "fail", "timeout", "exhausted")]
    if not moved:
        return None
    lines = ["🔌 *n8n breaker probes*"]
    for a in moved:
        lines.append(f"• {a['lane']}: {a['action']}" + (f" ({a.get('run_state')})" if a.get("run_state") else ""))
    lines.append("Half-open probe: one natural slot runs; a pass keeps the lane open, a failure re-opens it.")
    return "\n".join(lines)
