# FINAL_MATURITY_GAP_REGISTER@v2

Probe: `R5_PRE_CLOSURE_PROBE.json` @ 2026-08-18T20:33:36Z  
Classification: **MAIN_AHEAD_DOCS_ONLY** (origin/main `3d54dcbd` = R4 docs; CURRENT `244b7a41`)  
Authority: READ_ONLY_ADVISORY · MBI=0

## Classification legend

ENGINEERING_GAP · TIME_DEPENDENT_EVIDENCE · EXTERNAL_PROVIDER · OPERATOR_FINANCIAL_ACTION · PRODUCT_NON_GOAL

| gap_id | domain | sev | class | current | required | root_cause | this packet |
|---|---|---|---|---|---|---|---|
| G-HER-01 | Hermes loop | P0 | ENGINEERING | autonomous-loop + deep-research **failed** | resumable oneshot | 2×300s Ollama vs 600s TimeoutStart; DB SSL after long LLM | time budget + persist skip; deep-research reconnect |
| G-RES-01 | Challenge queue | P0 | ENGINEERING | 109 pending, no CIO worker timer | bounded drain | `hermes_cio_worker` exists, **no systemd timer** | unit+timer + queue health |
| G-OUT-01 | Outcomes | P0 | TIME_DEPENDENT | observer idle, 0 due | PROVEN_IDLE + next_due | cases <7d | next_due + PROVEN_IDLE |
| G-REC-01 | CIO recon | P1 | ENGINEERING | domain missing (no latest.json) | fail-soft producer | collector exists, **no writer** | `cio_reconciliation.persist` |
| G-ACT-01 | Actions | P1 | ENGINEERING | 12 system-backfill OPEN | SYSTEM_DIAGNOSTIC split | ledger untyped | recon counts diagnostics |
| G-PLN-01 | Plans | P1 | ENGINEERING | mostly draft | aging states | no SLA | recon flags draft backlog |
| G-OPN-01 | Advisory opinions | P1 | EXTERNAL/ENG | Flash/Pro EXPIRED | honest + refresh | timer/provider | freshness dims split; refresh not invented |
| G-HLD-01 | Holdings | P1 | ENGINEERING | desk CURRENT vs source 2026-08-14 | split clocks | FACT_FRESHNESS=cache | HOLDINGS_SOURCE_FRESHNESS |
| G-INF-01 | Influence | P1 | ENGINEERING | flags ACTIVE, runs=0 | comparator wiring | decorative flags | not claimed; MBI stays 0 |
| G-MEM-01 | Research→memory | P1 | ENGINEERING | no auto-bridge | admit on complete | hook missing | `on_hermes_completed` → admit |
| G-MAN-01 | Manifest | P1 | ENGINEERING | pins aa037b73 as CURRENT | historical pin or regen | generator semantics | left as historical pin; health still flags |
| G-LOOP-01 | Lineage infer | P1 | ENGINEERING | ADVISORY_USED inferred | receipt-only | symbol match | inference removed |
| G-CC-01 | CC queue | P1 | ENGINEERING | no queue projection | queue health on Closed Loop | missing | `/api/v3/intelligence/queue` + panel |
| Discovery | sector/asset | P2 | TIME_DEPENDENT | ARMED_NOT_PROVEN | durable events | worker failed | unblocked by G-HER-01 |
| Lesson reuse | learning | P2 | TIME_DEPENDENT | 0 reuse | historical replay | no scored cases | not fabricated |
| WhatsApp / exec | product | P3 | PRODUCT_NON_GOAL | — | — | — | out of scope |

Open stale PRs: #328 research-gov docs SUPERSEDED; #296 watch-review HISTORICAL; #255 research-prompt SUPERSEDED vs current worker. Do not merge.
