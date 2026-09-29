#!/usr/bin/env python3
"""Bounded stamp: last N Hermes COMPLETED results missing subject_guid.

Only stamps rows whose symbol resolves in the identity registry. Writes a
``.bak`` of the results JSONL, then rewrites the file with GUIDs filled on
matching last-N rows. Does not touch the full request corpus.

Usage:
  python3 scripts/ops/stamp_hermes_results_last_n.py --dry-run --n 200
  python3 scripts/ops/stamp_hermes_results_last_n.py --apply --n 200
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    apply = bool(args.apply)
    from scripts.lib.identity_carriage import is_forbidden_guid, is_registry_guid, resolve_security_identity

    path = args.root / "data" / "cio" / "hermes_research_results.jsonl"
    if not path.exists():
        print(json.dumps({"ok": False, "error": "missing_results"}))
        return 2

    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    rows: list[dict | None] = []
    completed_idx: list[int] = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            rows.append(None)
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            rows.append(None)
            continue
        rows.append(row if isinstance(row, dict) else None)
        if isinstance(row, dict) and row.get("event") == "HERMES_RESEARCH_COMPLETED":
            completed_idx.append(i)

    target = completed_idx[-max(1, args.n) :]
    report = {
        "as_of": _now(),
        "n_window": len(target),
        "apply": apply,
        "stamped": 0,
        "already": 0,
        "unresolved": 0,
        "forbidden_cleared": 0,
        "skipped_no_symbol": 0,
        "samples": [],
    }

    for i in target:
        row = rows[i]
        if not isinstance(row, dict):
            continue
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym:
            report["skipped_no_symbol"] += 1
            continue
        sg = row.get("subject_guid")
        if is_forbidden_guid(sg, symbol=sym):
            sg = None
            report["forbidden_cleared"] += 1
        if is_registry_guid(sg):
            report["already"] += 1
            continue
        env = resolve_security_identity(sym, root=args.root)
        if not is_registry_guid(env.get("subject_guid")):
            report["unresolved"] += 1
            continue
        report["stamped"] += 1
        if len(report["samples"]) < 15:
            report["samples"].append({
                "symbol": sym,
                "result_id": row.get("result_id"),
                "prior_guid": row.get("subject_guid"),
            })
        if apply:
            new_row = dict(row)
            new_row["subject_guid"] = env["subject_guid"]
            if env.get("issuer_guid"):
                new_row["issuer_guid"] = env["issuer_guid"]
            new_row["identity_backfill"] = "hermes_last_n_20260929"
            new_row["identity_backfill_ts"] = _now()
            rows[i] = new_row

    if apply and report["stamped"] > 0:
        bak = path.with_suffix(path.suffix + f".bak-{_now().replace(':', '')}")
        shutil.copy2(path, bak)
        report["backup"] = str(bak)
        out_lines = []
        for i, line in enumerate(lines):
            row = rows[i]
            if row is None:
                out_lines.append(line)
            else:
                out_lines.append(json.dumps(row, sort_keys=True, default=str))
        path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    # Post metric on window
    with_guid = 0
    for i in target:
        row = rows[i]
        if isinstance(row, dict) and row.get("subject_guid"):
            with_guid += 1
    report["window_with_guid"] = with_guid
    report["window_pct"] = round(100.0 * with_guid / max(len(target), 1), 1)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"window={report['n_window']} stamped={report['stamped']} "
            f"already={report['already']} unresolved={report['unresolved']} "
            f"pct={report['window_pct']} apply={apply}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
