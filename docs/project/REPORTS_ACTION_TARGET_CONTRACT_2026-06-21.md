# Reports Action Target Contract + 3-Column Briefing (2026-06-21)

Status:      HISTORICAL
as_of:       2026-06-21T18:53:04-04:00
Measured at: efcc51365 / not measured

Make every Reports action cue resolve to an **exact page + tab + drawer/modal**, not a generic hub, and
turn the reader into a presidential-brief layout (What-matters first, full body below). Advisory/read-only;
no broker execution, no new order path, no trading-gate/purge/secrets changes.

## Current defect (before)
Action buttons routed by `action_class` only → "Risk →", "Approvals →", "System →". A NEE approval, a PFLT
stop, and a cron failure all landed on the generic hub page. Body links went to `/v3/risk` even on
per-ticker lines.

## Target contract (`scripts/reports_portal.py` → `_action_target`)
Every extracted action now carries a canonical `target`:
```json
{ "target_type":"risk_stop|approval|recovery|system|hermes|research|portfolio|trading|report|unknown",
  "target_id":"<symbol/id/key>", "symbol":"PFLT",
  "route":"/v3/risk?symbol=PFLT&drawer=stop", "route_label":"Open PFLT stop detail",
  "modal":"risk_stop_drawer", "endpoint":"/api/v2/risk",
  "target_confidence":"high|medium|low", "reason":"<why>" }
```
Top-level `route`/`route_label` are **derived from `target`** (backward compatible).

## Supported target types → exact route
| Source line | target_type | route |
|---|---|---|
| `8 stop(s) TRIGGERED: PFLT, LHX, …` | risk_stop | `/v3/risk?symbols=PFLT,LHX,…&drawer=stops` (grouped) |
| `IRDM … stop FILLED` (single) | risk_stop | `/v3/risk?symbol=IRDM&drawer=stop` |
| `6 large positions without stops` | risk_stop | `/v3/risk?drawer=unprotected` |
| `CACI: stop-loss triggered → /v2/approvals` | approval | `/v3/trading?tab=Broker%20Proposals&symbol=CACI&modal=approval` |
| `RTX: reentry_candidate → /v2/recovery` | recovery | `/v3/risk?tab=Recovery&symbol=RTX&drawer=recovery` |
| `Research gap: … → /v2/research-topics` | research | `/v3/intelligence?tab=Research&query=<topic>&drawer=research` |
| `backup.sh cron failed` | system | `/v3/system?tab=Crons&query=backup.sh` |
| LLM / SIEM / broker health | system | `/v3/system?tab=LLM` / `?tab=SIEM` / `?tab=Brokers` |
| Hermes backlog/librarian/embedding | hermes | `/v3/hermes?tab=Research|Pipeline|Provenance&filter=…` |

The destination a line names (`→ /v2/approvals`) drives the **class** too (no Risk pill on an approval).
Stop lines pick the occurrence with the most tickers (the list line, not the bare summary).

## Page deep-link support added
- **RiskHub** — consumes `?tab`, `?symbol`, `?symbols=A,B,C`, `?drawer=stop|stops|unprotected|recovery`:
  opens the single-position stop drawer, the grouped triggered-stops drawer, the no-stop list, or the
  Recovery tab/detail. (verified)
- **SystemHub** — `?tab=` selects the exact tab (Crons/LLM/SIEM/Brokers/…); `?query=` shows a
  "Focused from Reports: <id>" banner. (verified)
- **TradingHub** — already selected `?tab=`; now `?symbol=` + `modal=approval` passes `focusSymbol` to
  `BrokerProposals`, which filters to that symbol with a "Focused on NEE approval · show all" banner. (verified)
- **ReportsHub** — reader leads with a **"What matters"** block: the report's actions grouped by target_type
  (Immediate risk / Approvals / Recovery / Research / System / Hermes / Portfolio), each a one-click exact
  deep-link; full body rendered below (unchanged). Action-queue + reader buttons use `target.route`/
  `route_label`; `target_confidence: low` renders muted "Open related page".

## Unresolved / medium-confidence targets
- **Approvals**: report source has no exact approval/proposal id → symbol-only focus, `confidence: medium`.
- **Hermes / Intelligence**: precise route+tab/query emitted; page-side filter consumption is partial
  (Intelligence tab/query not yet wired) → `confidence: medium`.
- **system_health** without an explicit subsystem keyword → defaults to `tab=Pipeline`, `confidence: medium`.

## Acceptance tests (`python3 scripts/reports_portal.py --verify`)
`No Stop-Out` not stop; retirement `drawdown` not risk; `/v2/approvals`→trading modal (no risk pill);
stop list→`drawer=stops`+symbols; `/v2/recovery`→`tab=Recovery`; research→intelligence; cron→`tab=Crons`;
every action has a target; high-confidence targets have route+label; no spurious `/v3/risk` default. **All pass.**

Browser-verified: grouped stops drawer, unprotected drawer, System Crons tab, Trading NEE approval focus —
all open the exact target, no console errors.
