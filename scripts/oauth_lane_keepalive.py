#!/usr/bin/env python3
"""oauth_lane_keepalive.py — keep the FREE OAuth LLM lanes warm and alert when one goes stale.

For each rolling-OAuth lane (Grok :8645, ChatGPT codex :8646) it sends a tiny REAL generate, which makes
Hermes refresh the OAuth token and roll it forward — so a lane that gets pinged regularly never lapses from
idle. For the Hermes/Nous portal and the local gemma lane it checks reachability/login. When a lane that was
healthy goes stale/expired/offline, it sends a deduped Telegram alert with the one-line re-login fix.

State: data/runtime/oauth_lane_status.json (per-lane status, last_ok, last_check, last_alert, consec_fail).
Run from cron (daily keeps the rolling tokens alive). Advisory/ops only — no broker, no paid API.

n8n refactor (2026-10-10, wave 1):
- ``--dry-run``: reachability only. Grok/ChatGPT are probed with the proxies' read-only ``/health``
  (lib.oauth_lane_status._probe_health), never a generate; local/hermes use the same read-only checks as
  a real run. It prints what a real run would record and alert, and returns before the status file, the
  Telegram send or the receipt are reachable (AGENTS.md §6).
- Exit 1 when a lane that was healthy before (it has a ``last_ok``) is not ok now — the alert is deduped
  to 12 h, so the exit code is the per-run signal. Exit 0 otherwise (never-set-up lanes are not failures).
- A failing lane is classified (``rate_limited`` / ``auth`` / ``other``) and the alert says what to do
  about THAT cause: an exhausted free quota (HTTP 429 from the proxy) heals by waiting, so the alert
  must not print the re-login command (2026-11-07 — the chatgpt lane was rate limited for 54 runs
  while /health reported authenticated=true).
- A real run writes ``<state_root>/data/runtime/oauth_lane_keepalive_last.json`` (LaneRunReceipt@v1;
  ``ok_at`` only on exit 0). The status file resolves under the persistent-state root, not the release.
- The in-script Telegram send is UNCHANGED (moving it to the incident router is a follow-up).

Quota discipline (LQ-20261107-1010; Fable Q5). A ping IS a real generate against a free OAuth quota.
At the ``*/30`` cron this lane spent 48 generates/day/lane (~2,597 in 30 days) to keep a rolling token
warm — far more than the daily cadence the flow needs, and the chatgpt account's quota was exhausted for
54 runs. So the ping is now spent only when it buys something:
- the lane states a token expiry (``token_expires_at``/``expires_at`` in the status file) within
  ``OAUTH_KEEPALIVE_LEAD_S`` (2 h), or
- its last successful roll is older than ``OAUTH_KEEPALIVE_MAX_IDLE_S`` (6 h ≈ 4 pings/day).
Otherwise the tick records ``skipped`` + ``skip_reason`` and sends nothing.
A ping carries ``_skip_consumption=True`` (it is infrastructure, not model work: no cap, no consumption
row). And a 429 is graded ``ok_rate_limited``: the lane is alive and authenticated, the quota heals by
waiting, so it does not alert, does not count as a regression and does not set exit 1 (the old
``consec_fail=54, exit 1`` streak was a quota wait graded as a dead lane). The refused attempt records
``rate_limited_until`` so the next ticks do not re-spend against a known-exhausted quota.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _runtime_dir() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env) / "data" / "runtime"
    try:
        from lib.lane_registry import state_root
        return state_root() / "data" / "runtime"
    except Exception:  # noqa: BLE001
        return ROOT / "data" / "runtime"


STATUS_FILE = _runtime_dir() / "oauth_lane_status.json"
ALERT_DEDUP_SEC = int(os.environ.get("OAUTH_LANE_ALERT_DEDUP_SEC", str(12 * 3600)))  # re-alert at most every 12h
# How often a free-OAuth token is actually rolled (LQ-20261107-1010). The cron may fire every 30 min;
# the ping fires ~4x/day, and sooner only when the lane states an expiry inside the lead.
KEEPALIVE_MAX_IDLE_S = int(os.environ.get("OAUTH_KEEPALIVE_MAX_IDLE_S", str(6 * 3600)))
KEEPALIVE_LEAD_S = int(os.environ.get("OAUTH_KEEPALIVE_LEAD_S", str(2 * 3600)))
KEEPALIVE_QUOTA_COOLDOWN_S = int(os.environ.get("OAUTH_KEEPALIVE_QUOTA_COOLDOWN_S", "900"))
PING = "Reply with exactly: OK"

HINTS = {
    "grok": "hermes proxy start --provider xai",
    "chatgpt": "hermes auth add openai-codex --type oauth",
    "hermes": "hermes portal login",
    "local": "start ollama (systemctl --user start ollama or `ollama serve`)",
}

RATE_LIMIT_STEPS = ("429", "rate limit", "rate_limit", "rate_limited", "too many requests",
                    "usage limit", "quota exceeded")
AUTH_STEPS = ("auth_expired", "session expired", "session ended", "not logged in", "please log in again",
              "token refresh failed")


def _failure_kind(detail):
    """Why a lane is down: "rate_limited", "auth", or "other" — the operator's next action depends on it.

    A free-OAuth quota that is exhausted upstream (HTTP 429 from the local proxy) heals by waiting; the
    fix is NOT a re-login. Before 2026-11-07 every failure carried the lane's one-line HINT, so the
    chatgpt lane — rate limited since 2026-11-06T00:00Z while ``/health`` reported authenticated=true,
    token_expired=false — told the operator to run a credential command 54 runs in a row. Running it
    would have been an operator-only action aimed at the wrong cause.
    """
    low = str(detail or "").lower()
    if any(t in low for t in RATE_LIMIT_STEPS):
        return "rate_limited"
    if any(t in low for t in AUTH_STEPS):
        return "auth"
    return "other"


def _hint_line(lane, kind, detail):
    """The one line the alert shows under a failing lane — what to do, or why there is nothing to do."""
    if kind == "rate_limited":
        return ("no action yet: the free Codex quota is exhausted upstream and heals on its own "
                "(the proxy advertises Retry-After 900 s). Do NOT re-login — /health reports "
                "authenticated=true; a re-login would not clear a 429.")
    if kind == "auth":
        return f"fix: {HINTS.get(lane, '')}"
    return f"fix: {HINTS.get(lane, '')} (unclassified failure: {str(detail)[:80]})"


def _expiry_ts(prev):
    """A stated token expiry as epoch seconds, or None when the lane does not state one.

    Neither proxy's ``/health`` publishes an expiry (it reports ``authenticated``/``token_expired``
    only), so this reads whatever the status file was given. When nothing is stated the idle window is
    the whole rule — the script does not guess an expiry from a credential.
    """
    from datetime import datetime
    for key in ("token_expires_at", "expires_at", "token_expiry"):
        v = prev.get(key)
        if v in (None, ""):
            continue
        try:
            if isinstance(v, (int, float)):
                return int(v)
            return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp())
        except (TypeError, ValueError):
            continue
    return None


def _needs_ping(lane, prev, now):
    """(need: bool, reason: str) — spend a generate only when it buys a token roll (LQ-20261107-1010).

    ``rate_limited_upstream`` — a recent ping was refused 429; re-spending against a known-exhausted
    quota buys nothing, so the ticks within the cooldown skip it.
    ``expiry_within_lead`` / ``max_idle_exceeded`` / ``no_prior_ok`` — ping.
    ``idle_within_window`` — the token was rolled recently; skip.
    """
    prev = prev or {}
    if lane not in ("grok", "chatgpt"):
        return True, "read_only_check"
    until = int(prev.get("rate_limited_until") or 0)
    if now < until:
        return False, "rate_limited_upstream"
    exp = _expiry_ts(prev)
    if exp is not None and now >= exp - KEEPALIVE_LEAD_S:
        return True, "expiry_within_lead"
    last_ok = int(prev.get("last_ok") or 0)
    if last_ok and (now - last_ok) < KEEPALIVE_MAX_IDLE_S:
        return False, "idle_within_window"
    return True, ("max_idle_exceeded" if last_ok else "no_prior_ok")


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
            # _skip_consumption=True: the ping is infrastructure (LQ-20261107-1010), so it takes no process
            # cap and writes no llm_consumption_log row — the burn this lane caused was in the free quota
            # itself, and the consumption page should not count keepalive pings as model work.
            txt = llm_lane.generate(PING, lane=lane, timeout=200 if lane == "chatgpt" else 40,
                                    process_id="oauth_lane_keepalive",
                                    task_summary=f"token keepalive ping ({lane})",
                                    _skip_consumption=True)
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


def _reach_lane(lane):
    """Dry-run probe: (ok, detail) WITHOUT a generate. Grok/ChatGPT: the proxy's read-only /health.

    ``serving``/``last_upstream`` are read when the proxy states them: a 200 from /health means the
    process is alive, not that the lane can answer (2026-11-07: chatgpt reported ready for 54 runs
    while every real call was 429). Reading the last upstream outcome keeps the dry run honest
    without spending a generate on a lane that is known to be rate limited.
    """
    if lane in ("grok", "chatgpt"):
        try:
            from lib.oauth_lane_status import _probe_health
            snap = _probe_health(lane)
            if not snap.get("ready"):
                return False, (f"/health: {snap.get('status')} "
                               "(dry run: no generate, token not rolled)")
            last = snap.get("last_upstream") or {}
            if snap.get("serving") is False and str(last.get("state")) == "rate_limited":
                return False, (f"rate_limited upstream (last call {last.get('at')}): "
                               "dry run sent no generate; the proxy says the free quota is exhausted "
                               "and retries after 900 s")
            return True, "/health: ready (dry run: no generate, token not rolled)"
        except Exception as e:  # noqa: BLE001
            return False, f"/health probe failed: {str(e)[:100]}"
    return _ping_lane(lane)  # local / hermes: already read-only (GET /api/tags, auth.json read)


def _evaluate(lanes, state, now, probe, planner=None):
    """(alerts, per-lane records, regressions). Pure apart from ``probe``; shared by the real run and the dry run.

    ``planner(lane, prev, now) -> (need, reason)`` decides whether the probe is spent at all; without one
    every lane is probed (the shape the pre-LQ-1010 tests use). A lane that is not probed keeps its prior
    record and carries ``skipped``/``skip_reason``, so "not pinged" is never confused with "pinged and ok".

    A ``rate_limited`` result is graded ``ok_rate_limited``: the lane is alive and authenticated (the
    proxy's /health says so) and the free quota heals by waiting, so it raises no alert, is not a
    regression and does not set exit 1 — it records ``quota_exhausted`` and ``rate_limited_until``.
    """
    alerts, out, regressions = [], {}, []
    for lane in lanes:
        prev = state.get(lane, {})
        if planner is not None:
            need, why = planner(lane, prev, now)
        else:
            need, why = True, "probe"
        if not need:
            rec = {**prev, "lane": lane, "ok": bool(prev.get("ok", True)), "last_check": now,
                   "last_ok": prev.get("last_ok"), "skipped": True, "skip_reason": why}
            out[lane] = rec
            continue
        ok, detail = probe(lane)
        kind = None if ok else _failure_kind(detail)
        quota = kind == "rate_limited"
        rec = {"lane": lane, "ok": ok, "detail": detail, "last_check": now,
               "last_ok": now if ok else prev.get("last_ok"),
               "consec_fail": 0 if ok else int(prev.get("consec_fail", 0)) + 1,
               "last_alert": prev.get("last_alert"), "skipped": False, "skip_reason": why}
        if kind:
            rec["kind"] = kind
        if quota:
            rec["quota_exhausted"] = True
            rec["rate_limited_until"] = now + KEEPALIVE_QUOTA_COOLDOWN_S
        healthy = ok or quota
        # Alert when a lane is NOT healthy and we haven't alerted recently (deduped). Skip 'hermes' if it was
        # never set up (don't nag about an optional lane that was never logged in) — only alert on a *regression*.
        was_ok = bool(prev.get("last_ok"))
        should_alert = (not healthy) and (lane != "hermes" or was_ok) and \
            (now - int(prev.get("last_alert") or 0) > ALERT_DEDUP_SEC)
        if should_alert:
            alerts.append(f"  • {lane.upper()}: {detail}\n    {_hint_line(lane, kind, detail)}")
            rec["last_alert"] = now
        if not healthy and was_ok:
            regressions.append(lane)
        out[lane] = rec
    return alerts, out, regressions


def dry_run(lanes):
    """What a real run would record/alert, from reachability only. Writes nothing, sends nothing."""
    now = int(time.time())
    alerts, out, regressions = _evaluate(lanes, _load_status(), now, _reach_lane, planner=_needs_ping)
    skipped = {lane: rec["skip_reason"] for lane, rec in out.items() if rec.get("skipped")}
    print(json.dumps({"mode": "dry_run", "checked": len(lanes), "ok": sum(1 for r in out.values() if r["ok"]),
                      "would_alert": len(alerts), "would_alert_lines": alerts, "regressions": regressions,
                      "would_exit": 1 if regressions else 0, "would_write": [str(STATUS_FILE)],
                      "skipped": skipped, "would_skip": len(skipped), "lanes": out}, indent=2, default=str))
    print("(dry run — no generate, status file not written, nothing sent, no receipt)")
    return 0


def _nyse_session(now: int) -> bool:
    """09:30–16:00 America/New_York on a trading day (weekends and NYSE holidays are not)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from market_session import is_trading_day

    dt = datetime.fromtimestamp(now, ZoneInfo("America/New_York"))
    if not is_trading_day(dt):
        return False
    minutes = dt.hour * 60 + dt.minute
    return (9 * 60 + 30) <= minutes < 16 * 60


def _priority_for_alerts(records: dict, now: int) -> str:
    """P2 while a lane is merely down. P1 after it has been down more than 2 hours in the session.

    Operator ruling 2026-10-11: keep ordinary stale alerts at P2; a lane stale more than
    2 hours during market hours is P1.
    """
    if not _nyse_session(now):
        return "P2"
    for rec in records.values():
        if rec.get("ok"):
            continue
        last_ok = rec.get("last_ok")
        if not last_ok:
            continue
        if now - int(last_ok) > 2 * 60 * 60:
            return "P1"
    return "P2"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    pos = [a for a in argv if not a.startswith("--")]
    lanes = (pos[0].split(",") if pos else ["grok", "chatgpt", "hermes", "local"])
    if "--dry-run" in argv:
        return dry_run(lanes)  # AGENTS.md §6: generate, status write, send and receipt are below
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    now = int(time.time())
    state = _load_status()
    # Same evaluation as the dry run, with the same planner (only a lane that needs a roll is pinged);
    # the probe differs (a real generate rolls the token).
    alerts, out, regressions = _evaluate(lanes, state, now, _ping_lane, planner=_needs_ping)
    state.update(out)

    _save_status(state)

    if alerts:
        msg = ("⚠️ *OAuth LLM lane(s) stale* — a free-OAuth lane needs attention "
               "(advisory/oversight uses these; the local gemma lane is unaffected if listed as ok):\n\n"
               + "\n".join(alerts) + "\n\nMonitor: /v3/rotation → Independent Oversight lane strip.")
        try:
            from telegram_alert import send_telegram
            priority = _priority_for_alerts(out, now)
            if priority == "P1":
                send_telegram(msg, priority="P1", producer="oauth_lane_keepalive")
            else:
                send_telegram(msg, priority="P2", producer="oauth_lane_keepalive")
        except Exception as e:
            print("telegram send failed:", e)

    skipped = {lane: rec["skip_reason"] for lane, rec in out.items() if rec.get("skipped")}
    quota = [lane for lane, rec in out.items() if rec.get("quota_exhausted")]
    summary = {"checked": len(lanes), "ok": sum(1 for r in out.values() if r["ok"]),
               "alerts_sent": len(alerts), "regressions": regressions, "skipped": skipped,
               "quota_exhausted": quota, "lanes": out}
    print(json.dumps(summary, indent=2, default=str))
    code = 1 if regressions else 0
    receipt_summary = {"checked": len(lanes), "ok": summary["ok"], "regressions": regressions,
                       "alerts": len(alerts), "skipped": skipped, "quota_exhausted": quota}
    kinds = {lane: rec["kind"] for lane, rec in out.items() if rec.get("kind")}
    if kinds:
        # Why each failing lane is down, so a 54-run streak can be read as a quota wait, not a dead login.
        receipt_summary["failed_kinds"] = kinds
    write_lane_receipt("oauth_lane_keepalive", ok=code == 0, exit_code=code, started_at=started,
                       summary=receipt_summary,
                       path=_runtime_dir() / "oauth_lane_keepalive_last.json")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
