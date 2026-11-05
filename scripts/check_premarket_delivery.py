#!/usr/bin/env python3
"""check_premarket_delivery.py — dead-man for the pre-market stack (health-tick step).

On a market day the operator must receive the pre-market stack before the open: the 05:45 ET
premarket pipeline (FRED, regime collector/classifier, catalysts) must leave a receipt, and the
07:30 ET morning brief must leave a delivery row. On 2026-10-30 neither happened (disk full at
05:45, brief API dead at 07:30) and nothing paged; the first operator message of the day was the
stop-fill alert at 10:10 ET (docs/audits/MARKET_SELLOFF_ALERT_RCA_2026-10-30.md, finding 7).

This step pages P1 (operator-action intent, dedupe window 0, AGENTS.md §9.1) when, on a trading
day:
  * after `pipeline_due_et`, the pipeline receipt is absent, from a previous day, or failed;
  * after `brief_due_et`, no outbound communication event matching `brief_match` exists today.
It repeats every `repeat_minutes` up to `max_repeats` while the condition persists (state file),
and is silent before the deadlines, after `window_end_et`, and on weekends/holidays.

Exit codes (scripts/lib/monitor_exit_codes.py): 0 ok · 3 finding · 1 crash. Writes the
LaneRunReceipt for `premarket-delivery-deadman` on every run so its own silence is visible.
`--dry-run` evaluates and prints what it would send; it writes no state and sends nothing.
All thresholds live in config/premarket_delivery_deadman.json (AGENTS.md: no hardcoded values).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.monitor_exit_codes import EXIT_FINDING, EXIT_OK  # noqa: E402

ET = ZoneInfo("America/New_York")
CONFIG_PATH = PROJECT_ROOT / "config" / "premarket_delivery_deadman.json"
PRODUCER = "check_premarket_delivery"


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _hm(now_et: datetime, hm: str) -> datetime:
    h, m = (int(x) for x in hm.split(":"))
    return now_et.replace(hour=h, minute=m, second=0, microsecond=0)


def _receipt_day_et(receipt: dict | None) -> str | None:
    """ET calendar day the receipt's run started on, or None when unreadable."""
    if not isinstance(receipt, dict):
        return None
    for key in ("started_at", "run_ts_utc"):
        raw = receipt.get(key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        return dt.astimezone(ET).strftime("%Y-%m-%d")
    return None


def evaluate(now_et: datetime, receipt: dict | None, brief_rows: int | None, cfg: dict) -> list[dict]:
    """Pure: decide the findings for this moment. `brief_rows` None = the ledger could not be read."""
    findings: list[dict] = []
    today = now_et.strftime("%Y-%m-%d")
    if now_et >= _hm(now_et, cfg["window_end_et"]):
        return findings
    if now_et >= _hm(now_et, cfg["pipeline_due_et"]):
        day = _receipt_day_et(receipt)
        if receipt is None:
            findings.append(
                {
                    "key": "PREMARKET_PIPELINE_MISSING",
                    "priority": "P1",
                    "detail": f"no receipt at {cfg['pipeline_receipt_rel']}",
                }
            )
        elif day != today:
            findings.append(
                {
                    "key": "PREMARKET_PIPELINE_MISSING",
                    "priority": "P1",
                    "detail": f"latest receipt is from {day or 'unknown'} (started_at {receipt.get('started_at')}); "
                    f"nothing ran after {cfg['pipeline_started_after_et']} ET today",
                }
            )
        elif receipt.get("overall_status") == "failed" or receipt.get("receipt_complete") is False:
            findings.append(
                {
                    "key": "PREMARKET_PIPELINE_FAILED",
                    "priority": "P1",
                    "detail": f"overall_status={receipt.get('overall_status')} receipt_complete={receipt.get('receipt_complete')} "
                    f"steps {receipt.get('step_count')}/{receipt.get('expected_step_count')}",
                }
            )
    if now_et >= _hm(now_et, cfg["brief_due_et"]):
        if brief_rows is None:
            findings.append(
                {
                    "key": "MORNING_BRIEF_CHECK_UNAVAILABLE",
                    "priority": "P2",
                    "detail": "communication_events could not be read — delivery is UNKNOWN, not confirmed",
                }
            )
        elif brief_rows == 0:
            findings.append(
                {
                    "key": "MORNING_BRIEF_NOT_DELIVERED",
                    "priority": "P1",
                    "detail": f"no outbound event matching '{cfg['brief_match']}' since 00:00 ET today "
                    f"(due {cfg['brief_due_et']} ET)",
                }
            )
    return findings


def load_receipt(state_root: Path, cfg: dict) -> dict | None:
    p = state_root / cfg["pipeline_receipt_rel"]
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def count_brief_rows(now_et: datetime, cfg: dict) -> int | None:
    """Outbound comms events today matching the brief. None when the ledger is unreadable (unknown ≠ zero)."""
    try:
        import db_adapter  # the same read path every lane uses; credentials come from its own bootstrap

        start = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = db_adapter._execute(
            "SELECT COUNT(*) AS n FROM communication_events WHERE created_at >= %s AND direction <> 'INBOUND' "
            "AND (COALESCE(short_summary,'') || ' ' || COALESCE(sanitized_body,'')) ILIKE %s",
            (start, f"%{cfg['brief_match']}%"),
            fetch="all",
        )
        if not rows:
            return None
        row = rows[0]
        return int(row["n"] if isinstance(row, dict) else row[0])
    except Exception:  # noqa: BLE001 — unknown is reported as unknown, never as zero
        return None


def _state_path(state_root: Path, cfg: dict) -> Path:
    return state_root / cfg["state_rel"]


def load_state(state_root: Path, cfg: dict) -> dict:
    try:
        return json.loads(_state_path(state_root, cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state_root: Path, cfg: dict, state: dict) -> None:
    p = _state_path(state_root, cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def due_to_send(finding: dict, state: dict, now_et: datetime, cfg: dict) -> bool:
    """First occurrence today sends; then every repeat_minutes up to max_repeats while it persists."""
    rec = state.get(f"{now_et.strftime('%Y-%m-%d')}:{finding['key']}")
    if not rec:
        return True
    if int(rec.get("repeats", 0)) >= int(cfg["max_repeats"]):
        return False
    last = datetime.fromisoformat(rec["last_sent"])
    return now_et - last >= timedelta(minutes=int(cfg["repeat_minutes"]))


def mark_sent(finding: dict, state: dict, now_et: datetime) -> None:
    k = f"{now_et.strftime('%Y-%m-%d')}:{finding['key']}"
    rec = state.get(k) or {"first_sent": now_et.isoformat(), "repeats": -1}
    rec["last_sent"] = now_et.isoformat()
    rec["repeats"] = int(rec.get("repeats", -1)) + 1
    state[k] = rec


def render(findings: list[dict], now_et: datetime, repeat_no: dict[str, int]) -> str:
    lines = ["🚨 *PRE-MARKET STACK DEAD-MAN* — " + now_et.strftime("%a %m-%d %H:%M ET")]
    for f in findings:
        rep = repeat_no.get(f["key"], 0)
        tag = f" (repeat {rep})" if rep else ""
        lines.append(f"• *{f['key']}*{tag}: {f['detail']}")
    lines.append(
        "The operator may have received nothing this morning. Check Ops → Incidents and the Risk page; "
        "the market-risk evaluation on the independent host path is unaffected by this failure."
    )
    return "\n".join(lines)


def deliver(message: str, priority: str) -> tuple[bool, str | None]:
    try:
        from telegram_alert import send_telegram

        ok = send_telegram(message, priority=priority, dedupe_minutes=0, producer=PRODUCER)
        return bool(ok), None if ok else "send_telegram returned falsy"
    except Exception as e:  # noqa: BLE001 — recorded on the receipt, never only logged
        return False, f"{type(e).__name__}: {e}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="evaluate and print; send nothing, write no state")
    ap.add_argument("--now", help="ISO timestamp (tests); default: now in America/New_York")
    ap.add_argument("--state-root", help="persistent-state root (tests); default: production_state_root()")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_config(Path(args.config))
    now_et = datetime.fromisoformat(args.now) if args.now else datetime.now(ET)
    if now_et.tzinfo is None:
        now_et = now_et.replace(tzinfo=ET)
    now_et = now_et.astimezone(ET)
    started = datetime.now(ET)

    if args.state_root:
        state_root = Path(args.state_root)
    else:
        from lib.persistent_state_root import good_persistent_root

        state_root = good_persistent_root()

    from market_session import is_trading_day

    out: dict = {
        "now_et": now_et.isoformat(),
        "trading_day": bool(is_trading_day(now_et)),
        "findings": [],
        "sent": [],
        "dry_run": bool(args.dry_run),
    }
    findings: list[dict] = []
    if out["trading_day"]:
        receipt = load_receipt(state_root, cfg)
        brief_rows = count_brief_rows(now_et, cfg) if now_et >= _hm(now_et, cfg["brief_due_et"]) else 0
        out["receipt_day_et"] = _receipt_day_et(receipt)
        out["brief_rows"] = brief_rows
        findings = evaluate(now_et, receipt, brief_rows, cfg)
    out["findings"] = findings

    delivery_error = None
    if findings:
        state = load_state(state_root, cfg)
        due = [f for f in findings if due_to_send(f, state, now_et, cfg)]
        if due:
            repeat_no = {
                f["key"]: int((state.get(f"{now_et.strftime('%Y-%m-%d')}:{f['key']}") or {}).get("repeats", -1)) + 1
                for f in due
            }
            priority = "P1" if any(f["priority"] == "P1" for f in due) else "P2"
            message = render(due, now_et, repeat_no)
            out["would_send"] = {"priority": priority, "message": message}
            if not args.dry_run:
                ok, delivery_error = deliver(message, priority)
                out["sent"] = [f["key"] for f in due] if ok else []
                out["delivery_error"] = delivery_error
                if ok:
                    for f in due:
                        mark_sent(f, state, now_et)
                    save_state(state_root, cfg, state)

    rc = EXIT_FINDING if findings else EXIT_OK
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(
            f"[premarket-deadman] {now_et.strftime('%Y-%m-%d %H:%M ET')} trading_day={out['trading_day']} "
            f"findings={[f['key'] for f in findings]} sent={out['sent']}" + (" DRY RUN" if args.dry_run else "")
        )
        if out.get("would_send"):
            print(out["would_send"]["message"])
    if not args.dry_run:
        try:
            from lib.lane_last_receipt import write_lane_receipt

            write_lane_receipt(
                cfg["lane_id"],
                ok=(delivery_error is None),
                exit_code=rc,
                started_at=started,
                summary={
                    "findings": [f["key"] for f in findings],
                    "sent": out["sent"],
                    "delivery_error": delivery_error,
                    "trading_day": out["trading_day"],
                },
            )
        except Exception as e:  # noqa: BLE001
            print(f"[premarket-deadman] WARNING receipt write failed: {e}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
