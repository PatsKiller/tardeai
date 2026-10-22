#!/usr/bin/env python3
"""n8n_host_deadman.py — a dead-man for n8n that runs OUTSIDE n8n and pages P1 without it (FW-P6). Dry run by default.

Why: AGENTS.md §23.23 "Independence" — the P0/P1 dead-man never depends on n8n; n8n is watched, never the watcher of
its own failure — and §23.24 Alerting (2). Measured (WS1-15, framework scorecard FW-P6): the only n8n heartbeat
watcher, ``heartbeat-watch``, is FIRED BY n8n, and its breach rows reach the operator through the incident fan-in,
which is also an n8n-fired lane. If n8n stops, the thing that would notice is the thing that stopped. The lab
watchdog (``scripts/n8n_lab_watchdog.py``) probes ``/healthz`` from the host but sends nothing by design.

What one run checks (all host-side, stdlib + the SYSTEM ops transport):

* ``healthz``: ``GET http://127.0.0.1:5678/healthz`` answers 200 with the healthz body (reuses
  ``n8n_lab_watchdog.check``; process liveness only).
* ``heartbeat``: n8n is still SCHEDULING — the receipt of a lane only n8n fires (default
  ``data/runtime/heartbeat-watch_last.json``, fired every 5 min by ``tradeai-heartbeat-watcher`` and the dispatcher;
  no cron line) has ``ok_at`` (or ``finished_at``) within ``--heartbeat-max-age-min`` (20). A healthy process
  whose schedules stopped fails here.

Two consecutive bad runs (``--threshold``) page **P1** through ``scripts/lib/host_p1_pager.py`` (send_system, the
SYSTEM ops family — the incident notifier's transport, not n8n, not the fan-in); a reminder every 6 h while it
stays bad; one recovery notice when both checks pass again. Every run writes
``data/runtime/n8n_host_deadman_last.json`` (``N8nHostDeadman@v1``; live only), which
``scripts/probe_n8n_platform_facts.py`` reads for FW-P6.

Limit (stated on the receipt): a watcher on this host cannot see this host's total outage; that is
``scripts/offbox_deadman.py``'s job (external pull-on-miss).

    python3 scripts/n8n_host_deadman.py            # dry run: probes, prints the page it WOULD send; writes and sends nothing
    python3 scripts/n8n_host_deadman.py --live     # what the timer runs (operator-installed unit, packet FW-P6)

Exit: 0 OK, 1 bad (dry run and live alike).
AUTHORITY: OPERATOR_NOTIFY_SYSTEM_OPS. Reads a URL and a receipt; no restart, no remediation, no n8n call beyond
/healthz, no broker. MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import n8n_lab_watchdog as LW  # noqa: E402
from scripts.lib import host_p1_pager as PG  # noqa: E402
from scripts.lib.atomic_json_store import atomic_write_json  # noqa: E402
from scripts.lib.n8n_pilot_observations import state_root  # noqa: E402

SCHEDULED_ENTRYPOINT = (
    "systemd --user tradeai-n8n-host-deadman.timer (every 5 min; PROPOSED, operator-installed: "
    "docs/ops/packets/n8n-platform-hardening-20261022/units/)"
)
SCHEMA = "N8nHostDeadman@v1"
RECEIPT_REL = Path("data") / "runtime" / "n8n_host_deadman_last.json"
STATE_REL = Path("data") / "runtime" / "n8n_host_deadman_state.json"
HEARTBEAT_REL = Path("data") / "runtime" / "heartbeat-watch_last.json"
RUNBOOK = "docs/ops/packets/n8n-platform-hardening-20261022/README.md#fw-p6"
PAGE_PREFIX = "n8n-deadman"
CADENCE_MIN = 5
DEFAULT_HEARTBEAT_MAX_AGE_MIN = 20.0


def _parse(ts: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else None


def heartbeat_check(path: Path, *, now: datetime, max_age_min: float) -> dict[str, Any]:
    out: dict[str, Any] = {"name": "heartbeat", "path": str(path), "max_age_min": max_age_min, "ok": False}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        out["error"] = "missing"
        return out
    except (OSError, ValueError) as exc:
        out["error"] = f"unreadable:{type(exc).__name__}"
        return out
    at = _parse(doc.get("ok_at")) or _parse(doc.get("finished_at"))
    if at is None:
        out["error"] = "no_timestamp"
        return out
    age = (now - at).total_seconds() / 60.0
    out.update(last_at=at.isoformat(), age_min=round(age, 1), lane_id=doc.get("lane_id"))
    if age < -5:
        out["error"] = "future_timestamp"
        return out
    out["ok"] = age <= max_age_min
    if not out["ok"]:
        out["error"] = "stale"
    return out


def page_text(checks: list[dict], action: dict) -> str:
    if action["kind"] == PG.RECOVER:
        return (
            "TRADE AI SYSTEM NOTICE — n8n dead-man CLEARED\n"
            f"n8n answers /healthz and is scheduling again (down since {action.get('onset')}).\n"
            f"Runbook: {RUNBOOK}"
        )
    lines = ["TRADE AI SYSTEM ALERT — P1 n8n DEAD-MAN (host watcher; n8n not involved)"]
    for c in checks:
        if c["name"] == "healthz":
            lines.append(
                f"• healthz: {'ok' if c['ok'] else 'FAIL'} (http {c.get('http_status')}, {c.get('error') or 'no error'})"
            )
        else:
            lines.append(
                f"• heartbeat ({c.get('lane_id') or 'heartbeat-watch'}): {'ok' if c['ok'] else 'FAIL'} "
                f"(last {c.get('last_at') or 'never'}, age {c.get('age_min', '?')} min "
                f"{'<=' if c['ok'] else 'vs'} limit {c['max_age_min']:g} min: "
                f"{c.get('error') or 'fresh'})"
            )
    lines.append(
        f"Bad since {action.get('onset')}. n8n schedules nothing while this stands; P1 still reaches you on this path. "
        f"Runbook: {RUNBOOK}"
    )
    if action["kind"] == PG.REMIND:
        lines.append("(reminder — still down)")
    return "\n".join(lines)


def _load(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def run_once(
    *,
    live: bool,
    root: Path,
    url: str = LW.DEFAULT_URL,
    heartbeat: Optional[Path] = None,
    heartbeat_max_age_min: float = DEFAULT_HEARTBEAT_MAX_AGE_MIN,
    threshold: int = 2,
    reminder_h: float = 6.0,
    now: Optional[datetime] = None,
    prober: Optional[Callable[[str], dict]] = None,
    sender: Optional[PG.Sender] = None,
    previewer: Optional[PG.Previewer] = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    hz = (prober or (lambda u: LW.check(u, timeout_s=5.0, now=now)))(url)
    checks = [
        {"name": "healthz", "ok": bool(hz.get("ok")), "http_status": hz.get("http_status"), "error": hz.get("error"),
         "url": hz.get("url", url)},
        heartbeat_check(heartbeat or (root / HEARTBEAT_REL), now=now, max_age_min=heartbeat_max_age_min),
    ]
    bad = not all(c["ok"] for c in checks)
    key = "down" if not checks[0]["ok"] else "not_scheduling"
    state_path = root / STATE_REL
    state, action = PG.decide(
        _load(state_path), bad=bad, key=key, now=now, prefix=PAGE_PREFIX, threshold=threshold, reminder_h=reminder_h
    )
    state, page = PG.run_action(
        state, action, page_text(checks, action), live=live, now=now, kind="n8n_host_deadman",
        sender=sender, previewer=previewer,
    )
    receipt = {
        "schema": SCHEMA,
        "checked_at": now.replace(microsecond=0).isoformat(),
        "mode": "live" if live else "dry_run",
        "authority": "OPERATOR_NOTIFY_SYSTEM_OPS",
        "cadence_min": CADENCE_MIN,
        "status": "BAD" if bad else "OK",
        "condition": key if bad else None,
        "consecutive_bad": state.get("consecutive_bad", 0) if bad else 0,
        "threshold": threshold,
        "checks": checks,
        "alert_path": PG.P1_PATH,
        "runs_inside_n8n": False,
        "host_failure_limitation": LW.HOST_FAILURE_LIMITATION,
        "runbook": RUNBOOK,
        "page": page,
    }
    if live:
        atomic_write_json(state_path, state)
        atomic_write_json(root / RECEIPT_REL, receipt)
    return receipt


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--live", action="store_true", help="write the receipt and page (default: dry run)")
    ap.add_argument("--url", default=LW.DEFAULT_URL)
    ap.add_argument("--heartbeat", default=None, help=f"lane receipt n8n alone fires (default $STATE_ROOT/{HEARTBEAT_REL})")
    ap.add_argument("--heartbeat-max-age-min", type=float, default=DEFAULT_HEARTBEAT_MAX_AGE_MIN)
    ap.add_argument("--threshold", type=int, default=2, help="consecutive bad runs before the P1 page")
    ap.add_argument("--state-root", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.state_root) if a.state_root else state_root()
    receipt = run_once(
        live=a.live,
        root=root,
        url=a.url,
        heartbeat=Path(a.heartbeat) if a.heartbeat else None,
        heartbeat_max_age_min=a.heartbeat_max_age_min,
        threshold=a.threshold,
    )
    if a.json:
        print(json.dumps(receipt, indent=1, default=str))
    else:
        parts = []
        for c in receipt["checks"]:
            parts.append(f"{c['name']} {'ok' if c['ok'] else 'FAIL'}" + (f" ({c.get('error')})" if c.get("error") else ""))
            if c["name"] == "heartbeat" and c.get("age_min") is not None:
                parts[-1] += f" age {c['age_min']} min"
        print(
            f"n8n host dead-man ({receipt['mode']}): {receipt['status']}  " + "; ".join(parts)
            + f"  page {receipt['page'].get('action')}"
            + (f" {receipt['page'].get('identity')}" if receipt["page"].get("identity") else "")
            + ("" if a.live else "  (dry run, nothing written or sent)")
        )
    return 0 if receipt["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
