#!/usr/bin/env python3
"""report_slo_burn_rate.py — current error-budget burn for the three SLOs, from real rows.

    .venv/bin/python scripts/report_slo_burn_rate.py
    .venv/bin/python scripts/report_slo_burn_rate.py --json
    .venv/bin/python scripts/report_slo_burn_rate.py --slo card_freshness

WHY THIS FILE AND NOT JUST THE CALCULATOR
-----------------------------------------
A burn-rate calculator with no data feed is another unscheduled validator, and
this repository already holds ~141 of those -- that pattern IS the audit's core
finding. So the feed came first: every table and column named in
config/slo_targets.json was read out of information_schema on 2026-09-22 and
counted before a target was written down. This script closes the loop by
computing the budget from those same rows.

REPORT ONLY. It opens a read-only cursor, prints, and writes one receipt under
artifacts/ (gitignored). It sends no alert, touches no queue, and is deliberately
attached to no scheduler -- arming anything on these budgets is an operator
decision under AGENTS.md §17.

AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.lib.slo_burn_rate import (  # noqa: E402
    SLOConfig,
    WindowSample,
    evaluate,
    freshness_window_sample,
    load_slo_configs,
)

SCHEMA = "SLOBurnRateReport@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
#: Stated explicitly because "there is a script for it" has repeatedly been
#: mistaken in this repo for "something runs it".
SCHEDULED_ENTRYPOINT = "NONE — unscheduled by design. Scheduling is operator-only (AGENTS.md §17)."

CONFIG_REL = "config/slo_targets.json"

_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
# A predicate comes from a repo-controlled config, but it is still interpolated
# into SQL, so it is held to a conservative charset: no semicolons, no comment
# markers, nothing that could carry a second statement.
_PREDICATE_RE = re.compile(r"^[A-Za-z0-9_ ()'.,<>=!%-]+$")


def _identifier(value: str, what: str) -> str:
    text = str(value or "")
    if not _IDENT_RE.match(text):
        raise ValueError(f"{what} is not a plain lowercase identifier: {value!r}")
    return text


def _predicate(value: str) -> str:
    text = str(value or "").strip()
    if not text or not _PREDICATE_RE.match(text) or "--" in text or "/*" in text:
        raise ValueError(f"good_predicate rejected: {value!r}")
    return text


def load_document(root: Path | None = None) -> dict[str, Any]:
    path = (root or PROJECT_ROOT) / CONFIG_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "SLOTargets@v1":
        raise ValueError(f"unexpected slo config schema: {data.get('schema')}")
    return data


def build_configs(document: dict[str, Any]) -> dict[str, SLOConfig]:
    """Parse the document into validated configs (ValueError on anything bad)."""
    return load_slo_configs(document)


def feed_for(document: dict[str, Any], name: str) -> dict[str, Any]:
    for entry in document.get("slos", []):
        if entry.get("name") == name:
            feed = entry.get("feed")
            if not isinstance(feed, dict):
                raise ValueError(f"{name}: 'feed' block is required — an SLO with no feed is not measurable")
            return feed
    raise KeyError(name)


def connect():
    """Open a connection, or return None. A missing database is not an error here.

    Returning None rather than raising is deliberate: this report runs in
    worktrees and on machines with no database, and the honest output there is
    "unavailable", not a traceback that reads like the SLOs are broken.
    """
    try:
        import db_adapter  # noqa: F401  # imported for its .env bootstrap side effect
        import psycopg2

        return psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            port=os.getenv("DB_PORT", "5432"),
            connect_timeout=10,
        )
    except Exception:
        return None


def ratio_samples(conn, feed: dict[str, Any], windows: tuple[int, ...]) -> dict[int, WindowSample]:
    """good/total over each window, straight from the rows."""
    table = _identifier(feed["table"], "feed.table")
    ts_col = _identifier(feed["timestamp_column"], "feed.timestamp_column")
    predicate = _predicate(feed["good_predicate"])
    sql = (
        f"SELECT count(*) AS total, count(*) FILTER (WHERE {predicate}) AS good "  # noqa: S608 — validated identifiers
        f"FROM {table} WHERE {ts_col} > now() - make_interval(secs => %s) AND {ts_col} <= now()"
    )
    out: dict[int, WindowSample] = {}
    with conn.cursor() as cur:
        for window in windows:
            cur.execute(sql, (window,))
            total, good = cur.fetchone()
            out[window] = WindowSample(window_seconds=window, good=int(good or 0), total=int(total or 0))
    return out


def freshness_samples(conn, feed: dict[str, Any], windows: tuple[int, ...]) -> dict[int, WindowSample]:
    """Bucket coverage over each window, from the producer's own timestamps.

    One query fetches distinct minute-truncated timestamps across the widest
    window PLUS the staleness budget -- without that extra lookback the oldest
    buckets would be scored stale for want of history rather than for want of
    freshness -- and the bucketing itself is done by the pure function in the
    library, which is what makes it testable with no database.
    """
    table = _identifier(feed["table"], "feed.table")
    ts_col = _identifier(feed["timestamp_column"], "feed.timestamp_column")
    bucket = int(feed["bucket_seconds"])
    staleness = int(feed["staleness_budget_seconds"])
    lookback = max(windows) + staleness

    sql = (
        f"SELECT DISTINCT extract(epoch FROM date_trunc('minute', {ts_col})) AS t "  # noqa: S608 — validated identifiers
        f"FROM {table} WHERE {ts_col} > now() - make_interval(secs => %s) AND {ts_col} <= now() ORDER BY t"
    )
    with conn.cursor() as cur:
        cur.execute("SELECT extract(epoch FROM now())")
        now = float(cur.fetchone()[0])
        cur.execute(sql, (lookback,))
        event_times = [float(r[0]) for r in cur.fetchall()]

    return {
        window: freshness_window_sample(
            event_times=event_times,
            now=now,
            window_seconds=window,
            bucket_seconds=bucket,
            staleness_budget_seconds=staleness,
        )
        for window in windows
    }


def collect_samples(conn, feed: dict[str, Any], windows: tuple[int, ...]) -> dict[int, WindowSample]:
    kind = feed.get("kind")
    if kind == "ratio_of_rows":
        return ratio_samples(conn, feed, windows)
    if kind == "freshness_buckets":
        return freshness_samples(conn, feed, windows)
    raise ValueError(f"unknown feed kind: {kind!r}")


def run(document: dict[str, Any], conn, only: str | None = None) -> dict[str, Any]:
    """Evaluate every configured SLO. Never raises for a dead database."""
    configs = build_configs(document)
    results: list[dict[str, Any]] = []
    for name, cfg in configs.items():
        if only and name != only:
            continue
        feed = feed_for(document, name)
        if conn is None:
            results.append(
                {
                    "slo": name,
                    "status": "UNAVAILABLE",
                    "why": "no database connection; burn rate not measured (reported as unknown, not as zero)",
                    "feed": {k: feed.get(k) for k in ("kind", "table", "timestamp_column")},
                }
            )
            continue
        try:
            samples = collect_samples(conn, feed, cfg.window_seconds())
        except Exception as exc:  # a broken feed is a finding, not a crash
            results.append(
                {
                    "slo": name,
                    "status": "FEED_ERROR",
                    "why": f"{type(exc).__name__}: {exc}",
                    "feed": {k: feed.get(k) for k in ("kind", "table", "timestamp_column")},
                }
            )
            continue
        verdict = evaluate(cfg, samples)
        verdict["feed"] = {k: feed.get(k) for k in ("kind", "table", "timestamp_column", "good_predicate")}
        verdict["feed"] = {k: v for k, v in verdict["feed"].items() if v is not None}
        results.append(verdict)

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "scheduled_entrypoint": SCHEDULED_ENTRYPOINT,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "config": CONFIG_REL,
        "config_as_of": document.get("as_of"),
        "database": "connected" if conn is not None else "unreachable",
        "slos": results,
        "note": "Report only. No alert was sent and no schedule was installed.",
    }


#: Stable-named mirror of the newest receipt. config/lane_registry.json declares
#: this lane's output_signal as file_mtime on THIS path, and file_mtime resolves
#: one fixed path -- it supports no glob. The timestamped receipts below live in
#: artifacts/, which is gitignored (.gitignore:185), so they cannot serve as the
#: durable signal a lane row must name. Declaring output_signal "none" would have
#: been the shortcut; the registry rejects that reasoning in its own words --
#: "code 0 has been wrong about this system three times."
LATEST_RECEIPT_REL = Path("data") / "runtime" / "slo_burn_rate_last.json"


def write_receipt(report: dict[str, Any], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["generated_at"].replace(":", "").replace("-", "")
    path = out_dir / f"slo_burn_rate_{stamp}.json"
    body = json.dumps(report, indent=2, sort_keys=True) + "\n"
    path.write_text(body, encoding="utf-8")
    # Mirror to the fixed path the lane registry observes. Best-effort: a failure
    # here must not lose the timestamped receipt that was already written.
    try:
        latest = PROJECT_ROOT / LATEST_RECEIPT_REL
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(body, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"  latest-receipt mirror failed: {exc}", file=sys.stderr)
    return path


def render(report: dict[str, Any]) -> str:
    lines = [
        f"SLO burn rate — {report['generated_at']} (database: {report['database']})",
        f"  config: {report['config']} (as_of {report['config_as_of']})",
        f"  schedule: {report['scheduled_entrypoint']}",
        "",
    ]
    for slo in report["slos"]:
        lines.append(f"[{slo['status']}] {slo['slo']}")
        if "tiers" not in slo:
            lines.append(f"    {slo.get('why', '')}")
            lines.append("")
            continue
        lines.append(
            f"    target {slo['slo_target']:.4g} over {slo['period_days']}d "
            f"(error budget {slo['error_budget_ratio'] * 100:.2f}% of events)"
        )
        for tier in slo["tiers"]:
            head = f"    {tier['label']:<12} {tier['severity']:<6} thr={tier['threshold']:<5g} {tier['status']}"
            if "burn_rate" in (tier.get("long") or {}):
                lg, sh = tier["long"], tier["short"]
                head += (
                    f"  long={lg['burn_rate']:.2f}x ({lg['good']}/{lg['total']}, "
                    f"{lg['consumed_budget_pct']:.3f}% budget)  short={sh['burn_rate']:.2f}x"
                )
            elif tier.get("why"):
                head += f"  — {tier['why']}"
            lines.append(head)
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Error-budget burn rate for the configured SLOs (read-only)")
    ap.add_argument("--json", action="store_true", help="emit the receipt to stdout instead of the text render")
    ap.add_argument("--slo", help="evaluate only this SLO by name")
    ap.add_argument("--receipt-dir", default=str(PROJECT_ROOT / "artifacts" / "slo"))
    ap.add_argument("--no-receipt", action="store_true", help="do not write the receipt file")
    args = ap.parse_args(argv)

    document = load_document()
    conn = connect()
    try:
        report = run(document, conn, only=args.slo)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if not args.no_receipt:
        try:
            report["receipt"] = str(write_receipt(report, Path(args.receipt_dir)))
        except OSError as exc:
            print(f"  receipt: could not write ({exc})", file=sys.stderr)

    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render(report))
    # Always 0: this is a report. A non-zero exit would invite someone to wire
    # it to a cron as an alarm, which is precisely the operator decision this
    # script does not get to make.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
