#!/usr/bin/env python3
"""alert_dispatcher_unified.py — Send alerts via Telegram AND email.

Checks for critical system conditions and dispatches notifications:
- Brave budget exhaustion (70%/90%/100%)
- Pipeline critical stage failures
- Data product staleness
- Portfolio risk conditions

Usage:
    python3 scripts/alert_dispatcher_unified.py                # check all and send
    python3 scripts/alert_dispatcher_unified.py --dry-run      # check without sending
    python3 scripts/alert_dispatcher_unified.py --brave-only   # check Brave budget only
"""
import json, os, shutil, sys, subprocess
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
DISPATCH_LOG = PROJECT_ROOT / "logs" / "alert_dispatcher.log"

# Recipients
TELEGRAM_CHAT_IDS = __import__("tg_chat_ids").chat_ids()  # env-sourced, no hardcoded IDs
EMAIL_TO = "john@jwwhiting.com"
GOG_ACCOUNT = "john@jwwhiting.com"


def _load_env():
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _send_telegram(message: str):
    # Route through the audited transport chokepoint (FQDN/v3 normalization, smart split,
    # report capture) instead of a raw urllib request. Pipeline-failure alerts are critical
    # ops — delivered immediately, not gated by the router — so this uses the approved
    # low-level sender directly with the exact configured recipients.
    try:
        from telegram_alert import _raw_send_telegram
        ok = _raw_send_telegram(message, chat_ids=TELEGRAM_CHAT_IDS)
        if not ok:
            print("  [telegram] No bot token or recipients configured")
    except Exception as e:
        print(f"  [telegram] Error: {e}")


def _send_email(subject: str, body: str):
    try:  # FQDN/v3 normalization chokepoint
        from notification_url_builder import publicize_message
        body = publicize_message(body)
    except Exception:
        pass
    kr_path = Path.home() / ".openclaw" / "credentials" / "gog_keyring_password"
    if not kr_path.exists():
        print("  [email] No GOG keyring password")
        return
    env = os.environ.copy()
    env["GOG_KEYRING_PASSWORD"] = kr_path.read_text().strip()
    # cron PATH has no ~/.local/bin, so a bare "gog" fails with ENOENT and the email lane dies
    # silently (every email errored since the cron env change; found in 2026-07-06 log audit)
    gog = shutil.which("gog") or str(Path.home() / ".local" / "bin" / "gog")
    try:
        subprocess.run([
            gog, "gmail", "send",
            "-a", GOG_ACCOUNT,
            "--to", EMAIL_TO,
            "--subject", subject,
            "--body", body,
            "--no-input",
        ], env=env, capture_output=True, text=True, timeout=30)
        print(f"  [email] Sent to {EMAIL_TO}")
    except Exception as e:
        print(f"  [email] Error: {e}")


def _log(msg: str):
    DISPATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(DISPATCH_LOG, "a") as f:
        f.write(f"{datetime.now().isoformat()} {msg}\n")


def check_brave_budget() -> list:
    """Check Brave Search API budget status."""
    alerts = []
    try:
        from brave_search import get_budget_status
        b = get_budget_status()
        pct = b.get("monthly_pct", 0)
        level = b.get("monthly_alert", "ok")
        if level == "critical":
            alerts.append({
                "type": "brave_budget_critical",
                "severity": "critical",
                "message": f"Brave Search API at {pct}% of monthly budget ({b['monthly_total']}/{b['monthly_limit']}). Rate limiting imminent.",
            })
        elif level == "warning":
            alerts.append({
                "type": "brave_budget_warning",
                "severity": "warning",
                "message": f"Brave Search API at {pct}% of monthly budget ({b['monthly_total']}/{b['monthly_limit']}). Consider reducing usage.",
            })
    except Exception as e:
        print(f"  [brave] Error checking budget: {e}")
    return alerts


def check_pipeline_critical() -> list:
    """Check for critical pipeline stage failures."""
    alerts = []
    try:
        from db_adapter import get_connection
        conn = get_connection()
        cur = conn.cursor()
        # D3: aggregate by cause with a count, not one alert per row.
        # "Five identical failures per batch" was never five failures -- it was
        # this query's LIMIT 5 with no aggregation and no dedupe, emitting one
        # critical alert per row, each rendering the SAME stringified exit code
        # under the label "Error:".
        cur.execute("""
            SELECT pipeline_key,
                   COALESCE(summary->>'errors', 'unknown') AS error,
                   COUNT(*) AS n,
                   MIN(started_at) AS first_at,
                   MAX(started_at) AS last_at
            FROM pipeline_runs
            WHERE status = 'failed' AND started_at > NOW() - INTERVAL '4 hours'
              AND COALESCE(trigger_source, 'cron') != 'manual_test'
            GROUP BY pipeline_key, COALESCE(summary->>'errors', 'unknown')
            ORDER BY MAX(started_at) DESC LIMIT 5
        """)
        for key, error, n, first_at, last_at in cur.fetchall():
            times = f"at {last_at}" if n == 1 else f"{n}x, {first_at} to {last_at}"
            alerts.append({
                "type": "pipeline_critical",
                "severity": "critical",
                "message": f"Pipeline FAILED: {key} ({times}). Error: {str(error)[:200]}",
            })

        # E4: A SUCCESS THAT PRODUCED NOTHING IS NOT A SUCCESS.
        #
        # Ten consecutive runs reported status='success' with rows_produced 0
        # while a Finviz outage aged from 64h to 97h, and nothing read it. Fixing
        # the second stage error had removed the ALARM, not the outage: with one
        # error instead of two the orchestrator began exiting 0. AGENTS.md §3 --
        # a green obtained by the wrong artifact is worse than a red, because a
        # red gets investigated.
        cur.execute("""
            SELECT pipeline_key, COUNT(*) AS n, MAX(started_at) AS last_at
            FROM pipeline_runs
            WHERE status = 'success'
              AND started_at > NOW() - INTERVAL '24 hours'
              AND COALESCE(trigger_source, 'cron') != 'manual_test'
              AND COALESCE((summary->>'rows_produced')::bigint, -1) = 0
            GROUP BY pipeline_key
            HAVING COUNT(*) >= 2
            ORDER BY MAX(started_at) DESC LIMIT 5
        """)
        for key, n, last_at in cur.fetchall():
            alerts.append({
                "type": "pipeline_zero_rows",
                "severity": "critical",
                "message": (f"Pipeline produced NOTHING while reporting success: "
                            f"{key} -- {n} runs with rows_produced=0 in 24h, "
                            f"latest {last_at}"),
            })
        conn.close()
    except Exception as e:
        print(f"  [pipeline] Error: {e}")
    return alerts


def check_data_staleness() -> list:
    """Check critical data product freshness. State-transition only (FRESH→STALE / STALE→FRESH)."""
    alerts = []
    now = datetime.now()
    checks = [
        ("holdings.json", STATE_DIR / "holdings.json", 36),  # 36h = hard alert threshold
        ("risk_management.json", STATE_DIR / "risk_management.json", 36),
    ]
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
        from alert_condition_state import observe
    except Exception:
        observe = None
    for label, path, max_h in checks:
        if not path.exists():
            continue
        age_h = (now - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600
        stale = age_h > max_h and now.weekday() < 5
        if observe is not None:
            obs = observe(
                f"data_staleness:{label}",
                f"STALE:{int(age_h)}h" if stale else "FRESH",
                alertable=stale,
            )
            if not obs.get("notify"):
                continue
            if obs.get("action") == "recovered":
                alerts.append({
                    "type": "data_staleness",
                    "severity": "info",
                    "message": f"RECOVERED: {label} is fresh again ({age_h:.0f}h)",
                })
                continue
        if stale:
            alerts.append({
                "type": "data_staleness",
                "severity": "warning",
                "message": f"STALE DATA: {label} is {age_h:.0f}h old (threshold {max_h}h)",
            })
    return alerts


def main():
    _load_env()
    dry_run = "--dry-run" in sys.argv
    brave_only = "--brave-only" in sys.argv

    print(f"[alert-dispatcher] {datetime.now().isoformat()} dry_run={dry_run}")

    all_alerts = []

    if brave_only:
        all_alerts.extend(check_brave_budget())
    else:
        all_alerts.extend(check_brave_budget())
        all_alerts.extend(check_pipeline_critical())
        all_alerts.extend(check_data_staleness())

    if not all_alerts:
        print("  No alerts to dispatch")
        return

    # Build combined message
    lines = [f"Trade AI Alert — {len(all_alerts)} issue(s):", ""]
    for a in all_alerts:
        icon = {"critical": "🔴", "warning": "🟡"}.get(a["severity"], "⚪")
        lines.append(f"{icon} [{a['type']}] {a['message']}")

    message = "\n".join(lines)
    subject = f"Trade AI: {len(all_alerts)} alert(s) — {all_alerts[0]['type']}"

    print(f"\n{message}\n")

    if dry_run:
        print("  [dry-run] Would send Telegram + email")
        return

    _send_telegram(message)
    _send_email(subject, message)
    _log(f"Dispatched {len(all_alerts)} alerts via Telegram + email")
    print(f"  Dispatched {len(all_alerts)} alerts")


if __name__ == "__main__":
    main()
