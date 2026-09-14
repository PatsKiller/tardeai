#!/usr/bin/env python3
"""cio_bridge_watchdog.py — keep the governed model bridge answering. Dry run by default.

WHY
---
2026-09-14:
- **The stall.** From 14:45 ET, DeepSeek held the bridge's non-streaming requests open for about 906 s each.
  It trickled keep-alive bytes and then returned a 50-character body with no usage. `requests`' 90 s read
  timeout never fired, because bytes kept arriving.
- **The wedge.** The bridge was a single-threaded `HTTPServer`, so each held call blocked every other
  caller: CIO Hermes research, desk answers, advisory opinions.
- **The cost.** For about 90 minutes every CIO Hermes job failed ("timed out" / "bridge unreachable"), and
  `/health` did not exist (501), so nothing noticed. The queue lane only saw a failure rate.

WHAT
----
Probes `GET /health` on the bridge (5 s) and classifies:

    OK             answers, nothing unusual
    BUSY_UPSTREAM  answers, but the oldest in-flight call is older than the upstream deadline
    CIRCUIT_OPEN   answers, but the provider circuit breaker is open (provider failing)
    WEDGED         no answer at all (timeout, refused, reset)

With `--apply`:
- After `--wedged-threshold` consecutive WEDGED probes it restarts `cio-governed-bridge.service`, at most
  once per `--restart-cooldown-min`, and re-probes.
- Any change into a non-OK state, or back to OK, sends one operator alert. A provider problem
  (CIRCUIT_OPEN, BUSY_UPSTREAM) is alerted but never "fixed" by a restart — a restart does not shorten
  the provider's queue.
- Every run writes `data/runtime/cio_bridge_watchdog.json`.

AUTHORITY: READ_ONLY_ADVISORY. Restarts one loopback service; never touches brokers, orders, keys or caps.
MBI_BEHAVIOR = 0.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

AUTHORITY = "READ_ONLY_ADVISORY"
UNIT = "cio-governed-bridge.service"
STATE = PROJECT_ROOT / "data" / "runtime" / "cio_bridge_watchdog.json"
NO_CONSUMER_REASON = "scheduled self-heal lane; research_lane_health reads the receipt, Telegram carries the alert"

OK, BUSY_UPSTREAM, CIRCUIT_OPEN, WEDGED = "OK", "BUSY_UPSTREAM", "CIRCUIT_OPEN", "WEDGED"


def bridge_url() -> str:
    return (os.getenv("CIO_GOVERNED_BRIDGE_URL") or "http://127.0.0.1:8766").rstrip("/")


def probe(url: Optional[str] = None, timeout_s: float = 5.0) -> dict[str, Any]:
    """One GET /health. Never raises: a failure is a result."""
    target = f"{url or bridge_url()}/health"
    try:
        with urllib.request.urlopen(target, timeout=timeout_s) as resp:  # noqa: S310 -- loopback bridge
            body = json.loads(resp.read().decode("utf-8") or "{}")
            return {"answered": True, "http": resp.status, "body": body}
    except urllib.error.HTTPError as exc:
        # An HTTP error still proves the server loop is alive (the pre-fix bridge answered 501).
        return {"answered": True, "http": exc.code, "body": {}, "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001 -- timeout, refused, reset: all mean "not answering"
        return {"answered": False, "http": None, "body": {}, "error": f"{type(exc).__name__}: {exc}"[:200]}


def classify(p: dict[str, Any]) -> str:
    if not p.get("answered"):
        return WEDGED
    body = p.get("body") or {}
    if body.get("circuit_open"):
        return CIRCUIT_OPEN
    oldest = body.get("oldest_inflight_s")
    deadline = body.get("upstream_deadline_s")
    if oldest is not None and deadline is not None and float(oldest) > float(deadline) + 30:
        return BUSY_UPSTREAM
    return OK


def decide(
    status: str, state: dict[str, Any], *, now: datetime, wedged_threshold: int, restart_cooldown_s: float
) -> dict[str, Any]:
    """Pure. What to do about this probe, given what previous runs recorded."""
    consecutive = int(state.get("consecutive_wedged") or 0) + 1 if status == WEDGED else 0
    last_restart = state.get("last_restart_at")
    cooled = True
    if last_restart:
        try:
            cooled = (now - datetime.fromisoformat(last_restart)).total_seconds() >= restart_cooldown_s
        except ValueError:
            cooled = True
    restart = status == WEDGED and consecutive >= wedged_threshold and cooled
    alert = status != (state.get("last_status") or OK)
    return {
        "status": status,
        "consecutive_wedged": consecutive,
        "restart": restart,
        "restart_blocked_by_cooldown": status == WEDGED and consecutive >= wedged_threshold and not cooled,
        "alert": alert,
    }


def restart_unit(run: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    r = run(["systemctl", "--user", "restart", UNIT], capture_output=True, text=True, timeout=60)
    return {"rc": getattr(r, "returncode", None), "stderr": (getattr(r, "stderr", "") or "")[:200]}


def alert_text(
    decision: dict[str, Any], p: dict[str, Any], restarted: Optional[dict[str, Any]], after: Optional[dict[str, Any]]
) -> str:
    status = decision["status"]
    body = p.get("body") or {}
    lines = {
        OK: "✅ <b>Model bridge answering again</b>",
        WEDGED: "🚨 <b>Model bridge not answering</b>",
        CIRCUIT_OPEN: "⚠️ <b>Model provider failing — bridge circuit open</b>",
        BUSY_UPSTREAM: "⚠️ <b>Model provider holding requests</b>",
    }
    out = [lines.get(status, status)]
    if status == WEDGED:
        out.append(
            f"No reply from /health for {decision['consecutive_wedged']} probe(s): {p.get('error') or 'no answer'}."
        )
        out.append("CIO research, desk answers and advisory opinions all wait on this bridge.")
    elif status == CIRCUIT_OPEN:
        out.append(
            f"Last provider error: {body.get('last_error') or 'unknown'}. Callers fail fast and research replays later."
        )
    elif status == BUSY_UPSTREAM:
        out.append(
            f"Oldest call in flight {body.get('oldest_inflight_s')} s (deadline {body.get('upstream_deadline_s')} s)."
        )
    if restarted is not None:
        healthy = bool(after and after.get("answered"))
        out.append(
            f"Restarted {UNIT} (rc={restarted.get('rc')}); /health after restart: "
            f"{'answering' if healthy else 'still not answering'}."
        )
    elif decision.get("restart_blocked_by_cooldown"):
        out.append("A restart ran recently; not restarting again inside the cooldown.")
    out.append(f"<i>Bridge watchdog · {AUTHORITY}</i>")
    return "\n".join(out)


def _load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def run_once(
    *,
    apply: bool,
    state_path: Path = STATE,
    now: Optional[datetime] = None,
    prober: Callable[[], dict[str, Any]] = probe,
    restarter: Callable[[], dict[str, Any]] = restart_unit,
    sender: Optional[Callable[..., Any]] = None,
    wedged_threshold: int = 2,
    restart_cooldown_s: float = 1800.0,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    state = _load_state(state_path)
    p = prober()
    decision = decide(
        classify(p), state, now=now, wedged_threshold=wedged_threshold, restart_cooldown_s=restart_cooldown_s
    )
    restarted = after = None
    if apply and decision["restart"]:
        restarted = restarter()
        after = prober()
        state["last_restart_at"] = now.isoformat()
    alerted = None
    if apply and (decision["alert"] or restarted is not None):
        if sender is None:
            from telegram_alert import send_telegram as sender  # noqa: PLC0415
        alerted = bool(sender(alert_text(decision, p, restarted, after), message_class="ops"))
    receipt = {
        "schema": "CioBridgeWatchdog@v1",
        "authority": AUTHORITY,
        "checked_at": now.isoformat(),
        "mode": "apply" if apply else "dry_run",
        "status": decision["status"],
        "consecutive_wedged": decision["consecutive_wedged"],
        "probe": p,
        "would_restart": decision["restart"],
        "restarted": restarted,
        "after_restart": after,
        "alert_needed": decision["alert"],
        "alerted": alerted,
        "last_status": decision["status"] if apply else state.get("last_status"),
        "last_restart_at": state.get("last_restart_at"),
    }
    if apply:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")
    return receipt


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="restart when wedged and send alerts (default: dry run)")
    ap.add_argument("--wedged-threshold", type=int, default=int(os.getenv("CIO_BRIDGE_WEDGED_THRESHOLD", "2")))
    ap.add_argument(
        "--restart-cooldown-min", type=float, default=float(os.getenv("CIO_BRIDGE_RESTART_COOLDOWN_MIN", "30"))
    )
    args = ap.parse_args(argv)
    receipt = run_once(
        apply=args.apply, wedged_threshold=args.wedged_threshold, restart_cooldown_s=args.restart_cooldown_min * 60
    )
    print(json.dumps(receipt, indent=2, default=str))
    return 0 if receipt["status"] in (OK, BUSY_UPSTREAM, CIRCUIT_OPEN) or receipt.get("restarted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
