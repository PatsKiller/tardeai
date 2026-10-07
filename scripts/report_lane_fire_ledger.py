#!/usr/bin/env python3
"""Expected / fired / artifact / consumed per lane over a bounded lookback (2026-10-07).

Fills the n8n packet's open Phase 0 gate ("missed-fire rate and fired/accepted/consumed for every
lane", 00-baseline.md) without a new store:

  expected  = floor(window_hours / expected_cadence_hours) from the registry row (no croniter on
              this host; calendar-exact counts are NOT_MEASURED and labelled so)
  fired     = cron CMD lines in the journal whose command carries the lane's `match`
  artifact  = the lane's output_signal last_output_at inside the window (lane_registry.observe_signal)
  consumed  = a consumer receipt where one exists (today: the approval reminder's reconcile receipt);
              everything else NOT_MEASURED

Read-only. Dry run prints; --write writes LaneFireLedger@v1 beside the packet's other ledgers.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(PROJ / "scripts"))

SCHEMA = "LaneFireLedger@v1"
NO_CONSUMER_REASON = "read-only report run by hand or from the n8n packet closeout; writes one ledger file under docs/"
PILOT_LANES = ("morning-brief-0730", "research-scheduler-holdings", "material-change-digest",
               "llm-spend-report-daily", "approval-package-reminder")
DEFAULT_JOURNAL = "/var/log/syslog"
_CMD_RE = re.compile(r"^(?P<ts>\S+)\s+\S+\s+CRON\[\d+\]:\s+\(\S+\)\s+CMD\s+\((?P<cmd>.*)\)\s*$")


def _parse_ts(raw: str) -> Optional[_dt.datetime]:
    try:
        ts = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)


def journal_fires(text: str, *, since: _dt.datetime) -> tuple[list[tuple[_dt.datetime, str]], Optional[_dt.datetime]]:
    """(fires at or after ``since``, earliest CMD timestamp in the whole journal).

    The earliest timestamp bounds the window: a rotated syslog that starts 3 days ago cannot
    testify about day 7, so counting 7 days of "expected" against it invents missed fires."""
    out = []
    earliest: Optional[_dt.datetime] = None
    for line in text.splitlines():
        m = _CMD_RE.match(line)
        if not m:
            continue
        ts = _parse_ts(m.group("ts"))
        if not ts:
            continue
        if earliest is None or ts < earliest:
            earliest = ts
        if ts >= since:
            out.append((ts, m.group("cmd")))
    return out, earliest


def lane_marker(lane: dict[str, Any]) -> str:
    sched = lane.get("scheduler") or {}
    return str(sched.get("match") or "").strip()


def consumer_receipt_for(lane_id: str, *, root: Path) -> dict[str, Any]:
    """The only consumer receipt that exists today is the approval reminder's reconcile receipt."""
    if lane_id == "approval-package-reminder":
        p = root / "data" / "runtime" / "approval_reminder_reconcile_last.json"
        if p.is_file():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                return {"status": "MEASURED", "source": str(p), "delivery_status": d.get("delivery_status"),
                        "delivery_receipt_count": d.get("delivery_receipt_count"), "as_of": d.get("as_of")}
            except ValueError:
                return {"status": "UNREADABLE", "source": str(p)}
        return {"status": "NOT_MEASURED", "reason": "no reconcile receipt yet", "source": str(p)}
    return {"status": "NOT_MEASURED", "reason": "no consumer receipt store for this lane"}


def build(lanes: list[dict[str, Any]], *, journal_text: Optional[str], now: _dt.datetime, days: int,
          observe, root: Path, served_sha: Optional[str], source_sha: Optional[str]) -> dict[str, Any]:
    since = now - _dt.timedelta(days=days)
    fires, earliest = journal_fires(journal_text, since=since) if journal_text is not None else (None, None)
    journal_covers_from = None
    if earliest is not None and earliest > since:
        journal_covers_from = earliest          # the journal does not reach back to `since`
        since = earliest
    hours = (now - since).total_seconds() / 3600.0
    rows = []
    for lane in lanes:
        lid = str(lane.get("lane_id"))
        cad = float(lane.get("expected_cadence_hours") or 0) or None
        marker = lane_marker(lane)
        expected = int(hours // cad) if cad else None
        if fires is None:
            fired: Any = "NOT_MEASURED"
            fire_times: list[str] = []
        elif not marker:
            fired, fire_times = "NOT_MEASURED", []
        else:
            hits = [ts for ts, cmd in fires if marker in cmd]
            fired, fire_times = len(hits), [t.isoformat() for t in hits[-5:]]
        sig = lane.get("output_signal") or {}
        obs = observe(sig, root=root) if sig else {"last_output_at": None, "readable": False, "detail": "no output_signal"}
        last = obs.get("last_output_at")
        if isinstance(last, str):
            last = _parse_ts(last)
        artifact = ("NOT_MEASURED" if not obs.get("readable") else
                    ("IN_WINDOW" if last and last >= since else ("STALE" if last else "ABSENT")))
        rows.append({
            "lane_id": lid, "declared_state": lane.get("state"), "scheduler": (lane.get("scheduler") or {}).get("kind"),
            "match": marker or None, "expected_cadence_hours": cad,
            "expected": expected, "expected_basis": "window_hours // cadence_hours (calendar-exact NOT_MEASURED: no croniter)",
            "fired": fired, "fired_basis": "journal CRON CMD lines carrying the lane's match", "last_fires": fire_times,
            "artifact": artifact, "artifact_last_output_at": last.isoformat() if last else None, "artifact_detail": obs.get("detail"),
            "consumed": consumer_receipt_for(lid, root=root),
            "missed_fire_rate": (round(1 - min(fired, expected) / expected, 3) if isinstance(fired, int) and expected else "NOT_MEASURED"),
        })
    return {"schema": SCHEMA, "authority": "READ_ONLY_ADVISORY", "as_of": now.isoformat(), "window_days": days,
            "since": since.isoformat(), "window_hours": round(hours, 1),
            "journal_covers_from": journal_covers_from.isoformat() if journal_covers_from else None,
            "journal_lines": (len(fires) if fires is not None else "NOT_MEASURED"),
            "served_sha": served_sha, "source_sha": source_sha, "lanes": rows}


def main(argv: Optional[list[str]] = None) -> int:
    from scripts.lib.lane_registry import load_registry, observe_signal, state_root

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--lane", action="append", help="lane_id (repeatable); default: the five n8n pilot lanes")
    ap.add_argument("--journal", default=os.environ.get("TRADEAI_CRON_JOURNAL", DEFAULT_JOURNAL))
    ap.add_argument("--registry", default=None)
    ap.add_argument("--out", default=str(PROJ / "docs" / "implementation" / "n8n-parallel" / "ledgers" / "fire-ledger.json"))
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    reg = load_registry(Path(a.registry) if a.registry else None)
    wanted = set(a.lane or PILOT_LANES)
    lanes = [l for l in reg.get("lanes") or [] if l.get("lane_id") in wanted]
    try:
        journal_text: Optional[str] = Path(a.journal).read_text(encoding="utf-8", errors="replace")
    except OSError:
        journal_text = None
    served = None
    try:
        served = (Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT" / "GIT_SHA").read_text().strip()
    except OSError:
        pass
    source = os.environ.get("TRADEAI_SOURCE_SHA")
    rep = build(lanes, journal_text=journal_text, now=_dt.datetime.now(_dt.timezone.utc), days=a.days,
                observe=observe_signal, root=state_root(), served_sha=served, source_sha=source)
    if rep.get("journal_covers_from"):
        print(f"journal covers from {rep['journal_covers_from']} only: window shortened to {rep['window_hours']} h")
    for r in rep["lanes"]:
        print(f"{r['lane_id']:<30} expected={r['expected']!s:<5} fired={r['fired']!s:<6} artifact={r['artifact']:<12} "
              f"consumed={r['consumed'].get('status')} missed={r['missed_fire_rate']}")
    if a.write:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(rep, indent=1, default=str) + "\n", encoding="utf-8")
        tmp.replace(out)
        print(f"wrote {out}")
    else:
        print("dry run: nothing written (add --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
