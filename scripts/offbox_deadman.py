#!/usr/bin/env python3
"""offbox_deadman.py — the heartbeat that leaves the host (WS3-18, WS3-20, WS8-06; 2026-10-15).

Every watcher on this box dies with the box: the freshness monitor's "off-host" ping goes to 127.0.0.1:18798
(scripts/heartbeat_receiver.py, same host), and every alert leaves through one Telegram bot. A power cut, a kernel
hang or a lost uplink is total silence, indefinitely.

This sender pings an EXTERNAL pull-on-miss check (healthchecks.io-class). The external service is the watcher: it
emails (and, if the operator adds it, pushes to the phone) when the ping stops arriving. On this side the module:

  1. reads a few local receipts (config/offbox_deadman.json ``checks``): is the incident notifier running and
     delivering, is its input fresh, is the health-plane dead-man still looking;
  2. all pass  -> GET  <ping url>          (success ping: "the alert path on this host is alive")
     any fail  -> POST <ping url>/fail     (body: the failed checks; the service alerts at once, off-box)

Independence, by construction: stdlib only (urllib), no import of n8n, the gateway, telegram_alert, the comms
editor, Postgres or the main bot. It runs from its own systemd timer (operator packet in the design), never from
n8n or health_tick. Ping URL: env TRADEAI_OFFBOX_DEADMAN_PING_URL (a secret NAME; the value is the operator's).

    python3 scripts/offbox_deadman.py              # dry run (default): prints the would-be request, no network
    python3 scripts/offbox_deadman.py --live       # one real request; operator activation only
    python3 scripts/offbox_deadman.py --config config/offbox_business_heartbeat.json   # business-output heartbeat

Two independent external checks (DD12, 2026-10-15): this file's default config watches the ALERT PATH (is the host
able to tell the operator anything); config/offbox_business_heartbeat.json watches BUSINESS OUTPUT (is the
scheduler producing useful work: scalp cycles in RTH, nightly n8n backup, weekly restore drill PASSED). Each has its
own ping URL env, so one running scheduler that produces nothing cannot keep the other check green. A check may
carry a ``window`` (days/start/end/tz) outside which it is not evaluated, and a ``status_field`` (default status).

Dry run never opens a socket, whether or not the URL is set; with no URL it prints the request it would make
against a placeholder. Live writes data/runtime/offbox_deadman_last.json (OffboxDeadmanPing@v1).

AUTHORITY: OPERATOR_NOTIFY_OFFBOX. Reads receipts read-only; no restart, no remediation, no Telegram.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "offbox_deadman.json"
SCHEMA = "OffboxDeadmanPing@v1"
NO_CONSUMER_REASON = (
    "the consumer is off-box by design: the external dead-man service reads the ping; the local receipt is "
    "operator evidence only. Its systemd timer is not installed until the operator runs the packet in PR #1751."
)
AUTHORITY = "OPERATOR_NOTIFY_OFFBOX"
RECEIPT_REL = "data/runtime/offbox_deadman_last.json"
DEFAULT_ENV = "TRADEAI_OFFBOX_DEADMAN_PING_URL"
# No provider host in code: the data-source-authority gate (AGENTS §7A) needs an operator grant for a new host,
# and the URL is the operator's secret. The dry run prints this placeholder until the env var is set.
PLACEHOLDER = "https://<offbox-check-host>/<operator-check-uuid>"
USER_AGENT = "tradeai-offbox-deadman/1"

Requester = Callable[[str, str, Optional[bytes], float], dict]


def state_root(env: dict) -> Path:
    """Same rule as scripts/lib/n8n_pilot_observations.state_root, inlined so this module imports nothing local."""
    return Path(env.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    try:
        doc = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _ts(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _dig(doc: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(doc, dict):
            return None
        doc = doc.get(part)
    return doc


DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def in_window(now: datetime, window: dict[str, Any]) -> bool:
    """True when ``now`` is inside {days: ["mon",...], start: "HH:MM", end: "HH:MM", tz}. A malformed window is
    treated as always-on (fail loud: a broken window must not silence a business heartbeat)."""
    try:
        local = now.astimezone(ZoneInfo(str(window.get("tz") or "America/New_York")))
        days = [str(d).lower()[:3] for d in (window.get("days") or DAYS)]
        sh, sm = (int(x) for x in str(window.get("start") or "00:00").split(":"))
        eh, em = (int(x) for x in str(window.get("end") or "23:59").split(":"))
    except (ValueError, KeyError, TypeError):
        return True
    minute = local.hour * 60 + local.minute
    return DAYS[local.weekday()] in days and sh * 60 + sm <= minute <= eh * 60 + em


def evaluate(root: Path, now: datetime, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per configured check: {name, ok, reason, age_min}. Pure apart from reading the receipts.

    A config with no checks is itself a failure: a dead-man that checks nothing must not report healthy."""
    checks = cfg.get("checks") or []
    if not checks:
        return [{"name": "config", "ok": False, "reason": "no_checks_configured", "age_min": None}]
    out = []
    for c in checks:
        name = str(c.get("name") or c.get("path"))
        row: dict[str, Any] = {"name": name, "ok": True, "reason": "ok", "age_min": None}
        if c.get("window") and not in_window(now, c["window"]):
            out.append({**row, "reason": "outside_window"})
            continue
        try:
            doc = json.loads((root / str(c["path"])).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError) as exc:
            out.append({**row, "ok": False, "reason": f"unreadable:{type(exc).__name__}"})
            continue
        ts = _ts(_dig(doc, str(c.get("ts_field") or "as_of")))
        if ts is None:
            out.append({**row, "ok": False, "reason": "no_timestamp"})
            continue
        age = round((now - ts).total_seconds() / 60, 1)
        row["age_min"] = age
        if age > float(c.get("max_age_min") or 15):
            row.update(ok=False, reason=f"stale:{age}m>{c.get('max_age_min')}m")
        elif c.get("require_ok") and doc.get("ok") is not True:
            row.update(ok=False, reason=f"not_ok:status={doc.get('status')}")
        elif str(_dig(doc, str(c.get("status_field") or "status")) or "") in (c.get("fail_status") or []):
            row.update(ok=False, reason=f"status:{_dig(doc, str(c.get('status_field') or 'status'))}")
        elif c.get("nonempty_fails") and _dig(doc, str(c["nonempty_fails"])):
            row.update(
                ok=False, reason=f"{c['nonempty_fails']}={json.dumps(_dig(doc, str(c['nonempty_fails'])))[:120]}"
            )
        out.append(row)
    return out


def redact(url: str) -> str:
    """The ping URL is a capability (anyone holding it can ping). Keep scheme, host and the last 4 characters."""
    try:
        u = urllib.parse.urlsplit(url)
    except ValueError:
        return "<unparseable>"
    path = u.path or ""
    tail = path[-4:] if len(path) > 4 else ""
    return f"{u.scheme}://{u.netloc}/…{tail}"


def build_request(url: Optional[str], checks: list[dict[str, Any]], now: datetime, cfg: dict[str, Any]) -> dict:
    """{method, url, body, kind}. Success -> GET <url>; any failed check -> POST <url>/fail with a short body."""
    base = (url or PLACEHOLDER).rstrip("/")
    failed = [c for c in checks if not c["ok"]]
    host = socket.gethostname()
    if not failed:
        return {"kind": "success", "method": "GET", "url": base, "body": None}
    label = str(cfg.get("label") or "off-box dead-man")
    lines = [f"TRADE AI {label}: {len(failed)} local check(s) failed on {host} at {now.isoformat()}"]
    lines += [f"- {c['name']}: {c['reason']}" for c in failed]
    lines.append(
        str(
            cfg.get("fail_hint")
            or "The alert path on the host may be silent. Check Telegram delivery and the Command Center."
        )
    )
    body = "\n".join(lines).encode("utf-8")[: int(cfg.get("body_max_bytes") or 8000)]
    return {"kind": "fail", "method": "POST", "url": base + str(cfg.get("fail_suffix") or "/fail"), "body": body}


def _urllib_request(method: str, url: str, body: Optional[bytes], timeout: float) -> dict:
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": USER_AGENT})
    if body is not None:
        req.add_header("Content-Type", "text/plain; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — operator-configured https URL
            return {"ok": 200 <= resp.status < 300, "status": resp.status}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": "http_error"}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "status": None, "error": type(exc).__name__}


def run(
    *,
    live: bool,
    env: Optional[dict] = None,
    now: Optional[datetime] = None,
    cfg: Optional[dict[str, Any]] = None,
    requester: Optional[Requester] = None,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    env = dict(os.environ) if env is None else env
    now = now or datetime.now(timezone.utc)
    cfg = load_config() if cfg is None else cfg
    root = root or state_root(env)
    var = str(cfg.get("ping_url_env") or DEFAULT_ENV)
    url = (env.get(var) or "").strip() or None
    checks = evaluate(root, now, cfg)
    req = build_request(url, checks, now, cfg)
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.isoformat(),
        "mode": "live" if live else "dry-run",
        "ping_url_env": var,
        "ping_url_configured": url is not None,
        "checks": checks,
        "request": {
            "kind": req["kind"],
            "method": req["method"],
            "url": redact(req["url"]) if url else req["url"],
            "body": req["body"].decode("utf-8") if req["body"] else None,
        },
    }
    if not live:
        receipt["outcome"] = {"status": "DRY_RUN", "network": False}
        receipt["ok"] = True
        return receipt
    if url is None:
        receipt["outcome"] = {"status": "NOT_CONFIGURED", "network": False}
        receipt["ok"] = False
        return receipt
    send = requester or _urllib_request
    tries = 1 + int(cfg.get("retries") or 0)
    res: dict[str, Any] = {}
    for i in range(tries):
        res = send(req["method"], req["url"], req["body"], float(cfg.get("timeout_s") or 10))
        if res.get("ok"):
            break
        if i + 1 < tries:
            time.sleep(min(2**i, 5))
    receipt["outcome"] = {
        "status": "PINGED" if res.get("ok") else "FAILED",
        "network": True,
        "tries": i + 1,
        "http_status": res.get("status"),
        "error": res.get("error"),
    }
    receipt["ok"] = bool(res.get("ok"))
    return receipt


def write_receipt(root: Path, receipt: dict[str, Any], rel: Optional[str] = None) -> Path:
    path = root / (rel or RECEIPT_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(receipt, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="default: print the would-be request; no network")
    g.add_argument("--live", action="store_true", help="make the one request (operator activation only)")
    ap.add_argument(
        "--config",
        type=Path,
        default=None,
        help="check set (default config/offbox_deadman.json; config/offbox_business_heartbeat.json is the "
        "separate business-output heartbeat with its own ping URL env and receipt)",
    )
    args = ap.parse_args(argv)
    env = dict(os.environ)
    cfg = load_config(args.config)
    receipt = run(live=bool(args.live), env=env, cfg=cfg)
    if args.live:
        write_receipt(state_root(env), receipt, cfg.get("receipt_rel"))
    print(json.dumps(receipt, indent=1, default=str))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
