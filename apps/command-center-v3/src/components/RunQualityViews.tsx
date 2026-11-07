import type { CSSProperties } from 'react'
import { FONT, RADIUS, TOKENS, TYPE, toneVars, type Tone } from '../lib/designTokens'
import { QUALITY_GRADES, checkRows, gradeChip, notAsDesigned, type RunQuality } from '../lib/runQuality'

// Ops › Jobs & n8n run quality (design pages/jobs v003, operator-approved 2026-11-06). Read-only views over the per-row
// `quality` block of /api/v2/jobs-history. "OK" is never shown for a dry run or a skip: the grade says what the run made.

const muted: CSSProperties = { color: TOKENS.text[2], fontSize: TYPE.sm, margin: 0 }
const wrap: CSSProperties = { overflowWrap: 'anywhere', minWidth: 0 }
const chip = (tone: Tone): CSSProperties => ({ display: 'inline-block', padding: '2px 8px', borderRadius: RADIUS.pill, fontSize: TYPE.sm, fontWeight: 600, color: toneVars(tone).color, background: toneVars(tone).bg, border: `1px solid ${toneVars(tone).border}`, whiteSpace: 'nowrap' })

/** "DEGRADED" chip plus the ⚠ not-as-designed chip. Nothing when the row carries no grade. */
export function QualityChips({ q }: { q: RunQuality | null | undefined }) {
  const g = gradeChip(q)
  if (!g) return null
  return <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
    <span style={chip(g.tone)} data-testid="quality-chip" title="Run quality: what the last run actually produced">{g.label}</span>
    {notAsDesigned(q) && <span style={chip('warning')} data-testid="quality-not-as-designed" title={(q?.design_issues ?? []).join('; ')}>⚠ Not as designed</span>}
  </span>
}

/** The card's one-line quality reason (skipped for GOOD, where the status line already says enough). */
export function QualityReason({ q }: { q: RunQuality | null | undefined }) {
  if (!q || q.grade === 'GOOD' || !q.headline) return null
  return <div data-testid="quality-reason" style={{ ...wrap, fontSize: TYPE.sm, color: TOKENS.text[1], background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: '6px 8px' }}>
    {q.headline}
    {notAsDesigned(q) && !!q.design_issues?.length && <><br />⚠ {q.design_issues[0]}</>}
  </div>
}

/** What the six grades mean, folded by default; the picked grade's definition is shown open. */
export function QualityLegend({ activeKey, notAsDesigned: offDesign }: { activeKey: string | null; notAsDesigned: number | null }) {
  const active = QUALITY_GRADES.find(g => g.key === activeKey)
  return <div style={{ display: 'grid', gap: 6, minWidth: 0 }} data-testid="quality-legend">
    {active && <p style={{ ...wrap, margin: 0, fontSize: TYPE.base }}><span style={chip(active.tone)}>{active.label}</span> {active.means}</p>}
    {offDesign != null && <p style={{ ...muted, ...wrap }}>⚠ {offDesign} {offDesign === 1 ? 'job is' : 'jobs are'} not as designed: the label disagrees with what ran (for example "fully moved" while a dry-run copy still fires, or two schedulers fire it).</p>}
    <details>
      <summary style={{ minHeight: 44, display: 'flex', alignItems: 'center', cursor: 'pointer', color: TOKENS.info, fontSize: TYPE.base }}>What the grades mean</summary>
      <dl style={{ display: 'grid', gap: 8, margin: 0 }}>
        {QUALITY_GRADES.map(g => <div key={g.key} style={{ display: 'grid', gap: 2 }}>
          <dt><span style={chip(g.tone)}>{g.label}</span></dt><dd style={{ ...wrap, margin: 0, fontSize: TYPE.sm, color: TOKENS.text[1] }}>{g.means}</dd>
        </div>)}
      </dl>
    </details>
  </div>
}

/** Detail-sheet block: grade, the status it replaces, plain reasons, design issues and the check list with values. */
export function QualityDetail({ q, statusLabel }: { q: RunQuality | null | undefined; statusLabel?: string | null }) {
  const g = gradeChip(q)
  if (!q || !g) return null
  const rows = checkRows(q)
  return <section aria-label="Run quality" data-testid="quality-detail" style={{ display: 'grid', gap: 10, padding: 12, border: `1px solid ${toneVars(g.tone).border}`, borderRadius: RADIUS.md, background: TOKENS.bg[1], minWidth: 0, maxWidth: 760 }}>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
      <strong style={{ fontSize: TYPE.md }}>Run quality</strong>
      <QualityChips q={q} />
      {statusLabel && <span style={muted}>run status said: {statusLabel}</span>}
    </div>
    {!!q.reasons?.length && <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4 }}>{q.reasons.map((r, i) => <li key={i} style={wrap}>{r}</li>)}</ul>}
    {notAsDesigned(q) && !!q.design_issues?.length && <div style={{ display: 'grid', gap: 4 }}>
      <span style={{ ...muted, color: toneVars('warning').color }}>⚠ Not as designed</span>
      <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 4 }}>{q.design_issues.map((r, i) => <li key={i} style={wrap}>{r}</li>)}</ul>
    </div>}
    {!!rows.length && <div role="table" aria-label="Quality checks" style={{ display: 'grid', gridTemplateColumns: 'auto minmax(0,1fr) minmax(0,auto)', gap: '4px 10px', fontSize: TYPE.base, alignItems: 'baseline' }}>
      {rows.map(r => <div role="row" key={r.key} style={{ display: 'contents' }}>
        <span role="cell" aria-label={r.mark === '✓' ? 'pass' : r.mark === '✕' ? 'fail' : 'not measured'} style={{ color: toneVars(r.tone).color, fontWeight: 700 }}>{r.mark}</span>
        <span role="cell" style={wrap}>{r.label}{r.detail && <span style={{ ...muted, display: 'block' }}>{r.detail}</span>}</span>
        <span role="cell" style={{ ...wrap, fontFamily: FONT.mono, fontSize: TYPE.sm, color: TOKENS.text[1], textAlign: 'right' }}>{r.value}</span>
      </div>)}
    </div>}
    {q.graded_run?.run_id && <p style={{ ...muted, ...wrap }}>Graded run: <span style={{ fontFamily: FONT.mono }}>{q.graded_run.run_id}</span>{q.graded_run.source ? ` · ${q.graded_run.source}` : ''}</p>}
  </section>
}
