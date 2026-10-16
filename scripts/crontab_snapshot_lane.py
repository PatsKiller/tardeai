#!/usr/bin/env python3
"""crontab_snapshot_lane.py — the n8n lane crontab-snapshot-for-health-agent, with a useful-output receipt.

The lane rewrites the readable crontab snapshot the hardened health agent falls back to
(scripts/lib/crontab_snapshot.py, R-03). It used to be the bare shell line
``crontab -l > "$1.tmp" && mv -f "$1.tmp" "$1"``: exit 0 was its only evidence (#1831 dropped it from "proven").
This script does the same tmp + rename and records what it wrote.

    python3 scripts/crontab_snapshot_lane.py <target>             # live: rewrite <target> + LaneRunReceipt
    python3 scripts/crontab_snapshot_lane.py --dry-run <shadow>   # writes ONLY the shadow copy; no receipt

produced_count = 1 when the snapshot was rewritten with a non-empty crontab (unit: snapshot file rewritten);
``crontab -l`` failing or the write failing = ``dependency_unavailable`` (fatal), exit 1, and the previous snapshot is
left untouched (the tmp file never replaces it). An empty crontab is ``no_input_unexpected`` (this host always has
one; an empty read would blind the health agent's cron checks) and is NOT written over the last good snapshot.

The cron copy of this lane is still the shell line (operator-owned crontab); both write the same file atomically.
AUTHORITY: READ_ONLY_ADVISORY (reads the user crontab; writes only the target file and its own receipt).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LANE_ID = "crontab-snapshot-for-health-agent"
#: `crontab -l` is a local file read; anything slower than this is a wedged spool, not a crontab.
CRONTAB_TIMEOUT_S = 20


def read_crontab(runner=subprocess.run) -> tuple[str | None, str | None]:
    """(text, None) on success; (None, typed error) when `crontab -l` fails."""
    try:
        proc = runner(["crontab", "-l"], capture_output=True, text=True, timeout=CRONTAB_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 -- typed below
        return None, type(exc).__name__
    if proc.returncode != 0:
        return None, f"crontab_exit_{proc.returncode}"
    return proc.stdout or "", None


def write_snapshot(target: Path, text: str) -> None:
    """tmp + rename, as the shell line did (a reader never sees a half-written file)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def lane_output(text: str | None, *, written: bool, error: str | None) -> dict:
    """LaneRunReceipt@v2 output fields (n8n expected_output, unit: snapshot file rewritten)."""
    if error is not None:
        return {"produced_count": 0, "attempted_count": 1, "skipped_reasons": {"dependency_unavailable": 1}}
    if not (text or "").strip():
        return {"produced_count": 0, "attempted_count": 1, "skipped_reasons": {"no_input_unexpected": 1}}
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    return {
        "produced_count": 1 if written else 0,
        "attempted_count": 1,
        "skipped_reasons": {},
        "output_evidence": [{"kind": "file", "lines": len(lines), "bytes": len(text.encode("utf-8")),
                             "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}],
    }


def main(argv: list[str] | None = None, *, runner=subprocess.run) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="the target is the shadow copy; no receipt")
    ap.add_argument("target")
    args = ap.parse_args(argv)
    target = Path(args.target)
    started = datetime.now(timezone.utc).isoformat()
    text, error = read_crontab(runner)
    written = False
    if error is None and (text or "").strip():
        try:
            write_snapshot(target, text)
            written = True
        except OSError as exc:
            error = type(exc).__name__
    output = lane_output(text, written=written, error=error)
    ok = written
    if args.dry_run:
        print("LANE_OUTPUT " + json.dumps(output, sort_keys=True), file=sys.stderr)
    else:
        from scripts.lib.lane_last_receipt import write_lane_receipt

        write_lane_receipt(LANE_ID, ok=ok, exit_code=0 if ok else 1, started_at=started,
                           script="crontab_snapshot_lane.py", error=error,
                           summary={"target": target.name, "written": written}, output=output)
    print(json.dumps({"lane": LANE_ID, "mode": "dry-run" if args.dry_run else "live", "target": str(target),
                      "written": written, "error": error, "produced_count": output["produced_count"]}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
