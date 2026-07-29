import type { BrokerAccount, MotionSnapshot, ScalpSignal } from './activeTrader.types';
import { MOTION_CONTRACT } from './activeTrader.types';

export const MOCK_SIGNAL: ScalpSignal = {
  id: 'sig-qttb-001', symbol: 'QTTB', last: 3.42, changePct: 18.3,
  ign: 72, ignDelta: 19, ignDeltaMinutes: 6, lane: 'TRIGGER',
  mode: 'REVIEW', state: 'ARMED', cohort: 'profiled',
  dataTier: 'T2', tierMultiplier: 0.5, primarySetupLabel: 'MICRO PULLBACK',
  matchedSetupLabels: ['MICRO PULLBACK', 'IGNITION BREAKOUT'], session: 'REGULAR',
  subscores: { v_rvol: 88, v_burst: 81, v_cat: 64, v_disp: 57, v_liq: 41, v_rs: 69 },
  fsm: ['IDLE', 'IMPULSE', 'PULLBACK', 'ARMED', 'TRIGGERED'], fsmCurrent: 'ARMED',
  expiresInSeconds: 41, entryRef: 3.42, stopRef: 3.29, riskPerShare: 0.13,
  stopBps: 380, legToR: 2.8, floatM: 8.4, rvolTod: 11.6,
  evidence: [
    { id: 'slip', label: 'PASS slip 21bp <= 57bp', tone: 'pass' },
    { id: 'luld', label: 'PASS LULD 6.1% clear', tone: 'pass' },
    { id: 'vdu', label: 'PASS VDU 0.44x', tone: 'pass' },
    { id: 'vwap', label: 'PASS above VWAP', tone: 'pass' },
    { id: 'ssr', label: 'SSR off', tone: 'context' },
    { id: 'macd', label: 'MACD 5m +0.02 logged', tone: 'context' },
    { id: 'profile', label: 'profile 20 sess', tone: 'context' },
  ],
  operatorQuantity: 500, tierDerivedQuantity: 384,
};

export const MOCK_QUEUE: ScalpSignal[] = [
  MOCK_SIGNAL,
  { ...MOCK_SIGNAL, id: 'sig-lase-001', symbol: 'LASE', last: 6.18, ign: 66, ignDelta: 15,
    riskPerShare: 0.29, stopBps: 470, legToR: 3.4, tierDerivedQuantity: 270,
    primarySetupLabel: 'L2 MOMENTUM', matchedSetupLabels: ['L2 MOMENTUM'] },
  { ...MOCK_SIGNAL, id: 'sig-grab-001', symbol: 'GRAB', last: 2.71, ign: 63, ignDelta: 11,
    state: 'VETOED', riskPerShare: 0.004, stopBps: 15, vetoReason: 'stop inside spread',
    primarySetupLabel: 'IGNITION BREAKOUT', matchedSetupLabels: ['IGNITION BREAKOUT'] },
  { ...MOCK_SIGNAL, id: 'sig-xrx-001', symbol: 'XRX', last: 4.05, ign: 61, ignDelta: 9,
    state: 'VETOED', cohort: 'proxy', vetoReason: 'LULD headroom 1.4% · ADV unverified',
    session: 'PREMARKET',
    primarySetupLabel: 'PREMARKET MOMENTUM', matchedSetupLabels: ['PREMARKET MOMENTUM'] },
];

// Reference account capabilities are deliberately generic. No account environment is encoded in
// the identifier, venue, or eligibility state; a real server workflow must resolve those at runtime.
export const MOCK_ACCOUNTS: BrokerAccount[] = [
  { id: 'account-example-1', venue: 'connector-a', label: 'Connected Account A', maskedNumber: '...123',
    permissionLabel: 'current integration read-only', buyingPower: 48210,
    eligible: false, eligibilityReason: 'Execution authority not granted', readOnly: true, maxShares: 384 },
  { id: 'account-example-2', venue: 'connector-b', label: 'Connected Account B', maskedNumber: '...258',
    permissionLabel: 'long-only capability · server verification required', buyingPower: 12400,
    eligible: false, eligibilityReason: 'Capability verification pending', readOnly: true, maxShares: 150 },
  { id: 'account-example-3', venue: 'connector-c', label: 'Connected Account C', maskedNumber: '...441',
    permissionLabel: 'allocation preview eligible · runtime authority required', buyingPower: 100000,
    eligible: true, readOnly: false, maxShares: 500 },
  { id: 'data-provider-example', venue: 'data-provider', label: 'Market Data Provider', maskedNumber: 'data-plane',
    permissionLabel: 'L2 + tape data · no execution capability', buyingPower: 0,
    eligible: false, eligibilityReason: 'Data-plane capability only', readOnly: true, maxShares: 0 },
];

// REFERENCE SAMPLE ONLY — an illustrative motion snapshot for the preview layout. It is rendered
// exclusively behind an explicit "REFERENCE SAMPLE" label and is NEVER used as a live fallback.
export const MOCK_MOTION_SNAPSHOT: MotionSnapshot = {
  contract: MOTION_CONTRACT,
  contractOk: true,
  generatedAt: 0,
  uiRefreshAfterS: 5,
  pushPrimary: true,
  maxPullFallbacksPerMinute: 2,
  t2: {
    operatingCap: 2,
    providerHardCap: 8,
    leases: [
      { leaseId: 't2_sample_qttb', symbol: 'QTTB', admittedAt: 0, renewedAt: 0, expiresAt: 20, priority: 100_620, positionOpen: false },
    ],
    decisions: [
      { symbol: 'QTTB', tier: 'T2', admitted: true, reasonCode: 'admitted', refreshAfterS: 5, priority: 620 },
      { symbol: 'LASE', tier: 'T1', admitted: false, reasonCode: 'not_near_fire', refreshAfterS: 10, priority: 210 },
      { symbol: 'XRX', tier: 'T1', admitted: false, reasonCode: 't2_cooldown', refreshAfterS: 10, priority: 140 },
    ],
  },
  positions: [
    {
      symbol: 'NVDA', state: 'WATCH', action: 'HOLD', reasonCode: 'momentum_deteriorating',
      score: 0.61, confirmations: 2, drawdownFromHighR: 0.42, armedForS: 6, fireForS: 0, recoveryForS: 0,
      refreshAfterS: 5, price: 118.40, entryPrice: 116.90, hardStopPrice: 115.20, highWatermark: 119.65, evidenceAgeS: 2,
    },
    {
      symbol: 'AMD', state: 'HOLD', action: 'HOLD', reasonCode: 'momentum_healthy',
      score: 0.18, confirmations: 0, drawdownFromHighR: 0.05, armedForS: 0, fireForS: 0, recoveryForS: 0,
      refreshAfterS: 5, price: 96.10, entryPrice: 95.20, hardStopPrice: 93.80, highWatermark: 96.30, evidenceAgeS: 1,
    },
  ],
  exitSignals: [],
};
