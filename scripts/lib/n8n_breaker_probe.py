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
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Optional

SCHEMA_RECEIPT = "N8nBreakerProbeReceipt@v1"
PASS_STATES = frozenset({"RUN_DONE"})
_NO_STAGES: Mapping[str, str] = MappingProxyType({})  # "no lane has a stage"; None means "registry unreadable"
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
    holds: Optional[Iterable[str]] = (),
    stages: Optional[Mapping[str, str]] = _NO_STAGES,
) -> list[dict]:
    """Actions: probe | gate | pass | fail | timeout | yield | wait | exhausted | blocked | held.

    Exactly one probe slot (review round 2): ``probe`` releases the breaker; as soon as the first run after the
    release is REQUESTED, ``gate`` re-opens the breaker so no second slot can start; that one slot's verdict decides —
    ``pass`` releases the breaker for good, ``fail`` keeps it open with backoff. At most ``max_concurrent_probes`` lanes
    probe at once. ``holds`` None (holds file unreadable) or ``stages`` None (lane registry unreadable) = fail closed:
    nothing new is probed.

    ``breakers``: rows {lane_id, opened_at, released_at, released_by, consecutive, open}. ``runs_after``: lane -> runs
    requested after the probe release, oldest first ({run_id, slot_key, state}). ``state``: lane -> {probes,
    probing_since, gate_opened_at, consecutive, exhausted_at}."""
    fail_closed = None
    if holds is None:
        fail_closed = "holds file unreadable"
    elif stages is None:
        fail_closed = "lane registry unreadable"
    hold = set(holds or ())
    stages = stages or {}
    acts: list[dict] = []
    candidates: list[tuple[datetime, dict]] = []
    ours = cfg["released_by"]
    probing_now = sum(1 for v in (state or {}).values() if (v or {}).get("probing_since"))
    for b in breakers or []:
        lane = str(b["lane_id"])
        st = dict(state.get(lane) or {})
        probes = int(st.get("probes") or 0)
        if lane in hold:
            acts.append({"lane": lane, "action": "held", "probes": probes})
            continue
        if st.get("probing_since"):
            since = parse_ts(st["probing_since"])
            gate = st.get("gate_opened_at")
            opened_raw = str(b.get("opened_at") or "")
            if gate:
                someone_else = (b.get("released_by") not in (None, ours)) or (opened_raw and opened_raw != gate)
            else:
                opened = parse_ts(opened_raw)
                someone_else = b.get("released_by") != ours or bool(opened and since and opened > since)
            if someone_else:
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
            mine = [r for r in runs if r.get("slot_key") == slot] if slot else []
            verdict = next((r for r in mine if r.get("state") in PASS_STATES | FAIL_STATES), None)
            if verdict and verdict["state"] in PASS_STATES:
                acts.append(
                    {
                        "lane": lane,
                        "action": "pass",
                        "run_id": verdict.get("run_id"),
                        "slot": slot,
                        "probes": probes,
                        "gated": bool(gate),
                    }
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
                        "gated": bool(gate),
                        "consecutive": st.get("consecutive") or 1,
                    }
                )
            elif runs and not gate:
                acts.append(
                    {
                        "lane": lane,
                        "action": "gate",
                        "slot": slot,
                        "probes": probes,
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
                        "gated": bool(gate),
                        "consecutive": st.get("consecutive") or 1,
                    }
                )
            else:
                acts.append({"lane": lane, "action": "wait", "probes": probes, "slot": slot})
            continue
        if not b.get("open"):
            continue
        why = fail_closed or blocked(lane, cfg, stage=stages.get(lane))
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
    room = max(0, int(cfg["max_concurrent_probes"]) - probing_now)
    candidates.sort(key=lambda c: c[0])
    for i, (_, act) in enumerate(candidates):
        if i == 0 and room > 0:
            acts.append(act)
        else:
            why = "one probe per tick (oldest first)" if room > 0 else "another lane is probing (max_concurrent_probes)"
            acts.append({**act, "action": "wait", "why": why})
    return acts


def next_state(state: Mapping[str, Any], act: Mapping[str, Any], now: datetime, *, gate_opened_at: Any = None) -> dict:
    """The probe state after an action (a probe's state is written BEFORE the release). On ``yield`` the backoff is
    KEPT (``probes``) and only ``probing_since``/``gate_opened_at`` are dropped (review round 2: clearing it made the
    lane probe every open_hours forever)."""
    st = {k: dict(v) for k, v in (state or {}).items()}
    lane = act["lane"]
    cur = st.get(lane, {})
    a = act["action"]
    if a == "probe":
        cur.update(probing_since=now.isoformat(), gate_opened_at=None, consecutive=act.get("consecutive"))
    elif a == "gate":
        cur.update(gate_opened_at=gate_opened_at)
    elif a == "pass":
        st.pop(lane, None)
        return st
    elif a == "yield":
        cur.update(probing_since=None, gate_opened_at=None)
    elif a == "exhausted":
        cur.update(exhausted_at=now.isoformat())
    elif a in ("fail", "timeout"):
        cur.update(
            probes=int(cur.get("probes") or 0) + 1,
            probing_since=None,
            gate_opened_at=None,
            last_result=a,
            last_at=now.isoformat(),
        )
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
