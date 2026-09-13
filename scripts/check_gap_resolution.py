#!/usr/bin/env python3
"""Report gaps nobody is trying to close, vectors that keep failing, and any
vector that ran a retired provider. Read-only.

WHY
---
Phase 7 of One Source of Truth turned "stale or missing" into a declared,
budgeted, receipted sequence of attempts (scripts/lib/gap_resolver.py). A
sequence that is declared and never run is the same as no sequence -- that is
the recurring defect in this repository (check_dark_contracts.py exists because
of it). So this measures the receipts against the gaps:

    OPEN_NO_ATTEMPT   a gap queued or registered more than 2h ago with no receipt
    VECTOR_FAILING    a vector whose receipts show >= 3 errors today
    RETIRED_RAN       a receipt whose provider is retired and whose outcome is
                      not retired_skipped -- the registry said never, and it ran

RETIRED_RAN must always be 0. It is a [DATA_INTEGRITY] finding because the
catalyst chain fell through four dead slots for seven weeks and nothing said so.

The receipt data/runtime/gap_resolution_last_run.json is written every run,
findings or not, so a stopped timer does not look like a clean result. The
alert state under ~/.local/state/tradeai/ makes the Telegram fire on CHANGE only.

USAGE
-----
    python scripts/check_gap_resolution.py            # human-readable
    python scripts/check_gap_resolution.py --json
    python scripts/check_gap_resolution.py --alert    # notify on change

EXIT CODES
----------
    0  nothing to report
    1  at least one finding
    2  could not run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SCHEMA = "GapResolutionReport@v1"
RECEIPT_NAME = "gap_resolution_last_run.json"
STATE_PATH = Path.home() / ".local/state/tradeai/gap_resolution_last_alert.json"
SENTINEL = "[DATA_INTEGRITY]"

OPEN_HOURS = 2.0
FAIL_THRESHOLD = 3

SCHEDULED_ENTRYPOINT = "systemd: tradeai-gap-resolution.timer -- every 30 min at :07/:37 (proposed, not installed)"


def _parse_ts(v) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return out


def open_gaps(queue_rows: list[dict], research_rows: list[dict], receipts: list[dict], *,
              now: datetime, open_hours: float = OPEN_HOURS) -> list[dict]:
    """Gaps older than `open_hours` with no receipt against their gap_id. Pure."""
    attempted = {str(r.get("gap_id")) for r in receipts if r.get("gap_id")}
    cutoff = now - timedelta(hours=open_hours)
    out: list[dict] = []
    seen: set[str] = set()
    for r in queue_rows:
        gid = str(r.get("gap_id") or "")
        ts = _parse_ts(r.get("ts"))
        if not gid or gid in seen or r.get("status") not in (None, "open") or ts is None or ts > cutoff:
            continue
        seen.add(gid)
        if gid not in attempted:
            out.append({"gap_id": gid, "domain": r.get("domain"), "subject": r.get("subject"),
                        "age_hours": round((now - ts).total_seconds() / 3600, 1), "origin": "gap_queue"})
    for r in research_rows:
        gid = str(r.get("gap_id") or "")
        ts = _parse_ts(r.get("created_at"))
        if not gid or gid in seen or str(r.get("status")) != "OPEN" or ts is None or ts > cutoff:
            continue
        seen.add(gid)
        if gid not in attempted:
            out.append({"gap_id": gid, "domain": "research_thesis", "subject": r.get("symbol"),
                        "age_hours": round((now - ts).total_seconds() / 3600, 1), "origin": "research_gaps"})
    return out


def failing_vectors(receipts: list[dict], *, now: datetime, threshold: int = FAIL_THRESHOLD) -> list[dict]:
    """Vectors with >= threshold `error` receipts today (UTC). Pure."""
    day = now.date().isoformat()
    counts: dict[str, int] = {}
    for r in receipts:
        if r.get("outcome") != "error" or str(r.get("started") or "")[:10] != day:
            continue
        v = str(r.get("vector") or "?")
        counts[v] = counts.get(v, 0) + 1
    return [{"vector": v, "errors_today": n} for v, n in sorted(counts.items()) if n >= threshold]


def retired_ran(receipts: list[dict], retired: frozenset[str]) -> list[dict]:
    """Receipts that RAN a retired provider. Refusals (retired_skipped) are correct. Pure."""
    out: list[dict] = []
    for r in receipts:
        p = str(r.get("provider") or "").strip().lower()
        if p and p in retired and r.get("outcome") != "retired_skipped":
            out.append({"gap_id": r.get("gap_id"), "vector": r.get("vector"), "provider": p,
                        "outcome": r.get("outcome"), "started": r.get("started")})
    return out


def collect(*, now: datetime | None = None, receipts_path: Path | None = None,
            queue_path: Path | None = None, research_path: Path | None = None,
            retired: frozenset[str] | None = None) -> dict:
    from scripts.lib.gap_resolver import RECEIPTS_PATH
    # data_broker is spelled `lib.data_broker` by its own __init__; importing it
    # as scripts.lib.data_broker loads the package twice (dual-import guard).
    from lib.data_broker.gap_hook import QUEUE_PATH
    from scripts.lib.research_gap import PATH as RESEARCH_REL

    now = now or datetime.now(timezone.utc)
    receipts = _jsonl(receipts_path or RECEIPTS_PATH)
    queue = _jsonl(queue_path or QUEUE_PATH)
    research = _jsonl(research_path or (PROJECT_ROOT / RESEARCH_REL))
    if retired is None:
        from scripts.lib.retired_providers import retired_providers
        retired = retired_providers()
    findings = {
        "OPEN_NO_ATTEMPT": open_gaps(queue, research, receipts, now=now),
        "VECTOR_FAILING": failing_vectors(receipts, now=now),
        "RETIRED_RAN": retired_ran(receipts, retired),
    }
    return {
        "schema": SCHEMA,
        "ran_at": now.isoformat(),
        "receipts": len(receipts),
        "queued_gaps": len(queue),
        "research_gaps": len(research),
        "findings": findings,
        "finding_count": sum(len(v) for v in findings.values()),
    }


def _write_run_receipt(report: dict) -> None:
    """Prove this ran, every run. The alert state only changes on change."""
    path = PROJECT_ROOT / "data" / "runtime" / RECEIPT_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    except OSError as exc:
        print(f"  receipt: could not write {path} ({exc})", file=sys.stderr)


def fingerprint(report: dict) -> dict[str, str]:
    fp: dict[str, str] = {}
    f = report["findings"]
    for g in f["OPEN_NO_ATTEMPT"]:
        fp[f"open:{g['gap_id']}"] = "OPEN_NO_ATTEMPT"
    for v in f["VECTOR_FAILING"]:
        fp[f"vector:{v['vector']}"] = "VECTOR_FAILING"
    for r in f["RETIRED_RAN"]:
        fp[f"retired:{r['vector']}:{r['provider']}"] = "RETIRED_RAN"
    return fp


def _alert(report: dict) -> None:
    """Notify only when the finding-set changes. Never raises."""
    fp = fingerprint(report)
    previous: dict = {}
    try:
        previous = json.loads(STATE_PATH.read_text()).get("fingerprint", {})
    except (OSError, ValueError):
        pass
    if fp == previous:
        print("\n  alert: suppressed — unchanged since the last run.")
        return

    f = report["findings"]
    if not fp:
        body = f"{SENTINEL} ✅ Gap resolution: every gap has an attempt, no vector failing, no retired provider ran."
    else:
        # The sentinel is what operator_alert_policy_v2 routes on. Without it
        # this would wait in the digest, and a retired provider running is not
        # a digest item.
        head = f"{SENTINEL} 🚨 Gap resolution: "
        head += "a RETIRED provider RAN" if f["RETIRED_RAN"] else "gaps unattended or vectors failing"
        lines = [head, ""]
        for r in f["RETIRED_RAN"]:
            lines.append(f"• [RETIRED_RAN] {r['vector']} ran {r['provider']} → {r['outcome']} ({r['started']})")
        for v in f["VECTOR_FAILING"]:
            lines.append(f"• [VECTOR_FAILING] {v['vector']}: {v['errors_today']} errors today")
        for g in f["OPEN_NO_ATTEMPT"][:12]:
            lines.append(f"• [OPEN_NO_ATTEMPT] {g['domain']}:{g['subject']} open {g['age_hours']}h, no attempt ({g['origin']})")
        if len(f["OPEN_NO_ATTEMPT"]) > 12:
            lines.append(f"  … and {len(f['OPEN_NO_ATTEMPT']) - 12} more")
        newly = [k for k in fp if k not in previous]
        if newly:
            lines += ["", f"NEW since the last run: {len(newly)}"]
        recovered = [k for k in previous if k not in fp]
        if recovered:
            lines += ["", f"Cleared: {len(recovered)}"]
        lines += ["", "Receipts: data/cio/gap_resolution_receipts.jsonl · docs/GAP_RESOLUTION.md"]
        body = "\n".join(lines)

    try:
        from telegram_alert import send_telegram

        ok = send_telegram(body, message_class="operator_alert")
        print(f"\n  alert: {'accepted' if ok else 'NOT accepted'} by the platform")
    except Exception as exc:
        print(f"\n  alert: FAILED to send ({exc}). The findings above still stand.", file=sys.stderr)
        return

    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"fingerprint": fp}, indent=2))
    except OSError as exc:
        print(f"  alert: could not record state ({exc}).", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alert", action="store_true", help="notify the operator when the finding-set changes")
    args = ap.parse_args()

    try:
        report = collect()
    except Exception as exc:  # noqa: BLE001 -- cannot-run is exit 2, never a green 0
        print(f"ERROR: could not collect: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        f = report["findings"]
        print("Gap resolution — is anything trying to close the gaps?")
        print("=" * 74)
        print(f"  receipts={report['receipts']}  queued_gaps={report['queued_gaps']}  research_gaps={report['research_gaps']}")
        for r in f["RETIRED_RAN"]:
            print(f"  [RETIRED_RAN     ] {r['vector']} ran {r['provider']} → {r['outcome']}")
        for v in f["VECTOR_FAILING"]:
            print(f"  [VECTOR_FAILING  ] {v['vector']}: {v['errors_today']} errors today")
        for g in f["OPEN_NO_ATTEMPT"]:
            print(f"  [OPEN_NO_ATTEMPT ] {g['domain']}:{g['subject']} open {g['age_hours']}h ({g['origin']})")
        if not report["finding_count"]:
            print("  nothing to report.")
        print("-" * 74)
        print(f"  findings={report['finding_count']}")

    _write_run_receipt(report)
    if args.alert:
        _alert(report)
    return 1 if report["finding_count"] else 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
