// Coordination — what is waiting, in progress, written, consumed or refused in the n8n
// coordination ledger (GET /api/v2/coordination/events). Read-only. 2026-10-07 roadmap Phase 1.
import { useMemo, useState, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow, SortHeader, useSort } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT } from '../lib/designTokens'
import { projectCoordination, type CoordinationPayload, type CoordinationRow } from '../lib/coordinationEvents'
import { projectOutbox, type OutboxPayload } from '../lib/outboxProjection'
import { projectApprovalBoard, type ApprovalBoardPayload } from '../lib/approvalBoard'
import { projectMigrationBoard, type MigrationBoardPayload, type MigrationRow } from '../lib/migrationBoard'

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

// Tabs: the events ledger (events + outbox + approvals) and the n8n migration board (stream G, 2026-10-08).
const TABS = ['events', 'migration'] as const
type CoordinationTab = (typeof TABS)[number]
const TAB_LABEL: Record<CoordinationTab, string> = { events: 'Events', migration: 'Migration board' }
const tabButton = (active: boolean): CSSProperties => ({
  padding: '7px 14px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`,
  background: active ? TOKENS.bg[2] : TOKENS.bg[1], color: active ? TOKENS.text[0] : TOKENS.text[2],
  cursor: 'pointer', fontSize: TYPE.sm, fontWeight: active ? 750 : 500, letterSpacing: 0.4,
})

function boardGetter(row: MigrationRow, key: string): unknown {
  switch (key) {
    case 'signalAge': return row.signalAgeHours
    default: return (row as unknown as Record<string, unknown>)[key]
  }
}

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
  const [searchParams, setSearchParams] = useSearchParams()
  const [tab, setTab] = useState<CoordinationTab>(() => (searchParams.get('tab') === 'migration' ? 'migration' : 'events'))
  const boardApi = useApi<MigrationBoardPayload>('/api/v2/coordination/migration-board', 60_000, { enabled: tab === 'migration' })
  const board = useMemo(() => projectMigrationBoard(boardApi.loading && !boardApi.data ? null : boardApi.data), [boardApi.data, boardApi.loading])
  const boardSort = useSort(board.rows, { key: 'tranche', dir: 'asc' }, boardGetter)
  const selectTab = (t: CoordinationTab) => {
    setTab(t)
    const next = new URLSearchParams(searchParams)
    if (t === 'events') next.delete('tab'); else next.set('tab', t)
    setSearchParams(next, { replace: true })
  }
  return (
    <div data-testid="coordination-page" style={{ display: 'grid', gap: 12 }}>
      <nav style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }} aria-label="Coordination sections" role="tablist">
        {TABS.map(t => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => selectTab(t)} style={tabButton(tab === t)} data-testid={`coordination-tab-${t}`}>
            {TAB_LABEL[t]}
          </button>
        ))}
      </nav>
      {tab === 'migration' ? (
      <div style={panel} data-testid="coordination-migration-board">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>Migration board</div>
          <div style={label}>n8n as scheduler of record · shadow → canary → cutover → rollback · the registry and the receipts decide, this page only shows</div>
        </div>
        <ChipRow style={{ marginTop: 8 }}>
          <Chip tone={board.statusTone} title="board status">{board.statusLabel}</Chip>
          <Chip tone="neutral" title="board clock">{board.asOfLabel}</Chip>
          {board.byPhase.map(p => (
            <Chip key={p.phase} tone={p.n > 0 ? p.tone : 'neutral'} title={`${p.phase} count`}>{p.phase.toLowerCase().replace('_', ' ')} {p.n}</Chip>
          ))}
          <Chip tone={board.openRiskCount > 0 ? 'danger' : 'neutral'} title="open risk flags (RUN_FAILED after cutover, stale output signal, double scheduler)">risks {board.openRiskCount}</Chip>
          <Chip tone={board.noRegistryRow > 0 ? 'warning' : 'neutral'} title="program lanes without a lane_registry row yet">no registry row {board.noRegistryRow}</Chip>
          {board.tranches.map(t => (
            <Chip key={t.tranche} tone={t.tone} title={`${t.tranche}: ${t.cutOver}/${t.lanes} cut over, ${t.risks} risks`}>{t.tranche} {t.cutOver}/{t.lanes}</Chip>
          ))}
        </ChipRow>
        {board.note ? <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[2] }}>{board.note}</div> : null}
        {boardApi.error ? <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[2] }}>read failed: {String(boardApi.error)}</div> : null}
        <div style={{ overflowX: 'auto', marginTop: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <SortHeader sortKey="tranche" sort={boardSort.sort} onToggle={boardSort.toggle} firstDir="asc">tranche</SortHeader>
                <SortHeader sortKey="lane" sort={boardSort.sort} onToggle={boardSort.toggle} firstDir="asc">lane</SortHeader>
                <SortHeader sortKey="scheduler" sort={boardSort.sort} onToggle={boardSort.toggle} firstDir="asc">scheduler</SortHeader>
                <SortHeader sortKey="phase" sort={boardSort.sort} onToggle={boardSort.toggle} firstDir="asc">phase</SortHeader>
                <SortHeader sortKey="lastRun" sort={boardSort.sort} onToggle={boardSort.toggle} firstDir="asc">last run</SortHeader>
                <SortHeader sortKey="signalAge" sort={boardSort.sort} onToggle={boardSort.toggle} align="right">signal age</SortHeader>
                <SortHeader sortKey="readiness" sort={boardSort.sort} onToggle={boardSort.toggle} firstDir="asc">readiness</SortHeader>
                <SortHeader sortKey="rollbackReady" sort={boardSort.sort} onToggle={boardSort.toggle} firstDir="asc">rollback</SortHeader>
                <SortHeader sortKey="riskLabel" sort={boardSort.sort} onToggle={boardSort.toggle} firstDir="asc">risk</SortHeader>
              </tr>
            </thead>
            <tbody>
              {boardSort.rows.map(r => (
                <tr key={r.key} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                  <td style={mono}>{r.tranche}</td>
                  <td style={{ ...cell, color: r.registryRow ? TOKENS.text[1] : TOKENS.text[3] }} title={r.note || (r.registryRow ? '' : 'no lane_registry row yet')}>{r.lane}</td>
                  <td style={mono}>{r.scheduler}</td>
                  <td style={cell}><Chip tone={r.phaseTone}>{r.phase.toLowerCase().replace('_', ' ')}</Chip></td>
                  <td style={cell}>{r.lastRun === 'no run' ? <span style={{ color: TOKENS.text[3] }}>no run</span> : <Chip tone={r.lastRunTone}>{r.lastRun}</Chip>}</td>
                  <td style={{ ...mono, textAlign: 'right', color: r.signalStale ? TOKENS.text[0] : TOKENS.text[1] }}>{r.signalAgeLabel}</td>
                  <td style={cell}>{r.readiness ? <Chip tone={r.readinessTone}>{r.readiness}</Chip> : <span style={{ color: TOKENS.text[3] }}>—</span>}</td>
                  <td style={cell}>{r.rollbackReady ? <Chip tone="success">ready</Chip> : <span style={{ color: TOKENS.text[3] }}>—</span>}</td>
                  <td style={cell}>{r.risks.length > 0 ? r.risks.map(f => <Chip key={f} tone={f === 'NO_REGISTRY_ROW' ? 'warning' : 'danger'} style={{ marginRight: 4 }}>{f.toLowerCase().replace(/_/g, ' ')}</Chip>) : <span style={{ color: TOKENS.text[3] }}>—</span>}</td>
                </tr>
              ))}
              {boardSort.rows.length === 0 ? (
                <tr><td colSpan={9} style={{ ...cell, color: TOKENS.text[3] }}>
                  {board.status === 'NO_BOARD' ? 'no board yet: scripts/n8n_migration_board.py --write has not run on this host' : board.status === 'UNAVAILABLE' ? 'migration board unavailable' : 'no program lanes'}
                </td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
      ) : (<>
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
      </>)}
    </div>
  )
}
