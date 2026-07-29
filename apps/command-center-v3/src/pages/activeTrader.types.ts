// Workflow labels and venue identifiers are intentionally opaque strings. Neither one encodes an
// account environment or execution authority; those are resolved separately by runtime capability.
export type ActiveTraderWorkflowLabel = string;
export type SignalState = 'ARMED' | 'TRIGGERED' | 'VETOED' | 'EXPIRED';
export type MarketSession = 'PREMARKET' | 'REGULAR';
export type BrokerVenue = string;

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
  mode: ActiveTraderWorkflowLabel;      // opaque source/workflow label; never account environment
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
  setupIdentityState?: 'RESOLVED' | 'UNRESOLVED';
  displayEventLabel?: string;
  stopValidation?: 'PASS' | 'VETO' | 'NOT_EVALUATED' | string;
  executionEligibility?: string;        // legacy opaque capability evidence; not an account category
  primarySetupId?: string;
  matchedSetupIds?: string[];
  setupVersion?: string;
  registryHash?: string;
  dataFreshness?: string;
}

export type ActiveTraderDataState =
  | 'LIVE_DATA' | 'EMPTY_LIVE_QUEUE' | 'DATA_STALE' | 'API_UNAVAILABLE' | 'REFERENCE_SAMPLE' | 'LOADING';

export interface ScannerSignal {
  source: 'scanner';
  id: string;
  symbol: string;
  scannedAt: string | null;
  scannedAtEt: string | null;
  score: number | null;
  grade: string | null;
  decision: string | null;
  route: string | null;
  routeStrategyId: string | null;
  routeActionability: string | null;
  setupClass: string | null;
  operatorPill: string | null;
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
  reviewState: string;
}

export interface ArmingSignal {
  symbol: string;
  lane: string;
  ign: number;
  gate: string;
  setupState: string | null;
  dataTier: string;
  l2Engaged: boolean;
  rvolTod: number | null;
  primarySetupLabel: string | null;
  spreadBps: number | null;
}

export interface ArmingStatus {
  available: boolean;
  market_open: boolean;
  lane_ladder: Record<string, number>;
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
    opens_et: string;
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
  readOnly: boolean;
  maxShares: number;
}

export interface RoutingDraft {
  signalId: string;
  accountShares: Record<string, number>;
  selectedAccountIds: string[];
}

// ─────────────────────────────────────────────────────────────────────────────────────────────────
// Active Trader Live Motion (contract active-trader-motion-snapshot-v1).
// ONE aggregate read snapshot shaped from deterministic T2 JIT + momentum-exit policies.
// The stacked backend supplies GET /api/v3/active-trader/motion. The UI still fails closed when the
// endpoint is unavailable or stale and never fabricates live values.
// EXIT_SIGNAL is account-unbound display evidence, never permission to send an order.
// ─────────────────────────────────────────────────────────────────────────────────────────────────

export const MOTION_ENDPOINT = '/api/v3/active-trader/motion';
export const MOTION_CONTRACT = 'active-trader-motion-snapshot-v1';

export const MOTION_REFRESH_MIN_S = 5;
export const MOTION_REFRESH_MAX_S = 30;

export type MotionTier = 'T0' | 'T1' | 'T2' | 'UNKNOWN';
export type MotionExitState =
  | 'HOLD' | 'WATCH' | 'EXIT_ARMED' | 'EXIT_SIGNAL' | 'PROTECT_ONLY' | 'UNKNOWN';

export type MotionFetchStatus = 'idle' | 'loading' | 'live' | 'stale' | 'unavailable';

export interface MotionLease {
  leaseId: string;
  symbol: string;
  admittedAt: number | null;
  renewedAt: number | null;
  expiresAt: number | null;
  priority: number | null;
  positionOpen: boolean;
}

export interface MotionDecision {
  symbol: string;
  tier: MotionTier;
  admitted: boolean;
  reasonCode: string;
  refreshAfterS: number | null;
  priority: number | null;
}

export interface MotionT2 {
  operatingCap: number | null;
  providerHardCap: number | null;
  leases: MotionLease[];
  decisions: MotionDecision[];
}

export interface MotionPosition {
  symbol: string;
  state: MotionExitState;
  action: string | null;
  reasonCode: string;
  score: number | null;
  confirmations: number | null;
  drawdownFromHighR: number | null;
  armedForS: number | null;
  fireForS: number | null;
  recoveryForS: number | null;
  refreshAfterS: number | null;
  price: number | null;
  entryPrice: number | null;
  hardStopPrice: number | null;
  highWatermark: number | null;
  evidenceAgeS: number | null;
}

export interface MotionExitSignal {
  symbol: string;
  state: MotionExitState;
  reasonCode: string;
  at: number | null;
  accountBound: boolean;
}

export interface MotionSnapshot {
  contract: string;
  contractOk: boolean;
  generatedAt: number | null;
  uiRefreshAfterS: number | null;
  pushPrimary: boolean;
  maxPullFallbacksPerMinute: number | null;
  t2: MotionT2;
  positions: MotionPosition[];
  exitSignals: MotionExitSignal[];
}
