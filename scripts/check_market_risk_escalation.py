#!/usr/bin/env python3
"""check_market_risk_escalation.py — page when a RED market-risk escalation has stalled (health-tick step).

A RED episode must repeat until the operator acknowledges it (DSN-20261031-market-risk-engine plan §5.8). The repeats
are sent by the evaluator (scripts/market_risk_evaluate.py); if it dies, the operator hears nothing more — the
2026-10-30 failure shape. This step pages P1 when BOTH hold:

* an OPEN, unacknowledged RED episode exists whose repeats are not finished (``escalation.effective_tier`` RED, under
  ``escalation.repeat_cap``), and
* the evaluator missed a run it was scheduled to make: its run receipt (``evaluator_receipt_rel``, written by every
  scheduled dry or apply run) is older than the latest scheduled slot that is at least ``overdue_after_min`` old.

Outside the evaluator's schedule (nights, weekends, holidays on the trading-day windows) it is silent: send age alone
paged 46 times over one weekend while the evaluator was simply not scheduled (review of #2354). At most
``max_pages_per_episode`` pages per episode, at most one per ``repeat_minutes`` (config/market_risk_escalation_stall.json).

Exit codes (scripts/lib/monitor_exit_codes.py): 0 ok · 3 finding · 1 delivery failed or crash. ``--dry-run`` evaluates
and prints what it would send; it sends nothing and writes no state. Advisory only (MBI_BEHAVIOR = 0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.monitor_exit_codes import EXIT_FINDING, EXIT_OK  # noqa: E402

ET = ZoneInfo("America/New_York")
CONFIG_PATH = PROJECT_ROOT / "config" / "market_risk_escalation_stall.json"


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _hm(s: str) -> time:
    h, m = (int(x) for x in str(s).split(":"))
    return time(h, m)


def _parse(s) -> datetime | None:
    if not s:
        return None
    t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def last_due_slot(now: datetime, cfg: dict) -> datetime | None:
    """The latest evaluator slot that is at least ``overdue_after_min`` old, if ``now`` is inside a scheduled window
    (from its first slot + overdue to its last slot + overdue). None outside the schedule."""
    from lib.market_risk.sessions import is_trading_day

    local = now.astimezone(ET)
    lag = timedelta(minutes=float(cfg["overdue_after_min"]))
    # the health tick fires a few seconds after its minute; one tick interval of slack keeps the last slot of a window
    # (weekday 20:00, Sunday 18:30) checkable (review of #2411, M4)
    tick = timedelta(minutes=float(cfg.get("tick_interval_min") or 15))
    best = None
    for win in cfg["schedule"]:
        day = local.date()
        if day.weekday() not in win["weekdays"]:
            continue
        if win.get("trading_days_only") and not is_trading_day(day):
            continue
        start = datetime.combine(day, _hm(win["start"]), ET)
        end = datetime.combine(day, _hm(win["end"]), ET)
        if not (start + lag <= local <= end + lag + tick):
            continue
        step = timedelta(minutes=float(win.get("every_min") or 15))
        slot, latest = start, None
        while slot <= end and slot <= local - lag:
            latest, slot = slot, slot + step
        if latest and (best is None or latest > best):
            best = latest
    return best


def find(now: datetime, cfg: dict, *, state_root: Path, episodes: Path | None) -> dict | None:
    from lib.market_risk import escalation
    from lib.market_risk.policy import load_policy

    ep = escalation.open_episode(escalation.load(episodes))
    if ep is None or ep.get("status") != "OPEN" or escalation.effective_tier(ep) != "RED":
        return None
    if int(ep.get("repeats") or 0) >= escalation.repeat_cap("RED", load_policy().get("escalation") or {}):
        return None
    due = last_due_slot(now, cfg)
    if due is None:
        return None
    ran, receipt_note = read_receipt(state_root / cfg["evaluator_receipt_rel"], now, cfg)
    if ran is not None and ran >= due:
        return None
    return {
        "episode_id": ep["id"],
        "episode_anchor": str(ep.get("anchor_at") or ep.get("opened_at") or ""),
        "tier": "RED",
        "due_slot": due.isoformat(),
        "evaluator_last_run": ran.isoformat() if ran else None,
        "receipt_note": receipt_note,
    }


def read_receipt(path: Path, now: datetime, cfg: dict) -> tuple[datetime | None, str]:
    """The evaluator's last finished run, or (None, why). An unreadable receipt (torn JSON, a non-object, a bad
    timestamp) counts as stale — the step pages instead of crashing (review of #2411, M5); a receipt dated in the
    future beyond ``future_skew_s`` is suspicious and also counts as stale, never as fresh (M7)."""
    if not path.exists():
        return None, "no run receipt"
    try:
        doc = json.loads(path.read_text(encoding="utf-8") or "null")
        if not isinstance(doc, dict):
            return None, "run receipt is not an object"
        ran = _parse(doc.get("finished_at") or doc.get("started_at"))
    except (OSError, ValueError, TypeError) as exc:
        return None, f"run receipt unreadable ({type(exc).__name__})"
    if ran is None:
        return None, "run receipt has no run time"
    if ran > now + timedelta(seconds=float(cfg.get("future_skew_s") or 120)):
        return None, f"run receipt dated in the future ({ran.isoformat()})"
    return ran, ""


def _state_path(state_root: Path, cfg: dict) -> Path:
    return state_root / cfg["state_rel"]


def load_state(state_root: Path, cfg: dict) -> dict:
    """The page ledger. An unreadable one is archived beside itself (never deleted, AGENTS §0 rule 6) and read as
    empty, so the step still pages and then caps from the fresh ledger (review of #2411, M5)."""
    p = _state_path(state_root, cfg)
    if not p.exists():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8") or "{}")
        if isinstance(doc, dict) and all(isinstance(v, dict) for v in doc.values()):
            return doc
        why = "not an object of objects"
    except (OSError, ValueError) as exc:
        why = type(exc).__name__
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        p.replace(p.with_name(f"{p.name}.corrupt-{stamp}"))
    except OSError:
        pass  # a dry run on a read-only root: read as empty anyway
    print(f"[market-risk-stall] WARNING page ledger unreadable ({why}); archived and read as empty", file=sys.stderr)
    return {}


def _peek_state(state_root: Path, cfg: dict) -> dict:
    """Read-only view for --dry-run: never archives or rewrites anything."""
    p = _state_path(state_root, cfg)
    try:
        doc = json.loads(p.read_text(encoding="utf-8") or "{}") if p.exists() else {}
        return doc if isinstance(doc, dict) and all(isinstance(v, dict) for v in doc.values()) else {}
    except (OSError, ValueError):
        return {}


def cap_key(finding: dict) -> str:
    """The page cap belongs to one opening of one episode: a re-opened episode (new anchor) gets a fresh cap (M6)."""
    return f"{finding['episode_id']}@{finding.get('episode_anchor') or ''}"


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
    rec = state.get(cap_key(finding)) or {}
    if int(rec.get("pages") or 0) >= int(cfg["max_pages_per_episode"]):
        return False
    last = rec.get("paged_at")
    return not last or now - datetime.fromisoformat(last) >= timedelta(minutes=float(cfg["repeat_minutes"]))


def render(finding: dict, now: datetime, page_no: int, cfg: dict) -> str:
    ran = _parse(finding.get("evaluator_last_run"))
    ran_txt = ran.astimezone(ET).strftime("%a %H:%M ET") if ran else "never"
    due_txt = _parse(finding["due_slot"]).astimezone(ET).strftime("%H:%M ET")
    return (
        "🚨 *MARKET RISK ESCALATION STALLED* — "
        + now.astimezone(ET).strftime("%a %m-%d %H:%M ET")
        + f" (page {page_no} of {cfg['max_pages_per_episode']})"
        + f"\nRED episode {finding['episode_id']} is OPEN and unacknowledged, but the market-risk evaluator that sends "
        f"its repeats missed its {due_txt} run (last run {ran_txt}"
        + (f"; {finding['receipt_note']}" if finding.get("receipt_note") else "")
        + "). Open the Risk page, or reply ACK RED once you "
        "have seen the alert.\nAdvisory. No order, size or stop level is implied."
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
    if args.state_root:
        state_root = Path(args.state_root)
    else:
        from lib.persistent_state_root import good_persistent_root

        state_root = good_persistent_root()

    finding = find(now, cfg, state_root=state_root, episodes=Path(args.episodes) if args.episodes else None)
    out: dict = {"now": now.isoformat(), "finding": finding, "sent": False, "dry_run": bool(args.dry_run)}
    if finding:
        state = load_state(state_root, cfg) if not args.dry_run else _peek_state(state_root, cfg)
        if due_to_send(finding, state, now, cfg):
            page_no = int((state.get(cap_key(finding)) or {}).get("pages") or 0) + 1
            message = render(finding, now, page_no, cfg)
            out["would_send"] = {"priority": cfg["priority"], "message": message}
            if not args.dry_run:
                ok, err = deliver(message, cfg)
                out["sent"], out["delivery_error"] = ok, err
                if ok:
                    state[cap_key(finding)] = {"paged_at": now.isoformat(), "pages": page_no}
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
