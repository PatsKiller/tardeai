import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { Line, Bar } from 'react-chartjs-2'
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, BarElement, Filler, Tooltip, Legend } from 'chart.js'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import MetricTile from '../components/MetricTile'
import SectionHeader from '../components/SectionHeader'
import { DoughnutChart } from '../components/charts'
import { useApi } from '../hooks/useApi'
import { fmt$, timeAgo } from '../lib/format'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Filler, Tooltip, Legend)

interface RetirementData {
  as_of: string; current_age: number
  key_dates: Record<string, string | number>
  accounts: { total: number; roth: number; traditional: number; taxable: number }
  loan: { balance: number; deadline: string; days_remaining: number; monthly_to_payoff: number }
  timeline: { age: number; year: number; conservative: number; base: number; aggressive: number; milestone: string }[]
  golden_window: { start_age: number; end_age: number; years_available: number; optimal_annual_conversion: number; projected_roth_at_start: number; narrative?: string }
}

const fmtK = (v: number) => v >= 1000 ? `$${(v / 1000).toFixed(0)}K` : `$${v.toLocaleString()}`

interface AlexAnalysis { symbol: string; strategy_type: string; severity: string; provider: string; weight: number; pnl: number; trigger: string; created_at: string }
interface AlexResp { analyses: AlexAnalysis[]; total: number }
interface AgentRow { agent: string; total: number; buy_count: number; sell_count: number; hold_count: number; avg_confidence: number; latest: string }
interface AgentsResp { agents: AgentRow[]; handoffs: { from_agent: string; to_agent: string; cnt: number }[] }
interface AIReport { id: number; report_type: string; title: string; content: string; provider: string; generated_at: string }
interface AIReportsResp { reports: AIReport[] }
interface Proposal { id: number; symbol: string; action: string; strategy_type: string; reason: string; account_name: string; shares_to_sell: number; target_symbol: string; confidence: number; status: string; ssdi_impact: string; income_impact: string; irmaa_risk: boolean; review_date: string; created_at: string }
interface ProposalsResp { proposals: Proposal[] }
interface FeedbackStat { decision: string; cnt: number }
interface FeedbackResp { feedback: unknown[]; stats: FeedbackStat[] }
interface MacroResp { context: string }
interface HistoryDay { date: string; approved: number; rejected: number; proposed: number }
interface HistoryResp { daily: HistoryDay[] }

export default function Retirement() {
  const navigate = useNavigate()
  const { data } = useApi<RetirementData>('/api/v2/retirement')
  const { data: tax } = useApi<{ roth_conversions_ytd: number; bracket_room_22pct: number; current_bracket: number; agi: number; magi: number }>('/api/v2/tax-situation')
  const { data: alex } = useApi<AlexResp>('/api/v2/alex/recent')
  const { data: agentsSummary } = useApi<AgentsResp>('/api/v2/agents/summary')
  const { data: reports } = useApi<AIReportsResp>('/api/v2/ai-reports')
  const { data: proposalsResp } = useApi<ProposalsResp>('/api/v2/proposals')
  const { data: feedbackResp } = useApi<FeedbackResp>('/api/v2/proposals/feedback')
  const { data: macroResp } = useApi<MacroResp>('/api/v2/macro-context')
  const { data: historyResp } = useApi<HistoryResp>('/api/v2/proposals/history')
  const [deciding, setDeciding] = useState<Record<number, string>>({})
  const [decided, setDecided] = useState<Set<number>>(new Set())

  const handleProposalDecision = useCallback(async (id: number, decision: 'approved' | 'rejected') => {
    setDeciding(s => ({ ...s, [id]: decision }))
    try {
      const r = await fetch('/api/v2/proposals/decide', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, decision, reviewer: 'john' }) })
      const d = await r.json()
      if (d.ok) setDecided(s => new Set(s).add(id))
      else alert(d.error || 'Decision failed')
    } catch { alert('Network error') }
    setDeciding(s => { const n = { ...s }; delete n[id]; return n })
  }, [])

  if (!data) return <div style={{ color: 'var(--text3)', padding: 40, fontFamily: 'var(--sans)' }}>Loading retirement roadmap…</div>

  const gw = data.golden_window || {} as RetirementData['golden_window']
  const loan = data.loan || {} as RetirementData['loan']
  const daysToGolden = Number(data.key_dates?.days_to_golden ?? 0)
  const progressPct = daysToGolden > 0 ? Math.max(0, Math.min(100, ((3650 - daysToGolden) / 3650) * 100)) : 100

  // Tax defaults
  const rothYTD = tax?.roth_conversions_ytd ?? 35000
  const conversionTarget = 51000
  const bracketRoom = tax?.bracket_room_22pct ?? 66883
  const currentAGI = tax?.agi ?? 49342
  const currentMAGI = tax?.magi ?? currentAGI
  const conversionPct = Math.min(100, Math.round((rothYTD / conversionTarget) * 100))

  // Bracket data
  const brackets = [
    { label: '10%', upper: 11600, color: '#22c55e' },
    { label: '12%', upper: 47150, color: '#4ade80' },
    { label: '22%', upper: 100525, color: '#f0b90b' },
    { label: '24%', upper: 191950, color: '#f97316' },
  ]
  const maxBracketVal = brackets[brackets.length - 1].upper
  const agiPct = Math.min(100, (currentAGI / maxBracketVal) * 100)

  // Medicare countdown
  const medicareDate = new Date('2026-12-01')
  const now = new Date()
  const medicareDaysLeft = Math.max(0, Math.ceil((medicareDate.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)))

  return (
    <>
      <PageHeader title={`Strategic Portfolio & Retirement — Age ${data.current_age?.toFixed(1)}`} subtitle={`as of ${data.as_of}`} />

      {/* Quick nav */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 14, flexWrap: 'wrap' }}>
        {[['Portfolio', '/portfolio'], ['Tax & Lots', '/tax'], ['Rebalance', '/rebalance'], ['Forecast', '/forecast'], ['AI Analyst', '/ai-analyst']].map(([l, r]) => (
          <button key={r} onClick={() => navigate(r)} style={{ fontSize: 10, padding: '5px 12px', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 9999, background: 'rgba(255,255,255,0.04)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--sans)' }}>{l}</button>
        ))}
      </div>

      {/* Account summary strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 12, marginBottom: 16 }}>
        <MetricTile label="Total Portfolio" value={fmt$(data.accounts?.total ?? 0)} />
        <MetricTile label="Roth IRA" value={fmt$(data.accounts?.roth ?? 0)} deltaColor="var(--green)" />
        <MetricTile label="Traditional / Pre-tax" value={fmt$(data.accounts?.traditional ?? 0)} />
        <MetricTile label="Taxable" value={fmt$(data.accounts?.taxable ?? 0)} />
        <MetricTile label="Days to Golden Window" value={String(daysToGolden || '—')} deltaColor="var(--amber)" />
      </div>

      {/* === 1. Account Allocation Doughnut === */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: 16, marginBottom: 16 }}>
        <Card title="Account Type Allocation">
          <div style={{ position: 'relative', height: 180 }}>
            <DoughnutChart
              labels={['Roth', 'Traditional / Pre-tax', 'Taxable']}
              data={[data.accounts?.roth ?? 0, data.accounts?.traditional ?? 0, data.accounts?.taxable ?? 0]}
              height={180}
            />
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 12 }}>
            {[
              { label: 'Roth', color: '#4a90f4', val: data.accounts?.roth ?? 0 },
              { label: 'Pre-tax', color: '#0ecb81', val: data.accounts?.traditional ?? 0 },
              { label: 'Taxable', color: '#f6465d', val: data.accounts?.taxable ?? 0 },
            ].map(item => (
              <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <div style={{ width: 8, height: 8, borderRadius: 2, background: item.color }} />
                <span style={{ fontSize: 9, color: 'var(--text2)', fontFamily: 'var(--sans)' }}>{item.label}: {fmtK(item.val)}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* === 5. Medicare / Medicaid Status Card === */}
        <Card title="Healthcare Coverage Status">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            {/* Medicare */}
            <div style={{ padding: 12, background: 'rgba(74,144,244,0.06)', borderRadius: 8, border: '1px solid rgba(74,144,244,0.15)' }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#4a90f4', textTransform: 'uppercase', letterSpacing: '.06em', fontFamily: 'var(--sans)', marginBottom: 8 }}>Medicare Eligibility</div>
              <div style={{ fontSize: 32, fontWeight: 800, color: 'var(--text0)', fontFamily: 'var(--sans)', lineHeight: 1 }}>{medicareDaysLeft}</div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>days until Dec 2026</div>
              <div style={{ marginTop: 10, height: 4, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden' }}>
                <div style={{ width: `${Math.min(100, Math.max(0, 100 - (medicareDaysLeft / 365) * 100))}%`, height: '100%', background: '#4a90f4', borderRadius: 99 }} />
              </div>
            </div>
            {/* Medicaid */}
            <div style={{ padding: 12, background: 'rgba(14,203,129,0.06)', borderRadius: 8, border: '1px solid rgba(14,203,129,0.15)' }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#0ecb81', textTransform: 'uppercase', letterSpacing: '.06em', fontFamily: 'var(--sans)', marginBottom: 8 }}>Medicaid (NY)</div>
              <div style={{ fontSize: 11, color: 'var(--text2)', fontFamily: 'var(--sans)', marginBottom: 6 }}>Income limit: $20,124/yr</div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>
                <span>Current MAGI</span>
                <span style={{ color: currentMAGI <= 20124 ? '#0ecb81' : '#f6465d', fontWeight: 600 }}>{fmt$(currentMAGI)}</span>
              </div>
              <div style={{ height: 6, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden', marginBottom: 6 }}>
                <div style={{ width: `${Math.min(100, (currentMAGI / 20124) * 100)}%`, height: '100%', background: currentMAGI <= 20124 ? '#0ecb81' : '#f6465d', borderRadius: 99 }} />
              </div>
              <div style={{ fontSize: 9, color: currentMAGI <= 20124 ? '#0ecb81' : '#f6465d' }}>
                {currentMAGI <= 20124 ? `$${(20124 - currentMAGI).toLocaleString()} under limit` : `$${(currentMAGI - 20124).toLocaleString()} over limit`}
              </div>
            </div>
          </div>
          {/* IRMAA */}
          <div style={{ marginTop: 12, padding: '8px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 6, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 9, color: 'var(--text3)', fontFamily: 'var(--sans)' }}>IRMAA Tier</div>
              <div style={{ fontSize: 12, color: 'var(--text1)', fontWeight: 600, fontFamily: 'var(--sans)' }}>
                {currentMAGI <= 103000 ? 'Base (no surcharge)' : currentMAGI <= 129000 ? 'Tier 1' : currentMAGI <= 161000 ? 'Tier 2' : 'Tier 3+'}
              </div>
            </div>
            <div style={{ fontSize: 9, color: 'var(--text3)' }}>
              MAGI threshold: $103,000
            </div>
          </div>
        </Card>
      </div>

      {/* Golden Window — hero card */}
      <div style={{ background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(242,211,90,0.2)', borderRadius: 12, padding: '20px 24px', marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#f2d35a', textTransform: 'uppercase', letterSpacing: '.06em', fontFamily: 'var(--sans)', marginBottom: 6 }}>Golden Roth Conversion Window</div>
            <div style={{ fontSize: 48, fontWeight: 800, color: '#f2d35a', lineHeight: 1, fontFamily: 'var(--sans)' }}>{daysToGolden || '—'}</div>
            <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 6 }}>days remaining · Opens {String(data.key_dates?.golden_window_start || '—')} · Closes {String(data.key_dates?.golden_window_end || '—')}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 4 }}>Optimal annual conversion</div>
            <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--green)', fontFamily: 'var(--sans)' }}>${gw.optimal_annual_conversion?.toLocaleString() || '—'}/yr</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>Projected Roth at start: {fmt$(gw.projected_roth_at_start ?? 0)}</div>
          </div>
        </div>
        {/* Progress bar */}
        <div style={{ height: 8, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden' }}>
          <div style={{ width: `${progressPct}%`, height: '100%', background: 'linear-gradient(90deg, rgba(242,211,90,0.8), rgba(242,211,90,0.4))', borderRadius: 99 }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 9, color: 'var(--text3)' }}>
          <span>Window: {gw.years_available || '—'} years · Age {gw.start_age}–{gw.end_age}</span>
          <span>{progressPct.toFixed(0)}% of time until window</span>
        </div>
      </div>

      {/* === 2. Roth Conversion Progress Bar === */}
      <Card title="Roth Conversion YTD Progress">
        <div style={{ marginBottom: 8 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: 'var(--text1)', fontWeight: 600, fontFamily: 'var(--sans)' }}>
              Converted {fmtK(rothYTD)} of {fmtK(conversionTarget)} target ({conversionPct}%)
            </span>
            <span style={{ fontSize: 10, color: 'var(--text3)', fontFamily: 'var(--sans)' }}>
              22% bracket room: {fmt$(bracketRoom)} remaining
            </span>
          </div>
          {/* Bar container */}
          <div style={{ position: 'relative', height: 28, background: 'var(--bg3)', borderRadius: 6, overflow: 'visible' }}>
            {/* Filled progress */}
            <div style={{
              position: 'absolute', top: 0, left: 0, height: '100%',
              width: `${(rothYTD / bracketRoom) * 100}%`,
              background: 'linear-gradient(90deg, #0ecb81, #4ade80)',
              borderRadius: '6px 0 0 6px',
              transition: 'width 0.5s ease',
            }} />
            {/* Target marker */}
            <div style={{
              position: 'absolute', top: -4, left: `${(conversionTarget / bracketRoom) * 100}%`,
              width: 2, height: 36, background: '#f0b90b',
              zIndex: 2,
            }} />
            <div style={{
              position: 'absolute', top: -16, left: `${(conversionTarget / bracketRoom) * 100}%`,
              transform: 'translateX(-50%)',
              fontSize: 8, color: '#f0b90b', fontWeight: 700, fontFamily: 'var(--sans)', whiteSpace: 'nowrap',
            }}>
              Target {fmtK(conversionTarget)}
            </div>
            {/* Bracket room marker */}
            <div style={{
              position: 'absolute', top: -4, right: 0,
              width: 2, height: 36, background: '#f97316',
              zIndex: 2,
            }} />
            <div style={{
              position: 'absolute', top: -16, right: 0,
              transform: 'translateX(50%)',
              fontSize: 8, color: '#f97316', fontWeight: 700, fontFamily: 'var(--sans)', whiteSpace: 'nowrap',
            }}>
              22% cap {fmtK(bracketRoom)}
            </div>
            {/* Value label inside bar */}
            <div style={{
              position: 'absolute', top: '50%', left: Math.min((rothYTD / bracketRoom) * 50, 40) + '%',
              transform: 'translateY(-50%)',
              fontSize: 10, color: '#fff', fontWeight: 700, fontFamily: 'var(--sans)',
              zIndex: 3,
            }}>
              {fmtK(rothYTD)}
            </div>
          </div>
        </div>
      </Card>

      {/* 401k Loan tracker */}
      {loan.balance > 0 && (
        <div style={{ background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(240,185,11,0.15)', borderRadius: 12, padding: '16px 20px', marginTop: 16, marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--amber)', textTransform: 'uppercase', fontFamily: 'var(--sans)', marginBottom: 4 }}>401k Loan Payoff</div>
              <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--text0)', fontFamily: 'var(--sans)' }}>{fmt$(loan.balance)}</div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4 }}>Due {loan.deadline} · {loan.days_remaining} days · {fmt$(loan.monthly_to_payoff)}/mo to payoff</div>
            </div>
            <div style={{ width: 80, height: 80, borderRadius: 999, border: '4px solid var(--amber)', display: 'grid', placeItems: 'center' }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--amber)' }}>{loan.days_remaining}</div>
                <div style={{ fontSize: 7, color: 'var(--text3)' }}>DAYS</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* === 4. Tax Bracket Visualization + Key Dates side by side === */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
        <Card title="Tax Bracket Position">
          <div style={{ marginBottom: 8 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text2)', fontFamily: 'var(--sans)', marginBottom: 10 }}>
              <span>Current AGI: <strong style={{ color: 'var(--text0)' }}>{fmt$(currentAGI)}</strong></span>
              <span>Bracket: <strong style={{ color: '#f0b90b' }}>{tax?.current_bracket ?? 22}%</strong></span>
            </div>
            {/* Bracket bar */}
            <div style={{ position: 'relative', height: 24, display: 'flex', borderRadius: 6, overflow: 'hidden', marginBottom: 20 }}>
              {brackets.map((b, i) => {
                const prevUpper = i > 0 ? brackets[i - 1].upper : 0
                const segWidth = ((b.upper - prevUpper) / maxBracketVal) * 100
                return (
                  <div key={b.label} style={{
                    width: `${segWidth}%`, height: '100%',
                    background: b.color, opacity: 0.7,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <span style={{ fontSize: 8, color: '#000', fontWeight: 700, fontFamily: 'var(--sans)' }}>{b.label}</span>
                  </div>
                )
              })}
              {/* AGI pointer */}
              <div style={{
                position: 'absolute', top: -6, left: `${agiPct}%`,
                transform: 'translateX(-50%)',
                zIndex: 5,
              }}>
                <div style={{ width: 0, height: 0, borderLeft: '5px solid transparent', borderRight: '5px solid transparent', borderTop: '6px solid #fff', margin: '0 auto' }} />
              </div>
              <div style={{
                position: 'absolute', bottom: -16, left: `${agiPct}%`,
                transform: 'translateX(-50%)',
                fontSize: 8, color: 'var(--text1)', fontWeight: 700, fontFamily: 'var(--sans)', whiteSpace: 'nowrap',
              }}>
                {fmtK(currentAGI)}
              </div>
            </div>
            {/* Bracket room */}
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
              {brackets.map((b, i) => {
                const inBracket = currentAGI < b.upper && (i === 0 || currentAGI >= brackets[i - 1].upper)
                return inBracket ? (
                  <div key={b.label} style={{ padding: '4px 10px', background: 'rgba(255,255,255,0.05)', borderRadius: 6, fontSize: 9, color: 'var(--text2)', fontFamily: 'var(--sans)' }}>
                    Room in {b.label} bracket: <strong style={{ color: b.color }}>{fmt$(b.upper - currentAGI)}</strong>
                  </div>
                ) : null
              })}
            </div>
          </div>
        </Card>

        {/* Key Dates */}
        <div>
          <SectionHeader title="Key Dates & Milestones" count={Object.keys(data.key_dates || {}).length} />
          <Card>
            {Object.entries(data.key_dates || {}).filter(([k]) => !String(k).includes('days_') && !String(k).includes('years_')).map(([label, value]) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <span style={{ color: 'var(--text3)', fontSize: 11, fontFamily: 'var(--sans)' }}>{label.replace(/_/g, ' ')}</span>
                <span style={{ color: 'var(--text0)', fontSize: 11, fontWeight: 600, fontFamily: 'var(--sans)' }}>{String(value)}</span>
              </div>
            ))}
          </Card>
        </div>
      </div>

      {/* === 3. Timeline Projection Chart === */}
      <div style={{ marginTop: 16 }}>
        <SectionHeader title="Retirement Timeline Projections" count={data.timeline.length} />
        <Card>
          <div style={{ height: 300, position: 'relative' }}>
            <Line
              data={{
                labels: data.timeline.map(r => String(r.year)),
                datasets: [
                  {
                    label: 'Conservative',
                    data: data.timeline.map(r => r.conservative),
                    borderColor: '#f6465d',
                    backgroundColor: 'rgba(246,70,93,0.08)',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                  },
                  {
                    label: 'Base',
                    data: data.timeline.map(r => r.base),
                    borderColor: '#4a90f4',
                    backgroundColor: 'rgba(74,144,244,0.08)',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                  },
                  {
                    label: 'Aggressive',
                    data: data.timeline.map(r => r.aggressive),
                    borderColor: '#0ecb81',
                    backgroundColor: 'rgba(14,203,129,0.08)',
                    fill: false,
                    tension: 0.3,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    borderWidth: 2,
                  },
                ],
              }}
              options={{
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                  legend: {
                    display: true,
                    position: 'top',
                    labels: { color: '#b8c1d0', font: { size: 10 }, boxWidth: 12, padding: 16 },
                  },
                  tooltip: {
                    backgroundColor: '#1b2230',
                    titleColor: '#eaeff6',
                    bodyColor: '#b8c1d0',
                    borderColor: '#2c3a52',
                    borderWidth: 1,
                    callbacks: {
                      label: (ctx) => `${ctx.dataset.label}: ${fmt$(ctx.parsed.y)}`,
                    },
                  },
                },
                scales: {
                  x: {
                    display: true,
                    ticks: { color: '#6b7a8d', font: { size: 9 }, maxTicksLimit: 15 },
                    grid: { color: 'rgba(255,255,255,0.04)' },
                  },
                  y: {
                    display: true,
                    ticks: {
                      color: '#6b7a8d',
                      font: { size: 9 },
                      callback: (v) => typeof v === 'number' ? fmtK(v) : v,
                    },
                    grid: { color: 'rgba(255,255,255,0.04)' },
                  },
                },
              }}
            />
          </div>
          {/* Milestone annotations row */}
          {data.timeline.some(r => r.milestone) && (
            <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
              {data.timeline.filter(r => r.milestone).map((r, i) => (
                <div key={i} style={{
                  display: 'inline-flex', alignItems: 'center', gap: 5,
                  padding: '3px 10px', borderRadius: 99,
                  background: 'rgba(74,144,244,0.1)', border: '1px solid rgba(74,144,244,0.2)',
                }}>
                  <span style={{ fontSize: 9, color: '#4a90f4', fontWeight: 600, fontFamily: 'var(--sans)' }}>{r.year} (Age {r.age})</span>
                  <span style={{ fontSize: 9, color: 'var(--text2)', fontFamily: 'var(--sans)' }}>{r.milestone}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Alex Recent Analyses */}
      {(alex?.analyses?.length ?? 0) > 0 && (
        <div style={{ marginTop: 16 }}>
          <SectionHeader title="Alex Retirement Analyses" count={alex!.total} />
          <Card>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
              {alex!.analyses.slice(0, 8).map((a, i) => (
                <button key={i} onClick={() => navigate(`/research?symbol=${a.symbol}`)} style={{
                  padding: '12px 14px', borderRadius: 10, textAlign: 'left', cursor: 'pointer',
                  background: a.severity === 'high' ? 'rgba(246,70,93,0.06)' : 'rgba(74,144,244,0.04)',
                  border: `1px solid ${a.severity === 'high' ? 'rgba(246,70,93,0.15)' : 'rgba(255,255,255,0.06)'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: 16, fontWeight: 800, color: 'var(--accent)', fontFamily: 'var(--sans)' }}>{a.symbol}</span>
                    <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, fontWeight: 700,
                      background: a.severity === 'high' ? 'rgba(246,70,93,0.15)' : 'rgba(14,203,129,0.1)',
                      color: a.severity === 'high' ? 'var(--red)' : 'var(--green)',
                    }}>{a.severity}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 4 }}>{a.trigger || 'manual analysis'}</div>
                  <div style={{ display: 'flex', gap: 12, fontSize: 9, color: 'var(--text3)' }}>
                    <span>{a.strategy_type?.replace(/_/g, ' ')}</span>
                    <span>wt: {a.weight?.toFixed(1)}%</span>
                    <span>P&L: {fmt$(a.pnl ?? 0)}</span>
                  </div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>{a.provider} · {a.created_at ? new Date(a.created_at).toLocaleDateString() : ''}</div>
                </button>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* Agent Activity Summary */}
      {(agentsSummary?.agents?.length ?? 0) > 0 && (
        <div style={{ marginTop: 16 }}>
          <SectionHeader title="Agent Activity" count={agentsSummary!.agents.reduce((s, a) => s + a.total, 0)} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
            {agentsSummary!.agents.map(a => {
              const total = a.total || 1
              const buyPct = (a.buy_count / total) * 100
              const sellPct = (a.sell_count / total) * 100
              const holdPct = (a.hold_count / total) * 100
              return (
                <Card key={a.agent}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', fontFamily: 'var(--sans)', marginBottom: 8 }}>
                    {a.agent.replace('_agent', '').replace(/^\w/, c => c.toUpperCase())}
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--accent)', fontFamily: 'var(--sans)' }}>{a.total}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>analyses · avg conf: {(a.avg_confidence * 100).toFixed(0)}%</div>
                  {/* Recommendation bar */}
                  <div style={{ display: 'flex', height: 6, borderRadius: 99, overflow: 'hidden', marginBottom: 4 }}>
                    {buyPct > 0 && <div style={{ width: `${buyPct}%`, background: 'var(--green)' }} />}
                    {holdPct > 0 && <div style={{ width: `${holdPct}%`, background: 'var(--amber)' }} />}
                    {sellPct > 0 && <div style={{ width: `${sellPct}%`, background: 'var(--red)' }} />}
                    {(100 - buyPct - holdPct - sellPct) > 0 && <div style={{ width: `${100 - buyPct - holdPct - sellPct}%`, background: 'var(--bg3)' }} />}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: 'var(--text3)' }}>
                    <span style={{ color: 'var(--green)' }}>{a.buy_count} buy</span>
                    <span style={{ color: 'var(--amber)' }}>{a.hold_count} hold</span>
                    <span style={{ color: 'var(--red)' }}>{a.sell_count} sell</span>
                  </div>
                </Card>
              )
            })}
          </div>
        </div>
      )}

      {/* Latest Reports */}
      {(reports?.reports?.length ?? 0) > 0 && (
        <div style={{ marginTop: 16 }}>
          <SectionHeader title="Latest Alex Reports" count={reports!.reports.length} />
          <Card>
            {reports!.reports.slice(0, 3).map(r => (
              <div key={r.id} style={{ padding: '12px 0', borderBottom: '1px solid var(--border-subtle)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      fontSize: 9, padding: '2px 8px', borderRadius: 4, fontWeight: 700, textTransform: 'uppercase',
                      background: r.report_type === 'monthly' ? 'rgba(74,144,244,0.15)' : 'rgba(14,203,129,0.1)',
                      color: r.report_type === 'monthly' ? 'var(--accent)' : 'var(--green)',
                    }}>{r.report_type}</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', fontFamily: 'var(--sans)' }}>{r.title}</span>
                  </div>
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>{r.provider} · {r.generated_at ? new Date(r.generated_at).toLocaleDateString() : ''}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.6, maxHeight: 120, overflowY: 'auto', fontFamily: 'var(--sans)', whiteSpace: 'pre-wrap' }}>
                  {r.content.slice(0, 500)}{r.content.length > 500 ? '...' : ''}
                </div>
              </div>
            ))}
            <button onClick={() => navigate('/ai-analyst')} style={{ marginTop: 10, padding: '8px 16px', borderRadius: 8, border: '1px solid var(--accent)', background: 'rgba(74,144,244,0.08)', color: 'var(--accent)', fontWeight: 700, cursor: 'pointer', fontSize: 11 }}>
              View All Reports in AI Analyst →
            </button>
          </Card>
        </div>
      )}

      {/* Rotation Proposals */}
      {(() => {
        const proposals = (proposalsResp?.proposals ?? []).filter(p => !decided.has(p.id))
        const pending = proposals.filter(p => p.status === 'proposed')
        const recent = proposals.filter(p => p.status !== 'proposed').slice(0, 5)
        if (pending.length === 0 && recent.length === 0) return null
        const ssdiLabel: Record<string, string> = { none: 'No impact', conversion_taxable: 'Taxable event', capital_gains: 'Cap gains' }
        const ssdiColor: Record<string, string> = { none: 'var(--green)', conversion_taxable: 'var(--amber)', capital_gains: 'var(--amber)' }
        return (
          <div style={{ marginTop: 16 }}>
            <SectionHeader title="Rotation Proposals" count={pending.length} />
            {pending.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {pending.map(p => (
                  <div key={p.id} style={{
                    background: 'var(--bg2)', border: `1px solid ${p.irmaa_risk ? 'var(--red)' : 'var(--border)'}`,
                    borderRadius: 'var(--radius-lg)', padding: '14px 18px',
                    borderLeft: `4px solid ${p.irmaa_risk ? 'var(--red)' : 'var(--amber)'}`,
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                      <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--accent)', fontFamily: 'var(--sans)' }}>{p.symbol}</span>
                      <span style={{ fontSize: 9, padding: '2px 8px', borderRadius: 4, fontWeight: 700, background: 'rgba(240,185,11,0.12)', color: 'var(--amber)', textTransform: 'uppercase' }}>{p.action}</span>
                      {p.irmaa_risk && <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 6px', borderRadius: 3, background: 'var(--red-dim)', color: 'var(--red)' }}>IRMAA RISK</span>}
                      <span style={{ fontSize: 10, color: 'var(--text2)', fontWeight: 600 }}>{p.account_name || 'Unknown'}</span>
                      <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                        <div style={{ fontSize: 18, fontWeight: 800, color: p.confidence >= 0.7 ? 'var(--green)' : 'var(--amber)' }}>{(p.confidence * 100).toFixed(0)}%</div>
                        <div style={{ fontSize: 8, color: 'var(--text3)' }}>confidence</div>
                      </div>
                    </div>
                    {/* Details grid */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 10, fontSize: 10 }}>
                      <div>
                        <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Shares</div>
                        <div style={{ fontWeight: 700, color: 'var(--text0)' }}>{p.shares_to_sell?.toFixed(1) || '—'}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Target</div>
                        <div style={{ fontWeight: 700, color: 'var(--text0)' }}>{p.target_symbol || 'cash'}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>SSDI Impact</div>
                        <div style={{ fontWeight: 700, color: ssdiColor[p.ssdi_impact] || 'var(--text2)' }}>{ssdiLabel[p.ssdi_impact] || p.ssdi_impact || '—'}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>Review By</div>
                        <div style={{ fontWeight: 600, color: 'var(--text2)' }}>{p.review_date || '—'}</div>
                      </div>
                    </div>
                    {/* Reason */}
                    <div style={{ padding: '8px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', marginBottom: 10, fontSize: 10, color: 'var(--text2)', lineHeight: 1.5 }}>
                      {p.reason}
                    </div>
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8 }}>
                      Strategy: {p.strategy_type?.replace(/_/g, ' ')} | {p.created_at ? timeAgo(p.created_at) : ''}
                    </div>
                    {/* Decision buttons */}
                    <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', paddingTop: 8, borderTop: '1px solid var(--border-subtle)' }}>
                      <button onClick={() => handleProposalDecision(p.id, 'approved')} disabled={!!deciding[p.id]}
                        style={{ padding: '6px 16px', fontSize: 10, fontWeight: 700, border: '1px solid var(--green)', borderRadius: 'var(--radius)', background: 'var(--green-dim)', color: 'var(--green)', cursor: 'pointer', fontFamily: 'var(--mono)', opacity: deciding[p.id] ? 0.5 : 1 }}>
                        {deciding[p.id] === 'approved' ? 'Saving...' : 'Approve'}
                      </button>
                      <button onClick={() => handleProposalDecision(p.id, 'rejected')} disabled={!!deciding[p.id]}
                        style={{ padding: '6px 16px', fontSize: 10, fontWeight: 700, border: '1px solid var(--red)', borderRadius: 'var(--radius)', background: 'var(--red-dim)', color: 'var(--red)', cursor: 'pointer', fontFamily: 'var(--mono)', opacity: deciding[p.id] ? 0.5 : 1 }}>
                        {deciding[p.id] === 'rejected' ? 'Saving...' : 'Reject'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {/* Recent decisions */}
            {recent.length > 0 && (
              <Card compact>
                <div style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 700, padding: '4px 0 6px', textTransform: 'uppercase' }}>Recent Decisions</div>
                {recent.map(p => (
                  <div key={p.id} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                    <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 6px', borderRadius: 3, textTransform: 'uppercase', background: p.status === 'approved' ? 'var(--green-dim)' : 'var(--red-dim)', color: p.status === 'approved' ? 'var(--green)' : 'var(--red)' }}>{p.status}</span>
                    <span style={{ fontWeight: 700, color: 'var(--accent)' }}>{p.symbol}</span>
                    <span style={{ color: 'var(--text2)' }}>{p.account_name}</span>
                    <span style={{ flex: 1, color: 'var(--text3)' }}>{p.shares_to_sell?.toFixed(0) || '?'} shares → {p.target_symbol || 'cash'}</span>
                    <span style={{ color: 'var(--text3)' }}>{p.created_at ? timeAgo(p.created_at) : ''}</span>
                  </div>
                ))}
              </Card>
            )}
          </div>
        )
      })()}

      {/* Proposal history chart + feedback stats + macro context */}
      {(() => {
        const days = historyResp?.daily ?? []
        const hasActivity = days.some(d => d.approved > 0 || d.rejected > 0 || d.proposed > 0)
        const fbStats = feedbackResp?.stats ?? []
        const totalFb = fbStats.reduce((s, x) => s + x.cnt, 0)
        const approvedFb = fbStats.find(s => s.decision === 'approved')?.cnt ?? 0
        const approvalPct = totalFb > 0 ? Math.round((approvedFb / totalFb) * 100) : 0
        return (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 16 }}>
            {/* Proposal History Chart */}
            <Card title="Proposal Activity (30 days)">
              {hasActivity ? (
                <div style={{ height: 160, position: 'relative' }}>
                  <Bar
                    data={{
                      labels: days.map(d => typeof d.date === 'string' ? d.date.slice(5) : ''),
                      datasets: [
                        { label: 'Approved', data: days.map(d => d.approved), backgroundColor: 'rgba(14,203,129,0.7)', borderRadius: 2 },
                        { label: 'Rejected', data: days.map(d => d.rejected), backgroundColor: 'rgba(246,70,93,0.7)', borderRadius: 2 },
                        { label: 'Proposed', data: days.map(d => d.proposed), backgroundColor: 'rgba(74,144,244,0.3)', borderRadius: 2 },
                      ],
                    }}
                    options={{
                      responsive: true, maintainAspectRatio: false,
                      plugins: { legend: { display: true, position: 'top', labels: { color: '#b8c1d0', font: { size: 9 }, boxWidth: 10, padding: 8 } }, tooltip: { backgroundColor: '#1b2230', titleColor: '#eaeff6', bodyColor: '#b8c1d0', borderColor: '#2c3a52', borderWidth: 1 } },
                      scales: { x: { stacked: true, ticks: { color: '#6b7a8d', font: { size: 7 }, maxTicksLimit: 10 }, grid: { display: false } }, y: { stacked: true, ticks: { color: '#6b7a8d', font: { size: 8 }, stepSize: 1 }, grid: { color: 'rgba(255,255,255,0.04)' } } },
                    }}
                  />
                </div>
              ) : (
                <div style={{ padding: 20, textAlign: 'center', color: 'var(--text3)', fontSize: 11 }}>No proposal activity yet. Engine runs daily at 7 PM.</div>
              )}
              {totalFb > 0 && (
                <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div style={{ flex: 1, height: 6, background: 'var(--bg3)', borderRadius: 99, overflow: 'hidden' }}>
                    <div style={{ width: `${approvalPct}%`, height: '100%', background: 'var(--green)', borderRadius: 99 }} />
                  </div>
                  <span style={{ fontSize: 10, fontWeight: 700, color: approvalPct >= 50 ? 'var(--green)' : 'var(--red)' }}>{approvalPct}%</span>
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>approval rate ({totalFb} decisions)</span>
                </div>
              )}
            </Card>

            {/* FRED Macro Context */}
            {macroResp?.context ? (
              <Card title="Macro Economic Context">
                <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.8, fontFamily: 'var(--mono)', whiteSpace: 'pre-wrap' }}>
                  {macroResp.context}
                </div>
                <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>Source: FRED (St. Louis Fed). Injected into all agent analyses.</div>
              </Card>
            ) : (
              <Card title="Macro Context"><div style={{ padding: 16, color: 'var(--text3)', fontSize: 11 }}>Loading FRED data...</div></Card>
            )}
          </div>
        )
      })()}

      {/* Strategy guidance */}
      <div style={{ marginTop: 16, padding: '12px 16px', background: 'rgba(255,255,255,0.03)', borderRadius: 10, fontSize: 10, color: 'var(--text3)', fontFamily: 'var(--sans)', lineHeight: 1.6 }}>
        Strategic planning context: Use this page with <button onClick={() => navigate('/rebalance')} style={{ color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--sans)', fontSize: 10, textDecoration: 'underline' }}>Rebalance</button>, <button onClick={() => navigate('/tax')} style={{ color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--sans)', fontSize: 10, textDecoration: 'underline' }}>Tax & Lots</button>, and <button onClick={() => navigate('/forecast')} style={{ color: 'var(--accent)', background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'var(--sans)', fontSize: 10, textDecoration: 'underline' }}>Forecast</button> to plan Roth conversion pacing, rollover sequencing, and 401k loan cleanup.
      </div>
    </>
  )
}
