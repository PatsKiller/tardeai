// Coordination — what is waiting, in progress, written, consumed or refused in the n8n
// coordination ledger (GET /api/v2/coordination/events). Read-only. 2026-10-07 roadmap Phase 1.
import { useMemo, type CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow, SortHeader, useSort } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT } from '../lib/designTokens'
import { projectCoordination, type CoordinationPayload, type CoordinationRow } from '../lib/coordinationEvents'
import { projectOutbox, type OutboxPayload } from '../lib/outboxProjection'
import { projectApprovalBoard, type ApprovalBoardPayload } from '../lib/approvalBoard'

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
  const outboxApi = useApi<OutboxPayload>('/api/v2/coordination/outbox?hours=24', 60_000)
  const outbox = useMemo(() => projectOutbox(outboxApi.loading && !outboxApi.data ? null : outboxApi.data), [outboxApi.data, outboxApi.loading])
  const approvalsApi = useApi<ApprovalBoardPayload>('/api/v2/coordination/approvals', 60_000)
  const approvals = useMemo(() => projectApprovalBoard(approvalsApi.loading && !approvalsApi.data ? null : approvalsApi.data), [approvalsApi.data, approvalsApi.loading])
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
      <div style={panel} data-testid="coordination-outbox">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>Outbox</div>
          <div style={label}>what the senders did · sent / suppressed / recorded / withdrawn · n8n never sends</div>
        </div>
        <ChipRow style={{ marginTop: 8 }}>
          <Chip tone={outbox.statusTone} title="outbox projection status">{outbox.statusLabel}</Chip>
          <Chip tone="neutral" title="window">{outbox.windowLabel}</Chip>
          {outbox.counts.map(c => (
            <Chip key={`${c.outbox}:${c.state}`} tone={c.tone} title={`${c.outbox} ${c.state}`}>{c.outbox.replace('_outbox', '')} {c.state} {c.n}</Chip>
          ))}
        </ChipRow>
        {outbox.note ? <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[2] }}>{outbox.note}</div> : null}
        <div style={{ overflowX: 'auto', marginTop: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>state</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>outbox</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>channel</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>subject</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>reason</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>created</th>
                <th style={{ ...label, textAlign: 'right', padding: '5px 6px' }}>age (min)</th>
              </tr>
            </thead>
            <tbody>
              {outbox.rows.slice(0, 100).map(r => (
                <tr key={r.key} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                  <td style={cell}><Chip tone={r.tone}>{r.state}</Chip></td>
                  <td style={mono}>{r.outbox.replace('_outbox', '')}</td>
                  <td style={cell}>{r.channel}</td>
                  <td style={mono}>{r.subject}</td>
                  <td style={cell}>{r.reason}</td>
                  <td style={mono}>{r.createdAt ?? 'UNDATED'}</td>
                  <td style={{ ...mono, textAlign: 'right' }}>{r.ageMinutes ?? ''}</td>
                </tr>
              ))}
              {outbox.rows.length === 0 ? (
                <tr><td colSpan={7} style={{ ...cell, color: TOKENS.text[3] }}>
                  {outbox.status === 'OK' ? 'nothing sent, suppressed or withdrawn in the window' : 'outbox projection unavailable'}
                </td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
      <div style={panel} data-testid="coordination-approvals">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>Approvals</div>
          <div style={label}>open packages and active grants with time to expiry · the ledgers decide, this page only shows</div>
        </div>
        <ChipRow style={{ marginTop: 8 }}>
          <Chip tone={approvals.statusTone} title="approval board status">{approvals.statusLabel}</Chip>
          <Chip tone="neutral" title="board clock">{approvals.asOfLabel}</Chip>
          <Chip tone={approvals.expiringCount > 0 ? 'danger' : 'neutral'} title="rows inside their expiry warning window">expiring {approvals.expiringCount}</Chip>
          {approvals.counts.map(c => (
            <Chip key={`${c.kind}:${c.state}`} tone={c.tone} title={`${c.kind} ${c.state}`}>{c.kind} {c.state} {c.n}</Chip>
          ))}
        </ChipRow>
        {approvals.sourceNotes.length > 0 ? <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[2] }}>{approvals.sourceNotes.join(' · ')}</div> : null}
        <div style={{ overflowX: 'auto', marginTop: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>state</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>kind</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>id</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>scope</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>expiry</th>
                <th style={{ ...label, textAlign: 'right', padding: '5px 6px' }}>uses left</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>items</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>reason</th>
              </tr>
            </thead>
            <tbody>
              {approvals.rows.slice(0, 100).map(r => (
                <tr key={r.key} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                  <td style={cell}><Chip tone={r.tone}>{r.state}</Chip></td>
                  <td style={mono}>{r.kind}</td>
                  <td style={mono}>{r.id}</td>
                  <td style={cell}>{r.scope}</td>
                  <td style={{ ...mono, color: r.expiring ? TOKENS.text[0] : TOKENS.text[1] }}>{r.ttlLabel}</td>
                  <td style={{ ...mono, textAlign: 'right' }}>{r.usesLeft ?? ''}</td>
                  <td style={cell}>{r.pendingLabel}</td>
                  <td style={cell}>{r.reason}</td>
                </tr>
              ))}
              {approvals.rows.length === 0 ? (
                <tr><td colSpan={8} style={{ ...cell, color: TOKENS.text[3] }}>
                  {approvals.status === 'OK' ? 'no open packages and no active grants' : 'approval board unavailable'}
                </td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
