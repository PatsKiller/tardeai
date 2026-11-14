// Home deploy card (CAMPAIGN-8H Home item 5) — the deploy fact is the release that is SERVED, not the poller's last
// decision. Reuses the reviewed A09 summary from LQ-20261113-3077 (lib/deploys `deploysSummary`): one parse of the
// `/api/v2/ops/deploys` body, the same same/differs/unknown comparison, the same fail-closed STOP reading. Nothing here
// can turn the poller's receipt into a served version, and nothing here stores a relative age: the model carries
// instants only, and the view computes each age from the render clock (`nowIso` on the page's 30 s tick).
//
// Runs under `node --experimental-strip-types` (homeDeploy.test.ts); only ./deploys is imported at runtime.

import {
  DEPLOYS_PATHS, RESPONSE_STALE_AFTER_S, deploysSummary, freshness,
  type DataState, type DeploysStatusWire, type Tone,
} from './deploys.ts'

export const DEPLOY_SOURCE = DEPLOYS_PATHS.status

/** The shape the Home pages hand in (lib/homeV010's `Read<DeploysStatusWire>`, structurally). */
export interface DeploysRead {
  state: 'OK' | 'UNKNOWN' | 'TIMED OUT' | 'LOADING'
  data: DeploysStatusWire | null | undefined
  error: string | null
  at: string | null
  source: string
}

export interface HomeDeployView {
  /** Transport freshness of the body: OK / STALE (kept payload) / UNAVAILABLE (nothing readable) / LOADING. */
  state: DataState
  reason: string | null
  /** When this page read the body (absolute instant; the view ages it). */
  readAt: string | null
  /** What the SERVER says it is running. `sha` short, `fullSha` exact; `activatedAt` only when it parses. */
  served: { sha: string | null; fullSha: string | null; activatedAt: string | null; current: boolean | null; error: string | null }
  stop: { text: string; effective: boolean }
  /** The poller's last decision — a separate, labelled fact, never a substitute for `served`. */
  poller: { text: string; at: string | null; vsServed: 'same' | 'differs' | 'unknown'; beforeServed: boolean }
  tone: Tone
  tip: string
}

/**
 * `read` is the page's read of /api/v2/ops/deploys; `nowMs` is the render clock (transport STALE is computed against
 * it, so the card demotes a kept body on a later tick instead of trusting a stale "OK" forever).
 */
export function homeDeployView(read: DeploysRead | null | undefined, nowMs: number): HomeDeployView {
  const wire = read?.data ?? null
  const loading = !read || read.state === 'LOADING'
  const f = freshness(wire?.generated_at ?? wire?.stop?.as_of ?? null, !!wire, {
    nowMs: Number.isFinite(nowMs) ? nowMs : Date.now(),
    loading,
    // A state that is not OK is already a failed read: its text belongs in the card, not the transport clock.
    // LOADING is not a failure and must not be turned into one by its own state name.
    error: read && read.state !== 'OK' && read.state !== 'LOADING' ? read.error || read.state : null,
    staleAfterS: RESPONSE_STALE_AFTER_S,
  })
  const s = deploysSummary(wire, f)
  const sv = wire?.served ?? null
  const fullSha = typeof sv?.sha === 'string' && sv.sha.trim() ? sv.sha.trim() : null
  const activated = typeof sv?.activated_at === 'string' ? Date.parse(sv.activated_at) : NaN
  return {
    state: f.state,
    reason: f.reason,
    readAt: read?.at ?? null,
    served: {
      sha: s.servedSha,
      fullSha,
      activatedAt: Number.isFinite(activated) ? (sv!.activated_at as string) : null,
      current: typeof sv?.is_current === 'boolean' ? sv.is_current : null,
      error: typeof sv?.error === 'string' && sv.error ? sv.error : null,
    },
    stop: { text: s.stopText, effective: s.stopEffective },
    poller: { text: s.lastText, at: s.lastAt, vsServed: s.pollerVsServed, beforeServed: s.pollerBeforeServed },
    tone: s.cardTone,
    tip: s.cardTip,
  }
}
