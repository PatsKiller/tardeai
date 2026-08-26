# Command Center cutover plan

No cutover in this cycle. Shadow routes are registered under `/control-plane/*`.
Legacy routes stay. Feature flag: `localStorage.CC_CONTROL_PLANE_PREVIEW=1`.
Nav preview section appears when the flag is set or the path is already under `/control-plane`.

| New route | Old route | Feature flag | Data parity | Intentional differences | Operator acceptance | Rollback | Observation window | Retirement |
|---|---|---|---|---|---|---|---|---|
| `/control-plane/agents` | `/agents` | `CC_CONTROL_PLANE_PREVIEW` | NEW_SUPERSET (R21 envelope + evidence class) | Does not infer LIVE; CALLABLE_ONLY is valid | operator review of DRY_RUN pack | remove preview nav + keep `/agents` | 14 days after deployed CURRENT SHA includes R21 | only after parity+audit+rollback proof |
| `/control-plane/workflows` | none | same | NEW_SUPERSET | Cross-ID lookup; partial lineage explicit | same | same | same | same |
| `/control-plane/research` | `/research-intelligence` | same | UNMEASURED vs RI desk | Admin attention vs RI product | same | keep RI desk | same | DEFER |
| `/control-plane/data` | `/system` (partial) | same | UNMEASURED | Store registry projection | same | keep `/system` | same | DEFER |
| `/control-plane/identity` | none | same | NEW_SUPERSET | Identity spine only | same | same | same | same |
| `/control-plane/notifications` | Telegram/CIO desks | same | UNMEASURED | Receipts, not composer | same | no live Telegram from this UI | same | DEFER |
| `/control-plane/learning` | none | same | NEW_SUPERSET | candidate ≠ promoted | same | same | same | same |
| `/control-plane/maturity` | none | same | NEW_SUPERSET | no client scores | same | same | same | same |
| `/control-plane/audit` | docs/audit pack | same | NEW_SUPERSET | claims with proof refs | same | same | same | same |
| `/control-plane/system` | `/system` | same | NEW_SUPERSET | runtime.state UNKNOWN unless projected | same | keep `/system` | same | DEFER |

Rollback: un-register preview nav, leave GET APIs, keep legacy pages. No redirects in this cycle.
