#!/usr/bin/env python3
"""check_market_risk_escalation.py — page when a RED market-risk escalation has stalled (health-tick step).

A RED episode must repeat until the operator acknowledges it (DSN-20261031-market-risk-engine plan §5.8). If the
evaluator that sends those repeats dies, the operator would hear nothing more — the 2026-10-30 failure shape. This
step asks ``escalation.stalled`` whether an OPEN RED episode has had no send receipt for ``stalled_after_min``
(config/market_risk_policy.yaml) and, if so, pages P1 through ``telegram_alert.send_telegram``, re-paging at most every
``repeat_minutes`` (config/market_risk_escalation_stall.json) while the stall persists.

Exit codes (scripts/lib/monitor_exit_codes.py): 0 ok · 3 finding · 1 crash. ``--dry-run`` evaluates and prints what it
would send; it sends nothing and writes no state. Advisory only (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.monitor_exit_codes import EXIT_FINDING, EXIT_OK  # noqa: E402

ET = ZoneInfo("America/New_York")
CONFIG_PATH = PROJECT_ROOT / "config" / "market_risk_escalation_stall.json"


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _state_path(state_root: Path, cfg: dict) -> Path:
    return state_root / cfg["state_rel"]


def load_state(state_root: Path, cfg: dict) -> dict:
    p = _state_path(state_root, cfg)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8") or "{}")


def save_state(state_root: Path, cfg: dict, state: dict) -> None:
    p = _state_path(state_root, cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".stall.", dir=str(p.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def due_to_send(finding: dict, state: dict, now: datetime, cfg: dict) -> bool:
    last = (state.get(finding["episode_id"]) or {}).get("paged_at")
    if not last:
        return True
    return now - datetime.fromisoformat(last) >= timedelta(minutes=float(cfg["repeat_minutes"]))


def render(finding: dict, now: datetime) -> str:
    return (
        "🚨 *MARKET RISK ESCALATION STALLED* — "
        + now.astimezone(ET).strftime("%a %m-%d %H:%M ET")
        + f"\nRED episode {finding['episode_id']} is OPEN and unacknowledged, and no repeat has gone out for "
        f"{finding['minutes_since_last_send']} min (limit {finding['limit_min']} min). The market-risk evaluator may be "
        "down. Open the Risk page, or reply ACK RED once you have seen the alert.\n"
        "Advisory. No order, size or stop level is implied."
    )


def deliver(message: str, cfg: dict) -> tuple[bool, str | None]:
    try:
        from telegram_alert import send_telegram

        ok = send_telegram(
            message,
            priority=cfg["priority"],
            dedupe_minutes=0,
            producer=cfg["producer"],
            message_class=cfg["message_class"],
        )
        return bool(ok), None if ok else "send_telegram returned falsy"
    except Exception as e:  # noqa: BLE001 — surfaced in the output and the exit code, never only logged
        return False, f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="evaluate and print; send nothing, write no state")
    ap.add_argument("--now", help="ISO timestamp (tests); default: now")
    ap.add_argument("--state-root", help="persistent-state root (tests); default: production state root")
    ap.add_argument("--episodes", help="episode store path (tests); default: MARKET_RISK_EPISODES_PATH or the default")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config))
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=ET)

    from lib.market_risk import escalation
    from lib.market_risk.policy import load_policy

    finding = escalation.stalled(now=now, policy=load_policy(), path=Path(args.episodes) if args.episodes else None)
    out: dict = {"now": now.isoformat(), "finding": finding, "sent": False, "dry_run": bool(args.dry_run)}
    if finding:
        if args.state_root:
            state_root = Path(args.state_root)
        else:
            from lib.persistent_state_root import good_persistent_root

            state_root = good_persistent_root()
        state = load_state(state_root, cfg)
        if due_to_send(finding, state, now, cfg):
            message = render(finding, now)
            out["would_send"] = {"priority": cfg["priority"], "message": message}
            if not args.dry_run:
                ok, err = deliver(message, cfg)
                out["sent"], out["delivery_error"] = ok, err
                if ok:
                    state[finding["episode_id"]] = {"paged_at": now.isoformat()}
                    save_state(state_root, cfg, state)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(
            f"[market-risk-stall] {now.astimezone(ET).strftime('%Y-%m-%d %H:%M ET')} "
            f"stalled={bool(finding)} sent={out['sent']}" + (" DRY RUN" if args.dry_run else "")
        )
        if out.get("would_send"):
            print(out["would_send"]["message"])
    if out.get("delivery_error"):
        print(f"[market-risk-stall] DELIVERY FAILED: {out['delivery_error']}", file=sys.stderr)
        return 1
    return EXIT_FINDING if finding else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
