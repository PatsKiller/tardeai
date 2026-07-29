// useActiveTraderMotion — ONE aggregate polling hook for the Active Trader live-motion snapshot.
//
// Bandwidth contract (see docs/design/ACTIVE_TRADER_T2_JIT_AND_MOMENTUM_EXIT_v1.md §3):
//   • at most ONE request per refresh cycle, regardless of how many tickers are displayed;
//   • honor the server ui_refresh_after_s hint, clamped to 5–30s (5s T2/open-position,
//     10s near-fire T1, 30s idle);
//   • AbortController prevents overlapping requests and aborts on unmount;
//   • polling materially slows while the document is hidden, then refreshes on visible;
//   • bounded exponential backoff after failures (never a tight retry loop);
//   • the last good snapshot is preserved during a failure but labelled STALE with age + error;
//   • mock/reference data is NEVER presented as live (that path lives in the page, not here);
//   • `requestCount` is a deterministic test seam proving one aggregate request per cycle.
//
// No WebSocket in this tranche. This is a bounded aggregate READ fallback only. The hook performs
// no order/broker/session side effect of any kind.

import { useCallback, useEffect, useRef, useState } from 'react';
import { normalizeMotionSnapshot } from '../components/active-trader-motion/normalizeMotion';
import {
  MOTION_ENDPOINT,
  MOTION_REFRESH_MAX_S,
  MOTION_REFRESH_MIN_S,
  type MotionFetchStatus,
  type MotionSnapshot,
} from '../pages/activeTrader.types';

export interface UseActiveTraderMotionOptions {
  enabled?: boolean;
  endpoint?: string;
}

export interface ActiveTraderMotionState {
  snapshot: MotionSnapshot | null;   // last GOOD snapshot (never fabricated)
  status: MotionFetchStatus;
  error: string | null;
  lastGoodAt: number | null;         // Date.now() of the last successful fetch
  ageMs: number | null;              // age of the last good snapshot, ticks ~1s for the UI
  nextRefreshS: number | null;       // clamped delay currently scheduled
  requestCount: number;              // aggregate requests actually fired (test seam)
  refreshNow: () => void;            // manual bounded refresh (e.g. operator retry)
}

// Clamp the server hint into operator bounds. Missing/invalid → the idle ceiling (30s).
function clampRefreshS(hint: number | null | undefined): number {
  if (typeof hint !== 'number' || !Number.isFinite(hint) || hint <= 0) return MOTION_REFRESH_MAX_S;
  return Math.min(MOTION_REFRESH_MAX_S, Math.max(MOTION_REFRESH_MIN_S, hint));
}

// Bounded backoff after failures: 5s, 10s, 20s, capped at 30s. Always ≥ the min interval so a
// persistent outage (e.g. the endpoint being absent) can never become a tight request loop.
function backoffS(failures: number): number {
  const raw = MOTION_REFRESH_MIN_S * Math.pow(2, Math.max(0, failures - 1));
  return Math.min(MOTION_REFRESH_MAX_S, Math.max(MOTION_REFRESH_MIN_S, raw));
}

export function useActiveTraderMotion(
  options: UseActiveTraderMotionOptions = {},
): ActiveTraderMotionState {
  const enabled = options.enabled !== false;
  const endpoint = options.endpoint ?? MOTION_ENDPOINT;

  const [snapshot, setSnapshot] = useState<MotionSnapshot | null>(null);
  const [status, setStatus] = useState<MotionFetchStatus>(enabled ? 'loading' : 'idle');
  const [error, setError] = useState<string | null>(null);
  const [lastGoodAt, setLastGoodAt] = useState<number | null>(null);
  const [nextRefreshS, setNextRefreshS] = useState<number | null>(null);
  const [requestCount, setRequestCount] = useState(0);
  const [ageMs, setAgeMs] = useState<number | null>(null);

  const mountedRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout>>();
  const abortRef = useRef<AbortController | null>(null);
  const failuresRef = useRef(0);
  const hasSnapshotRef = useRef(false);
  const lastGoodAtRef = useRef<number | null>(null);
  const pollRef = useRef<() => void>(() => {});

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = undefined;
    }
  };

  const scheduleNext = useCallback((delayS: number) => {
    clearTimer();
    setNextRefreshS(delayS);
    timerRef.current = setTimeout(() => pollRef.current(), Math.max(0, delayS * 1000));
  }, []);

  const poll = useCallback(async () => {
    clearTimer();
    if (!mountedRef.current || !enabled) return;

    // Materially slow while the tab is hidden — no fetch; the visibility handler refreshes on return.
    if (typeof document !== 'undefined' && document.hidden) {
      scheduleNext(MOTION_REFRESH_MAX_S);
      return;
    }

    // Overlap guard: abort any in-flight request before starting a new one.
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    // Count the aggregate request BEFORE awaiting — one increment per cycle, any ticker count.
    setRequestCount((c) => c + 1);

    try {
      const sep = endpoint.includes('?') ? '&' : '?';
      const res = await fetch(`${endpoint}${sep}_=${Date.now()}`, {
        signal: controller.signal,
        cache: 'no-store',
        headers: { Accept: 'application/json' },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      const next = normalizeMotionSnapshot(json);
      if (!mountedRef.current) return;
      failuresRef.current = 0;
      hasSnapshotRef.current = true;
      const now = Date.now();
      lastGoodAtRef.current = now;
      setSnapshot(next);
      setLastGoodAt(now);
      setAgeMs(0);
      setError(null);
      setStatus('live');
      scheduleNext(clampRefreshS(next.uiRefreshAfterS));
    } catch (err) {
      if (controller.signal.aborted || !mountedRef.current) return;
      failuresRef.current += 1;
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      // Preserve last-good if we have one (label STALE); otherwise the endpoint is UNAVAILABLE.
      setStatus(hasSnapshotRef.current ? 'stale' : 'unavailable');
      scheduleNext(backoffS(failuresRef.current));
    }
  }, [enabled, endpoint, scheduleNext]);

  // Keep the ref pointing at the latest poll closure so scheduled timers always run the current one.
  useEffect(() => {
    pollRef.current = poll;
  }, [poll]);

  // Lifecycle: start on mount / when enabled, tear down cleanly (abort + clear timers) on unmount.
  useEffect(() => {
    if (!enabled) {
      setStatus('idle');
      return;
    }
    mountedRef.current = true;
    setStatus(hasSnapshotRef.current ? 'live' : 'loading');
    poll();

    const onVisibility = () => {
      if (typeof document !== 'undefined' && !document.hidden && mountedRef.current) {
        pollRef.current();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);

    return () => {
      mountedRef.current = false;
      document.removeEventListener('visibilitychange', onVisibility);
      abortRef.current?.abort();
      clearTimer();
    };
    // poll is stable per (enabled, endpoint); re-running on those is correct.
  }, [enabled, endpoint, poll]);

  // ~1s age tick so the UI can show a truthful last-update age. No fetch is performed here.
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => {
      if (lastGoodAtRef.current != null) setAgeMs(Date.now() - lastGoodAtRef.current);
    }, 1000);
    return () => clearInterval(id);
  }, [enabled]);

  const refreshNow = useCallback(() => {
    if (mountedRef.current) pollRef.current();
  }, []);

  return {
    snapshot,
    status,
    error,
    lastGoodAt,
    ageMs,
    nextRefreshS,
    requestCount,
    refreshNow,
  };
}
