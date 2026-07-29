// Pure display helpers for the live-motion panels. No fabrication: a missing value renders as an
// explicit em dash, never an invented number.

import type { MotionExitState, MotionTier } from '../../pages/activeTrader.types';

export const MOTION_UNKNOWN = '—'; // em dash for absent values

export function fmtAge(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return MOTION_UNKNOWN;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s ago`;
}

export function fmtSeconds(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s)) return MOTION_UNKNOWN;
  return `${Math.round(s)}s`;
}

export function fmtPrice(p: number | null | undefined): string {
  if (p == null || !Number.isFinite(p)) return MOTION_UNKNOWN;
  return p.toFixed(2);
}

export function fmtR(r: number | null | undefined): string {
  if (r == null || !Number.isFinite(r)) return MOTION_UNKNOWN;
  return `${r.toFixed(2)}R`;
}

// Score is a normalized 0..1 deterioration measure — render as a bounded percent.
export function fmtScorePct(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return MOTION_UNKNOWN;
  return `${Math.round(Math.min(1, Math.max(0, score)) * 100)}%`;
}

export function scorePctWidth(score: number | null | undefined): number {
  if (score == null || !Number.isFinite(score)) return 0;
  return Math.round(Math.min(1, Math.max(0, score)) * 100);
}

// Human-readable reason codes (backend snake_case → plain text). Unknown codes pass through
// lightly formatted rather than being hidden.
export function humanizeReason(code: string | null | undefined): string {
  if (!code) return MOTION_UNKNOWN;
  return code.replace(/_/g, ' ');
}

// Accessible, color-INDEPENDENT label for each exit state. Never rely on color alone.
export function exitStateLabel(state: MotionExitState): string {
  switch (state) {
    case 'HOLD': return 'HOLD';
    case 'WATCH': return 'WATCH';
    case 'EXIT_ARMED': return 'EXIT ARMED';
    case 'EXIT_SIGNAL': return 'EXIT SIGNAL';
    case 'PROTECT_ONLY': return 'PROTECT ONLY';
    default: return 'UNKNOWN STATE';
  }
}

// A short accessible description that makes the operator-safety boundary explicit in text.
export function exitStateDescription(state: MotionExitState): string {
  switch (state) {
    case 'HOLD': return 'Momentum healthy — no action.';
    case 'WATCH': return 'Temporary deterioration under watch — not an exit.';
    case 'EXIT_ARMED': return 'Persistent deterioration armed — evidence only, no order sent.';
    case 'EXIT_SIGNAL': return 'Exit-signal EVIDENCE — display only. No order, flatten, or broker action is taken here.';
    case 'PROTECT_ONLY': return 'Evidence stale — protective stop is the operative defense; no momentum exit inferred.';
    default: return 'State could not be interpreted from the payload.';
  }
}

// CSS modifier suffix for an exit state (styling lives in activeTrader.css, tokens only).
export function exitStateClass(state: MotionExitState): string {
  return `at-motion-state--${state.toLowerCase()}`;
}

export function tierClass(tier: MotionTier): string {
  return `at-motion-tier--${tier.toLowerCase()}`;
}
