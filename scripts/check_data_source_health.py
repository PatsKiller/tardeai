#!/usr/bin/env python3
"""Report data sources whose EFFECTIVE health is not healthy while something is
scheduled to feed them. Read-only.

WHY
---
On 2026-09-13 the data_source_health table said `yahoo_finance` was "healthy".
Its last success was 2026-08-24 -- twenty days earlier. The status column is
written once by report_source() and then sits there; nothing ever ages it. In
the same table `brave_search`, `fred` and `alpha_vantage` had been "unknown"
since the row was seeded, because no caller was wired, while Brave alone made
163 governed calls that month. `finnhub` read "error" (HTTP 401) for seven
weeks while four scheduled callers still tried it first every run.

The health agent and the API read that raw column and scored the platform 75.

This gate reads the same table through lib/data_source_health_view, which gives
a row the status it is ENTITLED to right now: healthy only if it succeeded
inside its registry window (config/data_source_authority.json
`stale_after_hours`), otherwise unknown -- or error if a failure is newer than
the last success. A source that is not healthy AND has a scheduled caller is a
finding: a job exists to feed it and either did not run or failed. A source
with no scheduled caller is idle, listed, and not alerted.

STATES (effective)
------------------
    healthy   succeeded inside its window, nothing failed since
    error     a failure is newer than the last success
    unknown   never reported, or the last success aged out of its window

USAGE
-----
    python scripts/check_data_source_health.py            # human-readable
    python scripts/check_data_source_health.py --json
    python scripts/check_data_source_health.py --alert    # notify on change
    python scripts/check_data_source_health.py --dry-run  # read + print; write nothing

EXIT CODES
----------
    0  every source with a scheduled caller is effectively healthy
    1  at least one such source is not
    2  could not run (no registry, no database)
"""

from __future__ import annotations

import argparse
import json
from typing import Optional
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.data_source_health_view import (  # noqa: E402
    HEALTHY,
    SCHEDULED_CALLERS,
    load_registry,
    not_healthy_with_scheduled_caller,
    provider_for,
    view_rows,
)

STATE_PATH = Path.home() / ".local/state/tradeai/data_source_health_last_alert.json"

# APPENDED, never prepended: scripts/lib holds modules whose names collide with
# top-level scripts (research_lane_health is both), and putting it first made
# `import research_lane_health` resolve to the library instead of the monitor.
sys.path.append(str(PROJECT_ROOT / "scripts" / "lib"))
from alert_transition import (  # noqa: E402
    TYPE_SYSTEM_HEALTH,
    evaluate,
    fingerprint_state,
    previous_fingerprint,
)

#: Durable identity for this condition in the shared alert state machine.
CONDITION_KEY = "platform_availability:data_source_health"

SCHEMA = "DataSourceHealthReport@v1"
RECEIPT_NAME = "data_source_health_last_run.json"

NO_CONSUMER_REASON = (
    "this IS an availability gate; an operator or a scheduled run invokes it and reads "
    "the report, nothing imports it. Same shape as check_expected_services.py."
)


def _db_env() -> dict:
    """Same resolution as data_plausibility_monitor: the runtime env file, then the process env."""
    env = {}
    runtime = Path("/run/user/1000/tradeai/env")
    if runtime.exists():
        for line in runtime.read_text().splitlines():
            line = line.strip()
            if line.startswith("export "):
                line = line[7:]
            m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
            if m:
                env[m.group(1)] = m.group(2).strip("\"'")
    for k in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def _read_ledger(env: dict) -> list[dict]:
    """SELECT the whole table in a READ-ONLY session. psycopg2 is imported lazily so
    the pure parts of this module (and its tests) never need the driver."""
    import psycopg2  # noqa: PLC0415
    import psycopg2.extras  # noqa: PLC0415

    conn = psycopg2.connect(
        host=env.get("DB_HOST", "localhost"),
        port=env.get("DB_PORT", 5432),
        dbname=env["DB_NAME"],
        user=env["DB_USER"],
        password=env.get("DB_PASSWORD", ""),
        connect_timeout=5,
        application_name="check_data_source_health",
    )
    try:
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT source_key, status, last_success_at, last_failure_at, last_row_count, "
            "failure_count, last_error, degraded, max_stale_minutes, updated_at "
            "FROM data_source_health ORDER BY source_key"
        )
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def classify(rows: list[dict], now: datetime, registry: dict) -> tuple[list[dict], list[dict]]:
    """(all viewed rows, the alert set). Pure -- rows are injected."""
    viewed = view_rows(rows, now, registry)
    return viewed, not_healthy_with_scheduled_caller(viewed)


def _describe(r: dict) -> str:
    age = r.get("age_minutes")
    win_h = float(r.get("window_minutes") or 0) / 60.0
    if age is None:
        when = "never succeeded"
    else:
        when = f"last success {age / 60.0:.1f}h ago (window {win_h:.0f}h)"
    bits = [when]
    if r.get("decayed"):
        bits.append("table still says healthy")
    if r.get("status") != HEALTHY and r.get("last_error"):
        bits.append(f"last_error: {str(r['last_error'])[:90]}")
    callers = SCHEDULED_CALLERS.get(r.get("source_key") or "", [])
    if callers:
        bits.append("fed by " + "; ".join(f"{c['script']} [{c['cron']}]" for c in callers[:2]))
    return " -- ".join(bits)


def _write_run_receipt(checked: int, off: int, detail: dict) -> None:
    """Prove this ran, every run, whether or not it found anything.

    The alert state file only changes when findings change, so a quiet run
    leaves no trace -- and a timer that silently stopped would look exactly like
    a clean result. config/lane_registry.json requires an output_signal that is
    a durable artifact, "not its exit code, not its log file existing", and this
    is that artifact.
    """
    path = PROJECT_ROOT / "data" / "runtime" / RECEIPT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "ran_at": datetime.now(timezone.utc).isoformat(),
                    "checked": checked,
                    "off": off,
                    **detail,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"  receipt: could not write {path} ({exc})", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="notify the operator when the not-healthy set changes")
    ap.add_argument("--dry-run", action="store_true",
                    help="read and report; write no receipt, no state, no alert (AGENTS.md section 0 rule 7)")
    args = ap.parse_args()

    registry = load_registry()
    if not registry.get("domains"):
        print("ERROR: config/data_source_authority.json unreadable or has no domains", file=sys.stderr)
        return 2

    env = _db_env()
    if not env.get("DB_NAME"):
        print("ERROR: database settings unavailable", file=sys.stderr)
        return 2
    try:
        rows = _read_ledger(env)
    except Exception as exc:
        print(f"ERROR: could not read data_source_health: {exc}", file=sys.stderr)
        return 2
    if not rows:
        # An empty table is not "everything healthy". Refuse to report a clean bill.
        print("ERROR: data_source_health returned no rows -- refusing to report all-clear", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    viewed, off = classify(rows, now, registry)
    idle = [r for r in viewed if r.get("status") != HEALTHY and not r.get("scheduled_caller")]

    if args.json:
        print(json.dumps({"schema": SCHEMA, "as_of": now.isoformat(), "checked": len(viewed),
                          "off": len(off), "off_items": off, "idle_not_alerted": idle,
                          "rows": viewed}, indent=2, default=str))
    else:
        print("Data source health -- EFFECTIVE status (decayed), sources with a scheduled caller")
        print("=" * 78)
        for r in sorted(off, key=lambda x: x["source_key"]):
            print(f"  [{r['status']:<8}] {r['source_key']}")
            print(f"             {_describe(r)}")
        if not off:
            fed = sum(1 for r in viewed if r.get("scheduled_caller"))
            print(f"  all {fed} sources with a scheduled caller are effectively healthy.")
        if idle:
            print("-" * 78)
            print("  not healthy, NO scheduled caller (listed, not alerted):")
            for r in sorted(idle, key=lambda x: x["source_key"]):
                print(f"    [{r['status']:<8}] {r['source_key']} -- {_describe(r)}")
        decayed = [r["source_key"] for r in viewed if r.get("decayed")]
        if decayed:
            print("-" * 78)
            print(f"  raw column said 'healthy' but the success is outside its window: {', '.join(decayed)}")
        print("-" * 78)
        print(f"  checked={len(viewed)}  off={len(off)}  idle={len(idle)}")

    if args.dry_run:
        print("\n  dry-run: no receipt, no state, no alert written.")
        return 1 if off else 0

    _write_run_receipt(len(viewed), len(off), {
        "off_items": [f"{r['status']}:{r['source_key']}" for r in off],
        "decayed": [r["source_key"] for r in viewed if r.get("decayed")],
    })

    if args.alert:
        _alert(off)

    return 1 if off else 0


# ── operator-facing copy ──────────────────────────────────────────────────────
# The first version of this alert printed cron strings and script paths. The
# operator's reply (2026-09-13 18:32): "what does this mean to me ... what
# actions do I need to take, who do I need to escalate it to". An alert that
# needs a translator is not an alert. Every source now gets: what it feeds, what
# is wrong in one sentence, whether it heals itself and when, and an Action line.
# The machine detail survives in a trailing "Details" block for the engineer.

_SUPPLY_WORDS = {
    "quotes": "live quotes", "bars": "price bars", "paper_execution": "paper trading",
    "positions": "account positions", "option_chain": "option chains", "stream_quotes": "streaming quotes",
    "instruments": "instrument master", "profiles": "symbol profiles", "quote_backup": "backup quotes",
    "prices": "daily prices", "technicals": "technicals", "earnings": "earnings dates",
    "analyst_on_demand": "on-demand analyst pulls", "analyst_targets": "analyst targets and consensus",
    "vix": "VIX / market regime", "news_feed": "news headlines", "screeners": "Finviz screens",
    "enrichment": "symbol enrichment", "industry_groups": "industry momentum", "sector_perf": "sector performance",
    "news": "catalyst news", "form4": "insider filings (Form 4)", "filings": "SEC filings",
    "macro": "macro series (rates, CPI, jobs)", "fundamentals": "company fundamentals",
    "web_search": "governed web research", "inference": "model inference", "sentiment": "social sentiment",
}
_SOURCE_WORDS = {
    "youtube_api": "YouTube transcript discovery", "sec_edgar": "SEC filings and insider activity",
    "social": "social sentiment sync", "hermes_social": "Hermes social sentiment", "social_scalp": "scalp social signals",
    "incubator": "screener incubator", "news_catalyst": "catalyst news discovery", "yahoo_movers": "market movers",
    "research_discovery": "research candidate discovery", "finviz": "Finviz screens and enrichment",
    "brave_search": "governed web research (Brave)", "yahoo_finance": "analyst targets, VIX and Yahoo feeds",
    "fred": "macro series (rates, CPI, jobs)", "alpha_vantage": "company fundamentals (weekly)",
}


def what_it_feeds(source_key: str, registry: Optional[dict] = None) -> str:
    """One plain phrase for what the operator loses if this source is down."""
    key = str(source_key or "")
    if key in _SOURCE_WORDS:
        return _SOURCE_WORDS[key]
    reg = registry if registry is not None else load_registry()
    prov = (reg.get("providers") or {}).get(provider_for(key)) or {}
    words = [_SUPPLY_WORDS.get(w, w.replace("_", " ")) for w in (prov.get("supplies") or [])]
    return ", ".join(words[:3]) if words else key


def _cron_field_matches(field: str, value: int, lo: int, hi: int) -> bool:
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, st = part.split("/", 1)
            step = max(1, int(st))
        if part == "*":
            rng = range(lo, hi + 1)
        elif "-" in part:
            a, b = part.split("-", 1)
            rng = range(int(a), int(b) + 1)
        else:
            rng = range(int(part), int(part) + 1)
        if value in rng and (value - rng.start) % step == 0:
            return True
    return False


def next_cron_run(cron: str, now: datetime, *, horizon_days: int = 8) -> Optional[datetime]:
    """Next fire time of a 5-field cron, in the tz of `now`. None if unparseable or
    not within the horizon. Minute-resolution scan; crons here fire at most a
    few times a day, so the scan is cheap and has no external dependency."""
    parts = str(cron or "").split()
    if len(parts) < 5:
        return None
    mi, ho, dom, mon, dow = parts[:5]
    t = (now + timedelta(minutes=1)).replace(second=0, microsecond=0)
    end = now + timedelta(days=horizon_days)
    try:
        while t <= end:
            if (_cron_field_matches(mi, t.minute, 0, 59) and _cron_field_matches(ho, t.hour, 0, 23)
                    and _cron_field_matches(dom, t.day, 1, 31) and _cron_field_matches(mon, t.month, 1, 12)
                    and _cron_field_matches(dow, t.isoweekday() % 7, 0, 6)):
                return t
            t += timedelta(minutes=1)
    except ValueError:
        return None
    return None


def _next_run_text(source_key: str, now: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo
        local = now.astimezone(ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001
        local = now
    best = None
    for c in SCHEDULED_CALLERS.get(source_key, []):
        n = next_cron_run(c.get("cron", ""), local)
        if n and (best is None or n < best):
            best = n
    if not best:
        return "no scheduled run found"
    day = "today" if best.date() == local.date() else ("tomorrow" if (best.date() - local.date()).days == 1 else best.strftime("%a"))
    return f"{day} {best.strftime('%H:%M')} ET"


def plain_row(r: dict, now: datetime, registry: Optional[dict] = None) -> tuple[str, str]:
    """(group, operator text) for one not-healthy source."""
    key = r.get("source_key") or "?"
    feeds = what_it_feeds(key, registry)
    age = r.get("age_minutes")
    win_h = float(r.get("window_minutes") or 0) / 60.0
    nxt = _next_run_text(key, now)
    err = str(r.get("last_error") or "")[:80]
    if r.get("status") == "error":
        when = "never" if age is None else f"{age / 60.0:.1f}h ago"
        inside = age is not None and age <= float(r.get("window_minutes") or 0)
        text = (f"▫ {key} — {feeds}.\n    Last run failed: {err or 'error'}"
                + (f"; the previous success ({when}) is still inside its window." if inside else f"; last success {when}.")
                + f"\n    Next run: {nxt}. Action: none now — if it fails again on the next two runs, tell me and I will chase the cause.")
        return "erroring", text
    if age is None:
        text = (f"▫ {key} — {feeds}.\n    Has never reported to the health ledger (recorder wired 2026-09-13)."
                f"\n    Next run: {nxt}. Action: none — it should clear after that run; if it is still listed afterwards, tell me.")
        return "waiting", text
    days = age / 1440.0
    text = (f"▫ {key} — {feeds}.\n    Health row last updated {days:.1f} days ago (allowed {win_h / 24.0:.0f} days)"
            + ("; the table still says healthy — that is the defect this monitor exists for." if r.get("decayed") else ".")
            + f"\n    Next run: {nxt}. Action: none unless it is still listed after that run.")
    return "stale", text


def build_alert_body(off: list[dict], previous: dict, now: Optional[datetime] = None,
                     registry: Optional[dict] = None) -> str:
    """Operator-facing body. Pure; tested. The sentinel token is load-bearing."""
    now = now or datetime.now(timezone.utc)
    fingerprint = {r["source_key"]: r["status"] for r in off}
    newly = [k for k in fingerprint if k not in previous]
    recovered = [k for k in previous if k not in fingerprint]
    if not fingerprint:
        return ("[PLATFORM_AVAILABILITY] ✅ Data sources: every source with a scheduled caller "
                "succeeded inside its window." + (f" Recovered: {', '.join(recovered)}." if recovered else ""))
    groups: dict[str, list[str]] = {"erroring": [], "stale": [], "waiting": []}
    for r in sorted(off, key=lambda x: x["source_key"]):
        g, t = plain_row(r, now, registry)
        groups[g].append(t)
    heal = len(groups["waiting"]) + len(groups["stale"])
    head = (f"[PLATFORM_AVAILABILITY] 🚨 Data sources: {len(off)} not healthy"
            + (f" ({heal} expected to self-heal on their next run)" if heal else ""))
    lines = [head, ""]
    titles = {"erroring": "Failing", "stale": "Stale health row", "waiting": "Waiting on first report"}
    for g in ("erroring", "stale", "waiting"):
        if groups[g]:
            lines.append(f"{titles[g]}:")
            lines += groups[g]
            lines.append("")
    if newly:
        lines.append("New since the last run: " + ", ".join(newly))
    if recovered:
        lines.append("Recovered: " + ", ".join(recovered))
    lines += ["", "You will hear about this again only when the list changes; a ✅ follows when it clears. "
                  "Escalation: none — this is the system reporting to its operator.",
              "", "Details (for the engineer):"]
    for r in sorted(off, key=lambda x: x["source_key"]):
        lines.append(f"  {r['source_key']}: {_describe(r)}")
    return "\n".join(lines)


def _alert(off: list[dict]) -> None:
    """Notify when the not-healthy set changes, and on a heartbeat. Never raises.

    finnhub returned 401 for fifty-one days and was mentioned once, because
    "unchanged" was read as "not worth saying". The shared state machine bounds
    that silence at six hours (OPERATIONS.md:71-75).
    """
    fingerprint = {r["source_key"]: r["status"] for r in off}
    t = evaluate(
        CONDITION_KEY,
        fingerprint_state(fingerprint),
        alertable=bool(fingerprint),
        path=STATE_PATH,
    )
    if not t.notify:
        print(f"\n  alert: {t.quiet_reason()}")
        return
    previous = previous_fingerprint(t.previous)

    body = build_alert_body(off, previous)

    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import telegram_alert as _ta

        # `resolving` tells the normalized plane this observation reports the
        # condition ENDING. The transition already knows -- `t.recovered` is
        # "was bad, now healthy" -- and without passing it every incident opens
        # and none ever closes (41 open / 0 resolved, measured 2026-09-21).
        ok = _ta.send_telegram(body, message_class="operator_alert",
                               resolving=t.recovered)
        message_id = getattr(_ta, "last_message_id", lambda: None)()
        print(f"\n  alert: {'accepted' if ok else 'NOT accepted'} by the platform")
    except Exception as exc:
        t.rollback()
        print(f"\n  alert: FAILED to send ({exc}). The findings above still stand.", file=sys.stderr)
        return

    rec = t.commit(
        body=body,
        alert_type=TYPE_SYSTEM_HEALTH,
        source_script="check_data_source_health.py",
        telegram_message_id=message_id,
        payload={"sources_off": sorted(fingerprint)},
    )
    print(f"  alert: {t.action} recorded (message_id={message_id}, "
          f"alert_event={rec['alert_event_id']}, resolved={rec['resolved_rows']})")


if __name__ == "__main__":
    raise SystemExit(main())
