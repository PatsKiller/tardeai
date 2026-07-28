// Defensive normalizers for the active-trader-motion-snapshot-v1 read contract.
//
// Every field is treated as untrusted. Unknown, absent, or malformed values normalize to `null`
// (numbers), `''` (strings), `[]` (lists) or a widened `'UNKNOWN'` enum — NEVER to a fabricated
// live value. The consuming UI renders those honest gaps as unavailable/stale, so a missing or
// broken payload can never masquerade as live motion.

import {
  MOTION_CONTRACT,
  type MotionDecision,
  type MotionExitSignal,
  type MotionExitState,
  type MotionLease,
  type MotionPosition,
  type MotionSnapshot,
  type MotionT2,
  type MotionTier,
} from '../../pages/activeTrader.types';

type Raw = Record<string, unknown>;

function asObject(value: unknown): Raw {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Raw) : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

// Finite number or null. Booleans are explicitly rejected (never coerced to 0/1).
function num(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return null;
}

function boolean(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

const TIERS = new Set(['T0', 'T1', 'T2']);
function tier(value: unknown): MotionTier {
  const upper = text(value).trim().toUpperCase();
  return TIERS.has(upper) ? (upper as MotionTier) : 'UNKNOWN';
}

const EXIT_STATES = new Set(['HOLD', 'WATCH', 'EXIT_ARMED', 'EXIT_SIGNAL', 'PROTECT_ONLY']);
function exitState(value: unknown): MotionExitState {
  const upper = text(value).trim().toUpperCase();
  return EXIT_STATES.has(upper) ? (upper as MotionExitState) : 'UNKNOWN';
}

function symbol(raw: Raw): string {
  return text(raw.symbol).trim().toUpperCase();
}

// Pull the first present numeric among candidate keys (backend snake_case may vary).
function pick(raw: Raw, keys: string[]): number | null {
  for (const key of keys) {
    const value = num(raw[key]);
    if (value !== null) return value;
  }
  return null;
}

function normalizeLease(value: unknown): MotionLease {
  const raw = asObject(value);
  return {
    leaseId: text(raw.lease_id) || text(raw.leaseId),
    symbol: symbol(raw),
    admittedAt: pick(raw, ['admitted_at', 'admittedAt']),
    renewedAt: pick(raw, ['renewed_at', 'renewedAt']),
    expiresAt: pick(raw, ['expires_at', 'expiresAt']),
    priority: num(raw.priority),
    positionOpen: boolean(raw.position_open ?? raw.positionOpen),
  };
}

function normalizeDecision(value: unknown): MotionDecision {
  const raw = asObject(value);
  return {
    symbol: symbol(raw),
    tier: tier(raw.tier),
    admitted: boolean(raw.admitted),
    reasonCode: text(raw.reason_code) || text(raw.reasonCode),
    refreshAfterS: pick(raw, ['refresh_after_s', 'refreshAfterS']),
    priority: num(raw.priority),
  };
}

function normalizeT2(value: unknown): MotionT2 {
  const raw = asObject(value);
  return {
    operatingCap: pick(raw, ['operating_cap', 'operatingCap']),
    providerHardCap: pick(raw, ['provider_hard_cap', 'providerHardCap']),
    leases: asArray(raw.leases).map(normalizeLease).filter((l) => l.symbol),
    decisions: asArray(raw.decisions).map(normalizeDecision).filter((d) => d.symbol),
  };
}

function normalizePosition(value: unknown): MotionPosition {
  const raw = asObject(value);
  return {
    symbol: symbol(raw),
    state: exitState(raw.state),
    action: text(raw.action) || null,
    reasonCode: text(raw.reason_code) || text(raw.reasonCode),
    score: num(raw.score),
    confirmations: pick(raw, ['confirmations']),
    drawdownFromHighR: pick(raw, ['drawdown_from_high_r', 'drawdownFromHighR']),
    armedForS: pick(raw, ['armed_for_s', 'armedForS']),
    fireForS: pick(raw, ['fire_for_s', 'fireForS']),
    recoveryForS: pick(raw, ['recovery_for_s', 'recoveryForS']),
    refreshAfterS: pick(raw, ['refresh_after_s', 'refreshAfterS']),
    price: pick(raw, ['price', 'current_price', 'currentPrice']),
    entryPrice: pick(raw, ['entry_price', 'entryPrice']),
    hardStopPrice: pick(raw, ['hard_stop_price', 'hardStopPrice']),
    highWatermark: pick(raw, ['high_watermark', 'highWatermark', 'high_water_mark']),
    evidenceAgeS: pick(raw, ['evidence_age_s', 'evidenceAgeS', 'quote_age_s', 'quoteAgeS']),
  };
}

function normalizeExitSignal(value: unknown): MotionExitSignal {
  const raw = asObject(value);
  return {
    symbol: symbol(raw),
    state: exitState(raw.state),
    reasonCode: text(raw.reason_code) || text(raw.reasonCode),
    at: pick(raw, ['at', 'generated_at', 'generatedAt']),
  };
}

/**
 * Normalize an untrusted motion payload into a typed snapshot.
 * Throws only if `raw` is not an object at all — the caller treats a throw as a fetch failure and
 * fails closed to an honest unavailable/stale state (it never substitutes fabricated data).
 */
export function normalizeMotionSnapshot(raw: unknown): MotionSnapshot {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    throw new Error('motion payload is not an object');
  }
  const root = raw as Raw;
  const contract = text(root.contract);
  return {
    contract,
    contractOk: contract === MOTION_CONTRACT,
    generatedAt: pick(root, ['generated_at', 'generatedAt']),
    uiRefreshAfterS: pick(root, ['ui_refresh_after_s', 'uiRefreshAfterS']),
    pushPrimary: boolean(root.push_primary ?? root.pushPrimary),
    maxPullFallbacksPerMinute: pick(root, ['max_pull_fallbacks_per_minute', 'maxPullFallbacksPerMinute']),
    t2: normalizeT2(root.t2),
    positions: asArray(root.positions).map(normalizePosition).filter((p) => p.symbol),
    exitSignals: asArray(root.exit_signals ?? root.exitSignals).map(normalizeExitSignal).filter((s) => s.symbol),
  };
}
