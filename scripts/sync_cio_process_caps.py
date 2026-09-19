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
    # 2026-09-09: shared Flash process — 100000 soft cap was effectively-unlimited
    # and let 4929 settled calls/day exhaust the $0.50 global budget. Bound to 600.
    "advisory_desk_opinion": (1.25, 600),
    # 2026-09-14: the callers that shared advisory_desk_opinion, each on its own id (operator: split the label so
    # scheduled work can be moved off-peak and operator answers stay exempt). Global cap $2.00/day still binds.
    "cio_operator_reply": (0.60, 400),
    "cio_plan_enrichment": (0.50, 400),
    "cio_prompt_judge": (0.10, 150),
    "research_circle_analyzer": (0.10, 40),
    "hermes_cloud_json": (0.30, 300),
    "hermes_usefulness_score": (0.30, 600),
    "cio_hermes_research": (0.40, 200),
    "hermes_golden_judge": (0.10, 150),
    # 2026-09-19: L3 author was paid unregistered (2026-09-11); bind a process ceiling.
    "l3_judgment_author": (0.25, 48),
    "l3_independent_critic": (0.10, 24),
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
              'alex_cio_escalation','reflective_critic_flash','hermes_external_research',
              'advisory_desk_opinion')
            ORDER BY process_id""",
        fetch="all",
    ) or []
    print("\n  verify:")
    for r in rows:
        print(f"    {r['process_id']:28} {float(r['daily_cost_cap_usd']):.2f}  soft={r['daily_soft_cap']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
