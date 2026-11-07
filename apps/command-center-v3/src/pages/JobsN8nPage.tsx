import { useCallback, useState, type CSSProperties } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import OpsDeskFrame from '../components/OpsDeskFrame'
import { IncidentsTab, JobsHistoryTab, JobsN8nStyles, N8nLanesTab } from '../components/JobsN8nViews'
import { SchedulerChecksTab } from '../components/SchedulerChecksViews'
import { useApi } from '../hooks/useApi'
import { RADIUS, TOKENS, TYPE, toneVars } from '../lib/designTokens'
import { JOBS_N8N_TABS, OPS_CONTROLS_PATH, resolveJobsN8nTab, tabLabel, type JobsN8nTab } from '../lib/jobsN8n'
import { opsApi, type OpsControlsState } from '../lib/opsControls'
import { JOB_CATALOG_PATH } from '../lib/jobCatalog'

const tabStyle = (on: boolean): CSSProperties => ({
  minHeight: 44, padding: '6px 14px', borderRadius: RADIUS.pill, fontSize: TYPE.base, cursor: 'pointer', whiteSpace: 'nowrap', flex: '0 0 auto',
  color: on ? TOKENS.info : TOKENS.text[1], border: `1px solid ${on ? TOKENS.info : TOKENS.border}`, background: on ? toneVars('info').bg : TOKENS.bg[1], fontWeight: on ? 600 : 400,
})

/** Ops › Jobs & n8n (design pages/jobs v002, operator-approved 2026-11-06). Read-only: six tabs over existing GETs.
 *  `?tab=needs|quality|all|checks|n8n|incidents|fixes` (quality = run-quality grades, design v003 approved 2026-11-06) (checks = scheduler checks merged from Coordination › Automation, 2026-11-06); job detail `?history=<lane>`, lane detail `?lane=<lane>` (full-screen sheets). */
export default function JobsN8nPage() {
  const [params, setParams] = useSearchParams()
  const tab = resolveJobsN8nTab(params.get('tab'))
  const [counts, setCounts] = useState<Partial<Record<JobsN8nTab, number>>>({})
  const onTotal = useCallback((t: string, total: number) => setCounts(c => (c[t as JobsN8nTab] === total ? c : { ...c, [t]: total })), [])
  // Lane rows feed the n8n tab; polled only while that tab is open (its count shows once it has been read).
  const controls = useApi<OpsControlsState>(opsApi.statePath, 60_000, { enabled: tab === 'n8n' })
  const laneCount = controls.data?.n8n?.rows ? controls.data.n8n.rows.length : counts.n8n
  const pick = (t: JobsN8nTab) => {
    const next = new URLSearchParams()
    if (t !== 'needs') next.set('tab', t)
    setParams(next)
  }
  return <main style={{ padding: 'clamp(12px, 3vw, 20px)', background: TOKENS.bg[0], minWidth: 0 }}>
    <OpsDeskFrame page="jobsN8n">
      <JobsN8nStyles />
      <div style={{ display: 'grid', gap: 12, minWidth: 0 }} data-testid="jobs-n8n-page">
        <nav role="tablist" aria-label="Jobs & n8n views" style={{ display: 'flex', gap: 6, overflowX: 'auto', paddingBottom: 4, minWidth: 0 }}>
          {JOBS_N8N_TABS.map(([k, label]) => <button key={k} type="button" role="tab" aria-selected={k === tab} data-testid={`jobs-n8n-tab-${k}`}
            onClick={() => pick(k)} style={tabStyle(k === tab)}>{tabLabel(label, k === 'n8n' ? laneCount : counts[k])}</button>)}
        </nav>
        <Link to={JOB_CATALOG_PATH} data-testid="jobs-n8n-catalog-link" style={{ minHeight: 44, display: 'flex', alignItems: 'center', color: TOKENS.info, fontSize: TYPE.base, textDecoration: 'none' }}>Browse every job by category and what it does → Job catalog</Link>
        <div role="tabpanel" style={{ minWidth: 0 }}>
          {(tab === 'needs' || tab === 'quality' || tab === 'all' || tab === 'fixes') && <JobsHistoryTab key={tab} tab={tab} onTotal={onTotal} />}
          {tab === 'checks' && <SchedulerChecksTab onTotal={onTotal} />}
          {tab === 'n8n' && <N8nLanesTab state={controls.data ?? null} loading={controls.loading} error={controls.error ?? null} />}
          {tab === 'incidents' && <IncidentsTab />}
        </div>
        <p data-testid="jobs-n8n-readonly-note" style={{ color: TOKENS.text[2], fontSize: TYPE.sm, margin: 0 }}>
          Read-only page. No Run, Retry or Pause buttons here; those stay in <Link to={OPS_CONTROLS_PATH} style={{ color: TOKENS.info }}>Ops Controls</Link>.
        </p>
      </div>
    </OpsDeskFrame>
  </main>
}
