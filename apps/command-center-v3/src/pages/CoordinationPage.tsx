// Coordination — what is waiting, in progress, written, consumed or refused in the n8n
// coordination ledger (GET /api/v2/coordination/events). Read-only. 2026-10-07 roadmap Phase 1.
import { useMemo, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow, SortHeader, useSort } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT } from '../lib/designTokens'
import { projectCoordination, type CoordinationPayload, type CoordinationRow } from '../lib/coordinationEvents'

const panel: CSSProperties = {
  background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14,
}
const label: CSSProperties = {
  fontSize: TYPE.xs, color: TOKENS.text[3], textTransform: 'uppercase', letterSpacing: 0.5, fontWeight: 750,
}
const cell: CSSProperties = { padding: '5px 6px', fontSize: TYPE.base, color: TOKENS.text[1], verticalAlign: 'top' }
const mono: CSSProperties = { ...cell, fontFamily: FONT.mono, fontSize: TYPE.sm }

const PHASES: Array<[CoordinationRow['phase'], string]> = [
  ['waiting', 'waiting'], ['in progress', 'in progress'], ['artifact', 'artifact written'],
  ['consumed', 'consumed'], ['refused', 'refused'], ['failed', 'failed'],
]

function getter(row: CoordinationRow, key: string): unknown {
  switch (key) {
    case 'recordedAt': return row.recordedAt
    case 'age': return row.ageMinutes
    default: return (row as unknown as Record<string, unknown>)[key]
  }
}

export default function CoordinationPage() {
  const { data, loading, error, transport, stale } = useApi<CoordinationPayload>('/api/v2/coordination/events?limit=200', 30_000)
  const model = useMemo(() => projectCoordination(loading && !data ? null : data, { transport, stale }), [data, loading, transport, stale])
  const { rows, sort, toggle } = useSort(model.rows, { key: 'recordedAt', dir: 'desc' }, getter)
  return (
    <div data-testid="coordination-page" style={{ display: 'grid', gap: 12 }}>
      <div style={panel}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>Coordination</div>
          <div style={label}>what is waiting · ledger written by the gateway · n8n and the dispatcher only coordinate</div>
        </div>
        <ChipRow style={{ marginTop: 8 }}>
          <Chip tone={model.statusTone} title="projection status">{model.statusLabel}</Chip>
          <Chip tone={model.asOf ? 'neutral' : 'warning'} title="projection clock">{model.asOfLabel}</Chip>
          {model.transportLabel ? <Chip tone="warning" title="transport">{model.transportLabel}</Chip> : null}
          {PHASES.map(([phase, text]) => (
            <Chip key={phase} tone={model.counts[phase] > 0 ? (phase === 'refused' || phase === 'failed' ? 'danger' : phase === 'consumed' ? 'success' : 'info') : 'neutral'} title={`${text} count`}>
              {text} {model.counts[phase]}
            </Chip>
          ))}
        </ChipRow>
        {model.note ? <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[2] }}>{model.note}</div> : null}
        {error ? <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[2] }}>read failed: {String(error)}</div> : null}
      </div>
      <div style={{ ...panel, overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <SortHeader sortKey="state" sort={sort} onToggle={toggle} firstDir="asc">state</SortHeader>
              <SortHeader sortKey="lane" sort={sort} onToggle={toggle} firstDir="asc">lane</SortHeader>
              <SortHeader sortKey="eventId" sort={sort} onToggle={toggle} firstDir="asc">event</SortHeader>
              <SortHeader sortKey="reason" sort={sort} onToggle={toggle} firstDir="asc">reason</SortHeader>
              <SortHeader sortKey="artifact" sort={sort} onToggle={toggle} firstDir="asc">artifact</SortHeader>
              <SortHeader sortKey="consumer" sort={sort} onToggle={toggle} firstDir="asc">consumer</SortHeader>
              <SortHeader sortKey="recordedAt" sort={sort} onToggle={toggle}>recorded</SortHeader>
              <SortHeader sortKey="age" sort={sort} onToggle={toggle} align="right">age (min)</SortHeader>
              <SortHeader sortKey="originSha" sort={sort} onToggle={toggle} firstDir="asc">origin</SortHeader>
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.key} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                <td style={cell}><Chip tone={r.tone} title={r.durable ? 'durable (ledger commit returned)' : 'not durable'}>{r.state}</Chip></td>
                <td style={cell}>{r.lane}</td>
                <td style={mono}>{r.eventId}</td>
                <td style={cell}>{r.reason}</td>
                <td style={mono}>{r.artifact}</td>
                <td style={cell}>{r.consumer}</td>
                <td style={mono}>{r.recordedAt ?? 'UNDATED'}</td>
                <td style={{ ...mono, textAlign: 'right' }}>{r.ageMinutes ?? ''}</td>
                <td style={mono}>{r.originSha}</td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr><td colSpan={9} style={{ ...cell, color: TOKENS.text[3] }}>
                {model.status === 'NO_LEDGER' ? 'no ledger yet: the coordination gateway has not written anything here' : model.status === 'UNAVAILABLE' ? 'projection unavailable' : 'nothing is waiting'}
              </td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  )
}
