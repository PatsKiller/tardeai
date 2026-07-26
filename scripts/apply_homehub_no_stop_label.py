#!/usr/bin/env python3
"""Idempotent: align HomeHub unprotected gauge with RiskHub no-stop taxonomy."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "apps/command-center-v3/src/pages/HomeHub.tsx"

IMPORT_OLD = "import { plain, plainAlert, runLabel, thresholdSentence, isScanStale } from '../lib/homeLabels'"
IMPORT_NEW = "import { plain, plainAlert, runLabel, thresholdSentence, isScanStale, protectionCounts } from '../lib/homeLabels'"

POS_OLD = "  const positions = risk?.positions ?? []\n  const triggered = positions.filter((p: any) => p.triggered)"
POS_NEW = (
    "  const positions = risk?.positions ?? []\n"
    "  const protection = protectionCounts(positions)\n"
    "  const triggered = positions.filter((p: any) => p.triggered)"
)

GAUGE_OLD = (
    '{riskLoading ? <SkelBlock h={100} /> : <RiskGauge value={positions.filter((p: any) => !p.has_stop).length} '
    'max={Math.max(positions.length, 8)} threshold={2} label="Unprotected" unit="" height={100} />}'
)
GAUGE_NEW = (
    '{riskLoading ? <SkelBlock h={100} /> : <RiskGauge value={protection.noStop} '
    'max={Math.max(protection.total, 8)} threshold={2} label="No stop" unit="" height={100} />}'
)


def main() -> int:
    text = TARGET.read_text()
    if "protectionCounts" in text and 'label="No stop"' in text:
        print("[ok] HomeHub already uses No-stop / protectionCounts")
        return 0
    for old, new in [(IMPORT_OLD, IMPORT_NEW), (POS_OLD, POS_NEW), (GAUGE_OLD, GAUGE_NEW)]:
        if old not in text:
            print(f"[warn] pattern missing: {old[:60]}...")
            continue
        text = text.replace(old, new, 1)
    TARGET.write_text(text)
    print(f"[ok] patched {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
