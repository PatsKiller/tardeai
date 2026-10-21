#!/usr/bin/env python3
"""Measure declared numeric columns against their declared scale. Read-only.

WHY
---
For five months `analyst_consensus_history.recom_score` held ten-year return
percentages on a column declared as a 1-5 analyst scale, and the labels derived
from it were ANTI-correlated with reality: stocks down -100% published as
"Strong Buy". Nothing failed. Every value parsed, every type converted, every row
stored. 97.9% of the table was wrong and no gate anywhere noticed, because the
column's scale existed only in a docstring.

This monitor is the gate that was missing. It reads
config/data_plausibility_contracts.json, measures each declared column, and
reports what violates its contract.

It NEVER writes to the tables it inspects -- it opens a read-only session.

A violation is not automatically a defect: it may equally mean the contract is
wrong. Both are worth knowing, and both are invisible today.

USAGE
-----
    python scripts/data_plausibility_monitor.py           # human-readable
    python scripts/data_plausibility_monitor.py --json    # machine-readable
    python scripts/data_plausibility_monitor.py --dry-run # measure + print; writes nothing (no receipt, no state)
    ... --lane-receipt [--alert --notify queue]           # the n8n lane argv (n8n-data-plausibility-audit)

2026-10-18 (data-integrity fix PR):
  * the alert fingerprint is (contract, column, rule, severity band), not raw
    counts -- a count that creeps every day is not news; crossing a band is
    (config alert_policy.pct_bands_pct);
  * range/min/max/finite/single_scale contracts measure a time WINDOW
    (config window_policy.default_window_days, per-contract window_column /
    window_days), so frozen historical rows stop firing every day;
  * ``retired_store`` contracts fail only on NEW empty rows after retired_at;
  * ``--notify queue`` queues a host comms intent (n8n lanes never call a
    sender, config/n8n_run_allowlist.json never-list); ``--notify send`` (the
    default, the systemd unit) keeps the chokepoint send;
  * ``--lane-receipt`` writes LaneRunReceipt@v2 output fields and exits 0 when
    the run completed (findings are output, not failure); 1 only when the
    database could not be measured (fatal ``dependency_unavailable``).

EXIT CODES
----------
    0  no BLOCK violations (WARN may be present)
    1  at least one BLOCK violation
    2  could not run (no contracts, no database)
  with --lane-receipt: 0 the run completed (findings or not), 1 could not run.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# psycopg2 is imported lazily inside main(), NOT here. The rules in this module
# -- _violation_predicate, _check_single_scale, _alert -- are pure and are tested
# without a database. A module-level driver import made those tests uncollectable
# anywhere psycopg2 is absent, which is every CI runner: the file errored at
# import and the gate went red without running a single assertion. Locally it
# passed, because the venv has the driver.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_PATH = PROJECT_ROOT / "config" / "data_plausibility_contracts.json"

# APPENDED, never prepended: scripts/lib holds modules whose names collide with
# top-level scripts (research_lane_health is both), and putting it first made
# `import research_lane_health` resolve to the library instead of the monitor.
sys.path.append(str(PROJECT_ROOT / "scripts" / "lib"))
from alert_transition import (  # noqa: E402
    TYPE_DATA_INTEGRITY,
    evaluate,
    fingerprint_state,
    previous_fingerprint,
)

#: Durable identity for this condition in the shared alert state machine.
CONDITION_KEY = "data_integrity:data_plausibility"

SCHEMA = "DataPlausibilityReport@v1"
RECEIPT_NAME = "data_plausibility_last_run.json"

#: n8n lane id (config/lane_registry.json, config/n8n_run_allowlist.json, config/n8n_health_contracts.json).
LANE_ID = "n8n-data-plausibility-audit"
#: Host comms-intent route this producer owns (config/host_comms_intent_routes.json).
INTENT_PRODUCER = "data_plausibility_monitor"
INTENT_DOMAIN = "data"
INTENT_KIND = "data_plausibility_violation"
#: LaneRunReceipt@v2 fatal skip: the database could not be measured.
SKIP_DEPENDENCY = "dependency_unavailable"
#: Rules that measure a time window (window_policy) instead of the whole table.
WINDOWED_RULES = ("range", "min", "max", "finite", "single_scale")

NO_CONSUMER_REASON = (
    "this IS a data-integrity gate; an operator or a scheduled run invokes it and "
    "reads the report, nothing imports it. Same shape as check_test_coverage.py "
    "and check_dark_contracts.py."
)


def _db_env() -> dict:
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


def _violation_predicate(contract: dict) -> str:
    """SQL that is TRUE for a row violating the contract.

    NULL is never a violation: absent data is a different problem from wrong
    data, and conflating them is how "no rating" became "Strong Buy".
    """
    col = f'"{contract["column"]}"'
    rule = contract["rule"]

    if rule == "range":
        return f"{col} IS NOT NULL AND NOT ({col} BETWEEN {contract['min']} AND {contract['max']})"
    if rule == "min":
        return f"{col} IS NOT NULL AND {col} < {contract['min']}"
    if rule == "max":
        return f"{col} IS NOT NULL AND {col} > {contract['max']}"
    if rule == "finite":
        # NaN is not comparable, so test it by text. 'NaN'::float = 'NaN'::float
        # is false, which is exactly why these rows survive ordinary range checks.
        return f"{col} IS NOT NULL AND {col}::text IN ('NaN','nan','Infinity','-Infinity')"
    if rule == "single_scale":
        # Cannot be expressed per-row: it is a property of the population.
        return ""
    if rule == "required_fields":
        # A threshold over a window, not a per-row verdict: see _check_required_fields.
        return ""
    if rule == "retired_store":
        # Rows written after the store was retired: see _check_retired_store.
        return ""
    raise ValueError(f"unknown rule {rule!r}")


def _empty_payload_predicate(contract: dict) -> str:
    """SQL that is TRUE for a row whose JSON payload says nothing.

    `{}`, `null`, `[]` and SQL NULL are all "nothing" here -- and unlike the
    numeric rules, NULL IS a violation for this rule, because the point of a
    payload column is to carry the fields; a row that exists with an empty
    payload is a row that LOOKS fresh (its as_of advanced) and carries no data.
    That is exactly how analyst_data_history accumulated 18,772 `{}` rows from
    2026-08-01 that every freshness check read as current.

    With `fields` declared, a payload missing any of them (or holding null for
    it) also counts. The cast to jsonb makes this work for json and jsonb alike.
    """
    col = f'"{contract["column"]}"'
    parts = [
        f"{col} IS NULL",
        f"({col})::jsonb = 'null'::jsonb",
        f"({col})::jsonb = '{{}}'::jsonb",
        f"({col})::jsonb = '[]'::jsonb",
    ]
    for f in contract.get("fields") or []:
        safe = str(f).replace("'", "''")
        parts.append(f"(({col})::jsonb ->> '{safe}') IS NULL")
    return "(" + " OR ".join(parts) + ")"


def _required_fields_sql(contract: dict) -> str:
    """The one query _check_required_fields runs. Separated so it can be asserted
    without a database."""
    table = contract["table"]
    win_col = f'"{contract.get("window_column") or "created_at"}"'
    days = int(contract.get("window_days") or 30)
    pred = _empty_payload_predicate(contract)
    return (
        f"SELECT count(*) FILTER (WHERE {pred}), count(*)"
        f"  FROM {table}"
        f" WHERE {win_col} > now() - interval '{days} days'"
    )


def _check_required_fields(cur, contract: dict) -> dict:
    """A JSON payload column must carry its declared fields. Violation when more
    than `max_empty_pct` of the rows in the window are empty or missing a field.

    Population-level, like single_scale: one empty payload is a fetch that
    found nothing; a majority of them is a producer writing rows without data.
    The window matters because the table's history may legitimately predate the
    fields -- the contract is about what is being written NOW.
    """
    cur.execute(_required_fields_sql(contract))
    empty, total = cur.fetchone()
    empty = int(empty or 0)
    total = int(total or 0)
    max_pct = float(contract.get("max_empty_pct", 0.0))
    pct = (100.0 * empty / total) if total else 0.0
    violating = empty if (total and pct > max_pct) else 0
    days = int(contract.get("window_days") or 30)
    return {
        "violations": violating,
        "total": total,
        "detail": (
            f"{empty:,} of {total:,} rows in the last {days}d have an empty payload"
            f" ({pct:.1f}%; contract allows {max_pct:g}%)"
            + (f"; required fields {contract['fields']}" if contract.get("fields") else "")
        ),
        "samples": [],
    }


def _check_single_scale(cur, contract: dict, window: dict | None = None) -> dict:
    """A column must pick one scale. Both populations present == violation."""
    table, col = contract["table"], f'"{contract["column"]}"'
    where = f" WHERE {window['sql']}" if window else ""
    cur.execute(
        f"SELECT count(*) FILTER (WHERE {col} > 0 AND {col} <= 1),"
        f"       count(*) FILTER (WHERE {col} > 1),"
        f"       count(*) FILTER (WHERE {col} IS NOT NULL)"
        f"  FROM {table}{where}"
    )
    unit, hundred, total = cur.fetchone()
    violating = min(unit, hundred)  # the smaller population is the anomaly
    return {
        "violations": violating if (unit and hundred) else 0,
        "total": total,
        "detail": f"{unit:,} rows in (0,1] and {hundred:,} rows >1" + (f" ({window['label']})" if window else ""),
        "samples": [],
    }


def window_policy(doc: dict | None) -> dict:
    """The window policy from the contracts file (2026-10-18). Pure."""
    pol = dict((doc or {}).get("window_policy") or {})
    pol.setdefault("default_window_days", None)
    pol.setdefault("window_column_candidates", [])
    pol.setdefault("rules", list(WINDOWED_RULES))
    return pol


def alert_policy(doc: dict | None) -> dict:
    """The alert policy from the contracts file (2026-10-18). Pure."""
    pol = dict((doc or {}).get("alert_policy") or {})
    pol.setdefault("pct_bands_pct", [])
    pol.setdefault("min_realert_minutes", None)
    return pol


def window_sql(column: str, days: int) -> str:
    """The row filter for a windowed rule. Separated so it can be asserted without a database."""
    return f"\"{column}\" > now() - interval '{int(days)} days'"


def _resolve_window(cur, contract: dict, policy: dict) -> dict | None:
    """Which time column (if any) bounds this contract's measurement.

    A frozen historical row that violated its contract months ago is debt, not
    news; measuring it every day made the alert fire every day. The window is
    explicit per contract (``window_column`` / ``window_days``), else the
    policy default over the first candidate column the table actually has.
    ``window_days: 0`` opts a contract out (whole table). No time column ->
    whole table, said in the detail rather than guessed.
    """
    if contract.get("rule") not in (policy.get("rules") or ()):
        return None
    days = contract.get("window_days", policy.get("default_window_days"))
    if not days:
        return None
    candidates = [contract["window_column"]] if contract.get("window_column") else list(
        policy.get("window_column_candidates") or [])
    for col in candidates:
        cur.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name=%s",
            (contract["table"], col),
        )
        if cur.fetchone():
            return {"column": col, "days": int(days), "sql": window_sql(col, int(days)),
                    "label": f"last {int(days)}d by {col}"}
    return {"column": None, "days": int(days), "sql": None, "label": "whole table (no time column)"}


def _retired_store_sql(contract: dict) -> str:
    """Empty-payload rows written on or after the store's retirement. Pure."""
    win_col = f'"{contract.get("window_column") or "created_at"}"'
    retired = str(contract["retired_at"]).replace("'", "")
    pred = _empty_payload_predicate(contract)
    return (
        f"SELECT count(*) FILTER (WHERE {pred}), count(*)"
        f"  FROM {contract['table']}"
        f" WHERE {win_col} >= '{retired}'::date"
    )


def _check_retired_store(cur, contract: dict) -> dict:
    """A RETIRED store must stop accumulating empty rows (2026-10-18).

    analyst_data_history's provider died 2026-07-28 and was retired 2026-09-13;
    every row since is ``{}``. The writer no longer inserts empty payloads, so
    the contract now asks the only question left: did an empty row arrive on or
    after ``retired_at``? Rows before it are known, frozen debt.
    """
    cur.execute(_retired_store_sql(contract))
    empty, total = cur.fetchone()
    empty, total = int(empty or 0), int(total or 0)
    return {
        "violations": empty,
        "total": total,
        "detail": f"{empty:,} empty payload row(s) written since the store was retired ({contract['retired_at']})",
        "samples": [],
    }


def _check(cur, contract: dict, policy: dict | None = None) -> dict | None:
    table = contract["table"]
    column = contract["column"]
    policy = policy if policy is not None else window_policy(None)

    cur.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND column_name=%s",
        (table, column),
    )
    if not cur.fetchone():
        return {
            "table": table,
            "column": column,
            "severity": "WARN",
            "violations": 0,
            "total": 0,
            "status": "COLUMN_ABSENT",
            "detail": "declared in contracts but not present in the database",
            "samples": [],
        }

    window = _resolve_window(cur, contract, policy)
    win = window if (window and window.get("sql")) else None
    if contract["rule"] == "single_scale":
        result = _check_single_scale(cur, contract, win)
    elif contract["rule"] == "required_fields":
        result = _check_required_fields(cur, contract)
    elif contract["rule"] == "retired_store":
        result = _check_retired_store(cur, contract)
    else:
        pred = _violation_predicate(contract)
        and_win = f" AND {win['sql']}" if win else ""
        where_win = f" WHERE {win['sql']}" if win else ""
        cur.execute(f"SELECT count(*) FROM {table} WHERE {pred}{and_win}")
        violations = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {table}{where_win}")
        total = cur.fetchone()[0]
        samples = []
        if violations:
            cur.execute(f'SELECT "{column}"::text FROM {table} WHERE {pred}{and_win} LIMIT 3')
            samples = [r[0] for r in cur.fetchall()]
        result = {
            "violations": violations,
            "total": total,
            "detail": f"rule={contract['rule']}" + (f" ({window['label']})" if window else ""),
            "samples": samples,
        }

    return {
        "table": table,
        "column": column,
        "rule": contract["rule"],
        "window": (window or {}).get("label"),
        "severity": contract["severity"],
        "status": "VIOLATION" if result["violations"] else "OK",
        **result,
    }


STATE_PATH = Path.home() / ".local/state/tradeai/data_plausibility_last_alert.json"

#: Notify modes: "send" = the chokepoint send (systemd unit); "queue" = a host comms intent (n8n lane, no sender).
NOTIFY_MODES = ("send", "queue")


def severity_band(violations: int, total: int, bands_pct: list | tuple) -> str:
    """The coarse band a violation count falls in, e.g. ``"10-50%"``. Pure.

    ``bands_pct`` are ascending edges in percent (config alert_policy.pct_bands_pct).
    No edges -> one band, ``"any"``: then only a new / resolved column is news.
    """
    edges = sorted(float(b) for b in (bands_pct or []))
    if not edges:
        return "any"
    pct = (100.0 * violations / total) if total else 100.0
    lo = 0.0
    for edge in edges:
        if pct < edge:
            return f"{lo:g}-{edge:g}%"
        lo = edge
    return f">={lo:g}%"


def alert_fingerprint(blocking: list[dict], bands_pct: list | tuple = ()) -> dict[str, str]:
    """(contract, column, rule) -> "severity:band". Pure (2026-10-18).

    The previous fingerprint carried the raw violation count, and a count that
    moves by one row is a "changed finding set" to the shared state machine, so
    the daily run re-alerted every day on the same known violation. A column
    that starts violating, stops, changes severity or crosses a band is news;
    a count creeping inside its band is not.
    """
    fp: dict[str, str] = {}
    for r in blocking:
        key = f"{r['table']}.{r['column']}:{r.get('rule') or '?'}"
        fp[key] = f"{r.get('severity') or 'BLOCK'}:{severity_band(int(r.get('violations') or 0), int(r.get('total') or 0), bands_pct)}"
    return fp


def intent_execution_id(run_id: str | None = None) -> str:
    """The run id in the comms-intent execution_id alphabet ([A-Za-z0-9_-], <= 40; the store refuses others). Pure."""
    import re as _re

    raw = run_id if run_id is not None else os.environ.get("TRADEAI_RUN_ID", "")
    safe = _re.sub(r"[^A-Za-z0-9_-]", "_", str(raw or ""))[-40:].strip("_")
    return safe or "host"


def _deliver_queue(body: str) -> tuple[bool, object]:
    """n8n lane: QUEUE a host comms intent, never send (config/n8n_run_allowlist.json never-list; AGENTS.md §24.1).

    Raises on refusal (ledger absent, route refused, rate limited) so the caller keeps the finding for the next run.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.lib.host_comms_intents import queue_intent

    head = body.split("\n", 1)[0]
    rest = " ".join(line.strip() for line in body.split("\n")[1:] if line.strip().startswith("•"))
    receipt = queue_intent(
        producer=INTENT_PRODUCER,
        domain=INTENT_DOMAIN,
        kind=INTENT_KIND,
        subject=head,
        summary=rest or head,
        execution_id=intent_execution_id(),
        node=LANE_ID,
    )
    return True, (receipt or {}).get("intent_id")


def _deliver_send(body: str) -> tuple[bool, object]:
    """systemd unit: the host chokepoint send (P1 intent). Never reachable from the n8n entry (lane_main)."""
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import telegram_alert as _ta

    ok = _ta.send_telegram(body, message_class="operator_alert", priority="P1", producer="data_plausibility_monitor")
    message_id = getattr(_ta, "last_message_id", lambda: None)()
    return bool(ok), message_id


def _alert(results: list[dict], blocking: list[dict], *, notify: str = "send",
           bands_pct: list | tuple | None = None, min_realert_minutes: int | None = None) -> dict:
    """The systemd/CLI spelling: picks the channel by ``notify`` and runs :func:`_alert_core`."""
    deliver = _deliver_queue if notify == "queue" else _deliver_send
    return _alert_core(results, blocking, deliver=deliver, channel=notify, bands_pct=bands_pct,
                       min_realert_minutes=min_realert_minutes)


def _alert_core(results: list[dict], blocking: list[dict], *, deliver, channel: str,
                bands_pct: list | tuple | None = None, min_realert_minutes: int | None = None) -> dict:
    """Tell the operator, but only when the picture actually changed.

    An alert that fires every run for a known-open violation trains the reader to
    ignore it, and an ignored alert is worse than none -- it looks like coverage
    while providing none. So the fingerprint is the set of violating
    (contract, column, rule) keys and their severity band (2026-10-18; it was
    the raw counts, which moved daily): a new violation, a resolved one, or a
    band crossing speaks; a steady state stays quiet.

    ``deliver(body) -> (accepted, message_id)`` is the channel; it raises on failure.
    Returns {"notified": bool, "action": str, "channel": channel}.
    """
    notify = channel
    bands = list(bands_pct) if bands_pct is not None else []
    fingerprint = alert_fingerprint(blocking, bands)

    # The suppression decision is the shared state machine's, so a steady
    # violation is quiet for min_realert_minutes and then says so again rather
    # than never. A changed band is a changed state string, so it re-alerts.
    kw = {} if not min_realert_minutes else {"min_realert_minutes": int(min_realert_minutes)}
    t = evaluate(
        CONDITION_KEY,
        fingerprint_state(fingerprint),
        alertable=bool(fingerprint),
        path=STATE_PATH,
        **kw,
    )
    if not t.notify:
        print(f"\n  alert: {t.quiet_reason(**kw)}")
        return {"notified": False, "action": t.action, "channel": notify}
    previous = previous_fingerprint(t.previous)

    if not fingerprint:
        body = (
            "[DATA_INTEGRITY] ✅ Data plausibility: all declared columns now satisfy their "
            "contracts.\n\nPreviously violating: " + ", ".join(previous)
            if previous
            else "[DATA_INTEGRITY] ✅ Data plausibility: all declared columns satisfy their contracts."
        )
    else:
        # A column that starts violating is a live integrity breach and earns an
        # interrupt; a known-open one already reported does not, or the alarm
        # becomes wallpaper. telegram_alert_router routes on "CRITICAL", so the
        # word is load-bearing -- it is the escalation, not decoration. Only a
        # NEWLY violating column gets it.
        newly = [k for k in fingerprint if k not in previous]
        lines = [
            # See the note in check_expected_services._alert: the sentinel, not
            # the wording, is what routes this immediately.
            (
                "[DATA_INTEGRITY] 🚨 A new column is off its declared scale"
                if newly
                else "[DATA_INTEGRITY] 🚨 Data plausibility — declared scale violated"
            ),
            "",
            "A value off its declared scale is not a rounding problem. The Finviz",
            'column shift published stocks down -100% as "Strong Buy" for five',
            "months because nothing measured this.",
            "",
        ]
        for r in sorted(blocking, key=lambda x: -x["violations"]):
            pct = (100.0 * r["violations"] / r["total"]) if r["total"] else 0.0
            lines.append(f"• {r['table']}.{r['column']}")
            lines.append(f"    {r['violations']:,} of {r['total']:,} rows ({pct:.1f}%) — {r['detail']}")
        if newly:
            lines += ["", "NEW since the last run: " + ", ".join(newly)]
        resolved = [k for k in previous if k not in fingerprint]
        if resolved:
            lines += ["", "Resolved since last run: " + ", ".join(resolved)]
        lines += [
            "",
            "Either the data is wrong or the contract is wrong.",
            "config/data_plausibility_contracts.json carries the reasoning.",
        ]
        body = "\n".join(lines)

    try:
        ok, message_id = deliver(body)
        print(f"\n  alert: {'accepted' if ok else 'NOT accepted'} by the platform ({notify})")
    except Exception as exc:
        # An alerting failure must never mask the finding it was carrying, and
        # must not consume the transition either — the next run has to be able
        # to say it again.
        t.rollback()
        print(f"\n  alert: FAILED to {notify} ({exc}). The findings above still stand.", file=sys.stderr)
        return {"notified": False, "action": "failed", "channel": notify, "error": type(exc).__name__}

    rec = t.commit(
        body=body,
        alert_type=TYPE_DATA_INTEGRITY,
        source_script="data_plausibility_monitor.py",
        telegram_message_id=message_id if notify == "send" else None,
        payload={"violating_columns": sorted(fingerprint), "channel": notify},
    )
    print(f"  alert: {t.action} recorded (message_id={message_id}, "
          f"alert_event={rec['alert_event_id']}, resolved={rec['resolved_rows']})")
    return {"notified": True, "action": t.action, "channel": notify}


def receipt_detail(results: list[dict], blocking: list[dict]) -> dict:
    """Receipt body beyond checked/off: the blocking items, the violation count and one row per rule (2026-10-21).

    GET /api/v2/system/data-plausibility serves this file; without the per-rule rows a page could only say "0 off".
    Samples are left out (they are row values, and the page needs the rule, not the data). Pure."""
    rules = [
        {
            "table": r.get("table"),
            "column": r.get("column"),
            "status": r.get("status"),
            "severity": r.get("severity"),
            "violations": r.get("violations"),
            "total": r.get("total"),
            "detail": str(r.get("detail") or "")[:240],
        }
        for r in results
    ]
    return {
        "blocking_items": [f"{r['table']}.{r['column']}" for r in blocking],
        "violations": sum(1 for r in results if r.get("status") == "VIOLATION"),
        "blocking": len(blocking),
        "results": rules,
    }


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
                    "ran_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
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


def lane_output(results: list[dict] | None, *, error: str | None = None) -> dict:
    """LaneRunReceipt@v2 output fields for one run (unit: declared contracts measured). Pure.

    produced = contracts measured (OK or VIOLATION -- a finding IS output);
    attempted = every declared contract; COLUMN_ABSENT / CHECK_FAILED are named
    skips. A database that could not be reached is the fatal skip
    ``dependency_unavailable``.
    """
    if error:
        return {"produced_count": 0, "attempted_count": 0, "skipped_reasons": {SKIP_DEPENDENCY: 1},
                "empty_reason": None}
    rows = results or []
    produced = sum(1 for r in rows if r.get("status") in ("OK", "VIOLATION"))
    skipped: dict[str, int] = {}
    for r in rows:
        st = r.get("status")
        if st not in ("OK", "VIOLATION"):
            skipped[str(st).lower()] = skipped.get(str(st).lower(), 0) + 1
    return {"produced_count": produced, "attempted_count": len(rows), "skipped_reasons": skipped,
            "empty_reason": None}


def _lane_receipt_lib():
    sys.path.insert(0, str(PROJECT_ROOT))
    from scripts.lib import lane_last_receipt as lr

    return lr


#: The LaneRunReceipt@v2 output fields of the last receipt this process wrote (the n8n entry prints them).
LAST_LANE_OUTPUT: dict = {}


def _write_lane_receipt(*, ok: bool, started_at: str, summary: dict, output: dict, error: str | None = None):
    LAST_LANE_OUTPUT.clear()
    LAST_LANE_OUTPUT.update(output)
    lr = _lane_receipt_lib()
    return lr.write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        started_at=started_at,
        script="scripts/data_plausibility_monitor.py",
        summary=summary,
        error=error,
        output=output,
    )


def _connect_db():
    """A read-only session, or raise. Separated so the CLI can be exercised without a database."""
    env = _db_env()
    if not env.get("DB_NAME"):
        raise RuntimeError("database settings unavailable")
    import psycopg2  # noqa: PLC0415 — see the note beside the imports

    conn = psycopg2.connect(
        host=env["DB_HOST"],
        port=env.get("DB_PORT", 5432),
        dbname=env["DB_NAME"],
        user=env["DB_USER"],
        password=env["DB_PASSWORD"],
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


def measure(cur, doc: dict) -> list[dict]:
    """Measure every declared contract. A broken contract must not hide the others."""
    policy = window_policy(doc)
    results = []
    for contract in doc["contracts"]:
        try:
            results.append(_check(cur, contract, policy))
        except Exception as exc:  # a broken contract must not hide the others
            results.append(
                {
                    "table": contract["table"],
                    "column": contract["column"],
                    "rule": contract.get("rule"),
                    "severity": "WARN",
                    "status": "CHECK_FAILED",
                    "violations": 0,
                    "total": 0,
                    "detail": str(exc)[:160],
                    "samples": [],
                }
            )
    return results


def _parser(lane: bool = False) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--alert", action="store_true", help="notify the operator when the violation set changes")
    if not lane:
        ap.add_argument("--notify", choices=NOTIFY_MODES, default="send",
                        help="send = chokepoint send (systemd unit); queue = host comms intent (no sender)")
        ap.add_argument("--lane-receipt", action="store_true",
                        help=f"write the LaneRunReceipt@v2 for lane {LANE_ID}; exit 0 when the run completed")
    ap.add_argument("--dry-run", action="store_true",
                    help="measure (read-only) and print; write no receipt, no alert state, notify nobody")
    return ap


def main(argv: list[str] | None = None, *, connect=None) -> int:
    """systemd unit / operator CLI. ``--notify send`` (default) uses the chokepoint; ``queue`` a host intent."""
    args = _parser().parse_args(argv)
    deliver = _deliver_queue if args.notify == "queue" else _deliver_send
    return _run(args, connect=connect, deliver=deliver)


def lane_main(argv: list[str] | None = None, *, connect=None) -> int:
    """n8n lane n8n-data-plausibility-audit (entry scripts/n8n_data_plausibility_audit.py).

    Always writes the LaneRunReceipt@v2 (unless --dry-run) and, with --alert, QUEUES a host comms intent. It never
    references the chokepoint send, so the dispatcher sender gate (scripts/lib/advisory_lane_guard.py, definition-
    granular) sees no sender on this lane.
    """
    args = _parser(lane=True).parse_args(argv)
    args.notify, args.lane_receipt = "queue", not args.dry_run
    return _run(args, connect=connect, deliver=_deliver_queue)


def _run(args, *, connect=None, deliver) -> int:
    if args.dry_run and (args.alert or args.lane_receipt):
        print("ERROR: --dry-run writes nothing; it cannot be combined with --alert or --lane-receipt", file=sys.stderr)
        return 2
    started_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

    if not CONTRACTS_PATH.exists():
        print(f"ERROR: no contracts at {CONTRACTS_PATH}", file=sys.stderr)
        return 2
    doc = json.loads(CONTRACTS_PATH.read_text())
    apol = alert_policy(doc)

    def _fatal(msg: str) -> int:
        print(f"ERROR: {msg}", file=sys.stderr)
        if args.lane_receipt:
            _write_lane_receipt(ok=False, started_at=started_at, summary={"error": msg[:120]},
                                output=lane_output(None, error=msg), error=msg[:120])
            return 1
        return 2

    try:
        if connect is not None:
            conn = connect()
        else:
            env = _db_env()
            if not env.get("DB_NAME"):
                return _fatal("database settings unavailable")
            try:
                import psycopg2  # noqa: F401,PLC0415 — see the note beside the imports
            except ImportError:
                return _fatal("psycopg2 is not installed; cannot measure the database.")
            conn = _connect_db()
    except Exception as exc:  # noqa: BLE001 — cannot-measure is a fatal skip, never a green run
        return _fatal(f"could not connect: {type(exc).__name__}")
    cur = conn.cursor()
    results = measure(cur, doc)
    cur.close()
    conn.close()

    blocking = [r for r in results if r["status"] == "VIOLATION" and r["severity"] == "BLOCK"]

    if args.json:
        print(
            json.dumps(
                {
                    "schema": "DataPlausibilityReport@v1",
                    "checked": len(results),
                    "violations": sum(1 for r in results if r["status"] == "VIOLATION"),
                    "blocking": len(blocking),
                    "fingerprint": alert_fingerprint(blocking, apol["pct_bands_pct"]),
                    "results": results,
                },
                indent=2,
                default=str,
            )
        )
    else:
        print("Data plausibility — declared columns measured against declared scale")
        print("=" * 78)
        for r in sorted(results, key=lambda x: (x["status"] != "VIOLATION", x["table"])):
            mark = "OK   " if r["status"] == "OK" else f"{r['severity']:<5}"
            pct = (100.0 * r["violations"] / r["total"]) if r["total"] else 0.0
            print(f"  [{mark}] {r['table']}.{r['column']}")
            if r["status"] == "VIOLATION":
                print(f"           {r['violations']:,} of {r['total']:,} rows ({pct:.1f}%) — {r['detail']}")
                if r["samples"]:
                    print(f"           samples: {r['samples']}")
            elif r["status"] != "OK":
                print(f"           {r['status']}: {r['detail']}")
        print("-" * 78)
        print(
            f"  checked={len(results)}  violations="
            f"{sum(1 for r in results if r['status'] == 'VIOLATION')}  blocking={len(blocking)}"
        )
        if blocking:
            print("\n  A BLOCK violation means the value cannot be valid on its declared")
            print("  scale. Either the data is wrong or the contract is wrong; both are")
            print("  worth a look, and neither is visible without this check.")

    if args.dry_run:
        print(f"\n  DRY RUN — nothing written; alert fingerprint would be "
              f"{json.dumps(alert_fingerprint(blocking, apol['pct_bands_pct']), sort_keys=True)}")
        return 1 if blocking else 0

    if not args.json:
        _write_run_receipt(
            len(results), len(blocking), receipt_detail(results, blocking)
        )

    alert = None
    if args.alert:
        alert = _alert_core(results, blocking, deliver=deliver, channel=args.notify, bands_pct=apol["pct_bands_pct"],
                            min_realert_minutes=apol["min_realert_minutes"])

    if args.lane_receipt:
        summary = {
            "checked": len(results),
            "blocking": len(blocking),
            "blocking_items": [f"{r['table']}.{r['column']}" for r in blocking][:20],
            "alert": (alert or {}).get("action"),
            "notify": args.notify if args.alert else None,
        }
        ok = not (alert and alert.get("action") == "failed")
        _write_lane_receipt(ok=ok, started_at=started_at, summary=summary, output=lane_output(results),
                            error=None if ok else "alert_delivery_failed")
        return 0 if ok else 1

    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
