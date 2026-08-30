#!/usr/bin/env python3
"""P3 InstrumentRecord@v1 persistence drill — tmp dry by default.

No LLM. READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
Does not touch the live overlay unless --live-ro is passed (read-only census).

  python3 scripts/cio_instrument_record_drill.py --tmp
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _run_tmp_drills() -> dict[str, Any]:
    from scripts.lib.cio_instrument_record import (
        BEHAVIOR_FIELDS,
        BehaviorWriteRefused,
        InstrumentRecordStore,
        apply_cognition,
        cc_narrative,
        new_record,
        thesis_summary,
    )

    out: dict[str, Any] = {"mode": "tmp", "checks": {}}
    with tempfile.TemporaryDirectory(prefix="cio_ir_p3_") as td:
        path = Path(td) / "cio_instrument_records.jsonl"
        store = InstrumentRecordStore(path)

        rec = new_record("HELD", "SCHD", symbols=["SCHD"], thesis_ref="desk@v5")
        rec, _ = apply_cognition(
            rec,
            next_research_question="Has the defer condition changed?",
            notify_priority="cc",
            narrative=cc_narrative(
                what="Operator deferred: wait for price buffer.",
                thesis_fit="CONSTRAINT: defer",
            ),
        )
        store.upsert(rec)

        tip = dict(store.load("HELD:SCHD") or {})
        tip["thesis_ref"] = "desk@v6"
        tip, _ = apply_cognition(
            tip,
            next_research_question="Is the buffer durable?",
            notify_priority="digest",
            narrative=cc_narrative(
                what="Updated thesis: buffer met; re-evaluate.",
                thesis_fit="ACTIVE: re-eval",
            ),
        )
        store.upsert(tip)

        cold = InstrumentRecordStore(path).load("HELD:SCHD")
        out["checks"]["cold_start_reload"] = bool(
            cold and cold.get("thesis_ref") == "desk@v6"
        )

        hist = store.history("HELD:SCHD")
        out["checks"]["append_version"] = len(hist) == 2
        prior = thesis_summary(hist[0])
        out["checks"]["prior_thesis_recoverable"] = (
            prior.get("thesis_ref") == "desk@v5"
            and "defer" in str(prior.get("what") or "").lower()
        )

        rolled = store.rollback("HELD:SCHD", to_index=0)
        out["checks"]["rollback_reappend"] = rolled.get("thesis_ref") == "desk@v5"

        with open(path, "a", encoding="utf-8") as fh:
            fh.write('{"subject_key":"HELD:SCHD","thesis_ref":"CORRUPT_PARTIAL"')
        after = InstrumentRecordStore(path).load("HELD:SCHD")
        out["checks"]["partial_write_recovery"] = bool(
            after and after.get("thesis_ref") == "desk@v5"
        )

        refused = 0
        for bf in BEHAVIOR_FIELDS:
            try:
                apply_cognition(new_record("HELD", "X"), next_research_question="q", **{bf: 1})
            except BehaviorWriteRefused:
                refused += 1
        out["checks"]["mbi_behavior_refused"] = refused == len(BEHAVIOR_FIELDS)
        out["tmp_path"] = str(path)
        out["history_len_after_rollback"] = len(InstrumentRecordStore(path).history("HELD:SCHD"))
        out["ok"] = all(out["checks"].values())
    return out


def _live_ro_census(path: Path) -> dict[str, Any]:
    from collections import Counter

    if not path.is_file():
        return {"ok": False, "reason": f"missing:{path}"}
    rows = 0
    by_key: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    mbi = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:                                        # noqa: BLE001
            continue
        rows += 1
        key = str(row.get("subject_key") or "")
        if key:
            by_key[key] += 1
        kinds[str(row.get("kind") or "?")] += 1
        mbi.add(row.get("memory_behavior_influence"))
    multi = sum(1 for n in by_key.values() if n > 1)
    return {
        "ok": True,
        "path": str(path),
        "rows": rows,
        "subjects": len(by_key),
        "multi_version_subjects": multi,
        "kinds": dict(kinds),
        "mbi_values": sorted(mbi, key=lambda x: (x is None, x)),
        "note": "read-only census; no mutation",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tmp", action="store_true", default=True,
                    help="run tmp_path drills (default)")
    ap.add_argument("--no-tmp", action="store_true",
                    help="skip tmp drills")
    ap.add_argument("--live-ro", action="store_true",
                    help="read-only census of overlay JSONL (no write)")
    ap.add_argument(
        "--live-path",
        default="/home/johnclaw/trade-ai-releases/persistent-state/data/cio/cio_instrument_records.jsonl",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    report: dict[str, Any] = {
        "schema": "InstrumentRecordPersistenceDrill@v1",
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
    }
    if not args.no_tmp:
        report["tmp"] = _run_tmp_drills()
    if args.live_ro:
        report["live_ro"] = _live_ro_census(Path(args.live_path))

    ok = True
    if "tmp" in report:
        ok = ok and bool(report["tmp"].get("ok"))
    if "live_ro" in report:
        ok = ok and bool(report["live_ro"].get("ok"))
    report["ok"] = ok

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
