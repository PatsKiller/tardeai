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
  // Distinct state systems (kept separate — a lane is not a setup, TRIGGERED is FSM, VETO is a gate):
  gateDecision?: 'PASS' | 'VETO' | 'DEFER';
  setupState?: 'SCANNING' | 'ARMED' | 'FIRED' | 'INVALIDATED' | 'EXPIRED' | 'DATA_UNAVAILABLE' | 'OUTSIDE_WINDOW';
  fsmState?: 'IDLE' | 'IMPULSE' | 'PULLBACK' | 'ARMED' | 'TRIGGERED';
  // Persisted setup identity (so a future label change never rewrites historical meaning):
  primarySetupId?: string;
  matchedSetupIds?: string[];
  setupVersion?: string;
  registryHash?: string;
  dataFreshness?: string;   // e.g. 'FRESH' | 'STALE' | 'UNKNOWN'
}

export type ActiveTraderDataState =
  | 'LIVE_DATA' | 'EMPTY_LIVE_QUEUE' | 'DATA_STALE' | 'API_UNAVAILABLE' | 'REFERENCE_SAMPLE' | 'LOADING';

export interface PermissionQueuePayload {
  data_state?: Exclude<ActiveTraderDataState, 'REFERENCE_SAMPLE' | 'LOADING'>;
  is_sample?: boolean;
  signals?: ScalpSignal[];
  actionable_count?: number;
  accounts?: BrokerAccount[];
  source_session_date?: string | null;
  is_live_session?: boolean;
  last_event_at?: string | null;
  generated_at?: string | null;
  registry_version?: string | null;
  registry_hash?: string | null;
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
