# Command Center Replacement Matrix

No live cutover. Existing routes KEEP or DEFER while R20–R24 pages are built side-by-side.
Every old page: KEEP | REPLACE | MERGE | SPLIT | RETIRE | REDIRECT | DEFER.

| Old route | New route | Disposition | Parity | Retirement condition |
|---|---|---|---|---|
| `/` | — | KEEP | UNMEASURED | none |
| `/portfolio` | — | KEEP | UNMEASURED | none |
| `/portfolio/re-entry` | — | KEEP | UNMEASURED | none |
| `/risk` | — | KEEP | UNMEASURED | none |
| `/trading` | — | KEEP | UNMEASURED | none |
| `/active-trader` | — | KEEP | UNMEASURED | none |
| `/trading/active-trader` | `/active-trader` | REDIRECT | existing | already Navigate |
| `/go/order/:intentId` | — | KEEP | UNMEASURED | none |
| `/go/proposal/:proposalId` | — | KEEP | UNMEASURED | none |
| `/manual-execution` | `/trading?tab=Entry+Desk` | REDIRECT | existing | already Navigate |
| `/strategy` | — | KEEP | UNMEASURED | none |
| `/agents` | `/control-plane/agents` | DEFER | UNMEASURED | R22 parity + audit + rollback; do not cut over |
| `/intelligence` | — | KEEP | UNMEASURED | none |
| `/research-intelligence` | `/control-plane/research` | DEFER | UNMEASURED | R23 parity + audit |
| `/research` | `/research-intelligence` | REDIRECT | existing | already Navigate |
| `/hermes` | — | KEEP | UNMEASURED | none |
| `/retirement` | — | KEEP | UNMEASURED | none |
| `/journal` | — | KEEP | UNMEASURED | none |
| `/trade-in-view` | `/journal` | REDIRECT | existing | already Navigate |
| `/watch` | — | KEEP | UNMEASURED | none |
| `/watch/intelligence/:symbol` | — | KEEP | UNMEASURED | none |
| `/watch/discovery` | — | KEEP | UNMEASURED | none |
| `/watch-legacy` | — | DEFER | UNMEASURED | operator review |
| `/defense` | — | KEEP | UNMEASURED | none |
| `/watchlist` | `/watch?tab=intelligence&view=top_ideas` | REDIRECT | existing | already Navigate |
| `/watchpool` | `/watch?tab=watchpool` | REDIRECT | existing | already Navigate |
| `/sectors` | `/watch?tab=sectors` | REDIRECT | existing | already Navigate |
| `/pullback-macd` | `/watch?tab=pullback-macd` | REDIRECT | existing | already Navigate |
| `/reports` | — | KEEP | UNMEASURED | none |
| `/rotation` | — | KEEP | UNMEASURED | none |
| `/redeploy` | — | KEEP | UNMEASURED | none |
| `/advisor-changes` | `/rotation?tab=advisor-guide` | REDIRECT | existing | already Navigate |
| `/rec-intel` | — | KEEP | UNMEASURED | none |
| `/advisory` | — | KEEP | UNMEASURED | none |
| `/cio` | — | KEEP | UNMEASURED | none |
| `/health` | `/control-plane/*` (partial) | DEFER | UNMEASURED | R23 data integrity + system |
| `/consumption` | — | KEEP | UNMEASURED | none |
| `/system` | `/control-plane/*` | DEFER | UNMEASURED | R21/R23/R24 parity + audit + rollback |
| `/system/schwab-reauth` | — | KEEP | UNMEASURED | none |

New preview routes (not registered in App.tsx / NavRail yet):

| New route | Owner | Disposition |
|---|---|---|
| `/control-plane/agents` | R22 | KEEP (preview) |
| `/control-plane/workflows` | R22 | KEEP (preview) |
| `/control-plane/research` | R23 | KEEP (preview) |
| `/control-plane/data` | R23 | KEEP (preview) |
| `/control-plane/identity` | R23 | KEEP (preview) |
| `/control-plane/notifications` | R23 | KEEP (preview) |
| `/control-plane/learning` | R24 | KEEP (preview) |
| `/control-plane/maturity` | R24 | KEEP (preview) |
| `/control-plane/audit` | R24 | KEEP (preview) |

No old route is retired by this program's current implementation.
