#!/usr/bin/env python3
"""check_active_trader_motion_heartbeat.py — n8n's supervision of the Active Trader motion runtime.

Operator decision 2026-10-19: the 5/10/30-second motion loop stays a systemd user service
(``tradeai-active-trader-motion.service``, ``python -m active_trader.motion_runtime``) because n8n's minimum schedule
is one minute and its runs are stateless processes; n8n OWNS its supervision through lane
``active-trader-motion-watchdog`` (``*/5``, fired by ``tradeai-dispatcher``), which runs this script.

Read-only towards the runtime. It reads the heartbeat file (contract ``active-trader-motion-runtime-heartbeat-v1``),
``/proc/<pid>`` and ``/proc/<pid>/cmdline`` (never ``environ``), and whether the operator's marker
``/etc/tradeai/enable-active-trader-motion`` exists. It never restarts, stops, starts or edits a unit, never imports
``active_trader`` and never touches a broker, an order or a credential.

Bands (config/active_trader_motion_watchdog.json):

    HEALTHY   heartbeat fresh (age <= stale_after_s), status healthy, pid alive and running the motion module
    STALE     the process is alive but the heartbeat is older than stale_after_s
    DEGRADED  fresh heartbeat whose status is not healthy, or consecutive_failures >= degraded_consecutive_failures
    DOWN      no heartbeat, an unreadable or wrong-contract heartbeat, or its pid is not alive / not the runtime
    DISABLED  the operator marker is absent and the runtime is not running: an operator-gated state, never a page

Window: trading days (scripts/lib/cio_market_session.py, the repo's NYSE calendar) from 07:00 ET to the official
close (13:00 on early-close days). Outside it the verdict is computed and reported but never alerts. A calendar error
counts as inside the window (a watchdog fails towards telling the operator).

Alerts go only through the host comms-intent path (scripts/lib/host_comms_intents.py, route
host/active_trader_motion_watchdog in config/host_comms_intent_routes.json, DIGEST -> P2 via the comms-intent consumer
and the incident notifier). Band-change dedupe: an alert band is queued once when it first differs from the last
alerted band; HEALTHY after an alert band queues one recovery line; DISABLED never alerts and resets the band.

    python3 scripts/check_active_trader_motion_heartbeat.py            # --dry-run (default): prints, writes nothing
    python3 scripts/check_active_trader_motion_heartbeat.py --apply    # + state file, intents, LaneRunReceipt

Output (LaneRunReceipt@v2 ``output=`` fields, like scripts/n8n_comms_intent_consumer.py): produced_count = 1 for a
verdict recorded inside the window; outside it 0 with empty_reason ``market_closed`` (non-trading day or after the
close) or ``window_not_reached`` (a trading day before 07:00 ET). An unreadable config, a state write that failed or
an alert that could not be queued is the fatal skip ``dependency_unavailable`` (exit 1; the band is not marked as
alerted, so the next run tries again).

Exit: 0 the run completed (any band: the band is the output, not a run failure); 1 dependency failure; 2 usage.
MBI_BEHAVIOR = 0. No send, no network, no subprocess. Authority: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LANE_ID = "active-trader-motion-watchdog"
SCRIPT = "scripts/check_active_trader_motion_heartbeat.py"
SCHEMA = "ActiveTraderMotionWatchdog@v1"
STATE_SCHEMA = "ActiveTraderMotionWatchdogState@v1"
VERDICT_SCHEMA = "ActiveTraderMotionVerdict@v1"
# check_dark_contracts: these three schemas are self-contained. The state file is read back only by this checker
# (band-change dedupe); the verdict leaves through the LaneRunReceipt@v2 receipt (n8n output verdict) and the host
# comms intent, which consumers read by their own contracts, not by these names.
NO_CONSUMER_REASON = (
    "self-contained watchdog: state is read back only by this checker; results reach consumers via the "
    "LaneRunReceipt@v2 receipt and the host comms intent"
)
CONFIG_REL = Path("config") / "active_trader_motion_watchdog.json"
DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases" / "persistent-state"
LEDGER_REL = "data/governance/n8n_coordination_ledger.sqlite"

HEALTHY, STALE, DEGRADED, DOWN, DISABLED = "HEALTHY", "STALE", "DEGRADED", "DOWN", "DISABLED"
BANDS = (HEALTHY, STALE, DEGRADED, DOWN, DISABLED)
EMPTY_MARKET_CLOSED = "market_closed"
EMPTY_WINDOW_NOT_REACHED = "window_not_reached"
SKIP_DEPENDENCY = "dependency_unavailable"
_EXEC_ID_RE = re.compile(r"[^A-Za-z0-9_-]")


class ConfigError(ValueError):
    pass


# --------------------------------------------------------------------------------------------------------- config
def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    p = path or (ROOT / CONFIG_REL)
    try:
        cfg = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigError(f"config_unreadable: {type(exc).__name__}") from exc
    if not isinstance(cfg, dict) or cfg.get("schema") != SCHEMA:
        raise ConfigError("config_schema")
    try:
        stale = float(cfg["stale_after_s"])
        int(cfg["degraded_consecutive_failures"])
        w = cfg["window"]
        _hm(w["start"])
        alert = cfg["alert"]
        for k in ("domain", "kind", "tier", "producer"):
            if not isinstance(alert[k], str) or not alert[k]:
                raise ConfigError(f"alert.{k}")
        if alert["tier"] == "PAGE":
            raise ConfigError("alert.tier PAGE is never allowed on the host intent path")
        if stale <= 0:
            raise ConfigError("stale_after_s")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"config_field: {exc}") from exc
    return cfg


def _hm(text: str) -> dtime:
    h, m = str(text).split(":")
    return dtime(int(h), int(m))


# --------------------------------------------------------------------------------------------------------- window
def window_state(now: datetime, cfg: Mapping[str, Any], session_service: Any = None) -> dict[str, Any]:
    """{in_window, reason, session_date, close}. Pure apart from the calendar (injectable)."""
    try:
        from scripts.lib import cio_market_session as M

        svc = session_service or M.NYSESessionService()
        s = svc.session_at(now)
        et = now.astimezone(svc.tz)
    except Exception as exc:  # noqa: BLE001 — a watchdog fails towards telling the operator
        return {"in_window": True, "reason": f"calendar_error:{type(exc).__name__}", "session_date": None, "close": None}
    w = cfg["window"]
    trading = bool(s.get("is_trading_day"))
    if w.get("trading_days_only", True) and not trading:
        return {"in_window": False, "reason": "not_trading_day", "session_date": s.get("session_date"), "close": None}
    start = _hm(w["start"])
    end_raw = w.get("end", "official_close")
    if end_raw == "official_close":
        close = s.get("official_close")
        end = datetime.fromisoformat(close).time() if close else _hm("16:00")
    else:
        end = _hm(end_raw)
        close = None
    t = et.time()
    if t < start:
        return {"in_window": False, "reason": "before_window", "session_date": s.get("session_date"), "close": close}
    if t >= end:
        return {"in_window": False, "reason": "after_close", "session_date": s.get("session_date"), "close": close}
    return {"in_window": True, "reason": "in_window", "session_date": s.get("session_date"), "close": close}


# --------------------------------------------------------------------------------------------------------- observe
def _marker_present(path: Path) -> Optional[bool]:
    try:
        return path.exists()
    except OSError:
        return None


def read_heartbeat(path: Path, contract: str) -> tuple[str, dict[str, Any]]:
    """(state, doc): state is ok | missing | unreadable | contract_mismatch."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "missing", {}
    except OSError:
        return "unreadable", {}
    try:
        doc = json.loads(raw)
    except ValueError:
        return "unreadable", {}
    if not isinstance(doc, dict):
        return "unreadable", {}
    if doc.get("contract") != contract:
        return "contract_mismatch", doc
    return "ok", doc


def pid_state(pid: Any, proc_root: Path, match: str) -> str:
    """alive | dead | not_runtime (pid reused by another program) | no_pid. Reads /proc/<pid>/cmdline only."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return "no_pid"
    d = proc_root / str(pid)
    if not d.is_dir():
        return "dead"
    try:
        cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return "dead"
    return "alive" if match in cmd else "not_runtime"


def evaluate(
    cfg: Mapping[str, Any],
    *,
    now_epoch: float,
    heartbeat_path: Path,
    marker_path: Path,
    proc_root: Path,
) -> dict[str, Any]:
    """The band and its evidence. Pure apart from the three injectable paths (read-only)."""
    marker = _marker_present(marker_path)
    hb_state, hb = read_heartbeat(heartbeat_path, cfg["heartbeat_contract"])
    pid = hb.get("pid")
    proc = pid_state(pid, proc_root, cfg["process_match"]) if hb_state == "ok" else "unknown"
    updated = hb.get("updated_at")
    age = None
    if isinstance(updated, (int, float)) and not isinstance(updated, bool):
        age = round(max(0.0, now_epoch - float(updated)), 1)
    status = hb.get("status")
    failures = hb.get("consecutive_failures")
    stale_after = float(cfg["stale_after_s"])
    running = hb_state == "ok" and proc == "alive"
    reasons: list[str] = []
    if marker is False and not running:
        band = DISABLED
        reasons.append("marker_absent")
        reasons.append(f"heartbeat_{hb_state}" if hb_state != "ok" else f"pid_{proc}")
    elif hb_state != "ok":
        band = DOWN
        reasons.append(f"heartbeat_{hb_state}")
    elif proc != "alive":
        band = DOWN
        reasons.append(f"pid_{proc}")
    elif age is None or age > stale_after:
        band = STALE
        reasons.append("heartbeat_age_unknown" if age is None else f"heartbeat_age_{int(age)}s>{int(stale_after)}s")
    elif status != "healthy" or (isinstance(failures, int) and failures >= int(cfg["degraded_consecutive_failures"])):
        band = DEGRADED
        reasons.append(f"status_{status}")
        if isinstance(failures, int) and failures:
            reasons.append(f"consecutive_failures_{failures}")
    else:
        band = HEALTHY
    if marker is False and running:
        reasons.append("marker_absent_while_running: the unit will not start again after a stop")
    if marker is None:
        reasons.append("marker_unreadable")
    return {
        "schema": VERDICT_SCHEMA,
        "band": band,
        "reasons": reasons,
        "marker_path": str(marker_path),
        "marker_present": marker,
        "heartbeat_path": str(heartbeat_path),
        "heartbeat_state": hb_state,
        "heartbeat_age_s": age,
        "stale_after_s": stale_after,
        "status": status,
        "consecutive_failures": failures,
        "cycle_count": hb.get("cycle_count"),
        "pid": pid,
        "pid_state": proc,
        "authority_all_false": (all(v is False for v in hb["authority"].values())
                                if isinstance(hb.get("authority"), dict) and hb["authority"] else None),
    }


# --------------------------------------------------------------------------------------------------------- decide
def decide(prev: Mapping[str, Any], band: str, in_window: bool, cfg: Mapping[str, Any]) -> dict[str, Any]:
    """{action: None|alert|recover|reset, last_alerted_band: <new>}. Pure.

    The dedupe key is the last ALERTED band (None means nothing was ever alerted, read as HEALTHY). Outside the
    window nothing alerts and the alerted band is kept, so a fault that started overnight alerts at 07:00 ET."""
    alert_bands = set(cfg["alert"]["alert_bands"])
    last = prev.get("last_alerted_band") or HEALTHY
    if not in_window:
        return {"action": None, "last_alerted_band": prev.get("last_alerted_band")}
    if band in alert_bands:
        if band != last:
            return {"action": "alert", "last_alerted_band": band}
        return {"action": None, "last_alerted_band": band}
    if band == HEALTHY and last in alert_bands:
        return {"action": "recover", "last_alerted_band": HEALTHY}
    if band == DISABLED and last != DISABLED:
        return {"action": "reset", "last_alerted_band": DISABLED}
    return {"action": None, "last_alerted_band": band if band in (HEALTHY, DISABLED) else last}


def _fmt_age(age: Optional[float]) -> str:
    if age is None:
        return "unknown"
    s = int(age)
    if s < 120:
        return f"{s}s"
    if s < 7200:
        return f"{s // 60}m"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def intent_text(verdict: Mapping[str, Any], action: str) -> tuple[str, str]:
    band = verdict["band"]
    if action == "recover":
        subject = "Active Trader motion runtime RECOVERED"
    else:
        subject = f"Active Trader motion runtime {band}"
    summary = (
        f"{band}: {'; '.join(verdict['reasons']) or 'heartbeat fresh, status healthy'}. heartbeat age "
        f"{_fmt_age(verdict['heartbeat_age_s'])}, status {verdict['status']}, cycles {verdict['cycle_count']}, "
        f"pid {verdict['pid']} {verdict['pid_state']}, marker {'present' if verdict['marker_present'] else 'ABSENT'}. "
        "Watchdog never restarts; runbook docs/ops/packets/active-trader-motion-n8n-20261019/README.md"
    )
    return subject, summary


# --------------------------------------------------------------------------------------------------------- io
def load_state(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) and doc.get("schema") == STATE_SCHEMA else {}
    except (OSError, ValueError):
        return {}


def write_state(path: Path, doc: Mapping[str, Any]) -> None:
    from scripts.lib.atomic_json_store import atomic_write_json

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, dict(doc), indent=1)


def _queue(cfg: Mapping[str, Any], subject: str, summary: str, execution_id: str, ledger: Path, now: float) -> dict:
    """scripts/lib/host_comms_intents.queue_intent (a seam the tests replace)."""
    from scripts.lib.host_comms_intents import queue_intent

    a = cfg["alert"]
    return queue_intent(
        producer=a["producer"], domain=a["domain"], kind=a["kind"], subject=subject, summary=summary,
        execution_id=execution_id, node="check_active_trader_motion_heartbeat", ledger_path=ledger, now=now,
    )


def lane_output(*, error: bool, in_window: bool, window_reason: str) -> dict[str, Any]:
    """LaneRunReceipt@v2 output fields. Pure."""
    if error:
        return {"produced_count": 0, "attempted_count": 1, "skipped_reasons": {SKIP_DEPENDENCY: 1}, "empty_reason": None}
    if in_window:
        return {"produced_count": 1, "attempted_count": 1, "skipped_reasons": {}, "empty_reason": None}
    empty = EMPTY_WINDOW_NOT_REACHED if window_reason == "before_window" else EMPTY_MARKET_CLOSED
    return {"produced_count": 0, "attempted_count": 0, "skipped_reasons": {}, "empty_reason": empty}


def run(
    *,
    apply: bool,
    now: datetime,
    config_path: Optional[Path] = None,
    heartbeat: Optional[Path] = None,
    marker: Optional[Path] = None,
    proc_root: Path = Path("/proc"),
    state_root: Path,
    ledger: Path,
    receipt: Optional[Path] = None,
    session_service: Any = None,
    queue: Any = None,
) -> tuple[int, dict[str, Any]]:
    from scripts.lib import lane_last_receipt as R

    receipt = receipt or R.receipt_path(LANE_ID, state_root)
    summary: dict[str, Any] = {"schema": SCHEMA, "lane_id": LANE_ID, "as_of": now.isoformat(), "mode": "apply" if apply else "dry_run"}
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        summary["error"] = str(exc)
        return _finish(R, apply, receipt, ok=False, summary=summary, now=now,
                       output=lane_output(error=True, in_window=False, window_reason=""))
    hb_path = heartbeat or Path(os.path.expanduser(cfg["heartbeat_path"]))
    marker_path = marker or Path(cfg["marker_path"])
    verdict = evaluate(cfg, now_epoch=now.timestamp(), heartbeat_path=hb_path, marker_path=marker_path,
                       proc_root=proc_root)
    win = window_state(now, cfg, session_service)
    state_path = state_root / cfg["state_rel"]
    prev = load_state(state_path)
    d = decide(prev, verdict["band"], win["in_window"], cfg)
    summary.update(verdict=verdict, window=win, previous_alerted_band=prev.get("last_alerted_band"),
                   action=d["action"], alerted_band=d["last_alerted_band"])
    if d["action"] in ("alert", "recover"):
        summary["intent_subject"], summary["intent_summary"] = intent_text(verdict, d["action"])
    if not apply:
        would = [str(receipt), str(state_path)] + (["comms_intents (host comms-intent path)"]
                                                   if d["action"] in ("alert", "recover") else [])
        R.dry_run_report(LANE_ID, summary, would_write=would, receipt=receipt)
        return 0, summary
    error = None
    if d["action"] in ("alert", "recover"):
        exec_id = _EXEC_ID_RE.sub("_", f"atmw-{now.strftime('%Y%m%dT%H%M%S')}")[:40]
        try:
            summary["intent_receipt"] = (queue or _queue)(cfg, summary["intent_subject"], summary["intent_summary"],
                                                          exec_id, ledger, now.timestamp())
        except Exception as exc:  # noqa: BLE001 — the band stays un-alerted, so the next run tries again
            error = f"intent_queue_failed:{getattr(exc, 'reason', type(exc).__name__)}"
    band_since = prev.get("last_band_since") if prev.get("last_band") == verdict["band"] else now.isoformat()
    new_state = {
        "schema": STATE_SCHEMA,
        "last_observed_at": now.isoformat(),
        "last_band": verdict["band"],
        "last_band_since": band_since,
        "last_alerted_band": prev.get("last_alerted_band") if error else d["last_alerted_band"],
        "last_alerted_at": (now.isoformat() if d["action"] in ("alert", "recover") and not error
                            else prev.get("last_alerted_at")),
        "last_verdict": verdict,
        "last_window": win,
    }
    try:
        write_state(state_path, new_state)
    except Exception as exc:  # noqa: BLE001
        error = error or f"state_write_failed:{type(exc).__name__}"
    if error:
        summary["error"] = error
    out = lane_output(error=bool(error), in_window=win["in_window"], window_reason=win["reason"])
    return _finish(R, True, receipt, ok=not error, summary=summary, now=now, output=out)


def _finish(R: Any, apply: bool, receipt: Path, *, ok: bool, summary: dict[str, Any], now: datetime,
            output: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if not apply:
        R.dry_run_report(LANE_ID, summary, would_write=[], receipt=receipt)
        return (0 if ok else 1), summary
    written = R.write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=now, script=SCRIPT,
                                   summary=summary, error=summary.get("error"), path=receipt, output=output)
    v = summary.get("verdict") or {}
    print(json.dumps({"mode": "apply", "ok": ok, "receipt": str(written) if written else None,
                      "band": v.get("band"), "action": summary.get("action"),
                      "in_window": (summary.get("window") or {}).get("in_window"),
                      "produced_count": output["produced_count"], "empty_reason": output["empty_reason"],
                      "error": summary.get("error")}, default=str))
    if written is None:
        return 1, summary
    return (0 if ok else 1), summary


def _parse_now(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return datetime.now(timezone.utc)
    try:
        d = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.astimezone(timezone.utc) if d.tzinfo else None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: compute and print, write nothing")
    g.add_argument("--apply", action="store_true", help="write the state file and receipt; queue a band-change intent")
    ap.add_argument("--state-root", help="persistent-state root (default: TRADEAI_STATE_ROOT)")
    ap.add_argument("--ledger", help="coordination ledger (default: TRADEAI_N8N_COORDINATION_LEDGER, else state root)")
    ap.add_argument("--config", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--heartbeat", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--marker", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--proc-root", default="/proc", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: ISO 8601, aware
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    now = _parse_now(a.now)
    if now is None:
        print("--now must be an aware ISO 8601 timestamp", file=sys.stderr)
        return 2
    sr = Path(a.state_root) if a.state_root else Path(os.environ.get("TRADEAI_STATE_ROOT") or DEFAULT_STATE_ROOT)
    ledger = Path(a.ledger) if a.ledger else Path(os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER") or sr / LEDGER_REL)
    rc, _ = run(
        apply=bool(a.apply), now=now, config_path=Path(a.config) if a.config else None,
        heartbeat=Path(a.heartbeat) if a.heartbeat else None, marker=Path(a.marker) if a.marker else None,
        proc_root=Path(a.proc_root), state_root=sr, ledger=ledger,
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
