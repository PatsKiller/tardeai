#!/usr/bin/env python3
"""Read-only provider-spend reconciliation.

Uses fixtures and/or operator exports. Never generates paid traffic.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# G2: root-only + scripts.lib — never also put scripts/ on path
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.provider_cost.parse import (  # noqa: E402
    parse_bypass_rows,
    parse_claude_code_jsonl,
    parse_console_totals,
    parse_consumption_rows,
    parse_openclaw_jsonl,
    parse_reservation_rows,
)
from scripts.lib.provider_cost.reconcile import reconcile  # noqa: E402

SUPPLIED_BASELINE = {
    "period_a_console": 48.32,
    "period_a_attributed_local": 0.833,
    "period_a_gap": 47.49,
    "period_b_console": 12.62,
    "period_b_attributed_local": 0.034,
    "period_b_gap": 12.59,
    "ab_console": 60.94,
    "ab_attributed": 0.867,
    "LEDGER_GAP": 60.07,
    "HOST_GAP": 49.77,
    "corrections": {
        "trade_ai_period_a_billing_matched": 0.53,
        "not_retroactive_new_table": 1.17,
        "openclaw": 0.25,
        "not_openclaw_30d": 1.46,
        "test_star_fake": 4.85,
        "kchar_not_usd": 8065,
        "claude_code_linux": 10.30,
    },
}


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    # G2: after imports settle — refuse dual lib.X / scripts.lib.X identity
    from scripts.lib import assert_single_import_identity
    assert_single_import_identity()
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", default=str(ROOT / "tests/fixtures/provider_cost/period_ab.json"))
    ap.add_argument("--out", default=str(ROOT / "docs/ops/provider-spend-attribution/latest_reconciliation.json"))
    args = ap.parse_args()
    data = _load_json(Path(args.fixture))
    events = []
    events += parse_console_totals(data.get("console") or [])
    events += parse_reservation_rows(data.get("reservations") or [])
    events += parse_consumption_rows(data.get("consumption") or [], at_default="2026-08-08T12:00:00+00:00")
    events += parse_bypass_rows(data.get("bypass") or [])
    events += parse_openclaw_jsonl([Path(p) for p in data.get("openclaw_paths") or []])
    events += parse_claude_code_jsonl([Path(p) for p in data.get("claude_paths") or []])
    # inline openclaw/claude fixture events
    if data.get("openclaw_inline"):
        events += parse_openclaw_jsonl(_write_temp_jsonl(data["openclaw_inline"], "openclaw"))
    if data.get("claude_inline"):
        events += parse_claude_code_jsonl(_write_temp_jsonl(data["claude_inline"], "claude"))
    report = reconcile(events, supplied_baseline=SUPPLIED_BASELINE)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "CONSOLE_TOTAL", "LEDGER_ATTRIBUTED", "LEDGER_GAP", "HOST_ATTRIBUTED",
        "HOST_GAP", "TEST_ONLY_COST", "CLAUDE_CODE", "OPENCLAW",
        "double_count_prevented", "residual_disposition", "report_hash",
    )}, indent=2))
    return 0


def _write_temp_jsonl(lines: list, prefix: str) -> list[Path]:
    import tempfile
    p = Path(tempfile.mkdtemp(prefix=f"pc_{prefix}_")) / f"{prefix}.jsonl"
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return [p]


if __name__ == "__main__":
    raise SystemExit(main())
