#!/usr/bin/env python3
"""Dry report: which few subjects the daily research budget picks, and why.

    python3 scripts/cio_research_budget_report.py --root CURRENT [--json]
    python3 scripts/cio_research_budget_report.py --root CURRENT --apply

Reads the InstrumentRecord store and the plan projection, collapses plans onto
subjects, and prints the at-most-5 subjects that get a decision today. It calls
no model, contacts no vendor, touches no database and — unless `--apply` is
passed — writes nothing. `--apply` appends to the budget ledger ONLY; it never
runs the research it selected.

REFUSES an empty or absent record store rather than printing a tidy zero. A
tool that reports success against a store it never found is how four separate
"0 items" bugs got believed in one day; several CIO stores resolve relative to
the CWD, so `--root` is explicit here and defaults to $TRADEAI_ROOT.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.lib.cio_instrument_record import InstrumentRecordStore  # noqa: E402
from scripts.lib.cio_research_budget import (  # noqa: E402
    BudgetLedger, DAILY_CAP, HELD_SLOTS, collapse_plans_to_subjects, day_of,
    ledger_path, select,
)

NO_CONSUMER_REASON = (
    "operator-run CLI entry point: this script's consumer is a person at a "
    "terminal. The schema it exercises, ResearchBudget@v1, is defined and "
    "consumed in scripts/lib/cio_research_budget.py, which this imports."
)

# `data/cio/reentry_payload_last.json` is the notification DEDUP CACHE written
# by agent_decision_payload, not the adjudicated Surface A re-entry book
# (cio_investment_product.build_reentry_book, which is Postgres-backed and
# therefore not reachable from a dry report). Its vocabulary is NEAR/READY, so
# it is translated into the Surface A vocabulary rather than blended with it:
# READY here means "at the trigger", which is Surface A's REENTER.
REENTRY_PAYLOAD_RELPATH = ("data", "cio", "reentry_payload_last.json")
REENTRY_ACTION_TO_SURFACE_A = {"READY": "REENTER", "NEAR": "NEAR"}


def load_plans(root: Path) -> list[dict]:
    path = root / "data" / "cio" / "cio_plans_projection.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return []
    plans = [p for p in (doc.get("plans") or {}).values() if isinstance(p, dict)]
    return [p for p in plans if str(p.get("status")) in {"draft", "proposed"}]


def load_statuses(root: Path, source: str, path: str | None) -> tuple[dict, str]:
    """subject_key -> surface label. Returns (statuses, provenance)."""
    if source == "none":
        return {}, "none (fifth slot cannot be filled)"
    if source == "file":
        if not path:
            return {}, "file (no --statuses-file given)"
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:                                 # noqa: BLE001
            return {}, f"file (unreadable: {exc})"
        return {str(k): str(v) for k, v in raw.items()}, f"file:{path}"

    p = root.joinpath(*REENTRY_PAYLOAD_RELPATH)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {}, f"reentry-payload (absent at {p})"
    out: dict[str, str] = {}
    for sym, row in (raw or {}).items():
        if not isinstance(row, dict):
            continue
        mapped = REENTRY_ACTION_TO_SURFACE_A.get(
            str(row.get("action") or "").strip().upper())
        if mapped:
            out[f"EXIT:{str(sym).strip().upper()}"] = mapped
    return out, (f"reentry-payload:{p.name} (dedup cache, NOT the adjudicated "
                 f"Surface A book; {len(out)} labels)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=os.environ.get("TRADEAI_ROOT") or ".")
    ap.add_argument("--cap", type=int, default=DAILY_CAP)
    ap.add_argument("--held-slots", type=int, default=HELD_SLOTS)
    ap.add_argument("--status-source", default="reentry-payload",
                    choices=("reentry-payload", "file", "none"))
    ap.add_argument("--statuses-file", default=None)
    ap.add_argument("--apply", action="store_true",
                    help="append the selection to the budget ledger (no research runs)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    now = datetime.now(timezone.utc)

    store = InstrumentRecordStore(root / "data" / "cio" / "cio_instrument_records.jsonl")
    records = store.all()
    if not records:
        print(f"REFUSED: no InstrumentRecord@v1 rows under {root}\n"
              f"  expected: {store.path}\n"
              f"  An empty store is not an empty book — it is usually the "
              f"wrong --root. Pass the release that holds the live data.",
              file=sys.stderr)
        return 2

    plans = load_plans(root)
    plan_subjects = collapse_plans_to_subjects(plans)
    statuses, provenance = load_statuses(root, args.status_source,
                                         args.statuses_file)

    ledger = BudgetLedger(ledger_path(root))
    day = day_of(now)
    already = ledger.decided_on(day)

    selection = select(
        records,
        now=now,
        statuses=statuses,
        plan_subjects=plan_subjects,
        already_decided=already,
        cap=args.cap,
        held_slots=args.held_slots,
        run_id=f"budget_{uuid.uuid4().hex[:12]}",
    )
    selection["root"] = str(root)
    selection["status_source"] = provenance
    selection["records_loaded"] = len(records)
    selection["open_plans"] = len(plans)
    selection["plan_subjects"] = len(plan_subjects)
    selection["already_decided_today"] = len(already)

    appended = 0
    if args.apply:
        appended = ledger.record(selection)
    selection["ledger_rows_appended"] = appended
    selection["applied"] = bool(args.apply)

    if args.json:
        print(json.dumps(selection, indent=2, default=str))
        return 0

    print(f"ResearchBudget@v1 dry report — root={root}")
    print(f"  records loaded            : {len(records)}")
    print(f"  open plans                : {len(plans)} -> {len(plan_subjects)} subjects")
    print(f"  status source             : {provenance}")
    print(f"  already decided today     : {len(already)}")
    print(f"  cap                       : {selection['cap']}  slots={selection['slots']}")
    print()
    print(f"  SELECTED ({selection['selected_count']}):")
    for row in selection["selected"]:
        plans_note = (f"  [{len(row['plan_ids'])} plans]" if row["plan_ids"] else "")
        status = f" status={row['status']}" if row.get("status") else ""
        print(f"    {row['slot']:<18} {row['subject_key']:<16} "
              f"rank={row['rank']} {row['reason']}{status}{plans_note}")
    if not selection["selected"]:
        print("    (none — every subject is deferred, refused, or already decided)")
    print()
    print(f"  eligible but unpicked     : {len(selection['not_selected_sample'])}"
          f" (sample capped at 20)")
    print(f"  deferred                  : {selection['deferred_count']} "
          f"{selection['deferred_by_reason']}")
    print(f"  refused (dust/TEST/cash)  : {selection['refused_count']} "
          f"{selection['refused_by_reason']}")
    if args.apply:
        print(f"\n  ledger rows appended      : {appended} -> {ledger.path}")
    else:
        print("\n  dry run — nothing written. --apply records the day's choice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
