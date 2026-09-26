// Deterministic fixtures shaped to the Stage 4 /api/v3/active-trader read contract.
// They are intentionally labelled FIXTURE/READ_ONLY. No value in this file claims
// live broker, Level 2, tape, account, authorization, or order state.

export type Freshness = 'FRESH' | 'AGING' | 'STALE' | 'UNAVAILABLE';
export type WarningCategory =
  | 'STALE' | 'UNAVAILABLE' | 'PARTIAL' | 'CONFLICT' | 'NOT_INSTALLED'
  | 'NOT_CONFIGURED' | 'UNVERIFIED' | 'REDACTED' | 'BLOCKED';

export interface Envelope<T> {
  api_version: 'v3';
  service: 'active-trader-read';
  environment: 'SHADOW' | 'SIMULATION';
  request_id: string;
  generated_at: string;
  data_as_of: string | null;
  source_sha: string;
  sources: { source_name: string; source_type: string; freshness_state: Freshness }[];
  warnings: { category: WarningCategory; detail: string }[];
  data: T;
}

const UNAVAILABLE = 'UNAVAILABLE';

function env<T>(data: T, warnings: Envelope<T>['warnings'] = [], environment: 'SHADOW' | 'SIMULATION' = 'SHADOW'): Envelope<T> {
  return {
    api_version: 'v3', service: 'active-trader-read', environment,
    request_id: 'fixture-iteration-2', generated_at: '2026-07-23T20:51:39-04:00',
    data_as_of: '2026-07-23T20:51:39-04:00', source_sha: '70a681bb-fixture-ui-iteration-2',
    sources: [{ source_name: 'stage-06-fixture', source_type: 'FIXTURE', freshness_state: 'FRESH' }],
    warnings, data,
  };
}

export const MOOMOO_STATUS = {
  connector_state: 'DATA_ONLY_READY' as const,
  workspace_badges: ['DATA_AGREEMENT_CLEARED', 'SESSION_1_ARMED', 'LIVE_TRADING_BLOCKED'] as const,
  live_badge: false,
  observation_sessions_completed: 0,
  observation_sessions_required: 5,
  capture_sha: '70a681bb386713508767d9297f167d51d2bec4e4',
};

export const fixtures = {
  session: () =>
    env({
      session_state: 'READ_ONLY_SHADOW', environment: 'SIMULATION', authorization_short_hash: 'not-issued',
      selected_accounts: ['alpaca/alpaca_paper'], entry_cutoff: '2026-07-24T10:05:00-04:00',
      expiry: '2026-07-24T10:12:00-04:00', risk_limits: { max_trades: 0, max_daily_loss: 0 },
      kill_switch: 'ARMED', mode: 'SIMULATION', fixture: true,
      stage_gate: 'STAGE_5_OBSERVATION_0_OF_5', promotion_state: 'BLOCKED',
    }, [{ category: 'BLOCKED', detail: 'live trading and Stage 14 remain blocked until observation and promotion gates pass' }], 'SIMULATION'),
  candidates: () =>
    env({
      items: [
        { symbol: 'TESTA', company: 'Synthetic Alpha', state: 'IN_SCOPE', price: 4.20, rvol: 4.1,
          float_shares: 12_000_000, float_source: 'SYNTHETIC_FIXTURE', catalyst: 'fixture catalyst',
          book_state: UNAVAILABLE, tape_state: UNAVAILABLE, halt_state: 'NONE', freshness: 'FIXTURE',
          score: 82, res: 72, rrs: 38, reason: 'price, RVOL and float pass fixture prime filters' },
        { symbol: 'TESTB', company: 'Synthetic Beta', state: 'BLOCKED', price: 2.10, rvol: null,
          float_shares: null, float_source: UNAVAILABLE, catalyst: UNAVAILABLE,
          book_state: UNAVAILABLE, tape_state: UNAVAILABLE, halt_state: 'UNKNOWN', freshness: 'FIXTURE',
          score: 28, res: null, rrs: null, reason: 'required RVOL, float and microstructure evidence unavailable' },
        { symbol: 'TESTC', company: 'Synthetic Gamma', state: 'WATCH', price: 8.75, rvol: 2.3,
          float_shares: 28_500_000, float_source: 'SYNTHETIC_FIXTURE', catalyst: 'fixture earnings watch',
          book_state: UNAVAILABLE, tape_state: UNAVAILABLE, halt_state: 'NONE', freshness: 'FIXTURE',
          score: 61, res: 54, rrs: 44, reason: 'candidate remains below fire threshold' },
      ],
      next_cursor: null,
    }, [{ category: 'UNAVAILABLE', detail: 'book and tape remain unavailable until a qualifying Stage 5 data session is accepted' }]),
  symbol: (s: string) => {
    const candidate = fixtures.candidates().data.items.find(item => item.symbol === s) ?? fixtures.candidates().data.items[0];
    return env({
      symbol: s,
      identity: { symbol: s, company: candidate.company, instrument_type: 'EQUITY' },
      quote: { price: candidate.price, source: 'FIXTURE', as_of: '2026-07-23T20:51:39-04:00' },
      technical: { rvol: candidate.rvol, score: candidate.score, res: candidate.res, rrs: candidate.rrs },
      microstructure: UNAVAILABLE,
      price_structure: { support: s === 'TESTA' ? 4.05 : null, resistance: s === 'TESTA' ? 4.48 : null },
      eligibility: candidate.state === 'IN_SCOPE' ? 'SHADOW_ELIGIBLE' : 'NOT_ELIGIBLE',
      reason: candidate.reason,
      rejection_history: candidate.state === 'BLOCKED' ? [{ code: 'MISSING_REQUIRED_EVIDENCE' }] : [],
    }, [{ category: 'UNAVAILABLE', detail: 'Level 2 and tape require accepted Stage 5 observation evidence' }]);
  },
  accounts: () =>
    env({
      items: [
        { account_label: 'alpaca_paper', masked_account_id: '***ASV1', broker: 'alpaca',
          environment: 'SIMULATION', status: 'ACTIVE', read_state: 'OK', authentication_state: 'OK',
          active_trader_eligible: true, selected: true },
        { account_label: 'schwab_taxable', masked_account_id: '***', broker: 'schwab',
          environment: 'LIVE', status: 'READ_ONLY', read_state: 'OK', authentication_state: 'OK',
          active_trader_eligible: false, selected: false },
      ],
      discrepancies: [{ kind: 'account_label_mismatch', broker: 'alpaca' }],
    }, [{ category: 'CONFLICT', detail: '1 configuration discrepancy; no write path is enabled' }]),
  brokers: () =>
    env({
      alpaca: { connector_state: 'AVAILABLE', account_discovery: 'PARTIAL', write_state: 'SIMULATION_ONLY' },
      schwab: { connector_state: 'AVAILABLE', account_discovery: 'OK', write_state: 'BLOCKED' },
      moomoo: { connector_state: 'DATA_ONLY_READY', account_discovery: 'NOT_REQUESTED', write_state: 'BLOCKED' },
      excluded_from_active_trader_v1: ['snaptrade', 'fidelity', 'tastytrade'],
    }, [{ category: 'BLOCKED', detail: 'Moomoo trade context, account query and unlock are prohibited in the observation program' }]),
  capabilities: () =>
    env({
      items: [
        { broker: 'alpaca', account_label: 'alpaca_paper', capability: 'PLACE_LIMIT_RTH', effective_state: 'SIMULATION_ONLY', expired: false },
        { broker: 'schwab', account_label: 'schwab_taxable', capability: 'PLACE_LIMIT_RTH', effective_state: 'BLOCKED', expired: false },
        { broker: 'moomoo', account_label: '(data-only)', capability: 'MARKET_DATA_CAPTURE', effective_state: 'ARMED_SESSION_1', expired: false },
        { broker: 'moomoo', account_label: '(none)', capability: 'LIVE_SESSION_UNLOCK', effective_state: 'BLOCKED', expired: false },
      ],
      next_cursor: null,
    }),
  rejections: () =>
    env({ items: [
      { broker: 'schwab', account_label: 'schwab_taxable', symbol: 'GME',
        normalized_code: 'SECURITY_REQUIRES_BROKER_ASSISTANCE', retryable: false,
        requires_operator: true, requires_broker_call: true, raw_message_redacted: '[REDACTED]' },
    ], next_cursor: null }, [{ category: 'REDACTED', detail: 'raw broker payloads remain redacted' }]),
  notifications: () =>
    env({ items: [
      { severity: 'INFO', title: 'Session 1 observation armed for 06:55 ET', status: 'SCHEDULED' },
      { severity: 'ACTION_REQUIRED', title: 'Schwab broker assistance required for fixture rejection', status: 'OPEN' },
    ], next_cursor: null }),
  orders: (symbol = 'TESTA') =>
    env({ items: [
      { order_intent_id: 'fixture-preview', broker: 'alpaca', account_label: 'alpaca_paper', masked_account_id: '***',
        symbol, side: 'BUY', quantity: 10, order_type: 'LIMIT', limit_price: symbol === 'TESTA' ? 4.18 : null,
        status: 'PREVIEW_ONLY', environment: 'SIMULATION', validation: symbol === 'TESTA' ? 'PASS_FIXTURE' : 'BLOCKED_MISSING_EVIDENCE' },
    ], next_cursor: null }, [{ category: 'UNVERIFIED', detail: 'preview fixture only; no order is queued or submitted' }]),
  positions: () =>
    env({ items: [
      { symbol: 'TESTA', broker: 'alpaca', masked_account_id: '***', shares: 10, average_entry: 4.1,
        res: 72, rrs: 38, protection_state: 'CONFIRMED_FIXTURE', mark: 4.2, unrealized_pnl: 1.0,
        total_pnl: 1.0, source: 'FIXTURE' },
    ], next_cursor: null }, [{ category: 'UNVERIFIED', detail: 'position and P&L are deterministic fixtures, not broker state' }]),
  journal: () =>
    env({ items: [
      { event_type: 'candidate_in_scope', symbol: 'TESTA', replay_segment_ref: 'replay://stage4/segment-001', at: '09:31:04' },
      { event_type: 'order_intent_created', symbol: 'TESTA', replay_segment_ref: 'replay://stage4/segment-001', at: '09:31:08' },
      { event_type: 'protection_confirmed', symbol: 'TESTA', replay_segment_ref: 'replay://stage4/segment-001', at: '09:31:12' },
    ], next_cursor: null }, [{ category: 'REDACTED', detail: 'replay references only; fixture event stream' }]),
  features: () =>
    env({ items: [
      { flag_name: 'active_trader_next_visible', production_effective_mode: 'OFF', test_effective_mode: 'READ_ONLY' },
      { flag_name: 'active_trader_next_read_only', production_effective_mode: 'ON', test_effective_mode: 'ON' },
      { flag_name: 'active_trader_session_builder_enabled', production_effective_mode: 'OFF', test_effective_mode: 'PREVIEW' },
      { flag_name: 'active_trader_live_canary_enabled', production_effective_mode: 'OFF', test_effective_mode: 'OFF' },
    ], mutable_via_this_api: false }),
  parity: () =>
    env({
      parity_state: 'BASELINE_CAPTURED',
      note: 'visual shell iteration only; live parity is not claimed',
      checks: [
        { key: 'route_isolation', label: '/v3 remains untouched', state: 'PASS' },
        { key: 'read_only', label: 'no write-capable controls', state: 'PASS' },
        { key: 'quote', label: 'old/new quote parity', state: 'PENDING' },
        { key: 'candidate', label: 'candidate parity', state: 'PENDING' },
        { key: 'accounts', label: 'account quantity parity', state: 'PENDING' },
        { key: 'orders', label: 'order state parity', state: 'PENDING' },
        { key: 'positions', label: 'position and P&L parity', state: 'PENDING' },
        { key: 'risk', label: 'risk budget parity', state: 'PENDING' },
        { key: 'authorization', label: 'authorization hash parity', state: 'PENDING' },
        { key: 'kill', label: 'kill-switch parity', state: 'PENDING' },
      ],
    }, [{ category: 'UNVERIFIED', detail: 'production parity waits for read API and WebSocket projection' }]),

  // Decision surface — the LIVE /v3-next presents THIS (GO/WAIT/NO-GO that matches the right entry),
  // not raw charts/L2/tape. Verdict derives from the shadow engine (PRIME x FIRE); RES/RRS = confidence;
  // L2/tape/OFI are inputs consumed to produce the call and are deliberately NOT displayed.
  decisions: () =>
    env(
      {
        items: [
          { symbol: 'TESTA', verdict: 'GO', near_entry: true, price: 4.2,
            entry: 'buy next candle > 4.22 (bar after reversal-break)',
            rvol: '4.1×', vwap: 'reclaim +0.3%', macd: 'bull cross', momentum: 'accelerating', volume: '2.1M',
            prime_state: 'PRIMED', fire_state: 'FIRE', runner_state: 'ELIGIBLE',
            res: 72, rrs: 38, confidence: 'HIGH', freshness: 'FRESH',
            reason: 'reversal-break bar confirmed; enter next bar > 4.22' },
          { symbol: 'TESTW', verdict: 'WAIT', near_entry: true, price: 8.05,
            entry: 'arm: reversal bar forming ~8.20; enter next bar on break',
            rvol: '3.2×', vwap: 'below -0.4%', macd: 'flattening', momentum: 'building', volume: '1.4M',
            prime_state: 'PRIMED', fire_state: 'NO_FIRE', runner_state: 'NONE',
            res: 64, rrs: 51, confidence: 'MEDIUM', freshness: 'FRESH',
            reason: 'no reversal-break bar yet; sellers stacked at 8.20' },
          { symbol: 'TESTB', verdict: 'NO_GO', near_entry: false, price: 2.1,
            entry: '—', rvol: '—', vwap: '—', macd: '—', momentum: '—', volume: '—',
            prime_state: 'BLOCKED', fire_state: 'NO_FIRE', runner_state: 'NONE',
            res: null, rrs: null, confidence: 'LOW', freshness: 'AGING',
            reason: 'blocked: halt/eligibility gate; not near entry' },
        ],
        next_cursor: null,
      },
      [{ category: 'UNVERIFIED', detail: 'shadow decisions from fixtures; live GO/WAIT requires the Stage 5 Moomoo data plane' }],
    ),
};

export type Verdict = 'GO' | 'WAIT' | 'NO_GO';

// ---- LIVE integration with the real Command Center scanner (/api/v2/trade-ai/scanner) ----
// The v3-next static page is served same-origin on :7777, so it can read the actual TradeAI
// discovery output (screener -> enrichment -> scalp critic -> GO/WAIT/NO-GO). Read-only /
// awareness: copying/surfacing a symbol never places, validates, or queues a trade.

export interface ScannerTicker {
  symbol: string; decision: string; grade?: string; score?: number;
  rvol?: number; volume?: number; price?: number | string; change_pct?: number | string;
  gap_pct?: number | string; float_m?: number | string; catalyst?: string; sector?: string;
  setup_class?: string; operator_pill?: string; not_tradeable?: boolean;
  manual_review_required?: boolean; route_actionability?: string; critic_reasoning?: string;
  critic_verdict?: string;
}
export interface ScannerData {
  tickers: ScannerTicker[]; vix?: number; market_regime?: string;
  latest_run_go_count?: number; latest_run_wait_count?: number; latest_run_no_go_count?: number;
  latest_run_label?: string; run_date?: string; stale?: boolean; cache_age_sec?: number;
}

export async function fetchScanner(): Promise<ScannerData | null> {
  try {
    const r = await fetch('/api/v2/trade-ai/scanner', { headers: { accept: 'application/json' } });
    if (!r.ok) return null;
    const j = await r.json();
    return j && j.data ? (j.data as ScannerData) : null;
  } catch {
    return null;
  }
}
