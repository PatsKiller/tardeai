/**
 * SurfaceModeBanner — the server's verdict on what this page is showing.
 *
 * Rendered above every /v3/control-plane/* surface from the route layout, not
 * from the page, so an individual page cannot omit it. It has no dismiss
 * control by design: a banner a user can close is a banner they will close, and
 * the fixture underneath looks exactly like live data.
 *
 * Data source: GET /api/v2/system/control-plane-surface-authority
 * (ControlPlaneSurfaceAuthority@v1). While that read is in flight or has failed
 * the mode is UNKNOWN and the banner still renders — the absence of an answer is
 * itself a fact the operator needs.
 */

import { useApi } from '../../hooks/useApi'
import { BB, DASH } from '../../lib/watchTokens'
import { surfaceVerdict, type SurfaceAuthority, type DataMode } from '../../lib/surfaceAuthority'

// House palette only (watchTokens BB/DASH) — no local hex, no sub-10px type.
// FROZEN has no dedicated house colour: it is a stale-but-honest state, so it
// borrows the amber ground and is separated by its label, not by a new hue.
const TONE: Record<DataMode, { bg: string; fg: string }> = {
  LIVE_GOVERNED: { bg: BB.greenDim, fg: BB.green },
  PREVIEW_FIXTURE: { bg: BB.amberDim, fg: BB.amber },
  FROZEN_SNAPSHOT: { bg: BB.amberDim, fg: BB.amber },
  UNAVAILABLE: { bg: BB.redDim, fg: BB.red },
  UNKNOWN: { bg: BB.bgShift, fg: BB.text3 },
}

export default function SurfaceModeBanner({ route }: { route: string }) {
  const { data, loading } = useApi<SurfaceAuthority>(
    '/api/v2/system/control-plane-surface-authority',
    300_000,
  )
  // LQ-1789: an in-flight first read is not a verdict. The endpoint takes 26-47 s under load, and rendering the
  // UNKNOWN verdict for that whole time told the operator the server had failed to determine something it had not
  // yet been asked to say. UNKNOWN now means "the server has said nothing"; reading is its own state.
  const pending = loading && !data
  const v = surfaceVerdict(pending ? null : data, route)
  const mode = pending ? 'PENDING' : v.mode
  // A last-known answer is a real answer, but it must never wear the live tone: amber until the live compute returns.
  const tone = pending ? { bg: BB.bgShift, fg: BB.text3 } : v.lastKnown ? TONE.FROZEN_SNAPSHOT : TONE[v.mode] ?? TONE.UNKNOWN

  return (
    <div
      data-surface-mode={mode}
      data-surface-route={v.route}
      data-banner-dismissible="false"
      role="status"
      aria-label={pending ? 'Data mode pending: asking the server' : `Data mode ${v.mode}: ${v.reason}`}
      style={{
        display: 'grid',
        gap: 3,
        margin: '0 0 12px',
        padding: '7px 10px',
        background: tone.bg,
        borderLeft: `3px solid ${tone.fg}`,
        fontSize: DASH.data,
        lineHeight: 1.45,
      }}
    >
      <div style={{ fontWeight: 800, letterSpacing: 0.4, color: tone.fg }}>
        {pending ? 'ASKING THE SERVER…' : v.label}
      </div>
      <div style={{ color: BB.text2 }}>
        {pending ? 'asking the server what this surface is showing…' : v.reason}
      </div>
      {!pending && v.asOf && (
        <div style={{ color: BB.text3, fontFamily: 'var(--mono)' }}>
          {v.asOf}
        </div>
      )}
      {v.fixtureBundled && (
        <div style={{ color: BB.text3, fontFamily: 'var(--mono)' }}>
          bundled fixture present: {v.fixturePath} — disclosed, never rendered as live data
        </div>
      )}
      <div style={{ color: BB.text3 }}>
        decided by the server · /api/v2/system/control-plane-surface-authority
      </div>
    </div>
  )
}
