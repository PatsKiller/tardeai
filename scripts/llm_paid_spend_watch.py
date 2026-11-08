#!/usr/bin/env python3
"""Paid LLM spend watch: one CRITICAL alert when a process spends too much on too many days.

Operator directive 2026-11-07 21:08 ET (LQ-20261107-538): "Make sure free is first. Leave the cap at 1.50. Alert when
it goes over .75, 3 times in a week." The cap stays where the registry (``config/llm_process_registry.json``) sets it;
this script is the "alert" half.

What it measures
  * Paid spend is ``llm_consumption_log.estimated_cost_usd`` on rows whose ``metadata_json->>'billing'`` is not
    ``free_oauth``, summed per America/New_York calendar day. A free OAuth call (grok, chatgpt) costs nothing and is
    not read. The projection a bridge reservation settles for an OAuth-served call (LQ-20261107-531) is not spend and
    is not read either: the reservation table is not this script's source.
  * For each watch in ``config/llm_paid_spend_alerts.json`` it counts the days, in the last ``window_days`` ET days
    (today included), whose paid spend is strictly above ``day_threshold_usd``. At ``days_over`` or more it raises ONE
    alert through the critical channel hub (``scripts/lib/critical_channels.deliver``): the Critical Telegram chat
    and email. A text goes out only if the operator enables the class in ``config/critical_text_classes.json``.
  * Dedupe: after a delivered alert the watch stays quiet for ``dedupe_days`` ET days (default ``window_days``), so a
    breach that persists all week alerts once per window. An alert that reached no channel is not stamped and is
    retried on the next run.

Every threshold lives in config; nothing here is a number the operator set.

Modes
  * ``--dry-run`` computes and prints everything, sends nothing and writes nothing (no state, no receipt).
  * A real run writes ``data/runtime/llm_paid_spend_watch_state.json`` (dedupe) and the lane receipt
    ``data/runtime/llm-paid-spend-watch_last.json`` under the persistent state root.

The DB session is READ ONLY at the server on every path. MBI_BEHAVIOR = 0: no broker, no order, no sizing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LANE_ID = "llm-paid-spend-watch"
CONFIG_REL = "config/llm_paid_spend_alerts.json"
STATE_NAME = "llm_paid_spend_watch_state.json"
CONFIG_SCHEMA = "LlmPaidSpendAlerts@v1"
STATE_SCHEMA = "LlmPaidSpendWatchState@v1"
SOURCES = frozenset({"llm_consumption_log"})

# The one paid predicate. Summed per ET day for one process over a closed date range. ``billing`` is absent on most
# metered rows (DeepSeek, Anthropic), so a missing key counts as paid; only an explicit free_oauth is free.
PAID_DAILY_SQL = """
SELECT (created_at AT TIME ZONE %(tz)s)::date AS et_day,
       COALESCE(SUM(estimated_cost_usd), 0)::float8 AS paid_usd,
       COUNT(*)::int AS paid_calls
  FROM llm_consumption_log
 WHERE process_id = %(process_id)s
   AND estimated_cost_usd > 0
   AND COALESCE(metadata_json->>'billing', '') <> 'free_oauth'
   AND (created_at AT TIME ZONE %(tz)s)::date BETWEEN %(start)s AND %(end)s
 GROUP BY 1
 ORDER BY 1
"""


class ConfigError(ValueError):
    """The alert config is missing or malformed. The watch refuses rather than guessing a threshold."""


# ── config ────────────────────────────────────────────────────────────────────────────────────────────────


def _positive_number(watch: Mapping[str, Any], key: str) -> float:
    value = watch.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ConfigError(f"{key}_must_be_positive")
    return float(value)


def _positive_int(watch: Mapping[str, Any], key: str) -> int:
    value = watch.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError(f"{key}_must_be_a_positive_integer")
    return value


def validate_config(doc: Any) -> dict[str, Any]:
    """Return ``{"timezone", "watches": [...]}`` with every field checked, or raise :class:`ConfigError`."""
    if not isinstance(doc, dict) or doc.get("schema") != CONFIG_SCHEMA:
        raise ConfigError("schema_mismatch")
    tz_name = doc.get("timezone")
    if not isinstance(tz_name, str) or not tz_name:
        raise ConfigError("timezone_missing")
    try:
        ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001 -- any zone lookup failure is the same config error
        raise ConfigError("timezone_unknown") from exc
    raw = doc.get("watches")
    if not isinstance(raw, list) or not raw:
        raise ConfigError("watches_missing")
    watches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for watch in raw:
        if not isinstance(watch, dict):
            raise ConfigError("watch_not_an_object")
        process_id = watch.get("process_id")
        if not isinstance(process_id, str) or not process_id:
            raise ConfigError("process_id_missing")
        if process_id in seen:
            raise ConfigError("process_id_duplicated")
        seen.add(process_id)
        source = watch.get("source")
        if source not in SOURCES:
            raise ConfigError("source_unsupported")
        alert_class = watch.get("alert_class")
        if not isinstance(alert_class, str) or not alert_class:
            raise ConfigError("alert_class_missing")
        window_days = _positive_int(watch, "window_days")
        days_over = _positive_int(watch, "days_over")
        if days_over > window_days:
            raise ConfigError("days_over_exceeds_window")
        dedupe_days = _positive_int(watch, "dedupe_days") if "dedupe_days" in watch else window_days
        watches.append({
            "process_id": process_id,
            "source": source,
            "day_threshold_usd": _positive_number(watch, "day_threshold_usd"),
            "days_over": days_over,
            "window_days": window_days,
            "dedupe_days": dedupe_days,
            "alert_class": alert_class,
        })
    return {"timezone": tz_name, "watches": watches}


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    target = Path(path) if path else ROOT / CONFIG_REL
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError("config_missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError("config_unreadable") from exc
    return validate_config(doc)


# ── measurement ───────────────────────────────────────────────────────────────────────────────────────────


def window_dates(today: date, window_days: int) -> list[date]:
    """The last ``window_days`` ET calendar days, oldest first, today included."""
    return [today - timedelta(days=offset) for offset in range(window_days - 1, -1, -1)]


def fetch_daily_paid(conn: Any, *, process_id: str, start: date, end: date, tz: str) -> dict[date, dict[str, Any]]:
    """Paid spend per ET day for one process.

    A day with no paid row is absent from the result. That is a measured zero: the query ran over the whole window.
    A returned row with a NULL sum or count is unreadable data and raises, so the run fails instead of reading $0.
    """
    cur = conn.cursor()
    try:
        cur.execute(PAID_DAILY_SQL, {"tz": tz, "process_id": process_id, "start": start, "end": end})
        rows = cur.fetchall()
    finally:
        cur.close()
    out: dict[date, dict[str, Any]] = {}
    for et_day, paid_usd, paid_calls in rows:
        day = et_day if isinstance(et_day, date) else date.fromisoformat(str(et_day))
        if paid_usd is None or paid_calls is None:
            raise ValueError(f"paid_daily_row_incomplete:{day.isoformat()}")
        out[day] = {"paid_usd": float(paid_usd), "paid_calls": int(paid_calls)}
    return out


def evaluate(watch: Mapping[str, Any], daily: Mapping[date, Mapping[str, Any]], today: date) -> dict[str, Any]:
    """Count the window's days above the threshold. Pure: no DB, no clock, no send."""
    threshold = float(watch["day_threshold_usd"])
    days = []
    for day in window_dates(today, int(watch["window_days"])):
        row = daily.get(day)
        if row is None:
            # Absent means the window query found no paid row for this ET day: a measured zero (see fetch_daily_paid).
            paid, calls = 0.0, 0
        else:
            paid, calls = round(float(row["paid_usd"]), 6), int(row["paid_calls"])
        days.append({"et_day": day.isoformat(), "paid_usd": paid, "paid_calls": calls, "over": paid > threshold})
    over = [d["et_day"] for d in days if d["over"]]
    return {
        "process_id": watch["process_id"],
        "day_threshold_usd": threshold,
        "days_over_required": int(watch["days_over"]),
        "window_days": int(watch["window_days"]),
        "window": [days[0]["et_day"], days[-1]["et_day"]],
        "days": days,
        "over_days": over,
        "over_count": len(over),
        "breach": len(over) >= int(watch["days_over"]),
        "window_paid_usd": round(sum(d["paid_usd"] for d in days), 6),
    }


# ── dedupe ────────────────────────────────────────────────────────────────────────────────────────────────


def suppressed_by_dedupe(state: Mapping[str, Any], watch: Mapping[str, Any], today: date) -> str | None:
    """The ET date of the alert that still covers today, or None when a new alert may go out."""
    entry = (state.get("watches") or {}).get(watch["process_id"]) if isinstance(state, Mapping) else None
    last = entry.get("last_alert_et_day") if isinstance(entry, Mapping) else None
    if not isinstance(last, str):
        return None
    try:
        last_day = date.fromisoformat(last)
    except ValueError:
        return None  # an unreadable stamp must not silence the alert forever
    if 0 <= (today - last_day).days < int(watch["dedupe_days"]):
        return last
    return None


def load_state(path: Path) -> dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": STATE_SCHEMA, "watches": {}}
    except (OSError, json.JSONDecodeError):
        # Unreadable dedupe state fails toward ALERTING: a duplicate alert is cheaper than a silent breach.
        return {"schema": STATE_SCHEMA, "watches": {}, "unreadable": True}
    if not isinstance(doc, dict) or not isinstance(doc.get("watches"), dict):
        return {"schema": STATE_SCHEMA, "watches": {}, "unreadable": True}
    return doc


def state_path(state_root: Path | str | None = None) -> Path:
    from scripts.lib.lane_last_receipt import runtime_dir

    return runtime_dir(state_root) / STATE_NAME


# ── alert ─────────────────────────────────────────────────────────────────────────────────────────────────


def build_event(watch: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    """The critical-hub event: what happened, which days, and what the operator can do."""
    over_rows = [d for d in result["days"] if d["over"]]
    listed = ", ".join(f"{d['et_day']} ${d['paid_usd']:.2f}" for d in over_rows)
    what = (f"LLM paid spend: {watch['process_id']} spent more than ${result['day_threshold_usd']:.2f} on "
            f"{result['over_count']} of the last {result['window_days']} days ({listed}).")
    action = ("Check why the free OAuth lanes did not serve these calls. The daily cost cap still binds; "
              "nothing is changed automatically.")
    return {
        "alert_class": watch["alert_class"],
        "symbol": "",
        "account": "",
        "what": what,
        "trigger": f"{result['over_count']} of {result['window_days']} ET days over "
                   f"${result['day_threshold_usd']:.2f} (needs {result['days_over_required']})",
        "action": action,
        "evidence": {
            "process_id": watch["process_id"],
            "window": result["window"],
            "over_days": result["over_days"],
            "window_paid_usd": result["window_paid_usd"],
            "source": watch["source"],
        },
    }


def _default_deliver(event: dict[str, Any]) -> dict[str, Any]:
    from scripts.lib import critical_channels  # lazy: a dry run and the tests never import the senders

    return critical_channels.deliver(event).as_dict()


# ── DB ────────────────────────────────────────────────────────────────────────────────────────────────────


def _default_connect() -> Any:
    """A READ ONLY session at the server. psycopg2 is imported lazily so the pure parts never need the driver."""
    import psycopg2  # noqa: PLC0415

    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST") or "/var/run/postgresql",
        port=os.environ.get("DB_PORT") or 5432,
        dbname=os.environ.get("DB_NAME") or "trade_ai",
        user=os.environ.get("DB_USER") or None,
        password=os.environ.get("DB_PASSWORD") or None,
        connect_timeout=5,
        application_name=LANE_ID,
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


# ── run ───────────────────────────────────────────────────────────────────────────────────────────────────


def run(
    *,
    dry_run: bool,
    config_path: Path | str | None = None,
    connect: Callable[[], Any] | None = None,
    deliver: Callable[[dict[str, Any]], Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    state_file: Path | str | None = None,
    write_receipt: Callable[..., Any] | None = None,
    emit: Callable[[str], None] = print,
) -> tuple[int, dict[str, Any]]:
    """Evaluate every watch; alert on a breach not already covered by dedupe. Returns ``(exit_code, report)``."""
    started = datetime.now(timezone.utc) if now is None else now
    report: dict[str, Any] = {"lane_id": LANE_ID, "dry_run": dry_run, "watches": []}
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        report.update(ok=False, error=f"config:{exc}")
        _finish(report, dry_run=dry_run, started=started, write_receipt=write_receipt, emit=emit)
        return 1, report
    tz = ZoneInfo(cfg["timezone"])
    today = started.astimezone(tz).date()
    report["et_today"] = today.isoformat()

    st_path = Path(state_file) if state_file else state_path()
    state = load_state(st_path)
    state.setdefault("watches", {})
    exit_code = 0
    try:
        conn = (connect or _default_connect)()
    except Exception as exc:  # noqa: BLE001 -- a DB outage is the run's failure, reported by type
        report.update(ok=False, error=f"db_connect:{type(exc).__name__}")
        _finish(report, dry_run=dry_run, started=started, write_receipt=write_receipt, emit=emit)
        return 1, report
    try:
        for watch in cfg["watches"]:
            days = window_dates(today, watch["window_days"])
            daily = fetch_daily_paid(conn, process_id=watch["process_id"], start=days[0], end=days[-1],
                                     tz=cfg["timezone"])
            result = evaluate(watch, daily, today)
            row: dict[str, Any] = {"evaluation": result, "alert": "none"}
            if result["breach"]:
                covered_by = suppressed_by_dedupe(state, watch, today)
                event = build_event(watch, result)
                row["event"] = event
                if covered_by:
                    row["alert"] = "deduped"
                    row["covered_by_alert_on"] = covered_by
                elif dry_run:
                    row["alert"] = "would_send"
                else:
                    delivery = dict((deliver or _default_deliver)(event))
                    row["delivery"] = delivery
                    if delivery.get("delivered") is True:
                        row["alert"] = "sent"
                        state["watches"][watch["process_id"]] = {
                            "last_alert_et_day": today.isoformat(),
                            "last_alert_at": started.isoformat(),
                            "over_days": result["over_days"],
                            "alert_class": watch["alert_class"],
                        }
                    else:
                        # Reached no channel: not stamped, so the next run tries again.
                        row["alert"] = "undelivered"
                        exit_code = 1
            report["watches"].append(row)
    except Exception as exc:  # noqa: BLE001 -- a failed query is the run's failure, reported by type
        report.update(ok=False, error=f"query:{type(exc).__name__}:{str(exc)[:160]}")
        _finish(report, dry_run=dry_run, started=started, write_receipt=write_receipt, emit=emit)
        return 1, report
    finally:
        close = getattr(conn, "close", None)
        if close:
            close()

    report["ok"] = exit_code == 0
    if not dry_run and any(r["alert"] == "sent" for r in report["watches"]):
        from scripts.lib.atomic_json_store import atomic_write_json

        state["schema"] = STATE_SCHEMA
        state.pop("unreadable", None)
        atomic_write_json(st_path, state)
        report["state_written"] = str(st_path)
    _finish(report, dry_run=dry_run, started=started, write_receipt=write_receipt, emit=emit, exit_code=exit_code)
    return exit_code, report


def _finish(report: dict[str, Any], *, dry_run: bool, started: datetime, write_receipt: Callable[..., Any] | None,
            emit: Callable[[str], None], exit_code: int | None = None) -> None:
    """Print the report; on a real run also write the lane receipt. A dry run writes nothing."""
    summary = {
        "ok": report.get("ok"),
        "error": report.get("error"),
        "et_today": report.get("et_today"),
        "watches": [
            {"process_id": r["evaluation"]["process_id"], "over_count": r["evaluation"]["over_count"],
             "breach": r["evaluation"]["breach"], "alert": r["alert"],
             "window_paid_usd": r["evaluation"]["window_paid_usd"]}
            for r in report.get("watches", [])
        ],
    }
    if dry_run:
        from scripts.lib.lane_last_receipt import dry_run_report

        dry_run_report(LANE_ID, summary, would_write=[STATE_NAME] if any(
            r["alert"] == "would_send" for r in report.get("watches", [])) else [])
        emit(json.dumps(report, default=str, indent=2, sort_keys=True))
        return
    writer = write_receipt
    if writer is None:
        from scripts.lib.lane_last_receipt import write_lane_receipt as writer
    evaluated = len(report.get("watches", []))
    writer(
        LANE_ID,
        ok=bool(report.get("ok")),
        exit_code=1 if exit_code is None else exit_code,
        started_at=started,
        script="scripts/llm_paid_spend_watch.py",
        summary=summary,
        error=report.get("error"),
        produced_count=evaluated,
        attempted_count=evaluated,
        empty_reason=None if evaluated else "no_watch_evaluated",
    )
    emit(json.dumps(summary, default=str, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="compute and print; send nothing, write nothing")
    parser.add_argument("--config", default=None, help=f"alert config (default {CONFIG_REL})")
    args = parser.parse_args(argv)
    code, _report = run(dry_run=args.dry_run, config_path=args.config)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
