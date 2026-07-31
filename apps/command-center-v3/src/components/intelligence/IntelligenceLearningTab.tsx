import { Link } from 'react-router-dom'
import { useMemo } from 'react'
import { useApi } from '../../hooks/useApi'
import type { DrillContext } from '../DetailDrawer'
import { KPI, MiniBarRow, SectionHeader, dashboardCard } from './dashboardKit'

interface Props { onDrill: (ctx: DrillContext) => void }

const GREEN = 'var(--green)', AMBER = 'var(--amber)', RED = 'var(--red)', BLUE = 'var(--blue)'

function gateColor(score: number, total: number) {
  if (total === 0) return 'var(--text3)'
  const pct = score / total
  return pct >= 0.75 ? GREEN : pct >= 0.4 ? AMBER : RED
}

const DIM_LABEL: Record<string, string> = {
  scope: 'Scope discipline', research: 'Research quality', tagging: 'Tagging accuracy',
  efficiency: 'Resource efficiency', closed_loop: 'Closed-loop learning', autonomy: 'Autonomous operation',
}

const RESEARCH_GATE_LABEL: Record<string, string> = {
  external_error_rate: 'External error rate',
  proposals_with_prior_research: 'Proposals w/ prior research',
  s0_research_freshness: 'S0 research freshness',
}

function fmtGateValue(g: { value?: unknown; target?: string; pass?: boolean }) {
  const v = g?.value
  const target = g?.target ?? ''
  if (v == null) return target || '—'
  if (typeof v === 'number' && target.startsWith('<')) return `${v} (target ${target})`
  if (typeof v === 'number' && target.startsWith('>=')) return `${(v * 100).toFixed(1)}% (target ${target})`
  return `${String(v)} (target ${target})`
}

export default function IntelligenceLearningTab({ onDrill }: Props) {
  const { data: maturity, loading: mLoading, stale: mStale } = useApi<any>('/api/v2/hermes/maturity-dashboard', 300_000)
  const { data: scorecard, loading: sLoading } = useApi<any>('/api/v2/hermes/learning-scorecard', 300_000)
  const { data: recIntel } = useApi<any>('/api/v2/rec-intel/summary', 300_000)
  const { data: remediation, error: remError, stale: remStale } = useApi<any>('/api/v2/intelligence/remediation-summary', 120_000)

  const rem7 = remediation?.totals_7d ?? remediation?.data?.totals_7d
  const hermes7 = remediation?.hermes_research_7d ?? remediation?.data?.hermes_research_7d
  const remediationUnavailable = Boolean(remError) && !remediation
  const remediationDegraded = remediationUnavailable || remStale

  const gates = maturity?.maturity_gates ?? maturity?.data?.maturity_gates
  const dims = gates?.dimensions ?? {}
  const scores = gates?.scores ?? {}
  const fallbackResearchGates = remediation?.research_gates ?? remediation?.data?.research_gates
  const ms = scorecard?.maturity_score_by_subsystem ?? scorecard?.data?.maturity_score_by_subsystem

  const bySource = (recIntel?.by_source ?? recIntel?.data?.by_source ?? []) as any[]
  const sourcesWithSignal = bySource.filter(s => s.tickers > 0)
  const totalExecuted = bySource.reduce((a, s) => a + (s.executed ?? 0), 0)

  const gateBarRows = useMemo(() => {
    return Object.entries(dims).map(([key, gateSet]: any) => {
      const mergedGateSet = key === 'research' && fallbackResearchGates && Object.keys(fallbackResearchGates).length
        ? { ...gateSet, ...fallbackResearchGates }
        : gateSet
      const total = Object.keys(mergedGateSet).length
      const score = scores[key] ?? 0
      const pct = total ? Math.round((score / total) * 100) : 0
      return {
        label: DIM_LABEL[key] ?? key,
        value: pct,
        max: 100,
        color: gateColor(score, total),
        sub: `${score}/${total}`,
        key,
        gateSet: mergedGateSet,
        score,
        total,
      }
    })
  }, [dims, scores, fallbackResearchGates])

  const researchGates = gateBarRows.find(r => r.key === 'research')?.gateSet ?? fallbackResearchGates ?? {}
  const failingResearchGates = Object.entries(researchGates).filter(([, g]: any) => !g.pass)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <SectionHeader
        title="Learning & Autonomy"
        subtitle="What the pipeline has learned and how much runs unattended"
        accent={BLUE}
        right={
          <div style={{ display: 'flex', gap: 10, fontSize: 10 }}>
            <Link to="/hermes?tab=maturity" style={{ color: BLUE, fontWeight: 700, textDecoration: 'none' }}>Hermes Maturity →</Link>
            <Link to="/hermes?tab=closed-loop" style={{ color: BLUE, fontWeight: 700, textDecoration: 'none' }}>Closed Loop →</Link>
            <Link to="/rec-intel" style={{ color: BLUE, fontWeight: 700, textDecoration: 'none' }}>Rec Intelligence →</Link>
          </div>
        }
      />

      {ms && (
        <div style={{ ...dashboardCard, borderLeft: `4px solid ${GREEN}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase' }}>Overall maturity</div>
            <div style={{ fontSize: 28, fontWeight: 900, color: 'var(--text0)' }}>{ms.maturity_score?.toFixed(2)}<span style={{ fontSize: 12, color: 'var(--text3)' }}>/5 · {ms.tier}</span></div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>trend: {ms.trend ?? '—'}</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(90px, 1fr))', gap: 10 }}>
            {[['outcome yield', ms.outcome_yield], ['scope discipline', ms.scope_discipline], ['stop quality', ms.stop_quality], ['feedback loop', ms.feedback_loop], ['research actionability', ms.research_actionability]].map(([label, v]) => (
              <KPI key={label as string} label={label as string} value={typeof v === 'number' ? `${v.toFixed(0)}%` : '—'} color={(v as number) >= 80 ? GREEN : (v as number) >= 50 ? AMBER : RED} />
            ))}
          </div>
        </div>
      )}

      <div style={{ ...dashboardCard, borderLeft: `4px solid ${remediationDegraded ? AMBER : GREEN}`, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Automated remediation (7d)</div>
        {remediationDegraded && (
          <div style={{ fontSize: 10, color: AMBER, marginBottom: 8 }}>
            {remediationUnavailable ? 'Remediation unavailable — server busy or DB offline; retrying…' : 'Showing last-good remediation metrics — live refresh paused'}
          </div>
        )}
        {remediation?.error && (
          <div style={{ fontSize: 10, color: RED, marginBottom: 8 }}>{String(remediation.error).slice(0, 120)}</div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10 }}>
          <KPI label="Gaps enqueued" value={rem7?.gaps_enqueued ?? '—'} sub={`${remediation?.pending_gaps ?? '—'} pending`} color={(remediation?.pending_gaps ?? 0) > 0 ? AMBER : GREEN} />
          <KPI label="Items archived" value={rem7?.items_archived ?? '—'} sub="stale / ensemble BLOCK" color={BLUE} />
          <KPI label="Ensemble queued" value={rem7?.ensemble_queued ?? '—'} sub={`${remediation?.pending_ensemble_jobs ?? '—'} in flight`} color={BLUE} />
          <KPI label="Watch critics" value={rem7?.watch_critics ?? '—'} sub="free lane auto-runs" color={BLUE} />
          <KPI label="Research backfills (7d)" value={hermes7?.proposal_backfills ?? rem7?.proposal_backfills ?? '—'} sub={`${hermes7?.external_retries ?? rem7?.external_retries ?? '—'} ext retries · ${hermes7?.s0_refreshes ?? rem7?.s0_refreshes ?? '—'} S0`} color={BLUE} />
        </div>
        {remediation?.last_run?.run_at && (
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>Last intelligence pass: {String(remediation.last_run.run_at).slice(0, 19)} UTC</div>
        )}
        {remediation?.hermes_candidates && (
          <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>
            Research queue: {remediation.hermes_candidates.failed_external ?? '—'} failed externals · {remediation.hermes_candidates.proposals_missing_prior ?? '—'} proposals missing prior research · {remediation.hermes_candidates.stale_s0 ?? '—'} stale S0
          </div>
        )}
      </div>

      <div style={{ ...dashboardCard, borderLeft: `4px solid ${AMBER}`, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Maturity gates by dimension</div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 12 }}>
          Pass-rate by dimension — click a row to drill gate detail.{mStale ? ' Maturity data may be last-good (server busy).' : ''}
        </div>
        {mLoading && !gates && !fallbackResearchGates ? (
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Loading maturity gates…</div>
        ) : !gates && !fallbackResearchGates ? (
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>No maturity data available.</div>
        ) : (
          <>
            {failingResearchGates.length > 0 && (
              <div style={{ marginBottom: 12, padding: 10, background: 'var(--bg2)', borderRadius: 8 }}>
                <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>Research quality — failing gates</div>
                {failingResearchGates.map(([name, g]: any) => (
                  <div key={name} style={{ fontSize: 11, color: RED, marginTop: 4 }}>
                    {RESEARCH_GATE_LABEL[name] ?? name}: {fmtGateValue(g)}
                  </div>
                ))}
              </div>
            )}
            <MiniBarRow
              rows={gateBarRows.map(r => ({ label: r.label, value: r.value, max: 100, color: r.color, sub: r.sub }))}
              onRowClick={label => {
                const row = gateBarRows.find(r => r.label === label)
                if (row) onDrill({ title: row.label, subtitle: `${row.score}/${row.total} gates passing`, endpoint: '/api/v2/hermes/maturity-dashboard', rows: [row.gateSet], links: [{ label: 'Hermes Maturity', href: '/v3/hermes?tab=maturity' }] })
              }}
            />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10, marginTop: 14 }}>
              {gateBarRows.map(r => {
                const failing = Object.entries(r.gateSet).filter(([, g]: any) => !g.pass)
                const failDetail = r.key === 'research'
                  ? failing.map(([name, g]: any) => `${RESEARCH_GATE_LABEL[name] ?? name}: ${fmtGateValue(g as any)}`)
                  : failing.map(([name]) => name)
                return (
                  <div key={r.key}
                    onClick={() => onDrill({ title: r.label, subtitle: `${r.score}/${r.total} gates passing`, endpoint: '/api/v2/hermes/maturity-dashboard', rows: [r.gateSet], links: [{ label: 'Hermes Maturity', href: '/v3/hermes?tab=maturity' }] })}
                    style={{ background: 'var(--bg2)', borderRadius: 8, padding: '10px 12px', cursor: 'pointer' }}>
                    <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase' }}>{r.label}</div>
                    <div style={{ fontSize: 20, fontWeight: 800, color: r.color, marginTop: 2 }}>{r.score}/{r.total}</div>
                    <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 3 }}>
                      {failDetail.length
                        ? failDetail.slice(0, 2).join(' · ') + (failDetail.length > 2 ? '…' : '')
                        : 'all gates passing'}
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}
      </div>

      <div style={{ ...dashboardCard, borderLeft: `4px solid ${BLUE}`, padding: 14 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Which recommendation sources get acted on</div>
        <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>
          High idea volume with near-zero execution = learned distrust signal.
        </div>
        {sourcesWithSignal.length === 0 ? (
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>No source attribution data available.</div>
        ) : (
          <>
            <MiniBarRow rows={sourcesWithSignal.slice(0, 8).map(s => {
              const rate = s.tickers > 0 ? (s.executed / s.tickers) * 100 : 0
              return { label: s.source, value: rate, max: 100, color: rate > 5 ? GREEN : rate > 0 ? AMBER : 'var(--text3)', sub: `${s.executed}/${s.tickers} (${rate.toFixed(1)}%)` }
            })} />
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 8 }}>{totalExecuted.toLocaleString()} total executed · full lineage on Rec Intelligence →</div>
          </>
        )}
      </div>

      {!sLoading && scorecard && (scorecard.false_positive_rate != null || scorecard.outcome_hit_rate != null) && (
        <div style={{ ...dashboardCard, borderLeft: '4px solid var(--purple)', padding: 14, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <Metric label="Outcome hit rate" value={scorecard.outcome_hit_rate} />
          <Metric label="False positive rate" value={scorecard.false_positive_rate} invert />
          <Metric label="False negative rate" value={scorecard.false_negative_rate} invert />
          <Metric label="Resource efficiency" value={scorecard.resource_efficiency_score} />
          <div style={{ fontSize: 10, color: 'var(--text3)', alignSelf: 'center' }}>
            {scorecard.thresholds_learned_vs_static ? `${scorecard.thresholds_learned_vs_static.learned_count ?? 0} thresholds learned vs ${scorecard.thresholds_learned_vs_static.static_count ?? 0} still static` : ''}
          </div>
        </div>
      )}
    </div>
  )
}

function Metric({ label, value, invert }: { label: string; value: number | null | undefined; invert?: boolean }) {
  if (value == null) return null
  const pct = value <= 1 ? value * 100 : value
  const good = invert ? pct < 15 : pct >= 60
  const bad = invert ? pct >= 35 : pct < 30
  return (
    <div>
      <div style={{ fontSize: 18, fontWeight: 800, color: good ? GREEN : bad ? RED : AMBER }}>{pct.toFixed(1)}%</div>
      <div style={{ fontSize: 10, color: 'var(--text3)', textTransform: 'uppercase' }}>{label}</div>
    </div>
  )
}
