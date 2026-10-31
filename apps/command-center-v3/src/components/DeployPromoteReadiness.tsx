// Job B — site vs main promote readiness (operator clarity). Uses releases-schedules data.
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Chip, ChipRow } from './primitives'
import { FONT, RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'
import { ciLabel, ciTone, countOrUnavailable, type NextRelease, type Serving } from '../lib/releasesSchedules'

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
  pushLiveSlot,
}: {
  serving: Serving | null
  next: NextRelease | null
  stopEffective: boolean
  stopState?: string | null
  /** Optional Push Live control when that surface is mounted on the page. */
  pushLiveSlot?: ReactNode
}) {
  const ahead = next == null ? null : next.is_serving ? 0 : next.commits_ahead
  const ciOk = next?.ci?.state === 'SUCCESS' || next?.ci?.state === 'OK'
  const ciPending = next?.ci?.state === 'PENDING'
  const promoteReady = !stopEffective && ahead != null && ahead > 0 && !!ciOk

  let headline = 'Site and main look aligned — nothing waiting to promote.'
  if (stopEffective) headline = 'Deploy STOP is latched — promote to the live site is blocked.'
  else if (ahead != null && ahead > 0 && ciOk) headline = `${ahead} commit${ahead === 1 ? '' : 's'} on main are not on the site yet — ready to promote when you choose.`
  else if (ahead != null && ahead > 0 && ciPending) headline = 'main is ahead of the site, but exact-SHA CI on main is still pending.'
  else if (ahead != null && ahead > 0) headline = 'main is ahead of the site, but main CI is not green yet — wait before promote.'

  return (
    <section data-testid="deploy-promote-readiness" style={panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <h2 style={h2}>On the site vs on main</h2>
        <ChipRow>
          <Chip tone={promoteReady ? 'info' : stopEffective ? 'danger' : 'neutral'}>
            {promoteReady ? 'promote candidate' : stopEffective ? 'STOP' : ahead === 0 ? 'serving main' : 'waiting'}
          </Chip>
        </ChipRow>
      </div>
      <p style={muted}>{headline}</p>

      <div style={{ display: 'grid', gap: 6 }}>
        <Item
          ok={serving ? serving.pins_agree : null}
          label="On the site now"
          detail={serving
            ? <><span style={mono}>{serving.short_sha}</span>{serving.release_name ? ` · ${serving.release_name}` : ''}</>
            : 'serving pin UNAVAILABLE'}
        />
        <Item
          ok={next ? true : null}
          label="On main (not necessarily live)"
          detail={next
            ? <><span style={mono}>{next.short_sha}</span>{next.subject ? ` · ${next.subject}` : ''}</>
            : 'main HEAD UNAVAILABLE'}
        />
        <Item
          ok={ahead == null ? null : ahead === 0}
          label="Commits ahead of site"
          detail={ahead == null ? 'unknown' : ahead === 0 ? 'none — site matches main' : countOrUnavailable(ahead)}
        />
        <Item
          ok={stopEffective ? false : true}
          label="Deploy STOP"
          detail={stopEffective
            ? <>latched ({stopState ?? 'STOP'}) — <Link to="/system/ops-controls?tab=jobs" style={{ color: TOKENS.primary }}>Ops → Controls</Link></>
            : 'off — promote allowed by STOP latch'}
        />
        <Item
          ok={next == null ? null : ciOk}
          label="Exact-SHA CI on main"
          detail={<span title={next?.ci?.reason ?? ''} style={{ color: toneVars(ciTone(next?.ci?.state)).color }}>{ciLabel(next?.ci)}</span>}
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
