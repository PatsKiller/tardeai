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

// One actionable signal from the TradeAI orchestrator (trade_ai_scans) — decision GO or MANUAL_REVIEW
// (the momentum fires: squeeze / runner / top-gainer / micro-float). REAL scanner fields only — NO
// fabricated IGN/subscores (those exist only on an ign_trigger item).
export interface ScannerSignal {
  source: 'scanner';
  id: string;
  symbol: string;
  scannedAt: string | null;
  scannedAtEt: string | null;        // "HH:MM" ET
  score: number | null;
  grade: string | null;              // A/B/C/D
  decision: string | null;           // GO / MANUAL_REVIEW
  route: string | null;
  routeStrategyId: string | null;
  routeActionability: string | null;
  setupClass: string | null;         // squeeze / high_rvol_runner / low_price_runner / micro_float_runner
  operatorPill: string | null;       // "SQUEEZE · R/S · 47.9x", "RUNNER · 8.6x"
  operatorSubtitle: string | null;
  criticVerdict: string | null;
  catalystVerified: boolean | null;
  rvol: number | null;
  gapPct: number | null;
  changePct: number | null;
  price: number | null;
  floatM: number | null;
  sector: string | null;
  manualReviewRequired: boolean | null;
  notTradeable: boolean | null;
  reviewState: string;               // GO / MANUAL_REVIEW
}

// Pre-fire visibility: the ignition ladder (climbing toward a trigger) + moomoo L2 arm set.
export interface ArmingSignal {
  symbol: string;
  lane: string;                      // IGN_45 / IGN_60 / IGN_75 / IGN_ACCEL
  ign: number;
  gate: string;
  setupState: string | null;
  dataTier: string;                  // T0 / T1 / T2 (T2 = L2/book engaged)
  l2Engaged: boolean;
  rvolTod: number | null;
  primarySetupLabel: string | null;
  spreadBps: number | null;
}

export interface ArmingStatus {
  available: boolean;
  market_open: boolean;
  lane_ladder: Record<string, number>;   // BELOW / IGN_45 / IGN_60 / IGN_75 / IGN_ACCEL / TRIGGER → count
  near_firing: ArmingSignal[];
  l2: {
    enabled: boolean;
    max_armed: number | null;
    ttl_seconds: number | null;
    armed: string[];
    connected: boolean;
    note: string;
  };
  note: string;
}

// Compact live status of the two engines feeding the queue (NOT a data dump).
export interface EngineStatus {
  scanner: {
    available: boolean;
    go_count_today: number;
    manual_review_count_today: number;
    wait_count_today: number;
    actionable_count_today: number;
    distinct_symbols: number;
    last_scan_at: string | null;
    latest_run_label: string | null;
  };
  ign: {
    rth_only: boolean;
    opens_et: string;                // "09:30"
    market_open: boolean;
    today_row_count: number;
    today_trigger_count: number;
    note: string;
  };
}

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
