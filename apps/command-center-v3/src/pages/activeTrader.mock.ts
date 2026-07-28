import type { BrokerAccount, ScalpSignal } from './activeTrader.types';

export const MOCK_SIGNAL: ScalpSignal = {
  id: 'sig-qttb-001', symbol: 'QTTB', last: 3.42, changePct: 18.3,
  ign: 72, ignDelta: 19, ignDeltaMinutes: 6, lane: 'TRIGGER',
  mode: 'MANUAL_PAPER_TEST_ONLY', state: 'ARMED', cohort: 'profiled',
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
    primarySetupLabel: 'PREMARKET MOMENTUM', matchedSetupLabels: ['PREMARKET MOMENTUM'] },
];

export const MOCK_ACCOUNTS: BrokerAccount[] = [
  { id: 'schwab-taxable', venue: 'schwab', label: 'Schwab Taxable', maskedNumber: '...123',
    permissionLabel: 'margin / short OK · current integration read-only', buyingPower: 48210,
    eligible: false, eligibilityReason: 'Live route not authorized in this build', paper: false,
    readOnly: true, maxShares: 384 },
  { id: 'schwab-rollover', venue: 'schwab', label: 'Schwab Rollover IRA', maskedNumber: '...258',
    permissionLabel: 'long only / no margin · current integration read-only', buyingPower: 12400,
    eligible: false, eligibilityReason: 'Manual paper test only', paper: false, readOnly: true, maxShares: 150 },
  { id: 'schwab-roth', venue: 'schwab', label: 'Schwab Roth IRA', maskedNumber: '...441',
    permissionLabel: 'long only / no margin · current integration read-only', buyingPower: 6980,
    eligible: false, eligibilityReason: 'Manual paper test only', paper: false, readOnly: true, maxShares: 0 },
  { id: 'alpaca-paper', venue: 'alpaca_paper', label: 'Alpaca Paper', maskedNumber: 'PA-tradeai',
    permissionLabel: 'paper / manual confirmation only', buyingPower: 100000,
    eligible: true, paper: true, readOnly: false, maxShares: 500 },
  { id: 'alpaca-live', venue: 'alpaca_live', label: 'Alpaca Taxable Live', maskedNumber: '...LIVE',
    permissionLabel: 'READ-ONLY / cannot route', buyingPower: 8140,
    eligible: false, eligibilityReason: 'Live route structurally blocked', paper: false, readOnly: true, maxShares: 0 },
  { id: 'moomoo', venue: 'moomoo', label: 'Moomoo / OpenD', maskedNumber: 'data-plane',
    permissionLabel: 'L2 + tape data · execution disabled', buyingPower: 0,
    eligible: false, eligibilityReason: 'Stage 0 data plane only', paper: false, readOnly: true, maxShares: 0 },
];
