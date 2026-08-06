#!/usr/bin/env python3
"""defense_engine_gap_checker.py — Defense v10: stale-sector watchdog.

Checks sector_momentum_latest.json for sectors whose as_of exceeds STALE_DAYS.
Logs gaps to a JSON ledger and fires a Telegram alert if any sector is stale.
Runs as a cron job; the desk page reads the gap ledger and display chips.

Design: The frontend "engine gap filed" string (DefenseRedesign.tsx line 119)
previously had NO backend mechanism. This script IS that mechanism.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STALE_DAYS = 5
GAP_LEDGER = ROOT / "data" / "runtime" / "defense_engine_gaps.json"
MOMENTUM_FILE = ROOT / "data" / "runtime" / "sector_momentum_latest.json"


def load_gap_ledger() -> dict:
    try:
        return json.loads(GAP_LEDGER.read_text())
    except Exception:
        return {"gaps": [], "last_check": None}


def save_gap_ledger(ledger: dict):
    GAP_LEDGER.write_text(json.dumps(ledger, default=str, indent=1))


def check_staleness() -> dict:
    """Check all sectors for staleness. Returns dict with {stale: [...], fresh: [...]}."""
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "stale": [], "fresh": []}
    try:
        snap = json.loads(MOMENTUM_FILE.read_text())
    except Exception:
        result["error"] = "momentum file missing or unreadable"
        return result

    rows = snap.get("rows", [])
    if not rows:
        result["error"] = "momentum file has no rows — engine has not run"
        return result

    now = datetime.now(timezone.utc)
    for r in rows:
        as_of = r.get("as_of")
        if not as_of:
            result["stale"].append({"sector": r.get("sector", "unknown"), "etf": r.get("etf", ""),
                                    "as_of": None, "days_stale": None, "note": "no as_of field"})
            continue
        try:
            as_of_dt = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
            if as_of_dt.tzinfo is None:
                as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
            days = (now - as_of_dt).total_seconds() / 86400
        except Exception:
            days = None
        info = {
            "sector": r.get("sector", "unknown"),
            "etf": r.get("etf", ""),
            "as_of": str(as_of),
            "days_stale": round(days, 1) if days is not None else None,
        }
        if days is not None and days > STALE_DAYS:
            result["stale"].append(info)
        else:
            result["fresh"].append(info)
    return result


def update_ledger(result: dict) -> list:
    """Update the gap ledger and return any NEW gaps that appeared since last check."""
    ledger = load_gap_ledger()
    ledger["last_check"] = result["checked_at"]
    prev_stale = {g["etf"] for g in ledger.get("gaps", [])}
    new_gaps = []

    for s in result["stale"]:
        info = {"sector": s["sector"], "etf": s["etf"], "as_of": s["as_of"],
                "days_stale": s["days_stale"], "detected_at": result["checked_at"]}
        if s["etf"] not in prev_stale:
            new_gaps.append(info)

    # Keep gaps that are still stale; drop those that are now fresh
    current_stale_etfs = {s["etf"] for s in result["stale"]}
    ledger["gaps"] = [g for g in ledger.get("gaps", []) if g["etf"] in current_stale_etfs]
    ledger["gaps"].extend(new_gaps)
    save_gap_ledger(ledger)
    return new_gaps


def send_telegram_alert(gaps: list, all_stale: list):
    """Fire Telegram alert for new gaps. Returns True if sent."""
    if not gaps:
        return False
    try:
        import requests
        bot_token = _read_token()
        if not bot_token:
            print("[gap-checker] no TELEGRAM_BOT_TOKEN — skipping alert", flush=True)
            return False
        chat_id = _read_chat_id()
        if not chat_id:
            return False

        gap_lines = [f"  {g['sector']} ({g['etf']}): last refresh {g['as_of']} — {g['days_stale']}d stale"
                     for g in sorted(all_stale, key=lambda x: x.get('days_stale', 0) or 0, reverse=True)]
        msg = (
            "Defense Engine Gap Alert\n"
            f"{len(all_stale)} sector(s) stale >{STALE_DAYS}d\n\n"
            + "\n".join(gap_lines) + "\n\n"
            "Action: POST /api/v2/defense/refresh or verify sector_momentum_engine cron"
        )
        resp = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": msg[:4096], "parse_mode": "Markdown"},
            timeout=10)
        if resp.status_code == 200:
            print(f"[gap-checker] alert sent: {len(all_stale)} stale sectors", flush=True)
            return True
        print(f"[gap-checker] Telegram send failed: {resp.status_code} {resp.text[:200]}", flush=True)
    except Exception as e:
        print(f"[gap-checker] Telegram send error: {e}", flush=True)
    return False


def _read_token() -> str | None:
    import os
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if tok:
        return tok
    try:
        cfg = json.loads((ROOT / "config" / "telegram.json").read_text())
        return cfg.get("bot_token") or cfg.get("botToken") or cfg.get("token")
    except Exception:
        pass
    return None


def _read_chat_id() -> str | None:
    import os
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if cid:
        return cid
    try:
        cfg = json.loads((ROOT / "config" / "telegram.json").read_text())
        return str(cfg.get("chat_id") or cfg.get("chatId") or "")
    except Exception:
        pass
    return None


def main() -> int:
    print("[gap-checker] running", flush=True)
    result = check_staleness()
    if result.get("error"):
        print(f"[gap-checker] {result['error']}", flush=True)
        return 1

    n_stale = len(result["stale"])
    n_fresh = len(result["fresh"])
    print(f"[gap-checker] {n_stale} stale, {n_fresh} fresh sectors", flush=True)

    if n_stale > 0:
        new_gaps = update_ledger(result)
        if new_gaps:
            print(f"[gap-checker] {len(new_gaps)} NEW gap(s) detected", flush=True)
            send_telegram_alert(new_gaps, result["stale"])
        else:
            print("[gap-checker] no new gaps — previously detected", flush=True)
    else:
        # All sectors fresh — clear the gap ledger
        ledger = load_gap_ledger()
        if ledger.get("gaps"):
            print("[gap-checker] all sectors fresh — clearing gap ledger", flush=True)
        ledger["gaps"] = []
        ledger["last_check"] = result["checked_at"]
        save_gap_ledger(ledger)

    return 0


if __name__ == "__main__":
    sys.exit(main())
