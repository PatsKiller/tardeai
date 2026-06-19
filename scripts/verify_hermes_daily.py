#!/usr/bin/env python3
"""verify_hermes_daily.py — one-shot watchdog (tonight 2026-06-19 ~23:20) confirming the daily hermes
auto-commit cron (23:13) ran. Reads its log + today's git history, Telegrams the verdict, removes its own
cron line so it runs once. Safe to run manually."""
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / "commit_hermes_daily.log"


def _sh(args):
    try:
        return subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True, timeout=30).stdout
    except Exception as e:
        return f"(cmd err: {e})"


def build_report() -> str:
    today = date.today().isoformat()
    # today's hermes auto-commit in git?
    commits = _sh(["git", "log", "--since", f"{today} 00:00", "--oneline", "--grep", "hermes: auto-commit daily"])
    log_tail = ""
    try:
        lines = [l for l in LOG.read_text().splitlines() if "[hermes-daily]" in l]
        log_tail = "\n".join(lines[-4:])
    except Exception:
        log_tail = "(no log file yet)"

    lines = ["\U0001f50e HERMES DAILY AUTO-COMMIT — tonight's result"]
    if commits.strip():
        lines.append("✅ ran + committed:")
        for c in commits.strip().splitlines()[:3]:
            lines.append(f"  {c}")
    elif "no hermes changes today" in log_tail:
        lines.append("✓ ran, nothing to commit (no new hermes reports today).")
    elif "commit blocked" in log_tail:
        lines.append("⚠️ commit BLOCKED (secret hook or error) — left staged. Check logs/commit_hermes_daily.log.")
    elif "IRON RULE failed" in log_tail:
        lines.append("⛔ IRON RULE failed (holdings guard) — cron aborted, did NOT commit.")
    else:
        lines.append("⚠️ no evidence the 23:13 cron ran tonight. Check logs/commit_hermes_daily.log + crontab.")
    if log_tail and log_tail != "(no log file yet)":
        lines.append("log: " + log_tail.replace("\n", " · "))
    return "\n".join(lines)


def _self_remove_cron():
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if cur.returncode != 0:
            return
        kept = [ln for ln in cur.stdout.splitlines() if "verify_hermes_daily.py" not in ln]
        subprocess.run(["crontab", "-"], input="\n".join(kept) + "\n", text=True)
    except Exception:
        pass


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(str(ROOT / ".env"))
    except Exception:
        pass
    report = build_report()
    print(report)
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alert import send_telegram
        send_telegram(report, bypass_router=True)
    except Exception as e:
        print(f"(telegram failed: {e})")
    if "--keep-cron" not in sys.argv:
        _self_remove_cron()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
