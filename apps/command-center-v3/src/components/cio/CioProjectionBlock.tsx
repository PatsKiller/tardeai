import type { ReactNode } from 'react'
import { RADIUS } from '../../lib/designTokens'
import { loadLine, projectionFacts, projectionLabels, projectionRows } from '../../lib/cioProjection'

/** One read-only CIO projection block.
 *
 * Shows the block's own schema, state labels and clocks verbatim (or
 * NOT_IN_PAYLOAD), a few scalar facts and the first rows of a named list.
 * Never infers a state; never spins forever.
 */
export default function CioProjectionBlock({
  title, block, rows, rowsLabel, testId, loading = false, error = null, note, children,
}: {
  title: string
  block: unknown
  rows?: unknown
  rowsLabel?: string
  testId: string
  loading?: boolean
  error?: string | null
  note?: ReactNode
  children?: ReactNode
}) {
  const hasData = block !== undefined && block !== null
  const status = loadLine({ loading, error, hasData })
  const labels = projectionLabels(block)
  const facts = projectionFacts(block)
  const lines = projectionRows(rows)
  return (
    <section data-testid={testId} style={{ border: '1px solid var(--border-subtle)', borderRadius: RADIUS.sm, padding: '8px 10px', background: 'var(--bg1)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text1)' }}>{title}</span>
        <span style={{ fontSize: 10, color: 'var(--text3)', fontFamily: 'var(--mono)' }} data-testid={`${testId}-schema`}>{labels.schema}</span>
      </div>
      {status && <div style={{ fontSize: 11, color: error ? 'var(--amber)' : 'var(--text3)', marginTop: 4 }} data-testid={`${testId}-status`}>{status}</div>}
      {hasData && (
        <>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }} data-testid={`${testId}-labels`}>
            {labels.ok === false && <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)' }}>ok=false{labels.error ? ` · ${labels.error}` : ''}</span>}
            {labels.states.length === 0 && <span style={{ fontSize: 10, color: 'var(--text3)' }}>state NOT_IN_PAYLOAD</span>}
            {labels.states.map(([k, v]) => (
              <span key={k} style={{ fontSize: 10, fontWeight: 700, color: 'var(--text2)', border: '1px solid var(--border)', borderRadius: RADIUS.pill, padding: '0 6px' }}>{k} {v}</span>
            ))}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }} data-testid={`${testId}-clocks`}>
            {labels.clocks.length === 0 ? 'clock NOT_IN_PAYLOAD' : labels.clocks.map(([k, v]) => `${k} ${v.replace('T', ' ').slice(0, 19)}`).join(' · ')}
          </div>
          {facts.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '2px 12px', marginTop: 6 }}>
              {facts.map(([k, v]) => (
                <div key={k} style={{ fontSize: 11, color: 'var(--text2)', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  <span style={{ color: 'var(--text3)' }}>{k}</span> {v}
                </div>
              ))}
            </div>
          )}
          {lines.length > 0 && (
            <div style={{ marginTop: 6 }}>
              {rowsLabel && <div style={{ fontSize: 10, color: 'var(--text3)' }}>{rowsLabel}</div>}
              <ul style={{ margin: '2px 0 0 16px', padding: 0, fontSize: 11, color: 'var(--text2)' }}>
                {lines.map((line, i) => <li key={`${i}-${line.slice(0, 24)}`}>{line}</li>)}
              </ul>
            </div>
          )}
          {children}
        </>
      )}
      {note && <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>{note}</div>}
    </section>
  )
}

/** Collapsible group wrapper (closed by default; children mount only when open). */
export function CioProjectionGroup({ title, testId, open, onToggle, children, note }: {
  title: string
  testId: string
  open: boolean
  onToggle: (open: boolean) => void
  children: ReactNode
  note?: ReactNode
}) {
  return (
    <details
      data-testid={testId}
      open={open}
      onToggle={(e) => onToggle((e.currentTarget as HTMLDetailsElement).open)}
      style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: '8px 12px', background: 'var(--bg2)', marginTop: 16 }}
    >
      <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 800, color: 'var(--text1)', letterSpacing: '.3px' }}>{title}</summary>
      {note && <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 6 }}>{note}</div>}
      {open && <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>{children}</div>}
    </details>
  )
}
