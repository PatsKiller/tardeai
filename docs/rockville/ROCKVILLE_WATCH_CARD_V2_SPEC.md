# ROCKVILLE_WATCH_CARD_V2_SPEC

## Hierarchy (5-second operator scan)

1. **Identity + market strip** — symbol, company, sector, badges, last, day %, timestamp  
2. **Canonical decision banner** — one of READY | WAIT | REVIEW_PENDING | STALE | AVOID | BLOCKED | DETERMINISTIC_FAIL | DATA_UNAVAILABLE | MANAGING  
3. **DeepSeek synthesis** — visible without audit drawer; provenance exact model  
4. **Actionability module** — state-specific (READY mechanics / WAIT contract / MANAGING position / else blockers only)  
5. **Why now / why not** — top supporting / conflicting / blocking  
6. **Evidence modules** — collapsible drill-down (later expansion)  
7. **CTAs** — state-appropriate only; never trade-like primary on fail/blocked  

## State → mechanics

| State | Current mechanics | Primary CTA |
|-------|-------------------|-------------|
| READY | Yes (verified) | REVIEW PROPOSAL |
| WAIT | No (wait contract) | SET CONDITION ALERT |
| REVIEW_PENDING | No | VIEW REVIEW STATUS |
| STALE / DATA_UNAVAILABLE | No | REFRESH INPUTS |
| BLOCKED / AVOID / DETERMINISTIC_FAIL | No | VIEW BLOCKERS |
| MANAGING | Position management only | VIEW POSITION PLAN |

## FTH required presentation

See fixture `tests/fixtures/rockville/ROCKVILLE_FTH_REGRESSION_FIXTURE.json`.

- Banner: **DETERMINISTIC FAIL — NO TRADE MECHANICS**  
- WHY BLOCKED: float floor + ATR cap  
- WHAT HAPPENS NEXT: refresh admission → rerun gate  
- HISTORY: collapsed, NOT CURRENT  
- Synthesis: may explain; must state no actionable ticket  

## Wireframe

See implementation prompt §7 and components under `apps/command-center-v3/src/components/rockville/`.
