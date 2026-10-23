// Coordination — what is waiting, in progress, written, consumed or refused in the n8n
// coordination ledger (GET /api/v2/coordination/events). Read-only. 2026-10-07 roadmap Phase 1.
import { useMemo, useState, type CSSProperties } from 'react'
import SchedulerOperations from './SchedulerOperations'
import N8nToday from './N8nToday'
import ReleaseTrainTab from './ReleaseTrainTab'
import AgentClaimsPanel from './AgentClaimsPanel'
import WorkBoardPanel from './WorkBoardPanel'
import { useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { projectionReadPath } from '../lib/projectionReadProtocol'
import { Chip, ChipRow, SortHeader, useSort } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT, toneVars } from '../lib/designTokens'
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

// Tabs: the events ledger (events + outbox + approvals), the n8n migration board (stream G, 2026-10-08) and the
// release train (Release Train v2, 2026-10-21: queue, trains, history, census, STOP RELEASES) and the agent claim board
// (2026-10-22: who's working on what — Claude, Codex, Cursor sessions and the files each has claimed).
const TABS = ['operations', 'today', 'events', 'migration', 'release', 'agents', 'work'] as const
type CoordinationTab = (typeof TABS)[number]
const TAB_LABEL: Record<CoordinationTab, string> = { operations: 'Automation', today: 'n8n today', events: 'Events', migration: 'Migration board', release: 'Release train', agents: "Who's working", work: 'Work board' }
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
  const { data, loading, error, transport, stale } = useApi<CoordinationPayload>(projectionReadPath('events'), 30_000)
  const runsApi = useApi<{ schema?: string; status?: string; as_of?: string; items?: Array<Record<string, unknown>>; count?: number | null; total_count?: number | null; coverage?: { scope?: string; since?: string | null; through?: string | null; items_truncated?: boolean }; note?: string }>(
    projectionReadPath('runs'),
    60_000,
  )
  const [laneFilter, setLaneFilter] = useState<string | null>(null)
  const model = useMemo(
    () => projectCoordination(loading && !data ? null : data, { transport, stale, error: !!error, laneFilter }),
    [data, loading, transport, stale, error, laneFilter],
  )
  const runsV2 = runsApi.data?.schema === 'N8nCoordinationRunsProjection@v2'
  const runsKnown = !runsApi.data?.schema || ['N8nCoordinationRunsProjection@v1', 'N8nCoordinationRunsProjection@v2'].includes(runsApi.data.schema)
  const runRows = useMemo(() => {
    if (!runsKnown) return []
    const items = Array.isArray(runsApi.data?.items) ? runsApi.data!.items! : []
    const prefer = new Set(['n8n-research-intake-consumer', 'n8n-incident-fanin'])
    return [...items].sort((a, b) => {
      const ap = prefer.has(String(a.lane_id || '')) ? 0 : 1
      const bp = prefer.has(String(b.lane_id || '')) ? 0 : 1
      return ap - bp
    })
  }, [runsApi.data, runsKnown])
  const { rows, sort, toggle } = useSort(model.rows, { key: 'recordedAt', dir: 'desc' }, getter)
  const waveBChips = useMemo(() => {
    const lanes = model.waveBLanes.length ? model.waveBLanes : ['research-intake', 'watch-refresh', 'incident-fanin']
    return lanes.map(lane => ({ lane, n: model.countsAvailable ? model.laneCounts[lane] || 0 : null }))
  }, [model.waveBLanes, model.laneCounts, model.countsAvailable])
  const outboxApi = useApi<OutboxPayload>(projectionReadPath('outbox'), 60_000)
  const outbox = useMemo(() => projectOutbox(outboxApi.loading && !outboxApi.data ? null : outboxApi.data, { error: !!outboxApi.error, stale: outboxApi.stale }), [outboxApi.data, outboxApi.loading, outboxApi.error, outboxApi.stale])
  const approvalsApi = useApi<ApprovalBoardPayload>('/api/v2/coordination/approvals', 60_000)
  const approvals = useMemo(() => projectApprovalBoard(approvalsApi.loading && !approvalsApi.data ? null : approvalsApi.data), [approvalsApi.data, approvalsApi.loading])
  const [searchParams, setSearchParams] = useSearchParams()
  const [tab, setTab] = useState<CoordinationTab>(() => (searchParams.get('tab') === 'migration' ? 'migration' : searchParams.get('tab') === 'events' ? 'events' : searchParams.get('tab') === 'today' ? 'today' : searchParams.get('tab') === 'release' ? 'release' : searchParams.get('tab') === 'agents' ? 'agents' : searchParams.get('tab') === 'work' ? 'work' : 'operations'))
  const boardApi = useApi<MigrationBoardPayload>('/api/v2/coordination/migration-board', 60_000, { enabled: tab === 'migration' })
  const board = useMemo(() => projectMigrationBoard(boardApi.loading && !boardApi.data ? null : boardApi.data), [boardApi.data, boardApi.loading])
  const boardSort = useSort(board.rows, { key: 'tranche', dir: 'asc' }, boardGetter)
  const selectTab = (t: CoordinationTab) => {
    setTab(t)
    const next = new URLSearchParams(searchParams)
    if (t === 'operations') next.delete('tab'); else next.set('tab', t)
    setSearchParams(next, { replace: true })
  }
  return (
    <div data-testid="coordination-page" style={{ display: 'grid', gap: 12, minWidth: 0 }}>
      <nav style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }} aria-label="Coordination sections" role="tablist">
        {TABS.map(t => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => selectTab(t)} style={tabButton(tab === t)} data-testid={`coordination-tab-${t}`}>
            {TAB_LABEL[t]}
          </button>
        ))}
      </nav>
      {tab === 'operations' ? <SchedulerOperations /> : tab === 'today' ? <N8nToday /> : tab === 'agents' ? <AgentClaimsPanel /> : tab === 'work' ? <WorkBoardPanel /> : tab === 'release' ? (
        <div style={{ display: 'grid', gap: 12 }}>
          {/* Releases & schedules (2026-10-22): the full page (serving release, main HEAD, windows, queue, shipped history,
              release errors, n8n + cron timeline) is linked from here; the queue/trains/events views and STOP RELEASES stay on this tab. */}
          <div data-testid="coordination-releases-link" style={{ ...panel, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1] }}>Serving release, what releases next, train windows, shipped history, release errors and the next 3 hours of n8n and cron are on one page.</div>
            <a href="/v3/system/releases" style={{ fontSize: TYPE.sm, fontWeight: 750, color: TOKENS.primary, textDecoration: 'none' }}>Open Releases &amp; schedules →</a>
          </div>
          <ReleaseTrainTab />
        </div>
      ) : tab === 'migration' ? (
      <div style={panel} data-testid="coordination-migration-board">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>Migration board</div>
          <div style={label}>n8n as scheduler of record · shadow → canary → cutover → rollback · the registry and the receipts decide, this page only shows</div>
        </div>
        {board.stale ? (
          <div role="alert" data-testid="migration-board-stale" style={{ marginTop: 8, padding: '8px 10px', borderRadius: RADIUS.sm, fontSize: TYPE.sm, fontWeight: 700, color: toneVars('warning').color, background: toneVars('warning').bg, border: `1px solid ${toneVars('warning').border}` }}>
            {board.staleLabel} · counts below may not reflect the registry or receipts now
          </div>
        ) : null}
        {board.dispatchStages.length ? (
          <ChipRow style={{ marginTop: 8 }}>
            <span style={label}>dispatcher stages (lane registry)</span>
            {board.dispatchStages.map(s => <Chip key={s.stage} tone={s.n > 0 ? s.tone : 'neutral'} title={`lanes with scheduler.stage ${s.stage}`}>{s.stage} {s.n}</Chip>)}
            {board.computed ? <Chip tone={board.computed === 'LIVE' ? 'neutral' : 'warning'} title="LIVE = computed on this request; FILE_FALLBACK = last --write receipt">{board.computed.toLowerCase().replace('_', ' ')}</Chip> : null}
          </ChipRow>
        ) : null}
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
                  {board.status === 'NO_BOARD' ? 'no board: the live build failed and no --write receipt exists on this host' : board.status === 'UNAVAILABLE' ? 'migration board unavailable' : 'no program lanes'}
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
            <Chip key={phase} tone={(model.counts[phase] ?? 0) > 0 ? (phase === 'refused' || phase === 'failed' ? 'danger' : phase === 'consumed' ? 'success' : 'info') : 'neutral'} title={`${text} count`}>
              {text} {model.counts[phase] ?? 'UNAVAILABLE'}
            </Chip>
          ))}
        </ChipRow>
        <ChipRow style={{ marginTop: 8 }} data-testid="coordination-wave-b-lanes">
          <Chip
            tone={laneFilter == null ? 'info' : 'neutral'}
            title="show all lanes"
            onClick={() => setLaneFilter(null)}
          >all lanes</Chip>
          {waveBChips.map(({ lane, n }) => (
            <Chip
              key={lane}
              tone={laneFilter === lane ? 'info' : ((n ?? 0) > 0 ? 'success' : 'neutral')}
              title={`filter ${lane}; count follows the labelled aggregate or sample scope`}
              onClick={() => setLaneFilter(laneFilter === lane ? null : lane)}
            >{lane} {n ?? 'UNAVAILABLE'}</Chip>
          ))}
        </ChipRow>
        <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[2] }}>{model.coverageLabel} Last good observation age: {model.lastGoodAgeMinutes == null ? 'UNAVAILABLE' : `${model.lastGoodAgeMinutes} min`}.</div>
        {model.note ? <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[2] }}>{model.note}</div> : null}
        {error ? <div style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[2] }}>read failed: {String(error)}</div> : null}
      </div>
      {model.spotlights.length > 0 ? (
        <div style={panel} data-testid="coordination-spotlights">
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>Wave B receipts</div>
            <div style={label}>research-intake · watch-refresh · host consumer last.json · never invent success from n8n UI status</div>
          </div>
          <div style={{ overflowX: 'auto', marginTop: 8 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>lane</th>
                  <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>source</th>
                  <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>summary</th>
                  <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>as of</th>
                  <th style={{ ...label, textAlign: 'right', padding: '5px 6px' }}>age (min)</th>
                </tr>
              </thead>
              <tbody>
                {model.spotlights.map((s, i) => (
                  <tr key={`${s.lane}-${s.source}-${i}`} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                    <td style={cell}><Chip tone={s.tone}>{s.lane}</Chip></td>
                    <td style={mono}>{s.source}</td>
                    <td style={cell}>{s.summary}</td>
                    <td style={mono}>{s.asOf ?? 'UNDATED'}</td>
                    <td style={{ ...mono, textAlign: 'right' }}>{s.ageMinutes ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
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
              <tr key={r.key} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}`, background: waveBChips.some(w => w.lane === r.lane) ? TOKENS.bg[2] : undefined }}>
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
                {!model.countsAvailable || model.totalCount == null ? `${model.status}: coverage incomplete; no details returned` : laneFilter ? `No ${laneFilter} details in this page` : 'No rows in retained ledger coverage'}
              </td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
      <div style={panel} data-testid="coordination-runs">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>Lane runs</div>
          <div style={label}>executor RunReceipt rows · research-intake-consumer · incident-fanin · prove from ledger not n8n status</div>
        </div>
        <ChipRow style={{ marginTop: 8 }}>
          <Chip tone={runsApi.error || runsApi.stale || !runsV2 ? 'warning' : runsApi.data?.status === 'OK' ? 'info' : runsApi.data?.status === 'NO_LEDGER' ? 'warning' : 'neutral'}>
            {runsApi.error || !runsKnown ? 'UNAVAILABLE' : runsApi.stale ? 'STALE' : runsApi.data && !runsV2 ? 'LEGACY SAMPLE' : String(runsApi.data?.status || (runsApi.loading ? '…' : 'UNAVAILABLE'))}
          </Chip>
          <Chip tone="neutral">{runsApi.data?.as_of ? `projected ${runsApi.data.as_of}` : 'UNDATED'}</Chip>
          <Chip tone="neutral">details shown {runsApi.error ? 'UNAVAILABLE' : runRows.length}; all retained rows {runsApi.error || runsApi.stale || !runsV2 ? 'UNAVAILABLE' : runsApi.data?.total_count ?? 'UNAVAILABLE'}</Chip>
        </ChipRow>
        <p style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>All retained ledger rows; observed bounds {runsApi.data?.coverage?.since ?? 'UNAVAILABLE'} → {runsApi.data?.coverage?.through ?? 'UNAVAILABLE'}. Details limited to 40; no 24h filter. Execution success is separate from useful output.</p>
        <div style={{ overflowX: 'auto', marginTop: 8 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>state</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>lane</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>mode</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>run</th>
                <th style={{ ...label, textAlign: 'left', padding: '5px 6px' }}>finished</th>
              </tr>
            </thead>
            <tbody>
              {runRows.slice(0, 40).map(r => (
                <tr key={`run-${String(r.run_id)}`} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
                  <td style={cell}><Chip tone={String(r.state).includes('FAIL') ? 'danger' : 'neutral'}>{String(r.state || '')}</Chip></td>
                  <td style={cell}>{String(r.lane_id || '')}</td>
                  <td style={mono}>{runsV2 ? `${String(r.mode ?? 'UNKNOWN')} / requested ${String(r.requested_mode ?? 'UNKNOWN')}` : `requested ${String(r.mode ?? 'UNKNOWN')}; effective UNKNOWN (legacy)`}</td>
                  <td style={mono}>{String(r.run_id || '')}</td>
                  <td style={mono}>{String(r.finished_at || r.started_at || r.requested_at || 'UNDATED')}</td>
                </tr>
              ))}
              {runRows.length === 0 ? (
                <tr><td colSpan={5} style={{ ...cell, color: TOKENS.text[3] }}>
                  {runsApi.error || runsApi.stale || runsApi.data?.status !== 'OK' ? 'UNAVAILABLE: current run history unknown' : (runsApi.data?.note || 'No rows in retained ledger coverage')}
                </td></tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
      <div style={panel} data-testid="coordination-outbox">
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: TOKENS.text[0] }}>Outbox</div>
          <div style={label}>what the senders did · sent / suppressed / recorded / withdrawn · n8n never sends</div>
        </div>
        <ChipRow style={{ marginTop: 8 }}>
          <Chip tone={outbox.statusTone} title="outbox projection status">{outbox.statusLabel}</Chip>
          <Chip tone="neutral" title="window">{outbox.windowLabel}</Chip>
          <Chip tone="neutral">last good observation age {outbox.lastGoodAgeMinutes == null ? 'UNAVAILABLE' : `${outbox.lastGoodAgeMinutes} min`}</Chip>
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
                  {outbox.status === 'OK' ? 'No item details returned; see aggregate counts and coverage above' : `${outbox.status}: current outbox coverage unavailable`}
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
