// Dev/test fixtures shaped to the Stage 4 /api/v3/active-trader read contract.
// The real read API (Stage 4) is manual/loopback/off by default; /v3-next consumes
// these deterministic fixtures so the workspace is developable without a live server
// and without any live Moomoo data. Nothing here fabricates live Level 2 or tape:
// microstructure and Moomoo-dependent values are explicit UNAVAILABLE.

export type Freshness = 'FRESH' | 'AGING' | 'STALE' | 'UNAVAILABLE';
export type WarningCategory =
  | 'STALE' | 'UNAVAILABLE' | 'PARTIAL' | 'CONFLICT' | 'NOT_INSTALLED'
  | 'NOT_CONFIGURED' | 'UNVERIFIED' | 'REDACTED';

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
    request_id: 'fixture-0000', generated_at: '2026-07-23T00:00:00Z',
    data_as_of: '2026-07-23T00:00:00Z', source_sha: 'v3next-fixture',
    sources: [{ source_name: 'fixture', source_type: 'FIXTURE', freshness_state: 'FRESH' }],
    warnings, data,
  };
}

export const MOOMOO_STATUS = {
  connector_state: 'NOT_INSTALLED' as const,
  workspace_badges: ['OFFLINE_IMPLEMENTED', 'CREDENTIAL_GATE_BLOCKED', 'LIVE_DATA_UNAVAILABLE'] as const,
  live_badge: false,
};

export const fixtures = {
  session: () =>
    env({
      session_state: 'AUTHORIZED', environment: 'SIMULATION', authorization_short_hash: 'auth-a002xx',
      selected_accounts: ['alpaca/alpaca_paper'], entry_cutoff: '2026-07-23T01:00:00Z',
      expiry: '2026-07-23T04:00:00Z', risk_limits: { max_trades: 3, max_daily_loss: 50 },
      kill_switch: 'ARMED', mode: 'SIMULATION',
    }),
  candidates: () =>
    env(
      {
        items: [
          { symbol: 'TESTA', company: 'Test Alpha Corp', state: 'IN_SCOPE', price: 4.2, rvol: 4.1,
            float_shares: 12_000_000, float_source: 'SYNTHETIC_FIXTURE', catalyst: 'synthetic',
            book_state: UNAVAILABLE, tape_state: UNAVAILABLE, halt_state: 'NONE' },
          { symbol: 'TESTB', company: 'Test Beta Inc', state: 'BLOCKED', price: 2.1, rvol: null,
            float_shares: null, float_source: UNAVAILABLE, catalyst: UNAVAILABLE,
            book_state: UNAVAILABLE, tape_state: UNAVAILABLE, halt_state: 'UNKNOWN' },
        ],
        next_cursor: null,
      },
      [{ category: 'UNAVAILABLE', detail: 'microstructure unavailable before Stage 5 Moomoo data plane' }],
    ),
  symbol: (s: string) =>
    env(
      { symbol: s, identity: { symbol: s }, microstructure: UNAVAILABLE, price_structure: UNAVAILABLE,
        eligibility: 'UNKNOWN', rejection_history: [] },
      [{ category: 'NOT_INSTALLED', detail: 'Level 2 / tape require the Stage 5 Moomoo data plane' }],
    ),
  accounts: () =>
    env({
      items: [
        { account_label: 'alpaca_paper', masked_account_id: '***ASV1', broker: 'alpaca',
          environment: 'SIMULATION', status: 'ACTIVE', read_state: 'OK', authentication_state: 'OK',
          active_trader_eligible: true },
        { account_label: 'schwab_taxable', masked_account_id: '***', broker: 'schwab',
          environment: 'LIVE', status: 'ACTIVE', read_state: 'OK', authentication_state: 'OK',
          active_trader_eligible: true },
      ],
      discrepancies: [{ kind: 'account_label_mismatch', broker: 'alpaca' }],
    }, [{ category: 'CONFLICT', detail: '1 configuration discrepancy' }]),
  brokers: () =>
    env({
      alpaca: { connector_state: 'AVAILABLE', account_discovery: 'PARTIAL' },
      schwab: { connector_state: 'AVAILABLE', account_discovery: 'OK' },
      moomoo: { connector_state: 'NOT_INSTALLED', account_discovery: 'UNAVAILABLE' },
      excluded_from_active_trader_v1: ['snaptrade', 'fidelity', 'tastytrade'],
    }, [{ category: 'NOT_INSTALLED', detail: 'moomoo connector not installed (credential gate blocked)' }]),
  capabilities: () =>
    env({
      items: [
        { broker: 'alpaca', account_label: 'alpaca_paper', capability: 'PLACE_LIMIT_RTH',
          effective_state: 'SUPPORTED', expired: false },
        { broker: 'schwab', account_label: 'schwab_taxable', capability: 'PLACE_LIMIT_RTH',
          effective_state: 'RESTRICTED', expired: false },
        { broker: 'moomoo', account_label: '(none)', capability: 'LIVE_SESSION_UNLOCK',
          effective_state: 'UNKNOWN', expired: false },
      ],
      next_cursor: null,
    }),
  rejections: () =>
    env({ items: [
      { broker: 'schwab', account_label: 'schwab_taxable', symbol: 'GME',
        normalized_code: 'SECURITY_REQUIRES_BROKER_ASSISTANCE', retryable: false,
        requires_operator: true, requires_broker_call: true, raw_message_redacted: '[REDACTED]' },
    ], next_cursor: null }, [{ category: 'REDACTED', detail: 'raw payloads redacted' }]),
  notifications: () =>
    env({ items: [
      { severity: 'ACTION_REQUIRED', title: 'schwab: broker assistance required', status: 'OPEN' },
    ], next_cursor: null }),
  orders: () =>
    env({ items: [
      { order_intent_id: 'oi-1', broker: 'alpaca', account_label: 'alpaca_paper', masked_account_id: '***',
        symbol: 'TESTA', side: 'BUY', quantity: 10, order_type: 'LIMIT', status: 'VALIDATED',
        environment: 'SIMULATION' },
    ], next_cursor: null }, [{ category: 'UNVERIFIED', detail: 'test/shadow projections; no live refresh' }]),
  positions: () =>
    env({ items: [
      { symbol: 'TESTA', broker: 'alpaca', masked_account_id: '***', shares: 10, average_entry: 4.1,
        res: 72, rrs: 38, protection_state: 'CONFIRMED', mark: UNAVAILABLE, unrealized_pnl: UNAVAILABLE,
        total_pnl: UNAVAILABLE },
    ], next_cursor: null }, [{ category: 'UNAVAILABLE', detail: 'marks/P&L require later market-data stages' }]),
  journal: () =>
    env({ items: [
      { event_type: 'order_intent_created', symbol: 'TESTA', replay_segment_ref: 'replay://stage4/segment-001' },
    ], next_cursor: null }, [{ category: 'REDACTED', detail: 'replay references only' }]),
  features: () =>
    env({ items: [
      { flag_name: 'active_trader_next_visible', production_effective_mode: 'OFF', test_effective_mode: 'READ_ONLY' },
      { flag_name: 'quick_add', production_effective_mode: 'OFF', test_effective_mode: 'OFF' },
    ], mutable_via_this_api: false }),
  parity: () =>
    env({ parity_state: 'BASELINE_ONLY', note: 'no UI parity claimed; comparison begins post-/v3-next' },
      [{ category: 'UNVERIFIED', detail: 'pre-parity baseline' }]),

  // Decision surface — the LIVE /v3-next presents THIS (GO/WAIT/NO-GO that matches the right entry),
  // not raw charts/L2/tape. Verdict derives from the shadow engine (PRIME x FIRE); RES/RRS = confidence;
  // L2/tape/OFI are inputs consumed to produce the call and are deliberately NOT displayed.
  decisions: () =>
    env(
      {
        items: [
          { symbol: 'TESTA', verdict: 'GO', price: 4.2, entry_trigger: 'limit ≤ 4.22 (VWAP reclaim)',
            prime_state: 'PRIMED', fire_state: 'FIRE', runner_state: 'ELIGIBLE',
            res: 72, rrs: 38, confidence: 'HIGH', freshness: 'FRESH',
            reason: 'reclaimed VWAP on RVOL 4.1×; resistance thin above' },
          { symbol: 'TESTW', verdict: 'WAIT', price: 8.05, entry_trigger: 'awaiting break > 8.20',
            prime_state: 'PRIMED', fire_state: 'NO_FIRE', runner_state: 'NONE',
            res: 64, rrs: 51, confidence: 'MEDIUM', freshness: 'FRESH',
            reason: 'primed but no trigger yet; sellers stacked at 8.20' },
          { symbol: 'TESTB', verdict: 'NO_GO', price: 2.1, entry_trigger: '—',
            prime_state: 'BLOCKED', fire_state: 'NO_FIRE', runner_state: 'NONE',
            res: null, rrs: null, confidence: 'LOW', freshness: 'AGING',
            reason: 'blocked: halt/eligibility gate; float unverified' },
        ],
        next_cursor: null,
      },
      [{ category: 'UNVERIFIED', detail: 'shadow decisions from fixtures; live GO/WAIT requires the Stage 5 Moomoo data plane' }],
    ),
};

export type Verdict = 'GO' | 'WAIT' | 'NO_GO';
