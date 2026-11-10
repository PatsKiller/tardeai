#!/usr/bin/env python3
"""CC v3 audit re-measure: one row per audit item, measured on live, read-only.

Why this exists: the CC v3 due-diligence audit (2026-11-09) found outcomes, not code paths. On 11-10 the
items LQ-1607..1612 were marked LIVE while their lanes stayed shadow or unregistered, so the outcomes were
not fixed. DONE for an audit item is its metric re-measured on live. This script is that measurement.

Every row is ``item, metric, value, threshold, PASS/FAIL, detail``. It never writes:

* Postgres is opened with ``default_transaction_read_only=on`` (PGOPTIONS) AND a read-only session; the
  connection is rolled back and closed, never committed.
* Files are only stat'ed or read (the retrieval receipt log is read from its tail).
* ``crontab -l`` is the only subprocess (read-only listing).
* It never calls the portfolio server (:7777).

Usage::

    PGOPTIONS='-c default_transaction_read_only=on' .venv/bin/python scripts/ops/ccv3_audit_remeasure.py
    ... --json            # machine-readable rows
    ... --state-root DIR  # persistent state root (default: TRADEAI_STATE_ROOT, else the live layout)
    ... --registry FILE   # lane registry (default: the served release's config/lane_registry.json)

Exit code: 0 when every row was measured (PASS or FAIL); 2 when a row could not be measured (ERROR).
A FAIL is a finding, not a crash; the scorecard is the output, not the exit code.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

READ_ONLY_PGOPTIONS = "-c default_transaction_read_only=on"
RELEASES = Path(os.environ.get("TRADEAI_RELEASES_ROOT") or Path.home() / "trade-ai-releases")
LIVE_STATE_ROOT = RELEASES / "persistent-state"
LIVE_CURRENT = RELEASES / "portfolio-server" / "CURRENT"

RECEIPT_TAIL = 2000
ALERT_STALE_MINUTES = 10
CATALYST_WINDOW_HOURS = 24
OVERVIEW_MAX_AGE_S = 300
CAPITAL_PLAN_MAX_AGE_H = 26.0
REGIME_MAX_AGE_H = 24.0
CRONTAB_AUDIT_BASELINE_ACTIVE = 298  # audit 2026-11-09: 298 active crontab lines

#: Lanes whose outcome the audit depends on. Live = state ACTIVE, not ``dispatch.mode == dry_run``, and for n8n a
#: live stage (canary or cutover, scripts/check_n8n_workflow_framework.py); a cron/systemd row in stage shadow is not live.
LIVE_STAGES = ("canary", "cutover")
LANE_THRESHOLD = "registered, ACTIVE, live stage, not dry_run"
AUDIT_LANES: tuple[str, ...] = (
    "alert-delivery-queue-hygiene",
    "overview-projection",
    "cio-capital-plan-record",
    "frozen-output-monitor",
    "rag-indexer",
    "market-regime-collector",
    "news-to-catalyst",
    "event-detector",
    "hermes-news-bridge",
    "sec-filings-feed",
)

Query = Callable[[str, Sequence[Any]], list[tuple]]


@dataclass
class Row:
    item: str
    metric: str
    value: Any
    threshold: str
    status: str  # PASS | FAIL | ERROR
    detail: str = ""


def _verdict(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _error_row(item: str, metric: str, threshold: str, exc: BaseException) -> Row:
    return Row(item, metric, None, threshold, "ERROR", f"{type(exc).__name__}: {exc}"[:300])


# ---------------------------------------------------------------- DB items


def alert_queue(q: Query) -> list[Row]:
    """Delivery queue: nothing queued past the 10-minute contract, something completed, nothing suppressed."""
    rows = q(
        "SELECT"
        " count(*) FILTER (WHERE delivery_status = 'queued'),"
        " count(*) FILTER (WHERE delivery_status = 'queued' AND created_at < now() - %s * interval '1 minute'),"
        " count(*) FILTER (WHERE completed_at IS NOT NULL AND delivery_status NOT IN ('queued', 'suppressed')),"
        " count(*) FILTER (WHERE delivery_status = 'suppressed' AND created_at > now() - interval '24 hours')"
        " FROM alert_notification_deliveries",
        (ALERT_STALE_MINUTES,),
    )
    queued, stale, completed, suppressed = (int(v or 0) for v in rows[0])
    return [
        Row("alert_queue", "queued_older_than_10m", stale, "== 0", _verdict(stale == 0), f"queued total {queued}"),
        Row("alert_queue", "completed_total", completed, ">= 1", _verdict(completed >= 1),
            "rows completed as sent, delivered or expired (suppressed excluded)"),
        Row("alert_queue", "suppressed_not_delivered_24h", suppressed, "== 0", _verdict(suppressed == 0),
            "alerts written as suppressed in 24h: raised, never delivered to anyone"),
    ]


def regime(q: Query, now: datetime) -> list[Row]:
    rows = q(
        "SELECT generated_at, regime_label, breadth_state FROM market_regime_snapshots"
        " ORDER BY generated_at DESC NULLS LAST LIMIT 1",
        (),
    )
    if not rows or rows[0][0] is None:
        return [
            Row("regime", "snapshot_age_h", None, f"<= {REGIME_MAX_AGE_H:g}", "FAIL", "no snapshot"),
            Row("regime", "breadth_measured", None, "!= not_measured", "FAIL", "no snapshot"),
        ]
    generated_at, label, breadth = rows[0]
    age_h = round((now - generated_at).total_seconds() / 3600.0, 2)
    measured = bool(breadth) and str(breadth).lower() not in ("not_measured", "unknown")
    return [
        Row("regime", "snapshot_age_h", age_h, f"<= {REGIME_MAX_AGE_H:g}", _verdict(age_h <= REGIME_MAX_AGE_H),
            f"label {label}, generated_at {generated_at.isoformat()}"),
        Row("regime", "breadth_measured", breadth, "!= not_measured", _verdict(measured)),
    ]


def catalyst_lead_time(q: Query) -> list[Row]:
    """Lag = created_at - published_at over catalysts created in the last 24 h (negative lag counts as 0)."""
    rows = q(
        "SELECT EXTRACT(EPOCH FROM (created_at - published_at)) FROM catalyst_events"
        " WHERE created_at > now() - %s * interval '1 hour'",
        (CATALYST_WINDOW_HOURS,),
    )
    lags = [max(0.0, float(r[0])) / 3600.0 for r in rows if r[0] is not None]
    n_null = sum(1 for r in rows if r[0] is None)
    n = len(lags)
    detail = f"{n} events with published_at in {CATALYST_WINDOW_HOURS}h ({n_null} without published_at)"
    if n == 0:
        return [Row("catalyst_lead_time", m, None, t, "FAIL", detail) for m, t in (
            ("share_within_1h", ">= 0.50"), ("share_within_6h", ">= 0.90"), ("median_h", "<= 1.0"))]
    w1 = round(sum(1 for x in lags if x <= 1.0) / n, 4)
    w6 = round(sum(1 for x in lags if x <= 6.0) / n, 4)
    med = round(statistics.median(lags), 2)
    return [
        Row("catalyst_lead_time", "share_within_1h", w1, ">= 0.50", _verdict(w1 >= 0.50), detail),
        Row("catalyst_lead_time", "share_within_6h", w6, ">= 0.90", _verdict(w6 >= 0.90), detail),
        Row("catalyst_lead_time", "median_h", med, "<= 1.0", _verdict(med <= 1.0), detail),
    ]


def yfinance_quotes(q: Query) -> list[Row]:
    rows = q(
        "SELECT source, count(*) FROM market_quotes WHERE fetched_at > now() - interval '1 hour' GROUP BY 1",
        (),
    )
    by_source = {str(s): int(c) for s, c in rows}
    yf = sum(c for s, c in by_source.items() if s.lower().startswith("yfinance"))
    detail = ", ".join(f"{s} {c}" for s, c in sorted(by_source.items())) or "no rows in the last hour"
    return [Row("quotes", "yfinance_rows_last_1h", yf, "== 0", _verdict(yf == 0), detail)]


def memory_index(q: Query) -> list[Row]:
    rows = q("SELECT count(*), max(projected_at) FROM intelligence.embedding", ())
    count, latest = rows[0]
    count = int(count or 0)
    return [Row("memory", "intelligence_embedding_rows", count, ">= 1", _verdict(count >= 1),
                f"latest projected_at {latest.isoformat() if latest else None}")]


# ---------------------------------------------------------------- file items


def _tail_lines(path: Path, n: int, chunk: int = 1 << 20) -> list[bytes]:
    """The last ``n`` complete lines of ``path``, read backwards (the log is tens of MB)."""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        end = fh.tell()
        buf = b""
        pos = end
        while pos > 0 and buf.count(b"\n") <= n:
            step = min(chunk, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
    lines = [ln for ln in buf.split(b"\n") if ln.strip()]
    if pos > 0:  # the first line may be cut mid-record
        lines = lines[1:]
    return lines[-n:]


def retrieval_mode(state_root: Path) -> list[Row]:
    path = state_root / "data" / "cio" / "retrieval_receipts.jsonl"
    if not path.exists():
        return [Row("retrieval", f"shadow_share_last_{RECEIPT_TAIL}", None, "< 1.0", "FAIL", f"missing {path}")]
    modes: dict[str, int] = {}
    bad = 0
    for raw in _tail_lines(path, RECEIPT_TAIL):
        try:
            mode = str(json.loads(raw).get("mode") or "UNKNOWN").upper()
        except (ValueError, AttributeError):
            bad += 1
            continue
        modes[mode] = modes.get(mode, 0) + 1
    total = sum(modes.values())
    if total == 0:
        return [Row("retrieval", f"shadow_share_last_{RECEIPT_TAIL}", None, "< 1.0", "FAIL", "no parseable receipts")]
    share = round(modes.get("SHADOW", 0) / total, 4)
    detail = ", ".join(f"{m} {c}" for m, c in sorted(modes.items())) + (f", unparseable {bad}" if bad else "")
    return [Row("retrieval", f"shadow_share_last_{RECEIPT_TAIL}", share, "< 1.0", _verdict(share < 1.0), detail)]


def _file_age_s(path: Path, now: datetime) -> float | None:
    try:
        return round(now.timestamp() - path.stat().st_mtime, 1)
    except FileNotFoundError:
        return None


def overview_projection(state_root: Path, now: datetime) -> list[Row]:
    path = state_root / "data" / "runtime" / "overview_projection.json"
    age = _file_age_s(path, now)
    if age is None:
        return [Row("overview_projection", "file_age_s", None, f"<= {OVERVIEW_MAX_AGE_S}", "FAIL", f"missing {path}")]
    return [Row("overview_projection", "file_age_s", age, f"<= {OVERVIEW_MAX_AGE_S}",
                _verdict(age <= OVERVIEW_MAX_AGE_S), str(path))]


def capital_plan_record(state_root: Path, now: datetime) -> list[Row]:
    """Age of the scheduled writer's last receipt; the journal's mtime is shown for context only."""
    receipt = state_root / "data" / "runtime" / "cio-capital-plan-record_last.json"
    journal = state_root / "data" / "cio" / "cio_capital_plan_decisions.jsonl"
    j_age = _file_age_s(journal, now)
    j_txt = f"journal age {round(j_age / 3600, 2)}h" if j_age is not None else "journal missing"
    age = _file_age_s(receipt, now)
    if age is None:
        return [Row("capital_plan_record", "lane_receipt_age_h", None, f"<= {CAPITAL_PLAN_MAX_AGE_H:g}", "FAIL",
                    f"no lane receipt {receipt.name}; {j_txt}")]
    age_h = round(age / 3600.0, 2)
    return [Row("capital_plan_record", "lane_receipt_age_h", age_h, f"<= {CAPITAL_PLAN_MAX_AGE_H:g}",
                _verdict(age_h <= CAPITAL_PLAN_MAX_AGE_H), j_txt)]


def lane_stages(registry: dict, lanes: Iterable[str] = AUDIT_LANES) -> list[Row]:
    by_id = {str(l.get("lane_id")): l for l in registry.get("lanes", []) if isinstance(l, dict)}
    out: list[Row] = []
    for lane_id in lanes:
        lane = by_id.get(lane_id)
        if lane is None:
            out.append(Row("lane_stage", lane_id, "unregistered", LANE_THRESHOLD, "FAIL"))
            continue
        sched = lane.get("scheduler") or {}
        kind, stage, state = sched.get("kind"), sched.get("stage"), lane.get("state")
        mode = (lane.get("dispatch") or {}).get("mode") or sched.get("mode")
        value = f"{state}/{kind}/{stage or '-'}" + (f"/{mode}" if mode else "")
        if state != "ACTIVE" or mode == "dry_run":
            ok = False
        elif kind == "n8n":
            ok = stage in LIVE_STAGES
        else:
            ok = kind in ("cron", "systemd") and stage != "shadow"
        cadence = sched.get("cadence") or sched.get("expression") or ""
        out.append(Row("lane_stage", lane_id, value, LANE_THRESHOLD, _verdict(ok),
                       f"cadence {cadence}"))
    return out


def crontab_lines(run: Callable[[], str]) -> list[Row]:
    text = run()
    lines = text.splitlines()
    active = sum(1 for ln in lines if ln.strip() and not ln.lstrip().startswith("#"))
    return [Row("crontab", "active_lines", active, f"<= {CRONTAB_AUDIT_BASELINE_ACTIVE} (audit 11-09)",
                _verdict(active <= CRONTAB_AUDIT_BASELINE_ACTIVE), f"wc -l {len(lines)}")]


def _crontab_l() -> str:
    proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=20, check=False)
    if proc.returncode != 0 and "no crontab" in (proc.stderr or "").lower():
        return ""
    if proc.returncode != 0:
        raise RuntimeError(f"crontab -l exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    return proc.stdout


# ---------------------------------------------------------------- wiring


def pg_query_factory() -> tuple[Query, Callable[[], None]]:
    """A read-only psycopg2 query function and its closer. Writes are refused by the server, twice over."""
    import psycopg2  # local import: tests never need a driver

    opts = os.environ.get("PGOPTIONS", "")
    if "default_transaction_read_only=on" not in opts:
        os.environ["PGOPTIONS"] = (opts + " " + READ_ONLY_PGOPTIONS).strip()
    conn = psycopg2.connect(
        dbname=os.environ.get("PGDATABASE", "trade_ai"),
        user=os.environ.get("PGUSER") or getpass.getuser(),
        host=os.environ.get("PGHOST", "/var/run/postgresql"),
        application_name="ccv3_audit_remeasure",
    )
    conn.set_session(readonly=True, autocommit=False)

    def query(sql: str, params: Sequence[Any]) -> list[tuple]:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        conn.rollback()
        return rows

    def close() -> None:
        conn.rollback()
        conn.close()

    return query, close


def measure(
    query: Query,
    state_root: Path,
    registry: dict,
    crontab: Callable[[], str],
    now: datetime | None = None,
) -> list[Row]:
    now = now or datetime.now(timezone.utc)
    steps: list[tuple[str, str, str, Callable[[], list[Row]]]] = [
        ("alert_queue", "queue", "see rows", lambda: alert_queue(query)),
        ("retrieval", f"shadow_share_last_{RECEIPT_TAIL}", "< 1.0", lambda: retrieval_mode(state_root)),
        ("regime", "snapshot", f"<= {REGIME_MAX_AGE_H:g}h", lambda: regime(query, now)),
        ("catalyst_lead_time", "lag", "see rows", lambda: catalyst_lead_time(query)),
        ("overview_projection", "file_age_s", f"<= {OVERVIEW_MAX_AGE_S}", lambda: overview_projection(state_root, now)),
        ("capital_plan_record", "lane_receipt_age_h", f"<= {CAPITAL_PLAN_MAX_AGE_H:g}",
         lambda: capital_plan_record(state_root, now)),
        ("quotes", "yfinance_rows_last_1h", "== 0", lambda: yfinance_quotes(query)),
        ("memory", "intelligence_embedding_rows", ">= 1", lambda: memory_index(query)),
        ("lane_stage", "registry", LANE_THRESHOLD, lambda: lane_stages(registry)),
        ("crontab", "active_lines", f"<= {CRONTAB_AUDIT_BASELINE_ACTIVE}", lambda: crontab_lines(crontab)),
    ]
    rows: list[Row] = []
    for item, metric, threshold, fn in steps:
        try:
            rows.extend(fn())
        except Exception as exc:  # noqa: BLE001 -- one broken probe must not hide the other rows; it prints as ERROR
            rows.append(_error_row(item, metric, threshold, exc))
    return rows


def render(rows: list[Row], now: datetime) -> str:
    head = ("item", "metric", "value", "threshold", "status", "detail")
    table = [head] + [(r.item, r.metric, "" if r.value is None else str(r.value), r.threshold, r.status, r.detail)
                      for r in rows]
    widths = [max(len(t[i]) for t in table) for i in range(5)]
    out = [f"# CC v3 audit re-measure  as_of={now.isoformat(timespec='seconds')}"]
    for t in table:
        out.append("  ".join(t[i].ljust(widths[i]) for i in range(5)) + "  " + t[5])
    counts = {s: sum(1 for r in rows if r.status == s) for s in ("PASS", "FAIL", "ERROR")}
    out.append(f"# PASS {counts['PASS']}  FAIL {counts['FAIL']}  ERROR {counts['ERROR']}  of {len(rows)}")
    return "\n".join(out)


def _default_state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    return Path(env) if env else LIVE_STATE_ROOT


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--json", action="store_true", help="print rows as JSON")
    ap.add_argument("--state-root", type=Path, default=None)
    ap.add_argument("--registry", type=Path, default=LIVE_CURRENT / "config" / "lane_registry.json")
    args = ap.parse_args(argv)

    now = datetime.now(timezone.utc)
    state_root = args.state_root or _default_state_root()
    try:
        registry = json.loads(args.registry.read_text())
    except (OSError, ValueError) as exc:
        print(f"cannot read registry {args.registry}: {exc}", file=sys.stderr)
        registry = {"lanes": []}
    query, close = pg_query_factory()
    try:
        rows = measure(query, state_root, registry, _crontab_l, now)
    finally:
        close()
    if args.json:
        print(json.dumps({"as_of": now.isoformat(), "registry": str(args.registry),
                          "rows": [asdict(r) for r in rows]}, indent=1, default=str))
    else:
        print(render(rows, now))
    return 2 if any(r.status == "ERROR" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
