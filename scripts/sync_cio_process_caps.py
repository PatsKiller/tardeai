#!/usr/bin/env python3
"""Sync CIO specialist-agent + reflective-critic LLM cost caps to Postgres llm_process_config.

2026-08-12: The CIO specialist family (guardian/ledger/steph/maria/morgan/alex)
routed through the governed bridge on DeepSeek-only lanes, but several caps were
below the projected cost of a single call, so every call was rejected with
COST_CAP_EXCEEDED before any spend. This mirrors the advisory_desk cap fix.

Also 2026-08-12: the reflective critics (sentinel/iris/reflection) migrated from
local Ollama to governed DeepSeek Flash (reflective_critic_flash); their cap is
synced here too.

Matches config/llm_process_registry.json (source of truth), and is idempotent
(UPSERT so a brand-new process row is created if it was never seeded).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

CAPS: dict[str, tuple[float, int]] = {
    "guardian_risk_critique": (0.20, 60),
    "ledger_tax_critique": (0.20, 60),
    "steph_allocation_review": (0.30, 40),
    "maria_research_critique": (0.30, 80),
    "morgan_wealth_synthesis": (0.20, 60),
    "alex_cio_synthesis": (0.40, 100),
    "alex_cio_escalation": (0.15, 20),
    "reflective_critic_flash": (0.10, 100),
    "hermes_external_research": (0.30, 120),
}


def main() -> int:
    import db_adapter

    for process_id, (cost, soft) in CAPS.items():
        db_adapter._execute(
            """INSERT INTO llm_process_config
                     (process_id, process_name, category, mode, daily_soft_cap,
                      daily_cost_cap_usd, notes, updated_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
               ON CONFLICT (process_id) DO UPDATE SET
                     daily_cost_cap_usd = EXCLUDED.daily_cost_cap_usd,
                     daily_soft_cap = EXCLUDED.daily_soft_cap,
                     updated_at = NOW()""",
            (process_id, process_id, None, "automated", soft, cost,
             "synced by sync_cio_process_caps.py"),
        )
        print(f"  [db] {process_id}: cost={cost} soft={soft}")

    # Verify
    rows = db_adapter._execute(
        """SELECT process_id, daily_cost_cap_usd, daily_soft_cap
             FROM llm_process_config
            WHERE process_id IN (
              'guardian_risk_critique','ledger_tax_critique','steph_allocation_review',
              'maria_research_critique','morgan_wealth_synthesis','alex_cio_synthesis',
              'alex_cio_escalation','reflective_critic_flash','hermes_external_research')
            ORDER BY process_id""",
        fetch="all",
    ) or []
    print("\n  verify:")
    for r in rows:
        print(f"    {r['process_id']:28} {float(r['daily_cost_cap_usd']):.2f}  soft={r['daily_soft_cap']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
