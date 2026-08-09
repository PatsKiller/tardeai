#!/usr/bin/env python3
"""
system_health_alerts.py

Checks Trade AI system health and sends Telegram warnings when:
- any state freshness file is stale/failing
- reliability score is degraded
- high-impact decisions should be blocked
- critical agent dependencies are missing/bad

Always writes:
- data/portfolios/state/system_health_alert.json
- logs/system_health_alerts.log

Sends Telegram only if credentials exist in .env.
"""

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = PROJECT_ROOT / "data/portfolios/state"
LOG_DIR = PROJECT_ROOT / "logs"
ENV_FILE = PROJECT_ROOT / ".env"

AGENTS = ["maria", "steph", "risk_agent", "tax_agent", "orchestrator"]


def load_env():
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def db_env_ok():
    return all(os.environ.get(k) for k in ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"])


def run_psql_json(sql):
    if not db_env_ok():
        return []

    env = os.environ.copy()
    env["PGPASSWORD"] = os.environ["DB_PASSWORD"]

    proc = subprocess.run(
        [
            "psql",
            "-h", os.environ["DB_HOST"],
            "-p", os.environ["DB_PORT"],
            "-U", os.environ["DB_USER"],
            "-d", os.environ["DB_NAME"],
            "-t",
            "-A",
            "-c",
            sql,
        ],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        env=env,
    )

    if proc.returncode != 0:
        return [{"error": proc.stderr.strip()}]

    out = proc.stdout.strip()
    if not out:
        return []
    try:
        return json.loads(out)
    except Exception:
        return [{"raw": out}]


def get_latest_freshness():
    sql = """
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
    FROM (
      SELECT state_file, ok, age_hours, max_age_hours, source_script, checked_at
      FROM latest_state_freshness
      ORDER BY state_file
    ) t;
    """
    return run_psql_json(sql)


def get_recent_failures(hours=24):
    sql = f"""
    SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json)
    FROM (
      SELECT state_file,
             COUNT(*) FILTER (WHERE ok = false) AS bad_checks,
             COUNT(*) AS total_checks,
             MAX(checked_at) AS latest_check
      FROM state_freshness_history
      WHERE checked_at >= now() - interval '{int(hours)} hours'
      GROUP BY state_file
      HAVING COUNT(*) FILTER (WHERE ok = false) > 0
      ORDER BY bad_checks DESC, state_file
    ) t;
    """
    return run_psql_json(sql)


def get_agent_reliability():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    try:
        from agent_reliability import get_agent_reliability
        from reliability_decision_control import apply_reliability_controls

        rows = []
        for agent in AGENTS:
            rel = get_agent_reliability(agent)
            route = {
                "to_agent": agent,
                "action_type": "pending_write",
                "high_impact": True,
                "reliability": rel,
                "pending_actions": [],
                "reviewers": [],
            }
            controlled = apply_reliability_controls(route)
            rows.append({
                "agent": agent,
                "reliability_score": rel.get("reliability_score"),
                "confidence_adjustment": rel.get("confidence_adjustment"),
                "warnings": rel.get("warnings"),
                "control_mode": controlled.get("reliability_controls", {}).get("mode"),
                "blocked": controlled.get("reliability_controls", {}).get("blocked"),
                "requires_manual_approval": controlled.get("reliability_controls", {}).get("requires_manual_approval"),
                "reasons": controlled.get("reliability_controls", {}).get("reasons"),
            })
        return rows
    except Exception as exc:
        return [{"agent": "system", "error": str(exc)}]


def telegram_config():
    token_keys = [
        "TELEGRAM_BOT_TOKEN",
        "TG_BOT_TOKEN",
        "TELEGRAM_TOKEN",
        "BOT_TOKEN",
    ]
    chat_keys = [
        "TELEGRAM_CHAT_ID",
        "TG_CHAT_ID",
        "TELEGRAM_USER_ID",
        "CHAT_ID",
    ]

    token = next((os.environ.get(k) for k in token_keys if os.environ.get(k)), None)
    chat_id = next((os.environ.get(k) for k in chat_keys if os.environ.get(k)), None)
    return token, chat_id


def send_telegram(text):
    """Send via the centralized telegram_alert router (outbox, dedup, report capture).
    Falls back to direct urllib only if the router import fails (e.g. missing deps)."""
    try:
        from telegram_alert import send_telegram as router_send
        ok = router_send(text)
        return {"sent": ok, "via": "router"}
    except Exception:
        pass

    # Fallback: direct urllib to Telegram (legacy path — no router/outbox/dedup)
    token, chat_id = telegram_config()
    if not token or not chat_id:
        return {"sent": False, "reason": "missing Telegram token/chat id in .env"}

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chat_ids = [c.strip() for c in chat_id.split(",") if c.strip()]
    last_result = {"sent": False, "reason": "no chat IDs"}

    for cid in chat_ids:
        data = urllib.parse.urlencode({
            "chat_id": cid,
            "text": text[:3900],
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()

        try:
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            last_result = {"sent": True, "response": body[:500]}
        except Exception as exc:
            last_result = {"sent": False, "reason": f"chat_id {cid}: {exc}"}

    return last_result


def build_alert():
    now = datetime.now(timezone.utc).isoformat()
    latest = get_latest_freshness()
    failures = get_recent_failures()
    reliability = get_agent_reliability()

    stale_now = [
        r for r in latest
        if isinstance(r, dict) and r.get("ok") is False
    ]

    degraded_agents = [
        r for r in reliability
        if isinstance(r, dict)
        and (
            (r.get("reliability_score") is not None and float(r.get("reliability_score")) < 0.90)
            or r.get("blocked")
            or r.get("requires_manual_approval")
            or r.get("warnings")
            or r.get("error")
        )
    ]

    severity = "OK"
    if any(r.get("blocked") for r in degraded_agents if isinstance(r, dict)):
        severity = "CRITICAL"
    elif stale_now or failures or degraded_agents:
        severity = "WARN"

    lines = []
    if severity == "OK":
        lines.append("✅ <b>Trade AI System Health OK</b>")
        lines.append("All tracked freshness files are current and agent reliability is healthy.")
    else:
        icon = "🚨" if severity == "CRITICAL" else "⚠️"
        lines.append(f"{icon} <b>Trade AI System Health: {severity}</b>")

    if stale_now:
        lines.append("")
        lines.append("<b>Currently stale/failing files:</b>")
        for r in stale_now[:10]:
            lines.append(f"- {r.get('state_file')}: age {r.get('age_hours')}h / max {r.get('max_age_hours')}h")

    if failures:
        lines.append("")
        lines.append("<b>Recent DB freshness failures:</b>")
        for r in failures[:10]:
            lines.append(f"- {r.get('state_file')}: {r.get('bad_checks')}/{r.get('total_checks')} bad checks")

    if degraded_agents:
        lines.append("")
        lines.append("<b>Agent reliability controls:</b>")
        for r in degraded_agents[:10]:
            lines.append(
                f"- {r.get('agent')}: score={r.get('reliability_score')} "
                f"mode={r.get('control_mode')} blocked={r.get('blocked')}"
            )

    lines.append("")
    lines.append(f"Checked: {now}")

    return {
        "checked_at": now,
        "severity": severity,
        "latest_freshness": latest,
        "recent_failures": failures,
        "agent_reliability": reliability,
        "stale_now_count": len(stale_now),
        "degraded_agent_count": len(degraded_agents),
        "telegram_text": "\n".join(lines),
    }


def main():
    load_env()
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    alert = build_alert()
    out_file = STATE_DIR / "system_health_alert.json"
    out_file.write_text(json.dumps(alert, indent=2))

    should_send = alert["severity"] != "OK" or os.environ.get("HEALTH_ALERT_SEND_OK", "").lower() in {"1", "true", "yes"}
    telegram_result = {"sent": False, "reason": "severity OK; not sending"}
    if should_send:
        telegram_result = send_telegram(alert["telegram_text"])

    alert["telegram_result"] = telegram_result
    out_file.write_text(json.dumps(alert, indent=2))

    with (LOG_DIR / "system_health_alerts.log").open("a") as f:
        f.write(json.dumps({
            "checked_at": alert["checked_at"],
            "severity": alert["severity"],
            "stale_now_count": alert["stale_now_count"],
            "degraded_agent_count": alert["degraded_agent_count"],
            "telegram_result": telegram_result,
        }) + "\n")

    print(json.dumps({
        "ok": True,
        "severity": alert["severity"],
        "stale_now_count": alert["stale_now_count"],
        "degraded_agent_count": alert["degraded_agent_count"],
        "telegram_result": telegram_result,
        "file": str(out_file),
    }, indent=2))


if __name__ == "__main__":
    main()
