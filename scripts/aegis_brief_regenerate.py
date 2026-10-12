#!/usr/bin/env python3
"""Executor CLI for lane aegis-brief-regenerate (Wave C).

Rebuilds today's aegis morning brief .md + .json sidecar. Telegram is NOT re-sent.

Usage:
  $PY scripts/aegis_brief_regenerate.py --dry-run
  $PY scripts/aegis_brief_regenerate.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aegis brief regenerate (Wave C; no Telegram send)")
    ap.add_argument("--dry-run", action="store_true", help="plan only; do not write export files")
    args = ap.parse_args(argv)

    from lib.n8n_cc_wave_c import LANE_BRIEF, write_lane_receipt

    mode = "dry_run" if args.dry_run else "live"
    if args.dry_run:
        detail = {"would": "aegis_morning_brief_delivery._get_morning_brief + write_formal_export"}
        write_lane_receipt(LANE_BRIEF, ok=True, mode=mode, detail=detail)
        print(json.dumps({"ok": True, "mode": mode, "lane_id": LANE_BRIEF, **detail}, default=str))
        return 0
    try:
        from aegis_morning_brief_delivery import _get_morning_brief, write_formal_export

        brief, summary = _get_morning_brief()
        path = write_formal_export(brief, summary)
        detail = {"export": path, "sections": len(brief.get("sections", []))}
        write_lane_receipt(LANE_BRIEF, ok=True, mode=mode, detail=detail)
        print(json.dumps({"ok": True, "mode": mode, "lane_id": LANE_BRIEF, **detail}, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001
        write_lane_receipt(
            LANE_BRIEF,
            ok=False,
            mode=mode,
            detail={"error": f"{type(exc).__name__}: {exc}"[:400]},
        )
        print(json.dumps({"ok": False, "error": str(exc)[:200]}, default=str))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
