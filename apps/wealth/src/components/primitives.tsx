// Shared v02 primitives: Tag, CueBadge, Panel, MetricGrid/Metric, TableWrap, Note, ActionCard.
// Markup and class names follow the v02 reference helpers (tag, panel, metrics, table, action) so the
// ported stylesheet applies unchanged. No data lives here; every number comes from a page's reader.
import type { ReactNode } from 'react'
import type { Cue } from '../contracts/cue'

export type Tone = '' | 'good' | 'warn' | 'bad' | 'purple'

export function Tag({ children, tone = '', title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return <span className={`tag ${tone}`.trim()} title={title}>{children}</span>
}

const CUE_TONE: Record<Cue['level'], Tone> = { GREEN: 'good', AMBER: 'warn', RED: 'bad', NEUTRAL: '' }
const CUE_GLYPH: Record<Cue['icon'], string> = { ok: '✓', caution: '!', alert: '✕', info: 'i', unassessed: '?' }

/** Colour is never the only carrier: text + icon + tooltip, always (cue contract). */
export function CueBadge({ cue }: { cue: Cue }) {
  return (
    <span className={`tag ${CUE_TONE[cue.level]}`.trim()} title={cue.tooltip} aria-label={`${cue.label}. ${cue.tooltip}`} data-cue={cue.level}>
      <span aria-hidden="true">{CUE_GLYPH[cue.icon]}</span>{cue.label}
    </span>
  )
}

export function Panel({ title, sub, right, children, flat }: { title: ReactNode; sub?: ReactNode; right?: ReactNode; children?: ReactNode; flat?: boolean }) {
  return (
    <section className={flat ? 'panel flat' : 'panel'}>
      <div className="panel-head"><div><h2>{title}</h2>{sub ? <p>{sub}</p> : null}</div>{right}</div>
      {children}
    </section>
  )
}

export function MetricGrid({ children }: { children: ReactNode }) {
  return <div className="metric-grid">{children}</div>
}

/**
 * One metric card. `series`, when given, draws the v02 spark from real points; with no series the
 * spark is omitted (the reference's spark path is illustrative and would imply a trend we do not have).
 */
export function Metric({ label, value, sub, tone = '', series, index = 0 }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: '' | 'pos' | 'neg' | 'gold'; series?: number[]; index?: number }) {
  return (
    <article className="metric">
      <div className="label">{label}</div>
      <div className={`big mono ${tone}`.trim()}>{value}</div>
      {sub ? <div className="sub">{sub}</div> : null}
      {series && series.length > 1 ? <Spark series={series} accent={index % 2 ? 'blue' : 'gold'} /> : null}
    </article>
  )
}

function Spark({ series, accent }: { series: number[]; accent: 'blue' | 'gold' }) {
  const lo = Math.min(...series), hi = Math.max(...series), span = hi - lo || 1
  const pts = series.map((v, i) => `${(i / (series.length - 1)) * 110} ${50 - ((v - lo) / span) * 50}`)
  const line = `M${pts.join(' ')}`
  const colour = accent === 'blue' ? 'var(--blue)' : 'var(--gold)'
  return (
    <svg className="spark" viewBox="0 0 110 50" aria-hidden="true">
      <path d={`${line}V50H0Z`} fill={colour} opacity=".1" />
      <path d={line} stroke={colour} fill="none" strokeWidth={2} />
    </svg>
  )
}

export function TableWrap({ heads, rows, className }: { heads: ReactNode[]; rows: ReactNode[][]; className?: string }) {
  return (
    <div className="table-wrap">
      <table className={className}>
        <thead><tr>{heads.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )
}

export function Note({ children, tone }: { children: ReactNode; tone?: 'blue' | 'bad' }) {
  return <div className={tone ? `note ${tone}` : 'note'}>{children}</div>
}

export function ActionCard({ title, desc, meta, tone = 'gold', cta }: { title: ReactNode; desc: ReactNode; meta?: ReactNode; tone?: string; cta?: ReactNode }) {
  return (
    <article className="action-card">
      <div className={`action-icon ${tone}`} aria-hidden="true">↗</div>
      <div className="action-body"><h3>{title}</h3><p>{desc}</p>{meta ? <div className="action-meta">{meta}</div> : null}</div>
      {cta}
    </article>
  )
}
