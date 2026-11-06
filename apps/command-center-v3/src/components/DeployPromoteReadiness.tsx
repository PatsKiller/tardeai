// Job B — site vs main promote readiness (operator clarity). Uses releases-schedules data.
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Chip, ChipRow } from './primitives'
import { FONT, RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'
import {
  ciLabel, ciTone, countOrUnavailable, promoteFacts, type Freshness, type NextRelease, type Serving,
} from '../lib/releasesSchedules'

const panel: CSSProperties = {
  background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md,
  padding: 14, minWidth: 0, display: 'grid', gap: 8,
}
const h2: CSSProperties = { margin: 0, fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }
const muted: CSSProperties = { margin: 0, fontSize: TYPE.sm, color: TOKENS.text[2], lineHeight: 1.4 }
const mono: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm }
const row: CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }

function Item({ ok, label, detail }: { ok: boolean | null; label: string; detail: ReactNode }) {
  const tone = ok === null ? 'warning' : ok ? 'success' : 'danger'
  return (
    <div style={{ ...row, fontSize: TYPE.sm }}>
      <Chip tone={tone}>{ok === null ? '?' : ok ? 'ok' : 'blocked'}</Chip>
      <span style={{ fontWeight: 700, color: TOKENS.text[0] }}>{label}</span>
      <span style={{ color: TOKENS.text[2] }}>{detail}</span>
    </div>
  )
}

export default function DeployPromoteReadiness({
  serving,
  next,
  stopEffective,
  stopState,
  nextFreshness = 'OK',
  servingFreshness = 'OK',
  pushLiveSlot,
}: {
  serving: Serving | null
  next: NextRelease | null
  /** Tri-state: `false` is a measured off; `null` is an unread latch and is never rendered as "off". */
  stopEffective: boolean | null
  stopState?: string | null
  nextFreshness?: Freshness
  servingFreshness?: Freshness
  /** Optional Push Live control when that surface is mounted on the page. */
  pushLiveSlot?: ReactNode
}) {
  const f = promoteFacts({ next, stopEffective, nextFreshness })
  const freshWord = nextFreshness === 'UNAVAILABLE' ? 'unavailable' : 'stale'
  const staleNote = (fresh: Freshness, text = '') => fresh === 'OK' ? text : `${text}${text ? ' · ' : ''}${fresh === 'UNAVAILABLE' ? 'unavailable' : 'stale'} — not current`

  return (
    <section data-testid="deploy-promote-readiness" style={panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <h2 style={h2}>On the site vs on main</h2>
        <ChipRow>
          <Chip tone={f.badgeTone}>{f.badge}</Chip>
        </ChipRow>
      </div>
      <p style={muted}>{f.headline}</p>

      <div style={{ display: 'grid', gap: 6 }}>
        <Item
          ok={serving && servingFreshness === 'OK' ? serving.pins_agree : null}
          label="On the site now"
          detail={serving
            ? <><span style={mono}>{serving.short_sha}</span>{serving.release_name ? ` · ${serving.release_name}` : ''}{staleNote(servingFreshness)}</>
            : 'serving pin UNAVAILABLE'}
        />
        <Item
          ok={next && nextFreshness === 'OK' ? true : null}
          label="On main (not necessarily live)"
          detail={next
            ? <><span style={mono}>{next.short_sha}</span>{next.subject ? ` · ${next.subject}` : ''}{staleNote(nextFreshness)}</>
            : 'main HEAD UNAVAILABLE'}
        />
        <Item
          ok={f.aheadCurrent ? (f.ahead == null ? null : f.ahead === 0) : null}
          label="Commits ahead of site"
          detail={f.ahead == null ? 'unknown'
            : !f.aheadCurrent ? `${countOrUnavailable(f.ahead)} (${freshWord} — not current)`
              : f.ahead === 0 ? 'none — site matches main'
                : countOrUnavailable(f.ahead)}
        />
        <Item
          ok={stopEffective == null ? null : !stopEffective}
          label="Deploy STOP"
          detail={stopEffective == null
            ? 'not read — unknown, not off'
            : stopEffective
              ? <>latched ({stopState ?? 'STOP'}) — <Link to="/system/ops-controls?tab=jobs" style={{ color: TOKENS.primary }}>Ops → Controls</Link></>
              : 'off — promote allowed by STOP latch'}
        />
        <Item
          ok={f.ciCurrent ? f.ciGreen : null}
          label="Exact-SHA CI on main"
          detail={<span title={next?.ci?.reason ?? ''} style={{ color: toneVars(ciTone(next?.ci?.state)).color }}>{ciLabel(next?.ci)}{f.ciCurrent ? '' : ' — not current'}</span>}
        />
      </div>

      {pushLiveSlot ? <div data-testid="deploy-push-live-slot">{pushLiveSlot}</div> : (
        <p style={muted}>
          Push Live (one-click prepare → promote) mounts here when that control is on the served build.
          Until then, auto-promote runs on the host when STOP is off, delegation is armed, and main CI is green —
          or use the host runbook under release-write.
        </p>
      )}
    </section>
  )
}
