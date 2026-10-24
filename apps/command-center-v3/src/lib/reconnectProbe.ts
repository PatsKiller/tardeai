// Reconnect banner probe decision (site validation 2026-10-22).
//
// While any useApi feed is failing, ReconnectingBar probes /api/health every 3 s. It used to call
// signalApiRecover() after two OK probes. That dispatches a refetch to EVERY useApi hook on the page
// and resets each hook's backoff. When the server is up but ONE endpoint keeps failing (a heavy
// endpoint timing out, or a 5xx), /api/health is OK on the first two probes, so the whole page
// refetched every ~6 s for as long as that endpoint failed. The crawl measured /v3/agents » Memory
// re-issuing the failing request 100 times and each header feed 49 times in 150 s, against a server
// that was OOM-cycling at its 2 GiB limit.
//
// A global refetch is a recovery from a global outage: only after /api/health itself failed during
// this degraded episode. When health never failed, the failure is endpoint-specific and that
// hook's own backoff and 30 s slow retry handle it, so the probe stops and nothing is broadcast.

export type ProbeState = { okStreak: number; sawOutage: boolean }
export type ProbeAction = 'continue' | 'recover' | 'endpoint-only'

export const initialProbeState = (): ProbeState => ({ okStreak: 0, sawOutage: false })

export function onProbeResult(state: ProbeState, ok: boolean, okNeeded = 2): { state: ProbeState; action: ProbeAction } {
  if (!ok) return { state: { okStreak: 0, sawOutage: true }, action: 'continue' }
  const next = { ...state, okStreak: state.okStreak + 1 }
  if (next.okStreak < okNeeded) return { state: next, action: 'continue' }
  return { state: next, action: next.sawOutage ? 'recover' : 'endpoint-only' }
}
