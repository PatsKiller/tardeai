export type ActiveTraderMode = 'SHADOW' | 'MANUAL_PAPER_TEST_ONLY';
export type SignalState = 'ARMED' | 'TRIGGERED' | 'VETOED' | 'EXPIRED';
export type MarketSession = 'PREMARKET' | 'REGULAR';
export type BrokerVenue = 'schwab' | 'alpaca_paper' | 'alpaca_live' | 'moomoo' | 'thinkorswim_manual';

export interface EvidenceChip {
  id: string;
  label: string;
  tone: 'pass' | 'fail' | 'context' | 'warning';
  detail?: string;
}

export interface ScalpSignal {
  id: string;
  symbol: string;
  last: number;
  changePct: number;
  ign: number;
  ignDelta: number;
  ignDeltaMinutes: number;
  lane: string;
  mode: ActiveTraderMode;
  state: SignalState;
  cohort: 'profiled' | 'proxy';
  dataTier: 'T0' | 'T1' | 'T2';
  tierMultiplier: number;
  primarySetupLabel: string;
  matchedSetupLabels: string[];
  session: MarketSession;
  subscores: Record<'v_rvol' | 'v_burst' | 'v_cat' | 'v_disp' | 'v_liq' | 'v_rs', number>;
  fsm: Array<'IDLE' | 'IMPULSE' | 'PULLBACK' | 'ARMED' | 'TRIGGERED'>;
  fsmCurrent: 'IDLE' | 'IMPULSE' | 'PULLBACK' | 'ARMED' | 'TRIGGERED';
  expiresInSeconds: number;
  entryRef: number;
  stopRef: number;
  riskPerShare: number;
  stopBps: number;
  legToR: number;
  floatM: number;
  rvolTod: number;
  evidence: EvidenceChip[];
  operatorQuantity: number;
  tierDerivedQuantity: number;
  vetoReason?: string;
}

export interface BrokerAccount {
  id: string;
  venue: BrokerVenue;
  label: string;
  maskedNumber: string;
  permissionLabel: string;
  buyingPower: number;
  eligible: boolean;
  eligibilityReason?: string;
  paper: boolean;
  readOnly: boolean;
  maxShares: number;
}

export interface RoutingDraft {
  signalId: string;
  accountShares: Record<string, number>;
  selectedAccountIds: string[];
}
