#!/usr/bin/env python3
"""prewarm_options_ensemble.py — enqueue Grok+ChatGPT+local ensemble for all current options proposals.

Mirrors prewarm_retirement_ensemble.py: idempotent, skips fresh results and open jobs.
Run after options_engine scan or on cron:

  python3 scripts/prewarm_options_ensemble.py              # dry-run
  python3 scripts/prewarm_options_ensemble.py --apply
  python3 scripts/prewarm_options_ensemble.py --apply --force-scan
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import options_engine as oe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force-scan", action="store_true", help="regenerate proposals before enqueue")
    ap.add_argument("--fresh-hours", type=int, default=24)
    a = ap.parse_args()

    data = oe.generate_proposals(force=a.force_scan)
    proposals = data.get("proposals") or []
    print(f"{'APPLY' if a.apply else 'DRY-RUN'} · {len(proposals)} proposals (fresh window {a.fresh_hours}h)")
    for p in proposals:
        print(f"  · {p.get('id', '')[:50]:<50} {p.get('symbol')} ${p.get('strike')} {p.get('account', '')[:16]}")

    if not a.apply:
        print("(pass --apply to enqueue ensemble jobs)")
        return 0

    ens = oe.enqueue_ensemble_for_proposals(proposals, fresh_hours=a.fresh_hours)
    print(ens)
    return 0 if ens.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())