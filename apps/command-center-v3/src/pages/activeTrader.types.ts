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
  gateDecision?: 'PASS' | 'VETO' | 'DEFER';   // DEFER = gate NULL/NOT_EVALUATED (fail closed, never PASS)
  setupState?: 'SCANNING' | 'ARMED' | 'FIRED' | 'INVALIDATED' | 'EXPIRED' | 'DATA_UNAVAILABLE' | 'OUTSIDE_WINDOW';
  fsmState?: 'IDLE' | 'IMPULSE' | 'PULLBACK' | 'ARMED' | 'TRIGGERED';
  // Canonical setup identity (a bare lane=TRIGGER is UNRESOLVED — never a fabricated named setup):
  setupIdentityState?: 'RESOLVED' | 'UNRESOLVED';
  displayEventLabel?: string;                 // e.g. "IGN TRIGGER — SETUP UNCLASSIFIED" for a bare trigger
  stopValidation?: 'PASS' | 'VETO' | 'NOT_EVALUATED' | string;
  executionEligibility?:
    | 'SIMULATION_ELIGIBLE' | 'SETUP_NOT_FIRED' | 'GATE_NOT_EVALUATED' | 'GATE_VETO'
    | 'SETUP_IDENTITY_UNRESOLVED' | 'STOP_INVALID' | 'DATA_INCOMPLETE' | string;
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

// ── L2 lifecycle (Moomoo/OpenD data plane) — explicit states, never "ARMED == fresh" ──
export type L2LifecycleState =
  | 'NOT_REQUESTED' | 'ARM_INTENT' | 'QUOTA_DEFERRED' | 'SUBSCRIBE_REQUESTED' | 'SUBSCRIBED'
  | 'WAITING_FIRST_BOOK' | 'WAITING_FIRST_TAPE' | 'FRESH' | 'STALE' | 'SEQUENCE_GAP'
  | 'CROSSED_BOOK' | 'ENTITLEMENT_MISSING' | 'PROVIDER_DISCONNECTED' | 'FAILED'
  | 'POST_FIRE_RETENTION' | 'UNSUBSCRIBE_PENDING' | 'UNSUBSCRIBED';

export interface L2Quota {
  total_quota: number | null;
  total_used: number | null;
  remain: number | null;
  own_used: number | null;
  other_connection_usage: number | null;
  reserved_units: number;
  available_for_discretionary: number | null;
  last_queried_at: string | null;
}

export interface L2SymbolLifecycle {
  symbol: string;
  state: L2LifecycleState;
  reason?: string;
  confirmed_subtypes?: string[];
  book_age_ms?: number | null;
  tape_age_ms?: number | null;
  sequence_id?: number | null;
  reconnect_epoch?: number;
  quota_units?: number;
  t2?: { is_t2: boolean; reason: string; freshness_state?: string; sequence_state?: string };
}

export interface L2Status {
  contract: string;
  read_only: boolean;
  write: boolean;
  order_path: boolean;
  source_commit?: string;
  connected: boolean;
  provider_state: string;
  entitlement_state: string;
  quota: L2Quota | null;
  concurrent_symbols?: number;
  max_concurrent_l2_symbols?: number;
  min_dwell_seconds?: number;
  reconnect_epoch?: number;
  confirmed_subscriptions?: Record<string, string[]>;
  symbols?: Record<string, L2SymbolLifecycle>;
  subscribed_any?: boolean;
  t2_any?: boolean;
}

// ── Fire performance (server-computed; immutable fire price, live current mark) ──
export type FireLifecycleState =
  | 'FIRED_FRESH' | 'ACTIVE_OBSERVATION' | 'STOP_TOUCHED' | 'TARGET_TOUCHED'
  | 'EXPIRED' | 'OUTCOME_PENDING' | 'OUTCOME_RESOLVED' | 'DATA_STALE';

export interface FirePerformance {
  fire_id: string;
  symbol: string;
  primary_setup_id: string | null;
  primary_setup_label: string | null;
  lane: string | null;
  setup_state: string | null;
  gate_decision: string | null;
  fired_at: string | null;
  fire_price: number | null;          // IMMUTABLE
  stop_ref: number | null;
  target_ref: number | null;
  current_bid: number | null;
  current_ask: number | null;
  current_last: number | null;
  mark_source: string | null;
  mark_at: string | null;
  mark_age_ms: number | null;
  change_from_fire: number | null;
  change_from_fire_pct: number | null;
  high_since_fire: number | null;
  low_since_fire: number | null;
  mfe_since_fire: number | null;
  mae_since_fire: number | null;
  current_r_multiple: number | null;
  risk_per_share: number | null;
  hit_stop: boolean;
  hit_1r: boolean;
  hit_target: boolean;
  outcome_state: string;
  lifecycle_state: FireLifecycleState;
  in_active_queue: boolean;
  age_seconds: number | null;
  l2_state_at_fire: string | null;
  l2_state_now: string | null;
  mark_stale: boolean;
}

export interface FirePerformancePayload {
  contract: string;
  read_only: boolean;
  write: boolean;
  order_path: boolean;
  generated_at: string;
  active_fires: FirePerformance[];
  fire_history: FirePerformance[];
  active_count: number;
  history_count: number;
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
