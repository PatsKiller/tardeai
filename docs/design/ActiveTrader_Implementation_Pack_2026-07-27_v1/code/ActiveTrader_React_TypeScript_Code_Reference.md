Status:      ACTIVE
as_of:       2026-07-28T00:17:07-04:00
Measured at: efcc51365 / not measured

ActiveTrader React / TypeScript Code Reference

Canonical folder:  
https://drive.google.com/drive/folders/1LFVCEPt243vdKYyBrVfRcFdaBByRDvnw

This document is a searchable Drive reference. The full raw TSX, TypeScript, CSS, and integration files are included in the downloadable implementation ZIP delivered with the project response.

COMPONENT TREE

ActiveTraderPage  
  ActiveTraderHeader  
  PermissionQueue  
    PermissionQueueRow  
  ActiveTradeCard  
    IgnitionEvidence  
    SetupAndTierBadges  
    TriggerStateMachine  
    LevelGrid  
    GateChipRail  
    DisplayOnlyOrderGrid  
    QuantityRail  
    PermissionFooter  
  AccountAllocationModal  
  SetupStrategyModal integration hook

CORE TYPES

export type ActiveTraderMode \= 'SHADOW' | 'MANUAL\_PAPER\_TEST\_ONLY'  
export type SignalState \= 'ARMED' | 'TRIGGERED' | 'VETOED' | 'EXPIRED'  
export type MarketSession \= 'PREMARKET' | 'REGULAR'  
export type BrokerVenue \=  
  | 'schwab'  
  | 'alpaca\_paper'  
  | 'alpaca\_live'  
  | 'moomoo'  
  | 'thinkorswim\_manual'

export interface ScalpSignal {  
  id: string  
  symbol: string  
  last: number  
  changePct: number  
  ign: number  
  ignDelta: number  
  ignDeltaMinutes: number  
  lane: string  
  mode: ActiveTraderMode  
  state: SignalState  
  cohort: 'profiled' | 'proxy'  
  dataTier: 'T0' | 'T1' | 'T2'  
  tierMultiplier: number  
  primarySetupLabel: string  
  matchedSetupLabels: string\[\]  
  session: MarketSession  
  subscores: Record\<string, number\>  
  fsm: string\[\]  
  fsmCurrent: string  
  expiresInSeconds: number  
  entryRef: number  
  stopRef: number  
  riskPerShare: number  
  stopBps: number  
  legToR: number  
  floatM: number  
  rvolTod: number  
  evidence: EvidenceChip\[\]  
  operatorQuantity: number  
  tierDerivedQuantity: number  
  vetoReason?: string  
}

export interface BrokerAccount {  
  id: string  
  venue: BrokerVenue  
  label: string  
  maskedNumber: string  
  permissionLabel: string  
  buyingPower: number  
  eligible: boolean  
  eligibilityReason?: string  
  paper: boolean  
  readOnly: boolean  
  maxShares: number  
}

TRADINGHUB INTEGRATION

import ActiveTraderPage from './ActiveTraderPage'

const TABS \= \[  
  'Trade AI', 'Options', 'Open Trades', 'Proposals', 'Entry Desk',  
  'Execution', 'Broker Recon', 'Scalp', 'ActiveTrader',  
  'ATM Controls', 'Broker Orders', 'Schwab Accounts',  
\] as const

const { data: activeTrader } \= useApi\<any\>(  
  '/api/v3/active-trader/permission-queue',  
  5\_000,  
  { enabled: tab \=== 'ActiveTrader' },  
)

{tab \=== 'ActiveTrader' && (  
  \<ActiveTraderPage  
    signals={activeTrader?.signals ?? \[\]}  
    accounts={activeTrader?.accounts ?? \[\]}  
    onOpenStrategies={() \=\> setActiveTraderStrategiesOpen(true)}  
  /\>  
)}

QUEUE ROW CONTRACT

function PermissionQueueRow({ signal, onSelect }) {  
  const reviewable \= signal.state \=== 'ARMED' || signal.state \=== 'TRIGGERED'  
  return (  
    \<button type="button" onClick={() \=\> onSelect(signal)}\>  
      \<span\>{signal.symbol}\<small\>{signal.last.toFixed(2)}\</small\>\</span\>  
      \<span\>{signal.ign}\<small\>delta \+{signal.ignDelta}\</small\>\</span\>  
      \<span\>  
        \<strong\>{signal.state \=== 'VETOED'  
          ? \`VETOED — ${signal.vetoReason}\`  
          : \`${signal.state} / ${signal.cohort} / ${signal.dataTier}\`}\</strong\>  
        \<small\>{signal.primarySetupLabel} · R {signal.riskPerShare} · {signal.stopBps}bp\</small\>  
      \</span\>  
      \<span\>{reviewable ? 'Review' : 'no action'}\</span\>  
    \</button\>  
  )  
}

ACTIVE TRADE CARD RULES

\- Render IGN and six subscores.  
\- Render primary and matched setup labels.  
\- Render FSM chain and expiry countdown.  
\- Render measured gate chips, never bare checks.  
\- Keep operator quantity separate from tier-derived quantity.  
\- Disable all order-shaped buttons in the first build.  
\- The only enabled transition is Prepare paper route, which opens a draft/allocation modal.  
\- Do not import an order-submit client.

ACCOUNT MODAL RULES

const selectable \= account.paper && account.eligible && \!account.readOnly

\- Alpaca Paper may be selectable after server-side environment verification.  
\- Schwab accounts remain visible but disabled/read-only.  
\- Alpaca Live remains visible but disabled.  
\- Moomoo/OpenD is DATA\_ONLY and has no checkbox.  
\- Thinkorswim is a manual handoff action outside the account table.  
\- Share count is entered per account and never split automatically.  
\- Paper notional and stop risk are labeled simulated.  
\- The first build contains no enabled final submit button.

MINIMUM CSS LAYOUT

.active-trader-page\_\_layout {  
  display: grid;  
  grid-template-columns: minmax(310px, 420px) minmax(0, 1fr);  
  gap: 18px;  
  align-items: start;  
}

.at-panel {  
  background: \#171b20;  
  border: 1px solid \#303740;  
  border-radius: 16px;  
  overflow: hidden;  
}

.at-evidence-grid {  
  display: grid;  
  grid-template-columns: 160px 1fr;  
  gap: 20px;  
  padding: 24px;  
}

.at-subscore-grid {  
  display: grid;  
  grid-template-columns: repeat(6, minmax(80px, 1fr));  
  gap: 12px;  
}

.at-level-grid {  
  display: grid;  
  grid-template-columns: repeat(6, 1fr);  
}

.at-order-grid {  
  display: grid;  
  grid-template-columns: repeat(4, 1fr);  
  gap: 10px;  
}

@media (max-width: 1100px) {  
  .active-trader-page\_\_layout { grid-template-columns: 1fr; }  
  .at-subscore-grid { grid-template-columns: repeat(3, 1fr); }  
  .at-level-grid { grid-template-columns: repeat(3, 1fr); }  
}

@media (max-width: 700px) {  
  .at-subscore-grid { grid-template-columns: repeat(2, 1fr); }  
  .at-level-grid { grid-template-columns: repeat(2, 1fr); }  
  .at-order-grid { grid-template-columns: repeat(2, 1fr); }  
}

AUTHORITY REQUIREMENTS

\- Initial mode: MANUAL\_PAPER\_TEST\_ONLY.  
\- No submitOrder callback in the page component.  
\- No automatic paper proposal route.  
\- No live fallback.  
\- No Moomoo order path.  
\- No Schwab order path.  
\- No real 2FA request.  
\- All read API envelopes: read\_only=true, write=false, auto\_route=false, canary=false.

TESTS

\- queue sorting and veto visibility;  
\- setup-label rendering;  
\- operator quantity versus tier quantity;  
\- only paper accounts selectable;  
\- live/read-only/data-only rows disabled with reasons;  
\- Moomoo has no routable checkbox;  
\- Thinkorswim is manual handoff only;  
\- focus trap and keyboard modal behavior;  
\- desktop and narrow screenshots;  
\- AST/import scan proving no order-submit client is imported.  
