"""n8n breaker half-open probe — the pure decisions (no I/O).

A lane's breaker opens after ``breaker_threshold`` consecutive dead slots (``n8n_retry_policy.finalize_outcome``) and
then holds every later slot (``n8n_due``: BREAKER_OPEN). Only a RUN_DONE or an operator release closes it, so an open
breaker never recovers on its own. On 2026-10-31 ten breakers had been open for 22 hours to 8 days.

Half-open, driven by ``scripts/n8n_breaker_probe.py`` on a host tick:

* **probe** — at most ONE lane per tick, the longest-open first: a breaker open for ``open_hours *
  backoff_factor**probes`` (capped at ``max_interval_hours``), with fewer than ``max_probes`` probes, is released once
  (``released_by`` = ``auto:half_open_probe``). The probe state is written BEFORE the release.
* **judge** — exactly one probe slot: the slot of the first run requested after the release. Its RUN_DONE = pass (the
  breaker stays closed, state cleared); RUN_FAILED / RUN_TIMEOUT = fail (re-open at once with backoff — a release
  resets ``consecutive_dead``, so without this the lane would fail three more times before re-opening); no verdict on
  that slot inside ``probe_timeout_hours`` = re-open. Runs of later slots never decide. RUN_SKIPPED_LOCK / RUN_REFUSED
  decide nothing.
* **yield** — someone other than the prober acted on the breaker since the probe started (an operator release or
  re-open, the retry policy re-opening it): the prober drops its state and leaves the lane alone.
* **hold** — a lane in the operator hold marker is never touched.

Never probed: NEVER_PROBE (code; config may add, never remove) and live canary lanes (AGENTS.md §23.14, review
2026-10-31).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional

SCHEMA_RECEIPT = "N8nBreakerProbeReceipt@v1"
PASS_STATES = frozenset({"RUN_DONE"})
FAIL_STATES = frozenset({"RUN_FAILED", "RUN_TIMEOUT"})
#: Code floor (case-insensitive substrings). Config ``never_probe_extra`` may only add.
NEVER_PROBE = (
    "broker",
    "schwab",
    "alpaca",
    "moomoo",
    "order",
    "stop",
    "execution",
    "active-trader",
    "options-lifecycle",
    "scalp",
    "sender",
    "telegram",
    "secret",
    "deploy",
    "release",
    "guard",
    "position",
    "paper",
    "account",
    "dof",
)


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


def blocked(lane: str, cfg: Mapping[str, Any], *, stage: Optional[str] = None) -> Optional[str]:
    low = lane.lower()
    for p in (*NEVER_PROBE, *[str(x).lower() for x in cfg.get("never_probe_extra") or []]):
        if p in low:
            return f"never-probe pattern {p!r}"
    if stage and str(stage).lower() == "canary":
        return "live canary lane"
    return None


def decide(
    breakers: Iterable[Mapping[str, Any]],
    runs_after: Mapping[str, list[Mapping[str, Any]]],
    state: Mapping[str, Any],
    cfg: Mapping[str, Any],
    now: datetime,
    *,
    holds: Iterable[str] = (),
    stages: Optional[Mapping[str, str]] = None,
) -> list[dict]:
    """Actions: probe (at most one per tick) | pass | fail | timeout | yield | wait | exhausted | blocked | held.

    ``breakers``: ledger rows {lane_id, opened_at, released_at, released_by, consecutive, open}. ``runs_after``:
    lane -> runs requested after the probe release, oldest first ({run_id, slot_key, state, finished_at}). ``state``:
    lane -> {probes, probing_since, last_result, consecutive}."""
    hold = set(holds or ())
    stages = stages or {}
    acts: list[dict] = []
    candidates: list[tuple[datetime, dict]] = []
    released_by = cfg["released_by"]
    for b in breakers or []:
        lane = str(b["lane_id"])
        st = dict(state.get(lane) or {})
        probes = int(st.get("probes") or 0)
        if lane in hold:
            acts.append({"lane": lane, "action": "held", "probes": probes})
            continue
        if st.get("probing_since"):
            since = parse_ts(st["probing_since"])
            opened = parse_ts(b.get("opened_at"))
            if b.get("released_by") != released_by or (opened and since and opened > since):
                acts.append(
                    {
                        "lane": lane,
                        "action": "yield",
                        "probes": probes,
                        "why": f"another actor ({b.get('released_by') or 're-open'}) acted since the probe",
                    }
                )
                continue
            runs = list(runs_after.get(lane, []))
            slot = runs[0].get("slot_key") if runs else None
            mine = [r for r in runs if r.get("slot_key") == slot] if slot else runs[:1]
            verdict = next((r for r in mine if r.get("state") in PASS_STATES | FAIL_STATES), None)
            if verdict and verdict["state"] in PASS_STATES:
                acts.append(
                    {"lane": lane, "action": "pass", "run_id": verdict.get("run_id"), "slot": slot, "probes": probes}
                )
            elif verdict:
                acts.append(
                    {
                        "lane": lane,
                        "action": "fail",
                        "run_id": verdict.get("run_id"),
                        "slot": slot,
                        "probes": probes,
                        "run_state": verdict["state"],
                        "consecutive": st.get("consecutive") or 1,
                    }
                )
            elif since and now - since >= timedelta(hours=float(cfg["probe_timeout_hours"])):
                acts.append(
                    {
                        "lane": lane,
                        "action": "timeout",
                        "probes": probes,
                        "slot": slot,
                        "consecutive": st.get("consecutive") or 1,
                    }
                )
            else:
                acts.append({"lane": lane, "action": "wait", "probes": probes, "slot": slot})
            continue
        if not b.get("open"):
            continue
        why = blocked(lane, cfg, stage=stages.get(lane))
        if why:
            acts.append({"lane": lane, "action": "blocked", "probes": probes, "why": why})
            continue
        if probes >= int(cfg["max_probes"]):
            if not st.get("exhausted_at"):
                acts.append({"lane": lane, "action": "exhausted", "probes": probes})
            continue
        opened = parse_ts(b.get("opened_at"))
        need = interval_hours(cfg, probes)
        if opened and now - opened >= timedelta(hours=need):
            candidates.append(
                (
                    opened,
                    {
                        "lane": lane,
                        "action": "probe",
                        "probes": probes,
                        "open_hours": round((now - opened).total_seconds() / 3600, 1),
                        "interval_hours": need,
                        "consecutive": b.get("consecutive"),
                    },
                )
            )
        else:
            acts.append({"lane": lane, "action": "wait", "probes": probes, "interval_hours": need})
    candidates.sort(key=lambda c: c[0])
    for i, (_, act) in enumerate(candidates):
        acts.append(act if i == 0 else {**act, "action": "wait", "why": "one probe per tick (oldest first)"})
    return acts


def next_state(state: Mapping[str, Any], act: Mapping[str, Any], now: datetime) -> dict:
    """The probe state after an action (for a probe: written BEFORE the release)."""
    st = {k: dict(v) for k, v in (state or {}).items()}
    lane = act["lane"]
    cur = st.get(lane, {})
    a = act["action"]
    if a == "probe":
        cur.update(probing_since=now.isoformat(), consecutive=act.get("consecutive"))
    elif a in ("pass", "yield"):
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


def receipt(act: Mapping[str, Any], now: datetime, *, applied: bool, error: Optional[str] = None) -> dict:
    out = {"schema": SCHEMA_RECEIPT, "at": now.isoformat(), "applied": applied, **act}
    if error:
        out["error"] = error
    return out


def render(acts: list[dict]) -> Optional[str]:
    moved = [a for a in acts if a["action"] in ("probe", "pass", "fail", "timeout", "exhausted")]
    if not moved:
        return None
    lines = ["🔌 *n8n breaker probes*"]
    for a in moved:
        lines.append(f"• {a['lane']}: {a['action']}" + (f" ({a.get('run_state')})" if a.get("run_state") else ""))
    lines.append("Half-open probe: one natural slot runs; a pass keeps the lane open, a failure re-opens it.")
    return "\n".join(lines)
