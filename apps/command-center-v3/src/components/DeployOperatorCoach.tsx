// Two-job coach strip for Deploys (operator clarity): Approve merge vs put on site.
import type { CSSProperties } from 'react'
import { Chip, ChipRow } from './primitives'
import { RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'
import type { NextRelease, Serving } from '../lib/releasesSchedules'
import { coachFacts } from '../lib/releasesSchedules'

const panel: CSSProperties = {
  background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md,
  padding: 14, minWidth: 0, display: 'grid', gap: 10,
}
const h2: CSSProperties = { margin: 0, fontSize: TYPE.md, fontWeight: 800, color: TOKENS.text[0] }
const muted: CSSProperties = { margin: 0, fontSize: TYPE.sm, color: TOKENS.text[2], lineHeight: 1.4 }
const job: CSSProperties = {
  background: TOKENS.bg[0], border: `1px solid ${TOKENS.borderSubtle}`, borderRadius: RADIUS.md,
  padding: 10, display: 'grid', gap: 4,
}
const jobTitle: CSSProperties = { margin: 0, fontSize: TYPE.sm, fontWeight: 800, color: TOKENS.text[0] }

export type CoachInFlight = {
  ready_count?: number | null
  count?: number | null
  freshness?: string
}

export default function DeployOperatorCoach({
  inFlight,
  serving,
  next,
  stopEffective,
  onHelp,
}: {
  inFlight: CoachInFlight | null
  serving: Serving | null
  next: NextRelease | null
  stopEffective: boolean
  onHelp: () => void
}) {
  const facts = coachFacts({ inFlight, next, stopEffective })
  const { ready, open, ahead, recommend } = facts

  return (
    <section data-testid="deploy-operator-coach" style={panel}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <h2 style={h2}>What to do here</h2>
        <button type="button" data-testid="deploy-help-open" onClick={onHelp}
          title="Open glossary and how-this-works"
          style={{
            borderRadius: RADIUS.pill, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2],
            color: TOKENS.text[0], padding: '4px 12px', fontSize: TYPE.sm, fontWeight: 700, cursor: 'pointer',
          }}>
          ? Help
        </button>
      </div>
      <p style={muted}>{recommend}</p>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
        <div style={job} data-testid="deploy-coach-job-a">
          <p style={jobTitle}>Job A · Approve a merge</p>
          <p style={muted}>Say yes to a change joining main. Same as Telegram Approve. Not live yet.</p>
          <ChipRow>
            {ready == null
              ? <Chip tone="warning">READY count not stated</Chip>
              : <Chip tone={ready > 0 ? 'success' : 'neutral'}>{ready} READY to Approve</Chip>}
            {open != null ? <Chip tone="neutral">{open} open PR{open === 1 ? '' : 's'}</Chip> : null}
          </ChipRow>
        </div>
        <div style={job} data-testid="deploy-coach-job-b">
          <p style={jobTitle}>Job B · Put on the site</p>
          <p style={muted}>
            Serving {serving?.short_sha ?? 'unknown'}
            {next ? ` · main ${next.short_sha}` : ' · main commit not stated'}
            {next?.is_serving ? ' · already serving main' : ahead != null ? ` · ${ahead} ahead` : ' · distance not stated'}
          </p>
          <ChipRow>
            {ahead == null
              // An unread next-release is not "matches main": that badge is the one that would hide a stuck deploy.
              ? <Chip tone="warning">main vs site not known</Chip>
              : stopEffective
                ? <Chip tone="danger">STOP blocks promote</Chip>
                : ahead > 0
                  ? <Chip tone={facts.ciOk ? 'info' : 'warning'}>{facts.ciOk ? 'Promote candidate' : 'Waiting on main CI'}</Chip>
                  : <Chip tone="success">Site matches main</Chip>}
          </ChipRow>
        </div>
      </div>
      <p style={{ ...muted, color: toneVars('warning').color }}>
        The row button labeled “Update branch” (Advanced only) is not Push Live — it only updates GitHub.
      </p>
    </section>
  )
}
