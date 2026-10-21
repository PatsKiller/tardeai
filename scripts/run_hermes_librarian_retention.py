#!/usr/bin/env python3
"""Run Hermes librarian retention enforcement (archive → purge ladder).

The daily backlog timer only stages research. This entrypoint applies
``scripts/lib/hermes_librarian/retention.py`` so orphan embeddings and
archived research are actually purged per ``config/hermes_librarian_policy.yaml``.

Usage:
  python scripts/run_hermes_librarian_retention.py --dry-run
  python scripts/run_hermes_librarian_retention.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

NO_CONSUMER_REASON = (
    "HermesLibrarianRetentionReceipt@v1 is an audit receipt (data/runtime/hermes_librarian_retention_last.json) for the "
    "05:10 hermes-librarian-retention.timer run. Its only reader was the Sun 06:30 weekly disk cleanup, which no longer "
    "runs librarian retention (operator ruling D6, 2026-10-21); operators and the retention runbook read it directly."
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Count only (default unless --apply)")
    ap.add_argument("--apply", action="store_true", help="Mutate DB per retention policy")
    args = ap.parse_args()
    dry = True if not args.apply else False
    if args.dry_run:
        dry = True

    from db_adapter import _get_conn
    from lib.hermes_librarian.retention import apply_retention

    conn = _get_conn()
    try:
        result = apply_retention(conn, dry_run=dry)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    out = {
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry,
        **result,
    }
    print(json.dumps(out, indent=2, default=str))
    if not dry:
        # 2026-10-11 (retention-all-managed): a receipt per applied run (the study found this deleter
        # unreceipted; lane output_signal was `none`). Read by docs/runbooks/DB_RETENTION.md checks.
        write_receipt(out)
    return 0


def receipt_path() -> Path:
    import os
    base = os.getenv("TRADEAI_STATE_ROOT")
    root = Path(base) if base else Path.home() / "trade-ai-releases" / "persistent-state"
    return root / "data" / "runtime" / "hermes_librarian_retention_last.json"


def write_receipt(out: dict) -> Path:
    import os
    p = receipt_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "HermesLibrarianRetentionReceipt@v1", **out}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    return p


if __name__ == "__main__":
    raise SystemExit(main())
