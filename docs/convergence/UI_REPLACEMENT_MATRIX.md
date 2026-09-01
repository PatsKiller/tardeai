# Command Center Replacement Matrix

Status:      ACTIVE
as_of:       2026-08-26T14:08:51-04:00
Measured at: efcc51365 / not measured

Measured 2026-08-26 against `convergence/r20-r24` HEAD. No live cutover.
Every old page: KEEP | REPLACE | MERGE | SPLIT | RETIRE | REDIRECT | DEFER.
Parity class: PARITY | NEW_SUPERSET | INTENTIONAL_SEMANTIC_REPLACEMENT | REGRESSION.
REGRESSION = 0.

Live pages that are not replaced remain PARITY (the old page is still the live UI).
New `/control-plane/*` pages are NEW_SUPERSET or INTENTIONAL_SEMANTIC_REPLACEMENT.

| Old route | Purpose | Old sources | New route | New contract | Disposition | Parity | Retirement condition |
|---|---|---|---|---|---|---|---|
| `/` | home | live hubs | — | — | KEEP | PARITY | none |
| `/portfolio` | portfolio desk | portfolio APIs | — | — | KEEP | PARITY | none |
| `/portfolio/re-entry` | re-entry book | re-entry APIs | — | — | KEEP | PARITY | none |
| `/risk` | risk hub | risk APIs | — | — | KEEP | PARITY | none |
| `/trading` | trading hub | trading APIs | — | — | KEEP | PARITY | none |
| `/active-trader` | active trader | AT read APIs | — | — | KEEP | PARITY | none |
| `/trading/active-trader` | AT alias | Navigate | `/active-trader` | — | REDIRECT | PARITY | already Navigate |
| `/go/order/:intentId` | order deep link | sessionStorage | — | — | KEEP | PARITY | none |
| `/go/proposal/:proposalId` | proposal deep link | sessionStorage | — | — | KEEP | PARITY | none |
| `/manual-execution` | entry desk alias | Navigate | `/trading?tab=Entry+Desk` | — | REDIRECT | PARITY | already Navigate |
| `/strategy` | strategy hub | strategy APIs | — | — | KEEP | PARITY | none |
| `/agents` | legacy agent runtime hub | `/api/v3` agent-runtime | `/control-plane/agents` | CONTROL_PLANE_API_V1.1 | DEFER | INTENTIONAL_SEMANTIC_REPLACEMENT | operator review; old hub stays live |
| `/intelligence` | intelligence hub | intel APIs | — | — | KEEP | PARITY | none |
| `/research-intelligence` | RI desk | RI APIs | `/control-plane/research` | CONTROL_PLANE_API_V1.1 | DEFER | INTENTIONAL_SEMANTIC_REPLACEMENT | RI desk ≠ admin attention; no cutover |
| `/research` | RI alias | Navigate | `/research-intelligence` | — | REDIRECT | PARITY | already Navigate |
| `/hermes` | hermes hub | hermes APIs | — | — | KEEP | PARITY | none |
| `/retirement` | retirement hub | retirement APIs | — | — | KEEP | PARITY | none |
| `/journal` | journal | journal APIs | — | — | KEEP | PARITY | none |
| `/trade-in-view` | journal alias | Navigate | `/journal` | — | REDIRECT | PARITY | already Navigate |
| `/watch` | watch desk | watch APIs | — | — | KEEP | PARITY | none |
| `/watch/intelligence/:symbol` | symbol intel | watch APIs | — | — | KEEP | PARITY | none |
| `/watch/discovery` | watch discovery | watch APIs | — | — | KEEP | PARITY | none |
| `/watch-legacy` | legacy watch | watch APIs | — | — | DEFER | PARITY | operator review of legacy UI |
| `/defense` | defense hub | defense APIs | — | — | KEEP | PARITY | none |
| `/watchlist` | watch alias | Navigate | `/watch?tab=intelligence&view=top_ideas` | — | REDIRECT | PARITY | already Navigate |
| `/watchpool` | watchpool alias | Navigate | `/watch?tab=watchpool` | — | REDIRECT | PARITY | already Navigate |
| `/sectors` | sectors alias | Navigate | `/watch?tab=sectors` | — | REDIRECT | PARITY | already Navigate |
| `/pullback-macd` | pullback alias | Navigate | `/watch?tab=pullback-macd` | — | REDIRECT | PARITY | already Navigate |
| `/reports` | reports | reports APIs | — | — | KEEP | PARITY | none |
| `/rotation` | rotation intel | rotation APIs | — | — | KEEP | PARITY | none |
| `/redeploy` | redeploy desk | redeploy APIs | — | — | KEEP | PARITY | none |
| `/advisor-changes` | advisor alias | Navigate | `/rotation?tab=advisor-guide` | — | REDIRECT | PARITY | already Navigate |
| `/rec-intel` | recommendation intel | rec APIs | — | — | KEEP | PARITY | none |
| `/advisory` | advisory desk | advisory APIs | — | — | KEEP | PARITY | none |
| `/cio` | CIO desk | CIO APIs | — | — | KEEP | PARITY | none |
| `/health` | ops health | health APIs | `/control-plane/data` (partial) | CONTROL_PLANE_API_V1.1 | DEFER | NEW_SUPERSET | keep `/health`; stores page is additive |
| `/consumption` | consumption hub | consumption APIs | — | — | KEEP | PARITY | none |
| `/system` | legacy system/admin | system APIs | `/control-plane/system` | CONTROL_PLANE_API_V1.1 | DEFER | NEW_SUPERSET | keep `/system`; preview is additive |
| `/system/schwab-reauth` | schwab reauth | reauth APIs | — | — | KEEP | PARITY | none |

Intentional differences (not regressions):

- `/agents` vs `/control-plane/agents`: legacy runtime hub vs R21 envelope (`data` + `data_quality` + `evidence_class`). New page does not infer LIVE.
- `/research-intelligence` vs `/control-plane/research`: RI product desk vs admin attention list.
- `/system` vs `/control-plane/system`: full ops console vs read-only projection (`runtime.state` UNKNOWN unless projected).

New preview routes (registered, not cut over):

| New route | Owner | Disposition | Parity |
|---|---|---|---|
| `/control-plane` | INTEGRATOR | KEEP | NEW_SUPERSET |
| `/control-plane/system` | INTEGRATOR | KEEP | NEW_SUPERSET |
| `/control-plane/agents` | R22 | KEEP | NEW_SUPERSET |
| `/control-plane/workflows` | R22 | KEEP | NEW_SUPERSET |
| `/control-plane/research` | R23 | KEEP | INTENTIONAL_SEMANTIC_REPLACEMENT |
| `/control-plane/data` | R23 | KEEP | NEW_SUPERSET |
| `/control-plane/identity` | R23 | KEEP | NEW_SUPERSET |
| `/control-plane/notifications` | R23 | KEEP | NEW_SUPERSET |
| `/control-plane/learning` | R24 | KEEP | NEW_SUPERSET |
| `/control-plane/maturity` | R24 | KEEP | NEW_SUPERSET |
| `/control-plane/audit` | R24 | KEEP | NEW_SUPERSET |

No old route is retired by this cycle.
