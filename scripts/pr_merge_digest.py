#!/usr/bin/env python3
"""One-tap Telegram PR merge digest (Mergify go-signal) — AGENTS.md §25.10.

  # what the next digest would say (no send, no writes):
  .venv/bin/python scripts/pr_merge_digest.py --dry-run --json
  # host timer (weekdays 08:00/12:00/16:30 ET, weekends every 3h):
  .venv/bin/python scripts/pr_merge_digest.py --apply
  # coordinator: send now even if an identical digest is pending:
  .venv/bin/python scripts/pr_merge_digest.py --apply --now
  # head-SHA binding + Merged/Live notes (host timer every 3 min):
  .venv/bin/python scripts/pr_merge_digest.py --reconcile --apply

Default is a dry run. Agents never run --apply (host timers / coordinator only).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai"))
    ap.add_argument("--apply", action="store_true", help="Send Telegram / write labels and state")
    ap.add_argument("--dry-run", action="store_true", help="Default; overrides --apply")
    ap.add_argument("--now", action="store_true", help="Send even when an identical digest is pending")
    ap.add_argument("--reconcile", action="store_true", help="Head-SHA binding + Merged/Live notes")
    ap.add_argument("--json", action="store_true", dest="as_json")
    a = ap.parse_args(argv)
    apply = bool(a.apply) and not a.dry_run

    from scripts.lib import pr_merge_digest as pmd

    try:
        if a.reconcile:
            out = pmd.reconcile(repo=a.repo, apply=apply)
        else:
            out = pmd.run_digest(repo=a.repo, apply=apply, force=bool(a.now))
    except RuntimeError as exc:
        out = {"ok": False, "error": str(exc)}
    if a.as_json:
        print(json.dumps(out, indent=2, default=str))
    elif a.reconcile:
        hb = out.get("head_binding") or []
        notes = out.get("notes") or {}
        print(f"apply={apply} labelled={len(hb)} "
              f"removed={sum(1 for r in hb if r['action'] in ('label_removed', 'would_remove_label'))} "
              f"merged_note={(notes.get('merged_note') or {}).get('prs')} live_notes={len(notes.get('live_notes') or [])}")
    else:
        print(f"action={out.get('action')} ready={out.get('ready')} needs_operator={out.get('needs_operator')} "
              f"digest={out.get('digest_id')} apply={apply}")
        if out.get("message") and not apply:
            print("---\n" + out["message"])
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
