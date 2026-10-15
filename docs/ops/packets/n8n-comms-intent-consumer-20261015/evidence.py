#!/usr/bin/env python3
"""Read-only evidence for the comms-intent consumer packet. Opens the ledger with sqlite mode=ro; writes nothing.

    python3 docs/ops/packets/n8n-comms-intent-consumer-20261015/evidence.py [--ledger PATH] [--state-root PATH]

Prints: the ledger's consumer tables (present or absent), every comms_intents row, every consumption row, every
comms-intent incident, and the lane receipt (or its absence).
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--state-root",
        default=os.environ.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state"),
    )
    ap.add_argument("--ledger", default=None)
    a = ap.parse_args()
    sr = Path(a.state_root)
    ledger = Path(a.ledger) if a.ledger else sr / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    conn = sqlite3.connect(f"{ledger.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    print("ledger:", ledger)
    for t in ("comms_intents", "comms_intent_consumption", "comms_intent_incidents"):
        print(f"table {t}:", "present" if t in tables else "absent")
        if t in tables:
            for r in conn.execute(f"SELECT * FROM {t} ORDER BY 1"):  # noqa: S608 — fixed table names
                print("  ", json.dumps(dict(r), sort_keys=True))
    conn.close()
    rc = sr / "data" / "runtime" / "n8n-comms-intent-consumer_last.json"
    print("receipt:", rc, "present" if rc.exists() else "absent")
    if rc.exists():
        print("  ", rc.read_text(encoding="utf-8").strip().replace("\n", "\n   "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
