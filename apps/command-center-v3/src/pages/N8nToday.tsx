// What n8n did today (operator 2026-10-16: "how do i know whats n8n did"). Read-only view of
// GET /api/v2/coordination/n8n-today (scripts/lib/data_broker/n8n_today.py): runs by state (live / dry run),
// failures with reason, lock skips, heals and diagnoses, lanes cut over today. Receipts only.
import type { CSSProperties } from 'react'
import { useApi } from '../hooks/useApi'
import { Chip, ChipRow } from '../components/primitives'
import { RADIUS, TOKENS, TYPE, FONT } from '../lib/designTokens'

import { projectN8nToday, displayCount, type N8nTodayPayload } from '../lib/n8nTodayProjection'
export type { N8nTodayPayload } from '../lib/n8nTodayProjection'

const panel: CSSProperties = { background: TOKENS.bg[1], border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.md, padding: 14, minWidth: 0 }
const cell: CSSProperties = { padding: '6px 6px', fontSize: TYPE.sm, color: TOKENS.text[1], verticalAlign: 'top', textAlign: 'left' }
const mono: CSSProperties = { ...cell, fontFamily: FONT.mono }
const h2: CSSProperties = { margin: '0 0 8px', fontSize: TYPE.base, color: TOKENS.text[0] }
const muted: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[2] }
const s = (v: unknown) => (v === null || v === undefined || v === '' ? '—' : String(v))
const etTime = (v: unknown) => {
  const t = Date.parse(String(v ?? ''))
  if (!Number.isFinite(t)) return s(v)
  return new Date(t).toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false }) + ' ET'
}

function Table({ label, heads, rows, emptyLabel }: { label: string; heads: string[]; rows: Array<Array<unknown>>; emptyLabel: string }) {
  return <div style={{ overflowX: 'auto' }}>
    <table aria-label={label} style={{ width: '100%', borderCollapse: 'collapse' }}>
      <thead><tr>{heads.map(h => <th key={h} style={{ ...cell, color: TOKENS.text[3], whiteSpace: 'nowrap' }}>{h}</th>)}</tr></thead>
      <tbody>
        {rows.map((r, i) => <tr key={i} style={{ borderTop: `1px solid ${TOKENS.borderSubtle}` }}>{r.map((c, j) => <td key={j} style={j === 0 ? cell : mono}>{s(c)}</td>)}</tr>)}
        {!rows.length ? <tr><td colSpan={heads.length} style={{ ...cell, color: TOKENS.text[2] }}>{emptyLabel}</td></tr> : null}
      </tbody>
    </table>
  </div>
}

export default function N8nToday({ active = true }: { active?: boolean }) {
  const api = useApi<N8nTodayPayload>('/api/v2/coordination/n8n-today', 60_000, { enabled: active })
  const model = projectN8nToday(api.data, { error: !!api.error, stale: api.stale })
  const d = model.data
  const live = model.available('runs') ? d?.runs?.by_mode_state?.live || {} : {}
  const dry = model.available('runs') ? d?.runs?.by_mode_state?.dry_run || {} : {}
  const states = Array.from(new Set([...Object.keys(live), ...Object.keys(dry)])).sort()
  return <section data-testid="n8n-today" style={{ display: 'grid', gap: 12, minWidth: 0, maxWidth: '100%' }}>
    <div style={panel}>
      <h1 style={{ margin: 0, fontSize: TYPE.lg, color: TOKENS.text[0] }}>What n8n did today</h1>
      <p style={muted}>Executor receipts, relay log and failure diagnoses for {s(d?.day)} (ET). Read-only; messages sent by an n8n run end with “· via n8n &lt;lane&gt; &lt;HH:MM&gt;”.</p>
      <ChipRow>
        <Chip tone={api.error ? 'warning' : 'neutral'}>{api.loading && !d ? 'Loading' : model.status}</Chip>
        <Chip tone="neutral">Observed {etTime(d?.as_of)}</Chip>
        <Chip tone="neutral">live runs {displayCount(model.counts.live)}</Chip>
        <Chip tone="neutral">dry runs {displayCount(model.counts.dry)}</Chip>
        <Chip tone={(d?.failures_total || 0) > 0 ? 'danger' : 'neutral'}>failures {displayCount(model.counts.failures)}</Chip>
        <Chip tone={(d?.lock_skips?.length || 0) > 0 ? 'warning' : 'neutral'}>lock-skipped lanes {displayCount(model.counts.lockSkippedLanes)}</Chip>
        <Chip tone="neutral">recovery actions {displayCount(model.counts.recoveryActions)}</Chip>
        <Chip tone="neutral">diagnoses {displayCount(model.counts.diagnoses)}</Chip>
        <Chip tone="neutral">reported cutovers {displayCount(model.counts.cutovers)}</Chip>
      </ChipRow>
      <p style={muted}>{model.coverageLabel}</p>
      <p style={muted}>Last good observation age: {model.lastGoodAgeSeconds == null ? 'UNAVAILABLE' : `${model.lastGoodAgeSeconds}s`}. Source availability is separate from business health.</p>
      {api.error ? <p role="alert" style={muted}>n8n receipts unavailable. No counts are reported.</p> : null}
    </div>
    <div style={panel}><h2 style={h2}>Runs by state</h2>
      <Table emptyLabel={model.empty('runs')} label="n8n runs by state" heads={['State', 'Live', 'Dry run']} rows={states.map(st => [st, live[st] ?? 0, dry[st] ?? 0])} />
    </div>
    <div style={panel}><h2 style={h2}>Failures</h2>
      <p style={muted}>Showing {d?.failures?.length ?? 0} failure details; observed total {displayCount(model.counts.failures)}{d?.failures_truncated ? ' (detail list limited)' : ''}.</p>
      <Table emptyLabel={model.empty('runs')} label="n8n failures" heads={['Lane', 'Mode', 'Slot', 'State', 'Reason', 'Exit']}
        rows={(d?.failures || []).map(f => [f.lane, f.mode, f.slot, f.state, f.reason, f.exit_code])} />
    </div>
    <div style={panel}><h2 style={h2}>Lock skips</h2>
      <p style={muted}>RUN_SKIPPED_LOCK: another run (often a cron line on the same lock) held the lane's lock.</p>
      <Table emptyLabel={model.empty('runs')} label="n8n lock skips" heads={['Lane', 'Mode', 'Skips']} rows={(d?.lock_skips || []).map(r => [r.lane, r.mode, r.count])} />
    </div>
    <div style={panel}><h2 style={h2}>Recovery requests and diagnoses</h2>
      <p style={muted}>An action or remediation request does not establish recovered business output.</p>
      <Table emptyLabel={model.empty('diagnoses')} label="n8n heals" heads={['Lane', 'At', 'Decision', 'Remediation run', 'Outcome']}
        rows={(d?.heals || []).map(r => [r.lane, etTime(r.at), r.decision, r.remediation_run_id, r.outcome])} />
      <div style={{ height: 10 }} />
      <Table emptyLabel={model.empty('diagnoses')} label="n8n diagnoses by lane" heads={['Lane', 'Diagnoses']} rows={Object.entries(d?.diagnoses?.by_lane || {}).map(([k, v]) => [k, v])} />
      <div style={{ height: 10 }} />
      <Table emptyLabel={model.empty('relay')} label="n8n workflow errors" heads={['Workflow', 'At', 'Node', 'Execution']}
        rows={(d?.relay?.workflow_errors || []).map(r => [r.workflow_id, etTime(r.at), r.node, r.execution_id])} />
    </div>
    <div style={panel}><h2 style={h2}>Reported cutover receipts</h2>
      <Table emptyLabel={model.empty('cutovers')} label="n8n cutovers today" heads={['Lane', 'At', 'Evidence']}
        rows={(d?.cutovers_today || []).map(r => [r.lane, r.at, r.source])} />
      {d?.note ? <p style={muted}>{d.note}</p> : null}
    </div>
  </section>
}
