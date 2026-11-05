// One release-history card, in the operator's words (FQ-069 + FQ-070), extracted from the page so a test can RENDER it.
//
// The card used to be inline JSX in ReleasesSchedules.tsx, and its boundary test could only grep the page's source. The
// cloud review of 2026-11-05 proved that weakness: against an entirely commented-out copy of the page the test still
// reported 8 passed, because a comment contains the same strings as code. Rendering is the only thing that establishes the
// card actually prints these things, so the card lives in its own module and releaseHistory.boundary.test.mjs renders it.
//
// What must hold: the purpose and the verdict label are visible; the hashes, the SHA basis, the receipt and the raw reason
// are inside the disclosure and nowhere else; nothing on the card is nowrap.
import type { CSSProperties, ReactNode } from 'react'
import { Chip } from '../components/primitives'
import { FONT, RADIUS, TOKENS, TYPE, type Tone } from './designTokens'
import { releaseRowModel } from './releaseRow'
import type { ReleaseRow } from './releasesSchedules'

const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2], margin: 0 }
const mono: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm }

function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <Chip tone={tone} variant="solid">{children}</Chip>
}

export function ReleaseHistoryCard({ r, when }: { r: ReleaseRow; when: string }) {
  const m = releaseRowModel(r, when)
  return (
    <div data-testid="rs-history-row" style={{ display: 'grid', gap: 4, padding: 10, minWidth: 0,
      background: TOKENS.bg[2], border: `1px solid ${TOKENS.borderSubtle}`, borderRadius: RADIUS.sm }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <span data-testid="rs-release-purpose" style={{ fontSize: TYPE.base, fontWeight: 800, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{m.purpose}</span>
        <Pill tone={m.verdict.tone}>{m.verdict.label}</Pill>
      </div>
      <span style={{ ...muted, overflowWrap: 'anywhere' }}>{m.when} · {m.changes}</span>
      {m.blocker ? <span style={{ fontSize: TYPE.sm, color: TOKENS.text[1], overflowWrap: 'anywhere' }}>{m.blocker}</span> : null}
      <span style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>{m.nextAction}</span>
      <details data-testid="rs-release-diagnostics" style={{ minWidth: 0 }}>
        <summary style={{ cursor: 'pointer', fontSize: TYPE.xs, color: TOKENS.text[2], minHeight: 44, display: 'flex', alignItems: 'center' }}>Diagnostics</summary>
        <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(88px, auto) 1fr', gap: '2px 8px', margin: '6px 0 0' }}>
          {m.diagnostics.map(d => [<dt key={`${d.label}-k`} style={{ fontSize: TYPE.xs, color: TOKENS.text[2], fontWeight: 800 }}>{d.label}</dt>,
            <dd key={`${d.label}-v`} style={{ ...mono, margin: 0, color: TOKENS.text[1], overflowWrap: 'anywhere' }}>{d.value}</dd>])}
        </dl>
      </details>
    </div>
  )
}
