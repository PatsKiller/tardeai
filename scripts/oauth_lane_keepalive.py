#!/usr/bin/env python3
"""oauth_lane_keepalive.py — keep the FREE OAuth LLM lanes warm and alert when one goes stale.

For each rolling-OAuth lane (Grok :8645, ChatGPT codex :8646) it sends a tiny REAL generate, which makes
Hermes refresh the OAuth token and roll it forward — so a lane that gets pinged regularly never lapses from
idle. For the Hermes/Nous portal and the local gemma lane it checks reachability/login. When a lane that was
healthy goes stale/expired/offline, it sends a deduped Telegram alert with the one-line re-login fix.

State: data/runtime/oauth_lane_status.json (per-lane status, last_ok, last_check, last_alert, consec_fail).
Run from cron (daily keeps the rolling tokens alive). Advisory/ops only — no broker, no paid API.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STATUS_FILE = ROOT / "data" / "runtime" / "oauth_lane_status.json"
ALERT_DEDUP_SEC = int(os.environ.get("OAUTH_LANE_ALERT_DEDUP_SEC", str(12 * 3600)))  # re-alert at most every 12h
PING = "Reply with exactly: OK"

HINTS = {
    "grok": "hermes proxy start --provider xai",
    "chatgpt": "hermes auth add openai-codex --type oauth",
    "hermes": "hermes portal login",
    "local": "start ollama (systemctl --user start ollama or `ollama serve`)",
}


def _load_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception:
        return {}


def _save_status(s):
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(s, indent=2))


def _ping_lane(lane):
    """Returns (ok: bool, detail: str). For cloud lanes a real generate rolls the OAuth token forward."""
    try:
        import llm_lane
        if lane in ("grok", "chatgpt"):
            # Always attempt a real ping — don't trust JWT-only /health; hermes refreshes rolling OAuth on use.
            txt = llm_lane.generate(PING, lane=lane, timeout=200 if lane == "chatgpt" else 40,
                                    process_id="oauth_lane_keepalive",
                                    task_summary=f"token keepalive ping ({lane})",
                                    _skip_consumption=False)
            return (bool(txt and str(txt).strip()), "rolled token (ping ok)" if txt else "empty response")
        if lane == "local":
            import requests
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=4)
            return (r.ok, "ollama reachable" if r.ok else f"ollama HTTP {r.status_code}")
        if lane == "hermes":
            aj = json.loads((Path.home() / ".hermes" / "auth.json").read_text())
            ok = any("nous" in k.lower() for k in (aj.get("providers") or {}))
            return (ok, "nous portal logged in" if ok else "nous portal not logged in")
    except Exception as e:
        msg = str(e)
        if any(t in msg for t in ("AUTH_EXPIRED", "session ended", "not logged in")):
            return False, "session expired — re-login required"
        return False, msg[:120]
    return False, "unknown lane"


def main():
    lanes = (sys.argv[1].split(",") if len(sys.argv) > 1 else ["grok", "chatgpt", "hermes", "local"])
    now = int(time.time())
    state = _load_status()
    alerts = []
    out = {}
    for lane in lanes:
        prev = state.get(lane, {})
        ok, detail = _ping_lane(lane)
        rec = {"lane": lane, "ok": ok, "detail": detail, "last_check": now,
               "last_ok": now if ok else prev.get("last_ok"),
               "consec_fail": 0 if ok else int(prev.get("consec_fail", 0)) + 1,
               "last_alert": prev.get("last_alert")}
        # Alert when a lane is NOT ok and we haven't alerted recently (deduped). Skip 'hermes' if it was never
        # set up (don't nag about an optional lane that was never logged in) — only alert on a *regression*.
        was_ok = bool(prev.get("last_ok"))
        should_alert = (not ok) and (lane != "hermes" or was_ok) and \
            (now - int(prev.get("last_alert") or 0) > ALERT_DEDUP_SEC)
        if should_alert:
            alerts.append(f"  • {lane.upper()}: {detail}\n    fix: {HINTS.get(lane, '')}")
            rec["last_alert"] = now
        out[lane] = rec
        state[lane] = rec

    _save_status(state)

    if alerts:
        msg = ("⚠️ *OAuth LLM lane(s) stale* — a free-OAuth lane needs attention "
               "(advisory/oversight uses these; the local gemma lane is unaffected if listed as ok):\n\n"
               + "\n".join(alerts) + "\n\nMonitor: /v3/rotation → Independent Oversight lane strip.")
        try:
            from telegram_alert import send_telegram
            send_telegram(msg)
        except Exception as e:
            print("telegram send failed:", e)

    summary = {"checked": len(lanes), "ok": sum(1 for r in out.values() if r["ok"]),
               "alerts_sent": len(alerts), "lanes": out}
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
